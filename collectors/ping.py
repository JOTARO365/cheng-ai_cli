"""Ping collector — checks every monitored node and records its up/down state.

Design rules (see .claude/skills/skill.md):
- This collector must NEVER crash the agent. Every tick is wrapped; a flaky host
  logs an error and the loop keeps going.
- On timeout we mark the node 'down' (a failed reply), and only escalate to a state
  change / event when the status actually flips, so we don't spam the event log.
- Windows `ping` output is localized (Thai/other) — we rely on the return code for
  up/down and parse latency best-effort with a regex. Output is decoded with
  errors='ignore' to dodge cp874/utf-8 issues (see powershell-windows-encoding).

The Rule Engine (engine/rules.py) decides what to do with the events recorded here;
this module only gathers facts and persists them.
"""
from __future__ import annotations

import logging
import platform
import re
import subprocess
import threading
from dataclasses import dataclass

from config import Config
from storage.db import Database, utcnow

log = logging.getLogger(__name__)

_LATENCY_RE = re.compile(r"[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_IS_WINDOWS = platform.system().lower().startswith("win")


@dataclass
class PingResult:
    host: str
    alive: bool
    latency_ms: float | None


def ping_host(host: str, timeout_ms: int = 1000) -> PingResult:
    """Send a single ICMP echo. Never raises — returns alive=False on any failure."""
    if _IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        # -W is seconds on Linux/mac; round up to >=1
        cmd = ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), host]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=(timeout_ms / 1000) + 2,  # hard wall in case ping hangs
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("ping %s failed to execute: %s", host, exc)
        return PingResult(host=host, alive=False, latency_ms=None)

    out = proc.stdout.decode("utf-8", errors="ignore") + proc.stderr.decode(
        "utf-8", errors="ignore"
    )
    alive = proc.returncode == 0
    latency: float | None = None
    if alive:
        m = _LATENCY_RE.search(out)
        if m:
            latency = float(m.group(1))
    return PingResult(host=host, alive=alive, latency_ms=latency)


def check_node(db: Database, host: str, timeout_ms: int) -> PingResult:
    """Ping one host, update its row, and record an event only on a state change."""
    result = ping_host(host, timeout_ms)
    prev = db.get_node(host)
    prev_status = prev.status if prev else "unknown"
    new_status = "up" if result.alive else "down"

    fails = 0 if result.alive else (prev.consecutive_fails + 1 if prev else 1)
    last_seen = utcnow() if result.alive else (prev.last_seen if prev else None)

    db.upsert_node(
        host=host,
        status=new_status,
        latency_ms=result.latency_ms,
        consecutive_fails=fails,
        last_seen=last_seen,
    )

    if new_status != prev_status and prev_status != "unknown":
        kind = "node_up" if result.alive else "node_down"
        severity = "info" if result.alive else "warning"
        msg = (
            f"{host} is back UP ({result.latency_ms} ms)"
            if result.alive
            else f"{host} went DOWN (no reply)"
        )
        db.record_event(
            source="ping",
            kind=kind,
            severity=severity,
            host=host,
            message=msg,
            data={"latency_ms": result.latency_ms, "consecutive_fails": fails},
        )
        log.warning("state change: %s", msg)
    return result


def check_once(config: Config, db: Database) -> list[PingResult]:
    """Ping every configured target once. Per-host errors are isolated."""
    if not config.ping_targets:
        log.info("ping: no targets configured (set PING_TARGETS or data/nodes.txt)")
        return []
    results: list[PingResult] = []
    for host in config.ping_targets:
        try:
            results.append(check_node(db, host, config.ping_timeout_ms))
        except Exception:  # never let one host kill the sweep
            log.exception("ping: unexpected error checking %s", host)
    up = sum(1 for r in results if r.alive)
    log.info("ping sweep: %d/%d up", up, len(results))
    return results


def run_loop(config: Config, db: Database, stop: threading.Event) -> None:
    """Run check_once() forever until `stop` is set, sleeping ping_interval_sec."""
    log.info(
        "ping loop started: %d target(s), every %ds",
        len(config.ping_targets),
        config.ping_interval_sec,
    )
    while not stop.is_set():
        try:
            check_once(config, db)
        except Exception:  # the loop must survive anything
            log.exception("ping: sweep failed")
        stop.wait(config.ping_interval_sec)
    log.info("ping loop stopped")


if __name__ == "__main__":
    # Manual smoke test:  python -m collectors.ping
    from config import load_config, setup_logging

    setup_logging()
    cfg = load_config()
    database = Database(cfg.db_path)
    for r in check_once(cfg, database):
        status = "UP  " if r.alive else "DOWN"
        print(f"{status} {r.host}  {r.latency_ms if r.latency_ms is not None else '-'} ms")
