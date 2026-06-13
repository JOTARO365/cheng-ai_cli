"""CHENG AI TUI — a full-screen terminal UI (Textual) for the SME IT Agent.

A real app UI: a status bar (model · mode · skills), a scrollable conversation log
(mouse wheel works), and an input box. The model runs in a worker THREAD so the UI
never freezes; tool calls (⏺) and results (⎿) stream into the log, then the answer.

Run:  python cheng_tui.py
Keys: Enter send · Ctrl+L clear · Ctrl+C quit · / for commands
This v1 is monitor mode (read-only IT tools) + memory + skills. Reuses the same backend.
"""
from __future__ import annotations

import os
import sys

from rich.markdown import Markdown
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Input, RichLog, Static

from ai.brain import OllamaUnavailable, _CJK
from config import load_config
from cheng import (HELP, SLASH_CMDS, _autosave, _summarize, build_brain,
                   dispatch_command, session_key, session_user)
from storage.db import Database

CORAL = "#d97757"


class JotaroTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #status { height: 1; padding: 0 2; background: $panel; color: $text-muted; }
    #chat { height: 1fr; padding: 1 2; background: $surface; }
    #prompt {
        height: 3;                 /* 1 line of text + the rounded border */
        margin: 1 2 1 2;           /* breathing room: above, sides, and off the footer */
        border: round #d97757;
        background: $surface;
    }
    #prompt:focus { border: round #ffb59d; }   /* brighter coral when active */
    #live { height: auto; max-height: 8; padding: 0 2; color: $text-muted; }
    Footer { background: $panel; }
    """
    BINDINGS = [("ctrl+c", "quit", "quit"), ("ctrl+l", "clear", "clear")]
    SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.db = Database(self.cfg.db_path)
        self.brain = build_brain(self.cfg, self.db, None)
        # bind to the same (user, cwd) session as the CLI → shared context across both
        self.sess_id = session_key(session_user(None), os.getcwd())
        loaded = self.db.load_session(self.sess_id)
        self.history = loaded if loaded else self.brain.new_history()
        self._resumed_turns = sum(1 for m in (loaded or []) if m.get("role") == "user")
        self._busy = False          # a request is in flight (drives the spinner)
        self._phase = ""            # what we're doing now: thinking / running <tool>
        self._spin = 0
        self._stream: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static(self._status_text(), id="status")
        yield RichLog(id="chat", wrap=True, markup=True, highlight=False)
        yield Static("", id="live")          # transient: spinner-streamed answer preview
        yield Input(placeholder="ask in Thai or English · / for commands", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "CHENG AI"
        self.sub_title = "SME IT Agent · local · offline"
        log = self.query_one("#chat", RichLog)
        log.write(Text("✻ CHENG AI", style=f"bold {CORAL}"))
        if self._resumed_turns:
            log.write(Text(f"↻ resumed {self._resumed_turns} turn(s) from this folder "
                           f"(shared with the CLI) — context is loaded", style="grey58"))
        else:
            log.write(Text("ask about offline PCs, login fails, lockouts, alerts — or /help",
                           style="grey58"))
        prompt = self.query_one("#prompt", Input)
        prompt.border_title = "ask"                 # label on the rounded box
        prompt.border_subtitle = "Enter ⏎ · / cmds"
        prompt.focus()
        self.set_interval(0.09, self._tick)          # animate the working spinner

    def _tick(self) -> None:
        if not self._busy:
            return
        self._spin = (self._spin + 1) % len(self.SPIN)
        self._set_status(f" [b]{self.SPIN[self._spin]}[/] {self._phase}")

    def _status_text(self) -> str:
        online = "[green]●[/] online" if self.brain.is_available() else "[red]●[/] offline"
        sk = f"skills:{len(self.brain.skill_names())}" if self.brain.skills_enabled else "skills:off"
        return f" [b]{self.cfg.ollama_model}[/]  {online}   monitor · read-only   {sk}"

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def action_clear(self) -> None:
        self.history = self.brain.new_history()
        self.db.delete_session(self.sess_id)        # wipe this folder's shared context
        self.query_one("#chat", RichLog).clear()

    @on(Input.Submitted, "#prompt")
    def _submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one("#prompt", Input).value = ""
        if not text:
            return
        log = self.query_one("#chat", RichLog)
        log.write(Text.assemble(("❯ ", f"bold {CORAL}"), (text, "bold")))

        action = dispatch_command(text)
        if action == "exit":
            self.exit()
        elif action == "help":
            log.write(Text.from_markup(HELP))
        elif action == "status":
            s = self.db.system_summary()
            log.write(f"nodes [green]{s['nodes_up']} up[/] / [red]{s['nodes_down']} down[/]"
                      f" · fails {s['login_fail_users_24h']} · locked {s['locked_accounts_24h']}"
                      f" · alerts {s['alerts_pending']}")
        elif action == "memory":
            mems = self.db.recent_memory(50)
            log.write("\n".join(f"  #{m['id']} {m['text']}" for m in mems) or "(no memories)")
        elif action == "remember":
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                log.write(f"[{CORAL}]✓[/] remembered (#{self.db.add_memory(parts[1].strip())})")
        elif action == "skills":
            log.write(f"skills: {'on' if self.brain.skills_enabled else 'off'} "
                      f"({len(self.brain.skill_names())})  " + ", ".join(self.brain.skill_names()))
        elif action == "clear":
            self.action_clear()
        else:
            self._ask(text)

    @work(thread=True)
    def _ask(self, text: str) -> None:
        log = self.query_one("#chat", RichLog)
        live = self.query_one("#live", Static)
        self._stream = []
        self._busy = True
        self._phase = "thinking…"

        def on_tool(name: str, args: dict) -> None:
            self._phase = f"running {name}…"          # spinner reflects the live step
            arg_s = ", ".join(f"{k}={_summarize(v) if not isinstance(v, (str, int, float)) else v}"
                              for k, v in args.items())
            self.call_from_thread(log.write, Text.assemble(("⏺ ", CORAL), (name, "bold"),
                                                           (f"({arg_s})", "grey58")))

        def on_result(name: str, result: object) -> None:
            self._phase = "thinking…"
            self.call_from_thread(log.write, Text.assemble(("  ⎿ ", "grey58"),
                                                           (_summarize(result), "grey58")))

        def on_token(delta: str) -> None:
            d = _CJK.sub("", delta)                   # strip Chinese leakage per token
            if not d:
                return
            self._phase = "writing…"
            self._stream.append(d)
            tail = "".join(self._stream)[-700:]       # show the growing answer (tail)
            self.call_from_thread(live.update, Text("▌ " + tail, style="grey70"))

        ans = None
        try:
            ans = self.brain.ask(self.history, text, on_tool=on_tool,
                                 on_result=on_result, on_token=on_token)
        except OllamaUnavailable as exc:
            self.call_from_thread(log.write, f"[red]✖ Ollama unreachable:[/] {exc}")
        finally:
            self._busy = False
        self.call_from_thread(live.update, "")         # clear the transient preview
        if ans is not None:
            self.call_from_thread(log.write, Markdown(ans or "_(no answer)_"))
        _autosave(self.db, self.sess_id, self.history)  # persist → shared with the CLI
        self.call_from_thread(self._set_status, self._status_text())


def main() -> None:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    JotaroTUI().run()


if __name__ == "__main__":
    main()
