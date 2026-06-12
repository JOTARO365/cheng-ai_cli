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
                "Load the full instructions of a skill by name when its description "
                "matches the task. Call this BEFORE doing a task a skill covers."
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "the skill's name"}},
                "required": ["name"],
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


def catalog(skills: dict[str, Skill]) -> str:
    """The name+description list injected into the system prompt (the triggers)."""
    return "\n".join(f"- {s.name}: {s.description}" for s in skills.values())
