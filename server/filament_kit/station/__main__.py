"""`python -m filament_kit.station`: start the panel, reader and scale threads and serve the read-only view over HTTPS
on STATION_PORT (default 5003) for the addresses in STATION_ALLOW (space-separated, default 127.0.0.1). The certificate
is the station's own (state.ensure_cert); after each start it tells the Hub its fingerprint, port and version."""
from __future__ import annotations

import logging
import signal
import sys
import threading
from http.server import ThreadingHTTPServer

from . import beep, camera, flow, http, nfc, panel, scale, server_api, speech
from . import state as st

log = logging.getLogger("intake-station")


def stop_service(signum, frame):
    """SIGTERM/SIGINT: let the reader loop close nfcpy first (at most 3 s), so the PN532 is left at 115200 and idle;
    otherwise a restart finds it at 921600 and times out until it is unplugged."""
    nfc.stop()
    sys.exit(0)


def make_server(port: int, handler):
    """(listener, certificate fingerprint or None, why there is none or None): HTTPS with the station's own certificate.
    Functionality first: a station that cannot make its certificate still serves, over plain HTTP as before. It says
    so in the journal and in its hello (`plain=<why>`: the Hub's Checks row); a Hub that pinned it never follows it
    down to plain HTTP."""
    try:
        cert, key, fp = st.ensure_cert()
        context = http.tls_context(cert, key)
    except (OSError, ValueError, ImportError) as e:
        plain = f"{type(e).__name__}: {e}"
        log.error("no HTTPS certificate for the station (%s): serving plain HTTP", plain)
        return ThreadingHTTPServer(("0.0.0.0", port), handler), None, plain
    log.info("https: port %s, certificate %s", port, fp)
    return http.TlsServer(("0.0.0.0", port), handler, context), fp, None


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = st.settings
    log.info("scan beep: %s", (s["beep_device"] or beep.beep_device() or "no speaker output found")
             if s["beep"] else "off")
    log.info("camera: %s", camera.camera_dev() or "none found (looked for again at each new spool)")
    log.info("kit server: %s", "paired" if flow.api().paired else "not paired (sudo spoolwarden station pair)")
    server, fp, plain = make_server(s["port"], http.make_handler(st.view, s["allow"]))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop_service)
    for fn in (panel.panel_loop, nfc.nfc_loop, scale.scale_loop, speech.speech_loop, flow.tick_loop):
        threading.Thread(target=fn, daemon=True).start()
    if not flow.api().paired:       # ask the kit server once; a long press of yellow asks again
        flow.ask_to_pair()
    threading.Thread(target=server_api.announce, args=(flow.api, fp, s["port"]), kwargs={"plain": plain},
                     daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
