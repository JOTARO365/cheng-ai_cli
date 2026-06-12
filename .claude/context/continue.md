================================================================
CONTINUE — SME IT Agent (ai-agent-cli)
================================================================
Project  : ai-agent-cli (SME IT Agent)
Started  : 2026-06-10
Updated  : 2026-06-10

## CURRENT STATUS
🟢 In progress : v0.1.0 — collectors + Rule Engine + sandbox + tool server + JOTARO CLI (34 tests)

---- 2026-06-12 — JOTARO AI CLI (terminal tool-calling agent) + live stack up ----
✅ Done:
  - ai/tools.py: single tool registry (5 IT tools in Ollama/OpenAI function-spec) +
    dispatch(name,args,db) with hours/limit clamps. Reused by the CLI agent;
    LangChain-portable (wrap as @tool later).
  - ai/brain.py: Brain = ReAct harness around Ollama /api/chat (tools). HARNESS owns
    the loop (max_steps cap), read-only tools, graceful OllamaUnavailable. Brain takes
    `system=` + `tools=` args → future supervisor can spawn SPECIALIST brains per use case.
  - jotaro.py: branded REPL (rich banner + prompt_toolkit), Thai/EN, /help /status
    /clear /exit, live ⚙ tool-call display, + `--ask "Q"` one-shot mode.
  - tests/test_brain.py: mock-Ollama ReAct flow + dispatch + unavailable fallback. 34 pass.
  - LIVE VERIFIED against running Ollama+qwen2.5:3b+seeded DB:
    `jotaro.py --ask "PC ไหนปิดอยู่บ้าง"` → model called get_down_nodes → "PC20, PC12 ปิดอยู่".
    `--ask "login fail ใครเยอะสุด"` → get_login_fails → john 6 / nan 2. Tool-calling works on 3B.
💡 Two interfaces now share ONE backend (Ollama + SQLite): Open WebUI (web) and JOTARO (CLI).
🧱 RUNNING (this session, background tasks): ollama serve→D: (bjixs79a2), tool server :8000
   (bq7585yhm), open-webui :8080 (bhwmz1gb2). Open WebUI needs RAG_EMBEDDING_ENGINE=ollama
   (+ HF_HUB_OFFLINE=1) or it hangs on boot downloading the sentence-transformers model.
🔭 Roadmap discussed (not built): formalize harness + LangChain port; supervisor →
   specialist agents split by use case (security/network/service); evaluate C (from
   D:\Projects\42) ONLY for the ping-sweep collector — NOT the LLM path (inference-bound).

---- 2026-06-12 — Phase B: Hybrid harness (contract + LangChain/LangGraph adapter) ----
✅ Done:
  - docs/HARNESS.md: the harness contract (3 decoupled pieces: tools registry /
    SYSTEM_CHAT / Brain loop), reuse guide, 9-things coverage, runtime-choice table.
  - ai/langchain_adapter.py: build_tools(db) wraps the SAME ai/tools.py registry as
    LangChain StructuredTools; build_agent() = LangGraph create_react_agent over
    ChatOllama + SYSTEM_CHAT + MemorySaver; ask(thread_id) for per-thread memory.
    Lazy imports (optional dep). requirements-langchain.txt (langchain/langgraph/langchain-ollama).
  - examples/langchain_demo.py + tests/test_langchain_adapter.py (importorskip). 35 tests pass.
  - LIVE VERIFIED: python -m examples.langchain_demo → LangGraph agent called our tool,
    listed PC20/PC12, and the 2nd question answered FROM THREAD MEMORY (checkpointer) —
    the persistence raw Brain lacks. Hybrid proven end to end.
💡 Decision: Hybrid runtime — our Brain ships (offline/light, httpx-only); LangChain
   adapter is opt-in for target systems that already use LangChain/LangGraph. Same
   tools + same SYSTEM_CHAT both ways → behavior matches.
