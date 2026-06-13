================================================================
CONTINUE — SME IT Agent (ai-agent-cli)
================================================================
Project  : ai-agent-cli (SME IT Agent)
Started  : 2026-06-10
Updated  : 2026-06-10

---- 2026-06-13 — Polish: steering error messages + few-shot (Anthropic refinements) ----
✅ ai/fs_tools.py: edit_file "old_string not found" → now STEERS: "read_file '<path>' first
   and copy exact text incl. indentation (file has N lines)" + whitespace-hint when the
   first line IS present (differs only by indentation). FileNotFoundError → "call list_dir
   to see what exists." (Anthropic "Writing tools": errors should guide recovery, not just
   report. excel_tools already steered — "available headers: [...]".)
✅ ai/prompts.py SYSTEM_CHAT: + "after a tool returns, ALWAYS compose a final answer" +
   3 compact EXAMPLES (pattern not data) — few-shot the 3b on the call-tool→answer flow
   (the skill's gotcha: small models stop after a tool call). Prompt still 1.8KB.
✅ tests/test_fs_tools.py +2 (edit steer, missing-file steer). 275 tests pass.
💡 "make model smarter" layer now: #1 tool scoping, #2 structured output, #3 model router,
   + steering errors + few-shot. All grounded in Anthropic "Building/Writing tools for agents".

---- 2026-06-13 — #3 Model router by difficulty (easy→3b, hard→coder/14b) ----
✅ ai/router.py ModelRouter(classifier, easy_model, hard_model, use_llm=False): pick(q) →
   (model, difficulty). Routes UP only when the hard model is actually pulled (_hard_ok
   cached); fails safe to easy. config OLLAMA_MODEL_HARD (default = OLLAMA_MODEL → no-op).
   cheng --auto-model (non-team): per-turn brain.model swap + "↗ hard turn → <model>" note.
✅ tests/test_router.py (8) + config field. 273 tests pass.
🐞 HONEST FINDING (live): the 3b is UNRELIABLE at self-classifying difficulty — it labelled
   even "PC ไหนปิดอยู่บ้าง" as hard (same meta-task weakness as the specialist-router/excel
   findings). FIX: made a DETERMINISTIC heuristic the DEFAULT (coding/planning/explain-step
   keywords EN+TH = hard, else easy); the structured LLM classifier is opt-in (use_llm,
   only worthwhile with a capable classifier model). Heuristic live = 4 IT lookups→easy,
   3 coding/design→hard. Reliable + zero-cost — mirrors the keyword specialist router.
💡 Pattern reaffirmed: on a 3B, prefer deterministic logic for meta-decisions (routing,
   difficulty); reserve the model for the actual answer. Anthropic routing = classifier OR rules.
🧱 coder:7b still downloading (flaky net, blob restarts) — when it lands, hard turns
   auto-route to it (no code change) + run python -m eval.compare_models for the A/B.

---- 2026-06-13 — #2 Structured output (Ollama format=schema → reliable on 3b) ----
✅ Brain.structured(prompt, schema, system=) → constrained JSON via Ollama `format` (no
   tools/stream); _parse_json strips fences/extracts {..}; retries then StructuredError.
   _chat gained fmt= param. The reliable primitive for routing/classify/extract on a small model.
✅ Applied: Supervisor(llm_route=True) → _route_llm uses structured {"specialist": enum},
   falls back to keyword on StructuredError/OllamaUnavailable (routing never breaks).
   Keyword stays DEFAULT (zero LLM calls, offline). cheng --llm-route flag (with --team).
✅ tests/test_structured.py (8: parser + structured + schema-passed + retry) +
   test_specialists (3: llm route, fallback, default). 265 tests pass.
✅ LIVE on qwen2.5:3b: extraction PERFECT ("SRV1 บริการ Print Spooler ล่ม" → host=SRV1,
   service=Print Spooler, severity=critical); router agrees w/ keyword on clear cases.
💡 Anthropic/skill: structured/typed output = big reliability win on small models. Next
   candidate in the "smarter model" layer: #3 model router by difficulty (3b vs coder:7b/14b).

---- 2026-06-13 — #1 Tool scoping (Anthropic: fewer tools = smarter small model) ----
✅ Just-in-time per-turn tool gating in Brain._gate_tools(question): ALWAYS domain tools;
   memory tools (remember/recall) ONLY on a save/recall intent (_MEMORY_INTENT EN+TH);
   skill tools (find/load_skill) ONLY when skills on AND a skill STRONGLY matches
   (search_skills min_hits=2 + stopword filter). self.tools stays the full superset for
   introspection; _chat(tools=) sends the gated subset. _rebuild_tools() centralizes assembly.
   FIXED a latent bug: skill tools were injected whenever skills were DISCOVERED, ignoring
   skills_enabled/--no-skills.
✅ tests/test_tool_gating.py (5) + search_skills min_hits. 254 tests pass.
✅ LIVE: default/coding Q → 5 tools (was 9); "จำไว้ว่า…" → 7 (+memory); "account lockout
   ต้องทำยังไง" → 7 (+skill, the lockout runbook matched) — tools appear only when relevant.
   Coding prompt via ask() 0/5-blank (old) → 2-3/3 correct now.
💡 Grounds in Anthropic "Writing tools for agents" (more tools waste cognitive capacity)
   + our own empty-answer evidence. Harness PLUMBING already matches Claude Code; this is
   the "make the MODEL smarter" layer (context/tool engineering). Next candidates: #2
   structured output (Ollama format=json) for routing/classify, #3 model router by difficulty.

---- 2026-06-13 — Shared sessions (user+cwd) + TUI streaming/spinner/layout ----
✅ Session now bound to (user, cwd) — cheng.session_key(user, folder) + session_user(None|User).
   DEFAULT (no flag) auto-binds CLI to its folder+user session; TUI does the SAME →
   CLI & TUI launched from the same folder SHARE one conversation (live-verified: TUI
   loaded a fact the CLI saved). --resume <id> = specific; --continue = latest anywhere;
   /clear = delete THIS folder's session. cwd is used ALWAYS (even in --workspace mode,
   per user). tests/test_session_key.py (6). 249 tests pass.
