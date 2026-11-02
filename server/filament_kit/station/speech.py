"""The panel talks ("Held, 1042 grams"): espeak-ng speech, cut to the 8 kHz speech band by ffmpeg and streamed to the
panel's speaker in 256-byte `A <n>` frames (else played on the beep output with aplay). STATION_SPEECH=0 turns it off.

A newer phrase cuts off the one playing, fading it out from where it is so the speaker's coupling capacitor doesn't
thump; each phrase is ramped up from 0 (off) before and back down after for the same reason."""
from __future__ import annotations

import logging
import struct
import subprocess
import threading
import time

from . import beep, wire
from . import state as st

log = logging.getLogger("intake-station")

RATE = 8000  # panel speaker sample rate
RAMP = RATE * 3 // 20  # 150 ms ramp of the speaker's DC level in and out, so its coupling capacitor doesn't thump

speech = {"text": None}
speech_ready = threading.Event()


def say(text):
    """Speak text on the panel's speaker; a newer phrase cuts off the one playing."""
    if st.settings["speech"]:
        speech["text"] = text
        speech_ready.set()


def synth(text):
    """espeak-ng's WAV for text, or None (not installed)."""
    try:
        p = subprocess.run(["espeak-ng", "-v", "en-us", "-s", "165", "--stdout", text], capture_output=True, timeout=10)
        return p.stdout if p.returncode == 0 and p.stdout else None
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("speech: %s", e)
        return None


def to_panel(wav):
    """WAV -> the panel's speaker samples: 8 kHz speech band, peak-normalised, as MOSFET duty bytes around 128
    (kept within 16-240), with a ramp up from 0 (off) before and back down after."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
                        "-af", "highpass=f=250,lowpass=f=3500", "-ar", str(RATE), "-ac", "1", "-f", "s16le", "pipe:1"],
                       input=wav, capture_output=True, timeout=10)
    if p.returncode:
        raise OSError(p.stderr.decode(errors="replace").strip())
    pcm = struct.unpack(f"<{len(p.stdout) // 2}h", p.stdout[:len(p.stdout) // 2 * 2])
    gain = 112 / max(1, max(map(abs, pcm), default=1))
    body = bytes(128 + max(-112, min(112, round(s * gain))) for s in pcm)
    ramp = bytes(round(128 * i / RAMP) for i in range(RAMP))
    return ramp + bytes([128]) * (RATE // 20) + body + bytes([128]) * (RATE // 20) + ramp[::-1]


def speak(text):
    """One phrase: synthesise it and stream it in real time (0.25 s ahead) in 256-byte "A" frames between the lamp
    lines, or play it on the PC's own output when there is no panel."""
    wav = synth(text)
    if not wav:
        return
    if not st.panel["ser"]:  # no panel: the PC's own output, if any
        dev = st.settings["beep_device"] or beep.beep_device()
        if dev:
            subprocess.run(["aplay", "-q", "-D", dev, "-"], input=wav, capture_output=True, timeout=15)
        return
    try:
        samples = to_panel(wav)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("speech: %s", e)
        return
    start, lead = time.monotonic(), RATE // 4
    for i in range(0, len(samples), 256):
        if speech_ready.is_set():  # cut off by a newer phrase: fade out from where this one is
            chunk = bytes(round(samples[i] * (RAMP - j) / RAMP) for j in range(RAMP))
            for k in range(0, RAMP, 256):
                wire.panel_send(b"A %d\n" % len(chunk[k:k + 256]) + chunk[k:k + 256])
            break
        wait = start + (i - lead) / RATE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        chunk = samples[i:i + 256]
        if not wire.panel_send(b"A %d\n" % len(chunk) + chunk):
            break


def speech_loop():
    """Speak each phrase `say` leaves, newest only."""
    while True:
        speech_ready.wait()
        speech_ready.clear()
        try:
            speak(speech["text"])
        except (OSError, subprocess.TimeoutExpired) as e:  # aplay missing or the output hung
            log.warning("speech: %s", e)
