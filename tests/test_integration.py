"""Integration: Rule Engine wired to the REAL alert dispatcher + AI analyst.

Proves the product path (replacing fake_alert/fake_ai) — offline: alert channels are
mocked, and the analyst's Brain is faked so no Ollama is needed.
"""
from __future__ import annotations

from unittest.mock import patch

from ai.escalate import Analyst
from alert.dispatch import AlertDispatcher
from engine.rules import Decision, RuleEngine
from engine.thresholds import Thresholds
from storage.db import Database


class _Cfg:
    ollama_host = "http://x"
    ollama_model = "m"
    ad_domain = "corp.local"
    alert_teams_webhook = None
    alert_line_token = None
    alert_email_smtp = None


_DEC = Decision("alert", "critical", "service 'Spooler' is down", alert=True, send_ai=True)
_SIG = {"kind": "service_down", "host": "SRV1", "service": "Spooler"}


def test_dispatch_noop_when_unconfigured():
    assert AlertDispatcher(_Cfg()).dispatch(_DEC, _SIG) == []   # nothing leaves the box


def test_dispatch_teams_when_configured():
    cfg = _Cfg()
    cfg.alert_teams_webhook = "https://hook.example/x"
    with patch("alert.dispatch.requests.post") as post:
        post.return_value.raise_for_status = lambda: None
        sent = AlertDispatcher(cfg).dispatch(_DEC, _SIG)
    assert sent == ["teams"] and post.called


def test_dispatch_channel_failure_never_raises():
    cfg = _Cfg()
    cfg.alert_teams_webhook = "https://hook.example/x"
    with patch("alert.dispatch.requests.post", side_effect=RuntimeError("boom")):
        assert AlertDispatcher(cfg).dispatch(_DEC, _SIG) == []   # swallowed, not raised


class _FakeBrain:
    available = True
    def is_available(self): return self.available
    def new_history(self): return []
    def ask(self, h, q, **k): return "Likely brute-force from one IP; watch for a lockout."


def test_engine_escalation_stores_ai_analysis(tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    analyst = Analyst(_Cfg(), db)
    monkeypatch.setattr(analyst, "_brain", lambda system: _FakeBrain())
    eng = RuleEngine(db, thresholds=Thresholds(),
                     on_alert=AlertDispatcher(_Cfg()).dispatch, on_ai=analyst.on_ai)

    eng.process({"kind": "login_fail", "host": "PC07", "user": "john", "count": 4})  # 3<=4<5 → AI

    evs = db.recent_events(20)
    assert any(e["source"] == "ai" and "brute-force" in e["message"] for e in evs)


def test_escalation_skips_when_ollama_down(tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    analyst = Analyst(_Cfg(), db)
    fb = _FakeBrain()
    fb.available = False
    monkeypatch.setattr(analyst, "_brain", lambda system: fb)
    assert analyst.on_ai(_DEC, {"kind": "login_fail", "host": "PC07", "count": 4}) is None
    assert not any(e["source"] == "ai" for e in db.recent_events(20))
