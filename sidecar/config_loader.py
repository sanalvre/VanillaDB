"""Load per-agent configuration from agents.toml.

This augments the runtime VanillaConfig.llm.models dict with TOML-defined
model overrides and agent-level settings (temperature, timeouts, tools).
"""

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]  # Python < 3.11
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

USER_CONFIG_PATH = Path.home() / ".vanilla" / "agents.toml"
FALLBACK_CONFIG_PATH = Path(__file__).parent.parent / "agents.default.toml"


@dataclass
class AgentConfig:
    model: str = "gpt-4o-mini"
    temperature: float = 0.4
    max_tokens: int = 4000
    timeout_seconds: int = 120
    max_turns: int = 5
    max_context_tokens: int = 12000
    tools: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class PipelineConfig:
    debounce_seconds: int = 300
    hash_check: bool = True


@dataclass
class AgentsConfig:
    pipeline: PipelineConfig
    ingest: AgentConfig
    analysis: AgentConfig
    proposal: AgentConfig
    review: AgentConfig
    fileback: AgentConfig


def load_config() -> AgentsConfig:
    """Load agent config from ~/.vanilla/agents.toml, falling back to agents.default.toml."""
    path: Optional[Path] = None
    if USER_CONFIG_PATH.exists():
        path = USER_CONFIG_PATH
    elif FALLBACK_CONFIG_PATH.exists():
        path = FALLBACK_CONFIG_PATH

    raw: dict = {}
    if path:
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    pipeline_raw = raw.get("pipeline", {})
    agents_raw = raw.get("agents", {})

    return AgentsConfig(
        pipeline=_parse_pipeline(pipeline_raw),
        ingest=_parse_agent(agents_raw.get("ingest", {})),
        analysis=_parse_agent(
            agents_raw.get("analysis", {}),
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            tools=["vault_stats", "concept_search", "graph_neighbors", "concept_staleness"],
        ),
        proposal=_parse_agent(
            agents_raw.get("proposal", {}),
            model="claude-opus-4-6",
            max_tokens=8000,
            timeout_seconds=180,
            tools=["concept_search", "run_code", "graph_stats"],
        ),
        review=_parse_agent(
            agents_raw.get("review", {}),
            model="claude-sonnet-4-20250514",
            max_turns=1,
            tools=["concept_search", "graph_neighbors"],
        ),
        fileback=_parse_agent(agents_raw.get("fileback", {}), timeout_seconds=30),
    )


def _parse_pipeline(raw: dict) -> PipelineConfig:
    valid = {f for f in PipelineConfig.__dataclass_fields__}
    return PipelineConfig(**{k: v for k, v in raw.items() if k in valid})


def _parse_agent(raw: dict, **defaults) -> AgentConfig:
    base = {f: getattr(AgentConfig(), f) for f in AgentConfig.__dataclass_fields__}
    base.update(defaults)
    base.update({k: v for k, v in raw.items() if k in AgentConfig.__dataclass_fields__})
    return AgentConfig(**base)
