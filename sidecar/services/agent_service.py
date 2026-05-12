"""
Agent instruction service — processes user instructions and generates staging proposals.

Supported operations:
  edit_file      — modify content of an existing file
  create_concept — create a new knowledge base article
  change_links   — add/remove [[WikiLinks]] between concepts
  restructure    — rename/merge multiple concepts (multi-file batch)
  search         — read-only query, returns answer inline (no proposal)

All file-modifying operations route through the existing staging → approve/reject flow.
Nothing is written to wiki-vault/concepts/ until the user explicitly approves in ProposalPanel.
"""

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from config import VanillaConfig

from db.repository import create_proposal, add_proposal_article
from services.llm_service import chat_completion

logger = logging.getLogger("vanilla.agent_service")


# ─── Operation Classification ─────────────────────────────────────────

_CLASSIFY_PROMPT = """Classify this user instruction for a personal knowledge base editor into exactly one operation type.
Reply with ONLY the operation type — no punctuation, no explanation.

Operation types:
  edit_file      - modifies content of ONE specific open/named file (rewrite, expand, summarize, fix, add section, improve THIS file)
  create_concept - creates a new knowledge base article (write about, create, add entry for, document a new topic)
  change_links   - adds or removes wikilinks between concepts (link X to Y, connect, unlink, add reference)
  restructure    - renames or merges multiple concepts across files (rename X to Y, merge, consolidate)
  multi_edit     - edits MULTIPLE files at once (all concepts, every article, bulk add/remove/clean, mass edit, apply to all X, clean topic from files, add section to all Y)
  graph_settings - changes how the knowledge graph looks or behaves (color nodes by, show/hide edges, cluster mode, node size, particles, dim nodes, grouping, labels)
  search         - answers a question without making changes (what is, find, show, list, explain)

Instruction: {instruction}"""


async def _classify(instruction: str, config: "VanillaConfig") -> str:
    model = config.llm.models.get("analysis", "gpt-4o-mini")
    try:
        result = await chat_completion(
            provider=config.llm.provider,
            api_key=config.llm.api_key,
            model=model,
            messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(instruction=instruction)}],
            base_url=config.llm.base_url,
            max_tokens=15,
            temperature=0.0,
        )
        op = result.strip().lower().split()[0] if result.strip() else ""
        valid = {"edit_file", "create_concept", "change_links", "restructure", "multi_edit", "graph_settings", "search"}
        return op if op in valid else "edit_file"
    except Exception as exc:
        logger.warning("Instruction classification failed (%s) — defaulting to edit_file", exc)
        return "edit_file"


# ─── Context Helpers ──────────────────────────────────────────────────

def _read_file(file_path: str) -> str:
    p = Path(file_path)
    if not p.is_absolute():
        logger.warning(
            "_read_file received a relative path %r — caller should resolve it first", file_path
        )
    try:
        return p.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return ""


def _graph_summary(limit: int = 40) -> str:
    try:
        from db.database import get_connection
        rows = get_connection().execute(
            "SELECT label FROM graph_nodes ORDER BY label LIMIT ?", (limit,)
        ).fetchall()
        return ", ".join(r["label"] for r in rows) if rows else ""
    except Exception:
        return ""


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len] or "concept"


