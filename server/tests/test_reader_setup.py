"""`filament-kit reader setup` (reader_setup.py): a Printer Station set up with today's firmware, whose settings are
compiled in from secrets.h. Nothing secret is printed; a token nobody holds is removed."""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import cli, reader_setup as rs, reader_tokens

TOKEN = "A" * 20 + "b-c_d" + "9" * 18                          # the shape token_urlsafe(32) makes: 43 characters
KEY = "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEabc+/=\nxyz=\n-----END PUBLIC KEY-----\n"
BASE = "https://kit.example.net/filament/reader"


def test_c_strings_escape_everything_that_could_end_or_bend_the_literal():
    assert rs.c_string('a"b\\c?d') == '"a\\042b\\134c\\077d"'
    assert rs.c_string("é\n") == '"\\303\\251\\012"'
    assert rs.c_string("\x01" + "7") == '"\\0017"'                # three octal digits: the 7 stays a character


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_the_written_strings_compile_back_to_the_same_bytes(tmp_path):
    text = 'na"me\\ ?? é\t\x01' + "7" + "ü" * 3
    src = tmp_path / "t.c"
    src.write_text('#include <stdio.h>\nint main(void){fputs(' + rs.c_string(text) + ', stdout);return 0;}\n')
    subprocess.run(["cc", "-trigraphs", "-o", str(tmp_path / "t"), str(src)], check=True)
    assert subprocess.run([str(tmp_path / "t")], capture_output=True).stdout == text.encode()


def test_secrets_h_has_every_setting_and_checks_them():
    text = rs.secrets_h("Home", "pa\"ss", BASE, TOKEN, KEY)
    assert 'WIFI_SSID = "Home";' in text and 'WIFI_PASS = "pa\\042ss";' in text
    assert f'READER_BASE = "{BASE}";' in text and f'READER_TOKEN = "{TOKEN}";' in text
    assert f'OTA_PUBKEY = R"KEY({KEY})KEY";' in text
    for args, msg in [(("", "p", BASE, TOKEN, KEY), "Wi-Fi name"), (("x" * 33, "p", BASE, TOKEN, KEY), "Wi-Fi name"),
                      (("H", "p" * 64, BASE, TOKEN, KEY), "password"), (("H", "p", BASE, "short", KEY), "token")]:
        with pytest.raises(rs.SetupError, match=msg):
            rs.secrets_h(*args)


def test_the_update_key_must_be_a_pem_public_key():
    assert rs.pubkey(None) == (rs.PLACEHOLDER_KEY, False)
    assert rs.pubkey(KEY.replace("\n", "\r\n")) == (KEY, True)
    for bad in ("hello", KEY + ")KEY\";", "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"):
        with pytest.raises(rs.SetupError):
            rs.pubkey(bad)


def test_reader_base_is_the_public_https_address():
    assert rs.reader_base({"web": {"public_url": "https://kit.example.net/filament/"}}) == BASE
    for cfg in ({}, {"web": {"public_url": "http://kit.local/filament"}}):
        with pytest.raises(rs.SetupError, match="https"):
            rs.reader_base(cfg)


def _usb(sysfs, name, vid, tty, product="USB JTAG/serial debug unit"):
    d = sysfs / name
    (d / f"{name}:1.0" / "tty" / tty).mkdir(parents=True)
    (d / "idVendor").write_text(vid + "\n")
    (d / "product").write_text(product + "\n")


@pytest.mark.skipif(sys.platform == "win32", reason="sysfs names like 1-1:1.0 are not Windows folder names")
def test_only_espressif_boards_with_a_tty_are_found(tmp_path):
    sysfs = tmp_path / "sys"
    _usb(sysfs, "1-1", "303a", "ttyACM0")
    _usb(sysfs, "1-2", "10c4", "ttyUSB0", "CP2102")              # someone else's serial adapter
    (sysfs / "1-3").mkdir()                                      # a hub without idVendor read
    found = rs.find_readers(sysfs, tmp_path / "no-by-id")
    assert [(r.port, r.product) for r in found] == [("/dev/ttyACM0", "USB JTAG/serial debug unit")]
    assert rs.find_readers(tmp_path / "nothing", tmp_path / "no-by-id") == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes and links")
