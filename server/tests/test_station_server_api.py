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
