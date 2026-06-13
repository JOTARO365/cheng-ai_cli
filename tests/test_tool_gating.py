"""Tests for per-turn tool gating (Anthropic: 'more tools waste cognitive capacity').

_gate_tools offers a turn only the relevant tools: always the domain tools, memory tools
only on a save/recall intent, skill tools only when skills are on AND a skill matches.
Offline: no Ollama needed.
"""
from __future__ import annotations

import pytest

from ai.brain import Brain
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


def _names(specs):
    return {s["function"]["name"] for s in specs}


def _brain(db, **kw):
    # domain = two fake tools; skills off unless a tmp skills dir is given
    domain = [{"type": "function", "function": {"name": "get_down_nodes", "description": "d"}},
              {"type": "function", "function": {"name": "get_login_fails", "description": "d"}}]
    return Brain("http://x", "m", db, tools=domain, skills_enabled=False, **kw)


def test_plain_question_gets_domain_tools_only(db):
    b = _brain(db)
    sel = _names(b._gate_tools("which PCs are offline?"))
    assert sel == {"get_down_nodes", "get_login_fails"}      # no memory, no skill noise
    assert "remember" not in sel and "recall" not in sel


def test_memory_intent_adds_memory_tools(db):
    b = _brain(db)
    assert "remember" in _names(b._gate_tools("remember that SRV1 is the print server"))
    assert "remember" in _names(b._gate_tools("จำไว้ว่า PC12 เป็นของ mary"))


def test_full_superset_still_exposed_for_introspection(db):
    """self.tools stays the full set (domain + memory) so tool_count/UX is unchanged."""
    b = _brain(db)
    assert {"remember", "recall"} <= _names(b.tools)         # superset has them
    assert "remember" not in _names(b._gate_tools("any host down?"))   # turn doesn't


def test_skill_tools_only_when_enabled_and_matching(tmp_path, db):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "disk-cleanup.md").write_text(
        "---\nname: disk-cleanup\ndescription: how to free disk space on a Windows server\n---\nsteps",
        encoding="utf-8")
    domain = [{"type": "function", "function": {"name": "get_down_nodes", "description": "d"}}]
    b = Brain("http://x", "m", db, tools=domain, skills_dir=str(skills), skills_enabled=True)
    # a matching question surfaces the skill tools…
    assert "load_skill" in _names(b._gate_tools("how do I free disk space on the server?"))
    # …an unrelated question does not
    assert "load_skill" not in _names(b._gate_tools("which PCs are offline right now?"))


def test_skills_disabled_never_adds_skill_tools(tmp_path, db):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "x.md").write_text("---\nname: x\ndescription: free disk space\n---\ns", encoding="utf-8")
    domain = [{"type": "function", "function": {"name": "get_down_nodes", "description": "d"}}]
    b = Brain("http://x", "m", db, tools=domain, skills_dir=str(skills), skills_enabled=False)
    assert "load_skill" not in _names(b._gate_tools("how to free disk space?"))
