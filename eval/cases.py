"""Eval cases + the deterministic data they're scored against.

Each case: a question, the keywords the answer MUST contain (ground truth, derived
from SEED below), and the tool the model should call. `seed(db)` writes the same
fixture into any Database so the eval is reproducible and never touches real data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from storage.db import Database


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds"
    )


def seed(db: Database) -> None:
    """Known fixture: 3 up / 2 down, john 6 fails (peak), nan 2, mary locked, 2 alerts."""
    with db._conn() as c:  # noqa: SLF001 (eval fixture)
        for t in ("events", "alerts", "nodes"):
            c.execute(f"DELETE FROM {t}")
    db.upsert_node("PC01-RECEPTION", "up", 1.0, 0, last_seen=_iso(0))
    db.upsert_node("PC02-ACCOUNT", "up", 1.0, 0, last_seen=_iso(0))
    db.upsert_node("SRV1-FILE", "up", 0.5, 0, last_seen=_iso(0))
    db.upsert_node("PC12-SALES", "down", None, 4, last_seen=_iso(9))
    db.upsert_node("PC20-WAREHOUSE", "down", None, 9, last_seen=_iso(40))   # offline longest
    db.record_event("rule_engine", "login_fail", "warning", "6 fails",
                    host="PC07-IT", data={"user": "john", "count": 6, "ip": "192.168.1.66"})
    db.record_event("rule_engine", "login_fail", "info", "2 fails",
                    host="PC02-ACCOUNT", data={"user": "nan", "count": 2, "ip": "192.168.1.42"})
    db.record_event("rule_engine", "account_lockout", "warning", "locked",
                    host="PC09-HR", data={"user": "mary"})
    db.record_alert("critical", "service_down Spooler", "Print Spooler down")
    db.record_alert("warning", "node_offline PC20-WAREHOUSE", "offline 40m")


# must_include = ALL of these (lowercased) must appear in the answer to count correct.
CASES: list[dict] = [
    {"q": "PC ไหนปิดอยู่บ้าง", "must_include": ["pc20", "pc12"], "tool": "get_down_nodes"},
    {"q": "which machines are offline right now?", "must_include": ["pc20", "pc12"], "tool": "get_down_nodes"},
    {"q": "เครื่องไหน offline นานที่สุด", "must_include": ["pc20"], "tool": "get_down_nodes"},
    {"q": "login fail วันนี้ใครเยอะสุด กี่ครั้ง", "must_include": ["john", "6"], "tool": "get_login_fails"},
    {"q": "nan login fail กี่ครั้ง", "must_include": ["2"], "tool": "get_login_fails"},
    {"q": "มีใครโดน lock บ้าง", "must_include": ["mary"], "tool": "get_locked_accounts"},
    {"q": "ตอนนี้มี alert ค้างกี่อัน", "must_include": ["2"], "tool": "get_recent_alerts"},
    {"q": "สรุปสถานะระบบ มีกี่เครื่อง down", "must_include": ["2"], "tool": "get_system_summary"},
]


def score(case: dict, answer: str, tools_called: list[str]) -> tuple[bool, bool]:
    """Return (fact_ok, tool_ok). Pure — unit-testable without a model."""
    a = (answer or "").lower()
    fact_ok = all(k.lower() in a for k in case["must_include"])
    tool_ok = case["tool"] in (tools_called or [])
    return fact_ok, tool_ok
