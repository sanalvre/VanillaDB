"""
Embedding generation service.

Generates float32 vector embeddings for text using the configured provider's
embedding model. Used for semantic search (sqlite-vec), RAG context retrieval,
and graph node clustering.

Supported providers:
  OpenAI      — text-embedding-3-small (1536 dims), text-embedding-3-large (3072)
  OpenRouter  — text-embedding-3-small via openrouter.ai/api/v1/embeddings
  Anthropic   — NO native embedding API. Falls back to transcription_api_key
                (an optional secondary OpenAI key) if set; otherwise raises
                EmbeddingNotSupportedError so callers can show a clear message.
  Ollama      — excluded per product decision (no local models)

Callers must handle None returns gracefully — embedding failures never block writes.
"""

import logging
import struct
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import VanillaConfig

logger = logging.getLogger("vanilla.embedding")

# Truncate input to ~8 000 tokens (≈ 32 000 chars) before embedding.
_MAX_EMBED_CHARS = 32_000


class EmbeddingNotSupportedError(Exception):
    """
    Raised when the configured provider has no embedding API and no fallback key.

    Callers (e.g. the /wiki/graph/clusters endpoint) should catch this and return
    a 503 with a human-readable message so the frontend can surface it clearly.
    """
    pass


def _resolve_embedding_key(config: VanillaConfig) -> Optional[str]:
    """
    Return the API key to use for embeddings based on provider.

    - openai / openrouter: use main api_key
    - anthropic: use transcription_api_key (secondary OpenAI key) if set,
                 otherwise None (will trigger EmbeddingNotSupportedError)
    """
    provider = config.llm.provider
    if provider in ("openai", "openrouter"):
        return config.llm.api_key or None
    if provider == "anthropic":
        # Anthropic has no embedding API — reuse the optional transcription key
        # (an OpenAI key stored for Whisper) as an embedding key.
        key = config.llm.transcription_api_key
        if key:
            return key
        return None  # will raise EmbeddingNotSupportedError downstream
    # Unknown provider — try main key and let the HTTP call fail gracefully
    return config.llm.api_key or None


def can_embed(config: VanillaConfig) -> bool:
    """
    Return True if embedding generation is available for the current config.
    Use this to gate the semantic clustering feature in the UI.
    """
    return _resolve_embedding_key(config) is not None


async def generate_embedding(
    text: str,
    config: VanillaConfig,
) -> Optional[list[float]]:
    """
    Generate a vector embedding for *text* using the configured provider.

    Returns a list of floats on success, or None on any error (including when
    the provider doesn't support embeddings — error is logged, not raised,
    so ingest pipelines degrade gracefully).
    """
    if not text or not text.strip():
        return None

    truncated = text[:_MAX_EMBED_CHARS]
    provider  = config.llm.provider
    model     = config.llm.embedding_model

    api_key = _resolve_embedding_key(config)
    if api_key is None:
        if provider == "anthropic":
            logger.warning(
                "Anthropic has no embedding API. Set a secondary OpenAI key in "
                "Settings → Voice Transcription Key to enable embeddings/semantic clustering."
            )
        else:
            logger.warning("No API key for embeddings (provider=%s)", provider)
        return None

    try:
        return await _embed_openai_compat(
            truncated, model, api_key, provider, config.llm.base_url
        )
    except Exception as e:
        logger.warning("Embedding failed (provider=%s, model=%s): %s", provider, model, e)
        return None


async def generate_embedding_or_raise(
    text: str,
    config: VanillaConfig,
) -> list[float]:
    """
    Like generate_embedding() but raises EmbeddingNotSupportedError if the
    provider has no embedding capability. Used by the clustering endpoint
    so it can return a structured 503 rather than silently returning None.
    """
    if not text or not text.strip():
        raise ValueError("Empty text cannot be embedded")

    provider = config.llm.provider
    api_key  = _resolve_embedding_key(config)

    if api_key is None:
        if provider == "anthropic":
            raise EmbeddingNotSupportedError(
                "Claude/Anthropic does not have an embedding API. "
                "To enable semantic clustering, add an OpenAI key in "
                "Settings → Voice Transcription Key."
            )
        raise EmbeddingNotSupportedError(
            f"No API key configured for embeddings (provider={provider})."
        )

    return await _embed_openai_compat(
        text[:_MAX_EMBED_CHARS],
        config.llm.embedding_model,
        api_key,
        provider,
        config.llm.base_url,
    )


