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
import getpass
import json
import re
import sys
from datetime import datetime

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
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory

from ai.auth import Auth, AuthError, User
from ai.brain import Brain, OllamaUnavailable, _CJK
from ai.excel_tools import EXCEL_TOOL_SPECS, EXCEL_WRITE_TOOLS, make_excel_dispatcher
from ai.fs_tools import FS_TOOL_SPECS, WRITE_TOOLS, make_fs_dispatcher
from ai.hooks import default_safe_hooks
from ai.shell_tools import SHELL_TOOL_SPECS, SHELL_WRITE_TOOLS, make_shell_dispatcher
from ai.parallel import fan_out_summarize
from ai.prompts import SYSTEM_FS, SYSTEM_SUMMARIZER
from ai.specialists import Supervisor
from ai.verify import Verifier
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
  [bold]/summarize[/] fan-out summarize a big file (chunk → sub-agents → merge)
  [bold]/sessions[/] list saved sessions  [{MUTED}](resume with --resume <id> / --continue)[/]
  [bold]/hooks[/]    list active safety hooks       [{MUTED}](--no-hooks to disable)[/]
  [bold]/whoami[/]   show the signed-in user        [{MUTED}](--login)[/]
  [bold]/passwd[/]   change your password           [{MUTED}](--login)[/]
  [bold]/users[/]    manage users (admin): /users · add · passwd · del
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
    if c == "/summarize" or c.startswith("/summarize "):
        return "summarize"
    if c == "/whoami":
        return "whoami"
    if c == "/passwd":
        return "passwd"
    if c == "/users" or c.startswith("/users "):
        return "users"
    if c == "/sessions" or c.startswith("/sessions "):
        return "sessions"
    if c == "/hooks":
        return "hooks"
    return "ask"


SLASH_CMDS = [
    ("/help", "show commands"),
    ("/status", "system status (no model)"),
    ("/model", "list / switch the model"),
    ("/remember", "save a durable fact"),
    ("/memory", "list what's remembered"),
    ("/skills", "list · on|off · load a dir"),
    ("/summarize", "fan-out summarize a file"),
    ("/sessions", "list saved sessions"),
    ("/hooks", "list active safety hooks"),
    ("/whoami", "show the signed-in user"),
    ("/passwd", "change your password"),
    ("/users", "manage users (admin)"),
    ("/clear", "reset the conversation"),
    ("/exit", "quit"),
]


class SlashCompleter(Completer):
    """Pop up the /commands (with descriptions) when the line starts with '/'."""
    def get_completions(self, document, complete_event):
        token = document.text_before_cursor.split(" ", 1)[0]
        if not token.startswith("/"):
            return
        for cmd, desc in SLASH_CMDS:
            if cmd.startswith(token):
                yield Completion(cmd, start_position=-len(token), display=cmd, display_meta=desc)


_NOINFO = re.compile(
    r"ไม่ทราบ|ไม่มีข้อมูล|ไม่แน่ใจ|ไม่สามารถ(ตอบ|หา|ให้)|ไม่พบ(ข้อมูล)?|ขอโทษ.*ไม่|"
    r"don'?t (know|have)|not sure|no (information|data|record)|can'?t (find|answer|help)|"
    r"unable to", re.IGNORECASE)


def _no_knowledge(text: str) -> bool:
    """True if the answer signals the model doesn't know — used to trigger an auto web search."""
    return bool(text) and bool(_NOINFO.search(text))


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


def _new_session_id() -> str:
    """A readable, sortable per-session id (local time). Collisions need two launches
    in the same second; the DB upsert would just merge them harmlessly anyway."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def print_sessions(db: Database) -> None:
    rows = db.list_sessions(30)
    if not rows:
        console.print(f"  [{MUTED}](no saved sessions yet)[/]")
        return
    console.print(f"[{CORAL}]saved sessions[/] [{MUTED}](newest first — `--resume <id>`)[/]")
    for s in rows:
        when = (s["updated_at"] or "")[:16].replace("T", " ")
        label = (s["label"] or "—").replace("\n", " ")[:50]
        console.print(f"  [bold]{s['id']}[/]  [{MUTED}]{when}[/]  {label}")


def _autosave(db: Database, sess_id: str, history: list) -> None:
    """Persist the conversation after a turn. Skips trivial (system-only) history so an
    empty launch doesn't create a blank session."""
    if len(history) <= 1:
        return
    label = next((m.get("content") for m in history if m.get("role") == "user"), None)
    db.save_session(sess_id, history, label=(label or "").strip()[:80] or None)


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


