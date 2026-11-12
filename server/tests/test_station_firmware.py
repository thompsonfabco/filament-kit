"""The station reflashes the button panel when its HELLO version differs from the bundled firmware (esptool, once per
version per run), and never writes to the NFC reader's port. Ported from filament-ops panel sync 2; subprocess and
serial are fakes."""
from __future__ import annotations

import subprocess
import os
import re
import sys
import time
import types
from pathlib import Path

import pytest

from filament_kit.station import panel
from filament_kit.station import state as st


class Done:
    def __init__(self, code=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = code, out, err


class FakeSerial:
    """pyserial stand-in: each port in VERSIONS says HELLO <version> on open; the rest stay silent."""
    VERSIONS: dict[str, str] = {}
    opened: list[str] = []

    def __init__(self):
        self.port = None
        self._lines: list[bytes] = []
        self.closed = False

    def open(self):
        FakeSerial.opened.append(self.port)
        if self.port in self.VERSIONS:
            self._lines.append(b"HELLO intake-panel %s\r\n" % self.VERSIONS[self.port].encode())

    def readline(self):
        time.sleep(0.005)
        return self._lines.pop(0) if self._lines else b""

    def write(self, data):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fw(tmp_path, monkeypatch):
    (tmp_path / "intake-panel.bin").write_bytes(b"\xe9fake")
    (tmp_path / "VERSION").write_text("2\n")
    monkeypatch.setitem(st.settings, "panel_fw", str(tmp_path / "intake-panel.bin"))
    monkeypatch.setitem(st.settings, "panel_flash", True)
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=FakeSerial))
    monkeypatch.setattr(st, "usb_ttys", lambda: ["/dev/ttyUSB0"])
    monkeypatch.setattr(st, "panel_ttys", lambda: ["/dev/ttyACM0", "/dev/ttyACM1"])
    monkeypatch.setattr(panel.time, "sleep", lambda s: None)
    monkeypatch.setitem(st.ports, "panel", None)
    monkeypatch.setitem(st.ports, "panel_version", None)
    monkeypatch.setitem(st.ports, "panel_chip", None)
    monkeypatch.setitem(st.ports, "nfc", None)
    st.flashed.clear()
    FakeSerial.VERSIONS = {"/dev/ttyACM1": "1 esp32c3"}
    FakeSerial.opened = []
    runs = []
    monkeypatch.setattr(panel.subprocess, "run", lambda a, **kw: runs.append(a) or Done(0, b"Hard resetting"))
    yield runs
    st.flashed.clear()


def test_fw_version_reads_version_beside_the_bin(fw, tmp_path):
    assert panel.fw_version() == "2"
    (tmp_path / "intake-panel.bin").unlink()
    assert panel.fw_version() is None  # nothing bundled
    st.settings["panel_fw"] = str(tmp_path / "nope" / "intake-panel.bin")
    assert panel.fw_version() is None


def test_hello_version_is_recorded(fw):
    ser = panel.find_panel()
    assert ser.panel_version == "1" and st.ports["panel_version"] == "1"
    FakeSerial.VERSIONS = {}
    assert panel.find_panel() is None and st.ports["panel_version"] is None


def test_old_firmware_is_flashed_once_with_esptool(fw, tmp_path):
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is True and ser.closed
    assert fw == [[sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", "/dev/ttyACM1", "--baud", "460800",
                   "--before", "default-reset", "--after", "hard-reset", "write-flash", "0x0", str(tmp_path / "intake-panel.bin")]]
    # it still says 1 afterwards (the flash didn't take): used as it is, not flashed again
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is False and len(fw) == 1


def test_current_firmware_is_left_alone(fw):
    FakeSerial.VERSIONS = {"/dev/ttyACM1": "2 esp32c3"}
    assert panel.update_firmware(panel.find_panel()) is False and fw == []


def test_newer_firmware_is_never_flashed_down(fw):
    """panel-c3 review, note 1: a panel on a later version than the bundled one (2 here) is used as it is."""
    for newer in ("3", "12"):
        FakeSerial.VERSIONS = {"/dev/ttyACM1": f"{newer} esp32c3"}
        assert panel.update_firmware(panel.find_panel()) is False and fw == [], newer


def test_older_means_older_by_number():
    assert panel._older("10", "11") and panel._older("9", "11") and panel._older("?", "11")
    assert not panel._older("12", "11") and not panel._older("11", "11") and not panel._older("1", "x")


