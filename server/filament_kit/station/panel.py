"""The button panel (station/panel/ firmware + PANEL.md in the repo): an ESP32-C3 on USB serial with a buzzer, an OLED,
a speaker and two lit buttons, yellow (Hold) and red (Discard), relayed to the intake flow (`flow`).

The station keeps the panel's firmware current: a panel whose HELLO version differs from the bundled one
(STATION_PANEL_FW, VERSION beside it) is reflashed over USB with esptool, once per version per run, then found
again; if the flash doesn't take the panel is used as it is. STATION_PANEL_FLASH=0 turns that off.

The panel is found by its HELLO: ttyACM ports with USB vendor 303a (the C3), then ttyUSB; an old CH340 panel and the
PN532 board can swap ttyUSB numbers, so the reader gets the other port (NFC_DEVICE=auto).
Protocol (firmware 10), 115200 baud, one line each: PC -> panel `?`, `L <yellow> <red>` (lamp modes 0-4, resent every
second), `D <row> [text]` (OLED row 0 the title, 1-4 the body; sent when it changes), `B <hz> <ms> [count]`, `V <percent>` (speech volume, 0-100);
`A <n>` + n raw bytes (speech, see `speech`);
panel -> PC `HELLO intake-panel <version> [<chip>]` (firmware 10: `esp32c3`; no chip token: an ESP8266), `P H` / `P D` (the yellow / red button, a short press, on release),
`L H` / `L D` (the yellow / red button held 0.8 s), `AIR <C> <RH|-> <hPa>` (see `air`).

`H` is yellow and `D` red, as PANEL.md wires them. A panel wired the other way round (yellow's button and
lamp on red's pins) sets station.panel_swap (STATION_PANEL_SWAP=1): the buttons' roles and the `L` lamp modes are swapped
here, so the wiring never needs a reflash. Firmware 9 reports both buttons alike for that; a long press on red
cancels like a short one.
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
    if line in (b"P H", b"L H", b"P D", b"L D"):
        kind, pin = line.split()
        if (pin == b"H") != st.settings["panel_swap"]:  # yellow: advance, a long press saves
            flow.on_yellow(kind == b"L")
        else:  # red: cancel, short or long
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
        if not wire.panel_send("L %d %d" % (modes[::-1] if st.settings["panel_swap"] else modes)):
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
    """Write the bundled (merged, address 0) firmware to the ESP32-C3 panel on dev with esptool (its native USB
    resets into the ROM bootloader, so a failed write can always be retried). Never touches the reader's port; keeps the panel's port
    claimed (ports["panel"]) so nfcpy never opens it meanwhile. True only when esptool exits 0."""
    if dev == st.ports["nfc"]:
        log.warning("not flashing %s: it is the NFC reader's port", dev)
        return False
    log.info("flashing button panel on %s with firmware %s", dev, version)
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", dev, "--baud", "460800",
           "--before", "default-reset", "--after", "hard-reset", "write-flash", "0x0", st.settings["panel_fw"]]
    ok = False
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=180)
        ok = p.returncode == 0
        tail = (p.stdout + p.stderr).decode(errors="replace").strip().splitlines()[-3:]
        (log.info if p.returncode == 0 else log.warning)("esptool exit %d: %s", p.returncode, " | ".join(tail))
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("esptool: %s", e)
    time.sleep(2)  # let it boot
    return ok


def update_firmware(ser):
    """Reflash the ESP32-C3 panel behind ser if it runs other firmware than the bundled one. True when it was flashed (ser is
    closed; look for the panel again). Once per bundled version and run, so a build that won't take can't loop; then
    the panel is used as it is."""
    want = fw_version()
    if not want or ser.panel_version == want:
        return False
    if ser.panel_chip != "esp32c3":  # an ESP8266 panel: the C3 image would not run on it; never flash it
        log.warning("button panel runs old firmware %s (an ESP8266, not the bundled %s); using it as it is",
                    ser.panel_version, want)
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
    ser.write_timeout = 1  # a stalled port must not hold panel_lock for long
    ser.dtr = ser.rts = False  # don't hold the board in reset or flash mode
    try:
        ser.open()
        end, asked = time.time() + 3, False
        while time.time() < end:
            hello = ser.readline().split()
            if hello[:2] == [b"HELLO", b"intake-panel"]:
                ser.panel_version = hello[2].decode(errors="replace") if len(hello) > 2 else "?"
                ser.panel_chip = hello[3].decode(errors="replace") if len(hello) > 3 else None  # none: ESP8266
                return ser
            if not asked and time.time() > end - 1.5:
                ser.write(b"?\n")  # it didn't reset on open: ask
                asked = True
    except Exception:
        pass
    ser.close()
    return None


def blank_c3_ports():
    """The ttyACM ports of an Espressif USB device (303a) that give no HELLO within 3 s: candidates for a first flash.
    Never a ttyUSB port (the PN532 or an old panel). A bench reader plugged in for power looks the same as a blank
    board, so these are only candidates; the owner confirms each one."""
    blank = []
    for dev in st.panel_ttys():
        if not os.path.basename(dev).startswith("ttyACM") or st.usb_vendor(dev) != st.PANEL_VENDOR:
            continue
        ser = open_panel(dev)
        if ser:
            ser.close()
        else:
            blank.append(dev)
    return blank


def find_panel():
    """One pass over the USB serial ports (skipping the reader's): the panel's port, or None. Records the result in
    ports["panel"] and sets `probed`, so the reader loop then takes another port."""
    ser = None
    for dev in st.panel_ttys():
        if dev != st.ports["nfc"] and (ser := open_panel(dev)):
            break
    st.ports["panel"] = ser.port if ser else None
    st.ports["panel_version"] = ser.panel_version if ser else None
    st.ports["panel_chip"] = ser.panel_chip if ser else None
    st.probed.set()  # after ports["panel"], so a waiting reader never sees the panel's port as free
    return ser


def warn_swap_needs_fw9(version):
    """station.panel_swap with a panel older than firmware 9: its D2 button has no long press, so a swapped yellow
    can't save. Say so; the panel is used as it is (panel_flash may be off on purpose). True when warned."""
    if not st.settings["panel_swap"]:
        return False
    try:
        if int(version) >= 9:
            return False
    except (TypeError, ValueError):
        pass
    log.warning("station.panel_swap is on but the panel runs firmware %s: yellow (on D2) can't long-press to save "
                "until the panel has firmware 9 or later (STATION_PANEL_FLASH=1 reflashes it)", version)
    return True


def send_volume():
    """Tell the C3 panel the speaker volume (percent). A setting change rewrites the drop-in and restarts the
    service, so one send when the panel is found covers changes."""
    return wire.panel_send("V %d" % st.settings["speaker_volume"])


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
        warn_swap_needs_fw9(ser.panel_version)
        with st.panel_lock:
            st.panel["ser"] = ser
        if ser.panel_chip == "esp32c3":
            send_volume()
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
        st.ports["panel"] = st.ports["panel_version"] = st.ports["panel_chip"] = None
        log.info("button panel gone")
        time.sleep(2)
