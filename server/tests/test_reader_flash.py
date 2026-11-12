"""`filament-kit reader setup` over the server's USB (reader_flash.py): the kit's own image, then the settings over the
serial port, then the reader's report of its first start. A fake board speaks the firmware's line protocol
(reader/lib/reader_core/src/settings.h)."""
from __future__ import annotations

import argparse
import json
import subprocess

import pytest

from filament_kit import cli, reader_flash as rf, reader_setup as rs, reader_tokens

BASE = "https://kit.example.net/filament/reader"
BUILD = 1794000000


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Board:
    """What the firmware does: answers FK? (once it runs our build), takes FK-SET, restarts and reports its start."""

    def __init__(self, clock, build=None, wifi="ok", server="ok", refuse=None):
        self.clock, self.build, self.wifi, self.server, self.refuse = clock, build, wifi, server, refuse
        self.settings = None
        self.lines = []

    def port(self, name):
        board = self

        class Port:
            def __init__(self):
                self.out = []

            def write(self, data):
                board.lines.append(data.decode())
                cmd = data.decode().strip()
                if board.build is None:
                    return                      # a blank board, or another firmware: no answer
                if cmd == "FK?":
                    done = board.settings is not None
                    self.out.append(f"FK-READER {board.build} configured={int(done)} "
                                    f"wifi={board.wifi if done else '-'} server={board.server if done else '-'}\n")
                elif cmd.startswith("FK-SET "):
                    if board.refuse:
                        self.out.append(f"FK-ERR {board.refuse}\n")
                    else:
                        board.settings = json.loads(cmd[7:])
                        self.out.append("FK-OK\n")

            def readline(self):
                board.clock.t += 0.1
                return self.out.pop(0).encode() if self.out else b""

            def close(self):
                pass
        return Port()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    image = tmp_path / "opt" / "resources" / "reader"
    image.mkdir(parents=True)
    (image / rf.IMAGE).write_bytes(b"\xe9fake image")
    (image / "VERSION").write_text(f"{BUILD}\n")
    return tmp_path


def _device(board, clock):
    return rf.Device("/dev/ttyACM0", opener=board.port, clock=clock, sleep=clock.sleep)


def _flasher(board, ok=True):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if ok:
            board.build = BUILD
        return subprocess.CompletedProcess(cmd, 0 if ok else 2, "", "")
    return run, calls


SETTINGS = {"ssid": "Home", "pass": "pw", "base": BASE, "token": "t" * 43, "buzzer_low": False}


def test_parse_hello():
    h = rf.parse_hello("FK-READER 1794000000 configured=1 wifi=ok server=unauth\r\n")
    assert (h.build, h.configured, h.wifi, h.server) == (BUILD, True, "ok", "unauth")
    assert rf.parse_hello("garbage") is None and rf.parse_hello("FK-READER x") is None


def test_the_bundled_image_is_found_installed(env):
    path, build = rf.bundled_image()
    assert path.name == rf.IMAGE and build == BUILD


def test_a_blank_board_is_flashed_then_set_up(env):
    clock = Clock()
    board = Board(clock)
    run, calls = _flasher(board)
    r = rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(board, clock), run=run, say=lambda *a: None)
    assert r.ok and r.flashed and "joined 'Home'" in r.message
    assert calls and calls[0][-2:] == ["0x0", str(env / "opt" / "resources" / "reader" / rf.IMAGE)]
    assert "write-flash" in calls[0] and "esp32c3" in calls[0]
    assert board.settings == SETTINGS


def test_a_board_on_this_build_only_gets_its_settings(env):
    clock = Clock()
    board = Board(clock, build=BUILD)
    run, calls = _flasher(board)
    said = []
    r = rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(board, clock), run=run, say=said.append)
    assert r.ok and not r.flashed and calls == [] and "settings only" in said[0]


def test_an_older_build_is_flashed(env):
    clock = Clock()
    board = Board(clock, build=BUILD - 1)
    run, calls = _flasher(board)
    assert rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(board, clock), run=run, say=lambda *a: None).flashed


@pytest.mark.parametrize("wifi,server,words", [("fail", "-", "could not join the Wi-Fi network 'Home'"),
                                               ("ok", "unauth", "did not accept its token"),
                                               ("ok", "fail", "could not reach the kit")])
def test_a_failed_first_start_says_why_plainly(env, wifi, server, words):
    clock = Clock()
    board = Board(clock, build=BUILD, wifi=wifi, server=server)
    r = rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(board, clock), run=_flasher(board)[0],
                 say=lambda *a: None)
    assert not r.ok and words in r.message


def test_refused_settings_and_a_failed_flash(env):
    clock = Clock()
    board = Board(clock, build=BUILD, refuse="ssid must be 1 to 32 bytes")
    r = rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(board, clock), run=_flasher(board)[0],
                 say=lambda *a: None)
    assert not r.ok and "ssid must be 1 to 32 bytes" in r.message
    blank = Board(clock)
    r = rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(blank, clock), run=_flasher(blank, ok=False)[0],
                 say=lambda *a: None)
    assert not r.ok and "esptool" in r.message and blank.settings is None


