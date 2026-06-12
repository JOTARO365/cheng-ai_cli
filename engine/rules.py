"""Rule Engine — the harness that filters/escalates signals BEFORE the AI.

This is the resource-saving gate from the architecture: collectors feed raw signals
in, the engine applies the documented escalation ladder, and only genuinely
interesting events reach the local LLM. The AI is NEVER called from a collector —
only the engine decides to call it (via the on_ai callback).

Pattern (borrowed conceptually from a shell's builtin dispatch — avoid an if/else
forest): each signal `kind` maps to a handler in `_dispatch`. The decide_* functions
are PURE (no I/O) so the thresholds can be unit-tested in a table; `process()` is the
only part with side effects (writing events / raising alerts / invoking the AI).

A "signal" is a plain dict, e.g.:
    {"kind": "login_fail", "host": "PC07", "user": "john", "count": 5}
    {"kind": "node_offline", "host": "PC12", "offline_sec": 420}
    {"kind": "service_down", "host": "SRV1", "service": "Spooler"}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from engine.thresholds import Thresholds, is_work_time
from storage.db import Database

log = logging.getLogger(__name__)

# action labels
ACTION_LOG = "log_only"
ACTION_WAIT = "wait"
ACTION_AI = "escalate_ai"
ACTION_ALERT = "alert"


@dataclass
class Decision:
    action: str        # one of ACTION_*
    severity: str      # info | warning | critical
    reason: str        # human-readable why
    alert: bool = False   # raise an alert now?
    send_ai: bool = False  # hand off to the local LLM for analysis?


# --------------------------------------------------------------------------
# PURE decision functions — no I/O, fully unit-testable.
# --------------------------------------------------------------------------
def decide_login_fail(count: int, t: Thresholds) -> Decision:
    if count >= t.login_fail_alert_min:
        return Decision(
            ACTION_ALERT, "critical",
            f"{count} login failures (>= {t.login_fail_alert_min}) — alert immediately",
            alert=True, send_ai=False,
        )
    if count >= t.login_fail_ai_min:
        return Decision(
            ACTION_AI, "warning",
            f"{count} login failures (>= {t.login_fail_ai_min}) — analyze pattern",
            alert=False, send_ai=True,
        )
    return Decision(
        ACTION_LOG, "info",
        f"{count} login failure(s) (<= {t.login_fail_log_max}) — log only",
    )


def decide_node_offline(offline_sec: float, when: datetime, t: Thresholds) -> Decision:
    if offline_sec < t.node_offline_wait_sec:
        return Decision(
            ACTION_WAIT, "info",
            f"offline {int(offline_sec)}s (< {t.node_offline_wait_sec}s) — wait",
        )
    if offline_sec >= t.node_offline_alert_sec:
        if is_work_time(when, t):
            return Decision(
                ACTION_ALERT, "warning",
                f"offline {int(offline_sec)}s (>= {t.node_offline_alert_sec}s) during work hours",
                alert=True,
            )
        return Decision(
            ACTION_LOG, "info",
            f"offline {int(offline_sec)}s but outside work hours — log only",
        )
    # between wait and alert thresholds: keep watching, no page yet
    return Decision(
        ACTION_LOG, "info",
        f"offline {int(offline_sec)}s — watching (below alert threshold)",
    )


def decide_service_down(service: str, t: Thresholds) -> Decision:
    return Decision(
        ACTION_ALERT, "critical",
        f"service '{service}' is down — alert now + assess impact",
        alert=True, send_ai=True,
    )


def decide_account_lockout(user: str, t: Thresholds) -> Decision:
    # A lockout (Event 4740) is always worth telling IT, and worth AI context
    # (was it the user fat-fingering, or a brute-force that tripped the policy?).
    return Decision(
        ACTION_ALERT, "warning",
        f"account '{user}' was locked out — alert IT + analyze cause",
        alert=True, send_ai=True,
    )


# --------------------------------------------------------------------------
# Engine: wires decisions to side effects (DB, alerts, AI).
# --------------------------------------------------------------------------
AlertCallback = Callable[[Decision, dict[str, Any]], None]
AiCallback = Callable[[Decision, dict[str, Any]], None]


class RuleEngine:
    def __init__(
        self,
        db: Database,
        thresholds: Thresholds | None = None,
        on_alert: AlertCallback | None = None,
        on_ai: AiCallback | None = None,
    ) -> None:
        self.db = db
        self.t = thresholds or Thresholds.from_env()
        self.on_alert = on_alert
        self.on_ai = on_ai
        # signal kind -> handler (dispatch table instead of an if/else forest)
        self._dispatch: dict[str, Callable[[dict[str, Any]], Decision]] = {
            "login_fail": self._on_login_fail,
            "account_lockout": self._on_account_lockout,
            "node_offline": self._on_node_offline,
            "service_down": self._on_service_down,
        }

    def process(self, signal: dict[str, Any]) -> Decision:
        """Evaluate one signal, apply side effects, return the Decision."""
        kind = signal.get("kind")
        handler = self._dispatch.get(kind or "")
        if handler is None:
            log.warning("rule engine: no handler for signal kind %r", kind)
            return Decision(ACTION_LOG, "info", f"unhandled signal kind {kind!r}")
        decision = handler(signal)
        self._apply(decision, signal)
        return decision

    # ---- handlers (extract fields, call the pure decider) ----------------
    def _on_login_fail(self, s: dict[str, Any]) -> Decision:
        return decide_login_fail(int(s.get("count", 1)), self.t)

    def _on_account_lockout(self, s: dict[str, Any]) -> Decision:
        return decide_account_lockout(str(s.get("user", "?")), self.t)

    def _on_node_offline(self, s: dict[str, Any]) -> Decision:
        when = s.get("when") or datetime.now()
        return decide_node_offline(float(s.get("offline_sec", 0)), when, self.t)

    def _on_service_down(self, s: dict[str, Any]) -> Decision:
        return decide_service_down(str(s.get("service", "?")), self.t)

    # ---- side effects ----------------------------------------------------
    def _apply(self, decision: Decision, signal: dict[str, Any]) -> None:
        host = signal.get("host")
        self.db.record_event(
            source="rule_engine",
            kind=signal.get("kind", "unknown"),
            severity=decision.severity,
            message=decision.reason,
            host=host,
            data={"action": decision.action, **{k: v for k, v in signal.items() if k != "kind"}},
        )
        if decision.alert:
            title = f"[{decision.severity.upper()}] {signal.get('kind')} {host or ''}".strip()
            alert_id = self.db.record_alert(decision.severity, title, decision.reason)
            log.warning("ALERT #%d: %s — %s", alert_id, title, decision.reason)
            if self.on_alert:
                try:
                    self.on_alert(decision, signal)
                except Exception:
                    log.exception("rule engine: on_alert callback failed")
        if decision.send_ai and self.on_ai:
            try:
                self.on_ai(decision, signal)
            except Exception:
                log.exception("rule engine: on_ai callback failed")

    # ---- convenience: scan current down nodes from the DB ----------------
    def scan_offline_nodes(self, now: datetime | None = None) -> list[Decision]:
        """Look at nodes currently 'down', compute how long they've been offline
        (from last_seen), and run each through the offline rule. Returns decisions.
        Nodes never seen 'up' (last_seen is NULL) are skipped — we can't prove a
        duration, so we don't page on them."""
        now = now or datetime.now(timezone.utc)
        decisions: list[Decision] = []
        for node in self.db.list_nodes(status="down"):
            if not node.last_seen:
                continue
            try:
                last = datetime.fromisoformat(node.last_seen)
            except ValueError:
                continue
            offline_sec = (now - last).total_seconds()
            # is_work_time uses local wall-clock; convert for the work-hours check
            decisions.append(
                self.process(
                    {
                        "kind": "node_offline",
                        "host": node.host,
                        "offline_sec": offline_sec,
                        "when": datetime.now(),
                    }
                )
            )
        return decisions
