"""The one write path to the panel's serial port, shared by `panel` (lamps), `beep` (buzzer) and `speech` (audio
frames), so none of them has to import the others to send."""
from __future__ import annotations

import logging

from . import state as st

log = logging.getLogger("intake-station")


def panel_send(msg):
    """Send one line (str) or a ready-made frame (bytes) to the panel; False when there's no panel (or it just went
    away)."""
    with st.panel_lock:
        ser = st.panel["ser"]
        if not ser:
            return False
        try:
            ser.write(msg if isinstance(msg, bytes) else msg.encode() + b"\n")
            return True
        except Exception as e:
            log.warning("panel %s: %s", ser.port, e)
            st.panel["ser"] = None
            return False
