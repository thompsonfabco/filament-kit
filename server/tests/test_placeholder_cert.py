"""The home-only path's placeholder certificate: it lasts, a phone can accept it, a foreign certificate is never touched,
and `web status` warns before it ends. And an IPv6 client is told why it was refused. No real iPhone behind this."""
from __future__ import annotations

import datetime
import functools
import hashlib
import os
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from filament_kit import apply, cli, config, lan, modules, remote
from filament_kit.apply import Action

HOST = "fk.example.org"
INSTALL = Path(__file__).resolve().parents[2] / "install"
NOW = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(" ".join(str(c) for c in cmd))

    def texts(self):
        return self.calls


@functools.lru_cache(maxsize=None)
def _key():
    """One RSA key for every certificate made here (generating one per test costs seconds)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def self_signed(host=HOST, days=30, start=NOW) -> bytes:
    key = _key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(start)
            .not_valid_after(start + datetime.timedelta(days=days)).sign(key, hashes.SHA256())
            .public_bytes(Encoding.PEM))


def signed_by_a_ca(days=90) -> bytes:
    key = _key()
    return (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Some CA")])).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(NOW)
            .not_valid_after(NOW + datetime.timedelta(days=days)).sign(key, hashes.SHA256())
            .public_bytes(Encoding.PEM))


def mark_of(pem: bytes) -> str:
    return hashlib.sha256(pem).hexdigest() + "\n"


def test_the_placeholder_is_what_an_iphone_asks_for():
    pem, key = remote.make_placeholder(HOST, NOW)
    c = x509.load_pem_x509_certificate(pem)
    assert c.not_valid_after_utc - NOW == datetime.timedelta(days=825)
    assert c.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value == x509.ExtendedKeyUsage(
        [ExtendedKeyUsageOID.SERVER_AUTH])
    assert c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
        x509.DNSName) == [HOST]
    assert c.signature_hash_algorithm.name == "sha256" and b"PRIVATE KEY" in key and b"PRIVATE KEY" not in pem


@pytest.mark.parametrize("left,due", [(400, False), (31, False), (30, True), (1, True), (-5, True)])
def test_our_placeholder_is_renewed_only_near_its_end(left, due):
    pem = self_signed(days=825, start=NOW - datetime.timedelta(days=825 - left))
    assert bool(remote.placeholder_due(pem, mark_of(pem), HOST, NOW)) is due


def test_no_certificate_means_make_one():
    assert remote.placeholder_due(None, None, HOST, NOW)


def test_the_old_30_day_placeholder_is_recognised_once():
    assert "30 days" in remote.placeholder_due(self_signed(days=30), None, HOST, NOW)


@pytest.mark.parametrize("pem", [signed_by_a_ca(10), signed_by_a_ca(1), self_signed(days=365),
                                 self_signed(host="other.example.org"), b"not a certificate"],
                         ids=["ca", "ca-almost-over", "hand-made-long", "hand-made-other-host", "junk"])
def test_a_certificate_without_our_mark_is_never_touched(pem):
    assert remote.placeholder_due(pem, None, HOST, NOW) is None
    assert remote.placeholder_due(pem, "0" * 64, HOST, NOW) is None


def test_certbot_replacing_ours_makes_the_mark_stale_and_the_new_one_foreign():
    old = self_signed(days=825)
    real = signed_by_a_ca(5)
    assert remote.placeholder_due(real, mark_of(old), HOST, NOW) is None


def test_a_changed_host_name_makes_ours_again():
    pem = self_signed(days=825)
    assert "host" in remote.placeholder_due(pem, mark_of(pem), "new.example.org", NOW)


def _install(root, run=None):
    run = run or Rec()
    apply.execute([Action("remote_install", HOST)], run=run, resources=INSTALL, root=root)
    return run


def _tls(root):
    return root / "etc/mcp-router/tls"


def test_a_first_install_makes_it_and_its_mark(tmp_path):
    run = _install(tmp_path)
    pem = (_tls(tmp_path) / "fullchain.pem").read_bytes()
    assert (_tls(tmp_path) / "placeholder.sha256").read_text() == mark_of(pem)
    assert b"PRIVATE KEY" in (_tls(tmp_path) / "privkey.pem").read_bytes()
    assert "systemctl reload nginx" not in run.texts() and "nginx -t" in run.texts()


def test_an_upgrade_replaces_the_old_placeholder_and_reloads_nginx(tmp_path, capsys):
    tls = _tls(tmp_path)
    tls.mkdir(parents=True)
    old = self_signed(days=30, start=datetime.datetime.now(datetime.timezone.utc))
    (tls / "fullchain.pem").write_bytes(old)
    run = _install(tmp_path)
    assert (tls / "fullchain.pem").read_bytes() != old
    assert "systemctl reload nginx" in run.texts()
    assert "asks you to accept this one too" in capsys.readouterr().out


def test_an_apply_leaves_a_good_placeholder_and_a_real_certificate_alone(tmp_path):
    _install(tmp_path)
    tls = _tls(tmp_path)
    first = (tls / "fullchain.pem").read_bytes()
    run = _install(tmp_path)
    assert (tls / "fullchain.pem").read_bytes() == first and "systemctl reload nginx" not in run.texts()
    real = signed_by_a_ca(5)
    (tls / "fullchain.pem").write_bytes(real)     # the acme hook's copy, leaving our stale mark
    run = _install(tmp_path)
    assert (tls / "fullchain.pem").read_bytes() == real and "systemctl reload nginx" not in run.texts()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_key_is_not_readable_by_others(tmp_path):
    _install(tmp_path)
    assert (_tls(tmp_path) / "privkey.pem").stat().st_mode & 0o077 == 0


def test_a_crash_while_it_changes_leaves_either_certificate_provably_ours():
    """The mark names both until the new certificate is in place."""
    old, new = self_signed(days=30), self_signed(days=825)
    both = mark_of(new) + mark_of(old)
    assert remote.placeholder_due(old, both, HOST, NOW)                         # the old one is still renewed
    assert remote.placeholder_due(new, both, HOST, NOW) is None                 # the new one is recognised
    pem = self_signed(days=825, start=NOW - datetime.timedelta(days=810))
    assert remote.placeholder_due(pem, mark_of(new) + mark_of(pem), HOST, NOW)  # and renewed in its turn


@pytest.mark.parametrize("step", [0, 1, 2])
def test_each_write_on_the_way_leaves_a_mark_that_holds_the_cert_on_disk(tmp_path, monkeypatch, step):
    tls = _tls(tmp_path)
    tls.mkdir(parents=True)
    old = self_signed(days=30, start=datetime.datetime.now(datetime.timezone.utc))
    (tls / "fullchain.pem").write_bytes(old)
    (tls / "privkey.pem").write_bytes(_key().private_bytes(
        Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    calls = []
    real = apply._Exec.write

    def write(self, dest, data, mode, owner=""):
        if "/tls/" in dest:
            if len(calls) == step + 1:
                raise KeyboardInterrupt
            calls.append(dest)
        return real(self, dest, data, mode, owner)
    monkeypatch.setattr(apply._Exec, "write", write)
    with pytest.raises(KeyboardInterrupt):
        _install(tmp_path)
    pem = (tls / "fullchain.pem").read_bytes()
    assert hashlib.sha256(pem).hexdigest() in (tls / "placeholder.sha256").read_text()
    # and what nginx would load together still matches: the certificate on disk belongs to the key on disk
    public = serialization.load_pem_private_key((tls / "privkey.pem").read_bytes(), None).public_key().public_numbers()
    assert x509.load_pem_x509_certificate(pem).public_key().public_numbers() == public


def test_a_mark_of_junk_bytes_is_just_not_ours(tmp_path):
    tls = _tls(tmp_path)
    tls.mkdir(parents=True)
    real = signed_by_a_ca(90)
    (tls / "fullchain.pem").write_bytes(real)
    (tls / "placeholder.sha256").write_bytes(bytes(range(256)))
    _install(tmp_path)
    assert (tls / "fullchain.pem").read_bytes() == real


@pytest.mark.parametrize("left,expect", [(31, None), (30, False), (1, False), (-1, True)])
def test_the_warning_starts_30_days_out(left, expect):
    info = {"self_signed": True, "not_after": NOW + datetime.timedelta(days=left)}
    w = remote.certificate_warning(info, NOW)
    assert (w[0] if w else None) is expect
    if w:
        assert "modules apply" in w[2] and "accept it again" in w[2] and "yours to replace" in w[2]


@pytest.mark.parametrize("left,warned", [(30, False), (15, False), (14, True), (1, True)])
def test_a_real_certificate_is_news_only_well_after_certbots_renewal(left, warned):
    info = {"self_signed": False, "not_after": NOW + datetime.timedelta(days=left)}
    assert bool(remote.certificate_warning(info, NOW)) is warned


def test_a_real_certificate_near_its_end_points_at_certbot_and_nothing_answering_says_nothing():
    w = remote.certificate_warning({"self_signed": False, "not_after": NOW + datetime.timedelta(days=3)}, NOW)
    assert w[0] is False and "certbot" in w[2]
    assert remote.certificate_warning(None, NOW) is None


@pytest.fixture
def web_on(monkeypatch):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    c = config.load()
    c["modules"] = {n: n in {"server", "web", "remote"} for n in modules.MODULES}
    c["web"] = {**c["web"], "public_url": f"https://{HOST}/filament"}
    config.save(c)
    monkeypatch.setattr(cli, "_web_health", lambda port: (True, "ok"))


def test_web_status_warns_and_a_warning_is_not_a_failure(web_on, monkeypatch, capsys):
    soon = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)
    monkeypatch.setattr(remote, "served_certificate", lambda: {"self_signed": True, "not_after": soon})
    assert cli.main(["web", "status"]) == 0
    out = capsys.readouterr().out
    assert "self-signed certificate ends on" in out and "modules apply" in out


def test_web_status_fails_on_an_expired_one(web_on, monkeypatch, capsys):
    gone = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    monkeypatch.setattr(remote, "served_certificate", lambda: {"self_signed": True, "not_after": gone})
    assert cli.main(["web", "status"]) == 1
    assert "FAIL the web address's self-signed certificate ended on" in capsys.readouterr().out


def test_web_status_says_nothing_with_the_remote_module_off(web_on, monkeypatch, capsys):
    c = config.load()
    c["modules"]["remote"] = False
    config.save(c)
    monkeypatch.setattr(remote, "served_certificate", lambda: pytest.fail("looked"))
    cli.main(["web", "status"])
    assert "certificate" not in capsys.readouterr().out


# ---------- IPv6 ----------

@pytest.mark.parametrize("host,yes", [("2001:db8::5", True), ("fd12::1", True), ("fe80::1", True), ("192.0.2.5", False),
                                      ("::ffff:192.0.2.5", False), ("junk", False), ("", False)])
def test_over_ipv6(host, yes):
    assert lan.over_ipv6(host) is yes


def test_the_hint_names_a_section_the_guide_has():
    """Held to merge with the docs branch that adds the section."""
    guide = (Path(__file__).resolve().parents[2] / "docs" / "user-guide.md").read_text(encoding="utf-8")
    assert any(ln.lstrip("#").strip().startswith(lan.IPV6_HELP) for ln in guide.splitlines() if ln.startswith("#"))
    assert lan.IPV6_HELP in lan.IPV6_HINT


def test_the_hint_never_holds_the_clients_address():
    assert "2001" not in lan.IPV6_HINT and "IPv6" in lan.IPV6_HINT and "web.lan" in lan.IPV6_HINT


def test_only_a_refused_ipv6_client_sees_it():
    pytest.importorskip("mcp")
    from filament_kit.web import auth
    assert lan.IPV6_HINT in auth._home_only("2001:db8::5")
    assert lan.IPV6_HINT not in auth._home_only("203.0.113.9") and "home network" in auth._home_only("203.0.113.9")

