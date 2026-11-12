import io
import json
import os
import sys

import pytest

from filament_kit import cli, config, modules, pairing


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
    cfg["server_name"] = "Kit's Küche"
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


# ---------- printers menu ----------

def _printers_session(monkeypatch, lines, code="ACCESS1234"):
    monkeypatch.setattr(sys, "stdin", io.StringIO(lines))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": code)
    return cli.main(["config"])


def test_printers_add_rename_remove(capsys, monkeypatch):
    from filament_kit.bridge import registry
    assert _printers_session(monkeypatch, "5\n2\nOffice\n10.0.0.5\nSER1\n\n0\n0\n") == 0
    p = registry.load()["SER1"]
    assert (p.name, p.ip, p.access_code, p.configured) == ("Office", "10.0.0.5", "ACCESS1234", True)
    out = capsys.readouterr().out
    assert "ACCESS1234" not in out

    assert _printers_session(monkeypatch, "5\n3\n1\nShed\n0\n0\n") == 0
    assert registry.load()["SER1"].name == "Shed"
    assert registry.load()["SER1"].access_code == "ACCESS1234"

    assert _printers_session(monkeypatch, "5\n4\n1\n0\n0\n") == 0
    assert registry.load() == {}
    assert "ACCESS1234" not in capsys.readouterr().out


def test_printers_list_shows_detected_without_code(capsys, monkeypatch):
    from filament_kit.bridge import registry
    registry.detected("DET1", "10.0.0.9", "C11", "Found one")
    registry.upsert(registry.Printer("CFG1", "Mine", "O1D", "10.0.0.2", "SECRETCODE", True))
    assert _printers_session(monkeypatch, "5\n1\n0\n0\n") == 0
    out = capsys.readouterr().out
    assert "Found one" in out and "Mine" in out and "SECRETCODE" not in out
    assert "not set up" in out


def test_printers_add_rejects_blank_fields(capsys, monkeypatch):
    from filament_kit.bridge import registry
    assert _printers_session(monkeypatch, "5\n2\n\n10.0.0.5\n\n0\n0\n") == 0
    assert registry.load() == {}


def test_config_menu_lists_printers_entry(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("0\n"))
    cli.main(["config"])
    assert "5) Printers" in capsys.readouterr().out


def test_printers_bad_number_says_no_such_printer(capsys, monkeypatch):
    from filament_kit.bridge import registry
    registry.upsert(registry.Printer("S1", "A", configured=True))
    assert _printers_session(monkeypatch, "5\n4\n0\n4\n-1\n4\n9\n4\nx\n0\n0\n") == 0
    assert capsys.readouterr().out.count("No such printer.") == 4
    assert "S1" in registry.load()


def test_printers_corrupt_file_reports_error_and_keeps_it(capsys, monkeypatch, env):
    f = env / "state" / "printers.json"
    f.write_text("garbage")
    assert _printers_session(monkeypatch, "5\n2\nA\n1.2.3.4\nS1\n0\n0\n") == 0
    assert "unreadable" in capsys.readouterr().out
    assert f.read_text() == "garbage"


# ---------- final review ----------

def test_printers_add_rejects_bad_serial(capsys, monkeypatch):
    from filament_kit.bridge import registry
    assert _printers_session(monkeypatch, "5\n2\nOffice\n10.0.0.5\nbad serial!\n0\n0\n") == 0
    assert registry.load() == {}
    assert "serial" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("code", ["1234-5678", "x" * 33, "côde12"])
def test_printers_add_rejects_bad_access_code(capsys, monkeypatch, code):
    from filament_kit.bridge import registry
    assert _printers_session(monkeypatch, "5\n2\nOffice\n10.0.0.5\nSER1\n\n0\n0\n", code=code) == 0
    assert registry.load() == {}
    out = capsys.readouterr().out
    assert "Access Code" in out and code not in out


