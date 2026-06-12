"""Test the MCP client against a real (in-repo) stdio MCP server."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from ai.mcp_client import MCPClient, load_mcp_config  # noqa: E402

SERVER = str(Path(__file__).parent / "mcp_echo_server.py")


def test_connect_list_and_call():
    client = MCPClient({"echo": {"command": sys.executable, "args": [SERVER]}})
    try:
        assert "echo" in client.names()
        assert any(s["function"]["name"] == "echo" for s in client.tool_specs())
        out = client.dispatch("echo", {"text": "hi there"})
        assert "echo: hi there" in str(out)
        assert "error" in client.dispatch("nonexistent", {})
    finally:
        client.close()


def test_load_mcp_config(tmp_path):
    p = tmp_path / "mcp.json"
    p.write_text('{"mcpServers": {"x": {"command": "c", "args": ["a"]}}}', encoding="utf-8")
    assert load_mcp_config(p) == {"x": {"command": "c", "args": ["a"]}}
