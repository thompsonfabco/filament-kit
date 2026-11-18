"""The Devices section's kind, version, out of date and Open, a device's detail with the station's settings, and the Weigh
Station's own page passed through the Hub (R83 section 9, 10.2, 10.4; setup_console/device_tab.py).

The Hub's other parts (a pairing's kind and version, the reader's build, the station's own routes and its pinned client) are
not in the tree yet: a stub Hub lends the rows their kind and version, and a stub station (a thread with the ruled routes
of 10.4) stands in for the station. The registry that mounts the routes is not this step's either: the tests mount them.
The same skip rules as test_hub_devices.py (no Node 22 or no browser is a skip, a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing, reader_tokens, setup_console, setup_page
from filament_kit.setup_console import device_tab
from filament_kit.web.slots import INTAKE_DEVICE

from test_hub_devices import DEVICES_PRELUDE, _T, _page_drive
from test_hub_page_audit import CODE, hub_app, hub_change  # noqa: F401
from test_setup_page import env, helper, manager  # noqa: F401
import test_setup_page as SP

browser = pytest.mark.browser_audit      # tools/testenv runs the browser tests as a group of 2 workers

# ---------------------------------------------------------------- the stubs
PAGE = ("<!doctype html><title>Bench station</title><link rel=stylesheet href='static/page.css'>"
        "<p id=out>waiting</p><p id=settings></p><script src='static/page.js'></script>")
SCRIPT = ("fetch('state').then(r => r.json()).then(s => { document.getElementById('out').textContent = 'tag ' + s.tag.uid; });"
          "fetch('settings').then(r => r.json()).then(s => { document.getElementById('settings').textContent = s.settings.map(x => x.id).join(','); });"
          "window.save = (v) => fetch('settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) })"
          ".then(async (r) => [r.status, await r.json()]);")
SETTINGS = [{"id": "beep", "label": "Beep", "kind": "switch", "value": True},
            {"id": "voice", "label": "Voice", "kind": "choice", "value": "piper", "choices": ["piper", {"value": "espeak", "label": "espeak-ng"}]},
            {"id": "volume", "label": "Volume", "kind": "number", "value": 60, "min": 0, "max": 100},
            {"id": "lamp.weigh", "label": "Lamp for weighing", "kind": "choice", "value": "yellow", "choices": ["yellow", "red", "off"]}]
STATE = {"tag": {"uid": "04A1B2"}, "scale": None, "last_weight": {"grams": 612.5}, "panel": "v1.2", "version": "0.7.0", "settings_changed": False}


class Station:
    """A station's own listener with the routes of 10.4: its page and files, /state, /settings."""

    def __init__(self):
        self.calls, self.settings = [], json.loads(json.dumps(SETTINGS))
        me = self

        class H(BaseHTTPRequestHandler):
            def _send(self, status, body, kind):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                me.calls.append(("GET", self.path, None))
                path = self.path.split("?")[0]
                if path == "/":
                    return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                if path == "/static/page.js":
                    return self._send(200, SCRIPT.encode(), "application/javascript")
                if path == "/static/page.css":
                    return self._send(200, b"#out{color:rgb(1,2,3)}", "text/css")
                if path == "/state":
                    return self._send(200, json.dumps(STATE).encode(), "application/json")
                if path == "/settings":
                    return self._send(200, json.dumps({"settings": me.settings}).encode(), "application/json")
                if path == "/photo.jpg":
                    return self._send(200, b"\xff\xd8\xff\xe0jpeg", "image/jpeg")
                self._send(404, b'{"error": "no such page"}', "application/json")

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                me.calls.append(("POST", self.path, json.loads(raw or b"{}")))
                if self.path != "/settings":
                    return self._send(404, b'{"error": "no such page"}', "application/json")
                got = json.loads(raw)
                if got.get("reset"):
                    me.settings = json.loads(json.dumps(SETTINGS))
                else:
                    for s in me.settings:
                        if s["id"] in got:
                            s["value"] = got[s["id"]]
                self._send(200, json.dumps({"settings": me.settings}).encode(), "application/json")

            def log_message(self, *a):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def posts(self):
        return [c[2] for c in self.calls if c[0] == "POST"]


