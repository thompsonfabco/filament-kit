"""The live printer view of the Hub page (R83 sections 2 and 3, the 20:58 ruling point 3): setup_console/printer_live_tab.py (the page's
routes, against a stub Hub: no printer, no Spoolman) and setup_static/setup_printer_live.js and .css (a real headless browser, the Hub
page's own scripts and styles, the view mounted by the test because the printer detail does not call it yet; the page routes it asks are
a stub in the page, the Hub's own are tested here in Python). The same skip rules as the page audit: no Node 22 or no browser is a skip
(a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from filament_kit import config, modules, setup_page, trusted
from filament_kit.bridge import camera, family, loading, mapping, pending, registry, usage
from filament_kit.bridge.connection import NoReply, PrinterOffline
from filament_kit.setup_console import printer_live_tab
from filament_kit.setup_console.printer_live_tab import Tickets
from filament_kit.spoolman import Spoolman

from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import ROOT, T, _drive, hub  # noqa: F401
from test_setup_page import BASE, CODE, H, HOME, HOSTNAME, env, helper  # noqa: F401
from test_setup_trusted import AGENT

STATIC = ROOT / "server" / "filament_kit" / "setup_static"
JS = STATIC / "setup_printer_live.js"
CSS = STATIC / "setup_printer_live.css"
SERIAL = "00M00A000000001"
OTHER = "00M00A000000002"
KSERIAL = "klipper-garage"


# ======================================================================================================== the page routes, on a stub Hub

class StubPrinters:
    """The printer families as the page routes see them: what a family answers, and what it was asked."""

    def __init__(self):
        self.asked, self.cmd_reply, self.states = [], {"ok": True, "reply": {"result": "success"}}, {}
        self.klipper = StubKlipper()
        self.synced = 0

    def sync(self):
        self.synced += 1

    def state(self, pid):
        return self.states.get(pid, "connected")

    def summary(self, pid):
        return {"gcode_state": "RUNNING", "percent": 42, "remaining_min": 75, "job": "benchy.3mf"}

    def status(self, pid):
        if pid == KSERIAL:
            return self.klipper.status(pid)
        return {"gcode_state": "RUNNING", "job": "benchy.3mf", "percent": 42, "light": "on",
                "ams": [{"unit": 0, "label": "AMS 1", "slots": [{"label": "A1", "spool": {"id": 7}}, {"label": "A2", "spool": None}]}]}

    def command(self, pid, action):
        self.asked.append(("command", pid, action))
        if isinstance(self.cmd_reply, Exception):
            raise self.cmd_reply
        return self.cmd_reply


class StubKlipper:
    def __init__(self):
        self.asked, self.light = [], False

    def status(self, pid):
        return {"gcode_state": "IDLE", "ams": [], "light": None}

    def model(self, pid):
        return (type("M", (), {"light_on": "SET_LED" if self.light else ""})(),)

    def camera_kind(self, pid):
        return "mjpeg"

    def load(self, sm, pid, label, spool_id, dry, *, sealed_location):
        self.asked.append(("load", pid, label, spool_id, dry))
        return {"dry_run": dry, "confirmed": None if dry else True, "moved_back": []}

    def unload(self, sm, pid, label, dry, *, sealed_location):
        self.asked.append(("unload", pid, label, dry))
        return {"spool": {"id": 3}, "moved_back": [{"id": 3, "location": "Rack 1"}], "dry_run": dry}

    def clear(self, sm, pid, label, dry, *, sealed_location):
        self.asked.append(("clear", pid, label, dry))
        return {"slot": label, "spool": None, "moved_back": None, "waiting_ended": False, "printer_cleared": not dry, "dry_run": dry}

    def usage(self, pid, days):
        return [{"id": "k-1", "at": "2026-11-17T10:00:00+00:00", "job": "x", "grams": 5, "spool_id": None, "slot": "T0", "observe": False, "undone": False}]


class StubSrc:
    """A camera source with one picture; it ends at once, so a test's request returns."""
    dir = None
    cert_changed = False

    def frame(self):
        return 1, b"jpeg"

    def alive(self):
        return False


class StubCameraHub:
    def __init__(self, tmp_path):
        self.stopping, self.acquired, self.released = threading.Event(), [], []
        self.src = StubSrc()
        self.src.dir = tmp_path
        (tmp_path / "index.m3u8").write_text("#EXTM3U\n", encoding="utf-8")

    def acquire(self, serial, kind=None):
        self.acquired.append((serial, kind))
        return self.src

    def release(self, serial):
        self.released.append(serial)

    def touch_hls(self, serial):
        self.acquired.append((serial, "hls"))
        return self.src


@pytest.fixture
def stub(env, helper, tmp_path, monkeypatch):  # noqa: F811
    """The page and its printer routes on a stub Hub: the real setup page (its guard, its lock and the real helper's code check), the
    page's routes plus the live view's, the bridge calls recorded."""
    cfg = config.load()
    cfg["modules"].update(printers=True, klipper=True)
    config.save(cfg)
    registry.upsert(registry.Printer(SERIAL, "Workshop X1", "X1C", "192.0.2.40", "12345678", True))
    registry.upsert(registry.Printer(OTHER, "Second X1", "X1C", "192.0.2.41", "12345678", True))
    k = registry.add_klipper("Garage Voron", "voron.example.com", 7125)
    printers = StubPrinters()
    page = setup_page.SetupPage(printers, families={"bambu", "klipper"}, helper=helper, hosts=lambda: {HOSTNAME}, mapper=type("M", (), {"in_progress": lambda self, s: False})())
    cam = StubCameraHub(tmp_path)
    seen: list = []
    monkeypatch.setattr(pending, "load_or_wait", lambda m, sm, serial, label, spool_id, dry, **kw: seen.append(("load", serial, label, spool_id, dry)) or
                        {"dry_run": dry, "confirmed": None, "moved_back": [], **({} if dry else {"pending": True})})
    monkeypatch.setattr(pending, "unload", lambda m, sm, serial, label, dry, **kw: seen.append(("unload", serial, label, dry)) or
                        {"spool": {"id": 7, "location": "Rack 1"}, "moved_back": [{"id": 7, "location": "Rack 1"}], "dry_run": dry, "waiting_ended": True})
    monkeypatch.setattr(pending, "clear_slot", lambda m, sm, serial, label, dry, **kw: seen.append(("clear", serial, label, dry)) or
                        {"slot": label, "spool": None, "moved_back": None, "waiting_ended": True, "printer_cleared": False, "dry_run": dry})
    monkeypatch.setattr(usage, "entries", lambda serial, days: [{"id": "e1", "at": "2026-11-17T10:00:00+00:00", "job": "benchy", "grams": 12.5, "spool_id": 7,
                                                                  "slot": "A1", "observe": False, "undone": False, "days": days}])
    monkeypatch.setattr(printer_live_tab.inventory, "with_spools", lambda entries, sm: [{**e, "spool": {"id": 7, "name": "PLA"}} for e in entries])
    monkeypatch.setattr(usage, "undo", lambda entry_id, sm: seen.append(("undo", entry_id)) or {"id": entry_id, "undone": True})
    monkeypatch.setattr(printer_live_tab.storage, "current", lambda: type("S", (), {"sealed_location": lambda self: type("L", (), {"name": "Sealed stock"})()})())
    monkeypatch.setattr(pending.STORE, "waiting_for", lambda serial: {"A2": 9} if serial == SERIAL else {})
    mine = printer_live_tab.routes(page, sm=Spoolman("http://127.0.0.1:9"), camera_hub=cam)
    app = Starlette(routes=page.routes() + [Route("/setup/api" + p, fn, methods=[m]) for p, fn, m in mine])
    c = TestClient(app, base_url=BASE, client=HOME)
    return type("Stub", (), {"c": c, "printers": printers, "seen": seen, "cam": cam, "page": page, "app": app, "k": k.serial})()


