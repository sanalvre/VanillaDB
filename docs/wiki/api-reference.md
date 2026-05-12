# FastAPI Sidecar API Reference

Base URL: `http://localhost:{PORT}` (port is ephemeral, read from sidecar stdout on launch)

## System

### GET /health
Returns sidecar health status.
```json
Response: { "status": "ok" }
```

### GET /status
Returns agent pipeline status and pending proposal count.
```json
Response: {
  "agent_status": "idle" | "running" | "error",
  "current_phase": "ingest" | "analysis" | "proposal" | "fileback" | null,
  "last_run": {
    "id": "run_abc123",
    "completed_at": 1713024000,
    "tokens_used": 12340,
    "warnings": [{ "code": "rag_degraded", "detail": "..." }]
  } | null,
  "pending_proposals": 3,
  "last_run_warnings": [{ "code": "rag_degraded" | "missing_ontology" | "missing_agents_md" | "skipped_file", "detail": "..." }]
}
```

### GET /system/capabilities
Returns hardware detection results.
```json
Response: {
  "gpu": true | false,
  "gpu_type": "cuda" | "mps" | "none",
  "python_version": "3.10.0"
}
```

## Vault

### GET /vault/structure
Returns current vault paths and initialization state.
```json
Response: {
  "initialized": true | false,
  "clean_vault_path": "/path/to/clean-vault" | null,
  "wiki_vault_path": "/path/to/wiki-vault" | null
}
```

### POST /vault/create
Creates vault directory structure.
```json
Request: {
  "base_path": "/path/to/vanilla/root",
  "ontology_content": "...",
  "agents_content": "..."
}
Response: { "success": true, "clean_vault_path": "...", "wiki_vault_path": "..." }
```

## Ingestion

### POST /ingest/file
Start ingestion of a local file (drag-and-drop or file picker). Requires vault to be initialized.
```
Query params: file_path (absolute path to file on disk)
Response: { "job_id": "ingest_abc123" }
Errors: 400 if vault not initialized or unsupported file type
```

### POST /ingest/url
Ingest a URL (online-only). Requires vault to be initialized.
```json
Request: { "url": "https://example.com/article" }
Response: { "job_id": "ingest_abc123" }
Errors: 400 if vault not initialized
```

### GET /ingest/status/{job_id}
Poll ingestion job status.
```json
Response: {
  "job_id": "ingest_abc123",
  "status": "pending" | "processing" | "complete" | "error",
  "progress": 0.75,
  "output_path": "clean-vault/raw/article.md" | null,
  "error": "..." | null,
  "source_type": "pdf" | "md" | "url"
}
Errors: 404 if job not found
```

### GET /ingest/active
List all active (pending/processing) ingest jobs.
```json
Response: {
  "jobs": [
    { "job_id": "...", "status": "processing", "progress": 0.5, "source_type": "pdf" }
  ]
}
```

## Proposals

### GET /proposals
List all proposal batches.
```json
Response: {
  "batches": [
    {
      "batch_id": "batch_001",
      "summary": "3 new concept articles about...",
      "status": "pending",
      "articles": [
        { "filename": "article_a.md", "title": "...", "action": "create", "status": "pending" }
      ],
      "created_at": 1713024000
    }
  ]
}
```

### POST /proposals/{batch_id}/approve
Approve a batch (optionally partial).
```json
Request: { "article_ids": ["article_a.md"] }  // optional; omit for approve-all
Response: { "success": true, "articles_written": 3 }
```

### POST /proposals/{batch_id}/reject
Reject an entire batch.
```json
Response: { "success": true }
```

## LLM

### POST /llm/validate
Validate an LLM API key/connection.
```json
Request: {
  "provider": "openai" | "anthropic" | "openrouter" | "ollama",
  "api_key": "sk-...",
  "base_url": "http://localhost:11434"  // for Ollama
}
Response: { "valid": true, "error": null }
```

## Onboarding

### POST /onboarding/generate-ontology
Generate ontology and AGENTS.md from user description.
```json
Request: {
  "description": "I'm a PhD student researching climate policy",
  "provider": "openai",
  "model": "gpt-4o",
  "api_key": "sk-..."
}
Response: {
  "ontology_md": "...",
  "agents_md": "...",
  "suggested_categories": ["Policy Frameworks", "Climate Models", "Key Actors"]
}
```

## Search

### GET /search
Full-text search across vaults.
```
Query params: q (string), vault (all|clean|wiki), limit (int, default 20)
Response: {
  "results": [
    {
      "path": "clean-vault/raw/paper.md",
      "vault": "clean",
      "title": "Climate Policy Overview",
      "snippet": "...matching text excerpt...",
      "score": 0.95
    }
  ]
}
```

## Agent Control

### POST /agent/run-now
Force-trigger agent pipeline (bypasses 5-min debounce). Processes changed files only.
```json
Response: { "run_id": "run_abc123" }
```

### GET /runs
Paginated agent run history.
```json
Query params: limit (int), offset (int)
Response: {
  "runs": [
    {
      "run_id": "run_abc123",
      "trigger_path": "clean-vault/raw/paper.md",
      "status": "complete",
      "started_at": 1713024000,
      "completed_at": 1713024060,
      "tokens_used": 12340
    }
  ]
}
```

## Internal (called by Tauri, not user-facing)

### POST /internal/file-event
Receives file system events from Tauri watcher bridge.
```json
Request: {
  "path": "clean-vault/raw/paper.md",
  "event_type": "create" | "modify" | "delete",
  "timestamp": 1713024000
}
Response: { "queued": true }
```
