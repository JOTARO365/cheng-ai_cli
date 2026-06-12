"""Tests for the web_search tool (ddgs mocked — no real network)."""
from __future__ import annotations

import sys
import types

from ai.web_tools import make_web_dispatcher


class _FakeDDGS:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=5):
        return [{"title": "T", "href": "http://x", "body": "snip"}][:max_results]


def test_web_search(monkeypatch):
    fake = types.ModuleType("ddgs")
    fake.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake)   # web_tools does `from ddgs import DDGS`
    d = make_web_dispatcher()
    out = d("web_search", {"query": "hello", "n": 3})
    assert out["results"][0] == {"title": "T", "url": "http://x", "snippet": "snip"}
    assert "empty" in d("web_search", {"query": "  "})["error"]
    assert "unknown" in d("nope", {})["error"]
