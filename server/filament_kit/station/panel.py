"""The optional button panel (station/panel/ firmware + PANEL.md in the repo): a D1 mini on USB serial with a buzzer
and lit Hold / Discard buttons.

Hold keeps the current weight with the scan (both stay current for the phone app until Discard or the next scan:
"held" in /state); Discard forgets the scan and weight. Both the panel and the PN532 board use CH340 USB serial chips
(no serial numbers), so the panel is found by its HELLO and the reader gets the other ttyUSB port (NFC_DEVICE=auto).
Protocol, 115200 baud, one line each: PC -> panel `?`, `L <hold> <discard>`, `B <hz> <ms> [count]`;
`A <n>` + n raw bytes (speech, see `speech`);
panel -> PC `HELLO intake-panel <version>`, `P H`, `P D`, `AIR <C> <RH|-> <hPa>` (see `air`).
"""
from __future__ import annotations

import logging
import threading
import time

from . import air, beep, camera, speech
from . import state as st

log = logging.getLogger("intake-station")


def lamps(now):
    """Panel lamp modes (0 off, 1 on, 2 flash, 3 three blinks): Hold lit on a scan, flashing while a weight is held;
    Discard lit while there's a scan or a weight, three blinks after a discard."""
    with st.lock:
        tag, weight = st.active(now)
        held, blink = st.state["held"] is not None, now < st.state["blink_until"]
    return (2 if held else 1 if tag else 0), (3 if blink else 1 if tag or weight is not None else 0)


def on_hold():
    """Hold: keep the current weight for this scan (the phone app then uses it however long the photos take).
    Pressed again while holding: let go. Needs a scan and a stable weight."""
    now = time.time()
    with st.lock:
        tag, _ = st.active(now)
        if tag and st.state["held"] is not None:
            st.state.update(held=None, held_at=None, photo=None, photo_at=None)
            kind, words = "release", "Released"
        elif tag and not st.state["suppress"] and st.fresh(st.state["last_at"], now):
            st.state.update(held=st.state["last"], held_at=now)
            kind, words = "hold", f"Held, {st.state['last']:.0f} grams"
        else:
            kind, words = "nothing", "Scan a tag first" if not tag else "Put the spool on the scale"
    log.info("hold button: %s", kind)
    beep.beep(kind)
    speech.say(words)
    st.panel_dirty.set()
    if kind == "hold":
        threading.Thread(target=camera.take_photo, args=(now,), daemon=True).start()


def on_discard():
    """Discard: forget the scan and any held or last weight. A spool left on the scale stays ignored until the pan
    is emptied (or the scale switches off), so the lamp doesn't come straight back on."""
    now = time.time()
    with st.lock:
        tag, weight = st.active(now)
        if tag or weight is not None:
            sc = st.state["scale"]
            st.state.update(tag=None, tag_at=None, held=None, held_at=None, last=None, last_at=None, photo=None,
                            photo_at=None,
                            suppress=bool(sc and sc["grams"] >= st.MIN_GRAMS and st.fresh(st.state["scale_at"], now)),
                            blink_until=now + 0.7)
            kind, words = "discard", "Discarded"
        else:
            kind, words = "nothing", "Nothing to discard"
    log.info("discard button: %s", kind)
    beep.beep(kind)
    speech.say(words)
    st.panel_dirty.set()


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


def open_panel(dev):
    """Open dev and return it if a panel answers with HELLO (it resets when the port opens, then says HELLO)."""
    import serial  # the [station] extra; only the panel loop needs it
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = dev, 115200, 0.3
    ser.dtr = ser.rts = False  # don't hold the D1 mini in reset / flash mode
    try:
        ser.open()
        end, asked = time.time() + 3, False
        while time.time() < end:
            if ser.readline().startswith(b"HELLO intake-panel"):
                return ser
            if not asked and time.time() > end - 1.5:
                ser.write(b"?\n")  # it didn't reset on open: ask
                asked = True
    except Exception:
        pass
    ser.close()
    return None


def find_panel():
    """One pass over the USB serial ports (skipping the reader's): the panel's port, or None. Records the result in
    ports["panel"] and sets `probed`, so the reader loop then takes another port."""
    ser = None
    for dev in st.usb_ttys():
        if dev != st.ports["nfc"] and (ser := open_panel(dev)):
            break
    st.ports["panel"] = ser.port if ser else None
    st.probed.set()  # after ports["panel"], so a waiting reader never sees the panel's port as free
    return ser


def panel_loop():
    """Find the button panel among the USB serial ports, then relay its presses and keep its lamps current."""
    while True:
        ser = find_panel()
        if not ser:
            time.sleep(5)
            continue
        log.info("button panel on %s", ser.port)
        with st.panel_lock:
            st.panel["ser"] = ser
        sent, last_sent = None, 0
        try:
            while st.panel["ser"] is ser:
                line = ser.readline().strip()
                if line == b"P H":
                    on_hold()
                elif line == b"P D":
                    on_discard()
                elif line.startswith(b"AIR "):
                    air.on_air(line)
                now = time.time()
                modes = lamps(now)
                if modes != sent or now - last_sent >= 1 or st.panel_dirty.is_set():
                    st.panel_dirty.clear()
                    if not panel_send("L %d %d" % modes):
                        break
                    sent, last_sent = modes, now
        except Exception as e:  # unplugged
            log.warning("panel %s: %s", ser.port, e)
        with st.panel_lock:
            st.panel["ser"] = None
        ser.close()
        st.ports["panel"] = None
        log.info("button panel gone")
        time.sleep(2)
