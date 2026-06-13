"""Local-model agent loop (the harness around Ollama) for JOTARO AI CLI.

The HARNESS owns the loop, not the model (ReAct): send the question + tool specs to
Ollama → if the model asks for a tool, WE run it and feed the result back → repeat
until the model answers. Deterministic control flow, a hard step cap, and the guards
a bare 3B model needs.

Guards this harness enforces:
- **stop condition** — `max_steps` caps the loop.
- **permission gate** — tools named in `confirm_tools` are NOT run until `confirm()`
  approves (used by --workspace file writes). Read-only agents pass neither → no gate.
- **language guard** — qwen2.5 (a Chinese-origin model) sometimes leaks Chinese into
  Thai answers; low temperature + a one-shot regenerate keep output Thai/English.

Decoupled for reuse: `Brain` takes its persona (`system`), tool specs (`tools`), and a
`dispatcher(name,args)` as arguments — so a supervisor can spin up specialist brains,
and the LangChain adapter can wrap the same pieces.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

import httpx

from ai.memory_tools import MEMORY_TOOL_SPECS
from ai.skills import (DEFAULT_SKILLS_DIR, SKILL_TOOL_SPECS, discover_skills,
                       search_skills, select_skill_content, skills_block)
from ai.prompts import SYSTEM_CHAT, SYSTEM_SUMMARIZER
from ai.tools import TOOL_SPECS, dispatch as _db_dispatch
from storage.db import Database

log = logging.getLogger(__name__)

# CJK ranges — used to detect Chinese leaking into a Thai/English answer.
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


class OllamaUnavailable(RuntimeError):
    """Raised when the local Ollama server can't be reached — the caller should fall
    back (e.g. tell IT the AI is offline) rather than crash."""


# A dispatcher runs a tool by name and returns JSON-ready data.
Dispatcher = Callable[[str, dict[str, Any]], Any]
Confirm = Callable[[str, dict[str, Any]], bool]


class Brain:
    def __init__(
        self,
        host: str,
        model: str,
        db: Database,
        *,
        system: str = SYSTEM_CHAT,
        tools: list[dict[str, Any]] | None = None,
        dispatcher: Dispatcher | None = None,
        confirm_tools: frozenset[str] | set[str] = frozenset(),
        confirm: Confirm | None = None,
        timeout: float = 120.0,
        max_steps: int = 6,
        temperature: float = 0.2,
        skills_dir: Any = DEFAULT_SKILLS_DIR,
        skills_enabled: bool = True,
        context_budget: int = 16_000,
        keep_recent_turns: int = 2,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.db = db
        self.system = system
        # every brain also gets the memory tools (remember/recall), handled in _execute
        self.tools = list(TOOL_SPECS if tools is None else tools) + MEMORY_TOOL_SPECS
        # progressive-loading skills (skill.md runbooks) — toggleable
        self._skills = discover_skills(skills_dir)
        self._disabled: set[str] = set()     # individually turned-off skills
        if self._skills:
            self.tools = self.tools + SKILL_TOOL_SPECS
        self.skills_enabled = skills_enabled and bool(self._skills)
        # default dispatcher = the read-only IT-monitor tools over the DB
        self._dispatcher: Dispatcher = dispatcher or (lambda n, a: _db_dispatch(n, a, db))
        self.confirm_tools = set(confirm_tools)
        self.confirm = confirm
        self.timeout = timeout
        self.max_steps = max_steps
        self.temperature = temperature
        # context compaction: fold old turns into a summary when history grows past
        # context_budget (chars ≈ tokens*4), always keeping the last keep_recent_turns
        self.context_budget = context_budget
        self.keep_recent_turns = keep_recent_turns

    @classmethod
    def from_config(cls, cfg: Any, db: Database, **kw: Any) -> "Brain":
        return cls(cfg.ollama_host, cfg.ollama_model, db, **kw)

    def new_history(self) -> list[dict[str, Any]]:
        """Fresh conversation seeded with the system persona + anything the user has
        told the agent to remember (so it 'knows' those facts without calling recall)."""
        text = self.system
        mems = self.db.recent_memory(20)
        if mems:
            text += "\n\nThings the user told you to remember:\n" + "\n".join(
                f"- {m['text']}" for m in reversed(mems))
        active = self._active()
        if self.skills_enabled and active:
            text += "\n\n" + skills_block(active)
        return [{"role": "system", "content": text}]

    # ---- skills control ---------------------------------------------------
    def _active(self) -> dict[str, Any]:
        return {n: s for n, s in self._skills.items() if n not in self._disabled}

    def set_skills_enabled(self, on: bool) -> bool:
        self.skills_enabled = bool(on) and bool(self._skills)
        return self.skills_enabled

    def set_skill(self, name: str, on: bool) -> bool:
        """Turn ONE skill on/off by name. Returns True if the skill exists."""
        if name not in self._skills:
            return False
        self._disabled.discard(name) if on else self._disabled.add(name)
        return True

    def skill_status(self) -> list[tuple[str, bool]]:
        return [(n, n not in self._disabled) for n in self._skills]

    def load_skills_from(self, skills_dir: Any) -> int:
        """Pull skill.md files from a local directory and enable them. Returns count."""
        self._skills = discover_skills(skills_dir)
        if self._skills and not any(
            t["function"]["name"] == "load_skill" for t in self.tools
        ):
            self.tools = self.tools + SKILL_TOOL_SPECS
        self.skills_enabled = bool(self._skills)
        return len(self._skills)

    def skill_names(self) -> list[str]:
        return list(self._skills)

    def is_available(self) -> bool:
        try:
            return httpx.get(f"{self.host}/api/tags", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        """Models the local Ollama has pulled (for the /model command)."""
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=5.0)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return []

    def ask(
        self,
        history: list[dict[str, Any]],
        question: str,
        on_tool: Callable[[str, dict[str, Any]], None] | None = None,
        on_result: Callable[[str, Any], None] | None = None,
        on_token: Callable[[str], None] | None = None,
        on_compact: Callable[[int, int], None] | None = None,
    ) -> str:
        """Run one user turn through the ReAct loop. Mutates `history`, returns the
        model's final answer. on_tool(name,args) fires before a tool runs;
        on_result(name,result) after (⎿ display); on_token(delta) streams the answer
        text token-by-token (when set, the answer is NOT language-guard-regenerated —
        the caller is expected to strip CJK per token); on_compact(before,after) fires
        when old turns were folded into a summary to stay within the context budget."""
        self._compact(history, on_compact)
        history.append({"role": "user", "content": question})
        last: dict[str, Any] = {}
        for _ in range(self.max_steps):
            last = self._chat(history, on_token=on_token)
            history.append(last)
            tool_calls = last.get("tool_calls") or []
            if not tool_calls:
                final = (last.get("content") or "").strip()
                if on_token is not None:
                    # already streamed to the user (the caller strips CJK per-token); just
                    # clean the copy we keep, no re-generate (can't un-stream).
                    return _CJK.sub("", final).strip() if _has_cjk(final) else final
                return self._language_guard(history, final)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = _as_args(fn.get("arguments"))
                if on_tool:
                    on_tool(name, args)
                # tool-error isolation: a tool that *raises* (buggy MCP/custom tool)
                # must not kill the turn — feed the error back so the model can recover
                # or report it. (OllamaUnavailable comes from _chat, not here; Keyboard-
                # Interrupt/SystemExit are BaseException, so `except Exception` won't eat them.)
                try:
                    result = self._execute(name, args)
                except Exception as exc:  # noqa: BLE001
                    log.warning("tool %r raised, isolating: %s", name, exc)
                    result = {"error": f"tool {name!r} failed: {exc}"}
                if on_result:
                    on_result(name, result)
                history.append(_tool_msg(name, result))
        final = (last.get("content") or "").strip()
        if on_token is not None:
            return _CJK.sub("", final).strip()
        return self._language_guard(history, final) or (
            "ขอข้อมูลเครื่องมือหลายรอบแล้วยังไม่ได้คำตอบ — ลองถามให้เจาะจงขึ้นนะ"
        )

    # ---- tools + permission gate -----------------------------------------
    def _execute(self, name: str, args: dict[str, Any]) -> Any:
        if name == "remember":
            text = str(args.get("text", "")).strip()
            if not text:
                return {"error": "nothing to remember"}
            return {"status": "remembered", "id": self.db.add_memory(text)}
        if name == "recall":
            return {"matches": self.db.search_memory(str(args.get("query", "")))}
        if name == "find_skill":
            if not self.skills_enabled:
                return {"error": "skills are turned off"}
            return {"matches": search_skills(self._active(), str(args.get("query", "")))}
        if name == "load_skill":
            if not self.skills_enabled:
                return {"error": "skills are turned off"}
            want = str(args.get("name", ""))
            if want in self._disabled:
                return {"error": "that skill is turned off"}
            sk = self._skills.get(want)
            if not sk:
                return {"error": f"unknown skill; available: {list(self._active())}"}
            return select_skill_content(sk, str(args.get("query", "")))
        if name in self.confirm_tools:
            approved = self.confirm(name, args) if self.confirm else False
            if not approved:
                log.info("permission gate: %s DECLINED", name)
                return {"status": "declined by user — not executed"}
        return self._dispatcher(name, args)

    # ---- language guard (kill Chinese leakage) ---------------------------
    def _language_guard(self, history: list[dict[str, Any]], answer: str,
                        retries: int = 2) -> str:
        """qwen2.5 (Chinese-origin) sometimes leaks Chinese into Thai. Regenerate up
        to `retries` times; if it STILL leaks (weak 3B model), strip the CJK chars as
        a deterministic last resort so the user never sees Chinese."""
        for _ in range(retries):
            if not answer or not _has_cjk(answer):
                return answer
            log.info("language guard: CJK detected, regenerating")
            history.append({"role": "user", "content":
                            "ตอบใหม่อีกครั้งด้วยข้อมูลเดิม เป็นภาษาไทยหรืออังกฤษล้วนเท่านั้น "
                            "ห้ามมีอักษรจีนหรือภาษาอื่นเด็ดขาด"})
            try:
                msg = self._chat(history, use_tools=False)
            except OllamaUnavailable:
                break
            history.append(msg)
            answer = (msg.get("content") or "").strip() or answer
        if answer and _has_cjk(answer):
            log.warning("language guard: still leaking after retries — stripping CJK")
            answer = _CJK.sub("", answer).strip()
        return answer

    # ---- context compaction (keep history under budget) ------------------
    @staticmethod
    def _msg_chars(m: dict[str, Any]) -> int:
        n = len(m.get("content") or "")
        if m.get("tool_calls"):
            n += len(json.dumps(m["tool_calls"], default=str))
        return n

    def _history_chars(self, history: list[dict[str, Any]]) -> int:
        return sum(self._msg_chars(m) for m in history)

    def _recent_tail(self, body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The last `keep_recent_turns` user turns to the end, starting at a clean
        boundary (a user message) so no tool result is split from its assistant call."""
        user_idx = [i for i, m in enumerate(body) if m.get("role") == "user"]
        if len(user_idx) <= self.keep_recent_turns:
            return body
        return body[user_idx[-self.keep_recent_turns]:]

    def _compact(self, history: list[dict[str, Any]],
                 on_compact: Callable[[int, int], None] | None = None) -> None:
        """Fold the oldest turns into a one-message summary when history exceeds the
        budget. Mutates `history` in place (so the caller's reference stays valid),
        always preserving the system message + the recent tail verbatim."""
        before = self._history_chars(history)
        if before <= self.context_budget or len(history) < 2:
            return
        system, body = history[0], history[1:]
        keep = self._recent_tail(body)
        older = body[:len(body) - len(keep)]
        if not older:
            return                                   # the tail alone is already too big
        summary = self._summarize_history(older)
        note = {"role": "user",
                "content": "[earlier conversation — summary]\n" + summary}
        history[:] = [system, note, *keep]
        after = self._history_chars(history)
        log.info("context compaction: %d → %d chars (folded %d msgs)",
                 before, after, len(older))
        if on_compact:
            on_compact(before, after)

    def _summarize_history(self, msgs: list[dict[str, Any]]) -> str:
        """Summarize old turns, preserving facts/decisions/paths/open tasks. Uses the
        model; falls back to deterministic truncation if Ollama is unavailable."""
        transcript = "\n".join(
            f"{m.get('role', '?')}: {(m.get('content') or '').strip()}"
            for m in msgs if (m.get("content") or "").strip())
        try:
            msg = self._chat([
                {"role": "system", "content": SYSTEM_SUMMARIZER},
                {"role": "user", "content":
                    "Summarize this earlier conversation. Preserve facts, decisions, "
                    "file paths, names, and open tasks. Be concise:\n\n" + transcript},
            ], use_tools=False)
            text = (msg.get("content") or "").strip()
            if text:
                return _CJK.sub("", text) if _has_cjk(text) else text
        except OllamaUnavailable:
            log.warning("compaction summarizer offline — using truncated transcript")
        return transcript[-self.context_budget // 2:]   # deterministic fallback

    # ---- Ollama call ------------------------------------------------------
    def _chat(self, messages: list[dict[str, Any]], use_tools: bool = True,
              on_token: Callable[[str], None] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": on_token is not None,
            "options": {"temperature": self.temperature},
        }
        if use_tools:
            payload["tools"] = self.tools

        if on_token is None:
            try:
                r = httpx.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                raise OllamaUnavailable(str(exc)) from exc
            msg = r.json().get("message")
            if not isinstance(msg, dict):
                raise OllamaUnavailable("unexpected response from Ollama (no message)")
            return msg

        # streaming: Ollama returns NDJSON; accumulate content + tool_calls, emit deltas
        content: list[str] = []
        tool_calls = None
        try:
            with httpx.stream("POST", f"{self.host}/api/chat", json=payload,
                              timeout=self.timeout) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    obj = json.loads(line)
                    m = obj.get("message") or {}
                    delta = m.get("content") or ""
                    if delta:
                        content.append(delta)
                        on_token(delta)
                    if m.get("tool_calls"):
                        tool_calls = m["tool_calls"]
                    if obj.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(str(exc)) from exc
        msg: dict[str, Any] = {"role": "assistant", "content": "".join(content)}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg


def _tool_msg(name: str, result: Any) -> dict[str, Any]:
    return {"role": "tool", "tool_name": name,
            "content": json.dumps(result, ensure_ascii=False, default=str)}


def _as_args(raw: Any) -> dict[str, Any]:
    """Ollama usually sends tool arguments as a dict, but some builds send a JSON
    string — accept both."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
