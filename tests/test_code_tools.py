"""Tests for the dedicated code-runner (ai/code_tools.run_python).

Executes a Python snippet in a separate process (workspace cwd, timeout) and returns
stdout/stderr/exit_code. Confirm-gating is exercised in test_brain/jotaro; here we test
the executor itself.
"""
from __future__ import annotations

import pytest

from ai.code_tools import CODE_WRITE_TOOLS, make_code_dispatcher


@pytest.fixture()
def run(tmp_path):
    return make_code_dispatcher(tmp_path, timeout=10)


def test_captures_stdout_and_exit_zero(run):
    out = run("run_python", {"code": "print('hello'); print(2 + 2)"})
    assert out["exit_code"] == 0
    assert "hello" in out["stdout"] and "4" in out["stdout"]
    assert out["stderr"] == ""


def test_captures_traceback_and_nonzero_exit(run):
    out = run("run_python", {"code": "raise ValueError('boom')"})
    assert out["exit_code"] != 0
    assert "ValueError" in out["stderr"] and "boom" in out["stderr"]


def test_runs_in_workspace_cwd(run, tmp_path):
    (tmp_path / "data.txt").write_text("payload", encoding="utf-8")
    out = run("run_python", {"code": "print(open('data.txt').read())"})
    assert "payload" in out["stdout"]                 # cwd is the workspace


def test_timeout_is_reported(tmp_path):
    r = make_code_dispatcher(tmp_path, timeout=1)
    out = r("run_python", {"code": "import time; time.sleep(5)"})
    assert "timed out" in out["error"]


def test_empty_code_errors(run):
    assert "empty" in run("run_python", {"code": "   "})["error"]


def test_unknown_tool_name(run):
    assert "unknown tool" in run("nope", {})["error"]


def test_no_temp_file_left_behind(run, tmp_path):
    run("run_python", {"code": "print('x')"})
    assert not list(tmp_path.glob("cheng_run_*.py"))   # temp script cleaned up


def test_thai_output_roundtrips(run):
    out = run("run_python", {"code": "print('สวัสดีครับ')"})
    assert "สวัสดีครับ" in out["stdout"]               # UTF-8 preserved


def test_run_python_is_confirm_gated():
    assert "run_python" in CODE_WRITE_TOOLS
