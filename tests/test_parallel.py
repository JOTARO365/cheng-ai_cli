"""Tests for the fan-out helper (parallel_map, chunk_text, fan_out_summarize)."""
from __future__ import annotations

from ai.parallel import chunk_text, fan_out_summarize, parallel_map


def test_parallel_map_preserves_order():
    assert parallel_map([1, 2, 3], lambda x: x * 2) == [2, 4, 6]
    assert parallel_map([], lambda x: x) == []


def test_parallel_map_isolates_failures():
    def fn(x):
        if x == 2:
            raise ValueError("boom")
        return x
    assert parallel_map([1, 2, 3], fn) == [1, None, 3]   # one bad slice → None, not a crash


def test_chunk_text():
    assert chunk_text("", 10) == []
    assert chunk_text("short", 10) == ["short"]
    chunks = chunk_text("a" * 25, 10)
    assert len(chunks) == 3 and "".join(chunks) == "a" * 25


class _FakeBrain:
    def new_history(self):
        return []

    def ask(self, h, q, **k):
        return "SUM"


def test_fan_out_summarize_chunks_then_reduces():
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return _FakeBrain()

    summary, n = fan_out_summarize("x" * 6000, factory, chunk_chars=2500, max_workers=2)
    assert n == 3                       # 6000 / 2500 → 3 chunks
    assert calls["n"] == 4              # 3 chunk sub-agents + 1 reduce sub-agent
    assert "SUM" in summary


def test_fan_out_single_chunk_skips_reduce():
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return _FakeBrain()

    summary, n = fan_out_summarize("small text", factory, chunk_chars=2500)
    assert n == 1 and summary == "SUM" and calls["n"] == 1   # no reduce step
