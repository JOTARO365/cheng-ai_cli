# JOTARO CLI vs Claude Code — harness gap analysis

What a real agent harness provides (the "9 things"), and where JOTARO stands today.
Scored against Claude Code as the reference harness. Legend: ✅ have · ◑ partial · ✗ missing.

| # | Harness capability | Claude Code | JOTARO | Notes / gap |
|---|---|---|---|---|
| 1 | **Loop / stop condition** | ✅ | ✅ | `max_steps` cap (6). Loop is code-owned (ReAct). |
| 1b| ↳ tool-error recovery | ✅ | ◑ | Built-in dispatchers catch their own errors → fed back as `{error}`. But the loop does **not** wrap `_execute`, so a *raising* tool (buggy MCP/custom) crashes the turn. |
| 1c| ↳ network retry/backoff | ✅ | ✗ | One Ollama failure → `OllamaUnavailable`, no retry/backoff. |
| 2 | **Context management** (compaction) | ✅ auto-compact | ✗ | **Biggest gap.** History grows unbounded; no token budget, no summarize-old-turns. Long sessions will eventually overflow the model context. (We *do* have `fan_out_summarize` — but for files, not the conversation.) |
| 3 | **Tool & skill registry** | ✅ | ✅ | Tools + progressive-loading `SKILL.md` (`find_skill`/`load_skill`), per-skill toggle. |
| 4 | **Permission gating** | ✅ rules + remember | ◑ | `confirm_tools` + `confirm()` y/N per call. No "always allow", no allow/deny rule config, no per-path granularity. |
| 5 | **Sub-agent splitting** | ✅ Task tool | ◑ | `fan_out_summarize` (file chunks) + specialist routing. No general "spawn a sub-agent with its own context, return a result" primitive. |
| 6 | **Session persistence / resume** | ✅ `--continue/--resume` | ✗ | History is in-memory only; quitting loses the conversation. No resume. |
| 7 | **System prompt + caching** | ✅ prompt cache | ◑ | System prompt yes; prompt caching is N/A for Ollama. Tool specs rebuilt each call (cheap). |
| 8 | **Lifecycle hooks** (pre/post tool) | ✅ configurable | ◑ | `on_tool`/`on_result` are *display* callbacks only — can't block/modify a call. No user-config hooks (PreToolUse/PostToolUse/Stop). |
| 9 | **Safety / sandbox** | ✅ | ✅ | Path-jail on fs tools (traversal/abs/symlink blocked), confirm gate on writes+shell, web opt-out, offline monitor. Shell is confirm-not-sandbox (documented). |

## Claude Code features beyond the 9
| Feature | JOTARO | Note |
|---|---|---|
| Conversation auto-compact | ✗ | see #2 — the priority gap |
| Session resume (`--continue`) | ✗ | see #6 |
| Configurable hooks | ✗ | see #8 |
| TodoWrite / task tracking | ✗ | no in-agent task list |
| Diff preview before edit | ◑ | `edit_file` confirms y/N but shows args, not a colored diff |
| `@file` mentions | ✗ | model reads files via `read_file` tool instead |
| Custom slash commands | ✗ | slash set is fixed in code |
| Plan mode | ✗ | — |
| Image / multimodal input | ✗ | text model (qwen2.5) |
| Token / cost readout | ✗ | no usage accounting |
| MCP servers | ✅ | sync bridge over the MCP SDK |
| Streaming output | ✅ | NDJSON token streaming |
| Memory across sessions | ✅ | SQLite `remember`/`recall` (Claude Code uses CLAUDE.md/memory files) |
| Username/password auth | ✅ | **JOTARO has this; Claude Code does not** (it's a single-user CLI) |

## What JOTARO already matches or beats
- Real code-owned ReAct loop with a hard stop — the thing AutoGPT lacked.
- Path sandbox + per-write confirmation — solid safety floor.
- Progressive skill loading + per-skill toggle.
- Persistent memory + multi-user login (beyond Claude Code's scope).
- Hybrid runtimes (built-in / LangGraph / PydanticAI) over the same tools.
- Anti-hallucination: verifier sub-agent + deterministic degeneracy detector + auto web fallback.

## Priority gaps (ranked)
1. **Conversation context compaction (#2)** — without it, long sessions overflow. *Highest value.*
2. **Tool-error isolation in the loop (#1b)** — one buggy tool shouldn't kill the turn. *Cheap, high value.*
3. **Session persistence / resume (#6)** — quality-of-life; reuse the SQLite store.
4. **Configurable hooks (#8)** — pre/post-tool guard points (e.g. block `rm -rf`).
5. **Diff preview on edit (#5/UX)** — show a real diff in the confirm prompt.

> Verdict: JOTARO is a *genuine* harness (not a chat wrapper) and matches Claude Code on
> loop/registry/sandbox/permission, and exceeds it on memory + multi-user auth. The
> real missing modules are **context compaction**, **session resume**, **hook config**,
> and **tool-error isolation** — see `tests/test_hardcore.py` for the empirical probes
> and `eval/prod_compare.py` for the live end-to-end scenarios.
