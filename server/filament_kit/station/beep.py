"""Beeps: the panel's buzzer when the panel is connected, else (scan beep only) a tone on the PC's speaker output
through ALSA's aplay (Linux only) on STATION_BEEP_DEVICE, default the first USB speaker, else the first analog
output. STATION_BEEP=0 turns beeps off."""
from __future__ import annotations

import glob
import io
import logging
import math
import re
import struct
import subprocess
import threading
import wave

from . import panel
from . import state as st

log = logging.getLogger("intake-station")

TONES = {"scan": "B 2200 90", "hold": "B 2600 60 2", "release": "B 1500 90", "discard": "B 700 180",
         "nothing": "B 400 250"}


def beep_device():
    """A USB speaker if one is plugged in, else the first analog output; HDMI is skipped (usually no speaker)."""
    try:
        pcms = open("/proc/asound/pcm").read().splitlines()  # "01-00: ALC269VC Analog : ... : playback 1 : capture 1"
    except OSError:
        return None
    outs = [(int(m[1]), int(m[2]), m[3]) for p in pcms if "playback" in p
            for m in [re.match(r"(\d+)-(\d+): ([^:]*)", p)] if m]
    usb = {int(re.search(r"card(\d+)", p)[1]) for p in glob.glob("/proc/asound/card*/usbid")}
    for pick in ([o for o in outs if o[0] in usb], [o for o in outs if "hdmi" not in o[2].lower()]):
        if pick:
            return f"plughw:{pick[0][0]},{pick[0][1]}"
    return None


def tone(hz=1800, ms=120, rate=44100):
    """A short sine beep as WAV bytes, with 5 ms fades so it doesn't click."""
    n, fade = rate * ms // 1000, rate * 5 // 1000
    frames = b"".join(struct.pack("<h", int(12000 * min(1, i / fade, (n - i) / fade) *
                                             math.sin(2 * math.pi * hz * i / rate))) for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)
    return buf.getvalue()


BEEP_WAV = tone()


def beep(kind="scan"):
    """The panel's buzzer if the panel is connected, else (scan beep only) a tone on the PC's speaker output.
    Plays in the background so the reader loop isn't held up; a missing speaker only logs."""
    if not st.settings["beep"] or panel.panel_send(TONES[kind]) or kind != "scan":
        return
    dev = st.settings["beep_device"] or beep_device()
    if not dev:
        return

    def play():
        try:
            p = subprocess.run(["aplay", "-q", "-D", dev, "-"], input=BEEP_WAV, capture_output=True, timeout=5)
            if p.returncode:
                log.warning("beep on %s: %s", dev, p.stderr.decode(errors="replace").strip())
        except (OSError, subprocess.TimeoutExpired) as e:  # aplay missing or the device hung
            log.warning("beep on %s: %s", dev, e)
    threading.Thread(target=play, daemon=True).start()
