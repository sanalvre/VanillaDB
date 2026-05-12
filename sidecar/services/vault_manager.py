"""
Vault directory creation and validation.

Creates and validates the two-vault structure (clean-vault + wiki-vault).
Repairs corrupted structural files (AGENTS.md, ontology.md, index.md) by
detecting article content written into them, backing up, and restoring defaults.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional, List

from services.paths import normalize_path

logger = logging.getLogger("vanilla.vault_manager")


# Default template for AGENTS.md — the agent constitution
DEFAULT_AGENTS_MD = """# AGENTS.md — Vanilla Wiki Constitution

This file defines how the AI agent should behave when processing the clean vault
and generating wiki content. The agent re-reads this file on every run.

## Directory Schema

- `concepts/` — Approved concept articles (one per concept)
- `staging/` — Proposed articles awaiting human approval
- `index.md` — Auto-maintained alphabetical index of all concepts
- Knowledge graph stored in SQLite (graph_nodes, graph_edges, graph_source_map tables)

## Rules

1. Never write to the clean vault. It is read-only for agents.
2. Always write proposals to `staging/batch_NNN/` before they can be approved.
3. Every article must have YAML frontmatter with: title, sources, created, last_updated, status, confidence.
4. Sources must reference actual files in the clean vault using relative paths.
5. Use `[[wikilinks]]` to link between concept articles.
6. Group related concepts into a single batch when they come from the same source.
7. When updating an existing article, explain what changed and why in the proposal.

## Traceability Format

```yaml
---
title: Concept Name
sources:
  - clean-vault/raw/source_file.md
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
status: proposed | approved | rejected | stale
confidence: high | medium | low
---
```

## Ontology Reference

See `ontology.md` for the domain-specific ontology that shapes how concepts are categorized.
"""

DEFAULT_ONTOLOGY_MD = """# Ontology

This file defines the domain ontology for the wiki. It is generated during onboarding
and can be edited at any time. The agent reads this on every run.

## Concept Categories

(Generated during onboarding based on your vault description)

## Relationship Types

- **references** — One concept references another
- **extends** — One concept builds on another
- **contradicts** — Two concepts are in tension
- **exemplifies** — One concept is an example of another
"""

DEFAULT_INDEX_MD = """# Wiki Index

*Auto-maintained by the File-back Agent. Do not edit manually.*

## Concepts

(No concepts yet. Approve proposals to populate this index.)
"""

# Initial empty graph — written to wiki-vault/graph.json on vault creation.
# The graph_service exports an updated copy here after every pipeline run so
# the frontend force-graph can load it without hitting the SQLite API.
DEFAULT_GRAPH_JSON = '{"nodes":[],"edges":[],"source_map":{}}'

def create_vault_structure(
    base_path: str,
    ontology_content: Optional[str] = None,
    agents_content: Optional[str] = None,
) -> dict:
    """
    Create the full two-vault directory structure.

    Args:
        base_path: Parent directory for both vaults (e.g., ~/Vanilla/)
        ontology_content: Custom ontology.md content (or use default)
        agents_content: Custom AGENTS.md content (or use default)

    Returns:
        dict with clean_vault_path and wiki_vault_path
    """
    base = Path(base_path)

    # Clean vault directories
    clean_vault = base / "clean-vault"
    (clean_vault / "raw").mkdir(parents=True, exist_ok=True)
    (clean_vault / "notes").mkdir(parents=True, exist_ok=True)

    # Wiki vault directories
    wiki_vault = base / "wiki-vault"
    (wiki_vault / "concepts").mkdir(parents=True, exist_ok=True)
    (wiki_vault / "staging").mkdir(parents=True, exist_ok=True)
    (wiki_vault / "staging" / ".meta").mkdir(parents=True, exist_ok=True)

    # Write wiki vault files (only if they don't already exist)
    _write_if_missing(wiki_vault / "AGENTS.md", agents_content or DEFAULT_AGENTS_MD)
    _write_if_missing(wiki_vault / "ontology.md", ontology_content or DEFAULT_ONTOLOGY_MD)
    _write_if_missing(wiki_vault / "index.md", DEFAULT_INDEX_MD)
    _write_if_missing(wiki_vault / "graph.json", DEFAULT_GRAPH_JSON)

    return {
        "clean_vault_path": normalize_path(str(clean_vault)),
        "wiki_vault_path": normalize_path(str(wiki_vault)),
    }


def validate_vault_structure(base_path: str) -> List[str]:
    """
    Validate that the vault structure is intact.

    Returns a list of warnings (empty list = all good).
    Never auto-repairs — only reports issues.
    """
    warnings = []
    base = Path(base_path)

    # Check clean vault
    clean_vault = base / "clean-vault"
    if not clean_vault.exists():
        warnings.append("clean-vault/ directory is missing")
    else:
        if not (clean_vault / "raw").exists():
            warnings.append("clean-vault/raw/ directory is missing")
        if not (clean_vault / "notes").exists():
            warnings.append("clean-vault/notes/ directory is missing")

    # Check wiki vault
    wiki_vault = base / "wiki-vault"
    if not wiki_vault.exists():
        warnings.append("wiki-vault/ directory is missing")
    else:
        for required in ["concepts", "staging", "AGENTS.md", "ontology.md", "index.md", "graph.json"]:
            if not (wiki_vault / required).exists():
                warnings.append(f"wiki-vault/{required} is missing")

    return warnings


def _write_if_missing(path: Path, content: str) -> None:
    """Write content to a file only if it doesn't exist."""
    if not path.exists():
        path.write_text(content, encoding="utf-8")


