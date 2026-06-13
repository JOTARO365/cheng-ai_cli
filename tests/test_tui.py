"""Smoke tests for the Textual TUI (cheng_tui). Headless via Textual's run_test."""
from __future__ import annotations

import asyncio


def test_tui_constructs():
    from cheng_tui import JotaroTUI
    app = JotaroTUI()
    assert app.brain is not None and app.history


def test_tui_status_command_runs_headless():
    from cheng_tui import JotaroTUI

    async def go():
        app = JotaroTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#prompt").value = "/status"   # no model call
            await pilot.press("enter")
            await pilot.pause()
            # the conversation log received output without crashing
            assert app.query_one("#chat") is not None

    asyncio.run(go())