def _on_compact(before: int, after: int) -> None:
    _status_clear()
    console.print(f"  [{MUTED}]⟳ compacted context {before:,} → {after:,} chars[/]")


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


def build_brain(cfg, db: Database, workspace: str | None, web: bool = False,
                mcp_config: str | None = None, **skill_kw) -> Brain:
    if not workspace:
        return Brain.from_config(cfg, db, **skill_kw)

    base = Path(workspace).resolve()
    fs_d, xl_d, sh_d = (make_fs_dispatcher(base), make_excel_dispatcher(base),
                        make_shell_dispatcher(base))
    tools = FS_TOOL_SPECS + EXCEL_TOOL_SPECS + SHELL_TOOL_SPECS
    system = SYSTEM_FS

    web_d = None
    if web:
        from ai.web_tools import WEB_TOOL_SPECS, make_web_dispatcher
        from ai.prompts import WEB_NUDGE
        web_d = make_web_dispatcher()
        tools = tools + WEB_TOOL_SPECS
        system = SYSTEM_FS + WEB_NUDGE

    mcp_client = None
    if mcp_config:
        from ai.mcp_client import MCPClient, load_mcp_config
        try:
            mcp_client = MCPClient(load_mcp_config(mcp_config))
            tools = tools + mcp_client.tool_specs()
            console.print(f"[{MUTED}]mcp:[/] connected {len(mcp_client.names())} tool(s) "
                          f"({', '.join(mcp_client.names()) or 'none'})")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]MCP load failed:[/yellow] {exc}")

    def dispatcher(name: str, args: dict):
        if web_d and name == "web_search":
            return web_d(name, args)
        if mcp_client and name in mcp_client.names():
            return mcp_client.dispatch(name, args)
        if name.startswith("excel_"):
            return xl_d(name, args)
        if name == "run_command":
            return sh_d(name, args)
        return fs_d(name, args)

    return Brain.from_config(
        cfg, db, system=system, tools=tools, dispatcher=dispatcher,
        confirm_tools=WRITE_TOOLS | EXCEL_WRITE_TOOLS | SHELL_WRITE_TOOLS,
        confirm=_confirm, **skill_kw,
    )


def _getpass(label: str) -> str:
    """Hidden password prompt. Returns '' on Ctrl-C/EOF so callers can bail cleanly."""
    try:
        return getpass.getpass(f"  {label}: ")
    except (EOFError, KeyboardInterrupt):
        return ""


def _bootstrap_admin(auth: Auth) -> User | None:
    """First run: no users exist yet — create the initial admin interactively."""
    console.print(Panel(
        Text.from_markup(f"[{CORAL}]✻[/] [bold]Welcome to JOTARO[/]\n\n"
                         f"[{MUTED}]No accounts yet — let's create the first admin.[/]"),
        box=box.ROUNDED, border_style=CORAL, expand=False, padding=(1, 2)))
    try:
        username = console.input(f"  [{MUTED}]admin username[/] [dim](admin)[/]: ").strip() or "admin"
    except (EOFError, KeyboardInterrupt):
        return None
    for _ in range(3):
        pw, pw2 = _getpass("password"), _getpass("confirm ")
        if pw != pw2:
            console.print("  [red]✖[/] passwords don't match")
            continue
        try:
            user = auth.register(username, pw, role="admin")
        except AuthError as exc:
            console.print(f"  [red]✖[/] {exc}")
            continue
        console.print(f"\n[green]✓[/] admin [bold]{user.username}[/] created — you're signed in.\n")
        return user
    return None


