"""HTTP bridge that exposes the agent's IT-context as OpenAPI "tools".

Open WebUI (the open-source chat UI for Phase 1) handles the chat window and the
Ollama calls itself; it just needs to *reach our live data*. This package serves
each read-only DB query as an OpenAPI endpoint that Open WebUI registers as a
tool, so the local model can answer "PC ไหนปิดอยู่?" / "login fail วันนี้กี่ครั้ง?"
from real data instead of guessing.

READ-ONLY by design — there are no write endpoints. The agent never mutates AD,
nodes, or alerts from here (Phase 1 hard rule: monitor + alert only).
"""
