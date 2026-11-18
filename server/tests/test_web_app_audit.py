"""AUT-5 on the web app (design 09 S3.4, 07 section 15): the page audit (tests/page_audit.js) in every view, Console
light and dark, at 1280 px and 320 px, through tests/aut5_run.mjs in a headless Chrome, Edge or Chromium already on
the machine. Example data only (mockups/CONTENT-SPEC.md: "Workshop hub", invented filaments).

Findings of today's markup that a later step rebuilds are listed in tests/allowlists/aut5/; a line nothing matches
fails the run. Skipped when Node 22+ or a Chromium-family browser is missing (the runner exits 2 for "no browser")."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from fakes import serving
from filament_kit import config, intake_history, inventory, modules
from filament_kit.profiles import lines
from filament_kit.spoolman import Spoolman
from filament_kit.web import mcp_tools
from filament_kit.web.intake_app import IntakeApp
from test_web_printers import SERIAL, FakeKit

pytestmark = pytest.mark.browser_audit      # tools/testenv runs the browser audits as a group of 2 workers

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "aut5_run.mjs"
ALLOW = ROOT / "tests" / "allowlists" / "aut5"      # a folder, one file per screen
VIEWS = "#add,#spools,#printers,#recent,#recent,#presets,#settings"     # the Hub tests drive these: PAGES, with the record page as a second #recent (they know no record id; the allow-list counts are for seven views)
PAGES = ("#add", "#spools", "#printers", "#recent", "#recent/{id}", "#presets", "#settings")     # {id}: the seeded record
ALLOW_PRINTERS = ROOT / "tests" / "aut5_allowlist_printers.txt"      # the same list for the run with Printers on (S3.11)
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
         "sealed_location": "Sealed stock"}
FILAMENTS = [("Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E"),
             ("Bambu Lab", "PETG HF Orange", "PETG", "F2762E"),
             ("eSUN", "ABS+ White", "ABS", "F4F4F2"),
             ("Prusament", "PLA Galaxy Silver", "PLA", "8D9199")]


class PrintersKit(FakeKit):
    """The fake kit of test_web_printers with a fuller printers page: four slots (one empty, one in use), a Klipper printer, a
    found Bambu Lab printer, and filament used with the spool it was taken from (example data only)."""

    def __init__(self):
        super().__init__()
        slots = [{"slot": i, "label": f"A{i + 1}", "say": [], "type": "PLA", "color_hex": hx, "active": i == 0, "present": True, "reading": False,
                  "spool": {"id": 7 + i, "name": name, "material": "PLA", "color_hex": hx, "remaining_weight": 612.0 - 100 * i}}
                 for i, (hx, name) in enumerate([("2B2B2E", "Polymaker PolyTerra PLA Charcoal Black"), ("F2762E", "Bambu Lab PETG HF Orange"),
                                                  ("8D9199", "Prusament PLA Galaxy Silver")])]
        slots.append({"slot": 3, "label": "A4", "say": [], "type": "", "color_hex": "", "active": False, "present": False, "reading": False, "spool": None})
        self.status["ams"][0]["slots"] = slots
        self.status["hms"] = [{"code": "0300_0100", "text": "The chamber door is open."}]

    def get(self, path):
        if path == "/api/printers":
            self.calls.append(("GET", path))
            return {"printers": [
                {"id": SERIAL, "name": "Workshop X1", "model": "BL-P001", "model_name": "X1 Carbon", "family": "bambu", "ip": "192.0.2.40", "configured": True,
                 "state": "connected", "camera": {"kind": "mjpeg"}, "pinned": True},
                {"id": "garage-voron", "name": "Garage Voron", "family": "klipper", "host": "192.0.2.57", "configured": True, "state": "connected"},
                {"id": "03W00X123456789", "name": "Study A1", "model_name": "A1 mini", "family": "bambu", "ip": "192.0.2.58", "configured": True, "state": "offline"},
                {"id": "0948ZZ0A0000099", "name": "P1S", "model_name": "P1S", "family": "bambu", "ip": "192.0.2.42", "configured": False, "state": "not_configured"}]}
        if path.startswith(f"/api/printers/{SERIAL}/usage"):
            return {"entries": [{"id": "u1", "at": "2026-11-12T14:05:00", "job": "Benchy", "slot": "A1", "grams": 12.4, "undone": False,
                                 "spool": {"id": 7, "vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black", "material": "PLA", "colour": "2B2B2E", "state": "opened"}},
                                {"id": "u0", "at": "2026-11-10T09:30:00", "job": "Test cube", "slot": "A2", "grams": 5.0, "undone": True, "spool": None}]}
        return super().get(path)


class WaitingKit(PrintersKit):
    """PrintersKit with an assignment waiting on two slots: the empty A4 (the case of the spool put there before it is loaded) and the loaded A2."""

    def __init__(self):
        super().__init__()
        slots = self.status["ams"][0]["slots"]
        slots[1]["pending"] = {"spool_id": 12, "text": "Waiting for A2 to load"}
        slots[3]["pending"] = {"spool_id": 13, "text": "Waiting for the filament in A4"}


class ChangingKit(PrintersKit):
    """PrintersKit that keeps its printer list: an add makes a printer (still connecting, so its page says Added.), a forget removes it."""

    def __init__(self):
        super().__init__()
        self.listed = None

    def get(self, path):
        out = super().get(path)
        if path == "/api/printers":
            if self.listed is None:
                self.listed = out["printers"]
            return {"printers": [dict(p) for p in self.listed]}
        return out

    def post(self, path, body):
        if path == "/api/printers":
            self.get(path)
            if body.get("family") == "klipper":
                new = {"id": "bench-voron", "name": body.get("name") or "Bench Voron", "family": "klipper", "host": body["host"], "configured": True, "state": "connecting"}
                self.listed.append(new)
            else:
                new = next(p for p in self.listed if p["id"] == body["serial"])
                new.update(configured=True, state="connecting", name=body.get("name") or new["name"])
            return {"printer": dict(new)}
        return super().post(path, body)

    def delete(self, path):
        self.get("/api/printers")
        gone = path.rsplit("/", 1)[-1]
        self.listed = [p for p in self.listed if p["id"] != gone]
        return {"ok": True, "id": gone}


# The Slicer presets screen in the states 04 8 draws: filaments waiting for a line (nothing in lines.json), waiting with a
# line of their brand to join (the "Add to the line" select), every filament covered (the empty state), and switched off.
STATES = ("waiting", "waiting-with-a-line", "all-covered", "presets-off", "public-address")

# Recently added (04 7): a record added from two photos, edited by hand twice with the second edit undone (a revision, and
# one struck through), and one added at the Weigh Station with no photo; a seeded record also shows on the public address,
# where the page shows the notice instead
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
                     "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc2000b080001000101011100ffc4001400010000"
                     "0000000000000000000000000000ffda0008010100013f10ffd9")
ITEM = {"vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black", "material": "PLA", "color_hex": "2B2B2E", "net": 1000,
        "tare": 140, "density": 1.31, "count": 2, "nozzle": 220, "bed": 55, "sealed": True, "line": "PolyTerra PLA"}


def _history(sm) -> str:
    intake_history.stash_read("r1", [JPEG, JPEG], {"items": [ITEM]}, "", None)
    made = inventory.add_and_link(sm, [dict(ITEM)], RULES, False, None)
    hid = intake_history.record_save(made.saved, source="phone", read_id="r1")
    intake_history.apply(sm, hid, item=0, values={"tare": 150})
    intake_history.apply(sm, hid, item=0, values={"nozzle": 215})
    intake_history.undo(sm, hid, 2)
    hand = {**ITEM, "vendor": "Bambu Lab", "name": "PETG HF Orange", "material": "PETG", "color_hex": "F2762E", "count": 1}
    intake_history.record_save(inventory.add_and_link(sm, [hand], RULES, False, None).saved, source="station")
    return hid


def _serving(param, tmp_path, monkeypatch, spoolman_url, history):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: False for n in modules.MODES["server"]}
    mods.update(web=True, ai_intake=True, presets=param != "presets-off")
    config.save({"placement": RULES, "modules": mods, "server_name": "Workshop hub", "web": {"lan": ["127.0.0.0/8"]}})
    api = spoolman_url + "/api/v1"
    made = []
    with httpx.Client() as c:
        vendors = {}
        for i, (vendor, name, material, colour) in enumerate(FILAMENTS):
            if vendor not in vendors:
                vendors[vendor] = c.post(api + "/vendor", json={"name": vendor, "empty_spool_weight": 200}).json()["id"]
            f = c.post(api + "/filament", json={"vendor_id": vendors[vendor], "name": name, "material": material,
                                                "color_hex": colour, "density": 1.24, "diameter": 1.75, "weight": 1000,
                                                "spool_weight": 200}).json()
            made.append((vendor, name, material, f["id"]))
            c.post(api + "/spool", json={"filament_id": f["id"], "location": "Rack 1" if i % 2 else "Sealed stock",
                                         "remaining_weight": 1000 - 150 * i})
    if param in ("waiting-with-a-line", "all-covered"):
        used: set[str] = set()
        ls = {}
        for vendor, name, material, fid in made:
            if param == "waiting-with-a-line" and vendor != "Prusament":
                continue
            product = name.rsplit(" ", 1)[0]
            line_id = lines.line_id_for(vendor, product)
            made_id = lines.new_filament_id(used)
            used.add(made_id)
            ls[line_id] = lines.Line(line_id=line_id, vendor=vendor, product=product, material=material, bambu_parent=None,
                                     parent_source="none", filament_id=made_id, created="2026-01-01T00:00:00Z",
                                     filaments=[fid] if param == "all-covered" else [])
        lines.save(ls)
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    hid = _history(sm) if history else None
    if param == "public-address":       # the web unit's page: its address has a path, and it keeps no history (04 7.4)
        site = IntakeApp(mcp_tools.Tools(sm), public_url="https://hub.example.test/f", lan_cidrs=["127.0.0.0/8"], push=False)
        app, path = Starlette(routes=[Mount("/f", routes=site.routes())]), "/f/intake"
    else:
        app, path = Starlette(routes=IntakeApp(mcp_tools.Tools(sm), public_url=None, lan_cidrs=["127.0.0.0/8"], push=False).routes()), "/intake"
    running = serving.start(app)
    try:
        # on the public address a record address shows the same notice as the list, so its page title is the list's: the
        # audit asks for #recent a second time there, to keep every state at the same number of passes
        views = [v.replace("{id}", hid or "") if "{id}" in v and path == "/intake" else "#recent" if "{id}" in v else v for v in PAGES]
        yield SimpleNamespace(url=running.url + path, views=",".join(views), hid=hid)
    finally:
        running.stop()


@pytest.fixture(params=STATES[:4])
def served(request, tmp_path, monkeypatch, spoolman_url):
    """The web app's address as a string, in the four states of the presets screen: what the Hub tests import and drive."""
    for running in _serving(request.param, tmp_path, monkeypatch, spoolman_url, False):
        yield running.url


@pytest.fixture(params=STATES)
def served_web(request, tmp_path, monkeypatch, spoolman_url):
    """The web app with records in Recently added, in every state (and on the web unit's public address): .url, .views, .hid."""
    yield from _serving(request.param, tmp_path, monkeypatch, spoolman_url, True)


def _serve_printers(tmp_path, monkeypatch, spoolman_url, kit):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: False for n in modules.MODES["server"]}
    mods.update(web=True, ai_intake=True, presets=True, printers=True)
    config.save({"placement": RULES, "modules": mods, "server_name": "Workshop hub", "web": {"lan": ["127.0.0.0/8"]}})
    api = spoolman_url + "/api/v1"
    with httpx.Client() as c:
        vendors = {}
        for i, (vendor, name, material, colour) in enumerate(FILAMENTS):
            if vendor not in vendors:
                vendors[vendor] = c.post(api + "/vendor", json={"name": vendor}).json()["id"]
            f = c.post(api + "/filament", json={"vendor_id": vendors[vendor], "name": name, "material": material,
                                                "color_hex": colour, "density": 1.24, "diameter": 1.75, "weight": 1000,
                                                "spool_weight": 200}).json()
            c.post(api + "/spool", json={"filament_id": f["id"], "location": "Rack 1" if i % 2 else "Sealed stock",
                                         "remaining_weight": 1000 - 150 * i})
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    return serving.start(Starlette(routes=IntakeApp(mcp_tools.Tools(sm), public_url=None, lan_cidrs=["127.0.0.0/8"], push=False,
                                                    kit_api=kit()).routes()))


@pytest.fixture
def served_printers(tmp_path, monkeypatch, spoolman_url):
    """The same state with the Printers module on, over a fake kit (no printer, no kit server)."""
    running = _serve_printers(tmp_path, monkeypatch, spoolman_url, PrintersKit)
    try:
        yield running.url + "/intake"
    finally:
        running.stop()


@pytest.fixture
def served_waiting(tmp_path, monkeypatch, spoolman_url):
    running = _serve_printers(tmp_path, monkeypatch, spoolman_url, WaitingKit)
    try:
        yield running.url + "/intake"
    finally:
        running.stop()


@pytest.fixture
def served_changing(tmp_path, monkeypatch, spoolman_url):
    """The Printers module over a kit that keeps what is added and forgotten."""
    running = _serve_printers(tmp_path, monkeypatch, spoolman_url, ChangingKit)
    try:
        yield running.url + "/intake"
    finally:
        running.stop()


