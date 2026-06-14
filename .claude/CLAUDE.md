================================================================
CLAUDE CONTEXT — SME IT Agent (ai-agent-cli)
================================================================
Updated: 2026-06-10 | Version: v0.1.0

## STARTUP — read in order each session
1. .claude/context/QUICKREF.md
2. .claude/context/continue.md
3. .claude/roles/role.md       (rules — read before touching code)
4. .claude/skills/skill.md     (conventions — read before writing code)

Do NOT read large source files unless necessary — use QUICKREF.
Do NOT change the rule-engine thresholds or AD/Event-Log logic without
understanding the full Collector → Rule Engine → AI → Alert flow.

## PROJECT IN ONE LINE
CHENG AI — a terminal AI agent (monitor · workspace · web · team). It started as a
local-first IT monitor for a Windows AD / on-prem network (alert IT *before* users
complain) and is now **online-capable / hybrid**: local Ollama by default, but it MAY
use the internet / cloud models / online tools for the best result (policy updated
2026-06-14 — see roles/role.md). Phase 1 core = monitor + alert only, NO auto-fix.

## CONTINUE.MD UPDATE RULES
Update .claude/context/continue.md whenever you:
- Edit any code
- Find a bug
- Fix a bug
- Change approach or architecture
- Adjust a rule-engine threshold or an Ollama prompt

## SKILLS THIS PROJECT USES (invoke only when applicable)
- agent-harness-and-skills    → designing the Rule Engine / harness + AI loop
- live-system-rollout-safety  → anything that touches real AD / prod PCs
- powershell-windows-encoding → .ps1 helpers + Thai/non-ASCII CLI output
(42-* skills are for 42 School C projects — not used here.)

## MCP CONFIG
Configured in .claude/settings.json:
- filesystem → browse/edit project files during dev
- sqlite     → inspect the local event/alert store during dev/debug
MCP also lets the product reach external tools at runtime (online-capable now).
