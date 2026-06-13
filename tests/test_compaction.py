"""Tests for conversation context compaction (gap #1) in ai/brain.py.

Offline: Ollama is monkeypatched. Verifies that history is folded into a summary
once it grows past the budget, the system message + recent tail survive verbatim,
the summary call falls back deterministically when Ollama is down, and the public
ask() loop keeps a long session bounded.
"""
from __future__ import annotations

import httpx
import pytest

from ai import brain as brain_mod
from ai.brain import Brain
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


class _Resp:
    def __init__(self, message: dict) -> None:
        self._m, self.status_code = message, 200

    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return {"message": self._m}


def _fake_summary(monkeypatch, text="SUMMARY: discussed PC12 outage and SRV01."):
    monkeypatch.setattr(brain_mod.httpx, "post",
                        lambda url, json=None, timeout=None:
                        _Resp({"role": "assistant", "content": text}))


def _big_history(n_turns: int, size: int = 2000) -> list[dict]:
    h = [{"role": "system", "content": "sys"}]
    for i in range(n_turns):
        h.append({"role": "user", "content": f"question {i} " + "x" * size})
        h.append({"role": "assistant", "content": f"answer {i} " + "y" * size})
    return h


# ---- below budget: untouched ----------------------------------------------
def test_no_compaction_under_budget(db, monkeypatch):
    _fake_summary(monkeypatch)
    b = Brain("http://x", "m", db, context_budget=100_000)
    h = _big_history(3)
    before = list(h)
    fired = []
    b._compact(h, on_compact=lambda a, c: fired.append((a, c)))
    assert h == before and not fired           # nothing changed, no callback


# ---- over budget: fold old turns into a summary ----------------------------
def test_compaction_folds_old_turns(db, monkeypatch):
    _fake_summary(monkeypatch)
    b = Brain("http://x", "m", db, context_budget=8_000, keep_recent_turns=2)
    h = _big_history(8)                         # ~32k chars >> budget
    before_chars = b._history_chars(h)
    fired = []
    b._compact(h, on_compact=lambda a, c: fired.append((a, c)))

    assert h[0]["content"] == "sys"             # system preserved
    assert h[1]["content"].startswith("[earlier conversation — summary]")
    assert "SUMMARY:" in h[1]["content"]
    assert b._history_chars(h) < before_chars   # shrunk
    assert fired and fired[0][0] > fired[0][1]  # (before, after) reported, after smaller
    # the recent tail survived verbatim: last user turn still present
    assert any(m["role"] == "user" and "question 7" in m["content"] for m in h)


def test_recent_tail_starts_at_user_boundary(db, monkeypatch):
    """The kept tail must begin with a user message (no orphaned tool/assistant)."""
    _fake_summary(monkeypatch)
    b = Brain("http://x", "m", db, context_budget=5_000, keep_recent_turns=2)
    h = _big_history(6)
    b._compact(h)
    tail = h[2:]                                 # after [system, summary]
    assert tail[0]["role"] == "user"


def test_compaction_fallback_when_ollama_down(db, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(brain_mod.httpx, "post", boom)
    b = Brain("http://x", "m", db, context_budget=8_000, keep_recent_turns=1)
    h = _big_history(8)
    before = b._history_chars(h)
    b._compact(h)                                # must not raise
    assert b._history_chars(h) < before          # deterministic truncation still compacts
    assert h[1]["content"].startswith("[earlier conversation — summary]")


# ---- end-to-end: a long session stays bounded ------------------------------
def test_ask_keeps_long_session_bounded(db, monkeypatch):
    """Many turns through ask() should not grow history without bound."""
    # every model reply is a short final answer (no tool calls); summary call reuses it
    monkeypatch.setattr(brain_mod.httpx, "post",
                        lambda url, json=None, timeout=None:
                        _Resp({"role": "assistant", "content": "ok " + "z" * 1500}))
    b = Brain("http://x", "m", db, context_budget=12_000, keep_recent_turns=2)
    h = b.new_history()
    for i in range(30):
        b.ask(h, f"turn {i} " + "q" * 1500)
    # without compaction this would be ~30*(1500+1500)=90k+ chars; bounded well under that
    assert b._history_chars(h) <= 12_000 + 6_000   # budget + one in-flight turn of slack
