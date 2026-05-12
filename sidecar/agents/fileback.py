"""
File-back agent — writes approved articles to wiki-vault.

Only runs when a human approves a proposal batch.
"""

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from config import VanillaConfig
from db import repository as repo
from services.embedding_service import generate_embedding
from services.graph_service import (
    add_node,
    add_edge,
    add_source_citation,
    get_hub_nodes,
    upsert_hub_summary,
)
from services.ingestion.normalizer import slugify
from services.paths import normalize_path

logger = logging.getLogger("vanilla.fileback")

# Regex to extract YAML frontmatter from a markdown file
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _extract_frontmatter(content: str) -> dict:
    """Extract YAML-like frontmatter fields from article content.

    Handles scalar values, flat lists (``- value``), and lists of dicts
    (``- key: value`` / ``  key: value`` blocks) without requiring PyYAML.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    result: dict = {}
    current_key: Optional[str] = None
    current_list: Optional[list] = None
    current_dict: Optional[dict] = None  # active dict item in a list-of-dicts

    for line in match.group(1).splitlines():
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # Nested key inside a list-of-dicts item (indented, no leading dash)
        if indent >= 4 and current_dict is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            current_dict[k.strip()] = v.strip().strip('"').strip("'")
            continue

        # List item
        if stripped.startswith("- ") and current_key:
            remainder = stripped[2:].strip()
            if current_list is None:
                current_list = []
                result[current_key] = current_list
            if ":" in remainder:
                # Start of a dict item inside the list
                current_dict = {}
                current_list.append(current_dict)
                k, _, v = remainder.partition(":")
                current_dict[k.strip()] = v.strip().strip('"').strip("'")
            else:
                current_dict = None
                current_list.append(remainder.strip('"').strip("'"))
            continue

        # Top-level key: value
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            current_key = key.strip()
            value = value.strip().strip('"').strip("'")
            current_list = None
            current_dict = None
            result[current_key] = value if value else ""

    return result


def _extract_frontmatter_title(path: Path) -> Optional[str]:
    """Read just the title field from a file's frontmatter."""
    try:
        content = path.read_text(encoding="utf-8")
        fm = _extract_frontmatter(content)
        return fm.get("title")
    except OSError:
        return None


