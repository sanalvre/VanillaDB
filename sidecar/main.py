"""
Vanilla Sidecar — FastAPI application entry point.

This is the Python backend for Vanilla, spawned by Tauri as a sidecar process.
It handles: agent orchestration (CrewAI), SQLite database, ingestion pipeline,
and vault management.

On startup, it binds to an ephemeral port and prints the port number to stdout
so Tauri can read it and configure the frontend's base URL.

All file paths are normalized to forward slashes via services.paths.
"""

import asyncio
import logging
import sys
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import VanillaConfig
from db.database import init_db, get_db_path
from db import repository as repo
from models.responses import (
    HealthResponse,
    StatusResponse,
    VaultCreateRequest,
    VaultCreateResponse,
    FileEventRequest,
    FileTreeNode,
    FileContentResponse,
    FileWriteRequest,
    IngestUrlRequest,
    LastRun,
    LLMValidateRequest,
    LLMValidateResponse,
    OnboardingGenerateRequest,
    OnboardingGenerateResponse,
    ProposalApproveRequest,
    ProposalRejectRequest,
    ProposalActionResponse,
    RunPipelineResponse,
    SyncStatusResponse,
    SyncConfigRequest,
    SyncActionResponse,
)
from services.vault_manager import create_vault_structure, validate_vault_structure, repair_structural_files
from services.graph_service import (
    get_all_nodes,
    get_all_edges,
    get_node,
    get_node_neighbors,
    get_articles_citing,
    get_hub_summary,
    upsert_hub_summary,
    get_source_map,
)
from services.watcher_bridge import WatcherBridge, FileEvent
from services.paths import normalize_path
from services.gpu_detect import detect_gpu
from services.llm_service import validate_connection as llm_validate_connection
from services.git_sync import (
    init_repo as git_init_repo,
    set_remote as git_set_remote,
    get_status as git_get_status,
    push as git_push,
    pull as git_pull,
)
from services.ingestion.job_queue import ingest_queue, JobStatus
from services.ingestion.normalizer import (
    ingest_markdown, ingest_pdf, ingest_url, detect_source_type,
)
from agents.pipeline import run_pipeline, pipeline_status
from agents.fileback import execute_fileback
from routers.events import router as events_router

logger = logging.getLogger("vanilla")


def find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Global config — loaded once at startup, updated via endpoints
config = VanillaConfig.load()

# Watcher bridge — initialized in lifespan
watcher_bridge: Optional[WatcherBridge] = None

# When True, on_file_ready skips pipeline triggering (used during force dispatch)
_suppress_pipeline_trigger = False

# Prevents concurrent pipeline runs triggered by rapid file events
_pipeline_lock = asyncio.Lock()


async def _run_pipeline_locked(paths: list[str], cfg: VanillaConfig) -> None:
    """Run the pipeline under a lock to prevent concurrent runs from simultaneous file events."""
    async with _pipeline_lock:
        # Re-check inside the lock — only one pipeline runs at a time.
        if not pipeline_status.running:
            await run_pipeline(paths, cfg)
        else:
            logger.debug("Pipeline already running, skipping trigger for: %s", paths)


async def on_file_ready(event: FileEvent) -> None:
    """
    Callback fired when a file passes the debounce check.
    Triggers the agent pipeline for changed files; prunes graph nodes for deletions.
    """
    logger.info("File ready for processing: %s (%s)", event.path, event.event_type)

    # Graph pruning: if a wiki-vault/concepts file was deleted externally
    # (e.g. via OS file explorer), remove the matching graph node immediately.
    if event.event_type == "delete" and "wiki-vault/concepts/" in normalize_path(event.path):
        from services import graph_service as _gs
        norm = normalize_path(event.path)
        for node in _gs.get_all_nodes():
            if normalize_path(node.get("path", "")) == norm:
                _gs.remove_node(node["id"])
                logger.info("Pruned graph node for externally deleted file: %s", event.path)
                break

    # Stale article detection: if a clean-vault file changed,
    # find all wiki articles that cite it and flag them as stale.
    if event.event_type != "delete" and event.path.startswith("clean-vault/") and config.wiki_vault_path:
        stale_articles = get_articles_citing(event.path)
        for article_path in stale_articles:
            repo.flag_stale_article(article_path, event.path)
            logger.info("Flagged stale article: %s (source changed: %s)", article_path, event.path)

    # Don't trigger the pipeline for delete events — there's nothing left to ingest.
    if event.event_type == "delete":
        return

    # Trigger the agent pipeline if not already running and not suppressed
    if not _suppress_pipeline_trigger and config.initialized:
        asyncio.create_task(_run_pipeline_locked([event.path], config))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    global watcher_bridge

    # Initialize SQLite database with WAL mode and vector extension
    init_db(get_db_path(config), embedding_dims=config.llm.embedding_dims)

    # One-time migration: import graph.json into SQLite graph tables
    if config.wiki_vault_path:
        repo.graph_migrate_from_json(config.wiki_vault_path)

    # Repair structural files if they were corrupted by article content
    if config.wiki_vault_path:
        repaired = repair_structural_files(config.wiki_vault_path)
        if repaired:
            logger.warning("Repaired corrupted structural files on startup: %s", repaired)

    # Initialize watcher bridge with debounce
    vault_root = ""
    if config.clean_vault_path:
        # Vault root is the parent of clean-vault
        from pathlib import Path
        vault_root = str(Path(config.clean_vault_path).parent)

    watcher_bridge = WatcherBridge(
        debounce_seconds=300,
        on_ready=on_file_ready,
        vault_root=vault_root,
    )
    await watcher_bridge.start()

    yield

    # Shutdown
    if watcher_bridge:
        await watcher_bridge.stop()


