"""Tests for filesystem tools (ai/fs_tools.py) + the Brain permission gate.

Offline: fs ops run on a tmp workspace; the gate test mocks Ollama to emit a write
tool-call and checks the file is written only when confirm() approves.
"""
from __future__ import annotations

import httpx
import pytest

from ai import brain as brain_mod
from ai.brain import Brain
from ai.fs_tools import WRITE_TOOLS, make_fs_dispatcher
from storage.db import Database


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "notes.txt").write_text("hello world", encoding="utf-8")
    return tmp_path


# ---- dispatcher + sandbox --------------------------------------------------
def test_read_and_list(ws):
    d = make_fs_dispatcher(ws)
    assert d("read_file", {"path": "notes.txt"})["content"] == "hello world"
    names = [e["name"] for e in d("list_dir", {"path": "."})["entries"]]
    assert "notes.txt" in names


def test_write_edit_make_dir(ws):
    d = make_fs_dispatcher(ws)
    assert d("write_file", {"path": "sub/new.txt", "content": "abc"})["status"] == "written"
    assert (ws / "sub" / "new.txt").read_text(encoding="utf-8") == "abc"
    assert d("edit_file", {"path": "sub/new.txt", "old_string": "abc", "new_string": "XYZ"})["replacements"] == 1
    assert (ws / "sub" / "new.txt").read_text(encoding="utf-8") == "XYZ"
    assert d("make_dir", {"path": "deep/er"})["status"] == "created"
    assert (ws / "deep" / "er").is_dir()


def test_path_jail_blocks_escape(ws):
    d = make_fs_dispatcher(ws)
    assert "escapes workspace" in d("read_file", {"path": "../secret"}).get("error", "")
    assert "escapes workspace" in d("write_file", {"path": "../../evil.txt", "content": "x"}).get("error", "")


def test_edit_missing_string(ws):
    d = make_fs_dispatcher(ws)
    assert "not found" in d("edit_file", {"path": "notes.txt", "old_string": "ZZZ", "new_string": "q"})["error"]


# ---- permission gate -------------------------------------------------------
def _scripted_post(responses):
    state = {"i": 0}

    def post(url, json=None, timeout=None):
        r = responses[state["i"]]
        state["i"] += 1

        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": r}
        return _R()

    return post


def _write_then_done():
    return [
        {"role": "assistant", "content": "",
         "tool_calls": [{"function": {"name": "write_file",
                                      "arguments": {"path": "x.txt", "content": "hi"}}}]},
        {"role": "assistant", "content": "done"},
    ]


def test_gate_declined_does_not_write(ws, monkeypatch):
    monkeypatch.setattr(brain_mod.httpx, "post", _scripted_post(_write_then_done()))
    b = Brain("http://x", "m", Database(ws / "db.sqlite"),
              tools=[], dispatcher=make_fs_dispatcher(ws),
              confirm_tools=WRITE_TOOLS, confirm=lambda n, a: False)
    b.ask(b.new_history(), "write hi to x.txt")
    assert not (ws / "x.txt").exists()  # declined → not executed


def test_gate_approved_writes(ws, monkeypatch):
    monkeypatch.setattr(brain_mod.httpx, "post", _scripted_post(_write_then_done()))
    b = Brain("http://x", "m", Database(ws / "db.sqlite"),
              tools=[], dispatcher=make_fs_dispatcher(ws),
              confirm_tools=WRITE_TOOLS, confirm=lambda n, a: True)
    b.ask(b.new_history(), "write hi to x.txt")
    assert (ws / "x.txt").read_text(encoding="utf-8") == "hi"
