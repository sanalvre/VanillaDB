"""
VanillaDB MCP Server — exposes your knowledge base to AI agents via the
Model Context Protocol (MCP).

Usage
-----
Install the optional dep:
    pip install ".[mcp]"

Run (requires a running VanillaDB sidecar):
    VANILLA_URL=http://127.0.0.1:<port> python mcp_server.py

The port is printed to stdout when the sidecar starts:
    VANILLA_PORT:54321

Claude Desktop config (~/.config/claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "vanilladb": {
          "command": "python",
          "args": ["/path/to/sidecar/mcp_server.py"],
          "env": { "VANILLA_URL": "http://127.0.0.1:<port>" }
        }
      }
    }

Tools exposed
-------------
search_knowledge     — hybrid BM25 + semantic search, returns ranked snippets
get_context          — RAG retrieval, returns article bodies ready for prompts
get_related_concepts — traverse the knowledge graph from a concept
list_concepts        — browse the full concept index, optionally by category
"""

import os
import httpx
from fastmcp import FastMCP
from services.mcp_sanitize import sanitize_all_tools

# ─── Configuration ───────────────────────────────────────────────────────────

_port = os.environ.get("VANILLA_PORT", "")
VANILLA_URL = os.environ.get(
    "VANILLA_URL",
    f"http://127.0.0.1:{_port}" if _port else "http://127.0.0.1:8765",
)

# ─── MCP server ──────────────────────────────────────────────────────────────

mcp = FastMCP(
    "VanillaDB",
    instructions=(
        "VanillaDB is an agent-native knowledge base. "
        "Use search_knowledge or get_context to retrieve relevant information, "
        "get_related_concepts to traverse the knowledge graph, and "
        "list_concepts to browse what's in the vault."
    ),
)


@mcp.tool()
async def search_knowledge(query: str, k: int = 10, vault: str = "wiki") -> str:
    """
    Search the knowledge base using hybrid BM25 + semantic search.

    Returns a ranked list of matching articles with title, path, and a snippet.
    Use get_context() instead when you need full article bodies for prompt injection.

    Args:
        query: Natural-language search query
        k:     Number of results to return (default 10, max 50)
        vault: "wiki" (approved articles only), "clean" (source docs), or "all"
    """
    k = min(k, 50)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{VANILLA_URL}/search",
            params={"q": query, "vault": vault, "limit": k},
        )
        r.raise_for_status()
        results = r.json().get("results", [])

    if not results:
        return f"No results found for: {query!r}"

    lines = [f"Search results for {query!r} ({len(results)} found):\n"]
    for i, res in enumerate(results, 1):
        lines.append(f"{i}. **{res['title']}**  `{res['path']}`")
        if res.get("snippet"):
            lines.append(f"   {res['snippet']}")
    return "\n".join(lines)


@mcp.tool()
async def get_context(query: str, k: int = 5) -> str:
    """
    Retrieve rich context from the knowledge base for a given topic.

    Returns full article bodies (frontmatter stripped) ranked by relevance,
    separated by horizontal rules. Ideal for injecting into an agent's prompt
    as background knowledge.

    Args:
        query: The topic or question you need context for
        k:     Number of articles to include (default 5)
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{VANILLA_URL}/context",
            params={"q": query, "k": k},
        )
        r.raise_for_status()
        data = r.json()

    context = data.get("context", "")
    sources = data.get("sources", [])

    if not context:
        return f"No context found for: {query!r}"

    footer = "\n\nSources: " + ", ".join(s["title"] for s in sources)
    return context + footer


@mcp.tool()
async def get_related_concepts(
    concept: str,
    relationship_type: str = "",
    depth: int = 1,
) -> str:
    """
    Traverse the knowledge graph to find concepts related to a given one.

    Args:
        concept:           Node ID of the concept (slug, e.g. "transformer-architecture")
        relationship_type: Filter by type: uses, is-a, derived-from, extends,
                           contrasts-with, implements, part-of, related-to.
                           Leave empty for all relationship types.
        depth:             1 = direct neighbors, 2 = include second-hop neighbors
    """
    params: dict = {"depth": depth}
    if relationship_type:
        params["type"] = relationship_type

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{VANILLA_URL}/wiki/graph/concepts/{concept}/neighbors",
            params=params,
        )
        if r.status_code == 404:
            return f"Concept {concept!r} not found in the knowledge graph."
        r.raise_for_status()
        data = r.json()

    neighbors = data.get("neighbors", [])
    if not neighbors:
        rel_note = f" with relationship type '{relationship_type}'" if relationship_type else ""
        return f"No related concepts found for {concept!r}{rel_note}."

    hop1 = [n for n in neighbors if n.get("hop", 1) == 1]
    hop2 = [n for n in neighbors if n.get("hop") == 2]

    lines = [f"Concepts related to **{concept}** ({len(neighbors)} total):\n"]

    if hop1:
        lines.append("**Direct relationships:**")
        for n in hop1:
            direction = "->" if n.get("direction") == "outbound" else "<-"
            cat = f" [{n.get('category', '')}]" if n.get("category") else ""
            lines.append(f"  {direction} **{n['label']}**{cat}  [{n.get('relationship', '')}]")

    if hop2:
        lines.append("\n**Second-hop (depth 2):**")
        for n in hop2:
            cat = f" [{n.get('category', '')}]" if n.get("category") else ""
            lines.append(f"  · **{n['label']}**{cat}  [{n.get('relationship', '')}]")

    return "\n".join(lines)


@mcp.tool()
async def list_concepts(category: str = "") -> str:
    """
    List all concepts in the knowledge base.

    Args:
        category: Optional filter — one of: concept, model, method, algorithm,
                  event, person, organization, tool, general.
                  Leave empty to list everything.
    """
    params = {"category": category} if category else {}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{VANILLA_URL}/wiki/graph/concepts",
            params=params,
        )
        r.raise_for_status()
        data = r.json()

    concepts = data.get("concepts", [])
    total = data.get("total", 0)

    if not concepts:
        note = f" in category '{category}'" if category else ""
        return f"No concepts found{note}."

    cat_note = f" (category: {category})" if category else ""
    lines = [f"Knowledge base{cat_note} — {total} concepts:\n"]
    for c in concepts:
        cat = f" [{c['category']}]" if c.get("category") else ""
        rels = c.get("relationship_count", 0)
        rel_note = f"  {rels} relationship{'s' if rels != 1 else ''}" if rels else ""
        lines.append(f"- **{c['label']}**{cat}{rel_note}  `{c['id']}`")

    return "\n".join(lines)


# ─── Entry point ─────────────────────────────────────────────────────────────


async def get_sanitized_tool_defs() -> list[dict]:
    """Return all MCP tool definitions sanitized for OpenAI function-calling.

    Use when forwarding these tool schemas to an OpenAI-compatible API client:
        tools = await get_sanitized_tool_defs()
        client.chat.completions.create(..., tools=tools)
    """
    tools = await mcp.list_tools()
    raw = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.parameters or {"type": "object", "properties": {}, "required": []},
            },
        }
        for t in tools
    ]
    return sanitize_all_tools(raw)


if __name__ == "__main__":
    mcp.run()
