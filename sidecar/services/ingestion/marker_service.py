"""
Marker PDF conversion service.

Converts structured/book-like PDFs to markdown using the Marker library.
Marker works on CPU (no GPU required) and handles:
- Clear heading hierarchy
- Chapter/section structure
- Standard layouts

For academic papers with complex tables or multi-column layouts,
MinerU (mineru_service.py) may produce better results when GPU is available.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger("vanilla.ingestion.marker")


async def convert_pdf_marker(pdf_path: str, output_path: str) -> str:
    """
    Convert a PDF to markdown using Marker.

    Runs in a thread executor since Marker is synchronous and CPU-intensive.

    Args:
        pdf_path: Path to the source PDF file
        output_path: Desired path for the output .md file

    Returns:
        The actual output path (may differ slightly from requested)

    Raises:
        ImportError: If marker-pdf is not installed
        RuntimeError: If conversion fails
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _convert_sync, pdf_path, output_path)


def _convert_sync(pdf_path: str, output_path: str) -> str:
    """Synchronous Marker conversion (runs in executor thread)."""
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        logger.info("Converting PDF with Marker: %s", pdf_path)

        models = create_model_dict()
        converter = PdfConverter(artifact_dict=models)
        rendered = converter(pdf_path)

        # rendered.markdown contains the converted text
        markdown_text = rendered.markdown

        # Write output
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown_text, encoding="utf-8")

        logger.info("Marker conversion complete: %s -> %s", pdf_path, output_path)
        return str(output)

    except ImportError:
        raise ImportError(
            "marker-pdf is not installed. Install with: pip install marker-pdf"
        )
    except Exception as e:
        raise RuntimeError(f"Marker PDF conversion failed for {pdf_path}: {e}") from e
