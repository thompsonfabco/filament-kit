import hashlib
import ipaddress
import json
import os
import threading
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from filament_kit import config, pairing


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k in ("ETC", "STATE", "BACKUPS", "OPT"):
        monkeypatch.setenv(f"FK_{k}", str(tmp_path / k.lower()))
    (tmp_path / "state").mkdir()
    pairing.make_cert("fkhost", ["192.168.1.5"], config.paths().etc)
    return tmp_path


def test_cert_sans_include_host_local_and_ips():
    pem = (config.paths().etc / "cert.pem").read_bytes()
    san = x509.load_pem_x509_certificate(pem).extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value
    assert {"fkhost", "fkhost.local", "localhost"} <= set(san.get_values_for_type(x509.DNSName))
    assert ipaddress.ip_address("192.168.1.5") in san.get_values_for_type(x509.IPAddress)


def test_fingerprint_matches_pem(tmp_path):
    dest = tmp_path / "other"
    ret = pairing.make_cert("h2", [], dest)
    pem = (dest / "cert.pem").read_bytes()
    der = x509.load_pem_x509_certificate(pem).public_bytes(serialization.Encoding.DER)
    assert ret == pairing.fingerprint(pem) == hashlib.sha256(der).hexdigest()
    assert len(ret) == 64 and ret == ret.lower() and ":" not in ret
    pem = (config.paths().etc / "cert.pem").read_bytes()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(pairing.issue().qr).query)
    assert q["fp"] == [pairing.fingerprint(pem)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_key_mode_600():
    assert (config.paths().etc / "key.pem").stat().st_mode & 0o777 == 0o600


def test_issue_without_cert_raises():
    (config.paths().etc / "cert.pem").unlink()
    with pytest.raises(pairing.PairingError):
        pairing.issue()


def test_token_stored_hashed():
    p = pairing.issue("my phone")
    assert f"t={p.token}" in p.qr
    for f in config.paths().state.iterdir():
        assert p.token not in f.read_text()
    assert pairing.check(p.token) is not None
    assert pairing.check("nope") is None


def test_code_redeem_once():
    p = pairing.issue()
    tok = pairing.redeem_code(p.code)
    assert pairing.check(tok) is not None
    with pytest.raises(pairing.PairingError):
        pairing.redeem_code(p.code)


def test_code_five_wrong_attempts_locks():
    p = pairing.issue()
    wrong = "000000" if p.code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(pairing.PairingError):
            pairing.redeem_code(wrong)
    with pytest.raises(pairing.PairingError):
        pairing.redeem_code(p.code)


def test_four_wrong_then_right_succeeds():
    p = pairing.issue()
    wrong = "000000" if p.code != "000000" else "111111"
    for _ in range(4):
        with pytest.raises(pairing.PairingError):
            pairing.redeem_code(wrong)
    assert pairing.check(pairing.redeem_code(p.code)) is not None


def test_code_expires(monkeypatch):
    p = pairing.issue()
    monkeypatch.setattr(pairing.time, "time", lambda: p.expires + 1)
    with pytest.raises(pairing.PairingError):
        pairing.redeem_code(p.code)


def test_revoke():
    p = pairing.issue("a")
    dev = pairing.check(p.token)
    assert [d["id"] for d in pairing.devices()] == [dev]
    assert pairing.revoke(dev) is True
    assert pairing.check(p.token) is None
    assert pairing.revoke(dev) is False
    assert pairing.devices() == []


def test_qr_token_unclaimed_expires(monkeypatch):
    p = pairing.issue("a")
    monkeypatch.setattr(pairing.time, "time", lambda: p.expires + 1)
    assert pairing.check(p.token) is None
    assert pairing.devices() == []
    assert json.loads((config.paths().state / "devices.json").read_text()) == []


def test_qr_token_claimed_stays_valid(monkeypatch):
    p = pairing.issue("a")
    dev = pairing.check(p.token)
    assert dev is not None
    monkeypatch.setattr(pairing.time, "time", lambda: p.expires + 1)
    assert pairing.check(p.token) == dev
    assert [d["id"] for d in pairing.devices()] == [dev]


def test_qr_claim_kills_code():
    p = pairing.issue()
    assert pairing.check(p.token) is not None
    with pytest.raises(pairing.PairingError):
        pairing.redeem_code(p.code)
    assert pairing.check(p.token) is not None


def test_non_ascii_code_is_pairing_error():
    pairing.issue()
    for bad in ("٣٤٥٦٧٨", "12345é", "12", ""):
        with pytest.raises(pairing.PairingError):
            pairing.redeem_code(bad)


def test_devices_lists_only_claimed_with_paired():
    p = pairing.issue("a")
    assert pairing.devices() == []
    pairing.check(p.token)
    (d,) = pairing.devices()
    assert d["paired"] is not None
    q = pairing.issue("b")
    pairing.redeem_code(q.code)
    assert len(pairing.devices()) == 2
    assert all(x["paired"] is not None for x in pairing.devices())


def test_qr_is_urlencoded(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: {"server_name": "a b&c", "port": 8710})
    q = pairing.issue().qr
    assert "a b" not in q and "h=a+b%26c" in q


def test_last_seen_not_rewritten_every_check():
    p = pairing.issue()
    pairing.check(p.token)
    f = config.paths().state / "devices.json"
    before = f.read_text()
    pairing.check(p.token)
    assert f.read_text() == before


def test_revoke_races_check():
    p = pairing.issue()
    dev = pairing.check(p.token)
    stop = threading.Event()
    errors = []

    def spin():
        try:
            while not stop.is_set():
                pairing.check(p.token)
        except Exception as e:
            errors.append(e)

    ts = [threading.Thread(target=spin) for _ in range(4)]
    for t in ts:
        t.start()
    assert pairing.revoke(dev) is True
    stop.set()
    for t in ts:
        t.join()
    assert not errors
    assert pairing.check(p.token) is None
    for f in config.paths().state.iterdir():
        json.loads(f.read_text())
