"""Tests for chat-session persistence (gap #6: --continue / --resume) in storage/db.py.

Sessions store a whole conversation history as one JSON blob keyed by id, so a quit
+ relaunch can pick the conversation back up. All offline — pure SQLite.
"""
from __future__ import annotations

import pytest

from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


def _hist(*users: str) -> list[dict]:
    h = [{"role": "system", "content": "sys"}]
    for u in users:
        h.append({"role": "user", "content": u})
        h.append({"role": "assistant", "content": f"re: {u}"})
    return h


def test_save_then_load_roundtrips(db):
    h = _hist("hello", "ปัญหา PC12")           # incl. non-ASCII → ensure_ascii=False path
    db.save_session("s1", h, label="hello")
    assert db.load_session("s1") == h


def test_load_missing_returns_none(db):
    assert db.load_session("nope") is None


def test_resave_updates_history_keeps_label(db):
    db.save_session("s1", _hist("first"), label="first")
    db.save_session("s1", _hist("first", "second"), label="second")   # label arg ignored
    loaded = db.load_session("s1")
    assert len(loaded) == 5                                            # sys + 2 turns
    sess = next(s for s in db.list_sessions() if s["id"] == "s1")
    assert sess["label"] == "first"                                   # set once, sticky


def test_latest_session_id_tracks_most_recent_update(db):
    db.save_session("old", _hist("a"), label="a")
    db.save_session("new", _hist("b"), label="b")
    assert db.latest_session_id() == "new"
    db.save_session("old", _hist("a", "a2"))      # touching old makes it latest again
    assert db.latest_session_id() == "old"


def test_latest_none_when_empty(db):
    assert db.latest_session_id() is None


def test_list_sessions_orders_and_limits(db):
    for i in range(5):
        db.save_session(f"s{i}", _hist(f"q{i}"), label=f"q{i}")
    listed = db.list_sessions(limit=3)
    assert len(listed) == 3
    assert listed[0]["id"] == "s4"                # most-recent first
    assert {"id", "created_at", "updated_at", "label"} <= set(listed[0])


def test_delete_session(db):
    db.save_session("s1", _hist("x"), label="x")
    db.delete_session("s1")
    assert db.load_session("s1") is None
    assert db.latest_session_id() is None
