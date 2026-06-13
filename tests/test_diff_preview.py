"""Tests for the edit/write diff preview (gap #5) — ai/fs_tools.diff_for.

diff_for computes the unified diff a write/edit WOULD produce, for a confirm-time
preview. Pure: it reads the file but never writes. Path-jail still applies.
"""
from __future__ import annotations

import pytest

from ai.fs_tools import diff_for


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    return tmp_path


def test_edit_shows_minus_and_plus(ws):
    d = diff_for(ws, "edit_file", {"path": "a.txt", "old_string": "line2",
                                   "new_string": "LINE-TWO"})
    assert "-line2" in d and "+LINE-TWO" in d
    assert "line1" in d                         # context line present
    assert "line3" in d


def test_edit_old_string_missing_is_flagged(ws):
    d = diff_for(ws, "edit_file", {"path": "a.txt", "old_string": "nope",
                                   "new_string": "x"})
    assert "not found" in d and "fail" in d     # warns instead of a misleading diff


def test_edit_missing_file_is_flagged(ws):
    d = diff_for(ws, "edit_file", {"path": "ghost.txt", "old_string": "a",
                                   "new_string": "b"})
    assert "not found" in d


def test_edit_no_change_when_old_equals_new(ws):
    d = diff_for(ws, "edit_file", {"path": "a.txt", "old_string": "line2",
                                   "new_string": "line2"})
    assert d == "(no change)"


def test_write_new_file_labeled(ws):
    d = diff_for(ws, "write_file", {"path": "new.txt", "content": "hello\nworld\n"})
    assert "new file" in d
    assert "+hello" in d and "+world" in d


def test_write_overwrite_shows_diff(ws):
    d = diff_for(ws, "write_file", {"path": "a.txt", "content": "line1\nCHANGED\nline3\n"})
    assert "-line2" in d and "+CHANGED" in d


def test_path_escape_returns_none(ws):
    assert diff_for(ws, "edit_file", {"path": "../evil.txt", "old_string": "a",
                                      "new_string": "b"}) is None


def test_non_preview_tool_returns_none(ws):
    assert diff_for(ws, "read_file", {"path": "a.txt"}) is None
    assert diff_for(ws, "make_dir", {"path": "sub"}) is None
