# Testing Strategy

## Philosophy

Tests are added where a senior engineer would insist on them — data integrity, API contracts, and business logic. We don't test pure styling or static config.

## Test Pyramid

```
         /  E2E Tests  \           <- Deferred until Phase 6+
        / Integration    \         <- FastAPI TestClient, full pipelines
       / Unit Tests        \       <- Python + TypeScript, core logic
      +---------------------+
```

## Python Unit Tests (`tests/python/`)

Run with: `cd sidecar && python -m pytest ../tests/python/ -v`

| Test file | What it covers |
|-----------|---------------|
| `test_paths.py` | Path normalization (Windows backslash -> forward slash, relative path extraction) |
| `test_vault_manager.py` | Vault creation, directory structure validation, template file generation |
| `test_repository.py` | SQLite CRUD for all tables (proposals, agent_runs, stale_articles, FTS) |
| `test_graph_service.py` | SQLite graph CRUD, source_map lookups, graph.json migration, stale detection |
| `test_watcher_bridge.py` | Async event debounce, force dispatch, sync-write skip, pending path tracking |
| `test_normalizer.py` | Source type detection, slugify, title extraction, MD/PDF/URL ingestion routing |
| `test_job_queue.py` | Job lifecycle, status updates, active filtering, cleanup, unique IDs |
| `test_gpu_detect.py` | CUDA/MPS detection mocks, caching, torch-not-installed fallback |
| `test_setup_crew.py` | Setup crew JSON response parsing, code fence handling, validation |
| `test_pipeline.py` | Pipeline JSON parsing, slugify, token estimation, fileback frontmatter/wikilink extraction, index updates |

## Python Integration Tests (`tests/python/integration/`)

Run with: `cd sidecar && python -m pytest ../tests/python/integration/ -v`

| Test file | What it covers |
|-----------|---------------|
| `test_api.py` | All FastAPI endpoints via TestClient — system, vault, ingestion, proposals, search, runs (31 tests) |

## TypeScript Tests (`tests/ts/`)

Run with: `npx vitest run`

| Test file | What it covers |
|-----------|---------------|
| `paths.test.ts` | TypeScript path normalization matching Python behavior |
| `editorStore.test.ts` | Editor store reset(), split percent clamping |
| `statusStore.test.ts` | Status store warning field population |
| `graphStore.test.ts` | Graph store fetchGraph() API call and state update |
| `fileWatcher.test.ts` | Watcher suppression path API |

## E2E Tests (`tests/e2e/`)

Deferred until Phase 6+ when UI components are in place. Will use Tauri + WebDriver.

## When to Add Tests (Decision Guide)

- **Always test:** Data persistence (SQLite), file system operations (vault creation), API contracts, path handling
- **Always test:** State machines (proposal status transitions), business rules (debounce logic)
- **Skip testing:** React component rendering (visual), Tailwind classes, static config files, Tauri manifest
- **Integration test when:** Multiple systems interact (watcher -> queue -> agent), API endpoints need contract verification

## Test Logging

All test results are logged in BUILDLOG.md with:
- Which tests were added/updated
- What they cover
- Pass/fail status at time of writing
