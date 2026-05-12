# Agent Pipeline

## Overview

The agent pipeline is event-driven, triggered by file system changes detected by Tauri's notify plugin. It uses CrewAI Flows to chain four specialized agents.

## Pipeline Trigger Flow

```
File change in clean-vault/
  -> Tauri notify plugin detects change
  -> Emits vault:file-changed event to React frontend
  -> Frontend POSTs to /internal/file-event
  -> watcher_bridge.py pushes to asyncio Queue
  -> 5-minute debounce (per-path, with content hash verification)
  -> VanillaFlow starts (Ingest -> Analysis -> Proposal)
```

## The Four Agents

### 1. Ingest Agent (`agents/ingest.py`)
- **Reads:** New/changed files from clean-vault/
- **Outputs:** Topic tags, 2-3 sentence summary, source path
- **Writes to:** `staging/.meta/{run_id}_ingest.json`
- **Token budget:** 2,000 tokens (configurable)
- **Model tier:** Cheap (gpt-4o-mini / claude-haiku)

### 2. Analysis Agent (`agents/analysis.py`)
- **Reads:** Ingest metadata + existing wiki articles + knowledge graph (SQLite) + AGENTS.md + ontology.md
- **Outputs:** List of `{action: "create"|"update", concept, reason, sources}`
- **Key behavior:** Re-reads AGENTS.md and ontology.md on EVERY run (never cached)
- **Token budget:** 4,000 tokens (configurable)
- **Model tier:** Mid-tier

### 3. Proposal Agent (`agents/proposal.py`)
- **Reads:** Analysis output
- **Outputs:** `staging/batch_{NNN}/` directory with proposal.md + draft articles
- **Writes to:** staging/ directory + proposals DB table
- **Token budget:** 6,000 tokens (configurable)
- **Model tier:** Powerful (gpt-4o / claude-sonnet)

### 4. File-back Agent (`agents/fileback.py`)
- **Triggered by:** Human approval only (POST /proposals/{batch_id}/approve)
- **Actions:**
  - Writes approved articles to `wiki-vault/concepts/`
  - Updates `index.md` (alphabetical concept list)
  - Updates knowledge graph in SQLite (nodes, edges, source citations)
  - Cleans up staging batch directory
- **Token budget:** Minimal (mostly file operations, not LLM)
- **Model tier:** Cheap

## CrewAI Flow Definitions

```python
# flows.py (conceptual structure)

class VanillaFlow(Flow):
    """Main pipeline: Ingest -> Analysis -> Proposal"""

    @start()
    def ingest_step(self):
        # Ingest Agent processes changed files

    @listen(ingest_step)
    def analysis_step(self):
        # Analysis Agent compares against existing wiki

    @listen(analysis_step)
    def proposal_step(self):
        # Proposal Agent writes batch to staging/

class FilebackFlow(Flow):
    """Separate flow, triggered only by human approval"""

    @start()
    def execute_writes(self):
        # File-back Agent writes to concepts/
```

## Debounce System

- 5-minute (300s) debounce per file path
- Timer resets on every new change to the same file
- At debounce end: SHA-256 content hash compared to hash at debounce start
  - If hash matches: file was stable, trigger pipeline
  - If hash differs: someone wrote again during debounce, reset timer
- "Run agent now" command bypasses debounce for all queued files

## Stale Article Detection

When a clean-vault file changes:
1. Look up source citations in SQLite (`graph_source_map`) for all wiki articles citing it
2. Set `status: stale` in each article's frontmatter
3. Insert rows into `stale_articles` SQLite table
4. Stale articles are included in the next Analysis Agent run
5. Agent proposes updates; human approves; stale status clears

## Token Budgeting

- Each agent has a configurable max token budget
- Default total per run: ~12,000 tokens (2k + 4k + 6k)
- Configurable `MAX_TOKENS_PER_RUN` (default 20,000) acts as a safety valve
- Token usage tracked via LiteLLM callback, written to `agent_runs` table
- Different agents can use different LLM providers/models
