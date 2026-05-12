# Vanilla Architecture

## Overview

Vanilla is a desktop application (Tauri v2) that serves as an agent-native knowledge base. A background AI agent reads the user's files and builds a structured wiki — the human approves or rejects all changes.

## System Diagram

```
+----------------------------------------------+
|               Tauri v2 Shell (Rust)           |
|  - File watching (notify plugin)             |
|  - Native OS integration                     |
|  - Sidecar process management                |
+----------------------------------------------+
          |                          |
          v                          v
+-------------------+   +-------------------------+
| React Frontend    |   | Python Sidecar (FastAPI) |
| - Vite + TS       |   | - CrewAI agent pipeline  |
| - Tailwind CSS    |   | - SQLite (WAL mode)      |
| - Zustand stores  |   | - Ingestion services     |
| - Milkdown editor |   | - Vault management       |
| - Reagraph graph  |   | - PyInstaller binary     |
| - cmdk palette    |   +-------------------------+
+-------------------+
          |                          |
          +--- HTTP (localhost) -----+
```

## Communication Flow

1. **Frontend <-> Sidecar**: All communication over HTTP on localhost (ephemeral port)
2. **Tauri <-> Frontend**: Tauri events (e.g., `vault:file-changed`) emitted to React
3. **Frontend -> Sidecar**: React forwards Tauri file events to FastAPI via POST
4. **Sidecar -> Disk**: Python reads/writes vault files and SQLite database

## Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| FastAPI sidecar over Tauri Python plugin | `tauri-plugin-python` is immature; sidecar pattern is proven |
| SQLite owned by Python only | Avoids dual-access locking; frontend gets data via HTTP API |
| PyInstaller binary | CrewAI is Python-only; sidecar compiled to standalone binary |
| WAL mode for SQLite | Allows concurrent reads from async tasks while serializing writes |
| Path normalization everywhere | macOS uses `/`, Windows uses `\`; all stored paths use `/` |

## Directory Ownership

```
clean-vault/   -> Human writes, Agent reads (NEVER writes)
wiki-vault/    -> Agent writes (with approval), Human reads (NEVER writes directly)
  staging/     -> Agents 1-3 write here (proposals)
  concepts/    -> Agent 4 (File-back) writes here ONLY after human approval
```

## Process Lifecycle

1. Tauri launches → spawns Python sidecar as child process
2. Sidecar binds to ephemeral localhost port, prints port to stdout
3. Tauri reads port, stores in app state, frontend builds base URL
4. If sidecar crashes → UI stays up, shows error, attempts restart
5. On app quit → Tauri sends SIGTERM to sidecar
