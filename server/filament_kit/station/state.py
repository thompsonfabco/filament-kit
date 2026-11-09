"""Settings and the shared state of the station's threads (reader, scale, panel, intake flow, HTTP).

Settings come from the environment (the systemd drop-in written by `filament-kit modules apply`); the station never
reads /etc/filament-kit. The other station modules import this one and use these objects; nothing else holds state.
"""
from __future__ import annotations

import glob
import os
import re
import threading

from . import voice


def settings_from_env() -> dict:
    return {
        "port": int(os.environ.get("STATION_PORT", "5003")),
        # one space-separated value in the drop-in; localhost unless apply adds the server's address
        "allow": set(os.environ.get("STATION_ALLOW", "127.0.0.1").split()),
        "nfc_device": os.environ.get("NFC_DEVICE", "auto"),  # auto: the ttyUSB port that isn't the button panel
        "beep": os.environ.get("STATION_BEEP", "1") != "0",
        "beep_device": os.environ.get("STATION_BEEP_DEVICE", ""),
        "speech": os.environ.get("STATION_SPEECH", "1") != "0",  # the panel talks (Piper or espeak-ng, + ffmpeg)
        # auto: Piper when its voice model is installed, else espeak-ng; espeak: always espeak-ng
        "tts": os.environ.get("STATION_TTS", "auto"),
        "piper_voice": os.environ.get("STATION_PIPER_VOICE", voice.model_path()),
        "camera": os.environ.get("STATION_CAMERA", "auto"),  # the new spool's picture: auto | /dev/videoN | off
        # the bundled panel firmware (a VERSION file beside it); a panel on another version is reflashed
        "panel_fw": os.environ.get("STATION_PANEL_FW", "/opt/filament-kit/resources/panel/intake-panel.bin"),
        "panel_flash": os.environ.get("STATION_PANEL_FLASH", "1") != "0",
        # the panel is wired the other way round (yellow on D2/D6, red on D1/D5): swap the buttons and lamps
        "panel_swap": os.environ.get("STATION_PANEL_SWAP", "0") == "1",
        # the intake flow: no progress this long and it goes back to idle; a recognition (local AI, then Claude)
        # may take this long. The server's address and token come from the pairing files (server_api).
        "flow_timeout": int(os.environ.get("STATION_FLOW_TIMEOUT", "600")),
        "recognise_timeout": int(os.environ.get("STATION_RECOGNISE_TIMEOUT", "90")),
    }


settings = settings_from_env()

MIN_GRAMS = 20  # an empty pan reads 0; anything under this isn't a spool

lock = threading.Lock()
state = {"tag": None, "tag_at": None, "scale": None, "scale_at": None, "last": None, "last_at": None,
         "held": None, "held_at": None, "blink_until": 0, "air": None, "air_at": None,
         "photo": None, "photo_at": None}
# the intake flow (flow.py): its step, attempt number, the linked spool or recognised filament, the server's display
# lines for the step and the station's own message
flow = {"step": "idle", "seq": 0, "spool": None, "filament": None, "display": [], "message": "", "at": 0.0}
# serial ports: the panel's (found by its HELLO) and the one nfcpy uses; neither probes the other's
ports = {"panel": None, "panel_version": None, "panel_chip": None, "nfc": None}
flashed: set[str] = set()  # bundled firmware versions already written this run
probed = threading.Event()  # set once the panel search has looked at every port, so nfcpy picks the right one
panel_lock = threading.Lock()
panel = {"ser": None}
panel_dirty = threading.Event()


def usb_ttys() -> list[str]:
    return _by_number(glob.glob("/dev/ttyUSB*"))


SYSFS_TTY = "/sys/class/tty"
PANEL_VENDOR = "303a"  # Espressif: the ESP32-C3's own USB serial


def _by_number(paths) -> list[str]:
    return sorted(paths, key=lambda p: int(re.sub(r"\D", "", p) or 0))


def usb_vendor(dev: str) -> str | None:
    """The USB vendor ID (lowercase hex) of the device behind a tty, or None when sysfs doesn't say."""
    try:
        iface = os.path.realpath(os.path.join(SYSFS_TTY, os.path.basename(dev), "device"))  # the USB interface
        with open(os.path.join(os.path.dirname(iface), "idVendor")) as f:  # its parent is the USB device
            return f.read().strip().lower() or None
    except OSError:
        return None


def panel_ttys() -> list[str]:
    """The ports that may hold the button panel: ttyACM ports of an Espressif USB device (other ttyACM boards are
    never opened), then the ttyUSB ports."""
    acm = [d for d in glob.glob("/dev/ttyACM*") if usb_vendor(d) == PANEL_VENDOR]
    return _by_number(acm) + usb_ttys()


def view() -> dict:
    """A snapshot for the HTTP handler: the state plus the panel's port and firmware version and the flow."""
    with lock:
        return dict(state, panel=ports["panel"], panel_version=ports["panel_version"],
                    flow={k: flow[k] for k in ("step", "message", "spool", "filament")})
