"""PydanticAI adapter — file assistant with NATIVE human-in-the-loop approval.

This is the "rich runtime" option of the Hybrid: instead of our hand-built permission
gate (ai/brain.py) + hand-built MCP, PydanticAI gives both natively. Here it drives
the SAME filesystem dispatch (ai/fs_tools.py) but:
  - write/edit/make_dir are marked `requires_approval=True` → PydanticAI pauses the run
    and returns a DeferredToolRequests; we ask the user, then resume with the answer.
  - the workspace defaults to the FOLDER THE CLI IS RUN FROM (cwd), sandboxed by the
    same path-jail in fs_tools.

Optional dependency:  pip install -r requirements-pydantic.txt
Run:  python -m ai.pydantic_agent --ask "what files are here?"
      python -m ai.pydantic_agent --workspace D:/some/dir
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ai.brain import _CJK  # reuse the same CJK detector as the built-in runtime
from ai.fs_tools import make_fs_dispatcher
from ai.prompts import SYSTEM_FS

# Needed in module globals so PydanticAI can resolve the `RunContext[FsDeps]` tool
# annotations (they're strings under `from __future__ import annotations`). Guarded
# so importing this module without the optional extra doesn't hard-fail.
try:
    from pydantic_ai import RunContext
except ImportError:
    RunContext = None  # type: ignore[assignment,misc]

_INSTALL_HINT = ("PydanticAI not installed (optional extra). Run:\n"
                 "    pip install -r requirements-pydantic.txt")


@dataclass
class FsDeps:
    """Typed dependency passed to every tool (PydanticAI's ctx.deps) — our sandboxed
    filesystem dispatcher, rooted at the workspace."""
    dispatch: Callable[[str, dict[str, Any]], Any]


def build_agent(cfg: Any) -> Any:
    """Build a PydanticAI agent over the local Ollama model with the fs tools.
    Reads/lists run freely; writes/edits/mkdir require user approval."""
    try:
        from pydantic_ai import Agent, DeferredToolRequests
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.ollama import OllamaProvider
    except ImportError as exc:  # pragma: no cover
        raise ImportError(_INSTALL_HINT) from exc

    base_url = cfg.ollama_host.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"  # Ollama's OpenAI-compatible endpoint
    model = OpenAIChatModel(cfg.ollama_model, provider=OllamaProvider(base_url=base_url))

    agent = Agent(
        model,
        deps_type=FsDeps,
        output_type=[str, DeferredToolRequests],  # lets the run pause for approval
        instructions=SYSTEM_FS,
    )

    @agent.output_validator
    def _strip_chinese(output: Any) -> Any:
        """Same guard as the built-in runtime: qwen2.5 leaks Chinese into Thai — strip
        any CJK from the final text so the user never sees it. (DeferredToolRequests
        outputs pass through untouched.)"""
        if isinstance(output, str) and _CJK.search(output):
            return _CJK.sub("", output).strip()
        return output

    @agent.tool
    def read_file(ctx: "RunContext[FsDeps]", path: str) -> Any:
        """Read a text file inside the workspace."""
        return ctx.deps.dispatch("read_file", {"path": path})

    @agent.tool
    def list_dir(ctx: "RunContext[FsDeps]", path: str = ".") -> Any:
        """List files/folders in a workspace directory (default the root)."""
        return ctx.deps.dispatch("list_dir", {"path": path})

    @agent.tool(requires_approval=True)
    def write_file(ctx: "RunContext[FsDeps]", path: str, content: str) -> Any:
        """Create or overwrite a file (requires user approval)."""
        return ctx.deps.dispatch("write_file", {"path": path, "content": content})

    @agent.tool(requires_approval=True)
    def edit_file(ctx: "RunContext[FsDeps]", path: str, old_string: str, new_string: str) -> Any:
        """Replace old_string with new_string in a file (requires user approval)."""
        return ctx.deps.dispatch(
            "edit_file", {"path": path, "old_string": old_string, "new_string": new_string})

    @agent.tool(requires_approval=True)
    def make_dir(ctx: "RunContext[FsDeps]", path: str) -> Any:
        """Create a directory inside the workspace (requires user approval)."""
        return ctx.deps.dispatch("make_dir", {"path": path})

    return agent


def _args_of(call: Any) -> dict[str, Any]:
    a = getattr(call, "args", None)
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except json.JSONDecodeError:
            return {}
    return a if isinstance(a, dict) else {}


def run(agent: Any, question: str, base_dir: str | Path, confirm: Callable[[str, dict], bool],
        message_history: list | None = None) -> tuple[str, list]:
    """Run one turn with the native approval loop. `confirm(tool, args)->bool` is
    called for each write the model wants to make. Returns (answer, message_history)."""
    from pydantic_ai import DeferredToolRequests, DeferredToolResults

    deps = FsDeps(make_fs_dispatcher(base_dir))
    result = agent.run_sync(question, deps=deps, message_history=message_history)

    while isinstance(result.output, DeferredToolRequests):
        results = DeferredToolResults()
        for call in result.output.approvals:
            results.approvals[call.tool_call_id] = confirm(call.tool_name, _args_of(call))
        result = agent.run_sync(
            deps=deps, message_history=result.all_messages(), deferred_tool_results=results)

    return str(result.output), result.all_messages()


# --------------------------------------------------------------------------
def _cli() -> None:
    import argparse

    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    from config import load_config

    parser = argparse.ArgumentParser(description="CHENG AI file assistant (PydanticAI)")
    parser.add_argument("--workspace", default=".",
                        help="folder to operate in (default: current directory)")
    parser.add_argument("--ask", help="one-shot question, then exit")
    args = parser.parse_args()

    base = Path(args.workspace).resolve()
    cfg = load_config()
    agent = build_agent(cfg)

    def confirm(tool: str, a: dict) -> bool:
        preview = ", ".join(f"{k}={str(v)[:50]}" for k, v in a.items())
        print(f"  ⚠ confirm write: {tool}({preview})")
        return input("  proceed? [y/N] ").strip().lower() in ("y", "yes")

    print(f"CHENG AI file assistant (PydanticAI) · workspace: {base}")
    if args.ask:
        answer, _ = run(agent, args.ask, base, confirm)
        print(answer)
        return

    history: list = []
    while True:
        try:
            q = input("\nit › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nsession ended.")
            break
        if not q:
            continue
        if q.lower() in ("/exit", "/quit"):
            break
        answer, history = run(agent, q, base, confirm, history)
        print(answer)


if __name__ == "__main__":
    _cli()
