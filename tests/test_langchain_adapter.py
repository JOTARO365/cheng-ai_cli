"""Tests for the LangChain/LangGraph adapter (ai/langchain_adapter.py).

LangChain is an OPTIONAL extra, so this whole module is skipped when it isn't
installed (the default offline product doesn't ship it). When present, we check the
adapter builds the SAME tool set from the shared registry and that the tools really
run our read-only dispatch — no live model needed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")  # skip entire file if the extra isn't installed

from ai.langchain_adapter import build_tools  # noqa: E402
from storage.db import Database  # noqa: E402


def test_build_tools_match_registry(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    db.upsert_node("PC9", "down", None, 2, last_seen="2026-06-12T03:00:00+00:00")

    tools = build_tools(db)
    assert {t.name for t in tools} == {
        "get_down_nodes",
        "get_login_fails",
        "get_locked_accounts",
        "get_recent_alerts",
        "get_system_summary",
    }

    # the LangChain tool actually runs our dispatch against the DB
    down = next(t for t in tools if t.name == "get_down_nodes")
    result = down.invoke({})
    assert any(n["host"] == "PC9" for n in result)
