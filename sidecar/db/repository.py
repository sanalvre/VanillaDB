"""
Repository layer — all SQLite reads and writes go through this module.

No raw SQL should exist outside of this file (except schema.sql / database.py).
All writes are serialized to prevent WAL contention under concurrent async tasks.
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from db.database import get_connection, is_vec_available

logger = logging.getLogger("vanilla.repository")

# Serialize all writes through a single lock
_write_lock = threading.Lock()


# ─── FTS Content ────────────────────────────────────────────────────

def upsert_fts(path: str, vault: str, title: str, body: str) -> None:
    """Insert or update a document in the FTS index."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """INSERT INTO fts_content (path, vault, title, body, modified_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 vault=excluded.vault,
                 title=excluded.title,
                 body=excluded.body,
                 modified_at=excluded.modified_at""",
            (path, vault, title, body, int(time.time())),
        )
        conn.commit()


def delete_fts(path: str) -> None:
    """Remove a document from the FTS index."""
    with _write_lock:
        conn = get_connection()
        conn.execute("DELETE FROM fts_content WHERE path = ?", (path,))
        conn.commit()


def search_fts(query: str, vault: Optional[str] = None, limit: int = 20):
    """
    Full-text search across indexed documents.

    Returns list of dicts: {path, vault, title, snippet, score}
    """
    conn = get_connection()
    vault_clause = "AND fc.vault = ?" if vault and vault != "all" else ""
    params = [query]
    if vault and vault != "all":
        params.append(vault)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT fc.path, fc.vault, fc.title,
                   snippet(fts_index, 1, '<mark>', '</mark>', '...', 32) as snippet,
                   rank as score
            FROM fts_index fi
            JOIN fts_content fc ON fi.rowid = fc.id
            WHERE fts_index MATCH ?
            {vault_clause}
            ORDER BY rank
            LIMIT ?""",
        params,
    ).fetchall()

    return [dict(row) for row in rows]


# ─── Proposals ──────────────────────────────────────────────────────

def create_proposal(batch_id: str, batch_path: str, summary: str, source: str = "pipeline") -> None:
    """Create a new proposal batch."""
    with _write_lock:
        conn = get_connection()
        now = int(time.time())
        conn.execute(
            """INSERT INTO proposals (batch_id, batch_path, summary, status, source, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
            (batch_id, batch_path, summary, source, now, now),
        )
        conn.commit()


def add_proposal_article(batch_id: str, filename: str, title: str, action: str = "create") -> None:
    """Add an article to a proposal batch."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO proposal_articles (batch_id, filename, title, action) VALUES (?, ?, ?, ?)",
            (batch_id, filename, title, action),
        )
        conn.commit()


def get_pending_proposals():
    """Get all pending proposal batches with their articles."""
    conn = get_connection()
    batches = conn.execute(
        "SELECT * FROM proposals WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()

    result = []
    for batch in batches:
        articles = conn.execute(
            "SELECT * FROM proposal_articles WHERE batch_id = ?",
            (batch["batch_id"],),
        ).fetchall()
        result.append({
            **dict(batch),
            "articles": [dict(a) for a in articles],
        })
    return result


def count_pending_proposals() -> int:
    """Count pending proposal batches."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM proposals WHERE status = 'pending'"
    ).fetchone()
    return row["cnt"]


def claim_proposal(batch_id: str) -> bool:
    """
    Atomically transition a proposal from 'pending' to 'processing'.

    Returns True if the claim succeeded (caller should proceed with fileback).
    Returns False if the proposal is already processing/approved/rejected,
    which means another concurrent request already claimed it.
    """
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """UPDATE proposals SET status = 'processing', updated_at = ?
               WHERE batch_id = ? AND status = 'pending'""",
            (int(time.time()), batch_id),
        )
        conn.commit()
        return conn.execute(
            "SELECT 1 FROM proposals WHERE batch_id = ? AND status = 'processing'",
            (batch_id,),
        ).fetchone() is not None


def update_proposal_status(batch_id: str, status: str) -> None:
    """Update a proposal batch status (pending -> approved|rejected)."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "UPDATE proposals SET status = ?, updated_at = ? WHERE batch_id = ?",
            (status, int(time.time()), batch_id),
        )
        conn.commit()


