"""AF2 fix: a station that cannot make its certificate serves plain HTTP and says so; the Hub calls a station it never
pinned over plain HTTP, never downgrades one it pinned, and has the Checks row text for the first."""
import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import pairing, station_client
from filament_kit.station import __main__ as station_main
from filament_kit.station import http as station_http
from filament_kit.station import server_api
from filament_kit.station import state as st
from filament_kit.station_client import StationCertChanged, StationClient, StationUnreachable

STATE = {"tag": "04:aa", "tag_at": None, "held": None}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setattr(st, "tls_dir", lambda: tmp_path / "station-state" / "tls")
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")


def _station_device():
    p = pairing.issue("station", scope="station")
    dev, _ = pairing.authorize(p.qr.split("t=")[1].split("&")[0])
    return dev


@pytest.fixture
def plain_station():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            data = json.dumps({"tag": "04:aa"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port, hits
    srv.shutdown()
    srv.server_close()


# the station

def test_a_station_that_cannot_make_its_certificate_serves_plain_http_and_says_why(monkeypatch, caplog):
    def broken(folder=None):
        raise OSError("read-only file system")
    monkeypatch.setattr(st, "ensure_cert", broken)
    handler = station_http.make_handler(lambda: dict(STATE), {"127.0.0.1"})
    with caplog.at_level("ERROR", logger="intake-station"):
        srv, fp, plain = station_main.make_server(0, handler)
    try:
        assert fp is None and plain == "OSError: read-only file system"
        assert "serving plain HTTP" in caplog.text and "read-only file system" in caplog.text
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
        c.request("GET", "/last-tag")
        assert c.getresponse().status == 200
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_station_with_a_certificate_still_serves_https():
    handler = station_http.make_handler(lambda: dict(STATE), {"127.0.0.1"})
    srv, fp, plain = station_main.make_server(0, handler)
    try:
        assert plain is None and len(fp) == 64 and isinstance(srv, station_http.TlsServer)
    finally:
        srv.server_close()


def test_the_hello_of_a_station_without_a_certificate_has_no_fp_and_says_why():
    values = server_api.hello_values(None, 5003, "OSError: read-only\nfile system")
    assert "fp" not in values and values["port"] == 5003 and values["plain"] == "OSError: read-only file system"
    api = type("A", (), {"paired": True, "calls": [], "hello": lambda self, v=None: (self.calls.append(v), (200, {}))[1]})()
    assert server_api.announce(lambda: api, None, 5003, plain="no openssl", sleep=lambda s: None) is True
    assert api.calls == [server_api.hello_values(None, 5003, "no openssl")] and "fp" not in api.calls[0]


# the Hub

def test_the_hub_keeps_a_plain_by_necessity_station_apart_from_an_older_one():
    dev = _station_device()
    assert pairing.record_station_hello(dev, None, 5003, "0.6.2", plain="OSError: read-only") is True
    assert pairing.station_info() is None                       # no certificate to pin
    assert pairing.station_plain_reason() == "OSError: read-only"
    assert pairing.record_station_hello(dev, None, 5003, "0.6.2") is False      # no fp and no reason: still the old way
    assert pairing.record_station_hello(dev, None, 0, "0.6.2", plain="x") is False


def test_the_hub_calls_an_unpinned_plain_station_over_http(plain_station):
    port, hits = plain_station
    dev = _station_device()
    pairing.record_station_hello(dev, None, port, "0.6.2", plain="no openssl")
    assert StationClient(f"http://127.0.0.1:{port}", backoff=0).state()["tag"] == "04:aa"
    assert hits == ["/state"]


def test_the_hub_never_calls_a_pinned_station_over_plain_http(plain_station):
    port, hits = plain_station
    dev = _station_device()
    assert pairing.record_station_hello(dev, "ab" * 32, port, "0.6.2")     # pinned: it once served this certificate
    with pytest.raises(StationCertChanged) as e:
        StationClient(f"http://127.0.0.1:{port}", backoff=0).state()        # now it answers only plain HTTP
    assert e.value.error == station_client.TEXT_STATION_CERT_CHANGED and e.value.fix == station_client.TEXT_STATION_CERT_FIX
    assert hits == []                                                        # nothing went over plain HTTP
    assert station_client.station_https(f"http://127.0.0.1:{port}") == "changed"


def test_a_plain_hello_from_a_pinned_station_does_not_clear_its_pin(plain_station):
    port, hits = plain_station
    dev = _station_device()
    pairing.record_station_hello(dev, "ab" * 32, 5003, "0.6.2")
    assert pairing.record_station_hello(dev, None, port, "0.6.3", plain="no cert now") is True
    info = pairing.station_info()
    assert info["fp"] == "ab" * 32 and info["port"] == 5003                  # pin and HTTPS port stay
    with pytest.raises(StationUnreachable):                                  # nothing answers on its HTTPS port
        StationClient(f"http://127.0.0.1:{port}", backoff=0).state()
    assert hits == []                                                        # and the plain port is never tried
    assert pairing.record_station_hello(dev, "cd" * 32, 5003, "0.6.4")      # a later hello with a certificate re-pins
    assert pairing.station_plain_reason() is None


def test_the_checks_row_text_says_why_or_just_that_it_is_plain():
    url = "http://station.example:5003"
    assert station_client.station_https_row(None) is None
    dev = _station_device()
    assert station_client.station_https_row(url) == "The Weigh Station at station.example:5003 is not using HTTPS."
    pairing.record_station_hello(dev, None, 5003, "0.6.2", plain="PermissionError: [Errno 13] key.pem")
    assert station_client.station_https_row(url) == (
        "The Weigh Station at station.example:5003 is not using HTTPS: it could not make its certificate "
        "(PermissionError: [Errno 13] key.pem).")
    pairing.record_station_hello(dev, "ab" * 32, 5003, "0.6.2")
    assert station_client.station_https_row(url) is None                     # pinned: the other rows apply