def test_printers_add_records_the_model_for_the_camera(capsys, monkeypatch):
    # A printer added by hand never announces itself, so its model (which picks the camera kind) is asked for.
    from filament_kit.bridge import models, registry
    assert _printers_session(monkeypatch, "5\n2\nWorkshop\n10.0.0.6\nSER2\nH2D\n0\n0\n") == 0
    p = registry.load()["SER2"]
    assert p.model == "H2D" and models.camera_kind(p.model) == "hls"


def test_pair_prints_grouped_certificate_fingerprint(capsys):
    _cert()
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    assert cli.main(["pair"]) == 0
    out = capsys.readouterr().out
    grouped = " ".join(fp[i:i + 4] for i in range(0, len(fp), 4))
    assert "Certificate fingerprint (the phone asks for two groups of it):" in out
    assert grouped in out and len(grouped.split(" ")) == 16


# ---------- Task 7b: profiles, pair --pc, status lines ----------

import time  # noqa: E402

from filament_kit import library as library_mod  # noqa: E402
from filament_kit.profiles import builds, lines as lines_mod  # noqa: E402


def _spoolman_cfg(url):
    cfg = config.load()
    cfg["spoolman_url"] = url
    config.save(cfg)


def test_profiles_build_waiting_exits_0_with_message(capsys, spoolman_url):
    _spoolman_cfg(spoolman_url)
    assert cli.main(["profiles", "build"]) == 0
    out = capsys.readouterr()
    assert "install and pair the PC sync" in out.out
    assert "see README: Pair your PC" in out.out
    assert "FAIL" not in out.out and out.err == ""


def test_profiles_build_ok_prints_stamp(capsys, monkeypatch, spoolman_url):
    _spoolman_cfg(spoolman_url)
    seen = {}

    def run_build(sm):
        seen["sm"] = sm
        return {"stamp": "20261102-080100", "ok": True, "error": None, "problems": ["a: no parent"]}

    monkeypatch.setattr(builds, "run_build", run_build)
    monkeypatch.setattr(builds, "current", lambda: {"stamp": "20261102-080100", "presets": 12, "problems": 1})
    assert cli.main(["profiles", "build"]) == 0
    out = capsys.readouterr().out
    assert "build 20261102-080100" in out and "12 presets" in out
    assert "problem: a: no parent" in out
    assert seen["sm"] is not None


def test_profiles_build_failed_exits_1(capsys, monkeypatch, spoolman_url):
    _spoolman_cfg(spoolman_url)
    monkeypatch.setattr(builds, "run_build", lambda sm: {"stamp": None, "ok": False, "error": "ValueError: boom",
                                                        "problems": []})
    assert cli.main(["profiles", "build"]) == 1
    assert "ValueError: boom" in capsys.readouterr().err


def test_pair_pc_prints_link_not_qr(capsys, monkeypatch):
    _cert()

    def no_qr(name):
        raise AssertionError("pair --pc must not make a QR code")

    monkeypatch.setattr(cli.shutil, "which", no_qr)
    assert cli.main(["pair", "--pc"]) == 0
    out = capsys.readouterr().out
    rows = out.splitlines()
    i = rows.index("Link for filament-kit-sync (paste it when asked):")
    assert rows[i + 1].startswith("fkit://pair?")
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    assert " ".join(fp[j:j + 4] for j in range(0, len(fp), 4)) in out
    pend = json.loads((config.paths().state / "pending.json").read_text())
    assert f"Pairing code: {pend[0]['code']}" in out
    pairing.redeem_code(pend[0]["code"])
    assert [d["name"] for d in pairing.devices()] == ["pc"]


def test_pair_qr_has_four_module_quiet_zone(capsys, monkeypatch):
    _cert()
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return cli.subprocess.CompletedProcess(args, 0, stdout="QR\n", stderr="")

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/qrencode")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.main(["pair"]) == 0
    args = seen["args"]
    assert args[:3] == ["qrencode", "-t", "ansiutf8"]
    assert args[args.index("-m") + 1] == "4"
    assert args[-1].startswith("fkit://pair?")
    assert "QR" in capsys.readouterr().out


def _ok_client(key):
    class Models:
        def list(self):
            return []

    class Client:
        models = Models()
    return Client()


