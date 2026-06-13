# JOTARO AI CLI

A **local-first AI assistant for your terminal** — a small, hand-rolled **agent
harness** over [Ollama](https://ollama.com) with a full tool belt (files, Excel,
shell, web search, MCP, memory, skills) and a Claude-Code-style UI. It started as a
**100% offline** Windows AD / on-prem IT monitor ("PC ไหนปิดอยู่?", "login fail
วันนี้กี่ครั้ง?") and grew into a general-purpose coding/ops assistant you can point
at any folder.

> **Two postures, one codebase.** The **IT monitor** stays strictly offline and
> read-only. The **workspace assistant** can reach the web and edit files — every
> write or shell command goes through an explicit confirmation gate, and web access
> is opt-out (`--no-web`).

## Why it works
The proven insight behind the project: **the harness — not the model size — is the
enabler.** In our eval, `qwen2.5:3b` *with the tool harness* scored 100% on grounded
fact questions while the bare model scored 0%. Learning lives in the harness store
(memory + skills + tools), not in frozen model weights.

## Highlights
- **Local LLM** — Ollama only (dev `qwen2.5:3b`, prod `qwen2.5:14b`). Swap via `.env` or `/model`.
- **Real agent harness** (not just a chat): a ReAct tool-calling loop the *code* owns —
  stop condition, tool registry, permission gating, path sandbox, streaming, and a
  language guard that keeps a Chinese-origin model answering in Thai/English.
- **Full tool belt** (workspace mode):

  | tool group | what the model can do |
  |---|---|
  | **files** | list / glob / grep / read / **edit** / **write** (sandboxed to the folder) |
  | **excel** | read & write `.xlsx` sheets (openpyxl) |
  | **shell** | `run_command` — confirmed before each run |
  | **web** | `web_search` (DuckDuckGo via Google/Bing backend — free, no API key) + `fetch_url` |
  | **mcp** | connect external MCP servers; their tools become callable |
  | **memory** | `remember` / `recall` durable facts (SQLite) |
  | **skills** | progressive-loading `SKILL.md` runbooks, toggled per-skill |

- **Username/password login** (`--login`) — PBKDF2-HMAC-SHA256 + per-user salt,
  temporary lockout after repeated failures. First run bootstraps an admin.
- **Anti-hallucination** — an opt-in verifier sub-agent (`--verify`) checks each
  answer against the tool evidence; a deterministic degeneracy detector catches
  small-model meltdown; auto web-search fallback when the model says "I don't know".
- **Scales context** — `fan_out_summarize` splits a big file across sub-agents
  (context firewall) and merges; specialist routing splits by domain.
- **Hybrid runtimes** over the *same* tools + prompts: the built-in `Brain` (light,
  offline), a **LangGraph** adapter (memory/checkpoint), and a **PydanticAI** adapter
  (native human-in-the-loop approval + MCP).

## Modes
One shared backend (Ollama + SQLite), four entrypoints:

| command | mode | what it does |
|---|---|---|
| `jotaro-mon` / `python jotaro.py` | monitor | **offline, read-only** IT tools: offline nodes, login fails, lockouts, alerts |
| `jotaro-ai` / `python jotaro.py --workspace` | file assistant | read/edit/write files in the current folder + web/excel/shell — writes ask first |
| `jotaro-team` / `python jotaro.py --team` | specialist routing | a supervisor routes each question to a security / network / service agent |
| `jotaro-tui` / `python jotaro_tui.py` | full TUI | a Textual full-screen interface (status bar / chat log / input) |

## Quickstart
```powershell
# 1. install Ollama + pull the model (dev box)
ollama pull qwen2.5:3b

# 2. python deps
pip install -r requirements.txt

# 3. (optional) seed demo data so there's something to chat about
python -m sandbox.seed_demo

# 4. run
python jotaro.py                                   # monitor REPL (offline)
python jotaro.py --workspace --ask "what files are here?"
python jotaro.py --workspace --login               # require sign-in first
python jotaro.py --team                            # specialist routing
```

Optional extras (only if you want those runtimes):
`pip install -r requirements-langchain.txt` · `pip install -r requirements-pydantic.txt`

### Global command (any terminal)
`bin/` holds portable launchers (`jotaro-ai.cmd`, `jotaro-mon.cmd`, `jotaro-team.cmd`,
`jotaro-tui.cmd`). Add `bin/` to your PATH and type `jotaro-ai` in any folder to launch
the assistant scoped to that folder.

## In-session commands
```
/help                 show commands              /status    system status (no model)
/model [name]         list / switch the model    /clear     reset the conversation
/remember <fact>      save a durable fact         /memory    list what's remembered
/skills [on|off|dir]  list · toggle · load a dir  /summarize fan-out summarize a file
/whoami               show the signed-in user     /passwd    change your password
/users [add|passwd|del <name>]                    admin-only user management
```
Type `/` for a pop-up command menu (↑↓ to choose).

## Web search & MCP
Workspace mode is **online by default** (`--no-web` to disable). `web_search` uses
DuckDuckGo's Google/Bing backends for clean results with **no API key**, plus query
cleanup, language-aware region, and junk/duplicate filtering.

For a real Google-quality backend, run the in-repo MCP search server, which picks a
backend from env (Google Custom Search API → SearXNG → Google-scrape → DuckDuckGo):
```powershell
python jotaro.py --workspace --mcp mcp_servers/search.mcp.json
```
See `mcp_servers/README.md` for the free Google Custom Search setup.

## Architecture
```
collectors ─▶ Rule Engine (harness) ─┬─▶ Alert engine
 (ping/eventlog/wmi/ldap)            └─▶ Ollama brain ─▶ findings
                                                  ▲
                            IT admin ── chat (JOTARO CLI / TUI) ──┘
```
The chat layer talks to Ollama and reaches live data through tools. See
`docs/HARNESS.md` for the harness contract and `docs/architecture.md` for the full flow.

## Layout
```
jotaro.py            CLI entrypoint (monitor / --workspace / --team / --login)
jotaro_tui.py        Textual full-screen TUI
ai/                  brain (ReAct loop), auth, fs/excel/shell/web tools, memory,
                     skills, verify, parallel fan-out, specialists, mcp client, adapters
engine/              rule engine + tunable thresholds
collectors/          ping + Windows Event Log collectors
storage/db.py        SQLite store — nodes/events/alerts/memory/users (all DB access here)
mcp_servers/         in-repo MCP search server (pluggable backend)
eval/                harness-vs-bare evaluation harness
docs/                setup, architecture, HARNESS contract
tests/               pytest suite (offline; mocks Ollama/AD/network)
```

## Tests
```powershell
python -m pytest -q          # 153 tests, fully offline (Ollama/AD/network mocked)
```

## Safety
The **IT monitor** is read-only and offline: no AD writes, no auto-remediation, no
internet. In the **workspace assistant**, file writes are sandboxed to the chosen
folder and shell commands each require a `y/N` confirmation; the web tools are the one
place the assistant reaches the internet — for looking things up, never for sending
your data out. Passwords are stored hashed (PBKDF2 + salt), never plaintext, and the
`*.db` store is gitignored.