PAIRINGS = [
    {"id": "d1", "name": "Kitchen phone", "type": None, "paired": 1.0, "last_seen": 1.0, "kind": "android", "version": "1.4.0"},
    {"id": "d2", "name": "Shop PC", "type": None, "paired": 1.0, "last_seen": 1.0, "kind": "slicer-sync", "version": "0.5.0"},
    {"id": "d3", "name": "Bench station", "type": "station", "paired": 1.0, "last_seen": 1.0, "kind": "weigh-station", "version": "0.5.0"},
    {"id": "d4", "name": "Garage tablet", "type": None, "paired": 1.0, "last_seen": 1.0, "kind": "web", "version": None},
    {"id": "d5", "name": "Old phone", "type": None, "paired": 1.0, "last_seen": 1.0},
    {"id": "d6", "name": INTAKE_DEVICE, "type": None, "paired": 1.0, "last_seen": 1.0},
]
READERS = [{"id": "r1", "name": "Tag Reader for Workshop X1", "created": "2026-11-01T10:00:00", "build": 5, "last_seen": 1.0},
           {"id": "r2", "name": "Tag Reader for Garage Voron", "created": "2026-11-02T10:00:00"}]


@pytest.fixture
def stub(monkeypatch):
    """The Hub the Devices rows are built on, as the other Hub steps will leave it, and a station."""
    st = Station()
    monkeypatch.setattr(device_tab, "_pairings", lambda: [dict(p) for p in PAIRINGS])
    monkeypatch.setattr(device_tab, "_readers", lambda: [dict(r) for r in READERS])
    monkeypatch.setattr(device_tab, "_phone_offer", lambda: "1.5.0")
    monkeypatch.setattr(device_tab, "_reader_offer", lambda: "7")
    monkeypatch.setattr(device_tab, "__version__", "0.7.0")
    # the mounting EV5 does: the page routes, and the pass-through under /setup/device
    orig_page, orig_console = setup_page.SetupPage.routes, setup_console.routes
    monkeypatch.setattr(setup_page.SetupPage, "routes", lambda self: orig_page(self) + device_tab.passthrough_routes(self))
    monkeypatch.setattr(setup_console, "routes", lambda page: orig_console(page) + device_tab.routes(page))
    return st


def _station_url(st):
    cfg = config.load()
    cfg["station"] = {**cfg["station"], "url": st.url}
    config.save(cfg)


# ---------------------------------------------------------------- the routes
@pytest.fixture
def env_hub(env, helper, manager, stub):
    _station_url(stub)
    return SP.client(SP.make(env, helper, manager)), stub


def test_the_rows_have_a_kind_a_version_and_the_out_of_date_sentence_of_the_table(env_hub):
    c, _ = env_hub
    rows = {r["name"]: r for r in c.get("/setup/api/devices").json()["devices"]}
    assert (rows["Kitchen phone"]["kind"], rows["Kitchen phone"]["version"], rows["Kitchen phone"]["out_of_date"]) == ("phone", "1.4.0", True)
    assert rows["Kitchen phone"]["advice"] == "Out of date. The app offers the update when it is opened."
    assert rows["Shop PC"]["advice"] == "Out of date (0.5.0). Install the current Slicer Sync on that PC."
    assert rows["Shop PC"]["kind"] == "pc" and rows["Shop PC"]["newest"] == "0.7.0"
    assert rows["Bench station"]["advice"] == "Out of date (0.5.0; the Hub is 0.7.0). On that machine: sudo spoolwarden update"
    assert rows["Bench station"]["kind"] == "station" and rows["Bench station"]["page"] is True
    assert rows["Tag Reader for Workshop X1"]["advice"] == "Out of date. Hold the knob for 4 seconds to update."
    assert rows["Tag Reader for Workshop X1"]["id"] == "reader-r1" and rows["Tag Reader for Workshop X1"]["kind"] == "reader"
    # a version that is not known is never out of date; a pairing without a kind is the name alone; the Hub's own is built in
    for name in ("Garage tablet", "Old phone", "Tag Reader for Garage Voron"):
        assert rows[name]["out_of_date"] is False and "version" not in rows[name] and "advice" not in rows[name], name
    assert rows["Garage tablet"]["kind"] == "web" and rows["Old phone"]["kind"] is None
    assert rows[INTAKE_DEVICE]["kind"] == "builtin" and rows[INTAKE_DEVICE]["built_in"] is True
    assert all(r["page"] is (r["kind"] == "station") for r in rows.values())


