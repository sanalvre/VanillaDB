"""Review Agent — checks proposals against existing wiki for quality issues."""

import json
import logging
from typing import TYPE_CHECKING

from services.tracing import trace_agent

if TYPE_CHECKING:
    from config_loader import AgentsConfig

logger = logging.getLogger("vanilla.review")

REVIEW_SYSTEM_PROMPT = """\
You are a knowledge base reviewer. You receive a drafted wiki article and existing wiki context.
Your job is to identify quality issues:

1. DUPLICATE: Does this concept already exist under a different name?
2. CONTRADICTION: Does any claim contradict an existing article?
3. MISSING_RELATIONSHIP: Are there obvious relationships to existing concepts not captured?
4. FACTUAL_CONCERN: Are any claims unsupported or likely hallucinated?
5. MERGE_CANDIDATE: Should this be merged with an existing concept instead of being new?

Respond with a JSON array of issues. If no issues, return an empty array [].
Each issue: {"type": "DUPLICATE|CONTRADICTION|MISSING_RELATIONSHIP|FACTUAL_CONCERN|MERGE_CANDIDATE", "description": "...", "related_concept": "..."}
Return ONLY the JSON array, no other text.\
"""


async def run_review_agent(
    draft_article: str,
    wiki_context: str,
    config: "AgentsConfig",
    run_id: str,
    llm_caller,  # callable(model, messages, temperature, max_tokens) -> str
) -> list[dict]:
    """Review a proposed article against existing wiki context.

    Returns a list of issue dicts (empty list if the draft is clean).
    Uses config.review settings. Returns [] immediately if review is disabled.
    """
    review_cfg = config.review
    if not review_cfg.enabled:
        return []

    context_snippet = wiki_context[: review_cfg.max_context_tokens]

    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Draft article to review:\n\n{draft_article}\n\n"
                f"## Existing wiki context (relevant excerpts):\n\n{context_snippet}\n\n"
                "Review the draft and return a JSON array of issues."
            ),
        },
    ]

    with trace_agent(run_id, "review", review_cfg.model) as trace:
        trace.emit_progress("Reviewing draft article for quality issues…")
        try:
            content = await llm_caller(
                model=review_cfg.model,
                messages=messages,
                temperature=review_cfg.temperature,
                max_tokens=review_cfg.max_tokens,
            )
        except Exception as e:
            logger.warning("Review agent failed: %s", e)
            return []

        trace.set_response_preview(content[:500])

        try:
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
            issues = json.loads(clean)
            if not isinstance(issues, list):
                issues = []
        except json.JSONDecodeError:
            logger.warning("Review agent returned invalid JSON, ignoring")
            issues = []

        return issues
