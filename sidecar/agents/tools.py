"""Tool functions available to agents via LLM function calling."""

import json
from typing import Optional

from db.database import get_connection
from services.sandbox import execute_code


def vault_stats() -> dict:
    """Get high-level statistics about the current knowledge base."""
    conn = get_connection()
    return {
        "total_sources": conn.execute(
            "SELECT COUNT(*) FROM source_hashes"
        ).fetchone()[0],
        "total_concepts": conn.execute(
            "SELECT COUNT(*) FROM graph_nodes"
        ).fetchone()[0],
        "total_edges": conn.execute(
            "SELECT COUNT(*) FROM graph_edges"
        ).fetchone()[0],
        "pending_proposals": conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE status = 'pending'"
        ).fetchone()[0],
    }


def concept_search(query: str, k: int = 5) -> list[dict]:
    """Search for existing concepts by keyword. Returns top-k matches with snippets."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT fc.path, fc.title,
                  snippet(fts_index, 1, '>>>', '<<<', '...', 30) as snippet,
                  rank
           FROM fts_index
           JOIN fts_content fc ON fts_index.rowid = fc.id
           WHERE fts_index MATCH ? AND fc.vault = 'wiki'
           ORDER BY rank
           LIMIT ?""",
        (query, k),
    ).fetchall()
    return [dict(r) for r in rows]


def graph_neighbors(
    concept_id: str,
    depth: int = 1,
    relationship_type: Optional[str] = None,
) -> list[dict]:
    """Get concepts connected to a given concept in the knowledge graph."""
    conn = get_connection()
    query = """
        SELECT ge.target AS target, gn.label, gn.category, ge.type as relationship_type
        FROM graph_edges ge
        JOIN graph_nodes gn ON ge.target = gn.id
        WHERE ge.source = ?
    """
    params: list = [concept_id]
    if relationship_type:
        query += " AND ge.type = ?"
        params.append(relationship_type)
    query += " LIMIT 20"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def concept_staleness() -> list[dict]:
    """List concepts whose source documents have changed since compilation."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT gn.id, gn.label, gsm.source_path, sh.status as source_status
           FROM graph_source_map gsm
           JOIN graph_nodes gn ON gsm.article_path = gn.path
           LEFT JOIN source_hashes sh ON gsm.source_path = sh.source_path
           WHERE sh.status = 'failed'
              OR sh.source_path IS NULL
           LIMIT 50"""
    ).fetchall()
    return [dict(r) for r in rows]


def graph_stats(concept_id: str) -> dict:
    """Get degree centrality and source count for a specific concept node."""
    conn = get_connection()
    in_degree = conn.execute(
        "SELECT COUNT(*) FROM graph_edges WHERE target = ?", (concept_id,)
    ).fetchone()[0]
    out_degree = conn.execute(
        "SELECT COUNT(*) FROM graph_edges WHERE source = ?", (concept_id,)
    ).fetchone()[0]
    source_count = conn.execute(
        "SELECT COUNT(*) FROM graph_source_map WHERE article_path = ("
        "  SELECT path FROM graph_nodes WHERE id = ?"
        ")",
        (concept_id,),
    ).fetchone()[0]
    return {
        "concept_id": concept_id,
        "in_degree": in_degree,
        "out_degree": out_degree,
        "total_degree": in_degree + out_degree,
        "source_count": source_count,
    }


def run_code(code: str) -> dict:
    """Execute Python code and return output. Use for computing statistics,
    analysing data, or verifying numerical claims."""
    result = execute_code(code)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "success": result.success,
        "duration_ms": result.duration_ms,
    }


# ─── Tool schema definitions (OpenAI function-calling format) ─────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "vault_stats",
            "description": "Get counts of sources, concepts, edges, and pending proposals.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "concept_search",
            "description": (
                "Search existing wiki concepts by keyword. "
                "Use before creating new concepts to avoid duplicates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query keywords"},
                    "k": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_neighbors",
            "description": "Get concepts connected to a concept in the knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string", "description": "ID of the concept (slug)"},
                    "relationship_type": {
                        "type": "string",
                        "description": (
                            "Filter by type: uses, is-a, derived-from, extends, "
                            "contrasts-with, implements, part-of"
                        ),
                    },
                },
                "required": ["concept_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "concept_staleness",
            "description": "List concepts whose source documents have changed since they were compiled.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_stats",
            "description": "Get degree centrality and source count for a concept.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string", "description": "ID of the concept"},
                },
                "required": ["concept_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": (
                "Execute Python code to compute statistics, analyse data, or verify numerical claims. "
                "Available libraries: math, statistics, pandas, numpy, csv, json. "
                "No filesystem or network access."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Must print results to stdout.",
                    },
                },
                "required": ["code"],
            },
        },
    },
]

# ─── Dispatcher ───────────────────────────────────────────────────────────────

TOOL_DISPATCH = {
    "vault_stats": vault_stats,
    "concept_search": concept_search,
    "graph_neighbors": graph_neighbors,
    "concept_staleness": concept_staleness,
    "graph_stats": graph_stats,
    "run_code": run_code,
}
