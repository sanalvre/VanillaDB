"""
Provider-aware audio transcription service.

Priority order:
  1. transcription_api_key set in config → OpenAI Whisper API (whisper-1)
  2. provider == "openai" AND api_key set → OpenAI Whisper API
  3. groq_transcription_key set → Groq Whisper API (whisper-large-v3, free tier)
  4. Otherwise → NotImplementedError (frontend shows "add a key" message)
"""

import logging
from typing import TYPE_CHECKING, Optional, Tuple

import httpx

if TYPE_CHECKING:
    from config import VanillaConfig

logger = logging.getLogger("vanilla.transcription")

OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def _resolve_provider(config: "VanillaConfig") -> Tuple[Optional[str], str]:
    """
    Return (api_key, endpoint_url) for the best available transcription provider.
    Returns (None, "") if no provider is configured.
    """
    # 1. Explicit OpenAI transcription key (works with any LLM provider)
    if config.llm.transcription_api_key:
        return config.llm.transcription_api_key, OPENAI_TRANSCRIPTION_URL

    # 2. LLM provider is OpenAI — reuse the main key
    if config.llm.provider == "openai" and config.llm.api_key:
        return config.llm.api_key, OPENAI_TRANSCRIPTION_URL

    # 3. Groq fallback (free tier, whisper-large-v3)
    if config.llm.groq_transcription_key:
        return config.llm.groq_transcription_key, GROQ_TRANSCRIPTION_URL

    return None, ""


def can_transcribe(config: "VanillaConfig") -> bool:
    """Return True if server-side transcription is available (OpenAI or Groq)."""
    key, _ = _resolve_provider(config)
    return key is not None


def _transcription_model(endpoint_url: str) -> str:
    """Return the correct model name for the given endpoint."""
    if "groq" in endpoint_url:
        return "whisper-large-v3"
    return "whisper-1"


async def transcribe_audio(audio_bytes: bytes, config: "VanillaConfig") -> str:
    """
    Transcribe audio bytes to text.

    Tries OpenAI first (if configured), then Groq.
    Raises NotImplementedError if neither is configured.
    Raises ValueError on API errors (bad key, bad audio format).
    Raises RuntimeError on network/timeout errors.
    """
    api_key, endpoint_url = _resolve_provider(config)

    if not api_key:
        raise NotImplementedError(
            "No transcription provider configured. "
            "Add an OpenAI key, Groq key, or set provider=openai in Settings."
        )

    provider_name = "Groq" if "groq" in endpoint_url else "OpenAI"
    model = _transcription_model(endpoint_url)
    logger.debug(
        "Transcribing %d bytes via %s (%s)", len(audio_bytes), provider_name, model
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                endpoint_url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("audio.webm", audio_bytes, "audio/webm")},
                data={"model": model},
            )

            if resp.status_code == 401:
                raise ValueError(
                    f"Invalid {provider_name} API key for transcription — "
                    "check your key in Settings."
                )
            if resp.status_code == 400:
                try:
                    body = resp.json()
                    msg = (body.get("error") or {}).get("message") or resp.text[:200]
                except Exception:
                    msg = resp.text[:200]
                raise ValueError(f"Transcription error: {msg}")
            if resp.status_code == 429:
                raise RuntimeError(
                    f"{provider_name} transcription rate limit — wait a moment and try again."
                )

            resp.raise_for_status()
            return resp.json()["text"]

    except httpx.TimeoutException:
        raise RuntimeError("Transcription timed out — try a shorter recording.")
    except httpx.ConnectError:
        raise RuntimeError(
            f"Could not reach {provider_name} — check your network connection."
        )
    except (ValueError, RuntimeError, NotImplementedError):
        raise
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {e}") from e
