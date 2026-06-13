"""Tests for the CHENG AI agent loop (ai/brain.py) + tool registry (ai/tools.py).

Fully offline: Ollama's HTTP calls are mocked, so the ReAct loop, tool dispatch,
and the unavailable-fallback are all exercised on any machine without a model.
"""
from __future__ import annotations

import httpx
import pytest

from ai import brain as brain_mod
from ai.brain import Brain, OllamaUnavailable
from ai.tools import dispatch
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    d = Database(tmp_path / "t.db")
    d.upsert_node("PC12", "down", None, 3, last_seen="2026-06-12T03:00:00+00:00")
    d.upsert_node("PC01", "up", 1.0, 0, last_seen="2026-06-12T09:00:00+00:00")
    d.record_event("rule_engine", "login_fail", "warning", "5 fails",
                   host="PC07", data={"user": "john", "count": 5, "ip": "10.0.0.9"})
    return d


# ---- tool registry ---------------------------------------------------------
def test_dispatch_runs_db_helpers(db: Database) -> None:
    down = dispatch("get_down_nodes", {}, db)
    assert [n["host"] for n in down] == ["PC12"]
    fails = dispatch("get_login_fails", {"hours": 24}, db)
    assert fails[0]["user"] == "john" and fails[0]["count"] == 5


def test_dispatch_clamps_and_unknown(db: Database) -> None:
    # absurd hours is clamped (no crash), unknown tool returns an error signal
    assert dispatch("get_login_fails", {"hours": 99999}, db) == [
        {"user": "john", "count": 5, "host": "PC07", "ip": "10.0.0.9",
         "last_ts": dispatch("get_login_fails", {}, db)[0]["last_ts"]}
    ]
    assert "error" in dispatch("get_nonexistent", {}, db)


# ---- fake Ollama -----------------------------------------------------------
class _FakeResp:
    def __init__(self, message: dict) -> None:
        self._m = message
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": self._m}


def test_ask_runs_tool_then_answers(db: Database, monkeypatch) -> None:
    # 1st call: model asks for the tool. 2nd call: model gives the final answer.
    scripted = [
        _FakeResp({"role": "assistant", "content": "",
                   "tool_calls": [{"function": {"name": "get_down_nodes", "arguments": {}}}]}),
        _FakeResp({"role": "assistant", "content": "PC12 กำลัง offline อยู่"}),
    ]
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        return scripted[i]

    monkeypatch.setattr(brain_mod.httpx, "post", fake_post)

    b = Brain("http://x", "qwen2.5:3b", db)
    seen: list[str] = []
    history = b.new_history()
    answer = b.ask(history, "PC ไหนปิดอยู่", on_tool=lambda n, a: seen.append(n))

    assert answer == "PC12 กำลัง offline อยู่"
    assert seen == ["get_down_nodes"]                 # the tool was invoked
    assert calls["n"] == 2                             # looped exactly twice
    # a tool-result message got fed back into the history
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    assert tool_msgs and "PC12" in tool_msgs[0]["content"]


def test_language_guard_regenerates_on_chinese(db: Database, monkeypatch) -> None:
    # 1st answer leaks Chinese → guard fires a no-tools regenerate → clean Thai.
    scripted = [
        _FakeResp({"role": "assistant", "content": "PC12 关机了 offline"}),
        _FakeResp({"role": "assistant", "content": "PC12 ปิดอยู่"}),
    ]
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        # the retry must NOT send tools (use_tools=False)
        if i == 1:
            assert "tools" not in (json or {})
        return scripted[i]

    monkeypatch.setattr(brain_mod.httpx, "post", fake_post)
    answer = Brain("http://x", "qwen2.5:3b", db).ask(Brain("http://x", "m", db).new_history(),
                                                      "PC ไหนปิด")
    assert answer == "PC12 ปิดอยู่"
    assert calls["n"] == 2


def test_ask_raises_when_ollama_down(db: Database, monkeypatch) -> None:
    def boom(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(brain_mod.httpx, "post", boom)
    b = Brain("http://x", "qwen2.5:3b", db)
    with pytest.raises(OllamaUnavailable):
        b.ask(b.new_history(), "hi")


def test_is_available(db: Database, monkeypatch) -> None:
    monkeypatch.setattr(brain_mod.httpx, "get",
                        lambda url, timeout=None: _FakeResp({}))
    assert Brain("http://x", "m", db).is_available() is True

    def boom(*a, **k):
        raise httpx.ConnectError("x")

    monkeypatch.setattr(brain_mod.httpx, "get", boom)
    assert Brain("http://x", "m", db).is_available() is False


# --- regression: degenerate empty reply must not surface as a blank answer ---
def test_empty_reply_retries_without_tools(db, monkeypatch):
    """Model returns empty content + no tool call (weak-model failure mode) → ask()
    retries once without tools and uses that answer instead of returning ''."""
    import ai.brain as brain_mod
    calls = {"n": 0}

    def fake_chat(self, messages, use_tools=True, on_token=None):
        calls["n"] += 1
        if calls["n"] == 1:                       # first call: empty, tools were in scope
            assert use_tools is True
            return {"role": "assistant", "content": ""}
        assert use_tools is False                 # retry must drop tools
        return {"role": "assistant", "content": "def first(x): return x[0] if x else None"}

    monkeypatch.setattr(brain_mod.Brain, "_chat", fake_chat)
    b = brain_mod.Brain("http://x", "m", db)
    ans = b.ask(b.new_history(), "fix it")
    assert "return x[0] if x else None" in ans
    assert calls["n"] == 2


def test_persistent_empty_falls_back_to_message(db, monkeypatch):
    """If even the no-tools retry is empty, return the fallback, never a blank string."""
    import ai.brain as brain_mod
    monkeypatch.setattr(brain_mod.Brain, "_chat",
                        lambda self, m, use_tools=True, on_token=None:
                        {"role": "assistant", "content": ""})
    b = brain_mod.Brain("http://x", "m", db)
    ans = b.ask(b.new_history(), "hi")
    assert ans == brain_mod._EMPTY_FALLBACK and ans.strip()