def _extract_title(markdown: str) -> Optional[str]:
    """Extract title from YAML frontmatter or first H1."""
    m = re.match(r"^---\s*\n.*?^title:\s*['\"]?(.+?)['\"]?\s*$.*?^---", markdown, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"^#\s+(.+)", markdown, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def _strip_fences(text: str) -> str:
    """Remove markdown code fences the LLM might wrap around its output."""
    text = re.sub(r"^```(?:markdown|md)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text.strip())
    return text.strip()


def _write_staging(config: "VanillaConfig", batch_id: str, filename: str, content: str) -> None:
    staging_dir = Path(config.wiki_vault_path) / "staging" / batch_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / filename).write_text(content, encoding="utf-8")


# ─── Prompts ──────────────────────────────────────────────────────────

_EDIT_PROMPT = """You are a markdown editor for a personal knowledge base.
Given the instruction and the current file content, return the COMPLETE edited markdown.
Rules:
- Preserve YAML frontmatter exactly unless the instruction explicitly says to change it.
- Do NOT add commentary, preamble, or markdown code fences around your response.
- Return only the complete markdown content of the file.
{neighbors_block}
Current file ({path}):
---
{content}
---

Instruction: {instruction}"""

_CREATE_PROMPT = """You are a knowledge base author creating a new concept article.
Format as clean markdown with a YAML frontmatter block:
  ---
  title: <title>
  tags: [tag1, tag2]
  related: [Related Concept 1, Related Concept 2]
  ---
Use [[WikiLinks]] for related concepts where natural.
Write clearly — this is a reference document, not an essay.
{neighbors_block}
Existing concepts for context: {graph_summary}

Instruction: {instruction}"""

_LINKS_PROMPT = """You are a knowledge base editor updating wikilinks.
Return the COMPLETE file with [[WikiLinks]] added or removed as instructed.
- Add a link: insert [[Target Concept]] naturally in the text
- Remove a link: replace [[Concept]] with just the concept name
Preserve all other content and frontmatter exactly.
Do NOT add commentary or markdown fences.

Current file ({path}):
---
{content}
---

Instruction: {instruction}"""

_SEARCH_PROMPT = """You are a knowledge base assistant. Answer the question using the graph context provided.
Be concise. Cite concept names in **bold** where relevant.

Existing concepts: {graph_summary}
{file_context}
Question: {instruction}"""

_MULTI_EDIT_SCOPE_PROMPT = """You are selecting which knowledge base files should be edited by this instruction.
Given the file manifest and the instruction, return ONLY a JSON array of filenames to edit.
Be selective — only include files clearly in scope of the instruction.
Cap at 15 files maximum.

Files (filename | label | category | tags | excerpt):
{manifest}

Instruction: {instruction}

Reply with ONLY a JSON array, e.g.: ["concept-a.md", "concept-b.md"]
If no files match, reply with: []"""

_MULTI_EDIT_FILE_PROMPT = """You are a markdown editor for a personal knowledge base.
Apply this instruction to the file below. Return the COMPLETE edited markdown.
Rules:
- Preserve YAML frontmatter exactly unless the instruction explicitly says to change it.
- Do NOT add commentary, preamble, or markdown code fences.
- Return ONLY the complete markdown content.

Instruction: {instruction}

File ({filename}):
---
{content}
---"""

_GRAPH_SETTINGS_PROMPT = """You control the visual settings of a knowledge graph. Map the user's instruction to the correct settings.

Available settings and their valid values:
  colorMode          : "category" (color nodes by concept type) | "cluster-topology" (color by Louvain community) | "cluster-semantic" (color by AI similarity) | "uniform" (all same color)
  nodeSizeMode       : "degree" (larger = more connections) | "citations" (larger = more source docs cite it) | "uniform" (all same size)
  clusterMode        : "none" | "topology" (Louvain community detection) | "semantic" (K-Means on embeddings)
  showEdgeParticles  : true | false  — animated particles flowing along edges
  showEdgeTypeColors : true | false  — color edges by their relationship type
  showEdgeLabels     : true | false  — show relationship type as label on edges
  showHulls          : true | false  — convex hull bubble drawn around each cluster
  forceGrouping      : true | false  — physics force that drifts cluster nodes together
  dimUnhoveredNodes  : true | false  — dim non-neighbor nodes when hovering a node
  labelZoomThreshold : number 0.4–2.0 — zoom level at which hub labels appear (lower = appear sooner)

Reply with ONLY a JSON object containing ONLY the settings that need to change. No prose, no markdown fences.
Example: {{"colorMode": "cluster-topology", "clusterMode": "topology", "showHulls": true}}

Instruction: {instruction}"""

_RESTRUCTURE_PLAN_PROMPT = """You are restructuring a personal knowledge base.
Given the existing concept files and the user's instruction, produce a JSON plan of changes.
Reply with ONLY a valid JSON array — no prose, no markdown fences.

Existing concepts:
{file_list}

Instruction: {instruction}

Return a JSON array like:
[
  {{"file": "existing-filename.md", "new_name": "new-filename.md", "changes": "description of what changes"}}
]
Only include files that genuinely need to change. Use "new_name" = null if the filename stays the same."""


# ─── Operation Handlers ───────────────────────────────────────────────

async def _edit_file(
    instruction: str,
    file_path: str,
    graph_neighbors: list[str],
    config: "VanillaConfig",
    op_type: str = "edit_file",
) -> dict:
    content = _read_file(file_path)
    if not content:
        raise ValueError(f"Could not read file: {file_path}")

    neighbors_block = (
        f"Linked concepts: {', '.join(graph_neighbors)}\n\n"
        if graph_neighbors else ""
    )

    if op_type == "change_links":
        prompt = _LINKS_PROMPT.format(
            path=file_path,
            content=content,
            instruction=instruction,
        )
    else:
        prompt = _EDIT_PROMPT.format(
            neighbors_block=neighbors_block,
            path=file_path,
            content=content,
            instruction=instruction,
        )

    model = config.llm.models.get("proposal", "gpt-4o")
    new_content = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        base_url=config.llm.base_url,
        max_tokens=4096,
        temperature=0.3,
    )
    new_content = _strip_fences(new_content)

    batch_id = uuid.uuid4().hex[:8]
    filename = Path(file_path).name
    _write_staging(config, batch_id, filename, new_content)
    batch_path = str(Path(config.wiki_vault_path) / "staging" / batch_id)

    title = _extract_title(new_content) or Path(file_path).stem
    action_label = "links updated" if op_type == "change_links" else "edited"
    create_proposal(batch_id, batch_path, f"Agent {action_label}: {instruction[:80]}", source="agent")
    add_proposal_article(batch_id, filename, title, action="update")

    return {
        "batch_id": batch_id,
        "operation_type": op_type,
        "summary": f"{filename} — {instruction[:60]}",
    }


