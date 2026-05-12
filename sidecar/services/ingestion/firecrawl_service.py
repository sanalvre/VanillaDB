"""
Web scraping service — cascading scraper with multiple backends.

Priority order:
  0. GitHub API   (auto-detected) — free, no key, fetches README + repo metadata directly
  1. Firecrawl   (if api_key provided) — best quality, paid, handles most sites
  2. Crawl4AI    (if installed)        — Playwright-based, handles JS-heavy SPAs, free
                                         Only available when running sidecar from raw Python;
                                         not bundled in the PyInstaller binary due to Playwright size.
  3. Jina Reader (always available)    — r.jina.ai proxy, free, no API key, handles JS via Jina's infra

All backends return (markdown_content, page_title).
"""

import base64
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("vanilla.ingestion.firecrawl")

# ── Content quality guard ─────────────────────────────────────────────────────

# Phrases that indicate the scraper got a bot-gate / JS-wall instead of the
# real page.  All checked case-insensitively against the first 2 000 chars of
# the returned content (the error is almost always near the top).
_BOT_GATE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"javascript\s+(is\s+)?(not\s+enabled|disabled|required|must\s+be\s+enabled)",
        r"please\s+enable\s+javascript",
        r"enable\s+javascript\s+to\s+continue",
        r"you\s+need\s+to\s+enable\s+javascript",
        r"this\s+site\s+requires\s+javascript",
        r"verify\s+(you\s+are|that\s+you('re|\s+are))\s+(a\s+)?human",
        r"checking\s+your\s+browser",
        r"ddos.{0,30}protection",
        r"access\s+denied",
        r"403\s+forbidden",
        r"<noscript>",          # raw noscript tag leaking through
    ]
]

_MIN_CONTENT_CHARS = 200  # anything shorter than this is almost certainly a gate page


def _is_bot_gate(content: str) -> str | None:
    """
    Return a human-readable reason string if `content` looks like a bot-gate
    or JS-disabled wall, or None if the content looks legitimate.
    """
    sample = content[:2_000]
    for pat in _BOT_GATE_PATTERNS:
        m = pat.search(sample)
        if m:
            return f"bot-gate detected: matched pattern '{pat.pattern}' near: …{m.group()!r}…"
    if len(content.strip()) < _MIN_CONTENT_CHARS:
        return f"content too short ({len(content.strip())} chars) — likely a gate page"
    return None

# Matches: github.com/{owner}/{repo}[/blob/{branch}/{path}][/tree/{branch}/{path}]
_GITHUB_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/?#]+)"
    r"(?:/(?P<kind>blob|tree)/(?P<branch>[^/]+)/(?P<path>.+))?",
    re.IGNORECASE,
)


def _is_github_url(url: str) -> bool:
    return bool(_GITHUB_RE.search(url))


async def fetch_url(url: str, api_key: Optional[str] = None) -> Tuple[str, str]:
    """
    Fetch a URL and return (markdown_content, title).

    Tries backends in priority order:
      GitHub API → Firecrawl → Crawl4AI → Jina Reader.
    Raises RuntimeError only if all backends fail.
    """
    # 0. GitHub API — free, rich content for any public repo/file URL
    if _is_github_url(url):
        try:
            return await _fetch_github(url)
        except Exception as e:
            logger.warning("GitHub fetch failed (%s), falling back to general scrapers", e)

    # 1. Firecrawl — highest quality for standard pages
    if api_key:
        try:
            content, title = await _fetch_with_firecrawl(url, api_key)
            reason = _is_bot_gate(content)
            if reason:
                logger.warning("Firecrawl returned a gate page (%s), trying next scraper", reason)
            else:
                return content, title
        except ImportError:
            logger.warning("firecrawl-py not installed, falling back")
        except Exception as e:
            logger.warning("Firecrawl failed (%s), trying next scraper", e)

    # 2. Crawl4AI — Playwright-based, handles JS-heavy sites (dev/power-user only)
    try:
        content, title = await _fetch_with_crawl4ai(url)
        reason = _is_bot_gate(content)
        if reason:
            logger.warning("Crawl4AI returned a gate page (%s), trying Jina Reader", reason)
        else:
            return content, title
    except ImportError:
        pass  # Not installed — expected in production binary
    except Exception as e:
        logger.warning("Crawl4AI failed (%s), trying Jina Reader", e)

    # 3. Jina Reader — reliable free fallback, handles most pages including JS
    try:
        content, title = await _fetch_with_jina(url)
        reason = _is_bot_gate(content)
        if reason:
            raise RuntimeError(
                f"Jina Reader returned a gate page ({reason}). "
                "This URL requires JavaScript rendering or blocks bots. "
                "Configure a Firecrawl API key in Settings for better coverage."
            )
        return content, title
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("Jina Reader failed (%s)", e)

    raise RuntimeError(
        f"All scrapers failed for: {url}. "
        "The site may block automated access. "
        "Configure a Firecrawl API key in Settings for more reliable scraping."
    )


