"""
Graph service — manages the knowledge graph stored in SQLite.

Replaces the old graph.json file I/O with normalized SQLite tables
(graph_nodes, graph_edges, graph_source_map) for atomicity, concurrent
read safety, and O(1) per-mutation cost at any graph size.

All functions delegate to db.repository; this module is the sole
graph entry-point for the rest of the codebase.
"""

from services.paths import normalize_path
from db import repository as repo


# ─── Nodes ─────────────────────────────────────────────────────────

def add_node(
    node_id: str,
    label: str,
    path: str,
    category: str = "",
    batch_id: str = "",
) -> None:
    """Insert or update a concept node."""
    repo.graph_upsert_node(
        node_id=node_id,
        label=label,
        path=normalize_path(path),
        category=category,
        last_batch=batch_id,
    )


def remove_node(node_id: str) -> None:
    """Remove a node and cascade-delete its edges."""
    repo.graph_remove_node(node_id)


def get_node(node_id: str) -> dict | None:
    """Look up a single node by its ID."""
    return repo.graph_get_node(node_id)


def get_all_nodes() -> list[dict]:
    """Return all concept nodes."""
    return repo.graph_get_all_nodes()


# ─── Edges ─────────────────────────────────────────────────────────

def add_edge(source: str, target: str, edge_type: str = "wikilink") -> None:
    """Add a typed edge between two nodes (idempotent)."""
    repo.graph_add_edge(source=source, target=target, edge_type=edge_type)


def get_all_edges() -> list[dict]:
    """Return all edges."""
    return repo.graph_get_all_edges()


def get_node_neighbors(node_id: str, edge_type: str = "") -> list[dict]:
    """
    Return depth-1 neighbors of a node.

    Each result dict has: id, label, path, category, relationship, direction.
    Optionally filter by relationship type.
    """
    edges = repo.graph_get_edges_for_node(node_id)
    neighbors: list[dict] = []
    seen: set[str] = set()

    for edge in edges:
        rel_type = edge.get("type", "wikilink")
        if edge_type and rel_type != edge_type:
            continue

        if edge["source"] == node_id:
            peer_id = edge["target"]
            direction = "outbound"
        else:
            peer_id = edge["source"]
            direction = "inbound"

        if peer_id in seen:
            continue
        seen.add(peer_id)

        peer = repo.graph_get_node(peer_id)
        if peer:
            neighbors.append({**peer, "relationship": rel_type, "direction": direction})

    return neighbors


# ─── Source Map ────────────────────────────────────────────────────

def add_source_citation(source_path: str, article_path: str) -> None:
    """Record that an article cites a source file (idempotent)."""
    repo.graph_add_source_citation(
        normalize_path(source_path),
        normalize_path(article_path),
    )


def update_source_map(source_path: str, article_paths: list[str]) -> None:
    """Replace the full citation list for a source path."""
    repo.graph_upsert_source_map(
        normalize_path(source_path),
        [normalize_path(p) for p in article_paths],
    )


def get_source_map() -> dict:
    """Return full source→articles mapping as {source_path: [article_path, ...]}."""
    return repo.graph_get_source_map()


def get_articles_citing(source_path: str) -> list[str]:
    """Return all wiki article paths that cite a given source file."""
    return repo.graph_get_articles_citing(normalize_path(source_path))


def get_all_source_paths() -> list[str]:
    """Return all source file paths that have at least one citation."""
    return repo.graph_get_all_source_paths()


# ─── Hub Summaries ─────────────────────────────────────────────────

def get_hub_summary(node_id: str) -> str | None:
    """Return the stored hub summary for a node, or None."""
    return repo.graph_get_hub_summary(node_id)


def upsert_hub_summary(node_id: str, summary: str) -> None:
    """Store a generated hub summary."""
    repo.graph_upsert_hub_summary(node_id, summary)


def get_hub_nodes(min_degree: int = 3) -> list[dict]:
    """Return nodes whose total edge count >= min_degree."""
    return repo.graph_get_hub_nodes(min_degree)
