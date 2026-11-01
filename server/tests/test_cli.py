import io
import json
import os
import sys

import pytest

from filament_kit import cli, config, pairing


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path


def _cert():
    config.paths().etc.mkdir(parents=True, exist_ok=True)
    return pairing.make_cert("fk-test", ["127.0.0.1"], config.paths().etc)


def test_status_reports_spoolman_down(capsys, monkeypatch):
    cfg = config.load()
    cfg["spoolman_url"] = "http://127.0.0.1:1"
    config.save(cfg)
    assert cli.main(["status"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "sudo systemctl start spoolman" in out


def test_status_all_ok(capsys, spoolman_url):
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    fp = _cert()
    (config.paths().etc / "anthropic_key").write_text("sk-ant-secret", encoding="utf-8")
    pairing.issue("x")

    class Models:
        def list(self):
            return []

    class Client:
        models = Models()

    seen = {}

    def factory(key):
        seen["key"] = key
        return Client()

    assert cli.main(["status"], client_factory=factory) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert fp in out
    assert "sk-ant-secret" not in out
    assert seen["key"] == "sk-ant-secret"
    assert "reads used today: 0" in out


def test_status_rejected_key(capsys, spoolman_url):
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    _cert()
    (config.paths().etc / "anthropic_key").write_text("sk-bad", encoding="utf-8")

    def factory(key):
        raise RuntimeError("401 invalid x-api-key")

    assert cli.main(["status"], client_factory=factory) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "sk-bad" not in out


def test_status_counts_reads_today(capsys, spoolman_url):
    import time
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    now = time.time()
    (config.paths().state / "reads.json").write_text(json.dumps([now - 10, now - 20, now - 90000]))
    cli.main(["status"])
    assert "reads used today: 2" in capsys.readouterr().out


def test_pair_prints_code(capsys):
    _cert()
    assert cli.main(["pair"]) == 0
    out = capsys.readouterr().out
    pend = json.loads((config.paths().state / "pending.json").read_text())
    assert pend[0]["code"] in out
    assert "fkit://pair?" in out or "█" in out or "▀" in out


def test_pair_without_cert_fails(capsys):
    assert cli.main(["pair"]) == 1
    assert "certificate" in capsys.readouterr().err


def test_unpair_lists_and_revokes(capsys):
    _cert()
    p = pairing.issue("pixel")
    pairing.redeem_code(p.code)
    dev = pairing.devices()[0]
    assert cli.main(["unpair"]) == 0
    assert dev["id"] in capsys.readouterr().out
    assert cli.main(["unpair", dev["id"]]) == 0
    assert pairing.devices() == []
    assert cli.main(["unpair", "nope"]) == 1


def test_config_menu_sets_box_count(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("2\n4\n12\n0\n0\n"))
    assert cli.main(["config"]) == 0
    assert config.load()["placement"]["box_count"] == 12


def test_config_menu_server_name_and_model(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("1\nmy-kit\n3\nclaude-x\n30\n0\n"))
    cli.main(["config"])
    cfg = config.load()
    assert cfg["server_name"] == "my-kit"
    assert cfg["model"] == "claude-x"
    assert cfg["reads_per_day"] == 30


def test_config_menu_storage_text_fields(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("2\n1\nA, B ,C\n2\nShelf\n3\nBox \n5\nSpill\n0\n0\n"))
    cli.main(["config"])
    cfg = config.load()
    assert cfg["locations"] == ["A", "B", "C"]
    assert cfg["placement"]["pla_location"] == "Shelf"
    assert cfg["placement"]["box_prefix"] == "Box "
    assert cfg["placement"]["overflow"] == "Spill"


def test_config_invalid_box_count_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("2\n4\nabc\n0\n0\n"))
    cli.main(["config"])
    assert config.load()["placement"]["box_count"] == 0
    assert "number" in capsys.readouterr().out


def test_key_never_printed(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("4\n0\n"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-ant-TOPSECRET")
    assert cli.main(["config"]) == 0
    cap = capsys.readouterr()
    assert "sk-ant-TOPSECRET" not in cap.out + cap.err
    keyfile = config.paths().etc / "anthropic_key"
    assert keyfile.read_text(encoding="utf-8").strip() == "sk-ant-TOPSECRET"
    if os.name != "nt":
        assert keyfile.stat().st_mode & 0o777 == 0o640


def test_cert_creates_once_and_never_regenerates(capsys):
    assert cli.main(["cert"]) == 0
    first = capsys.readouterr().out.strip()
    pem = (config.paths().etc / "cert.pem").read_bytes()
    assert first == pairing.fingerprint(pem)
    assert cli.main(["cert"]) == 0
    assert (config.paths().etc / "cert.pem").read_bytes() == pem
    assert capsys.readouterr().out.strip() == first


def test_cert_force_not_offered():
    with pytest.raises(SystemExit):
        cli.main(["cert", "--force"])


def test_ensure_fields(capsys, spoolman_url):
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    assert cli.main(["ensure-fields"]) == 0
    assert "nfc_id" in capsys.readouterr().out
    assert cli.main(["ensure-fields"]) == 0


def test_ensure_fields_unreachable(capsys):
    cfg = config.load()
    cfg["spoolman_url"] = "http://127.0.0.1:1"
    config.save(cfg)
    assert cli.main(["ensure-fields"]) == 1


def test_cert_uses_hostname_not_display_name(monkeypatch):
    from cryptography import x509
    cfg = config.load()
    cfg["server_name"] = "Pat's Küche"
    config.save(cfg)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "fkbox")
    monkeypatch.setattr(pairing, "_candidate_ips", lambda: ["169.254.7.7", "192.168.1.20", "127.0.0.1"])
    assert cli.main(["cert"]) == 0
    cert = x509.load_pem_x509_certificate((config.paths().etc / "cert.pem").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert cert.subject.rfc4514_string() == "CN=fkbox"
    assert set(san.get_values_for_type(x509.DNSName)) == {"fkbox", "fkbox.local", "localhost"}
    assert [str(a) for a in san.get_values_for_type(x509.IPAddress)] == ["192.168.1.20"]


class _Active:
    stdout = "active\n"


def _systemd_on(monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: _Active())


def test_status_api_not_answering_fails(capsys, monkeypatch):
    from conftest import free_port
    _systemd_on(monkeypatch)
    cfg = config.load()
    cfg["port"] = free_port()
    config.save(cfg)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert f"FAIL filament-kit API not answering at https://127.0.0.1:{cfg['port']}/api/info" in out
    assert "sudo journalctl -u filament-kit -n 50" in out


def test_status_api_answering_ok(capsys, monkeypatch):
    _systemd_on(monkeypatch)
    seen = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    real_urlopen = cli.urllib.request.urlopen

    def urlopen(url, timeout=None, context=None):
        if not isinstance(url, str):  # Spoolman's own requests
            return real_urlopen(url, timeout=timeout)
        seen.update(url=url, timeout=timeout, verify=context.verify_mode)
        return Resp()

    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "OK   filament-kit API answering at https://127.0.0.1:8710/api/info" in out
    import ssl
    assert seen == {"url": "https://127.0.0.1:8710/api/info", "timeout": 5, "verify": ssl.CERT_NONE}


def test_cert_short_hostname_keeps_full_name_as_san(monkeypatch):
    from cryptography import x509
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "fkbox.lan.example")
    monkeypatch.setattr(pairing, "_candidate_ips", lambda: [])
    assert cli.main(["cert"]) == 0
    cert = x509.load_pem_x509_certificate((config.paths().etc / "cert.pem").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert cert.subject.rfc4514_string() == "CN=fkbox"
    assert set(san.get_values_for_type(x509.DNSName)) == {"fkbox", "fkbox.local", "localhost", "fkbox.lan.example"}


def test_status_api_bad_http_answer_fails(capsys, monkeypatch):
    import http.client
    _systemd_on(monkeypatch)
    real_urlopen = cli.urllib.request.urlopen

    def urlopen(url, timeout=None, context=None):
        if not isinstance(url, str):
            return real_urlopen(url, timeout=timeout)
        raise http.client.BadStatusLine("garbage")

    monkeypatch.setattr(cli.urllib.request, "urlopen", urlopen)
    assert cli.main(["status"]) == 1
    out = capsys.readouterr().out
    assert "FAIL filament-kit API not answering" in out and "sudo journalctl -u filament-kit -n 50" in out


def test_status_api_check_skipped_without_systemd(capsys):
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "api/info" not in out and f"display name: {config.load()['server_name']}" in out
