"""`python -m filament_kit.station`: start the panel, reader and scale threads and serve the read-only HTTP view on
STATION_PORT (default 5003) for the addresses in STATION_ALLOW (space-separated, default 127.0.0.1)."""
from __future__ import annotations

import logging
import threading
from http.server import ThreadingHTTPServer

from . import beep, http, nfc, panel, scale
from . import state as st

log = logging.getLogger("intake-station")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = st.settings
    log.info("scan beep: %s", (s["beep_device"] or beep.beep_device() or "no speaker output found")
             if s["beep"] else "off")
    for fn in (panel.panel_loop, nfc.nfc_loop, scale.scale_loop):
        threading.Thread(target=fn, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", s["port"]), http.make_handler(st.view, s["allow"])).serve_forever()


if __name__ == "__main__":
    main()
