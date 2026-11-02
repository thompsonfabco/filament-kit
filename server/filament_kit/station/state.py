"""Settings and the shared state of the station's threads (reader, scale, panel, HTTP).

Settings come from the environment (the systemd drop-in written by `filament-kit modules apply`); the station never
reads /etc/filament-kit. The other station modules import this one and use these objects; nothing else holds state.
"""
from __future__ import annotations

import glob
import os
import re
import threading


def settings_from_env() -> dict:
    return {
        "port": int(os.environ.get("STATION_PORT", "5003")),
        # one space-separated value in the drop-in; localhost unless apply adds the server's address
        "allow": set(os.environ.get("STATION_ALLOW", "127.0.0.1").split()),
        "nfc_device": os.environ.get("NFC_DEVICE", "auto"),  # auto: the ttyUSB port that isn't the button panel
        "active": int(os.environ.get("STATION_ACTIVE", "300")),  # a scan / weight counts this long (TAG_FRESH)
        "beep": os.environ.get("STATION_BEEP", "1") != "0",
        "beep_device": os.environ.get("STATION_BEEP_DEVICE", ""),
        "speech": os.environ.get("STATION_SPEECH", "1") != "0",  # the panel talks (espeak-ng + ffmpeg)
        "camera": os.environ.get("STATION_CAMERA", "auto"),  # webcam picture on Hold: auto | /dev/videoN | off
    }


settings = settings_from_env()

MIN_GRAMS = 20  # an empty pan reads 0; anything under this isn't a spool

lock = threading.Lock()
state = {"tag": None, "tag_at": None, "scale": None, "scale_at": None, "last": None, "last_at": None,
         "held": None, "held_at": None, "suppress": False, "blink_until": 0, "air": None, "air_at": None,
         "photo": None, "photo_at": None}
# serial ports: the panel's (found by its HELLO) and the one nfcpy uses; neither probes the other's
ports = {"panel": None, "nfc": None}
probed = threading.Event()  # set once the panel search has looked at every port, so nfcpy picks the right one
panel_lock = threading.Lock()
panel = {"ser": None}
panel_dirty = threading.Event()


def usb_ttys() -> list[str]:
    return sorted(glob.glob("/dev/ttyUSB*"), key=lambda p: int(re.sub(r"\D", "", p) or 0))


def fresh(t, now) -> bool:
    return t is not None and now - t <= settings["active"]


def active(now):
    """(tag, weight grams) that count right now: a held weight keeps its scan; otherwise both expire after ACTIVE."""
    s = state
    tag = s["tag"] if s["tag"] and (s["held"] is not None or fresh(s["tag_at"], now)) else None
    weight = s["held"] if s["held"] is not None else (s["last"] if fresh(s["last_at"], now) else None)
    return tag, weight


def view() -> dict:
    """A snapshot for the HTTP handler: the state plus the panel's port."""
    with lock:
        return dict(state, panel=ports["panel"])
