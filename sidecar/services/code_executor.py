"""
Agent-initiated code execution service (approval-gated).

Agents write <!-- exec --> tagged code blocks in proposals.
After user approval, these run in a subprocess with:
  - Hard timeout (default: 30s for Python, 10s for shell)
  - Working directory locked to vault_root
  - Output captured and returned

No filesystem sandboxing beyond cwd — document this clearly.
Only Python and shell are supported.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("vanilla.code_executor")


@dataclass
class ExecResult:
    success: bool
    stdout: str
    stderr: str
    runtime_ms: int
    exit_code: int


async def execute_python(
    code: str,
    timeout_s: float = 30,
    vault_root: str = "",
) -> ExecResult:
    """
    Run Python code in a subprocess.
    Captures stdout and stderr; kills process on timeout.
    """
    import time

    start = time.monotonic()

    loop = asyncio.get_event_loop()

    def _run() -> subprocess.CompletedProcess:
        proc = subprocess.Popen(
            ["python", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=vault_root or None,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
            return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()  # drain pipes to avoid deadlock
            raise

    try:
        proc = await loop.run_in_executor(None, _run)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ExecResult(
            success=proc.returncode == 0,
            stdout=proc.stdout[:8000],
            stderr=proc.stderr[:4000],
            runtime_ms=elapsed_ms,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = int(timeout_s * 1000)
        logger.warning("Python exec timed out after %.0fs", timeout_s)
        return ExecResult(
            success=False,
            stdout="",
            stderr=f"Process timed out after {timeout_s:.0f}s",
            runtime_ms=elapsed_ms,
            exit_code=-1,
        )
    except FileNotFoundError:
        return ExecResult(
            success=False,
            stdout="",
            stderr="Python interpreter not found",
            runtime_ms=0,
            exit_code=-1,
        )
    except Exception as exc:
        logger.error("Python exec failed: %s", exc)
        return ExecResult(
            success=False,
            stdout="",
            stderr=str(exc),
            runtime_ms=0,
            exit_code=-1,
        )


async def execute_shell(
    cmd: str,
    timeout_s: float = 10,
    vault_root: str = "",
) -> ExecResult:
    """
    Run a shell command.
    Captures stdout and stderr; kills process on timeout.
    """
    import time

    start = time.monotonic()

    loop = asyncio.get_event_loop()

    def _run() -> subprocess.CompletedProcess:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=vault_root or None,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
            return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()  # drain pipes to avoid deadlock
            raise

    try:
        proc = await loop.run_in_executor(None, _run)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ExecResult(
            success=proc.returncode == 0,
            stdout=proc.stdout[:8000],
            stderr=proc.stderr[:4000],
            runtime_ms=elapsed_ms,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = int(timeout_s * 1000)
        logger.warning("Shell exec timed out after %.0fs", timeout_s)
        return ExecResult(
            success=False,
            stdout="",
            stderr=f"Process timed out after {timeout_s:.0f}s",
            runtime_ms=elapsed_ms,
            exit_code=-1,
        )
    except Exception as exc:
        logger.error("Shell exec failed: %s", exc)
        return ExecResult(
            success=False,
            stdout="",
            stderr=str(exc),
            runtime_ms=0,
            exit_code=-1,
        )
