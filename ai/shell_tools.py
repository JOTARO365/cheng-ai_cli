"""Shell command tool for JOTARO's --workspace mode.

Lets the agent run a shell command (bash if available, else the OS shell) IN the
workspace folder and read its output. This is powerful and dangerous, so:
  - `run_command` is ALWAYS in the confirm set — the harness shows the FULL command and
    waits for the user's y/N before anything runs (nothing executes un-approved);
  - it runs with a timeout and captures/truncates output;
  - it stays in the workspace dir (cwd), like the other workspace tools.

The safety model here is human confirmation, not sandboxing — the user sees and approves
each exact command. Never wire this into the unattended IT-monitor product.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_OUT = 8000          # chars of stdout/stderr returned to the model
DEFAULT_TIMEOUT = 30    # seconds

# Always require confirmation before running a command.
SHELL_WRITE_TOOLS: frozenset[str] = frozenset({"run_command"})

SHELL_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command in the workspace folder and return its exit code + "
                "output. Use for git, running tests/build, listing, grep, etc. The USER "
                "must approve the exact command first, so state plainly what you intend to run."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "the shell command line to run"}
                },
                "required": ["command"],
            },
        },
    },
]


def make_shell_dispatcher(
    base_dir: str | Path, timeout: int = DEFAULT_TIMEOUT
) -> Callable[[str, dict[str, Any]], Any]:
    base = Path(base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    bash = shutil.which("bash")  # prefer bash when present (git-bash / WSL / *nix)

    def dispatch(name: str, args: dict[str, Any]) -> Any:
        if name != "run_command":
            return {"error": f"unknown tool {name!r}"}
        command = str((args or {}).get("command", "")).strip()
        if not command:
            return {"error": "empty command"}
        try:
            if bash:
                proc = subprocess.run(
                    [bash, "-lc", command], cwd=str(base), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=timeout,
                )
            else:
                proc = subprocess.run(
                    command, shell=True, cwd=str(base), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            return {"error": f"command timed out after {timeout}s"}
        except OSError as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

        log.warning("shell run_command (exit %s): %s", proc.returncode, command)
        out, err = proc.stdout or "", proc.stderr or ""
        return {
            "exit_code": proc.returncode,
            "stdout": out[:MAX_OUT],
            "stderr": err[:MAX_OUT],
            "truncated": len(out) > MAX_OUT or len(err) > MAX_OUT,
        }

    return dispatch
