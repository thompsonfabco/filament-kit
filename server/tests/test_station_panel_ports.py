"""The panel search: ttyACM ports only with the Espressif USB vendor ID, the HELLO chip token, and the 1 s write
timeout that drops a stalled panel. sysfs, glob and serial are fakes."""
from __future__ import annotations

import sys
import time
import types

import pytest

from filament_kit.station import panel, wire
from filament_kit.station import state as st

# the fake sysfs tree has folders like 1-1:1.0, which Windows cannot make; the station runs on Linux only
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="sysfs folder names with a colon (Linux only)")


class SerialTimeoutException(Exception):
    pass


class FakeSerial:
    """pyserial stand-in: each port in HELLOS answers that line on open; the rest stay silent."""
    HELLOS: dict[str, bytes] = {}
    opened: list[str] = []

    def __init__(self):
        self.port = None
        self.write_timeout = None
        self._lines: list[bytes] = []
        self.closed = False

    def open(self):
        FakeSerial.opened.append(self.port)
        if self.port in self.HELLOS:
            self._lines.append(self.HELLOS[self.port] + b"\r\n")

    def readline(self):
        time.sleep(0.005)
        return self._lines.pop(0) if self._lines else b""

    def write(self, data):
        pass

    def close(self):
        self.closed = True


class StopLoop(Exception):
    pass


@pytest.fixture
def ports(tmp_path, monkeypatch):
    for name, vendor in (("ttyACM0", "2e8a"), ("ttyACM1", "303A\n")):
        dev = tmp_path / "usb" / name / "1-1" / "1-1:1.0"
        dev.mkdir(parents=True)
        (dev.parent / "idVendor").write_text(vendor)
        tty = tmp_path / "sys" / name
        tty.mkdir(parents=True)
        (tty / "device").symlink_to(dev, target_is_directory=True)
    monkeypatch.setattr(st, "SYSFS_TTY", str(tmp_path / "sys"))
    monkeypatch.setattr(st.glob, "glob", lambda pat: {"/dev/ttyACM*": ["/dev/ttyACM1", "/dev/ttyACM0"],
                                                      "/dev/ttyUSB*": ["/dev/ttyUSB0"]}[pat])
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(
        Serial=FakeSerial, SerialTimeoutException=SerialTimeoutException))
    monkeypatch.setattr(panel.time, "sleep", lambda s: None)
    for k in ("panel", "panel_version", "panel_chip", "nfc"):
        monkeypatch.setitem(st.ports, k, None)
    monkeypatch.setitem(st.panel, "ser", None)
    FakeSerial.HELLOS = {}
    FakeSerial.opened = []


def test_acm_ports_need_the_espressif_vendor(ports):
    assert st.usb_vendor("/dev/ttyACM1") == "303a" and st.usb_vendor("/dev/ttyACM0") == "2e8a"
    assert st.usb_vendor("/dev/ttyACM7") is None
    assert st.panel_ttys() == ["/dev/ttyACM1", "/dev/ttyUSB0"]


def test_foreign_acm_board_is_never_opened(ports):
    FakeSerial.HELLOS = {"/dev/ttyACM0": b"HELLO intake-panel 10 esp32c3"}
    assert panel.find_panel() is None
    assert "/dev/ttyACM0" not in FakeSerial.opened


def test_c3_panel_found_before_usb_ports(ports):
    FakeSerial.HELLOS = {"/dev/ttyACM1": b"HELLO intake-panel 10 esp32c3"}
    ser = panel.find_panel()
    assert ser.port == "/dev/ttyACM1" and FakeSerial.opened == ["/dev/ttyACM1"]
    assert ser.write_timeout == 1


def test_hello_chip_token_recorded(ports):
    FakeSerial.HELLOS = {"/dev/ttyACM1": b"HELLO intake-panel 10 esp32c3"}
    ser = panel.find_panel()
    assert (ser.panel_version, ser.panel_chip) == ("10", "esp32c3")
    assert (st.ports["panel_version"], st.ports["panel_chip"]) == ("10", "esp32c3")
    FakeSerial.HELLOS = {"/dev/ttyUSB0": b"HELLO intake-panel 9"}
    ser = panel.find_panel()
    assert (ser.panel_version, ser.panel_chip) == ("9", None) and st.ports["panel_chip"] is None


def test_c3_that_is_not_a_panel_is_skipped(ports):
    FakeSerial.HELLOS = {"/dev/ttyACM1": b"HELLO something-else 1"}
    assert panel.open_panel("/dev/ttyACM1") is None
    assert panel.find_panel() is None and st.ports["panel"] is None and st.ports["panel_chip"] is None


def test_write_timeout_drops_and_refinds_panel(ports, monkeypatch):
    class Stalled(FakeSerial):
        def write(self, data):
            raise SerialTimeoutException("write timeout")

    ser = Stalled()
    ser.port = "/dev/ttyACM1"
    monkeypatch.setitem(st.panel, "ser", ser)
    assert wire.panel_send("L 0 0") is False and st.panel["ser"] is None

    ser.panel_version, ser.panel_chip = "10", "esp32c3"
    finds = []

    def find():
        finds.append(1)
        if len(finds) > 1:
            raise StopLoop
        return ser

    monkeypatch.setattr(panel, "find_panel", find)
    monkeypatch.setattr(panel, "update_firmware", lambda s: False)
    with pytest.raises(StopLoop):
        panel.panel_loop()
    assert len(finds) == 2 and st.panel["ser"] is None and st.ports["panel_chip"] is None


def test_empty_passes_back_off_and_a_new_port_cuts_the_wait_short(ports, monkeypatch):
    sleeps, passes = [], []
    listing = ["/dev/ttyUSB0"]

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 6:
            listing.append("/dev/ttyUSB1")  # a port appears in the third step of the slow wait

    def find():
        passes.append(1)
        if len(passes) == 5:
            raise StopLoop
        return None

    monkeypatch.setattr(panel.time, "sleep", sleep)
    monkeypatch.setattr(st, "panel_ttys", lambda: list(listing))
    monkeypatch.setattr(panel, "find_panel", find)
    with pytest.raises(StopLoop):
        panel.panel_loop()
    assert sleeps == [5] * 6  # passes 1-3 wait 5 s; pass 4 starts the slow wait and the new port ends it after 3 steps


def test_slow_wait_runs_the_whole_minute_when_the_ports_stay_the_same(ports, monkeypatch):
    sleeps = []
    monkeypatch.setattr(panel.time, "sleep", sleeps.append)
    monkeypatch.setattr(st, "panel_ttys", lambda: ["/dev/ttyUSB0"])
    panel.wait_for_panel(panel.EMPTY_PASSES + 1)
    assert sum(sleeps) == panel.SLOW_SECONDS