def test_a_version_that_is_not_lower_is_not_out_of_date(env_hub, monkeypatch):
    c, _ = env_hub
    new = [dict(p) for p in PAIRINGS]
    new[0]["version"], new[1]["version"], new[2]["version"] = "1.5.0", "0.7.0", "0.7.1"
    monkeypatch.setattr(device_tab, "_pairings", lambda: [dict(p) for p in new])
    rows = {r["name"]: r for r in c.get("/setup/api/devices").json()["devices"]}
    assert [rows[n]["out_of_date"] for n in ("Kitchen phone", "Shop PC", "Bench station")] == [False, False, False]


def test_the_state_keeps_its_devices_and_readers_fields(env_hub):
    c, _ = env_hub
    pairing._write("devices.json", [{"id": "d1", "name": "Kitchen phone", "hash": "0" * 64, "paired": 1.0, "last_seen": 1.0, "expires": 0, "claimed": 1.0}])
    s = c.get("/setup/api/state").json()
    assert {"id", "name", "type", "paired", "last_seen", "reachable", "built_in"} <= set(s["devices"][0]) and "kind" not in s["devices"][0]
    assert set(s["readers"]) == {"list", "error"}


def test_a_station_detail_reads_status_and_settings_and_a_phone_detail_is_the_row(env_hub):
    c, _ = env_hub
    one = c.get("/setup/api/device/d3").json()
    assert one["device"]["name"] == "Bench station" and one["status"]["tag"]["uid"] == "04A1B2"
    assert [s["id"] for s in one["settings"]] == ["beep", "voice", "volume", "lamp.weigh"]
    plain = c.get("/setup/api/device/d1").json()
    assert plain["device"]["name"] == "Kitchen phone" and "status" not in plain and "settings" not in plain
    assert c.get("/setup/api/device/nope").status_code == 404


def test_a_station_that_does_not_answer_is_a_row_marked_not_reachable_not_an_error(env_hub, monkeypatch):
    c, st = env_hub
    st.server.shutdown()
    st.server.server_close()
    one = c.get("/setup/api/device/d3")
    assert one.status_code == 200 and one.json()["device"]["reachable"] is False and "status" not in one.json()


def test_a_setting_is_saved_only_with_the_code_and_goes_to_the_station_without_it(env_hub):
    c, st = env_hub
    url = "/setup/api/device/d3/settings"
    assert c.post(url, json={"beep": False}, headers=SP.H).status_code == 403
    assert st.posts() == []
    r = SP.post(c, "device/d3/settings", {"beep": False, "volume": 40})
    assert r.status_code == 200, r.text
    assert st.posts() == [{"beep": False, "volume": 40}]
    assert {s["id"]: s["value"] for s in r.json()["settings"]}["beep"] is False
    assert SP.post(c, "device/d3/settings", {"reset": True}).status_code == 200 and st.posts()[-1] == {"reset": True}
    # what is not a setting, a row with nothing to set, and a device nobody knows
    assert SP.post(c, "device/d3/settings", {"Beep Loud": 1}).status_code == 400
    assert SP.post(c, "device/d3/settings", {"beep": {"a": 1}}).status_code == 400
    assert SP.post(c, "device/d3/settings", {}).status_code == 400
    assert SP.post(c, "device/d1/settings", {"beep": True}).status_code == 404
    assert SP.post(c, "device/zz/settings", {"beep": True}).status_code == 404
    assert len(st.posts()) == 2


