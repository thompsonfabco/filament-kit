"""Run the app API: `python -m filament_kit` (HTTPS on 0.0.0.0:<port>, one worker)."""
import logging
import sys
import time
from contextlib import asynccontextmanager

import anyio.to_thread
import uvicorn
from uvicorn.main import STARTUP_FAILURE

from . import config
from .api import create_app
from .bridge import camera, discovery, mapping, registry, usage
from .bridge.connection import Manager
from .spoolman import Spoolman

log = logging.getLogger(__name__)


CONNECTED = {"connected", "needs_developer_mode"}  # Manager states with a live MQTT session
REGISTRY_ERROR_EVERY = 60.0  # seconds between log lines about an unreadable printer registry


def discovery_callback(manager):
    """The SSDP listener's `on_found`. A configured printer the manager is connected to keeps its IP whatever an
    announcement says (an announce from elsewhere cannot steer the Access Code to another host); the registry
    logs every IP change of a configured printer. An unreadable registry is logged at most once a minute."""
    last_error = [float("-inf")]

    def found(info: dict) -> None:
        serial = info["serial"]
        keep = manager.state(serial) in CONNECTED
        try:
            registry.detected(serial, info["ip"], info.get("model", ""), info.get("name", ""), keep_ip=keep)
        except registry.RegistryError as e:
            now = time.monotonic()
            if now - last_error[0] >= REGISTRY_ERROR_EVERY:
                last_error[0] = now
                log.error("printer discovery: %s", e)
    return found


def printer_lifespan(manager, listener_factory=discovery.Listener, camera_hub=None, tracker=None, mapper=None):
    """Starlette lifespan: the printer connection manager and the SSDP listener live as long as the app.
    A listener that cannot bind (port in use) is logged and skipped; printers already set up still work.
    The slot mapper (if given) restores, once its printer is connected and idle, any slot snapshot a killed job
    left; on the way out it stops a running mapping job and waits for its restore BEFORE the printer connections
    close (a restore needs them). Then the usage tracker (if given) stops taking new jobs, and the camera hub (if
    given) stops every camera source, so no ffmpeg outlives the app."""
    @asynccontextmanager
    async def lifespan(app):
        listener = None
        try:
            try:
                listener = listener_factory(discovery_callback(manager)).start()
            except OSError as e:
                log.warning("printer discovery is off: %s", e)
            manager.start()
            if mapper is not None:
                try:
                    mapper.recover_pending()
                except Exception:
                    log.exception("mapping: cannot check for pending slot snapshots")
            yield
        finally:
            try:
                if mapper is not None:
                    try:
                        await anyio.to_thread.run_sync(mapper.shutdown)
                    except Exception:
                        log.exception("mapping: shutdown failed")
                await anyio.to_thread.run_sync(manager.stop)
                if listener is not None:
                    await anyio.to_thread.run_sync(listener.stop)
                if tracker is not None:
                    tracker.stop()
            finally:
                if camera_hub is not None:
                    await anyio.to_thread.run_sync(camera_hub.shutdown)
    return lifespan


GRACEFUL_SHUTDOWN = 5  # seconds uvicorn waits for open connections (camera streams) before the lifespan exit


class _Server(uvicorn.Server):
    """uvicorn waits for open connections before running the lifespan shutdown, so an open MJPEG stream would
    hold `systemctl stop`. The signal handler first tells the camera hub to end its streams."""

    def __init__(self, config: uvicorn.Config, on_exit):
        super().__init__(config)
        self._on_exit = on_exit

    def handle_exit(self, sig, frame) -> None:
        try:
            self._on_exit()
        finally:
            super().handle_exit(sig, frame)


def serve(app, hub, **kw) -> None:
    """Run uvicorn. A server that never started (port in use, bad certificate ...) exits with uvicorn's
    STARTUP_FAILURE code 3 so systemd's `Restart=on-failure` retries; Ctrl-C ends quietly, as `uvicorn.run`."""
    server = _Server(uvicorn.Config(app, **kw), hub.begin_stop)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        sys.exit(STARTUP_FAILURE)


def _log_to_journal() -> None:
    """uvicorn configures only its own loggers, so ours (command audit lines, IP-change warnings) need a handler;
    stderr goes to the systemd journal."""
    app_log = logging.getLogger("filament_kit")
    if not app_log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        app_log.addHandler(handler)
        app_log.propagate = False
    app_log.setLevel(logging.INFO)


def main() -> None:
    _log_to_journal()
    cfg = config.load()
    etc = config.paths().etc
    sm = Spoolman(cfg["spoolman_url"])
    manager = Manager(spoolman=sm)
    tracker = usage.Tracker(manager, sm)   # listens before the manager connects: sees every first report
    hub = camera.Hub(printer_state=manager.state)  # ip / Access Code / model / pin from the registry
    mapper = mapping.Mapper(manager)               # one per process: the app's routes and the lifespan share it
    app = create_app(sm, printers=manager, camera_hub=hub, mapper=mapper)
    app.router.lifespan_context = printer_lifespan(manager, camera_hub=hub, tracker=tracker, mapper=mapper)
    # one worker only: the pairing and inventory locks are per process
    serve(app, hub, host="0.0.0.0", port=cfg["port"], ssl_certfile=str(etc / "cert.pem"),
          ssl_keyfile=str(etc / "key.pem"), workers=1, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN)


if __name__ == "__main__":
    main()
