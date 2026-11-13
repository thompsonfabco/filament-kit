"""AUT-5 on the web app (design 09 S3.4, 07 section 15): the page audit (tests/page_audit.js) in every view, Console
light and dark, at 1280 px and 320 px, through tests/aut5_run.mjs in a headless Chrome, Edge or Chromium already on
the machine. Example data only (mockups/CONTENT-SPEC.md: "Workshop hub", invented filaments).

Findings of today's markup that a later step rebuilds are listed in tests/aut5_allowlist.txt; a line nothing matches
fails the run. Skipped when Node 22+ or a Chromium-family browser is missing (the runner exits 2 for "no browser")."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette

from fakes import serving
from filament_kit import config, modules
from filament_kit.spoolman import Spoolman
from filament_kit.web import mcp_tools
from filament_kit.web.intake_app import IntakeApp

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "aut5_run.mjs"
ALLOW = ROOT / "tests" / "aut5_allowlist.txt"
VIEWS = "#add,#spools,#printers,#recent,#presets,#settings"
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
         "sealed_location": "Sealed stock"}
FILAMENTS = [("Polymaker", "PolyTerra PLA Charcoal Black", "PLA", "2B2B2E"),
             ("Bambu Lab", "PETG HF Orange", "PETG", "F2762E"),
             ("eSUN", "ABS+ White", "ABS", "F4F4F2"),
             ("Prusament", "PLA Galaxy Silver", "PLA", "8D9199")]


@pytest.fixture
def served(tmp_path, monkeypatch, spoolman_url):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: False for n in modules.MODES["server"]}
    mods.update(web=True, ai_intake=True, presets=True)
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
    app = Starlette(routes=IntakeApp(mcp_tools.Tools(sm), public_url=None, lan_cidrs=["127.0.0.0/8"], push=False).routes())
    running = serving.start(app)
    try:
        yield running.url + "/intake"
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
    run = _run("--url", served, "--views", VIEWS, "--allow", str(ALLOW))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == 6 * 2 * 2 and out["failing"] == 0      # six views, two widths, light and dark


def test_the_allow_list_names_a_later_step_and_a_count_on_every_line():
    for line in ALLOW.read_text(encoding="utf-8").splitlines():
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
