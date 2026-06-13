"""Agent skills — loadable markdown runbooks with progressive loading.

A skill is a `.md` file with YAML-ish front-matter (name + description) and a body of
instructions:

    ---
    name: account-lockout-response
    description: Use when an account is locked out (Event 4740) — how to triage it.
    ---
    1. Check recent login failures for that user ...

Progressive loading (the key mechanic, per the agent-skills pattern): at startup only
each skill's name+description is injected into the system prompt — that's the *trigger*.
The full body is pulled into context only when the model calls `load_skill(name)`. So
many skills cost almost nothing until one is actually used.

Skills are read from a local directory (default: <project>/skills), so you can drop in
your own skill.md files. Toggle on/off at runtime.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

SKILL_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "Load a skill's instructions by name when its description matches the "
                "task. Pass `query` (the task/keywords) so only the relevant SECTION of a "
                "large skill is returned (saves context). Call BEFORE doing the task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "the skill's name"},
                    "query": {"type": "string",
                              "description": "the task/keywords — returns just the matching section of a big skill"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_skill",
            "description": "Search available skills by keyword (use when many skills exist and "
                           "you need to discover which one fits). Returns matching name+description; "
                           "then call load_skill.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "task keywords"}},
                "required": ["query"],
            },
        },
    },
]


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path


def _parse(text: str, fallback_name: str) -> tuple[str, str, str]:
    """Return (name, description, body). Tolerant of missing front-matter."""
    name, desc, body = fallback_name, "", text.strip()
    if text.lstrip().startswith("---"):
        t = text.lstrip()
        end = t.find("---", 3)
        if end != -1:
            front, body = t[3:end], t[end + 3:].strip()
            for line in front.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k, v = k.strip().lower(), v.strip()
                    if k == "name" and v:
                        name = v
                    elif k == "description":
                        desc = v
    return name, desc, body


def discover_skills(dirs: Any) -> dict[str, Skill]:
    """Load skills from one or more directories. In each: every top-level `*.md` AND
    every `SKILL.md` at any depth is a skill — so this works for both flat skill files
    and the Claude-style `<dir>/<name>/SKILL.md` layout (e.g. ~/.claude)."""
    if not dirs:
        return {}
    if isinstance(dirs, (str, Path)):
        dirs = [dirs]
    skills: dict[str, Skill] = {}
    for d in dirs:
        base = Path(d)
        if not base.is_dir():
            continue
        paths = sorted(set(base.glob("*.md")) | set(base.rglob("SKILL.md")))
        for p in paths:
            try:
                name, desc, body = _parse(p.read_text(encoding="utf-8"), p.parent.name
                                          if p.name.upper() == "SKILL.MD" else p.stem)
            except OSError:
                continue
            skills.setdefault(name, Skill(name=name, description=desc or "(no description)",
                                          body=body, path=p))
        log.info("skills: scanned %s", base)
    log.info("loaded %d skill(s)", len(skills))
    return skills


CATALOG_CAP = 30  # don't dump hundreds of skills into a small model's context


def catalog(skills: dict[str, Skill], limit: int = CATALOG_CAP) -> str:
    """The name+description list injected into the system prompt (the triggers). Capped
    so a large skill dir (e.g. ~/.claude with 65) can't bloat/melt a small model — the
    rest stay loadable by name via load_skill."""
    items = list(skills.values())
    lines = [f"- {s.name}: {s.description}" for s in items[:limit]]
    if len(items) > limit:
        lines.append(f"- (+{len(items) - limit} more skills — call load_skill by name)")
    return "\n".join(lines)


_STOPWORDS = {
    "the", "and", "for", "you", "are", "can", "how", "what", "this", "that", "with",
    "give", "only", "please", "fix", "make", "need", "want", "show", "tell", "from",
    "input", "output", "return", "function", "code", "empty", "value", "when", "into",
}


def search_skills(skills: dict[str, Skill], query: str, limit: int = 5,
                  min_hits: int = 1) -> list[dict[str, str]]:
    """Keyword-overlap search over name+description — for find_skill when there are too
    many skills to list. `min_hits` raises the bar: gating tool-visibility passes a higher
    value so a single casual word doesn't surface the skill tools to a small model."""
    words = {w for w in query.lower().split() if len(w) > 2 and w not in _STOPWORDS}
    if not words:
        return []
    scored = []
    for s in skills.values():
        hay = (s.name + " " + s.description).lower()
        hits = sum(1 for w in words if w in hay)
        if hits >= min_hits:
            scored.append((hits, s))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [{"name": s.name, "description": s.description} for _, s in scored[:limit]]


def skills_block(skills: dict[str, Skill]) -> str:
    """What to inject into the system prompt: the full catalog if there are few skills,
    otherwise a hint to discover them with find_skill (so a big dir can't bloat context)."""
    if len(skills) <= CATALOG_CAP:
        return ("Available skills (call load_skill(name) when one matches the task):\n"
                + catalog(skills))
    return (f"You have {len(skills)} skills available — too many to list. Call "
            f"find_skill(query) to find relevant ones by keyword, then load_skill(name).")


# --------------------------------------------------------------------------
# Section-level loading — only feed the LLM the relevant part of a big skill.
# (The "find the heading, read that part" idea, in idiomatic Python — no FFI.)
# --------------------------------------------------------------------------
SMALL_SKILL = 900  # chars; at or below this we just return the whole skill


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, text) blocks by '#' headings (text keeps the
    heading line). No headings → one block."""
    out: list[tuple[str, str]] = []
    head, buf = "", []
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            if buf:
                out.append((head, "\n".join(buf).strip()))
            head, buf = line.lstrip("# ").strip(), [line]
        else:
            buf.append(line)
    if buf:
        out.append((head, "\n".join(buf).strip()))
    return [(h, t) for h, t in out if t]


def select_skill_content(skill: Skill, query: str = "") -> dict[str, Any]:
    """Return the whole skill if it's small, else only the section(s) whose
    heading/text best match `query`, plus a table of contents of the rest."""
    sections = split_sections(skill.body)
    if len(skill.body) <= SMALL_SKILL or len(sections) <= 1 or not query.strip():
        return {"name": skill.name, "instruction": skill.body}

    words = {w for w in query.lower().split() if len(w) > 2}
    scored = sorted(
        ((sum(1 for w in words if w in (h + " " + t).lower()), h, t) for h, t in sections),
        key=lambda x: -x[0],
    )
    top = [s for s in scored if s[0] > 0][:2] or [scored[0]]
    return {
        "name": skill.name,
        "sections_returned": [h for _, h, _ in top],
        "instruction": "\n\n".join(t for _, _, t in top),
        "all_sections": [h for h, _ in sections],
    }
