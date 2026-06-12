"""Fan-out helper — split work across sub-agents that each hold their own context.

`parallel_map` runs a function over many items on a small thread pool (brain.ask is
I/O-bound on the Ollama HTTP call, so threads overlap the waits). `fan_out_summarize`
is the headline use: a "context firewall" — a huge text is chunked, one throwaway
sub-agent summarizes each chunk in ITS OWN context, and only the distilled summaries
come back to be merged. The raw bulk never enters the main context window.

NOTE on speed: one local Ollama serializes inference, so the win here is CONTEXT
management (each sub-agent sees only its slice), not wall-clock — real parallel speed
needs OLLAMA_NUM_PARALLEL + VRAM or multiple backends. Keep max_workers low on a small box.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

log = logging.getLogger(__name__)


def parallel_map(items: list[Any], fn: Callable[[Any], Any], max_workers: int = 2) -> list[Any]:
    """Apply fn to each item across a capped thread pool, preserving order. A failing
    item becomes None (never raises) so one bad slice can't sink the batch."""
    if not items:
        return []

    def safe(it: Any) -> Any:
        try:
            return fn(it)
        except Exception:  # noqa: BLE001 — isolate sub-agent failures
            log.exception("parallel_map: item failed")
            return None

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        return list(ex.map(safe, items))


def chunk_text(text: str, size: int = 2500) -> list[str]:
    """Split text into ~size-char chunks, preferring to break on newlines."""
    text = text or ""
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl
        chunks.append(text[start:end])
        start = end
    return chunks


def fan_out_summarize(
    text: str,
    brain_factory: Callable[[], Any],
    chunk_chars: int = 2500,
    max_workers: int = 2,
    reduce: bool = True,
) -> tuple[str, int]:
    """Chunk → summarize each chunk with a fresh sub-agent (parallel) → merge. Returns
    (summary, n_chunks). `brain_factory()` must return a fresh Brain each call."""
    chunks = chunk_text(text, chunk_chars)
    if not chunks:
        return "", 0

    def work(chunk: str) -> str:
        b = brain_factory()
        return b.ask(b.new_history(), f"Summarize this section concisely:\n\n{chunk}")

    summaries = [s for s in parallel_map(chunks, work, max_workers) if s]
    if len(summaries) <= 1 or not reduce:
        return "\n".join(summaries), len(chunks)

    # reduce step: one more sub-agent merges the section summaries
    b = brain_factory()
    joined = "\n".join(f"- {s}" for s in summaries)
    merged = b.ask(b.new_history(),
                   f"Combine these section summaries into one concise summary:\n{joined}")
    return merged, len(chunks)
