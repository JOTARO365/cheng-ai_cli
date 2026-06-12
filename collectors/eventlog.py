"""Windows Event Log collector — login failures (4625) and lockouts (4740).

It reads NEW Security-log records, correlates login failures per user inside a
rolling window, and feeds signals into the Rule Engine (which alone decides whether
to alert / call the AI). It never alerts directly.

Design notes:
- pywin32 is imported LAZILY inside WindowsEventSource so this module imports fine on
  any OS (and so the sandbox can run without Windows privileges).
- Reading the Security log needs the "Manage auditing and security log" right (or
  local admin) — see docs/setup.md. On first run we establish a baseline and emit
  NOTHING, so we don't replay historical failures as fresh alerts.
- Everything is wrapped so a flaky read can never crash the agent loop.

The `EventSource` Protocol lets us swap the real Windows reader for the
`SimulatedEventSource` used by the sandbox and tests — same collector code path.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Protocol

from engine.rules import RuleEngine

log = logging.getLogger(__name__)

EVENT_LOGIN_FAIL = 4625
EVENT_ACCOUNT_LOCKOUT = 4740
WANTED_EVENTS = frozenset({EVENT_LOGIN_FAIL, EVENT_ACCOUNT_LOCKOUT})


@dataclass
class SecurityEvent:
    event_id: int
    when: datetime
    user: str
    host: str | None = None       # source workstation or IP
    raw: dict | None = None


class EventSource(Protocol):
    def read_new(self) -> Iterable[SecurityEvent]:
        """Return SecurityEvents seen since the last call (chronological order)."""
        ...


# --------------------------------------------------------------------------
# Login-failure correlation (pure, testable)
# --------------------------------------------------------------------------
class LoginFailTracker:
    """Counts login failures per user within a rolling time window."""

    def __init__(self, window_sec: int) -> None:
        self.window = timedelta(seconds=window_sec)
        self._hits: dict[str, list[datetime]] = defaultdict(list)

    def add(self, user: str, when: datetime) -> int:
        times = self._hits[user]
        times.append(when)
        cutoff = when - self.window
        # keep only hits inside the window
        self._hits[user] = [t for t in times if t >= cutoff]
        return len(self._hits[user])

    def reset(self, user: str) -> None:
        self._hits.pop(user, None)


# --------------------------------------------------------------------------
# Collector — wires an EventSource to the Rule Engine
# --------------------------------------------------------------------------
class EventLogCollector:
    def __init__(self, source: EventSource, engine: RuleEngine, window_sec: int) -> None:
        self.source = source
        self.engine = engine
        self.tracker = LoginFailTracker(window_sec)

    def check_once(self) -> int:
        """Process all new events; return how many were handled."""
        handled = 0
        try:
            events = list(self.source.read_new())
        except Exception:
            log.exception("eventlog: read failed")
            return 0

        for ev in events:
            try:
                self._handle(ev)
                handled += 1
            except Exception:
                log.exception("eventlog: failed to handle %r", ev)
        if handled:
            log.info("eventlog: processed %d security event(s)", handled)
        return handled

    def _handle(self, ev: SecurityEvent) -> None:
        if ev.event_id == EVENT_LOGIN_FAIL:
            count = self.tracker.add(ev.user, ev.when)
            self.engine.process(
                {
                    "kind": "login_fail",
                    "host": ev.host,
                    "user": ev.user,
                    "count": count,
                    "ip": (ev.raw or {}).get("ip"),
                }
            )
        elif ev.event_id == EVENT_ACCOUNT_LOCKOUT:
            # a lockout resets the fail streak — the policy already acted
            self.tracker.reset(ev.user)
            self.engine.process(
                {"kind": "account_lockout", "host": ev.host, "user": ev.user}
            )

    def run_loop(self, stop: threading.Event, interval_sec: int = 30) -> None:
        log.info("eventlog loop started (every %ds)", interval_sec)
        while not stop.is_set():
            self.check_once()
            stop.wait(interval_sec)
        log.info("eventlog loop stopped")


# --------------------------------------------------------------------------
# Real Windows reader (pywin32) — Windows only, lazily imported
# --------------------------------------------------------------------------
class WindowsEventSource:
    """Reads the live Windows Security log via pywin32."""

    def __init__(self, server: str | None = None) -> None:
        self.server = server
        self._last_record: int | None = None  # None until baseline established

    def read_new(self) -> list[SecurityEvent]:
        try:
            import win32evtlog  # lazy: only needed on the Windows host
        except ImportError:
            log.error("eventlog: pywin32 not available — cannot read Security log")
            return []

        try:
            handle = win32evtlog.OpenEventLog(self.server, "Security")
        except Exception:
            log.exception("eventlog: OpenEventLog failed (need audit-log rights?)")
            return []

        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        baseline = self._last_record is None
        collected: list[SecurityEvent] = []
        highest = self._last_record or 0
        try:
            while True:
                records = win32evtlog.ReadEventLog(handle, flags, 0)
                if not records:
                    break
                stop = False
                for r in records:
                    rec = r.RecordNumber
                    if self._last_record is not None and rec <= self._last_record:
                        stop = True
                        break
                    highest = max(highest, rec)
                    eid = r.EventID & 0xFFFF
                    if not baseline and eid in WANTED_EVENTS:
                        parsed = _parse_record(eid, r)
                        if parsed:
                            collected.append(parsed)
                if stop:
                    break
        except Exception:
            log.exception("eventlog: ReadEventLog failed")
        finally:
            win32evtlog.CloseEventLog(handle)

        self._last_record = highest
        if baseline:
            log.info("eventlog: baseline set at record %d (history not replayed)", highest)
            return []
        return list(reversed(collected))  # chronological order


def _parse_record(eid: int, r: object) -> SecurityEvent | None:
    """Pull user/host out of a raw pywin32 EventLogRecord. String-insert indexes are
    the documented Microsoft layout; guarded because layouts vary by OS/locale."""
    si = list(getattr(r, "StringInserts", None) or [])
    try:
        when = datetime.fromtimestamp(int(r.TimeGenerated), tz=timezone.utc)  # type: ignore[attr-defined]
    except Exception:
        when = datetime.now(timezone.utc)

    def at(i: int) -> str | None:
        return si[i] if 0 <= i < len(si) else None

    if eid == EVENT_LOGIN_FAIL:
        user = at(5) or "?"          # TargetUserName
        workstation = at(13)          # WorkstationName
        ip = at(19)                   # IpAddress
        return SecurityEvent(eid, when, user, workstation or ip, raw={"ip": ip})
    if eid == EVENT_ACCOUNT_LOCKOUT:
        user = at(0) or "?"          # TargetUserName (locked account)
        caller = at(1)                # caller computer
        return SecurityEvent(eid, when, user, caller)
    return None


# --------------------------------------------------------------------------
# Simulated reader — for the sandbox and tests (no Windows needed)
# --------------------------------------------------------------------------
class SimulatedEventSource:
    """Yields pre-scripted SecurityEvents. Push events, then read_new() drains them."""

    def __init__(self, events: Iterable[SecurityEvent] | None = None) -> None:
        self._queue: list[SecurityEvent] = list(events or [])

    def push(self, event: SecurityEvent) -> None:
        self._queue.append(event)

    def push_login_fail(self, user: str, host: str, ip: str | None = None,
                        when: datetime | None = None) -> None:
        self.push(SecurityEvent(EVENT_LOGIN_FAIL, when or datetime.now(timezone.utc),
                                user, host, raw={"ip": ip}))

    def push_lockout(self, user: str, host: str, when: datetime | None = None) -> None:
        self.push(SecurityEvent(EVENT_ACCOUNT_LOCKOUT, when or datetime.now(timezone.utc),
                                user, host))

    def read_new(self) -> list[SecurityEvent]:
        out, self._queue = self._queue, []
        return out
