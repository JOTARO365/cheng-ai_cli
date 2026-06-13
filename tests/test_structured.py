"""Tests for Brain.structured() — constrained JSON output (Ollama format=schema).

Structured output makes a small model reliable for routing / classification / extraction.
Offline: httpx.post is monkeypatched to return canned content.
"""
from __future__ import annotations

import json

import pytest

from ai import brain as brain_mod
from ai.brain import Brain, StructuredError, _parse_json
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


class _Resp:
    status_code = 200

    def __init__(self, content: str) -> None:
        self._c = content

    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return {"message": {"role": "assistant", "content": self._c}}


SCHEMA = {"type": "object", "properties": {"specialist": {"type": "string"}},
          "required": ["specialist"]}


# ---- the parser ------------------------------------------------------------
def test_parse_plain_json():
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_strips_code_fence():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_extracts_embedded_object():
    assert _parse_json('sure, here: {"a": 1} done') == {"a": 1}


def test_parse_returns_none_on_garbage():
    assert _parse_json("not json at all") is None
    assert _parse_json("[1,2,3]") is None          # not a dict


# ---- structured() ----------------------------------------------------------
def test_structured_returns_parsed_dict(db, monkeypatch):
    monkeypatch.setattr(brain_mod.httpx, "post",
                        lambda url, json=None, timeout=None: _Resp('{"specialist": "security"}'))
    b = Brain("http://x", "m", db)
    assert b.structured("route this", SCHEMA) == {"specialist": "security"}


def test_structured_passes_schema_as_format(db, monkeypatch):
    seen = {}

    def post(url, json=None, timeout=None):
        seen.update(json)
        return _Resp('{"specialist": "network"}')

    monkeypatch.setattr(brain_mod.httpx, "post", post)
    Brain("http://x", "m", db).structured("q", SCHEMA, system="you route")
    assert seen["format"] == SCHEMA                # schema sent to Ollama
    assert seen["messages"][0]["role"] == "system"
    assert "tools" not in seen                      # structured calls are tool-free


def test_structured_retries_then_raises(db, monkeypatch):
    monkeypatch.setattr(brain_mod.httpx, "post",
                        lambda url, json=None, timeout=None: _Resp("definitely not json"))
    with pytest.raises(StructuredError):
        Brain("http://x", "m", db).structured("q", SCHEMA, retries=1)


def test_structured_recovers_on_second_try(db, monkeypatch):
    calls = {"n": 0}

    def post(url, json=None, timeout=None):
        calls["n"] += 1
        return _Resp("oops" if calls["n"] == 1 else '{"specialist": "service"}')

    monkeypatch.setattr(brain_mod.httpx, "post", post)
    assert Brain("http://x", "m", db).structured("q", SCHEMA, retries=1)["specialist"] == "service"
    assert calls["n"] == 2
