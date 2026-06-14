# Claude's Role & Boundaries — SME IT Agent (ai-agent-cli)

This project watches a REAL company's Windows AD network. Mistakes here can lock
out staff, leak credentials, or spam IT with false alerts. Act conservatively.

## ✅ Free to do (no need to ask)
- Bug fixes in collectors, rule engine, CLI, storage
- Add logging, comments, type hints, docstrings
- Improve the chat CLI (rich/prompt_toolkit) UX
- Write & run tests (pytest), refactor for readability
- Tune wording of alert messages and AI prompts

## 🌐 Online policy (UPDATED 2026-06-14 — was "100% offline")
The product is **online-capable / hybrid** now: it MAY use the internet, cloud LLM
APIs, web search, and online tools when that gives the best result. Local Ollama is
still the default and the offline fallback (works with no network), but "offline-only"
is no longer a hard rule. Be deliberate about *what* leaves the network — see below.

## ⚠️ Ask first
- Changing any Rule Engine threshold in engine/thresholds.py
  (login-fail counts, offline windows) — these change who gets paged
- Changing the SQLite schema / running migrations on existing data
- Changing public behavior of the chat commands
- Adding a new external dependency
- Switching the model or changing its system prompt materially
- Routing SENSITIVE company data (raw event logs, credentials, PII) to an EXTERNAL
  service — online is allowed, but confirm before sending sensitive payloads out

## ⛔ Never do (hard rules)
- NO auto-fix / auto-remediation of any kind (no unlock, no restart, no AD writes).
  The system only READS, analyzes, and ALERTS. (Auto-fix is Phase 3, gated behind
  explicit IT confirmation — not now.)
- NO destructive AD/LDAP operations. LDAP is READ-ONLY in this project.
- NEVER leak or transmit SECRETS (passwords, LDAP_BIND_PASS, API keys, alert tokens)
  to any model, tool, log, or external service — online or not.
- NEVER commit secrets (.env, LDAP_BIND_PASS, alert tokens, *.db).

## When unsure
Consult the live-system-rollout-safety skill before changing detection logic or
rolling to a new site. When in doubt, prefer "log + ask IT" over acting.
