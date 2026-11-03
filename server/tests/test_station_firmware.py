"""The station reflashes the button panel when its HELLO version differs from the bundled firmware (esptool, once per
version per run), and never writes to the NFC reader's port. Ported from filament-ops panel sync 2; subprocess and
serial are fakes."""
from __future__ import annotations

import subprocess
import os
import sys
import time
import types

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
    monkeypatch.setattr(st, "usb_ttys", lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"])
    monkeypatch.setattr(panel.time, "sleep", lambda s: None)
    monkeypatch.setitem(st.ports, "panel", None)
    monkeypatch.setitem(st.ports, "panel_version", None)
    monkeypatch.setitem(st.ports, "nfc", None)
    st.flashed.clear()
    FakeSerial.VERSIONS = {"/dev/ttyUSB1": "1"}
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
    assert fw == [[sys.executable, "-m", "esptool", "--chip", "esp8266", "--port", "/dev/ttyUSB1", "--baud", "460800",
                   "write-flash", "0x0", str(tmp_path / "intake-panel.bin")]]
    # it still says 1 afterwards (the flash didn't take): used as it is, not flashed again
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is False and len(fw) == 1


def test_current_firmware_is_left_alone(fw):
    FakeSerial.VERSIONS = {"/dev/ttyUSB1": "2"}
    assert panel.update_firmware(panel.find_panel()) is False and fw == []


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
    panel.flash_panel("/dev/ttyUSB1", "2")


def test_never_flashes_the_nfc_readers_port(fw):
    st.ports["nfc"] = "/dev/ttyUSB1"
    panel.flash_panel("/dev/ttyUSB1", "2")
    assert fw == []
    # and the panel search never even opens the reader's port, so it can't be picked for a flash
    FakeSerial.VERSIONS = {"/dev/ttyUSB0": "1", "/dev/ttyUSB1": "1"}
    ser = panel.find_panel()
    assert ser.port == "/dev/ttyUSB0" and "/dev/ttyUSB1" not in FakeSerial.opened
    assert panel.update_firmware(ser) is True
    assert [c[c.index("--port") + 1] for c in fw] == ["/dev/ttyUSB0"]


def test_nfc_port_stays_out_of_the_panels_way_while_flashing(fw):
    """The panel's port stays claimed (ports["panel"]) through the flash, so nfcpy picks the other port."""
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is True
    assert st.ports["panel"] == "/dev/ttyUSB1"
    from filament_kit.station import nfc
    assert nfc.nfc_path() == "tty:USB0:pn532"


def test_bundled_firmware_is_version_6_and_flashes_an_older_panel(fw, monkeypatch):
    """The repo's own bundled pair (not the fixture's) is what the self-flash logic picks up."""
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "station", "panel", "firmware")
    bundled = os.path.normpath(bundled)   # from the test file: the package may be installed (CI), not editable
    monkeypatch.setitem(st.settings, "panel_fw", os.path.join(bundled, "intake-panel.bin"))
    assert panel.fw_version() == "6"
    FakeSerial.VERSIONS = {"/dev/ttyUSB1": "5"}
    ser = panel.find_panel()
    assert panel.update_firmware(ser) is True
    assert fw == [[sys.executable, "-m", "esptool", "--chip", "esp8266", "--port", "/dev/ttyUSB1", "--baud", "460800",
                   "write-flash", "0x0", os.path.join(bundled, "intake-panel.bin")]]
    st.flashed.clear()
    fw.clear()
    FakeSerial.VERSIONS = {"/dev/ttyUSB1": "6"}
    assert panel.update_firmware(panel.find_panel()) is False and fw == []
