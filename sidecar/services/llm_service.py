"""
LLM connection validation and chat completion service.

Supports OpenAI, Anthropic, OpenRouter, and Ollama providers.
Uses litellm for provider-agnostic calls when available, falls back to httpx.
"""

import logging
from typing import Optional, Tuple

import httpx

logger = logging.getLogger("vanilla.llm_service")

# Try to import litellm; fall back gracefully
try:
    import litellm

    litellm.set_verbose = False
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False
    logger.info("litellm not installed — using httpx fallback for LLM calls")


# Provider -> litellm model prefix mapping
PROVIDER_PREFIX = {
    "openai": "",
    "anthropic": "anthropic/",
    "openrouter": "openrouter/",
    "ollama": "ollama/",
}


def _litellm_model_name(provider: str, model: str) -> str:
    """Build the litellm-style model identifier."""
    prefix = PROVIDER_PREFIX.get(provider, "")
    return f"{prefix}{model}"


async def validate_connection(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Test that the LLM provider is reachable and the credentials are valid.

    Returns (valid, error_message).
    """
    try:
        if provider == "ollama":
            return await _validate_ollama(base_url or "http://localhost:11434")

        # For cloud providers, ensure we have an API key
        if not api_key:
            return False, "API key is required"

        if HAS_LITELLM:
            return await _validate_via_litellm(provider, api_key, base_url, model)
        else:
            return await _validate_via_httpx(provider, api_key, base_url, model)

    except Exception as e:
        logger.error("LLM validation error: %s", e)
        return False, str(e)


async def _validate_ollama(base_url: str) -> Tuple[bool, Optional[str]]:
    """Check that Ollama is running by hitting /api/tags."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            if resp.status_code == 200:
                return True, None
            return False, f"Ollama returned status {resp.status_code}"
    except httpx.ConnectError:
        return False, f"Cannot connect to Ollama at {base_url}"
    except Exception as e:
        return False, f"Ollama check failed: {e}"


async def _validate_via_litellm(
    provider: str,
    api_key: str,
    base_url: Optional[str],
    model: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """Validate by making a tiny chat completion via litellm."""
    import asyncio

    test_model = model or _default_model(provider)
    litellm_model = _litellm_model_name(provider, test_model)

    kwargs: dict = {
        "model": litellm_model,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
        "api_key": api_key,
    }
    if base_url:
        kwargs["api_base"] = base_url

    try:
        resp = await litellm.acompletion(**kwargs)
        return True, None
    except Exception as e:
        return False, str(e)


async def _validate_via_httpx(
    provider: str,
    api_key: str,
    base_url: Optional[str],
    model: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """Validate using raw httpx against an OpenAI-compatible endpoint."""
    test_model = model or _default_model(provider)
    url, headers = _build_request_params(provider, api_key, base_url)

    payload = {
        "model": test_model,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return True, None
            if resp.status_code == 401:
                return False, "Invalid API key — check your credentials and try again."
            if resp.status_code == 403:
                return False, "Access denied — your API key may lack permissions for this model."
            if resp.status_code == 404:
                return False, f"Model '{test_model}' not found. Check the model name for your provider."
            if resp.status_code == 429:
                return False, "Rate limit reached — wait a moment and try again."
            try:
                body = resp.json()
                msg = (body.get("error", {}) or {}).get("message") or str(body)[:200]
            except Exception:
                msg = resp.text[:200]
            return False, f"Connection failed ({resp.status_code}): {msg}"
    except httpx.ConnectError:
        return False, f"Could not reach {provider} — check your network or base URL."
    except httpx.TimeoutException:
        return False, "Connection timed out — the provider may be slow or unreachable."
    except Exception as e:
        return False, str(e)


async def chat_completion(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    base_url: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """
    Make a chat completion call and return the assistant message content.

    Uses litellm when available, otherwise falls back to httpx.
    """
    if HAS_LITELLM:
        return await _completion_litellm(
            provider, api_key, model, messages, base_url, max_tokens, temperature
        )
    else:
        return await _completion_httpx(
            provider, api_key, model, messages, base_url, max_tokens, temperature
        )


async def _completion_litellm(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    base_url: Optional[str],
    max_tokens: int,
    temperature: float,
) -> str:
    litellm_model = _litellm_model_name(provider, model)
    kwargs: dict = {
        "model": litellm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "api_key": api_key,
    }
    if base_url:
        kwargs["api_base"] = base_url

    resp = await litellm.acompletion(**kwargs)
    return resp.choices[0].message.content


async def _completion_httpx(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    base_url: Optional[str],
    max_tokens: int,
    temperature: float,
) -> str:
    url, headers = _build_request_params(provider, api_key, base_url)
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _build_request_params(
    provider: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> Tuple[str, dict]:
    """Return (url, headers) for an OpenAI-compatible chat completions call."""
    headers = {
        "Content-Type": "application/json",
    }

    if provider == "openai":
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "anthropic":
        # Use OpenAI-compatible proxy via litellm's hosted endpoint is not
        # available — for httpx fallback we target Anthropic's messages API
        # wrapped in an OpenAI-compatible adapter.  In practice, litellm
        # handles this; the httpx path targets an OpenAI-compatible endpoint.
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "openrouter":
        url = (base_url or "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "ollama":
        url = (base_url or "http://localhost:11434").rstrip("/") + "/v1/chat/completions"
    else:
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        headers["Authorization"] = f"Bearer {api_key}"

    return url, headers


def _default_model(provider: str) -> str:
    """Fallback model name when none is specified."""
    defaults = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-haiku-4-5",
        "openrouter": "openai/gpt-4o-mini",
        "ollama": "llama3",
    }
    return defaults.get(provider, "gpt-4o-mini")
