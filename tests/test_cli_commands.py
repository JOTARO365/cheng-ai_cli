"""Tests for JOTARO CLI slash-command dispatch (jotaro.dispatch_command).

The prompt_toolkit REPL can't be driven headless on Windows, so the command routing
is a pure function we test directly — covers every /command + aliases + the 'ask'
fall-through.
"""
from __future__ import annotations

import pytest

from jotaro import dispatch_command


@pytest.mark.parametrize("text, action", [
    ("/help", "help"), ("/h", "help"), ("?", "help"),
    ("/status", "status"),
    ("/clear", "clear"),
    ("/model", "model"), ("/model qwen2.5:14b", "model"), ("  /MODEL llama3.2", "model"),
    ("/exit", "exit"), ("/quit", "exit"), ("/q", "exit"),
    ("  /HELP  ", "help"),          # trimmed + case-insensitive
    ("/STATUS", "status"),
    ("PC ไหนปิดอยู่บ้าง", "ask"),     # a real question
    ("/unknown", "ask"),            # unknown slash → treated as a question
    ("", "ask"),
])
def test_dispatch_command(text: str, action: str) -> None:
    assert dispatch_command(text) == action
