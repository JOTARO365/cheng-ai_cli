================================================================
QUICKREF — SME IT Agent (ai-agent-cli)
================================================================
Updated: 2026-06-10

## OVERVIEW
CLI AI IT Agent for SMEs (30–200 staff, 1–3 IT people). It monitors a Windows
Active Directory / on-prem network, filters events through a Rule Engine to save
resources, escalates only the interesting ones to a LOCAL LLM (Ollama) for root-cause
analysis, lets IT chat with the system in natural Thai/English, and fires alerts
(Line / Teams / Email) so IT learns about problems before users do.
Everything runs offline; no data leaves the company. Phase 1 = monitor + alert only.

## MODEL SIZING — dev vs prod
The same code runs any model; just change `OLLAMA_MODEL` in `.env` (no code change).
| Env | Model | Why |
|---|---|---|
| **dev** (this machine: 8GB RAM, RTX 3050 4GB VRAM) | **qwen2.5:3b** (or llama3.2:3b) | ~2.3GB Q4, fits in 4GB VRAM, fast enough to test the full flow |
| **prod** (spec: 16GB+ RAM) | **qwen2.5:14b** (or llama3.1:8b) | the designed model; needs ~9–10GB, won't run on the dev box |
Rule: dev hardware caps out at ~7–8B (RAM-bound). Do NOT pull 14B on an 8GB box.
Since the Rule Engine filters before the AI, a 3B model is fine to validate the
pipeline; swap to 14B on the real deployment target.

## REQUIRED ENVIRONMENT VARIABLES (.env)
| Var | Purpose | Example |
|---|---|---|
| OLLAMA_HOST        | Local Ollama endpoint                | http://127.0.0.1:11434 |
| OLLAMA_MODEL       | Model to use (dev vs prod, see below)| qwen2.5:3b (dev) / qwen2.5:14b (prod) |
| AD_DOMAIN          | Windows AD domain                    | corp.local |
| LDAP_SERVER        | Domain controller for ldap3          | ldap://dc01.corp.local |
| LDAP_BIND_USER     | Service account for LDAP queries     | CORP\svc-itagent |
| LDAP_BIND_PASS     | Service account password (keep safe) | (secret) |
| PING_INTERVAL_SEC  | Node ping cadence                    | 45 |
| DB_PATH            | SQLite file                          | ./data/itagent.db |
| ALERT_LINE_TOKEN   | Line Notify token (optional)         | (secret) |
| ALERT_TEAMS_WEBHOOK| Teams incoming webhook (optional)    | https://... |
| ALERT_EMAIL_SMTP   | SMTP host for email alerts (optional)| smtp.corp.local |

## FILE STRUCTURE (target layout)
| Path | Purpose |
|---|---|
| main.py                     | CLI entrypoint (chat loop + start monitors) |
| collectors/eventlog.py      | Read Windows Event Log (4625 login-fail, 4740 lockout) via pywin32 |
| collectors/ping.py          | Ping every node every PING_INTERVAL_SEC |
| collectors/wmi_status.py    | WMI/WinRM: PC + critical-service status |
| collectors/ldap_query.py    | LDAP/AD user lookups via ldap3 |
| engine/rules.py             | Rule Engine — filter/escalate BEFORE hitting the AI |
| engine/thresholds.py        | Tunable thresholds (login-fail counts, offline windows) |
| ai/brain.py                 | Ollama client — root-cause analysis + chat answers |
| ai/prompts.py               | System prompts / templates for the LLM |
| alert/dispatch.py           | Send alerts → Line / Teams / Email |
| cli/chat.py                 | prompt_toolkit chat UI + rich rendering |
| storage/db.py               | SQLite schema + read/write (events, alerts, nodes) |
| config.py                   | Load .env / settings |
| data/itagent.db             | SQLite store (gitignored) |

## SYSTEM FLOW
```
                       ┌─────────────────────────────────────────┐
                       │              COLLECTORS                  │
   Windows AD / LAN →  │ eventlog | ping | wmi_status | ldap      │
                       └───────────────────┬─────────────────────┘
                                           │ raw events
                                           ▼
                       ┌─────────────────────────────────────────┐
                       │            RULE ENGINE (harness)         │
                       │  login-fail 1-2  → log only              │
                       │  login-fail 3+   → send to AI            │
                       │  login-fail 5+   → ALERT now (skip AI)   │
                       │  node off <2m    → wait                  │
                       │  node off >5m    → ALERT (work hours)    │
                       │  service down    → ALERT + AI impact     │
                       └─────────┬───────────────────┬───────────┘
                        escalate │                   │ alert
                                 ▼                   ▼
                       ┌──────────────────┐   ┌──────────────┐
                       │ OLLAMA AI BRAIN  │   │ ALERT ENGINE │
                       │ root-cause /     │   │ Line / Teams │
                       │ chat answers     │   │ Email        │
                       └────────┬─────────┘   └──────────────┘
                                │ findings           ▲
                                └────────────────────┘
                                 ▲
                   IT admin ──── │ Chat CLI (rich + prompt_toolkit)
                   "PC ไหนปิดอยู่?" 
```

## COMMON COMMANDS
```powershell
# setup
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# pull the local model (one time) — dev box:
ollama pull qwen2.5:3b
# production box (16GB+ RAM):  ollama pull qwen2.5:14b

# run
python main.py

# run only the monitors (no chat) — for the Windows service / scheduled task
python main.py --monitor-only

# tests
pytest -q
```

## KNOWN ISSUES & GOTCHAS
- pywin32 Event Log reads need the agent to run as a user with the
  "Manage auditing and security log" right (or local admin) — see docs/setup.md.
- ldap3 over plain LDAP sends the bind password in clear text; use LDAPS in prod.
- Ollama on CPU-only boxes is slow — the Rule Engine MUST filter aggressively so
  the AI is only called on genuinely interesting events.
- Model must match the box: dev (8GB RAM / 4GB VRAM) → 3B; prod (16GB+) → 14B.
  Pulling 14B on an 8GB machine will OOM/thrash. See the "MODEL SIZING" section.
- Thai output in the Windows console needs UTF-8 (chcp 65001) — see the
  powershell-windows-encoding skill.
- SQLite is single-writer; keep all writes funneled through storage/db.py.
- This is a LIVE system watching real infra — see live-system-rollout-safety before
  changing thresholds or rolling out to a new site.
