"""
Vanilla sidecar configuration.

Manages paths, LLM settings, and runtime config.
All paths are normalized to forward slashes for cross-platform compatibility.
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def _default_data_dir() -> Path:
    """Return the platform-appropriate app data directory."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        # Linux / other POSIX — respect XDG_DATA_HOME if set
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return Path(base) / "vanilla"


# Known embedding model → output dimensions
EMBEDDING_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
}


def get_embedding_dims(model: str) -> int:
    """Return the output dimension count for a known embedding model (default 1536)."""
    return EMBEDDING_DIMS.get(model, 1536)


@dataclass
class LLMConfig:
    provider: str = "openai"  # openai | anthropic | openrouter | ollama
    api_key: str = ""
    base_url: Optional[str] = None  # for Ollama: http://localhost:11434
    models: dict = field(default_factory=lambda: {
        "ingest": "gpt-4o-mini",
        "analysis": "gpt-4o-mini",
        "proposal": "gpt-4o",
        "fileback": "gpt-4o-mini",
    })
    max_tokens_per_run: int = 20000
    # Embedding model used for semantic search and RAG
    # OpenAI: "text-embedding-3-small" (1536 dims, cheap)
    # Ollama:  "nomic-embed-text" (768 dims, free/local)
    embedding_model: str = "text-embedding-3-small"
    # Optional separate OpenAI key for Whisper audio transcription.
    # When set, overrides provider-based transcription resolution.
    # Useful when using OpenRouter/Anthropic as the LLM provider but still
    # wanting server-side Whisper transcription.
    transcription_api_key: Optional[str] = None
    # Optional Groq key for Whisper transcription (whisper-large-v3, free tier).
    # Used as a fallback when no OpenAI transcription key is available.
    groq_transcription_key: Optional[str] = None

    @property
    def embedding_dims(self) -> int:
        """Output dimension count for the configured embedding model."""
        return get_embedding_dims(self.embedding_model)


@dataclass
class VanillaConfig:
    clean_vault_path: Optional[str] = None
    wiki_vault_path: Optional[str] = None
    data_dir: Path = field(default_factory=_default_data_dir)
    llm: LLMConfig = field(default_factory=LLMConfig)
    initialized: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vanilla.db"

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.json"

    def save(self) -> None:
        """Persist config to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "clean_vault_path": self.clean_vault_path,
            "wiki_vault_path": self.wiki_vault_path,
            "initialized": self.initialized,
            "llm": {
                "provider": self.llm.provider,
                "api_key": self.llm.api_key,
                "base_url": self.llm.base_url,
                "models": self.llm.models,
                "max_tokens_per_run": self.llm.max_tokens_per_run,
                "embedding_model": self.llm.embedding_model,
                "transcription_api_key": self.llm.transcription_api_key,
                "groq_transcription_key": self.llm.groq_transcription_key,
            },
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "VanillaConfig":
        """Load config from disk, or return defaults."""
        config = cls()
        if config.config_file.exists():
            with open(config.config_file) as f:
                data = json.load(f)
            config.clean_vault_path = data.get("clean_vault_path")
            config.wiki_vault_path = data.get("wiki_vault_path")
            config.initialized = data.get("initialized", False)
            llm_data = data.get("llm", {})
            config.llm = LLMConfig(
                provider=llm_data.get("provider", "openai"),
                api_key=llm_data.get("api_key", ""),
                base_url=llm_data.get("base_url"),
                models=llm_data.get("models", LLMConfig().models),
                max_tokens_per_run=llm_data.get("max_tokens_per_run", 20000),
                embedding_model=llm_data.get("embedding_model", "text-embedding-3-small"),
                transcription_api_key=llm_data.get("transcription_api_key"),
                groq_transcription_key=llm_data.get("groq_transcription_key"),
            )
        return config
