"""The Devices section's kind, version, out of date and Open, a device's detail the Hub page draws itself with the station's
settings, and "Open this station's page" (R83 section 9, 10.2 and the rulings of 2026-11-17 21:18 and 21:22;
setup_console/device_tab.py). Nothing a station sends is served by the Hub: the checks on what it takes are pinned here.

The Hub's other parts (a pairing's kind and version, the reader's build, the station's own routes and its pinned client) are
not in the tree yet: a stub Hub lends the rows their kind and version, and a stub station (a thread with the ruled routes
of 10.4 and /ticket) stands in for the station. The registry that mounts the routes is not this step's either: the tests mount them.
The same skip rules as test_hub_devices.py (no Node 22 or no browser is a skip, a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import config, pairing, setup_console
from filament_kit.setup_console import device_tab
from filament_kit.web.slots import INTAKE_DEVICE

from test_hub_devices import DEVICES_PRELUDE, _T
from test_hub_page_audit import CODE, hub_app, hub_change  # noqa: F401
from test_setup_page import env, helper, manager  # noqa: F401
import test_setup_page as SP

browser = pytest.mark.browser_audit      # tools/testenv runs the browser tests as a group of 2 workers

# ---------------------------------------------------------------- the stubs
JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
                        "wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")
SETTINGS = [{"id": "beep", "label": "Beep", "kind": "switch", "value": True},
            {"id": "voice", "label": "Voice", "kind": "choice", "value": "piper", "choices": ["piper", {"value": "espeak", "label": "espeak-ng"}]},
            {"id": "volume", "label": "Volume", "kind": "number", "value": 60, "min": 0, "max": 100},
            {"id": "lamp.weigh", "label": "Lamp for weighing", "kind": "choice", "value": "yellow", "choices": ["yellow", "red", "off"]}]
STATE = {"tag": {"uid": "04A1B2"}, "scale": None, "last_weight": {"grams": 612.5}, "panel": "v1.2", "version": "0.7.0",
         "settings_changed": False, "photo": True}
TICKET = "t" * 32


class Station:
    """A station's own listener with the routes of 10.4 and /ticket. `fault` makes one route misbehave: {path: what}."""

    def __init__(self):
        self.calls, self.settings, self.fault = [], json.loads(json.dumps(SETTINGS)), {}
        me = self

        class H(BaseHTTPRequestHandler):
            def _send(self, status, body, kind, extra=()):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, path, obj):
                what = me.fault.get(path)
                if what == "html":
                    return self._send(200, json.dumps(obj).encode(), "text/html")
                if what == "text":
                    return self._send(200, b"not json at all", "application/json")
                if what == "big":
                    return self._send(200, json.dumps({"pad": "x" * (300 * 1024)}).encode(), "application/json")
                if what == "redirect":
                    return self._send(302, b"", "text/plain", [("Location", "http://127.0.0.1:9/elsewhere")])
                if what == "list":
                    return self._send(200, b"[1, 2]", "application/json")
                if callable(what):
                    obj = what(obj)
                self._send(200, json.dumps(obj).encode(), "application/json")

            def do_GET(self):
                me.calls.append(("GET", self.path, None))
                if self.path == "/state":
                    return self._json("state", STATE)
                if self.path == "/settings":
                    return self._json("settings", {"settings": me.settings})
                if self.path == "/photo":
                    what = me.fault.get("photo")
                    if what == "png":
                        return self._send(200, JPEG, "image/png")
                    if what == "html":
                        return self._send(200, b"<script>1</script>", "image/jpeg")
                    if what == "big":
                        return self._send(200, b"\xff\xd8" + b"0" * (4 * 1024 * 1024), "image/jpeg")
                    return self._send(200, JPEG, "image/jpeg")
                self._send(404, b'{"error": "no such page"}', "application/json")

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                me.calls.append(("POST", self.path, json.loads(raw or b"{}")))
                if self.path == "/ticket":
                    return self._json("ticket", {"ticket": TICKET, "expires_in": 60})
                if self.path != "/settings":
                    return self._send(404, b'{"error": "no such page"}', "application/json")
                got = json.loads(raw)
                if got.get("reset"):
                    me.settings = json.loads(json.dumps(SETTINGS))
                else:
                    for s in me.settings:
                        if s["id"] in got:
                            s["value"] = got[s["id"]]
                self._json("post", {"settings": me.settings})

            def log_message(self, *a):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def posts(self):
        return [c[2] for c in self.calls if c[0] == "POST" and c[1] == "/settings"]


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
    """The Hub the Devices rows are built on, as the other Hub steps will leave it, and a station (over http: the stub has no
    certificate, so the https-only rule of Open this station's page is lifted here and tested on its own)."""
    st = Station()
    monkeypatch.setattr(device_tab, "_pairings", lambda: [dict(p) for p in PAIRINGS])
    monkeypatch.setattr(device_tab, "_readers", lambda: [dict(r) for r in READERS])
    monkeypatch.setattr(device_tab, "_phone_offer", lambda: "1.5.0")
    monkeypatch.setattr(device_tab, "_reader_offer", lambda: "7")
    monkeypatch.setattr(device_tab, "__version__", "0.7.0")
    monkeypatch.setattr(device_tab, "OPEN_SCHEMES", ("http", "https"))
    # the mounting EV5 does: the page routes (there is no pass-through route any more)
    orig_console = setup_console.routes
    monkeypatch.setattr(setup_console, "routes", lambda page: orig_console(page) + device_tab.routes(page))
    return st