def _status_setup(spoolman_url):
    _spoolman_cfg(spoolman_url)
    _cert()
    (config.paths().etc / "anthropic_key").write_text("sk-ant-secret", encoding="utf-8")


def _status_lines(capsys) -> list:
    return capsys.readouterr().out.splitlines()


def test_status_fresh_install_profiles_lines_no_fail(capsys, spoolman_url, no_library):
    _status_setup(spoolman_url)
    assert cli.main(["status"], client_factory=_ok_client) == 0
    out = _status_lines(capsys)
    assert not any(ln.startswith("FAIL") for ln in out)
    assert "--   library not downloaded (filament-kit library update), 0 local additions" in out
    assert "--   profiles: no build yet (waiting for the PC sync)" in out
    assert "--   PC sync: not set up (see README: Pair your PC)" in out


def test_status_after_waiting_build_no_fail(capsys, spoolman_url):
    _status_setup(spoolman_url)
    assert cli.main(["profiles", "build"]) == 0
    capsys.readouterr()
    assert cli.main(["status"], client_factory=_ok_client) == 0
    out = _status_lines(capsys)
    assert not any(ln.startswith("FAIL") for ln in out)
    assert "--   profiles: no build yet (waiting for the PC sync)" in out


def _fake_profiles(monkeypatch, **st):
    base = {"lines": 3, "presets": 0, "build": None, "last_attempt": None, "installed": None, "pc": None,
            "stale": [], "problems": []}
    base.update(st)
    monkeypatch.setattr(builds, "status", lambda: base)


def _fake_library(monkeypatch, source="bundled", local=2, last_check=None, at=None):
    monkeypatch.setattr(library_mod, "status", lambda: {"version": 7, "source": source, "local": local,
                                                        "url": "x", "last_check": last_check})
    monkeypatch.setattr(library_mod, "_pointer", lambda name: {"dir": "7-x", "version": 7, "at": at}
                        if name == "current.json" and at else None)


def test_status_good_build_and_pc_sync(capsys, monkeypatch, spoolman_url):
    _status_setup(spoolman_url)
    up = time.mktime((2026, 11, 2, 8, 1, 0, 0, 0, -1))
    _fake_profiles(monkeypatch, presets=12,
                   build={"stamp": "20261102-080100", "live_hash": "h", "created": up, "presets": 12, "problems": 2},
                   last_attempt={"at": up, "ok": True, "error": None},
                   installed={"stamp": "20261102-080100", "at": up}, pc={"device_id": "d1", "last_upload": up})
    _fake_library(monkeypatch, source="updated", at=up)
    assert cli.main(["status"], client_factory=_ok_client) == 0
    out = _status_lines(capsys)
    assert "--   library version 7 (updated 2026-11-02), 2 local additions" in out
    assert "OK   profiles: build 20261102-080100, 12 presets for 3 lines (2 problems)" in out
    assert "--   PC sync: last upload 2026-11-02 08:01, installed build 20261102-080100" in out


def test_status_failed_build_and_library_update_warning(capsys, monkeypatch, spoolman_url):
    _status_setup(spoolman_url)
    _fake_profiles(monkeypatch, presets=12,
                   build={"stamp": "20261101-070000", "live_hash": "h", "created": 1.0, "presets": 12, "problems": 0},
                   last_attempt={"at": 2.0, "ok": False, "error": "ValueError: boom"},
                   pc={"device_id": "d1", "last_upload": None})
    _fake_library(monkeypatch, last_check={"at": 1.0, "ok": False, "error": "HTTP 404: using bundled version 7"})
    assert cli.main(["status"], client_factory=_ok_client) == 1
    out = _status_lines(capsys)
    assert "--   library update: HTTP 404: using bundled version 7" in out
    i = out.index("FAIL profiles: last build failed: ValueError: boom; using build 20261101-070000")
    assert out[i + 1] == "     fix: sudo journalctl -u filament-kit-build -n 50"
    assert "--   PC sync: last upload never, no build installed yet" in out


