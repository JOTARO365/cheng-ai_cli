"""Fair head-to-head: run the SAME prompts through the SAME real path (workspace
Brain, SYSTEM_FS persona) on two models. Usage: python -m eval.compare_models

Not a unit test — a live A/B so we see whether weak answers are the model or the harness.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from ai.brain import Brain                       # noqa: E402
from cheng import build_brain, expand_mentions  # noqa: E402
from config import load_config                   # noqa: E402
from storage.db import Database                  # noqa: E402

# A clean coding/file-assistant persona with NO tools, so we compare pure answer
# quality (no write-tool / confirm noise). @file content is inlined into the prompt.
CODE_SYSTEM = ("You are a precise coding assistant. Answer directly using any Referenced "
               "files content given. For code tasks, output only the code. Be concise.")

MODELS = ["qwen2.5:3b", "qwen2.5-coder:7b"]

# realistic file-assistant tasks (the @file content is inlined by expand_mentions)
TASKS = [
    ("read a value", "in @config.py what is DB_PORT? answer the number only"),
    ("reason over file", "in @config.py is DEBUG on or off? one word"),
    ("write code", "write a Python function reverse_words(s) that reverses the order "
                   "of words in a string. code only, no explanation"),
    ("fix a bug", "this Python crashes on empty input: def first(x): return x[0] — "
                  "fix it to return None when x is empty. give only the fixed function"),
]


def main() -> None:
    cfg = load_config()
    ws = Path(tempfile.mkdtemp())
    (ws / "config.py").write_text("DB_HOST = 'srv-db-01'\nDB_PORT = 5432\nDEBUG = True\n",
                                  encoding="utf-8")
    db = Database(ws / ".cmp.db")

    probe = Brain.from_config(cfg, db, system=CODE_SYSTEM, tools=[], skills_enabled=False)
    have = set(probe.list_models())
    todo = [m for m in MODELS if m in have]
    skip = [m for m in MODELS if m not in have]
    if skip:
        print(f"(skipping not-yet-pulled: {', '.join(skip)})")
    for model in todo:
        print("\n" + "=" * 72)
        print(f"  MODEL: {model}")
        print("=" * 72)
        brain = Brain.from_config(cfg, db, system=CODE_SYSTEM, tools=[], skills_enabled=False)
        brain.model = model
        if not brain.is_available():
            print("  (Ollama offline)"); continue
        for label, q in TASKS:
            expanded, _ = expand_mentions(q, ws)
            t0 = time.time()
            try:
                ans = brain.ask(brain.new_history(), expanded)
            except Exception as exc:  # noqa: BLE001
                ans = f"<error: {exc}>"
            dt = time.time() - t0
            u = brain.last_usage
            print(f"\n— [{label}] ({dt:.1f}s, {u.get('completion_tokens', 0)} tok)")
            print("  " + ans.strip().replace("\n", "\n  ")[:500])


if __name__ == "__main__":
    main()
