"""Test the in-repo search MCP server connects and exposes its tools (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from ai.mcp_client import MCPClient  # noqa: E402

SERVER = str(Path(__file__).parent.parent / "mcp_servers" / "search_server.py")


def test_search_server_exposes_tools():
    client = MCPClient({"search": {"command": sys.executable, "args": [SERVER]}})
    try:
        assert {"search", "fetch"} <= set(client.names())
    finally:
        client.close()
