"""The station's client for the button flow (station/server_api.py): the pairing link, the pairing files, and the
three calls over pinned TLS against the real kit API."""
import json
import os
import sys
import threading
import time

import pytest
import uvicorn
from fakes.claude_fake import FakeClaude

from conftest import free_port
from filament_kit import cli, config, inventory, pairing
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman
from filament_kit.station import server_api

UID = "4:77:90:e:9:22:89"
FP = "ab" * 32
ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "OVERTURE", "name": "PETG Black",
        "material": "PETG", "color_hex": "111111", "net": 1000, "tare": 155, "density": 1.27, "count": 1,
        "nozzle": 240, "bed": 75, "nozzle_range": "230-250", "bed_range": "70-80", "lot": None, "note": "",
        "estimates": [], "sealed": False, "sealed_reason": "bare spool", "line": "PETG"}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})
    monkeypatch.setattr(inventory, "_record_lines", lambda items: None)
    monkeypatch.setattr(inventory, "_check_parents", lambda items: None)


def test_parse_link():
    link = server_api.parse_link(f"fkit://pair?h=srv.local&p=8710&t={'x' * 43}&fp={FP}&ip=192.0.2.5&ip=192.0.2.6")
    assert (link.host, link.port, link.fp, link.ips) == ("srv.local", 8710, FP, ["192.0.2.5", "192.0.2.6"])
    for bad in ("https://example.com", f"fkit://pair?h=a&p=0&t={'x' * 43}&fp={FP}",
                f"fkit://pair?h=a&p=1&t=short&fp={FP}", f"fkit://pair?h=a&p=1&t={'x' * 43}&fp=zz"):
        with pytest.raises(ValueError):
            server_api.parse_link(bad)


def test_save_pairing_writes_the_files(tmp_path):
    link = server_api.parse_link(f"fkit://pair?h=srv.local&p=8710&t={'y' * 43}&fp={FP}&ip=192.0.2.5")
    server_api.save_pairing(link, owner=None)
    cfg = json.loads(server_api.server_file().read_text())
    assert cfg == {"ips": ["192.0.2.5"], "port": 8710, "fp": FP, "host": "srv.local"}
    assert server_api.token_file().read_text().strip() == "y" * 43
    if sys.platform != "win32":
        assert (os.stat(server_api.token_file()).st_mode & 0o777) == 0o600
    api = server_api.ServerApi()
    assert api.paired and api.ips == ["192.0.2.5"]


def test_not_paired_answers_without_a_call():
    status, body = server_api.ServerApi().tag_lookup(UID)
    assert status == 0 and body["error"] == "not_paired" and body["display"][0] == "Not paired"


@pytest.fixture
def server(spoolman_url, tmp_path):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    port = free_port()
    etc = tmp_path / "etc"
    srv = uvicorn.Server(uvicorn.Config(create_app(sm=sm, claude=FakeClaude({"questions": [], "items": [ITEM]})),
                                        host="127.0.0.1", port=port, log_level="warning",
                                        ssl_certfile=str(etc / "cert.pem"), ssl_keyfile=str(etc / "key.pem")))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield port, sm
    srv.should_exit = True
    t.join(5)


def _pair(port) -> None:
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    tok = pairing.redeem_code(pairing.issue("station").code)
    server_api.save_pairing(server_api.Link("fkhost.local", port, tok, fp, ["127.0.0.1"]), owner=None)


def test_the_flow_over_pinned_tls(server):
    port, sm = server
    _pair(port)
    api = server_api.ServerApi(timeout=10)
    status, body = api.tag_lookup(UID)
    assert status == 200 and body["known"] is False
    status, body = api.recognize(b"\xff\xd8\xff\xe0" + b"x" * 100, UID)
    assert status == 200 and body["source"] == "claude", body
    status, body = api.save({"uid": UID, "gross_g": 900, "item": body["item"]})
    assert status == 200 and body["created"] and body["remaining_g"] == 745
    status, body = api.tag_lookup(UID)
    assert status == 200 and body["known"] is True