def test_secrets_are_written_0600_and_never_through_a_link(tmp_path):
    p = tmp_path / "secrets.h"
    rs.write_private(p, "x")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and p.read_text() == "x"
    target = tmp_path / "elsewhere"
    target.write_text("keep")
    (tmp_path / "secrets.h.tmp").symlink_to(target)               # a planted temporary name is replaced, not followed
    rs.write_private(p, "y")
    assert target.read_text() == "keep" and p.read_text() == "y"


def _source(tmp_path) -> Path:
    src = tmp_path / "checkout" / "reader"
    (src / "src").mkdir(parents=True, exist_ok=True)
    (src / "platformio.ini").write_text("[env:esp32-c3-supermini]\n")
    (src / "src" / "main.cpp").write_text("int main(){}\n")
    (src / ".pio").mkdir(exist_ok=True)                                        # an old build is not copied
    return src


def test_flash_builds_a_private_copy_and_deletes_it(tmp_path):
    src = _source(tmp_path)
    seen = {}

    def run(cmd):
        tree = Path(cmd[cmd.index("-d") + 1])
        seen.update(cmd=cmd, secrets=(tree / "src" / "secrets.h").read_text(), tree=tree,
                    pio_copied=(tree / ".pio").exists(),
                    mode=stat.S_IMODE((tree / "src" / "secrets.h").stat().st_mode))
        return subprocess.CompletedProcess(cmd, 0)

    assert rs.flash(src, "SECRET", "/dev/ttyACM0", "/usr/bin/pio", run=run) == 0
    assert seen["cmd"][-6:] == ["-e", "esp32-c3-supermini", "-t", "upload", "--upload-port", "/dev/ttyACM0"]
    assert seen["secrets"] == "SECRET" and not seen["pio_copied"]
    if sys.platform != "win32":
        assert seen["mode"] == 0o600
    assert not seen["tree"].exists() and not (src / "src" / "secrets.h").exists()
    with pytest.raises(rs.SetupError, match="source folder"):
        rs.flash(tmp_path, "S", "/dev/ttyACM0", "/usr/bin/pio", run=run)


# ---------- the command ----------

def _args(**kw) -> argparse.Namespace:
    base = dict(name="bench", ssid="Home", source=None, port=None, out=None, ota_pubkey=None, token_file=None,
                base=BASE, secrets=None, buzzer="high")
    base.update(kw)
    return argparse.Namespace(**base)


