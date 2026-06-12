# Agent Harness — contract & reuse

This is the layer around the local model that turns it into a reliable agent. It is
**deterministic code**, not prompt text: the harness owns the loop, decides when to
call which tool, and feeds results back. (Same kind of thing as Claude Code — a
narrower, hand-built version. See the comparison at the bottom.)

The harness is built from **three decoupled pieces**, so it ports cleanly to other
runtimes (we ship our own lightweight loop *and* a LangChain/LangGraph adapter over
the exact same pieces):

| Piece | File | What it is |
|---|---|---|
| **Tool registry** | `ai/tools.py` | `TOOL_SPECS` (framework-neutral function specs) + `dispatch(name, args, db)`. READ-ONLY. |
| **Persona / rules** | `ai/prompts.py` | `SYSTEM_CHAT` (the agent's instructions + guardrails). |
| **The loop** | `ai/brain.py` | `Brain` — a ReAct loop over Ollama. Owns the loop + stop condition. |
| State / tool backend | `storage/db.py` | the SQLite store the tools read. |

## The contract

A harness here = `(system prompt) + (tool set) + (loop policy)` over a model + a data
backend. `Brain` takes all of these as arguments, so the same class is reused for
different agents (this is what Phase C — specialist agents — builds on):

```python
from ai.brain import Brain
from ai.prompts import SYSTEM_CHAT
from ai.tools import TOOL_SPECS

brain = Brain(
    host="http://127.0.0.1:11434",
    model="qwen2.5:3b",
    db=db,
    system=SYSTEM_CHAT,        # swap persona per agent
    tools=TOOL_SPECS,          # or a SUBSET → a specialist that only sees some tools
    max_steps=5,               # stop condition (loop policy)
)
history = brain.new_history()
answer = brain.ask(history, "PC ไหนปิดอยู่บ้าง", on_tool=lambda n, a: ...)
```

Loop (ReAct), owned by the harness — not the model:

```
ask(question)
  └─ append user msg
     repeat up to max_steps:
        model = POST /api/chat (messages, tools)
        if model returns tool_calls:
            for each: dispatch(name, args, db) → append tool result → loop
        else:
            return model's answer
```

**Invariants the harness enforces (the guardrails a bare LLM lacks):**
- **Stop condition** — `max_steps` caps the loop so it can't spin forever.
- **Read-only safety** — every tool in `dispatch` only reads. There is no write/exec
  tool, so no permission gate or sandbox is needed in Phase 1. (When Phase 3 adds an
  action that writes, it MUST go behind explicit IT confirmation — add a permission
  step then; do not add write tools to this registry silently.)
- **Grounding** — `SYSTEM_CHAT` tells the model to answer only from tool results.

## Reusing it in another system

- **Different data, same shape:** point `Database` at another store and the tools
  follow. Add a tool = add one `TOOL_SPECS` entry + one `dispatch` branch.
- **Different model/provider:** change `host`/`model`. The loop is provider-shaped
  around the Ollama `/api/chat` `tools` format (OpenAI-compatible).
- **Inside a LangChain/LangGraph app:** use `ai/langchain_adapter.py` — it builds
  LangChain tools from the SAME `TOOL_SPECS`/`dispatch` and a LangGraph ReAct agent
  with the SAME `SYSTEM_CHAT`. Install the extra: `pip install -r requirements-langchain.txt`.

### Runtime choice (Hybrid)

| | Our `Brain` (default) | LangChain/LangGraph adapter |
|---|---|---|
| Deps | `httpx` only — offline, light | heavy tree (install only when a target needs it) |
| Loop | our `run_loop()` (Level 3) | framework-provided (Level 2) |
| Memory / persistence | in-RAM history | `checkpointer` (MemorySaver / SQLite) across turns & threads |
| Use it when | shipping to SME boxes | integrating into a larger LangChain/LangGraph system |

Both consume the identical tool registry + system prompt, so behavior matches; you
pick the runtime per deployment.

## How complete is this harness? (vs a full one like Claude Code)

Has: ✅ loop+stop · ✅ tool registry · ✅ system prompt · ✅ tool exec/feed-back.
Not yet (by design for Phase 1): ❌ permission gating · ❌ context compaction ·
❌ sub-agent splitting (→ Phase C) · ❌ session persistence (→ LangGraph checkpointer)
· ❌ lifecycle hooks/skills/MCP · ❌ sandbox (not needed while read-only).
