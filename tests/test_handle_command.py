"""Tests for the shared slash-command handler (cheng.handle_command).

This is the single place command behaviour lives now — both the CLI and the TUI call it,
so testing it once covers both front-ends. No model calls (commands don't hit Ollama).
"""
from __future__ import annotations

import pytest

from ai.brain import Brain
from cheng import handle_command
from config import load_config
from storage.db import Database


@pytest.fixture()
def ctx(tmp_path):
    cfg = load_config()
    db = Database(tmp_path / "t.db")
    brain = Brain.from_config(cfg, db)
    return cfg, db, brain


def _run(action, text, ctx, current_user=None):
    cfg, db, brain = ctx
    return handle_command(action, text, cfg=cfg, db=db, brain=brain, team=None,
                          current_user=current_user)


def test_exit(ctx):
    assert _run("exit", "/exit", ctx).do == "exit"


def test_help_renders_a_panel(ctx):
    res = _run("help", "/help", ctx)
    assert res.do == "handled" and len(res.render) == 1


def test_status_renders(ctx):
    assert _run("status", "/status", ctx).render            # a panel built from the db


def test_whoami_without_account_shows_os_user(ctx):
    out = _run("whoami", "/whoami", ctx).render
    assert any("not signed in" in str(x) for x in out)


def test_remember_then_memory(ctx):
    _run("remember", "/remember SRV1 is the print server", ctx)
    out = " ".join(str(x) for x in _run("memory", "/memory", ctx).render)
    assert "print server" in out


def test_clear_resets_history(ctx):
    res = _run("clear", "/clear", ctx)
    assert res.do == "clear" and res.history is not None and len(res.history) == 1  # system only


def test_model_no_arg_shows_current(ctx):
    out = " ".join(str(x) for x in _run("model", "/model", ctx).render)
    assert "current" in out


def test_interactive_and_ask_pass_through(ctx):
    for action in ("login", "passwd", "users", "summarize", "ask"):
        assert _run(action, "/" + action, ctx).do == action   # UI drives these