def update_article_status(batch_id: str, filename: str, status: str) -> None:
    """Update an individual article status within a batch."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "UPDATE proposal_articles SET status = ? WHERE batch_id = ? AND filename = ?",
            (status, batch_id, filename),
        )
        conn.commit()


# ─── Agent Runs ─────────────────────────────────────────────────────

def create_agent_run(run_id: str, trigger_path: Optional[str] = None) -> None:
    """Record the start of an agent run."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """INSERT INTO agent_runs (run_id, trigger_path, status, started_at)
               VALUES (?, ?, 'running', ?)""",
            (run_id, trigger_path, int(time.time() * 1000)),
        )
        conn.commit()


def complete_agent_run(run_id: str, status: str = "complete",
                       error_msg: Optional[str] = None, tokens_used: int = 0,
                       warnings: Optional[list] = None) -> None:
    """Mark an agent run as complete or errored."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """UPDATE agent_runs
               SET status = ?, completed_at = ?, error_msg = ?, tokens_used = ?, warnings = ?
               WHERE run_id = ?""",
            (status, int(time.time()), error_msg, tokens_used,
             json.dumps(warnings or []), run_id),
        )
        conn.commit()


def update_run_warnings(run_id: str, warnings: list) -> None:
    """Update the warnings list for an in-progress run."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "UPDATE agent_runs SET warnings = ? WHERE run_id = ?",
            (json.dumps(warnings), run_id),
        )
        conn.commit()


def get_last_run():
    """Get the most recent agent run, including its warnings."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    # Parse warnings JSON; default to empty list if missing or malformed
    try:
        result["warnings"] = json.loads(result.get("warnings") or "[]")
    except (json.JSONDecodeError, TypeError):
        result["warnings"] = []
    return result


def get_runs(limit: int = 20, offset: int = 0):
    """Get paginated agent run history."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


# ─── Stale Articles ────────────────────────────────────────────────

def flag_stale_article(article_path: str, source_path: str) -> None:
    """Flag a wiki article as stale due to a source change. Idempotent."""
    with _write_lock:
        conn = get_connection()
        existing = conn.execute(
            "SELECT 1 FROM stale_articles WHERE article_path = ? AND source_path = ?",
            (article_path, source_path),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO stale_articles (article_path, source_path, flagged_at) VALUES (?, ?, ?)",
                (article_path, source_path, int(time.time())),
            )
            conn.commit()


def get_stale_articles():
    """Get all currently stale articles."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM stale_articles").fetchall()
    return [dict(row) for row in rows]


def clear_stale_article(article_path: str) -> None:
    """Remove stale flag for an article (after it's been re-evaluated)."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "DELETE FROM stale_articles WHERE article_path = ?",
            (article_path,),
        )
        conn.commit()


# ─── Sync Writes ────────────────────────────────────────────────────

def record_sync_write(path: str) -> None:
    """Record that a file was written by sync (to prevent double-trigger)."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO sync_writes (path, sync_timestamp) VALUES (?, ?)",
            (path, int(time.time())),
        )
        conn.commit()


def is_recent_sync_write(path: str, within_seconds: int = 30) -> bool:
    """Check if a path was recently written by sync."""
    conn = get_connection()
    cutoff = int(time.time()) - within_seconds
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM sync_writes WHERE path = ? AND sync_timestamp > ?",
        (path, cutoff),
    ).fetchone()
    return row["cnt"] > 0


def cleanup_old_sync_writes(older_than_seconds: int = 60) -> None:
    """Remove old sync write records."""
    with _write_lock:
        conn = get_connection()
        cutoff = int(time.time()) - older_than_seconds
        conn.execute("DELETE FROM sync_writes WHERE sync_timestamp < ?", (cutoff,))
        conn.commit()


# ─── Meta / Key-Value ──────────────────────────────────────────────

def get_meta(key: str) -> Optional[str]:
    """Get a value from the meta table."""
    conn = get_connection()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    """Set a value in the meta table."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


# ─── Vector Embeddings ─────────────────────────────────────────────

def _serialize_f32(vector: list[float]) -> bytes:
    """Serialize a float32 list to bytes for sqlite-vec storage."""
    import sqlite_vec
    return sqlite_vec.serialize_float32(vector)