🔜 Phase C next: supervisor → specialist agents (security/network/service) on Brain(system=, tools=subset).

---- 2026-06-12 — File tools + permission gate + language guard + PydanticAI runtime ----
✅ Done:
  - ai/fs_tools.py: read_file/list_dir (safe) + write_file/edit_file/make_dir (WRITE_TOOLS,
    need confirm). Path-jail to a workspace root (rejects ../ + abs escapes), audit-logged.
  - ai/brain.py: permission gate (confirm_tools + confirm callback; declined→fed back, not run),
    pluggable dispatcher, temperature 0.2, + LANGUAGE GUARD (qwen2.5 leaks Chinese into Thai:
    regenerate up to 2x, then strip CJK as last resort). All backward-compatible.
  - jotaro.py: rewrote UI = professional-retro (SESSION/MODEL/STATUS/TOOLS HUD, dropped
    arcade FIGHTER/PLAYER1/INSERT COIN). Added --workspace [DIR] (bare = cwd) → fs mode with
    interactive y/N confirm for writes. SYSTEM_FS persona added to prompts.py.
  - ai/pydantic_agent.py: PydanticAI runtime (OllamaProvider+OpenAIChatModel) driving the SAME
    fs dispatch; write tools requires_approval=True → native DeferredToolRequests/Results
    approval loop; workspace defaults to cwd. requirements-pydantic.txt (optional extra).
  - tests: test_fs_tools (sandbox/dispatch/gate), test_brain (+language guard), test_pydantic_agent
    (importorskip). 44 pass.
  - LIVE VERIFIED: jotaro --workspace read via list_dir; PydanticAI `--ask` read via list_dir.
