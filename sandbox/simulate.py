"""Sandbox — simulate a real IT day end-to-end, no AD / Ollama / privileges needed.

It wires the REAL Rule Engine + EventLog collector to a SimulatedEventSource and
plays out the problems an SME IT team actually hits: a brute-force login, an account
lockout, a PC going offline, and a service dying. For each, you see exactly what the
system decides (log / wait / escalate-to-AI / ALERT) and what IT would receive.

The AI and alert channels are STUBBED here (Ollama isn't installed yet, and we don't
spam Line/Teams in a sandbox) — the callbacks just print what *would* happen. When
ai/brain.py and alert/dispatch.py exist, drop them in as these same callbacks.

Run:  python -m sandbox.simulate
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# This entrypoint prints emoji + Thai; force UTF-8 so the Windows console (cp874)
# doesn't choke. See powershell-windows-encoding.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from ai.escalate import Analyst
from alert.dispatch import AlertDispatcher
from collectors.eventlog import EventLogCollector, SimulatedEventSource
from config import load_config
from engine.rules import Decision
from engine.rules import RuleEngine
from engine.thresholds import Thresholds
from storage.db import Database

# A fixed "now" inside work hours so the offline scenario alerts deterministically.
WORK_NOW = datetime(2026, 6, 10, 10, 0)


def banner(text: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


# ---- REAL integrations: alert dispatcher + AI analyst (offline-safe) --------
# These are the production on_alert / on_ai. AlertDispatcher no-ops (logs) when no
# channel is configured; Analyst skips gracefully if Ollama isn't running — so this
# narrative still runs offline, but now exercises the real wiring.
def make_callbacks(cfg, db):
    dispatcher = AlertDispatcher(cfg)
    analyst = Analyst(cfg, db)

    def on_alert(decision: Decision, signal: dict) -> None:
        chans = dispatcher.dispatch(decision, signal)
        where = " → " + ", ".join(chans) if chans else " (no channel configured)"
        print(f"     📢 ALERT{where}  | [{decision.severity.upper()}] "
              f"{signal.get('kind')} on {signal.get('host', '?')}")

    def on_ai(decision: Decision, signal: dict) -> None:
        verdict = analyst.on_ai(decision, signal)
        print(f"     🧠 AI → {verdict}" if verdict
              else "     🧠 AI → (Ollama offline — skipped; rule alert still stands)")

    return on_alert, on_ai


def report(label: str, d: Decision) -> None:
    flags = []
    if d.send_ai:
        flags.append("→AI")
    if d.alert:
        flags.append("→ALERT")
    tag = (" " + " ".join(flags)) if flags else ""
    print(f"   [{d.action:11}] {label:42} {tag}")


def main() -> None:
    db = Database(Path(tempfile.gettempdir()) / "itagent_sandbox.db")
    # fresh slate each run
    for tbl in ("events", "alerts", "nodes"):
        with db._conn() as c:  # noqa: SLF001  (sandbox only)
            c.execute(f"DELETE FROM {tbl}")

    on_alert, on_ai = make_callbacks(load_config(), db)
    engine = RuleEngine(db, thresholds=Thresholds(), on_alert=on_alert, on_ai=on_ai)
    source = SimulatedEventSource()
    collector = EventLogCollector(source, engine, window_sec=Thresholds().login_fail_window_sec)

    print("\n🖥️  SME IT Agent — SANDBOX (simulated day)")
    print("   AI: real Analyst (skips if Ollama down)  |  Alerts: real dispatcher "
          "(no channel configured → logged only)")

    # ---- Scenario A: brute-force login on 'john' from PC07 ----------------
    banner("A) 09:01 — repeated login failures for 'john' (PC07 / 192.168.1.66)")
    for i in range(1, 7):
        source.push_login_fail("john", "PC07", ip="192.168.1.66", when=WORK_NOW)
        collector.check_once()  # collector counts within the window, feeds the engine
        # re-derive the decision label from the last engine call for display
    # show the ladder explicitly by replaying counts through the pure path:
    from engine.rules import decide_login_fail
    print("   ladder seen by the engine as failures accumulate:")
    for n in (1, 2, 3, 4, 5, 6):
        report(f"login_fail x{n} (john@PC07)", decide_login_fail(n, engine.t))

    # ---- Scenario B: account lockout (4740) for 'mary' -------------------
    banner("B) 09:05 — 'mary' account locked out (Event 4740)")
    source.push_lockout("mary", "PC09", when=WORK_NOW)
    collector.check_once()
    from engine.rules import decide_account_lockout
    report("account_lockout (mary@PC09)", decide_account_lockout("mary", engine.t))

    # ---- Scenario C: PC12 goes offline, time passes ----------------------
    banner("C) 11:00 — PC12 stops responding to ping (work hours)")
    from engine.rules import decide_node_offline
    for secs, note in [(60, "after 1 min"), (180, "after 3 min"), (360, "after 6 min")]:
        d = engine.process(
            {"kind": "node_offline", "host": "PC12", "offline_sec": secs, "when": WORK_NOW}
        )
        report(f"PC12 offline {note}", d)

    # ---- Scenario D: critical service down -------------------------------
    banner("D) 14:20 — Print Spooler service down on SRV1")
    d = engine.process({"kind": "service_down", "host": "SRV1", "service": "Spooler"})
    report("service_down (Spooler@SRV1)", d)

    # ---- end-of-day summary ----------------------------------------------
    banner("END OF DAY — what landed in the store")
    events = db.recent_events(99)
    alerts = [e for e in events if e["severity"] in ("warning", "critical")]
    print(f"   events recorded : {len(events)}")
    print(f"   alerts raised   : "
          f"{sum(1 for e in events if e['kind'] in ('login_fail','account_lockout','service_down','node_offline') and e['severity'] in ('warning','critical'))}")
    print("\n   IT would have been paged about:")
    seen = set()
    for e in events:
        key = (e["kind"], e["host"])
        if e["severity"] in ("warning", "critical") and key not in seen:
            seen.add(key)
            print(f"     • [{e['severity']}] {e['kind']} @ {e['host']}: {e['message']}")
    print()


if __name__ == "__main__":
    main()