class HttpsOrigin:
    """The web app answers a change only from its own https address, and this test's server is plain http: the Origin the browser
    sends is written as https here (shipped code is untouched), so Preview and Add can run in the page."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope["headers"] = [(k, b"https://" + v[len(b"http://"):] if k == b"origin" and v.startswith(b"http://") else v)
                                for k, v in scope["headers"]]
        await self.app(scope, receive, send)


def _serving_add(tmp_path, monkeypatch, spoolman_url, ai):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: False for n in modules.MODES["server"]}
    mods.update(web=True, ai_intake=ai, presets=True)
    config.save({"placement": RULES, "modules": mods, "server_name": "Workshop hub", "web": {"lan": ["127.0.0.0/8"]}})
    api = spoolman_url + "/api/v1"
    with httpx.Client() as c:
        vendors = {}
        for i, (vendor, name, material, colour) in enumerate(FILAMENTS):
            if vendor not in vendors:
                vendors[vendor] = c.post(api + "/vendor", json={"name": vendor, "empty_spool_weight": 200}).json()["id"]
            f = c.post(api + "/filament", json={"vendor_id": vendors[vendor], "name": name, "material": material,
                                                "color_hex": colour, "density": 1.24, "diameter": 1.75, "weight": 1000,
                                                "spool_weight": 200}).json()
            c.post(api + "/spool", json={"filament_id": f["id"], "location": "Rack 1" if i % 2 else "Sealed stock",
                                         "remaining_weight": 1000 - 150 * i})
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    app = Starlette(routes=IntakeApp(mcp_tools.Tools(sm), public_url=None, lan_cidrs=["127.0.0.0/8"], push=False).routes())
    running = serving.start(HttpsOrigin(app))
    try:
        yield running.url + "/intake"
    finally:
        running.stop()


@pytest.fixture
def served_add(tmp_path, monkeypatch, spoolman_url):
    yield from _serving_add(tmp_path, monkeypatch, spoolman_url, True)


@pytest.fixture
def served_off(tmp_path, monkeypatch, spoolman_url):
    """The same Hub with the Label Reader switched off."""
    yield from _serving_add(tmp_path, monkeypatch, spoolman_url, False)


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    major = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0]
    return node if major.isdigit() and int(major) >= 22 else None


def _missing(why: str):
    """No Node 22 or no browser: a skip, or a failure where the run is required (AUT5_REQUIRED=1, e.g. in CI)."""
    if os.environ.get("AUT5_REQUIRED") == "1":
        pytest.fail(f"AUT5_REQUIRED=1 but {why}")
    pytest.skip(why)


def _run(*args: str) -> subprocess.CompletedProcess:
    node = _node()
    if not node:
        _missing("AUT-5 needs Node 22 or later")
    run = subprocess.run([node, str(RUNNER), *args], capture_output=True, encoding="utf-8", timeout=600)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("AUT-5 needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:          # a browser was found but cannot run headless on this machine (its error is shown)
        _missing("AUT-5: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    return run


def test_the_page_audit_passes_on_every_view(served_web):
    run = _run("--url", served_web.url, "--views", served_web.views, "--allow", str(ALLOW))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == len(PAGES) * 2 * 2 and out["failing"] == 0      # seven views, two widths, light and dark



@pytest.mark.parametrize("look", ("console", "palette", "workbench", "panes"))
def test_a_record_opens_with_its_fields_in_every_theme(served_web, request, look):
    """R298: Palette (a sheet), Workbench (a card) and Panes show the record in a dialog or a pane; it must open there with
    the 13 fields of its one saved item, as in Console where it opens in place, and without a page error."""
    if request.node.callspec.params["served_web"] != "waiting":
        pytest.skip("one data state is enough: the themes differ in markup, not in data")
    view = "#recent/" + served_web.hid
    run = _run("--url", served_web.url, "--views", view, "--widths", "375,1280", "--schemes", "light", "--look", look,
               "--count", f"{view}|.kv__row|13", "--allow", str(ALLOW))
    out = json.loads(run.stdout) if run.stdout.strip() else {}
    bad = [f for r in out.get("report", []) for f in r["findings"] if f["check"] in ("view did not show its content", "page error")]
    assert not bad, bad


def test_the_page_audit_passes_on_the_printers_list_and_one_printer(served_printers):
    """S3.11: `#printers` (cards, the found printer) and `#printers/<id>` (status, slots, filament used, mapping, settings), live over the fake kit."""
    run = _run("--url", served_printers, "--views", f"#printers,#printers/{SERIAL}", "--allow", str(ALLOW_PRINTERS), "--settle", "1500")
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == 2 * 2 * 2 and out["failing"] == 0      # two views, two widths, light and dark


FLOWS = ROOT / "tests" / "printers_flow_run.mjs"


def _flow(url: str, flow: str, width: int) -> dict:
    """One flow of the Printers screen in the browser (tests/printers_flow_run.mjs): the address it ends on, what it shows, the page's errors."""
    node = _node()
    if not node:
        _missing("the flow needs Node 22 or later")
    run = subprocess.run([node, str(FLOWS), "--url", url, "--flow", flow, "--width", str(width)], capture_output=True, encoding="utf-8", timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the flow needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("flow: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["errors"] == [] and not out["sideways"], json.dumps(out)
    return out


@pytest.mark.parametrize("flow, width", [("add-found", 375), ("add-klipper", 375), ("add-found", 768), ("add-klipper", 768)])
def test_a_printer_just_added_opens_with_added(served_changing, flow, width):
    """R304 MED 1: the add sheet's own Back lands before the address changes, so the page ends on the new printer (not back on #printers)."""
    out = _flow(served_changing, flow, width)
    assert out["opened"] and out["cardsAfter"] == out["cardsBefore"] + 1, json.dumps(out)
    assert out["hash"].startswith("#printers/") and out["events"][-1] == "hashchange:" + out["hash"], json.dumps(out)
    assert out["added"] and out["title"].startswith(out["h1"] if width <= 600 else "P1S" if flow == "add-found" else "Bench Voron"), json.dumps(out)


@pytest.mark.parametrize("width", [375, 768])
def test_forgetting_a_printer_closes_its_page(served_changing, width):
    """R304 MED 2: at tablet width the open printer can sit at #printers with no id, so no hashchange closes it after Forget."""
    out = _flow(served_changing, "forget", width)
    assert out["openBefore"] and not out["openAfter"] and not out["has404"], json.dumps(out)
    assert out["hash"] == "#printers" and "Workshop X1" not in out["cardsAfter"] and len(out["cardsAfter"]) == 2, json.dumps(out)
    if width > 600:
        assert out["hashBefore"] == "#printers", out        # the case that has no hashchange to rely on


@pytest.mark.parametrize("width", [375, 768])
def test_a_slot_with_a_waiting_assignment_says_so_in_its_row(served_waiting, width):
    """15b: the slot's `pending` text is shown in the new slot row, on the loaded slot and on the empty one; the others show nothing of it."""
    rows = {r["label"]: r for r in _flow(served_waiting, "waiting", width)["rows"]}
    assert rows["A2"]["waiting"] == ["Waiting for A2 to load"] and rows["A2"]["name"] == "Bambu Lab PETG HF Orange", rows
    assert rows["A4"]["waiting"] == ["Waiting for the filament in A4"] and rows["A4"]["name"] == "Empty", rows
    assert rows["A1"]["waiting"] == [] and rows["A3"]["waiting"] == [], rows


def test_an_address_for_no_printer_does_not_put_its_id_in_the_heading_or_title(served_printers):
    out = _flow(served_printers, "unknown", 375)
    assert "NOPE123" not in out["h1"] + out["title"] and "No such printer" in out["h1"], json.dumps(out)


@pytest.mark.parametrize("allow", [ALLOW, ALLOW_PRINTERS], ids=lambda p: p.name)
def test_the_allow_list_names_a_later_step_and_a_count_on_every_line(allow):
    text = "".join(f.read_text(encoding="utf-8") for f in sorted(allow.glob("*.txt"))) if allow.is_dir() else allow.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            check, where, count, reason = (x.strip() for x in line.split("|"))
            assert check and where and count.isdigit() and int(count) > 0 and "rebuilt by S3." in reason, line


# ---- Add spools (design 09 S3.8): every state of 04 4, driven in the page and audited -------------------------------------
# The Label Reader is not run here: the page's fetch answers `read` with a made-up reading (a small stand-in the state's
# script puts in), everything else (find, vendors, preview, add) is the real Hub on a fake Spoolman. A state script throws
# when the page is not in the state it names, then the runner audits that state at 1280 px and 320 px, light and dark.

READING = {"read_id": "r-1", "reader": "cloud", "tier": None, "confidence": None, "unsure": False, "confidence_rated": True,
           "engine": {"reader": "cloud", "model": "model-name", "tier": None},
           "confidence_summary": {"level": "low", "low": ["tare"], "medium": ["color_hex", "density"], "not_on_label": ["price_per_kg"]},
           "usage": {"model": "model-name", "input_tokens": 1800, "cached": 1200, "output_tokens": 240},
           "questions": ["Are the two orange spools the same lot?"], "note": "",
           "tag": {"nfc_id": "04:77:90:E", "age_seconds": 40, "reader": "station"}, "scale": {"grams": 1212, "age_seconds": 8},
           "items": [
               {"vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black", "material": "PLA", "net": 1000, "tare": 200, "density": 1.24,
                "count": 1, "color_hex": "2B2B2E", "color_name": "Charcoal", "color_family": "black", "sealed": False, "gross": 1212, "photos": [0], "estimates": ["density"],
                "price_line": "Price: $19.99/kg - order of 2026-10-02", "price_per_kg": 19.99, "existing_filament_id": None,
                "confidence_levels": {"vendor": "high", "name": "high", "material": "high", "color_hex": "medium", "net": "high",
                                      "tare": "high", "density": "medium", "nozzle": "high", "bed": "high", "price_per_kg": "high"}},
               {"vendor": "Bambu Lab", "name": "PETG HF Orange", "material": "PETG", "net": 1000, "tare": 250, "density": 1.27,
                "count": 2, "color_hex": "F2762E", "sealed": True, "sealed_reason": "The bag is closed.", "photos": [1], "estimates": ["tare"],
                "price_line": "", "existing_filament_id": None,
                "confidence_levels": {"vendor": "high", "name": "high", "material": "high", "color_hex": "high", "net": "high",
                                      "tare": "low", "density": "high", "nozzle": "high", "bed": "high", "price_per_kg": "not_on_label"}}]}
UNRATED = {**READING, "confidence_rated": False, "confidence_summary": {"level": "not_rated", "low": [], "medium": ["tare"], "not_on_label": []},
           "tag": None, "scale": None, "questions": [],
           "items": [{**i, "confidence_levels": {k: (None if v in ("high", "low") else v) for k, v in i["confidence_levels"].items()}} for i in READING["items"]]}

PRELUDE = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (what, fn, ms = 10000) => { const t0 = Date.now(); for (;;) { const v = fn(); if (v) return v; if (Date.now() - t0 > ms) throw new Error('Add spools: ' + what); await sleep(50); } };
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const text = (s) => ($(s) ? $(s).textContent.replace(/\s+/g, ' ').trim() : '');
const need = (what, ok) => { if (!ok) throw new Error('Add spools: ' + what); };
const typeIn = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); };
const reply = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const stub = (path, answer) => { const real = window.fetch.bind(window); window.fetch = (u, i) => (String(u).includes('/api/' + path) ? answer(u, i) : real(u, i)); };
const photo = async (n) => { const c = document.createElement('canvas'); c.width = 80; c.height = 60; const g = c.getContext('2d'); g.fillStyle = ['#c0392b', '#2980b9', '#27ae60'][n % 3]; g.fillRect(0, 0, 80, 60); const b = await new Promise((ok) => c.toBlob(ok, 'image/jpeg')); return new File([b], 'label' + n + '.jpg', { type: 'image/jpeg' }); };
const give = async (n) => { const dt = new DataTransfer(); for (let i = 0; i < n; i++) dt.items.add(await photo(i)); const want = Math.min(8, $$('.add__photo').length + n), input = $('input[type=file][multiple]'); input.files = dt.files; input.dispatchEvent(new Event('change', { bubbles: true })); await until('the photos', () => $$('.add__photo').length === want); };
const button = (label, root = document) => $$('button', root).find((b) => b.textContent.trim() === label);
const field = (label, root = document) => $$('.field', root).find((f) => f.querySelector('.field__label').firstChild.textContent.trim() === label);
const search = async (q) => { typeIn($('.add__search .field__control'), q); await until('no rows for ' + q, () => $('.add__row') || $('.add__none'), 6000); };
const waitPage = () => until('the page did not draw', () => $('.add__bar-text') && !document.querySelector('[aria-busy="true"]:not(button)'));
const newFilament = async (vendor, name, material, tare) => {
  button('New filament').click();
  const card = $$('.add__card').pop();
  typeIn(field('Brand', card).querySelector('input'), vendor);
  typeIn(field('Name', card).querySelector('input'), name);
  typeIn(field('Material', card).querySelector('input'), material);
  if (tare) typeIn(field('Empty spool weight', card).querySelector('input'), tare);
  return card;
};
const sent = [];                                                         // the bodies of the calls to `add`, in order
const gate = () => { let release; const wait = new Promise((r) => { release = r; }); return { wait, release }; };
const ITEMS = [{ index: 0, vendor: 'Elegoo', name: 'PLA Red', filament: 'new', filament_id: null, new_vendor: false, spools: 1, spool_ids: [], location: 'Sealed stock', placements: [{ location: 'Sealed stock', spools: 1, placed_by: null }], opened: false, remaining_g: 1000, problems: [] }];
const PREVIEWED = () => reply({ exit_code: 0, output: 'Would add 1 spool of Elegoo PLA Red', items: ITEMS, dry: true });
const ADDED = () => reply({ exit_code: 0, output: 'Added 1 spool of Elegoo PLA Red', spool_ids: [7], items: ITEMS.map((i) => ({ ...i, spool_ids: [7] })) });
const spyAdd = (answer) => { const real = window.fetch.bind(window); window.fetch = (u, i) => { if (String(u).includes('/api/add')) { sent.push(JSON.parse(i.body)); return answer ? answer(sent.length) : real(u, i); } return real(u, i); }; };
const busy = () => $('.add__bar-btn').getAttribute('aria-busy') === 'true';
const reading = async (answer) => { stub('read', answer); await give(2); button('Read labels').click(); };
"""

READY = {
    "empty": r"""
  await waitPage();
  need('the intro', text('.add__intro').includes('Nothing is saved until you preview and press Add.'));
  need('the empty state', text('.add').includes('No spools yet. Photograph the labels, or find a filament you already have.'));
  need('the bar says what to do', text('.add__bar-text') === 'Add a spool first: photograph a label or find a filament.');
  need('Preview is aria-disabled and described by the bar', $('.add__bar-btn').getAttribute('aria-disabled') === 'true' && $('.add__bar-btn').getAttribute('aria-describedby') === $('.add__bar-text').id);
  need('the photo group comes first', $('.add__inputs').firstElementChild.querySelector('.add__buttons'));
  need('Read labels says why', text('.add__read').includes('Add a photo first.') && $('.add__read .btn').getAttribute('aria-disabled') === 'true');
  need('the title takes the focus order: one h1', $$('h1').length === 1);
""",
    "results": r"""
  await waitPage(); await search('pla');
  need('two rows for pla', $$('.add__row').length === 2);
  need('a swatch and a filament number in a row', $('.add__row .swatch') && /^F\d+$/.test(text('.add__row-id')));
  need('the row says material, weight and spools', /PLA · 1000 g · 1 spool/.test(text('.add__row-text')));
  typeIn($('.add__search .field__control'), 'zzzz');
  await until('no match', () => $('.add__none'), 6000);
  need('no match says so, with the button', text('.add__none').startsWith('No filament matches. Use New filament.') && button('New filament', $('.add__none')));
""",
    "cards": r"""
  await waitPage(); await search('pla');
  $('.add__row').click();
  await newFilament('', '', '');
  const cards = $$('.add__card');
  need('two cards', cards.length === 2);
  need('the first is collapsed and the second open', cards[0].querySelector('.add__body').hidden && !cards[1].querySelector('.add__body').hidden);
  need('the first says existing filament', /Existing filament F\d+/.test(cards[0].textContent));
  need('the second says what it needs', cards[1].textContent.includes('Needs: Brand, Name, Material'));
  need('the bar names the spool', text('.add__bar-text') === 'Spool 2 needs: Brand, Name, Material.');
  $('.add__bar-btn').click();
  need('pressing Preview focuses Brand', document.activeElement.closest('.field').querySelector('.field__label').textContent.startsWith('Brand'));
  $('button[aria-label="Edit Polymaker PolyTerra PLA Charcoal Black"]').click();
  need('the expand button opens the card', !cards[0].querySelector('.add__body').hidden);
""",
    "photos": r"""
  await waitPage(); await give(2);
  await until('two photos', () => $$('.add__photo').length === 2);
  need('the count', text('.add__photo-count') === '2 of 8 photos');
  need('Read labels is the filled button now', button('Read labels').classList.contains('btn--primary') && !button('Take photo').classList.contains('btn--primary'));
  need('a thumbnail and its own remove button', $('.add__thumb').getAttribute('aria-label') === 'Photo 1 of 2, enlarge' && $$('.add__photo .btn--icon')[1].getAttribute('aria-label') === 'Remove photo 2 of 2');
  typeIn($('.add__read').closest('.group__body').querySelector('textarea'), 'e.g. 3 of the grey ones');
  need('Read labels is available', $('.add__read .btn').getAttribute('aria-disabled') !== 'true');
""",
    "photo_limit": r"""
  await waitPage(); await give(8);
  await until('eight photos', () => $$('.add__photo').length === 8);
  need('the count', text('.add__photo-count') === '8 of 8 photos');
  need('both buttons say why', ['Take photo', 'Choose photos'].every((l) => button(l).getAttribute('aria-disabled') === 'true') && text('.add__limit') === '8 photos at a time. Remove one to add another.');
  await give(1);
  need('a ninth is not added', $$('.add__photo').length === 8);
""",
    "photo_viewer": r"""
  await waitPage(); await give(2);
  await until('two photos', () => $$('.add__photo').length === 2);
  $$('.add__thumb')[1].click();
  await until('the viewer', () => $('dialog[open] .add__big'));
  need('titled by position, with Remove this photo and Close', text('dialog[open] .sheet__title') === 'Photo 2 of 2' && button('Remove this photo') && button('Close', $('dialog[open]')));
""",
    "photo_removed": r"""
  await waitPage(); await give(3);
  await until('three photos', () => $$('.add__photo').length === 3);
  $$('.add__photo .btn--icon')[1].click();
  need('two left and the toast offers Undo', $$('.add__photo').length === 2 && button('Undo', $('.toasts')));
  button('Undo', $('.toasts')).click();
  need('Undo puts it back', $$('.add__photo').length === 3);
  $$('.add__photo .btn--icon')[0].click();
""",
    "reading": r"""
  await waitPage(); stub('read', () => new Promise(() => {})); await give(2);
  button('Read labels').click();
  await until('the reading line', () => text('.add__read').includes('The Label Reader is reading 2 photos… (up to a minute)'));
  need('the button shows Reading…', button('Reading…') && button('Reading…').getAttribute('aria-busy') === 'true');
  need('the bar waits for the Label Reader', text('.add__bar-text') === 'Wait for the Label Reader.');
  need('the photo buttons stay usable', button('Choose photos').getAttribute('aria-disabled') !== 'true');
""",
    "read_summary": r"""
  await waitPage(); await reading(() => reply(%(READING)s));
  await until('the cards', () => $$('.add__card').length === 2);
  const found = $('.group[aria-labelledby]:not(.add__group:first-child)') && $$('.group').find((g) => g.textContent.includes('What the Label Reader found'));
  need('the summary group', found);
  const t = found.textContent.replace(/\s+/g, ' ');
  for (const part of ['Found 2 spools in 2 photos.', 'Label Reader: Cloud (Claude) · model-name', 'Low: check Empty spool weight', 'Medium: Colour, Density', 'Not on the label: Price per kg',
    'The Label Reader asks', 'Are the two orange spools the same lot?', 'Tag 04:77:90:E was tapped 40 s before the photos on the Weigh Station', 'Weigh Station scale: 1212 g, 8 s ago (not used: only for one opened spool).'])
    need('the summary says "' + part + '"', t.includes(part));
  need('Details hold the tokens', found.querySelector('details').textContent.includes('1800 tokens in (1200 cached), 240 out'));
  const [one, two] = $$('.add__card');
  need('both cards open: both need a look', !one.querySelector('.add__body').hidden && !two.querySelector('.add__body').hidden);
  need('the colour carries its Medium mark', field('Colour', one).querySelector('.add__mark').textContent.includes('Medium'));
  need('the reader\'s colour name and family are read facts', field('Colour', one).textContent.includes('Colour: Charcoal (black)'));
  need('a medium field says to check it', field('Colour', one).textContent.includes('The Label Reader was not sure: check this.'));
  need('an estimate says so', field('Density', one).textContent.includes('Estimated by the Label Reader: not printed on the label.'));
  need('a low field has the Low mark', field('Empty spool weight', two).querySelector('.add__mark').textContent.includes('Low: check this'));
  need('not on the label has its mark', field('Price per kg', two).querySelector('.add__mark').textContent.includes('Not on the label'));
  need('the price line is the helper', field('Price per kg', one).textContent.includes('From the label: $19.99/kg - order of 2026-10-02'));
  need('the sealed reason is under the toggle', two.textContent.includes('Label Reader: The bag is closed.'));
  need('an opened spool has its weight', field('Weight with spool', one) && !field('Weight with spool', one).hidden && field('Weight with spool', two).hidden);
  need('the summary line of a card', one.querySelector('.add__sum').textContent.includes('Opened, 1212 g on the scale'));
  need('the bar counts the fields to check', text('.add__bar-text') === '3 fields to check · 3 spools · not previewed');
  typeIn(field('Colour', one).querySelector('input'), '#2B2B2F');
  need('an edit clears the mark and the hint', !field('Colour', one).querySelector('.add__mark') && !field('Colour', one).textContent.includes('not sure'));
