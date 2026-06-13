"""PRODUCTION tier — live end-to-end scenarios against the real Ollama model.

Unlike the unit suite (mocked) and the hardcore suite (adversarial, offline), this
drives an actual Brain in --workspace mode against a live model and checks whether the
right tool fired AND the answer is grounded. It is the honest "does it work in
practice, and where does Claude Code still win" probe.

Run:  python eval/prod_compare.py            (needs `ollama serve` + the model pulled)
It auto-approves write confirmations (so edits actually happen) and prints a report.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config                      # noqa: E402
from cheng import build_brain                      # noqa: E402
from storage.db import Database                     # noqa: E402


def _seed(ws: Path) -> None:
    (ws / "notes.txt").write_text("project status: draft\nowner: alice\n", encoding="utf-8")
    (ws / "todo.md").write_text("- [ ] ship the thing\n- [ ] write tests\n", encoding="utf-8")
    (ws / "data").mkdir(exist_ok=True)
    (ws / "data" / "hosts.txt").write_text("SRV01\nSRV02\nPC42\n", encoding="utf-8")


def _run_one(brain, prompt: str) -> tuple[str, list[str]]:
    """One fresh turn; returns (answer, tool_names_fired)."""
    fired: list[str] = []
    history = brain.new_history()
    answer = brain.ask(history, prompt, on_tool=lambda n, a: fired.append(n))
    return answer or "", fired


def main() -> int:
    cfg = load_config()
    ws = Path(tempfile.mkdtemp(prefix="cheng_prod_"))
    _seed(ws)
    db = Database(ws / ".cheng.db")
    # workspace brain, web ON, auto-approve writes so edits actually run
    brain = build_brain(cfg, db, str(ws), web=True)
    brain.confirm = lambda name, args: True

    if not brain.is_available():
        print("✖ Ollama not reachable — start `ollama serve` and pull the model.")
        return 2
    print(f"model: {cfg.ollama_model}   workspace: {ws}\n")

    # (label, prompt, expected tool(s) — any-of, grounding check on the answer)
    scenarios = [
        ("list files", "List the files in this folder.",
         {"list_dir", "find_files"}, lambda a: "notes" in a.lower() or "todo" in a.lower()),
        ("read file", "What is the project status in notes.txt?",
         {"read_file"}, lambda a: "draft" in a.lower()),
        ("edit file", "In notes.txt, change the word draft to final.",
         {"edit_file"}, lambda a: (ws / "notes.txt").read_text(encoding="utf-8").find("final") >= 0),
        ("grep", "Which file mentions PC42?",
         {"search_text", "find_files", "read_file"}, lambda a: "hosts" in a.lower()),
        ("memory", "Remember that the print server is SRV-PRINT01.",
         {"remember"}, lambda a: True),
        ("web search", "Search the web: what is the capital of France?",
         {"web_search"}, lambda a: "paris" in a.lower()),
    ]

    rows, passed = [], 0
    for label, prompt, want_tools, grounded in scenarios:
        try:
            answer, fired = _run_one(brain, prompt)
            tool_ok = bool(want_tools & set(fired))
            ground_ok = grounded(answer)
            ok = tool_ok and ground_ok
        except Exception as exc:                      # noqa: BLE001
            answer, fired, tool_ok, ground_ok, ok = f"EXCEPTION: {exc}", [], False, False, False
        passed += ok
        rows.append((label, ok, tool_ok, ground_ok, fired, answer))

    print(f"{'scenario':<12} {'pass':<5} {'tool':<5} {'grnd':<5} tools_fired")
    print("-" * 70)
    for label, ok, tool_ok, ground_ok, fired, answer in rows:
        mark = "✓" if ok else "✗"
        print(f"{label:<12} {mark:<5} {('y' if tool_ok else '-'):<5} "
              f"{('y' if ground_ok else '-'):<5} {','.join(fired) or '(none)'}")
        print(f"    └ {answer[:110].strip().replace(chr(10), ' ')}")
    print("-" * 70)
    print(f"PASSED {passed}/{len(scenarios)}   "
          f"(tool-selection is the usual failure mode for a 3B model — that's the harness's job)")
    return 0 if passed == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(main())