def post(c, path, body=None, code=CODE):
    return c.post("/setup/api/" + path, json={**(body or {}), **({"code": code} if code is not None else {})}, headers=H)


def get(c, path):
    return c.get("/setup/api/" + path)


def test_live_is_open_and_gives_the_summary_the_status_the_slots_with_what_waits_and_what_the_printer_can_do(stub):
    r = get(stub.c, f"printers/{SERIAL}/live")        # no code: looking is open
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["state"] == "connected" and d["family"] == "bambu" and d["name"] == "Workshop X1"
    assert d["summary"]["percent"] == 42 and d["status"]["job"] == "benchy.3mf"
    slots = {s["label"]: s for s in d["status"]["ams"][0]["slots"]}
    assert "pending" not in slots["A1"] and slots["A2"]["pending"]["spool_id"] == 9 and "A2" in slots["A2"]["pending"]["text"]
    assert d["camera"] == {"kind": "hls"} and d["controls"] == {"light": True}      # an X1C relays RTSPS as HLS; the report has a light
    k = get(stub.c, f"printers/{stub.k}/live").json()
    assert k["family"] == "klipper" and k["controls"] == {"light": False}               # no light gcode: the page shows no light control
    stub.printers.klipper.light = True
    assert get(stub.c, f"printers/{stub.k}/live").json()["controls"] == {"light": True}
    assert get(stub.c, "printers/00M00A00000FFFF/live").status_code == 404


def test_a_command_needs_the_code_and_stop_needs_confirm_and_a_refusal_keeps_the_printers_words(stub):
    p = f"printers/{SERIAL}/command"
    assert post(stub.c, p, {"action": "pause"}, code=None).status_code == 403 and stub.printers.asked == []
    assert post(stub.c, p, {"action": "pause"}, code="00000000").status_code == 403 and stub.printers.asked == []
    assert post(stub.c, p, {"action": "dance"}).status_code == 400
    r = post(stub.c, p, {"action": "stop"})                                       # asked first: no confirm, no stop
    assert r.status_code == 400 and r.json()["field"] == "confirm" and stub.printers.asked == []
    assert post(stub.c, p, {"action": "stop", "confirm": "yes"}).status_code == 400
    r = post(stub.c, p, {"action": "pause"})
    assert r.status_code == 200 and r.json()["ok"] is True and stub.printers.asked == [("command", SERIAL, "pause")]
    assert post(stub.c, p, {"action": "stop", "confirm": True}).status_code == 200 and stub.printers.asked[-1] == ("command", SERIAL, "stop")
    stub.printers.cmd_reply = {"ok": False, "reply": {"reason": "not_supported", "message": "no light gcode"}}
    r = post(stub.c, p, {"action": "light_on"})
    assert r.status_code == 409 and r.json()["code"] == "not_supported" and "no light gcode" in r.json()["error"]
    stub.printers.cmd_reply = {"ok": False, "reply": {"reason": "busy"}}
    r = post(stub.c, p, {"action": "resume"})
    assert r.status_code == 409 and r.json()["code"] == "refused" and r.json()["error"] == "busy"
    for e, status, code in ((PrinterOffline(SERIAL), 409, "printer_offline"), (NoReply(), 504, "no_reply"), (family.ModuleOff("klipper"), 409, "module_off")):
        stub.printers.cmd_reply = e
        r = post(stub.c, p, {"action": "pause"})
        assert (r.status_code, r.json()["code"]) == (status, code), r.text
    assert post(stub.c, "printers/00M00A00000FFFF/command", {"action": "pause"}).status_code == 404


def test_every_slot_action_needs_the_code_previews_by_default_and_sends_for_real_only_when_asked(stub):
    base = f"printers/{SERIAL}/slots/A1/"
    for what, body in (("load", {"spool_id": 7}), ("unload", {}), ("clear", {})):
        assert post(stub.c, base + what, body, code=None).status_code == 403
    assert stub.seen == []
    r = post(stub.c, base + "load", {"spool_id": 7})                                # dry_run defaults to true
    assert r.status_code == 200 and r.json()["dry_run"] is True and stub.seen[-1] == ("load", SERIAL, "A1", 7, True)
    r = post(stub.c, base + "load", {"spool_id": 7, "dry_run": False})
    assert r.json()["pending"] is True and r.json()["confirmed"] is False and stub.seen[-1] == ("load", SERIAL, "A1", 7, False)
    assert post(stub.c, base + "load", {"spool_id": "7"}).status_code == 400 and post(stub.c, base + "load", {"spool_id": True}).status_code == 400
    assert post(stub.c, base + "load", {"spool_id": 7, "dry_run": "no"}).status_code == 400
    r = post(stub.c, base + "unload", {"dry_run": False})
    assert r.json()["waiting_ended"] is True and r.json()["location"] == "Rack 1" and stub.seen[-1] == ("unload", SERIAL, "A1", False)
    r = post(stub.c, base + "clear", {})
    assert r.json()["dry_run"] is True and r.json()["waiting_ended"] is True and stub.seen[-1] == ("clear", SERIAL, "A1", True)
    r = post(stub.c, base + "clear", {"dry_run": False})
    assert r.json()["dry_run"] is False and stub.seen[-1] == ("clear", SERIAL, "A1", False)
    assert post(stub.c, f"printers/{SERIAL}/slots/a%20b/clear", {}).status_code in (400, 404)
    assert post(stub.c, "printers/00M00A00000FFFF/slots/A1/clear", {}).status_code == 404


def test_a_klipper_printers_slots_go_through_its_own_family_and_a_refused_slot_names_its_reason(stub):
    base = f"printers/{stub.k}/slots/T0/"
    assert post(stub.c, base + "clear", {"dry_run": False}).json()["printer_cleared"] is True
    assert post(stub.c, base + "unload", {}).json()["location"] == "Rack 1"
    assert post(stub.c, base + "load", {"spool_id": 4}).json()["dry_run"] is True
    assert [a[0] for a in stub.printers.klipper.asked] == ["clear", "unload", "load"] and stub.seen == []     # nothing went to the Bambu code
    # a refused load: the kit's code beside the sentence
    stub_load = pending.load_or_wait
    def refuse(*a, **k):
        raise loading.SlotInUse("Workshop X1 is printing; load A1 once it is done")
    pending.load_or_wait = refuse
    try:
        r = post(stub.c, f"printers/{SERIAL}/slots/A1/load", {"spool_id": 7})
    finally:
        pending.load_or_wait = stub_load
    assert r.status_code == 409 and r.json()["code"] == "slot_in_use" and "printing" in r.json()["error"]
    stub.printers.states[SERIAL] = "cert_changed"
    assert post(stub.c, f"printers/{SERIAL}/slots/A1/load", {"spool_id": 7}).json()["code"] == "cert_changed"
    stub.printers.states[SERIAL] = "connected"


