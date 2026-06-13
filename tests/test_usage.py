"""Tests for token/usage accounting (beyond-the-9) in ai/brain.py.

Ollama returns prompt_eval_count / eval_count / eval_duration per call; the Brain
accumulates them so the CLI can show /usage. Offline: httpx.post is monkeypatched.
"""
from __future__ import annotations

import pytest

from ai import brain as brain_mod
from ai.brain import Brain
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


class _Resp:
    status_code = 200

    def __init__(self, data: dict) -> None:
        self._d = data

    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return self._d


def _reply(monkeypatch, prompt_tokens, completion_tokens, eval_ns):
    data = {"message": {"role": "assistant", "content": "ok"},
            "prompt_eval_count": prompt_tokens, "eval_count": completion_tokens,
            "eval_duration": eval_ns}
    monkeypatch.setattr(brain_mod.httpx, "post",
                        lambda url, json=None, timeout=None: _Resp(data))


def test_usage_starts_empty(db):
    b = Brain("http://x", "m", db)
    assert b.usage_total == {"calls": 0, "prompt_tokens": 0,
                             "completion_tokens": 0, "eval_ms": 0.0}


def test_single_call_records_tokens(db, monkeypatch):
    _reply(monkeypatch, prompt_tokens=120, completion_tokens=40, eval_ns=2_000_000_000)
    b = Brain("http://x", "m", db)
    b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert b.last_usage == {"prompt_tokens": 120, "completion_tokens": 40, "eval_ms": 2000.0}
    assert b.usage_total["calls"] == 1
    assert b.usage_total["prompt_tokens"] == 120
    assert b.usage_total["completion_tokens"] == 40


def test_usage_accumulates_across_calls(db, monkeypatch):
    _reply(monkeypatch, 100, 50, 1_000_000_000)
    b = Brain("http://x", "m", db)
    for _ in range(3):
        b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert b.usage_total["calls"] == 3
    assert b.usage_total["completion_tokens"] == 150


def test_usage_summary_computes_tokens_per_sec(db, monkeypatch):
    _reply(monkeypatch, 10, 30, 2_000_000_000)      # 30 tok in 2.0s → 15 tok/s
    b = Brain("http://x", "m", db)
    b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert b.usage_summary()["tokens_per_sec"] == 15.0


def test_missing_counts_count_as_zero(db, monkeypatch):
    monkeypatch.setattr(brain_mod.httpx, "post",
                        lambda url, json=None, timeout=None:
                        _Resp({"message": {"role": "assistant", "content": "ok"}}))
    b = Brain("http://x", "m", db)
    b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert b.usage_total["calls"] == 1
    assert b.usage_total["completion_tokens"] == 0
    assert b.usage_summary()["tokens_per_sec"] == 0.0
