"""Demo: drive the SME IT Agent's tools through LangChain/LangGraph instead of Brain.

Proves the Hybrid story — same tools (ai/tools.py) + same persona (SYSTEM_CHAT),
running inside a LangGraph ReAct agent with per-thread memory.

Needs the optional extra:  pip install -r requirements-langchain.txt
Run:  python -m examples.langchain_demo
"""
from __future__ import annotations

import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from ai.langchain_adapter import ask, build_agent
from config import load_config
from storage.db import Database


def main() -> None:
    cfg = load_config()
    db = Database(cfg.db_path)
    agent = build_agent(cfg, db)

    tid = "demo"
    for q in ["PC ไหนปิดอยู่บ้าง", "แล้วเครื่องไหน offline นานที่สุด"]:  # 2nd relies on memory
        print(f"\nIT> {q}")
        print("CHENG AI(LC):", ask(agent, q, thread_id=tid))


if __name__ == "__main__":
    main()