async def _create_concept(
    instruction: str,
    graph_neighbors: list[str],
    config: "VanillaConfig",
) -> dict:
    summary = _graph_summary()
    neighbors_block = (
        f"Relevant concepts from context: {', '.join(graph_neighbors)}\n\n"
        if graph_neighbors else ""
    )

    prompt = _CREATE_PROMPT.format(
        neighbors_block=neighbors_block,
        graph_summary=summary or "No existing concepts yet",
        instruction=instruction,
    )

    model = config.llm.models.get("proposal", "gpt-4o")
    content = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        base_url=config.llm.base_url,
        max_tokens=4096,
        temperature=0.4,
    )
    content = _strip_fences(content)

    title = _extract_title(content) or "New Concept"
    slug = _slugify(title)
    # Deduplicate filename if needed
    filename = f"{slug}-{uuid.uuid4().hex[:4]}.md"

    batch_id = uuid.uuid4().hex[:8]
    _write_staging(config, batch_id, filename, content)
    batch_path = str(Path(config.wiki_vault_path) / "staging" / batch_id)

    create_proposal(batch_id, batch_path, f"Agent created: {title}", source="agent")
    add_proposal_article(batch_id, filename, title, action="create")

    return {
        "batch_id": batch_id,
        "operation_type": "create_concept",
        "summary": f"New article: {title}",
    }


async def _restructure(instruction: str, config: "VanillaConfig") -> dict:
    concepts_dir = Path(config.wiki_vault_path) / "concepts"
    if not concepts_dir.exists():
        raise ValueError("No concepts directory found in wiki-vault")

    concept_files = sorted(concepts_dir.glob("*.md"))[:25]
    if not concept_files:
        raise ValueError("No concept files found to restructure")

    file_list = "\n".join(f.name for f in concept_files)

    plan_raw = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=config.llm.models.get("analysis", "gpt-4o-mini"),
        messages=[{"role": "user", "content": _RESTRUCTURE_PLAN_PROMPT.format(
            file_list=file_list,
            instruction=instruction,
        )}],
        base_url=config.llm.base_url,
        max_tokens=1000,
        temperature=0.2,
    )

    # Parse plan JSON
    plan_raw = _strip_fences(plan_raw)
    try:
        changes: list[dict] = json.loads(plan_raw)
    except Exception as exc:
        raise ValueError(
            f"Could not parse restructure plan — try rephrasing the instruction. ({exc})"
        ) from exc

    if not changes:
        raise ValueError("No changes identified for this instruction.")

    batch_id = uuid.uuid4().hex[:8]
    batch_path = str(Path(config.wiki_vault_path) / "staging" / batch_id)
    create_proposal(
        batch_id, batch_path,
        f"Agent restructure ({len(changes)} files): {instruction[:60]}",
        source="agent",
    )

    edit_model = config.llm.models.get("proposal", "gpt-4o")
    for change in changes[:10]:
        src = concepts_dir / change.get("file", "")
        if not src.exists():
            continue

        old_content = _read_file(str(src))
        new_name = change.get("new_name") or change.get("file")
        change_desc = change.get("changes", instruction)

        edit_prompt = (
            f"Apply this change to the file: {change_desc}\n\n"
            f"Return the complete new markdown:\n---\n{old_content}\n---"
        )

        new_content = await chat_completion(
            provider=config.llm.provider,
            api_key=config.llm.api_key,
            model=edit_model,
            messages=[{"role": "user", "content": edit_prompt}],
            base_url=config.llm.base_url,
            max_tokens=4096,
            temperature=0.2,
        )
        new_content = _strip_fences(new_content)

        _write_staging(config, batch_id, new_name, new_content)
        title = _extract_title(new_content) or Path(new_name).stem
        add_proposal_article(batch_id, new_name, title, action="update")

    return {
        "batch_id": batch_id,
        "operation_type": "restructure",
        "summary": f"Restructured {len(changes)} file(s): {instruction[:50]}",
    }


