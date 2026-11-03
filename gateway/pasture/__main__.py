"""Entry point: `pasture-gateway` (or `python -m pasture`)."""

from __future__ import annotations

import logging
import os
import sys

from aiohttp import web

from .app import Gateway
from .config import ConfigError, load


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("PASTURE_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        cfg = load()
    except ConfigError as e:
        raise SystemExit(f"pasture: {e}")
    gateway = Gateway(cfg)
    logging.getLogger("pasture").info(
        "listening on %s:%d for %s (enrollment %s)",
        cfg.bind,
        cfg.port,
        cfg.origin,
        "open" if gateway.auth.enrollment_open() else "closed",
    )
    web.run_app(
        gateway.app(),
        host=cfg.bind,
        port=cfg.port,
        print=None,
        access_log=None,
        handle_signals=True,
        shutdown_timeout=3.0,  # SSE streams and terminals never finish on their own
    )


if __name__ == "__main__":
    main()
