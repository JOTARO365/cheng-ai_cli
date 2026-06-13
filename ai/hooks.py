"""Pre/post-tool hooks — configurable guard points around tool execution
(Claude-Code-style PreToolUse / PostToolUse), gap #8.

A hook is a plain Python callable registered against a tool-name matcher. A *pre*
hook runs before a tool and may:
  • ALLOW  — let it run (return ALLOW or None),
  • DENY   — block it; the reason is fed back to the model instead of a result,
  • MODIFY — rewrite the call's args before it runs (e.g. clamp a limit, redact a path).
A *post* hook runs after a tool and may rewrite the result (e.g. truncate, scrub).

Hooks live in code so guards (block `rm -rf`, clamp a query) are unit-testable, and a
HookRegistry is attached to a Brain via `hooks=`. The Brain runs every tool call
through the registry in `_execute`, so model-driven and internal calls are both covered.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class HookDecision:
    action: str = "allow"                  # allow | deny | modify
    reason: str = ""                       # why (shown to the model on deny)
    args: dict[str, Any] | None = None     # replacement args (modify only)


ALLOW = HookDecision("allow")


def deny(reason: str) -> HookDecision:
    return HookDecision("deny", reason=reason)


def modify(args: dict[str, Any], reason: str = "") -> HookDecision:
    return HookDecision("modify", reason=reason, args=dict(args))


# name, args -> decision (None == allow)
PreHook = Callable[[str, dict[str, Any]], "HookDecision | None"]
# name, args, result -> replacement result (None == keep)
PostHook = Callable[[str, dict[str, Any], Any], Any]


def _match(pattern: str, name: str) -> bool:
    return pattern == "*" or pattern == name or fnmatch.fnmatch(name, pattern)


class HookRegistry:
    """An ordered set of pre/post hooks keyed by a tool-name pattern ('*', an exact
    name, or an fnmatch glob like 'excel_*'). First DENY wins; MODIFYs chain."""

    def __init__(self) -> None:
        self._pre: list[tuple[str, PreHook]] = []
        self._post: list[tuple[str, PostHook]] = []

    def pre(self, pattern: str, fn: PreHook) -> "HookRegistry":
        self._pre.append((pattern, fn))
        return self                                   # chainable

    def post(self, pattern: str, fn: PostHook) -> "HookRegistry":
        self._post.append((pattern, fn))
        return self

    def run_pre(self, name: str, args: dict[str, Any]) -> HookDecision:
        """Apply matching pre-hooks. Returns deny (first one wins), or modify if any
        hook changed the args, else ALLOW. Hooks see args as mutated by earlier ones."""
        cur = dict(args)
        for pattern, fn in self._pre:
            if not _match(pattern, name):
                continue
            dec = fn(name, cur)
            if dec is None or dec.action == "allow":
                continue
            if dec.action == "deny":
                return dec
            if dec.action == "modify" and dec.args is not None:
                cur = dict(dec.args)
        return modify(cur) if cur != args else ALLOW

    def run_post(self, name: str, args: dict[str, Any], result: Any) -> Any:
        for pattern, fn in self._post:
            if _match(pattern, name):
                new = fn(name, args, result)
                if new is not None:
                    result = new
        return result

    def __len__(self) -> int:
        return len(self._pre) + len(self._post)

    def describe(self) -> list[str]:
        """Human-readable list of active hooks (for `/hooks`)."""
        out = [f"pre  {pat:14} → {getattr(fn, '__name__', repr(fn))}" for pat, fn in self._pre]
        out += [f"post {pat:14} → {getattr(fn, '__name__', repr(fn))}" for pat, fn in self._post]
        return out


# ---- built-in guards --------------------------------------------------------
# Catastrophic shell commands the agent should NEVER run unattended, even if the
# user would otherwise confirm. These are hard blocks (deny), not confirm prompts.
_DANGEROUS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(?:-\w+\s+)*-\w*[rf]", re.I), "recursive/forced delete (rm -rf)"),
    (re.compile(r"\b(?:mkfs|format)\b", re.I), "filesystem format"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/", re.I), "raw disk write (dd of=/dev/...)"),
    (re.compile(r"\bdel\s+/[a-z]", re.I), "recursive Windows delete (del /s /q)"),
    (re.compile(r"\bRemove-Item\b[^\n]*-Recurse", re.I), "recursive delete (Remove-Item -Recurse)"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b", re.I), "power/shutdown command"),
    (re.compile(r":\(\)\s*\{[^}]*\}\s*;\s*:", re.S), "fork bomb"),
    (re.compile(r">\s*/dev/sd[a-z]", re.I), "overwrite a raw disk device"),
]


def dangerous_shell_guard(name: str, args: dict[str, Any]) -> HookDecision:
    """Block destructive shell commands outright (run_command)."""
    cmd = str(args.get("command", ""))
    for rx, why in _DANGEROUS:
        if rx.search(cmd):
            return deny(f"blocked by safety hook: {why}. "
                        f"If you truly intend this, run it yourself in a terminal.")
    return ALLOW


def default_safe_hooks() -> HookRegistry:
    """The hooks JOTARO installs by default (disable with --no-hooks)."""
    return HookRegistry().pre("run_command", dangerous_shell_guard)
