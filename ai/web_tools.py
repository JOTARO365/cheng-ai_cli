"""Web search tool (opt-in) — the agent's window to the internet.

OFF by design for the offline IT-monitor; enabled only for the general/workspace mode
via `jotaro --web`. Uses DuckDuckGo (ddgs) — no API key. This is the ONE place the
general assistant reaches the internet, so keep it for looking things up, never for
sending the company's private data out.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

WEB_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web (DuckDuckGo) and return top results (title, url, snippet). "
                           "Use to look up docs/facts you don't know.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "n": {"type": "integer", "description": "how many results (default 5, max 10)"},
                },
                "required": ["query"],
            },
        },
    },
]


def make_web_dispatcher() -> Callable[[str, dict[str, Any]], Any]:
    def dispatch(name: str, args: dict[str, Any]) -> Any:
        if name != "web_search":
            return {"error": f"unknown tool {name!r}"}
        query = str((args or {}).get("query", "")).strip()
        if not query:
            return {"error": "empty query"}
        try:
            n = max(1, min(int(args.get("n", 5)), 10))
        except (TypeError, ValueError):
            n = 5
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                rows = list(ddgs.text(query, max_results=n))
        except Exception as exc:  # network/parse — surface, don't crash the loop
            log.warning("web_search failed: %s", exc)
            return {"error": f"web search failed: {exc}"}
        results = [{"title": r.get("title"), "url": r.get("href") or r.get("url"),
                    "snippet": r.get("body") or r.get("snippet")} for r in rows]
        return {"query": query, "results": results}

    return dispatch
