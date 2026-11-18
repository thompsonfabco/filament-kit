"""AF2 (a): the Weigh Station's own certificate and HTTPS listener, the three values on its hello call, and what the
Hub keeps of them with the station's pairing (R82 section 2 points 2 and 3)."""
import hashlib
import http.client
import json
import os
import ssl
import threading

import pytest

from filament_kit import config, pairing
from filament_kit.station import http as station_http
from filament_kit.station import server_api
from filament_kit.station import state as st


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setattr(st, "tls_dir", lambda: tmp_path / "station-state" / "tls")    # STATE_DIRECTORY is split on ":"
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")


def _station_device():
    """A claimed Weigh Station pairing on the Hub: (device id, token)."""
    p = pairing.issue("station", scope="station")
    token = p.qr.split("t=")[1].split("&")[0]
    dev, _scope = pairing.authorize(token)
    return dev, token


def _der_fp(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def test_the_station_makes_its_certificate_once_and_keeps_it(tmp_path):
    cert, key, fp = st.ensure_cert()
    assert cert == tmp_path / "station-state" / "tls" / "cert.pem" and cert.is_file() and key.is_file()
    assert fp == _der_fp(ssl.PEM_cert_to_DER_cert(cert.read_text()))
    if os.name != "nt":
        assert (key.stat().st_mode & 0o777) == 0o600
    assert st.ensure_cert()[2] == fp                       # a second start keeps it: the Hub's pin stays good
    key.unlink()
    assert st.ensure_cert()[2] != fp                       # a certificate without its key is made again
    assert key.is_file()


def test_a_certificate_that_cannot_be_read_is_made_again(tmp_path):
    cert, key, fp = st.ensure_cert()
    cert.write_text("not a certificate")
    assert st.ensure_cert()[2] != fp


def _serve(allow):
    cert, key, fp = st.ensure_cert()
    view = lambda: {"tag": "04:aa", "tag_at": None, "held": None}
    srv = station_http.TlsServer(("127.0.0.1", 0), station_http.make_handler(view, allow),
                                 station_http.tls_context(cert, key))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, fp


def _client():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_the_listener_serves_https_with_that_certificate():
    srv, fp = _serve({"127.0.0.1"})
    try:
        c = http.client.HTTPSConnection("127.0.0.1", srv.server_port, context=_client(), timeout=5)
        c.connect()
        assert _der_fp(c.sock.getpeercert(binary_form=True)) == fp
        c.request("GET", "/last-tag")
        r = c.getresponse()
        body = json.loads(r.read())
        assert r.status == 200 and body["nfc_id"] == "04:aa"
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_plain_http_caller_gets_no_answer_and_the_listener_lives_on():
    srv, _fp = _serve({"127.0.0.1"})
    try:
        plain = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
        with pytest.raises((http.client.HTTPException, OSError)):
            plain.request("GET", "/last-tag")
            plain.getresponse()
        plain.close()
        c = http.client.HTTPSConnection("127.0.0.1", srv.server_port, context=_client(), timeout=5)
        c.request("GET", "/last-tag")
        assert c.getresponse().status == 200
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_an_address_not_on_the_allow_list_still_gets_403_over_https():
    srv, _fp = _serve({"192.0.2.1"})
    try:
        c = http.client.HTTPSConnection("127.0.0.1", srv.server_port, context=_client(), timeout=5)
        c.request("GET", "/state")
        assert c.getresponse().status == 403
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


# the three values on the hello call

FP = "ab" * 32


def test_the_hub_keeps_the_three_values_with_the_stations_pairing():
    dev, _ = _station_device()
    assert pairing.station_info() is None                  # nothing said yet: plain HTTP
    assert pairing.record_station_hello(dev, FP, 5003, "0.6.2") is True
    info = pairing.station_info()
    assert (info["fp"], info["port"], info["version"]) == (FP, 5003, "0.6.2") and info["hello_at"]
    stored = json.loads((config.paths().state / "devices.json").read_text())
    assert [d for d in stored if d["id"] == dev][0]["fp"] == FP        # in the pairing's existing (JSON) file
    assert pairing.record_station_hello(dev, "cd" * 32, 443, "0.7.0") is True   # a new certificate replaces it
    info = pairing.station_info()
    assert (info["fp"], info["port"], info["version"]) == ("cd" * 32, 443, "0.7.0")


@pytest.mark.parametrize("fp,port,version", [
    ("zz" * 32, 5003, "1"), ("ab" * 31, 5003, "1"), (FP, 0, "1"), (FP, 70000, "1"), (FP, "five", "1"),
    (FP, 5003, "x" * 41), (FP, 5003, "a\nb"), (None, 5003, "1")])
def test_a_value_that_is_not_one_is_not_stored(fp, port, version):
    dev, _ = _station_device()
    assert pairing.record_station_hello(dev, fp, port, version) is False
    assert pairing.station_info() is None


def test_only_a_station_pairing_takes_the_values():
    p = pairing.issue("phone")
    token = p.qr.split("t=")[1].split("&")[0]
    dev, _ = pairing.authorize(token)
    assert pairing.record_station_hello(dev, FP, 5003, "1") is False
    assert pairing.record_station_hello("nosuchdevice", FP, 5003, "1") is False
    assert pairing.station_info() is None


# the station's side of the call

class _Api:
    def __init__(self, answers, paired=True):
        self.paired, self.answers, self.calls = paired, list(answers), []

    def hello(self, values=None):
        self.calls.append(values)
        return self.answers.pop(0)


def test_hello_values_are_the_fingerprint_the_port_and_the_version():
    from filament_kit import __version__
    assert server_api.hello_values(FP, 443) == {"fp": FP, "port": 443, "version": __version__}


def test_hello_sends_the_values_as_the_query_of_the_call(monkeypatch):
    seen = []
    api = server_api.ServerApi.__new__(server_api.ServerApi)
    api.paired = True
    monkeypatch.setattr(api, "_call", lambda method, path, *a: seen.append((method, path)) or (200, {"ok": True}),
                        raising=False)
    assert api.hello() == (200, {"ok": True})
    api.hello({"fp": FP, "port": 5003, "version": "0.6.2"})
    assert seen == [("GET", "/api/station/hello"), ("GET", f"/api/station/hello?fp={FP}&port=5003&version=0.6.2")]


def test_announce_tells_the_hub_once_and_stops():
    api = _Api([(200, {"ok": True})])
    assert server_api.announce(lambda: api, FP, 5003, sleep=lambda s: None) is True
    assert api.calls == [server_api.hello_values(FP, 5003)]


def test_announce_asks_again_while_the_hub_does_not_answer():
    api = _Api([(0, {"error": "unreachable"}), (0, {"error": "unreachable"}), (200, {})])
    waits = []
    assert server_api.announce(lambda: api, FP, 5003, wait=7, sleep=waits.append) is True
    assert len(api.calls) == 3 and waits == [3, 6]          # quick at first, then at most `wait`
    api = _Api([(0, {})] * 7 + [(200, {})])
    waits = []
    assert server_api.announce(lambda: api, FP, 5003, wait=10, sleep=waits.append) is True
    assert waits == [3, 6, 10, 10, 10, 10, 10]


def test_announce_gives_up_after_its_tries_and_on_a_bad_token_and_when_unpaired():
    api = _Api([(0, {})] * 3)
    assert server_api.announce(lambda: api, FP, 5003, tries=3, sleep=lambda s: None) is False and len(api.calls) == 3
    api = _Api([(401, {})])
    assert server_api.announce(lambda: api, FP, 5003, sleep=lambda s: None) is False and len(api.calls) == 1
    api = _Api([], paired=False)
    assert server_api.announce(lambda: api, FP, 5003, sleep=lambda s: None) is False and api.calls == []
