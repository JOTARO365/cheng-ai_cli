"""LangChain / LangGraph adapter — run the SAME tools + persona inside a framework.

The Hybrid runtime: our lightweight `Brain` (ai/brain.py) is the default offline
runtime; this adapter lets a target system that already speaks LangChain/LangGraph
drive the EXACT same IT-context tools (ai/tools.py) and system prompt (ai/prompts.py).
Using LangGraph's prebuilt ReAct agent also brings the pieces our Brain skips —
per-thread memory / checkpointing.

Optional dependency — install only where needed:
    pip install -r requirements-langchain.txt

Usage:
    from ai.langchain_adapter import build_agent, ask
    agent = build_agent(cfg, db)                 # uses MemorySaver by default
    print(ask(agent, "PC ไหนปิดอยู่บ้าง", thread_id="it-1"))
    print(ask(agent, "แล้วเครื่องไหน offline นานสุด", thread_id="it-1"))  # remembers the thread
"""
from __future__ import annotations

from typing import Any

from ai.prompts import SYSTEM_CHAT
from ai.tools import TOOL_SPECS, dispatch
from storage.db import Database

_INSTALL_HINT = (
    "LangChain runtime not installed. This is an optional extra — run:\n"
    "    pip install -r requirements-langchain.txt"
)


def _descriptions() -> dict[str, str]:
    return {s["function"]["name"]: s["function"]["description"] for s in TOOL_SPECS}


def build_tools(db: Database) -> list[Any]:
    """Wrap the framework-neutral registry as LangChain StructuredTools (same names,
    same descriptions, same read-only dispatch — just a different shell)."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ImportError(_INSTALL_HINT) from exc

    desc = _descriptions()

    # Signatures mirror TOOL_SPECS so LangChain infers the args schema; bodies just
    # delegate to the one dispatch() so behavior can't drift from Brain's.
    def get_down_nodes() -> list:
        return dispatch("get_down_nodes", {}, db)

    def get_login_fails(hours: int = 24) -> list:
        return dispatch("get_login_fails", {"hours": hours}, db)

    def get_locked_accounts(hours: int = 24) -> list:
        return dispatch("get_locked_accounts", {"hours": hours}, db)

    def get_recent_alerts(limit: int = 10) -> list:
        return dispatch("get_recent_alerts", {"limit": limit}, db)

    def get_system_summary() -> dict:
        return dispatch("get_system_summary", {}, db)

    fns = [get_down_nodes, get_login_fails, get_locked_accounts,
           get_recent_alerts, get_system_summary]
    return [StructuredTool.from_function(fn, name=fn.__name__, description=desc[fn.__name__])
            for fn in fns]


def build_agent(cfg: Any, db: Database, checkpointer: Any | None = None) -> Any:
    """Build a LangGraph ReAct agent over Ollama using our tools + SYSTEM_CHAT.

    `checkpointer` defaults to an in-memory MemorySaver so the agent remembers a
    conversation per `thread_id` (the persistence our raw Brain lacks). Pass a
    SqliteSaver to persist across restarts.
    """
    try:
        from langchain_ollama import ChatOllama
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc

    model = ChatOllama(model=cfg.ollama_model, base_url=cfg.ollama_host)
    agent = create_react_agent(
        model,
        build_tools(db),
        prompt=SYSTEM_CHAT,
        checkpointer=checkpointer or MemorySaver(),
    )
    return agent


def ask(agent: Any, question: str, thread_id: str = "default") -> str:
    """Run one turn. `thread_id` selects the memory thread (same id → remembers)."""
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config)
    msg = result["messages"][-1]
    return getattr(msg, "content", "") or ""