def _extract_wikilinks(content: str) -> list[str]:
    """Return all [[wikilink]] targets found in content."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)


async def execute_fileback(batch_id: str, config: VanillaConfig) -> dict:
    """
    Write approved articles from staging to wiki-vault/concepts/.

    Steps:
    1. Read batch from staging/batch_{id}/
    2. Copy approved .md files to wiki-vault/concepts/ (with slug collision detection)
    3. Update index.md with new article links
    4. Update graph (SQLite) with new nodes/edges + source_map
    5. Generate and store vector embeddings for each article
    6. Record sync writes so watcher doesn't re-trigger
    7. Clean up staging directory
    8. Update proposal status in DB
    9. Trigger hub summary regeneration for newly-promoted hub nodes (B3)

    Returns {"articles_written": int, "errors": list}
    """
    wiki_vault = config.wiki_vault_path
    if not wiki_vault:
        return {"articles_written": 0, "errors": ["No wiki vault configured"]}

    # Atomically claim this batch: only proceed if it's still pending.
    claimed = repo.claim_proposal(batch_id)
    if not claimed:
        logger.warning("Batch %s already claimed or not found — skipping fileback", batch_id)
        return {"articles_written": 0, "errors": ["Batch already processing or approved"]}

    wiki_path = Path(wiki_vault)
    concepts_dir = wiki_path / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    staging_dir = wiki_path / "staging" / batch_id
    if not staging_dir.exists():
        repo.update_proposal_status(batch_id, "error")
        return {"articles_written": 0, "errors": [f"Staging directory not found: {batch_id}"]}

    articles_written = 0
    errors = []
    written_articles = []  # Track for index update

    # Find all article .md files in staging (skip proposal.md)
    for md_file in staging_dir.glob("*.md"):
        if md_file.name == "proposal.md":
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
            frontmatter = _extract_frontmatter(content)

            title = frontmatter.get("title", md_file.stem)
            category = frontmatter.get("category", "general")
            sources = frontmatter.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]

            # ── D4: Slug collision detection ─────────────────────────
            dest_path = concepts_dir / md_file.name
            if dest_path.exists():
                existing_title = _extract_frontmatter_title(dest_path)
                if existing_title and existing_title.lower() != title.lower():
                    logger.warning(
                        "Slug collision: '%s' would overwrite '%s' — skipping",
                        title,
                        existing_title,
                    )
                    errors.append(
                        f"Slug collision: '{title}' maps to '{md_file.name}' "
                        f"which already belongs to '{existing_title}'"
                    )
                    continue

            # Copy to concepts directory
            dest_path.write_text(content, encoding="utf-8")

            # Record sync write to prevent watcher re-trigger
            relative_dest = normalize_path(
                f"wiki-vault/concepts/{md_file.name}"
            )
            repo.record_sync_write(relative_dest)

            # Update graph: add node
            node_id = slugify(title)
            add_node(
                node_id=node_id,
                label=title,
                path=relative_dest,
                category=category,
                batch_id=batch_id,
            )

            # Update graph: add source citations
            for source in sources:
                source_normalized = normalize_path(source)
                add_source_citation(source_normalized, relative_dest)

            # Update graph: add typed edges from relationships frontmatter,
            # then fall back to plain wikilinks for any refs not listed there.
            relationships = frontmatter.get("relationships", [])
            typed_targets: set[str] = set()
            if isinstance(relationships, list):
                for rel in relationships:
                    if isinstance(rel, dict):
                        target_label = rel.get("target", "")
                        edge_type = rel.get("type", "related-to")
                        if target_label:
                            target_id = slugify(target_label)
                            typed_targets.add(target_id)
                            add_edge(source=node_id, target=target_id, edge_type=edge_type)

            # Plain [[wikilinks]] not already covered by relationships
            wikilinks = _extract_wikilinks(content)
            for link_target in wikilinks:
                target_id = slugify(link_target)
                if target_id not in typed_targets:
                    add_edge(source=node_id, target=target_id, edge_type="related-to")

            # Update FTS index
            repo.upsert_fts(relative_dest, "wiki", title, content)

            # Generate and store vector embedding for future RAG retrieval
            try:
                emb = await generate_embedding(content[:32_000], config)
                if emb:
                    repo.upsert_embedding(relative_dest, "wiki", emb)
            except Exception as emb_err:
                logger.warning("Embedding failed for wiki article %s: %s", relative_dest, emb_err)

            # Clear stale flags for this article if any
            repo.clear_stale_article(relative_dest)

            # Update individual article status
            repo.update_article_status(batch_id, md_file.name, "approved")

            # Scan for <!-- exec --> code blocks and create exec_run records
            _create_exec_runs_for_article(content, relative_dest)

            written_articles.append({"title": title, "filename": md_file.name})
            articles_written += 1

            logger.info("Wrote article: %s -> %s", md_file.name, dest_path)

        except Exception as e:
            error_msg = f"Error processing {md_file.name}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    # sync write guards for index
    repo.record_sync_write(normalize_path("wiki-vault/index.md"))

    # Update index.md
    _update_index(wiki_path, written_articles)

    # Update proposal status in DB
    repo.update_proposal_status(batch_id, "approved")

    # Clean up staging directory
    try:
        shutil.rmtree(staging_dir)
        logger.info("Cleaned up staging directory: %s", staging_dir)
    except OSError as e:
        logger.warning("Could not clean staging dir %s: %s", staging_dir, e)

    # ── B3: Hub summary generation ───────────────────────────────────
    # After graph is updated, find newly promoted hub nodes and generate
    # summaries in the background (fire-and-forget; failures don't block).
    try:
        import asyncio
        asyncio.create_task(_refresh_hub_summaries(config))
    except Exception as e:
        logger.debug("Could not schedule hub summary refresh: %s", e)

    logger.info(
        "Fileback complete for %s: %d articles written, %d errors",
        batch_id,
        articles_written,
        len(errors),
    )

    return {"articles_written": articles_written, "errors": errors}


async def _refresh_hub_summaries(config: VanillaConfig) -> None:
    """
    Regenerate hub summaries for all nodes with degree >= 3 whose summary
    is missing or stale. Called after every successful fileback.
    """
    from services.llm_service import chat_completion

    hub_nodes = get_hub_nodes(min_degree=3)
    for node in hub_nodes:
        node_id = node["id"]
        # Only regenerate if no summary exists yet
        existing = repo.graph_get_hub_summary(node_id)
        if existing:
            continue

        try:
            from services.graph_service import get_node_neighbors
            neighbors = get_node_neighbors(node_id)
            neighbor_lines = "\n".join(
                f"- {n['label']} (via {n['relationship']})"
                for n in neighbors[:10]
            )
            prompt = (
                f"Concept: {node['label']} (category: {node.get('category', '')})\n"
                f"Connected to:\n{neighbor_lines}\n\n"
                "Write 2–3 sentences summarizing what this concept represents "
                "and how it relates to its neighbors. Be precise and factual."
            )
            model = config.llm.models.get("ingest", "gpt-4o-mini")
            summary = await chat_completion(
                provider=config.llm.provider,
                api_key=config.llm.api_key,
                model=model,
                messages=[{"role": "user", "content": prompt}],
                base_url=config.llm.base_url,
                max_tokens=200,
                temperature=0.3,
            )
            upsert_hub_summary(node_id, summary.strip())
            logger.info("Generated hub summary for '%s'", node["label"])
        except Exception as e:
            logger.warning("Hub summary generation failed for %s: %s", node_id, e)


_EXEC_BLOCK_RE = re.compile(
    r"<!--\s*exec\s*-->\s*```(\w+)\s*\n(.*?)```\s*<!--\s*/exec\s*-->",
    re.DOTALL,
)


def _create_exec_runs_for_article(content: str, article_path: str) -> list[str]:
    """
    Scan article content for <!-- exec -->```lang ... ```<!-- /exec --> blocks.
    Creates an exec_run record for each found block.

    Idempotent: skips any block whose code already has a pending run for this
    article (prevents duplicates when fileback runs on the same article twice).
    Returns list of created run IDs (may be empty if all are already pending).
    """
    # Build a set of pending code blobs for this article to detect duplicates
    existing_pending = {r["code"] for r in repo.get_pending_exec_runs_for_article(article_path)}

    run_ids = []
    for match in _EXEC_BLOCK_RE.finditer(content):
        lang = match.group(1).strip()
        code = match.group(2).strip()
        if not lang or not code:
            continue
        if code in existing_pending:
            logger.debug("Skipping duplicate exec run for %s (already pending)", article_path)
            continue
        run_id = repo.create_exec_run(article_path, code, lang)
        existing_pending.add(code)  # prevent same block from being queued twice within one call
        run_ids.append(run_id)
        logger.info(
            "Queued exec run %s for article %s (%s, %d chars)",
            run_id,
            article_path,
            lang,
            len(code),
        )
    return run_ids


def _update_index(wiki_path: Path, new_articles: list[dict]) -> None:
    """Append new articles to wiki-vault/index.md."""
    index_path = wiki_path / "index.md"

    if not new_articles:
        return

    # Read existing index
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
    else:
        existing = "# Wiki Index\n\n*Auto-maintained by the File-back Agent. Do not edit manually.*\n\n## Concepts\n"

    # Append new entries
    new_lines = []
    for art in new_articles:
        link = f"- [[{art['title']}]] — `concepts/{art['filename']}`"
        # Avoid duplicates
        if link not in existing:
            new_lines.append(link)

    if new_lines:
        updated = existing.rstrip() + "\n" + "\n".join(new_lines) + "\n"
        index_path.write_text(updated, encoding="utf-8")
