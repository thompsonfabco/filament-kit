"""`filament-kit reader setup` (reader_setup.py): a bench reader set up with today's firmware, whose settings are
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
                base=BASE, secrets=None)
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
    monkeypatch.setattr(rs, "find_pio", lambda: "/usr/bin/pio")
    monkeypatch.setattr(rs, "find_readers", lambda: [rs.Reader(f"/dev/ttyACM{i}", None, "JTAG") for i in range(readers)])
    calls = []

    def flash(source, text, port, pio):
        calls.append((port, text))
        return rc
    monkeypatch.setattr(rs, "flash", flash)
    return calls


def test_a_failed_flash_removes_the_token_nobody_holds(tmp_path, monkeypatch, capsys):
    calls = _flash_env(monkeypatch, tmp_path, rc=1)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p")) == 1
    assert calls and calls[0][0] == "/dev/ttyACM0"
    assert reader_tokens.TokenStore().list() == [] and "token was removed" in capsys.readouterr().err


def test_a_good_flash_keeps_the_token(tmp_path, monkeypatch, capsys):
    _flash_env(monkeypatch, tmp_path, rc=0)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p")) == 0
    assert len(reader_tokens.TokenStore().list()) == 1 and "Flashed. The reader joins Home" in capsys.readouterr().out


def test_two_boards_need_a_port_and_none_says_check_the_cable(tmp_path, monkeypatch, capsys):
    _flash_env(monkeypatch, tmp_path, rc=0, readers=2)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p")) == 1
    assert "--port" in capsys.readouterr().err
    _flash_env(monkeypatch, tmp_path, rc=0, readers=0)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path))), ask_secret=_secret("p", "p")) == 1
    assert "data cable" in capsys.readouterr().err and reader_tokens.TokenStore().list() == []


def test_without_platformio_it_says_how_to_add_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rs, "find_pio", lambda: None)
    assert cli.cmd_reader_setup(_args(source=str(_source(tmp_path)))) == 1
    assert "pip install --user platformio" in capsys.readouterr().err


def test_main_routes_reader_setup(monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "cmd_reader_setup", lambda a: got.update(vars(a)) or 0)
    assert cli.main(["reader", "setup", "--out", "s.h", "--ssid", "Home", "--ota-pubkey", "k.pem"]) == 0
    assert got["out"] == "s.h" and got["ssid"] == "Home" and got["ota_pubkey"] == "k.pem" and got["source"] is None