def upsert_embedding(path: str, vault: str, embedding: list[float]) -> None:
    """
    Store a float32 embedding vector keyed by fts_content.id (via path lookup).

    Silently skips if sqlite-vec is unavailable or the path isn't indexed yet.
    """
    if not is_vec_available():
        return
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM fts_content WHERE path = ?", (path,)
    ).fetchone()
    if not row:
        logger.debug("upsert_embedding: path not in fts_content yet, skipping: %s", path)
        return
    rowid = row["id"]
    blob = _serialize_f32(embedding)
    with _write_lock:
        conn.execute(
            "INSERT OR REPLACE INTO vec_embeddings (rowid, embedding) VALUES (?, ?)",
            (rowid, blob),
        )
        conn.commit()


def search_vector(
    query_embedding: list[float],
    vault: Optional[str] = None,
    k: int = 10,
) -> list[dict]:
    """
    K-nearest-neighbour search against vec_embeddings.

    Returns list of {path, vault, title, distance} sorted by distance ascending.
    Returns [] if sqlite-vec is unavailable.

    vec0 requires LIMIT on the inner KNN subquery; vault filtering is applied
    after joining to fts_content.
    """
    if not is_vec_available():
        return []
    conn = get_connection()
    blob = _serialize_f32(query_embedding)
    # Fetch more than k from the KNN step so vault filtering still returns k results
    inner_k = k * 3 if vault else k
    vault_filter = "AND fc.vault = ?" if vault else ""
    params: list = [blob, inner_k]
    if vault:
        params = [blob, inner_k, vault, k]
    else:
        params = [blob, inner_k, k]
    try:
        # vec0 requires k= in the WHERE clause of the vec table query (not outer LIMIT)
        rows = conn.execute(
            f"""SELECT fc.path, fc.vault, fc.title, v.distance
                FROM (
                    SELECT rowid, distance
                    FROM vec_embeddings
                    WHERE embedding MATCH ?
                    AND k = ?
                ) v
                JOIN fts_content fc ON v.rowid = fc.id
                {vault_filter}
                ORDER BY v.distance
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Vector search failed: %s", e)
        return []


# ─── Graph CRUD ────────────────────────────────────────────────────


def graph_upsert_node(node_id: str, label: str, path: str,
                      category: str = "", last_batch: str = "") -> None:
    """Insert or update a concept node."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """INSERT INTO graph_nodes (id, label, path, category, last_batch)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 label=excluded.label,
                 path=excluded.path,
                 category=excluded.category,
                 last_batch=excluded.last_batch""",
            (node_id, label, path, category, last_batch),
        )
        conn.commit()


def graph_remove_node(node_id: str) -> None:
    """Remove a node and cascade-delete its edges."""
    with _write_lock:
        conn = get_connection()
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
        conn.commit()


def graph_get_node(node_id: str) -> Optional[dict]:
    """Look up a single node by its ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM graph_nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return dict(row) if row else None


def graph_get_all_nodes() -> list[dict]:
    """Return all concept nodes."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM graph_nodes").fetchall()
    return [dict(r) for r in rows]


def graph_add_edge(source: str, target: str, edge_type: str = "wikilink") -> None:
    """Add an edge; silently skips if the identical (source, target, type) already exists."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """INSERT OR IGNORE INTO graph_edges (source, target, type)
               VALUES (?, ?, ?)""",
            (source, target, edge_type),
        )
        conn.commit()


def graph_get_all_edges() -> list[dict]:
    """Return all edges."""
    conn = get_connection()
    rows = conn.execute("SELECT source, target, type FROM graph_edges").fetchall()
    return [dict(r) for r in rows]


def graph_get_edges_for_node(node_id: str) -> list[dict]:
    """Return all edges where the node is source or target."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT source, target, type FROM graph_edges WHERE source = ? OR target = ?",
        (node_id, node_id),
    ).fetchall()
    return [dict(r) for r in rows]


def graph_upsert_source_map(source_path: str, article_paths: list[str]) -> None:
    """Replace all citations for a source path with the new list."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "DELETE FROM graph_source_map WHERE source_path = ?", (source_path,)
        )
        for art in article_paths:
            conn.execute(
                "INSERT OR IGNORE INTO graph_source_map (source_path, article_path) VALUES (?, ?)",
                (source_path, art),
            )
        conn.commit()


def graph_add_source_citation(source_path: str, article_path: str) -> None:
    """Add a single citation from a source file to a wiki article (idempotent)."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO graph_source_map (source_path, article_path) VALUES (?, ?)",
            (source_path, article_path),
        )
        conn.commit()


