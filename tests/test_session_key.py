"""Tests for (user, folder)-bound session ids (cheng.session_key / session_user).

Same user + same folder → same id, so the CLI and TUI launched from one folder share
one conversation. Different user or folder → different id.
"""
from __future__ import annotations

from cheng import session_key, session_user


def test_same_user_and_folder_same_key():
    assert session_key("alice", "/work/proj") == session_key("alice", "/work/proj")


def test_path_is_normalized():
    # trailing slash / relative noise resolve to the same absolute folder
    a = session_key("bob", "/work/proj")
    b = session_key("bob", "/work/proj/")
    assert a == b


def test_different_folder_differs():
    assert session_key("alice", "/work/a") != session_key("alice", "/work/b")


def test_different_user_differs():
    assert session_key("alice", "/work/proj") != session_key("bob", "/work/proj")


def test_key_is_readable_and_safe():
    k = session_key("CORP\\Joe", "/work/My Project!")
    assert " " not in k and "\\" not in k          # slugified, filesystem-noise stripped
    assert k.startswith("my-project")              # basename slug leads
    assert k.endswith("corp-joe")                  # user slug trails


def test_session_user_falls_back_to_os(monkeypatch):
    assert session_user(None)                       # never empty (OS user or 'local')

    class _U:
        username = "neo"
    assert session_user(_U()) == "neo"              # signed-in user wins
