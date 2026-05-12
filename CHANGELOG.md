# Changelog

All notable changes to VanillaDB are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **Agent Panel** — natural-language instructions for bulk edits, concept creation, graph configuration, and search
- **Multi-edit operation** — agent edits multiple files in a single approved batch
- **Graph settings via NL** — color mode, clustering, particles, edge labels configurable by instruction
- **Voice transcription** — browser MediaRecorder → OpenAI Whisper server-side (Web Speech API fallback)
- **Browser research panel** — cascading scraper (Playwright → Crawl4AI → Jina) with bot-gate detection
- **SSE pipeline streaming** — real-time progress overlay during agent runs
- **Hash-based incremental compilation** — skip unchanged source files across sessions
- **Pipeline run audit** — per-agent timing and token tracking
- **Review agent** — inter-agent feedback loop with issue chips in proposal preview
- **MCP server** — Claude Desktop and MCP-compatible agent support with schema sanitization
- **Code execution sandbox** — safe Python execution in analysis steps

### Fixed
- Node-click bug: CodeMirror stale closure caused all graph nodes to show identical content
- URL ingestion: JS-disabled / Cloudflare-walled pages now fail gracefully instead of creating garbage articles

## [0.1.0] — 2026-01-01

Initial public release.

### Added
- Two-vault architecture (clean-vault + wiki-vault)
- Four-agent pipeline: ingest → analysis → proposal → fileback
- Knowledge graph with hybrid BM25 + semantic search
- Wikilink-based graph edges with typed relationships
- Proposal review UI (approve / reject)
- LLM provider support: OpenAI, Anthropic, OpenRouter, Ollama
- MCP server for Claude Desktop integration
- Tauri desktop app (Windows, macOS, Linux)
