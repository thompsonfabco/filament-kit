"""`station flash-panel`: writes the panel firmware to a blank C3 only after the owner confirms the port. The USB
ports, the HELLO probe, esptool and systemctl are fakes."""
from __future__ import annotations

import pytest

from filament_kit import cli
from filament_kit.station import panel
from filament_kit.station import state as st

SVC = ["systemctl", "{}", "filament-kit-station.service"]


class Probe:
    """open_panel stand-in: ports in HELLO answer (and hand back a Serial to close); the rest stay silent."""
    def __init__(self, hello=()):
        self.hello, self.opened, self.sers, self.version = set(hello), [], [], "10"

    def __call__(self, dev):
        self.opened.append(dev)
        if dev not in self.hello:
            return None
        ser = type("S", (), {"port": dev, "panel_version": self.version, "closed": False, "close": lambda s: setattr(s, "closed", True)})()
        self.sers.append(ser)
        return ser


@pytest.fixture
def bench(monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(st, "panel_ttys", lambda: ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0"])
    monkeypatch.setattr(st, "usb_vendor", lambda dev: "303a" if "ACM" in dev else "1a86")
    monkeypatch.setattr(panel, "fw_version", lambda: "10")
    probe = Probe()
    monkeypatch.setattr(panel, "open_panel", probe)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    flashed = []

    def flash(dev, version):  # a good flash: the board then says HELLO with the new version
        flashed.append((dev, version))
        probe.hello.add(dev)
        return True
    monkeypatch.setattr(panel, "flash_panel", flash)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()
    return type("B", (), {"probe": probe, "flashed": flashed, "calls": calls, "run": staticmethod(run)})


def services(b):
    return [c[1] for c in b.calls if c[0] == "systemctl"]


def test_flash_panel_needs_root(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert "root" in capsys.readouterr().err
    assert bench.calls == [] and bench.flashed == []


def test_no_blank_board_flashes_nothing_and_restarts_service(bench):
    bench.probe.hello = {"/dev/ttyACM0", "/dev/ttyACM1"}
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert bench.flashed == []
    assert services(bench) == ["stop", "start"]


def test_declined_port_is_not_flashed(bench):
    asked = []
    answers = iter(["", "no"])
    assert cli.cmd_station_flash_panel(ask=lambda p: asked.append(p) or next(answers), run=bench.run) == 1
    assert bench.flashed == []
    assert asked == ["Flash the intake panel firmware to /dev/ttyACM0? [y/N] ",
                     "Flash the intake panel firmware to /dev/ttyACM1? [y/N] "]
    assert services(bench) == ["stop", "start"]


def test_confirmed_port_is_flashed_with_c3_command(bench):
    answers = iter(["n", "YES"])
    assert cli.cmd_station_flash_panel(ask=lambda p: next(answers), run=bench.run) == 0
    assert bench.flashed == [("/dev/ttyACM1", "10")]
    assert "/dev/ttyUSB0" not in bench.probe.opened
    assert services(bench) == ["stop", "start"]


def test_a_port_that_says_hello_is_not_offered(bench):
    bench.probe.hello = {"/dev/ttyACM0"}
    asked = []
    assert cli.cmd_station_flash_panel(ask=lambda p: asked.append(p) or "y", run=bench.run) == 0
    assert bench.flashed == [("/dev/ttyACM1", "10")]
    assert len(asked) == 1 and "ttyACM0" not in asked[0]
    assert all(s.closed for s in bench.probe.sers)


def test_service_restarted_when_flash_raises(bench, monkeypatch):
    def boom(dev, version):
        raise RuntimeError("esptool died")
    monkeypatch.setattr(panel, "flash_panel", boom)
    with pytest.raises(RuntimeError):
        cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run)
    assert services(bench) == ["stop", "start"]


def test_no_bundled_firmware_is_an_error_and_restarts_service(bench, monkeypatch, capsys):
    monkeypatch.setattr(panel, "fw_version", lambda: None)
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert "firmware" in capsys.readouterr().err
    assert bench.flashed == [] and services(bench) == ["stop", "start"]


def test_blank_c3_ports_ignores_ttyusb_and_other_vendors(monkeypatch):
    monkeypatch.setattr(st, "panel_ttys", lambda: ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0"])
    monkeypatch.setattr(st, "usb_vendor", lambda dev: {"/dev/ttyACM0": "303a"}.get(dev, "303a" if "USB" in dev else "2341"))
    monkeypatch.setattr(panel, "open_panel", Probe())
    assert panel.blank_c3_ports() == ["/dev/ttyACM0"]


def test_failed_esptool_exits_1(bench, monkeypatch, capsys):
    monkeypatch.setattr(panel, "flash_panel", lambda dev, version: False)
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert "ttyACM0" in capsys.readouterr().err
    assert services(bench) == ["stop", "start"]


def test_flash_without_hello_afterwards_exits_1(bench, monkeypatch, capsys):
    monkeypatch.setattr(panel, "flash_panel", lambda dev, version: True)  # esptool ok, board stays silent
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert "ttyACM0" in capsys.readouterr().err
    assert bench.probe.opened == ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM0"]


def test_flash_with_wrong_version_afterwards_exits_1(bench):
    orig = panel.flash_panel
    bench.probe.version = "9"

    def flash(dev, version):
        bench.probe.hello.add(dev)
        return True
    panel.flash_panel = flash
    try:
        assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    finally:
        panel.flash_panel = orig


def test_flash_with_matching_hello_exits_0(bench, capsys):
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 0
    assert "Wrote panel firmware 10" in capsys.readouterr().out
    assert bench.probe.sers[-1].closed


def test_failed_service_stop_aborts(bench, capsys):
    def run(cmd, **kw):
        bench.calls.append(cmd)
        return type("R", (), {"returncode": 1 if cmd[1] == "stop" else 0})()
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=run) == 1
    assert bench.probe.opened == [] and bench.flashed == []
    assert services(bench) == ["stop", "start"]
    assert "stop" in capsys.readouterr().err


def test_unit_not_loaded_stop_is_fine(bench):
    def run(cmd, **kw):
        bench.calls.append(cmd)
        return type("R", (), {"returncode": 5 if cmd[1] == "stop" else 0})()
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=run) == 0


def test_stop_happens_before_the_first_probe(bench, monkeypatch):
    order = []
    monkeypatch.setattr(panel, "open_panel", lambda dev: order.append(("probe", dev)))
    monkeypatch.setattr(panel, "blank_c3_ports", panel.blank_c3_ports)
    cli.cmd_station_flash_panel(ask=lambda p: "n",
                                run=lambda cmd, **kw: order.append((cmd[1],)) or type("R", (), {"returncode": 0})())
    assert order[0] == ("stop",) and order[1][0] == "probe"


def test_ctrl_c_at_the_prompt_flashes_nothing_and_restarts(bench, capsys):
    def ask(p):
        raise KeyboardInterrupt
    assert cli.cmd_station_flash_panel(ask=ask, run=bench.run) == 1
    assert "Nothing was flashed." in capsys.readouterr().out
    assert bench.flashed == [] and services(bench) == ["stop", "start"]
