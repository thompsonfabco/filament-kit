"""Run the web unit: `python -I -m filament_kit.web` (filament-kit-web.service).

Plain HTTP on 127.0.0.1:<web.port>, one worker: the remote module's nginx router owns TLS and the public port and
forwards here. The client address comes from X-Forwarded-For (which nginx overwrites), trusted from 127.0.0.1 only,
so the LAN-only checks see the real caller.
"""
from __future__ import annotations

import logging
import sys

import uvicorn

from .. import config
from .app import NotConfigured, build_app

TRUSTED_PROXY = "127.0.0.1"


def _log_to_journal() -> None:
    app_log = logging.getLogger("filament_kit")
    if not app_log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        app_log.addHandler(handler)
        app_log.propagate = False
    app_log.setLevel(logging.INFO)


def uvicorn_options(cfg: dict) -> dict:
    return {"host": "127.0.0.1", "port": int(cfg["web"]["port"]), "proxy_headers": True,
            "forwarded_allow_ips": TRUSTED_PROXY, "server_header": False, "log_level": "info", "workers": 1}


def main() -> int:
    _log_to_journal()
    cfg = config.load()
    try:
        app = build_app(cfg)
    except NotConfigured as e:
        print(f"filament-kit web: {e}", file=sys.stderr)
        return 2
    uvicorn.run(app, **uvicorn_options(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
