"""Run the web unit: `python -I -m filament_kit.web` (filament-kit-web.service).

Plain HTTP on 127.0.0.1:<web.port>, one worker: the remote module's nginx router owns TLS and the public port and
forwards here. The client address comes from X-Forwarded-For (which nginx overwrites), trusted from 127.0.0.1 only,
so the LAN-only checks see the real caller.
"""
from __future__ import annotations

import logging
import sys

import uvicorn

from .. import config, modules
from . import slots
from .app import NotConfigured, build_app

log = logging.getLogger("filament_kit.web")

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


def kit_api_at_start(cfg: dict):
    """With no slot_service and the printers module on, the printer tools use the kit server's API: pair with it
    now (or reuse the saved token), so an earlier unpair is healed by this start and a failure shows in the log."""
    svc = cfg.get("slot_service")
    if (isinstance(svc, dict) and svc.get("state_url")) or "printers" not in modules.enabled(cfg):
        return None
    kit = slots.KitApi()
    try:
        kit.ensure_paired()
    except Exception as e:  # noqa: BLE001 - the rest of the unit works without printer slots
        log.error("cannot pair with the kit server for the printer slot tools: %s: %s", type(e).__name__, e)
    return kit


def main() -> int:
    _log_to_journal()
    cfg = config.load()
    try:
        app = build_app(cfg, kit_api=kit_api_at_start(cfg))
    except NotConfigured as e:
        print(f"filament-kit web: {e}", file=sys.stderr)
        return 2
    uvicorn.run(app, **uvicorn_options(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