def test_usage_is_open_and_its_undo_needs_the_code_and_a_klipper_entry_cannot_be_undone_here(stub):
    r = get(stub.c, f"printers/{SERIAL}/usage?days=3")
    assert r.status_code == 200 and r.json()["entries"][0]["spool"] == {"id": 7, "name": "PLA"} and r.json()["entries"][0]["days"] == 3.0
    assert get(stub.c, f"printers/{SERIAL}/usage").json()["entries"][0]["days"] == 7.0
    assert get(stub.c, f"printers/{SERIAL}/usage?days=abc").status_code == 400 and get(stub.c, f"printers/{SERIAL}/usage?days=9999").status_code == 400
    assert get(stub.c, f"printers/{stub.k}/usage").json()["entries"][0]["id"] == "k-1"
    assert post(stub.c, "usage/e1/undo", code=None).status_code == 403 and stub.seen == []
    assert post(stub.c, "usage/e1/undo").json() == {"entry": {"id": "e1", "undone": True}} and stub.seen == [("undo", "e1")]
    r = post(stub.c, "usage/k-5/undo")
    assert r.status_code == 409 and r.json()["code"] == "recorded_by_moonraker" and stub.seen == [("undo", "e1")]


def _stream(stub, serial, query="", name="camera.mjpeg"):
    return stub.c.get(f"/setup/api/printers/{serial}/{name}{query}")


def test_a_ticket_needs_the_code_starts_one_stream_for_its_printer_and_is_worthless_afterwards(stub):
    assert post(stub.c, f"printers/{SERIAL}/camera/ticket", code=None).status_code == 403
    assert _stream(stub, SERIAL).status_code == 403 and stub.cam.acquired == []                    # no ticket, no cookie: nothing starts
    assert _stream(stub, SERIAL, "?ticket=nope").status_code == 403
    r = post(stub.c, f"printers/{SERIAL}/camera/ticket")
    assert r.status_code == 200 and r.json()["expires_in"] == 60 and len(r.json()["ticket"]) >= 30
    t = r.json()["ticket"]
    assert _stream(stub, OTHER, f"?ticket={t}").status_code == 403 and stub.cam.acquired == []      # the ticket of another printer
    assert _stream(stub, SERIAL, f"?ticket={t}").status_code == 403                                   # and it is spent by the asking
    t = post(stub.c, f"printers/{SERIAL}/camera/ticket").json()["ticket"]
    other = post(stub.c, f"printers/{SERIAL}/camera/ticket").json()["ticket"]
    ok = _stream(stub, SERIAL, f"?ticket={t}")
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("multipart/x-mixed-replace") and stub.cam.acquired == [(SERIAL, "mjpeg")]
    assert stub.cam.released == [SERIAL]                                                          # counted out when the stream ends
    assert _stream(stub, SERIAL, f"?ticket={t}").status_code == 403                                 # used once
    assert _stream(stub, SERIAL, f"?ticket={other}").status_code == 200                              # a second ticket is its own
    assert post(stub.c, f"printers/{SERIAL}/camera/ticket").json()["ticket"] != other
    assert post(stub.c, f"printers/{SERIAL}/camera/ticket", code="00000000").status_code == 403


def test_a_ticket_past_60_seconds_is_refused_and_the_table_does_not_grow_without_end():
    now = [100.0]
    held = Tickets(clock=lambda: now[0])
    a = held.issue(SERIAL)
    now[0] += 59.9
    assert held.take(a, SERIAL) is True
    b = held.issue(SERIAL)
    now[0] += 60.1
    assert held.take(b, SERIAL) is False and held.take(b, SERIAL) is False
    assert held.take(None, SERIAL) is False and held.take(["x"], SERIAL) is False
    for _ in range(printer_live_tab.TICKET_MAX * 3):
        held.issue(SERIAL)
    assert len(held._held) <= printer_live_tab.TICKET_MAX


def test_a_trusted_computer_asks_the_stream_directly_and_a_cookie_that_is_not_one_gets_nothing(stub):
    assert stub.c.post("/setup/api/trust", json={"code": CODE}, headers={**H, **AGENT}).status_code == 200
    assert trusted.COOKIE in stub.c.cookies
    r = _stream(stub, SERIAL)                                                                      # no ticket: the cookie is checked by the helper
    assert r.status_code == 200 and stub.cam.acquired == [(SERIAL, "mjpeg")]
    assert _stream(stub, SERIAL, name="camera/index.m3u8").status_code == 200 and stub.cam.acquired[-1] == (SERIAL, "hls")
    assert _stream(stub, SERIAL, "?ticket=whatever").status_code == 200                              # a bad ticket does not spoil the cookie
    stub.c.cookies.clear()
    stub.c.cookies.set(trusted.COOKIE, "A" * 43, path="/setup")
    assert _stream(stub, SERIAL).status_code == 403
    assert _stream(stub, SERIAL, name="camera/index.m3u8").status_code == 403


def test_the_playlist_does_not_take_a_ticket_and_no_camera_hub_is_said_plainly(stub, tmp_path):
    t = post(stub.c, f"printers/{SERIAL}/camera/ticket").json()["ticket"]
    assert _stream(stub, SERIAL, f"?ticket={t}", name="camera/index.m3u8").status_code == 403       # a segment's address cannot carry one
    page = stub.page
    page.camera_hub = None
    none = Starlette(routes=page.routes() + [Route("/setup/api" + p, fn, methods=[m]) for p, fn, m in printer_live_tab.routes(page, sm=Spoolman("http://127.0.0.1:9"))])
    c = TestClient(none, base_url=BASE, client=HOME)
    r = c.post(f"/setup/api/printers/{SERIAL}/camera/ticket", json={"code": CODE}, headers=H)
    assert r.status_code == 409 and r.json()["code"] == "module_off"


def test_the_routes_are_the_ones_of_the_contract_and_a_locked_get_still_reads():
    paths = {(m, p) for p, _, m in printer_live_tab.routes(type("P", (), {"guard": staticmethod(lambda fn, **k: fn)})())}
    assert paths == {("GET", "/printers/{serial}/live"), ("POST", "/printers/{serial}/command"), ("POST", "/printers/{serial}/slots/{label}/load"),
                     ("POST", "/printers/{serial}/slots/{label}/unload"), ("POST", "/printers/{serial}/slots/{label}/clear"),
                     ("GET", "/printers/{serial}/usage"), ("POST", "/usage/{entry_id}/undo"), ("POST", "/printers/{serial}/camera/ticket"),
                     ("GET", "/printers/{serial}/camera.mjpeg"), ("GET", "/printers/{serial}/camera/{name:path}")}


# ======================================================================================================== the texts

CATALOGUE = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))


def _stub_table() -> dict:
    body = re.search(r"const STUB = \{(.*?)\n\};", JS.read_text(encoding="utf-8"), re.S).group(1)
    return dict(re.findall(r'(live_[a-z_]+): "((?:[^"\\]|\\.)*)"', body))


def _keys_used() -> set:
    src = JS.read_text(encoding="utf-8")
    keys = set(re.findall(r'"((?:printers?|slot|common|spools?|status|live)_[a-z0-9_]+)"', src))
    keys |= {f"live_{w}_slot" for w in ("load", "unload", "clear")}          # built from the action's name
    return {k for k in keys if k != "live_" and not k.endswith("_reason_") and not k.startswith("printer_usage_reason_")}


