"""MCP client — connect to Model Context Protocol servers and use their tools.

This is how JOTARO gets an UNLIMITED toolset: point it at any MCP server (filesystem,
git, web, databases, your own) and its tools become callable like ours. The MCP SDK is
async; Brain is sync — so we run an asyncio loop in a background thread that owns the
sessions, and proxy each tool call through it (run_coroutine_threadsafe).

Config (Claude-style JSON):
    {"mcpServers": {"echo": {"command": "python", "args": ["server.py"]}}}

Usage:
    mcp = MCPClient(load_mcp_config("mcp.json"))
    specs = mcp.tool_specs()            # feed to Brain(tools=...)
    result = mcp.dispatch("echo", {"text": "hi"})
    mcp.close()
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    _HAVE_MCP = True
except ImportError:  # pragma: no cover
    _HAVE_MCP = False


def load_mcp_config(path: str | Path) -> dict[str, dict]:
    """Read a Claude-style config and return {server_name: {command, args, env}}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("mcpServers", data)


def _content_to_data(result: Any) -> Any:
    parts = []
    for c in getattr(result, "content", None) or []:
        text = getattr(c, "text", None)
        parts.append(text if text is not None else str(c))
    joined = "\n".join(parts)
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, TypeError):
        return {"result": joined, "isError": bool(getattr(result, "isError", False))}


class MCPClient:
    """Owns one bg thread + asyncio loop holding all the MCP sessions open."""

    def __init__(self, servers: dict[str, dict], ready_timeout: float = 30.0) -> None:
        if not _HAVE_MCP:
            raise ImportError("the 'mcp' package is required (pip install mcp)")
        self._servers = servers
        self._sessions: dict[str, Any] = {}
        self._owner: dict[str, str] = {}     # tool name -> server name
        self._specs: list[dict] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True)
        self._thread.start()
        self._ready.wait(ready_timeout)

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
            async with AsyncExitStack() as stack:
                for name, cfg in self._servers.items():
                    try:
                        params = StdioServerParameters(
                            command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env"))
                        read, write = await stack.enter_async_context(stdio_client(params))
                        session = await stack.enter_async_context(ClientSession(read, write))
                        await session.initialize()
                        self._sessions[name] = session
                        for t in (await session.list_tools()).tools:
                            self._owner[t.name] = name
                            self._specs.append({"type": "function", "function": {
                                "name": t.name, "description": t.description or "",
                                "parameters": t.inputSchema or {"type": "object", "properties": {}}}})
                        log.info("mcp: connected %s", name)
                    except Exception as exc:  # one bad server shouldn't sink the rest
                        log.warning("mcp: server %r failed: %s", name, exc)
                self._ready.set()
                await self._stop.wait()
        except Exception as exc:  # pragma: no cover
            log.warning("mcp: loop error: %s", exc)
            self._ready.set()

    def tool_specs(self) -> list[dict]:
        return list(self._specs)

    def names(self) -> list[str]:
        return list(self._owner)

    def dispatch(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self._owner:
            return {"error": f"unknown mcp tool {name!r}"}
        if self._loop is None:
            return {"error": "mcp not ready"}

        async def call() -> Any:
            res = await self._sessions[self._owner[name]].call_tool(name, args or {})
            return _content_to_data(res)

        try:
            return asyncio.run_coroutine_threadsafe(call(), self._loop).result(timeout=60)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    def close(self) -> None:
        if self._loop and self._stop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