✅ TUI (cheng_tui.py): now streams tokens (on_token) like the CLI + animated spinner
   (set_interval 0.09s) showing live phase (thinking→running <tool>→writing) + transient
   #live preview that settles into the log; input box layout fixed (margin/breathing room,
   border title "ask", brighter focus). Shares the CLI's session store.
✅ CLI spinner now ANIMATES: cheng._Spinner = bg thread rotating ⠋⠙⠹⠸ on the status line
   (was a static "· thinking…"), lock-guarded so it never writes between clear+output.
💡 Why TUI vs CLI answers differed: (a) temperature 0.2 = non-deterministic wording per
   call (dominant), (b) TUI was non-streaming → went through _language_guard regenerate
   while CLI streamed → now both stream (aligned). Facts identical (same DB/tools).

---- 2026-06-13 — BUG FOUND BY REAL-USAGE TESTING: blank-answer fix ----
🐞 FIXED (real harness bug, mocks didn't catch it): when the model returned EMPTY content
   + no tool call (weak 3B's failure mode when irrelevant tools — memory/skill specs are
   always injected — are in scope), ask() returned '' (the fallback only existed on the
   max-steps path). User saw a BLANK reply. Live repro: a "fix this code" prompt → 0/5
   non-blank via ask(), yet raw _chat(use_tools=False) gave perfect code.
✅ Fix (ai/brain.py): on empty no-tool reply, pop the empty turn + retry once WITHOUT tools
   (clean context) → then _EMPTY_FALLBACK constant (TH+EN) instead of ''. Both the empty
   branch and the max-steps branch now share the fallback → ask() NEVER returns ''.
   tests/test_brain.py +2 (retry-without-tools, persistent-empty→fallback). 243 tests.
✅ AFTER: same prompt 5/5 non-blank, 5/5 contain the correct fix. (3B still adds a verbose
   preamble — model quality, not a harness bug; coder:7b A/B pending slow download.)
💡 PROCESS LESSON (user was right to push): unit tests mock Ollama so they pass while the
   live model returns blanks. Must live-test through the REAL CLI entrypoint. This bug was
   found ONLY by driving real prompts through the real path. eval/compare_models.py added
   (fair A/B: same prompts, same tools-free coding persona, 3b vs coder:7b).
🧱 coder:7b downloading to D: (slow ~360KB/s link, DNS flaky — 1st pull died at 3% w/ DNS
   'no such host', resumed). Run `python -m eval.compare_models` once it lands.

---- 2026-06-13 — Beyond-the-9: @file mentions + token/usage readout ----
✅ cheng.py: expand_mentions(text, base) inlines a user-typed @path's content into the
   prompt (workspace-relative, capped MENTION_MAX=20k, unknown @tokens left alone). Wired
   into answer_turn; shows "⏺ @path loaded into context". tests/test_mentions.py (6).
✅ ai/brain.py: _record_usage captures Ollama prompt_eval_count/eval_count/eval_duration;
   usage_total (calls/prompt/output tokens/eval_ms) + usage_summary (tok/s). /usage panel
   in cheng.py (aggregates team brains via Supervisor.brains()). tests/test_usage.py (5).
   241 tests pass.
🔬 TESTING-RIGOR FINDING (important): my FIRST two live @file tests used a hand-built Brain
   with the WRONG persona (SYSTEM_CHAT monitor + DB tools, or a generic system) → 3B gave
   false-negative "DB_PORT not found" even though the file content was delivered verbatim.
   Testing the REAL integrated path `cheng.py --workspace --no-web --ask "@config.py ..."`
   (SYSTEM_FS persona) → answered "5432" CORRECTLY. LESSON: live-test through the actual
   CLI entrypoint, not hand-assembled components — wrong persona ≠ broken feature. Validates
   the harness thesis: same 3B, wrong persona = garbage, product persona = correct.
📌 Beyond-9 status: @file ✅, token/usage ✅. Remaining (lower value): custom slash cmds,
   plan mode, TodoWrite; multimodal = BLOCKED (qwen2.5 is text-only).

---- 2026-06-13 — Ollama retry/backoff (gap #1c) — ALL ranked gaps now closed ----
✅ ai/brain.py: Brain(retries=2, backoff=0.5). _chat retries TRANSIENT failures
   (httpx.TransportError = connect/read/timeout/protocol, or 5xx = model still loading)
   with exponential backoff (0.5, 1.0…); 4xx and an already-streamed partial are NOT
   retried (can't un-emit tokens → stream retries only while content empty). _is_transient
   + _retry_wait helpers.
✅ tests/test_retry.py (5): transient→succeed w/ backoff schedule, 5xx retried, give-up
   raises after N, 4xx not retried, retries=0 disables.
🐞 FIXED (caught by full suite): sessions "latest" ordering was flaky on Windows' coarse
   clock (microsecond updated_at still tied → rowid tiebreak picked insert order). Replaced
   with a monotonic seq column (MAX(seq)+1 per save) + migration (ALTER add seq, then index
   AFTER so old tables upgrade). latest_session_id/list_sessions order by seq DESC. Solid.
✅ LIVE VERIFIED: happy path unaffected; dead port (127.0.0.1:9) logged "retry 1/2 in 0.3s"
   then "2/2 in 0.6s" then raised OllamaUnavailable. 230 tests pass; flaky tests green 3x.
📌 GAP doc: #1c DONE. ALL ranked priority gaps closed — harness matches Claude Code on the
   core 9. Leftover "beyond the 9" items (TodoWrite, @file, custom slash, plan mode,
   multimodal, token/cost) are lower-value, non-blocking.

---- 2026-06-13 — Diff preview on edit/write (Claude-Code gap #5) ----
✅ ai/fs_tools.py: diff_for(base, name, args) → unified diff a write/edit WOULD make
   (pure: reads, never writes; path-jail applies; flags missing old_string / new file).
   + _unified() helper (difflib).
✅ cheng.py: _confirm → make_confirm(base) factory; for edit_file/write_file it prints a
   colored unified diff (_render_diff: green +, red -, cyan @@, capped 80 lines) before
   the y/N prompt. run_command + other writes unchanged. build_brain wires make_confirm(base).
✅ tests/test_diff_preview.py (8): edit -/+, missing old_string, missing file, no-change,
   new file label, overwrite, path-escape→None, non-preview tool→None. 225 tests pass.
✅ VISUAL VERIFIED: edit shows git-style -PORT=8000/+PORT=9090 with context; new file shows
   @@ -0,0 +1,3 @@ + lines; bad old_string shows a ⚠ warning instead of a misleading diff.
📌 GAP doc: #5 DONE. Remaining ranked: #1c Ollama retry/backoff.

---- 2026-06-13 — REBRAND: JOTARO → CHENG AI ----
✅ Product renamed JOTARO → "CHENG AI" everywhere. Files: jotaro.py→cheng.py,
   jotaro_tui.py→cheng_tui.py, bin/jotaro-*.cmd→bin/cheng-*.cmd (git mv, history kept).
   Commands now: cheng-ai / cheng-mon / cheng-team / cheng-tui. Module imports updated
   (from cheng import ...). 32 files content-rewritten; brand strings → "CHENG AI",
   "JOTARO AI CLI" → "CHENG AI CLI" (no double-AI). GitHub handle JOTARO365 left intact;
   repo path → cheng-ai_cli. 217 tests still pass. PowerShell $PROFILE aliases updated to
   cheng-*. GitHub repo renamed jotaro-ai_cli → cheng-ai_cli + git remote re-pointed.

## CURRENT STATUS (Phase-1 product loop now COMPLETE end-to-end)
🟢 Collector → Rule Engine → REAL AI analysis (ai/escalate.py) + REAL alert dispatch
   (alert/dispatch.py, opt-in/no-op) — verified by sandbox: AI root-cause stored as
   source=ai events, alerts logged (no channel configured = nothing leaves the box). 96 tests.
   alert/dispatch.py = on_alert; ai/escalate.py Analyst.on_ai = on_ai (replaced fake_alert/fake_ai).

---- 2026-06-12 — Skills subsystem + section-level loading ----
✅ ai/skills.py: skill.md runbooks, progressive loading. Front-matter name+description
   injected as the trigger; full body via load_skill on demand. discover_skills reads
   one or many dirs (flat *.md or Claude-style <name>/SKILL.md, rglob) — `~/.claude` finds 65.
   Toggle on/off. cheng --skills DIR / --no-skills + /skills (list/on|off/load a dir).
   Brain auto-loads (default ./skills); Supervisor propagates to specialists.
✅ Section-level loading (context mgmt): split_sections + select_skill_content(skill, query)
   returns whole skill if small, else only keyword-matching section(s) + a TOC. On a real
   43KB / 53-section .claude skill → ~1.7KB (97% less context). Pure Python — NOT 42 C FFI
   (substr/gnl = Python str ops already) and NOT LangGraph (deterministic keyword match). 106 tests.
💡 Standing principle reaffirmed: reuse high-level strategy (section loading, Textual, Open WebUI)
   but NOT primitives (C substr/gnl, hand-built UI) — Python/open-source libs already provide them.

---- 2026-06-13 — Verifier, fan-out, UI polish, Full TUI ----
✅ Verifier (ai/verify.py): deterministic degeneracy check (catches small-model repetition
   meltdown w/o a model call) + critic Brain (grounding). cheng --verify. Also capped skill
   catalog at 30 (loading .claude's 65 into a 3B caused a hallucination loop — real finding).
✅ Fan-out (ai/parallel.py): parallel_map (capped threads) + fan_out_summarize (chunk →
   sub-agents summarize in isolated context → merge = context firewall). cheng /summarize.
   Note: one Ollama serializes inference → win is context, not wall-clock.
✅ UI: slash-command popup menu (SlashCompleter, arrow-selectable) + ❯ prompt + bottom toolbar.
✅ FULL TUI (cheng_tui.py, Textual): status bar + scrollable chat (mouse) + input + worker
   thread (UI never blocks) + ⏺/⎿ in log. monitor v1, reuses backend+memory+skills+commands.
   bin/cheng-tui.cmd. 121 tests.
💡 Q: does the MODEL learn from user data? NO — memory = inject facts into context (weights
   frozen). Correct tool for facts/RAG. Fine-tune (LoRA) = for style/skill, needs GPU (4GB
   can't), risks staleness — wrong tool for facts. Documented, not built.
🔭 Roadmap left: TUI v2 (workspace/team modes, sidebar, streaming-in-log), LLM router,
   cross-specialist memory, fine-tune pipeline design (prod GPU).

---- 2026-06-13 — Configurable pre/post-tool hooks (Claude-Code gap #8) ----
✅ ai/hooks.py: HookRegistry (pre = ALLOW/DENY/MODIFY, post = rewrite result), matched
   by tool-name glob ('*', exact, fnmatch). deny short-circuits, modify chains. Built-in
   dangerous_shell_guard blocks rm -rf / mkfs / dd of=/dev / del /s / Remove-Item -Recurse
   / shutdown / fork-bomb. default_safe_hooks() = pre run_command guard.
✅ ai/brain.py: hooks= param; _execute now wraps _execute_inner with run_pre (deny →
   {"status":"blocked by hook"} fed back to model; modify → swap args) + run_post. No
   hooks = pass-through. Every tool call (model-driven or internal) passes the chain.
✅ cheng.py: default_safe_hooks attached unless --no-hooks; /hooks lists active guards.
✅ tests/test_hooks.py (24): registry semantics, glob scoping, guard block/allow table,
   Brain block/modify/post/passthrough. 217 tests pass.
✅ LIVE VERIFIED: build_brain workspace + default hooks → "rm -rf /" and "Remove-Item
   -Recurse" hard-blocked before the shell dispatcher; /hooks shows the guard.
📌 GAP doc: #8 DONE. Remaining ranked: #5 edit diff-preview, #1c Ollama retry/backoff.

---- 2026-06-13 — Session persistence / resume (Claude-Code gap #6) ----
✅ storage/db.py: sessions table (id, created/updated_at, label, history JSON) +
   save_session (upsert, label sticky, microsecond updated_at so re-save = latest),
   load_session, latest_session_id, list_sessions, delete_session.
✅ cheng.py: --continue (resume latest), --resume <id>, --sessions (list & exit),
   /sessions in REPL, autosave after every non-team turn, /clear starts a NEW session.
   Team mode excluded (per-specialist history, no single thread to resume).
✅ tests/test_sessions.py (7): roundtrip+Thai, missing→None, sticky label, latest tracks
   re-save, list order/limit, delete. 193 tests pass.
✅ LIVE VERIFIED (qwen2.5:3b): launch1 learned "file server=SRV07, Chiang Mai" + autosaved;
   a FRESH Brain loaded the session from SQLite and answered the follow-up correctly
   ("SRV07 อยู่ในสำนักงานเชียงใหม่"). Also `cheng.py --sessions` lists with Thai labels intact.
📌 GAP doc updated: #2 compaction, #1b tool-error, #6 resume all DONE. Next ranked: #8
   configurable hooks, then #5 edit diff-preview, #1c Ollama retry/backoff.

---- 2026-06-13 — Context compaction (Claude-Code gap) ----
✅ ai/brain.py: Brain now self-compacts history. When _history_chars(history) exceeds
   context_budget (default 16k chars ≈ 4k tok), _compact folds the OLDEST turns into one
   model-written summary (SYSTEM_SUMMARIZER), always keeping the system msg + last
   keep_recent_turns (2) user-turns verbatim. _recent_tail starts the kept slice at a
   user boundary so no tool result is orphaned from its call. on_compact(before,after)
   callback. Summarizer falls back to deterministic truncation if Ollama is down.
✅ cheng.py: _on_compact prints "⟳ compacted N → M chars"; wired into all 3 ask() paths.
✅ tests/test_compaction.py (6) + updated test_hardcore (#2 gap now FIXED). 186 tests pass.
✅ LIVE VERIFIED (qwen2.5:3b): forced budget=900 → compaction fired (2011→1885), the
   model summary preserved "print server=SRV01, Bangkok office", and the next question
   was answered CORRECTLY from the folded summary ("SRV01 อยู่ในสำนักงานกรุงเทพ"), clean Thai.
🧱 Ollama models live on D:\ollama-models — serve MUST be started with OLLAMA_MODELS set
   (export 'OLLAMA_MODELS=D:\ollama-models'; mind shell backslash-stripping) or it sees 0 blobs.

## (history) CURRENT STATUS
🟢 In progress : v0.1.0 — collectors + Rule Engine + sandbox + tool server + CHENG AI CLI (34 tests)

---- 2026-06-12 — CHENG AI CLI (terminal tool-calling agent) + live stack up ----
✅ Done:
  - ai/tools.py: single tool registry (5 IT tools in Ollama/OpenAI function-spec) +
    dispatch(name,args,db) with hours/limit clamps. Reused by the CLI agent;
    LangChain-portable (wrap as @tool later).
  - ai/brain.py: Brain = ReAct harness around Ollama /api/chat (tools). HARNESS owns
    the loop (max_steps cap), read-only tools, graceful OllamaUnavailable. Brain takes
    `system=` + `tools=` args → future supervisor can spawn SPECIALIST brains per use case.
  - cheng.py: branded REPL (rich banner + prompt_toolkit), Thai/EN, /help /status
    /clear /exit, live ⚙ tool-call display, + `--ask "Q"` one-shot mode.
  - tests/test_brain.py: mock-Ollama ReAct flow + dispatch + unavailable fallback. 34 pass.
  - LIVE VERIFIED against running Ollama+qwen2.5:3b+seeded DB:
    `cheng.py --ask "PC ไหนปิดอยู่บ้าง"` → model called get_down_nodes → "PC20, PC12 ปิดอยู่".
    `--ask "login fail ใครเยอะสุด"` → get_login_fails → john 6 / nan 2. Tool-calling works on 3B.
💡 Two interfaces now share ONE backend (Ollama + SQLite): Open WebUI (web) and CHENG AI (CLI).
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
  - cheng.py: rewrote UI = professional-retro (SESSION/MODEL/STATUS/TOOLS HUD, dropped
    arcade FIGHTER/PLAYER1/INSERT COIN). Added --workspace [DIR] (bare = cwd) → fs mode with
    interactive y/N confirm for writes. SYSTEM_FS persona added to prompts.py.
  - ai/pydantic_agent.py: PydanticAI runtime (OllamaProvider+OpenAIChatModel) driving the SAME
    fs dispatch; write tools requires_approval=True → native DeferredToolRequests/Results
    approval loop; workspace defaults to cwd. requirements-pydantic.txt (optional extra).
  - tests: test_fs_tools (sandbox/dispatch/gate), test_brain (+language guard), test_pydantic_agent
    (importorskip). 44 pass.
  - LIVE VERIFIED: cheng --workspace read via list_dir; PydanticAI `--ask` read via list_dir.
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
  - cheng.py: --team mode routes each question to a specialist, panel subtitle shows
    which one answered. respond() unifies single/workspace/team. /clear, --ask work in all.
  - tests/test_specialists.py: routing (TH+EN) + tool-subset + build. 53 tests pass.
  - LIVE VERIFIED: `cheng --team --ask "login fail ใครเยอะสุด"` → routed to security →
    get_login_fails → clean Thai answer (john 6 / nan 2), NO Chinese leak.
💡 Brain(system=, tools=subset) carried the whole Phase C with no Brain changes — the
  decoupling paid off. Fewer tools per specialist also helps the 3B pick the right tool.
🔭 GitHub harness Chachamaru127/claude-code-harness evaluated → NOT usable (Claude-only
  dev-workflow harness in Shell/Go, not an embeddable offline-Ollama runtime). Kept our own.
🧱 CHENG AI now has modes: (default) monitor · --workspace [DIR] file assistant w/ write-confirm ·
  --team specialist routing. Three runtimes still: Brain / LangGraph adapter / PydanticAI.

---- 2026-06-12 — Claude-Code-style UI + global alias ----
✅ Done:
  - cheng.py UI restyled to Claude Code / Codex look: rounded welcome panel (box.ROUNDED,
    coral #d97757 accent), ✻ wordmark, ⏺ markers for tool calls, answers as flowing markdown
    (no heavy box), clean muted palette. Replaced the 8-bit arcade theme.
  - PowerShell $PROFILE aliases (CurrentUserAllHosts): cheng-ai (file assistant in CWD),
    cheng-mon (monitor), cheng-team (specialist routing) — guarded block w/ marker so re-run
    is idempotent. `cheng-ai` in any folder = file AI sandboxed to that folder.
  - VERIFIED: 53 tests pass; cheng imports clean; `cheng-ai --ask` run from D:\sandbox\alias_try
    → list_dir → correct answer, clean Thai. No bugs found.

---- 2026-06-12 — Published to GitHub + cross-terminal launchers ----
✅ Done:
  - bin/cheng-ai.cmd / cheng-mon.cmd / cheng-team.cmd: portable launchers (use %~dp0 →
    find cheng.py relative to themselves). Added bin/ to USER PATH → `cheng-ai` works in
    ANY terminal (cmd/PowerShell/pwsh) from any folder (file assistant scoped to cwd).
    NOTE: open a NEW terminal to pick up PATH. (Also kept $PROFILE functions for PS.)
  - README.md written. .gitignore hardened (+.webui_secret_key, /workspace/, sandbox/ws_demo,
    sandbox/alias_try, .claude/settings.local.json).
  - git init + initial commit + PydanticAI-guard commit, pushed to
    https://github.com/JOTARO365/cheng-ai_cli (main). gh auth = JOTARO365. Verified NO
    secrets/db/logs staged.
  - ai/pydantic_agent.py: added @agent.output_validator that strips CJK (reuses ai.brain._CJK)
    → PydanticAI runtime no longer leaks Chinese. All 3 runtimes now language-guarded. 53 tests.
🔭 Remaining roadmap: LLM router (vs keyword), cross-specialist memory, and the big one —
  wire Brain/specialists into the Rule Engine escalation (replace fake_ai) + real alert/dispatch.py
  (Line/Teams/Email). Latter touches live-system + new deps → role.md "ask first".

---- 2026-06-12 — Excel + shell tools + /command fix ----
✅ Done:
  - Verified all CLI slash commands; FOUND+FIXED bug: /help crashed (stale FRAME const from
    the restyle) → routed via pure dispatch_command() (+13 headless tests, prompt_toolkit
    can't run piped on Windows).
  - ai/excel_tools.py (openpyxl): excel_list_sheets/excel_read free; excel_write_cell/
    excel_append_row/excel_create confirmed. Shares fs path-jail. EXCEL_WRITE_TOOLS.
  - ai/shell_tools.py: run_command runs in workspace (bash if present, else OS shell),
    ALWAYS confirmed, timeout + output capture/truncate. _confirm shows FULL command.
  - cheng --workspace now COMBINES fs + excel + shell (route excel_*→excel, run_command→shell,
    else fs) behind one path-jail + permission gate. SYSTEM_FS updated. 77 tests pass. Pushed.
🐞 Live finding (3B reasoning, not a tool bug): asked "who's in HR", model passed sheet="HR"
  (a dept value) instead of reading rows of the only sheet → wrong answer. excel_read itself
  is correct (unit-tested). Prod 14b expected to reason better. Shell/excel writes are
  confirm-gated (gate unit-tested); not live-driven (would block on y/N non-interactively).

---- 2026-06-12 — Eval harness + result (harness vs model size) ----
✅ Done: eval/cases.py (seeded fixture + 8 IT Q&A + ground-truth keywords + expected tool +
  pure scorer) + eval/run_eval.py (FACT + TOOL accuracy; --bare = no-tools comparison; --model).
  +2 scorer tests (79 total). Pushed.
📊 LIVE RESULT (qwen2.5:3b, 8 cases):
  - HARNESSED: fact 8/8 (100%), tool-call 7/8 (87%)
  - BARE (no tools): fact 0/8 (0%)  → harness lift = +100 points on fact-accuracy
  KEY INSIGHT: on data Q&A a bare model scores 0% at ANY size (no DB access) → the HARNESS
  (tools) is the enabler, not parameter count. Size only shows up in tool-SELECTION (the 1/8
  miss). So "3B+harness ≈ N B" has no single answer: fact-accuracy ≈ big model; planning ≈ 3B.

---- 2026-06-12 — Streaming/UX + Excel specialist + Memory (learn from user) ----
✅ Streaming: Brain on_token (Ollama stream=true) → cheng streams tokens (CJK-stripped),
  ⏺ tool / ⎿ result lines, transient "· thinking/running…" status, /model (list+switch),
  read-only grep/glob (find_files/search_text). UI = Claude-Code style.
✅ Excel specialist: smart read-only tools (excel_find_rows by column value, excel_aggregate
  sum/avg/min/max/count, excel_read_range, header-aware excel_read) — pushes filtering/math
  into code. SYSTEM_FS Excel procedure. eval --excel. RESULT: tool-selection 0→100% (the
  sheet=HR miss FIXED); fact 25% (mostly scorer number-format artifact + 3B phrasing).
✅ Memory subsystem (learn from user across sessions): db memory table + add/search/recent/
  forget; remember/recall tools merged into EVERY Brain (handled in _execute); new_history()
  injects recent memories into the system prompt; cheng /remember + /memory. Learning lives
  in the harness store, not the frozen model. LIVE: stored "SRV1-FILE is print server" →
  recalled correctly next run. 91 tests. Pushed (2d7aa57).
⏳ STILL PENDING: item 2 product integration (specialist→Rule Engine escalation replacing
  fake_ai + real alert/dispatch.py Line/Teams/Email, opt-in) — touches live-system/deps.

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
