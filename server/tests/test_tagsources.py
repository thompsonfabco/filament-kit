import json
import threading
import time
import types
import urllib.error
import urllib.request
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
    monkeypatch.setattr(tagsources, "time", types.SimpleNamespace(monotonic=lambda: t0 + 61))   # this module's clock only
    tagsources.latest(cfg)
    assert bad.hits == 2


def test_unreachable_source_does_not_raise():
    cfg = {"tag_sources": [{"name": "dead", "url": "http://127.0.0.1:9/last-tag"}]}
    assert tagsources.latest(cfg) is None


def test_garbage_and_malformed_entries_ignored(fakes):
    bad = fakes(["not", "an", "object"])
    cfg = {"tag_sources": [{"name": "x", "url": bad.url}, {"name": "nourl"}, "junk", {"url": ""}]}
    assert tagsources.latest(cfg) is None


# ---------- merge-ops: fresh unknown tag, station scale weight ----------

class _SM:
    def __init__(self, spools):
        self.spools = spools

    def get(self, path):
        assert path.startswith("spool")
        return self.spools


def test_scale_weight_fresh_or_held():
    assert tagsources.scale_weight(None) is None
    assert tagsources.scale_weight({"last_weight": None}) is None
    w = {"grams": 900, "age_seconds": 300, "held": False}
    assert tagsources.scale_weight({"last_weight": w}) == w
    assert tagsources.scale_weight({"last_weight": {**w, "age_seconds": 301}}) is None
    assert tagsources.scale_weight({"last_weight": {**w, "age_seconds": 999, "held": True}})["grams"] == 900


def test_fresh_unknown_tag(monkeypatch):
    tag = {"nfc_id": "04:A1:B2:C3", "read_at_unix": 1, "age_seconds": 20, "reader": "station", "held": False}
    monkeypatch.setattr(tagsources, "latest", lambda cfg: dict(tag))
    linked = [{"id": 1, "extra": {"nfc_id": json.dumps("4:a1:b2:c3")}}]
    assert tagsources.fresh_unknown_tag({}, _SM(linked)) is None            # already on a spool
    got = tagsources.fresh_unknown_tag({}, _SM([]))
    assert got["nfc_id"] == "4:a1:b2:c3" and got["age_seconds"] == 20 and got["reader"] == "station"
    tag["age_seconds"] = 301
    assert tagsources.fresh_unknown_tag({}, _SM([])) is None                # stale
    tag["held"] = True
    assert tagsources.fresh_unknown_tag({}, _SM([])) is not None            # held on the panel
    monkeypatch.setattr(tagsources, "latest", lambda cfg: None)
    assert tagsources.fresh_unknown_tag({}, _SM([])) is None


def test_only_http_and_https_sources_are_read(monkeypatch):
    """A-M2: a tag source is fetched only over http(s) (urllib would also open file: and ftp: URLs)."""
    seen = []
    monkeypatch.setattr(tagsources, "_fetch", lambda url: seen.append(url) or None)
    cfg = {"tag_sources": [{"name": "f", "url": "file:///etc/passwd"}, {"name": "ftp", "url": "ftp://x/y"},
                           {"name": "ok", "url": "http://lasttag.example.lan:5002/last-tag"},
                           {"name": "tls", "url": "HTTPS://reader.example.lan/last-tag"}],
           "station": {"url": "file:///tmp"}}
    tagsources.latest(cfg)
    assert seen == ["http://lasttag.example.lan:5002/last-tag", "HTTPS://reader.example.lan/last-tag"]


class Redirector:
    """A web server that answers every GET with a 302 to `to`."""

    def __init__(self, to):
        outer = self
        self.hits = 0

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                self.send_response(302)
                self.send_header("Location", to)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.mark.parametrize("target", ["ftp://127.0.0.1:1/last-tag", "file:///etc/passwd", "gopher://127.0.0.1:1/x"])
def test_a_source_that_redirects_to_another_scheme_is_not_followed(monkeypatch, target):
    """A-M2 again: the configured URL is http(s), but the server there can answer with a 30x to anything urllib opens."""
    opened = []

    def ftp_open(self, req):
        opened.append(req.full_url)
        raise urllib.error.URLError("not for real")
    monkeypatch.setattr(urllib.request.FTPHandler, "ftp_open", ftp_open)
    r = Redirector(target)
    try:
        assert tagsources.latest({"tag_sources": [{"name": "r", "url": r.url}]}) is None
        assert r.hits == 1
    finally:
        r.close()
    assert opened == []
    assert tagsources._failed.get(r.url) is not None          # and it backs off like any failing source


def test_a_source_that_redirects_to_http_is_still_followed(fakes):
    good = fakes(tag("GGG", 5))
    r = Redirector(good.url + "/last-tag")
    try:
        assert tagsources.latest({"tag_sources": [{"name": "r", "url": r.url}]})["nfc_id"] == "GGG"
    finally:
        r.close()