def test_flash_off_or_nothing_bundled_leaves_the_panel(fw, tmp_path):
    st.settings["panel_flash"] = False
    assert panel.update_firmware(panel.find_panel()) is False and fw == []
    st.settings["panel_flash"] = True
    (tmp_path / "VERSION").unlink()
    assert panel.update_firmware(panel.find_panel()) is False and fw == []


def test_flash_failures_do_not_raise(fw, monkeypatch):
    def boom(a, **kw):
        raise subprocess.TimeoutExpired("esptool", 180)
    monkeypatch.setattr(panel.subprocess, "run", boom)
    assert panel.update_firmware(panel.find_panel()) is True  # tried; the loop looks again and uses it as it is
    monkeypatch.setattr(panel.subprocess, "run", lambda a, **kw: (_ for _ in ()).throw(FileNotFoundError("python")))
    panel.flash_panel("/dev/ttyACM1", "2")


def test_never_flashes_the_nfc_readers_port(fw):
    st.ports["nfc"] = "/dev/ttyACM1"
    panel.flash_panel("/dev/ttyACM1", "2")
    assert fw == []
    # and the panel search never even opens the reader's port, so it can't be picked for a flash
    FakeSerial.VERSIONS = {"/dev/ttyACM0": "1 esp32c3", "/dev/ttyACM1": "1 esp32c3"}
    ser = panel.find_panel()
    assert ser.port == "/dev/ttyACM0" and "/dev/ttyACM1" not in FakeSerial.opened
    assert panel.update_firmware(ser) is True
    assert [c[c.index("--port") + 1] for c in fw] == ["/dev/ttyACM0"]


def test_nfc_port_stays_out_of_the_panels_way_while_flashing(fw):
    """The panel's port stays claimed (ports["panel"]) through the flash, so nfcpy picks the other port."""
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is True
    assert st.ports["panel"] == "/dev/ttyACM1"
    from filament_kit.station import nfc
    assert nfc.nfc_path() == "tty:USB0:pn532"


def test_bundled_firmware_is_version_12_and_flashes_an_older_c3_panel(fw, monkeypatch):
    """The repo's own bundled pair (not the fixture's) is what the self-flash logic picks up."""
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "station", "panel", "firmware")
    bundled = os.path.normpath(bundled)   # from the test file: the package may be installed (CI), not editable
    monkeypatch.setitem(st.settings, "panel_fw", os.path.join(bundled, "intake-panel.bin"))
    assert panel.fw_version() == "12"
    FakeSerial.VERSIONS = {"/dev/ttyACM1": "10 esp32c3"}
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is True
    assert fw == [[sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", "/dev/ttyACM1", "--baud", "460800",
                   "--before", "default-reset", "--after", "hard-reset", "write-flash", "0x0",
                   os.path.join(bundled, "intake-panel.bin")]]
    st.flashed.clear()
    fw.clear()
    FakeSerial.VERSIONS = {"/dev/ttyACM1": "12 esp32c3"}
    assert panel.update_firmware(panel.find_panel()) is False and fw == []


def test_old_esp8266_panel_is_never_flashed(fw, tmp_path, caplog):
    (tmp_path / "VERSION").write_text("10\n")
    FakeSerial.VERSIONS = {"/dev/ttyACM1": "9"}  # no chip token: an ESP8266
    ser = panel.find_panel()
    assert ser is not None and ser.panel_chip is None
    with caplog.at_level("WARNING"):
        assert panel.update_firmware(ser) is False
    assert fw == [] and not ser.closed  # still in use
    assert len([r for r in caplog.records if "old firmware" in r.getMessage()]) == 1


# ---------- the committed firmware: built from this source, by a known platform ----------

PANEL_DIR = Path(__file__).resolve().parents[2] / "station" / "panel"


def test_the_bundled_version_is_the_sources():
    """A VERSION bump in main.cpp with no rebuild would ship the old bin: the station flashes it, reads the old HELLO
    back, and reports "flashing it didn't take" on every start. build.sh writes both, so they only differ if it wasn't run."""
    src = re.search(r'^static const char \*VERSION = "([^"]*)";', (PANEL_DIR / "src" / "main.cpp").read_text(encoding="utf-8"),
                    re.M)
    assert src, "no VERSION in main.cpp"
    assert (PANEL_DIR / "firmware" / "VERSION").read_text(encoding="utf-8").strip() == src.group(1)


def test_the_build_platform_is_pinned():
    """An unpinned platform builds different firmware from the same source as soon as PlatformIO updates it."""
    ini = (PANEL_DIR / "platformio.ini").read_text(encoding="utf-8")
    assert re.search(r"^platform = https://github\.com/pioarduino/platform-espressif32/releases/download/53\.03\.13/"
                     r"platform-espressif32\.zip\s*$", ini, re.M)
    assert re.search(r"^board = esp32-c3-devkitm-1\b", ini, re.M)


