"""Entry point: `pasture-gateway` (or `python -m pasture`)."""

from __future__ import annotations

import logging
import os
import ssl
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
    context = None
    if cfg.tls_cert:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cfg.tls_cert, cfg.tls_key)
    logging.getLogger("pasture").info(
        "listening on %s:%d%s for %s (enrollment %s)",
        cfg.bind,
        cfg.port,
        " with TLS" if context else "",
        cfg.origin,
        "open" if gateway.auth.enrollment_open() else "closed",
    )
    web.run_app(
        gateway.app(),
        host=cfg.bind,
        port=cfg.port,
        ssl_context=context,
        print=None,
        access_log=None,
        handle_signals=True,
        shutdown_timeout=3.0,  # SSE streams and terminals never finish on their own
    )


if __name__ == "__main__":
    main()