def _secret(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_setup_writes_the_file_with_a_new_token_and_prints_no_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.delenv("SUDO_UID", raising=False)
    out = tmp_path / "secrets.h"
    assert cli.cmd_reader_setup(_args(out=str(out)), ask_secret=_secret("wifi-pass", "wifi-pass")) == 0
    text = out.read_text()
    tid, = [t["id"] for t in reader_tokens.TokenStore().list()]
    tok = text.split('READER_TOKEN = "')[1].split('"')[0]
    assert len(tok) == 43 and 'WIFI_PASS = "wifi-pass"' in text and f'READER_BASE = "{BASE}"' in text
    printed = capsys.readouterr()
    assert tok not in printed.out + printed.err and "wifi-pass" not in printed.out + printed.err
    assert f"reader revoke {tid}" in printed.out and "refuses every update" in printed.out


def test_a_token_file_needs_no_root_and_makes_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    (tmp_path / "tok").write_text(TOKEN + "\n")
    (tmp_path / "key.pem").write_text(KEY)
    out = tmp_path / "secrets.h"
    assert cli.cmd_reader_setup(_args(out=str(out), token_file=str(tmp_path / "tok"), ota_pubkey=str(tmp_path / "key.pem")),
                                ask_secret=_secret("p", "p")) == 0
    assert TOKEN in out.read_text() and KEY in out.read_text() and reader_tokens.TokenStore().list() == []


def test_without_root_or_a_token_file_nothing_happens(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.cmd_reader_setup(_args(out=str(tmp_path / "s.h")), ask_secret=_secret("p", "p")) == 1
    assert "run as root" in capsys.readouterr().err and not (tmp_path / "s.h").exists()


def test_two_different_passwords_change_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    assert cli.cmd_reader_setup(_args(out=str(tmp_path / "s.h")), ask_secret=_secret("one", "two")) == 1
    assert not (tmp_path / "s.h").exists() and reader_tokens.TokenStore().list() == []


def test_a_bad_wifi_name_is_refused_before_a_token_is_made(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    assert cli.cmd_reader_setup(_args(out=str(tmp_path / "s.h"), ssid="x" * 40), ask_secret=_secret("p", "p")) == 1
    assert reader_tokens.TokenStore().list() == []


def test_nothing_to_do_is_an_error(capsys):
    assert cli.cmd_reader_setup(_args()) == 1
    assert "--source" in capsys.readouterr().err


def _flash_env(monkeypatch, tmp_path, rc, readers=1):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(rs, "find_pio", lambda who=None: "/usr/bin/pio")
    monkeypatch.setattr(rs, "owner", lambda: None)
    monkeypatch.setattr(cli, "_answers_as_panel", lambda port: False)
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")                 # no systemctl here; the stop/start has its own test
    monkeypatch.setattr(rs, "find_readers", lambda: [rs.Reader(f"/dev/ttyACM{i}", None, "JTAG") for i in range(readers)])
    calls = []

    def flash(source, text, port, pio, who=None):
        calls.append((port, text))
        return rc
    monkeypatch.setattr(rs, "flash", flash)
    return calls


def test_a_failed_flash_removes_the_token_nobody_holds(tmp_path, monkeypatch, capsys):
    calls = _flash_env(monkeypatch, tmp_path, rc=1)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask=lambda p: "y",
                                ask_secret=_secret("p", "p")) == 1
    assert calls and calls[0][0] == "/dev/ttyACM0"
    assert reader_tokens.TokenStore().list() == [] and "token was removed" in capsys.readouterr().err


def test_a_good_flash_keeps_the_token(tmp_path, monkeypatch, capsys):
    _flash_env(monkeypatch, tmp_path, rc=0)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask=lambda p: "y",
                                ask_secret=_secret("p", "p")) == 0
    assert len(reader_tokens.TokenStore().list()) == 1 and "Flashed. The reader joins Home" in capsys.readouterr().out


def test_two_boards_need_a_port_and_none_says_check_the_cable(tmp_path, monkeypatch, capsys):
    _flash_env(monkeypatch, tmp_path, rc=0, readers=2)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p")) == 1
    assert "--port" in capsys.readouterr().err
    _flash_env(monkeypatch, tmp_path, rc=0, readers=0)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p")) == 1
    assert "data cable" in capsys.readouterr().err and reader_tokens.TokenStore().list() == []


def test_without_platformio_it_says_how_to_add_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rs, "find_pio", lambda who=None: None)
    monkeypatch.setattr(rs, "owner", lambda: rs.Owner("someone", 1000, 1000, Path("/home/someone")))
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path)))) == 1
    err = capsys.readouterr().err
    assert "pip install --user platformio" in err and "someone's account" in err and "not with sudo" in err


def test_main_routes_reader_setup(monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "cmd_reader_setup", lambda a: got.update(vars(a)) or 0)
    assert cli.main(["reader", "setup", "--out", "s.h", "--ssid", "Home", "--ota-pubkey", "k.pem"]) == 0
    assert got["out"] == "s.h" and got["ssid"] == "Home" and got["ota_pubkey"] == "k.pem" and got["source"] is None


# ---------- under sudo: the owner's PlatformIO, run as the owner (R66) ----------

posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX users")


def _me(home):
    import pwd
    pw = pwd.getpwuid(os.getuid())
    return pw.pw_name, rs.Owner(pw.pw_name, pw.pw_uid, pw.pw_gid, home)


@posix
def test_the_owner_is_the_user_behind_sudo(tmp_path):
    name, me = _me(tmp_path)
    got = rs.owner({"SUDO_USER": name, "SUDO_UID": str(me.uid)})
    assert got is not None and (got.name, got.uid, got.gid) == (me.name, me.uid, me.gid)
    assert rs.owner({}) is None and rs.owner({"SUDO_USER": "root", "SUDO_UID": "0"}) is None
    assert rs.owner({"SUDO_USER": name, "SUDO_UID": str(me.uid + 1)}) is None           # a name and uid that disagree
    assert rs.owner({"SUDO_USER": "no-such-user-fk", "SUDO_UID": "4242"}) is None


@posix
@pytest.mark.parametrize("where", [".local/bin", ".platformio/penv/bin"])
def test_pio_is_found_in_the_owners_home_not_roots(tmp_path, where, monkeypatch):
    _, me = _me(tmp_path / "home")
    f = me.home / where / "pio"
    f.parent.mkdir(parents=True)
    f.write_text("#!/bin/sh\n")
    f.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))          # sudo's PATH has neither folder
    assert rs.find_pio(me) == str(f)
    f.chmod(0o644)                                                # not executable: not taken
    assert rs.find_pio(rs.Owner(me.name, me.uid, me.gid, tmp_path / "nobody")) in (None, "/usr/local/bin/pio",
                                                                                     "/usr/bin/pio", "/usr/local/bin/platformio", "/usr/bin/platformio")


