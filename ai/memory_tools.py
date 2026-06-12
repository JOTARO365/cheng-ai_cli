"""Memory tools — let the agent learn from the user across sessions.

The model can call `remember` (store a durable fact the user told it) and `recall`
(look something up). These are handled inside Brain (which owns the DB), and every
Brain also gets recent memories injected into its system prompt so it "knows" them
without having to call recall. This is how a small local model gets smarter over time:
the learning lives in the harness's store, not in the (frozen) model weights.
"""
from __future__ import annotations

from typing import Any

MEMORY_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save a durable fact the user wants you to remember across sessions "
                "(e.g. 'SRV1 is the print server', 'PC20 is in the warehouse'). Call this "
                "when the user says remember / จำไว้."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "the fact to store"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Look up previously remembered facts by keyword.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "what to look up"}},
                "required": ["query"],
            },
        },
    },
]

MEMORY_TOOLS: frozenset[str] = frozenset({"remember", "recall"})