def test_a_changed_certificate_is_refused_before_sending(server):
    port, _ = server
    _pair(port)
    cfg = json.loads(server_api.server_file().read_text())
    server_api.server_file().write_text(json.dumps({**cfg, "fp": FP}))
    status, body = server_api.ServerApi(timeout=10).tag_lookup(UID)
    assert status == 0 and body["error"] == "cert_changed" and body["display"][0] == "Server changed"


def test_unreachable_server(server):
    port, _ = server
    _pair(port)
    cfg = json.loads(server_api.server_file().read_text())
    server_api.server_file().write_text(json.dumps({**cfg, "port": free_port()}))
    status, body = server_api.ServerApi(timeout=3).tag_lookup(UID)
    assert status == 0 and body["error"] == "unreachable" and body["display"] == server_api.UNREACHABLE


def test_station_pair_command(server, monkeypatch):
    port, _ = server
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(server_api, "save_pairing", lambda link, owner="x", first=None, _real=server_api.save_pairing:
                        _real(link, owner=None, first=first))
    pr = pairing.issue("station")
    # an address the station can't reach comes first (a container bridge): pairing skips it and remembers the good one
    link = pr.qr.split("&ip=")[0] + "&ip=127.0.0.2&ip=127.0.0.1"
    link = link.replace(f"p={config.load()['port']}", f"p={port}")
    answers = iter([link, "y"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 0
    api = server_api.ServerApi(timeout=10)
    assert api.paired and api.ips[0] == "127.0.0.1"
    assert api.tag_lookup(UID)[0] == 200
    answers = iter([link, "n"])
    assert cli.cmd_station_pair(ask=lambda prompt: next(answers)) == 1


def test_pairing_files_live_in_the_stations_own_folder(tmp_path):
    """Not /etc/filament-kit (root:filament-kit 2750, closed to the station's service user)."""
    link = server_api.parse_link(f"fkit://pair?h=srv.local&p=8710&t={'y' * 43}&fp={FP}&ip=192.0.2.5")
    server_api.save_pairing(link, owner=None)
    d = server_api.pairing_dir()
    assert d == config.paths().etc.parent / f"{config.paths().etc.name}-station"
    assert server_api.server_file().parent == d and server_api.token_file().parent == d
    assert not (config.paths().etc / "station_token").exists()
    if sys.platform != "win32":
        assert (os.stat(d).st_mode & 0o777) == 0o750


def test_uninstall_purge_removes_the_station_pairing_folder():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "install" / "uninstall.sh").read_text(encoding="utf-8")
    assert "rm -rf /etc/filament-kit /etc/filament-kit-station " in text


# ---------- the station's network allow-list follows the pairing (fix round 1, I1) ----------

def _paired(ips):
    link = server_api.parse_link(f"fkit://pair?h=kit.example.com&p=8710&t={'z' * 43}&fp={FP}"
                                 + "".join(f"&ip={i}" for i in ips))
    server_api.save_pairing(link, owner=None)


def _allow_line(text: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith("IPAddressAllow="))


def test_station_mode_dropin_allows_the_paired_servers_addresses():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "station")
    cfg["station"]["allow"] = ["192.0.2.10"]
    assert _allow_line(apply.station_dropin(cfg, ["192.0.2.10"])) == "IPAddressAllow=localhost 192.0.2.10"
    _paired(["192.0.2.10", "198.51.100.7"])
    text = apply.station_dropin(cfg, ["192.0.2.10"])
    assert _allow_line(text) == "IPAddressAllow=localhost 192.0.2.10 198.51.100.7"
    assert '"STATION_ALLOW=127.0.0.1 192.0.2.10"' in text  # the HTTP answers are not widened