@posix
def test_flash_as_the_owner_runs_pio_as_them_with_their_home_and_groups(tmp_path):
    src = _source(tmp_path)
    _, me = _me(tmp_path / "home")
    seen = {}

    def run(cmd, **kw):
        tree = Path(cmd[cmd.index("-d") + 1])
        st = (tree / "src" / "secrets.h").stat()
        seen.update(kw=kw, owner=(st.st_uid, st.st_gid), mode=stat.S_IMODE(st.st_mode),
                    work_mode=stat.S_IMODE(tree.parent.stat().st_mode), tree=tree)
        return subprocess.CompletedProcess(cmd, 0)

    assert rs.flash(src, "SECRET", "/dev/ttyACM0", "/home/x/.local/bin/pio", run=run, who=me) == 0
    kw = seen["kw"]
    assert (kw["user"], kw["group"]) == (me.uid, me.gid) and me.gid in kw["extra_groups"]
    assert kw["env"]["HOME"] == str(me.home) and kw["env"]["USER"] == me.name
    assert kw["env"]["PATH"].split(os.pathsep)[:2] == [str(me.home / ".platformio/penv/bin"), str(me.home / ".local/bin")]
    assert "SECRET" not in repr(kw["env"])
    assert seen["owner"] == (me.uid, me.gid) and seen["mode"] == 0o600 and seen["work_mode"] == 0o700
    assert not seen["tree"].exists()


@posix
def test_out_never_replaces_a_path_that_is_not_the_callers_file(tmp_path):
    mine = tmp_path / "mine.h"
    mine.write_text("old")
    assert rs.out_ok(tmp_path / "new.h", os.getuid()) and rs.out_ok(mine, os.getuid())
    assert not rs.out_ok(mine, os.getuid() + 1)                   # someone else's file (as root: /etc/hosts)
    assert not rs.out_ok(tmp_path, os.getuid())                   # a folder
    (tmp_path / "link.h").symlink_to(mine)
    assert not rs.out_ok(tmp_path / "link.h", os.getuid())        # a link, even to a file of mine


@posix
def test_setup_refuses_an_out_path_it_must_not_replace(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(rs, "owner", lambda: rs.Owner("someone", os.getuid() + 1, os.getgid(), tmp_path))
    victim = tmp_path / "hosts"
    victim.write_text("127.0.0.1 localhost\n")
    assert cli.cmd_reader_setup(_args(out=str(victim)), ask_secret=_secret("p", "p")) == 1
    assert victim.read_text() == "127.0.0.1 localhost\n" and reader_tokens.TokenStore().list() == []
    assert "not a file of yours" in capsys.readouterr().err


# ---------- the buzzer's trigger (reader/src/main.cpp: no line in secrets.h = the older low-triggered module) ----------

def test_secrets_h_says_the_buzzer_trigger():
    assert "#define READER_BUZZER_ACTIVE_LOW 0\n" in rs.secrets_h("Home", "p", BASE, TOKEN, KEY)
    assert "#define READER_BUZZER_ACTIVE_LOW 1\n" in rs.secrets_h("Home", "p", BASE, TOKEN, KEY, buzzer_active_low=True)


@pytest.mark.parametrize("buzzer,line,said", [("high", "0", "high-triggered"), ("low", "1", "low-triggered")])
def test_setup_writes_the_buzzer_choice_and_says_it(tmp_path, monkeypatch, capsys, buzzer, line, said):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.delenv("SUDO_UID", raising=False)
    out = tmp_path / "secrets.h"
    assert cli.cmd_reader_setup(_args(out=str(out), buzzer=buzzer), ask_secret=_secret("pw", "pw")) == 0
    assert f"#define READER_BUZZER_ACTIVE_LOW {line}\n" in out.read_text()
    assert f"Buzzer: {said}" in capsys.readouterr().out


def test_the_buzzer_option_defaults_to_high(monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "cmd_reader_setup", lambda a: got.update(vars(a)) or 0)
    assert cli.main(["reader", "setup", "--out", "s.h"]) == 0 and got["buzzer"] == "high"
    assert cli.main(["reader", "setup", "--out", "s.h", "--buzzer", "low"]) == 0 and got["buzzer"] == "low"


def _refused(monkeypatch, tmp_path, capsys, **kw):
    calls = _flash_env(monkeypatch, tmp_path, rc=0)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p"), **kw) == 1
    assert calls == [] and reader_tokens.TokenStore().list() == []
    return capsys.readouterr()


def test_a_lone_board_is_not_flashed_unless_the_owner_says_yes(tmp_path, monkeypatch, capsys):
    for answer in ("", "n", "no"):
        out = _refused(monkeypatch, tmp_path, capsys, ask=lambda p, a=answer: a)
        assert "Nothing was flashed" in out.out


def test_a_lone_board_with_no_terminal_is_not_flashed(tmp_path, monkeypatch, capsys):
    def no_tty(prompt):
        raise EOFError
    assert "--port" in _refused(monkeypatch, tmp_path, capsys, ask=no_tty).err


def test_a_lone_board_that_answers_as_the_panel_is_never_asked_about(tmp_path, monkeypatch, capsys):
    calls = _flash_env(monkeypatch, tmp_path, rc=0)
    monkeypatch.setattr(cli, "_answers_as_panel", lambda port: True)
    def boom(prompt):
        raise AssertionError("asked")
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask=boom, ask_secret=_secret("p", "p")) == 1
    assert calls == [] and "button panel" in capsys.readouterr().err


