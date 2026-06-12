# JOTARO AI CLI

A **100% offline**, local-LLM IT assistant for your terminal — built on a small,
hand-rolled **agent harness** over [Ollama](https://ollama.com). It watches a Windows
Active Directory / on-prem network and answers IT's questions ("PC ไหนปิดอยู่?",
"login fail วันนี้กี่ครั้ง?") from real data, and can also act as a sandboxed
**file assistant** in any folder. No internet, no cloud — data never leaves the box.

> Phase 1 = monitor + report (read-only). Asking it to change anything (or edit files)
> always goes through an explicit confirmation gate.

## Highlights
- **Offline & local** — Ollama only (dev: `qwen2.5:3b`, prod: `qwen2.5:14b`). Swap via `.env`.
- **Real agent harness** (not just a chat): a ReAct tool-calling loop the *code* owns —
  stop condition, tool registry, permission gating, path sandbox, and a language guard
  that keeps a Chinese-origin model answering in Thai/English.
- **Three modes**, one shared backend (Ollama + SQLite):

| command | mode | what it does |
|---|---|---|
| `jotaro-mon` / `python jotaro.py` | monitor | read-only IT tools: offline nodes, login fails, lockouts, alerts |
| `jotaro-ai` / `python jotaro.py --workspace` | file assistant | read/edit/write files **in the current folder** — writes ask first |
| `jotaro-team` / `python jotaro.py --team` | specialist routing | a supervisor routes each question to a security / network / service agent |

- **Hybrid runtimes** over the *same* tools + prompts: the built-in `Brain` (light,
  offline), a **LangGraph** adapter (memory/checkpoint), and a **PydanticAI** adapter
  (native human-in-the-loop approval + MCP). Pick per deployment.

## Quickstart
```powershell
# 1. install Ollama + pull the model (dev box)
ollama pull qwen2.5:3b

# 2. python deps
pip install -r requirements.txt

# 3. (optional) seed demo data so there's something to chat about
python -m sandbox.seed_demo

# 4. run
python jotaro.py            # monitor REPL
python jotaro.py --team     # specialist routing
python jotaro.py --workspace --ask "what files are here?"
```

Optional extras (only if you want those runtimes):
`pip install -r requirements-langchain.txt` · `pip install -r requirements-pydantic.txt`

### Global command (any terminal)
`bin/` contains portable launchers (`jotaro-ai.cmd`, `jotaro-mon.cmd`, `jotaro-team.cmd`).
Add `bin/` to your PATH and type `jotaro-ai` in any folder to launch the file assistant
scoped to that folder.

## Architecture
```
collectors ─▶ Rule Engine (harness) ─┬─▶ Alert engine
 (ping/eventlog/wmi/ldap)            └─▶ Ollama brain ─▶ findings
                                                  ▲
                       IT admin ── chat (JOTARO / Open WebUI) ──┘
```
The chat layer (JOTARO CLI, or Open WebUI via the FastAPI tool server in `webtools/`)
talks to Ollama and reaches live data through read-only tools (`ai/tools.py`). See
`docs/HARNESS.md` for the harness contract and `docs/architecture.md` for the full flow.

## Layout
```
jotaro.py            CLI entrypoint (monitor / --workspace / --team)
ai/                  brain (ReAct loop), tools, fs tools, prompts, specialists, adapters
engine/              rule engine + tunable thresholds
collectors/          ping + Windows Event Log collectors
storage/db.py        SQLite store (all DB access here)
webtools/            FastAPI OpenAPI tool server for Open WebUI
docs/                setup, architecture, HARNESS contract
tests/               pytest suite (offline; mocks Ollama/AD)
```

## Tests
```powershell
python -m pytest -q
```
Everything is mocked — the suite runs offline on any machine.

## Safety (Phase 1)
Read-only by default. File writes are sandboxed to the chosen folder and require a
`y/N` confirmation. No AD writes, no auto-remediation, no internet, no data leaves the
machine.
