"""Verifier sub-agent — check a draft answer before it's delivered (anti-hallucination).

Two layers, cheap first:
  1. a DETERMINISTIC degeneracy check (no model call) — catches the small-model failure
     mode where the answer collapses into the same line repeated dozens of times;
  2. a critic Brain that judges whether the draft is grounded in the tool data.

If either flags the draft, the caller can regenerate once before sending. Used opt-in
(cheng --verify) because it costs an extra pass and can't stream.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ai.brain import Brain, OllamaUnavailable
from ai.prompts import SYSTEM_VERIFIER
from storage.db import Database

log = logging.getLogger(__name__)


def is_degenerate(text: str) -> bool:
    """True if the text is repetitive/looping (a normalized line repeats too often, or
    the text has very low unique-line ratio). Pure heuristic — no model."""
    lines = [re.sub(r"\d+", "#", ln.strip().lower()) for ln in text.splitlines() if ln.strip()]
    if len(lines) < 6:
        return False
    counts: dict[str, int] = {}
    for ln in lines:
        counts[ln] = counts.get(ln, 0) + 1
    if max(counts.values()) >= 5:                 # same line 5+ times
        return True
    return len(counts) / len(lines) < 0.4         # <40% of lines are unique


class Verifier:
    def __init__(self, cfg: Any, db: Database) -> None:
        self._brain = Brain.from_config(cfg, db, system=SYSTEM_VERIFIER, tools=[],
                                        skills_enabled=False)

    def check(self, question: str, answer: str, evidence: str) -> tuple[bool, str]:
        """Return (ok, issue). ok=False means the draft should be fixed before sending."""
        if is_degenerate(answer):
            return False, "the answer is repetitive/degenerate (looping output)"
        prompt = (f"Question: {question}\n\nTool data available:\n{evidence or '(none)'}\n\n"
                  f"Draft answer:\n{answer}\n\nVerdict:")
        try:
            verdict = self._brain.ask(self._brain.new_history(), prompt).strip()
        except OllamaUnavailable:
            return True, ""                        # can't verify → don't block delivery
        if verdict.upper().startswith("OK"):
            return True, ""
        issue = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
        return False, issue or "not supported by the tool data"
