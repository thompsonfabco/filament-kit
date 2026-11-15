"""`station flash-panel`: writes the panel firmware to a blank C3 only after the owner confirms the port. The USB
ports, the HELLO probe, esptool and systemctl are fakes."""
from __future__ import annotations

import pytest

from filament_kit import cli
from filament_kit.station import panel
from filament_kit.station import state as st


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
    return [c[1] for c in b.calls if c[0] == "systemctl" and c[1] != "is-active"]


def test_flash_panel_needs_root(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 3
    assert "administrator rights" in capsys.readouterr().err
    assert bench.calls == [] and bench.flashed == []


def test_no_blank_board_flashes_nothing_and_restarts_service(bench):
    bench.probe.hello = {"/dev/ttyACM0", "/dev/ttyACM1"}
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert bench.flashed == []
    assert services(bench) == ["stop", "start"]


def test_declined_port_is_not_flashed(bench, capsys):
    answers = iter(["", "no"])

    def ask(prompt):
        print(prompt, end="")               # what the real input() writes at a terminal
        return next(answers)
    assert cli.cmd_station_flash_panel(ask=ask, run=bench.run) == 5
    assert bench.flashed == []
    said = " ".join(capsys.readouterr().out.split())
    assert "Write the intake panel firmware to /dev/ttyACM0? [y/N]" in said
    assert "Write the intake panel firmware to /dev/ttyACM1? [y/N]" in said
    assert said.count("Nothing changed.") == 2
    assert services(bench) == ["stop", "start"]


def test_no_terminal_and_no_yes_stops_before_the_service_is_touched(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    assert cli.cmd_station_flash_panel(run=bench.run) == 2
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("Error: ") and "--yes" in err
    assert bench.calls == [] and bench.flashed == []


def test_yes_writes_the_one_blank_board_without_asking(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    bench.probe.hello = {"/dev/ttyACM1"}                # one blank board left
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True) == 0
    assert bench.flashed == [("/dev/ttyACM0", "10")] and "[y/N]" not in capsys.readouterr().out


def test_yes_with_several_blank_boards_stops_and_names_port(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True) == 2      # two blank boards: --yes does not pick
    out, err = capsys.readouterr()
    assert bench.flashed == [] and out == "" and "--port" in err and "/dev/ttyACM0" in err
    assert services(bench) == ["stop", "start"]


def test_yes_with_port_writes_that_board_only(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True, only_port="/dev/ttyACM1") == 0
    assert bench.flashed == [("/dev/ttyACM1", "10")] and "[y/N]" not in capsys.readouterr().out


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


def test_flash_with_wrong_version_afterwards_exits_1(bench, monkeypatch, capsys):
    bench.probe.version = "9"

    def flash(dev, version):
        bench.probe.hello.add(dev)
        return True
    monkeypatch.setattr(panel, "flash_panel", flash)
    assert cli.cmd_station_flash_panel(ask=lambda p: "y", run=bench.run) == 1
    assert "does not answer with firmware" in capsys.readouterr().err


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
    assert order[0] == ("is-active",) and order[1] == ("stop",) and order[2][0] == "probe"


def test_ctrl_c_at_the_prompt_flashes_nothing_and_restarts(bench, capsys):
    def ask(p):
        raise KeyboardInterrupt
    assert cli.cmd_station_flash_panel(ask=ask, run=bench.run) == 1
    assert "Nothing was flashed." in capsys.readouterr().out
    assert bench.flashed == [] and services(bench) == ["stop", "start"]


def test_service_that_was_active_is_started_again(bench):
    assert cli.cmd_station_flash_panel(ask=lambda p: "n", run=bench.run) == 5
    assert [c[1] for c in bench.calls] == ["is-active", "stop", "start"]


def test_service_that_was_inactive_is_not_started(bench):
    def run(cmd, **kw):
        bench.calls.append(cmd)
        return type("R", (), {"returncode": 3 if cmd[1] == "is-active" else 0})()
    assert cli.cmd_station_flash_panel(ask=lambda p: "n", run=run) == 5
    assert [c[1] for c in bench.calls] == ["is-active", "stop"]


@pytest.mark.parametrize("port", ["/dev/ttyUSB0", "/dev/ttyACM0", "/etc/passwd"])
def test_port_the_scan_would_not_offer_writes_nothing_and_exits_2(bench, monkeypatch, capsys, port):
    """ttyUSB (the PN532), a board that answers HELLO (a running panel), a path that is no board."""
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    bench.probe.hello = {"/dev/ttyACM0"}
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True, only_port=port) == 2
    err = " ".join(capsys.readouterr().err.split())
    assert bench.flashed == [] and err.startswith("Error: " + port) and "Fix: use one of: /dev/ttyACM1." in err
    assert services(bench) == ["stop", "start"]


def test_port_with_no_blank_board_says_none_were_found(bench, monkeypatch, capsys):
    bench.probe.hello = {"/dev/ttyACM0", "/dev/ttyACM1"}
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True, only_port="/dev/ttyACM0") == 2
    assert "no such board was found" in " ".join(capsys.readouterr().err.split()) and bench.flashed == []


def test_port_with_an_empty_name_writes_nothing_and_exits_2(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True, only_port="") == 2
    err = " ".join(capsys.readouterr().err.split())
    assert bench.flashed == [] and err.startswith("Error: --port needs") and "/dev/ttyACM0" in err


def test_port_written_another_way_is_the_board_the_scan_found(bench):
    """`..` and links resolve to the scanned name, and that name is the one written."""
    assert cli.cmd_station_flash_panel(run=bench.run, yes=True, only_port="/dev/ttyUSB0/../ttyACM1") == 0
    assert bench.flashed == [("/dev/ttyACM1", "10")]


def test_port_check_matches_a_link_to_the_board(monkeypatch):
    real = {"/dev/serial/by-id/usb-x": "/dev/ttyACM0", "/dev/link": "/dev/ttyACM0"}
    monkeypatch.setattr(cli.os.path, "realpath", lambda p: real.get(p, p))
    boards = [("/dev/ttyACM0", "/dev/serial/by-id/usb-x")]
    assert cli._port_check("/dev/serial/by-id/usb-x", boards, "x") == "/dev/ttyACM0"
    assert cli._port_check("/dev/link", [("/dev/ttyACM0",)], "x") == "/dev/ttyACM0"   # only the link resolves to it
    assert cli._port_check("/dev/ttyACM9", boards, "x") is None


def test_an_explicit_port_still_asks_at_a_terminal(bench, capsys):
    asked = []
    assert cli.cmd_station_flash_panel(ask=lambda p: asked.append(p) or "n", run=bench.run,
                                       only_port="/dev/ttyACM1") == 5
    assert len(asked) == 1 and bench.flashed == []


def test_an_explicit_port_piped_without_yes_exits_2_and_writes_nothing(bench, monkeypatch, capsys):
    monkeypatch.setattr(cli.output, "terminal", lambda: False)
    assert cli.cmd_station_flash_panel(run=bench.run, only_port="/dev/ttyACM1") == 2
    assert bench.flashed == [] and "--yes" in capsys.readouterr().err
