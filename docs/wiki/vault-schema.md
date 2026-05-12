# Vault Schema

## Directory Structure

```
~/Vanilla/
  clean-vault/                # Human-owned vault
    raw/                      # Ingested files (PDFs->md, URLs->md)
    notes/                    # User's own markdown notes
    ...                       # User can organize freely

  wiki-vault/                 # Agent-owned vault (human reads only)
    concepts/                 # Approved concept articles
    index.md                  # Auto-maintained master index
    index.md                  # Auto-maintained master concept index
    AGENTS.md                 # Constitution: schema, rules, ontology reference
    ontology.md               # User's domain ontology (from onboarding)
    staging/                  # Proposed articles awaiting approval
      .meta/                  # Temporary ingest/analysis metadata
      batch_001/
        proposal.md           # Human-readable batch summary
        article_a.md          # Draft concept article
        article_b.md
```

## Article Frontmatter Schema

Every wiki article in `concepts/` must have this YAML frontmatter:

```yaml
---
title: Concept Name
sources:
  - clean-vault/raw/paper_a.md
  - clean-vault/notes/meeting_notes.md
created: 2026-04-13
last_updated: 2026-04-13
status: approved          # proposed | approved | rejected | stale
confidence: high          # high | medium | low
---
```

## Knowledge Graph Schema

The knowledge graph is stored in SQLite (not on disk as a JSON file). Three tables:

**`graph_nodes`** — one row per concept article:
```
id TEXT PRIMARY KEY       -- slug (e.g. "transformer-architecture")
label TEXT                -- display name
path TEXT                 -- vault-relative path to article
category TEXT             -- ontology category
last_batch TEXT           -- batch_id that last wrote this node
```

**`graph_edges`** — typed relationships between concepts:
```
source TEXT               -- source node id
target TEXT               -- target node id
type TEXT                 -- wikilink | uses | is-a | derived-from | extends | contrasts-with | implements | part-of | related-to
UNIQUE(source, target, type)
```

**`graph_source_map`** — which articles cite which source files (used for stale detection):
```
source_path TEXT          -- clean-vault relative path
article_path TEXT         -- wiki-vault relative path
```

The graph is queried via REST endpoints (`GET /wiki/graph/concepts`, `/wiki/graph/concepts/{id}/neighbors`) and exposed as MCP tools.

## Path Normalization Rules

All paths stored in frontmatter and SQLite use forward slashes regardless of OS:
- Windows: `C:\Users\User\Vanilla\clean-vault\raw\paper.md` -> stored as `clean-vault/raw/paper.md`
- macOS: `/Users/user/Vanilla/clean-vault/raw/paper.md` -> stored as `clean-vault/raw/paper.md`

Paths are always **relative to the Vanilla root directory** (the parent of both vaults).
