"""Tests for JOTARO CLI slash-command dispatch (jotaro.dispatch_command).

The prompt_toolkit REPL can't be driven headless on Windows, so the command routing
is a pure function we test directly — covers every /command + aliases + the 'ask'
fall-through.
"""
from __future__ import annotations

import pytest

from prompt_toolkit.document import Document

from jotaro import SlashCompleter, _no_knowledge, dispatch_command


@pytest.mark.parametrize("text, action", [
    ("/help", "help"), ("/h", "help"), ("?", "help"),
    ("/status", "status"),
    ("/clear", "clear"),
    ("/model", "model"), ("/model qwen2.5:14b", "model"), ("  /MODEL llama3.2", "model"),
    ("/skills", "skills"), ("/summarize", "summarize"), ("/summarize big.md", "summarize"),
    ("/exit", "exit"), ("/quit", "exit"), ("/q", "exit"),
    ("  /HELP  ", "help"),          # trimmed + case-insensitive
    ("/STATUS", "status"),
    ("PC ไหนปิดอยู่บ้าง", "ask"),     # a real question
    ("/unknown", "ask"),            # unknown slash → treated as a question
    ("", "ask"),
])
def test_dispatch_command(text: str, action: str) -> None:
    assert dispatch_command(text) == action


def test_no_knowledge_detector():
    assert _no_knowledge("ขอโทษครับ ผมไม่มีข้อมูลเรื่องนี้")
    assert _no_knowledge("I don't know the founding date")
    assert _no_knowledge("ไม่ทราบวันก่อตั้ง")
    assert not _no_knowledge("PC20 และ PC12 ปิดอยู่ตอนนี้")
    assert not _no_knowledge("")


def test_slash_completer():
    c = SlashCompleter()
    on_slash = [x.text for x in c.get_completions(Document("/"), None)]
    assert "/help" in on_slash and "/skills" in on_slash
    assert [x.text for x in c.get_completions(Document("/me"), None)] == ["/memory"]
    assert list(c.get_completions(Document("hello"), None)) == []   # non-slash → no menu
