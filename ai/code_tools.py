"""Code-runner tool for CHENG AI's --workspace mode.

`run_python` executes a Python 3 snippet in a SEPARATE process (the same interpreter),
with cwd = the workspace folder and a timeout, and returns its stdout / stderr / exit
code. Use it to compute, parse data, or test a fix and SEE the real result instead of
guessing.

Like `run_command` it is ALWAYS confirm-gated — the harness shows the exact code and
waits for y/N. The safety model is human approval + a timeout + a separate process,
NOT a security sandbox; never wire this into the unattended IT-monitor product.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_OUT = 8000          # chars of stdout/stderr returned to the model
DEFAULT_TIMEOUT = 30    # seconds

# Always require confirmation before executing code.
CODE_WRITE_TOOLS: frozenset[str] = frozenset({"run_python"})

CODE_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute a Python 3 snippet in the workspace and return its stdout, "
                "stderr, and exit code. Use to compute, parse files/data, or test a fix "
                "and see the REAL output — print() whatever you want to read back. The "
                "USER approves the exact code before it runs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "the Python 3 source to run"}
                },
                "required": ["code"],
            },
        },
    },
]


def make_code_dispatcher(
    base_dir: str | Path, timeout: int = DEFAULT_TIMEOUT, python: str | None = None
) -> Callable[[str, dict[str, Any]], Any]:
    base = Path(base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    py = python or sys.executable

    def dispatch(name: str, args: dict[str, Any]) -> Any:
        if name != "run_python":
            return {"error": f"unknown tool {name!r}"}
        code = str((args or {}).get("code", "")).strip()
        if not code:
            return {"error": "empty code"}
        # write to a temp .py IN the workspace so tracebacks carry a real filename and
        # multi-line code needs no shell quoting; remove it afterwards.
        fd, path = tempfile.mkstemp(suffix=".py", prefix="cheng_run_", dir=str(base))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
            proc = subprocess.run(
                [py, path], cwd=str(base), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except subprocess.TimeoutExpired:
            return {"error": f"code timed out after {timeout}s — likely an infinite "
                             "loop or a blocking call (network/input)"}
        except OSError as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        log.warning("code run_python (exit %s, %d chars of code)", proc.returncode, len(code))
        out, err = proc.stdout or "", proc.stderr or ""
        return {
            "exit_code": proc.returncode,
            "stdout": out[:MAX_OUT],
            "stderr": err[:MAX_OUT],
            "truncated": len(out) > MAX_OUT or len(err) > MAX_OUT,
        }

    return dispatch