def _station_url(st):
    cfg = config.load()
    cfg["station"] = {**cfg["station"], "url": st.url}
    config.save(cfg)


@pytest.fixture
def env_hub(env, helper, manager, stub):
    _station_url(stub)
    return SP.client(SP.make(env, helper, manager)), stub


# ---------------------------------------------------------------- the routes
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


def test_a_station_detail_reads_status_settings_and_its_own_address_and_a_phone_detail_is_the_row(env_hub, stub):
    c, _ = env_hub
    one = c.get("/setup/api/device/d3").json()
    assert one["device"]["name"] == "Bench station" and one["status"]["tag"]["uid"] == "04A1B2" and one["photo"] is True
    assert [s["id"] for s in one["settings"]] == ["beep", "voice", "volume", "lamp.weigh"] and "settings_dropped" not in one
    assert one["own_page"] == stub.url + "/"
    plain = c.get("/setup/api/device/d1").json()
    assert plain["device"]["name"] == "Kitchen phone" and plain["photo"] is False
    assert not ({"status", "settings", "own_page"} & set(plain))
    assert c.get("/setup/api/device/nope").status_code == 404


def test_a_station_that_does_not_answer_is_a_row_marked_not_reachable_not_an_error(env_hub):
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


def test_no_route_serves_a_stations_page(env_hub):
    c, _ = env_hub
    for path in ("/setup/device/d3/", "/setup/device/d3", "/setup/device/d3/static/page.js", "/setup/device/d3/state"):
        assert c.get(path, follow_redirects=False).status_code == 404, path
    assert not hasattr(device_tab, "passthrough_routes")


# ---------------------------------------------------------------- what the Hub takes from a station is checked data
@pytest.mark.parametrize("fault,why", [("html", "JSON"), ("text", "valid"), ("big", "too large"), ("redirect", "redirect"), ("list", "valid")])
def test_a_station_answer_that_is_not_checked_data_is_an_error_not_a_detail(env_hub, fault, why):
    c, st = env_hub
    st.fault["state"] = fault
    one = c.get("/setup/api/device/d3")
    assert one.status_code == 200 and one.json()["device"]["reachable"] is False and "status" not in one.json()      # as unreachable
    st.fault.clear()
    st.fault["settings"] = fault
    two = c.get("/setup/api/device/d3").json()
    assert two["device"]["reachable"] is False and "settings" not in two
    st.fault.clear()
    st.fault["post"] = fault
    r = SP.post(c, "device/d3/settings", {"beep": False})
    assert r.status_code == 502 and why in r.json()["error"], r.text


def test_a_redirect_is_never_followed(env_hub):
    c, st = env_hub
    st.fault["state"] = "redirect"
    c.get("/setup/api/device/d3")
    assert all(call[1] != "/elsewhere" for call in st.calls)