def test_every_text_is_in_the_catalogue_or_in_the_local_table_and_the_table_holds_only_what_the_catalogue_lacks():
    table = _stub_table()
    assert len(table) > 20
    missing = sorted(k for k in _keys_used() if k not in CATALOGUE and k not in table)
    assert not missing, missing
    assert sorted(k for k in table if k in CATALOGUE) == [], "the catalogue has these now: drop them from the table"
    built = {f"live_{w}_slot" for w in ("load", "unload", "clear")}                    # named by the action, in one place
    src = JS.read_text(encoding="utf-8")
    assert sorted(k for k in table if k not in built and k not in src.replace(f'{k}: "', "")) == []    # each is used
    for k, v in table.items():
        assert v and not v.endswith(" ") and "  " not in v, k


# ======================================================================================================== the view, in a real browser

PRELUDE = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (look, what, ms = 8000) => { const end = Date.now() + ms; for (;;) { const v = look(); if (v) return v; if (Date.now() > end) throw new Error("waited for " + what); await sleep(50); } };
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
const shown = (el) => !!el && el.getClientRects().length > 0 && !el.hidden;
const clone = (x) => JSON.parse(JSON.stringify(x));
const SERIAL = "00M00A000000001", CODE = "__CODE__";
const AMS = [{ unit: 0, label: "AMS 1", type_name: "AMS", slots: [
  { slot: 0, label: "A1", type: "PLA", color_hex: "2B2B2E", active: true, present: true, spool: { id: 7, name: "Polymaker PolyTerra PLA", material: "PLA", color_hex: "2B2B2E", remaining_weight: 620 } },
  { slot: 1, label: "A2", type: "", color_hex: "", active: false, present: false, spool: null, pending: { spool_id: 9, text: "waiting for the spool to load in slot A2" } },
  { slot: 2, label: "A3", type: "PETG", color_hex: "FF8800", active: false, present: true, spool: null }] }];
const LIVE = { summary: { gcode_state: "RUNNING", percent: 42 }, state: "connected", family: "bambu", name: "Workshop X1", camera: { kind: "mjpeg" }, controls: { light: true },
  status: { gcode_state: "RUNNING", job: "benchy.3mf", percent: 42, layer: 120, total_layers: 300, remaining_min: 75, eta: new Date(Date.now() + 75 * 60000).toISOString(), stage: "Printing",
    temps: { nozzle: [{ current: 219.6, target: 220 }], bed: { current: 60, target: 60 }, chamber: { current: 34, target: null } }, ams: AMS,
    hms: [{ code: "0300_0100", text: "The heatbed temperature is abnormal." }], print_error: "", light: "on", notes: [] } };
const USAGE = [{ id: "e1", at: "2026-11-17T10:00:00+00:00", job: "benchy.3mf", grams: 12.5, spool_id: 7, slot: "A1", observe: false, undone: false, spool: { id: 7, name: "Polymaker PolyTerra PLA" } },
  { id: "e2", at: "2026-11-16T09:30:00+00:00", job: "gear.3mf", grams: 3, spool_id: null, slot: "A3", observe: false, undone: false, spool: null },
  { id: "k-4", at: "2026-11-15T09:30:00+00:00", job: "clip.gcode", grams: 8, spool_id: 7, slot: "T0", observe: false, undone: false, spool: { id: 7, name: "Polymaker PolyTerra PLA" } },
  { id: "e3", at: "2026-11-14T09:30:00+00:00", job: "old.3mf", grams: 20, spool_id: 7, slot: "A1", observe: false, undone: true, spool: { id: 7, name: "Polymaker PolyTerra PLA" } }];