def _parse_fm_tags(content: str) -> list[str]:
    """Extract tags list from YAML frontmatter (handles both inline and block styles)."""
    fm_match = re.match(r"^---\s*\n([\s\S]*?)\n---", content)
    if not fm_match:
        return []
    fm = fm_match.group(1)
    # Inline: tags: [a, b, c]
    inline = re.search(r"^tags:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline:
        return [t.strip().strip('"\'') for t in inline.group(1).split(",") if t.strip()]
    # Block: tags:\n  - a\n  - b
    block = re.search(r"^tags:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.MULTILINE)
    if block:
        return [re.sub(r"^\s*-\s*", "", line).strip() for line in block.group(1).splitlines() if line.strip()]
    return []


def _parse_fm_field(content: str, field: str) -> str:
    """Extract a single string field from YAML frontmatter."""
    fm_match = re.match(r"^---\s*\n([\s\S]*?)\n---", content)
    if not fm_match:
        return ""
    m = re.search(rf"^{field}:\s*['\"]?(.+?)['\"]?\s*$", fm_match.group(1), re.MULTILINE)
    return m.group(1).strip() if m else ""


def _get_concept_manifest(config: "VanillaConfig") -> list[dict]:
    """
    Build a compact manifest of all concept files for multi-edit targeting.
    Returns list of {filename, label, category, tags, excerpt, abs_path}.
    """
    concepts_dir = Path(config.wiki_vault_path) / "concepts"
    if not concepts_dir.exists():
        return []
    result = []
    for path in sorted(concepts_dir.glob("*.md"))[:60]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        label = _parse_fm_field(content, "title") or _extract_title(content) or path.stem
        category = _parse_fm_field(content, "category")
        tags = _parse_fm_tags(content)
        # Strip frontmatter for excerpt
        body = re.sub(r"^---\s*\n[\s\S]*?\n---\s*\n", "", content).strip()
        excerpt = body[:120].replace("\n", " ")
        result.append({
            "filename": path.name,
            "label": label,
            "category": category,
            "tags": ", ".join(tags),
            "excerpt": excerpt,
            "abs_path": str(path),
        })
    return result


async def _multi_edit(
    instruction: str,
    config: "VanillaConfig",
) -> dict:
    """
    Edit multiple concept files matching the instruction's scope.
    Step 1: LLM selects which files are in scope from a compact manifest.
    Step 2: LLM edits each selected file.
    Step 3: All changes are bundled into one proposal batch.
    """
    manifest = _get_concept_manifest(config)
    if not manifest:
        raise ValueError("No concept files found. Create some concepts first.")

    # Build compact manifest string for scope selection
    manifest_lines = "\n".join(
        f"{m['filename']} | {m['label']} | {m['category']} | {m['tags']} | {m['excerpt']}"
        for m in manifest
    )

    scope_raw = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=config.llm.models.get("analysis", "gpt-4o-mini"),
        messages=[{"role": "user", "content": _MULTI_EDIT_SCOPE_PROMPT.format(
            manifest=manifest_lines,
            instruction=instruction,
        )}],
        base_url=config.llm.base_url,
        max_tokens=500,
        temperature=0.0,
    )

    scope_raw = _strip_fences(scope_raw).strip()
    try:
        selected_filenames: list[str] = json.loads(scope_raw)
    except Exception as exc:
        raise ValueError(
            f"Could not parse file scope — try rephrasing. ({exc})"
        ) from exc

    if not selected_filenames:
        return {
            "answer": "No matching files found for that instruction. Try a broader description, or name a specific category or tag.",
            "sources": [],
        }

    # Cap to 15 and verify files exist
    file_map = {m["filename"]: m for m in manifest}
    targets = [file_map[fn] for fn in selected_filenames[:15] if fn in file_map]
    if not targets:
        return {
            "answer": "No matching files found. The instruction may be too specific.",
            "sources": [],
        }

    batch_id = uuid.uuid4().hex[:8]
    batch_path = str(Path(config.wiki_vault_path) / "staging" / batch_id)
    create_proposal(
        batch_id, batch_path,
        f"Agent multi-edit ({len(targets)} files): {instruction[:60]}",
        source="agent",
    )

    edit_model = config.llm.models.get("proposal", "gpt-4o")
    edited_count = 0
    for target in targets:
        try:
            old_content = Path(target["abs_path"]).read_text(encoding="utf-8")
        except Exception:
            continue

        new_content = await chat_completion(
            provider=config.llm.provider,
            api_key=config.llm.api_key,
            model=edit_model,
            messages=[{"role": "user", "content": _MULTI_EDIT_FILE_PROMPT.format(
                instruction=instruction,
                filename=target["filename"],
                content=old_content,
            )}],
            base_url=config.llm.base_url,
            max_tokens=4096,
            temperature=0.2,
        )
        new_content = _strip_fences(new_content)
        _write_staging(config, batch_id, target["filename"], new_content)
        title = _extract_title(new_content) or target["label"]
        add_proposal_article(batch_id, target["filename"], title, action="update")
        edited_count += 1

    if edited_count == 0:
        raise ValueError("All file edits failed — check the sidecar logs.")

    return {
        "batch_id": batch_id,
        "operation_type": "multi_edit",
        "summary": f"Edited {edited_count} file(s): {instruction[:50]}",
    }


async def _graph_settings(
    instruction: str,
    config: "VanillaConfig",
) -> dict:
    """
    Map a natural-language instruction to a GraphSettings delta.
    Returns {"operation_type": "graph_settings", "settings": {...partial settings...}}.
    The frontend applies the delta to the settings store directly.
    """
    raw = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=config.llm.models.get("analysis", "gpt-4o-mini"),
        messages=[{"role": "user", "content": _GRAPH_SETTINGS_PROMPT.format(
            instruction=instruction,
        )}],
        base_url=config.llm.base_url,
        max_tokens=200,
        temperature=0.0,
    )

    raw = _strip_fences(raw).strip()
    try:
        settings_delta: dict = json.loads(raw)
    except Exception as exc:
        raise ValueError(
            f"Could not parse graph settings response — try rephrasing. ({exc})"
        ) from exc

    # Validate keys — only allow known settings fields
    _VALID_KEYS = {
        "colorMode", "nodeSizeMode", "clusterMode",
        "showEdgeParticles", "showEdgeTypeColors", "showEdgeLabels",
        "showHulls", "forceGrouping", "dimUnhoveredNodes", "labelZoomThreshold",
    }
    settings_delta = {k: v for k, v in settings_delta.items() if k in _VALID_KEYS}

    if not settings_delta:
        return {
            "answer": "I couldn't map that to any graph settings. Try something like: 'color nodes by cluster', 'hide edge particles', 'make all nodes the same size', or 'group nodes by community'.",
            "sources": [],
        }

    # Build a human-readable summary of the changes
    change_descriptions = []
    for key, val in settings_delta.items():
        change_descriptions.append(f"{key} → {val}")

    return {
        "operation_type": "graph_settings",
        "settings": settings_delta,
        "summary": f"Graph settings updated: {', '.join(change_descriptions)}",
    }


