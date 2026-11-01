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


def _qr(p):
    return urllib.parse.parse_qs(urllib.parse.urlparse(p.qr).query)


def test_qr_is_urlencoded(monkeypatch):
    monkeypatch.setattr(pairing.socket, "gethostname", lambda: "a b&c")
    monkeypatch.setattr(pairing, "local_ips", lambda: [])
    q = pairing.issue().qr
    assert "a b" not in q and "h=a+b%26c.local" in q


def test_qr_host_is_hostname_not_display_name(monkeypatch):
    cfg = config.load()
    cfg["server_name"] = "Pat's Küche"
    config.save(cfg)
    monkeypatch.setattr(pairing.socket, "gethostname", lambda: "fkbox")
    q = _qr(pairing.issue())
    assert q["h"] == ["fkbox.local"] and q["p"] == ["8710"]


def test_qr_uses_short_hostname(monkeypatch):
    monkeypatch.setattr(pairing.socket, "gethostname", lambda: "fkbox.lan.example")
    assert _qr(pairing.issue())["h"] == ["fkbox.local"]


def test_qr_has_ip_params_without_link_local(monkeypatch):
    monkeypatch.setattr(pairing, "_candidate_ips",
                        lambda: ["127.0.0.1", "169.254.3.4", "192.168.1.9", "fe80::1", "10.0.0.2", "192.168.1.9"])
    q = _qr(pairing.issue())
    assert q["ip"] == ["192.168.1.9", "10.0.0.2"]


def test_local_ips_filters_loopback_link_local_and_junk(monkeypatch):
    monkeypatch.setattr(pairing, "_candidate_ips",
                        lambda: ["127.0.1.1", "169.254.0.9", "fe80::2", "not-an-ip", "172.16.0.4"])
    assert pairing.local_ips() == ["172.16.0.4"]


def test_cert_skips_link_local_and_loopback_ips(tmp_path):
    pairing.make_cert("h3", ["169.254.1.1", "192.168.1.5", "127.0.0.1"], tmp_path / "c")
    san = x509.load_pem_x509_certificate((tmp_path / "c" / "cert.pem").read_bytes()).extensions         .get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("192.168.1.5")]


def test_last_seen_not_rewritten_every_check():
    p = pairing.issue()
    pairing.check(p.token)
    f = config.paths().state / "devices.json"
    before = f.read_text()
    pairing.check(p.token)
    assert f.read_text() == before


def test_revoke_races_check(monkeypatch):
    monkeypatch.setattr(pairing, "LAST_SEEN_STALE", -1)  # every check rewrites devices.json
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
    for f in config.paths().state.glob("*.json"):  # pairing.lock (POSIX) is empty and not JSON
        json.loads(f.read_text())


def _mp_worker(n: int) -> None:
    for i in range(n):
        keep, drop = pairing.issue("keep"), pairing.issue("drop")
        pairing.check(keep.token)
        pairing.revoke(pairing.check(drop.token))


@pytest.mark.skipif(os.name == "nt", reason="cross-process flock is POSIX only")
def test_two_processes_do_not_lose_updates():
    import multiprocessing
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_mp_worker, args=(15,)) for _ in range(3)]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(60)
        assert pr.exitcode == 0
    devs = pairing.devices()
    assert len(devs) == 45 and {d["name"] for d in devs} == {"keep"}


# ---------- final review: root-run CLI must leave files the service user can read ----------

def test_root_state_write_gives_file_to_state_dir_owner(tmp_path, monkeypatch):
    import os as _os
    monkeypatch.setenv("FK_STATE", str(tmp_path / "st"))
    (tmp_path / "st").mkdir()
    st = _os.stat(tmp_path / "st")
    calls = []
    monkeypatch.setattr(_os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(_os, "chown", lambda p, u, g: calls.append((_os.fspath(p), u, g)), raising=False)
    pairing._write("devices.json", [])
    assert any(_os.path.basename(c[0]).startswith("devices.json.") and c[1:] == (st.st_uid, st.st_gid)
               for c in calls), calls
    if _os.name != "nt":
        calls.clear()
        pairing.devices()
        assert any(_os.path.basename(c[0]) == "pairing.lock" for c in calls), calls
