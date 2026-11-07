"""The panel talks ("1042 grams. Hold yellow to save."): Piper speech (the `voice` module's model, STATION_PIPER_VOICE)
or, without it, espeak-ng (STATION_TTS=espeak forces it), cut to the 8 kHz speech band by ffmpeg and streamed to the
panel's speaker in 256-byte `A <n>` frames (else played on the beep output with aplay). STATION_SPEECH=0 turns it off.
Piper's voice loads once (about 1 s), then makes a phrase in about 0.1 s; piper-tts is the `[station-tts]` extra.

A newer phrase cuts off the one playing, fading it out from where it is so the speaker's coupling capacitor doesn't
thump; each phrase is ramped up from 0 (off) before and back down after for the same reason."""
from __future__ import annotations

import io
import logging
import os
import struct
import subprocess
import threading
import time
import wave

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


piper = {}  # the loaded Piper voice, kept between phrases (loading takes ~1 s, a phrase ~0.1 s)


def piper_voice():
    """The Piper voice if STATION_TTS allows it and its model is installed, else None (then espeak-ng speaks)."""
    path = st.settings["piper_voice"]
    if st.settings["tts"] == "espeak" or not os.path.exists(path):
        return None
    if "voice" not in piper:
        try:
            from piper import PiperVoice  # the [station-tts] extra
            piper["voice"] = PiperVoice.load(path)
        except Exception as e:  # noqa: BLE001 - piper-tts missing or the model broken: don't retry every phrase
            log.warning("piper: %s; speaking with espeak-ng", e)
            piper["voice"] = None
    return piper["voice"]


def engine():
    """Which voice speaks: for the log at start (which also preloads Piper's)."""
    return f"Piper ({os.path.basename(st.settings['piper_voice'])})" if piper_voice() else "espeak-ng"


def synth(text):
    """The phrase as WAV bytes: Piper's natural voice when installed (libritts_r, speaker 0: the owner's pick,
    2026-11-07), else
    espeak-ng's; None if neither works."""
    voice = piper_voice()
    if voice:
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                voice.synthesize_wav(text, w)
            return buf.getvalue()
        except Exception as e:  # noqa: BLE001 - one bad phrase: espeak-ng says it
            log.warning("piper: %s; this phrase with espeak-ng", e)
    try:
        p = subprocess.run(["espeak-ng", "-v", "en-us", "-s", "165", "--stdout", text], capture_output=True, timeout=10)
        return p.stdout if p.returncode == 0 and p.stdout else None
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("speech: %s", e)
        return None


def to_panel(wav):
    """WAV -> the panel's speaker samples, voiced for a small unbaffled headset driver (user's A/B pick 2026-11-02):
    nothing under 450 Hz (it can't play it), +8 dB at 2.5 kHz (consonants), hard compression, normalised so all but
    the loudest 2 % of samples fit (those clip). Then PWM duty bytes around 128 (kept within 16-240), with a ramp up
    from 0 (off) before and back down after."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
                        "-af", "highpass=f=450,highpass=f=450,equalizer=f=2500:t=q:w=1:g=8,lowpass=f=3600,"
                               "acompressor=threshold=0.03:ratio=10:attack=2:release=50",
                        "-ar", str(RATE), "-ac", "1", "-f", "s16le", "pipe:1"],
                       input=wav, capture_output=True, timeout=10)
    if p.returncode:
        raise OSError(p.stderr.decode(errors="replace").strip())
    pcm = struct.unpack(f"<{len(p.stdout) // 2}h", p.stdout[:len(p.stdout) // 2 * 2])
    mags = sorted(map(abs, pcm))
    gain = 112 / max(1, mags[int(len(mags) * 0.98)] if mags else 1)
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
    if st.settings["speech"]:
        log.info("speech: %s", engine())
    while True:
        speech_ready.wait()
        speech_ready.clear()
        try:
            speak(speech["text"])
        except (OSError, subprocess.TimeoutExpired) as e:  # aplay missing or the output hung
            log.warning("speech: %s", e)