def login_gate(db: Database) -> User | None:
    """Sign the user in before the REPL. Returns the User, or None to abort startup."""
    auth = Auth(db)
    if not auth.has_users():
        return _bootstrap_admin(auth)
    console.print(f"\n[{CORAL}]✻[/] [bold]JOTARO login[/]  [{MUTED}]· sign in to continue[/]")
    for _ in range(3):
        try:
            username = console.input(f"  [{MUTED}]username:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        ok, user, msg = auth.authenticate(username, _getpass("password"))
        if ok and user is not None:
            console.print(f"[green]✓[/] welcome, [bold]{user.username}[/] [{MUTED}]({user.role})[/]\n")
            return user
        console.print(f"  [red]✖[/] {msg}")
    console.print("[red]login failed — exiting.[/]")
    return None


def _cmd_passwd(auth: Auth, user: User) -> None:
    """`/passwd` — change your own password (verifies the current one)."""
    old = _getpass("current password")
    new, new2 = _getpass("new password    "), _getpass("confirm new     ")
    if new != new2:
        console.print("  [red]✖[/] new passwords don't match")
        return
    try:
        auth.change_password(user.username, old, new)
        console.print(f"[green]✓[/] password updated for [bold]{user.username}[/]")
    except AuthError as exc:
        console.print(f"  [red]✖[/] {exc}")


def _cmd_users(auth: Auth, user: User, text: str) -> None:
    """`/users [add|del|passwd <name>]` — admin-only user management."""
    toks = text.split()
    if not user.is_admin:
        console.print(f"  [red]✖[/] only an admin can manage users")
        return
    if len(toks) == 1:                                   # list
        for u in auth.list_users():
            tag = "[cyan]admin[/]" if u["role"] == "admin" else f"[{MUTED}]user[/] "
            last = u["last_login"] or "never"
            console.print(f"  {tag}  [bold]{u['username']}[/]  [{MUTED}]last: {last}[/]")
        return
    action = toks[1].lower()
    if action in ("add", "passwd") and len(toks) >= 3:
        name = toks[2]
        pw, pw2 = _getpass("password"), _getpass("confirm ")
        if pw != pw2:
            console.print("  [red]✖[/] passwords don't match")
            return
        try:
            if action == "add":
                auth.register(name, pw, role="user")
                console.print(f"[green]✓[/] user [bold]{name}[/] created")
            else:
                auth.reset_password(name, pw)
                console.print(f"[green]✓[/] password reset for [bold]{name}[/]")
        except AuthError as exc:
            console.print(f"  [red]✖[/] {exc}")
    elif action in ("del", "delete", "rm") and len(toks) >= 3:
        name = toks[2]
        if name == user.username:
            console.print("  [red]✖[/] you can't delete yourself")
        elif auth.delete_user(name):
            console.print(f"[green]✓[/] user [bold]{name}[/] removed")
        else:
            console.print(f"  [{MUTED}]no such user: {name}[/]")
    else:
        console.print(f"  [{MUTED}]usage: /users · /users add <name> · "
                      f"/users passwd <name> · /users del <name>[/]")


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
    parser.add_argument("--verify", action="store_true",
                        help="check each answer for grounding/hallucination before showing it (slower, no streaming)")
    parser.add_argument("--web", action="store_true", help=argparse.SUPPRESS)  # now default-on in workspace
    parser.add_argument("--no-web", action="store_true",
                        help="disable web search in workspace mode (workspace is online by default)")
    parser.add_argument("--mcp", metavar="CONFIG",
                        help="connect to MCP servers from a JSON config (their tools become callable)")
    parser.add_argument("--login", action="store_true",
                        help="require username/password sign-in before the session "
                             "(first run creates an admin account)")
    parser.add_argument("--continue", dest="cont", action="store_true",
                        help="resume the most recent chat session")
    parser.add_argument("--resume", metavar="ID",
                        help="resume a specific chat session by id (see --sessions)")
    parser.add_argument("--sessions", action="store_true",
                        help="list saved chat sessions and exit")
    parser.add_argument("--no-hooks", action="store_true",
                        help="disable the default safety hooks (e.g. the rm -rf shell guard)")
    args = parser.parse_args()

    cfg = load_config()
    db = Database(cfg.db_path)

    if args.sessions:
        print_sessions(db)
        return

    auth = Auth(db)
    current_user: User | None = None
    if args.login:
        current_user = login_gate(db)
        if current_user is None:
            sys.exit(1)
    from ai.skills import DEFAULT_SKILLS_DIR
    skill_kw = {"skills_dir": args.skills or DEFAULT_SKILLS_DIR,
                "skills_enabled": not args.no_skills}
    team = Supervisor(cfg, db, **skill_kw) if args.team else None
    web = bool(args.workspace) and not args.no_web          # workspace is ONLINE by default
    brain = None if team else build_brain(cfg, db, args.workspace, web=web,
                                          mcp_config=args.mcp, **skill_kw)
    if brain is not None and not args.no_hooks:
        brain.hooks = default_safe_hooks()              # gap #8: block rm -rf etc. by default
    verifier = Verifier(cfg, db) if args.verify else None
    web_enabled = web and brain is not None                 # auto web-search fallback on
    subtitle = ("team · security / network / service" if team
                else f"workspace · {Path(args.workspace).resolve()}" if args.workspace
                else "read-only · offline")
    if current_user is not None:
        subtitle += f" · {current_user.username}"

    def answer_turn(text: str, history: list) -> None:
        """Stream one answer (tokens) with ⏺/⎿ tool lines, a live status, + a footer.
        With --verify, switch to a non-streaming verify-then-show pass."""
        console.print()
        if verifier is not None:
            _verified_turn(text, history)
            return
        if web_enabled:
            _web_turn(text, history)
            return
        _status_show("thinking")
        try:
            if team:
                label, _ = team.ask(text, on_tool=_on_tool, on_result=_on_result,
                                    on_token=_stream_token)
            else:
                brain.ask(history, text, on_tool=_on_tool, on_result=_on_result,
                          on_token=_stream_token, on_compact=_on_compact)
                label = "JOTARO"
        except OllamaUnavailable as exc:
            _status_clear()
            console.print(f"[bold red]✖ Ollama unreachable:[/bold red] {exc}")
            return
        _status_clear()
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print(f"[{MUTED}]— {subtitle} · {label}[/]")

    def _verified_turn(text: str, history: list) -> None:
        _status_show("thinking")
        try:
            if team:
                label, ans = team.ask(text, on_tool=_on_tool, on_result=_on_result)
                evidence = ""
            else:
                ans = brain.ask(history, text, on_tool=_on_tool, on_result=_on_result,
                                on_compact=_on_compact)
                label = "JOTARO"
                evidence = "\n".join(m["content"] for m in history
                                     if m.get("role") == "tool")[-3000:]
            _status_show("verifying")
            ok, issue = verifier.check(text, ans, evidence)
            if not ok and not team:
                _status_show("revising")
                ans = brain.ask(history, f"(verifier) your previous answer had a problem: "
                                f"{issue}. Answer again concisely using only the tool data, "
                                f"no repetition.")
        except OllamaUnavailable as exc:
            _status_clear()
            console.print(f"[bold red]✖ Ollama unreachable:[/bold red] {exc}")
            return
        _status_clear()
        mark = "[green]✓ verified[/green]" if ok else f"[yellow]⚠ revised: {issue}[/yellow]"
        console.print(Text.assemble(("⏺ ", CORAL), (label, MUTED)))
        console.print(Markdown(ans or "_(no answer)_"))
        console.print(f"[{MUTED}]— {subtitle} · {label} · [/]{mark}")

    def _web_turn(text: str, history: list) -> None:
        _status_show("thinking")
        searched = False
        try:
            ans = brain.ask(history, text, on_tool=_on_tool, on_result=_on_result,
                            on_compact=_on_compact)
            if _no_knowledge(ans):                       # model doesn't know → search ourselves
                _status_show("searching the web")
                sr = brain._execute("web_search", {"query": text})  # noqa: SLF001 — deterministic
                _on_tool("web_search", {"query": text})
                _on_result("web_search", sr)
                searched = True
                ans = brain.ask(history, "Web search results: "
                                + json.dumps(sr, ensure_ascii=False)[:2500]
                                + f"\n\nNow answer the question from these results: {text}")
        except OllamaUnavailable as exc:
            _status_clear()
            console.print(f"[bold red]✖ Ollama unreachable:[/bold red] {exc}")
            return
        _status_clear()
        console.print(Text.assemble(("⏺ ", CORAL), ("JOTARO", MUTED)))
        console.print(Markdown(ans or "_(no answer)_"))
        tail = " · [green]web ↗[/green]" if searched else ""
        console.print(f"[{MUTED}]— {subtitle} · JOTARO[/]{tail}")

    if args.ask:
        answer_turn(args.ask, [])
        return

    online = team.is_available() if team else brain.is_available()
    n_tools = team.tool_count() if team else len(brain.tools)
    title_screen(cfg.ollama_model, online, n_tools, args.workspace)
    if team:
        console.print(Align.center(Text("TEAM ROUTING: security · network · service",
                                        style="bold cyan")))
    # ---- session persistence (--continue / --resume) ----------------------
    # Team mode keeps no single history (each specialist has its own) → not resumable.
    sess_id = _new_session_id()
    history: list = [] if team else brain.new_history()
    if not team and (args.resume or args.cont):
        target = args.resume or db.latest_session_id()
        loaded = db.load_session(target) if target else None
        if loaded:
            sess_id, history = target, loaded
            turns = sum(1 for m in history if m.get("role") == "user")
            console.print(f"[{MUTED}]↻ resumed session [bold]{sess_id}[/] "
                          f"({turns} turn{'s' if turns != 1 else ''})[/]")
        else:
            console.print(f"[yellow]no session to resume"
                          f"{f' ({args.resume})' if args.resume else ''} — starting fresh[/]")
    elif team and (args.resume or args.cont):
        console.print(f"[{MUTED}]↻ --team sessions aren't resumable (per-specialist history)[/]")

    session: PromptSession = PromptSession(
        history=InMemoryHistory(), completer=SlashCompleter(), complete_while_typing=True,
        bottom_toolbar=lambda: HTML("  <b>/</b> commands   <b>↑↓</b> history   <b>Ctrl-D</b> quit  "),
    )

    while True:
        try:
            text = session.prompt(HTML("\n<ansibrightmagenta><b>❯</b></ansibrightmagenta> ")).strip()
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
            toks = text.split()
            if len(toks) == 1:                                   # list + per-skill status
                console.print(f"[{MUTED}]skills:[/] {'on' if obj.skills_enabled else 'off'} (global)")
                for nm, en in obj.skill_status():
                    console.print(f"  {'[green]on [/]' if en else '[red]off[/]'}  {nm}")
            elif toks[1].lower() in ("on", "off"):
                on = toks[1].lower() == "on"
                if len(toks) >= 3:                               # one or more named skills
                    for nm in toks[2:]:
                        ok = obj.set_skill(nm, on)
                        console.print(f"[{MUTED}]skill[/] {nm} → {'on' if on else 'off'}"
                                      + ("" if ok else "  [yellow](not found)[/]"))
                else:                                            # all skills
                    obj.set_skills_enabled(on)
                    console.print(f"[{MUTED}]skills →[/] {'on' if obj.skills_enabled else 'off'} (all)")
                history = [] if team else brain.new_history()
            else:                                                # a directory path → load
                d = text.split(maxsplit=1)[1].strip()
                console.print(f"[{MUTED}]loaded[/] {obj.load_skills_from(d)} skill(s) from {d}")
                history = [] if team else brain.new_history()
            continue
        if action == "summarize":
            parts = text.split(maxsplit=1)
            if len(parts) == 1:
                console.print(f"[{MUTED}]usage: /summarize <path>[/]")
                continue
            p = Path(parts[1].strip())
            if args.workspace and not p.is_absolute():
                p = Path(args.workspace).resolve() / p
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                console.print(f"[red]cannot read {p}:[/red] {exc}")
                continue

            def _factory():
                return Brain.from_config(cfg, db, system=SYSTEM_SUMMARIZER, tools=[],
                                         skills_enabled=False)

            with console.status("[cyan]fan-out summarizing…[/cyan]", spinner="line"):
                summary, n = fan_out_summarize(content, _factory)
            console.print(Text.assemble(("⏺ ", CORAL), ("summarize ", "bold"),
                          (f"{p.name} — {n} chunk(s) across sub-agents", MUTED)))
            console.print(Markdown(summary or "_(empty)_"))
            continue
        if action in ("whoami", "passwd", "users"):
            if current_user is None:
                console.print(f"  [{MUTED}]not signed in — start with [bold]--login[/] "
                              f"to use accounts[/]")
                continue
            if action == "whoami":
                console.print(f"  [bold]{current_user.username}[/] [{MUTED}]· "
                              f"{current_user.role}[/]")
            elif action == "passwd":
                _cmd_passwd(auth, current_user)
            else:
                _cmd_users(auth, current_user, text)
            continue
        if action == "sessions":
            print_sessions(db)
            continue
        if action == "hooks":
            hk = getattr(brain, "hooks", None) if not team else None
            rows = hk.describe() if hk else []
            if not rows:
                console.print(f"  [{MUTED}](no hooks active"
                              f"{' — team mode' if team else ' — started with --no-hooks'})[/]")
            else:
                console.print(f"[{CORAL}]active hooks[/] [{MUTED}](guard points around tool calls)[/]")
                for r in rows:
                    console.print(f"  [{MUTED}]{r}[/]")
            continue
        if action == "clear":
            history = [] if team else brain.new_history()
            sess_id = _new_session_id()                  # a clear starts a new session
            console.print("[dim cyan]context cleared.[/dim cyan]")
            continue

        answer_turn(text, history)
        if not team:
            _autosave(db, sess_id, history)              # persist after each turn


if __name__ == "__main__":
    main()
