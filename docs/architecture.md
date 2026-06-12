# Architecture — SME IT Agent (ai-agent-cli)

## Goal
Turn IT from **reactive → proactive**: a 100% offline CLI agent that watches a
Windows AD / on-prem network and alerts IT before users complain. Phase 1 is
monitor + alert only — no auto-fix, no internet.

## Components
```
collectors/   → gather raw signals from the environment
engine/       → Rule Engine: filter, decide, escalate (the "harness")
ai/           → Ollama brain: root-cause analysis + chat answers (local)
alert/        → push notifications to Line / Teams / Email
cli/          → chat interface for IT (rich + prompt_toolkit)
storage/      → SQLite persistence (events, nodes, alerts)
```

## Data flow
1. **Collectors** poll the environment:
   - eventlog: Windows Event Log — 4625 (login fail), 4740 (lockout) via pywin32
   - ping: every node every 30–60s
   - wmi_status: PC + critical-service state via WMI/WinRM
   - ldap_query: AD user info via ldap3 (read-only)
2. **Rule Engine** filters BEFORE the AI to save resources:
   | Signal | Action |
   |---|---|
   | login-fail 1–2 | log only |
   | login-fail 3+  | send to AI for pattern analysis |
   | login-fail 5+  | ALERT immediately (skip AI) |
   | node offline <2m | wait |
   | node offline >5m (work hours) | ALERT |
   | service down | ALERT now + AI impact assessment |
3. **AI Brain (Ollama)** analyzes escalated events and answers IT's chat questions —
   local model only (qwen2.5:14b or llama3.1:8b), offline.
4. **Alert Engine** delivers context-rich alerts (who/when/how-many/IP).
5. **Chat CLI** lets IT query current state in natural Thai/English.

## Key decisions
- **Local-only AI (Ollama):** privacy/compliance — company data never leaves the LAN.
- **Rule Engine before AI:** CPU inference is slow; the harness must filter hard so
  the model is only used where it adds value. (See agent-harness-and-skills.)
- **SQLite:** zero extra install; single-writer, funnel writes through storage/db.py.
- **Tunable thresholds:** all in engine/thresholds.py so each site can adjust without
  code changes. Changing them changes who gets paged → treat as live-system change.
- **No auto-fix in Phase 1:** read + alert only; remediation is deferred to Phase 3
  behind explicit IT confirmation.

## Phase plan
- **P1 (MVP ~2wk):** Collector + Rule Engine + Chat CLI + basic Alert
- **P2:** ServiceWatcher + dashboard summary + all alert channels
- **P3:** Auto-remediation w/ IT confirm in chat (e.g. unlock account)
- **P4:** Installer, multi-site, web dashboard (SaaS)

## Non-goals (Phase 1)
No auto-fix · no internet · no data egress · no Azure AD.
