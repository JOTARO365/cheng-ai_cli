"""Tool registry for the local-model agent (CHENG AI CLI).

ONE place that defines the IT-context tools the model may call, in the
Ollama/OpenAI function-calling schema, plus a dispatcher that runs each against
storage/db.py. The CLI agent (ai/brain.py) passes TOOL_SPECS to Ollama and calls
dispatch() when the model asks for a tool.

All tools are READ-ONLY (Phase 1: monitor + report only). `hours` params are
clamped so the model can't ask for an absurd window.
"""
from __future__ import annotations

from typing import Any, Callable

from storage.db import Database

# --- function specs sent to Ollama (the model reads the descriptions to choose) ---
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_down_nodes",
            "description": (
                "List PCs/servers currently OFFLINE (not responding to ping) and how "
                "long each has been down. Use for 'PC ไหนปิดอยู่บ้าง' / which machines "
                "are down / any host offline."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_login_fails",
            "description": (
                "Login-failure activity per user in the last N hours (peak fail count + "
                "source host/IP). Use for 'login fail วันนี้กี่ครั้ง' / who failed to log "
                "in / possible brute-force."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "look-back window in hours (default 24)",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_locked_accounts",
            "description": (
                "Accounts that hit a lockout (Windows Event 4740) in the last N hours. "
                "Reflects lockout EVENTS, not current AD state. Use for 'john lock อยู่ไหม' "
                "/ who got locked out."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "look-back window in hours (default 24)",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_alerts",
            "description": (
                "Most recent alerts the system raised (severity + delivered flag). Use "
                "for 'มี alert อะไรบ้าง' / what happened recently."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "how many alerts to return (default 10)",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_summary",
            "description": (
                "One-glance overall health: node counts by status + today's "
                "failure/lockout/alert tallies. Use for 'สถานะระบบตอนนี้เป็นยังไง' / "
                "system status."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _clamp_hours(args: dict[str, Any], default: int = 24) -> int:
    try:
        h = int(args.get("hours", default))
    except (TypeError, ValueError):
        h = default
    return max(1, min(h, 168))


def _clamp_limit(args: dict[str, Any], default: int = 10) -> int:
    try:
        n = int(args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, 100))


def dispatch(name: str, args: dict[str, Any], db: Database) -> Any:
    """Run a tool by name against the DB. Returns JSON-ready data, or an {'error'}
    dict for an unknown tool (so the model gets a usable signal, not an exception)."""
    args = args or {}
    handlers: dict[str, Callable[[], Any]] = {
        "get_down_nodes": db.down_nodes,
        "get_login_fails": lambda: db.login_fails(_clamp_hours(args)),
        "get_locked_accounts": lambda: db.locked_accounts(_clamp_hours(args)),
        "get_recent_alerts": lambda: db.recent_alerts(_clamp_limit(args)),
        "get_system_summary": db.system_summary,
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"unknown tool {name!r}"}
    return handler()
