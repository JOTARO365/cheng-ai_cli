"""Tests for the verifier (anti-hallucination): degeneracy heuristic + critic parsing."""
from __future__ import annotations

from ai.verify import Verifier, is_degenerate
from storage.db import Database


class _Cfg:
    ollama_host = "http://x"
    ollama_model = "m"


def test_degenerate_catches_repetition_loop():
    bad = "\n".join(f"{i}. check the server config and API access" for i in range(30))
    assert is_degenerate(bad)               # the exact small-model meltdown we saw


def test_normal_answer_not_degenerate():
    good = ("PC20 is offline 40 min.\nPC12 is offline 9 min.\nNo brute-force detected.\n"
            "All services are up.\nCheck the warehouse switch.\nContact the user.")
    assert not is_degenerate(good)


def test_verifier_shortcircuits_on_degenerate(tmp_path):
    v = Verifier(_Cfg(), Database(tmp_path / "t.db"))
    ok, issue = v.check("q", "\n".join("same line" for _ in range(20)), "evidence")
    assert ok is False and "repetit" in issue.lower()    # no model call needed


def test_verifier_parses_ok_and_fix(tmp_path, monkeypatch):
    v = Verifier(_Cfg(), Database(tmp_path / "t.db"))
    monkeypatch.setattr(v._brain, "ask", lambda h, q, **k: "OK")
    assert v.check("q", "a grounded one-line answer", "ev") == (True, "")
    monkeypatch.setattr(v._brain, "ask", lambda h, q, **k: "FIX: invented a host name")
    ok, issue = v.check("q", "a one-line answer", "ev")
    assert ok is False and "invented" in issue
