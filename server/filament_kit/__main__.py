"""Run the app API: `python -m filament_kit` (HTTPS on 0.0.0.0:<port>, one worker)."""
import logging
from contextlib import asynccontextmanager

import anyio.to_thread
import uvicorn

from . import config
from .api import create_app
from .bridge import camera, discovery, registry
from .bridge.connection import Manager
from .spoolman import Spoolman

log = logging.getLogger(__name__)


def _found(info: dict) -> None:
    registry.detected(info["serial"], info["ip"], info.get("model", ""), info.get("name", ""))


def printer_lifespan(manager, listener_factory=discovery.Listener, camera_hub=None):
    """Starlette lifespan: the printer connection manager and the SSDP listener live as long as the app.
    A listener that cannot bind (port in use) is logged and skipped; printers already set up still work.
    On the way out the camera hub (if given) stops every camera source, so no ffmpeg outlives the app."""
    @asynccontextmanager
    async def lifespan(app):
        listener = None
        try:
            try:
                listener = listener_factory(_found).start()
            except OSError as e:
                log.warning("printer discovery is off: %s", e)
            manager.start()
            yield
        finally:
            try:
                await anyio.to_thread.run_sync(manager.stop)
                if listener is not None:
                    await anyio.to_thread.run_sync(listener.stop)
            finally:
                if camera_hub is not None:
                    await anyio.to_thread.run_sync(camera_hub.shutdown)
    return lifespan


def main() -> None:
    cfg = config.load()
    etc = config.paths().etc
    sm = Spoolman(cfg["spoolman_url"])
    manager = Manager(spoolman=sm)
    hub = camera.Hub()  # reads ip / Access Code / model from the printer registry
    app = create_app(sm, printers=manager, camera_hub=hub)
    app.router.lifespan_context = printer_lifespan(manager, camera_hub=hub)
    # one worker only: the pairing and inventory locks are per process
    uvicorn.run(app, host="0.0.0.0", port=cfg["port"], ssl_certfile=str(etc / "cert.pem"),
                ssl_keyfile=str(etc / "key.pem"), workers=1)


if __name__ == "__main__":
    main()