def test_all_in_one_dropin_allows_the_paired_lan_address():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    _paired(["127.0.0.1", "192.0.2.5"])  # the server's LAN address from its link, loopback first
    assert _allow_line(apply.station_dropin(cfg, ["127.0.0.1"])) == "IPAddressAllow=localhost 127.0.0.1 192.0.2.5"


def test_a_broken_pairing_file_does_not_stop_the_dropin():
    from filament_kit import apply, modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    server_api.pairing_dir().mkdir(parents=True, exist_ok=True)
    server_api.server_file().write_text("{not json", encoding="utf-8")
    assert _allow_line(apply.station_dropin(cfg, ["127.0.0.1"])) == "IPAddressAllow=localhost 127.0.0.1"
    server_api.server_file().write_text(json.dumps({"ips": ["10.0.0.1; rm -rf /", "192.0.2.9"]}), encoding="utf-8")
    assert _allow_line(apply.station_dropin(cfg, ["127.0.0.1"])) == "IPAddressAllow=localhost 127.0.0.1 192.0.2.9"


def test_refresh_station_rewrites_the_dropin_and_restarts(tmp_path, monkeypatch):
    from filament_kit import apply, modules
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one")
    _paired(["127.0.0.1", "192.0.2.5"])
    ran = []
    apply.refresh_station(cfg, run=ran.append, root=tmp_path / "root")
    dropin = (tmp_path / "root" / apply.DROPIN.lstrip("/")).read_text(encoding="utf-8")
    assert "192.0.2.5" in _allow_line(dropin)
    assert ran == [["systemctl", "daemon-reload"], ["systemctl", "restart", apply.STATION_UNIT]]


def _pair_cli(monkeypatch, mode, link_ips, refresh):
    from filament_kit import modules
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    cfg = modules.set_mode({"placement": {"box_count": 2}}, mode, say=None)
    if mode == "station":
        cfg.setdefault("station", {})["allow"] = ["192.0.2.10"]
    config.save(cfg)
    probed = []
    monkeypatch.setattr(server_api, "peer_fingerprint", lambda ip, port, timeout=10: probed.append(ip) or FP)
    monkeypatch.setattr(server_api, "save_pairing", lambda link, owner="x", first=None, _real=server_api.save_pairing:
                        _real(link, owner=None, first=first))
    from filament_kit import apply
    monkeypatch.setattr(apply, "refresh_station", refresh)
    link = f"fkit://pair?h=kit.example.com&p=8710&t={'q' * 43}&fp={FP}" + "".join(f"&ip={i}" for i in link_ips)
    answers = iter([link, "y"])
    return cli.cmd_station_pair(ask=lambda prompt: next(answers)), probed


def test_station_pair_on_the_servers_machine_uses_loopback_first_and_refreshes(monkeypatch, capsys):
    refreshed = []
    code, probed = _pair_cli(monkeypatch, "all-in-one", ["192.0.2.5"], lambda cfg, **kw: refreshed.append(cfg))
    assert code == 0 and probed == ["127.0.0.1"]
    assert server_api.ServerApi().ips == ["127.0.0.1", "192.0.2.5"]
    assert len(refreshed) == 1 and "restarted" in capsys.readouterr().out


def test_station_pair_says_the_command_when_the_refresh_fails(monkeypatch, capsys):
    from filament_kit import apply

    def boom(cfg, **kw):
        raise apply.ApplyError("install_file: read-only")
    code, probed = _pair_cli(monkeypatch, "station", ["192.0.2.5"], boom)
    assert code == 0 and probed == ["192.0.2.5"]  # no local server: the link's address only
    out = capsys.readouterr()
    assert "sudo filament-kit modules apply" in out.out + out.err


def test_save_pairing_server_file_is_world_readable_whatever_the_umask():
    if sys.platform == "win32":
        pytest.skip("POSIX modes")
    old = os.umask(0o077)
    try:
        _paired(["192.0.2.5"])
    finally:
        os.umask(old)
    assert (os.stat(server_api.server_file()).st_mode & 0o777) == 0o644
