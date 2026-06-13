"""Filesystem tools for CHENG AI's --workspace mode (read / edit / write).

SEPARATE from the read-only IT-monitor tools (ai/tools.py): these MUTATE files, so
they live behind two guards the monitor never needed —
  1. a path-jail (every path is resolved and must stay inside the workspace root), and
  2. WRITE_TOOLS — names the harness must get the user to CONFIRM before running.
Reads/lists are free; writes/edits/mkdir are gated + audit-logged.

`make_fs_dispatcher(base)` returns a dispatcher the Brain calls as dispatch(name, args).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_READ = 50_000  # chars returned by read_file (keep prompts small)

# Tools that change the filesystem → the harness asks the user first.
WRITE_TOOLS: frozenset[str] = frozenset({"write_file", "edit_file", "make_dir"})

FS_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside the workspace. Returns its content.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "path relative to the workspace"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files/folders in a workspace directory (default the root).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "dir relative to the workspace (default '.')"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or OVERWRITE a file with the given content (needs user confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path relative to the workspace"},
                    "content": {"type": "string", "description": "full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace old_string with new_string in an existing file (needs confirmation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string", "description": "exact text to find"},
                    "new_string": {"type": "string", "description": "text to replace it with"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_dir",
            "description": "Create a directory (and parents) inside the workspace (needs confirmation).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files in the workspace by glob pattern (e.g. '*.py', '**/*.xlsx').",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string", "description": "glob, ** allowed"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search file CONTENTS in the workspace for a text query (like grep). Returns file:line matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "glob": {"type": "string", "description": "limit to files matching this glob (default '**/*')"},
                },
                "required": ["query"],
            },
        },
    },
]


class PathEscape(ValueError):
    """A requested path resolves outside the workspace root."""


def _safe(base: Path, rel: str) -> Path:
    """Resolve `rel` under `base` and refuse anything that escapes the root
    (absolute paths elsewhere, ../ traversal, symlink-out)."""
    p = (base / rel).resolve()
    if p != base and base not in p.parents:
        raise PathEscape(f"path escapes workspace: {rel!r}")
    return p


def make_fs_dispatcher(base_dir: str | Path) -> Callable[[str, dict[str, Any]], Any]:
    base = Path(base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)

    def dispatch(name: str, args: dict[str, Any]) -> Any:
        args = args or {}
        try:
            if name == "read_file":
                p = _safe(base, str(args.get("path", "")))
                text = p.read_text(encoding="utf-8", errors="replace")
                return {"path": str(p.relative_to(base)), "content": text[:MAX_READ],
                        "truncated": len(text) > MAX_READ}

            if name == "list_dir":
                p = _safe(base, str(args.get("path", ".")))
                entries = [
                    {"name": c.name, "type": "dir" if c.is_dir() else "file",
                     "size": (c.stat().st_size if c.is_file() else None)}
                    for c in sorted(p.iterdir())
                ]
                return {"path": str(p.relative_to(base)) or ".", "entries": entries}

            if name == "write_file":
                p = _safe(base, str(args.get("path", "")))
                content = str(args.get("content", ""))
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                log.warning("fs WRITE write_file %s (%d bytes)", p, len(content))
                return {"status": "written", "path": str(p.relative_to(base)), "bytes": len(content)}

            if name == "edit_file":
                p = _safe(base, str(args.get("path", "")))
                old, new = str(args.get("old_string", "")), str(args.get("new_string", ""))
                text = p.read_text(encoding="utf-8")
                count = text.count(old)
                if count == 0:
                    return {"error": "old_string not found in file"}
                p.write_text(text.replace(old, new), encoding="utf-8")
                log.warning("fs WRITE edit_file %s (%d replacements)", p, count)
                return {"status": "edited", "path": str(p.relative_to(base)), "replacements": count}

            if name == "make_dir":
                p = _safe(base, str(args.get("path", "")))
                p.mkdir(parents=True, exist_ok=True)
                log.warning("fs WRITE make_dir %s", p)
                return {"status": "created", "path": str(p.relative_to(base))}

            if name == "find_files":
                pat = str(args.get("pattern", "*"))
                hits = []
                for c in base.glob(pat):
                    rp = c.resolve()
                    if c.is_file() and (rp == base or base in rp.parents):
                        hits.append(str(c.relative_to(base)))
                        if len(hits) >= 200:
                            break
                return {"pattern": pat, "files": sorted(hits), "count": len(hits)}

            if name == "search_text":
                query = str(args.get("query", ""))
                if not query:
                    return {"error": "empty query"}
                pat = str(args.get("glob", "**/*"))
                matches = []
                for c in base.glob(pat):
                    if not c.is_file():
                        continue
                    try:
                        for i, line in enumerate(
                            c.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                        ):
                            if query in line:
                                matches.append({"file": str(c.relative_to(base)),
                                                "line": i, "text": line.strip()[:200]})
                                if len(matches) >= 100:
                                    break
                    except OSError:
                        continue
                    if len(matches) >= 100:
                        break
                return {"query": query, "matches": matches, "truncated": len(matches) >= 100}

            return {"error": f"unknown tool {name!r}"}
        except PathEscape as exc:
            return {"error": str(exc)}
        except FileNotFoundError:
            return {"error": "file or directory not found"}
        except OSError as exc:
            return {"error": f"os error: {exc}"}

    return dispatch