def test_profiles_lines_and_set_parent(capsys, monkeypatch):
    lib = library_mod.load()
    lines_mod.ensure_saved("ELEGOO", "PETG HF", "PETG", bambu_parent=None, library=lib, store=None)
    assert cli.main(["profiles", "lines"]) == 0
    out = capsys.readouterr().out
    assert "elegoo--petg-hf" in out and "Bambu PETG HF (library)" in out
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: asked.append(reason))
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "Generic PETG"]) == 0
    line = lines_mod.load()["elegoo--petg-hf"]
    assert (line.bambu_parent, line.parent_source) == ("Generic PETG", "user")
    assert asked
    assert cli.main(["profiles", "set-parent", "nope--x", "Generic PETG"]) == 1
    assert "no line nope--x" in capsys.readouterr().err
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "Generic PETG @BBL H2D"]) == 1
    assert "@" in capsys.readouterr().err
    assert lines_mod.load()["elegoo--petg-hf"].bambu_parent == "Generic PETG"


def test_profiles_set_parent_unknown_with_store(capsys, monkeypatch):
    import io as _io

    import test_builds as TB
    lib = library_mod.load()
    lines_mod.ensure_saved("ELEGOO", "PETG HF", "PETG", bambu_parent=None, library=lib, store=None)
    TB.pair("a")
    builds.store_upload("system", _io.BytesIO(TB.system_zip()), device_id="a")
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: None)
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "No Such Preset"]) == 1
    assert "not a usable" in capsys.readouterr().err
    assert lines_mod.load()["elegoo--petg-hf"].parent_source == "library"


def test_profiles_status_and_restore_deleted(capsys, monkeypatch):
    assert cli.main(["profiles", "status"]) == 0
    assert "no build yet" in capsys.readouterr().out
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: asked.append(reason))
    assert cli.main(["profiles", "restore-deleted"]) == 0
    assert (config.paths().state / "profiles" / "restore-deleted").exists() and asked


def test_import_guard_removed():
    import inspect
    assert "ImportError" not in inspect.getsource(cli._request_rebuild)


def test_profiles_lines_shows_orca_parent_and_set_parent_orca(capsys, monkeypatch):
    import io as _io

    import test_builds as TB
    lib = library_mod.load()
    lines_mod.ensure_saved("ELEGOO", "PETG HF", "PETG", bambu_parent=None, library=lib, store=None)
    assert cli.main(["profiles", "lines"]) == 0
    assert "orca Generic PETG (material)" in capsys.readouterr().out
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: asked.append(reason))
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "Overture PLA Pro", "--orca"]) == 0
    assert "Orca parent Overture PLA Pro (set by you)" in capsys.readouterr().out
    line = lines_mod.load()["elegoo--petg-hf"]
    assert (line.orca_parent, line.orca_parent_source) == ("Overture PLA Pro", "user")
    assert line.parent_source == "library" and asked
    assert cli.main(["profiles", "lines"]) == 0
    assert "orca Overture PLA Pro (user)" in capsys.readouterr().out
    # with an Orca store uploaded the name is checked against its library index
    TB.pair("a")
    builds.store_upload("orca_system", _io.BytesIO(TB.orca_system_zip()), device_id="a")
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "No Such", "--orca"]) == 1
    assert "not an Orca Slicer library preset" in capsys.readouterr().err
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "Generic PETG @System", "--orca"]) == 1
    assert "@" in capsys.readouterr().err
    assert lines_mod.load()["elegoo--petg-hf"].orca_parent == "Overture PLA Pro"



def test_profiles_set_parent_orca_canonical_spelling(capsys, monkeypatch):
    import io as _io

    import test_builds as TB
    lines_mod.ensure_saved("ELEGOO", "PETG HF", "PETG", bambu_parent=None, library=library_mod.load(), store=None)
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: None)
    TB.pair("a")
    builds.store_upload("orca_system", _io.BytesIO(TB.orca_system_zip()), device_id="a")
    assert cli.main(["profiles", "set-parent", "elegoo--petg-hf", "generic petg", "--orca"]) == 0
    assert "Orca parent Generic PETG (set by you)" in capsys.readouterr().out
    assert lines_mod.load()["elegoo--petg-hf"].orca_parent == "Generic PETG"


