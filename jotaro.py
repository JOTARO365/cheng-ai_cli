"""JOTARO AI CLI — terminal console for the SME IT Agent (retro, but a working tool).

A local, offline IT assistant in your terminal: ask in Thai or English, the model
calls our tools and answers from real data. Same backend as the Open WebUI interface
(local Ollama + the same SQLite store).

Run:
  python jotaro.py                      monitor console (read-only IT tools)
  python jotaro.py --workspace DIR      file assistant (read/edit/write in DIR; writes ask first)
  python jotaro.py --ask "…"            one-shot, no REPL
Commands:  /help   /status   /clear   /exit
"""
from __future__ import annotations

import argparse
import sys

# Force UTF-8 first — this entrypoint prints box-drawing + Thai. (cp874 console would
# mojibake it.) See the powershell-windows-encoding skill.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from ai.brain import Brain, OllamaUnavailable
from ai.fs_tools import FS_TOOL_SPECS, WRITE_TOOLS, make_fs_dispatcher
from ai.prompts import SYSTEM_FS
from ai.specialists import Supervisor
from config import load_config
from storage.db import Database

console = Console()

# Claude Code / Codex–style palette: warm coral accent, muted greys, clean lines
CORAL = "#d97757"
MUTED = "grey58"

HELP = f"""\
[{CORAL}]commands[/]
  [bold]/help[/]     show this screen
  [bold]/status[/]   system status (reads tools directly, no model)
  [bold]/clear[/]    clear the conversation context
  [bold]/exit[/]     quit  (or Ctrl-D)

[{CORAL}]examples[/]  [{MUTED}](ถามไทย/อังกฤษได้)[/]
  [{MUTED}]›[/] PC ไหนปิดอยู่บ้าง
  [{MUTED}]›[/] login fail วันนี้มีกี่ครั้ง
  [{MUTED}]›[/] john lock อยู่ไหม
  [{MUTED}]›[/] สถานะระบบตอนนี้เป็นยังไง
"""


def _short(v: object, n: int = 60) -> str:
    s = str(v).replace("\n", "⏎")
    return s if len(s) <= n else s[:n] + "…"


def title_screen(model: str, online: bool, n_tools: int, workspace: str | None) -> None:
    status = "[green]● online[/]" if online else "[red]● offline[/]"
    mode = f"workspace · {workspace}" if workspace else "monitor · read-only"
    body = Text.from_markup(
        f"[{CORAL}]✻[/] [bold]JOTARO[/]  [{MUTED}]· SME IT Agent · local · offline[/]\n\n"
        f"  [{MUTED}]model[/]   {model}   {status}\n"
        f"  [{MUTED}]mode[/]    {mode}\n"
        f"  [{MUTED}]tools[/]   {n_tools} loaded\n\n"
        f"[{MUTED}]/help for commands · /exit to quit[/]"
    )
    console.print(Panel(body, box=box.ROUNDED, border_style=CORAL,
                        padding=(1, 2), expand=False))
    if not online:
        console.print(f"[red]![/] [{MUTED}]Ollama not reachable — start `ollama serve` "
                      f"and pull the model[/]")


def show_status(db: Database) -> None:
    s = db.system_summary()
    up, down = s["nodes_up"], s["nodes_down"]
    body = Text.from_markup(
        f"  [{MUTED}]nodes[/]    [green]{up} up[/] / [red]{down} down[/] / "
        f"{s['nodes_unknown']} unknown   (total {s['nodes_total']})\n"
        f"  [{MUTED}]fails[/]    {s['login_fail_users_24h']} users (24h)      "
        f"[{MUTED}]locked[/] {s['locked_accounts_24h']}\n"
        f"  [{MUTED}]alerts[/]   {s['alerts_pending']} pending"
    )
    console.print(Panel(body, title=f"[{CORAL}]status[/]", title_align="left",
                        box=box.ROUNDED, border_style=MUTED, expand=False, padding=(0, 1)))


def _answer_panel(answer: str, subtitle: str):
    """Claude-style: a coral marker + dim label, then the answer as flowing markdown
    (no heavy box)."""
    head = Text.assemble(("⏺ ", CORAL), (subtitle, MUTED))
    return Group(Text(""), head, Markdown(answer or "_(no answer)_"))


