"""Pipeline run and agent trace recording."""

import uuid
import time
import json
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Generator

from db.database import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run(source_path: str, triggered_by: str = "watcher", profile: str = "default") -> str:
    """Create a new pipeline_runs record. Returns pipeline_run_id (UUID)."""
    run_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        """INSERT INTO pipeline_runs (id, source_path, triggered_by, profile, started_at, status)
           VALUES (?, ?, ?, ?, ?, 'running')""",
        (run_id, source_path, triggered_by, profile, _now()),
    )
    conn.commit()
    return run_id


def complete_run(
    run_id: str,
    status: str,
    proposal_count: int = 0,
    error_stage: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Mark a pipeline run as completed and roll up token counts from agent_traces."""
    conn = get_connection()
    row = conn.execute(
        """SELECT COALESCE(SUM(tokens_in), 0) as ti,
                  COALESCE(SUM(tokens_out), 0) as to_,
                  COALESCE(SUM(cost_usd), 0.0) as cost
           FROM agent_traces WHERE run_id = ?""",
        (run_id,),
    ).fetchone()

    conn.execute(
        """UPDATE pipeline_runs SET
             finished_at = ?, status = ?, proposal_count = ?,
             total_tokens_in = ?, total_tokens_out = ?, total_cost_usd = ?,
             error_stage = ?, error_message = ?
           WHERE id = ?""",
        (
            _now(), status, proposal_count,
            row["ti"], row["to_"], row["cost"],
            error_stage, error_message, run_id,
        ),
    )
    conn.commit()


def skip_run(source_path: str, reason: str, triggered_by: str = "watcher") -> str:
    """Record a skipped source with reason. Returns run_id."""
    run_id = str(uuid.uuid4())
    now = _now()
    conn = get_connection()
    conn.execute(
        """INSERT INTO pipeline_runs
             (id, source_path, triggered_by, started_at, finished_at, status, skipped_reason)
           VALUES (?, ?, ?, ?, ?, 'skipped', ?)""",
        (run_id, source_path, triggered_by, now, now, reason),
    )
    conn.commit()
    return run_id


@contextmanager
def trace_agent(run_id: str, agent_name: str, model: str) -> Generator["AgentTrace", None, None]:
    """Context manager that records an agent trace row.

    Usage:
        with trace_agent(run_id, "analysis", "claude-sonnet-4-20250514") as trace:
            result = call_llm(...)
            trace.set_tokens(result.tokens_in, result.tokens_out)
            trace.emit_progress("Analysing concepts...")
    """
    trace = AgentTrace(run_id=run_id, agent_name=agent_name, model=model)
    trace._start()
    try:
        yield trace
        trace._finish("success")
    except TimeoutError as e:
        trace._finish("timeout", str(e))
        raise
    except Exception as e:
        trace._finish("error", str(e))
        raise


@dataclass
class AgentTrace:
    run_id: str
    agent_name: str
    model: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _start_time: float = field(default=0.0, repr=False)
    _tokens_in: int = field(default=0, repr=False)
    _tokens_out: int = field(default=0, repr=False)
    _cost: float = field(default=0.0, repr=False)
    _tools: list = field(default_factory=list, repr=False)
    _prompt_preview: str = field(default="", repr=False)
    _response_preview: str = field(default="", repr=False)

    def set_tokens(self, tokens_in: int, tokens_out: int, cost_usd: float = 0.0) -> None:
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._cost = cost_usd

    def set_tools_called(self, tools: list[dict]) -> None:
        self._tools = tools

    def set_prompt_preview(self, text: str) -> None:
        self._prompt_preview = text[:500]

    def set_response_preview(self, text: str) -> None:
        self._response_preview = text[:500]

    def emit_progress(self, message: str) -> None:
        """Publish a mid-execution progress event to SSE subscribers."""
        from services.events import publish
        publish("agent.progress", {
            "run_id": self.run_id,
            "agent": self.agent_name,
            "message": message,
        })

    def emit_tool_call(self, tool_name: str, tool_input: str) -> None:
        """Publish a tool-call event to SSE subscribers."""
        from services.events import publish
        publish("agent.tool_call", {
            "run_id": self.run_id,
            "agent": self.agent_name,
            "tool": tool_name,
            "input": tool_input[:200],
        })

    def _start(self) -> None:
        self._start_time = time.monotonic()
        conn = get_connection()
        conn.execute(
            """INSERT INTO agent_traces (id, run_id, agent_name, model, started_at, status)
               VALUES (?, ?, ?, ?, ?, 'running')""",
            (self.id, self.run_id, self.agent_name, self.model, _now()),
        )
        conn.commit()

        from services.events import publish
        publish("agent.started", {
            "run_id": self.run_id,
            "agent": self.agent_name,
            "model": self.model,
        })

    def _finish(self, status: str, error_message: Optional[str] = None) -> None:
        duration = int((time.monotonic() - self._start_time) * 1000)
        conn = get_connection()
        conn.execute(
            """UPDATE agent_traces SET
                 finished_at = ?, duration_ms = ?, tokens_in = ?, tokens_out = ?,
                 cost_usd = ?, tools_called = ?, status = ?, error_message = ?,
                 prompt_preview = ?, response_preview = ?
               WHERE id = ?""",
            (
                _now(), duration, self._tokens_in, self._tokens_out,
                self._cost, json.dumps(self._tools), status, error_message,
                self._prompt_preview, self._response_preview, self.id,
            ),
        )
        conn.commit()

        from services.events import publish
        publish("agent.completed", {
            "run_id": self.run_id,
            "agent": self.agent_name,
            "status": status,
            "duration_ms": duration,
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
        })