""" % {"READING": json.dumps(READING)},
    "read_unrated": r"""
  await waitPage(); await reading(() => reply(%(UNRATED)s));
  await until('the cards', () => $$('.add__card').length === 2);
  const found = $$('.group').find((g) => g.textContent.includes('What the Label Reader found')).textContent.replace(/\s+/g, ' ');
  need('not rated, then the medium fields', found.includes('Not rated') && found.includes('Medium: Colour, Density'));
  need('the reader says it does not rate', found.includes('This reader does not say how sure it is. Check the values against the label.'));
  need('no High mark on an unrated field', !$$('.add__card .status').some((s) => s.textContent.trim() === 'High'));
""" % {"UNRATED": json.dumps(UNRATED)},
    "read_limit": r"""
  await waitPage(); stub('read', () => reply({ error: "Today's label reads on the Hub are used up." }, 429)); await give(2);
  button('Read labels').click();
  await until('the line', () => $('.add__read [data-state=bad]'));
  need('the Hub text, then the way on', text('.add__read').includes("Today's label reads on the Hub are used up. Add by hand, or try again tomorrow."));
  need('the photos are kept', $$('.add__photo').length === 2);
""",
    "read_failed": r"""
  await waitPage(); stub('read', () => reply({ error: 'The Label Reader did not answer.', read_id: null }, 502)); await give(2);
  button('Read labels').click();
  await until('the line', () => $('.add__read [data-state=bad]'));
  need('the Hub text, then the photos are kept, with Try again', text('.add__read').includes('The Label Reader did not answer. Your photos and edits are kept.') && button('Try again', $('.add__read')));
""",
    "read_replace": r"""
  await waitPage(); await reading(() => reply(%(READING)s));
  await until('the cards', () => $$('.add__card').length === 2);
  typeIn(field('Brand', $$('.add__card')[0]).querySelector('input'), 'Polymaker Edited');
  button('Read labels').click();
  await until('the sheet', () => $('dialog[open]'));
  need('it asks before replacing', text('dialog[open] .dialog__title') === 'Replace the spools from the last read?' && text('dialog[open] .dialog__text').startsWith('You changed 1 spool from the last read.'));
  need('Keep them and Read and replace', button('Keep them', $('dialog[open]')) && button('Read and replace', $('dialog[open]')));
""" % {"READING": json.dumps(READING)},
    "preview": r"""
  await waitPage(); await search('galaxy'); $('.add__row').click();
  need('ready to preview', text('.add__bar-text') === '1 spool · not previewed');
  $('.add__bar-btn').click();
  await until('the preview', () => $('.add__result-row'));
  need('the result group', text('.add__results').includes('Existing filament F') && text('.add__results').includes('1 spool') && text('.add__results').includes('Sealed'));
  await until('the line under the button', () => text('.add').includes('Preview ready. Nothing is saved yet.'));      // the shared result line is drawn a moment after the rows
  need('nothing is saved yet', text('.add').includes('Nothing is saved yet.') && text('.add').includes('Preview ready. Nothing is saved yet.'));
  need('the bar offers Add', text('.add__bar-text') === 'Preview ready: 1 spool.' && $('.add__bar-btn').textContent.trim() === 'Add 1 spool');
  need('the Hub text is under the line', $('.add__results').closest('.group').querySelector('.code'));
  typeIn(field('Net weight', $('.add__card')).querySelector('input'), '900');
  need('an edit makes it out of date', text('.add__bar-text') === 'You changed spool 1. Preview again.' && $('.add__bar-btn').textContent.trim() === 'Preview' && !$('.add__result-row'));
  $('.add__bar-btn').click();
  await until('the preview again', () => $('.add__result-row'));
""",
    "preview_problems": r"""
  await waitPage(); await newFilament('Elegoo', 'PLA Red', 'PLA', '');
  need('the card is ready for Preview', text('.add__bar-text') === '1 spool · not previewed');
  $('.add__bar-btn').click();
  await until('the problem at its field', () => { const f = field('Empty spool weight'); return f && !f.querySelector('.field__error').hidden; });
  need('the sentence is at the field, which has the focus', field('Empty spool weight').querySelector('.field__error').textContent.includes('tare') && document.activeElement === field('Empty spool weight').querySelector('input'));
  need('the bar says what to do', text('.add__bar-text') === 'The Hub found problems. Fix them and preview again.');
  need('no results beside the problems', !$('.add__result-row'));
  typeIn(field('Empty spool weight').querySelector('input'), '160');
  need('an edit clears the sentence', field('Empty spool weight').querySelector('.field__error').hidden);
""",
    "added": r"""
  const stamp = String(Date.now());                          // each pass of the run adds a brand and a filament of its own
  await waitPage(); await newFilament('Elegoo' + stamp, 'PLA Red' + stamp, 'PLA', '160');
  $('.add__bar-btn').click();
  await until('the preview', () => $('.add__result-row'));
  need('a new filament, and a new brand', text('.add__results').includes('New filament') && text('.add__results').includes('New brand'));
  $('.add__bar-btn').click();
  await until('the add', () => $('.add__added .group') && text('.add__added').includes('Added 1 spool:'));
  const done = text('.add__added');
  need('the group says what was added', done.includes('Spools added') && /Added 1 spool: \d+\./.test(done));
  need('new filaments need a preset line', done.includes('1 new filament needs a preset line.') && button('Set up Slicer presets', $('.add__added')));
  need('the add is cleared', !$$('.add__card').length && text('.add__bar-text') === 'Add a spool first: photograph a label or find a filament.');
  need('no draft is left', !localStorage.getItem('spoolwarden.draft.add'));
""",
    "draft": r"""
  await waitPage();
  if (!localStorage.getItem('spoolwarden.draft.add')) {               // the first pass keeps a draft; the later passes load it
    await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
    await until('the draft is kept', () => localStorage.getItem('spoolwarden.draft.add'));
    return;
  }
  need('the draft banner', text('.add__draft').includes('You have a draft from') && /1 spool\./.test(text('.add__draft')));
  need('Restore them and Discard', button('Restore them', $('.add__draft')) && button('Discard', $('.add__draft')));
  need('the Add destination has its badge', $('.nav__item[href="#add"] .nav__badge').textContent === '1' && $('.nav__item[href="#add"]').getAttribute('aria-label') === 'Add, 1 spool waiting');
  need('nothing is drawn yet', !$$('.add__card').length);
""",
    "draft_restored": r"""
  await waitPage();
  if (!localStorage.getItem('spoolwarden.draft.add')) {
    await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
    await until('the draft is kept', () => localStorage.getItem('spoolwarden.draft.add'));
    return;
  }
  button('Restore them').click();
  await until('the card', () => $$('.add__card').length === 1);
  need('the values are back', field('Brand', $('.add__card')).querySelector('input').value === 'Elegoo' && field('Empty spool weight', $('.add__card')).querySelector('input').value === '160');
  need('the banner is gone and the bar is not previewed', !button('Discard', $('.add__draft')) && text('.add__bar-text') === '1 spool · not previewed');
""",
    "draft_discard": r"""
  await waitPage();
  if (!localStorage.getItem('spoolwarden.draft.add')) {
    await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
    await until('the draft is kept', () => localStorage.getItem('spoolwarden.draft.add'));
    return;
  }
  button('Discard', $('.add__draft')).click();
  await until('the sheet', () => $('dialog[open]'));
  need('it asks', text('dialog[open] .dialog__title') === 'Discard this add?' && text('dialog[open] .dialog__text').startsWith('The 1 spool on this phone is deleted.') && button('Keep', $('dialog[open]')));
""",
    "draft_other_tab": r"""
  await waitPage(); await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  window.dispatchEvent(new StorageEvent('storage', { key: 'spoolwarden.draft.add', storageArea: localStorage }));
  need('this tab says it no longer keeps the draft', text('.add__notes').includes('This add is also open in another tab, which now keeps it. Reload this tab to continue here.'));
""",
    "draft_no_storage": r"""
  await waitPage();
  Storage.prototype.setItem = function () { throw new DOMException('full', 'QuotaExceededError'); };
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  await until('the notice', () => text('.add__notes').includes('This browser cannot keep a draft. Finish before leaving the page.'), 4000);
""",
    "card_removed": r"""
  await waitPage(); await search('pla'); $('.add__row').click();
  button('Remove', $('.add__card')).click();
  need('the card is gone and the toast offers Undo', !$$('.add__card').length && button('Undo', $('.toasts')));
  button('Undo', $('.toasts')).click();
  need('Undo puts it back', $$('.add__card').length === 1);
""",
    "sends": r"""
  await waitPage(); spyAdd(); const stamp = String(Date.now());
  const card = await newFilament('Elegoo' + stamp, 'PLA Red' + stamp, 'PLA', '160');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  need('the preview sends dry_run true, no tag and no read', sent.length === 1 && sent[0].dry_run === true && sent[0].link_tag === null && sent[0].read_id === null && sent[0].items.length === 1);
  const it = sent[0].items[0];
  need('the page\'s own keys stay home', !Object.keys(it).some((k) => k[0] === '_'));
  need('the values are the card\'s', it.vendor === 'Elegoo' + stamp && it.name === 'PLA Red' + stamp && it.material === 'PLA' && it.count === 1 && it.net === 1000 && it.tare === 160 && it.density === 1.24 && it.sealed === true && it.location === 'Sealed stock' && it.hand === true && it.match === 'new filament');
  $('.add__bar-btn').click(); await until('the add', () => text('.add__added').includes('Added 1 spool:'));
  need('the add sends the same items with dry_run false', sent.length === 2 && sent[1].dry_run === false && JSON.stringify(sent[1].items) === JSON.stringify(sent[0].items));
""",
    "edit_during_add": r"""
  await waitPage(); const g = gate(); let n = 0;
  stub('add', async () => { n++; if (n === 2) await g.wait; return n === 1 ? PREVIEWED() : ADDED(); });
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  $('.add__bar-btn').click(); await until('the add is under way', busy);
  typeIn(field('Net weight', $('.add__card')).querySelector('input'), '900');          // an edit while the Hub writes
  button('New filament').click();
  g.release();
  await until('the result', () => text('.add__added').includes('Added 1 spool:'));
  need('the result is the Add\'s, not "null"', text('.add__added').includes('Spools added') && !text('.add__added').split(' ').includes('null') && !text('.add').includes('null'));
  need('the sent card is gone, the one added meanwhile stays (it was not sent)', $$('.add__card').length === 1 && $('.add__card').textContent.includes('New spool') && !!localStorage.getItem('spoolwarden.draft.add'));
  need('nothing offers a second Add of the sent spool: the bar asks for a preview', $('.add__bar-btn').textContent.trim() === 'Preview' && n === 2);
""",
    "edit_during_preview": r"""
  await waitPage(); const g = gate(); let n = 0; const bodies = [];
  stub('add', async (u, i) => { bodies.push(JSON.parse(i.body)); n++; if (n === 1) await g.wait; return PREVIEWED(); });
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  $('.add__bar-btn').click(); await until('the preview is under way', busy);
  typeIn(field('Spools', $('.add__card')).querySelector('input'), '3');
  g.release(); await until('the answer', () => !busy());
  need('what was checked is not taken as previewed', text('.add__bar-text') === 'You changed spool 1. Preview again.' && $('.add__bar-btn').textContent.trim() === 'Preview' && !$('.add__result-row'));
  $('.add__bar-btn').click(); await until('the second preview', () => $('.add__result-row'));
  need('it checks the spools as they are now, and still only previews', bodies.length === 2 && bodies[1].dry_run === true && bodies[1].items[0].count === 3 && text('.add__bar-text') === 'Preview ready: 3 spools.');
""",
    "add_failed": r"""
  await waitPage(); const bodies = [];
  stub('add', (u, i) => { bodies.push(JSON.parse(i.body)); return bodies.length === 2 ? reply({ error: 'Spoolman is down.' }, 502) : PREVIEWED(); });
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  need('Add is offered', $('.add__bar-btn').textContent.trim() === 'Add 1 spool');
  $('.add__bar-btn').click(); await until('the failure', () => $('.add__added, .add [data-state=bad]') && text('.add').includes('Spoolman is down.'));
  need('the bar goes back to Preview, with the cards as they were', $('.add__bar-btn').textContent.trim() === 'Preview' && text('.add__bar-text') !== 'Preview ready: 1 spool.' && $$('.add__card').length === 1);
  $('.add__bar-btn').click(); await until('the next press', () => bodies.length === 3);
  need('that press is a preview, not an Add', bodies[1].dry_run === false && bodies[2].dry_run === true);
""",
    "sealed_gross": r"""
  await waitPage(); spyAdd(); const stamp = String(Date.now());
  const card = await newFilament('Elegoo' + stamp, 'PLA Red' + stamp, 'PLA', '160');
  const toggle = $('.toggle__input', card);
  toggle.click(); typeIn(field('Weight with spool', card).querySelector('input'), '700'); toggle.click();         // opened, a weight, sealed again
  need('sealed again hides the weight', toggle.checked && field('Weight with spool', card).hidden);
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  need('a sealed card sends no weight', sent.length === 1 && !('gross' in sent[0].items[0]) && !text('.add__results').includes('700'));
""",
    "numbers_and_colours": r"""
  await waitPage(); spyAdd(); const stamp = String(Date.now());
  const card = await newFilament('Elegoo' + stamp, 'PLA Red' + stamp, 'PLA', '160');
  typeIn(field('Net weight', card).querySelector('input'), '1,000');
  typeIn(field('Colour', card).querySelector('input'), 'F2762EFF');
  need('1,000 is a thousand and has no error', field('Net weight', card).querySelector('.field__error').hidden && field('Colour', card).querySelector('.field__error').hidden);
  need('an 8-digit colour is shown whole', $('.add__sum', card).textContent.includes('#F2762EFF'));
  need('the summary line says 1000 g', $('.add__sum', card).textContent.includes('1000 g'));
  typeIn(field('Net weight', card).querySelector('input'), '1,5');
  need('1,5 is one and a half', $('.add__sum', card).textContent.includes('1.5 g'));
  typeIn(field('Net weight', card).querySelector('input'), '1,000');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  need('the Hub got net 1000 and the 8-digit colour', sent[0].items[0].net === 1000 && sent[0].items[0].color_hex === 'F2762EFF');
""",
    "draft_waiting": r"""
  await waitPage(); const KEY = 'spoolwarden.draft.add', NEW = KEY + '-new';
  if (!localStorage.getItem(KEY)) { await newFilament('Elegoo', 'PLA Red', 'PLA', '160'); await until('the draft is kept', () => localStorage.getItem(KEY)); return; }
  const before = localStorage.getItem(KEY), waiting = JSON.parse(before).items.length;
  need('the draft banner waits', text('.add__draft').includes('You have a draft from'));
  await newFilament('Extra', 'Spool', 'PLA', '160');
  await until('the new work is kept in a slot of its own', () => localStorage.getItem(NEW));
  need('the waiting draft is not written over', localStorage.getItem(KEY) === before && JSON.parse(localStorage.getItem(NEW)).items.length === 1);
  need('the badge counts both', $('.nav__item[href="#add"] .nav__badge').textContent === String(waiting + 1));
""",
    "draft_corrupt": r"""
  await waitPage(); const KEY = 'spoolwarden.draft.add';
  if (!sessionStorage.getItem('s38-corrupt')) {                         // the first pass leaves bad drafts; the next ones load the page with them
    sessionStorage.setItem('s38-corrupt', '1');
    localStorage.setItem(KEY, JSON.stringify({ v: 1, items: [null, 7, 'x'] })); localStorage.setItem(KEY + '-new', 'not json');
    return;
  }
  need('the page started and says nothing of the bad drafts', $('.add__bar-text') && !$('.add__draft .banner'));
  need('the unusable second slot is dropped, the odd entries are not used', !localStorage.getItem(KEY + '-new') && !$$('.add__card').length);
