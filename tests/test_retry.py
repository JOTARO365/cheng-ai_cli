"""Tests for Ollama transient-failure retry/backoff (gap #1c) in ai/brain.py.

A flaky or just-starting Ollama (connection reset, 5xx while the model loads, timeout)
is retried with exponential backoff; permanent 4xx errors and exhausted retries raise
OllamaUnavailable. time.sleep is patched so tests don't actually wait.
"""
from __future__ import annotations

import httpx
import pytest

from ai import brain as brain_mod
from ai.brain import Brain, OllamaUnavailable
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(brain_mod.time, "sleep", lambda s: slept.append(s))
    return slept


class _OK:
    status_code = 200

    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return {"message": {"role": "assistant", "content": "ok"}}


class _HTTPErr:
    """A response whose raise_for_status raises an HTTPStatusError of `status`."""
    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        req = httpx.Request("POST", "http://x/api/chat")
        resp = httpx.Response(self.status_code, request=req)
        raise httpx.HTTPStatusError(f"{self.status_code}", request=req, response=resp)


def _flaky(monkeypatch, seq):
    """Drive httpx.post through `seq`: each item is either an Exception to raise or a
    response object to return. Returns a call counter."""
    it = iter(seq)
    calls = {"n": 0}

    def post(url, json=None, timeout=None):
        calls["n"] += 1
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(brain_mod.httpx, "post", post)
    return calls


def test_retries_transient_then_succeeds(db, monkeypatch, no_sleep):
    calls = _flaky(monkeypatch, [httpx.ConnectError("reset"),
                                 httpx.ReadTimeout("slow"), _OK()])
    b = Brain("http://x", "m", db, retries=2, backoff=0.5)
    msg = b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert msg["content"] == "ok"
    assert calls["n"] == 3                       # 2 failures + 1 success
    assert no_sleep == [0.5, 1.0]                # exponential backoff schedule


def test_retries_5xx_server_error(db, monkeypatch):
    calls = _flaky(monkeypatch, [_HTTPErr(503), _OK()])    # model still loading
    b = Brain("http://x", "m", db, retries=2)
    assert b._chat([{"role": "user", "content": "hi"}], use_tools=False)["content"] == "ok"
    assert calls["n"] == 2


def test_gives_up_after_retries(db, monkeypatch, no_sleep):
    calls = _flaky(monkeypatch, [httpx.ConnectError("x")] * 5)
    b = Brain("http://x", "m", db, retries=2)
    with pytest.raises(OllamaUnavailable):
        b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert calls["n"] == 3                        # initial + 2 retries, then give up
    assert len(no_sleep) == 2


def test_4xx_is_not_retried(db, monkeypatch, no_sleep):
    calls = _flaky(monkeypatch, [_HTTPErr(400), _OK()])    # bad request — permanent
    b = Brain("http://x", "m", db, retries=2)
    with pytest.raises(OllamaUnavailable):
        b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert calls["n"] == 1                         # no retry
    assert no_sleep == []


def test_retries_zero_disables(db, monkeypatch, no_sleep):
    calls = _flaky(monkeypatch, [httpx.ConnectError("x"), _OK()])
    b = Brain("http://x", "m", db, retries=0)
    with pytest.raises(OllamaUnavailable):
        b._chat([{"role": "user", "content": "hi"}], use_tools=False)
    assert calls["n"] == 1 and no_sleep == []
