"""The PN532 NFC reader through nfcpy (NFC_DEVICE, default auto: the first ttyUSB port the button panel isn't on).
Tag ids are formatted by `tags.format_uid` like nfc2klipper's ("a:b:c:d:e:f:1"), so they match Spoolman's
extra.nfc_id.

The PN532 keeps its UART speed until it loses power. nfcpy moves it from 115200 to 921600 baud when it opens the
reader and sets it back in its close(). A service stopped by SIGTERM used to die without that close, leaving the reader
at 921600: every later open at 115200 then timed out (Errno 110) until the reader was unplugged. So a stop now closes
nfcpy first (`stop`, called from the SIGTERM handler in __main__), and an open that fails tries the higher speeds to
set the chip back (`pn532_unwedge`)."""
from __future__ import annotations

import errno
import logging
import re
import threading
import time

from .. import tags
from . import flow
from . import state as st

log = logging.getLogger("intake-station")

nfc_stop = threading.Event()  # set on SIGTERM: the reader loop leaves its `with`, so nfcpy's close() runs
nfc_idle = threading.Event()  # set while nfcpy does not hold the reader
nfc_idle.set()
PN532_ACK = bytes.fromhex("0000ff00ff00")  # also cancels a command in progress
PN532_WAKE = b"\x55\x55" + bytes(14)  # wakes the HSU from power-down, then a long preamble
PN532_SET_115200 = bytes.fromhex("0000ff03fdd410041800")  # SetSerialBaudRate(4 = 115200)
PN532_SET_115200_RSP = bytes.fromhex("0000ff02fed5111a00")


def nfc_path():
    """nfcpy's path for the reader: NFC_DEVICE, or (auto) the first ttyUSB port the panel isn't on."""
    if st.settings["nfc_device"] != "auto":
        return st.settings["nfc_device"]
    st.probed.wait(15)
    ttys = st.usb_ttys()
    if st.ports["nfc"] in ttys and st.ports["nfc"] != st.ports["panel"]:
        dev = st.ports["nfc"]  # keep the claim across retries so the panel search never opens it
    else:
        dev = next((p for p in ttys if p != st.ports["panel"]), None)
    st.ports["nfc"] = dev
    return f"tty:{dev[len('/dev/tty'):]}:pn532" if dev else None


def tty_of(path):
    """The device node behind an nfcpy tty path ("tty:USB0:pn532" -> "/dev/ttyUSB0"), or None."""
    m = re.match(r"^tty:(\w+)", path or "")
    return f"/dev/tty{m.group(1)}" if m else None


def pn532_unwedge(dev, speeds=(921600, 460800, 230400, 115200)):
    """Find a PN532 left at another UART speed and set it back to 115200 (where nfcpy starts). Returns the speed it
    answered at, or None. At each speed: wake it, cancel any half-done command, then SetSerialBaudRate; the chip
    switches speed after the host's ACK to its answer."""
    import serial  # pyserial, which nfcpy needs anyway
    for baud in speeds:
        try:
            with serial.Serial(dev, baud, timeout=0.1) as s:
                s.write(PN532_WAKE + PN532_ACK)
                time.sleep(0.02)
                s.reset_input_buffer()
                s.write(PN532_WAKE + PN532_SET_115200)
                got = s.read(len(PN532_ACK) + len(PN532_SET_115200_RSP))
                if PN532_SET_115200_RSP in got:
                    s.write(PN532_ACK)
                    s.flush()
                    time.sleep(0.02)
                    return baud
        except (OSError, serial.SerialException) as e:
            log.debug("PN532 at %d baud on %s: %s", baud, dev, e)
    return None


def stop(timeout=3.0):
    """Ask the reader loop to close nfcpy (which leaves the chip at 115200, idle and asleep); wait up to `timeout`."""
    nfc_stop.set()
    return nfc_idle.wait(timeout)


def on_tag(nfc_id):
    flow.on_tag(nfc_id)  # a tap starts the intake flow over with this tag


_recent: dict[str, float] = {}  # formatted tag id -> when it was last accepted, from either reader
_recent_lock = threading.Lock()  # the panel and reader loops are separate threads
DEDUP_SECONDS = 2.0


def on_identifier(identifier: bytes):
    """A tag id from either reader (the USB PN532 here, or the panel's `TAG` line). The same tag within
    DEDUP_SECONDS counts as one tap, whichever reader saw it."""
    nfc_id = tags.format_uid(identifier)
    now = time.monotonic()
    with _recent_lock:
        for k in [k for k, t in _recent.items() if now - t >= DEDUP_SECONDS]:
            del _recent[k]
        if nfc_id in _recent:
            return
        _recent[nfc_id] = now
    on_tag(nfc_id)


def nfc_loop():
    """Poll the PN532 like nfc2klipper does: one read per tap, then wait for the tag to leave the field."""
    import nfc  # the [station] extra; only the reader loop needs it
    from nfc.clf import RemoteTarget
    stopping = nfc_stop.is_set
    while True:
        nfc_idle.clear()  # before the stop check: a stop() from here on waits for this pass to end
        retry_now = False
        try:
            if stopping():
                return
            path = nfc_path()
            if stopping():  # a stop during the port lookup: don't open the reader at all
                return
            try:
                if not path:
                    raise OSError("no USB serial port for the reader")
                with nfc.ContactlessFrontend(path) as clf:  # its exit runs nfcpy's close(): 115200, idle, asleep
                    log.info("NFC reader open: %s", clf)
                    while not stopping():
                        tag = clf.connect(rdwr={"on-connect": lambda tag: False}, terminate=stopping)
                        if tag and tag.identifier:
                            on_identifier(tag.identifier)
                            while not stopping() and clf.sense(RemoteTarget("106A"), RemoteTarget("106B"),
                                                               RemoteTarget("212F")):
                                time.sleep(0.2)
                        else:
                            time.sleep(0.2)
            except Exception as e:  # reader unplugged, not there yet, or left at another speed
                log.warning("NFC reader %s: %s; retrying in 5 s", path, e)
                dev = tty_of(path)
                if not stopping() and getattr(e, "errno", None) in (errno.ETIMEDOUT, errno.ENODEV) and dev:
                    baud = pn532_unwedge(dev)
                    # a chip that answers at 115200 was not wedged: the open failed for another reason, so wait
                    if baud and baud != 115200:
                        log.info("NFC reader on %s answered at %d baud; set it back to 115200", dev, baud)
                        retry_now = True
        finally:
            nfc_idle.set()
        if not retry_now:
            nfc_stop.wait(5)