""",
    "draft_partial": r"""
  await waitPage(); const KEY = 'spoolwarden.draft.add';
  if (!sessionStorage.getItem('s38-partial')) {                         // a draft of a read whose summary has no questions
    sessionStorage.setItem('s38-partial', '1');
    localStorage.setItem(KEY, JSON.stringify({ v: 1, started: Date.now(), changed: Date.now(), readId: 'r-1', tag: null, note: '',
      items: [null, { vendor: 'Elegoo', name: 'PLA Red', material: 'PLA', count: 1, net: 1000, tare: 160, density: 1.24, sealed: true, location: 'Sealed stock', hand: true, estimates: [], photos: [], _levels: 'x' }],
      found: { count: 1, photos: 1, reader: 'cloud', model: 'model-name' } }));
    return;
  }
  need('the draft is offered', text('.add__draft').includes('You have a draft from') && /1 spool\./.test(text('.add__draft')));
  button('Restore them').click(); await until('the card', () => $$('.add__card').length === 1);
  need('the summary is back, without questions', text('.group:has(.add__summary), .add').includes('What the Label Reader found') || $$('.group').some((g) => g.textContent.includes('What the Label Reader found')));
""",
    "read_retry": r"""
  await waitPage(); const reads = [];
  stub('read', (u, i) => { reads.push(i.body.getAll('photos').length); return reads.length === 1 ? reply({ error: 'The Label Reader did not answer.', read_id: null }, 502) : new Promise(() => {}); });
  await give(2); button('Read labels').click();
  await until('the failure', () => button('Try again', $('.add__read')));
  $$('.add__photo .btn--icon')[0].click();                              // a photo goes before trying again
  button('Try again', $('.add__read')).click();
  await until('the second read', () => reads.length === 2);
  need('it is a read again: the bar waits, with the photos there now', reads[1] === 1 && text('.add__bar-text') === 'Wait for the Label Reader.' && button('Reading…'));
""",
    "decimal_commas": r"""
  await waitPage(); spyAdd(); const stamp = String(Date.now());
  const card = await newFilament('Elegoo' + stamp, 'PLA Red' + stamp, 'PLA', '160');
  typeIn(field('Density', card).querySelector('input'), '1,240');
  need('in a decimal field the comma is the point: 1,240 is 1.24', field('Density', card).querySelector('.field__error').hidden);
  typeIn(field('Net weight', card).querySelector('input'), '1.000');
  need('1.000 g is flagged, not read as 1 g', !field('Net weight', card).querySelector('.field__error').hidden && field('Net weight', card).querySelector('.field__error').textContent.includes('Enter grams as a plain number, e.g. 1000.'));
  need('the bar says the same as the field', text('.add__bar-text') === 'Spool 1, Net weight: Enter grams as a plain number, e.g. 1000.');
  typeIn(field('Net weight', card).querySelector('input'), '2.500');
  need('2.500 g is flagged too, not read as 2.5 g', !field('Net weight', card).querySelector('.field__error').hidden && text('.add__bar-text').includes('Enter grams as a plain number'));
  typeIn(field('Net weight', card).querySelector('input'), '0,500');
  need('0,500 g is a half gram, not 500', $('.add__sum', card).textContent.includes('0.5 g'));
  typeIn(field('Spools', card).querySelector('input'), '1,000');
  need('a whole-number field refuses a comma, in words', !field('Spools', card).querySelector('.field__error').hidden && field('Spools', card).querySelector('.field__error').textContent.includes('Enter a whole number, 1 or more.')
    && text('.add__bar-text').startsWith('Spool 1, Spools:'));
  typeIn(field('Spools', card).querySelector('input'), '1');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  need('the Hub got density 1.24 and net 0.5', sent[0].items[0].density === 1.24 && sent[0].items[0].net === 0.5);
""",
    "preview_then_read": r"""
  await waitPage(); stub('add', () => PREVIEWED()); stub('read', () => reply(%(READING)s));
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  await give(2); button('Read labels').click();
  await until('the cards of the read', () => $$('.add__card').length === 3);
  need('a read that changes the cards ends the preview', !$('.add__result-row') && !text('.add').includes('Preview ready. Nothing is saved yet.') && text('.add__bar-text').includes('not previewed') && $('.add__bar-btn').textContent.trim() === 'Preview');
""" % {"READING": json.dumps(READING)},
    "undo_during_add": r"""
  await waitPage(); const g = gate(); let n = 0;
  stub('add', async () => { n++; if (n === 2) await g.wait; return n === 1 ? PREVIEWED() : ADDED(); });
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  await newFilament('Extra', 'Spool', 'PLA', '160');
  button('Remove', $$('.add__card')[1]).click();                        // a card removed; its toast offers Undo
  need('one card left, and Undo is offered', $$('.add__card').length === 1 && button('Undo', $('.toasts')));
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  $('.add__bar-btn').click(); await until('the add is under way', busy);
  button('Undo', $('.toasts')).click();                                 // too late to bring it back into the Add
  need('Undo does nothing while the Add is written', $$('.add__card').length === 1);
  g.release(); await until('the result', () => text('.add__added').includes('Added 1 spool:'));
  need('the Add finished cleanly, no card is left half added', !$$('.add__card').length && n === 2);
  await until('Undo is offered again', () => button('Undo', $('.toasts')));
  button('Undo', $('.toasts')).click();
  need('and it brings the removed card back', $$('.add__card').length === 1 && $('.add__card').textContent.includes('Extra Spool'));
""",
    "restore_during_add": r"""
  await waitPage(); const KEY = 'spoolwarden.draft.add';
  if (!localStorage.getItem(KEY)) { await newFilament('Seed', 'Spool', 'PLA', '160'); await until('the draft is kept', () => localStorage.getItem(KEY)); return; }
  const g = gate(); let n = 0;
  stub('add', async () => { n++; if (n === 2) await g.wait; return n === 1 ? PREVIEWED() : ADDED(); });
  await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  $('.add__bar-btn').click(); await until('the add is under way', busy);
  const restore = button('Restore them', $('.add__draft')); need('the draft is waiting', restore);
  restore.click();                                                      // not while the Add is written
  need('Restore does nothing yet: still one card', $$('.add__card').length === 1);
  g.release(); await until('the result', () => text('.add__added').includes('Added 1 spool:'));
  need('the waiting draft is still there, whole', localStorage.getItem(KEY) && button('Restore them', $('.add__draft')) && !$$('.add__card').length);
  button('Restore them', $('.add__draft')).click(); await until('the drafted card is back', () => $$('.add__card').length >= 1);
""",
    "draft_text_in_progress": r"""
  await waitPage(); const KEY = 'spoolwarden.draft.add';
  const base = { sealed: true, location: 'Sealed stock', hand: true, match: 'new filament', estimates: [], photos: [], net: 1000, tare: 160, density: 1.24, color_hex: '', price_per_kg: '' };
  if (!sessionStorage.getItem('s38-progress')) {                        // what was being typed: a cleared Spools, a bad Spools, a null brand and material
    sessionStorage.setItem('s38-progress', '1');
    localStorage.setItem(KEY, JSON.stringify({ v: 1, started: Date.now(), changed: Date.now(), note: '', readId: null, tag: null, found: null, items: [
      { ...base, vendor: 'Elegoo', name: 'PLA Red', material: 'PLA', count: null, _text: { count: '' } },
      { ...base, vendor: 'Elegoo', name: 'PLA Blue', material: 'PLA', count: null, _text: { count: 'abc' } },
      { ...base, vendor: null, name: 'Mystery', material: null, count: 1 },
      { ...base, vendor: 'Elegoo', name: 'PLA Green', material: 'PLA', count: true }] }));
    return;
  }
  need('the draft is offered, not deleted', text('.add__draft').includes('You have a draft from') && !!localStorage.getItem(KEY));
  button('Restore them').click(); await until('four cards', () => $$('.add__card').length === 4);
  const [one, two, three, four] = $$('.add__card');
  need('a cleared Spools stays cleared and is checked at Preview', field('Spools', one).querySelector('input').value === '' && one.textContent.includes('Needs: Spools'));
  need('an unparsable Spools stays as typed', field('Spools', two).querySelector('input').value === 'abc');
  need('a null brand and material are empty fields', field('Brand', three).querySelector('input').value === '' && field('Material', three).querySelector('input').value === '' && three.textContent.includes('Needs: Brand, Material'));
  need('a count of true is not shown as "true"', field('Spools', four).querySelector('input').value === '');
  need('the bar names the first spool', text('.add__bar-text').startsWith('3 spools need fields. Spool 1 is first.'));
""",
    "draft_number_text": r"""
  await waitPage(); spyAdd(); const KEY = 'spoolwarden.draft.add';
  const base = { vendor: 'Elegoo', name: 'PLA Red', material: 'PLA', sealed: true, location: 'Sealed stock', hand: true, match: 'new filament', estimates: [], photos: [], color_hex: '', price_per_kg: '' };
  if (!sessionStorage.getItem('s38-numtext')) {                         // numbers kept as text, and a draft whose Spools are all cleared
    sessionStorage.setItem('s38-numtext', '1');
    localStorage.setItem(KEY, JSON.stringify({ v: 1, started: Date.now(), changed: Date.now(), note: '', readId: null, tag: null, found: null, items: [
      { ...base, count: '3', net: '1000', tare: '160', density: '1,24' },
      { ...base, name: 'PLA Blue', count: null, _text: { count: '' }, net: 1000, tare: 160, density: 1.24 }] }));
    return;
  }
  need('the banner counts the spools of the cards that have a count (3, then 4 once restored and saved)', /You have a draft from .*: [1-9]\d* spools\./.test(text('.add__draft')));
  button('Restore them').click(); await until('two cards', () => $$('.add__card').length === 2);
  const one = $$('.add__card')[0];
  need('the text numbers are numbers on the card', field('Spools', one).querySelector('input').value === '3' && field('Density', one).querySelector('input').value === '1,24');
  typeIn(field('Spools', $$('.add__card')[1]).querySelector('input'), '1');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row') || $('.add__card .field__error:not([hidden])'));
  need('the Hub got the numbers the card shows', sent.length === 1 && sent[0].items[0].count === 3 && sent[0].items[0].net === 1000 && sent[0].items[0].tare === 160 && sent[0].items[0].density === 1.24);
""",
    "draft_no_counts": r"""
  await waitPage(); const KEY = 'spoolwarden.draft.add';
  if (!sessionStorage.getItem('s38-nocount')) {                         // a draft whose only card has no count
    sessionStorage.setItem('s38-nocount', '1');
    localStorage.setItem(KEY, JSON.stringify({ v: 1, started: Date.now(), changed: Date.now(), note: '', readId: null, tag: null, found: null, items: [
      { vendor: 'Elegoo', name: 'PLA Red', material: 'PLA', sealed: true, location: 'Sealed stock', hand: true, estimates: [], photos: [], count: null, _text: { count: '' }, net: 1000, tare: 160, density: 1.24 }] }));
    return;
  }
  need('the banner says 1 spool, not 0', /: 1 spool\./.test(text('.add__draft')) && !text('.add__draft').includes('0 spool'));
  need('the Add destination shows the badge', $('.nav__item[href="#add"] .nav__badge').textContent === '1');
""",
    "storage_places": r"""
  await waitPage();
  const card = await newFilament('', '', '');
  const sel = () => field('Location', card).querySelector('select'), labels = () => $$('option', sel()).map((o) => o.textContent);
  need('the Hub\'s own list shows how full each place is', labels().some((l) => l.includes(' · ')));
  stub('storage', () => reply({ error: 'not found' }, 404)); await refreshStorage();
  need('a Hub with no storage list shows the plain names', labels().length > 1 && labels()[0].startsWith('Automatic') && !labels().some((l) => l.includes(' \u00b7 ')));
  const STORE = { locations: [
    { id: 'loc-1', name: 'Sealed stock', type: 'bulk', limit: null, count: null, used: 30, free: null, fill: 'none', materials: [], overflow: false, default_overflow: false, sealed: true, position: 1 },
    { id: 'loc-2', name: 'Rack 1', type: 'bulk', limit: 20, count: null, used: 18, free: 2, fill: 'materials', materials: ['PLA'], overflow: false, default_overflow: false, sealed: false, position: 2 },
    { id: 'loc-3', name: 'Rack 2', type: 'bulk', limit: 20, count: null, used: 20, free: 0, fill: 'materials', materials: ['PLA'], overflow: false, default_overflow: false, sealed: false, position: 3 },
    { id: 'loc-4', name: 'Storage box', type: 'containers', prefix: 'Storage box ', containers: Array.from({ length: 12 }, (_, i) => ({ name: 'Storage box ' + String(i + 1).padStart(2, '0'), number: i + 1, taken: true })), limit: null, count: 12, used: 12, free: 0, fill: 'any', materials: [], overflow: false, default_overflow: false, sealed: false, position: 4 },
    { id: 'loc-5', name: 'Dry box', type: 'containers', prefix: 'Dry bin ', containers: [{ name: 'Dry bin 1', number: 1, taken: true }, { name: 'Dry bin 2', number: 2, taken: false }, { name: 'Dry bin 3', number: 3, taken: false }, { name: 'Dry bin 4', number: 4, taken: false }], limit: null, count: 4, used: 1, free: 3, fill: 'none', materials: [], overflow: false, default_overflow: false, sealed: false, position: 5 },
    { id: 'loc-6', name: 'Overflow', type: 'bulk', limit: 5, count: null, used: 9, free: 0, fill: 'none', materials: [], overflow: true, default_overflow: true, sealed: false, position: 6 }],
    order_by_material: [{ material: 'PLA', locations: ['Rack 1', 'Rack 2', 'Overflow'] }], everything_else: ['Storage box', 'Overflow'] };
  stub('storage', () => reply(STORE)); await refreshStorage();
  need('every place in fill order, with how full it is', JSON.stringify(labels().slice(1)) === JSON.stringify(['Sealed stock \u00b7 30 spools', 'Rack 1 \u00b7 18 of 20', 'Rack 2 \u00b7 Full',
    'Storage box \u00b7 Full', 'Dry box \u00b7 3 free', 'Overflow \u00b7 Full']) && labels()[0].startsWith('Automatic'));
  typeIn(sel(), 'Dry box');
  need('a container set is one entry and can be chosen', sel().value === 'Dry box' && $$('option', sel()).filter((o) => o.value.startsWith('Dry box')).length === 1);
  need('a full place stays choosable', !$$('option', sel()).find((o) => o.value === 'Rack 2').disabled);
  await refreshStorage(); need('a new answer keeps the choice', sel().value === 'Dry box');
  const here = placeEntries().find((e) => e.value === 'Dry box').here;
  need('a container of a prefixed set counts as the set, by the names the Hub lists and no name built here', here('Dry bin 1') && here('Dry bin 3') && here('Dry box') && !here('Dry box 1') && !here('Dry bin 5') && !here('Dry bin 01'));
""",
    "storage_auto_line": r"""
  await waitPage();
  let why = 'material';
  stub('add', () => reply({ exit_code: 0, output: 'Would add 1 spool', dry: true, items: [{ index: 0, vendor: 'Elegoo', name: 'PLA Red', filament: 'new', filament_id: null, new_vendor: false, spools: 1, spool_ids: [], location: 'Rack 2',
    placements: [{ location: 'Rack 2', spools: 1, placed_by: why }], opened: true, remaining_g: 1000, problems: [] }] }));
  const card = await newFilament('Elegoo', 'PLA Red', 'PLA', '160');
  const sel = field('Location', card).querySelector('select'), note = () => field('Location', card).querySelector('.field__hint').textContent;
  $('.toggle__input', card).click();
  need('a blank Location is just Automatic', sel.value === '' && $$('option', sel)[0].textContent === 'Automatic' && note() === '');
  $('.add__bar-btn').click(); await until('the preview', () => $('.add__result-row'));
  need('the preview says where it goes and why', note() === 'Rack 2 (the first place for PLA with room)');
  typeIn(sel, 'Rack 1'); need('choosing a place takes the line away', note() === '');
  typeIn(sel, ''); why = 'overflow_none'; typeIn(field('Name', card).querySelector('input'), 'PLA Blue');
  $('.add__bar-btn').click(); await until('the second preview', () => note() !== '');
  need('a material no place takes says so', note() === 'Rack 2 (no place takes PLA automatically)');
