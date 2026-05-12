"""Sandboxed Python execution for agent tool use during pipeline."""

import subprocess
import tempfile
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    success: bool
    duration_ms: int
    truncated: bool = False


ALLOWED_IMPORTS = {
    "math", "statistics", "collections", "itertools", "functools",
    "json", "csv", "re", "datetime", "decimal", "fractions",
    "textwrap", "string", "operator",
    "pandas", "numpy",
}

SAFETY_PREAMBLE = """# -*- coding: utf-8 -*-
import sys as _sys
_blocked = {'os', 'subprocess', 'shutil', 'socket', 'http', 'urllib',
            'ftplib', 'smtplib', 'importlib', 'ctypes', 'signal',
            'multiprocessing', 'threading', 'pickle', 'shelve'}
_orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
_stdlib_paths = tuple(p for p in _sys.path if 'lib' in p.lower() and 'site-packages' not in p)

def _safe_import(name, *args, **kwargs):
    base = name.split('.')[0]
    if base in _blocked:
        # Allow transitive stdlib imports; only block imports from user code
        frame = _sys._getframe(1)
        caller = frame.f_code.co_filename
        is_stdlib = any(caller.startswith(p) for p in _stdlib_paths if p)
        if not is_stdlib:
            raise ImportError(f"Module '{name}' is not allowed in the sandbox")
    return _orig_import(name, *args, **kwargs)

import builtins
builtins.__import__ = _safe_import
"""

MAX_OUTPUT_CHARS = 10_000
TIMEOUT_SECONDS = 30


def execute_code(code: str) -> ExecutionResult:
    """Execute Python code in a sandboxed subprocess.

    - Runs in a temp directory (no access to vault)
    - 30-second hard timeout
    - Blocked dangerous imports (os, subprocess, socket, etc.)
    - Sensitive env vars stripped
    """
    full_code = SAFETY_PREAMBLE + "\n" + code

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=tempfile.gettempdir(), delete=False, encoding="utf-8"
    ) as f:
        f.write(full_code)
        script_path = f.name

    start = time.monotonic()

    try:
        env = os.environ.copy()
        for key in list(env.keys()):
            if any(s in key.upper() for s in ["API_KEY", "SECRET", "TOKEN", "PASSWORD"]):
                del env[key]

        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=tempfile.gettempdir(),
            env=env,
        )

        duration = int((time.monotonic() - start) * 1000)
        stdout = result.stdout
        truncated = False

        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
            truncated = True

        return ExecutionResult(
            stdout=stdout,
            stderr=result.stderr[:2000] if result.stderr else "",
            success=result.returncode == 0,
            duration_ms=duration,
            truncated=truncated,
        )

    except subprocess.TimeoutExpired:
        duration = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            stdout="",
            stderr=f"Execution timed out after {TIMEOUT_SECONDS}s",
            success=False,
            duration_ms=duration,
        )

    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
