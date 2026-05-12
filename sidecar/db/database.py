"""
SQLite database initialization and connection management.

The Python sidecar is the sole owner of the SQLite database.
WAL mode is enabled for concurrent read access from async tasks.
All writes are serialized through the repository layer.

sqlite-vec is loaded as an extension to support float32 vector embeddings
for semantic search and RAG in the agent pipeline.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from config import VanillaConfig

logger = logging.getLogger("vanilla.db")

# Module-level connection (reused across requests)
_connection: Optional[sqlite3.Connection] = None


SCHEMA_SQL = """
-- Full-text search content table
CREATE TABLE IF NOT EXISTS fts_content (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    vault TEXT NOT NULL,
    title TEXT,
    body TEXT,
    modified_at INTEGER
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(
    title, body,
    content='fts_content', content_rowid='id'
);

-- FTS5 triggers to keep index in sync with content table
CREATE TRIGGER IF NOT EXISTS fts_content_ai AFTER INSERT ON fts_content BEGIN
    INSERT INTO fts_index(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS fts_content_ad AFTER DELETE ON fts_content BEGIN
    INSERT INTO fts_index(fts_index, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS fts_content_au AFTER UPDATE ON fts_content BEGIN
    INSERT INTO fts_index(fts_index, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO fts_index(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

-- Proposal batches
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    batch_path TEXT NOT NULL,
    summary TEXT,
    status TEXT DEFAULT 'pending',
    created_at INTEGER,
    updated_at INTEGER
);

-- Individual articles within a batch
CREATE TABLE IF NOT EXISTS proposal_articles (
    id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES proposals(batch_id),
    filename TEXT NOT NULL,
    title TEXT,
    action TEXT DEFAULT 'create',
    status TEXT DEFAULT 'pending'
);

-- Agent run history
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    trigger_path TEXT,
    status TEXT,
    started_at INTEGER,
    completed_at INTEGER,
    error_msg TEXT,
    tokens_used INTEGER DEFAULT 0
);

-- Stale article tracking
CREATE TABLE IF NOT EXISTS stale_articles (
    id INTEGER PRIMARY KEY,
    article_path TEXT NOT NULL,
    source_path TEXT NOT NULL,
    flagged_at INTEGER
);

-- Sync write tracking (prevents double-trigger when fileback writes wiki articles)
CREATE TABLE IF NOT EXISTS sync_writes (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    sync_timestamp INTEGER NOT NULL
);

-- Key-value metadata store (used to persist embedding dims across restarts)
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Knowledge graph nodes (replaces graph.json nodes array)
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    path TEXT NOT NULL,
    category TEXT DEFAULT '',
    last_batch TEXT DEFAULT ''
);

-- Knowledge graph edges (replaces graph.json edges array)
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    type TEXT NOT NULL DEFAULT 'wikilink',
    UNIQUE(source, target, type)
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target);

-- Graph source map (replaces graph.json source_map dict)
CREATE TABLE IF NOT EXISTS graph_source_map (
    source_path TEXT NOT NULL,
    article_path TEXT NOT NULL,
    PRIMARY KEY (source_path, article_path)
);
CREATE INDEX IF NOT EXISTS idx_graph_source_map_source ON graph_source_map(source_path);

-- Hub/cluster summaries for highly-connected concept nodes
CREATE TABLE IF NOT EXISTS hub_summaries (
    node_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

-- Agent-initiated code execution runs (approval-gated)
CREATE TABLE IF NOT EXISTS exec_runs (
    id TEXT PRIMARY KEY,
    article_path TEXT NOT NULL,
    code TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'python',
    status TEXT DEFAULT 'pending',
    stdout TEXT DEFAULT '',
    stderr TEXT DEFAULT '',
    exit_code INTEGER,
    created_at INTEGER NOT NULL,
    run_at INTEGER
);

-- Source hash tracking for incremental compilation (skip unchanged files)
CREATE TABLE IF NOT EXISTS source_hashes (
    source_path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    file_size INTEGER,
    last_processed_at TEXT NOT NULL,
    last_run_id TEXT,
    status TEXT NOT NULL DEFAULT 'processed'
);
CREATE INDEX IF NOT EXISTS idx_source_hashes_status ON source_hashes(status);

-- Rich pipeline run audit log (complements the lighter-weight agent_runs table)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    profile TEXT DEFAULT 'default',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    skipped_reason TEXT,
    proposal_count INTEGER DEFAULT 0,
    total_tokens_in INTEGER DEFAULT 0,
    total_tokens_out INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    error_stage TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source ON pipeline_runs(source_path);

-- Per-agent timing and token trace records within a pipeline run
CREATE TABLE IF NOT EXISTS agent_traces (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES pipeline_runs(id),
    agent_name TEXT NOT NULL,
    model TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    tools_called TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    prompt_preview TEXT,
    response_preview TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_traces_run ON agent_traces(run_id);
"""


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """
    Load the sqlite-vec extension for vector search support.

    Returns True if loaded successfully, False if sqlite-vec is not installed.
    Vector search is gracefully disabled when the extension is unavailable.
    """
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        logger.info("sqlite-vec loaded (version: %s)", sqlite_vec.__version__)
        return True
    except ImportError:
        logger.warning("sqlite-vec not installed — semantic search disabled. pip install sqlite-vec")
        return False
    except Exception as e:
        logger.warning("sqlite-vec failed to load: %s — semantic search disabled", e)
        return False


def _ensure_vec_table(conn: sqlite3.Connection, dims: int) -> None:
    """
    Create the vec_embeddings virtual table with the correct dimensions.

    If the stored dimension count differs from the requested dims (e.g. user
    switched embedding models), the old table is dropped and recreated.
    Embeddings will be regenerated lazily on the next ingest/fileback cycle.
    """
    stored_row = conn.execute(
        "SELECT value FROM meta WHERE key = 'embedding_dims'"
    ).fetchone()

    if stored_row is not None:
        stored_dims = int(stored_row[0])
        if stored_dims != dims:
            logger.warning(
                "Embedding dims changed (%d → %d), dropping vec_embeddings table. "
                "Embeddings will regenerate on next ingest.",
                stored_dims, dims,
            )
            conn.execute("DROP TABLE IF EXISTS vec_embeddings")

    conn.execute(
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings
            USING vec0(rowid INTEGER PRIMARY KEY, embedding float[{dims}])"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('embedding_dims', ?)",
        (str(dims),),
    )
    conn.commit()


def _run_column_migrations(conn: sqlite3.Connection) -> None:
    """
    Idempotently add columns and tables that were added after the initial schema.

    ALTER TABLE IF NOT EXISTS ... ADD COLUMN is not available in all SQLite
    versions, so we check the existing columns first.
    """
    # agent_runs: add warnings column for surfacing pipeline degradation to the UI
    cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_runs)")}
    if "warnings" not in cols:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN warnings TEXT DEFAULT '[]'")
        conn.commit()
        logger.info("Migrated agent_runs: added warnings column")

    # proposals: add source column to distinguish agent-created vs pipeline-created proposals
    prop_cols = {row[1] for row in conn.execute("PRAGMA table_info(proposals)")}
    if "source" not in prop_cols:
        conn.execute("ALTER TABLE proposals ADD COLUMN source TEXT DEFAULT 'pipeline'")
        conn.commit()
        logger.info("Migrated proposals: added source column")

    # graph_nodes: cluster assignment columns
    gn_cols = {row[1] for row in conn.execute("PRAGMA table_info(graph_nodes)")}
    if "topology_cluster_id" not in gn_cols:
        conn.execute(
            "ALTER TABLE graph_nodes ADD COLUMN topology_cluster_id INTEGER DEFAULT NULL"
        )
        conn.commit()
        logger.info("Migrated graph_nodes: added topology_cluster_id column")
    if "semantic_cluster_id" not in gn_cols:
        conn.execute(
            "ALTER TABLE graph_nodes ADD COLUMN semantic_cluster_id INTEGER DEFAULT NULL"
        )
        conn.commit()
        logger.info("Migrated graph_nodes: added semantic_cluster_id column")

    # node_embeddings: stores float32 embeddings for wiki concept nodes
    # (separate from vec_embeddings which covers source documents)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS node_embeddings (
            node_id    TEXT PRIMARY KEY,
            embedding  BLOB NOT NULL,
            dims       INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # cluster_labels: human-readable names for cluster ids (LLM-generated)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_labels (
            method       TEXT NOT NULL,
            cluster_id   INTEGER NOT NULL,
            label        TEXT NOT NULL,
            member_count INTEGER NOT NULL DEFAULT 0,
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (method, cluster_id)
        )
    """)

    conn.commit()


def get_db_path(config: VanillaConfig) -> Path:
    """Get the SQLite database file path from config."""
    return config.db_path


def init_db(db_path: Path, embedding_dims: int = 1536) -> sqlite3.Connection:
    """
    Initialize the SQLite database with WAL mode and create all tables.

    Loads the sqlite-vec extension for vector search if available.
    Creates the vec_embeddings virtual table with the given dimensions.

    Returns the connection for reuse.
    """
    global _connection

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Enable WAL mode for concurrent reads
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Create core schema (FTS, proposals, runs, graph tables, etc.)
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    # Add columns introduced after initial release (idempotent)
    _run_column_migrations(conn)

    # Load vector extension and create vec_embeddings table
    vec_available = _load_sqlite_vec(conn)
    if vec_available:
        _ensure_vec_table(conn, embedding_dims)

    _connection = conn
    return conn


def get_connection() -> sqlite3.Connection:
    """Get the active database connection. Raises if not initialized."""
    if _connection is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _connection


def is_vec_available() -> bool:
    """Return True if the vec_embeddings table exists (sqlite-vec loaded successfully)."""
    try:
        conn = get_connection()
        conn.execute("SELECT COUNT(*) FROM vec_embeddings LIMIT 1")
        return True
    except Exception:
        return False
