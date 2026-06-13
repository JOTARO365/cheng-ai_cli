"""Tests for @file mentions (beyond-the-9) — cheng.expand_mentions.

A user typing `@path` inlines that file's content into the prompt. Unknown @tokens
(emails, literal @) are left alone, and files are read relative to a base dir.
"""
from __future__ import annotations

import pytest

from cheng import MENTION_MAX, expand_mentions


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "config.py").write_text("PORT = 8000\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# notes\nhello\n", encoding="utf-8")
    return tmp_path


def test_no_mention_is_unchanged(ws):
    text, loaded = expand_mentions("what files are here?", ws)
    assert text == "what files are here?" and loaded == []


def test_single_file_inlined(ws):
    text, loaded = expand_mentions("explain @config.py please", ws)
    assert loaded == ["config.py"]
    assert "--- config.py ---" in text and "PORT = 8000" in text
    assert "Question: explain config.py please" in text   # @ stripped, path kept


def test_multiple_files(ws):
    text, loaded = expand_mentions("compare @config.py and @notes.md", ws)
    assert loaded == ["config.py", "notes.md"]
    assert "PORT = 8000" in text and "# notes" in text


def test_unknown_mention_left_intact(ws):
    text, loaded = expand_mentions("email me @ joe@x.com about @ghost.py", ws)
    assert loaded == []                          # neither resolves to a file
    assert text == "email me @ joe@x.com about @ghost.py"


def test_trailing_punctuation_not_part_of_path(ws):
    text, loaded = expand_mentions("look at @config.py.", ws)
    assert loaded == ["config.py"]               # trailing '.' dropped from the path


def test_large_file_is_truncated(ws):
    (ws / "big.dat").write_text("x" * (MENTION_MAX + 5000), encoding="utf-8")
    text, loaded = expand_mentions("@big.dat", ws)
    assert loaded == ["big.dat"]
    assert text.count("x") == MENTION_MAX        # content capped (filename has no 'x')
