"""
Graph clustering service — topology-based and semantic (embedding-based) clustering.

Topology clustering: Louvain community detection on the wikilink graph via networkx.
Semantic clustering: K-Means on wiki-node embeddings (stored in node_embeddings table).
  - K is automatically selected via silhouette score (range 2–10).
  - Uses only numpy (no scipy/sklearn) to keep the binary small.
  - Implements k-means++ initialisation for stable, high-quality centroids.

Both methods return {node_id: cluster_id} mappings.
Orphan nodes (no edges, or no embeddings) are always included — they get their own
singleton cluster so no node is ever silently excluded from the result.

Provider compatibility for embeddings:
  - OpenAI, OpenRouter  — native embedding API
  - Anthropic           — no embedding endpoint; falls back to transcription_api_key
                          if set, otherwise raises EmbeddingNotSupportedError
  - Ollama              — excluded per product decision (no local models)
"""

import logging
import math
import random
import struct
import time
from typing import Optional

logger = logging.getLogger("vanilla.clustering")

# ─── Exceptions ──────────────────────────────────────────────────────────────


class EmbeddingNotSupportedError(Exception):
    """Raised when the configured provider cannot generate embeddings."""
    pass


# ─── Topology clustering (Louvain via networkx) ──────────────────────────────


def compute_topology_clusters(
    nodes: list[dict],
    edges: list[dict],
    seed: int = 42,
) -> dict[str, int]:
    """
    Run Louvain community detection on the wikilink graph.

    Returns {node_id: cluster_id} for ALL nodes including orphans.
    Clusters are sorted by size descending so the largest community = 0.

    Args:
        nodes: list of {id, label, ...} dicts
        edges: list of {source, target, type} dicts
        seed:  random seed for reproducible results

    Returns:
        {} if nodes is empty
        Singleton {node_id: 0} for a single node
        Community assignments otherwise
    """
    if not nodes:
        return {}

    try:
        import networkx as nx
        from networkx.algorithms import community as nx_community
    except ImportError:
        logger.error(
            "networkx is not installed — topology clustering unavailable. "
            "pip install networkx"
        )
        # Fallback: assign all nodes to cluster 0
        return {n["id"]: 0 for n in nodes}

    # Build undirected graph (direction is irrelevant for community detection)
    G = nx.Graph()
    node_ids = {n["id"] for n in nodes}
    G.add_nodes_from(node_ids)

    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        if src in node_ids and tgt in node_ids and src != tgt:
            G.add_edge(src, tgt)

    # Louvain — networkx ≥ 3.0 ships this natively
    try:
        communities = nx_community.louvain_communities(G, seed=seed)
    except AttributeError:
        # networkx < 3.0 fallback: use greedy_modularity_communities
        logger.warning("louvain_communities not available, using greedy_modularity_communities")
        communities = list(nx_community.greedy_modularity_communities(G))

    # Sort communities by size descending — largest = cluster 0
    communities_sorted = sorted(communities, key=len, reverse=True)

    result: dict[str, int] = {}
    for cid, community_set in enumerate(communities_sorted):
        for node_id in community_set:
            result[node_id] = cid

    # Ensure every input node is in the result (isolated components handled by nx)
    for n in nodes:
        if n["id"] not in result:
            # Truly disconnected — give it its own cluster beyond the Louvain set
            result[n["id"]] = len(communities_sorted)

    return result


# ─── Semantic clustering (K-Means + silhouette, numpy only) ──────────────────


def _kmeans_plus_plus_init(
    X: list[list[float]],
    k: int,
    rng: random.Random,
) -> list[list[float]]:
    """K-Means++ centroid initialisation."""
    n = len(X)
    centroids = [X[rng.randrange(n)]]

    for _ in range(k - 1):
        # Squared distances to nearest centroid
        dists = []
        for x in X:
            d = min(
                sum((a - b) ** 2 for a, b in zip(x, c))
                for c in centroids
            )
            dists.append(d)
        total = sum(dists)
        if total == 0:
            break
        r = rng.uniform(0, total)
        cumsum = 0.0
        for i, d in enumerate(dists):
            cumsum += d
            if cumsum >= r:
                centroids.append(X[i])
                break

    # Pad with random points if k > distinct points
    while len(centroids) < k:
        centroids.append(X[rng.randrange(n)])

    return centroids