""",
    "card_fields": r"""
  await waitPage(); const card = await newFilament('', '', '');
  need('six groups', $$('.add__legend', card).map((l) => l.textContent).join('|') === 'Identity|Amount|State|Print settings|Storage|Other');
  typeIn(field('Brand', card).querySelector('input'), 'Polymaker');
  need('a known brand fills the empty spool weight from the vendor list', await until('the vendor list', () => field('Empty spool weight', card).querySelector('input').value === '200', 4000) && field('Empty spool weight', card).textContent.includes('Filled in from the brand list'));
  typeIn(field('Material', card).querySelector('input'), 'PETG');
  need('a known material fills the density', field('Density', card).querySelector('input').value === '1.27' && field('Density', card).textContent.includes('Typical for PETG'));
  typeIn(field('Name', card).querySelector('input'), 'PETG HF Orange');
  typeIn(field('Colour', card).querySelector('input'), 'F2762E');
  need('the swatch follows the colour', getComputedStyle($('.add__colour-tools .swatch', card)).getPropertyValue('--swatch').trim().toLowerCase() === '#f2762e');
  typeIn(field('Net weight', card).querySelector('input'), '0');
  need('the bar names the grams', text('.add__bar-text') === 'Spool 1: enter grams above 0 for Net weight.');
  typeIn(field('Net weight', card).querySelector('input'), '1000');
  typeIn(field('Colour', card).querySelector('input'), 'F2762');
  need('a colour that is not 6 digits is refused in words', field('Colour', card).querySelector('.field__error').textContent.includes('Enter a colour as 6 hex digits, e.g. #2B2B2E.'));
  typeIn(field('Colour', card).querySelector('input'), '#F2762E');
  const sealed = $('.toggle__input', card);
  need('sealed is on and the weight is hidden', sealed.checked && field('Weight with spool', card).hidden);
  sealed.click();
  need('opened shows the weight and Location goes to Automatic', !field('Weight with spool', card).hidden && field('Location', card).querySelector('select').value === '' && text('.add__sum').includes('Opened'));
  typeIn(field('Spools', card).querySelector('input'), '2');
  need('with two spools the weight is not used', field('Weight with spool', card).querySelector('input').readOnly && field('Weight with spool', card).textContent.includes('Only used for one opened spool.') && card.textContent.includes('x2'));
""",
}


def _states(url: str, name: str, *extra: str) -> dict:
    """Run the state's script, then audit that state: no finding of the page (the other screens' hidden markup is allowed by
    the run's allow-list, which counts for six views, so only the findings are read, not the counts)."""
    run = _run("--url", url, "--views", "#add", "--allow", str(ALLOW), "--ready", "(async () => {" + PRELUDE + READY[name] + "})()", *extra)
    assert run.returncode in (0, 1), run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert not out.get("report"), name + ": " + json.dumps(out["report"], indent=1)
    return out


MULTI_PASS = ("draft", "draft_restored", "draft_discard", "draft_waiting", "draft_corrupt", "draft_partial", "restore_during_add", "draft_text_in_progress", "draft_number_text", "draft_no_counts")


@pytest.mark.parametrize("name", [n for n in READY if n not in MULTI_PASS])
def test_add_spools_state_passes_the_audit(served_add, name):
    out = _states(served_add, name)
    assert out["views"] == 4


@pytest.mark.parametrize("name", MULTI_PASS)
def test_add_spools_draft_states_pass_the_audit(served_add, name):
    """The first pass of the run keeps a draft in the browser's storage; the next three load the page with it."""
    assert _states(served_add, name)["views"] == 4


def test_a_brand_typed_before_the_vendor_list_arrives_still_gets_its_empty_spool_weight(served_add, monkeypatch):
    """The list of brands is asked for when the page loads; a brand typed first is filled in when the list comes (here it takes 2 s)."""
    import time
    from filament_kit import inventory
    real = inventory.vendors

    def slow(sm):
        time.sleep(2)
        return real(sm)
    monkeypatch.setattr(inventory, "vendors", slow)
    out = _states(served_add, "card_fields", "--widths", "1280", "--schemes", "light")
    assert out["views"] == 1


def test_add_spools_with_the_label_reader_off_says_so_and_leads_with_by_hand(served_off):
    ready = """(async () => {""" + PRELUDE + r"""
  await waitPage();
  need('By hand comes first', $('.add__inputs').firstElementChild.querySelector('.add__search'));
  need('the photo group is one line', text('.add__inputs').includes('The Label Reader is switched off. Add the spool by hand, or switch it on in Features on the Hub page.') && !button('Take photo'));
  await search('pla'); $('.add__row').click();
  need('by hand still works', $$('.add__card').length === 1);
})()"""
    run = _run("--url", served_off, "--views", "#add", "--allow", str(ALLOW), "--ready", ready)
    assert run.returncode in (0, 1), run.stdout + run.stderr
    assert not json.loads(run.stdout).get("report"), run.stdout


# ---- the runner's own checks fire (R261): a probe page with a wide view, a view that does not open, a page error ----

PROBE = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>Probe</title>
<header>Probe</header><nav aria-label=Sections><a href='#home'>Home</a></nav><main><h1>Probe</h1>
<div id=box>text</div></main>
<script>
const box = document.getElementById('box');
function route() {
  const v = location.hash;
  if (v === '#gone') { location.replace('#home'); return; }
  box.className = v === '#wide' ? 'wide' : '';
  box.textContent = v === '#wide' ? 'wide' : 'text';
  document.title = 'Probe ' + v;
  if (v === '#boom') setTimeout(() => { throw new Error('probe error'); }, 0);
}
addEventListener('hashchange', route); route();
if (location.search.includes('loadboom')) throw new Error('load error');
</script><style>.wide { width: 900px; }</style></html>"""


@pytest.fixture
def probe():
    from starlette.responses import HTMLResponse
    from starlette.routing import Route
    running = serving.start(Starlette(routes=[Route("/probe", lambda request: HTMLResponse(PROBE))]))
    try:
        yield running.url + "/probe"
    finally:
        running.stop()


def test_the_runner_catches_sideways_scroll_a_view_that_did_not_open_and_page_errors(probe):
    run = _run("--url", probe, "--views", "#home,#wide,#gone,#boom", "--widths", "320", "--schemes", "light")
    assert run.returncode == 1, run.stdout + run.stderr
    found = {(r["view"], f["check"]) for r in json.loads(run.stdout)["report"] for f in r["findings"]}
    assert ("#wide", "sideways scroll") in found and ("#home", "sideways scroll") not in found
    assert ("#gone", "view did not open") in found and ("#home", "view did not open") not in found
    assert ("#boom", "page error") in found and ("#home", "page error") not in found


def test_an_allow_list_count_that_does_not_match_fails(probe, tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text("view did not open | page | 2 | rebuilt by S3.99\n", encoding="utf-8")
    run = _run("--url", probe, "--views", "#home,#gone", "--widths", "320", "--schemes", "light", "--allow", str(allow))
    assert run.returncode == 1 and "allowed 2, found 1" in run.stdout, run.stdout + run.stderr


def test_an_error_thrown_while_the_page_loads_is_reported_against_the_first_view(probe):
    run = _run("--url", probe + "?loadboom", "--views", "#home,#wide", "--widths", "320", "--schemes", "light")
    assert run.returncode == 1, run.stdout + run.stderr
    found = {(r["view"], f["check"]) for r in json.loads(run.stdout)["report"] for f in r["findings"]}
    assert ("#home", "page error") in found and ("#wide", "page error") not in found, found


def test_an_allow_list_line_with_a_view_covers_that_view_only(probe, tmp_path):
    args = ("--url", probe, "--views", "#home,#gone", "--widths", "320", "--schemes", "light", "--allow")
    right, wrong = tmp_path / "right.txt", tmp_path / "wrong.txt"
    right.write_text("# a comment\n#gone | view did not open | page | 1 | rebuilt by S3.99\n", encoding="utf-8")
    wrong.write_text("#home | view did not open | page | 1 | rebuilt by S3.99\n", encoding="utf-8")
    assert _run(*args, str(right)).returncode == 0
    run = _run(*args, str(wrong))
    assert run.returncode == 1 and "#home | view did not open | page: allowed 1, found 0" in run.stdout, run.stdout + run.stderr
    assert ("#gone", "view did not open") in {(r["view"], f["check"]) for r in json.loads(run.stdout)["report"] for f in r["findings"]}


# ---- Spools (design 09 S3.10): every state of 04 5, driven in the page and audited ----------------------------------------
# The Hub is the real one on a fake Spoolman (find, spool read, weight, move, mark empty). What needs a tag on a reader, or a
# printer, is answered by the state's script (the page's fetch is stood in for `tag`, `open`, `printers/...`). A state script
# throws when the page is not in the state it names, then the runner audits that state at 1280 px and 320 px, light and dark.

SP_SEALED_STATE = ("Sealed stock", "Rack 1", "Sealed stock", "Rack 1")      # where the four filaments' spools are (index 0 and 2 sealed)


class SpoolsHub:
    def __init__(self, url, ids):
        self.url, self.ids = url, ids


def _spools_hub(tmp_path, monkeypatch, spoolman_url, printers=False, bulk=0):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: False for n in modules.MODES["server"]}
    mods.update(web=True, ai_intake=True, presets=True, printers=printers)
    config.save({"placement": RULES, "modules": mods, "server_name": "Workshop hub", "web": {"lan": ["127.0.0.0/8"]}})
    api = spoolman_url + "/api/v1"
    ids = []
    with httpx.Client() as c:
        vendors = {}

        def filament(vendor, name, material, colour):
            if vendor not in vendors:
                vendors[vendor] = c.post(api + "/vendor", json={"name": vendor, "empty_spool_weight": 200}).json()["id"]
            return c.post(api + "/filament", json={"vendor_id": vendors[vendor], "name": name, "material": material, "color_hex": colour,
                                                   "density": 1.24, "diameter": 1.75, "weight": 1000, "spool_weight": 200}).json()["id"]
        for i, (vendor, name, material, colour) in enumerate(FILAMENTS):
            sealed = i % 2 == 0
            ids.append(c.post(api + "/spool", json={"filament_id": filament(vendor, name, material, colour), "location": SP_SEALED_STATE[i],
                                                    "remaining_weight": 1000 - 150 * i,
                                                    "comment": inventory.SEALED_COMMENT if sealed else None}).json()["id"])
        if bulk:
            fid = filament("Elegoo", "PLA Silver", "PLA", "C0C0C0")
            for _ in range(bulk):
                c.post(api + "/spool", json={"filament_id": fid, "location": "Sealed stock", "remaining_weight": 1000, "comment": inventory.SEALED_COMMENT})
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    app = Starlette(routes=IntakeApp(mcp_tools.Tools(sm), public_url=None, lan_cidrs=["127.0.0.0/8"], push=False).routes())

    class HttpsOrigin:
        """The web app answers a change only from its own https address, and this test's server is plain http: the Origin the browser
        sends is written as https here (shipped code is untouched), so Preview, Link and the edits can run in the page."""
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope["headers"] = [(k, b"https://" + v[len(b"http://"):] if k == b"origin" and v.startswith(b"http://") else v) for k, v in scope["headers"]]
            await app(scope, receive, send)
    running = serving.start(HttpsOrigin())
    try:
        yield SpoolsHub(running.url + "/intake", ids)
    finally:
        running.stop()


@pytest.fixture
def spools_hub(tmp_path, monkeypatch, spoolman_url):
    yield from _spools_hub(tmp_path, monkeypatch, spoolman_url)


@pytest.fixture
def spools_hub_printers(tmp_path, monkeypatch, spoolman_url):
    yield from _spools_hub(tmp_path, monkeypatch, spoolman_url, printers=True)


SP_BULK = 55


@pytest.fixture
def spools_hub_paged(tmp_path, monkeypatch, spoolman_url):
    yield from _spools_hub(tmp_path, monkeypatch, spoolman_url, bulk=SP_BULK)


SP_PRELUDE = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (what, fn, ms = 10000) => { const t0 = Date.now(); for (;;) { const v = fn(); if (v) return v; if (Date.now() - t0 > ms) throw new Error('Spools: ' + what); await sleep(50); } };
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const text = (s, r = document) => ($(s, r) ? $(s, r).textContent.replace(/\s+/g, ' ').trim() : '');
const need = (what, ok) => { if (!ok) throw new Error('Spools: ' + what); };
const typeIn = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); };
const reply = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const stub = (re, answer) => { const real = window.fetch.bind(window); window.fetch = (u, i) => (re.test(String(u).split('/api/')[1] || '') ? answer(u, i || {}) : real(u, i)); };
const fetchReal = window.fetch.bind(window);
const stubPost = (re, answer) => { const real = window.fetch.bind(window); window.fetch = (u, i) => (re.test(String(u).split('/api/')[1] || '') && (i || {}).method === 'POST' ? answer(u, i) : real(u, i)); };
const spy = (re, log) => { const real = window.fetch.bind(window); window.fetch = (u, i) => { if (re.test(String(u).split('/api/')[1] || '') && (i || {}).method === 'POST') log.push(JSON.parse(i.body)); return real(u, i); }; };
const repoll = () => document.dispatchEvent(new Event('visibilitychange'));       // the page polls the tag at once when it is shown again
const button = (label, root = document) => $$('button', root).find((b) => b.textContent.trim() === label && !b.closest('.hidden'));   // not another screen's, hidden
const field = (label, root = document) => $$('.field', root).find((f) => f.querySelector('.field__label').firstChild.textContent.trim() === label);
const reason = (b) => { const id = b.getAttribute('aria-describedby'); return b.getAttribute('aria-disabled') === 'true' && id && document.getElementById(id) ? document.getElementById(id).textContent : null; };
const TAG = (o) => Object.assign({ nfc_id: '04:77:90:E1', read_at: 1700000000, age_seconds: 12, reader: 'station', scale: null,
  text: 'last tag: 04:77:90:E1  12 s ago on the station reader\n  not linked to any spool yet (a new tag): ready to link' }, o);
// repoll again and again: a poll already out (the first one, or the 3 s timer) makes repoll do nothing, and its answer is the old one
const tap = async (o) => { stub(/^tag$/, () => reply(TAG(o))); await until('the tag is shown', () => { repoll(); return text('.spools__tagid') === TAG(o).nfc_id && text('.spools__age') !== ''; }); };
const waitPage = () => until('the page did not draw', () => $('.spools__results .spools__row, .spools__none') && !document.querySelector('[aria-busy="true"]:not(button)'));
const search = () => $('.spools__search .field__control');
const sheetOpen = () => until('the sheet', () => $('dialog[open].sheet'));
// the summary is drawn from the list row at once; the spool's own read comes after it, and until then Preview and Link
// are held with "Loading Spool N…", so a press before it lands does nothing (seen in CI under load)
const sheetReady = async () => { const d = await sheetOpen(); await until('the summary', () => $('.spools__sum-text') && !$('.spools__sum .skeleton'));
  await until('the spool read', () => !/^Loading /.test((button('Preview') && reason(button('Preview'))) || '')); return d; };
const out = (s) => $$('.spools__sheet .result').find((r) => r.textContent.includes(s));
const FRESH = () => localStorage.removeItem('spoolwarden.sealedOnly');
"""

