"""Tests for the difficulty-based model router (ai/router.py, gap #3).

Difficulty is a DETERMINISTIC heuristic by default (a small model is unreliable at
self-classifying); an LLM classifier is opt-in. Hard turns route up ONLY when the big
model is pulled. Fully offline (classifier stubbed).
"""
from __future__ import annotations

from ai.router import ModelRouter
from ai.brain import StructuredError


class _Classifier:
    """Stand-in for the classifier Brain: scripts structured() + list_models()."""
    def __init__(self, difficulty="easy", pulled=("small",), raise_exc=None):
        self._diff, self._pulled, self._raise = difficulty, list(pulled), raise_exc
        self.structured_calls = 0

    def structured(self, q, schema, **k):
        self.structured_calls += 1
        if self._raise:
            raise self._raise
        return {"difficulty": self._diff}

    def list_models(self):
        return self._pulled


# ---- enabled / disabled ----------------------------------------------------
def test_disabled_when_models_equal():
    r = ModelRouter(_Classifier(), "small", "small")
    assert not r.enabled
    assert r.pick("refactor this module") == ("small", "n/a")


# ---- heuristic (default) ---------------------------------------------------
def test_heuristic_easy_lookup_stays_small():
    c = _Classifier()
    r = ModelRouter(c, "small", "big")
    assert r.pick("which PC is down?") == ("small", "easy")
    assert r.pick("PC ไหนปิดอยู่บ้าง") == ("small", "easy")
    assert c.structured_calls == 0                     # heuristic = no LLM call


def test_heuristic_coding_is_hard_and_routes_up_when_pulled():
    r = ModelRouter(_Classifier(pulled=("small", "big")), "small", "big")
    assert r.pick("write a Python function to parse the log") == ("big", "hard")
    assert r.pick("เขียนฟังก์ชัน parse log 4625 ให้หน่อย") == ("big", "hard")


def test_heuristic_hard_stays_small_when_big_not_pulled():
    r = ModelRouter(_Classifier(pulled=("small",)), "small", "big")
    assert r.pick("refactor and debug this module") == ("small", "hard")


# ---- opt-in LLM classifier -------------------------------------------------
def test_llm_can_upgrade_an_easy_looking_question():
    # heuristic says easy (no hint words) but the LLM judges it hard
    c = _Classifier(difficulty="hard", pulled=("small", "big"))
    r = ModelRouter(c, "small", "big", use_llm=True)
    assert r.pick("should we unlock mary or investigate further") == ("big", "hard")
    assert c.structured_calls == 1


def test_llm_failure_falls_back_to_heuristic():
    c = _Classifier(raise_exc=StructuredError("x"), pulled=("small", "big"))
    r = ModelRouter(c, "small", "big", use_llm=True)
    assert r.pick("what's the system status") == ("small", "easy")   # heuristic easy stands


def test_llm_not_called_when_heuristic_already_hard():
    c = _Classifier(pulled=("small", "big"))
    r = ModelRouter(c, "small", "big", use_llm=True)
    r.pick("debug this regex")                          # heuristic hard → skip the LLM
    assert c.structured_calls == 0


# ---- availability cached ---------------------------------------------------
def test_availability_is_cached():
    calls = {"n": 0}

    class _C(_Classifier):
        def list_models(self):
            calls["n"] += 1
            return ["small", "big"]

    r = ModelRouter(_C(), "small", "big")
    r.pick("refactor a"); r.pick("debug b")            # both heuristic-hard → check pulled
    assert calls["n"] == 1                              # list_models hit once, then cached
