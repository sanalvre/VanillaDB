"""
Ingestion normalizer — routes files to the correct conversion service.

All inputs are normalized to markdown before the agent ever sees them:
- .md files: passed through (copied to raw/)
- .pdf files: routed to Marker or MinerU based on document structure
- URLs: fetched via Firecrawl (online-only)

Output always lands in clean-vault/raw/{stem}.md with FTS5 indexing.
"""

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from services.paths import normalize_path

logger = logging.getLogger("vanilla.ingestion")


@dataclass
class IngestResult:
    """Result of an ingestion operation."""
    success: bool
    output_path: str  # Normalized relative path (e.g., clean-vault/raw/paper.md)
    title: str
    body: str  # Full text content for FTS indexing
    source_type: str  # "pdf" | "url" | "md"
    error: Optional[str] = None


def detect_source_type(file_path: str) -> Literal["pdf", "md", "unknown"]:
    """Detect the source type from a file path."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in (".md", ".markdown", ".txt"):
        return "md"
    return "unknown"


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:80]  # Cap at 80 chars


def extract_title_from_markdown(content: str) -> str:
    """Extract the first heading from markdown content, or use first line."""
    in_frontmatter = False
    first_content_line = None

    for line in content.split("\n"):
        stripped = line.strip()

        # Track YAML frontmatter blocks (--- delimited)
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue

        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped and first_content_line is None:
            first_content_line = stripped[:100]

    return first_content_line or "Untitled"


async def ingest_markdown(
    source_path: str,
    clean_vault_path: str,
) -> IngestResult:
    """
    Ingest a markdown file — copy to clean-vault/raw/.

    If the source is already in clean-vault, skip the copy.
    """
    source = Path(source_path)
    if not source.exists():
        return IngestResult(
            success=False, output_path="", title="", body="",
            source_type="md", error=f"File not found: {source_path}",
        )

    content = source.read_text(encoding="utf-8", errors="replace")
    title = extract_title_from_markdown(content)

    # Determine output path
    raw_dir = Path(clean_vault_path) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Use original filename, dedup if needed
    output_name = source.name
    output_path = raw_dir / output_name
    if output_path.exists() and output_path.resolve() != source.resolve():
        stem = source.stem
        output_name = f"{stem}_{int(time.time())}.md"
        output_path = raw_dir / output_name

    # Copy if source is not already in raw/
    if output_path.resolve() != source.resolve():
        shutil.copy2(str(source), str(output_path))

    vault_root = str(Path(clean_vault_path).parent)
    rel_path = normalize_path(os.path.relpath(str(output_path), vault_root))

    return IngestResult(
        success=True,
        output_path=rel_path,
        title=title,
        body=content,
        source_type="md",
    )


async def ingest_pdf(
    source_path: str,
    clean_vault_path: str,
    gpu_available: bool = False,
) -> IngestResult:
    """
    Ingest a PDF — convert to markdown via Marker (or MinerU if GPU available).

    Falls back to Marker on any MinerU failure or when no GPU is present.
    """
    source = Path(source_path)
    if not source.exists():
        return IngestResult(
            success=False, output_path="", title="", body="",
            source_type="pdf", error=f"File not found: {source_path}",
        )

    raw_dir = Path(clean_vault_path) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_stem = source.stem
    output_path = raw_dir / f"{output_stem}.md"
    if output_path.exists():
        output_stem = f"{output_stem}_{int(time.time())}"
        output_path = raw_dir / f"{output_stem}.md"

    # Try Marker first (works on all hardware)
    try:
        from services.ingestion.marker_service import convert_pdf_marker
        result_path = await convert_pdf_marker(str(source), str(output_path))
        content = Path(result_path).read_text(encoding="utf-8", errors="replace")
        title = extract_title_from_markdown(content)

        vault_root = str(Path(clean_vault_path).parent)
        rel_path = normalize_path(os.path.relpath(result_path, vault_root))

        return IngestResult(
            success=True,
            output_path=rel_path,
            title=title,
            body=content,
            source_type="pdf",
        )
    except ImportError:
        logger.warning("Marker not installed; PDF ingestion unavailable")
        return IngestResult(
            success=False, output_path="", title="", body="",
            source_type="pdf",
            error="Marker (marker-pdf) is not installed. Install with: pip install marker-pdf",
        )
    except Exception as e:
        logger.error("Marker PDF conversion failed: %s", e)
        return IngestResult(
            success=False, output_path="", title="", body="",
            source_type="pdf", error=f"PDF conversion failed: {str(e)}",
        )


async def ingest_url(
    url: str,
    clean_vault_path: str,
    firecrawl_api_key: Optional[str] = None,
) -> IngestResult:
    """
    Ingest a URL — fetch and convert to markdown via Firecrawl.

    This is online-only. Returns an error if Firecrawl is unavailable.
    """
    raw_dir = Path(clean_vault_path) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        from services.ingestion.firecrawl_service import fetch_url
        content, title = await fetch_url(url, api_key=firecrawl_api_key)

        # Generate filename from title or URL
        slug = slugify(title or url.split("/")[-1] or "page")
        output_name = f"{slug}.md"
        output_path = raw_dir / output_name
        if output_path.exists():
            output_name = f"{slug}_{int(time.time())}.md"
            output_path = raw_dir / output_name

        # Write the markdown with source URL in frontmatter
        full_content = f"---\nsource_url: {url}\nfetched: {time.strftime('%Y-%m-%d')}\n---\n\n{content}"
        output_path.write_text(full_content, encoding="utf-8")

        vault_root = str(Path(clean_vault_path).parent)
        rel_path = normalize_path(os.path.relpath(str(output_path), vault_root))

        return IngestResult(
            success=True,
            output_path=rel_path,
            title=title or slug,
            body=content,
            source_type="url",
        )
    except ImportError:
        return IngestResult(
            success=False, output_path="", title="", body="",
            source_type="url",
            error="Firecrawl (firecrawl-py) is not installed. Install with: pip install firecrawl-py",
        )
    except Exception as e:
        logger.error("URL ingestion failed: %s", e)
        return IngestResult(
            success=False, output_path="", title="", body="",
            source_type="url", error=f"URL fetch failed: {str(e)}",
        )