def test_an_explicit_port_is_flashed_without_asking(tmp_path, monkeypatch):
    calls = _flash_env(monkeypatch, tmp_path, rc=0)
    def boom(prompt):
        raise AssertionError("asked")
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path)), port="/dev/ttyACM9"), ask=boom,
                                ask_secret=_secret("p", "p")) == 0
    assert calls[0][0] == "/dev/ttyACM9"


class _FakeSerial:
    """pyserial stand-in for the real HELLO probe: `line` is what the board says on open, b"" is silence."""
    line = b""
    fail = False
    made: list = []

    def __init__(self):
        self.closed = False
        self._lines = []
        _FakeSerial.made.append(self)

    def open(self):
        if _FakeSerial.fail:
            raise OSError("busy")
        if _FakeSerial.line:
            self._lines.append(_FakeSerial.line + b"\r\n")

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def write(self, data):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fake_serial(monkeypatch):
    import types
    from filament_kit.station import panel
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=_FakeSerial))
    clock = iter(x * 0.5 for x in range(10000))              # the 3 s wait for a HELLO passes without waiting
    monkeypatch.setattr(panel, "time", types.SimpleNamespace(time=lambda: next(clock)))
    _FakeSerial.line, _FakeSerial.fail, _FakeSerial.made = b"", False, []
    return _FakeSerial


def test_the_real_probe_sees_a_panel_hello_and_closes_the_port(fake_serial):
    fake_serial.line = b"HELLO intake-panel 9 esp32c3"
    assert cli._answers_as_panel("/dev/ttyACM0") is True
    assert fake_serial.made[0].closed


def test_the_real_probe_says_no_to_silence_and_to_an_open_error(fake_serial):
    assert cli._answers_as_panel("/dev/ttyACM0") is False
    fake_serial.fail = True
    assert cli._answers_as_panel("/dev/ttyACM0") is False


def test_the_real_probe_says_no_without_pyserial(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", None)         # import serial raises ImportError
    assert cli._answers_as_panel("/dev/ttyACM0") is False


def test_ctrl_c_at_the_prompt_flashes_nothing(tmp_path, monkeypatch, capsys):
    def interrupt(prompt):
        raise KeyboardInterrupt
    assert "Nothing was flashed" in _refused(monkeypatch, tmp_path, capsys, ask=interrupt).out


def test_the_station_is_stopped_around_the_probe_and_the_flash_and_restarted_after(tmp_path, monkeypatch):
    log = []
    def run(cmd, check=False, timeout=None):
        log.append(cmd[1])
        return subprocess.CompletedProcess(cmd, 0)
    real = cli._station_stopped
    monkeypatch.setattr(cli, "_station_stopped", lambda: real(run))
    _flash_env(monkeypatch, tmp_path, rc=0)                  # makes _is_root true
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setattr(cli, "_answers_as_panel", lambda port: log.append("probe") or False)
    monkeypatch.setattr(rs, "flash", lambda *a, **k: log.append("flash") or 0)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask=lambda p: "y",
                                ask_secret=_secret("p", "p")) == 0
    assert log == ["is-active", "stop", "probe", "start", "is-active", "stop", "flash", "start"]