# The peripheral standard's pins for the panel (spec "Pins"): never a strapping pin (2, 8, 9) or the USB pair (18, 19).
STANDARD_PINS = {"PIN_SDA": 5, "PIN_SCL": 6, "PIN_BUZZER": 0, "PIN_BTN_HOLD": 3, "PIN_BTN_DISCARD": 4,
                 "PIN_LAMP_HOLD": 1, "PIN_LAMP_DISCARD": 7, "PIN_I2S_BCLK": 10, "PIN_I2S_LRC": 20, "PIN_I2S_DIN": 21}


def test_firmware_pins_follow_the_standard():
    src = (PANEL_DIR / "src" / "main.cpp").read_text(encoding="utf-8")
    pins = {name: int(value) for name, value in re.findall(r"^static const uint8_t (PIN_\w+) = (\d+);", src, re.M)}
    assert pins == STANDARD_PINS
    assert not set(pins.values()) & {2, 8, 9, 18, 19}


def test_firmware_never_starts_the_radio():
    src = (PANEL_DIR / "src" / "main.cpp").read_text(encoding="utf-8")
    for used in ("WiFi.h", "BLEDevice", "WiFi.begin", "esp_wifi_start"):
        assert used not in src


def _close(src: str, i: int) -> int:
    """Index just past the `}` closing the block whose body starts at `i`."""
    depth = 1
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return i


def _body(src: str, name: str) -> str:
    """The brace-matched body of the function `name` (any storage specifiers; "" if absent)."""
    m = re.search(r"\bvoid\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    return src[m.end():_close(src, m.end()) - 1] if m else ""


def buzzer_problems(path: Path) -> list[str]:
    """Ways the buzzer could be left LOW (on) when silent. The buzzer module is low-level trigger: pin LOW is on, so duty 0
    / tone 0 would hold it on with DC in the coil. Silence is buzzerIdle() (LEDC detached, pin an OUTPUT driven HIGH); LEDC
    use is confined to buzzerTone()."""
    src = re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    idle, tone = _body(src, "buzzerIdle"), _body(src, "buzzerTone")
    if not idle or not tone:
        return ["buzzerIdle()/buzzerTone() missing"]
    out = []
    ledc = r"\bledc(?:Write\w*|Attach\w*)\(\s*PIN_BUZZER\b"
    if len(re.findall(ledc, src)) != len(re.findall(ledc, tone)):
        out.append("LEDC on PIN_BUZZER outside buzzerTone()")
    if re.search(r"\b(?:analogWrite|tone|noTone)\s*\(\s*PIN_BUZZER\b", src):
        out.append("analogWrite/tone/noTone must not name PIN_BUZZER")
    writes = re.findall(r"\bdigitalWrite\(\s*PIN_BUZZER\b[^;]*;", src)
    if not any(w in idle for w in writes) or not all(re.fullmatch(r"digitalWrite\(\s*PIN_BUZZER\s*,\s*HIGH\s*\);", w) for w in writes):
        out.append("every digitalWrite(PIN_BUZZER) must be HIGH, and buzzerIdle() must have one")
    modes = re.findall(r"\bpinMode\(\s*PIN_BUZZER\b[^;]*;", src)
    if len(modes) != 1 or modes[0] not in idle or not re.fullmatch(r"pinMode\(\s*PIN_BUZZER\s*,\s*OUTPUT\s*\);", modes[0]):
        out.append("pinMode(PIN_BUZZER) must appear once, as OUTPUT, inside buzzerIdle()")
    if "buzzerIdle()" not in _body(src, "setup"):
        out.append("setup() does not call buzzerIdle()")
    # Every clear of `beeping` (bar its declaration) must sit with a buzzerIdle() call: in the same braces, or the same
    # brace-less statement.
    clears = [m for m in re.finditer(r"\bbeeping\s*=\s*false\b", src) if not re.search(r"\bbool\s+$", src[:m.start()])]
    for m in clears:
        start = max(src.rfind(c, 0, m.start()) for c in "{}") + 1
        end = _close(src, start) if src[start - 1] == "{" else src.find(";", m.end()) + 1
        if "buzzerIdle()" not in src[start:end]:
            out.append("a beeping clear does not call buzzerIdle()")
    if not clears:
        out.append("end of beep does not clear beeping")
    return out


def test_firmware_never_idles_the_active_low_buzzer_low():
    assert buzzer_problems(PANEL_DIR / "src" / "main.cpp") == []
