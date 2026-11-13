"""AUT-5 on the web app (design 09 S3.4, 07 section 15): the page audit (tests/page_audit.js) in every view, Console
light and dark, at 1280 px and 320 px, through tests/aut5_run.mjs in a headless Chrome, Edge or Chromium already on
the machine. Example data only (mockups/CONTENT-SPEC.md: "Workshop hub", invented filaments).

Findings of today's markup that a later step rebuilds are listed in tests/aut5_allowlist.txt; a line nothing matches
fails the run. Skipped when Node 22+ or a Chromium-family browser is missing (the runner exits 2 for "no browser")."""
from __future__ import annotations

import json
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


def test_the_page_audit_passes_on_every_view(served):
    node = _node()
    if not node:
        pytest.skip("AUT-5 needs Node 22 or later")
    run = subprocess.run([node, str(RUNNER), "--url", served, "--views", VIEWS, "--allow", str(ALLOW)],
                         capture_output=True, text=True, timeout=600)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        pytest.skip("AUT-5 needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == 6 * 2 * 2 and out["failing"] == 0      # six views, two widths, light and dark


def test_the_allow_list_names_a_later_step_on_every_line():
    for line in ALLOW.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            check, where, reason = (x.strip() for x in line.split("|"))
            assert check and where and "rebuilt by S3." in reason, line