def graph_get_articles_citing(source_path: str) -> list[str]:
    """Return all wiki article paths that cite the given source file."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT article_path FROM graph_source_map WHERE source_path = ?",
        (source_path,),
    ).fetchall()
    return [r["article_path"] for r in rows]


def graph_get_source_map() -> dict:
    """Return source→articles mapping as {source_path: [article_path, ...]}."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT source_path, article_path FROM graph_source_map ORDER BY source_path"
    ).fetchall()
    result: dict = {}
    for row in rows:
        result.setdefault(row["source_path"], []).append(row["article_path"])
    return result


def graph_get_all_source_paths() -> list[str]:
    """Return all source file paths that have at least one citation."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT source_path FROM graph_source_map"
    ).fetchall()
    return [r["source_path"] for r in rows]


def graph_node_in_degree(node_id: str) -> int:
    """Return the total number of edges (in + out) for a node."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM graph_edges WHERE source = ? OR target = ?",
        (node_id, node_id),
    ).fetchone()
    return row["cnt"] if row else 0


def graph_get_hub_nodes(min_degree: int = 3) -> list[dict]:
    """Return all nodes with total degree >= min_degree."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT n.id, n.label, n.path, n.category, n.last_batch,
                  COUNT(e.id) as degree
           FROM graph_nodes n
           JOIN graph_edges e ON (e.source = n.id OR e.target = n.id)
           GROUP BY n.id
           HAVING degree >= ?
           ORDER BY degree DESC""",
        (min_degree,),
    ).fetchall()
    return [dict(r) for r in rows]


def graph_upsert_hub_summary(node_id: str, summary: str) -> None:
    """Store a generated hub summary for a concept node."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """INSERT INTO hub_summaries (node_id, summary, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                 summary=excluded.summary,
                 updated_at=excluded.updated_at""",
            (node_id, summary, int(time.time())),
        )
        conn.commit()


def graph_get_hub_summary(node_id: str) -> Optional[str]:
    """Return the stored hub summary for a node, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT summary FROM hub_summaries WHERE node_id = ?", (node_id,)
    ).fetchone()
    return row["summary"] if row else None


