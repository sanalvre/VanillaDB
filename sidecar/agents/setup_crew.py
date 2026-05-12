"""
Setup Crew — generates ontology.md and AGENTS.md from a vault description.

This is a direct LLM call implementation.  It can be upgraded to a full
CrewAI crew later once CrewAI is installed.
"""

import json
import logging
import re
from typing import Optional

from services.llm_service import chat_completion

logger = logging.getLogger("vanilla.setup_crew")

SYSTEM_PROMPT = """\
You are an expert knowledge-base architect for **Vanilla**, a personal \
knowledge management tool that maintains two Obsidian vaults:

1. **clean-vault** — the user's raw source material (notes, highlights, PDFs).
2. **wiki-vault** — an AI-curated wiki of interconnected articles generated \
from the clean-vault.

Your job is to design the **ontology** (category taxonomy and rules) and the \
**agent configuration** for a new Vanilla workspace based on the user's \
description of what they want to store.

Return your answer as a single JSON object with exactly these three keys:

{
  "ontology_md": "<full Markdown content for ontology.md>",
  "agents_md": "<full Markdown content for AGENTS.md>",
  "suggested_categories": ["cat1", "cat2", "cat3"]
}

### Guidelines for ontology.md
- Start with a YAML front-matter block containing `version: 1`.
- Include a **Categories** section listing 3-8 top-level categories relevant \
to the user's domain, each with a short description.
- Include a **Naming Conventions** section with rules for file naming.
- Include a **Linking Rules** section describing when and how wiki articles \
should cross-reference each other.
- Keep it practical, concise, and Markdown-formatted.

### Guidelines for AGENTS.md
- Define 3-5 agent roles (e.g., Librarian, Analyst, Writer, Reviewer).
- Each role should have: name, goal, backstory (1 sentence), and which LLM \
model tier to use (fast / balanced / quality).
- Use Markdown headers and bullet lists.

### Guidelines for suggested_categories
- Provide 3-5 concise category names (single words or short phrases).
- These should be the most important top-level categories from the ontology.

Return ONLY the JSON object, no extra text before or after it.\
"""


async def generate_ontology(
    description: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> dict:
    """
    Generate ontology.md, AGENTS.md, and category suggestions from a
    user-supplied vault description.

    Returns {
        "ontology_md": str,
        "agents_md": str,
        "suggested_categories": list[str],
    }
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Here is my description of what I want to store in my "
                f"knowledge base:\n\n{description}"
            ),
        },
    ]

    logger.info("Generating ontology via %s/%s", provider, model)

    raw = await chat_completion(
        provider=provider,
        api_key=api_key,
        model=model,
        messages=messages,
        base_url=base_url,
        max_tokens=4096,
        temperature=0.7,
    )

    return _parse_response(raw)


def _parse_response(raw: str) -> dict:
    """
    Extract the JSON object from the LLM response.

    Handles cases where the model wraps its answer in ```json fences.
    """
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        # Remove closing fence
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: try to find a JSON object in the text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            data = json.loads(match.group())
        else:
            logger.error("Failed to parse LLM response as JSON: %s", raw[:500])
            raise ValueError("LLM did not return valid JSON. Please try again.")

    # Validate required keys
    result = {
        "ontology_md": data.get("ontology_md", ""),
        "agents_md": data.get("agents_md", ""),
        "suggested_categories": data.get("suggested_categories", []),
    }

    if not result["ontology_md"]:
        raise ValueError("LLM response missing ontology_md content")
    if not result["agents_md"]:
        raise ValueError("LLM response missing agents_md content")

    return result