const PLAN_SPOOL = { id: 7, vendor: "Polymaker", name: "PolyTerra PLA", remaining_g: 620, location: "A1" };
const hub = { calls: [], live: clone(LIVE), usage: clone(USAGE), reply: {} };
const calls = (re) => hub.calls.filter((c) => re.test(c.method + " " + c.path));
const stubHub = (rec) => {
  const [m, p, b] = [rec.method, rec.path, rec.body], custom = hub.reply[p.replace(/\?.*/, "")] || hub.reply[m + " " + p.replace(/\?.*/, "")];
  if (custom) { const r = typeof custom === "function" ? custom(rec) : custom; if (r) return r; }
  let x;
  if ((x = /^printers\/[^/]+\/slots\/([^/]+)\/(load|unload|clear)$/.exec(p))) {
    const [, label, what] = x, dry = b.dry_run;
    if (what === "load") return [200, { dry_run: dry, spool: PLAN_SPOOL, slot: { label }, preset: { name: "Generic PLA" }, moved_back: label === "A1" ? [{ id: 7, location: "Rack 1" }, { id: 3, location: "Rack 2" }] : [], problems: [],
      confirmed: dry ? null : label !== "A2", ...(!dry && label === "A2" ? { pending: true } : {}) }];
    if (what === "unload") return [200, { dry_run: dry, spool: { id: 7, location: "Rack 1" }, slot: { label }, moved_back: [{ id: 7, location: "Rack 1" }], location: "Rack 1", waiting_ended: false }];
    return [200, { slot: label, spool: label === "A1" ? PLAN_SPOOL : null, moved_back: label === "A1" ? "Rack 1" : null, waiting_ended: label === "A2", printer_cleared: false, dry_run: dry,
      text: "The printer still shows the old filament for this slot until a spool is loaded." }];
  }
  if (/^printers\/[^/]+\/live$/.test(p)) return [200, hub.live];
  if (/^printers\/[^/]+\/command$/.test(p)) return [200, { ok: true, reply: { ok: true } }];
  if (/^printers\/[^/]+\/usage/.test(p)) return [200, { entries: hub.usage }];
  if (/^usage\/[^/]+\/undo$/.test(p)) return [200, { entry: { id: p.split("/")[1], undone: true } }];
  if (/^printers\/[^/]+\/camera\/ticket$/.test(p)) return [200, { ticket: "tk" + calls(/camera\/ticket/).length, expires_in: 60 }];
  if (/^spools\?/.test(p)) return [200, { spools: [PLAN_SPOOL, { id: 8, vendor: "Sunlu", name: "PETG Blue", remaining_g: 410, location: "Rack 2" }] }];
  return [404, { error: "no such stub " + p }];
};
const MINE = /^(printers\/00M00A00000000[12]\/|usage\/|spools\?)/;
const realFetch = window.fetch.bind(window);
window.fetch = async (url, init) => {
  const u = String(url);
  if (!u.startsWith("/setup/api/") || !MINE.test(u.slice(11))) return realFetch(url, init);
  const rec = { method: (init && init.method) || "GET", path: u.slice(11), body: init && init.body ? JSON.parse(init.body) : null };
  hub.calls.push(rec);
  const [status, data] = stubHub(rec);
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
};
// a picture request would go to a route the page does not have yet: the address is kept, nothing is asked
const imgs = [];
Object.defineProperty(HTMLImageElement.prototype, "src", { configurable: true, get() { return this.getAttribute("data-src") || ""; }, set(v) { imgs.push(v); this.setAttribute("data-src", v); } });
const css = __CSS__;
{ const sheet = new CSSStyleSheet(); sheet.replaceSync(css); document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet]; }
await until(() => window.SW && window.api && $("main") && !$(".chip--lock .skeleton__line"), "the page");
for (const c of [...document.body.children]) if (!/^(svg|script)$/i.test(c.tagName)) c.style.display = "none";      // the page behind it stays out of the way
const mount = (o = {}) => {
  const host = document.createElement("div");
  host.id = "host"; host.style.padding = "16px"; host.style.boxSizing = "border-box";
  if (o.width) host.style.width = o.width + "px";
  document.body.append(host);
  const el = window.printerLive(o.printer || { serial: SERIAL, name: "Workshop X1", family: "bambu" }, o.ctx || {});
  host.append(el);
  return { host, el };
};
const setLook = (look) => document.documentElement.setAttribute("data-look", look);
const unlock = () => SW.setLock("unlocked", { code: CODE });
const rows = () => $$(".plive__slot");
const row = (label) => rows().find((r) => r.dataset.slot === label);
const btn = (scope, action) => $(`[data-action="${action}"]`, scope);
const dialog = () => until(() => $("dialog[open]"), "a dialog");
const next = async (action) => { const d = await dialog(); $(`[data-action="${action}"]`, d).click(); return until(() => { const x = $("dialog[open]"); return x && x !== d ? x : null; }, "the next dialog"); };
const answer = async (action) => { const d = await dialog(); $(`[data-action="${action}"]`, d).click(); await until(() => !$("dialog[open]"), "the dialog to close"); await sleep(120); };      // the caller of the dialog goes on a moment after it closes
"""

def _live(body: str, width: int = 1280, look: str = "console") -> dict:
    css = json.dumps(CSS.read_text(encoding="utf-8"))
    js = JS.read_text(encoding="utf-8")
    return {"script": PRELUDE.replace("__CSS__", css) + js + f'\nsetLook("{look}");\nconst out = {{}};\n' + body + "\nreturn out;\n", "width": width}


def drive(hub, tmp_path, body, width=1280, look="console"):
    d = _live(body, width, look)
    return _drive(hub, tmp_path, d["script"], width=d["width"])


def test_the_view_shows_the_state_the_job_the_temperatures_the_alerts_and_the_slots_and_asks_again_every_two_seconds(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
SW.setLock("locked");
const m = mount();
await until(() => $(".plive__job .status") && rows().length === 3, "the first read");
out.head = text($(".plive__state")); out.job = text($(".plive__job"));
out.prog = { now: $(".plive .progress__track").getAttribute("aria-valuenow"), pct: text($(".plive__pct")) };
out.detail = text($(".plive__detail")); out.temps = text($(".plive__temps")); out.alerts = text($(".plive__alerts"));
out.labels = rows().map((r) => r.dataset.slot);
out.states = rows().map((r) => r.dataset.state || "");
out.names = rows().map((r) => text($(".plive__what", r)));
out.buttons = rows().map((r) => $$(".btn", r).map((b) => b.dataset.action));
out.waiting = text($(".plive__waiting", row("A2")));
out.usage = $$(".plive__used").map((r) => text(r));
out.camBtn = shown($('[data-action="camera"]'));
out.lockedNote = text($(".plive__locked"));
// every 2 s: a change at the Hub shows by itself
const first = calls(/live$/).length;
hub.live.status.percent = 60; hub.live.status.ams[0].slots[1].pending = null;
await until(() => text($(".plive__pct")) === "60 %", "the next read", 3500);
out.polled = calls(/live$/).length - first;
out.waitingGone = !row("A2").dataset.state;
// the tab hidden: nothing is asked; shown again: asked at once
Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
document.dispatchEvent(new Event("visibilitychange"));
await sleep(300);
const hiddenFrom = calls(/live$/).length;
await sleep(2600);
out.askedWhileHidden = calls(/live$/).length - hiddenFrom;
delete document.hidden;
document.dispatchEvent(new Event("visibilitychange"));
await until(() => calls(/live$/).length > hiddenFrom, "a read once the tab is shown", 1500);
// the detail closed (the view stays in the page, not shown): nothing is asked; open again: asked within a second
m.host.style.display = "none";
await sleep(400);
const closedFrom = calls(/live$/).length;
await sleep(2600);
out.askedWhileClosed = calls(/live$/).length - closedFrom;
m.host.style.display = "";
await until(() => calls(/live$/).length > closedFrom, "a read once the detail is open", 1500);
// taken off the page: it stops by itself
m.host.remove();
await sleep(2400);
const gone = calls(/live$/).length;
await sleep(2600);
out.askedWhenGone = calls(/live$/).length - gone;
""")
    assert page["head"] == T("status_connected")
    assert page["job"] == T("printer_state_printing", job="benchy.3mf")
    assert page["prog"] == {"now": "42", "pct": "42 %"}
    assert T("printer_progress_layer", layer=120, layers=300) in page["detail"] and T("printer_progress_left", time="1 h 15 min") in page["detail"]
    assert T("printer_progress_done", clock="") .split("{")[0] in page["detail"] and page["detail"].endswith("Printing")
    assert page["temps"] == " · ".join([T("printer_temp_nozzle", now=220, target=220), T("printer_temp_bed", now=60, target=60), T("printer_temp_chamber", now=34)])
    assert page["alerts"] == "The heatbed temperature is abnormal."
    assert page["labels"] == ["A1", "A2", "A3"] and page["states"] == ["active", "waiting", ""]
    assert "Polymaker PolyTerra PLA" in page["names"][0] and page["names"][1].startswith(T("slot_waiting")) and "#9" in page["names"][1] and page["names"][2].startswith("PETG")
    # Unload only where a spool is recorded; Load and Clear slot on every slot
    assert page["buttons"] == [["load", "unload", "clear"], ["load", "clear"], ["load", "clear"]]
    assert page["waiting"] == T("slot_waiting") + " #9"
    assert len(page["usage"]) == 4 and "12.5 g" in page["usage"][0] and "benchy.3mf" in page["usage"][0] and page["camBtn"] is True
    assert "Unlock the page" in page["lockedNote"] and T("common_unlock_to_show") in page["lockedNote"]
    assert page["polled"] >= 1 and page["waitingGone"] is True
    assert page["askedWhileHidden"] == 0 and page["askedWhileClosed"] == 0 and page["askedWhenGone"] == 0


