"""Alert dispatcher — sends an alert out via the configured channels.

This is the `on_alert` callback for the Rule Engine (replaces the sandbox's
fake_alert). Phase-1 rule: alerts are the ONLY outbound traffic allowed, and each
channel is OPT-IN — it fires only if its credential is present in .env. With the
default empty config NOTHING is sent (it just logs), so wiring this in is safe.

Channels use requests / smtplib (already available — no new deps). Every send is
wrapped so a flaky channel can never crash the monitoring loop.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

import requests

from engine.rules import Decision

log = logging.getLogger(__name__)
TIMEOUT = 8


class AlertDispatcher:
    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def channels(self) -> list[str]:
        out = []
        if self.cfg.alert_teams_webhook:
            out.append("teams")
        if self.cfg.alert_line_token:
            out.append("line")
        if self.cfg.alert_email_smtp:
            out.append("email")
        return out

    def dispatch(self, decision: Decision, signal: dict[str, Any]) -> list[str]:
        """on_alert callback: format + send to every configured channel. Returns the
        channels actually delivered to (empty = none configured → logged only)."""
        title, body = self._format(decision, signal)
        sent: list[str] = []
        if self.cfg.alert_teams_webhook and self._safe(self._teams, title, body):
            sent.append("teams")
        if self.cfg.alert_line_token and self._safe(self._line, title, body):
            sent.append("line")
        if self.cfg.alert_email_smtp and self._safe(self._email, title, body):
            sent.append("email")
        if not sent:
            log.info("ALERT (no channel configured, logged only): %s — %s", title, body)
        else:
            log.info("ALERT delivered via %s: %s", ", ".join(sent), title)
        return sent

    # ---- formatting -------------------------------------------------------
    @staticmethod
    def _format(decision: Decision, signal: dict[str, Any]) -> tuple[str, str]:
        host = signal.get("host", "?")
        extra = " ".join(f"{k}={v}" for k, v in signal.items()
                         if k not in ("kind", "host", "when"))
        title = f"[{decision.severity.upper()}] {signal.get('kind')} @ {host}"
        body = decision.reason + (f"  ({extra})" if extra else "")
        return title, body

    @staticmethod
    def _safe(fn, *a) -> bool:
        try:
            fn(*a)
            return True
        except Exception:  # never let a channel break the loop
            log.exception("alert channel failed")
            return False

    # ---- channels (only called when configured) --------------------------
    def _teams(self, title: str, body: str) -> None:
        requests.post(self.cfg.alert_teams_webhook,
                      json={"title": title, "text": body}, timeout=TIMEOUT).raise_for_status()

    def _line(self, title: str, body: str) -> None:
        requests.post("https://notify-api.line.me/api/notify",
                      headers={"Authorization": f"Bearer {self.cfg.alert_line_token}"},
                      data={"message": f"{title}\n{body}"}, timeout=TIMEOUT).raise_for_status()

    def _email(self, title: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = f"itagent@{self.cfg.ad_domain or 'localhost'}"
        msg["To"] = f"it@{self.cfg.ad_domain or 'localhost'}"
        msg.set_content(body)
        with smtplib.SMTP(self.cfg.alert_email_smtp, timeout=TIMEOUT) as s:
            s.send_message(msg)