SP_READY = {
    "list": r"""
  await waitPage();
  need('the intro', text('.spools > p').startsWith("Tap the spool's tag on a reader"));
  need('the Last tag group says no tag yet', $$('.group__title').some((t) => t.textContent === 'Last tag') && text('.spools__tag').includes('No tag read yet: tap one on a reader.'));
  need('the search label is for screen readers', $('.spools__search .field__label').classList.contains('sr') && text('.spools__search .field__label') === 'Find a spool'
    && search().getAttribute('placeholder') === 'Brand, colour, material');
  need('Sealed only is on', $('.spools .check__input').checked && text('.spools .check__label') === 'Sealed only');
  need('two sealed spools, one filament group each', $$('.spools__row').length === 2 && $$('.spools__fil-name').length === 2);
  need('a row says spool, place, weight and Sealed', /^Spool \d+/.test(text('.spools__row b')) && /Sealed stock · \d+ g · Sealed/.test(text('.spools__row-text')));
  need('a swatch and a chevron in a row', $('.spools__row .swatch') && $('.spools__row .spools__chevron'));
  need('the filament line has material and number', /^[A-Z]+ · F\d+$/.test(text('.spools__fil-meta')));
  need('one h1', $$('h1').length === 1);
""",
    "tag_fresh": r"""
  await waitPage(); await tap({ scale: { grams: 1212, age_seconds: 8 } });
  const t = text('.spools__tag');
  for (const part of ['04:77:90:E1', '12 s ago', 'Weigh Station', 'scale 1212 g', 'last tag: 04:77:90:E1']) need('the tag says "' + part + '"', t.includes(part));
  need('the id is in the mono face', $('.spools__tagid').classList.contains('mono'));
  await tap({ reader: 'reader', read_at: 1700000100, age_seconds: 180, scale: null });
  await until('the later tap', () => text('.spools__tag').includes('3 min ago'));
  need('a later tap on the Tag Reader, 3 min old', text('.spools__tag').includes('3 min ago') && text('.spools__tag').includes('Tag Reader') && !text('.spools__tag').includes('scale'));
""",
    "tag_stale": r"""
  await waitPage(); await tap({});
  stub(/^tag$/, () => Promise.reject(new TypeError('offline')));
  repoll();
  await until('the line', () => /Last update .*: the Hub did not answer\./.test(text('.spools .group__body > .result[data-state=warn]')));
  need('the last tag stays', text('.spools__tagid') === '04:77:90:E1');
""",
    "search_results": r"""
  await waitPage(); typeIn(search(), 'pla');
  await until('the sealed PLA only', () => $$('.spools__row').length === 1 && text('.spools__fil-name').includes('Polymaker'));
  $('.spools .check__input').click();
  await until('opened spools too', () => $$('.spools__row').length === 2 && $$('.spools__fil').length === 2);
  need('Sealed only is remembered', localStorage.getItem('spoolwarden.sealedOnly') === '0');
  const second = $$('.spools__row')[1].textContent.replace(/\s+/g, ' ');
  need('an opened row has its place and weight, no Sealed word', /Rack 1 · \d+ g/.test(second) && !second.includes('Sealed'));
  FRESH();
""",
    "search_empty": r"""
  await waitPage(); typeIn(search(), 'zzzz');
  await until('no sealed spools', () => text('.spools__none') === 'No sealed spools match. Turn off Sealed only to include opened spools.');
  $('.spools .check__input').click();
  await until('no spools', () => text('.spools__none') === 'No spools match.');
  FRESH();
""",
    "search_error": r"""
  await waitPage(); stub(/^find\?/, () => reply({ error: 'boom' }, 500));
  typeIn(search(), 'pla');
  await until('the words of 04 3.6 and Try again', () => text('.spools__find').includes('The Hub hit an error it did not expect.') && button('Try again', $('.spools__find')));
""",
    "search_cut": r"""
  await waitPage();
  stub(/^find\?/, () => reply({ matches: 1, filaments: [{ filament_id: 1, vendor: 'Polymaker', name: 'PolyTerra PLA Charcoal Black', material: 'PLA', net_g: 1000, tare_g: 200,
    color_hex: '2B2B2E', spools: [{ spool_id: 1, location: 'Rack 1', remaining_g: 900, sealed: true, lot: 'L-42', tagged: true }] }], truncated: true, total: 61, offset: 0, has_more: true }));
  typeIn(search(), 'pla');
  await until('the cut line', () => text('.spools__results').includes('More spools match. Type more of the name to narrow it down.'));
  need('the row says place, weight, Sealed, tag and lot', text('.spools__row-text').includes('Rack 1 · 900 g · Sealed · Has a tag · Lot L-42'));
""",
    "sealed_remembered": r"""
  await waitPage();
  if (localStorage.getItem('spoolwarden.sealedOnly') === null) {                // the first pass turns it off; the next passes load the page with it off
    $('.spools .check__input').click();
    await until('stored', () => localStorage.getItem('spoolwarden.sealedOnly') === '0');
    return;
  }
  need('the box loads unchecked and the opened spools are listed', !$('.spools .check__input').checked && $$('.spools__row').length === 4);
""",
    "sheet_from_row": r"""
  await waitPage(); const first = $('.spools__row'); first.click();
  const d = await sheetOpen();
  need('the address is the spool', /^#spools\/\d+$/.test(location.hash) && text('dialog[open] .sheet__title') === 'Spool ' + location.hash.split('/')[1]);
  need('the document title names the spool', document.title.startsWith('Spool ' + location.hash.split('/')[1] + ' · '));
  $('dialog[open] [aria-label="Close"]').click();
  await until('back to the list', () => location.hash === '#spools' && !$('dialog[open]'));
""",
    "sheet_open": r"""
  const d = await sheetReady();
  need('titled by the spool', text('dialog[open] .sheet__title') === 'Spool __ID__' && document.title.startsWith('Spool __ID__ · '));
  need('the summary names the filament and the place', text('.spools__sum-text').includes('Polymaker PolyTerra PLA Charcoal Black') && /Sealed stock · 1000 g left · Sealed/.test(text('.spools__sum-text')));
  need('the open part with its tag line', text('.spools__part-title') === 'Open it and link the tag' && text('.spools__sheet-tag') === "No tag read yet: tap the spool's tag on a reader.");
  const w = field('Weight with spool', d), l = field('Location', d), hu = field('Box humidity', d);
  need('three optional fields with their units and hints', w && l && hu && w.textContent.includes('(optional)') && w.textContent.includes('g') && hu.textContent.includes('%')
    && l.textContent.includes('Leave empty to choose automatically.') && hu.querySelector('input').placeholder === 'From the box hygrometer');
  const link = button('Link tag and open');
  need('Link says why it waits', reason(link) === 'Preview first: nothing changes until you link.' && !!button('Preview'));
  need('the other actions, Mark empty last and apart', ['Update weight', 'Move', 'Mark empty'].every((x) => button(x)) && !button('Load into a printer') && button('Mark empty').closest('.spools__danger'));
  need('the three open actions are not disabled', ['Update weight', 'Move', 'Mark empty'].every((x) => !button(x).getAttribute('aria-disabled')));
""",
    "sheet_scale": r"""
  await waitPage(); await tap({ scale: { grams: 1212, age_seconds: 8 } });
  location.hash = '#spools/__ID__';
  const d = await sheetReady();
  need('the weight is filled from the scale, and says so', field('Weight with spool', d).querySelector('input').value === '1212' && field('Weight with spool', d).textContent.includes('Filled in from the Weigh Station scale, 8 s ago'));
  need('the tag line names the tap', text('.spools__sheet-tag') === 'Tag: 04:77:90:E1, tapped 12 s ago on the Weigh Station');
  typeIn(field('Weight with spool', d).querySelector('input'), '1100');
  await tap({ read_at: 1700000200, age_seconds: 2, scale: { grams: 1300, age_seconds: 2 } });
  await until('the new tap', () => text('.spools__sheet-tag').includes('tapped 2 s ago'));
  need('a typed weight is not overwritten by a new tap', field('Weight with spool', d).querySelector('input').value === '1100');
""",
    "sheet_preview": r"""
  const d = await sheetReady(); await tap({});
  window.__open = []; stub(/^open$/, (u, i) => { const b = JSON.parse(i.body); window.__open.push(b); return reply({ output: 'tag 04:77:90:E1 will be linked to spool __ID__\ndry run: nothing changed', exit_code: 0 }); });
  typeIn(field('Weight with spool', d).querySelector('input'), '1212');
  button('Preview').click();
  await until('the preview', () => out('Preview ready. Nothing is saved yet.'));
  need('the Hub text sits under it in a code block', $('.spools__sheet .code') && $('.spools__sheet .code').textContent.includes('dry run: nothing changed'));
  need('the request is the one of today', JSON.stringify(window.__open[0]) === JSON.stringify({ spool: __ID__, gross: '1212', location: '', humidity: '', nfc_id: '04:77:90:E1', read_at: 1700000000, dry_run: true }));
  need('Link is available', reason(button('Link tag and open')) === null && button('Link tag and open').getAttribute('aria-disabled') !== 'true');
  typeIn(field('Weight with spool', d).querySelector('input'), '1300');
  need('an edit asks for a new preview', reason(button('Link tag and open')) === 'You changed the weight. Preview again.');
""",
    "sheet_preview_problem": r"""
  const d = await sheetReady();
  stub(/^open$/, () => reply({ output: 'No tag read on any reader yet: tap the tag on a reader first.', exit_code: 1 }));
  button('Preview').click();
  await until('the problem', () => out('The Hub found a problem. Nothing was changed.'));
  need('the Hub text under it', $('.spools__sheet .code').textContent.includes('No tag read on any reader yet'));
  need('Link says to fix and preview again', reason(button('Link tag and open')) === 'The Hub found a problem. Fix it and preview again.');
""",
    "sheet_link": r"""
  const d = await sheetReady(); await tap({});
  window.__open = []; stub(/^open$/, (u, i) => { const b = JSON.parse(i.body); window.__open.push(b); return reply({ output: b.dry_run ? 'dry run: nothing changed' : 'Spool __ID__ opened and tag 04:77:90:E1 linked.', exit_code: 0, nfc_id: '4:77:90:e1', read_at: 1700000000 }); });
  typeIn(field('Weight with spool', d).querySelector('input'), '1212'); typeIn(field('Location', d).querySelector('input'), 'Rack 1'); typeIn(field('Box humidity', d).querySelector('input'), '41,5');
  button('Preview').click();
  await until('the preview', () => out('Preview ready.') && reason(button('Link tag and open')) === null);
  button('Link tag and open').click();
  await until('the link', () => out('Spool __ID__ is open'));
  need('the Hub text follows it', $('.spools__sheet .code').textContent.includes('tag 04:77:90:E1 linked'));
  need('the real request is the one of today', JSON.stringify(window.__open[1]) === JSON.stringify({ spool: __ID__, gross: '1212', location: 'Rack 1', humidity: '41.5', nfc_id: '4:77:90:e1', read_at: 1700000000, dry_run: false }));
  need('a toast says it', text('.toasts').includes('Spool __ID__ opened.'));
  need('the fields are clear and Link waits again', ['Weight with spool', 'Location', 'Box humidity'].every((l) => field(l, $('dialog[open]')).querySelector('input').value === '') && reason(button('Link tag and open')) === 'Preview first: nothing changes until you link.');
""",
    "sheet_link_refused": r"""
  const d = await sheetReady();
  stub(/^open$/, (u, i) => JSON.parse(i.body).dry_run ? reply({ output: 'dry run: nothing changed', exit_code: 0 }) : reply({ error: 'Tag 04:77:90:E1 is already linked to spool 2: say so to move it.' }, 409));
  button('Preview').click();
  await until('the preview', () => reason(button('Link tag and open')) === null);
  button('Link tag and open').click();
  await until('the refusal', () => out('Tag 04:77:90:E1 is already linked to spool 2'));
  need('the Hub text as given, no code block, Link still there', !$('.spools__sheet .code') && !!button('Link tag and open'));
""",
    "sheet_weight": r"""
  const d = await sheetReady(); button('Update weight').click();
  const form = await until('the form', () => $('.spools__form:not([hidden])'));
  need('the form asks for the weight', field('Weight with spool', form).textContent.includes('Put the spool on the scale and type what it shows.') && button('Update weight').getAttribute('aria-expanded') === 'true');
  need('Save weight says why it waits', reason(button('Save weight')) === 'Enter the weight to see the result first.');
  const input = field('Weight with spool', form).querySelector('input'); typeIn(input, '1012');
  button('Preview', form).click();
  await until('the remaining', () => /Remaining changes from \d+ g to 812 g\./.test(text('.result', form)));
  need('Save weight is available', reason(button('Save weight')) === null);
  typeIn(input, '1100');
  need('an edit asks for a new preview', reason(button('Save weight')) === 'You changed the weight. Preview again.');
""",
    "sheet_weight_saved": r"""
  const d = await sheetReady(); button('Update weight').click();
  const form = await until('the form', () => $('.spools__form:not([hidden])'));
  typeIn(field('Weight with spool', form).querySelector('input'), '1012'); button('Preview', form).click();
  await until('the remaining', () => reason(button('Save weight')) === null);
  button('Save weight').click();
  await until('saved', () => out('Weight updated: 812 g left.'));
  need('the summary follows and the form is closed', text('.spools__sum-text').includes('812 g left') && $('.spools__form').hidden && text('.toasts').includes('Weight updated: 812 g left.'));
""",
    "sheet_weight_refused": r"""
  const d = await sheetReady(); button('Update weight').click();
  const form = await until('the form', () => $('.spools__form:not([hidden])'));
  typeIn(field('Weight with spool', form).querySelector('input'), '50'); button('Preview', form).click();
  await until('the Hub says it', () => text('.result', form).includes('below the spool tare'));
  need('the field shows it', !field('Weight with spool', form).querySelector('.field__error').hidden);
  need('Save weight still waits', reason(button('Save weight')) !== null);
  typeIn(field('Weight with spool', form).querySelector('input'), '');
  button('Preview', form).click();
  need('an empty weight is asked for in words', field('Weight with spool', form).querySelector('.field__error').textContent.includes('Enter grams above 0.'));
""",
    "sheet_move": r"""
  const d = await sheetReady(); button('Move').click();
  const menu = await until('the menu', () => $('dialog[open] .menu'));
  const items = $$('.menu__item', menu);
  need('the four places, the current one marked', items.length === 4 && items.filter((i) => i.getAttribute('aria-disabled') === 'true' && i.textContent.includes('Now here')).length === 1);
  const pick = items.find((i) => i.getAttribute('aria-disabled') !== 'true'), to = pick.querySelector('.menu__label').firstChild.textContent;
  pick.click();
  await until('moved', () => out('Moved to ' + to + '.'));
  need('Undo is offered, and says where it goes', $$('.spools__sheet .result .btn').some((b) => b.textContent.trim() === 'Undo') && text('.spools__sum-text').includes(to) && out('Undo returns it to'));
""",
    "sheet_move_storage": r"""
  const d = await sheetReady();
  const at = text('.spools__sum-text .muted').split(' \u00b7 ')[0];
  const STORE = { locations: [
    { id: 'loc-1', name: 'Sealed stock', type: 'bulk', limit: null, count: null, used: 30, free: null, fill: 'none', materials: [], overflow: false, default_overflow: false, sealed: true, position: 1 },
    { id: 'loc-2', name: 'Rack 1', type: 'bulk', limit: 20, count: null, used: 18, free: 2, fill: 'materials', materials: ['PLA'], overflow: false, default_overflow: false, sealed: false, position: 2 },
    { id: 'loc-3', name: 'Rack 2', type: 'bulk', limit: 20, count: null, used: 20, free: 0, fill: 'materials', materials: ['PLA'], overflow: false, default_overflow: false, sealed: false, position: 3 },
    { id: 'loc-4', name: 'Storage box', type: 'containers', prefix: 'Storage box ', containers: Array.from({ length: 12 }, (_, i) => ({ name: 'Storage box ' + String(i + 1).padStart(2, '0'), number: i + 1, taken: true })), limit: null, count: 12, used: 12, free: 0, fill: 'any', materials: [], overflow: false, default_overflow: false, sealed: false, position: 4 },
    { id: 'loc-5', name: 'Dry box', type: 'containers', prefix: 'Dry bin ', containers: [{ name: 'Dry bin 1', number: 1, taken: true }, { name: 'Dry bin 2', number: 2, taken: false }, { name: 'Dry bin 3', number: 3, taken: false }, { name: 'Dry bin 4', number: 4, taken: false }], limit: null, count: 4, used: 1, free: 3, fill: 'none', materials: [], overflow: false, default_overflow: false, sealed: false, position: 5 },
    { id: 'loc-6', name: 'Overflow', type: 'bulk', limit: 5, count: null, used: 9, free: 0, fill: 'none', materials: [], overflow: true, default_overflow: true, sealed: false, position: 6 }],
    order_by_material: [{ material: 'PLA', locations: ['Rack 1', 'Rack 2', 'Overflow'] }], everything_else: ['Storage box', 'Overflow'] };
  const other = LOCATIONS.find((l) => l !== at); STORE.locations[0].name = 'Spare shelf'; STORE.locations[5].name = 'Spare overflow';
  STORE.locations[1].name = at; STORE.locations[1].used = 7; STORE.locations[2].name = other;
  stub(/^storage$/, () => reply(STORE)); await refreshStorage();
  button('Move').click();
  const menu = await until('the menu', () => $('dialog[open] .menu'));
  const items = $$('.menu__item', menu), row = (n) => items.find((i) => i.querySelector('.menu__label').firstChild.textContent === n);
  need('every place of the list, in order', items.map((i) => i.querySelector('.menu__label').firstChild.textContent).join('|') === ['Spare shelf', at, other, 'Storage box', 'Dry box', 'Spare overflow'].join('|'));
  need('the current place says so and the others say how full they are', row(at).getAttribute('aria-disabled') === 'true' && row(at).textContent.includes('Now here')
    && row(other).textContent.includes('Full') && row('Dry box').textContent.includes('3 free') && row('Spare overflow').textContent.includes('Full'));
  need('a full place can be chosen', row(other).getAttribute('aria-disabled') !== 'true');
  row(other).click();
  await until('moved', () => out('Moved to ' + other + '.'));
""",
    "sheet_move_undo": r"""
  const d = await sheetReady(); button('Move').click();
  const menu = await until('the menu', () => $('dialog[open] .menu'));
  const pick = $$('.menu__item', menu).find((i) => i.getAttribute('aria-disabled') !== 'true'), to = pick.querySelector('.menu__label').firstChild.textContent;
  const was = text('.spools__sum-text .muted').split(' · ')[0];
  pick.click();
  await until('moved', () => out('Moved to ' + to + '.'));
  $$('.spools__sheet .result .btn').find((b) => b.textContent.trim() === 'Undo').click();
  await until('moved back', () => out('Moved to ' + was + '.') && !$$('.spools__sheet .result .btn').some((b) => b.textContent.trim() === 'Undo'));
""",
    "sheet_empty_ask": r"""
  const d = await sheetReady(); button('Mark empty').click();
  const ask = await until('the question', () => $('dialog.dialog[open]'));
  need('it asks in words', text('.dialog__title', ask) === 'Mark spool __ID__ empty?' && text('.dialog__text', ask) === 'Prusament PLA Galaxy Silver will be marked as used up.'
    && button('Cancel', ask) && button('Mark empty', ask).classList.contains('btn--danger'));
""",
    "sheet_empty_done": r"""
  const d = await sheetReady();
  if (button('Mark empty').getAttribute('aria-disabled') !== 'true') {              // the first pass marks it; the next passes find it empty
    button('Mark empty').click();
    const ask = await until('the question', () => $('dialog.dialog[open]')); button('Mark empty', ask).click();
    await until('marked', () => out('Marked empty.'));
  }
  await until('the summary', () => text('.spools__sum-text').includes('Empty'));
  need('Update weight and Mark empty say why', reason(button('Update weight')) === 'This spool is marked empty.' && reason(button('Mark empty')) === 'This spool is marked empty.');
  need('Move stays', !button('Move').getAttribute('aria-disabled'));
  need('an empty spool is not opened: Preview and Link say why', reason(button('Preview')) === 'This spool is marked empty.' && reason(button('Link tag and open')) === 'This spool is marked empty.');
""",
    "sheet_race_weight": r"""
  const d = await sheetReady(); await tap({});
  const bodies = [];
  let release; stub(/^open$/, (u, i) => { bodies.push(JSON.parse(i.body)); return new Promise((ok) => { release = () => ok(new Response(JSON.stringify({ output: 'dry run: nothing changed', exit_code: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })); }); });
  const w = field('Weight with spool', d).querySelector('input');
  typeIn(w, '1212'); button('Preview').click(); await until('the preview is out', () => bodies.length === 1);
  typeIn(w, '999'); release();
  await until('the old answer is dropped', () => reason(button('Link tag and open')) === 'You changed the weight. Preview again.' && !button('Preview').getAttribute('aria-busy'));
  need('no "Preview ready" for a weight that was not previewed', !out('Preview ready.'));
  button('Link tag and open').click(); await sleep(300);
  need('Link sends nothing', bodies.length === 1 && bodies[0].gross === '1212' && bodies[0].dry_run === true);
""",
    "sheet_race_tag": r"""
  const d = await sheetReady(); await tap({});
  const bodies = [];
  let release; stub(/^open$/, (u, i) => { bodies.push(JSON.parse(i.body)); return new Promise((ok) => { release = () => ok(new Response(JSON.stringify({ output: 'dry run: nothing changed', exit_code: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })); }); });
  button('Preview').click(); await until('the preview is out', () => bodies.length === 1);
  await tap({ nfc_id: '04:AA:BB:CC', read_at: 1700000500 });
  await until('the sheet names the newer tag', () => text('.spools__sheet-tag').includes('04:AA:BB:CC'));
  release();
  await until('the old answer is dropped, for the tag', () => reason(button('Link tag and open')) === 'A new tag was tapped. Preview again.' && !button('Preview').getAttribute('aria-busy'));
  button('Link tag and open').click(); await sleep(300);
  need('Link sends nothing for a tag that was not previewed', bodies.length === 1);
""",
    "sheet_race_link": r"""
  const d = await sheetReady(); await tap({});
  const bodies = []; let release = null;
  stub(/^open$/, (u, i) => { const b = JSON.parse(i.body); bodies.push(b); if (b.dry_run) return reply({ output: 'dry run: nothing changed', exit_code: 0, nfc_id: '4:77:90:e1', read_at: 1700000000 });
    return new Promise((ok) => { release = () => ok(new Response(JSON.stringify({ output: 'opened', exit_code: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })); }); });
  typeIn(field('Weight with spool', d).querySelector('input'), '1212'); button('Preview').click();
  await until('previewed', () => out('Preview ready.') && reason(button('Link tag and open')) === null);
  button('Link tag and open').click(); await until('the link is out', () => bodies.length === 2 && release);
  button('Preview').click(); await sleep(300);
  need('a Preview pressed while Link is out sends nothing', bodies.length === 2);
  release();
  await until('opened', () => out('Spool __ID__ is open'));
  await sleep(300);
  need('two requests in all, the real one with what was previewed', bodies.length === 2 && JSON.stringify(bodies[1]) === JSON.stringify({ spool: __ID__, gross: '1212', location: '', humidity: '', nfc_id: '4:77:90:e1', read_at: 1700000000, dry_run: false }));
  need('Link waits again', reason(button('Link tag and open')) === 'Preview first: nothing changes until you link.');
""",
    "sheet_race_save": r"""
  const d = await sheetReady(); button('Update weight').click();
  const form = await until('the form', () => $('.spools__form:not([hidden])')), input = field('Weight with spool', form).querySelector('input');
  const bodies = []; let release = null;
  const view = (g) => ({ id: __ID__, location: 'Sealed stock', remaining_g: g - 200, net_g: 1000, tare_g: 200, tag: null, state: 'sealed', vendor: 'Polymaker', name: 'PolyTerra PLA Charcoal Black', material: 'PLA', color_hex: '2B2B2E', lot: null });
  stubPost(/^spools\/\d+$/, (u, i) => { const b = JSON.parse(i.body); bodies.push(b); const r = () => new Response(JSON.stringify({ spool: {}, view: view(Number(b.gross)), before: view(1200), dry: b.dry_run }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    return bodies.length === 1 ? new Promise((ok) => { release = () => ok(r()); }) : Promise.resolve(r()); });
  typeIn(input, '1012'); button('Preview', form).click(); await until('the preview is out', () => bodies.length === 1);
  typeIn(input, '5000'); release();
  await until('the old answer is dropped', () => reason(button('Save weight')) === 'You changed the weight. Preview again.' && !button('Preview', form).getAttribute('aria-busy'));
  need('no "Remaining changes" for a weight that was not previewed', !text('.result', form).includes('Remaining changes'));
  button('Save weight').click(); await sleep(300);
  need('Save sends nothing', bodies.length === 1);
  button('Preview', form).click(); await until('previewed', () => reason(button('Save weight')) === null && text('.result', form).includes('Remaining changes from 1000 g to 4800 g.'));
  button('Save weight').click(); await until('saved', () => bodies.length === 3);
  need('Save sends the previewed weight', bodies[1].gross === '5000' && bodies[1].dry_run === true && bodies[2].gross === '5000' && bodies[2].dry_run === false);
""",
    "sheet_move_twice": r"""
  const d = await sheetReady();
  const log = []; spy(/^spools\/\d+$/, log);
  const where = () => text('.spools__sum-text .muted').split(' · ')[0], orig = where();
  const undo = () => $$('.spools__sheet .result .btn').find((b) => b.textContent.trim() === 'Undo');
  const move = async (not) => {
    button('Move').click();
    const menu = await until('the menu', () => $('dialog[open] .menu'));
    const pick = $$('.menu__item', menu).find((i) => i.getAttribute('aria-disabled') !== 'true' && i.querySelector('.menu__label').firstChild.textContent !== not);
    const to = pick.querySelector('.menu__label').firstChild.textContent; pick.click();
    await until('moved to ' + to, () => out('Moved to ' + to) && where().startsWith(to)); return to;
  };
  const one = await move(orig), two = await move(orig);
  need('two different places, neither the first', one !== two && two !== orig && one !== orig);
  need('Undo is offered after the second move', !!undo());
  undo().click();
  await until('back where it was before the first move', () => where() === orig && out('Moved to ' + orig + '.') && !undo());
  need('the requests are the two moves and the undo', log.length === 3 && log[2].location === orig && log.every((b) => b.dry_run === false));
""",
    "sheet_tap_refused": r"""
  const d = await sheetReady(); await tap({});
  const bodies = [];
  stub(/^open$/, (u, i) => { const b = JSON.parse(i.body); bodies.push(b);
    return b.dry_run ? reply({ output: 'dry run: nothing changed', exit_code: 0, nfc_id: '4:77:90:e1', read_at: 1700000000 }) : reply({ error: 'A new tag was tapped. Preview again.', code: 'tap_changed' }, 409); });
  button('Preview').click(); await until('previewed', () => reason(button('Link tag and open')) === null);
  need('Preview names the tap it looked at', bodies[0].nfc_id === '04:77:90:E1' && bodies[0].read_at === 1700000000);
  button('Link tag and open').click();
  await until('refused', () => text('.spools__sheet-note') === 'A new tag was tapped. Preview again.' && reason(button('Link tag and open')) === 'A new tag was tapped. Preview again.');
  need('Link named the same tap', bodies[1].nfc_id === '4:77:90:e1' && bodies[1].read_at === 1700000000 && bodies[1].dry_run === false);
  await tap({ nfc_id: '04:AA:BB:CC', read_at: 1700000600 });                               // the poll catches up: the reason is not lost
  await until('the sheet names the newer tag', () => text('.spools__sheet-tag').includes('04:AA:BB:CC')); await sleep(200);
  need('the reason stays after the poll', reason(button('Link tag and open')) === 'A new tag was tapped. Preview again.');
  button('Link tag and open').click(); await sleep(300);
  need('Link sends nothing until a new Preview', bodies.length === 2);
""",
    "sheet_unread": r"""
  await waitPage();
  let release; const log = []; const real = window.fetch.bind(window);
  window.fetch = (u, i) => { const p = String(u).split('/api/')[1] || '';
    if ((i || {}).method === 'POST') log.push(p);
    return /^spools\/\d+$/.test(p) && !(i && i.method === 'POST') ? new Promise((ok) => { release = () => ok(real(u, i)); }) : real(u, i); };
  location.hash = '#spools/__ID__';
  await until('the sheet', () => $('dialog[open].sheet') && release);
  need('Preview and Link say the spool is being read', reason(button('Preview')) === 'Loading Spool __ID__…' && reason(button('Link tag and open')) === 'Loading Spool __ID__…');
  button('Preview').click(); button('Link tag and open').click(); await sleep(300);
  need('nothing is sent before the spool is read', log.length === 0);
  release();
  await until('read', () => !$('.spools__sum .skeleton') && reason(button('Link tag and open')) === 'Preview first: nothing changes until you link.' && !button('Preview').getAttribute('aria-disabled'));
""",
    "sheet_move_wait": r"""
  const d = await sheetReady(); let release = null;
  stubPost(/^spools\/\d+$/, (u, i) => { const b = JSON.parse(i.body); return new Promise((ok) => { release = () => ok(fetchReal(u, i)); }); });
  button('Move').click();
  let menu = await until('the menu', () => $('dialog[open] .menu'));
  const first = $$('.menu__item', menu).find((x) => x.getAttribute('aria-disabled') !== 'true'); first.click();
  await until('the move is out', () => release);
  button('Move').click();
  menu = await until('the menu again', () => $('dialog[open] .menu'));
  need('every place says it waits', $$('.menu__item', menu).every((x) => x.getAttribute('aria-disabled') === 'true' && x.textContent.includes('Moving…')));
  release();
""",
    "sheet_undo_failed": r"""
  const d = await sheetReady();
  button('Move').click();
  const menu = await until('the menu', () => $('dialog[open] .menu'));
  const pick = $$('.menu__item', menu).find((i) => i.getAttribute('aria-disabled') !== 'true'), to = pick.querySelector('.menu__label').firstChild.textContent, was = text('.spools__sum-text .muted').split(' · ')[0];
  pick.click();
  await until('moved, with where Undo goes', () => out('Moved to ' + to + '. Undo returns it to ' + was + '.'));
  stubPost(/^spools\/\d+$/, () => reply({ error: 'boom' }, 500));
  $$('.spools__sheet .result .btn').find((b) => b.textContent.trim() === 'Undo').click();
  await until('the failure', () => out('The Hub hit an error') && $$('.spools__sheet .result .btn').some((b) => b.textContent.trim() === 'Try again'));
  await sleep(5600);
  need('the error and Try again stay after the Undo window', !!out('The Hub hit an error') && !out('Moved to ' + was + '.') && $$('.spools__sheet .result .btn').some((b) => b.textContent.trim() === 'Try again'));
""",
    "sheet_link_unseen": r"""
  const d = await sheetReady();
  need('the page shows no tag', text('.spools__sheet-tag') === "No tag read yet: tap the spool's tag on a reader.");
  const bodies = [];
  stub(/^open$/, (u, i) => { const b = JSON.parse(i.body); bodies.push(b); return reply({ output: b.dry_run ? 'dry run: nothing changed' : 'opened', exit_code: 0, nfc_id: '4:aa:bb:cc', read_at: 55 }); });
  button('Preview').click(); await until('previewed', () => reason(button('Link tag and open')) === null && out('Preview ready.'));
  need('Preview names no tap: the page had none to name', !('nfc_id' in bodies[0]) && !('read_at' in bodies[0]));
  button('Link tag and open').click(); await until('opened', () => out('Spool __ID__ is open'));
  need('Link names the tap the Hub used for the preview', bodies[1].nfc_id === '4:aa:bb:cc' && bodies[1].read_at === 55 && bodies[1].dry_run === false);
""",
    "sheet_poll_between": r"""
  const d = await sheetReady();
  need('the page shows no tag', text('.spools__sheet-tag') === "No tag read yet: tap the spool's tag on a reader.");
  const bodies = [], polls = [];
  stub(/^open$/, (u, i) => { const b = JSON.parse(i.body); bodies.push(b); return reply({ output: b.dry_run ? 'dry run: nothing changed' : 'opened', exit_code: 0, nfc_id: '4:aa:bb:cc', read_at: 55 }); });
  button('Preview').click(); await until('previewed', () => reason(button('Link tag and open')) === null && out('Preview ready.'));
  // a poll that brings no tap: still no tag, but not the answer the page last had
  stub(/^tag$/, () => { polls.push('none'); return reply({ nfc_id: null, read_at: 7, age_seconds: null, reader: null, scale: null, text: '' }); });
  await until('the poll without a tap is answered', () => { repoll(); return polls.length > 0; });
  // then the poll that brings the tap the Preview already named
  stub(/^tag$/, () => { polls.push('tap'); return reply(TAG({ nfc_id: '04:AA:BB:CC', read_at: 55 })); });
  await until('the sheet names the tap', () => { repoll(); return text('.spools__sheet-tag').includes('04:AA:BB:CC'); });
  need('neither poll made the Preview out of date: ' + reason(button('Link tag and open')), reason(button('Link tag and open')) === null && button('Link tag and open').getAttribute('aria-disabled') !== 'true');
  button('Link tag and open').click(); await until('opened', () => out('Spool __ID__ is open'));
  need('Link names the previewed tap', bodies.length === 2 && bodies[1].nfc_id === '4:aa:bb:cc' && bodies[1].read_at === 55 && bodies[1].dry_run === false);
""",
    "sheet_tap_again_unseen": r"""
  const d = await sheetReady();
  need('the page shows no tag', text('.spools__sheet-tag') === "No tag read yet: tap the spool's tag on a reader.");
  stub(/^open$/, () => reply({ output: 'dry run: nothing changed', exit_code: 0, nfc_id: '4:aa:bb:cc', read_at: 55 }));      // the Hub writes the id as bytes in lower case
  button('Preview').click(); await until('previewed', () => reason(button('Link tag and open')) === null && out('Preview ready.'));
  await tap({ nfc_id: '04:AA:BB:CC', read_at: 55 });                                      // the raw form of the previewed tap
  need('the previewed tap is not new', reason(button('Link tag and open')) === null);
  await tap({ nfc_id: '04:AA:BB:CC', read_at: 56, age_seconds: 2 });                      // the same tag, tapped again
  await until('the tap is shown', () => text('.spools__sheet-tag').includes('tapped 2 s ago'));
  need('the reason says it was tapped again, not that a new tag came', reason(button('Link tag and open')) === 'The tag was tapped again. Preview again.');
""",
    "sheet_tap_again": r"""
  const d = await sheetReady(); await tap({});
  stub(/^open$/, () => reply({ output: 'dry run: nothing changed', exit_code: 0, nfc_id: '4:77:90:e1', read_at: 1700000000 }));
  button('Preview').click(); await until('previewed', () => reason(button('Link tag and open')) === null && out('Preview ready.'));
  await tap({ read_at: 1700000900, age_seconds: 2 });                                      // the same tag, tapped again
  await until('the tap is shown', () => text('.spools__sheet-tag').includes('tapped 2 s ago'));
  need('the reason says it was tapped again', reason(button('Link tag and open')) === 'The tag was tapped again. Preview again.');
""",
    "sheet_read_failed": r"""
  await waitPage(); let n = 0; const real = window.fetch.bind(window);
  window.fetch = (u, i) => { const p = String(u).split('/api/')[1] || ''; return /^spools\/\d+$/.test(p) && !(i && i.method === 'POST') && n++ === 0 ? reply({ error: 'boom' }, 500) : real(u, i); };
  location.hash = '#spools/__ID__';
  const d = await sheetOpen();
  await until('the error with Try again', () => button('Try again', d) && text('.spools__sum', d).includes('The Hub hit an error'));
  need('Preview and Link say the spool could not be read', reason(button('Preview')) === 'This spool could not be read yet. Use Try again at the top.' && reason(button('Link tag and open')) === 'This spool could not be read yet. Use Try again at the top.');
  button('Try again', d).click();
  await until('read', () => !$('.spools__sum .skeleton') && text('.spools__sum-text') && reason(button('Link tag and open')) === 'Preview first: nothing changes until you link.' && !button('Preview').getAttribute('aria-disabled'));
""",
    "sheet_missing": r"""
  await until('the line', () => $('dialog[open] .result[data-state=bad]') && text('dialog[open]').includes('was not found'));
  const seen = (l) => { const b = button(l); return !!b && b.getClientRects().length > 0; };
  need('the Hub text, and nothing to act on', text('dialog[open]').includes('spool 99999 was not found') && !seen('Preview') && !seen('Mark empty'));
""",
}
SP_AT = {"sheet_from_row": "#spools", "sheet_unread": "#spools", "sheet_read_failed": "#spools", "sheet_missing": "#spools/99999", "sheet_empty_ask": 3, "sheet_empty_done": 2}   # the view, or which spool's sheet it opens
SP_PAGED = {
    "paging": r"""
  await waitPage();
  need('50 rows on the first page and the pager', $$('.spools__row').length === 50 && text('.coll__pager').includes('1–50 of __TOTAL__'));
  button('Next', $('.coll__pager')).click();
  await until('the rest', () => $$('.spools__row').length === __TOTAL__ - 50);
  need('the pager says where it is and the focus is on the first row', text('.coll__pager').includes('51–__TOTAL__ of __TOTAL__') && document.activeElement === $('.spools__row') && button('Previous', $('.coll__pager')));
""",
}
SP_PRINTERS = {
    "tag_linked": r"""
  await waitPage();
  stub(/^printers\/tagged$/, () => reply({ nfc_id: '04:77:90:E1', spool: { id: __ID__, vendor: 'Polymaker', name: 'PolyTerra PLA Charcoal Black', location: 'Rack 1', remaining_g: 900 } }));
  await tap({});
  await until('the link', () => text('.spools__linked').includes('Linked to spool __ID__, Polymaker PolyTerra PLA Charcoal Black'));
  button('Show spool __ID__').click();
  await sheetReady();
  need('the sheet is the spool', text('dialog[open] .sheet__title') === 'Spool __ID__' && location.hash === '#spools/__ID__');
""",
    "load_printers": r"""
  const d = await sheetReady();
  stub(/^printers$/, () => reply({ printers: [{ id: '01P0', name: 'Workshop X1', family: 'bambu', state: 'connected' }, { id: 'sv08', name: 'Corner SV08', family: 'klipper', state: 'offline' }] }));
  need('Load into a printer is offered with the Printers Feature on', !!button('Load into a printer'));
  button('Load into a printer').click();
  await until('the printers', () => text('.spools__step') === 'Load into which printer?' && $$('.spools__load .spools__row').length === 2);
  need('one row per printer, with its state in a word', /Workshop X1.*Connected/.test(text('.spools__load')) && /Corner SV08.*Offline/.test(text('.spools__load')));
""",
    "load_none": r"""
  const d = await sheetReady(); stub(/^printers$/, () => reply({ printers: [] }));
  button('Load into a printer').click();
  await until('the line', () => text('.spools__load').includes('No printers are set up yet. Add one under Printers.'));
""",
    "load_plan": r"""
  const d = await sheetReady();
  stub(/^printers$/, () => reply({ printers: [{ id: '01P0', name: 'Workshop X1', family: 'bambu', state: 'connected' }] }));
  stub(/^printers\/01P0\/state$/, () => reply({ printer: { id: '01P0' }, status: { ams: [{ label: 'AMS 1', type_name: 'AMS 2 Pro', slots: [
    { label: 'A1', color_hex: '2B2B2E', type: 'PLA', spool: { name: 'PolyTerra PLA Charcoal Black', remaining_weight: 900 } }, { label: 'A2', color_hex: '', type: '', spool: null, present: false }] }] } }));
  window.__load = [];
  stub(/^printers\/01P0\/slots\/A2\/load$/, (u, i) => { const b = JSON.parse(i.body); window.__load.push(b); return reply(b.dry_run ? { preset: { name: 'Polymaker PLA' }, nozzle_mm: 0.4, moved_back: [], problems: [] } : { confirmed: true, moved_back: [], problems: [] }); });
  button('Load into a printer').click();
  await until('the printers', () => $$('.spools__load .spools__row').length === 1);
  $('.spools__load .spools__row').click();
  await until('the slots', () => text('.spools__step') === 'Which slot on Workshop X1?' && $$('.spools__load .spools__row').length === 2);
  need('one row per slot, with its spool', text('.spools__load').includes('PolyTerra PLA Charcoal Black · 900 g') && text('.spools__load').includes('Empty'));
  $$('.spools__load .spools__row')[1].click();
  await until('the plan', () => text('.spools__load').includes('Preset: Polymaker PLA') && reason(button('Load')) === null);
  need('the plan is asked as a dry run', JSON.stringify(window.__load[0]) === JSON.stringify({ spool_id: __ID__, dry_run: true }));
""",
    "load_done": r"""
  const d = await sheetReady();
  stub(/^printers$/, () => reply({ printers: [{ id: '01P0', name: 'Workshop X1', family: 'bambu', state: 'connected' }] }));
  stub(/^printers\/01P0\/state$/, () => reply({ printer: { id: '01P0' }, status: { ams: [{ label: 'AMS 1', slots: [{ label: 'A2', color_hex: '', type: '', spool: null }] }] } }));
  window.__load = [];
  stub(/^printers\/01P0\/slots\/A2\/load$/, (u, i) => { const b = JSON.parse(i.body); window.__load.push(b); return reply(b.dry_run ? { preset: { name: 'Polymaker PLA' }, nozzle_mm: 0.4, moved_back: [], problems: [] } : { confirmed: true, moved_back: [], problems: [] }); });
  button('Load into a printer').click();
  await until('the printers', () => $$('.spools__load .spools__row').length === 1); $('.spools__load .spools__row').click();
  await until('the slots', () => $$('.spools__load .spools__row').length === 1); $('.spools__load .spools__row').click();
  await until('the plan', () => reason(button('Load')) === null && !button('Load').getAttribute('aria-busy'));
  button('Load').click();
  await until('loaded', () => out('Loaded into A2.') && $('.spools__load').hidden);
  need('the real load is sent after the plan, and a toast says it', JSON.stringify(window.__load[1]) === JSON.stringify({ spool_id: __ID__, dry_run: false }) && text('.toasts').includes('Loaded into A2.'));
""",
}


