"""JOTARO search MCP server — `search` + `fetch` tools over a pluggable backend.

Pick the backend with env vars (checked in this order); no code change needed:
  1. GOOGLE_API_KEY + GOOGLE_CSE_ID  → real Google (Custom Search JSON API, free 100/day)
  2. SEARXNG_URL                      → a SearXNG instance (aggregates Google etc., free)
  3. SEARCH_BACKEND=google_scrape     → best-effort Google scrape (fragile, no key)
  4. (default)                        → DuckDuckGo via ddgs (free, no setup)

Run standalone (stdio):  python mcp_servers/search_server.py
Use from JOTARO:          python jotaro.py --workspace --mcp mcp_servers/search.mcp.json

Free Google in 5 min: console.cloud.google.com → enable "Custom Search API" → make an
API key; programmablesearchengine.google.com → create an engine ("search entire web")
→ copy its ID. Set GOOGLE_API_KEY and GOOGLE_CSE_ID. That's the legit free Google path.
"""
from __future__ import annotations

import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jotaro-search")
_UA = {"User-Agent": "Mozilla/5.0 (JOTARO)"}
TIMEOUT = 15


def _google_cse(query: str, n: int) -> list[dict]:
    r = httpx.get("https://www.googleapis.com/customsearch/v1", timeout=TIMEOUT, params={
        "key": os.environ["GOOGLE_API_KEY"], "cx": os.environ["GOOGLE_CSE_ID"],
        "q": query, "num": min(n, 10)})
    r.raise_for_status()
    return [{"title": i.get("title"), "url": i.get("link"), "snippet": i.get("snippet")}
            for i in r.json().get("items", [])]


def _searxng(query: str, n: int) -> list[dict]:
    base = os.environ["SEARXNG_URL"].rstrip("/")
    r = httpx.get(f"{base}/search", timeout=TIMEOUT, headers=_UA,
                  params={"q": query, "format": "json"})
    r.raise_for_status()
    return [{"title": i.get("title"), "url": i.get("url"), "snippet": i.get("content")}
            for i in r.json().get("results", [])[:n]]


def _google_scrape(query: str, n: int) -> list[dict]:
    r = httpx.get("https://www.google.com/search", timeout=TIMEOUT, headers=_UA,
                  params={"q": query, "num": n, "hl": "th"}, follow_redirects=True)
    # best-effort: pull result blocks (fragile — Google may serve a consent/CAPTCHA page)
    out = []
    for m in re.finditer(r'<a href="(https?://[^"&]+)"[^>]*><h3[^>]*>(.*?)</h3>', r.text):
        out.append({"title": re.sub("<[^>]+>", "", m.group(2)), "url": m.group(1), "snippet": ""})
        if len(out) >= n:
            break
    return out


def _ddg(query: str, n: int) -> list[dict]:
    from ddgs import DDGS
    with DDGS() as d:
        # google/bing backends are far cleaner than "auto"
        rows = d.text(query, max_results=n, safesearch="moderate",
                      backend="google, bing, duckduckgo")
        return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                for r in rows]


def _backend() -> str:
    if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID"):
        return "google"
    if os.getenv("SEARXNG_URL"):
        return "searxng"
    if os.getenv("SEARCH_BACKEND") == "google_scrape":
        return "google_scrape"
    return "ddg"


@mcp.tool()
def search(query: str, n: int = 5) -> dict:
    """Search the web and return results (title, url, snippet). Backend picked from env
    (Google CSE / SearXNG / Google-scrape / DuckDuckGo)."""
    n = max(1, min(int(n), 10))
    backend = _backend()
    fn = {"google": _google_cse, "searxng": _searxng,
          "google_scrape": _google_scrape, "ddg": _ddg}[backend]
    try:
        return {"backend": backend, "query": query, "results": fn(query, n)}
    except Exception as exc:  # noqa: BLE001
        return {"backend": backend, "query": query, "error": str(exc), "results": []}


@mcp.tool()
def fetch(url: str) -> dict:
    """Fetch a web page and return its readable text."""
    try:
        r = httpx.get(url, timeout=TIMEOUT, headers=_UA, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "error": str(exc)}
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return {"url": str(r.url), "status": r.status_code, "text": text[:4000]}


if __name__ == "__main__":
    mcp.run()
