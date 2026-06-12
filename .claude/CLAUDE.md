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
A 100% offline (Ollama) CLI "AI IT assistant" that monitors a Windows AD / on-prem
network and alerts IT *before* users complain. Phase 1 = monitor + alert only,
NO auto-fix, NO internet, data never leaves the company.

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
The PRODUCT itself stays offline; MCP is a dev-time convenience only.