def graph_migrate_from_json(wiki_vault_path: str) -> bool:
    """
    One-time migration: read graph.json and populate SQLite graph tables.

    Checks meta['graph_v1_migrated'] to avoid running twice.
    Returns True if migration ran, False if already done.
    """
    if get_meta("graph_v1_migrated") == "1":
        return False

    graph_path = Path(wiki_vault_path) / "graph.json"
    if graph_path.exists():
        try:
            data = json.loads(graph_path.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                graph_upsert_node(
                    node_id=node["id"],
                    label=node.get("label", node["id"]),
                    path=node.get("path", ""),
                    category=node.get("category", ""),
                    last_batch=node.get("lastBatch", ""),
                )
            for edge in data.get("edges", []):
                graph_add_edge(
                    source=edge["source"],
                    target=edge["target"],
                    edge_type=edge.get("type", "wikilink"),
                )
            for src, articles in data.get("source_map", {}).items():
                for art in articles:
                    graph_add_source_citation(src, art)
            logger.info(
                "Migrated graph.json → SQLite: %d nodes, %d edges",
                len(data.get("nodes", [])),
                len(data.get("edges", [])),
            )
        except Exception as e:
            logger.error("graph.json migration failed: %s", e)

    set_meta("graph_v1_migrated", "1")
    return True


# ─── Hybrid Search ─────────────────────────────────────────────────


def hybrid_search(
    query: str,
    query_embedding: Optional[list[float]] = None,
    vault: Optional[str] = None,
    k: int = 10,
) -> list[dict]:
    """
    Hybrid BM25 + vector search using Reciprocal Rank Fusion (RRF).

    Combines FTS5 keyword ranking with semantic vector similarity.
    Falls back to FTS5-only when query_embedding is None or sqlite-vec is unavailable.

    Returns list of {path, vault, title, snippet, score} sorted by RRF score descending.
    """
    RRF_K = 60  # Standard RRF constant — balances precision vs recall

    # ── BM25 (FTS5) results ───────────────────────────────────────────
    fts_results = search_fts(query, vault=vault, limit=k * 2)
    fts_ranks: dict[str, int] = {r["path"]: i + 1 for i, r in enumerate(fts_results)}

    # ── Vector results (if available) ────────────────────────────────
    vec_ranks: dict[str, int] = {}
    if query_embedding and is_vec_available():
        vec_results = search_vector(query_embedding, vault=vault, k=k * 2)
        vec_ranks = {r["path"]: i + 1 for i, r in enumerate(vec_results)}

    # ── Graph-degree boost (B2) ──────────────────────────────────────
    # Hub nodes (highly connected concepts) receive a small RRF boost.
    # Max boost = 0.005, ensuring relevance always dominates.
    path_to_degree: dict[str, int] = {}
    try:
        conn = get_connection()
        degree_rows = conn.execute(
            """SELECT n.path,
                      (SELECT COUNT(*) FROM graph_edges e
                       WHERE e.source = n.id OR e.target = n.id) AS degree
               FROM graph_nodes n"""
        ).fetchall()
        path_to_degree = {r["path"]: r["degree"] for r in degree_rows}
    except Exception:
        pass  # Graph tables not yet populated; silently skip

    # ── RRF merge ────────────────────────────────────────────────────
    all_paths = set(fts_ranks) | set(vec_ranks)
    rrf_scores: dict[str, float] = {}
    for path in all_paths:
        score = 0.0
        if path in fts_ranks:
            score += 1.0 / (RRF_K + fts_ranks[path])
        if path in vec_ranks:
            score += 1.0 / (RRF_K + vec_ranks[path])
        degree = path_to_degree.get(path, 0)
        if degree > 0:
            score += min(degree / 1000.0, 0.005)  # subtle hub boost
        rrf_scores[path] = score

    ranked_paths = sorted(rrf_scores, key=lambda p: rrf_scores[p], reverse=True)[:k]

    # ── Build result dicts with snippets ────────────────────────────
    # Snippets come from FTS results; fall back to empty string for vector-only hits
    fts_by_path = {r["path"]: r for r in fts_results}
    conn = get_connection()
    results = []
    for path in ranked_paths:
        if path in fts_by_path:
            r = fts_by_path[path]
            results.append({
                "path": r["path"],
                "vault": r["vault"],
                "title": r["title"],
                "snippet": r.get("snippet", ""),
                "score": rrf_scores[path],
            })
        else:
            # Vector-only hit — fetch metadata from fts_content
            row = conn.execute(
                "SELECT path, vault, title, body FROM fts_content WHERE path = ?",
                (path,),
            ).fetchone()
            if row:
                body = row["body"] or ""
                results.append({
                    "path": row["path"],
                    "vault": row["vault"],
                    "title": row["title"],
                    "snippet": body[:200] + "..." if len(body) > 200 else body,
                    "score": rrf_scores[path],
                })

    return results


# ─── Exec Runs CRUD ────────────────────────────────────────────────


def get_pending_exec_runs_for_article(article_path: str) -> list[dict]:
    """Return all pending exec runs for a specific article."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM exec_runs WHERE article_path = ? AND status = 'pending'",
        (article_path,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_exec_run(article_path: str, code: str, lang: str = "python") -> str:
    """Create a pending exec run and return its ID."""
    import uuid as _uuid
    run_id = f"exec_{_uuid.uuid4().hex[:12]}"
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """INSERT INTO exec_runs (id, article_path, code, lang, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (run_id, article_path, code, lang, int(time.time())),
        )
        conn.commit()
    logger.info("Created exec run: %s (%s, %d chars)", run_id, lang, len(code))
    return run_id


def update_exec_run(
    run_id: str,
    status: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: Optional[int] = None,
) -> None:
    """Update exec run status and output."""
    with _write_lock:
        conn = get_connection()
        conn.execute(
            """UPDATE exec_runs
               SET status=?, stdout=?, stderr=?, exit_code=?, run_at=?
               WHERE id=?""",
            (status, stdout, stderr, exit_code, int(time.time()), run_id),
        )
        conn.commit()


def get_exec_run(run_id: str) -> Optional[dict]:
    """Get a single exec run by ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM exec_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return dict(row) if row else None


def get_pending_exec_runs() -> list[dict]:
    """Return all exec runs with status 'pending'."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM exec_runs WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]
