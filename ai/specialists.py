"""Phase C — supervisor → specialist agents, split by use case.

A supervisor analyses each question and dispatches it to the specialist that owns that
domain (security / network / service). Each specialist is just a `Brain` with its own
persona + a SUBSET of the tools — which also helps a small model pick the right tool
(fewer choices = fewer mistakes).

Routing is DETERMINISTIC (keyword match) on purpose: it costs zero LLM calls, which
matters on an offline CPU box. Swapping in an LLM router later is a one-method change
(`Supervisor.route`). Unmatched questions fall back to a generalist (all tools).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai.brain import Brain, OllamaUnavailable, StructuredError
from ai.prompts import NETWORK_ANALYST, SECURITY_ANALYST, SERVICE_ANALYST, SYSTEM_CHAT
from ai.tools import TOOL_SPECS
from storage.db import Database


def _specs(*names: str) -> list[dict[str, Any]]:
    """Pick a subset of TOOL_SPECS by tool name (keeps one source of truth)."""
    return [s for s in TOOL_SPECS if s["function"]["name"] in names]


@dataclass(frozen=True)
class Specialist:
    name: str
    system: str
    tools: list[dict[str, Any]]
    keywords: tuple[str, ...]


# Registry — keywords are matched against the (lowercased) question. Thai + English.
SPECIALISTS: list[Specialist] = [
    Specialist(
        "security", SECURITY_ANALYST,
        _specs("get_login_fails", "get_locked_accounts"),
        ("login", "fail", "lock", "locked", "password", "brute", "logon", "signin",
         "ล็อก", "ล็อค", "รหัส", "เข้าระบบ", "ล็อกอิน", "ล็อกเอ้า"),
    ),
    Specialist(
        "network", NETWORK_ANALYST,
        _specs("get_down_nodes"),
        ("offline", "down", "ping", "unreachable", "node", "host", "pc", "server",
         "ปิด", "ออฟไลน์", "เครื่อง", "ดับ", "ไม่ตอบ", "หลุด"),
    ),
    Specialist(
        "service", SERVICE_ANALYST,
        _specs("get_recent_alerts", "get_system_summary"),
        ("service", "alert", "status", "summary", "impact", "spooler", "health",
         "สถานะ", "แจ้งเตือน", "บริการ", "ภาพรวม", "ระบบ", "alert"),
    ),
]


class Supervisor:
    """Holds one Brain per specialist (+ a generalist) and routes questions."""

    def __init__(self, cfg: Any, db: Database, *, llm_route: bool = False,
                 **brain_kw: Any) -> None:
        self._brains: dict[str, Brain] = {
            s.name: Brain.from_config(cfg, db, system=s.system, tools=s.tools, **brain_kw)
            for s in SPECIALISTS
        }
        # generalist fallback: full persona + all tools
        self._brains["general"] = Brain.from_config(cfg, db, system=SYSTEM_CHAT, **brain_kw)
        self._db = db
        self._llm_route = llm_route          # opt-in: structured-output router vs keyword

    def set_skills_enabled(self, on: bool) -> bool:
        for b in self._brains.values():
            b.set_skills_enabled(on)
        return self._brains["general"].skills_enabled

    def load_skills_from(self, skills_dir: Any) -> int:
        n = 0
        for b in self._brains.values():
            n = b.load_skills_from(skills_dir)
        return n

    def skill_names(self) -> list[str]:
        return self._brains["general"].skill_names()

    def set_skill(self, name: str, on: bool) -> bool:
        ok = False
        for b in self._brains.values():
            ok = b.set_skill(name, on)
        return ok

    def skill_status(self) -> list[tuple[str, bool]]:
        return self._brains["general"].skill_status()

    @property
    def skills_enabled(self) -> bool:
        return self._brains["general"].skills_enabled

    def is_available(self) -> bool:
        return self._brains["general"].is_available()

    @property
    def model(self) -> str:
        return self._brains["general"].model

    def set_model(self, name: str) -> None:
        for b in self._brains.values():
            b.model = name

    def list_models(self) -> list[str]:
        return self._brains["general"].list_models()

    def tool_count(self) -> int:
        """Distinct tools across all specialists."""
        return len({s["function"]["name"] for sp in SPECIALISTS for s in sp.tools})

    def brains(self) -> list[Brain]:
        """Every specialist brain (so the CLI can aggregate token usage across them)."""
        return list(self._brains.values())

    def route(self, question: str) -> str:
        """Pick a specialist. Default = deterministic keyword match (zero LLM calls,
        offline-friendly). With llm_route=True, use a structured-output classifier and
        fall back to keyword if the model/JSON fails — so routing never breaks."""
        if self._llm_route:
            name = self._route_llm(question)
            if name:
                return name
        return self._route_keyword(question)

    def _route_keyword(self, question: str) -> str:
        q = question.lower()
        best, score = "general", 0
        for s in SPECIALISTS:
            hits = sum(1 for kw in s.keywords if kw in q)
            if hits > score:
                best, score = s.name, hits
        return best

    def _route_llm(self, question: str) -> str | None:
        """Structured-output router: the model returns {"specialist": <enum>}. Returns a
        valid specialist name, or None to signal 'fall back to keyword'."""
        names = [s.name for s in SPECIALISTS] + ["general"]
        schema = {"type": "object",
                  "properties": {"specialist": {"type": "string", "enum": names}},
                  "required": ["specialist"]}
        sysp = ("You route an IT question to the right specialist. "
                "security = logins/lockouts/brute-force; network = offline PCs/connectivity; "
                "service = Windows services/alerts/system status; general = anything else. "
                "Reply with the specialist only.")
        try:
            name = self._brains["general"].structured(question, schema, system=sysp).get("specialist")
            return name if name in self._brains else None
        except (StructuredError, OllamaUnavailable):
            return None

    def ask(self, question: str, on_tool=None, on_result=None, on_token=None) -> tuple[str, str]:
        """Route, delegate to that specialist's Brain, return (specialist_name, answer).
        Each turn is stateless across specialists (a fresh history) — fine for routed
        Q&A; cross-specialist memory is a later concern."""
        name = self.route(question)
        brain = self._brains[name]
        answer = brain.ask(brain.new_history(), question,
                           on_tool=on_tool, on_result=on_result, on_token=on_token)
        return name, answer
