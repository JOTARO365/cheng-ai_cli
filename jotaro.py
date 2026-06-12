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

from ai.brain import Brain, OllamaUnavailable, _CJK
from ai.excel_tools import EXCEL_TOOL_SPECS, EXCEL_WRITE_TOOLS, make_excel_dispatcher
from ai.fs_tools import FS_TOOL_SPECS, WRITE_TOOLS, make_fs_dispatcher
from ai.shell_tools import SHELL_TOOL_SPECS, SHELL_WRITE_TOOLS, make_shell_dispatcher
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
  [bold]/model[/]    show models / switch:  /model qwen2.5:14b
  [bold]/remember[/] save a durable fact:  /remember SRV1 is the print server
  [bold]/memory[/]   list what's remembered
  [bold]/skills[/]   list skills · /skills on|off · /skills <dir> (load local, e.g. ~/.claude)
  [bold]/clear[/]    clear the conversation context
  [bold]/exit[/]     quit  (or Ctrl-D)

[{CORAL}]examples[/]  [{MUTED}](ถามไทย/อังกฤษได้)[/]
  [{MUTED}]›[/] PC ไหนปิดอยู่บ้าง
  [{MUTED}]›[/] login fail วันนี้มีกี่ครั้ง
  [{MUTED}]›[/] john lock อยู่ไหม
  [{MUTED}]›[/] สถานะระบบตอนนี้เป็นยังไง
