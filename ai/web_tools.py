"""Web search tool (opt-in) — the agent's window to the internet.

OFF by design for the offline IT-monitor; enabled only for the general/workspace mode
via `jotaro --web`. Uses DuckDuckGo (ddgs) — no API key. This is the ONE place the
general assistant reaches the internet, so keep it for looking things up, never for
sending the company's private data out.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)
_UA = {"User-Agent": "Mozilla/5.0 (JOTARO IT agent)"}

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
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch a web page (or text URL) and return its readable text. Use after "
                           "web_search to read a result, or for a URL the user gives.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "the URL to fetch"}},
                "required": ["url"],
            },
        },
    },
]


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&#\d+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def make_web_dispatcher(max_chars: int = 4000) -> Callable[[str, dict[str, Any]], Any]:
    def dispatch(name: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if name == "fetch_url":
            url = str(args.get("url", "")).strip()
            if not url:
                return {"error": "empty url"}
            try:
                r = httpx.get(url, timeout=15, follow_redirects=True, headers=_UA)
                text = _html_to_text(r.text)
            except Exception as exc:  # network/parse
                return {"error": f"fetch failed: {exc}"}
            return {"url": str(r.url), "status": r.status_code,
                    "text": text[:max_chars], "truncated": len(text) > max_chars}
        if name != "web_search":
            return {"error": f"unknown tool {name!r}"}
        query = str(args.get("query", "")).strip()
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
