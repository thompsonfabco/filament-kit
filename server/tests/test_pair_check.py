"""The nginx start check (acme-hooks.sh check): a certificate and key that do not match are repaired, never block."""
import datetime
import shutil
import subprocess
from pathlib import Path

import pytest

from filament_kit import remote

SCRIPT = Path(__file__).resolve().parents[2] / "install" / "remote" / "acme-hooks.sh"
SH = shutil.which("bash") or shutil.which("sh")
OPENSSL = shutil.which("openssl")
pytestmark = pytest.mark.skipif(not (SH and OPENSSL), reason="needs a shell and openssl")


def _pair(d: Path, cn: str, now=None):
    d.mkdir(parents=True, exist_ok=True)
    cert_pem, key_pem = remote.make_placeholder(cn, now)
    (d / "fullchain.pem").write_bytes(cert_pem)
    (d / "privkey.pem").write_bytes(key_pem)


def _check(root: Path):
    r = subprocess.run([SH, SCRIPT.as_posix(), "check"], env={"PATH": __import__("os").environ["PATH"], "FK_ROOT": root.as_posix()},
                       capture_output=True, text=True)
    assert r.returncode == 0
    return r.stdout


def _setup(tmp_path):
    tls = tmp_path / "etc/mcp-router/tls"
    _pair(tls, "a.example.org")
    (tmp_path / "etc/mcp-router/host").write_text("a.example.org\n")
    # now a stop between the two writes: the key is another one
    _pair(tmp_path / "other", "b.example.org")
    shutil.copy(tmp_path / "other/privkey.pem", tls / "privkey.pem")
    return tls


def _matches(tls):
    def pub(*a):
        return subprocess.run([OPENSSL, *a], capture_output=True, text=True).stdout
    return pub("x509", "-noout", "-pubkey", "-in", str(tls / "fullchain.pem")) == \
        pub("pkey", "-pubout", "-in", str(tls / "privkey.pem"))


def test_a_matching_pair_is_left_alone(tmp_path):
    tls = tmp_path / "etc/mcp-router/tls"
    _pair(tls, "a.example.org")
    before = (tls / "privkey.pem").read_bytes()
    assert _check(tmp_path) == ""
    assert (tls / "privkey.pem").read_bytes() == before


def test_a_mismatch_goes_back_to_the_previous_pair(tmp_path):
    tls = _setup(tmp_path)
    _pair(tls / "previous", "old.example.org")
    assert not _matches(tls)
    out = _check(tmp_path)
    assert "previous working pair" in out and _matches(tls)
    assert (tls / "privkey.pem").read_bytes() == (tls / "previous/privkey.pem").read_bytes()


def test_a_mismatch_without_a_previous_pair_is_fetched_again(tmp_path):
    tls = _setup(tmp_path)
    _pair(tmp_path / "etc/letsencrypt/live/a.example.org", "a.example.org")
    out = _check(tmp_path)
    assert "fresh copy" in out and _matches(tls)


def test_a_mismatch_with_nothing_to_fall_back_on_says_so_and_does_not_block(tmp_path):
    tls = _setup(tmp_path)
    assert "filament-kit apply" in _check(tmp_path)
    assert not _matches(tls)


def test_the_off_switch_leaves_a_mismatch_alone(tmp_path):
    tls = _setup(tmp_path)
    _pair(tls / "previous", "old.example.org")
    (tmp_path / "etc/mcp-router/no-pair-check").write_text("")
    assert _check(tmp_path) == "" and not _matches(tls)


LONG_AGO = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)   # a placeholder made then ended in 2022


def test_the_live_store_is_preferred_over_the_previous_pair(tmp_path):
    tls = _setup(tmp_path)
    _pair(tls / "previous", "old.example.org")
    _pair(tmp_path / "etc/letsencrypt/live/a.example.org", "a.example.org")
    live = (tmp_path / "etc/letsencrypt/live/a.example.org/privkey.pem").read_bytes()
    out = _check(tmp_path)
    assert "fresh copy" in out and (tls / "privkey.pem").read_bytes() == live and _matches(tls)


def test_an_expired_previous_pair_is_not_put_back(tmp_path):
    tls = _setup(tmp_path)
    _pair(tls / "previous", "old.example.org", LONG_AGO)
    assert "filament-kit apply" in _check(tmp_path)
    assert not _matches(tls)


def test_an_expired_previous_pair_loses_to_a_valid_live_store(tmp_path):
    tls = _setup(tmp_path)
    _pair(tls / "previous", "old.example.org", LONG_AGO)
    _pair(tmp_path / "etc/letsencrypt/live/a.example.org", "a.example.org")
    assert "fresh copy" in _check(tmp_path) and _matches(tls)


def test_an_expired_live_store_falls_back_to_a_valid_previous_pair(tmp_path):
    tls = _setup(tmp_path)
    _pair(tls / "previous", "old.example.org")
    _pair(tmp_path / "etc/letsencrypt/live/a.example.org", "a.example.org", LONG_AGO)
    assert "previous working pair" in _check(tmp_path) and _matches(tls)
