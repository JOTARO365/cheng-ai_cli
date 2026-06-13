"""Tests for the memory subsystem (db.memory, Brain remember/recall + injection)."""
from __future__ import annotations

from ai.brain import Brain
from cheng import dispatch_command
from storage.db import Database


def test_db_memory_crud(tmp_path):
    db = Database(tmp_path / "m.db")
    i = db.add_memory("SRV1 is the print server")
    db.add_memory("PC20 is in the warehouse")
    assert len(db.recent_memory()) == 2
    hits = db.search_memory("print server")
    assert hits and "SRV1" in hits[0]["text"]
    assert db.search_memory("zzzznonexistent") == []
    db.forget_memory(i)
    assert len(db.recent_memory()) == 1


def test_brain_remember_and_recall(tmp_path):
    b = Brain("http://x", "m", Database(tmp_path / "m.db"))
    assert b._execute("remember", {"text": "PC20 = warehouse"})["status"] == "remembered"
    rec = b._execute("recall", {"query": "warehouse"})
    assert any("PC20" in m["text"] for m in rec["matches"])


def test_new_history_injects_memory(tmp_path):
    db = Database(tmp_path / "m.db")
    db.add_memory("SRV1 is the print server")
    sys_msg = Brain("http://x", "m", db).new_history()[0]["content"]
    assert "remember" in sys_msg.lower() and "SRV1" in sys_msg


def test_memory_tools_merged_into_every_brain(tmp_path):
    names = {t["function"]["name"] for t in Brain("http://x", "m", Database(tmp_path / "m.db")).tools}
    assert {"remember", "recall"} <= names


def test_dispatch_memory_commands():
    assert dispatch_command("/remember SRV1 is the print server") == "remember"
    assert dispatch_command("/remember") == "remember"
    assert dispatch_command("/memory") == "memory"
