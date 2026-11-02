import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import tagsources


class Fake:
    """A tiny HTTP server answering one JSON body (or an error status) on every GET."""

    def __init__(self, body=None, status=200):
        self.body, self.status, self.hits, self.paths = body, status, 0, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                outer.paths.append(self.path)
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(outer.body).encode())

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture(autouse=True)
def _reset():
    tagsources._failed.clear()
    yield
    tagsources._failed.clear()


@pytest.fixture
def fakes():
    made = []

    def make(*a, **k):
        f = Fake(*a, **k)
        made.append(f)
        return f
    yield make
    for f in made:
        f.close()


def tag(nfc, age, held=None):
    d = {"status": "ok", "nfc_id": nfc, "read_at_unix": time.time() - age, "age_seconds": age}
    if held is not None:
        d["held"] = held
    return d


def test_no_sources():
    assert tagsources.latest({}) is None
    assert tagsources.latest({"tag_sources": [], "station": {"url": None}}) is None


def test_newest_wins_across_sources_and_station(fakes):
    a = fakes(tag("AAA", 30))
    b = fakes(tag("BBB", 5))
    st = fakes(tag("SSS", 12, held=True))
    cfg = {"tag_sources": [{"name": "sv08", "url": a.url + "/last-tag"},
                           {"name": "h2d", "url": b.url + "/last-tag"}],
           "station": {"url": st.url}}
    got = tagsources.latest(cfg)
    assert got["nfc_id"] == "BBB" and got["reader"] == "h2d" and got["age_seconds"] == 5
    assert set(got) == {"nfc_id", "read_at_unix", "age_seconds", "reader", "held"}
    assert got["held"] is False
    b.body = tag("BBB", 50)
    got = tagsources.latest(cfg)
    assert got["nfc_id"] == "SSS" and got["reader"] == "station" and got["held"] is True


def test_station_url_gets_last_tag_path(fakes):
    st = fakes(tag("SSS", 1))
    tagsources.latest({"station": {"url": st.url + "/"}})
    assert st.paths == ["/last-tag"]


def test_skips_empty_and_non_ok_tags(fakes):
    none = fakes({"status": "ok", "nfc_id": None, "age_seconds": None})
    err = fakes({"status": "error", "message": "x"})
    good = fakes(tag("GGG", 40))
    cfg = {"tag_sources": [{"name": "n", "url": none.url}, {"name": "e", "url": err.url},
                           {"name": "g", "url": good.url}]}
    assert tagsources.latest(cfg)["nfc_id"] == "GGG"


def test_failing_source_skipped_for_60s(fakes, monkeypatch):
    bad = fakes({"x": 1}, status=500)
    good = fakes(tag("GGG", 9))
    cfg = {"tag_sources": [{"name": "bad", "url": bad.url}, {"name": "good", "url": good.url}]}
    assert tagsources.latest(cfg)["reader"] == "good"
    assert bad.hits == 1
    tagsources.latest(cfg)
    assert bad.hits == 1  # backing off
    t0 = time.monotonic()
    monkeypatch.setattr(tagsources.time, "monotonic", lambda: t0 + 61)
    tagsources.latest(cfg)
    assert bad.hits == 2


def test_unreachable_source_does_not_raise():
    cfg = {"tag_sources": [{"name": "dead", "url": "http://127.0.0.1:9/last-tag"}]}
    assert tagsources.latest(cfg) is None


def test_garbage_and_malformed_entries_ignored(fakes):
    bad = fakes(["not", "an", "object"])
    cfg = {"tag_sources": [{"name": "x", "url": bad.url}, {"name": "nourl"}, "junk", {"url": ""}]}
    assert tagsources.latest(cfg) is None