def test_profiles_help_mentions_orca(capsys):
    with pytest.raises(SystemExit):
        cli.main(["profiles", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Bambu Studio and Orca Slicer presets" in out
    assert "or with --orca the Orca Slicer library preset" in out


# ---------- C-M7: a root-only file read as another user ----------

@pytest.mark.parametrize("argv", [["modules", "list"], ["remote", "firewall"]])
def test_unreadable_config_says_run_with_sudo(argv, monkeypatch, capsys):
    def denied(*a, **k):
        raise PermissionError(13, "Permission denied", "/etc/filament-kit/config.json")

    monkeypatch.setattr(config, "load", denied)
    assert cli.main(argv) == 1
    err = capsys.readouterr().err
    assert "/etc/filament-kit/config.json" in err and f"sudo filament-kit {argv[0]}" in err
    assert "Traceback" not in err


def test_key_saved_with_ai_intake_off_says_how_to_turn_it_on(monkeypatch, capsys):
    """R1: AI is optional; a key alone does not switch label reading on, so the menu says where to do that."""
    cfg = config.load()
    cfg["modules"] = {n: n in modules.MODES["server"] for n in modules.MODULES}
    config.save(cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO("4\n0\n"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-ant-TOPSECRET")
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "Key saved." in out and "ai_intake" in out and "6) Modules" in out


def test_pair_station_says_the_link_works_for_10_minutes(capsys):
    _cert()
    assert cli.main(["pair", "--station"]) == 0
    assert "works for 10 minutes" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [["--pc", "--station"], ["--pc", "--text"], ["--station", "--text"]])
def test_pair_kinds_are_mutually_exclusive(capsys, flags):
    _cert()
    with pytest.raises(SystemExit) as e:
        cli.main(["pair", *flags])
    assert e.value.code == 2 and "not allowed with" in capsys.readouterr().err
    assert not (config.paths().state / "pending.json").exists()


def test_config_menu_station_voice_piper_or_espeak(monkeypatch, capsys):
    """Final review M5: the menu switches the station's speech between Piper and espeak-ng (no download)."""
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: print("APPLIED") or 0)
    monkeypatch.setattr(sys, "stdin", io.StringIO("7\n2\n0\n"))
    assert cli.main(["config"]) == 0
    assert config.load()["station"]["tts"] == "espeak" and "APPLIED" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO("7\n1\n0\n"))
    assert cli.main(["config"]) == 0
    assert config.load()["station"]["tts"] == "auto" and "APPLIED" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO("7\n\n0\n"))  # a blank answer keeps it
    assert cli.main(["config"]) == 0
    assert config.load()["station"]["tts"] == "auto" and "APPLIED" not in capsys.readouterr().out


def test_status_shows_the_pc_sync_waiting_for_studio(capsys, monkeypatch, spoolman_url):
    """The PC sync's last heartbeat says it waits for Bambu Studio to close."""
    _status_setup(spoolman_url)
    since = time.mktime((2026, 11, 3, 10, 0, 0, 0, 0, -1))
    _fake_profiles(monkeypatch, pc={"device_id": "d1", "last_upload": since,
                                    "waiting": {"since": since, "app": "Bambu Studio", "at": since + 3600}})
    _fake_library(monkeypatch)
    assert cli.main(["status"], client_factory=_ok_client) == 0
    out = _status_lines(capsys)
    assert "--   PC sync waiting for Bambu Studio to close since 2026-11-03 10:00" in out
    assert cli.main(["profiles", "status"]) == 0
    assert "PC sync waiting for Bambu Studio to close since 2026-11-03 10:00" in capsys.readouterr().out


def test_status_without_a_wait_has_no_waiting_line(capsys, monkeypatch, spoolman_url):
    _status_setup(spoolman_url)
    _fake_profiles(monkeypatch, pc={"device_id": "d1", "last_upload": 1.0})
    _fake_library(monkeypatch)
    cli.main(["status"], client_factory=_ok_client)
    assert not any("waiting for Bambu Studio" in ln for ln in _status_lines(capsys))