def test_pause_resume_the_light_and_stop_ask_the_hub_and_stop_asks_first(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
mount();
await until(() => $('[data-action="pause"]'), "the controls");
out.buttons = $$(".plive__controls .btn").map((b) => b.dataset.action);
const sent = () => calls(/POST printers\/[^/]+\/command$/).map((c) => c.body);
btn(document, "pause").click();
await until(() => sent().length === 1, "the pause");
out.pause = sent()[0]; out.pauseLine = await until(() => text($(".plive__msg .result__text")), "its line");
// Stop asks first: Keep printing sends nothing
btn(document, "stop").click();
let d = await dialog();
out.stopTitle = text($(".dialog__title", d)); out.stopText = text($(".dialog__text", d)); out.stopButtons = $$(".dialog__foot .btn", d).map(text);
await answer("cancel");
out.afterKeep = sent().length;
btn(document, "stop").click();
await dialog();
await answer("confirm");
await until(() => sent().length === 2, "the stop");
out.stop = sent()[1];
// the printer paused: Resume instead of Pause; the light toggles
hub.live.status.gcode_state = "PAUSE";
await until(() => $('[data-action="resume"]'), "Resume", 3500);
out.paused = $$(".plive__controls .btn").map((b) => b.dataset.action);
btn(document, "resume").click();
await until(() => sent().length === 3, "the resume");
out.resume = sent()[2];
btn(document, "light_off").click();
await until(() => sent().length === 4, "the light");
out.light = sent()[3];
// idle: no Pause, no Stop
hub.live.status.gcode_state = "IDLE";
await until(() => !$('[data-action="stop"]'), "no Stop while idle", 3500);
out.idle = $$(".plive__controls .btn").map((b) => b.dataset.action);
""")
    assert page["buttons"] == ["pause", "light_off", "stop"]
    assert page["pause"] == {"action": "pause", "code": CODE} and page["pauseLine"] == T("printer_result_paused")
    assert page["stopTitle"] == T("printer_stop_dialog_title") and page["stopText"] == T("printer_stop_dialog_body", job="benchy.3mf", printer="Workshop X1")
    assert page["stopButtons"] == [T("printer_stop_keep"), T("printer_stop")] and page["afterKeep"] == 1        # Keep printing: nothing sent
    assert page["stop"] == {"action": "stop", "confirm": True, "code": CODE}
    assert page["paused"] == ["resume", "light_off", "stop"] and page["resume"]["action"] == "resume" and page["light"]["action"] == "light_off"
    assert page["idle"] == ["light_off"]


def test_a_locked_page_opens_the_unlock_dialog_for_a_control_and_sends_nothing_but_still_shows_slots_and_usage(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
SW.setLock("locked");
mount();
await until(() => rows().length === 3 && $$(".plive__used").length === 4, "the view");
out.shownLocked = { slots: rows().length, usage: $$(".plive__used").length, state: text($(".plive__job")) };
for (const [what, find] of [["pause", () => btn(document, "pause")], ["stop", () => btn(document, "stop")], ["clear", () => btn(row("A1"), "clear")], ["load", () => btn(row("A1"), "load")],
  ["unload", () => btn(row("A1"), "unload")], ["camera", () => btn(document, "camera")], ["undo", () => btn($$(".plive__used")[0], "undo")]]) {
  find().click();
  const d = await dialog();
  out[what] = { dialog: !!$("form", d) && !!$('input[type="password"], input', d), title: text($(".dialog__title", d)) };
  await answer("cancel");
}
out.sent = hub.calls.filter((c) => c.method === "POST").length;
""")
    assert page["shownLocked"] == {"slots": 3, "usage": 4, "state": T("printer_state_printing", job="benchy.3mf")}
    for what in ("pause", "stop", "clear", "load", "unload", "camera", "undo"):
        assert page[what]["dialog"] is True, what
    assert page["sent"] == 0                                                         # nothing went to the Hub


def test_a_klipper_printer_shows_the_same_view_without_the_controls_it_has_not_got(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
hub.live.family = "klipper"; hub.live.controls = { light: false }; hub.live.status.light = null; hub.live.status.family = "klipper";
mount({ printer: { serial: SERIAL, name: "Garage Voron", family: "klipper" } });
await until(() => $('[data-action="pause"]'), "the controls");
out.noLight = $$(".plive__controls .btn").map((b) => b.dataset.action);
out.slots = rows().length;
// a light the model has, with no state: two buttons; the Hub says not_supported: they go and the line says why
hub.live.controls = { light: true };
await until(() => $('[data-action="light_on"]'), "the light buttons", 3500);
out.light = $$(".plive__controls .btn").map((b) => b.dataset.action);
hub.reply["POST printers/" + SERIAL + "/command"] = (rec) => (rec.body.action === "light_on" ? [409, { error: "no light gcode in klipper_hardware.xml for this printer", code: "not_supported" }] : null);
btn(document, "light_on").click();
await until(() => !$('[data-action="light_on"]'), "the light buttons to go");
out.after = $$(".plive__controls .btn").map((b) => b.dataset.action);
out.line = text($(".plive__msg .result__text"));
await sleep(2300);
out.stays = $$(".plive__controls .btn").map((b) => b.dataset.action);
""")
    assert page["noLight"] == ["pause", "stop"] and page["slots"] == 3
    assert page["light"] == ["pause", "light_on", "light_off", "stop"]
    assert page["after"] == ["pause", "stop"] and page["stays"] == ["pause", "stop"] and page["line"] == "This printer has no such control."


def test_a_refused_command_and_an_offline_printer_say_so(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
mount();
await until(() => $('[data-action="pause"]'), "the controls");
hub.reply["POST printers/" + SERIAL + "/command"] = [409, { error: "busy", code: "refused" }];
btn(document, "pause").click();
out.refused = await until(() => text($(".plive__msg .result__text")), "the refusal");
out.refusedKind = $(".plive__msg").dataset.state;
hub.live.state = "offline"; hub.live.status = null;
await until(() => !$('[data-action="pause"]') && text($(".plive__state")).includes("Offline"), "the offline view", 3500);
out.state = text($(".plive__state")); out.controls = $$(".plive__controls .btn").length;
out.slots = text($(".plive__units")); out.camBtn = shown($('[data-action="camera"]'));
""")
    assert page["refused"] == T("printer_said_no", error="busy") and page["refusedKind"] == "bad"
    assert T("status_offline") in page["state"] and T("printers_fix_offline") in page["state"] and page["controls"] == 0
    assert page["slots"] == T("slot_none_offline") and page["camBtn"] is True


