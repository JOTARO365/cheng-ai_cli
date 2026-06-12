# Code Conventions — SME IT Agent (ai-agent-cli)

Stack: Python 3.11+ · Ollama · pywin32 / ldap3 / wmi · rich + prompt_toolkit · SQLite

## SKILLS THIS PROJECT USES
Invoke only when the situation matches:
- **agent-harness-and-skills** — when designing/changing the Rule Engine (the
  "harness"), the escalate-to-AI loop, or tool/prompt structure for the Ollama brain.
- **live-system-rollout-safety** — when touching anything that reads real AD / prod
  PCs, or before changing thresholds / rolling out to a new site.
- **powershell-windows-encoding** — when writing .ps1 helpers or when the CLI prints
  Thai/non-ASCII and the Windows console garbles it.

## CODE STYLE
- PEP 8, 4-space indent, `snake_case` functions, `PascalCase` classes.
- Type hints on all public functions. Prefer dataclasses for event/alert records.
- One responsibility per module (collectors/ vs engine/ vs ai/ vs alert/ vs cli/).
- Keep thresholds and magic numbers in engine/thresholds.py — never inline them.
- Format with `black`; lint with `ruff`.

## ERROR HANDLING
- Collectors must NEVER crash the agent. Wrap each collector tick in try/except,
  log the error, and keep the loop alive — a flaky PC must not kill monitoring.
- Network/LDAP/WMI calls get explicit timeouts; on timeout, mark node "unknown",
  don't assume "down".
- Surface fatal config errors (missing OLLAMA_HOST, bad LDAP creds) loudly at startup,
  not silently at runtime.

## LOGGING
- Use Python `logging` with a rotating file handler under ./logs/.
- Levels: DEBUG=raw events, INFO=state changes, WARNING=rule escalation,
  ERROR=collector/AI failure.
- Never log secrets or full password fields. Mask user PII where not needed.

## STORAGE
- All DB access through storage/db.py only (SQLite is single-writer).
- Use parameterized queries — never string-format SQL.

## AI / OLLAMA
- All LLM access through ai/brain.py. Prompts live in ai/prompts.py.
- The Rule Engine decides WHETHER to call the AI; brain.py just calls it.
- Keep prompts short and structured — CPU inference is slow; send only the event
  context the model needs, not raw dumps.
- Always handle the case where Ollama is unreachable: fall back to rule-only alerts.

## TESTING
- pytest. Mock pywin32/ldap3/wmi/Ollama — tests must run on any machine, offline.
- Cover the Rule Engine thresholds with table-driven tests (they decide who's paged).

## CLI
- rich for rendering, prompt_toolkit for the input loop.
- Support Thai and English questions. Keep answers concise and actionable.

## SECURITY DEFAULTS
- LDAP is READ-ONLY. No AD writes anywhere in Phase 1.
- Secrets via .env only; .env, *.db, logs/ are gitignored.
