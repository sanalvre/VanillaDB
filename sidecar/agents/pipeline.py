"""
VanillaFlow — orchestrates the 4-agent pipeline.

Triggered by file changes (via on_file_ready callback) or manual /agent/run-now.
Chains: collect_changed_files -> ingest_step -> analysis_step -> proposal_step.
File-back runs separately on approval.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from config import VanillaConfig
from db import repository as repo
from services.llm_service import chat_completion
from services.graph_service import (
    get_all_nodes,
    get_node_neighbors,
)
from services.embedding_service import generate_embedding
from services.ingestion.normalizer import slugify as _normalizer_slugify
from services.paths import normalize_path
from services.hashing import get_changed_sources, mark_processed, mark_failed
from services.tracing import create_run, complete_run, skip_run, trace_agent
from services.events import publish

logger = logging.getLogger("vanilla.pipeline")


def _slugify(text: str) -> str:
    """Slug for article filenames — falls back to 'untitled' for empty input."""
    slug = _normalizer_slugify(text)
    return slug if slug else "untitled"


class AgentPipelineStatus:
    """Tracks the current state of the pipeline for /status endpoint."""

    def __init__(self):
        self.running = False
        self.current_phase: Optional[str] = None  # "ingest" | "analysis" | "proposal"
        self.current_run_id: Optional[str] = None
        self.total_tokens = 0


pipeline_status = AgentPipelineStatus()

# Maximum characters of file content to send per file in the ingest prompt.
_MAX_FILE_CHARS = 32_000


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token per 4 characters."""
    return max(1, len(text) // 4)


def _check_token_budget(config: VanillaConfig) -> None:
    """Raise if total_tokens exceeds the configured safety limit."""
    limit = config.llm.max_tokens_per_run
    if pipeline_status.total_tokens > limit:
        raise RuntimeError(
            f"Token budget exceeded: {pipeline_status.total_tokens} > {limit}"
        )


def _parse_json_response(raw: str) -> object:
    """Extract a JSON object or array from an LLM response, tolerating markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON in the text
        match = re.search(r"[\[{][\s\S]*[\]}]", cleaned)
        if match:
            return json.loads(match.group())
        raise ValueError(f"LLM did not return valid JSON: {cleaned[:300]}")


def _compute_rag_k(ingest_results: list[dict], existing_concepts: list) -> int:
    """
    A2: Adaptive RAG k — scales with batch size and wiki density.

    Formula: k = clamp(5, 20, len(ingest_results)*2 + len(existing_concepts)//15)
    Examples:
      1 doc, 0 concepts  → k=5  (floor)
      3 docs, 30 concepts → k=8
      5 docs, 90 concepts → k=16
     10 docs, 150 concepts → k=20 (ceiling)
    """
    k = len(ingest_results) * 2 + len(existing_concepts) // 15
    return min(20, max(5, k))


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Word-level Jaccard similarity between two strings. Pure Python — no numpy.
    Returns 0.0–1.0 where 1.0 = identical word bags.
    """
    words_a = set(re.findall(r"\b\w+\b", text_a.lower()))
    words_b = set(re.findall(r"\b\w+\b", text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union > 0 else 0.0


def _check_intra_batch_similarity(
    articles_written: list[dict],
    staging_dir: "Path",
    run_warnings: list[dict],
    threshold: float = 0.72,
) -> list[dict]:
    """
    Detect and remove near-duplicate articles within a staging batch.

    Reads each staged file, strips YAML frontmatter, and computes pairwise
    Jaccard similarity on the article body. If two articles exceed `threshold`
    the later one (alphabetically by title) is deleted from staging and
    recorded as a warning. Returns the deduplicated articles list.
    """
    if len(articles_written) < 2:
        return articles_written

    contents: list[str] = []
    for art in articles_written:
        path = staging_dir / art["filename"]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            # Strip frontmatter — compare only body prose
            body = re.sub(r"^---[\s\S]*?---\s*", "", text, count=1).strip()
            contents.append(body)
        except Exception:
            contents.append("")

    to_drop: set[int] = set()
    for i in range(len(articles_written)):
        if i in to_drop:
            continue
        for j in range(i + 1, len(articles_written)):
            if j in to_drop:
                continue
            sim = _jaccard_similarity(contents[i], contents[j])
            if sim >= threshold:
                logger.warning(
                    "Intra-batch duplicate: '%s' ≈ '%s' (Jaccard=%.2f) — dropping '%s'",
                    articles_written[i]["title"],
                    articles_written[j]["title"],
                    sim,
                    articles_written[j]["title"],
                )
                run_warnings.append({
                    "code": "intra_batch_duplicate",
                    "kept": articles_written[i]["title"],
                    "dropped": articles_written[j]["title"],
                    "similarity": round(sim, 3),
                })
                dup_path = staging_dir / articles_written[j]["filename"]
                try:
                    dup_path.unlink(missing_ok=True)
                except Exception:
                    pass
                to_drop.add(j)

    kept = [a for i, a in enumerate(articles_written) if i not in to_drop]
    if to_drop:
        logger.info(
            "Intra-batch dedup: %d duplicate(s) removed, %d article(s) kept",
            len(to_drop), len(kept),
        )
    return kept


# ─── Main Pipeline Entry Point ─────────────────────────────────────


async def run_pipeline(
    changed_paths: list[str],
    config: VanillaConfig,
) -> str:
    """
    Run the full pipeline for a set of changed file paths.

    Returns the run_id.
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    trigger_path = changed_paths[0] if changed_paths else None
    run_warnings: list[dict] = []  # Accumulates throughout the run

    # Feature 1: Hash-based incremental compilation — skip unchanged sources
    if config.clean_vault_path:
        vault_root = Path(config.clean_vault_path).parent
        filtered = get_changed_sources(changed_paths, vault_root)
        skipped = len(changed_paths) - len(filtered)
        if skipped:
            logger.info("Skipping %d unchanged source(s) (hash check)", skipped)
        changed_paths = filtered
    else:
        vault_root = Path(".")

    if not changed_paths:
        logger.info("All sources unchanged — skipping pipeline run")
        skip_run(trigger_path or "unknown", reason="hash_unchanged")
        return run_id

    # Feature 2: Create rich pipeline_runs audit record
    pipeline_run_id = create_run(
        source_path=trigger_path or "unknown",
        triggered_by="watcher",
    )

    pipeline_status.running = True
    pipeline_status.current_run_id = run_id
    pipeline_status.total_tokens = 0

    repo.create_agent_run(run_id, trigger_path=trigger_path)

    # Feature 3: SSE — notify frontend that a run has started
    publish("pipeline.started", {"run_id": pipeline_run_id, "source": trigger_path or ""})
    _run_start_time = time.monotonic()

    try:
        # Step 1: Ingest — read changed files, produce summaries
        pipeline_status.current_phase = "ingest"
        ingest_model = config.llm.models.get("ingest", "gpt-4o-mini")
        with trace_agent(pipeline_run_id, "ingest", ingest_model) as trace:
            trace.emit_progress("Reading and summarising source files…")
            ingest_results = await ingest_step(changed_paths, config, run_id, run_warnings)

        if not ingest_results:
            logger.info("No content to process after ingest step")
            repo.complete_agent_run(
                run_id, status="complete", tokens_used=pipeline_status.total_tokens,
                warnings=run_warnings,
            )
            complete_run(pipeline_run_id, status="complete")
            publish("pipeline.completed", {
                "run_id": pipeline_run_id, "status": "complete",
                "duration_ms": int((time.monotonic() - _run_start_time) * 1000),
                "proposals": 0,
            })
            return run_id

        # Step 2: Analysis — compare against existing wiki, determine actions
        pipeline_status.current_phase = "analysis"
        analysis_model = config.llm.models.get("analysis", "gpt-4o-mini")
        with trace_agent(pipeline_run_id, "analysis", analysis_model) as trace:
            trace.emit_progress("Comparing against existing wiki…")
            analysis_results, wiki_context = await analysis_step(
                ingest_results, config, run_id, run_warnings
            )

        if not analysis_results:
            logger.info("No actions recommended by analysis")
            repo.complete_agent_run(
                run_id, status="complete", tokens_used=pipeline_status.total_tokens,
                warnings=run_warnings,
            )
            complete_run(pipeline_run_id, status="complete")
            publish("pipeline.completed", {
                "run_id": pipeline_run_id, "status": "complete",
                "duration_ms": int((time.monotonic() - _run_start_time) * 1000),
                "proposals": 0,
            })
            return run_id

        # Step 3: Proposal — generate draft articles
        pipeline_status.current_phase = "proposal"
        proposal_model = config.llm.models.get("proposal", "gpt-4o")
        with trace_agent(pipeline_run_id, "proposal", proposal_model) as trace:
            trace.emit_progress("Drafting wiki articles…")
            proposal_count = await proposal_step(
                analysis_results, config, run_id, run_warnings,
                pipeline_run_id=pipeline_run_id,
                wiki_context=wiki_context,
                ingest_results=ingest_results,
            )

        # Mark all sources as successfully processed
        for p in changed_paths:
            mark_processed(p, vault_root, run_id=pipeline_run_id)

        repo.complete_agent_run(
            run_id, status="complete", tokens_used=pipeline_status.total_tokens,
            warnings=run_warnings,
        )
        complete_run(pipeline_run_id, status="proposals_pending", proposal_count=proposal_count)
        publish("pipeline.completed", {
            "run_id": pipeline_run_id,
            "status": "proposals_pending",
            "duration_ms": int((time.monotonic() - _run_start_time) * 1000),
            "proposals": proposal_count,
        })
        logger.info(
            "Pipeline complete: %s (tokens: %d, warnings: %d)",
            run_id, pipeline_status.total_tokens, len(run_warnings),
        )

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        for p in changed_paths:
            mark_failed(p, run_id=pipeline_run_id)
        repo.complete_agent_run(
            run_id,
            status="error",
            error_msg=str(e),
            tokens_used=pipeline_status.total_tokens,
            warnings=run_warnings,
        )
        complete_run(
            pipeline_run_id, status="failed",
            error_stage=pipeline_status.current_phase,
            error_message=str(e),
        )
        publish("pipeline.completed", {
            "run_id": pipeline_run_id, "status": "failed",
            "duration_ms": int((time.monotonic() - _run_start_time) * 1000),
            "proposals": 0,
        })
    finally:
        pipeline_status.running = False
        pipeline_status.current_phase = None
        pipeline_status.current_run_id = None

    return run_id


# ─── Step 1: Ingest ────────────────────────────────────────────────


INGEST_SYSTEM_PROMPT = """\
You are a document analysis agent. Read the following document and output a JSON with:
- "title": document title (infer from content if not explicit)
- "topics": list of 3-5 topic tags
- "summary": 2-3 sentence summary of key concepts
- "key_concepts": list of named concepts/entities worth tracking

Return ONLY valid JSON.\
"""


async def ingest_step(
    changed_paths: list[str],
    config: VanillaConfig,
    run_id: str,
    run_warnings: list[dict],
) -> list[dict]:
    """
    Read each changed file, send to LLM for topic extraction and summary.

    Returns list of dicts: {path, title, topics, summary, key_concepts}
    """
    results = []
    vault_root = ""
    if config.clean_vault_path:
        vault_root = str(Path(config.clean_vault_path).parent)

    for rel_path in changed_paths:
        _check_token_budget(config)

        # Resolve to absolute path
        if vault_root:
            abs_path = str(Path(vault_root) / rel_path)
        else:
            abs_path = rel_path

        # Read file content
        try:
            content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, FileNotFoundError):
            logger.warning("Cannot read file for ingest: %s", abs_path)
            continue

        if not content.strip():
            logger.debug("Skipping empty file: %s", rel_path)
            continue

        # Truncate to fit token budget
        truncated = content[:_MAX_FILE_CHARS]

        messages = [
            {"role": "system", "content": INGEST_SYSTEM_PROMPT},
            {"role": "user", "content": truncated},
        ]

        model = config.llm.models.get("ingest", "gpt-4o-mini")
        try:
            raw = await chat_completion(
                provider=config.llm.provider,
                api_key=config.llm.api_key,
                model=model,
                messages=messages,
                base_url=config.llm.base_url,
                max_tokens=2000,
                temperature=0.3,
            )
        except Exception as e:
            logger.error("Ingest LLM call failed for %s: %s", rel_path, e)
            continue

        # Track tokens
        prompt_text = INGEST_SYSTEM_PROMPT + truncated
        pipeline_status.total_tokens += _estimate_tokens(prompt_text) + _estimate_tokens(raw)

        try:
            parsed = _parse_json_response(raw)
            if isinstance(parsed, dict):
                entry = {
                    "path": normalize_path(rel_path),
                    "title": parsed.get("title", "Untitled"),
                    "topics": parsed.get("topics", []),
                    "summary": parsed.get("summary", ""),
                    "key_concepts": parsed.get("key_concepts", []),
                    # Keep truncated source text so the proposal step can pass
                    # real content to the LLM instead of metadata-only prompts.
                    "raw_content": truncated,
                }
                results.append(entry)

                # Generate and store embedding for semantic search / RAG
                try:
                    embed_text = (
                        f"{entry['title']} "
                        f"{entry['summary']} "
                        f"{' '.join(entry['key_concepts'])}"
                    )
                    emb = await generate_embedding(embed_text, config)
                    if emb:
                        repo.upsert_embedding(entry["path"], "clean", emb)
                except Exception as emb_err:
                    logger.warning("Embedding failed for %s: %s", rel_path, emb_err)

        except (ValueError, json.JSONDecodeError) as e:
            # C3: Record skipped file in run warnings
            logger.warning("Failed to parse ingest response for %s: %s", rel_path, e)
            run_warnings.append({
                "code": "skipped_file",
                "path": rel_path,
                "detail": str(e),
            })
            continue

    logger.info("Ingest step complete: %d files processed", len(results))
    return results


# ─── Step 2: Analysis ──────────────────────────────────────────────


ANALYSIS_SYSTEM_PROMPT = """\
You are a knowledge-base analysis agent for Vanilla. Your job is to compare \
newly ingested source material against the existing wiki and determine what \
actions to take.

You will receive:
1. Summaries of newly ingested documents (each labelled with its source path)
2. Full content of the most semantically similar existing wiki articles (via RAG)
3. A complete list of all existing wiki article titles (for deduplication)
4. The ontology rules
5. A list of stale articles (articles whose source material has changed)

Use the full article content in section 2 to avoid creating duplicates and to \
correctly identify updates vs new articles. If a concept is already well-covered \
in the wiki, do not recreate it — propose an "update" action instead.

STRICT RULES — violating these will produce a low-quality knowledge base:

1. BATCH SIZE CAP: You MUST propose at most as many actions as there are distinct \
source documents. If there are 2 source documents, propose at most 2 actions. \
Never fan-out one source into multiple near-identical articles.

2. SOURCE BINDING: Every action MUST include a "source_file" field naming the \
specific source document it is derived from. If you cannot point to a specific \
source, do not propose the action.

3. UNIQUE ANGLE: Every action MUST include a "unique_angle" field: a one-sentence \
statement of what is genuinely distinct about this article compared to all other \
actions in your response. If two actions would cover the same ground, merge them \
into one or drop the weaker one.

4. NO TITLE DUPLICATION: No two actions may have the same or near-identical concept \
names. Check your own output before returning it.

Output a JSON array of action objects. Each action:
{
  "action": "create" or "update",
  "concept": "Concept Name",
  "reason": "Why this article should be created/updated",
  "sources": ["clean-vault/raw/source-file.md"],
  "source_file": "clean-vault/raw/source-file.md",
  "unique_angle": "One sentence: what makes this article distinct from the others",
  "category": "category-name"
}

If no actions are needed, return an empty array: []

Return ONLY valid JSON.\
"""


async def analysis_step(
    ingest_results: list[dict],
    config: VanillaConfig,
    run_id: str,
    run_warnings: list[dict],
) -> list[dict]:
    """
    Compare ingest results against existing wiki state and determine actions.

    Returns list of action dicts: {action, concept, reason, sources, category}
    """
    _check_token_budget(config)

    wiki_vault = config.wiki_vault_path
    if not wiki_vault:
        logger.warning("No wiki vault configured, skipping analysis")
        return []

    # Load current graph nodes to get existing article titles
    existing_articles_raw = get_all_nodes()
    existing_articles = [node.get("label", node["id"]) for node in existing_articles_raw]

    # A2: Compute adaptive k for RAG retrieval
    k = _compute_rag_k(ingest_results, existing_articles)
    logger.info("RAG k=%d (docs=%d, concepts=%d)", k, len(ingest_results), len(existing_articles))

    # ── RAG: retrieve relevant wiki articles by semantic similarity ──────
    relevant_articles: dict[str, str] = {}  # {title: content}
    rag_degraded = False
    try:
        combined_summary = " ".join(
            f"{r['title']} {r['summary']} {' '.join(r['key_concepts'])}"
            for r in ingest_results
        )
        query_emb = await generate_embedding(combined_summary, config)
        if query_emb:
            similar = repo.search_vector(query_emb, vault="wiki", k=k)
            wiki_root = Path(wiki_vault).parent
            for hit in similar:
                article_abs = wiki_root / hit["path"]
                if article_abs.exists():
                    content = article_abs.read_text(encoding="utf-8", errors="replace")
                    relevant_articles[hit["title"]] = content[:3000]
            logger.info("RAG: retrieved %d relevant wiki articles (k=%d)", len(relevant_articles), k)
    except Exception as e:
        # C2: Warn user that RAG is degraded
        logger.warning("RAG retrieval failed, continuing with title-only context: %s", e)
        run_warnings.append({
            "code": "rag_degraded",
            "detail": str(e),
        })
        rag_degraded = True

    # ── B1: Multi-hop graph expansion (DRIFT-inspired) ───────────────────
    # For each semantically retrieved article, fetch its depth-1 graph
    # neighbors and include them as supplementary context.
    if not rag_degraded and relevant_articles:
        try:
            already_loaded = set(relevant_articles.keys())
            neighbor_count_before = 0
            wiki_root = Path(wiki_vault).parent

            for hit_title in list(already_loaded):
                # Derive node_id from the article path stem
                hit_node_id = hit_title.lower().replace(" ", "-")
                neighbors = get_node_neighbors(hit_node_id)
                for neighbor in neighbors:
                    neighbor_label = neighbor.get("label", neighbor["id"])
                    if neighbor_label in already_loaded:
                        continue
                    neighbor_path = neighbor.get("path", "")
                    if not neighbor_path:
                        continue
                    article_abs = wiki_root / neighbor_path
                    if article_abs.exists():
                        content = article_abs.read_text(encoding="utf-8", errors="replace")
                        # Shorter budget for neighbors — supplementary context
                        relevant_articles[f"[related] {neighbor_label}"] = content[:1500]
                        already_loaded.add(neighbor_label)
                        # Cap total articles at k+5
                        if len(relevant_articles) >= k + 5:
                            break
                if len(relevant_articles) >= k + 5:
                    break

            added = len(relevant_articles) - len(already_loaded.intersection(
                {t for t in relevant_articles if not t.startswith("[related]")}
            ))
            logger.info("Multi-hop: %d total articles in context after graph expansion", len(relevant_articles))
        except Exception as e:
            logger.warning("Multi-hop graph expansion failed: %s", e)

    # C4: Warn if ontology/AGENTS.md are missing
    ontology_content = ""
    ontology_path = Path(wiki_vault) / "ontology.md"
    if ontology_path.exists():
        try:
            ontology_content = ontology_path.read_text(encoding="utf-8")
        except OSError:
            pass
    else:
        logger.warning("MISSING: wiki-vault/ontology.md — analysis will use no ontology constraints")
        run_warnings.append({
            "code": "missing_ontology",
            "detail": "wiki-vault/ontology.md not found",
        })

    agents_content = ""
    agents_path = Path(wiki_vault) / "AGENTS.md"
    if agents_path.exists():
        try:
            agents_content = agents_path.read_text(encoding="utf-8")
        except OSError:
            pass
    else:
        logger.warning("MISSING: wiki-vault/AGENTS.md — analysis will use no agent constitution")
        run_warnings.append({
            "code": "missing_agents_md",
            "detail": "wiki-vault/AGENTS.md not found",
        })

    # Get stale articles
    stale_articles = repo.get_stale_articles()
    stale_list = [
        {"article": s["article_path"], "changed_source": s["source_path"]}
        for s in stale_articles
    ]

    # Build the user message
    user_parts = []
    user_parts.append("## Newly Ingested Documents\n")
    for r in ingest_results:
        user_parts.append(f"### {r['title']}")
        user_parts.append(f"- Source: {r['path']}")
        user_parts.append(f"- Topics: {', '.join(r['topics'])}")
        user_parts.append(f"- Summary: {r['summary']}")
        user_parts.append(f"- Key concepts: {', '.join(r['key_concepts'])}")
        user_parts.append("")

    user_parts.append("## Relevant Existing Wiki Articles (full content, via semantic search)\n")
    if relevant_articles:
        for title, content in relevant_articles.items():
            user_parts.append(f"### {title}\n{content}\n")
    else:
        user_parts.append("(No semantically similar articles found)\n")
    user_parts.append("")

    user_parts.append("## All Wiki Article Titles (for deduplication)\n")
    if existing_articles:
        for title in existing_articles:
            user_parts.append(f"- {title}")
    else:
        user_parts.append("(No articles exist yet)")
    user_parts.append("")

    user_parts.append("## Ontology Rules\n")
    user_parts.append(ontology_content or "(No ontology defined)")
    user_parts.append("")

    user_parts.append("## Agent Constitution\n")
    user_parts.append(agents_content or "(No agent constitution defined)")
    user_parts.append("")

    user_parts.append("## Stale Articles\n")
    if stale_list:
        for s in stale_list:
            user_parts.append(f"- {s['article']} (source changed: {s['changed_source']})")
    else:
        user_parts.append("(No stale articles)")

    user_message = "\n".join(user_parts)

    messages = [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    model = config.llm.models.get("analysis", "gpt-4o-mini")
    raw = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=model,
        messages=messages,
        base_url=config.llm.base_url,
        max_tokens=4096,
        temperature=0.3,
    )

    # Track tokens
    prompt_text = ANALYSIS_SYSTEM_PROMPT + user_message
    pipeline_status.total_tokens += _estimate_tokens(prompt_text) + _estimate_tokens(raw)

    try:
        parsed = _parse_json_response(raw)
        if isinstance(parsed, list):
            actions = parsed
        elif isinstance(parsed, dict) and "actions" in parsed:
            actions = parsed["actions"]
        else:
            actions = []
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse analysis response: %s", e)
        run_warnings.append({
            "code": "skipped_file",
            "path": "analysis_step",
            "detail": f"Analysis response unparseable: {e}",
        })
        actions = []

    # Hard cap: never propose more articles than distinct source files.
    # One source → one article. Prevents the fan-out duplication pattern.
    distinct_sources = len({r["path"] for r in ingest_results})
    if distinct_sources > 0 and len(actions) > distinct_sources:
        logger.warning(
            "Capping %d proposed actions to %d (distinct source limit)",
            len(actions), distinct_sources,
        )
        run_warnings.append({
            "code": "actions_capped",
            "original_count": len(actions),
            "capped_to": distinct_sources,
            "reason": "More proposals than distinct source documents",
        })
        actions = actions[:distinct_sources]

    # Drop actions where the LLM proposed identical concept names
    seen_concepts: dict[str, int] = {}
    deduped_actions = []
    for act in actions:
        c = act.get("concept", "").strip().lower()
        if c in seen_concepts:
            logger.warning(
                "Dropping duplicate concept '%s' from analysis results", act.get("concept")
            )
            run_warnings.append({
                "code": "duplicate_concept_dropped",
                "concept": act.get("concept"),
            })
            continue
        seen_concepts[c] = 1
        deduped_actions.append(act)
    actions = deduped_actions

    wiki_context = "\n\n".join(
        f"## {title}\n{content}" for title, content in relevant_articles.items()
    )
    logger.info("Analysis step complete: %d actions recommended", len(actions))
    return actions, wiki_context


# ─── Step 3: Proposal ──────────────────────────────────────────────


PROPOSAL_SYSTEM_PROMPT = """\
You are a wiki article writer for Vanilla. Write a well-structured Markdown \
article for a knowledge base.

The article MUST begin with YAML frontmatter in exactly this format:

```yaml
---
title: {concept}
category: {category}
sources:
{sources_yaml}
relationships:
  - target: "Related Concept Name"
    type: uses
created_by: vanilla-agent
batch_id: {batch_id}
status: draft
---
```

Valid relationship types: uses, is-a, derived-from, extends, contrasts-with, \
implements, part-of, related-to

List every concept you reference with [[wikilinks]] in the `relationships` \
frontmatter with the most accurate type. Use plain `related-to` when no \
stronger type applies. Omit relationships if there are none.

After the frontmatter, write a clear, informative article about the concept. \
Include:
- A concise introduction
- Key details and explanations
- Use [[wikilinks]] to reference related concepts when appropriate
- Keep it factual and well-sourced

Return the COMPLETE article including frontmatter. No extra explanation.\
"""


async def proposal_step(
    analysis_results: list[dict],
    config: VanillaConfig,
    run_id: str,
    run_warnings: list[dict],
    pipeline_run_id: str = "",
    wiki_context: str = "",
    ingest_results: "list[dict] | None" = None,
) -> int:
    """
    For each recommended action, generate a draft article and write to staging.
    Creates proposal records in the database.

    Returns the number of articles written.
    """
    ingest_results = ingest_results or []

    # Build a lookup: source path basename → ingest result, for fast matching
    _source_lookup: dict[str, dict] = {}
    for ir in ingest_results:
        # Index by full path, by basename, and by stem for flexible matching
        p = ir["path"]
        _source_lookup[p] = ir
        _source_lookup[Path(p).name] = ir
        _source_lookup[Path(p).stem] = ir

    wiki_vault = config.wiki_vault_path
    if not wiki_vault:
        logger.warning("No wiki vault configured, skipping proposal step")
        return

    batch_id = f"batch_{run_id}"
    staging_dir = Path(wiki_vault) / "staging" / batch_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    articles_written = []
    used_slugs: dict[str, str] = {}  # slug → title (D4: collision tracking)

    for action in analysis_results:
        _check_token_budget(config)

        concept = action.get("concept", "Untitled")
        category = action.get("category", "general")
        reason = action.get("reason", "")
        sources = action.get("sources", [])
        action_type = action.get("action", "create")

        # D4: Slug collision detection within this batch
        slug = _slugify(concept)
        if slug in used_slugs and used_slugs[slug] != concept:
            original_slug = slug
            suffix = 2
            while f"{slug}-{suffix}" in used_slugs:
                suffix += 1
            slug = f"{slug}-{suffix}"
            run_warnings.append({
                "code": "slug_collision",
                "original": concept,
                "collides_with": used_slugs[original_slug],
                "resolved_slug": slug,
            })
            logger.warning(
                "Slug collision: '%s' resolved to '%s' (collides with '%s')",
                concept, slug, used_slugs[original_slug],
            )
        used_slugs[slug] = concept

        # ── Resolve source content for this specific action ──────────────
        # Try to find the ingest result that matches this action's source file.
        source_content = ""
        source_ir: dict | None = None
        for s in sources + [action.get("source_file", "")]:
            if not s:
                continue
            for key in (s, Path(s).name, Path(s).stem):
                if key in _source_lookup:
                    source_ir = _source_lookup[key]
                    break
            if source_ir:
                break
        if source_ir:
            # Use up to half the file budget so we still have room for context
            source_content = source_ir.get("raw_content", "")[:_MAX_FILE_CHARS // 2]

        # ── Per-article RAG ──────────────────────────────────────────────
        # Generate an embedding specific to this article (not batch-blended)
        # and retrieve the most relevant wiki articles for it.
        per_article_wiki_ctx = wiki_context  # fallback to batch context
        if config.wiki_vault_path:
            try:
                article_query = f"{concept} {source_ir['summary'] if source_ir else reason}"
                article_emb = await generate_embedding(article_query, config)
                if article_emb:
                    wiki_root = Path(config.wiki_vault_path).parent
                    per_hits = repo.search_vector(article_emb, vault="wiki", k=5)
                    per_article_articles: dict[str, str] = {}
                    for hit in per_hits:
                        ap = wiki_root / hit["path"]
                        if ap.exists():
                            per_article_articles[hit["title"]] = (
                                ap.read_text(encoding="utf-8", errors="replace")[:2000]
                            )
                    if per_article_articles:
                        per_article_wiki_ctx = "\n\n".join(
                            f"## {t}\n{c}" for t, c in per_article_articles.items()
                        )
            except Exception as _rag_err:
                logger.warning("Per-article RAG failed for '%s': %s", concept, _rag_err)

        # ── Differentiation directive ────────────────────────────────────
        # Tell the LLM what other articles are in this batch so it can
        # write something genuinely distinct.
        other_concepts = [
            a.get("concept", "") for a in analysis_results
            if a.get("concept", "") != concept
        ]
        unique_angle = action.get("unique_angle", f"Focus specifically on {concept}")

        # Build sources YAML block
        sources_yaml = "\n".join(f"  - {s}" for s in sources) if sources else "  - unknown"

        # Build the prompt with placeholders filled in
        system_prompt = PROPOSAL_SYSTEM_PROMPT.format(
            concept=concept,
            category=category,
            sources_yaml=sources_yaml,
            batch_id=batch_id,
        )

        user_parts = [
            f"Write a wiki article about: {concept}",
            "",
            f"Action: {action_type}",
            f"Reason: {reason}",
            f"Category: {category}",
            f"Sources: {', '.join(sources)}",
            f"Unique angle for THIS article: {unique_angle}",
        ]

        if other_concepts:
            user_parts += [
                "",
                "OTHER ARTICLES BEING CREATED IN THIS SAME BATCH (your article MUST NOT",
                "duplicate their content — cover a clearly different aspect):",
                *[f"  - {c}" for c in other_concepts],
            ]

        if source_content:
            user_parts += [
                "",
                "## Source Material (write from this, do not invent facts)",
                source_content,
            ]

        if per_article_wiki_ctx:
            user_parts += [
                "",
                "## Relevant Existing Wiki Articles (for context and wikilinks)",
                per_article_wiki_ctx,
            ]

        user_message = "\n".join(user_parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        model = config.llm.models.get("proposal", "gpt-4o")
        try:
            article_content = await chat_completion(
                provider=config.llm.provider,
                api_key=config.llm.api_key,
                model=model,
                messages=messages,
                base_url=config.llm.base_url,
                max_tokens=4096,
                temperature=0.5,
            )
        except Exception as e:
            logger.error("Proposal LLM call failed for %s: %s", concept, e)
            run_warnings.append({
                "code": "skipped_file",
                "path": concept,
                "detail": f"Proposal LLM failed: {e}",
            })
            continue

        # Track tokens
        prompt_text = system_prompt + user_message
        pipeline_status.total_tokens += _estimate_tokens(prompt_text) + _estimate_tokens(
            article_content
        )

        # Feature 8: Review agent — check draft for quality issues before staging
        if pipeline_run_id and wiki_context:
            try:
                from agents.review import run_review_agent
                from config_loader import load_config as _load_agents_config

                async def _llm(model, messages, temperature, max_tokens):
                    return await chat_completion(
                        provider=config.llm.provider,
                        api_key=config.llm.api_key,
                        model=model,
                        messages=messages,
                        base_url=config.llm.base_url,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )

                agents_cfg = _load_agents_config()
                review_issues = await run_review_agent(
                    draft_article=article_content,
                    wiki_context=wiki_context,
                    config=agents_cfg,
                    run_id=pipeline_run_id,
                    llm_caller=_llm,
                )
                if review_issues:
                    review_block = (
                        "\nreview_status: issues_found\nreview_issues:\n"
                        + "".join(
                            f'  - type: {i.get("type", "UNKNOWN")}\n'
                            f'    description: "{i.get("description", "")}"\n'
                            for i in review_issues
                        )
                    )
                    article_content = article_content.replace(
                        "status: draft\n---",
                        f"status: draft{review_block}---",
                        1,
                    )
                    logger.info(
                        "Review: %d issue(s) found for '%s'", len(review_issues), concept
                    )
                else:
                    article_content = article_content.replace(
                        "status: draft\n---",
                        "status: draft\nreview_status: clean\n---",
                        1,
                    )
            except Exception as rev_err:
                logger.warning("Review agent error for '%s': %s", concept, rev_err)

        # Minimum word count gate — reject trivially short articles
        body_text = re.sub(r"^---[\s\S]*?---\s*", "", article_content, count=1).strip()
        word_count = len(body_text.split())
        if word_count < 100:
            logger.warning(
                "Article '%s' too short (%d words) — skipping", concept, word_count
            )
            run_warnings.append({
                "code": "article_too_short",
                "concept": concept,
                "word_count": word_count,
            })
            continue

        # Write article file to staging
        filename = f"{slug}.md"
        article_path = staging_dir / filename
        article_path.write_text(article_content, encoding="utf-8")

        articles_written.append({
            "filename": filename,
            "title": concept,
            "action": action_type,
            "slug": slug,
        })

    # Intra-batch deduplication — remove near-identical articles before
    # surfacing the batch to the user for review.
    if len(articles_written) > 1:
        articles_written = _check_intra_batch_similarity(
            articles_written, staging_dir, run_warnings
        )

    if not articles_written:
        logger.info("No proposal articles generated")
        return 0

    # Write proposal.md summary
    summary_lines = [
        f"# Proposal: {batch_id}\n",
        f"Run ID: {run_id}",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "## Articles\n",
    ]
    for art in articles_written:
        summary_lines.append(f"- **{art['title']}** ({art['action']}) — `{art['filename']}`")

    proposal_md = "\n".join(summary_lines) + "\n"
    (staging_dir / "proposal.md").write_text(proposal_md, encoding="utf-8")

    # Record in database
    batch_path = normalize_path(str(staging_dir))
    summary_text = f"{len(articles_written)} article(s): " + ", ".join(
        a["title"] for a in articles_written
    )
    repo.create_proposal(batch_id, batch_path, summary_text)

    for art in articles_written:
        repo.add_proposal_article(
            batch_id, art["filename"], art["title"], action=art["action"]
        )

    logger.info(
        "Proposal step complete: batch %s with %d articles",
        batch_id,
        len(articles_written),
    )
    return len(articles_written)
