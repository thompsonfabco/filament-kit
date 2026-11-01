"""Run the app API: `python -m filament_kit` (HTTPS on 0.0.0.0:<port>, one worker)."""
import logging
from contextlib import asynccontextmanager

import uvicorn

from . import config
from .api import create_app
from .bridge import discovery, registry
from .bridge.connection import Manager
from .spoolman import Spoolman

log = logging.getLogger(__name__)


def _found(info: dict) -> None:
    registry.detected(info["serial"], info["ip"], info.get("model", ""), info.get("name", ""))


def printer_lifespan(manager, listener_factory=discovery.Listener):
    """Starlette lifespan: the printer connection manager and the SSDP listener live as long as the app.
    A listener that cannot bind (port in use) is logged and skipped; printers already set up still work."""
    @asynccontextmanager
    async def lifespan(app):
        listener = None
        try:
            listener = listener_factory(_found).start()
        except OSError as e:
            log.warning("printer discovery is off: %s", e)
        manager.start()
        try:
            yield
        finally:
            manager.stop()
            if listener is not None:
                listener.stop()
    return lifespan


def main() -> None:
    cfg = config.load()
    etc = config.paths().etc
    sm = Spoolman(cfg["spoolman_url"])
    manager = Manager(spoolman=sm)
    app = create_app(sm, printers=manager)
    app.router.lifespan_context = printer_lifespan(manager)
    # one worker only: the pairing and inventory locks are per process
    uvicorn.run(app, host="0.0.0.0", port=cfg["port"], ssl_certfile=str(etc / "cert.pem"),
                ssl_keyfile=str(etc / "key.pem"), workers=1)


if __name__ == "__main__":
    main()