def _spools_run(url, name, script, view, *extra, allow=ALLOW):
    ready = "(async () => {" + SP_PRELUDE + script + "})()"
    run = _run("--url", url, "--views", view, "--allow", str(allow), "--ready", ready, *extra)
    assert run.returncode in (0, 1), run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert not out.get("report"), name + ": " + json.dumps(out["report"], indent=1)
    return out


def _at(hub, name, listed):
    """The view of a state and the script with the spool it is about (`__ID__`): the sheet states open the first spool's sheet unless SP_AT says."""
    at = SP_AT.get(name, 0 if name.startswith("sheet_") or name.startswith("load_") else "#spools")
    view = at if isinstance(at, str) else f"#spools/{hub.ids[at]}"
    spool = hub.ids[at] if isinstance(at, int) else hub.ids[0]
    return view, listed[name].replace("__ID__", str(spool))


@pytest.mark.parametrize("name", list(SP_READY))
def test_spools_state_passes_the_audit(spools_hub, name):
    view, script = _at(spools_hub, name, SP_READY)
    assert _spools_run(spools_hub.url, name, script, view)["views"] == 4


@pytest.mark.parametrize("name", list(SP_PRINTERS))
def test_spools_state_with_the_printers_feature_passes_the_audit(spools_hub_printers, name, tmp_path):
    """The Printers Feature is on here, so the Printers screen's own hidden markup is on the page: its findings are listed beside
    the allow-list for this run only (S3.11 rebuilds that screen)."""
    allow = tmp_path / "allow.txt"
    allow.write_text("".join(f.read_text(encoding="utf-8") for f in sorted(ALLOW.glob("*.txt"))) + "field without a label | main#main > section.page > section.hidden > select | 4 | Printers picker (hidden); rebuilt by S3.11\n",
                     encoding="utf-8")
    view, script = _at(spools_hub_printers, name, SP_PRINTERS)
    assert _spools_run(spools_hub_printers.url, name, script, view, allow=allow)["views"] == 4