def test_no_bundled_image_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "bundled_image", lambda: None)
    clock = Clock()
    board = Board(clock)
    run, calls = _flasher(board)
    r = rf.setup("/dev/ttyACM0", dict(SETTINGS), device=_device(board, clock), run=run, say=lambda *a: None)
    assert not r.ok and calls == [] and "no Printer Station firmware" in r.message


# ---------------------------------------------------------------- the command
def _args(**kw):
    base = dict(name=None, ssid=None, source=None, port=None, out=None, ota_pubkey=None, token_file=None, base=BASE,
                secrets=None, buzzer=None, reflash=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _answers(*items):
    it = iter(items)
    return lambda prompt="": next(it)


@pytest.fixture
def usb(env, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(rs, "find_readers", lambda: [rs.Reader("/dev/ttyACM0", None, "USB JTAG/serial debug unit")])
    got = {}

    def setup(port, settings, reflash=False, run=None):
        got.update(port=port, settings=settings, reflash=reflash)
        return got.get("result", rf.Result(True, "Done. The Printer Station joined 'Home' and reached the kit."))
    monkeypatch.setattr(rf, "setup", setup)
    return got


def _run():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 3, b"", b"")       # the station service is not running
    return run, calls


def test_the_command_asks_three_things_and_prints_no_secret(usb, capsys):
    run, _ = _run()
    rc = cli._reader_setup_usb(_args(), _answers("Home", "l"), _answers("wifi-pass", "wifi-pass"), run=run)
    assert rc == 0, capsys.readouterr().err
    s = usb["settings"]
    assert (s["ssid"], s["pass"], s["base"], s["buzzer_low"]) == ("Home", "wifi-pass", BASE, True)
    assert "ota_key" not in s and len(s["token"]) == 43 and usb["port"] == "/dev/ttyACM0"
    out = capsys.readouterr()
    assert "wifi-pass" not in out.out + out.err and s["token"] not in out.out + out.err
    assert "Done." in out.out and "Buzzer: low-triggered" in out.out
    assert [t["name"] for t in reader_tokens.TokenStore().list()] == ["printer-station"]


def test_an_empty_buzzer_answer_is_high_and_the_option_skips_the_question(usb):
    run, _ = _run()
    assert cli._reader_setup_usb(_args(), _answers("Home", ""), _answers("p", "p"), run=run) == 0
    assert usb["settings"]["buzzer_low"] is False
    assert cli._reader_setup_usb(_args(buzzer="low", ssid="Home"), _answers(), _answers("p", "p"), run=run) == 0
    assert usb["settings"]["buzzer_low"] is True


def test_a_failed_setup_removes_the_new_token(usb, capsys):
    usb["result"] = rf.Result(False, "the reader could not join the Wi-Fi network 'Home'")
    run, _ = _run()
    assert cli._reader_setup_usb(_args(ssid="Home", buzzer="high"), _answers(), _answers("p", "p"), run=run) == 1
    assert reader_tokens.TokenStore().list() == []
    assert "could not join" in capsys.readouterr().err


def test_two_boards_ask_which_and_none_says_plug_it_in(usb, monkeypatch, capsys):
    run, _ = _run()
    monkeypatch.setattr(rs, "find_readers", lambda: [rs.Reader("/dev/ttyACM0", None, "a"), rs.Reader("/dev/ttyACM1", None, "b")])
    assert cli._reader_setup_usb(_args(ssid="Home", buzzer="high"), _answers("2"), _answers("p", "p"), run=run) == 0
    assert usb["port"] == "/dev/ttyACM1"
    monkeypatch.setattr(rs, "find_readers", lambda: [])
    assert cli._reader_setup_usb(_args(), _answers(), _answers(), run=run) == 1
    assert "no ESP32 board" in capsys.readouterr().err


def test_the_station_service_is_stopped_and_started_again(usb):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")     # it runs
    assert cli._reader_setup_usb(_args(ssid="Home", buzzer="high"), _answers(), _answers("p", "p"), run=run) == 0
    assert ["systemctl", "stop", "filament-kit-station.service"] in calls
    assert calls[-1] == ["systemctl", "start", "filament-kit-station.service"]


def test_different_passwords_change_nothing(usb):
    run, _ = _run()
    assert cli._reader_setup_usb(_args(ssid="Home"), _answers(), _answers("a", "b"), run=run) == 1
    assert "settings" not in usb and reader_tokens.TokenStore().list() == []


def test_not_root_without_a_token_file_changes_nothing(usb, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli._reader_setup_usb(_args(), _answers(), _answers(), run=_run()[0]) == 1
    assert "run as root" in capsys.readouterr().err and "settings" not in usb
