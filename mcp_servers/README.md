# CHENG AI MCP servers

In-repo MCP servers you can plug into CHENG AI with `--mcp` (no Node needed).

## search_server.py — web search + fetch
Exposes two tools (`search`, `fetch`) over a pluggable backend. Connect it:

```powershell
python cheng.py --workspace --mcp mcp_servers/search.mcp.json
```

### Choosing a backend (env vars, checked in order)
| set this | backend | free? |
|---|---|---|
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | **real Google** (Custom Search JSON API) | ✅ free 100 queries/day |
| `SEARXNG_URL` (e.g. `http://localhost:8888`) | SearXNG (aggregates Google + others) | ✅ free, self-host |
| `SEARCH_BACKEND=google_scrape` | best-effort Google scrape | ✅ but ⚠️ fragile / may be blocked |
| *(nothing)* | DuckDuckGo (ddgs) | ✅ free, no setup |

### Get FREE Google (Custom Search API) — ~5 min
1. **API key:** [console.cloud.google.com](https://console.cloud.google.com) → enable
   **"Custom Search API"** → Credentials → create an **API key**.
2. **Engine ID (cx):** [programmablesearchengine.google.com](https://programmablesearchengine.google.com)
   → create an engine, turn on **"Search the entire web"** → copy the **Search engine ID**.
3. Put both in `search.mcp.json` (`GOOGLE_API_KEY`, `GOOGLE_CSE_ID`), then run with `--mcp`.

That is the legitimate free path to real Google results (no scraping, no ToS issues).
Free tier = 100 queries/day; beyond that Google bills per 1000.
