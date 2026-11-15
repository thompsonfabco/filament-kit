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
    run = subprocess.run([node, str(RUNNER), *args], capture_output=True, text=True, timeout=600)
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
    run = subprocess.run([node, str(FLOWS), "--url", url, "--flow", flow, "--width", str(width)], capture_output=True, text=True, timeout=300)
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
    localStorage.setItem(KEY, JSON.stringify({ v: 1, items: [null, {}, { vendor: 5, count: 'abc' }] })); localStorage.setItem(KEY + '-new', 'not json');
    return;
  }
  need('the page started and says nothing of the bad drafts', $('.add__bar-text') && !$('.add__draft .banner'));
  need('they are dropped', !localStorage.getItem(KEY) && !localStorage.getItem(KEY + '-new'));
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


MULTI_PASS = ("draft", "draft_restored", "draft_discard", "draft_waiting", "draft_corrupt", "draft_partial", "restore_during_add")


@pytest.mark.parametrize("name", [n for n in READY if n not in MULTI_PASS])
def test_add_spools_state_passes_the_audit(served_add, name):
    out = _states(served_add, name)
    assert out["views"] == 4


@pytest.mark.parametrize("name", MULTI_PASS)
def test_add_spools_draft_states_pass_the_audit(served_add, name):
    """The first pass of the run keeps a draft in the browser's storage; the next three load the page with it."""
    assert _states(served_add, name)["views"] == 4


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
