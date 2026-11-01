import ipaddress

import pytest
from cryptography import x509

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


def test_fingerprint_matches_pem():
    pem = (config.paths().etc / "cert.pem").read_bytes()
    fp = pairing.fingerprint(pem)
    assert len(fp) == 64 and fp == fp.lower() and ":" not in fp
    assert f"fp={fp}" in pairing.issue().qr


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
    assert len(pairing.devices()) == 1
    monkeypatch.setattr(pairing.time, "time", lambda: p.expires + 1)
    assert pairing.check(p.token) is None
    assert pairing.devices() == []


def test_qr_token_claimed_stays_valid(monkeypatch):
    p = pairing.issue("a")
    dev = pairing.check(p.token)
    assert dev is not None
    monkeypatch.setattr(pairing.time, "time", lambda: p.expires + 1)
    assert pairing.check(p.token) == dev
    assert [d["id"] for d in pairing.devices()] == [dev]