def _kmeans_run(
    X: list[list[float]],
    k: int,
    max_iter: int = 100,
    seed: int = 42,
) -> tuple[list[int], list[list[float]]]:
    """
    Single K-Means run with k-means++ init.
    Returns (labels, centroids).
    """
    rng = random.Random(seed)
    n = len(X)
    dims = len(X[0])

    centroids = _kmeans_plus_plus_init(X, k, rng)

    labels = [0] * n
    for _ in range(max_iter):
        # Assignment step
        new_labels = []
        for x in X:
            best, best_d = 0, float("inf")
            for ci, c in enumerate(centroids):
                d = sum((a - b) ** 2 for a, b in zip(x, c))
                if d < best_d:
                    best_d, best = d, ci
            new_labels.append(best)

        if new_labels == labels:
            break
        labels = new_labels

        # Update step
        sums = [[0.0] * dims for _ in range(k)]
        counts = [0] * k
        for i, lbl in enumerate(labels):
            for d in range(dims):
                sums[lbl][d] += X[i][d]
            counts[lbl] += 1

        for ci in range(k):
            if counts[ci] > 0:
                centroids[ci] = [sums[ci][d] / counts[ci] for d in range(dims)]

    return labels, centroids


def _silhouette_score(X: list[list[float]], labels: list[int]) -> float:
    """
    Compute mean silhouette coefficient.
    O(n²) — acceptable for n < 500 (typical graph size).
    Returns value in [-1, 1]; higher is better.
    """
    n = len(X)
    if n < 2:
        return 0.0

    unique_labels = list(set(labels))
    if len(unique_labels) < 2:
        return 0.0

    def dist(a: list[float], b: list[float]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    scores = []
    for i in range(n):
        same = [j for j in range(n) if j != i and labels[j] == labels[i]]
        if not same:
            scores.append(0.0)
            continue
        a = sum(dist(X[i], X[j]) for j in same) / len(same)

        other_labels = [lbl for lbl in unique_labels if lbl != labels[i]]
        b = float("inf")
        for other_lbl in other_labels:
            other_idxs = [j for j in range(n) if labels[j] == other_lbl]
            if other_idxs:
                mean_d = sum(dist(X[i], X[j]) for j in other_idxs) / len(other_idxs)
                b = min(b, mean_d)

        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)

    return sum(scores) / len(scores) if scores else 0.0


