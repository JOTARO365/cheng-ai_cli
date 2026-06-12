"""Table-driven tests for the Rule Engine decision logic.

These cover the escalation ladder from the architecture doc. The decide_* functions
are pure, so no DB / Ollama / network is needed — runs anywhere, offline.
"""
from datetime import datetime

import pytest

from engine.rules import (
    ACTION_AI,
    ACTION_ALERT,
    ACTION_LOG,
    ACTION_WAIT,
    decide_login_fail,
    decide_node_offline,
    decide_service_down,
)
from engine.thresholds import Thresholds, is_work_time

T = Thresholds()  # defaults: ai>=3, alert>=5, wait<120s, offline-alert>=300s

WORK_TIME = datetime(2026, 6, 10, 10, 0)   # Wed 10:00 — within work hours
AFTER_HOURS = datetime(2026, 6, 10, 22, 0)  # Wed 22:00 — outside work hours
WEEKEND = datetime(2026, 6, 13, 10, 0)      # Sat 10:00 — non-work day


@pytest.mark.parametrize(
    "count,expected_action,expect_alert,expect_ai",
    [
        (0, ACTION_LOG, False, False),
        (1, ACTION_LOG, False, False),
        (2, ACTION_LOG, False, False),   # boundary: still log-only
        (3, ACTION_AI, False, True),     # boundary: first AI escalation
        (4, ACTION_AI, False, True),
        (5, ACTION_ALERT, True, False),  # boundary: alert now, skip AI
        (9, ACTION_ALERT, True, False),
    ],
)
def test_login_fail_ladder(count, expected_action, expect_alert, expect_ai):
    d = decide_login_fail(count, T)
    assert d.action == expected_action
    assert d.alert is expect_alert
    assert d.send_ai is expect_ai


@pytest.mark.parametrize(
    "offline_sec,when,expected_action,expect_alert",
    [
        (60, WORK_TIME, ACTION_WAIT, False),     # < 2 min => wait
        (119, WORK_TIME, ACTION_WAIT, False),    # boundary just under wait
        (120, WORK_TIME, ACTION_LOG, False),     # between wait & alert => watch
        (299, WORK_TIME, ACTION_LOG, False),     # boundary just under alert
        (300, WORK_TIME, ACTION_ALERT, True),    # >= 5 min, work hours => ALERT
        (600, AFTER_HOURS, ACTION_LOG, False),   # long offline but after hours => log
        (600, WEEKEND, ACTION_LOG, False),       # weekend => log, no page
    ],
)
def test_node_offline_ladder(offline_sec, when, expected_action, expect_alert):
    d = decide_node_offline(offline_sec, when, T)
    assert d.action == expected_action
    assert d.alert is expect_alert


def test_service_down_always_alerts_and_asks_ai():
    d = decide_service_down("Spooler", T)
    assert d.action == ACTION_ALERT
    assert d.alert is True
    assert d.send_ai is True


def test_is_work_time():
    assert is_work_time(WORK_TIME, T) is True
    assert is_work_time(AFTER_HOURS, T) is False
    assert is_work_time(WEEKEND, T) is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("TH_LOGIN_FAIL_ALERT", "3")
    t = Thresholds.from_env()
    assert t.login_fail_alert_min == 3
    # with the override, 3 fails should now alert immediately
    assert decide_login_fail(3, t).alert is True
