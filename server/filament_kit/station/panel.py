"""The button panel (station/panel/ firmware + PANEL.md in the repo): a D1 mini on USB serial with a buzzer, an OLED,
a speaker and two lit buttons, yellow (Hold) and red (Discard), relayed to the intake flow (`flow`).

The station keeps the panel's firmware current: a panel whose HELLO version differs from the bundled one
(STATION_PANEL_FW, VERSION beside it) is reflashed over USB with esptool, once per version per run, then found
again; if the flash doesn't take the panel is used as it is. STATION_PANEL_FLASH=0 turns that off.

Both the panel and the PN532 board use CH340 USB serial chips (no serial numbers), so the panel is found by its HELLO
and the reader gets the other ttyUSB port (NFC_DEVICE=auto).
Protocol (firmware 8), 115200 baud, one line each: PC -> panel `?`, `L <yellow> <red>` (lamp modes 0-4, resent every
second), `D <row> [text]` (OLED row 0 the title, 1-4 the body; sent when it changes), `B <hz> <ms> [count]`;
`A <n>` + n raw bytes (speech, see `speech`);
panel -> PC `HELLO intake-panel <version>`, `P H` (yellow, a short press, on release), `L H` (yellow held 0.8 s),
`P D` (red, at once), `AIR <C> <RH|-> <hPa>` (see `air`).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

from . import air, flow, wire
from . import state as st

log = logging.getLogger("intake-station")


def on_line(line: bytes):
    """One line from the panel: a button for the flow, or the room air."""
    if line == b"P H":
        flow.on_yellow(False)
    elif line == b"L H":
        flow.on_yellow(True)
    elif line == b"P D":
        flow.on_red()
    elif line.startswith(b"AIR "):
        air.on_air(line)


class Shown:
    """What this panel shows: the lamp modes last sent (and when) and its five display rows."""

    def __init__(self):
        self.lamps, self.at, self.rows = None, 0.0, [None] * 5


def refresh(seen: Shown, now: float) -> bool:
    """Keep the panel current: the lamps when they change, every second (its 5 s watchdog) or when the flow moved,
    then any display row that changed. False when the panel went away."""
    modes = flow.lamps(now)
    if modes != seen.lamps or now - seen.at >= 1 or st.panel_dirty.is_set():
        st.panel_dirty.clear()
        if not wire.panel_send("L %d %d" % modes):
            return False
        seen.lamps, seen.at = modes, now
        for i, row in enumerate(flow.screen()):
            if row != seen.rows[i] and wire.panel_send(("D %d %s" % (i, row)).rstrip()):
                seen.rows[i] = row
    return True


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
        seen = Shown()
        try:
            while st.panel["ser"] is ser:
                on_line(ser.readline().strip())
                if not refresh(seen, time.time()):  # the flow's timeouts: flow.tick_loop
                    break
        except Exception as e:  # unplugged
            log.warning("panel %s: %s", ser.port, e)
        with st.panel_lock:
            st.panel["ser"] = None
        ser.close()
        st.ports["panel"] = st.ports["panel_version"] = None
        log.info("button panel gone")
        time.sleep(2)
