"""`filament-kit status` checks only the modules that are on."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import cli, config


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()


def _cfg(url=None):
    cfg = config.load()
    cfg["modules"] = {"station": True}
    cfg["spoolman_url"] = "http://127.0.0.1:1"   # Spoolman down: not this machine's business
    cfg["station"]["url"] = url
    config.save(cfg)


def _serve_station(body, status=200):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_status_station_only(capsys):
    _cfg()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out and "Anthropic" not in out and "certificate" not in out


def test_services_follow_modules():
    assert cli.services_for(frozenset({"server", "station"})) == ("filament-kit", "filament-kit-station")
    assert cli.services_for(frozenset({"spoolman", "server"})) == ("spoolman", "filament-kit")
    assert cli.services_for(frozenset({"backup"})) == ()


def test_status_station_unreachable_fails_naming_url(capsys):
    _cfg("http://127.0.0.1:1")
    assert cli.main(["status"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "http://127.0.0.1:1" in out


def test_status_station_not_seen_is_informational(capsys):
    srv, url = _serve_station({"tag": None, "scale": None, "last_weight": None, "held": None})
    try:
        _cfg(url)
        assert cli.main(["status"]) == 0
    finally:
        srv.shutdown()
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert "--   station reader not seen" in out and "--   station scale not seen" in out


def test_status_station_seen(capsys):
    srv, url = _serve_station({"tag": {"nfc_id": "a"}, "scale": {"n": 1}, "last_weight": None, "held": None})
    try:
        _cfg(url)
        assert cli.main(["status"]) == 0
    finally:
        srv.shutdown()
    out = capsys.readouterr().out
    assert "OK   station answering" in out and "not seen" not in out


# What filament_kit.station really answers (station/http.py): "tag" is always an object, "nfc_id" null until a tap.
FRESH_STATE = {"tag": {"status": "ok", "nfc_id": None, "read_at": None, "read_at_unix": None,
                       "age_seconds": None, "held": False},
               "scale": None, "last_weight": None, "panel": None}


def test_status_real_fresh_station_shows_reader_and_scale_not_seen(capsys):
    srv, url = _serve_station(FRESH_STATE)
    try:
        _cfg(url)
        assert cli.main(["status"]) == 0
    finally:
        srv.shutdown()
    out = capsys.readouterr().out
    assert "--   station reader not seen" in out and "--   station scale not seen" in out


def test_status_real_station_after_a_tap_reader_seen(capsys):
    state = json.loads(json.dumps(FRESH_STATE))
    state["tag"]["nfc_id"] = "4:77:90:e:9:22:89"
    srv, url = _serve_station(state)
    try:
        _cfg(url)
        assert cli.main(["status"]) == 0
    finally:
        srv.shutdown()
    out = capsys.readouterr().out
    assert "reader not seen" not in out and "--   station scale not seen" in out
