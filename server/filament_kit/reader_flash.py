"""Setting up a Printer Station over the kit server's USB with no toolchain: the kit's own prebuilt image is written
with esptool (as the intake panel's is), then the reader's settings go to it over the same USB serial port and it keeps
them in flash (reader/lib/reader_core/src/settings.h has the protocol):

    kit: FK?            reader: FK-READER <build> configured=<0|1> wifi=<ok|fail|-> server=<ok|fail|unauth|->
    kit: FK-SET <json>  reader: FK-OK (and restarts) or FK-ERR <reason>

After FK-OK the reader restarts, joins the Wi-Fi and calls the kit with its token; its next FK-READER line says how
that went, which is the "done" or the plain reason. The Wi-Fi password and the token go only into the FK-SET line on
the serial port: never printed, logged or kept here.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

BAUD = 115200
IMAGE = "printer-station.bin"


class FlashError(Exception):
    pass


@dataclass
class Hello:
    build: int
    configured: bool
    wifi: str           # ok / fail / -
    server: str         # ok / fail / unauth / -


def parse_hello(line: str) -> Hello | None:
    parts = line.strip().split()
    if len(parts) < 2 or parts[0] != "FK-READER" or not parts[1].isdigit():
        return None
    kv = dict(p.split("=", 1) for p in parts[2:] if "=" in p)
    return Hello(int(parts[1]), kv.get("configured") == "1", kv.get("wifi", "-"), kv.get("server", "-"))


def bundled_image() -> tuple[Path, int] | None:
    """The kit's Printer Station image and its build: the installed copy, else a source checkout's reader/firmware."""
    for d in (config.paths().opt / "resources" / "reader", Path(__file__).resolve().parents[2] / "reader" / "firmware"):
        try:
            return d / IMAGE, int((d / "VERSION").read_text().strip())
        except (OSError, ValueError):
            continue
    return None


def panel_image() -> tuple[Path, str] | None:
    """The intake panel's image and version, as the station flashes it: the installed copy, else a checkout's."""
    for d in (config.paths().opt / "resources" / "panel",
              Path(__file__).resolve().parents[2] / "station" / "panel" / "firmware"):
        try:
            version = (d / "VERSION").read_text().strip()
            if (d / "intake-panel.bin").is_file() and version:
                return d / "intake-panel.bin", version
        except OSError:
            continue
    return None


# What the setup page's "Flash a device" tab can write (setup_console/flash_tab.py): the kit's own images, from the
# installed version, never the internet. Both are merged images written at address 0 of an ESP32-C3.
DEVICES = {"printer-station": "Printer Station", "intake-panel": "Intake panel"}


def device_image(device: str) -> tuple[Path, str] | None:
    """(image, version) of one of DEVICES, or None when this kit has none bundled."""
    if device == "printer-station":
        got = bundled_image()
        return (got[0], str(got[1])) if got and got[0].is_file() else None
    if device == "intake-panel":
        return panel_image()
    return None


# The setup page's "plugged into the server" way: the root helper (op reader_usb) leaves the answers here, root only,
# and starts the job `reader_setup` (`reader setup --pending`), which takes them and deletes the file at once. Job
# arguments are never secret (they show in systemctl), so the Wi-Fi password travels this way.
PENDING = "reader-setup.json"
PENDING_MAX_AGE = 15 * 60


def pending_path() -> Path:
    return config.paths().etc / PENDING


def write_pending(answers: dict) -> None:
    import os
    path = pending_path()
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(answers, fh)


def take_pending() -> dict | None:
    """The answers the page left, once: the file is deleted whatever it holds. None when there are none, or they are
    older than PENDING_MAX_AGE (a job that never ran)."""
    path = pending_path()
    try:
        age = time.time() - path.stat().st_mtime
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data, age = None, 0
    finally:
        path.unlink(missing_ok=True)
    return data if isinstance(data, dict) and age <= PENDING_MAX_AGE else None


CHUNK = 256           # an FK-SET line goes out in pieces this size, with a pause between, so the board keeps up


def _open(port: str, timeout: float = 0.5):
    """The port the way station/panel.py opens the intake panel on the same boards: DTR and RTS low before it opens,
    so the board is not held in reset or in its flash mode."""
    import serial       # pyserial: the station and web extras install it
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, BAUD, timeout
    ser.write_timeout = 2
    ser.dtr = ser.rts = False
    ser.open()
    return ser


class Device:
    """One reader on a serial port. `opener(port)` gives a pyserial-like object (write, readline, close)."""

    def __init__(self, port: str, opener=_open, clock=time.monotonic, sleep=time.sleep):
        self.port, self._opener, self._clock, self._sleep = port, opener, clock, sleep

    def _session(self):
        try:
            return self._opener(self.port)
        except Exception:  # noqa: BLE001 - not there (yet): a restart re-enumerates the USB port
            return None

    def hello(self, wait: float = 5.0, done=lambda h: True) -> Hello | None:
        """Ask FK? until the reader answers with a line `done` accepts, for up to `wait` seconds. None: no answer (a
        blank board, another firmware, or not back from a restart yet)."""
        end = self._clock() + wait
        last = None
        while self._clock() < end:
            s = self._session()
            if s is None:
                self._sleep(0.5)
                continue
            try:
                while self._clock() < end:
                    s.write(b"FK?\n")
                    line = s.readline().decode("utf-8", "replace")
                    h = parse_hello(line) if line else None
                    if h is not None:
                        last = h
                        if done(h):
                            return h
                    self._sleep(0.3)
            except Exception:  # noqa: BLE001 - the port went away mid-read (a restart): open it again
                self._sleep(0.5)
            finally:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass
        return last if last is not None and done(last) else None

    def send_settings(self, settings: dict, wait: float = 5.0) -> None:
        """FK-SET; FlashError with the reader's reason when it refuses. The line is never logged. In one session: FK?
        first, so the board is known to be up and listening (a board that resets when the port opens is answering
        again) before the settings go, in CHUNK-sized pieces."""
        line = ("FK-SET " + json.dumps(settings, separators=(",", ":")) + "\n").encode("utf-8")
        s = self._session()
        if s is None:
            raise FlashError(f"cannot open {self.port}")
        try:
            end = self._clock() + wait
            while True:
                if self._clock() >= end:
                    raise FlashError("the reader did not answer before the settings")
                s.write(b"FK?\n")
                got = s.readline().decode("utf-8", "replace")
                if got and parse_hello(got) is not None:
                    break
                self._sleep(0.3)
            for i in range(0, len(line), CHUNK):
                s.write(line[i:i + CHUNK])
                self._sleep(0.02)
            end = self._clock() + wait
            while self._clock() < end:
                got = s.readline().decode("utf-8", "replace").strip()
                if got == "FK-OK":
                    return
                if got.startswith("FK-ERR"):
                    raise FlashError(f"the reader refused the settings: {got[6:].strip() or 'no reason given'}")
            raise FlashError("the reader did not answer the settings")
        finally:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass


def flash(port: str, image: Path, run=subprocess.run) -> bool:
    """Write the merged image at address 0 with esptool, as station/panel.py does for the intake panel."""
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", port, "--baud", "460800",
           "--before", "default-reset", "--after", "hard-reset", "write-flash", "0x0", str(image)]
    try:
        return run(cmd, check=False, capture_output=True, text=True, timeout=180).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@dataclass
class Result:
    ok: bool
    message: str
    flashed: bool = False


def setup(port: str, settings: dict, *, reflash: bool = False, device: Device | None = None, run=subprocess.run,
          say=print, step=None) -> Result:
    """The whole USB flow for one board: the kit's image unless it already runs that build (or newer), the settings,
    then the reader's own report of its first start. `settings` is the FK-SET JSON (settings.h). `step(sentence)` is
    told when each of the steps 2 to 5 of the job starts (steps.py); the caller has said step 1, "Finding the board",
    and this asks the board in it."""
    step = step or (lambda _text: None)
    dev = device or Device(port)
    found = bundled_image()
    if found is None:
        return Result(False, "this kit has no Printer Station firmware bundled (reader/firmware); nothing was written")
    image, build = found
    flashed = False
    now = dev.hello(wait=4.0)
    if reflash or now is None or now.build < build:
        step("Writing the program")
        say(f"Writing the Printer Station firmware (build {build}) to {port}...")
        if not flash(port, image, run=run):
            return Result(False, f"writing the firmware to {port} failed (esptool). Unplug and replug the board, "
                                 "then run this again.")
        flashed = True
        step("Checking what was written")
        now = dev.hello(wait=20.0)
        if now is None or now.build != build:
            return Result(False, f"{port} was written but does not answer as the Printer Station"
                                 + (f" (it reports build {now.build})" if now else "")
                                 + ". Unplug and replug it, then run this again.", flashed)
    else:       # steps 2 and 3 keep their places: nothing is written, the settings are
        step("Keeping the program that is on the board")
        step("Writing the settings")
        say(f"The board on {port} already runs Printer Station build {now.build}: writing its settings only.")
    try:
        dev.send_settings(settings)
    except FlashError as e:
        return Result(False, str(e), flashed)
    step("Joining the Wi-Fi")
    say("Settings written; the reader is restarting and joining the Wi-Fi...")
    reaching = []

    def tried(h) -> bool:
        # done once it tried: no Wi-Fi means it never tries the kit, so server stays "-"
        if h.configured and h.wifi == "ok" and not reaching:
            reaching.append(True)
            step("Reaching the Hub")
        return h.configured and (h.wifi == "fail" or (h.wifi != "-" and h.server != "-"))

    h = dev.hello(wait=60.0, done=tried)
    ssid = settings.get("ssid", "")
    if h is None:
        return Result(False, "the reader took its settings but did not report back within a minute. Watch its "
                             "screen: it says whether it reached the Wi-Fi and the kit.", flashed)
    if h.wifi != "ok":
        return Result(False, f"the reader could not join the Wi-Fi network {ssid!r}: check the name and the "
                             "password (and that it is a 2.4 GHz network), then run this again.", flashed)
    if h.server == "unauth":
        return Result(False, "the reader reached the kit, but the kit did not accept its token. Run this again to "
                             "give it a new one.", flashed)
    if h.server != "ok":
        return Result(False, f"the reader joined {ssid!r} but could not reach the kit at {settings.get('base')}: "
                             "check web.public_url and that the reader's network can reach it.", flashed)
    return Result(True, f"Done. The Printer Station joined {ssid!r} and reached the kit.", flashed)
