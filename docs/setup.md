# Setup — SME IT Agent (ai-agent-cli)

## Minimum spec (IT PC / Windows Server)
- RAM: 16GB (32GB recommended)
- Storage: SSD, 20GB+ free
- GPU: not required (CPU mode works, slower)
- OS: Windows 10/11 or Windows Server

## Model sizing — dev vs prod
Pick the model to match the hardware. The code is identical; only `OLLAMA_MODEL`
in `.env` changes.
| Environment | Hardware | Model | Notes |
|---|---|---|---|
| **dev**  | 8GB RAM, 4GB VRAM (e.g. RTX 3050 Laptop) | **qwen2.5:3b** (or llama3.2:3b) | ~2.3GB Q4, fits in 4GB VRAM, enough to test the full flow. Max this box can run is ~7–8B (RAM-bound). |
| **prod** | 16GB+ RAM | **qwen2.5:14b** (or llama3.1:8b) | the designed model; needs ~9–10GB. Won't run on an 8GB box. |
⚠️ Do NOT `ollama pull qwen2.5:14b` on an 8GB machine — it will OOM/thrash.
Because the Rule Engine filters events before the AI, a 3B model is fine for dev.

> **Architecture (Phase 1 = chatbot-first).** The chat UI is **Open WebUI**
> (open-source, offline). It talks to **Ollama** for the model and reaches our live
> monitoring data through a small **FastAPI tool server** (`webtools/server.py`,
> started by `python main.py`). So three local processes:
> `Ollama  ←  Open WebUI  →  our tool server (reads SQLite)`.

## 1. Install Ollama + pull a model
On this dev box **install to D:** (C: is space-tight) and keep models on D: too.
```powershell
# Models live on D: — set BEFORE pulling (one-time, user-level):
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS','D:\ollama-models','User')

# Silent install to D:\Ollama (will prompt UAC):
D:\Ollama\OllamaSetup.exe /SILENT /DIR="D:\Ollama"

ollama pull qwen2.5:3b        # DEV box (8GB RAM / 4GB VRAM) → ~2.3GB on D:
# ollama pull qwen2.5:14b     # PROD box (16GB+ RAM)  — or llama3.1:8b
ollama list                   # verify the model is present
```

## 2. Python environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Configure .env
Copy `.env.example` → `.env` and fill in (see QUICKREF for the full table):
```
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:3b          # dev box; use qwen2.5:14b on a 16GB+ prod box
AD_DOMAIN=corp.local
LDAP_SERVER=ldap://dc01.corp.local
LDAP_BIND_USER=CORP\svc-itagent
LDAP_BIND_PASS=...           # use a least-privilege, read-only service account
PING_INTERVAL_SEC=45
DB_PATH=./data/itagent.db
ALERT_LINE_TOKEN=...         # optional
ALERT_TEAMS_WEBHOOK=...      # optional
ALERT_EMAIL_SMTP=...         # optional
```

## 4. Windows permissions
- The account running the agent needs the **"Manage auditing and security log"**
  right (or local admin) to read Event IDs 4625 / 4740 from the Security log.
- For WMI/WinRM against other PCs, enable WinRM and grant the service account remote
  WMI access. Prefer **LDAPS** for AD queries.

## 5. Console encoding (Thai output)
```powershell
chcp 65001        # UTF-8, so Thai text in the CLI renders correctly
```
See the `powershell-windows-encoding` skill if you still see garbled characters.

## 6. Install Open WebUI (the chat UI)
Open WebUI's Python deps are large; on this box with little free space on C:, put
them in a **venv on D:** so C: isn't filled.
```powershell
python -m venv D:\openwebui-venv
D:\openwebui-venv\Scripts\Activate.ps1
pip install open-webui
$env:DATA_DIR = "D:\openwebui-data"          # keep its DB/uploads on D: too
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
open-webui serve --port 8080                  # then open http://127.0.0.1:8080
```
First launch creates a local admin account (offline; nothing leaves the machine).

## 7. Run our tool server + seed demo data
In the **project venv** (separate terminal):
```powershell
.\.venv\Scripts\Activate.ps1
python -m sandbox.seed_demo    # optional: demo nodes/alerts so there's data to chat about
python main.py                 # serves IT-context tools at http://127.0.0.1:8000
```

## 8. Wire Open WebUI → Ollama + our tools  (one-time, in the browser)
1. **Model**: Open WebUI auto-detects Ollama models. Pick `qwen2.5:3b`.
2. **System prompt**: Settings → (model) → set the System Prompt to the contents of
   `ai/prompts.py` `SYSTEM_CHAT`. Dump it with: `python -m ai.prompts`.
3. **Tools**: Settings → **Tools** → add an **OpenAPI tool server** with URL
   `http://127.0.0.1:8000` — it auto-discovers the 5 tools from `/openapi.json`.
   Enable the tools for your model.
4. Ask: **"PC ไหนปิดอยู่บ้าง"**, **"login fail วันนี้กี่ครั้ง"**, **"สถานะระบบตอนนี้เป็นยังไง"**.
   The model should call a tool and answer from real data.

## 9. Run as a service (DevOps)
Host `python main.py` (the tool server) and `open-webui serve` under Task Scheduler
(at startup) or NSSM, with auto-restart on failure. Keep logs in ./logs/ with
rotation. See the devops-engineer agent for the runbook.

## Troubleshooting
- **Ollama slow / timing out:** expected on CPU; the Rule Engine should be filtering
  most events out before the AI is called.
- **Can't read Security log:** missing audit right — see step 4.
- **Garbled Thai:** see step 5.
- **Open WebUI can't see the tools:** confirm `python main.py` is running and
  `http://127.0.0.1:8000/openapi.json` loads in a browser; the tool server must be
  reachable from wherever Open WebUI runs. (If Open WebUI is in Docker, use the host
  IP, not `127.0.0.1`.)
- **Model answers without calling a tool / makes data up:** make sure the SYSTEM_CHAT
  prompt is set and the tools are enabled for that model. Small models sometimes need
  the question phrased toward a tool ("check which PCs are down").
- **C: drive fills up:** Open WebUI + deps are large — install it in the D: venv
  (step 6) and set `DATA_DIR`/`OLLAMA_MODELS` to D: as shown.