def test_settings_that_fail_the_checks_are_dropped_and_the_detail_says_so(env_hub, monkeypatch):
    c, st = env_hub
    good = {"id": "ok.one", "label": "Fine", "kind": "text", "value": "x"}
    bad = [{"id": "Bad Id", "label": "x", "kind": "text", "value": "x"}, {"id": "a" * 41, "label": "x", "kind": "text", "value": "x"},
           {"id": "kind", "label": "x", "kind": "slider", "value": 1}, {"id": "long", "label": "x" * 81, "kind": "text", "value": "x"},
           {"id": "nolabel", "kind": "text", "value": "x"}, {"id": "badval", "label": "x", "kind": "switch", "value": "yes"},
           {"id": "ok.one", "label": "Twice", "kind": "text", "value": "y"}, "text", None]
    for extra in bad:
        st.settings = [good] + [extra]
        one = c.get("/setup/api/device/d3").json()
        assert [s["id"] for s in one["settings"]] == ["ok.one"] and one["settings_dropped"] is True, extra
    st.settings = [{"id": f"s{i}", "label": "x", "kind": "text", "value": "x"} for i in range(61)]
    one = c.get("/setup/api/device/d3").json()
    assert len(one["settings"]) == 60 and one["settings_dropped"] is True
    st.settings = [{"id": f"s{i}", "label": "x", "kind": "text", "value": "x"} for i in range(60)]
    assert "settings_dropped" not in c.get("/setup/api/device/d3").json()
    st.settings = json.loads(json.dumps(SETTINGS))
    r = SP.post(c, "device/d3/settings", {"beep": True})
    assert r.status_code == 200 and "settings_dropped" not in r.json()
    st.settings = [good, bad[0]]
    assert SP.post(c, "device/d3/settings", {"ok.one": "z"}).json()["settings_dropped"] is True


def test_the_photo_is_a_jpeg_of_at_most_four_mib_or_nothing(env_hub):
    c, st = env_hub
    ok = c.get("/setup/api/device/d3/photo")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg" and ok.content == JPEG
    assert ok.headers["x-content-type-options"] == "nosniff" and ok.headers["content-security-policy"] == "default-src 'none'"
    for fault in ("png", "html", "big"):
        st.fault["photo"] = fault
        assert c.get("/setup/api/device/d3/photo").status_code == 502, fault
    assert c.get("/setup/api/device/d1/photo").status_code == 404 and c.get("/setup/api/device/zz/photo").status_code == 404


# ---------------------------------------------------------------- Open this station's page
def test_open_gives_the_address_with_the_ticket_in_the_fragment_and_only_when_unlocked(env_hub, stub, caplog):
    c, st = env_hub
    assert c.post("/setup/api/device/d3/open", json={}, headers=SP.H).status_code == 403
    assert not [x for x in st.calls if x[1] == "/ticket"]
    with caplog.at_level("DEBUG"):
        r = SP.post(c, "device/d3/open")
    assert r.status_code == 200, r.text
    assert r.json() == {"address": f"{stub.url}/#ticket={TICKET}"} and "?" not in r.json()["address"]
    assert [x for x in st.calls if x[1] == "/ticket"] == [("POST", "/ticket", {})]
    assert TICKET not in caplog.text and TICKET not in str(c.get("/setup/api/device/d3").json())
    assert SP.post(c, "device/d1/open").status_code == 404 and SP.post(c, "device/zz/open").status_code == 404


@pytest.mark.parametrize("answer", [{"ticket": TICKET}, {"ticket": TICKET, "expires_in": 61}, {"ticket": TICKET, "expires_in": True},
                                    {"expires_in": 60}, {"ticket": "short", "expires_in": 60}, {"ticket": "a b" * 12, "expires_in": 60},
                                    {"ticket": 12345678901234567890, "expires_in": 60}])
def test_a_ticket_answer_that_is_not_right_is_a_clear_error(env_hub, answer):
    c, st = env_hub
    st.fault["ticket"] = lambda obj: answer
    r = SP.post(c, "device/d3/open")
    assert r.status_code == 502 and "ticket is not valid" in r.json()["error"]


@pytest.mark.parametrize("fault", ["html", "text", "big", "redirect", "list"])
def test_a_ticket_from_a_station_that_sends_anything_but_json_is_refused(env_hub, fault):
    c, st = env_hub
    st.fault["ticket"] = fault
    assert SP.post(c, "device/d3/open").status_code == 502


def test_the_station_page_is_opened_over_https_only(env_hub, monkeypatch):
    c, st = env_hub
    monkeypatch.setattr(device_tab, "OPEN_SCHEMES", ("https",))
    r = SP.post(c, "device/d3/open")
    assert r.status_code == 409 and "https" in r.json()["error"]
    assert not [x for x in st.calls if x[1] == "/ticket"]               # no ticket is asked for


def test_an_address_of_a_foreign_origin_is_refused(env_hub, monkeypatch):
    c, st = env_hub
    monkeypatch.setattr(device_tab, "own_page", lambda url: "http://evil.example/")
    r = SP.post(c, "device/d3/open")
    assert r.status_code == 502 and "ticket is not valid" in r.json()["error"]


