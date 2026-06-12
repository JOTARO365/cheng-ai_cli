"""Smoke test for the PydanticAI adapter (ai/pydantic_agent.py).

PydanticAI is an OPTIONAL extra → skip if absent. We only check the agent builds
offline (no model call) and that FsDeps drives our sandboxed fs dispatch — the live
approval loop needs a running model and is exercised by hand / the demo.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai")

from ai.pydantic_agent import FsDeps, build_agent  # noqa: E402
from ai.fs_tools import make_fs_dispatcher  # noqa: E402


class _Cfg:
    ollama_host = "http://127.0.0.1:11434"
    ollama_model = "qwen2.5:3b"


def test_build_agent_offline() -> None:
    agent = build_agent(_Cfg())          # builds model+tools, no network call
    assert agent is not None


def test_fsdeps_dispatch_is_sandboxed(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    deps = FsDeps(make_fs_dispatcher(tmp_path))
    assert deps.dispatch("read_file", {"path": "a.txt"})["content"] == "hi"
    assert "escapes workspace" in deps.dispatch("read_file", {"path": "../x"}).get("error", "")