def test_spools_pages_of_fifty_pass_the_audit(spools_hub_paged):
    script = SP_PAGED["paging"].replace("__TOTAL__", str(SP_BULK + 2))
    assert _spools_run(spools_hub_paged.url, "paging", script, "#spools")["views"] == 4


def test_the_tag_poll_runs_only_while_the_screen_is_shown_and_the_page_is_visible(spools_hub):
    """04 5.2: GET tag every 3 s; it stops when the page is hidden or the screen is left, and starts again at once."""
    script = r"""
  const calls = []; stub(/^tag$/, () => { calls.push(Date.now()); return reply(TAG({})); });
  await until('a first poll', () => calls.length >= 1);
  await sleep(3500); need('it polls again every 3 s while shown', calls.length >= 2);
  const hide = (v) => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => v }); document.dispatchEvent(new Event('visibilitychange')); };
  hide(true); const n = calls.length; await sleep(3600);
  need('no poll while the page is hidden', calls.length === n);
  hide(false); await until('a poll at once when shown again', () => calls.length > n, 1500);
  const m = calls.length; location.hash = '#add'; await sleep(300); const k = calls.length; await sleep(3600);
  need('no poll after the screen is left', calls.length === k);
  location.hash = '#spools'; await until('and at once on coming back', () => calls.length > k, 1500);
  need('the first polls are about 3 s apart', calls[1] - calls[0] >= 2500);
"""
    out = _spools_run(spools_hub.url, "poll", script, "#spools", "--widths", "1280", "--schemes", "light")
    assert out["views"] == 1
# ---- S3.15: the Add to Home Screen sheet and "Cannot reach the Hub" in a headless browser (tests/page_drive.mjs) ----

DRIVER = ROOT / "tests" / "page_drive.mjs"
SHOTS = os.environ.get("FK_SHOTS_DIR")        # set: also save a screenshot of each state (fake data only)
LOOKS = [(375, "light"), (375, "dark"), (1280, "light"), (1280, "dark")]
HOME_PRELUDE = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
async function until(look, what, ms = 8000) {
  for (let t = 0; t < ms; t += 50) { const v = look(); if (v) return v; await sleep(50); }
  throw new Error("waited for " + what + "; the page shows: " + text($("main")).slice(0, 300) + " | dialogs: " + [...document.querySelectorAll("dialog")].map((d) => d.open + ":" + text(d).slice(0, 60)) + " | buttons: " + [...document.querySelectorAll("button, a")].filter((b) => /Home/.test(text(b))).map((b) => b.className + ":" + text(b)));
}
const press = (label) => [...document.querySelectorAll("button, a")].find((b) => text(b).startsWith(label));
"""
INSTALL = """
if (innerWidth <= 600) { $(".nav__more").click(); await until(() => $(".more"), "the More sheet"); press("Add to Home Screen").click(); }
else {
  // a desktop Chrome that finds the app installable offers its own prompt: the row then reads "Install app" (04 10.1)
  location.hash = "#settings"; await until(() => press("Add to Home Screen") || press("Install app"), "the Settings page");
  await sleep(1500);
  if (press("Install app")) return { prompt: true, label: text(press("Install app")), sheet: !!$("dialog[open]") };
  press("Add to Home Screen").click();
}
const dlg = await until(() => $("dialog[open] ol.install"), "the install sheet");
return { title: text($("dialog[open] .sheet__title")), steps: [...dlg.querySelectorAll("li")].map(text),
         note: text($("dialog[open] .banner")), done: !!press("Done") };
"""
OFFLINE = """
const real = window.fetch;
let down = false;
window.fetch = (u, o) => (down && String(u).includes("/api/") ? Promise.reject(new TypeError("Failed to fetch")) : real(u, o));
const chip = () => $(".topbar__offline"), banner = () => $(".offline-banner");
const seen = { before: !!banner() && !chip().hidden };
const search = () => api("vendors").catch(() => {});   // any request of the page: the app's own helper
async function lose() { down = true; search(); await until(() => banner(), "the offline banner"); }
// the Hub stops answering: the shell stays, the chip and the banner show
await lose();
seen.chip = text(chip()); seen.chipShown = !chip().hidden; seen.banner = text(banner()); seen.role = banner().getAttribute("role");
seen.icon = !!banner().querySelector("use[href='#i-wifi-off']"); seen.title = text($("h1")); seen.nav = !!$(".nav");
if (__LEAVE__) return seen;
// the Hub answers again, Try now: the banner and the chip go and a toast says so
down = false; press("Try now").focus(); press("Try now").click();
await until(() => !banner(), "the banner to go");
seen.focus = document.activeElement === $("h1"); seen.chipGone = chip().hidden; seen.toast = text($(".toast"));
// the Hub stops again and answers again without a press: the page tries again by itself within 10 s
if (__AUTO__) { await lose(); down = false; await until(() => !banner(), "the automatic retry", 14000); seen.auto = true; }
return seen;
"""


def _drive(url: str, tmp_path, script: str, width: int, scheme: str, shot: str | None = None) -> dict:
    node = _node()
    if not node:
        _missing("the page driver needs Node 22 or later")
    file = tmp_path / "drive.js"
    file.write_text(HOME_PRELUDE + script, encoding="utf-8")
    init = tmp_path / "init.js"       # the browser's own install offer is not taken, so the sheet is what the row opens
    init.write_text("addEventListener('beforeinstallprompt', (e) => e.stopImmediatePropagation(), true);", encoding="utf-8")
    cmd = [node, str(DRIVER), "--url", url + "#add", "--script", str(file), "--width", str(width), "--scheme", scheme, "--init", str(init)]
    if SHOTS and shot:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        cmd += ["--shot", str(Path(SHOTS) / f"S3-15-{shot}-{width}-{scheme}.png")]
    run = subprocess.run(cmd, capture_output=True, encoding="utf-8", timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the page driver needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("page driver: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
@pytest.mark.parametrize("width,scheme", LOOKS)
def test_the_install_sheet_shows_the_three_iphone_steps(served_web, tmp_path, width, scheme):
    out = _drive(served_web.url, tmp_path, INSTALL, width, scheme, "install")
    if out.get("prompt"):                                  # the browser's own install prompt, not the sheet
        assert out["label"].startswith("Install app") and not out["sheet"]
        return
    assert out["title"].startswith("Add ") and out["title"].endswith(" to the Home Screen")
    assert out["steps"] == ["Tap Share in Safari's toolbar (the square with an arrow).", "Choose Add to Home Screen.", "Tap Add."]
    assert out["note"] == "Print alerts on iPhone work only from the Home Screen." and out["done"]


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
@pytest.mark.parametrize("width,scheme", LOOKS)
def test_the_hub_not_answering_shows_the_chip_and_the_banner_and_the_app_recovers(served_web, tmp_path, width, scheme):
    auto = (width, scheme) == (1280, "light")      # the 10 s wait is done once
    out = _drive(served_web.url, tmp_path, OFFLINE.replace("__LEAVE__", "true" if SHOTS else "false").replace("__AUTO__", "false" if SHOTS else str(auto).lower()),
                 width, scheme, "offline")
    assert out["before"] is False
    assert out["chip"] == "Offline" and out["chipShown"] and out["icon"] and out["role"] == "status" and out["nav"]
    assert out["banner"] == "Needs a look: Cannot reach the Hub. Retrying every 10 s.Try now"
    assert out["title"] == "Add spools"                    # the shell and the page stay
    if not SHOTS:
        assert out["chipGone"] and out["toast"] == "Connected to the Hub again."
        assert out["focus"]                                  # the banner's Try now is gone: focus goes to the heading
        assert out.get("auto", not auto)


MIGRATE = r"""
const log = [], base = BASE, scope = (p) => location.origin + p;
const fakeSub = (ep) => ({ endpoint: ep, unsubscribe: async () => log.push("unsub " + ep), toJSON: () => ({ endpoint: ep }) });
const mk = (p, sub) => ({ scope: scope(p), active: {}, unregister: async () => log.push("unregister " + p),
  pushManager: { getSubscription: async () => sub, subscribe: async (o) => { log.push("subscribe " + o.applicationServerKey.length); return fakeSub("new"); } } });
const real = window.fetch;
window.fetch = async (u, o) => {
  if (!String(u).includes("/api/printers/push/")) return real(u, o);
  log.push(String(u).split("/api/")[1] + " " + ((o && o.body) || ""));
  return new Response(JSON.stringify({ key: "AQID", ok: true }), { headers: { "Content-Type": "application/json" } });
};
Object.defineProperty(Notification, "permission", { get: () => "granted" });
const set = (regs) => { navigator.serviceWorker.getRegistrations = async () => regs; };
const cur = mk(base, null);
set([mk(base + "/", fakeSub("old")), cur]); await migrateAlerts(); const subscribed = log.splice(0);
set([mk(base + "/", null), cur]); await migrateAlerts(); const quiet = log.splice(0);
set([cur]); await migrateAlerts(); const none = log.splice(0);
set([mk(base + "/", fakeSub("old")), cur]); const own = (await ownReg()) === cur;
return { subscribed, quiet, none, own, base };
"""


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
def test_a_phone_from_0_5_moves_its_alerts_to_the_registration_of_the_app_path(served_web, tmp_path):
    out = _drive(served_web.url, tmp_path, MIGRATE, 1280, "light")
    base = out["base"]
    assert out["own"]                                           # the lookup for alerts picks the registration whose scope is the path
    assert out["subscribed"] == ["printers/push/key ", "subscribe 3", 'printers/push/subscribe {"subscription":{"endpoint":"new"}}',
                                 'printers/push/unsubscribe {"endpoint":"old"}', "unsub old", f"unregister {base}/"]
    assert out["quiet"] == [f"unregister {base}/"] and out["none"] == []     # no alerts on: only the stale one goes