def test_the_station_is_started_again_when_the_block_fails(monkeypatch):
    log = []
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    def run(cmd, check=False, timeout=None):
        log.append(cmd[1])
        return subprocess.CompletedProcess(cmd, 0)
    with pytest.raises(KeyboardInterrupt):
        with cli._station_stopped(run):
            raise KeyboardInterrupt
    assert log == ["is-active", "stop", "start"]


def _systemctl(monkeypatch, stop_rc=0, active_rc=0, stop_exc=None, active_exc=None):
    """A root run with systemd, and a fake systemctl: returns the log of its verbs."""
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    log = []
    def run(cmd, check=False, timeout=None):
        assert timeout, "every systemctl call needs a timeout"
        log.append(cmd[1])
        exc = {"stop": stop_exc, "is-active": active_exc}.get(cmd[1])
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, {"stop": stop_rc, "is-active": active_rc}.get(cmd[1], 0))
    return run, log


@pytest.mark.parametrize("kw", [dict(stop_rc=1), dict(stop_exc=OSError("denied")),
                                dict(stop_exc=subprocess.TimeoutExpired("systemctl", 60)),
                                dict(active_exc=subprocess.TimeoutExpired("systemctl", 15))])
def test_a_station_that_cannot_be_stopped_refuses_the_block(monkeypatch, kw):
    run, log = _systemctl(monkeypatch, **kw)
    ran = []
    with pytest.raises(cli._StationBusy, match="Nothing was flashed"):
        with cli._station_stopped(run):
            ran.append(1)
    assert ran == [] and "start" not in log[:2]


def test_a_failed_stop_restarts_what_was_running(monkeypatch):
    run, log = _systemctl(monkeypatch, stop_rc=1)
    with pytest.raises(cli._StationBusy):
        with cli._station_stopped(run):
            pass
    assert log == ["is-active", "stop", "start"]


def test_a_service_that_is_not_loaded_is_fine_and_missing_systemctl_is_skipped(monkeypatch):
    run, log = _systemctl(monkeypatch, stop_rc=5, active_rc=3)
    with cli._station_stopped(run):
        log.append("body")
    assert log == ["is-active", "stop", "body"]
    run, log = _systemctl(monkeypatch, active_exc=FileNotFoundError("systemctl"))
    with cli._station_stopped(run):
        log.append("body")
    assert log == ["is-active", "body"]


def test_without_root_it_says_the_service_is_not_stopped(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    def run(*a, **k):
        raise AssertionError("systemctl called")
    with cli._station_stopped(run):
        pass
    assert "not root" in capsys.readouterr().err


def test_a_start_that_fails_is_reported_not_raised(monkeypatch, capsys):
    run, log = _systemctl(monkeypatch)
    real = run
    def flaky(cmd, check=False, timeout=None):
        if cmd[1] == "start":
            raise subprocess.TimeoutExpired("systemctl", 60)
        return real(cmd, check, timeout)
    with cli._station_stopped(flaky):
        pass
    assert "could not start" in capsys.readouterr().err


def test_a_lone_board_is_not_probed_or_flashed_when_the_station_will_not_stop(tmp_path, monkeypatch, capsys):
    calls = _flash_env(monkeypatch, tmp_path, rc=0)
    run, log = _systemctl(monkeypatch, stop_rc=1)
    monkeypatch.setattr(cli, "_station_stopped", lambda real=cli._station_stopped: real(run))
    monkeypatch.setattr(cli, "_answers_as_panel", lambda port: log.append("probe"))
    def boom(prompt):
        raise AssertionError("asked")
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask=boom, ask_secret=_secret("p", "p")) == 1
    assert "probe" not in log and calls == [] and reader_tokens.TokenStore().list() == []
    assert "could not stop" in capsys.readouterr().err


def test_with_a_port_a_station_that_will_not_stop_leaves_no_token(tmp_path, monkeypatch, capsys):
    calls = _flash_env(monkeypatch, tmp_path, rc=0)
    run, log = _systemctl(monkeypatch, stop_exc=OSError("denied"))
    monkeypatch.setattr(cli, "_station_stopped", lambda real=cli._station_stopped: real(run))
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path)), port="/dev/ttyACM9"),
                                ask_secret=_secret("p", "p")) == 1
    err = capsys.readouterr().err
    assert calls == [] and reader_tokens.TokenStore().list() == []
    assert "could not stop" in err and "token was removed" in err