# ---------------------------------------------------------------- prove-first 4: the page passed through, relative addresses only
def test_the_stations_page_passes_through_under_the_hubs_address_and_the_lock_stays_on_the_hubs_side(env_hub):
    c, st = env_hub
    page = c.get("/setup/device/d3/")                                   # looking needs nothing
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html") and "static/page.js" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"] and page.headers["x-content-type-options"] == "nosniff"
    assert not re.search(r"""(?:src|href|action)=['"]?(?:/|https?:)""", page.text)    # the stub's page really is relative
    assert c.get("/setup/device/d3/static/page.js").text == SCRIPT
    assert c.get("/setup/device/d3/static/page.css").headers["content-type"].startswith("text/css")
    assert c.get("/setup/device/d3/state").json()["tag"]["uid"] == "04A1B2"
    assert c.get("/setup/device/d3/photo.jpg?t=12").content.startswith(b"\xff\xd8")
    assert ("GET", "/photo.jpg?t=12", None) in st.calls
    assert c.get("/setup/device/d3", follow_redirects=False).headers["location"] == "/setup/device/d3/"
    # saving needs the page unlocked: no code is a refusal and nothing reaches the station; the code never does
    assert c.post("/setup/device/d3/settings", json={"beep": False}, headers=SP.H).status_code == 403
    assert st.posts() == []
    ok = c.post("/setup/device/d3/settings", json={"beep": False, "code": CODE}, headers=SP.H)
    assert ok.status_code == 200 and st.posts() == [{"beep": False}]
    # the way out of the station's own files, other devices, other methods
    for bad in ("/setup/device/d3/../state", "/setup/device/d3/static/%2e%2e/state", "/setup/device/d3//state"):
        assert c.get(bad).status_code in (400, 404, 307, 308), bad
    assert c.get("/setup/device/d1/").status_code == 404 and c.get("/setup/device/nope/").status_code == 404
    assert c.put("/setup/device/d3/settings", json={}, headers=SP.H).status_code == 405
    away = SP.client(c.app, who=SP.AWAY)
    assert away.get("/setup/device/d3/").status_code == 403


@browser
def test_a_page_with_relative_addresses_works_in_a_browser_under_the_hubs_address(stub, hub_change, tmp_path):
    _station_url(stub)
    base = hub_change.rsplit("/setup", 1)[0]
    page = _page_drive(f"{base}/setup/device/d3/", tmp_path, """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 100 && document.getElementById("settings").textContent === ""; i++) await sleep(100);
const seen = performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname);
const locked = await window.save({ beep: false });
const open = await (await fetch("/setup/api/device/d3/settings", { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ beep: false, code: "__CODE__" }) })).json();
return { out: document.getElementById("out").textContent, settings: document.getElementById("settings").textContent,
  colour: getComputedStyle(document.getElementById("out")).color, seen, path: location.pathname, locked: locked[0],
  open: open.settings.map((s) => s.id) };
""")
    assert page["path"] == "/setup/device/d3/" and page["out"] == "tag 04A1B2" and page["settings"] == "beep,voice,volume,lamp.weigh"
    assert page["colour"] == "rgb(1, 2, 3)"                                  # the stylesheet came through
    assert {"/setup/device/d3/static/page.js", "/setup/device/d3/static/page.css", "/setup/device/d3/state",
            "/setup/device/d3/settings"} <= set(page["seen"]), page["seen"]
    assert page["locked"] == 403 and page["open"] == ["beep", "voice", "volume", "lamp.weigh"]
    assert all(p.startswith("/setup/device/d3/") for p in page["seen"] if "api" not in p and "d3" in p)