def test_the_web_apps_home_address_drops_the_port_on_443(env_hub):
    c, _ = env_hub
    cfg = config.load()
    assert c.get("/setup/api/webapp").json()["url"].endswith(".local:8710/intake")
    cfg["port"] = 443
    config.save(cfg)
    assert c.get("/setup/api/webapp").json()["url"].endswith(".local/intake")


# ---------------------------------------------------------------- the page: rows, Open, detail, settings, in the four looks
def _drive(url: str, tmp_path, script: str, width: int, look: str) -> dict:
    import subprocess
    from test_hub_devices import DRIVER, _missing, _node
    node = _node()
    if not node:
        _missing("the page driver needs Node 22 or later")
    (tmp_path / "drive.js").write_text(script.replace("__CODE__", CODE), encoding="utf-8")
    (tmp_path / "init.js").write_text(f'try {{ localStorage.setItem("spoolwarden.look", "{look}"); }} catch (e) {{}}', encoding="utf-8")
    run = subprocess.run([node, str(DRIVER), "--url", url, "--script", str(tmp_path / "drive.js"), "--width", str(width),
                          "--init", str(tmp_path / "init.js")], capture_output=True, encoding="utf-8", timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the page driver needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("page driver: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


EVIL = 'Beep <img src=x onerror="window.__x=1">'
ROWS_SCRIPT = DEVICES_PRELUDE + """
unlock();
await until(() => $$(".coll--paired .coll__item").length >= 8 && !$("[aria-busy=true]:not(button)"), "the rows with their kinds");
const row = (n) => $$(".coll--paired .coll__item").find((i) => text($(".devices__name", i)) === n);
const names = $$(".coll--paired .coll__item").map((i) => text($(".devices__name", i)));
const overflow = () => { const b = $("dialog[open] .dialog__body"); return { page: document.documentElement.scrollWidth - innerWidth,
  table: $(".coll--paired") ? $(".coll--paired").scrollWidth - $(".coll--paired").clientWidth : 0, dialog: b ? b.scrollWidth - b.clientWidth : 0 }; };
const info = (n) => { const i = row(n); return { subs: $$(".coll__sub", i).map(text), actions: $$(".actions > *", i).map((e) => e.tagName.toLowerCase() + ":" + e.dataset.action),
  name: Math.round($(".coll__cell[data-col=title]", i).getBoundingClientRect().width), cut: $$(".actions .btn", i).some((b) => b.getBoundingClientRect().right > $(".coll--paired").getBoundingClientRect().right + 1) }; };
out.rows = Object.fromEntries(names.map((n) => [n, info(n)]));
out.label = $('[data-action="open"]', row("Bench station")).getAttribute("aria-label");
const clicked = [], realClick = HTMLAnchorElement.prototype.click;      // a new tab is recorded, not opened
HTMLAnchorElement.prototype.click = function () { if (this.target === "_blank") { clicked.push([this.href, this.target, this.rel]); return; } return realClick.call(this); };
out.overflowRows = overflow();
// Open on a row that serves nothing: its detail in a dialog
$('[data-action="open"]', row("Kitchen phone")).click();
await until(() => dlg() && $$(".kv__row", dlg()).length, "the phone's detail");
out.phone = { title: text($(".dialog__title", dlg())), facts: $$(".kv__row", dlg()).map(text), banner: text($(".banner", dlg())), hash: location.hash,
  link: !!$('[data-action="open-station-page"]', dlg()) };
out.overflowPhone = overflow();
$('.dialog__foot [data-action="confirm"]').click();
await until(closed, "Close");
out.hashClosed = location.hash;
// a Tag Reader's detail points to Flash a device
$('[data-action="open"]', row("Tag Reader for Workshop X1")).click();
await until(() => dlg() && $$(".kv__row", dlg()).length, "the reader's detail");
out.reader = { stationLink: !!$('[data-action="open-station-page"]', dlg()), facts: $$(".kv__row", dlg()).map(text), line: text($(".dialog__body > .devdetail > p", dlg())), link: $('a[href="#flash"]', dlg()).textContent };
$('a[href="#flash"]', dlg()).click();
await until(() => closed() && location.hash === "#flash", "the link to Flash a device");
location.hash = "#devices";
await until(() => $$(".coll--paired .coll__item").length >= 8, "the section again");
// a Weigh Station's settings: change three, preview, cancel, then the lock, then save
$('[data-action="open"]', row("Bench station")).click();
await until(() => dlg() && $("form.group", dlg()), "the station's detail");
await sleep(400);
out.station = { hash: location.hash, facts: $$(".kv__row", dlg()).map(text), fields: $$(".field__label", dlg()).map(text), overflow: overflow(),
  ownPage: text($(".devdetail__page .mono", dlg())), hint: text($(".devdetail__page .muted", dlg())), button: text($('[data-action="open-station-page"]', dlg())),
  photo: (() => { const i = $("img", dlg()); return i ? [i.getAttribute("src").replace(/\?t=\d+/, ""), i.alt, i.naturalWidth] : null; })(),
  injected: [!!$("img[src=x]", dlg()), window.__x === undefined, !!$$(".field__label", dlg()).find((l) => l.textContent.includes("<img"))] };
$('[data-action="open-station-page"]', dlg()).click();
await until(() => clicked.length === 1 && sentTo("device/d3/open").length === 1, "the station's page to be opened");
out.openSent = sentTo("device/d3/open");
out.clicked = clicked;
const form = () => $("form.group", dlg());
const set = (name, value) => { const c = form().elements[name]; c.value = value; c.dispatchEvent(new Event("input", { bubbles: true })); c.dispatchEvent(new Event("change", { bubbles: true })); };
set("beep", "off"); set("volume", "40"); set("lamp.weigh", "red");
const save = () => $('[type="submit"]', form()).click();
const open2 = () => $$("dialog[open]")[1];
save();
await until(() => $$("dialog[open]").length === 2 && /Save these settings/.test(text(open2())), "the preview");
out.preview = $$("li", open2()).map(text);
open2().querySelector('[data-action="cancel"]').click();
await until(() => $$("dialog[open]").length === 1, "Cancel of the preview");
out.afterCancel = { sent: sentTo("device/d3/settings").length, dirty: form().dataset.state };
save();
await until(() => $$("dialog[open]").length === 2, "the preview again");
open2().querySelector('[data-action="confirm"]').click();
await until(() => sentTo("device/d3/settings").length === 1, "the save to be sent");
out.sent = sentTo("device/d3/settings");
await until(() => text($(".group__foot .result", form())), "the result");
out.saved = text($(".group__foot .result", form()));
out.values = ["beep", "volume", "lamp.weigh"].map((n) => form().elements[n].value);
// back to the installed values
$('[data-action="reset"]', form()).click();
await until(() => $$("dialog[open]").length === 2, "the question");
open2().querySelector('[data-action="confirm"]').click();
await until(() => sentTo("device/d3/settings").length === 2, "the reset to be sent");
await until(() => form() && form().elements["beep"].value === "on", "the form drawn again");
out.reset = { sent: sentTo("device/d3/settings")[1], values: ["beep", "volume", "lamp.weigh"].map((n) => form().elements[n].value) };
out.overflowEnd = overflow();
// locked: the preview, then the unlock dialog asks, and nothing is sent
SW.setLock("locked");
set("beep", "off");
save();
await until(() => $$("dialog[open]").length === 2 && /Save these settings/.test(text(open2())), "the preview while locked");
open2().querySelector('[data-action="confirm"]').click();
await until(() => $$("dialog[open]").length === 2 && !/Save these settings/.test(text(open2())), "the unlock dialog");
await sleep(300);
out.locked = { sent: sentTo("device/d3/settings").length, state: SW.lock.state };
return out;
"""


@browser
@pytest.mark.parametrize("look,width", [(lk, w) for lk in ("console", "workbench", "palette", "panes") for w in (1280, 390)])
def test_the_rows_open_and_the_station_settings_work_in_every_look_at_both_widths(stub, hub_change, tmp_path, look, width):
    _station_url(stub)
    stub.settings[0]["label"] = EVIL
    pairing._write("devices.json", [{"id": p["id"], "name": p["name"], "hash": "0" * 64, "paired": 1.0, "last_seen": 1.0, "expires": 0, "claimed": 1.0,
                                     **({"scope": "station"} if p["type"] == "station" else {})} for p in PAIRINGS])
    page = _drive(hub_change + "#devices", tmp_path, ROWS_SCRIPT, width, look)
    rows = page["rows"]
    # the kind and version line, the out-of-date sentence, "Version not known", the name alone
    assert rows["Kitchen phone"]["subs"] == ["Phone · Version 1.4.0", "Out of date. The app offers the update when it is opened."]
    assert rows["Shop PC"]["subs"] == ["Slicer Sync PC · Version 0.5.0", "Out of date (0.5.0). Install the current Slicer Sync on that PC."]
    assert rows["Bench station"]["subs"] == ["Weigh Station · Version 0.5.0",
                                             "Out of date (0.5.0; the Hub is 0.7.0). On that machine: sudo spoolwarden update"]
    assert rows["Garage tablet"]["subs"] == ["Web app · Version not known"]
    assert rows["Old phone"]["subs"] == []
    assert rows["Tag Reader for Workshop X1"]["subs"] == ["Tag Reader · Version 5", "Out of date. Hold the knob for 4 seconds to update."]
    assert rows["Tag Reader for Garage Voron"]["subs"] == ["Tag Reader · Version not known"]
    assert rows[INTAKE_DEVICE]["subs"][0] == _T("devices_built_in_line")
    # Open: a link to the pass-through for a station, a button for the rest; Unpair only where a pairing can be undone
    assert rows["Bench station"]["actions"] == ["button:open", "button:unpair"]
    assert rows["Kitchen phone"]["actions"] == ["button:open", "button:unpair"]
    assert rows["Tag Reader for Workshop X1"]["actions"] == ["button:open"] and rows[INTAKE_DEVICE]["actions"] == ["button:open"]
    assert page["label"] == "Open Bench station"
    assert page["phone"]["hash"] == "#devices/d1" and page["hashClosed"] == "#devices"
    assert page["phone"]["link"] is False and page["reader"]["stationLink"] is False        # nothing serves a page: no link
    st = page["station"]
    assert st["hash"] == "#devices/d3" and st["ownPage"] == f"Its own page: {stub.url}/" and st["button"] == "Open this station's page"
    assert st["hint"] == "Your browser asks once whether to trust this station's certificate."
    assert st["photo"] == ["/setup/api/device/d3/photo", "The last photo of the Weigh Station", 1]
    assert st["injected"] == [False, True, True]                                      # a station's text is text, never markup
    assert page["openSent"] == [{"code": CODE}] and page["clicked"] == [[f"{stub.url}/#ticket={TICKET}", "_blank", "noopener noreferrer"]]
    assert all(not r["cut"] and r["name"] >= 120 for r in rows.values()), rows
    assert max(page["overflowRows"].values()) <= 1 and page["overflowPhone"]["dialog"] <= 1 and page["overflowEnd"]["page"] <= 1
    # the details
    assert page["phone"]["title"] == "Kitchen phone" and len(page["phone"]["facts"]) == 4
    assert page["phone"]["facts"][:2] == ["KindPhone", "Version1.4.0"]
    assert "Out of date. The app offers the update" in page["phone"]["banner"]
    assert page["reader"]["facts"][:2] == ["KindTag Reader", "Build5"] and page["reader"]["line"] == "Its settings are changed in Flash a device."
    assert page["reader"]["link"] == _T("nav_flash_device")
    assert "Version0.5.0" in page["station"]["facts"] and "Tag{\"uid\": \"04A1B2\"}" not in page["station"]["facts"]
    assert page["station"]["fields"] == [EVIL, "Voice", "Volume", "Lamp for weighing"]
    assert page["station"]["overflow"]["dialog"] <= 1
    # the settings: a preview first, cancelling sends nothing, the lock asks, then the station gets only what changed
    assert page["preview"] == [f"{EVIL}: On to Off", "Volume: 60 to 40", "Lamp for weighing: yellow to red"]
    assert page["afterCancel"] == {"sent": 0, "dirty": "dirty"} and page["locked"] == {"sent": 2, "state": "locked"}
    assert page["sent"] == [{"beep": False, "volume": 40, "lamp.weigh": "red", "code": CODE}]
    assert page["values"] == ["off", "40", "red"] and page["saved"]
    assert page["reset"] == {"sent": {"reset": True, "code": CODE}, "values": ["on", "60", "yellow"]}
    assert stub.posts() == [{"beep": False, "volume": 40, "lamp.weigh": "red"}, {"reset": True}]


def test_the_web_apps_home_address_drops_the_port_on_443(env_hub):
    c, _ = env_hub
    cfg = config.load()
    assert c.get("/setup/api/webapp").json()["url"].endswith(".local:8710/intake")
    cfg["port"] = 443
    config.save(cfg)
    assert c.get("/setup/api/webapp").json()["url"].endswith(".local/intake")
