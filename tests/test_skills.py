"""Tests for the skills subsystem (discover, progressive loading, toggle)."""
from __future__ import annotations

from ai.brain import Brain
from ai.skills import (DEFAULT_SKILLS_DIR, Skill, discover_skills, select_skill_content,
                       split_sections)
from jotaro import dispatch_command
from storage.db import Database


def test_discover_project_skills():
    sk = discover_skills(DEFAULT_SKILLS_DIR)
    assert "account-lockout-response" in sk
    assert sk["account-lockout-response"].description != "(no description)"


def test_discover_flat_and_skillmd(tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "SKILL.md").write_text(
        "---\nname: x-skill\ndescription: do x\n---\nstep 1\n", encoding="utf-8")
    (tmp_path / "flat.md").write_text(
        "---\nname: flat\ndescription: flat one\n---\nbody here\n", encoding="utf-8")
    sk = discover_skills(tmp_path)
    assert {"x-skill", "flat"} <= set(sk)
    assert sk["x-skill"].body.strip() == "step 1"


def test_discover_multiple_dirs(tmp_path):
    (tmp_path / "a.md").write_text("---\nname: a\ndescription: d\n---\nx", encoding="utf-8")
    sk = discover_skills([tmp_path, DEFAULT_SKILLS_DIR])     # merges
    assert "a" in sk and "offline-node-triage" in sk


def test_brain_injects_catalog_and_loads(tmp_path):
    b = Brain("http://x", "m", Database(tmp_path / "m.db"), skills_dir=DEFAULT_SKILLS_DIR)
    assert b._skills
    assert "account-lockout-response" in b.new_history()[0]["content"]      # trigger injected
    out = b._execute("load_skill", {"name": "account-lockout-response"})
    assert "lock" in out["instruction"].lower()
    assert any(t["function"]["name"] == "load_skill" for t in b.tools)


def test_skills_toggle(tmp_path):
    b = Brain("http://x", "m", Database(tmp_path / "m.db"), skills_dir=DEFAULT_SKILLS_DIR)
    b.set_skills_enabled(False)
    assert "account-lockout-response" not in b.new_history()[0]["content"]
    assert "off" in b._execute("load_skill", {"name": "account-lockout-response"})["error"]
    assert b.set_skills_enabled(True) is True


def test_empty_dir_means_no_skills(tmp_path):
    b = Brain("http://x", "m", Database(tmp_path / "m.db"), skills_dir=tmp_path)
    assert b._skills == {} and b.skills_enabled is False


def test_dispatch_skills_command():
    assert dispatch_command("/skills") == "skills"
    assert dispatch_command("/skills on") == "skills"
    assert dispatch_command("/skills C:/Users/x/.claude") == "skills"


def test_split_sections():
    heads = [h for h, _ in split_sections("intro\n\n## A\naaa\n\n## B\nbbb\n")]
    assert "A" in heads and "B" in heads


def test_select_returns_whole_small_skill():
    sk = Skill("s", "d", "## A\nshort body", "x")
    assert select_skill_content(sk, "anything")["instruction"] == sk.body


def test_select_returns_only_relevant_section_for_large_skill():
    big = ("# T\nintro\n\n## Security\n" + "password lockout brute force " * 40
           + "\n\n## Network\n" + "offline switch ping outage " * 40 + "\n")
    sk = Skill("s", "d", big, "x")
    out = select_skill_content(sk, "password lockout")
    assert "Security" in out["sections_returned"]
    assert "password" in out["instruction"].lower()
    assert "Network" in out["all_sections"]              # rest still listed (TOC)
    assert len(out["instruction"]) < len(big)            # context saved
