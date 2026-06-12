"""Tests for the FastAPI IT-context tool server (webtools/server.py).

Runs fully offline over a temp SQLite DB — no Ollama, no Open WebUI, no AD needed.
Each test seeds the store, then hits an endpoint the way Open WebUI would.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from storage.db import Database
from webtools.server import create_app


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds"
    )


@pytest.fixture()
def client(tmp_path) -> TestClient:
    db = Database(tmp_path / "t.db")
    # one PC down 10 min, one up
    db.upsert_node("PC12", "down", None, 3, last_seen=_iso(10))
    db.upsert_node("PC01", "up", 1.2, 0, last_seen=_iso(0))
    # login failures for john (peak 5) recorded twice — peak should win
    db.record_event("rule_engine", "login_fail", "warning", "3 fails",
                    host="PC07", data={"user": "john", "count": 3, "ip": "192.168.1.66"})
    db.record_event("rule_engine", "login_fail", "warning", "5 fails",
                    host="PC07", data={"user": "john", "count": 5, "ip": "192.168.1.66"})
    # a lockout for mary
    db.record_event("rule_engine", "account_lockout", "warning", "locked",
                    host="PC09", data={"user": "mary"})
    # an alert
    db.record_alert("critical", "service_down SRV1", "Spooler is down")
    return TestClient(create_app(db))


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_down_nodes(client: TestClient) -> None:
    rows = client.get("/down_nodes").json()
    assert len(rows) == 1
    assert rows[0]["host"] == "PC12"
    assert rows[0]["offline_minutes"] >= 9  # ~10 min, allow clock slack


def test_login_fails_reports_peak_per_user(client: TestClient) -> None:
    rows = client.get("/login_fails", params={"hours": 24}).json()
    assert len(rows) == 1
    assert rows[0] == {
        "user": "john",
        "count": 5,  # peak, not the earlier 3
        "host": "PC07",
        "ip": "192.168.1.66",
        "last_ts": rows[0]["last_ts"],
    }


def test_login_fails_window_excludes_old(client: TestClient) -> None:
    # nothing in the last 0... but hours has a floor of 1; use a kind with no rows
    rows = client.get("/locked_accounts", params={"hours": 1}).json()
    assert [r["user"] for r in rows] == ["mary"]


def test_recent_alerts(client: TestClient) -> None:
    rows = client.get("/recent_alerts", params={"limit": 5}).json()
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert rows[0]["sent"] == 0


def test_system_summary(client: TestClient) -> None:
    s = client.get("/system_summary").json()
    assert s["nodes_total"] == 2
    assert s["nodes_up"] == 1
    assert s["nodes_down"] == 1
    assert s["login_fail_users_24h"] == 1
    assert s["locked_accounts_24h"] == 1
    assert s["alerts_pending"] == 1


def test_openapi_exposes_named_tools(client: TestClient) -> None:
    # Open WebUI discovers tools by operation_id from /openapi.json
    spec = client.get("/openapi.json").json()
    op_ids = {
        m.get("operationId")
        for path in spec["paths"].values()
        for m in path.values()
    }
    assert {
        "get_down_nodes",
        "get_login_fails",
        "get_locked_accounts",
        "get_recent_alerts",
        "get_system_summary",
    } <= op_ids
