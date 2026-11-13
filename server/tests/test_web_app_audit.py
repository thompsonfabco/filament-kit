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

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "aut5_run.mjs"
ALLOW = ROOT / "tests" / "allowlists" / "aut5"      # a folder, one file per screen
PAGES = ("#add", "#spools", "#printers", "#recent", "#recent/{id}", "#presets", "#settings")     # {id}: the seeded record
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
         "sealed_location": "Sealed stock"}
FILAMENTS = [("Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E"),
             ("Bambu Lab", "PETG HF Orange", "PETG", "F2762E"),
             ("eSUN", "ABS+ White", "ABS", "F4F4F2"),
             ("Prusament", "PLA Galaxy Silver", "PLA", "8D9199")]


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


@pytest.fixture(params=STATES)
def served(request, tmp_path, monkeypatch, spoolman_url):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: False for n in modules.MODES["server"]}
    mods.update(web=True, ai_intake=True, presets=request.param != "presets-off")
    config.save({"placement": RULES, "modules": mods, "server_name": "Workshop hub", "web": {"lan": ["127.0.0.0/8"]}})
    api = spoolman_url + "/api/v1"
    made = []
    with httpx.Client() as c:
        vendors = {}
        for i, (vendor, name, material, colour) in enumerate(FILAMENTS):
            if vendor not in vendors:
                vendors[vendor] = c.post(api + "/vendor", json={"name": vendor}).json()["id"]
            f = c.post(api + "/filament", json={"vendor_id": vendors[vendor], "name": name, "material": material,
                                                "color_hex": colour, "density": 1.24, "diameter": 1.75, "weight": 1000,
                                                "spool_weight": 200}).json()
            made.append((vendor, name, material, f["id"]))
            c.post(api + "/spool", json={"filament_id": f["id"], "location": "Rack 1" if i % 2 else "Sealed stock",
                                         "remaining_weight": 1000 - 150 * i})
    if request.param in ("waiting-with-a-line", "all-covered"):
        used: set[str] = set()
        ls = {}
        for vendor, name, material, fid in made:
            if request.param == "waiting-with-a-line" and vendor != "Prusament":
                continue
            product = name.rsplit(" ", 1)[0]
            line_id = lines.line_id_for(vendor, product)
            made_id = lines.new_filament_id(used)
            used.add(made_id)
            ls[line_id] = lines.Line(line_id=line_id, vendor=vendor, product=product, material=material, bambu_parent=None,
                                     parent_source="none", filament_id=made_id, created="2026-01-01T00:00:00Z",
                                     filaments=[fid] if request.param == "all-covered" else [])
        lines.save(ls)
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    hid = _history(sm)
    if request.param == "public-address":       # the web unit's page: its address has a path, and it keeps no history (04 7.4)
        site = IntakeApp(mcp_tools.Tools(sm), public_url="https://hub.example.test/f", lan_cidrs=["127.0.0.0/8"], push=False)
        app, path = Starlette(routes=[Mount("/f", routes=site.routes())]), "/f/intake"
    else:
        app, path = Starlette(routes=IntakeApp(mcp_tools.Tools(sm), public_url=None, lan_cidrs=["127.0.0.0/8"], push=False).routes()), "/intake"
    running = serving.start(app)
    try:
        # on the public address a record address shows the same notice as the list, so its page title is the list's: the
        # audit asks for #recent a second time there, to keep every state at the same number of passes
        views = [v.replace("{id}", hid) if "{id}" in v and path == "/intake" else "#recent" if "{id}" in v else v for v in PAGES]
        yield SimpleNamespace(url=running.url + path, views=",".join(views), hid=hid)
    finally:
        running.stop()


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


def test_the_page_audit_passes_on_every_view(served):
    run = _run("--url", served.url, "--views", served.views, "--allow", str(ALLOW))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == len(PAGES) * 2 * 2 and out["failing"] == 0      # seven views, two widths, light and dark



@pytest.mark.parametrize("look", ("console", "palette", "workbench", "panes"))
def test_a_record_opens_with_its_fields_in_every_theme(served, request, look):
    """R298: Palette (a sheet), Workbench (a card) and Panes show the record in a dialog or a pane; it must open there with
    the 13 fields of its one saved item, as in Console where it opens in place, and without a page error."""
    if request.node.callspec.params["served"] != "waiting":
        pytest.skip("one data state is enough: the themes differ in markup, not in data")
    view = "#recent/" + served.hid
    run = _run("--url", served.url, "--views", view, "--widths", "375,1280", "--schemes", "light", "--look", look,
               "--count", f"{view}|.kv__row|13", "--allow", str(ALLOW))
    out = json.loads(run.stdout) if run.stdout.strip() else {}
    bad = [f for r in out.get("report", []) for f in r["findings"] if f["check"] in ("view did not show its content", "page error")]
    assert not bad, bad


def test_the_allow_list_names_a_later_step_and_a_count_on_every_line():
    for line in "".join(p.read_text(encoding="utf-8") for p in sorted(ALLOW.glob("*.txt"))).splitlines():
        if line.strip() and not line.startswith("#"):
            check, where, count, reason = (x.strip() for x in line.split("|"))
            assert check and where and count.isdigit() and int(count) > 0 and "rebuilt by S3." in reason, line


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