"""


EXIT_CMDS = {"/exit", "/quit", "/q"}
HELP_CMDS = {"/help", "/h", "?"}


def dispatch_command(text: str) -> str:
    """Map a REPL line to an action: exit | help | status | clear | ask.
    Pure + unit-testable (the prompt_toolkit REPL can't be driven headless on Windows)."""
    c = text.strip().lower()
    if c in EXIT_CMDS:
        return "exit"
    if c in HELP_CMDS:
        return "help"
    if c == "/status":
        return "status"
    if c == "/clear":
        return "clear"
    if c == "/model" or c.startswith("/model "):
        return "model"
    if c == "/remember" or c.startswith("/remember "):
        return "remember"
    if c == "/memory":
        return "memory"
    if c == "/skills" or c.startswith("/skills "):
        return "skills"
    return "ask"


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


# ---- transient status line ("· thinking…" / "· running X…") ----------------
# Plain \r + padding (no ANSI) so it clears portably on any console; any real output
# (tool line / token) clears it first.
_status = {"len": 0}


def _status_show(msg: str) -> None:
    s = f"  · {msg}…"
    pad = max(0, _status["len"] - len(s))
    sys.stdout.write("\r" + s + " " * pad + "\r" + s)
    sys.stdout.flush()
    _status["len"] = len(s)


def _status_clear() -> None:
    if _status["len"]:
        sys.stdout.write("\r" + " " * _status["len"] + "\r")
        sys.stdout.flush()
        _status["len"] = 0


def _summarize(result: object) -> str:
    """One-line summary of a tool result for the ⎿ line."""
    if isinstance(result, list):
        return f"{len(result)} row(s)"
    if isinstance(result, dict):
        if "error" in result:
            return f"error: {result['error']}"
        parts = []
        for k, v in result.items():
            parts.append(f"{k}={len(v)}" if isinstance(v, list) else f"{k}={_short(v, 30)}")
        return ", ".join(parts)[:120] or "ok"
    return _short(result, 120)


def _on_tool(name: str, args: dict) -> None:
    _status_clear()
    arg_s = ", ".join(f"{k}={_short(v, 40)}" for k, v in args.items()) if args else ""
    console.print(Text.assemble(("⏺ ", CORAL), (name, "bold"), (f"({arg_s})", MUTED)))
    _status_show(f"running {name}")


def _on_result(name: str, result: object) -> None:
    _status_clear()
    console.print(Text.assemble(("  ⎿  ", MUTED), (_summarize(result), MUTED)))
    _status_show("thinking")


def _stream_token(delta: str) -> None:
    _status_clear()
    sys.stdout.write(_CJK.sub("", delta))   # strip any Chinese per-token
    sys.stdout.flush()


def _confirm(name: str, args: dict) -> bool:
    if name == "run_command":
        # show the FULL command (never truncated) via Text so any [brackets] aren't
        # parsed as markup — the user must see exactly what will run.
        console.print(Text.assemble(("⏺ ", CORAL), ("run_command  ", "bold"),
                                    (str(args.get("command", "")), "yellow")))
    else:
        arg_s = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
        console.print(Text.assemble(("⏺ ", CORAL), (name, "bold"), (f"({arg_s})", MUTED)))
    ans = console.input(f"  [{MUTED}]⎿  proceed? \\[y/N][/] ")
    return ans.strip().lower() in ("y", "yes")


def build_brain(cfg, db: Database, workspace: str | None, **skill_kw) -> Brain:
    if workspace:
        base = Path(workspace).resolve()
        fs_d, xl_d, sh_d = (make_fs_dispatcher(base), make_excel_dispatcher(base),
                            make_shell_dispatcher(base))

        def dispatcher(name: str, args: dict):
            if name.startswith("excel_"):
                return xl_d(name, args)
            if name == "run_command":
                return sh_d(name, args)
            return fs_d(name, args)

        return Brain.from_config(
            cfg, db, system=SYSTEM_FS,
            tools=FS_TOOL_SPECS + EXCEL_TOOL_SPECS + SHELL_TOOL_SPECS,
            dispatcher=dispatcher,
            confirm_tools=WRITE_TOOLS | EXCEL_WRITE_TOOLS | SHELL_WRITE_TOOLS,
            confirm=_confirm, **skill_kw,
        )
    return Brain.from_config(cfg, db, **skill_kw)


def main() -> None:
    parser = argparse.ArgumentParser(description="JOTARO AI CLI — SME IT Agent")
    parser.add_argument("--ask", metavar="QUESTION",
                        help="ask one question, print the answer, and exit (no REPL)")
    parser.add_argument("--workspace", metavar="DIR", nargs="?", const=".", default=None,
                        help="enable sandboxed file tools (read/edit/write; writes ask first). "
                             "Bare --workspace = current folder; or pass a DIR.")
    parser.add_argument("--team", action="store_true",
                        help="route each question to a specialist agent (security / network / service)")
    parser.add_argument("--skills", metavar="DIR",
                        help="load skill.md runbooks from DIR (e.g. a local ~/.claude). Default: ./skills")
    parser.add_argument("--no-skills", action="store_true", help="start with skills off")
    args = parser.parse_args()

    cfg = load_config()
    db = Database(cfg.db_path)
    from ai.skills import DEFAULT_SKILLS_DIR
    skill_kw = {"skills_dir": args.skills or DEFAULT_SKILLS_DIR,
                "skills_enabled": not args.no_skills}
    team = Supervisor(cfg, db, **skill_kw) if args.team else None
    brain = None if team else build_brain(cfg, db, args.workspace, **skill_kw)
    subtitle = ("team · security / network / service" if team
                else f"workspace · {Path(args.workspace).resolve()}" if args.workspace
                else "read-only · offline")

    def answer_turn(text: str, history: list) -> None:
        """Stream one answer (tokens) with ⏺/⎿ tool lines, a live status, + a footer."""
        console.print()
        _status_show("thinking")
        try:
            if team:
                label, _ = team.ask(text, on_tool=_on_tool, on_result=_on_result,
                                    on_token=_stream_token)
            else:
                brain.ask(history, text, on_tool=_on_tool, on_result=_on_result,
                          on_token=_stream_token)
                label = "JOTARO"
        except OllamaUnavailable as exc:
            _status_clear()
            console.print(f"[bold red]✖ Ollama unreachable:[/bold red] {exc}")
            return
        _status_clear()
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print(f"[{MUTED}]— {subtitle} · {label}[/]")

    if args.ask:
        answer_turn(args.ask, [])
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

        action = dispatch_command(text)
        if action == "exit":
            console.print("[dim cyan]session ended.[/dim cyan]")
            break
        if action == "help":
            console.print(Panel(HELP, box=box.ROUNDED, border_style=CORAL,
                                expand=False, padding=(1, 2)))
            continue
        if action == "status":
            show_status(db)
            continue
        if action == "model":
            parts = text.split(maxsplit=1)
            avail = team.list_models() if team else brain.list_models()
            if len(parts) == 1:
                cur = team.model if team else brain.model
                console.print(f"[{MUTED}]current:[/] [bold]{cur}[/]")
                console.print(f"[{MUTED}]available:[/] "
                              + (", ".join(avail) or "(none — `ollama pull <model>`)"))
            else:
                name = parts[1].strip()
                if team:
                    team.set_model(name)
                else:
                    brain.model = name
                warn = "" if (not avail or name in avail) else "  [yellow](not pulled yet)[/]"
                console.print(f"[{MUTED}]model →[/] [bold]{name}[/]{warn}")
            continue
        if action == "remember":
            parts = text.split(maxsplit=1)
            if len(parts) == 1:
                console.print(f"[{MUTED}]usage: /remember <fact>[/]")
            else:
                mid = db.add_memory(parts[1].strip())
                console.print(f"[{CORAL}]✓[/] remembered [dim](#{mid})[/]")
            continue
        if action == "memory":
            mems = db.recent_memory(50)
            if not mems:
                console.print(f"[{MUTED}](nothing remembered yet — /remember <fact>)[/]")
            for m in mems:
                console.print(f"  [{MUTED}]#{m['id']}[/] {m['text']}")
            continue
        if action == "skills":
            obj = team if team else brain
            parts = text.split(maxsplit=1)
            if len(parts) == 2 and parts[1].lower() in ("on", "off"):
                obj.set_skills_enabled(parts[1].lower() == "on")
                console.print(f"[{MUTED}]skills →[/] {'on' if obj.skills_enabled else 'off'}")
            elif len(parts) == 2:                       # a directory → load local skills
                n = obj.load_skills_from(parts[1].strip())
                console.print(f"[{MUTED}]loaded[/] {n} skill(s) from {parts[1].strip()}")
                history = [] if team else brain.new_history()   # refresh injected catalog
            else:
                names = obj.skill_names()
                console.print(f"[{MUTED}]skills:[/] {'on' if obj.skills_enabled else 'off'}"
                              f"  ({len(names)} loaded)")
                for nm in names:
                    console.print(f"  [{MUTED}]›[/] {nm}")
            continue
        if action == "clear":
            history = [] if team else brain.new_history()
            console.print("[dim cyan]context cleared.[/dim cyan]")
            continue

        answer_turn(text, history)


if __name__ == "__main__":
    main()
