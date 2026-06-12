"""Run the eval: score the local model on our IT Q&A, with vs without the harness.

    python -m eval.run_eval            # harnessed (Brain + tools) only
    python -m eval.run_eval --bare     # also run the bare model (no tools) to show the lift
    python -m eval.run_eval --model qwen2.5:14b   # try another model

Scores per case: FACT (does the answer contain the ground-truth values?) and TOOL
(did it call the right tool?). The point: on data questions a BARE model — at ANY
size — can't be right (it has no access to our DB), so the harness is the enabler,
not the parameter count.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from rich.console import Console
from rich.table import Table

from ai.brain import Brain, OllamaUnavailable
from config import load_config
from eval.cases import CASES, score, seed
from storage.db import Database

console = Console()
BARE_SYSTEM = ("You are a helpful IT assistant. Answer the user's question directly "
               "and concisely. Reply in the question's language.")


def main() -> None:
    ap = argparse.ArgumentParser(description="JOTARO eval — harness lift on a local model")
    ap.add_argument("--bare", action="store_true", help="also run the model with NO tools")
    ap.add_argument("--model", help="override OLLAMA_MODEL")
    args = ap.parse_args()

    cfg = load_config()
    model = args.model or cfg.ollama_model
    db = Database(Path(tempfile.gettempdir()) / "jotaro_eval.db")
    seed(db)

    harnessed = Brain(cfg.ollama_host, model, db)                       # tools + SYSTEM_CHAT
    bare = Brain(cfg.ollama_host, model, db, system=BARE_SYSTEM, tools=[]) if args.bare else None

    if not harnessed.is_available():
        console.print("[red]Ollama not reachable — start `ollama serve` first.[/red]")
        return

    table = Table(title=f"eval · model={model} · {len(CASES)} cases", show_lines=False)
    table.add_column("question", overflow="fold", max_width=40)
    table.add_column("tool ✓", justify="center")
    table.add_column("fact ✓", justify="center")
    if bare:
        table.add_column("bare fact ✓", justify="center")

    h_fact = h_tool = b_fact = 0
    mark = lambda ok: "[green]✓[/]" if ok else "[red]✗[/]"  # noqa: E731

    for case in CASES:
        tools_called: list[str] = []
        try:
            ans = harnessed.ask(harnessed.new_history(), case["q"],
                                on_tool=lambda n, a: tools_called.append(n))
        except OllamaUnavailable as exc:
            console.print(f"[red]Ollama error: {exc}[/red]")
            return
        f_ok, t_ok = score(case, ans, tools_called)
        h_fact += f_ok
        h_tool += t_ok
        row = [case["q"], mark(t_ok), mark(f_ok)]
        if bare:
            bans = bare.ask(bare.new_history(), case["q"])
            bf_ok, _ = score(case, bans, [])
            b_fact += bf_ok
            row.append(mark(bf_ok))
        table.add_row(*row)

    console.print(table)
    n = len(CASES)
    console.print(f"\n[bold]HARNESSED[/bold]  tool-call: [cyan]{h_tool}/{n}[/] "
                  f"({100*h_tool//n}%)   fact: [cyan]{h_fact}/{n}[/] ({100*h_fact//n}%)")
    if bare:
        console.print(f"[bold]BARE (no tools)[/bold]  fact: [cyan]{b_fact}/{n}[/] "
                      f"({100*b_fact//n}%)")
        console.print(f"\n[dim]→ harness lift on fact-accuracy: "
                      f"+{100*(h_fact-b_fact)//n} points[/dim]")


if __name__ == "__main__":
    main()
