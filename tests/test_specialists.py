"""Tests for Phase C supervisor routing + specialist tool subsets (ai/specialists.py).

Routing is deterministic (no model), so this runs fully offline.
"""
from __future__ import annotations

import pytest

from ai.specialists import SPECIALISTS, Supervisor
from storage.db import Database


class _Cfg:
    ollama_host = "http://127.0.0.1:11434"
    ollama_model = "qwen2.5:3b"


@pytest.fixture()
def sup(tmp_path) -> Supervisor:
    return Supervisor(_Cfg(), Database(tmp_path / "t.db"))


@pytest.mark.parametrize("question, expected", [
    ("PC ไหนปิดอยู่บ้าง", "network"),
    ("which servers are offline", "network"),
    ("login fail วันนี้มีกี่ครั้ง", "security"),
    ("john lock อยู่ไหม", "security"),
    ("สถานะระบบตอนนี้เป็นยังไง", "service"),
    ("มี alert อะไรบ้าง", "service"),
    ("สวัสดี ช่วยอะไรได้บ้าง", "general"),
])
def test_routing(sup: Supervisor, question: str, expected: str) -> None:
    assert sup.route(question) == expected


def test_specialists_own_tool_subsets() -> None:
    by_name = {s.name: {t["function"]["name"] for t in s.tools} for s in SPECIALISTS}
    assert by_name["security"] == {"get_login_fails", "get_locked_accounts"}
    assert by_name["network"] == {"get_down_nodes"}
    assert by_name["service"] == {"get_recent_alerts", "get_system_summary"}


def test_supervisor_builds_a_brain_per_specialist(sup: Supervisor) -> None:
    # each specialist + the generalist fallback exists
    names = set(sup._brains)  # noqa: SLF001 (test)
    assert {"security", "network", "service", "general"} <= names
    assert sup.tool_count() == 5
