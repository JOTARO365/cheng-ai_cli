"""Seed the REAL db (DB_PATH) with a little demo data so the chatbot has something
to talk about on a first try — before live collectors / AD are wired up.

This is DEMO data, clearly fake, written to your configured DB_PATH so Open WebUI
(via the tool server) returns real answers to questions like:
    "PC ไหนปิดอยู่บ้าง"   /  "login fail วันนี้มีกี่ครั้ง"  /  "สถานะระบบตอนนี้เป็นยังไง"

Run:  python -m sandbox.seed_demo
It clears prior rows first, so it's safe to re-run.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from config import load_config
from storage.db import Database

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds"
    )


def main() -> None:
    cfg = load_config()
    db = Database(cfg.db_path)
    with db._conn() as c:  # noqa: SLF001 — demo seeder only
        for tbl in ("events", "alerts", "nodes"):
            c.execute(f"DELETE FROM {tbl}")

    # nodes: 3 up, 2 down (one down a long time)
    db.upsert_node("PC01-RECEPTION", "up", 1.1, 0, last_seen=_iso(0))
    db.upsert_node("PC02-ACCOUNT", "up", 0.9, 0, last_seen=_iso(0))
    db.upsert_node("SRV1-FILE", "up", 0.4, 0, last_seen=_iso(0))
    db.upsert_node("PC12-SALES", "down", None, 4, last_seen=_iso(8))
    db.upsert_node("PC20-WAREHOUSE", "down", None, 9, last_seen=_iso(35))

    # login failures: a likely brute-force on 'john', a couple of fat-fingers
    db.record_event("rule_engine", "login_fail", "warning",
                    "6 login failures — alert immediately",
                    host="PC07-IT", data={"user": "john", "count": 6, "ip": "192.168.1.66"})
    db.record_event("rule_engine", "login_fail", "info",
                    "2 login failure(s) — log only",
                    host="PC02-ACCOUNT", data={"user": "nan", "count": 2, "ip": "192.168.1.42"})

    # an account lockout
    db.record_event("rule_engine", "account_lockout", "warning",
                    "account 'mary' was locked out",
                    host="PC09-HR", data={"user": "mary"})

    # alerts the system raised
    db.record_alert("critical", "service_down Spooler @ SRV1-FILE",
                    "Print Spooler is down — users can't print")
    db.record_alert("warning", "node_offline PC20-WAREHOUSE",
                    "PC20-WAREHOUSE offline 35 min during work hours")

    s = db.system_summary()
    print("✅ seeded demo data into", cfg.db_path)
    print("   nodes:", s["nodes_up"], "up /", s["nodes_down"], "down")
    print("   login-fail users (24h):", s["login_fail_users_24h"],
          "| locked (24h):", s["locked_accounts_24h"],
          "| alerts pending:", s["alerts_pending"])
    print("\nTry asking the chatbot: 'PC ไหนปิดอยู่บ้าง' / 'login fail วันนี้กี่ครั้ง' / 'สถานะระบบตอนนี้'")


if __name__ == "__main__":
    main()
