"""Web search tool (opt-in) — the agent's window to the internet.

OFF by design for the offline IT-monitor; enabled only for the general/workspace mode
via `cheng --web`. Uses DuckDuckGo (ddgs) — no API key. This is the ONE place the
general assistant reaches the internet, so keep it for looking things up, never for
sending the company's private data out.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)
_UA = {"User-Agent": "Mozilla/5.0 (CHENG AI IT agent)"}

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


# --- query/result tuning ---------------------------------------------------
_THAI = re.compile(r"[฀-๿]")
_JUNK_HOSTS = ("google.", "bing.", "duckduckgo.", "yahoo.", "yandex.")


def _region(query: str) -> str:
    """Localise Thai queries; worldwide otherwise."""
    return "th-th" if len(_THAI.findall(query)) >= 3 else "wt-wt"


def _clean_query(q: str) -> str:
    """Strip instruction filler the model often prepends/appends to a search query."""
    q = q.strip()
    q = re.sub(r"^(ช่วย)?(ค้นหา|ค้น|search( for)?|google|หา)\s*(เว็บ|web|ในเน็ต|ข้อมูล)?\s*(ให้(หน่อย)?)?\s*",
               "", q, flags=re.I)
    q = re.sub(r"\s*(ลองค้น(เว็บ)?ดู|ค้นเว็บดู|search the web( for it)?)\s*$", "", q, flags=re.I)
    return q.strip() or q


def _is_junk(url: str) -> bool:
    m = re.match(r"https?://(?:www\.)?([^/]+)(/[^?#]*)?", url or "")
    if not m:
        return True
    host, path = m.group(1).lower(), (m.group(2) or "").strip("/")
    return any(host.startswith(j) for j in _JUNK_HOSTS) and len(path) < 3  # bare engine page


def _filter_results(rows: list[dict], n: int) -> list[dict]:
    """Drop bare search-engine homepages + empty/dupe entries; keep up to n."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        url, title = (r.get("url") or "").strip(), (r.get("title") or "").strip()
        if not url or not title or _is_junk(url):
            continue
        key = url.split("?")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= n:
            break
    return out


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
        raw = str(args.get("query", "")).strip()
        if not raw:
            return {"error": "empty query"}
        query = _clean_query(raw)
        try:
            n = max(1, min(int(args.get("n", 5)), 10))
        except (TypeError, ValueError):
            n = 5
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                # explicit Google/Bing backends give far cleaner results than "auto";
                # over-fetch then filter junk/dupes down to n.
                rows = list(ddgs.text(query, max_results=n * 2, region=_region(query),
                                      safesearch="moderate", backend="google, bing, duckduckgo"))
        except Exception as exc:  # network/parse — surface, don't crash the loop
            log.warning("web_search failed: %s", exc)
            return {"error": f"web search failed: {exc}"}
        results = _filter_results(
            [{"title": r.get("title"), "url": r.get("href") or r.get("url"),
              "snippet": r.get("body") or r.get("snippet")} for r in rows], n)
        return {"query": query, "results": results}

    return dispatch
