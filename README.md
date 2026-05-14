# <img src="public/favicon.svg" width="32" height="32" alt="" valign="middle"> VanillaGraph
*Changed name to VanillaGraph on 5-13-26
A local knowledge base where AI agents do the filing.

Drop in documents or have agents search the web. Agents will read them, extract concepts, and propose structured wiki articles. After your approval, you have a full knowledge graph with markdown file nodes and a source of truth wiki. Inspired by Andrej Karpathy.

Over time, this knowledge base grows into a dynamic knowledge graph with agentic navigation tooling built in.

---

## How it works

```
You drop a file into clean-vault/
        ↓
Watcher detects the change (5-minute debounce)
        ↓
Ingest agent   — reads the file, extracts topics and a summary
Analysis agent — reads your existing wiki + graph, decides what to create or update
Proposal agent — drafts articles and writes them to a staging queue
        ↓
You review proposals and approve or reject each batch (one click)
        ↓
File-back agent — writes approved articles to wiki-vault/concepts/
                — updates the knowledge graph (nodes, edges, citations)
                — generates embeddings for future retrieval
                — updates the concept index
        ↓
Next run has richer context. The graph compounds.
```

---

## Architecture

```
┌──────────────────────────────────────┐
│  Tauri Desktop Shell (Rust)          │
│  ┌────────────────┐                  │
│  │  React + Vite  │  ← UI           │
│  └────────────────┘                  │
│          ↕ localhost HTTP            │
│  ┌──────────────────────────────┐   │
│  │  Python Sidecar (FastAPI)    │   │
│  │  • Agent pipeline (CrewAI)   │   │
│  │  • SQLite + FTS5 + vectors   │   │
│  │  • Hybrid search (BM25+ANN)  │   │
│  │  • Git sync                  │   │
│  └──────────────────────────────┘   │
└──────────────────────────────────────┘
```

The Python sidecar binds to a random localhost port and is the sole owner of SQLite. The Tauri shell reads the port on startup and configures the React frontend to talk to it. Nothing leaves your machine unless you configure a git remote.

---

## Vault structure

```
your-vault/
├── clean-vault/           # Your source documents (read-only for agents)
│   ├── raw/               # PDFs converted to markdown, scraped URLs
│   └── notes/             # Your own writing
└── wiki-vault/            # Agent-maintained knowledge base
    ├── concepts/          # One article per concept, approved by you
    │   └── transformer-architecture.md
    ├── staging/           # Pending proposals, waiting for your review
    ├── ontology.md        # Your domain schema — agents read this every run
    └── AGENTS.md          # Agent constitution — rules, article format, schema
```

The clean vault is yours. The wiki vault is maintained by agents.

---

## Article format

Every wiki article is a plain markdown file with YAML frontmatter:

```markdown
---
title: Transformer Architecture
category: model
sources:
  - clean-vault/raw/attention-is-all-you-need.md
relationships:
  - target: Self-Attention
    type: uses
  - target: BERT
    type: derived-from
created_by: vanilla-agent
status: approved
confidence: high
---

The Transformer is a sequence-to-sequence model that replaces recurrence
with [[Self-Attention]], enabling parallelization across positions...

## See also
- [[BERT]]
- [[Large Language Models]]
```

`[[wikilinks]]` automatically become graph edges. Typed relationships (`uses`, `is-a`, `derived-from`, `extends`, `contrasts-with`, `implements`, `part-of`) carry semantic meaning during traversal. Articles are plain `.md` files — diffable, versionable, and openable in any editor.

---

## Knowledge graph

The graph is the index agents use to navigate your knowledge base:

- **Hub detection** — concepts with many connections get larger context windows in future agent runs
- **Multi-hop traversal** — when analyzing a new document, agents pull in graph neighbors alongside vector-similar articles, catching relationships embeddings miss
- **Stale tracking** — when a source document changes, the graph knows which articles cited it and flags them for review
- **Degree-weighted search** — central concepts rank higher in retrieval, matching how importance actually distributes in a domain

---

## Quick start

### Prerequisites