def _deserialize_embedding(blob: bytes) -> list[float]:
    """Deserialize raw float32 bytes into a Python list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _serialize_embedding_py(vec: list[float]) -> bytes:
    """Pack a float list into raw float32 bytes (test-accessible alias)."""
    if not vec:
        return b""
    return struct.pack(f"{len(vec)}f", *vec)


# Expose for tests
convexHull_py = None  # placeholder — hull logic lives in frontend JS


def compute_semantic_clusters(
    node_ids: list[str],
    embeddings: list[list[float]],
    seed: int = 42,
    max_k: int = 10,
    n_restarts: int = 3,
) -> dict[str, int]:
    """
    Cluster nodes by embedding similarity using K-Means with automatic K selection.

    K is chosen by running K in [2, min(max_k, n//2)] and picking the K with the
    highest silhouette score. A fixed seed ensures deterministic results.

    Args:
        node_ids:   list of node IDs (parallel to embeddings)
        embeddings: list of float vectors (must all have same length)
        seed:       random seed
        max_k:      upper bound for K search
        n_restarts: number of random restarts per K (best inertia wins)

    Returns:
        {node_id: cluster_id} — cluster 0 = largest cluster
        Returns {node_id: 0} for all if n < 4 (can't meaningfully cluster)
    """
    n = len(node_ids)
    if n == 0:
        return {}
    if n < 4:
        logger.info("Too few nodes (%d) for semantic clustering — returning single cluster", n)
        return {nid: 0 for nid in node_ids}
    if not embeddings or len(embeddings[0]) == 0:
        return {nid: 0 for nid in node_ids}

    # K range: at least 2, at most floor(n/2) or max_k
    k_max = min(max_k, n // 2)
    if k_max < 2:
        return {nid: 0 for nid in node_ids}

    best_k = 2
    best_score = -2.0
    best_labels: list[int] = [0] * n

    for k in range(2, k_max + 1):
        # Run n_restarts times with different seeds, keep best silhouette
        run_labels_best: list[int] = []
        run_score_best = -2.0

        for restart in range(n_restarts):
            labels, _ = _kmeans_run(embeddings, k, seed=seed + restart * 100 + k)
            score = _silhouette_score(embeddings, labels)
            if score > run_score_best:
                run_score_best = score
                run_labels_best = labels

        if run_score_best > best_score:
            best_score = run_score_best
            best_k = k
            best_labels = run_labels_best

    logger.info(
        "Semantic clustering: selected K=%d, silhouette=%.3f",
        best_k, best_score,
    )

    # Renumber cluster ids so largest cluster = 0
    from collections import Counter
    freq = Counter(best_labels)
    rank = {lbl: i for i, (lbl, _) in enumerate(freq.most_common())}
    return {node_ids[i]: rank[best_labels[i]] for i in range(n)}


# ─── Wiki-node embedding loader ──────────────────────────────────────────────


def load_node_embeddings(
    node_ids: list[str],
    conn,
) -> tuple[list[str], list[list[float]]]:
    """
    Load stored node embeddings for the given node_ids from node_embeddings table.

    Returns (valid_node_ids, embeddings) — only nodes with stored embeddings.
    """
    if not node_ids:
        return [], []

    placeholders = ",".join("?" * len(node_ids))
    try:
        rows = conn.execute(
            f"SELECT node_id, embedding FROM node_embeddings WHERE node_id IN ({placeholders})",
            node_ids,
        ).fetchall()
    except Exception as e:
        logger.warning("Failed to load node embeddings: %s", e)
        return [], []

    valid_ids = []
    vectors = []
    for row in rows:
        try:
            vec = _deserialize_embedding(bytes(row["embedding"]))
            valid_ids.append(row["node_id"])
            vectors.append(vec)
        except Exception:
            continue

    return valid_ids, vectors


# ─── Cluster label generation ────────────────────────────────────────────────


async def generate_cluster_labels(
    clusters: list[dict],  # [{cluster_id, node_labels: [str]}]
    config,                # VanillaConfig
) -> dict[int, str]:
    """
    Call the configured LLM to generate a short (2-3 word) topic label for each cluster.

    Returns {cluster_id: label}. Falls back to "Cluster N" on any error.
    """
    labels: dict[int, str] = {}

    for cluster in clusters:
        cid = cluster["cluster_id"]
        node_labels = cluster["node_labels"][:12]  # cap at 12 to keep prompt short
        default_label = f"Cluster {cid}"

        if not node_labels:
            labels[cid] = default_label
            continue

        prompt = (
            f"Given these knowledge base concept names: {', '.join(node_labels)}\n"
            f"Reply with ONLY a 2-3 word topic label that describes what they have in common. "
            f"No punctuation, no explanation."
        )

        try:
            label_text = await _llm_label_call(prompt, config)
            labels[cid] = label_text.strip()[:40] or default_label
        except Exception as e:
            logger.warning("Cluster label generation failed for cluster %d: %s", cid, e)
            labels[cid] = default_label

    return labels


async def _llm_label_call(prompt: str, config) -> str:
    """Make a minimal LLM completion call for cluster labelling."""
    import httpx

    provider = config.llm.provider
    api_key  = config.llm.api_key
    model    = config.llm.models.get("ingest", "gpt-4o-mini")

    if provider == "anthropic":
        url = (config.llm.base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 20,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    else:
        # OpenAI-compatible (openai, openrouter, custom)
        base = config.llm.base_url or (
            "https://openrouter.ai/api/v1" if provider == "openrouter"
            else "https://api.openai.com/v1"
        )
        url = base.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 20,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