def test_load_unload_and_clear_slot_each_preview_with_a_dry_run_then_ask_then_send_and_say_the_result(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
mount();
await until(() => rows().length === 3, "the slots");
const slotCalls = () => calls(/POST printers\/[^/]+\/slots\//).map((c) => `${c.path.split("/").slice(-2).join("/")} ${JSON.stringify(c.body.spool_id ?? null)} ${c.body.dry_run}`);
const line = (label) => text($(".plive__slotline .result__text", row(label)));
// Clear slot on A1 (a spool recorded): the preview, the question with the Hub's words, then the result
btn(row("A1"), "clear").click();
let d = await dialog();
out.clearTitle = text($(".dialog__title", d)); out.clearText = text($(".dialog__text", d)); out.clearButtons = $$(".dialog__foot .btn", d).map(text);
out.clearBefore = slotCalls();
await answer("cancel");
out.clearCancelled = slotCalls();
btn(row("A1"), "clear").click();
await dialog();
await answer("confirm");
out.clearLine = await until(() => line("A1"), "the result");
out.clearCalls = slotCalls();
// Clear slot on A2 (a spool waiting): no spool recorded, the waiting one is no longer waiting
btn(row("A2"), "clear").click();
d = await dialog();
out.waitText = text($(".dialog__text", d)); out.waitBody = text($(".dialog__body", d));
await answer("confirm");
out.waitLine = await until(() => line("A2"), "the A2 result");
// Unload on A1
btn(row("A1"), "unload").click();
d = await dialog();
out.unloadTitle = text($(".dialog__title", d)); out.unloadText = text($(".dialog__text", d));
await answer("confirm");
out.unloadLine = await until(() => /Unloaded/.test(line("A1") || "") && line("A1"), "the unload result");
out.all = slotCalls();
""")
    assert page["clearTitle"] == "Clear slot A1?"
    assert page["clearText"] == "Clear slot A1? The Hub forgets the spool recorded here. Polymaker PolyTerra PLA goes back to Rack 1."
    assert page["clearButtons"] == [T("common_cancel"), "Clear slot"]
    assert page["clearBefore"] == ["slots/A1/clear null true"] or page["clearBefore"] == ["A1/clear null true"]
    assert page["clearCancelled"] == page["clearBefore"]                                    # Cancel sent nothing more
    assert page["clearCalls"][-1].endswith("clear null false") and len(page["clearCalls"]) == 3     # the preview, the preview again, the real one
    assert page["clearLine"].startswith("Slot A1 cleared.") and "The printer still shows the old filament" in page["clearLine"]
    assert page["waitText"] == "Clear slot A2? The Hub forgets the spool recorded here." and page["waitBody"].endswith("The spool waiting for this slot is no longer waiting.")
    assert "The spool waiting for this slot is no longer waiting." in page["waitLine"]
    assert page["unloadTitle"] == T("printer_unload_title", slot="A1") and page["unloadText"] == T("printer_unload_body", name="Polymaker PolyTerra PLA", slot="A1", location="Rack 1")
    assert T("printer_unload_line", name="Polymaker PolyTerra PLA", slot="A1") in page["unloadLine"]
    assert page["all"][-1].endswith("unload null false") and page["all"][-2].endswith("unload null true")


def test_load_picks_a_spool_previews_and_a_waiting_load_says_it_is_waiting(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
mount();
await until(() => rows().length === 3, "the slots");
const loads = () => calls(/POST printers\/[^/]+\/slots\/[^/]+\/load$/).map((c) => `${c.path.split("/")[3]} ${c.body.spool_id} ${c.body.dry_run}`);
const line = (label) => text($(".plive__slotline .result__text", row(label)));
btn(row("A1"), "load").click();
let d = await dialog();
out.pickTitle = text($(".dialog__title", d));
await until(() => $$(".plive__pick", d).length === 2, "the spools");
out.picks = $$(".plive__pick", d).map(text);
// nothing picked: Load stays and says so
$('[data-action="confirm"]', d).click();
out.none = await until(() => text($(".dialog__body .result__text", d)), "the note");
out.noCalls = loads().length;
$$(".plive__pick", d)[0].click();
out.pressed = $$(".plive__pick", d).map((b) => b.getAttribute("aria-pressed"));
d = await next("confirm");                              // the preview of what Load does
out.planTitle = text($(".dialog__title", d)); out.planText = text($(".dialog__text", d)); out.planBody = text($(".dialog__body", d));
out.beforeSend = loads();
await answer("confirm");
out.line = await until(() => line("A1"), "the result");
out.sent = loads();
// the waiting slot: the answer says pending
btn(row("A2"), "load").click();
d = await dialog();
await until(() => $$(".plive__pick", d).length === 2, "the spools");
$$(".plive__pick", d)[1].click();
await next("confirm");
await answer("confirm");
out.waitLine = await until(() => line("A2"), "the A2 result");
// a picker of the page's own may stand in for the built-in one
out.searchCalls = calls(/^GET spools\?/).map((c) => c.path);
""")
    assert page["pickTitle"] == "Load into slot A1" and page["noCalls"] == 0
    assert len(page["picks"]) == 2 and page["picks"][0].startswith("S7 Polymaker PolyTerra PLA") and "Rack 2" in page["picks"][1]
    assert page["none"] == "Pick a spool first." and page["pressed"] == ["true", "false"]
    assert page["planTitle"] == T("spool_load_title", slot="A1") and page["planText"] == "Load Polymaker PolyTerra PLA into A1."
    assert T("printer_load_preset", name="Generic PLA") in page["planBody"] and T("spool_load_plan_goes_back", id=3, slot="A1", location="Rack 2") in page["planBody"]
    assert page["beforeSend"] == ["A1 7 true"] and page["sent"] == ["A1 7 true", "A1 7 false"]       # the preview, then the real load
    assert page["line"].startswith("Loaded Polymaker PolyTerra PLA into A1.")
    assert page["waitLine"].startswith("Waiting for the spool to load in A2.")
    assert page["searchCalls"] and page["searchCalls"][0].startswith("spools?q=")


def test_filament_used_lists_entries_with_undo_that_asks_first_and_not_for_what_cannot_be_undone(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
mount();
await until(() => $$(".plive__used").length === 4, "the usage");
out.undo = $$(".plive__used").map((r) => [r.dataset.entry, !!btn(r, "undo"), r.dataset.state || ""]);
out.rows = $$(".plive__used").map(text);
btn($$(".plive__used")[0], "undo").click();
let d = await dialog();
out.title = text($(".dialog__title", d)); out.body = text($(".dialog__text", d)); out.buttons = $$(".dialog__foot .btn", d).map(text);
await answer("cancel");
out.afterKeep = calls(/usage\/[^/]+\/undo/).length;
btn($$(".plive__used")[0], "undo").click();
await dialog();
hub.usage[0].undone = true;                           // what the Hub says once it is done
await answer("confirm");
await until(() => calls(/usage\/[^/]+\/undo/).length === 1, "the undo");
out.sent = calls(/usage\/[^/]+\/undo/).map((c) => [c.path, c.body]);
out.line = await until(() => text($(".plive__used .result__text")), "the line");
await until(() => $$(".plive__used")[0].dataset.state === "undone", "the entry marked undone");
out.after = [!!btn($$(".plive__used")[0], "undo"), text($$(".plive__used")[0])];
""")
    # the entry of an earlier undo, one with no spool, and a Klipper entry (Moonraker's: the kit cannot undo it) have no Undo
    assert page["undo"] == [["e1", True, ""], ["e2", False, ""], ["k-4", False, ""], ["e3", False, "undone"]]
    assert "12.5 g" in page["rows"][0] and "benchy.3mf · A1" in page["rows"][0] and "2026-11-17 10:00" in page["rows"][0] and "Polymaker PolyTerra PLA" in page["rows"][0]
    assert T("printer_usage_note_no_spool") in page["rows"][1] and T("printer_usage_note_undone") in page["rows"][3]
    assert page["title"] == T("printer_usage_undo_title") and page["buttons"] == [T("common_keep"), T("printer_usage_undo_confirm")]
    assert page["body"] == T("printer_usage_undo_body", grams=12.5, job="benchy.3mf", slot="A1", time="2026-11-17 10:00") and page["afterKeep"] == 0
    assert page["sent"] == [["usage/e1/undo", {"code": CODE}]]
    assert page["line"] == T("printer_usage_undone", grams=12.5, id=7) and page["after"][0] is False and T("printer_usage_note_undone") in page["after"][1]


def test_the_camera_asks_for_a_ticket_off_a_trusted_computer_and_directly_on_one(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
mount();
await until(() => $('[data-action="camera"]'), "the camera button");
// Locked: the unlock dialog, no ticket
btn(document, "camera").click();
await dialog(); await answer("cancel");
out.lockedTickets = calls(/camera\/ticket/).length; out.lockedImgs = imgs.length;
// Unlocked, not trusted: the code asks for a ticket, the stream's address carries it
unlock();
btn(document, "camera").click();
await until(() => imgs.length === 1, "the picture");
out.ticket = { calls: calls(/camera\/ticket/).map((c) => [c.method, c.path, c.body]), img: imgs[0], label: text(btn(document, "camera")),
  alt: $(".plive__img").getAttribute("alt"), starting: text($(".plive__camtext")) };
$(".plive__img").dispatchEvent(new Event("load"));
out.started = !$(".plive__camtext");
btn(document, "camera").click();
out.hidden = { box: shown($(".plive__cam")), img: !!$(".plive__img"), label: text(btn(document, "camera")) };
// Trusted: no ticket, the address is asked directly (the cookie goes along)
SW.setLock("trusted");
btn(document, "camera").click();
await until(() => imgs.length === 2, "the direct picture");
out.direct = { img: imgs[1], tickets: calls(/camera\/ticket/).length };
btn(document, "camera").click();
// the picture fails: a line and Try again, which asks for a new ticket
unlock();
btn(document, "camera").click();
await until(() => imgs.length === 3, "the third picture");
$(".plive__img").dispatchEvent(new Event("error"));
await until(() => $('[data-action="try-again"]'), "Try again");
out.failed = text($(".plive__camtext"));
$('[data-action="try-again"]').click();
await until(() => imgs.length === 4, "the retry");
out.retry = { img: imgs[3], tickets: calls(/camera\/ticket/).length };
// locking the page stops the stream
SW.setLock("locked");
await until(() => !$(".plive__img"), "the stream to stop");
out.lockedStops = shown($(".plive__cam"));
""")
    assert page["lockedTickets"] == 0 and page["lockedImgs"] == 0
    assert page["ticket"]["calls"] == [["POST", f"printers/{'00M00A000000001'}/camera/ticket", {"code": CODE}]]
    assert page["ticket"]["img"] == "/setup/api/printers/00M00A000000001/camera.mjpeg?ticket=tk1" and page["ticket"]["label"] == T("printer_camera_hide")
    assert page["ticket"]["alt"] == T("printer_camera_alt", printer="Workshop X1") and page["ticket"]["starting"] == T("printer_camera_starting")
    assert page["started"] is True and page["hidden"] == {"box": False, "img": False, "label": T("printer_camera_show")}
    assert page["direct"] == {"img": "/setup/api/printers/00M00A000000001/camera.mjpeg", "tickets": 1}            # a trusted computer: no ticket, no query
    assert page["failed"].startswith(T("printer_camera_failed")) and page["retry"] == {"img": "/setup/api/printers/00M00A000000001/camera.mjpeg?ticket=tk3", "tickets": 3}
    assert page["lockedStops"] is False


def test_a_ticket_the_hub_refuses_is_said_and_a_printer_without_a_camera_has_no_button(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
hub.reply["POST printers/" + SERIAL + "/camera/ticket"] = [409, { error: "the camera is not running on this Hub", code: "module_off" }];
mount();
await until(() => $('[data-action="camera"]'), "the camera button");
btn(document, "camera").click();
await until(() => $('[data-action="try-again"]'), "the line");
out.text = text($(".plive__camtext")); out.imgs = imgs.length;
document.querySelector("#host").remove();
hub.reply = {}; hub.live.camera = { kind: null };
mount();
await until(() => rows().length === 3, "the second view");
out.button = shown($('[data-action="camera"]'));
""")
    assert page["text"].startswith("the camera is not running on this Hub") and page["imgs"] == 0
    assert page["button"] is False


def test_a_picker_of_the_pages_own_stands_in_for_the_built_in_one(hub, tmp_path):
    page = drive(hub, tmp_path, r"""
unlock();
mount({ ctx: { pickSpool: async (slot) => ({ id: 8, vendor: "Sunlu", name: "PETG Blue", remaining_g: 410, location: "Rack 2", slot: slot.label }) } });
await until(() => rows().length === 3, "the slots");
btn(row("A3"), "load").click();
await dialog();                                           // the preview
out.search = calls(/^GET spools\?/).length;
out.plan = text($(".dialog__text"));
out.sent = calls(/POST .*load$/).map((c) => [c.path, c.body.spool_id, c.body.dry_run]);
await answer("cancel");
""")
    assert page["search"] == 0 and page["plan"] == "Load Sunlu PETG Blue into A3." and page["sent"] == [["printers/00M00A000000001/slots/A3/load", 8, True]]


LAYOUT = r"""
unlock();
const measure = (tag, width) => {
  document.querySelector("#host")?.remove();
  const m = mount({ width });
  hub.live.status.hms = [{ code: "0300_0100", text: "The heatbed temperature is abnormal and the printer has stopped heating until someone looks at it." }];
  return m;
};
const out2 = [];
for (const width of [0, 360]) {
  for (const look of ["console", "workbench", "palette", "panes"]) {
    setLook(look);
    const m = measure(look, width);
    await until(() => rows().length === 3 && $$(".plive__used").length === 4, "the view");
    btn(document, "camera").click();
    await until(() => $(".plive__img"), "the picture");
    await sleep(120);
    const box = m.host.getBoundingClientRect(), view = m.el.getBoundingClientRect();
    const r = { look, width, view: Math.round(view.width), page: document.documentElement.scrollWidth <= innerWidth, host: m.host.scrollWidth <= m.host.clientWidth + 1 };
    r.outside = $$(".plive .btn, .plive__img", m.el).filter((b) => { const x = b.getBoundingClientRect(); return x.right > view.right + 1 || x.left < view.left - 1; }).map((b) => text(b) || b.className);
    r.names = rows().map((s) => Math.round($(".plive__what", s).getBoundingClientRect().width));
    const one = btn(document, "camera").getBoundingClientRect().height;                  // a button of one line
    r.lines = $$(".plive .btn", m.el).map((b) => Math.round(b.getBoundingClientRect().height / one * 10) / 10);
    r.used = $$(".plive__used", m.el).map((u) => [Math.round($(".plive__what", u).getBoundingClientRect().width), u.scrollWidth <= u.clientWidth + 1]);
    r.camera = Math.round($(".plive__img").getBoundingClientRect().width);
    r.alert = Math.round($(".plive__alerts", m.el).getBoundingClientRect().height);
    out2.push(r);
  }
}
out.rows = out2;
"""


@pytest.mark.parametrize("width", [1280, 390])
def test_the_view_holds_in_all_four_looks_at_a_wide_and_a_narrow_place(hub, tmp_path, width):
    page = drive(hub, tmp_path, LAYOUT, width=width)
    seen = page["rows"]
    assert {(r["look"], r["width"]) for r in seen} == {(l, w) for l in ("console", "workbench", "palette", "panes") for w in (0, 360)}
    for r in seen:
        where = (width, r["look"], r["width"])
        assert r["page"] is True and r["host"] is True, (where, "the page scrolls sideways", r)
        assert r["outside"] == [], (where, "a control sticks out of the view", r["outside"])
        assert min(r["names"]) >= 90, (where, "a slot's name is squeezed", r["names"])
        assert all(w >= 90 and ok for w, ok in r["used"]), (where, "a usage line is squeezed", r["used"])
        assert max(r["lines"]) < 1.9, (where, "a button is taller than one line and a half", r["lines"])
        assert r["camera"] >= 200 and r["view"] >= 280, (where, r)
