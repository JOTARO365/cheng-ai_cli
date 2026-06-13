"""Tests for configurable pre/post-tool hooks (gap #8) — ai/hooks.py + Brain wiring.

A pre-hook can allow / deny (block + feed reason back) / modify args; a post-hook can
rewrite the result. The built-in dangerous_shell_guard hard-blocks destructive commands.
All offline: the Brain's tool dispatch is stubbed, no Ollama needed.
"""
from __future__ import annotations

import pytest

from ai.brain import Brain
from ai.hooks import (ALLOW, HookRegistry, dangerous_shell_guard,
                      default_safe_hooks, deny, modify)
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


# ---- registry semantics ----------------------------------------------------
def test_pre_deny_first_wins():
    reg = HookRegistry()
    reg.pre("*", lambda n, a: deny("nope"))
    reg.pre("*", lambda n, a: modify({"x": 1}))      # never reached
    dec = reg.run_pre("anytool", {"x": 0})
    assert dec.action == "deny" and dec.reason == "nope"


def test_pre_modify_chains_and_reports():
    reg = HookRegistry()
    reg.pre("get_*", lambda n, a: modify({**a, "limit": min(a.get("limit", 0), 50)}))
    dec = reg.run_pre("get_login_fails", {"limit": 9999})
    assert dec.action == "modify" and dec.args["limit"] == 50


def test_pre_no_change_is_allow():
    reg = HookRegistry().pre("*", lambda n, a: ALLOW)
    assert reg.run_pre("t", {"a": 1}).action == "allow"


def test_matcher_glob_scopes_hooks():
    reg = HookRegistry().pre("excel_*", lambda n, a: deny("no excel"))
    assert reg.run_pre("excel_write_cell", {}).action == "deny"
    assert reg.run_pre("read_file", {}).action == "allow"      # unmatched → untouched


def test_post_hook_rewrites_result():
    reg = HookRegistry().post("read_file", lambda n, a, r: {"scrubbed": True})
    assert reg.run_post("read_file", {}, {"raw": "secret"}) == {"scrubbed": True}
    # a post-hook returning None keeps the original
    reg2 = HookRegistry().post("*", lambda n, a, r: None)
    assert reg2.run_post("x", {}, "keep") == "keep"


# ---- built-in dangerous_shell_guard ----------------------------------------
@pytest.mark.parametrize("cmd", [
    "rm -rf /", "rm -fr ~/data", "sudo rm  -r -f foo", "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda", "del /s /q C:\\Windows",
    "Remove-Item -Recurse -Force C:\\", "shutdown /s /t 0", ":(){ :|:& };:",
])
def test_guard_blocks_dangerous(cmd):
    assert dangerous_shell_guard("run_command", {"command": cmd}).action == "deny"


@pytest.mark.parametrize("cmd", [
    "ls -la", "rm notes.txt", "cat /etc/hosts", "git status",
    "python -m pytest", "echo hello",
])
def test_guard_allows_safe(cmd):
    assert dangerous_shell_guard("run_command", {"command": cmd}).action == "allow"


# ---- Brain integration -----------------------------------------------------
def test_brain_blocked_tool_is_not_dispatched(db):
    calls = []
    b = Brain("http://x", "m", db, dispatcher=lambda n, a: calls.append((n, a)) or "ran",
              hooks=default_safe_hooks())
    out = b._execute("run_command", {"command": "rm -rf /"})
    assert out["status"] == "blocked by hook" and "rm -rf" in out["reason"]
    assert calls == []                                # never reached the dispatcher


def test_brain_modify_reaches_dispatcher_with_new_args(db):
    seen = {}
    reg = HookRegistry().pre("get_x", lambda n, a: modify({"limit": 5}))
    b = Brain("http://x", "m", db,
              dispatcher=lambda n, a: seen.update(a) or {"ok": True}, hooks=reg)
    b._execute("get_x", {"limit": 10_000})
    assert seen == {"limit": 5}


def test_brain_post_hook_rewrites_result(db):
    reg = HookRegistry().post("*", lambda n, a, r: {**r, "tagged": True})
    b = Brain("http://x", "m", db, dispatcher=lambda n, a: {"v": 1}, hooks=reg)
    assert b._execute("get_x", {}) == {"v": 1, "tagged": True}


def test_no_hooks_is_passthrough(db):
    b = Brain("http://x", "m", db, dispatcher=lambda n, a: "raw")
    assert b.hooks is None
    assert b._execute("get_x", {}) == "raw"
