"""AF2 (c): a tag source at an https address is pinned the first time it is read (trust on first use), a changed
certificate is refused with the fix, and a plain-HTTP source is read as it was (R82 section 2 points 2 and 5)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import pairing, station_client, tagsources
from filament_kit.station import http as station_http
from filament_kit.station import state as st


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setattr(st, "tls_dir", lambda: tmp_path / "station-state" / "tls")
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")
    tagsources._failed.clear()
    yield
    tagsources._failed.clear()


@pytest.fixture
def servers(tmp_path):
    made = []

    def https(uid="04:aa:bb", folder=None):
        cert, key, fp = st.ensure_cert(folder)
        view = lambda: {"tag": uid, "tag_at": time.time() - 5, "held": None}
        srv = station_http.TlsServer(("127.0.0.1", 0), station_http.make_handler(view, {"127.0.0.1"}),
                                     station_http.tls_context(cert, key))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv.server_port, fp

    def plain(uid="04:cc:dd"):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps({"status": "ok", "nfc_id": uid, "age_seconds": 3}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv.server_port

    yield https, plain
    for s in made:
        s.shutdown()
        s.server_close()


def _cfg(url, name="printer"):
    return {"tag_sources": [{"name": name, "url": url}]}


def test_an_https_source_is_pinned_at_its_first_read_and_read_again(servers):
    https, _plain = servers
    port, fp = https()
    url = f"https://127.0.0.1:{port}/last-tag"
    assert station_client.pin_get("tag", tagsources.origin(url)) is None
    assert tagsources.latest(_cfg(url))["nfc_id"] == "04:aa:bb"
    assert station_client.pin_get("tag", tagsources.origin(url)) == fp
    assert tagsources.latest(_cfg(url))["reader"] == "printer"
    assert tagsources.issues(_cfg(url)) == []


def test_a_changed_certificate_is_refused_and_the_fix_is_to_save_the_source_again(servers, tmp_path):
    https, _plain = servers
    port, fp = https()
    url = f"https://127.0.0.1:{port}/last-tag"
    station_client.pin_set("tag", tagsources.origin(url), "ab" * 32)       # the Hub trusts another certificate
    assert tagsources.latest(_cfg(url)) is None                             # nothing is read from it
    assert tagsources._failed                                               # and it backs off like a dead source
    assert station_client.pin_get("tag", tagsources.origin(url)) == "ab" * 32    # never re-pinned by itself
    (row,) = tagsources.issues(_cfg(url))
    assert row["kind"] == "changed" and row["fix"] == "Save the tag source again to trust the new certificate."
    assert row["text"] == f"The tag service at 127.0.0.1:{port} presents a different certificate than the one the Hub trusts."
    assert tagsources.trust(url) == fp                                      # saved again: the new certificate is kept
    assert tagsources.issues(_cfg(url)) == []
    assert tagsources.latest(_cfg(url))["nfc_id"] == "04:aa:bb"


def test_forgetting_a_pin_lets_the_next_read_keep_the_certificate_it_meets(servers):
    https, _plain = servers
    port, fp = https()
    url = f"https://127.0.0.1:{port}/last-tag"
    station_client.pin_set("tag", tagsources.origin(url), "ab" * 32)
    tagsources.forget_pin(url)
    assert tagsources.latest(_cfg(url))["nfc_id"] == "04:aa:bb"
    assert station_client.pin_get("tag", tagsources.origin(url)) == fp


def test_trust_on_a_plain_address_pins_nothing(servers):
    _https, plain = servers
    url = f"http://127.0.0.1:{plain()}/last-tag"
    assert tagsources.trust(url) is None
    assert station_client.pin_get("tag", tagsources.origin(url)) is None


def test_a_plain_http_source_is_read_as_before_and_named_for_the_checks(servers):
    _https, plain = servers
    url = f"http://127.0.0.1:{plain()}/last-tag"
    assert tagsources.latest(_cfg(url))["nfc_id"] == "04:cc:dd"
    assert tagsources.issues(_cfg(url)) == []                               # this machine's own address: nothing to say
    (row,) = tagsources.issues(_cfg("http://192.0.2.9:5002/last-tag", name="sv08"))
    assert row == {"name": "sv08", "url": "http://192.0.2.9:5002/last-tag", "kind": "plain", "fix": None,
                   "text": "The tag service at 192.0.2.9:5002 is not using HTTPS. Update it."}


def test_a_source_that_is_down_is_no_issue_and_a_pin_is_not_made_for_it():
    url = "https://127.0.0.1:1/last-tag"
    assert tagsources.latest(_cfg(url)) is None
    assert station_client.pin_get("tag", tagsources.origin(url)) is None
    assert tagsources.issues(_cfg(url)) == []


def test_the_station_source_is_read_over_https_with_the_certificate_it_said(servers):
    https, plain = servers
    port, fp = https(uid="04:11:22")
    p = pairing.issue("station", scope="station")
    dev, _ = pairing.authorize(p.qr.split("t=")[1].split("&")[0])
    pairing.record_station_hello(dev, fp, port, "0.6.2")
    cfg = {"station": {"url": "http://127.0.0.1:1"}}                        # the old address and port: the stored port wins
    assert tagsources.latest(cfg)["nfc_id"] == "04:11:22"
    pairing.record_station_hello(dev, "ab" * 32, port, "0.6.2")
    tagsources._failed.clear()
    assert tagsources.latest(cfg) is None                                    # another certificate: refused, not plain


def test_a_station_that_said_nothing_is_read_over_plain_http_as_before(servers):
    _https, plain = servers
    port = plain(uid="04:33:44")
    assert tagsources.latest({"station": {"url": f"http://127.0.0.1:{port}"}})["reader"] == "station"