- Node.js 20+
- Python 3.10+
- Rust — [rustup.rs](https://rustup.rs)
- An API key: OpenAI, Anthropic, OpenRouter, or a local Ollama instance
- *(Optional)* [Firecrawl API key](https://firecrawl.dev) — higher-quality web scraping for paywalled or complex sites
- *(Optional)* Playwright for local JS rendering: `playwright install chromium`

### Install

```bash
git clone https://github.com/sanalvre/VanillaDB
cd VanillaDB

# Frontend dependencies
npm install

# Python sidecar
cd sidecar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[agents,ingestion]"
cd ..
```

### Build the sidecar binary

```bash
cd sidecar
pyinstaller vanilla-sidecar.spec
cd ..

# Copy to Tauri's expected location
# Windows:
copy sidecar\dist\vanilla-sidecar.exe src-tauri\binaries\vanilla-sidecar-x86_64-pc-windows-msvc.exe
# macOS:
cp sidecar/dist/vanilla-sidecar src-tauri/binaries/vanilla-sidecar-x86_64-apple-darwin
```

### Run in development

```bash
npm run tauri dev
```

### Build installer

```bash
npm run tauri build
# Windows: src-tauri/target/release/bundle/nsis/VanillaDB_0.1.0_x64-setup.exe
# macOS:   src-tauri/target/release/bundle/dmg/VanillaDB_0.1.0_x64.dmg
```

---

## LLM configuration

Config lives in `~/.vanilla/config.json`, created on first run via the in-app settings panel.

| Provider | Notes |
|----------|-------|
| OpenAI | `gpt-4o-mini` for ingest/analysis, `gpt-4o` for proposals |
| Anthropic | Claude Haiku for ingest, Claude Opus for proposals |
| OpenRouter | Any model via a single unified API |
| Ollama | Fully local — set base URL to `http://localhost:11434` |

**Embedding models**

| Model | Dims | Notes |
|-------|------|-------|
| `text-embedding-3-small` | 1536 | OpenAI — recommended |
| `nomic-embed-text` | 768 | Ollama — free, local |
| `mxbai-embed-large` | 1024 | Ollama — higher quality |

---

## Agent API

The sidecar exposes a REST API on a dynamic local port, printed to stdout on startup as `VANILLA_PORT:<n>`. Other agents and tools can query your knowledge base directly.

### Context retrieval

```http
GET /context?q=transformer+attention&k=5
```

Returns formatted context ready to inject into a prompt — full article content, ranked by hybrid BM25 + semantic similarity with Reciprocal Rank Fusion.

```json
{
  "context": "## Transformer Architecture\n...\n\n---\n\n## Self-Attention\n...",
  "sources": [
    {"path": "wiki-vault/concepts/transformer-architecture.md", "score": 0.91}
  ]
}
```

### Knowledge graph traversal

```http
GET /wiki/graph/concepts                            # All concepts
GET /wiki/graph/concepts/{id}                       # Concept + article + relationships
GET /wiki/graph/concepts/{id}/neighbors?depth=1     # Graph neighbors
GET /wiki/graph/concepts/{id}/neighbors?type=uses   # Filter by relationship type
```

### Ingest

```http
POST /ingest/file   {"file_path": "/absolute/path/to/doc.pdf"}
POST /ingest/url    {"url": "https://example.com/paper"}
GET  /ingest/status/{job_id}
```

---

## MCP integration

Vanilla ships an MCP server so Claude Desktop (and any MCP-compatible agent) can use your knowledge base as a native tool.

```bash
pip install fastmcp
VANILLA_URL=http://127.0.0.1:PORT python sidecar/mcp_server.py
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "vanilla": {
      "command": "python",
      "args": ["/path/to/vanilla/sidecar/mcp_server.py"],
      "env": { "VANILLA_URL": "http://127.0.0.1:YOUR_PORT" }
    }
  }
}
```

**Tools exposed:**

| Tool | What it does |
|------|-------------|
| `search_knowledge(query, k)` | Hybrid semantic + keyword search across the wiki |
| `get_context(query, k)` | RAG retrieval formatted for direct prompt injection |
| `get_related_concepts(concept, type)` | Traverse the knowledge graph from a concept |
| `list_concepts(category)` | Browse all concepts, optionally filtered by category |

---

## Security

**Network exposure:** The sidecar binds exclusively to `127.0.0.1` (loopback). It is never reachable from other machines on your network. The CORS policy uses `allow_origins=["*"]` because Tauri's WebView2 renderer presents requests from a non-predictable `tauri://localhost` scheme; restricting by origin would break the frontend without adding meaningful security since the port is localhost-only.

**Code execution sandbox:** VanillaDB can execute Python code snippets found in your ingested documents (e.g., for analysis steps). This runs in a restricted subprocess with a timeout and a blocked-import list (`os`, `subprocess`, `socket`, etc.). It is **not** a full security sandbox — treat it as a convenience for trusted personal documents. Disable it in `~/.vanilla/agents.toml` if you ingest untrusted content.

**API keys:** Keys are stored in `~/.vanilla/config.json` (user-only permissions on macOS/Linux; `%APPDATA%\vanilla\config.json` on Windows). They are never logged or transmitted except to the configured LLM provider endpoint.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, architecture notes, and contribution guidelines.

## License

MIT