# Map of structural file name → (default content, corruption signal)
# Corruption signal: a string that appears in article frontmatter but NEVER
# in a healthy structural file (e.g. "status: approved", "category: model").
_STRUCTURAL_FILES: dict[str, tuple[str, str]] = {
    "AGENTS.md":    (DEFAULT_AGENTS_MD,    "status:"),
    "ontology.md":  (DEFAULT_ONTOLOGY_MD,  "status:"),
    "index.md":     (DEFAULT_INDEX_MD,     "created_by:"),
}


def _looks_like_article(content: str, corruption_signal: str) -> bool:
    """Return True if the file contains YAML frontmatter matching the signal.

    Structural files (AGENTS.md, ontology.md, index.md) never contain article
    frontmatter.  If the file starts with ``---`` and the signal appears inside
    the first frontmatter block, we treat the file as corrupted.
    """
    if not content.startswith("---"):
        return False
    # Look for closing --- within the first 60 lines
    lines = content.splitlines()
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            header = "\n".join(lines[1:i])
            return corruption_signal in header
    return False


def repair_structural_files(wiki_vault_path: str) -> list[str]:
    """Detect and repair corrupted structural wiki files.

    For each of AGENTS.md, ontology.md, and index.md:
    - If the file contains article YAML frontmatter (a corruption indicator),
      the corrupted file is moved to ``staging/.meta/`` as a backup and the
      default content is restored.

    Returns a list of repaired file names (empty = nothing was wrong).
    """
    wiki_path = Path(wiki_vault_path)
    backup_dir = wiki_path / "staging" / ".meta"
    backup_dir.mkdir(parents=True, exist_ok=True)

    repaired: list[str] = []

    for filename, (default_content, signal) in _STRUCTURAL_FILES.items():
        file_path = wiki_path / filename
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            continue

        if not _looks_like_article(content, signal):
            continue

        # Back up the corrupted file before overwriting
        ts = int(time.time())
        backup_path = backup_dir / f"corrupted_{filename}_{ts}.md"
        try:
            backup_path.write_text(content, encoding="utf-8")
            logger.warning(
                "Structural file '%s' contained article content — backed up to %s and restored default",
                filename,
                backup_path,
            )
        except OSError as e:
            logger.warning("Could not write backup for %s: %s", filename, e)

        file_path.write_text(default_content, encoding="utf-8")
        repaired.append(filename)

    return repaired