🐞 FINDING (3B model limits, not our bug): qwen2.5:3b (a) leaks Chinese — our Brain guard
  catches+strips it, but the PydanticAI path does NOT (guard is Brain-only → would need an
  @agent.output_validator port); (b) weak at chaining tools (list_dir then didn't read_file).
  Root fix = prod 14b / Thai-tuned model. Confirms the skill's "small models need more guards".
💡 Hybrid now has THREE runtimes over the same tools/prompts: Brain (default, has guards),
  LangGraph adapter (memory/checkpoint), PydanticAI (native approval + MCP). Each needs guards
  re-applied per runtime.
🔭 Frameworks surveyed (GitHub): PydanticAI = best external fit (Ollama+HITL approval+MCP+multi-agent,
  lighter than LangChain); smolagents rejected (degrades <7B, CodeAgent unsafe). Installed:
  langchain/langgraph/langchain-ollama, pydantic-ai-slim[openai] (all in system python, dev only).

---- 2026-06-12 — Phase C: supervisor → specialist agents ----
✅ Done:
  - ai/prompts.py: SECURITY_ANALYST / NETWORK_ANALYST / SERVICE_ANALYST personas
    (read-only, no-Chinese, shared _LANG_RULE), each scoped to its domain.
  - ai/specialists.py: Specialist registry (name → persona + TOOL subset + keywords);
    Supervisor builds one Brain per specialist (+ general fallback) and routes each
    question DETERMINISTICALLY by keyword (zero LLM calls — offline-friendly; swap
    route() body for an LLM router later). security={login_fails,locked_accounts},
    network={down_nodes}, service={recent_alerts,system_summary}.
  - jotaro.py: --team mode routes each question to a specialist, panel subtitle shows
    which one answered. respond() unifies single/workspace/team. /clear, --ask work in all.
  - tests/test_specialists.py: routing (TH+EN) + tool-subset + build. 53 tests pass.
  - LIVE VERIFIED: `jotaro --team --ask "login fail ใครเยอะสุด"` → routed to security →
    get_login_fails → clean Thai answer (john 6 / nan 2), NO Chinese leak.
💡 Brain(system=, tools=subset) carried the whole Phase C with no Brain changes — the
  decoupling paid off. Fewer tools per specialist also helps the 3B pick the right tool.
🔭 GitHub harness Chachamaru127/claude-code-harness evaluated → NOT usable (Claude-only
  dev-workflow harness in Shell/Go, not an embeddable offline-Ollama runtime). Kept our own.
🧱 JOTARO now has modes: (default) monitor · --workspace [DIR] file assistant w/ write-confirm ·
  --team specialist routing. Three runtimes still: Brain / LangGraph adapter / PydanticAI.

---- 2026-06-12 — Claude-Code-style UI + global alias ----
✅ Done:
  - jotaro.py UI restyled to Claude Code / Codex look: rounded welcome panel (box.ROUNDED,
    coral #d97757 accent), ✻ wordmark, ⏺ markers for tool calls, answers as flowing markdown
    (no heavy box), clean muted palette. Replaced the 8-bit arcade theme.
  - PowerShell $PROFILE aliases (CurrentUserAllHosts): jotaro-ai (file assistant in CWD),
    jotaro-mon (monitor), jotaro-team (specialist routing) — guarded block w/ marker so re-run
    is idempotent. `jotaro-ai` in any folder = file AI sandboxed to that folder.
  - VERIFIED: 53 tests pass; jotaro imports clean; `jotaro-ai --ask` run from D:\sandbox\alias_try
    → list_dir → correct answer, clean Thai. No bugs found.

## (earlier) Chatbot tool server status
🟢 collectors + Rule Engine + sandbox + chatbot tool server
📍 Next        : install Ollama + Open WebUI to try the chatbot live (see docs/setup.md);
                 then ai/brain.py specialist-analyst escalation; then alert/dispatch.py.
⚠️ BLOCKER for live chat: Ollama AND Open WebUI not installed yet. Installer ready at
   D:\Ollama\OllamaSetup.exe. Our tool server half is DONE & verified live.

## ARCHITECTURE DECISION (2026-06-12) — Phase 1 = chatbot-first via Open WebUI
- Phase 1 reframed: ship the CHATBOT first (IT chats with the system), monitor/alert later.
- Chat UI = **Open WebUI** (open-source, offline) — NOT a hand-rolled prompt_toolkit REPL.
  It owns the chat window + Ollama calls. Open WebUI is also the Phase-4 web-dashboard path.
- Our job = expose live IT data as **OpenAPI tools** via a FastAPI "tool server"
  (webtools/server.py); Open WebUI registers it (Settings → Tools). Data flow:
  Ollama ← Open WebUI → tool server → SQLite (read-only).
- Multi-agent (user asked): the Rule Engine IS the deterministic supervisor (dispatch
  table). Plan = specialist PROMPTS per kind (security/network/service), single-shot —
  NOT an LLM-supervisor loop (too many calls for an offline CPU box). LangGraph
  supervisor deferred to Phase 3. See ai/prompts.py SYSTEM_ANALYST stub.
- Install on D: (C: only ~9GB free): OLLAMA_MODELS=D:\ollama-models; Open WebUI in a
  D: venv with DATA_DIR=D:\openwebui-data.

## ROADMAP (from sme_it_agent_prompt.md)
- Phase 1 (MVP ~2 wks): Collector + Rule Engine + Chat CLI + basic Alert
- Phase 2: ServiceWatcher + dashboard summary + all alert channels
- Phase 3: Auto-remediation w/ IT confirm in chat (e.g. unlock account)
- Phase 4: Installer, multi-site, web dashboard (SaaS)

## WORK LOG

---- 2026-06-10 — Project Initialized ----
✅ Done:
  - Ran /project; generated .claude context, roles, skills, agents, docs
  - Captured architecture from sme_it_agent_prompt.md
  - Agents created: backend-dev, ai-engineer, security-engineer, devops-engineer, it-support
  - Skills marked for use: agent-harness-and-skills, live-system-rollout-safety,
    powershell-windows-encoding
  - MCP configured (dev only): filesystem, sqlite

💡 Notes / key decisions:
  - 100% offline. NO internet, NO auto-fix in Phase 1, NO Azure AD.
  - Rule Engine must filter HARD before calling Ollama (CPU boxes are slow).
  - All thresholds live in engine/thresholds.py so they're tunable per site.
  - All DB writes go through storage/db.py (SQLite single-writer).

---- 2026-06-10 — Model sizing decided ----
✅ Done:
  - Checked dev box: 8GB RAM, RTX 3050 Laptop 4GB VRAM, i5-11320H.
  - Decision: dev=qwen2.5:3b, prod=qwen2.5:14b (swap via OLLAMA_MODEL, no code change).
  - Updated QUICKREF.md (MODEL SIZING section) + docs/setup.md accordingly.
💡 Note: dev box is RAM-bound, max ~7–8B. Never pull 14B here (OOM). Rule Engine
  filtering means 3B is fine to validate the pipeline.

---- 2026-06-10 — Scaffold: config + db + ping (first slice works) ----
✅ Done:
  - config.py — load/validate .env, Config dataclass, setup_logging (rotating).
  - storage/db.py — SQLite (WAL), tables nodes/events/alerts, all access here.
  - collectors/ping.py — ping_host/check_node/check_once/run_loop; events only on
    state change; latency parsed via regex (locale-proof); never crashes the loop.
  - requirements.txt, .env.example, data/nodes.txt added.
  - SMOKE TEST PASSED: pinged 127.0.0.1 (1ms) + 8.8.8.8 (26ms) = up; 10.255.255.1
    = down with consecutive_fails incrementing. DB rows written correctly.
💡 Verified design choice: no event on first sighting (prev='unknown') — only on
   real up↔down flips. Tested: empty event log on first-seen nodes is intentional.
   Note: data/itagent.db now holds dev test rows (gitignored).

---- 2026-06-10 — Rule Engine (thresholds + rules) done & tested ----
✅ Done:
  - engine/thresholds.py — single source of tunable numbers + per-site env overrides
    (TH_*); is_work_time() for work-hours gating. (Changing these = live-system change.)
  - engine/rules.py — pure decide_login_fail/node_offline/service_down + RuleEngine
    with a dispatch table (signal kind -> handler, no if/else forest — minishell-style
    builtin dispatch). Side effects (events/alerts/AI) isolated in _apply; on_alert /
    on_ai callbacks let alert/dispatch + ai/brain plug in later. scan_offline_nodes()
    reads 'down' nodes from DB and applies the offline rule.
  - tests/test_rules.py — 17 table-driven tests over the full ladder + boundaries
    (2/3/5 login-fail, 120/300s offline, work-hours vs after-hours/weekend) → ALL PASS.
  - Integration smoke test: signals → correct actions, 5 events + 2 alerts written,
    on_alert(x2)/on_ai(x2) callbacks fired.
  - FIXED: config.setup_logging now forces stdout/stderr to UTF-8 — Windows console
    was turning '—' and Thai into mojibake (powershell-windows-encoding). Verified.
💡 Decisions:
  - AI is only ever called by the engine (via on_ai), never by a collector.
  - decide_* are pure (no I/O) so thresholds stay unit-testable; process() = side effects.
  - pytest installed to user site (warn: Scripts not on PATH — run via `python -m pytest`).

---- 2026-06-10 — eventlog collector + sandbox (end-to-end works) ----
✅ Done:
  - engine/rules.py: added decide_account_lockout + 'account_lockout' to dispatch.
  - collectors/eventlog.py: EventSource Protocol; WindowsEventSource (pywin32, lazy
    import, baseline-on-first-run so history isn't replayed, 4625/4740 string-insert
    parsing); LoginFailTracker (per-user rolling-window count); EventLogCollector
    feeds login_fail/account_lockout signals to the engine; SimulatedEventSource.
  - sandbox/simulate.py: narrative "IT day" — brute-force, lockout, PC offline,
    service down — runs the REAL engine + collector with stubbed fake_alert/fake_ai.
    No AD / Ollama / admin needed. `python -m sandbox.simulate`.
  - tests/test_eventlog.py: tracker window/forget/reset, lockout decision, collector
    brute-force => exactly one alert. Full suite: 22 passed.
  - Env check: pywin32 PRESENT (system Python). Ollama NOT installed (no model).
🐞 Bug found BY THE SANDBOX & fixed:
  - record_event() did json.dumps(signal) but node_offline carries a datetime ('when')
    => TypeError "datetime is not JSON serializable". Fixed in storage/db.py with
    json.dumps(..., default=str). (Sandbox earned its keep on day one.)
🧩 Encoding (again): every print-heavy entrypoint must reconfigure stdout to UTF-8 or
   the cp874 console dies on emoji/Thai. Added the reconfigure to sandbox/simulate.py
   (config.setup_logging already does it). Pattern: any new __main__ that prints
   non-ASCII needs this. See powershell-windows-encoding.

🔜 Next concrete tasks:
  1. alert/dispatch.py — Line / Teams / Email senders; wire as the on_alert callback
     (replace sandbox fake_alert). Stub-then-real; keep offline-friendly.
  2. ai/brain.py + ai/prompts.py — Ollama HTTP client; wire as on_ai (replace fake_ai).
     BLOCKED on installing Ollama + `ollama pull qwen2.5:3b`.
  3. main.py — load config, setup_logging, start ping + eventlog loops + engine, chat CLI.

---- 2026-06-12 — Chatbot tool server (Phase 1 pivot to Open WebUI) ----
✅ Done:
  - storage/db.py: added READ-ONLY snapshot helpers (down_nodes, login_fails,
    locked_accounts, recent_alerts, system_summary) — the "tools" the chatbot answers from.
  - webtools/server.py: FastAPI OpenAPI tool server, create_app(db) factory + lazy
    `app` (uvicorn webtools.server:app). 5 GET tools with clear summaries/descriptions
    (the LLM reads them to pick a tool). Read-only by design (Phase 1 rule).
  - ai/prompts.py: SYSTEM_CHAT (paste into Open WebUI system prompt; `python -m ai.prompts`
    dumps it) + SYSTEM_ANALYST stub for the later escalation path.
  - main.py: rewritten as the tool-server launcher (uvicorn), --host/--port, UTF-8.
  - sandbox/seed_demo.py: seeds the real DB_PATH with demo nodes/fails/alerts so the
    chatbot has something to talk about on first try (re-runnable, clears first).
  - tests/test_tool_server.py: 7 tests via FastAPI TestClient over temp DB. Suite = 29 pass.
  - requirements.txt += fastapi, uvicorn; .env.example += TOOL_SERVER_HOST/PORT.
  - docs/setup.md rewritten for the new architecture (Ollama+Open WebUI+tool server wiring).
  - Ollama install prep: downloaded D:\Ollama\OllamaSetup.exe (BITS, ~1.33GB);
    created D:\ollama-models + set OLLAMA_MODELS (User) = D:\ollama-models.
✅ Verified LIVE: started `python main.py`, hit /down_nodes (PC20 35.8m, PC12 8.8m),
   /system_summary (up=3 down=2 pending=2), /openapi.json (5 tools). Our half works.
💡 Decisions: chat UI = Open WebUI (not custom REPL); integrate via FastAPI OpenAPI
   tool server (decoupled, version-controlled, all DB reads stay in db.py).
🔜 To try live: (a) run D:\Ollama\OllamaSetup.exe /SILENT /DIR="D:\Ollama" (UAC) +
   ollama pull qwen2.5:3b; (b) install Open WebUI in D: venv; (c) wire per docs/setup.md.
