"""AF2 (d): the remote Label Reader's https rule and its pin at Test (R82 section 2 point 6, section 10 point 6)."""
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from filament_kit import local_reader, pairing, station_client

HEALTH = {"status": "ok", "api_version": "1.0", "module_version": "1.2.3", "tiers": {"cpu": {"usable": True}}}
FP_OTHER = "ab" * 32


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))


@pytest.fixture
def reader(tmp_path):
    """A reader's health route over HTTPS with its own certificate: (url, fingerprint)."""
    fp = pairing.make_cert("reader-box", ["127.0.0.1"], tmp_path / "reader-tls")

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(HEALTH).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "reader-tls" / "cert.pem", tmp_path / "reader-tls" / "key.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{srv.server_port}", fp
    srv.shutdown()
    srv.server_close()


def _cfg(url):
    return {"local_intake": {"url": url}}


def test_the_first_test_pins_the_certificate_and_shows_its_fingerprint(reader):
    url, fp = reader
    out = local_reader.test(_cfg(url))
    assert out["ok"] is True and out["https"] is True and out["fp"] == fp and out["pin"] == "new"
    assert out["warning"] is None and local_reader.https_row(_cfg(url)) is None     # https: no row
    assert station_client.pin_get("reader", url) == fp
    again = local_reader.test(_cfg(url))
    assert again["ok"] is True and again["pin"] == "same" and again["fp"] == fp


def test_a_changed_certificate_fails_the_test_and_every_call_until_it_is_trusted(reader):
    url, fp = reader
    station_client.pin_set("reader", url, FP_OTHER)
    out = local_reader.test(_cfg(url))
    assert out["ok"] is False and out["pin"] == "changed" and out["fp"] == fp
    assert "presents a different certificate" in out["error"] and local_reader.TEXT_CERT_FIX in out["error"]
    assert station_client.pin_get("reader", url) == FP_OTHER                 # a plain Test never re-pins
    h = local_reader.health(_cfg(url))
    assert h["ok"] is False and "different certificate" in h["error"]        # nor does any other call get through
    out = local_reader.test(_cfg(url), trust=True)
    assert out["ok"] is True and out["pin"] == "replaced" and station_client.pin_get("reader", url) == fp


def test_a_call_made_before_any_test_pins_on_first_use_too(reader):
    url, fp = reader
    assert local_reader.health(_cfg(url))["ok"] is True
    assert station_client.pin_get("reader", url) == fp


def test_a_reader_that_does_not_answer_is_reported_not_raised():
    out = local_reader.test(_cfg("https://127.0.0.1:1"))
    assert out["ok"] is False and out["fp"] is None and out["pin"] is None and "does not answer" in out["error"]


def test_an_http_address_on_this_machine_is_never_a_problem():
    for url in ("http://127.0.0.1:7915", "http://localhost:7915"):
        assert local_reader.needs_https(url) is False
        assert local_reader.https_row(_cfg(url)) is None
    assert local_reader.check_url("http://127.0.0.1:7915") is None
    assert local_reader.test(_cfg("http://127.0.0.1:1"))["warning"] is None


def test_until_the_reader_serves_https_an_http_address_elsewhere_is_accepted_with_the_row(monkeypatch):
    assert local_reader.ENFORCE_HTTPS is False
    url = "http://gpu-box.example:7915"
    assert local_reader.needs_https(url) is True
    assert local_reader.check_url(url) is None                                # accepted as it always was
    assert local_reader.https_row(_cfg(url)) == {      # the one row: group Label Reader, a note, no fix
        "group": "Label Reader", "state": "note", "fix": None,
        "text": "The Label Reader at gpu-box.example:7915 is not using HTTPS. A later Label Reader version adds it."}
    monkeypatch.setattr(local_reader, "_reachable", lambda u: (_ for _ in ()).throw(
        local_reader.LocalReaderError("unreachable", "no answer here")))
    out = local_reader.test(_cfg(url))
    assert out["error"] == "no answer here"                                  # the call went as far as the connection
    assert out["warning"] == local_reader.https_row(_cfg(url))["text"] and out["fp"] is None and out["https"] is False


def test_with_the_rule_on_saving_an_http_address_elsewhere_is_refused_and_a_stored_one_becomes_needs_a_look(monkeypatch):
    monkeypatch.setattr(local_reader, "ENFORCE_HTTPS", True)
    assert local_reader.TEXT_NEEDS_HTTPS == "A Label Reader on another machine needs an https address."
    url = "http://gpu-box.example:7915"
    assert local_reader.check_url(url) == "A Label Reader on another machine needs an https address."
    assert local_reader.check_url("https://gpu-box.example:7915") is None
    assert local_reader.check_url("http://127.0.0.1:7915") is None
    assert local_reader.check_url("http://localhost:7915") is None
    assert local_reader.https_row(_cfg(url)) == {
        "group": "Label Reader", "state": "needs_a_look",
        "text": "The Label Reader at gpu-box.example:7915 is not using HTTPS.",
        "fix": "Update the Label Reader on that machine, then change its address to https:// in Settings > Label Reader."}
    assert local_reader.https_row(_cfg("http://127.0.0.1:7915")) is None
    monkeypatch.setattr(local_reader, "_reachable", lambda u: (_ for _ in ()).throw(
        local_reader.LocalReaderError("unreachable", "no answer here")))
    assert local_reader.health(_cfg(url))["error"] == "no answer here"       # a stored address keeps being used
