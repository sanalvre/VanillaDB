"""
Supervised browser research service.

User submits a topic or URL → pages are fetched and cleaned →
structured markdown is written to clean-vault/raw/research/ →
the normal agent pipeline picks it up and creates wiki proposals.

Graceful fallbacks:
  1. Playwright + Chromium (best — handles JS-heavy pages)
  2. crawl4ai (good — async, lightweight)
  3. httpx (basic — no JS, but always available)

DuckDuckGo search via the ddg-search lite API (no auth needed).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import VanillaConfig

logger = logging.getLogger("vanilla.browser_research")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ResearchResult:
    pages_fetched: int
    output_paths: list[str]
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 60) -> str:
    """Convert arbitrary text to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len] or "research"


async def _ddg_search(query: str, max_results: int = 10) -> list[str]:
    """
    DuckDuckGo web search — returns a list of result URLs.

    Primary:  ddgs / duckduckgo-search library (real organic results).
    Fallback: DDG instant-answer API (works for Wikipedia/factual topics).
    """
    # Primary: real web search via ddgs library
    for mod_name, cls_path in [("ddgs", "ddgs.DDGS"), ("duckduckgo_search", "duckduckgo_search.DDGS")]:
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            DDGS = mod.DDGS

            def _sync_search() -> list[str]:
                return [r["href"] for r in DDGS().text(query, max_results=max_results)]

            urls = await asyncio.get_event_loop().run_in_executor(None, _sync_search)
            if urls:
                logger.debug("DDG text search returned %d URLs for %r", len(urls), query)
                return urls
        except ImportError:
            continue
        except Exception as exc:
            logger.warning("DDG text search failed for %r: %s", query, exc)
            break

    # Fallback: instant-answer API (good for well-known topics only)
    import httpx
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "no_redirect": "1",
        "skip_disambig": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get("https://api.duckduckgo.com/", params=params)
            resp.raise_for_status()
            data = resp.json()

        urls = []
        for item in data.get("RelatedTopics", []):
            url = item.get("FirstURL", "")
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= max_results:
                break

        abstract_url = data.get("AbstractURL", "")
        if not urls and abstract_url:
            urls.append(abstract_url)

        if urls:
            return urls
    except Exception as exc:
        logger.warning("DDG instant-answer API failed for %r: %s", query, exc)

    return []


# ---------------------------------------------------------------------------
# Page fetching — three-tier fallback
# ---------------------------------------------------------------------------

async def _fetch_page_playwright(url: str) -> str:
    """Fetch page HTML using Playwright Chromium."""
    from playwright.async_api import async_playwright  # type: ignore

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        html = await page.content()
        await browser.close()
    return html


async def _fetch_page_crawl4ai(url: str) -> str:
    """Fetch page text using crawl4ai if installed."""
    from crawl4ai import AsyncWebCrawler  # type: ignore

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
        return result.markdown or result.html or ""


async def _fetch_page_httpx(url: str) -> str:
    """Minimal httpx fallback — static pages only."""
    import httpx

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; VanillaDB/1.0; "
                "+https://github.com/sanalvre/VanillaDB)"
            )
        }
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text


async def fetch_page(url: str) -> str:
    """Try each fetcher in order; return raw text/HTML."""
    for name, fetcher in [
        ("playwright", _fetch_page_playwright),
        ("crawl4ai", _fetch_page_crawl4ai),
        ("httpx", _fetch_page_httpx),
    ]:
        try:
            content = await fetcher(url)
            logger.debug("Fetched %s via %s (%d chars)", url, name, len(content))
            return content
        except ImportError:
            logger.debug("Fetcher %s not installed, trying next", name)
        except Exception as exc:
            logger.warning("Fetcher %s failed for %s: %s", name, url, exc)

    raise RuntimeError(f"All fetchers failed for {url}")


