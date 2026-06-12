"""FastAPI OpenAPI tool server — the bridge Open WebUI calls to read live IT data.

Each endpoint is ONE tool. The `summary`/`description` text is what the local LLM
reads to decide which tool to call, so keep them clear and intention-named (the
Thai hints help users phrase questions the model can map). All endpoints are GET
and READ-ONLY — this server can only look, never touch.

Run via `python main.py` (preferred) or:
    uvicorn webtools.server:app --host 127.0.0.1 --port 8000
Then in Open WebUI: Settings → Tools → add  http://127.0.0.1:8000  as an
OpenAPI tool server (it auto-discovers the tools from /openapi.json).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from storage.db import Database

log = logging.getLogger(__name__)


# ---- response models (give Open WebUI / the LLM a typed, self-describing shape) --
class DownNode(BaseModel):
    host: str
    consecutive_fails: int
    last_seen: str | None = Field(None, description="ISO8601 UTC of last 'up', or null if never")
    offline_minutes: float | None = Field(None, description="minutes offline since last_seen")


class LoginFail(BaseModel):
    user: str
    count: int = Field(description="peak consecutive failures seen in the window")
    host: str | None = None
    ip: str | None = None
    last_ts: str | None = None


class LockedAccount(BaseModel):
    user: str
    host: str | None = None
    ts: str | None = Field(None, description="when the lockout (Event 4740) was seen")


class AlertItem(BaseModel):
    id: int
    ts: str
    severity: str
    title: str
    body: str
    sent: int = Field(description="0 = not yet delivered, 1 = delivered")


class SystemSummary(BaseModel):
    generated_at: str
    nodes_total: int
    nodes_up: int
    nodes_down: int
    nodes_unknown: int
    login_fail_users_24h: int
    locked_accounts_24h: int
    alerts_pending: int


def create_app(db: Database) -> FastAPI:
    """Build the tool-server app over a given Database (injected so tests can use a
    temp DB). main.py passes the real Database(cfg.db_path)."""
    app = FastAPI(
        title="SME IT Agent — IT Context Tools",
        version="0.1.0",
        description=(
            "Read-only tools that expose the SME IT Agent's live monitoring data "
            "(offline nodes, login failures, account lockouts, alerts) to the local "
            "chat model. Phase 1: monitor + report only — no actions are taken here."
        ),
    )

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/down_nodes",
        operation_id="get_down_nodes",
        summary="List PCs/servers that are currently OFFLINE",
        description=(
            "Return hosts currently DOWN (not responding to ping) and how long each "
            "has been offline. Use for questions like 'PC ไหนปิดอยู่บ้าง' / "
            "'which machines are down' / 'มีเครื่องไหน offline ไหม'."
        ),
        response_model=list[DownNode],
    )
    def get_down_nodes() -> list[dict[str, Any]]:
        return db.down_nodes()

    @app.get(
        "/login_fails",
        operation_id="get_login_fails",
        summary="Recent login-failure activity per user",
        description=(
            "Return login failures in the last N hours, one row per user with the "
            "peak fail count and source host/IP. Use for 'login fail วันนี้มีกี่ครั้ง' / "
            "'ใคร login พลาดเยอะ' / 'any brute-force attempts'."
        ),
        response_model=list[LoginFail],
    )
    def get_login_fails(
        hours: int = Query(24, ge=1, le=168, description="look-back window in hours (default 24)")
    ) -> list[dict[str, Any]]:
        return db.login_fails(hours)

    @app.get(
        "/locked_accounts",
        operation_id="get_locked_accounts",
        summary="Accounts that were locked out recently",
        description=(
            "Return accounts that hit a lockout (Windows Event 4740) in the last N "
            "hours. NOTE: reflects lockout EVENTS, not current AD state (unlocks are "
            "not tracked in Phase 1). Use for 'john lock อยู่ไหม' / 'ใครโดนล็อกบ้าง'."
        ),
        response_model=list[LockedAccount],
    )
    def get_locked_accounts(
        hours: int = Query(24, ge=1, le=168, description="look-back window in hours (default 24)")
    ) -> list[dict[str, Any]]:
        return db.locked_accounts(hours)

    @app.get(
        "/recent_alerts",
        operation_id="get_recent_alerts",
        summary="Most recent alerts the system raised",
        description=(
            "Return the latest alerts (newest first) with severity and whether they "
            "were delivered. Use for 'มี alert อะไรบ้าง' / 'what happened recently'."
        ),
        response_model=list[AlertItem],
    )
    def get_recent_alerts(
        limit: int = Query(10, ge=1, le=100, description="how many alerts to return (default 10)")
    ) -> list[dict[str, Any]]:
        return db.recent_alerts(limit)

    @app.get(
        "/system_summary",
        operation_id="get_system_summary",
        summary="One-glance overall system health",
        description=(
            "Return node counts by status plus today's failure/lockout/alert tallies. "
            "Use for the broad question 'สถานะระบบตอนนี้เป็นยังไง' / 'system status'."
        ),
        response_model=SystemSummary,
    )
    def get_system_summary() -> dict[str, Any]:
        return db.system_summary()

    return app


def build_default_app() -> FastAPI:
    """App built from .env config — used by `uvicorn webtools.server:app`."""
    from config import load_config  # local import: avoid config side effects under tests

    cfg = load_config()
    return create_app(Database(cfg.db_path))


# Lazily constructed so importing this module (e.g. in tests) doesn't load .env or
# open the real DB. `uvicorn webtools.server:app` still works via __getattr__.
def __getattr__(name: str) -> Any:
    if name == "app":
        return build_default_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
