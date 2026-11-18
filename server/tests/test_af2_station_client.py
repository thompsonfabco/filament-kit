"""AF2 (b) and (e): the Hub's pinned calls to a Weigh Station, the refusal on a changed certificate, and an older
station (plain HTTP, no fingerprint said) that keeps working until it is updated (R82 section 2 points 3 and 4)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import config, pairing, station_client
from filament_kit.station import http as station_http
from filament_kit.station import state as st
from filament_kit.station_client import StationCertChanged, StationClient, StationUnreachable

STATE = {"tag": "04:aa", "tag_at": None, "held": None, "scale": None, "scale_at": None, "air": None, "air_at": 0,
         "last": None, "last_at": None, "held_at": None, "panel": None, "panel_version": None, "panel_nfc": None,
         "flow": {"step": "idle"}, "photo": None, "photo_at": None}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setattr(st, "tls_dir", lambda: tmp_path / "station-state" / "tls")
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")


@pytest.fixture
def stations():
    made = []

    def https(folder=None):
        cert, key, fp = st.ensure_cert(folder)
        srv = station_http.TlsServer(("127.0.0.1", 0), station_http.make_handler(lambda: dict(STATE), {"127.0.0.1"}),
                                     station_http.tls_context(cert, key))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv.server_port, fp

    def plain():
        hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                data = json.dumps(STATE).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv.server_port, hits

    yield https, plain
    for s in made:
        s.shutdown()
        s.server_close()


def _paired_station(fp=None, port=None, version="0.6.2"):
    p = pairing.issue("station", scope="station")
    dev, _ = pairing.authorize(p.qr.split("t=")[1].split("&")[0])
    if fp:
        assert pairing.record_station_hello(dev, fp, port, version)
    return dev


def test_a_station_that_said_hello_is_called_over_https_at_its_port(stations):
    https, _plain = stations
    port, fp = https()
    _paired_station(fp, port)
    # the configured address is the old plain one with the old port: the stored port and certificate win
    assert StationClient("http://127.0.0.1:5003", backoff=0).state()["tag"]["nfc_id"] == "04:aa"


def test_a_changed_certificate_is_refused_and_never_retried_over_plain_http(stations, tmp_path):
    https, plain = stations
    port, _fp = https()
    _paired_station("ab" * 32, port)                     # the Hub trusts another certificate than the one served
    plain_port, hits = plain()
    client = StationClient(f"http://127.0.0.1:{plain_port}", backoff=0)
    with pytest.raises(StationCertChanged) as e:
        client.state()
    assert e.value.error == station_client.TEXT_STATION_CERT_CHANGED
    assert "sudo systemctl restart filament-kit-station" in e.value.fix and "pair it again" in e.value.fix
    assert isinstance(e.value, StationUnreachable) and hits == []     # no plain request went anywhere


def test_the_station_telling_the_hub_its_new_certificate_makes_it_trusted_again(stations):
    https, _plain = stations
    port, fp = https()
    dev = _paired_station("ab" * 32, port)
    with pytest.raises(StationCertChanged):
        StationClient("http://127.0.0.1:1", backoff=0).state()
    assert pairing.record_station_hello(dev, fp, port, "0.6.3")        # its next hello, over the token's channel
    assert StationClient("http://127.0.0.1:1", backoff=0).state()["tag"]["nfc_id"] == "04:aa"


def test_an_older_station_with_no_fingerprint_keeps_working_over_plain_http(stations):
    _https, plain = stations
    port, hits = plain()
    _paired_station()                                    # paired, but it never sent the three values (0.5.0)
    assert pairing.station_info() is None
    assert StationClient(f"http://127.0.0.1:{port}", backoff=0).state()["tag"] == "04:aa"
    assert hits == ["/state"]


def test_no_station_pairing_at_all_is_as_before(stations):
    _https, plain = stations
    port, hits = plain()
    assert StationClient(f"http://127.0.0.1:{port}", backoff=0).state()["tag"] == "04:aa" and hits == ["/state"]


def test_a_dead_station_still_backs_off_after_one_failure():
    _paired_station("ab" * 32, 1)
    client = StationClient("http://127.0.0.1:1", timeout=1, backoff=60)
    with pytest.raises(StationUnreachable):
        client.state()
    with pytest.raises(StationUnreachable, match="backing off"):
        client.state()


def test_station_https_says_which_of_the_four_it_is(stations):
    https, plain = stations
    assert station_client.station_https(None) is None
    assert station_client.station_https("http://127.0.0.1:1") == "plain"       # no certificate said: not updated
    port, fp = https()
    dev = _paired_station(fp, port)
    assert station_client.station_https("http://127.0.0.1:5003") == "https"
    pairing.record_station_hello(dev, "ab" * 32, port, "1")
    assert station_client.station_https("http://127.0.0.1:5003") == "changed"
    pairing.record_station_hello(dev, fp, 1, "1")
    assert station_client.station_https("http://127.0.0.1:5003") == "unreachable"


def test_station_reach_uses_the_pinned_call(stations):
    https, _plain = stations
    port, fp = https()
    dev = _paired_station(fp, port)
    devs = [{"id": dev, "type": "station"}]
    station_client._reach.clear()
    assert station_client.station_reach(devs, "http://127.0.0.1:5003") == {dev: True}
    pairing.record_station_hello(dev, "ab" * 32, port, "1")
    station_client._reach.clear()
    assert station_client.station_reach(devs, "http://127.0.0.1:5003") == {dev: False}


# the pins of the tag sources and the remote Label Reader

def test_pins_are_kept_in_an_xml_file_and_dropped_by_saving_again():
    assert station_client.pin_get("tag", "https://h:5002") is None
    station_client.pin_set("tag", "https://h:5002", "AB" * 32)
    station_client.pin_set("reader", "https://g:7915", "cd" * 32)
    assert station_client.pin_get("tag", "https://h:5002") == "ab" * 32
    assert station_client.pin_get("reader", "https://h:5002") is None
    path = config.paths().state / station_client.PINS_FILE
    assert path.read_bytes().startswith(b"<?xml") and b"<pin " in path.read_bytes()
    station_client.pin_set("tag", "https://h:5002", None)
    assert station_client.pin_get("tag", "https://h:5002") is None
    assert station_client.pin_get("reader", "https://g:7915") == "cd" * 32


def test_an_unreadable_pins_file_reads_as_none_kept():
    (config.paths().state / station_client.PINS_FILE).write_text("<pins><pin")
    assert station_client.pin_get("tag", "x") is None
    station_client.pin_set("tag", "x", "ab" * 32)                      # and is written whole again
    assert station_client.pin_get("tag", "x") == "ab" * 32


def test_pinned_get_with_no_pin_reports_what_it_saw(stations):
    https, _plain = stations
    port, fp = https()
    status, body, seen = station_client.pinned_get("127.0.0.1", port, "/last-tag", None, 5)
    assert status == 200 and seen == fp and station_client.peer_fingerprint("127.0.0.1", port) == fp
    with pytest.raises(station_client.PinMismatch):
        station_client.pinned_get("127.0.0.1", port, "/last-tag", "ab" * 32, 5)
