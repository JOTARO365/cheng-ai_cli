# Claude's Role & Boundaries — SME IT Agent (ai-agent-cli)

This project watches a REAL company's Windows AD network. Mistakes here can lock
out staff, leak credentials, or spam IT with false alerts. Act conservatively.

## ✅ Free to do (no need to ask)
- Bug fixes in collectors, rule engine, CLI, storage
- Add logging, comments, type hints, docstrings
- Improve the chat CLI (rich/prompt_toolkit) UX
- Write & run tests (pytest), refactor for readability
- Tune wording of alert messages and AI prompts

## ⚠️ Ask first
- Changing any Rule Engine threshold in engine/thresholds.py
  (login-fail counts, offline windows) — these change who gets paged
- Changing the SQLite schema / running migrations on existing data
- Changing public behavior of the chat commands
- Adding a new external dependency
- Switching the Ollama model or changing its system prompt materially
- Anything that connects out to the network beyond the on-prem LAN

## ⛔ Never do (Phase 1 hard rules)
- NO auto-fix / auto-remediation of any kind (no unlock, no restart, no AD writes).
  The system only READS, analyzes, and ALERTS. (Auto-fix is Phase 3, gated behind
  explicit IT confirmation — not now.)
- NO internet calls. The system is offline by design; the only outbound traffic is
  the configured on-prem alert channels (Line/Teams/Email relay).
- NEVER send company data, event logs, or user info to any cloud/LLM API.
  The AI is LOCAL Ollama only.
- NO destructive AD/LDAP operations. LDAP is READ-ONLY in this project.
- NEVER commit secrets (.env, LDAP_BIND_PASS, alert tokens, *.db).

## When unsure
Consult the live-system-rollout-safety skill before changing detection logic or
rolling to a new site. When in doubt, prefer "log + ask IT" over acting.