app = FastAPI(
    title="Vanilla Sidecar",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — wildcard origin is intentional and safe here.
#
# The sidecar binds exclusively to 127.0.0.1 (loopback), so no external host
# can reach these endpoints.  We can't restrict by origin because Tauri's
# WebView2 renderer uses a non-standard scheme ("tauri://localhost" or
# "http://tauri.localhost") that varies by platform and Tauri version.
# Locking to a specific origin string would break the UI on some platforms
# without providing any meaningful security benefit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events_router)


# ─── System Endpoints ───────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    """Basic health check."""
    return HealthResponse(status="ok")


@app.get("/status", response_model=StatusResponse)
async def status():
    """Agent pipeline status and pending proposal count."""
    pending = repo.count_pending_proposals()
    last = repo.get_last_run()

    last_run = None
    last_run_warnings: list = []
    if last:
        run_warnings = last.get("warnings", [])
        if isinstance(run_warnings, str):
            import json as _json
            try:
                run_warnings = _json.loads(run_warnings)
            except Exception:
                run_warnings = []
        last_run_warnings = run_warnings if isinstance(run_warnings, list) else []
        last_run = LastRun(
            id=last["run_id"],
            completed_at=last.get("completed_at", 0) or 0,
            tokens_used=last.get("tokens_used", 0) or 0,
            warnings=last_run_warnings,
        )

    agent_status = "running" if pipeline_status.running else "idle"

    return StatusResponse(
        agent_status=agent_status,
        current_phase=pipeline_status.current_phase,
        last_run=last_run,
        pending_proposals=pending,
        last_run_warnings=last_run_warnings,
    )


# ─── Vault Endpoints ────────────────────────────────────────────────

@app.get("/vault/structure")
async def vault_structure():
    """Return current vault paths and initialization state."""
    warnings = []
    if config.initialized and config.clean_vault_path:
        from pathlib import Path
        base = str(Path(config.clean_vault_path).parent)
        warnings = validate_vault_structure(base)

    return {
        "initialized": config.initialized,
        "clean_vault_path": config.clean_vault_path,
        "wiki_vault_path": config.wiki_vault_path,
        "warnings": warnings,
    }


@app.post("/vault/create", response_model=VaultCreateResponse)
async def vault_create(request: VaultCreateRequest):
    """Create the two-vault directory structure."""
    global watcher_bridge

    try:
        result = create_vault_structure(
            base_path=request.base_path,
            ontology_content=request.ontology_content,
            agents_content=request.agents_content,
        )

        # Update config
        config.clean_vault_path = result["clean_vault_path"]
        config.wiki_vault_path = result["wiki_vault_path"]
        config.initialized = True
        config.save()

        # Repair structural files in case vault was previously corrupted
        repair_structural_files(result["wiki_vault_path"])

        # Restart watcher bridge with the new vault root
        if watcher_bridge:
            await watcher_bridge.stop()
        watcher_bridge = WatcherBridge(
            debounce_seconds=300,
            on_ready=on_file_ready,
            vault_root=request.base_path,
        )
        await watcher_bridge.start()

        return VaultCreateResponse(
            success=True,
            clean_vault_path=result["clean_vault_path"],
            wiki_vault_path=result["wiki_vault_path"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── System Capabilities ────────────────────────────────────────────

@app.get("/system/capabilities")
async def system_capabilities():
    """Return hardware detection results (GPU, Python version)."""
    import sys as _sys
    gpu = detect_gpu()
    return {
        "gpu": gpu.gpu,
        "gpu_type": gpu.gpu_type,
        "python_version": _sys.version.split()[0],
    }


# ─── Ingestion Endpoints ────────────────────────────────────────────

@app.post("/ingest/file")
async def ingest_file_upload(
    file_path: str,  # Absolute path to the file on disk
):
    """
    Start ingestion of a local file (dropped onto the app or selected via dialog).
    Returns a job ID for status polling.
    """
    if not config.clean_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    source_type = detect_source_type(file_path)
    if source_type == "unknown":
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_path}")

    job = ingest_queue.create_job(
        source_type=source_type,
        source_path=file_path,
    )

    # Run ingestion in background
    asyncio.create_task(_run_ingest_job(job.job_id))

    return {"job_id": job.job_id}


@app.post("/ingest/url")
async def ingest_url_endpoint(request: IngestUrlRequest):
    """
    Start ingestion of a URL. Requires internet access.
    Returns a job ID for status polling.
    """
    if not config.clean_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    job = ingest_queue.create_job(
        source_type="url",
        source_url=request.url,
    )

    asyncio.create_task(_run_ingest_job(job.job_id))

    return {"job_id": job.job_id}


@app.get("/ingest/status/{job_id}")
async def ingest_status(job_id: str):
    """Poll ingestion job status."""
    job = ingest_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dict()


@app.get("/ingest/active")
async def ingest_active():
    """List all active (pending/processing) ingest jobs."""
    return {"jobs": ingest_queue.get_active_jobs()}


async def _run_ingest_job(job_id: str) -> None:
    """Background task that runs an ingestion job."""
    job = ingest_queue.get_job(job_id)
    if not job:
        return

    ingest_queue.update_job(job_id, status=JobStatus.PROCESSING, progress=0.1)

    try:
        if job.source_type == "md" and job.source_path:
            result = await ingest_markdown(job.source_path, config.clean_vault_path)
        elif job.source_type == "pdf" and job.source_path:
            gpu = detect_gpu()
            result = await ingest_pdf(job.source_path, config.clean_vault_path, gpu_available=gpu.gpu)
        elif job.source_type == "url" and job.source_url:
            result = await ingest_url(job.source_url, config.clean_vault_path, firecrawl_api_key=config.llm.api_key)
        else:
            ingest_queue.update_job(job_id, status=JobStatus.ERROR, error="Invalid job configuration")
            return

        if result.success:
            # Update FTS index
            repo.upsert_fts(result.output_path, "clean", result.title, result.body)
            ingest_queue.update_job(
                job_id,
                status=JobStatus.COMPLETE,
                progress=1.0,
                output_path=result.output_path,
            )
            logger.info("Ingest complete: %s -> %s", job.source_path or job.source_url, result.output_path)
        else:
            ingest_queue.update_job(job_id, status=JobStatus.ERROR, error=result.error)
            logger.error("Ingest failed: %s", result.error)

    except Exception as e:
        logger.error("Ingest job error: %s", e)
        ingest_queue.update_job(job_id, status=JobStatus.ERROR, error=str(e))


# ─── File Event Endpoints ───────────────────────────────────────────

@app.post("/internal/file-event")
async def file_event(request: FileEventRequest):
    """
    Receive file system events from Tauri's watcher via the frontend.
    Events are queued and debounced before triggering the agent pipeline.
    """
    if not watcher_bridge:
        raise HTTPException(status_code=503, detail="Watcher bridge not initialized")

    event = FileEvent(
        path=request.path,
        event_type=request.event_type,
        timestamp=request.timestamp,
    )
    queued = await watcher_bridge.push_event(event)

    return {"queued": queued, "pending_count": watcher_bridge.get_pending_count()}


@app.post("/agent/run-now", response_model=RunPipelineResponse)
async def agent_run_now():
    """
    Force-trigger the agent pipeline, bypassing debounce.
    Collects all pending paths from the debounce queue and runs the pipeline.
    """
    if not watcher_bridge:
        raise HTTPException(status_code=503, detail="Watcher bridge not initialized")

    if pipeline_status.running:
        return RunPipelineResponse(already_running=True, dispatched=0)

    if not config.initialized:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    global _suppress_pipeline_trigger

    # Collect pending paths before force-dispatching
    pending_paths = watcher_bridge.get_pending_paths()

    # Suppress individual pipeline triggers during force dispatch —
    # we will run a single consolidated pipeline afterwards.
    _suppress_pipeline_trigger = True
    try:
        count = await watcher_bridge.force_dispatch_all()
    finally:
        _suppress_pipeline_trigger = False

    if pending_paths:
        # Launch consolidated pipeline in background
        asyncio.create_task(run_pipeline(pending_paths, config))
        # Give it a moment to initialise the run_id
        await asyncio.sleep(0.05)
        return RunPipelineResponse(
            run_id=pipeline_status.current_run_id,
            dispatched=len(pending_paths),
        )

    return RunPipelineResponse(dispatched=count)


# ─── Graph Endpoints ────────────────────────────────────────────────

@app.get("/wiki/graph")
async def wiki_graph():
    """Return the current knowledge graph for Reagraph visualization."""
    nodes = get_all_nodes()
    edges = get_all_edges()
    source_map = get_source_map()
    return {"nodes": nodes, "edges": edges, "source_map": source_map}


@app.get("/wiki/graph/clusters")
async def wiki_graph_clusters(
    method: str = "topology",
    recompute: bool = False,
):
    """
    Return cluster assignments for all graph nodes.

    method=topology  — Louvain community detection on wikilink graph
    method=semantic  — K-Means on wiki-node embeddings (requires embedding API)

    Cluster IDs are cached in graph_nodes table. Pass recompute=true to force
    a fresh run (e.g. after approving a proposal that changed the graph).

    Returns 503 with detail message when semantic clustering is requested but
    the provider has no embedding capability and no fallback key is configured.
    """
    from services.clustering_service import (
        compute_topology_clusters,
        compute_semantic_clusters,
        load_node_embeddings,
        generate_cluster_labels,
        EmbeddingNotSupportedError as ClusterEmbedError,
    )
    from services.embedding_service import (
        embed_all_wiki_nodes,
        EmbeddingNotSupportedError as EmbedError,
    )
    import time as _time
    from db.database import get_connection as _get_conn

    conn = _get_conn()
    nodes = get_all_nodes()
    edges = get_all_edges()

    if not nodes:
        return {"method": method, "clusters": [], "assignments": {}, "computed_at": int(_time.time())}

    col = "topology_cluster_id" if method == "topology" else "semantic_cluster_id"

    # Use cached assignments unless recompute requested or column is all-null
    if not recompute:
        sample = conn.execute(
            f"SELECT {col} FROM graph_nodes WHERE {col} IS NOT NULL LIMIT 1"
        ).fetchone()
        if sample is not None:
            # Return cached
            rows = conn.execute(
                f"SELECT id, {col} FROM graph_nodes"
            ).fetchall()
            assignments = {
                r["id"]: r[col]
                for r in rows
                if r[col] is not None
            }
            label_rows = conn.execute(
                "SELECT cluster_id, label, member_count FROM cluster_labels WHERE method = ?",
                (method,),
            ).fetchall()
            clusters = [
                {"cluster_id": r["cluster_id"], "label": r["label"], "member_count": r["member_count"]}
                for r in label_rows
            ]
            return {
                "method": method,
                "clusters": sorted(clusters, key=lambda c: c["cluster_id"]),
                "assignments": assignments,
                "computed_at": int(_time.time()),
            }

    # ── Compute fresh assignments ────────────────────────────────────────────
    if method == "topology":
        assignments = compute_topology_clusters(nodes, edges)

    elif method == "semantic":
        # Ensure wiki node embeddings exist / are fresh
        try:
            await embed_all_wiki_nodes(config, conn)
        except (EmbedError, ClusterEmbedError) as e:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": str(e),
                    "requires_embeddings": True,
                    "provider": config.llm.provider,
                },
            )

        node_ids = [n["id"] for n in nodes]
        valid_ids, vectors = load_node_embeddings(node_ids, conn)

        if not valid_ids:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": (
                        "No embeddings found for wiki nodes. "
                        "Ensure the pipeline has run and your embedding provider is configured."
                    ),
                    "requires_embeddings": True,
                },
            )

        assignments = compute_semantic_clusters(valid_ids, vectors)

        # Nodes without embeddings get singleton cluster beyond the computed range
        max_cid = max(assignments.values(), default=-1)
        for n in nodes:
            if n["id"] not in assignments:
                assignments[n["id"]] = max_cid + 1

    else:
        raise HTTPException(status_code=400, detail=f"Unknown method '{method}'. Use 'topology' or 'semantic'.")

    # ── Persist assignments ──────────────────────────────────────────────────
    for node_id, cid in assignments.items():
        conn.execute(
            f"UPDATE graph_nodes SET {col} = ? WHERE id = ?",
            (cid, node_id),
        )
    conn.commit()

    # ── Generate cluster labels (cheap LLM call) ─────────────────────────────
    from collections import defaultdict
    id_to_label = {n["id"]: n["label"] for n in nodes}
    by_cluster: dict[int, list[str]] = defaultdict(list)
    for nid, cid in assignments.items():
        by_cluster[cid].append(id_to_label.get(nid, nid))

    cluster_input = [
        {"cluster_id": cid, "node_labels": labels[:12]}
        for cid, labels in sorted(by_cluster.items())
    ]

    try:
        label_map = await generate_cluster_labels(cluster_input, config)
    except Exception as e:
        logger.warning("Cluster label generation failed: %s", e)
        label_map = {c["cluster_id"]: f"Cluster {c['cluster_id']}" for c in cluster_input}

    # Persist labels
    now_str = str(int(_time.time()))
    for cid, lbl in label_map.items():
        conn.execute(
            """INSERT OR REPLACE INTO cluster_labels (method, cluster_id, label, member_count, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (method, cid, lbl, len(by_cluster.get(cid, [])), now_str),
        )
    conn.commit()

    clusters = [
        {"cluster_id": cid, "label": label_map.get(cid, f"Cluster {cid}"), "member_count": len(by_cluster[cid])}
        for cid in sorted(by_cluster.keys())
    ]

    return {
        "method": method,
        "clusters": clusters,
        "assignments": assignments,
        "computed_at": int(_time.time()),
    }


@app.post("/wiki/graph/embeddings/refresh")
async def wiki_graph_embeddings_refresh():
    """
    Trigger (re-)generation of wiki node embeddings in the background.

    Returns immediately with {queued: true}. The embeddings are generated
    asynchronously and stored in node_embeddings. Once complete, semantic
    clustering will use the fresh embeddings on the next request.

    Returns 503 if the provider cannot generate embeddings.
    """
    from services.embedding_service import embed_all_wiki_nodes, EmbeddingNotSupportedError

    # Verify capability before queueing
    from services.embedding_service import can_embed
    if not can_embed(config):
        provider = config.llm.provider
        if provider == "anthropic":
            msg = (
                "Claude/Anthropic does not have an embedding API. "
                "Add an OpenAI key in Settings → Voice Transcription Key "
                "to enable semantic clustering."
            )
        else:
            msg = f"No API key configured for embeddings (provider={provider})."
        raise HTTPException(status_code=503, detail={"message": msg, "requires_embeddings": True})

    async def _run():
        try:
            from db.database import get_connection as _gc
            conn = _gc()
            n = await embed_all_wiki_nodes(config, conn)
            logger.info("Background embedding refresh complete: %d nodes", n)
        except Exception as e:
            logger.error("Background embedding refresh failed: %s", e)

    asyncio.create_task(_run())
    return {"queued": True}


@app.get("/wiki/stale")
async def wiki_stale():
    """Return all articles currently flagged as stale."""
    stale = repo.get_stale_articles()
    return {"stale_articles": stale}


# ─── File Endpoints ────────────────────────────────────────────────

def _build_tree(root_path: str, prefix: str) -> FileTreeNode:
    """
    Recursively build a directory tree rooted at root_path.
    prefix is the vault-relative path segment (e.g. "clean-vault").
    Excludes hidden files/dirs and staging/ under wiki-vault.
    """
    from pathlib import Path

    root = Path(root_path)
    children: list[FileTreeNode] = []
    dirs: list[FileTreeNode] = []
    files: list[FileTreeNode] = []

    if root.is_dir():
        for entry in sorted(root.iterdir(), key=lambda e: e.name.lower()):
            # Skip hidden files/dirs
            if entry.name.startswith("."):
                continue
            # Skip staging/ under wiki-vault
            if prefix.startswith("wiki-vault") and entry.name == "staging" and entry.is_dir():
                continue

            rel = f"{prefix}/{entry.name}"
            if entry.is_dir():
                dirs.append(_build_tree(str(entry), rel))
            else:
                files.append(FileTreeNode(
                    name=entry.name,
                    path=normalize_path(rel),
                    type="file",
                    children=[],
                ))

    # Directories first, then files — both alphabetically
    children = dirs + files

    return FileTreeNode(
        name=Path(root_path).name,
        path=normalize_path(prefix),
        type="directory",
        children=children,
    )


@app.get("/vault/files")
async def vault_files():
    """Return the directory tree for both vaults."""
    import hashlib
    import json as _json

    if not config.clean_vault_path or not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    tree = [
        _build_tree(config.clean_vault_path, "clean-vault"),
        _build_tree(config.wiki_vault_path, "wiki-vault"),
    ]
    tree_dicts = [node.model_dump() for node in tree]
    tree_hash = hashlib.md5(
        _json.dumps(tree_dicts, sort_keys=True).encode()
    ).hexdigest()[:8]
    return {"tree": tree, "tree_hash": tree_hash}


@app.get("/vault/file", response_model=FileContentResponse)
async def vault_file_read(path: str):
    """Read file content by vault-relative path."""
    from pathlib import Path

    if ".." in path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    if not path.startswith("clean-vault/") and not path.startswith("wiki-vault/"):
        raise HTTPException(status_code=400, detail="Path must start with clean-vault/ or wiki-vault/")

    if not config.clean_vault_path or not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    # Resolve to absolute path
    if path.startswith("clean-vault/"):
        base = Path(config.clean_vault_path)
        relative = path[len("clean-vault/"):]
    else:
        base = Path(config.wiki_vault_path)
        relative = path[len("wiki-vault/"):]

    file_path = base / relative
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FileContentResponse(path=normalize_path(path), content=content)


@app.post("/vault/file")
async def vault_file_write(request: FileWriteRequest):
    """Write file content. Only clean-vault paths are writable."""
    from pathlib import Path

    if ".." in request.path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    if not request.path.startswith("clean-vault/"):
        raise HTTPException(status_code=400, detail="Only clean-vault/ paths are writable")

    if not config.clean_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    relative = request.path[len("clean-vault/"):]
    file_path = Path(config.clean_vault_path) / relative

    # Ensure parent directories exist
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_path.write_text(request.content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "path": normalize_path(request.path)}


# ─── File CRUD (delete / rename / new / reveal) ─────────────────────

def _resolve_vault_path(path: str) -> "Path":
    """
    Resolve a vault-relative path (clean-vault/... or wiki-vault/...) to absolute.
    Raises HTTPException on traversal or unknown vault prefix.
    """
    from pathlib import Path as _Path
    if ".." in path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not config.clean_vault_path or not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")
    if path.startswith("clean-vault/"):
        return _Path(config.clean_vault_path) / path[len("clean-vault/"):]
    if path.startswith("wiki-vault/"):
        return _Path(config.wiki_vault_path) / path[len("wiki-vault/"):]
    raise HTTPException(status_code=400, detail="Path must start with clean-vault/ or wiki-vault/")


@app.delete("/vault/file")
async def vault_file_delete(path: str):
    """
    Move a file to _trash/ inside its vault root (recoverable).
    For wiki-vault/concepts/ files the matching graph node is also pruned.
    """
    from pathlib import Path
    import time as _time

    abs_path = _resolve_vault_path(path)
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    # Determine vault root (parent of clean-vault or wiki-vault directory)
    if path.startswith("clean-vault/"):
        vault_root = Path(config.clean_vault_path).parent
    else:
        vault_root = Path(config.wiki_vault_path).parent

    trash_dir = vault_root / "_trash"
    trash_dir.mkdir(exist_ok=True)

    # Prefix with timestamp to avoid filename collisions
    stamp = int(_time.time())
    trash_name = f"{stamp}_{abs_path.name}"
    trash_path = trash_dir / trash_name

    try:
        abs_path.rename(trash_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Prune graph node if this was a wiki-vault/concepts/ file
    if path.startswith("wiki-vault/concepts/"):
        from services import graph_service
        norm = normalize_path(path)
        for node in graph_service.get_all_nodes():
            if normalize_path(node.get("path", "")) == norm:
                graph_service.remove_node(node["id"])
                break

    return {"success": True, "trash_path": normalize_path(str(trash_path))}


@app.post("/vault/file/rename")
async def vault_file_rename(request: Request):
    """
    Rename a file within its current directory.
    For wiki-vault/concepts/ files the graph node path and label are updated.
    """
    from pathlib import Path
    body = await request.json()
    path: str = body.get("path", "")
    new_name: str = body.get("new_name", "")

    if not path or not new_name:
        raise HTTPException(status_code=400, detail="path and new_name are required")
    if "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="new_name must be a filename only (no slashes)")
    if ".." in new_name:
        raise HTTPException(status_code=400, detail="Invalid new_name")
    if not new_name.endswith(".md"):
        new_name = new_name + ".md"

    abs_path = _resolve_vault_path(path)
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    new_abs = abs_path.parent / new_name
    if new_abs.exists():
        raise HTTPException(status_code=409, detail=f"A file named '{new_name}' already exists")

    try:
        abs_path.rename(new_abs)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Compute new vault-relative path
    if path.startswith("clean-vault/"):
        prefix = "clean-vault/"
        rel_base = Path(config.clean_vault_path)
    else:
        prefix = "wiki-vault/"
        rel_base = Path(config.wiki_vault_path)

    new_rel = prefix + normalize_path(str(new_abs.relative_to(rel_base)))

    # Update graph node if wiki-vault/concepts/ file
    if path.startswith("wiki-vault/concepts/"):
        from services import graph_service
        from db import repository as _repo
        norm_old = normalize_path(path)
        for node in graph_service.get_all_nodes():
            if normalize_path(node.get("path", "")) == norm_old:
                new_label = Path(new_name).stem.replace("-", " ").replace("_", " ").title()
                _repo.get_connection().execute(
                    "UPDATE graph_nodes SET path = ?, label = ? WHERE id = ?",
                    (new_rel, new_label, node["id"]),
                )
                _repo.get_connection().commit()
                break

    return {"success": True, "new_path": new_rel}


@app.post("/vault/file/new")
async def vault_file_new(request: Request):
    """
    Create a new empty (or templated) file at the given vault-relative path.
    Allowed in both clean-vault/ and wiki-vault/.
    """
    from pathlib import Path
    body = await request.json()
    path: str = body.get("path", "")
    content: str = body.get("content", "")

    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    if ".." in path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not path.startswith("clean-vault/") and not path.startswith("wiki-vault/"):
        raise HTTPException(status_code=400, detail="Path must start with clean-vault/ or wiki-vault/")

    if not config.clean_vault_path or not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    if path.startswith("clean-vault/"):
        abs_path = Path(config.clean_vault_path) / path[len("clean-vault/"):]
    else:
        abs_path = Path(config.wiki_vault_path) / path[len("wiki-vault/"):]

    if abs_path.exists():
        raise HTTPException(status_code=409, detail="File already exists")

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        abs_path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "path": normalize_path(path)}


@app.get("/vault/reveal")
async def vault_file_reveal(path: str):
    """
    Open the system file explorer with the given file selected.
    Windows only: uses 'explorer /select,<path>'.
    """
    import subprocess
    import platform

    abs_path = _resolve_vault_path(path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", str(abs_path)])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(abs_path)])
        else:
            subprocess.Popen(["xdg-open", str(abs_path.parent)])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True}


# ─── Proposal Endpoints ─────────────────────────────────────────────

@app.get("/proposals")
async def list_proposals():
    """List all pending proposal batches."""
    batches = repo.get_pending_proposals()
    return {"batches": batches}


@app.get("/proposals/{batch_id}/article/{filename}")
async def get_proposal_article(batch_id: str, filename: str):
    """Read the raw markdown content of a staged article for preview."""
    if not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Wiki vault not configured")

    from pathlib import Path
    # Sanitize: only allow safe filenames (no path traversal)
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    article_path = Path(config.wiki_vault_path) / "staging" / batch_id / filename
    if not article_path.exists():
        raise HTTPException(status_code=404, detail="Article not found")

    try:
        content = article_path.read_text(encoding="utf-8")
        return {"filename": filename, "content": content}
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/proposals/{batch_id}/article/{filename}")
async def update_proposal_article(batch_id: str, filename: str, request: Request):
    """Overwrite a staged article's content (called from the edit-before-approve UI)."""
    if not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Wiki vault not configured")

    from pathlib import Path
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    article_path = Path(config.wiki_vault_path) / "staging" / batch_id / filename
    if not article_path.exists():
        raise HTTPException(status_code=404, detail="Article not found in staging")

    body = await request.json()
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content must be a string")

    try:
        article_path.write_text(content, encoding="utf-8")
        return {"success": True, "filename": filename}
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/proposals/{batch_id}/approve", response_model=ProposalActionResponse)
async def approve_proposal(batch_id: str):
    """
    Approve a proposal batch — triggers the file-back agent to write
    articles from staging into wiki-vault/concepts/.

    After approval, topology clusters are recomputed in the background since
    new nodes/edges may have changed community structure.
    """
    if not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Wiki vault not configured")

    result = await execute_fileback(batch_id, config)

    # Recompute topology clusters in background (non-blocking)
    async def _recompute_clusters():
        try:
            from services.clustering_service import compute_topology_clusters
            from db.database import get_connection as _gc
            conn = _gc()
            nodes = get_all_nodes()
            edges = get_all_edges()
            if nodes:
                assignments = compute_topology_clusters(nodes, edges)
                for nid, cid in assignments.items():
                    conn.execute(
                        "UPDATE graph_nodes SET topology_cluster_id = ? WHERE id = ?",
                        (cid, nid),
                    )
                conn.commit()
                logger.info("Topology clusters recomputed after approval (%d nodes)", len(nodes))
        except Exception as e:
            logger.warning("Cluster recompute after approval failed: %s", e)

    asyncio.create_task(_recompute_clusters())

    return ProposalActionResponse(
        batch_id=batch_id,
        status="approved",
        articles_written=result["articles_written"],
        errors=result["errors"],
    )


@app.post("/proposals/{batch_id}/reject", response_model=ProposalActionResponse)
async def reject_proposal(batch_id: str, request: ProposalRejectRequest = None):
    """
    Reject a proposal batch — marks it as rejected and optionally records a reason.
    """
    repo.update_proposal_status(batch_id, "rejected")
    logger.info(
        "Proposal %s rejected%s",
        batch_id,
        f": {request.reason}" if request and request.reason else "",
    )
    return ProposalActionResponse(batch_id=batch_id, status="rejected")


# ─── Run History ────────────────────────────────────────────────────

@app.get("/runs")
async def list_runs(limit: int = 20, offset: int = 0):
    """Paginated agent run history."""
    runs = repo.get_runs(limit=limit, offset=offset)
    return {"runs": runs}


# ─── Agent Context & Graph Traversal ────────────────────────────────

@app.get("/context")
async def get_context(q: str, k: int = 5):
    """
    RAG context retrieval for AI agents.

    Returns formatted context from the knowledge base, ready to inject into
    a prompt. Unlike /search (which returns search metadata and snippets),
    /context loads and returns the full article body for each result.

    Agents should prefer this endpoint for prompt augmentation; /search
    is better suited for UI result lists.
    """
    from pathlib import Path

    if not q.strip():
        return {"context": "", "sources": []}

    if not config.wiki_vault_path:
        raise HTTPException(status_code=400, detail="Wiki vault not configured")

    query_emb = None
    try:
        from services.embedding_service import generate_embedding
        query_emb = await generate_embedding(q, config)
    except Exception as e:
        logger.debug("Context query embedding failed, falling back to BM25: %s", e)

    results = repo.hybrid_search(
        query=q,
        query_embedding=query_emb,
        vault="wiki",
        k=k,
    )

    context_blocks: list[str] = []
    sources: list[dict] = []

    for result in results:
        sources.append({
            "path": result["path"],
            "title": result["title"],
            "score": result.get("score", 0),
        })

        # Prefer full article body; fall back to the FTS snippet
        article_file = Path(config.wiki_vault_path) / "concepts" / Path(result["path"]).name
        if article_file.exists():
            raw = article_file.read_text(encoding="utf-8")
            # Strip YAML frontmatter so agents get clean prose
            if raw.startswith("---"):
                end = raw.find("---", 3)
                body = raw[end + 3:].strip() if end != -1 else raw
            else:
                body = raw
            # Truncate long articles to avoid blowing out context windows
            context_blocks.append(f"## {result['title']}\n{body[:3000]}")
        elif result.get("snippet"):
            context_blocks.append(f"## {result['title']}\n{result['snippet']}")

    return {
        "context": "\n\n---\n\n".join(context_blocks),
        "sources": sources,
    }


@app.get("/wiki/graph/concepts")
async def list_graph_concepts(category: str = ""):
    """
    List all concept nodes in the knowledge graph.

    Optionally filter by category (concept, model, method, algorithm, etc.).
    Returns id, label, category, path, and total relationship count for each node.
    """
    nodes = get_all_nodes()

    if category:
        nodes = [n for n in nodes if n.get("category", "").lower() == category.lower()]

    concepts = []
    for node in nodes:
        nid = node["id"]
        rel_count = repo.graph_node_in_degree(nid)
        concepts.append({
            "id": nid,
            "label": node["label"],
            "category": node.get("category", ""),
            "path": node.get("path", ""),
            "relationship_count": rel_count,
        })

    return {"concepts": concepts, "total": len(concepts)}


@app.get("/wiki/graph/concepts/{node_id}")
async def get_graph_concept(node_id: str):
    """
    Get a single concept node with its full article content and relationships.

    Returns the article body (frontmatter stripped) alongside a structured
    list of inbound and outbound relationships so agents can build
    relationship-aware context without reading graph.json directly.
    Also returns hub_summary if this is a hub node (degree >= 3).
    """
    from pathlib import Path

    # Node existence check runs regardless of vault config
    node = get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Concept not found")

    neighbors = get_node_neighbors(node_id)
    relationships = [
        {
            "direction": n["direction"],
            "peer_id": n["id"],
            "peer_label": n["label"],
            "type": n["relationship"],
        }
        for n in neighbors
    ]

    # Article content requires vault to be configured
    content: str | None = None
    if config.wiki_vault_path:
        article_path = Path(config.wiki_vault_path) / "concepts" / f"{node_id}.md"
        if article_path.exists():
            raw = article_path.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end = raw.find("---", 3)
                content = raw[end + 3:].strip() if end != -1 else raw
            else:
                content = raw

    hub_summary = get_hub_summary(node_id)

    return {
        "id": node["id"],
        "label": node["label"],
        "category": node.get("category", ""),
        "path": node.get("path", ""),
        "content": content,
        "relationships": relationships,
        "hub_summary": hub_summary,
    }


@app.get("/wiki/graph/concepts/{node_id}/neighbors")
async def get_concept_neighbors(node_id: str, type: str = "", depth: int = 1):
    """
    Traverse the knowledge graph from a given concept node.

    type:  optional relationship filter (uses, is-a, derived-from, …)
    depth: 1 = direct neighbors only, 2 = include second-hop neighbors
           (capped at 2 to prevent expensive full-graph scans)
    """
    if not get_node(node_id):
        raise HTTPException(status_code=404, detail="Concept not found")

    depth = min(max(depth, 1), 2)

    neighbors = get_node_neighbors(node_id, edge_type=type)

    if depth == 2:
        seen = {node_id} | {n["id"] for n in neighbors}
        for first_hop in list(neighbors):
            for second in get_node_neighbors(first_hop["id"], edge_type=type):
                if second["id"] not in seen:
                    seen.add(second["id"])
                    neighbors.append({**second, "hop": 2})

    return {"node_id": node_id, "neighbors": neighbors, "total": len(neighbors)}


@app.post("/wiki/graph/concepts/{node_id}/refresh-summary")
async def refresh_hub_summary(node_id: str):
    """
    Manually trigger regeneration of the hub summary for a concept node.
    Only meaningful for nodes with degree >= 3 (hub nodes).
    """
    node = get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Concept not found")

    try:
        from services.llm_service import chat_completion

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
        return {"node_id": node_id, "summary": summary.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Search Endpoint ────────────────────────────────────────────────

@app.get("/search")
async def search(q: str, vault: str = "all", limit: int = 20):
    """
    Hybrid search across indexed vault documents.

    Combines BM25 keyword ranking (FTS5) with semantic vector similarity
    using Reciprocal Rank Fusion. Falls back to BM25-only if sqlite-vec
    is unavailable or embedding generation fails.
    """
    if not q.strip():
        return {"results": []}

    # Generate query embedding for semantic search component
    query_emb = None
    try:
        from services.embedding_service import generate_embedding
        query_emb = await generate_embedding(q, config)
    except Exception as e:
        logger.debug("Query embedding failed, using BM25 only: %s", e)

    results = repo.hybrid_search(
        query=q,
        query_embedding=query_emb,
        vault=vault if vault != "all" else None,
        k=limit,
    )
    return {"results": results}


# ─── LLM Endpoints ─────────────────────────────────────────────────

@app.get("/llm/config")
async def llm_get_config():
    """Return current LLM configuration (API key is masked)."""
    key = config.llm.api_key
    masked = (key[:4] + "..." + key[-4:]) if len(key) > 8 else ("*" * len(key) if key else "")
    tkey = config.llm.transcription_api_key or ""
    tmasked = (tkey[:4] + "..." + tkey[-4:]) if len(tkey) > 8 else ("*" * len(tkey) if tkey else "")
    gkey = config.llm.groq_transcription_key or ""
    gmasked = (gkey[:4] + "..." + gkey[-4:]) if len(gkey) > 8 else ("*" * len(gkey) if gkey else "")
    return {
        "provider": config.llm.provider,
        "api_key_set": bool(key),
        "api_key_masked": masked,
        "base_url": config.llm.base_url,
        "models": config.llm.models,
        "max_tokens_per_run": config.llm.max_tokens_per_run,
        "transcription_api_key_set": bool(tkey),
        "transcription_api_key_masked": tmasked,
        "groq_transcription_key_set": bool(gkey),
        "groq_transcription_key_masked": gmasked,
    }


@app.post("/llm/validate", response_model=LLMValidateResponse)
async def llm_validate(request: LLMValidateRequest):
    """Validate an LLM API key/connection."""
    valid, error = await llm_validate_connection(
        provider=request.provider,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )

    if valid:
        # Save validated LLM config
        config.llm.provider = request.provider
        config.llm.api_key = request.api_key or ""
        config.llm.base_url = request.base_url
        # Persist transcription key if provided (or clear it)
        if request.transcription_api_key is not None:
            config.llm.transcription_api_key = request.transcription_api_key or None
        if request.groq_transcription_key is not None:
            config.llm.groq_transcription_key = request.groq_transcription_key or None
        config.save()

    return LLMValidateResponse(valid=valid, error=error)


# ─── Onboarding Endpoints ──────────────────────────────────────────

@app.post("/onboarding/generate-ontology", response_model=OnboardingGenerateResponse)
async def generate_ontology_endpoint(request: OnboardingGenerateRequest):
    """Generate ontology and AGENTS.md from user description."""
    from agents.setup_crew import generate_ontology

    try:
        result = await generate_ontology(
            description=request.description,
            provider=request.provider,
            model=request.model,
            api_key=request.api_key,
            base_url=request.base_url,
        )
        return OnboardingGenerateResponse(**result)
    except Exception as e:
        logger.error("Ontology generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Sync Endpoints ─────────────────────────────────────────────────

def _vault_root() -> str | None:
    """Return the vault root (parent of clean-vault)."""
    if not config.clean_vault_path:
        return None
    from pathlib import Path as _Path
    return str(_Path(config.clean_vault_path).parent)


@app.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status():
    """Return git sync status for the vault."""
    root = _vault_root()
    if not root:
        raise HTTPException(status_code=400, detail="Vault not initialised")
    status = git_get_status(root)
    return SyncStatusResponse(**status)


@app.post("/sync/configure")
async def sync_configure(request: SyncConfigRequest):
    """Set the git remote URL and init repo if needed."""
    root = _vault_root()
    if not root:
        raise HTTPException(status_code=400, detail="Vault not initialised")

    git_init_repo(root)
    result = git_set_remote(root, request.remote_url)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"success": True, "remote_url": request.remote_url}


@app.post("/sync/push", response_model=SyncActionResponse)
async def sync_push(message: str | None = None):
    """Stage all, commit if dirty, push to remote."""
    root = _vault_root()
    if not root:
        raise HTTPException(status_code=400, detail="Vault not initialised")

    git_init_repo(root)
    result = git_push(root, message=message)
    return SyncActionResponse(**result, files_changed=0)


@app.post("/sync/pull", response_model=SyncActionResponse)
async def sync_pull():
    """Pull latest changes from remote (rebase)."""
    root = _vault_root()
    if not root:
        raise HTTPException(status_code=400, detail="Vault not initialised")

    result = git_pull(root)
    return SyncActionResponse(
        success=result["success"],
        files_changed=result["files_changed"],
        error=result["error"],
    )


# ─── Clipboard Clip Endpoint ────────────────────────────────────────

class ClipRequest(BaseModel):
    text: str
    title: str = ""


@app.post("/ingest/clip")
async def ingest_clip(request: ClipRequest):
    """
    Write clipboard text directly to clean-vault/raw/clips/{timestamp}.md
    and immediately trigger the agent pipeline (bypasses debounce).
    """
    if not config.clean_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    import time as _time
    from pathlib import Path as _Path

    clips_dir = _Path(config.clean_vault_path) / "raw" / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    ts = int(_time.time())
    ts_us = int(_time.time() * 1_000_000)  # microseconds for uniqueness
    filename = f"clip-{ts_us}.md"
    dest = clips_dir / filename

    title = request.title.strip() or f"Clip {ts}"
    content = f"---\ntitle: {title}\nsource: clipboard\ncreated_at: {ts}\n---\n\n{request.text}\n"

    try:
        dest.write_text(content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    vault_rel = normalize_path(f"clean-vault/raw/clips/{filename}")
    job = ingest_queue.create_job(source_type="clip", source_path=vault_rel)
    ingest_queue.update_job(job.job_id, status=JobStatus.COMPLETE, progress=1.0, output_path=vault_rel)

    # Trigger pipeline immediately (no debounce)
    if config.initialized:
        asyncio.create_task(_run_pipeline_locked([vault_rel], config))

    return {"job_id": job.job_id, "path": vault_rel}


# ─── Voice Endpoints ────────────────────────────────────────────────

class VoiceRecordRequest(BaseModel):
    duration_s: float = 5.0
    model_size: str = "base"


@app.post("/voice/record")
async def voice_record(request: VoiceRecordRequest):
    """
    Record audio for duration_s seconds and return the transcript.
    Requires faster-whisper + sounddevice installed.
    """
    try:
        from services.voice_service import record_and_transcribe

        transcript, duration_ms = await record_and_transcribe(
            duration_s=request.duration_s,
            model_size=request.model_size,
        )
        return {"transcript": transcript, "duration_ms": duration_ms}
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Voice dependencies not installed: {e}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class VoiceStartRequest(BaseModel):
    model_size: str = "base"


@app.post("/voice/start")
async def voice_start(request: VoiceStartRequest):
    """
    Begin recording from the microphone immediately (hold-to-talk / button-toggle).
    Returns immediately — audio is captured in the background.
    Call POST /voice/stop to finalise and get the transcript.
    """
    try:
        from services.voice_service import start_recording

        start_recording(model_size=request.model_size)
        return {"status": "recording", "model_size": request.model_size}
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Voice dependencies not installed: {e}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/voice/stop")
async def voice_stop():
    """
    Stop the active recording and transcribe the captured audio.
    Returns {"transcript": "...", "duration_ms": N}.
    Must be called after POST /voice/start.
    """
    try:
        from services.voice_service import stop_recording_and_transcribe

        transcript, duration_ms = await stop_recording_and_transcribe()
        return {"transcript": transcript, "duration_ms": duration_ms}
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Voice dependencies not installed: {e}",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/voice/models")
async def voice_models():
    """Return available Whisper model sizes and download status."""
    try:
        from services.voice_service import list_available_models

        return {"models": list_available_models()}
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Voice dependencies not installed: {e}",
        )


@app.get("/voice/transcribe-mode")
async def voice_transcribe_mode():
    """
    Report whether server-side Whisper transcription is available.

    Returns {"available": true, "method": "whisper"} if an OpenAI key is configured,
    or {"available": false, "method": "speech_api"} otherwise.
    Frontend uses this to decide whether to send audio blobs or use Web Speech API.
    """
    from services.transcription_service import can_transcribe
    available = can_transcribe(config)
    return {"available": available, "method": "whisper" if available else "speech_api"}


@app.post("/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)):
    """
    Transcribe an audio blob using OpenAI Whisper.

    Accepts a multipart form upload with field 'file' (WebM audio, max ~25 MB).
    Returns {"transcript": "..."} on success.
    Returns 501 if no OpenAI key is configured — frontend should use Web Speech API.
    Returns 400 on bad audio or API key error.
    """
    from services.transcription_service import transcribe_audio

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        transcript = await transcribe_audio(audio_bytes, config)
        return {"transcript": transcript}
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Transcription error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Agent Endpoints ─────────────────────────────────────────────────

class AgentInstructRequest(BaseModel):
    instruction: str
    file_path: Optional[str] = None
    graph_neighbors: list[str] = []


@app.post("/agent/instruct")
async def agent_instruct(request: AgentInstructRequest):
    """
    Execute an agent instruction against the knowledge base.

    The agent classifies the instruction, builds context, calls the LLM,
    and creates a staging proposal for file-modifying operations.

    Returns:
      - edit/create/link/restructure: {"batch_id", "operation_type", "summary"}
      - search: {"answer", "sources"}
    """
    if not config.initialized:
        raise HTTPException(status_code=400, detail="Vault not initialised")

    from services.agent_service import execute_instruction

    try:
        result = await execute_instruction(
            instruction=request.instruction,
            file_path=request.file_path,
            graph_neighbors=request.graph_neighbors,
            config=config,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Agent instruction failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/agent/history")
async def agent_history():
    """Return the last 5 agent-created proposals (approved, rejected, or pending)."""
    from services.agent_service import get_agent_history

    entries = await get_agent_history(limit=5)
    return {"history": entries}


# ─── Research Endpoints ─────────────────────────────────────────────

class ResearchTopicRequest(BaseModel):
    topic: str
    max_pages: int = 5
    follow_citations: bool = True


class ResearchUrlRequest(BaseModel):
    url: str


async def _run_research_job(
    job_id: str,
    coro,
) -> None:
    """Run a research coroutine inside the ingest job queue, then trigger pipeline."""
    from services.ingestion.job_queue import JobStatus

    ingest_queue.update_job(job_id, status=JobStatus.PROCESSING, progress=0.1)
    try:
        result = await coro
        ingest_queue.update_job(
            job_id,
            status=JobStatus.COMPLETE,
            progress=1.0,
            output_path=result.output_paths[0] if result.output_paths else None,
        )
        # Trigger pipeline for each written file
        if result.output_paths and config.initialized:
            asyncio.create_task(
                _run_pipeline_locked(result.output_paths, config)
            )
        if result.errors:
            logger.warning("Research job %s had errors: %s", job_id, result.errors)
    except Exception as exc:
        logger.error("Research job %s failed: %s", job_id, exc)
        ingest_queue.update_job(job_id, status=JobStatus.ERROR, error=str(exc))


@app.post("/research/topic")
async def research_topic_endpoint(request: ResearchTopicRequest):
    """
    Start a supervised research job for a topic.
    Returns a job_id immediately; research runs in the background.
    Progress visible via GET /ingest/status/{job_id}.
    """
    if not config.clean_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    from services.browser_research import research_topic as _research_topic

    job = ingest_queue.create_job(source_type="research", source_url=request.topic)

    async def _run():
        coro = _research_topic(
            topic=request.topic,
            config=config,
            max_pages=request.max_pages,
            follow_citations=request.follow_citations,
        )
        await _run_research_job(job.job_id, coro)

    asyncio.create_task(_run())
    return {"job_id": job.job_id, "status": "pending"}


@app.post("/research/url")
async def research_url_endpoint(request: ResearchUrlRequest):
    """
    Start a supervised research job for a single URL.
    Returns a job_id immediately; fetching runs in the background.
    """
    if not config.clean_vault_path:
        raise HTTPException(status_code=400, detail="Vault not initialized")

    from services.browser_research import research_url as _research_url

    job = ingest_queue.create_job(source_type="research", source_url=request.url)

    async def _run():
        coro = _research_url(url=request.url, config=config)
        await _run_research_job(job.job_id, coro)

    asyncio.create_task(_run())
    return {"job_id": job.job_id, "status": "pending"}


# ─── Exec Endpoints ─────────────────────────────────────────────────

@app.get("/exec/pending")
async def exec_pending():
    """List all pending code execution runs."""
    runs = repo.get_pending_exec_runs()
    return {"runs": runs}


@app.get("/exec/{run_id}")
async def exec_get(run_id: str):
    """Get a single exec run by ID."""
    run = repo.get_exec_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Exec run not found")
    return run


@app.post("/exec/{run_id}/approve")
async def exec_approve(run_id: str):
    """
    Approve and execute a code run. Appends output to the article.
    Returns the exec result.
    """
    run = repo.get_exec_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Exec run not found")

    if run["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Run is not pending (status: {run['status']})")

    from services.code_executor import execute_python, execute_shell
    from pathlib import Path as _Path
    import time as _time

    vault_root = ""
    if config.wiki_vault_path:
        vault_root = str(_Path(config.wiki_vault_path).parent)

    lang = run["lang"]
    code = run["code"]

    if lang not in ("python", "py", "bash", "sh", "shell"):
        raise HTTPException(status_code=400, detail=f"Unsupported language: {lang}")

    try:
        if lang in ("python", "py"):
            result = await execute_python(code, timeout_s=30, vault_root=vault_root)
        else:
            result = await execute_shell(code, timeout_s=10, vault_root=vault_root)
    except Exception as exc:
        repo.update_exec_run(run_id, "error", stderr=str(exc), exit_code=-1)
        raise HTTPException(status_code=500, detail=str(exc))

    status = "complete" if result.success else "error"
    repo.update_exec_run(
        run_id,
        status=status,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
    )

    # Append output to the article in wiki-vault/concepts/
    if config.wiki_vault_path and run.get("article_path"):
        article_file = _Path(config.wiki_vault_path) / "concepts" / _Path(run["article_path"]).name
        if article_file.exists():
            ts = _time.strftime("%Y-%m-%d %H:%M", _time.localtime())
            output_block = f"\n\n**Output** (run {ts}):\n```\n{result.stdout or result.stderr or '(no output)'}\n```\n"
            try:
                existing = article_file.read_text(encoding="utf-8")
                article_file.write_text(existing + output_block, encoding="utf-8")
            except OSError as e:
                logger.warning("Could not append exec output to %s: %s", article_file, e)

    return {
        "run_id": run_id,
        "status": status,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "runtime_ms": result.runtime_ms,
    }


@app.post("/exec/{run_id}/reject")
async def exec_reject(run_id: str):
    """Reject (skip) a code execution run."""
    run = repo.get_exec_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Exec run not found")
    repo.update_exec_run(run_id, "rejected")
    return {"run_id": run_id, "status": "rejected"}


# ─── Pipeline Run Audit Endpoints (Feature 2) ───────────────────────

@app.get("/pipeline-runs")
async def list_pipeline_runs(limit: int = 20, status: Optional[str] = None):
    """List pipeline runs from the rich audit log, most recent first."""
    from db.database import get_connection
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs WHERE status = ? ORDER BY started_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/pipeline-runs/{run_id}")
async def get_pipeline_run(run_id: str):
    """Get a single pipeline run with its per-agent traces."""
    from db.database import get_connection
    conn = get_connection()
    run = conn.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    traces = conn.execute(
        "SELECT * FROM agent_traces WHERE run_id = ? ORDER BY started_at",
        (run_id,),
    ).fetchall()
    return {"run": dict(run), "traces": [dict(t) for t in traces]}


# ─── Agent Config Endpoints (Feature 6) ─────────────────────────────

@app.get("/config")
async def get_agent_config():
    """Return current agent configuration (from agents.toml or defaults)."""
    from config_loader import load_config
    cfg = load_config()
    return {
        "pipeline": {
            "debounce_seconds": cfg.pipeline.debounce_seconds,
            "hash_check": cfg.pipeline.hash_check,
        },
        "agents": {
            "ingest": cfg.ingest.__dict__,
            "analysis": cfg.analysis.__dict__,
            "proposal": cfg.proposal.__dict__,
            "review": cfg.review.__dict__,
            "fileback": cfg.fileback.__dict__,
        },
    }


@app.put("/config")
async def save_agent_config(body: dict):
    """Write updated agent config to ~/.vanilla/agents.toml."""
    try:
        import tomli_w
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="tomli-w not installed. Run: pip install tomli-w",
        )
    import config_loader as _cl
    _cl.USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_cl.USER_CONFIG_PATH, "wb") as f:
        tomli_w.dump(body, f)
    return {"status": "saved", "path": str(_cl.USER_CONFIG_PATH)}


# ─── Entry Point ────────────────────────────────────────────────────

def main():
    port = find_free_port()
    # CRITICAL: Print port to stdout for Tauri to read
    print(f"VANILLA_PORT:{port}", flush=True)
    sys.stdout.flush()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