async def _embed_openai_compat(
    text: str,
    model: str,
    api_key: str,
    provider: str,
    base_url: Optional[str],
) -> list[float]:
    """Call an OpenAI-compatible /v1/embeddings endpoint."""
    if provider == "openrouter":
        url = (base_url or "https://openrouter.ai/api/v1").rstrip("/") + "/embeddings"
        # OpenRouter requires a specific embedding model; default to 3-small via OpenAI
        if not model or model not in ("text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"):
            model = "openai/text-embedding-3-small"
    else:
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"input": text, "model": model}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return data["data"][0]["embedding"]


def _serialize_embedding(vec: list[float]) -> bytes:
    """Pack a float list into raw float32 bytes for storage."""
    return struct.pack(f"{len(vec)}f", *vec)


async def embed_all_wiki_nodes(config: VanillaConfig, conn) -> int:
    """
    Generate and store embeddings for all graph nodes that don't yet have one
    (or whose node_embeddings row is older than 24 hours after a graph update).

    Embed text = "{label}\\n{category}\\n{neighbor labels joined by comma}"
    Including neighbor labels adds topological context so semantically similar
    AND structurally similar nodes have closer embeddings.

    Raises EmbeddingNotSupportedError if the provider cannot embed.
    Returns the count of nodes successfully embedded.
    """
    from db import repository as repo

    # Check capability before doing any work
    api_key = _resolve_embedding_key(config)
    if api_key is None:
        provider = config.llm.provider
        if provider == "anthropic":
            raise EmbeddingNotSupportedError(
                "Claude/Anthropic does not have an embedding API. "
                "Add an OpenAI key in Settings → Voice Transcription Key "
                "to enable semantic clustering."
            )
        raise EmbeddingNotSupportedError(
            f"No API key configured for embeddings (provider={provider})."
        )

    nodes = repo.graph_get_all_nodes()
    if not nodes:
        return 0

    # Build neighbor label map for richer embedding context
    edges = repo.graph_get_all_edges()
    neighbor_labels: dict[str, list[str]] = {}
    id_to_label = {n["id"]: n["label"] for n in nodes}

    for e in edges:
        src, tgt = e["source"], e["target"]
        neighbor_labels.setdefault(src, [])
        neighbor_labels.setdefault(tgt, [])
        if tgt in id_to_label:
            neighbor_labels[src].append(id_to_label[tgt])
        if src in id_to_label:
            neighbor_labels[tgt].append(id_to_label[src])

    # Determine which nodes need (re-)embedding
    existing_rows = conn.execute(
        "SELECT node_id, updated_at FROM node_embeddings"
    ).fetchall()
    existing = {r["node_id"]: r["updated_at"] for r in existing_rows}

    dims = config.llm.embedding_dims
    count = 0
    now = datetime.now(timezone.utc).isoformat()

    for node in nodes:
        nid = node["id"]
        # Skip if recently embedded (within last 24 h)
        if nid in existing:
            try:
                updated = datetime.fromisoformat(existing[nid].replace("Z", "+00:00"))
                age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
                if age_h < 24:
                    continue
            except Exception:
                pass

        # Build embed text
        neighbors = neighbor_labels.get(nid, [])[:10]
        embed_text = f"{node['label']}\n{node.get('category', '')}"
        if neighbors:
            embed_text += f"\nRelated: {', '.join(neighbors)}"

        try:
            vec = await _embed_openai_compat(
                embed_text[:_MAX_EMBED_CHARS],
                config.llm.embedding_model,
                api_key,
                config.llm.provider,
                config.llm.base_url,
            )
            raw = _serialize_embedding(vec)
            conn.execute(
                """INSERT OR REPLACE INTO node_embeddings (node_id, embedding, dims, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (nid, raw, dims, now),
            )
            count += 1
        except Exception as e:
            logger.warning("Failed to embed node %s: %s", nid, e)

    conn.commit()
    logger.info("Embedded %d/%d wiki nodes", count, len(nodes))
    return count
