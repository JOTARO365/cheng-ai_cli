"""Tests for the web_search tool (ddgs mocked — no real network)."""
from __future__ import annotations

import sys
import types

from ai.web_tools import _clean_query, _filter_results, _region, make_web_dispatcher


class _FakeDDGS:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=5, **kwargs):
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


def test_clean_query():
    assert _clean_query("search for python asyncio").lower() == "python asyncio"
    assert _clean_query("ค้นหา ราคาทองวันนี้") == "ราคาทองวันนี้"
    assert _clean_query("just a query") == "just a query"


def test_region():
    assert _region("ราคาทองคำวันนี้เท่าไหร่") == "th-th"
    assert _region("gold price today") == "wt-wt"


def test_filter_results_drops_junk_and_dupes():
    rows = [
        {"title": "Google", "url": "https://www.google.com/?hl=th", "snippet": ""},   # junk
        {"title": "Real", "url": "https://example.com/page", "snippet": "x"},
        {"title": "Dup", "url": "https://example.com/page/", "snippet": "y"},          # dupe
        {"title": "", "url": "https://x.com/a", "snippet": "z"},                        # no title
        {"title": "Ok2", "url": "https://site.org/info", "snippet": "w"},
    ]
    out = _filter_results(rows, 5)
    assert [r["url"] for r in out] == ["https://example.com/page", "https://site.org/info"]


def test_fetch_url(monkeypatch):
    class _R:
        url = "http://x"
        status_code = 200
        text = "<html><head><style>a{}</style></head><body><h1>Hi</h1><p>Hello world</p></body></html>"

    monkeypatch.setattr("ai.web_tools.httpx.get", lambda *a, **k: _R())
    d = make_web_dispatcher()
    out = d("fetch_url", {"url": "http://x"})
    assert out["status"] == 200 and "Hello world" in out["text"]
    assert "empty" in d("fetch_url", {"url": ""})["error"]