def _on_tool(name: str, args: dict) -> None:
    arg_s = ", ".join(f"{k}={_short(v, 40)}" for k, v in args.items()) if args else ""
    console.print(Text.assemble(("⏺ ", CORAL), (name, "bold"), (f"({arg_s})", MUTED)))


def _confirm(name: str, args: dict) -> bool:
    arg_s = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
    console.print(Text.assemble(("⏺ ", CORAL), (name, "bold"), (f"({arg_s})", MUTED)))
    ans = console.input(f"  [{MUTED}]⎿  proceed? \\[y/N][/] ")
    return ans.strip().lower() in ("y", "yes")


def build_brain(cfg, db: Database, workspace: str | None) -> Brain:
    if workspace:
        base = Path(workspace).resolve()
        return Brain.from_config(
            cfg, db, system=SYSTEM_FS, tools=FS_TOOL_SPECS,
            dispatcher=make_fs_dispatcher(base), confirm_tools=WRITE_TOOLS, confirm=_confirm,
        )
    return Brain.from_config(cfg, db)


def main() -> None:
    parser = argparse.ArgumentParser(description="JOTARO AI CLI — SME IT Agent")
    parser.add_argument("--ask", metavar="QUESTION",
                        help="ask one question, print the answer, and exit (no REPL)")
    parser.add_argument("--workspace", metavar="DIR", nargs="?", const=".", default=None,
                        help="enable sandboxed file tools (read/edit/write; writes ask first). "
                             "Bare --workspace = current folder; or pass a DIR.")
    parser.add_argument("--team", action="store_true",
                        help="route each question to a specialist agent (security / network / service)")
    args = parser.parse_args()

    cfg = load_config()
    db = Database(cfg.db_path)
    team = Supervisor(cfg, db) if args.team else None
    brain = None if team else build_brain(cfg, db, args.workspace)
    subtitle = ("team · security / network / service" if team
                else f"workspace · {Path(args.workspace).resolve()}" if args.workspace
                else "read-only · offline")

    def respond(text: str, history: list) -> tuple[str, str]:
        """Return (label, answer) for whichever mode is active."""
        if team:
            with console.status("[cyan]working…[/cyan]", spinner="line"):
                return team.ask(text, on_tool=_on_tool)
        if brain.confirm:  # workspace mode: keep stdin clean for the y/N prompt
            return "JOTARO", brain.ask(history, text, on_tool=_on_tool)
        with console.status("[cyan]working…[/cyan]", spinner="line"):
            return "JOTARO", brain.ask(history, text, on_tool=_on_tool)

    if args.ask:
        try:
            label, answer = respond(args.ask, [])
        except OllamaUnavailable as exc:
            console.print(f"[bold red]✖ Ollama unreachable:[/bold red] {exc}")
            return
        console.print(_answer_panel(answer, f"{subtitle} · {label}" if team else subtitle))
        return

    online = team.is_available() if team else brain.is_available()
    n_tools = team.tool_count() if team else len(brain.tools)
    title_screen(cfg.ollama_model, online, n_tools, args.workspace)
    if team:
        console.print(Align.center(Text("TEAM ROUTING: security · network · service",
                                        style="bold cyan")))
    history: list = [] if team else brain.new_history()
    session: PromptSession = PromptSession(history=InMemoryHistory())

    while True:
        try:
            text = session.prompt("\nit › ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim cyan]session ended.[/dim cyan]")
            break
        if not text:
            continue

        cmd = text.lower()
        if cmd in ("/exit", "/quit", "/q"):
            console.print("[dim cyan]session ended.[/dim cyan]")
            break
        if cmd in ("/help", "/h", "?"):
            console.print(Panel(HELP, box=box.SQUARE, border_style=FRAME, expand=False))
            continue
        if cmd == "/status":
            show_status(db)
            continue
        if cmd == "/clear":
            history = [] if team else brain.new_history()
            console.print("[dim cyan]context cleared.[/dim cyan]")
            continue

        try:
            label, answer = respond(text, history)
        except OllamaUnavailable as exc:
            console.print(f"[bold red]✖ Ollama unreachable:[/bold red] {exc}")
            continue

        console.print(_answer_panel(answer, f"{subtitle} · {label}" if team else subtitle))


if __name__ == "__main__":
    main()
