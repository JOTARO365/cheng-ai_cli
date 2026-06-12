"""AI escalation — the real `on_ai` callback for the Rule Engine (replaces fake_ai).

When the engine decides an event is interesting, it calls this. We route by signal
kind to a focused analyst persona, ask the local model for a SHORT root-cause read
(read-only — analysis only, Phase 1), and store the result so the chat CLI can surface
it. If Ollama is unreachable we skip gracefully — the rule-only alert already stands.
"""
from __future__ import annotations

import logging
from typing import Any

from ai.brain import Brain, OllamaUnavailable
from ai.prompts import SYSTEM_ANALYST
from engine.rules import Decision
from storage.db import Database

log = logging.getLogger(__name__)

# A per-kind focus line appended to the analyst persona (no tool mentions — the
# analyst reasons from the event the engine already gathered).
_FOCUS = {
    "login_fail": "Focus on whether this looks like brute-force vs a user fat-fingering.",
    "account_lockout": "Focus on whether the lockout is benign or the tail of an attack.",
    "node_offline": "Focus on scope (one host vs many → switch/power) and work-hours impact.",
    "service_down": "Focus on dependent services and the user-facing impact.",
}


class Analyst:
    def __init__(self, cfg: Any, db: Database) -> None:
        self.cfg = cfg
        self.db = db
        self._brains: dict[str, Brain] = {}

    def _brain(self, system: str) -> Brain:
        if system not in self._brains:
            # no IT tools — pure analysis of the event the engine passes in
            self._brains[system] = Brain.from_config(self.cfg, self.db, system=system, tools=[])
        return self._brains[system]

    def on_ai(self, decision: Decision, signal: dict[str, Any]) -> str | None:
        kind = signal.get("kind", "")
        system = (SYSTEM_ANALYST + " " + _FOCUS[kind]) if kind in _FOCUS else SYSTEM_ANALYST
        brain = self._brain(system)
        if not brain.is_available():
            log.info("escalation: Ollama unavailable — skipping AI analysis for %s", kind)
            return None

        fields = ", ".join(f"{k}={v}" for k, v in signal.items() if k != "kind")
        prompt = (f"Monitoring event: {kind} ({fields}). Rule decision: {decision.reason}. "
                  f"Give a SHORT root-cause read and the single best next step for IT.")
        try:
            analysis = brain.ask(brain.new_history(), prompt)
        except OllamaUnavailable:
            log.info("escalation: Ollama dropped mid-analysis for %s", kind)
            return None

        self.db.record_event(
            source="ai", kind="analysis", severity=decision.severity,
            message=analysis, host=signal.get("host"), data={"of_kind": kind},
        )
        log.info("escalation: stored AI analysis for %s @ %s", kind, signal.get("host"))
        return analysis