async def _fetch_github(url: str) -> Tuple[str, str]:
    """
    Fetch a GitHub repo or file URL using the public GitHub API — no auth required
    for public repos.

    Handles:
      github.com/{owner}/{repo}                        → README + repo metadata
      github.com/{owner}/{repo}/blob/{branch}/{file}  → raw file content
      github.com/{owner}/{repo}/tree/{branch}/{path}  → directory README
    """
    m = _GITHUB_RE.search(url)
    if not m:
        raise ValueError(f"Not a recognisable GitHub URL: {url}")

    owner = m.group("owner")
    repo = m.group("repo").rstrip("/")
    kind = m.group("kind")   # "blob" | "tree" | None
    branch = m.group("branch")
    path = m.group("path")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "VanillaDB/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:

        # ── Specific file (blob) ──────────────────────────────────────
        if kind == "blob" and path:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
            resp = await client.get(raw_url)
            resp.raise_for_status()
            content = resp.text

            # Wrap non-markdown files in a fenced code block
            suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if suffix and suffix != "md":
                lang = suffix
                content = f"```{lang}\n{content}\n```"

            title = f"{owner}/{repo}: {path}"
            return f"# {title}\n\n> Source: {url}\n\n{content}", title

        # ── Repo root or directory ────────────────────────────────────
        # 1. Fetch repo metadata
        repo_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
        repo_resp.raise_for_status()
        meta = repo_resp.json()

        title = meta.get("full_name", f"{owner}/{repo}")
        description = meta.get("description") or ""
        stars = meta.get("stargazers_count", 0)
        language = meta.get("language") or "Unknown"
        topics = meta.get("topics", [])
        homepage = meta.get("homepage") or ""
        default_branch = meta.get("default_branch", "main")

        # 2. Fetch README (use provided branch or default)
        readme_branch = branch or default_branch
        readme_path = f"{path}/README.md" if (kind == "tree" and path) else None

        readme_content = ""
        # Try explicit sub-path first, fall back to repo-root README endpoint
        if readme_path:
            try:
                raw = await client.get(
                    f"https://raw.githubusercontent.com/{owner}/{repo}/{readme_branch}/{readme_path}"
                )
                if raw.status_code == 200:
                    readme_content = raw.text
            except Exception:
                pass

        if not readme_content:
            try:
                readme_resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/readme",
                    params={"ref": readme_branch},
                )
                if readme_resp.status_code == 200:
                    data = readme_resp.json()
                    readme_content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            except Exception:
                pass

        # 3. Build rich markdown document
        parts = [f"# {title}"]
        if description:
            parts.append(f"\n{description}\n")

        meta_lines = [f"- **Language:** {language}", f"- **Stars:** {stars:,}"]
        if homepage:
            meta_lines.append(f"- **Homepage:** {homepage}")
        if topics:
            meta_lines.append(f"- **Topics:** {', '.join(topics)}")
        meta_lines.append(f"- **URL:** {url}")
        parts.append("\n".join(meta_lines))

        if readme_content:
            parts.append(f"\n## README\n\n{readme_content}")
        else:
            parts.append("\n*No README found.*")

        return "\n\n".join(parts), title


async def _fetch_with_firecrawl(url: str, api_key: str) -> Tuple[str, str]:
    """Fetch using the Firecrawl API (firecrawl-py package)."""
    from firecrawl import FirecrawlApp

    logger.info("Fetching with Firecrawl: %s", url)
    app = FirecrawlApp(api_key=api_key)
    result = app.scrape_url(url, params={"formats": ["markdown"]})

    markdown = result.get("markdown", "")
    metadata = result.get("metadata", {})
    title = metadata.get("title") or metadata.get("og:title") or url

    return markdown, title


async def _fetch_with_crawl4ai(url: str) -> Tuple[str, str]:
    """
    Fetch via Crawl4AI — Playwright-based, handles complex JS/SPAs.

    Raises ImportError if crawl4ai is not installed (expected in production binary).
    Install with: pip install crawl4ai && playwright install chromium
    """
    from crawl4ai import AsyncWebCrawler

    logger.info("Fetching with Crawl4AI: %s", url)
    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(url=url)

    if not result.success:
        raise RuntimeError(f"Crawl4AI: {result.error_message}")

    content = result.markdown or ""
    title = url
    if result.metadata:
        title = result.metadata.get("title", url)

    return content, title


async def _fetch_with_jina(url: str) -> Tuple[str, str]:
    """
    Fetch via Jina Reader (r.jina.ai) — free, no API key required.

    Jina renders pages server-side and returns clean markdown.
    Works on most sites including JS-rendered pages. Rate limit: ~20 req/min on free tier.
    """
    jina_url = f"https://r.jina.ai/{url}"
    logger.info("Fetching with Jina Reader: %s", url)

    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers={
            "Accept": "text/markdown, text/plain, */*",
            "User-Agent": "Vanilla/0.1 (Knowledge Base)",
        },
    ) as client:
        resp = await client.get(jina_url)
        resp.raise_for_status()
        content = resp.text

    # Jina prepends metadata lines: "Title: ...\nURL: ...\nPublished: ...\n---\n"
    title = url
    for line in content.splitlines()[:8]:
        if line.lower().startswith("title:"):
            title = line[6:].strip()
            break

    return content, title
