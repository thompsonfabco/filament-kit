"""`python -m filament_kit.station`: start the panel, reader and scale threads and serve the read-only HTTP view on
STATION_PORT (default 5003) for the addresses in STATION_ALLOW (space-separated, default 127.0.0.1)."""
from __future__ import annotations

import logging
import threading
from http.server import ThreadingHTTPServer

from . import beep, camera, flow, http, nfc, panel, scale, speech
from . import state as st

log = logging.getLogger("intake-station")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = st.settings
    log.info("scan beep: %s", (s["beep_device"] or beep.beep_device() or "no speaker output found")
             if s["beep"] else "off")
    log.info("camera: %s", camera.camera_dev() or "none found (looked for again at each new spool)")
    log.info("kit server: %s", "paired" if flow.api().paired else "not paired (sudo filament-kit station pair)")
    for fn in (panel.panel_loop, nfc.nfc_loop, scale.scale_loop, speech.speech_loop, flow.tick_loop):
        threading.Thread(target=fn, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", s["port"]), http.make_handler(st.view, s["allow"])).serve_forever()


if __name__ == "__main__":
    main()