async def _search(
    instruction: str,
    file_path: Optional[str],
    config: "VanillaConfig",
) -> dict:
    graph_sum = _graph_summary(60)
    file_context = ""
    if file_path:
        content = _read_file(file_path)
        if content:
            file_context = f"\nCurrent file content (excerpt):\n---\n{content[:3000]}\n---"

    prompt = _SEARCH_PROMPT.format(
        graph_summary=graph_sum or "No concepts indexed yet",
        file_context=file_context,
        instruction=instruction,
    )

    answer = await chat_completion(
        provider=config.llm.provider,
        api_key=config.llm.api_key,
        model=config.llm.models.get("analysis", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        base_url=config.llm.base_url,
        max_tokens=1000,
        temperature=0.5,
    )

    # Find which known concepts are mentioned in the answer
    sources: list[str] = []
    try:
        from db.database import get_connection
        rows = get_connection().execute("SELECT label FROM graph_nodes").fetchall()
        for row in rows:
            if row["label"].lower() in answer.lower():
                sources.append(row["label"])
    except Exception:
        pass

    return {"answer": answer, "sources": sources[:8]}


# ─── Public API ───────────────────────────────────────────────────────

async def execute_instruction(
    instruction: str,
    file_path: Optional[str],
    graph_neighbors: list[str],
    config: "VanillaConfig",
) -> dict:
    """
    Execute an agent instruction. Returns:
      - For file-modifying ops: {"batch_id", "operation_type", "summary"}
      - For search: {"answer", "sources"}

    Raises ValueError if LLM is not configured or input is invalid.
    """
    if not config.llm.api_key and config.llm.provider != "ollama":
        raise ValueError("LLM not configured — please set up your API key in Settings.")

    if not instruction.strip():
        raise ValueError("Instruction cannot be empty.")

    # Guard: catch bulk-destructive instructions that the agent cannot safely execute.
    # The agent only creates/edits/renames — it never mass-deletes nodes or files.
    _DESTRUCTIVE_PATTERNS = [
        r"\b(delete|remove|clear|erase|wipe|destroy)\b.{0,40}\b(all|every|entire|everything|all nodes?|all concepts?|all files?|graph)\b",
        r"\b(all|every|entire|everything)\b.{0,30}\b(delete|remove|clear|erase|wipe|destroy)\b",
    ]
    _instr_lower = instruction.strip().lower()
    if any(re.search(p, _instr_lower) for p in _DESTRUCTIVE_PATTERNS):
        return {
            "answer": (
                "Bulk deletion is not supported — the agent only creates, edits, and renames articles. "
                "To remove a concept, open the file in the editor and delete it manually from the file tree. "
                "This keeps destructive changes under your direct control rather than automated."
            ),
            "sources": [],
        }

    # Resolve relative file_path to absolute using the vault root.
    # The frontend sends paths like "wiki-vault/concepts/foo.md" (relative to vault root).
    # Path(relative).read_text() fails unless CWD happens to be the vault root, so we
    # anchor it against the parent of wiki_vault_path (which IS the vault root).
    if file_path and not Path(file_path).is_absolute():
        vault_root = Path(config.wiki_vault_path).parent
        resolved = vault_root / file_path
        if resolved.exists():
            file_path = str(resolved)
            logger.debug("Resolved relative file_path → %s", file_path)
        else:
            # Try interpreting the path as relative to wiki_vault_path itself
            resolved_alt = Path(config.wiki_vault_path) / Path(file_path).name
            if resolved_alt.exists():
                file_path = str(resolved_alt)
                logger.debug("Resolved file_path (alt) → %s", file_path)
            else:
                logger.warning(
                    "Could not resolve %r to an existing file (vault_root=%s) — "
                    "file reads will be skipped",
                    file_path,
                    vault_root,
                )
                file_path = None

    op_type = await _classify(instruction, config)
    logger.info("Agent instruction %r classified as: %s", instruction[:50], op_type)

    if op_type == "search":
        return await _search(instruction, file_path, config)

    if op_type == "graph_settings":
        return await _graph_settings(instruction, config)

    if op_type == "create_concept":
        return await _create_concept(instruction, graph_neighbors, config)

    if op_type == "restructure":
        return await _restructure(instruction, config)

    if op_type == "multi_edit":
        return await _multi_edit(instruction, config)

    if not file_path:
        # No file open — fall back to creating a new concept
        logger.info("No active file — falling back to create_concept")
        return await _create_concept(instruction, graph_neighbors, config)

    # edit_file and change_links share the same handler
    return await _edit_file(instruction, file_path, graph_neighbors, config, op_type=op_type)


async def get_agent_history(limit: int = 5) -> list[dict]:
    """Return the most recent agent-created proposals."""
    try:
        from db.database import get_connection
        rows = get_connection().execute(
            """SELECT p.batch_id, p.summary, p.status, p.created_at,
                      COUNT(pa.id) as article_count
               FROM proposals p
               LEFT JOIN proposal_articles pa ON pa.batch_id = p.batch_id
               WHERE p.source = 'agent'
               GROUP BY p.batch_id
               ORDER BY p.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("Could not fetch agent history: %s", exc)
        return []
