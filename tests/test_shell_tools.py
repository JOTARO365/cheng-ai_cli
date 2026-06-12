"""Tests for the shell tool (ai/shell_tools.py). Runs real (tiny) commands offline."""
from __future__ import annotations

from ai.shell_tools import SHELL_WRITE_TOOLS, make_shell_dispatcher


def test_run_echo(tmp_path):
    r = make_shell_dispatcher(tmp_path)("run_command", {"command": "echo hello123"})
    assert r["exit_code"] == 0
    assert "hello123" in r["stdout"]


def test_nonzero_exit(tmp_path):
    r = make_shell_dispatcher(tmp_path)("run_command", {"command": "exit 3"})
    assert r["exit_code"] == 3


def test_empty_and_unknown(tmp_path):
    d = make_shell_dispatcher(tmp_path)
    assert "empty" in d("run_command", {"command": "   "})["error"]
    assert "unknown" in d("nope", {})["error"]


def test_runs_in_workspace(tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    r = make_shell_dispatcher(tmp_path)("run_command", {"command": "ls"})
    assert "marker.txt" in r["stdout"]  # cwd is the workspace


def test_always_confirm():
    assert "run_command" in SHELL_WRITE_TOOLS