# ---------------------------------------------------------------------------
# HTML → markdown extraction (simple regex strip when no LLM)
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """Very rough HTML-to-text: strip tags, collapse whitespace."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = (
        text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
    )
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text))
    return text.strip()


async def _llm_extract(raw: str, url: str, config: "VanillaConfig") -> dict:
    """
    Use the configured LLM to extract structured content from raw page text.
    Returns: {title, summary, key_concepts, citation_urls, body_md}
    Falls back to naive extraction if LLM is unavailable.
    """
    # Trim to avoid blowing out context windows (≈6000 chars ≈ 1500 tokens)
    snippet = raw[:6000]

    try:
        from services.llm_service import chat_completion

        prompt = (
            "You are a research assistant. Given the following web page text, "
            "extract structured information.\n\n"
            f"URL: {url}\n\n"
            f"PAGE TEXT (truncated):\n{snippet}\n\n"
            "Respond ONLY with valid JSON (no markdown fences) with these keys:\n"
            "  title         - page title (string)\n"
            "  summary       - 2-3 sentence summary (string)\n"
            "  key_concepts  - list of 3-8 key concept strings\n"
            "  citation_urls - list of important outbound URLs found in the text\n"
            "  body_md       - the main content rewritten as clean markdown prose\n"
        )

        model = config.llm.models.get("ingest", "gpt-4o-mini")
        raw_json = await chat_completion(
            provider=config.llm.provider,
            api_key=config.llm.api_key,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            base_url=config.llm.base_url,
            max_tokens=1500,
            temperature=0.1,
        )

        import json
        # Strip markdown fences if the LLM added them anyway
        raw_json = re.sub(r"^```(?:json)?\s*", "", raw_json.strip(), flags=re.IGNORECASE)
        raw_json = re.sub(r"\s*```$", "", raw_json.strip())
        extracted = json.loads(raw_json)
        return extracted

    except Exception as exc:
        logger.warning("LLM extraction failed for %s: %s — using naive fallback", url, exc)

    # Naive fallback
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    title = lines[0][:120] if lines else url
    body = "\n\n".join(lines[:40])
    return {
        "title": title,
        "summary": body[:300],
        "key_concepts": [],
        "citation_urls": [],
        "body_md": body,
    }


# ---------------------------------------------------------------------------
# Write extracted content to clean-vault
# ---------------------------------------------------------------------------

def _write_research_file(
    clean_vault_path: str,
    slug: str,
    url: str,
    extracted: dict,
) -> str:
    """
    Write structured research content to clean-vault/raw/research/{slug}.md
    Returns the vault-relative path written.
    """
    research_dir = Path(clean_vault_path) / "raw" / "research"
    research_dir.mkdir(parents=True, exist_ok=True)

    # Ensure unique filename if slug already exists
    filename = f"{slug}.md"
    dest = research_dir / filename
    if dest.exists():
        ts = int(time.time())
        filename = f"{slug}-{ts}.md"
        dest = research_dir / filename

    title = extracted.get("title", slug)
    summary = extracted.get("summary", "")
    key_concepts = extracted.get("key_concepts", [])
    body_md = extracted.get("body_md", "")

    concepts_yaml = "\n".join(f"  - {c}" for c in key_concepts) if key_concepts else ""
    concepts_section = f"key_concepts:\n{concepts_yaml}" if concepts_yaml else "key_concepts: []"

    content = (
        f"---\n"
        f"title: {title}\n"
        f"source_url: {url}\n"
        f"fetched_at: {int(time.time())}\n"
        f"{concepts_section}\n"
        f"---\n\n"
        f"## Summary\n\n{summary}\n\n"
        f"## Content\n\n{body_md}\n"
    )

    dest.write_text(content, encoding="utf-8")
    vault_rel = f"clean-vault/raw/research/{filename}"
    logger.info("Wrote research file: %s", vault_rel)
    return vault_rel


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def research_topic(
    topic: str,
    config: "VanillaConfig",
    max_pages: int = 5,
    follow_citations: bool = True,
) -> ResearchResult:
    """
    Research a topic:
      1. DuckDuckGo search → top URLs
      2. Fetch + extract each URL
      3. Write to clean-vault/raw/research/
      4. If follow_citations: queue citation URLs (depth 1, up to max_pages total)
    """
    if not config.clean_vault_path:
        raise ValueError("clean_vault_path not configured")

    urls = await _ddg_search(topic, max_results=max_pages)
    if not urls:
        raise ValueError(
            f"No search results found for {topic!r}. "
            "Try rephrasing the topic, or switch to URL mode to research a specific page."
        )

    output_paths: list[str] = []
    errors: list[str] = []
    queued_citations: list[str] = []
    seen_urls: set[str] = set(urls)

    async def _process_url(url: str) -> None:
        try:
            raw = await fetch_page(url)
            # If raw looks like HTML, strip tags first
            if "<html" in raw.lower() or "<body" in raw.lower():
                raw = _strip_html(raw)
            extracted = await _llm_extract(raw, url, config)

            # Queue citations for later (depth 1 only)
            if follow_citations:
                for cit_url in extracted.get("citation_urls", [])[:5]:
                    if cit_url not in seen_urls and cit_url.startswith("http"):
                        seen_urls.add(cit_url)
                        queued_citations.append(cit_url)

            slug = _slugify(extracted.get("title", "") or topic)
            # Avoid slug collision by appending URL hash
            url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
            slug = f"{slug}-{url_hash}"

            path = _write_research_file(config.clean_vault_path, slug, url, extracted)
            output_paths.append(path)
        except Exception as exc:
            logger.error("Failed to process URL %s: %s", url, exc)
            errors.append(f"{url}: {exc}")

    # Process primary URLs
    tasks = [_process_url(url) for url in urls[:max_pages]]
    await asyncio.gather(*tasks)

    # Process citations if we have budget left
    remaining = max_pages - len(urls)
    if follow_citations and queued_citations and remaining > 0:
        citation_tasks = [_process_url(u) for u in queued_citations[:remaining]]
        await asyncio.gather(*citation_tasks)

    return ResearchResult(
        pages_fetched=len(output_paths),
        output_paths=output_paths,
        errors=errors,
    )


async def research_url(url: str, config: "VanillaConfig") -> ResearchResult:
    """Research a single URL."""
    if not config.clean_vault_path:
        raise ValueError("clean_vault_path not configured")

    try:
        raw = await fetch_page(url)
        if "<html" in raw.lower() or "<body" in raw.lower():
            raw = _strip_html(raw)
        extracted = await _llm_extract(raw, url, config)
        slug = _slugify(extracted.get("title", "") or url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
        slug = f"{slug}-{url_hash}"
        path = _write_research_file(config.clean_vault_path, slug, url, extracted)
        return ResearchResult(pages_fetched=1, output_paths=[path])
    except Exception as exc:
        logger.error("research_url failed for %s: %s", url, exc)
        return ResearchResult(pages_fetched=0, output_paths=[], errors=[str(exc)])
