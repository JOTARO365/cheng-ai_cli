"""CHENG AI CLI — terminal console for the SME IT Agent (retro, but a working tool).

A local, offline IT assistant in your terminal: ask in Thai or English, the model
calls our tools and answers from real data. Same backend as the Open WebUI interface
(local Ollama + the same SQLite store).

Run:
  python cheng.py                      monitor console (read-only IT tools)
  python cheng.py --workspace DIR      file assistant (read/edit/write in DIR; writes ask first)
  python cheng.py --ask "…"            one-shot, no REPL
Commands:  /help   /status   /clear   /exit
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import threading
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
from ai.fs_tools import FS_TOOL_SPECS, WRITE_TOOLS, diff_for, make_fs_dispatcher
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
  [bold]/usage[/]    token usage + speed this session
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
    if c == "/usage":
        return "usage"
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
    ("/usage", "token usage this session"),
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
        f"[{CORAL}]✻[/] [bold]CHENG AI[/]  [{MUTED}]· SME IT Agent · local · offline[/]\n\n"
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


def session_user(current_user: "User | None") -> str:
    """Whose session this is: the signed-in user (--login) or the OS user."""
    if current_user is not None:
        return current_user.username
    try:
        return getpass.getuser() or "local"
    except Exception:  # noqa: BLE001 — getuser can raise if no login info
        return "local"


def session_key(user: str, folder: str) -> str:
    """Deterministic session id bound to (user, folder) so the CLI and TUI launched
    from the SAME folder by the SAME user share one conversation context. The abspath
    hash keeps it unique; the basename slug keeps it readable in /sessions."""
    folder = os.path.abspath(folder)
    h = hashlib.sha1(folder.encode("utf-8", "replace")).hexdigest()[:8]
    base = os.path.basename(folder.rstrip("\\/")) or "root"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower() or "dir"
    user_slug = re.sub(r"[^A-Za-z0-9]+", "-", user).strip("-").lower() or "user"
    return f"{slug}-{h}-{user_slug}"


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


# ---- transient ANIMATED status line ("⠹ thinking…" / "⠼ running X…") ---------
# brain.ask() blocks while the model runs, so a background thread spins the frame on
# the same line (plain \r, no ANSI cursor codes → portable). Any real output clears it
# first; a lock makes sure the spinner never writes between a clear and that output.
class _Spinner:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop: "threading.Event | None" = None
        self._thread: "threading.Thread | None" = None
        self._len = 0
        self._msg = ""

    def show(self, msg: str) -> None:
        self.clear()
        self._msg = msg
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        i = 0
        assert self._stop is not None
        while not self._stop.is_set():
            with self._lock:
                if self._stop.is_set():
                    break
                s = f"  {self.FRAMES[i % len(self.FRAMES)]} {self._msg}…"
                pad = max(0, self._len - len(s))
                sys.stdout.write("\r" + s + " " * pad + "\r" + s)
                sys.stdout.flush()
                self._len = len(s)
            i += 1
            self._stop.wait(0.1)

    def clear(self) -> None:
        if self._thread is not None:
            assert self._stop is not None
            self._stop.set()
            self._thread.join(timeout=0.3)
            self._thread = None
        with self._lock:
            if self._len:
                sys.stdout.write("\r" + " " * self._len + "\r")
                sys.stdout.flush()
                self._len = 0


_spinner = _Spinner()


def _status_show(msg: str) -> None:
    _spinner.show(msg)


def _status_clear() -> None:
    _spinner.clear()


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


def _render_diff(diff_text: str, max_lines: int = 80) -> None:
    """Print a unified diff with +/- coloring (Claude-Code-style edit preview)."""
    out = Text()
    lines = diff_text.splitlines()
    for line in lines[:max_lines]:
        if line.startswith(("+++", "---")):
            style = MUTED
        elif line.startswith("@@"):
            style = "cyan"
        elif line.startswith("+"):
            style = "green"
        elif line.startswith("-"):
            style = "red"
        else:
            style = MUTED
        out.append("    " + line + "\n", style=style)
    if len(lines) > max_lines:
        out.append(f"    … {len(lines) - max_lines} more line(s)\n", style=MUTED)
    console.print(out, end="")


_MENTION = re.compile(r"@([^\s@]+)")
MENTION_MAX = 20_000  # chars per referenced file injected into the prompt


def expand_mentions(text: str, base) -> tuple[str, list[str]]:
    """Expand `@path` tokens the USER typed into inlined file context (Claude-Code-style
    @file mentions). Reads files relative to `base`; unknown @tokens are left untouched
    (could be an email or a literal @). Returns (possibly-rewritten text, loaded paths)."""
    base = Path(base)
    loaded: list[tuple[str, str]] = []

    def _sub(m: "re.Match[str]") -> str:
        rel = m.group(1).rstrip(".,;:)]}'\"")          # trailing punctuation isn't part of the path
        p = base / rel
        try:
            if p.is_file():
                loaded.append((rel, p.read_text(encoding="utf-8", errors="replace")[:MENTION_MAX]))
                return rel                              # keep the path word in the question
        except OSError:
            pass
        return m.group(0)                               # leave an unknown @token as-is

    new = _MENTION.sub(_sub, text)
    if not loaded:
        return text, []
    blocks = "\n\n".join(f"--- {rel} ---\n{content}" for rel, content in loaded)
    return f"Referenced files:\n{blocks}\n\nQuestion: {new}", [r for r, _ in loaded]


def make_confirm(base) -> "Callable[[str, dict], bool]":
    """A confirm callback bound to a workspace root so it can show a real diff before
    edit_file / write_file. Other write tools (shell, excel, mkdir) show their args."""
    def confirm(name: str, args: dict) -> bool:
        if name == "run_command":
            # show the FULL command (never truncated) via Text so any [brackets] aren't
            # parsed as markup — the user must see exactly what will run.
            console.print(Text.assemble(("⏺ ", CORAL), ("run_command  ", "bold"),
                                        (str(args.get("command", "")), "yellow")))
        elif name in ("edit_file", "write_file"):
            console.print(Text.assemble(("⏺ ", CORAL), (name + "  ", "bold"),
                                        (str(args.get("path", "")), "yellow")))
            diff = diff_for(base, name, args)
            if diff:
                _render_diff(diff)
        else:
            arg_s = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
            console.print(Text.assemble(("⏺ ", CORAL), (name, "bold"), (f"({arg_s})", MUTED)))
        ans = console.input(f"  [{MUTED}]⎿  proceed? \\[y/N][/] ")
        return ans.strip().lower() in ("y", "yes")
    return confirm


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
        confirm=make_confirm(base), **skill_kw,
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
        Text.from_markup(f"[{CORAL}]✻[/] [bold]Welcome to CHENG AI[/]\n\n"
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
    console.print(f"\n[{CORAL}]✻[/] [bold]CHENG AI login[/]  [{MUTED}]· sign in to continue[/]")
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
    parser = argparse.ArgumentParser(description="CHENG AI CLI — SME IT Agent")
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
    parser.add_argument("--llm-route", action="store_true",
                        help="with --team: route via a structured-output classifier "
                             "(falls back to keyword) instead of pure keyword matching")
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
    team = Supervisor(cfg, db, llm_route=args.llm_route, **skill_kw) if args.team else None
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
        text, mentions = expand_mentions(text, args.workspace or ".")
        for rel in mentions:
            console.print(Text.assemble(("⏺ ", CORAL), ("@" + rel, "bold"),
                                        (" loaded into context", MUTED)))
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
                label = "CHENG AI"
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
                label = "CHENG AI"
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
        console.print(Text.assemble(("⏺ ", CORAL), ("CHENG AI", MUTED)))
        console.print(Markdown(ans or "_(no answer)_"))
        tail = " · [green]web ↗[/green]" if searched else ""
        console.print(f"[{MUTED}]— {subtitle} · CHENG AI[/]{tail}")

    if args.ask:
        answer_turn(args.ask, [])
        return

    online = team.is_available() if team else brain.is_available()
    n_tools = team.tool_count() if team else len(brain.tools)
    title_screen(cfg.ollama_model, online, n_tools, args.workspace)
    if team:
        console.print(Align.center(Text("TEAM ROUTING: security · network · service",
                                        style="bold cyan")))
    # ---- session persistence (auto-bound to user + cwd) -------------------
    # By DEFAULT the session id is derived from (user, current folder) so the CLI and
    # TUI launched from the same folder share one conversation. --resume <id> jumps to a
    # specific past session; --continue resumes the most-recent one anywhere. Team mode
    # keeps no single history (each specialist has its own) → not resumable.
    if team:
        sess_id = _new_session_id()
        history: list = []
        if args.resume or args.cont:
            console.print(f"[{MUTED}]↻ --team sessions aren't resumable (per-specialist history)[/]")
    else:
        if args.resume:
            sess_id = args.resume
        elif args.cont:
            sess_id = db.latest_session_id() or session_key(session_user(current_user), os.getcwd())
        else:                                   # default: bind to this user + this folder
            sess_id = session_key(session_user(current_user), os.getcwd())
        loaded = db.load_session(sess_id)
        history = loaded if loaded else brain.new_history()
        if loaded:
            turns = sum(1 for m in history if m.get("role") == "user")
            console.print(f"[{MUTED}]↻ resumed [bold]{sess_id}[/] "
                          f"({turns} turn{'s' if turns != 1 else ''} in this folder)[/]")
        elif args.resume:
            console.print(f"[yellow]no session {args.resume} — starting fresh[/]")

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
        if action == "usage":
            brains = team.brains() if team and hasattr(team, "brains") else \
                ([brain] if brain else [])
            tot = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "eval_ms": 0.0}
            for b in brains:
                for k in tot:
                    tot[k] += b.usage_total.get(k, 0)
            secs = tot["eval_ms"] / 1000.0
            tps = round(tot["completion_tokens"] / secs, 1) if secs else 0.0
            console.print(Panel(Text.from_markup(
                f"  [{MUTED}]model[/]   {cfg.ollama_model}\n"
                f"  [{MUTED}]calls[/]   {tot['calls']}\n"
                f"  [{MUTED}]prompt[/]  {tot['prompt_tokens']:,} tokens\n"
                f"  [{MUTED}]output[/]  {tot['completion_tokens']:,} tokens\n"
                f"  [{MUTED}]speed[/]   {tps} tok/s [{MUTED}](generation)[/]"),
                title=f"[{CORAL}]usage · this session[/]", title_align="left",
                box=box.ROUNDED, border_style=MUTED, expand=False, padding=(0, 1)))
            continue
        if action == "clear":
            history = [] if team else brain.new_history()
            if not team:
                db.delete_session(sess_id)               # wipe THIS folder's saved context
            console.print("[dim cyan]context cleared.[/dim cyan]")
            continue

        answer_turn(text, history)
        if not team:
            _autosave(db, sess_id, history)              # persist after each turn


if __name__ == "__main__":
    main()
