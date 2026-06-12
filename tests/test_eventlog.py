"""Tests for the event-log correlation + the simulated collector path (no Windows)."""
from datetime import datetime, timedelta, timezone

from collectors.eventlog import (
    EventLogCollector,
    LoginFailTracker,
    SimulatedEventSource,
)
from engine.rules import RuleEngine, decide_account_lockout, ACTION_ALERT
from engine.thresholds import Thresholds
from storage.db import Database


def test_login_fail_tracker_counts_within_window():
    t0 = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
    tr = LoginFailTracker(window_sec=600)
    assert tr.add("john", t0) == 1
    assert tr.add("john", t0 + timedelta(seconds=30)) == 2
    assert tr.add("john", t0 + timedelta(seconds=60)) == 3
    # a different user is counted separately
    assert tr.add("mary", t0) == 1


def test_login_fail_tracker_forgets_old_hits():
    t0 = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
    tr = LoginFailTracker(window_sec=300)
    tr.add("john", t0)
    tr.add("john", t0 + timedelta(seconds=100))
    # this one is >5 min after the first -> first drops out of the window
    assert tr.add("john", t0 + timedelta(seconds=400)) == 2


def test_lockout_resets_the_streak():
    tr = LoginFailTracker(window_sec=600)
    t0 = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
    tr.add("john", t0)
    tr.add("john", t0)
    tr.reset("john")
    assert tr.add("john", t0) == 1


def test_decide_account_lockout_alerts_and_asks_ai():
    d = decide_account_lockout("mary", Thresholds())
    assert d.action == ACTION_ALERT
    assert d.alert is True
    assert d.send_ai is True


def test_collector_brute_force_triggers_one_alert(tmp_path):
    db = Database(tmp_path / "t.db")
    alerts: list = []
    engine = RuleEngine(db, on_alert=lambda d, s: alerts.append(s))
    source = SimulatedEventSource()
    collector = EventLogCollector(source, engine, window_sec=600)

    when = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
    for _ in range(5):  # 5 fails => crosses the alert threshold
        source.push_login_fail("john", "PC07", ip="10.0.0.9", when=when)
    collector.check_once()

    # 5th failure alerts; 3rd & 4th asked the AI (no alert). Exactly one alert here.
    assert len(alerts) == 1
    assert alerts[0]["user"] == "john"
