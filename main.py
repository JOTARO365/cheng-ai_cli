"""SME IT Agent — entrypoint.

Phase 1 is chatbot-first: the chat UI is Open WebUI (separate process), which talks
to Ollama and reaches our live data through the FastAPI tool server started here.

    python main.py                 # start the IT-context tool server
    python main.py --host 0.0.0.0  # bind all interfaces (on-prem LAN only!)

Then point Open WebUI at this server (Settings → Tools → add the URL). See
docs/setup.md for the full wiring.
"""
from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from config import load_config, setup_logging
from storage.db import Database
from webtools.server import create_app

log = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SME IT Agent — IT-context tool server")
    p.add_argument(
        "--host",
        default=os.getenv("TOOL_SERVER_HOST", "127.0.0.1"),
        help="bind address (default 127.0.0.1; use the LAN IP only on-prem)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TOOL_SERVER_PORT", "8000")),
        help="bind port (default 8000)",
    )
    return p.parse_args()


def main() -> None:
    setup_logging()  # also forces stdout/stderr to UTF-8 for Thai output
    args = parse_args()
    cfg = load_config()
    db = Database(cfg.db_path)
    app = create_app(db)

    log.info("config: %s", cfg.masked())
    print("\n🖥️  SME IT Agent — IT-context tool server")
    print(f"   serving tools at  http://{args.host}:{args.port}")
    print(f"   OpenAPI schema    http://{args.host}:{args.port}/openapi.json")
    print("   → In Open WebUI: Settings → Tools → add the URL above.")
    print("   (Read-only. Phase 1 monitors + reports; it never changes anything.)\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
