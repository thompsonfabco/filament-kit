"""The optional button panel (station/panel/ firmware + PANEL.md in the repo): a D1 mini on USB serial with a buzzer
and lit Hold / Discard buttons.

The station keeps the panel's firmware current: a panel whose HELLO version differs from the bundled one
(STATION_PANEL_FW, VERSION beside it) is reflashed over USB with esptool, once per version per run, then found
again; if the flash doesn't take the panel is used as it is. STATION_PANEL_FLASH=0 turns that off.

Hold keeps the current weight with the scan (both stay current for the phone app until Discard or the next scan:
"held" in /state); Discard forgets the scan and weight. Both the panel and the PN532 board use CH340 USB serial chips
(no serial numbers), so the panel is found by its HELLO and the reader gets the other ttyUSB port (NFC_DEVICE=auto).
Protocol, 115200 baud, one line each: PC -> panel `?`, `L <hold> <discard>`, `B <hz> <ms> [count]`;
`A <n>` + n raw bytes (speech, see `speech`);
panel -> PC `HELLO intake-panel <version>`, `P H`, `P D`, `AIR <C> <RH|-> <hPa>` (see `air`).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

from . import air, beep, camera, speech, wire
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


def fw_version():
    """The version of the panel firmware bundled with the station (VERSION beside STATION_PANEL_FW), or None."""
    fw = st.settings["panel_fw"]
    try:
        return open(os.path.join(os.path.dirname(fw), "VERSION")).read().strip() if os.path.exists(fw) else None
    except OSError:
        return None


def flash_panel(dev, version):
    """Write the bundled firmware to the panel on dev with esptool (the D1 mini's USB chip resets it into its ROM
    bootloader, so a failed write can always be retried). Never touches the reader's port; keeps the panel's port
    claimed (ports["panel"]) so nfcpy never opens it meanwhile."""
    if dev == st.ports["nfc"]:
        log.warning("not flashing %s: it is the NFC reader's port", dev)
        return
    log.info("flashing button panel on %s with firmware %s", dev, version)
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp8266", "--port", dev, "--baud", "460800",
           "write-flash", "0x0", st.settings["panel_fw"]]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=180)
        tail = (p.stdout + p.stderr).decode(errors="replace").strip().splitlines()[-3:]
        (log.info if p.returncode == 0 else log.warning)("esptool exit %d: %s", p.returncode, " | ".join(tail))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("esptool: %s", e)
    time.sleep(2)  # let it boot


def update_firmware(ser):
    """Reflash the panel behind ser if it runs other firmware than the bundled one. True when it was flashed (ser is
    closed; look for the panel again). Once per bundled version and run, so a build that won't take can't loop; then
    the panel is used as it is."""
    want = fw_version()
    if not want or ser.panel_version == want:
        return False
    if st.settings["panel_flash"] and want not in st.flashed:
        st.flashed.add(want)
        ser.close()
        flash_panel(ser.port, want)
        return True
    log.warning("button panel runs firmware %s, not the bundled %s; using it as it is (%s)",
                ser.panel_version, want,
                "STATION_PANEL_FLASH=0" if not st.settings["panel_flash"] else "flashing it didn't take")
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
            hello = ser.readline().split()
            if hello[:2] == [b"HELLO", b"intake-panel"]:
                ser.panel_version = hello[2].decode(errors="replace") if len(hello) > 2 else "?"
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
    st.ports["panel_version"] = ser.panel_version if ser else None
    st.probed.set()  # after ports["panel"], so a waiting reader never sees the panel's port as free
    return ser


def panel_loop():
    """Find the button panel among the USB serial ports, then relay its presses and keep its lamps current."""
    while True:
        ser = find_panel()
        if not ser:
            time.sleep(5)
            continue
        log.info("button panel on %s (firmware %s)", ser.port, ser.panel_version)
        if update_firmware(ser):
            continue  # look for it again: it boots the new firmware and says HELLO
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
                    if not wire.panel_send("L %d %d" % modes):
                        break
                    sent, last_sent = modes, now
        except Exception as e:  # unplugged
            log.warning("panel %s: %s", ser.port, e)
        with st.panel_lock:
            st.panel["ser"] = None
        ser.close()
        st.ports["panel"] = st.ports["panel_version"] = None
        log.info("button panel gone")
        time.sleep(2)
