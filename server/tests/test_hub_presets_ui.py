"""The Slicer presets section of the Hub page (design 09 S2.10, 03 section 8), pressed in a real headless browser through
tests/page_drive.mjs: each control reaches the same Hub route as before (the Hub's own functions are watched, in order), and
the page says what the catalogue says. The page is served with the data of test_hub_page_audit.py (a first install and a
rebuild with an update waiting). The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with
AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from filament_kit import cli, profiles_api
from filament_kit.profiles import builds

from test_hub_page_audit import _missing, _node, _serve, hub_app  # noqa: F401
from test_setup_page import CODE

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tests" / "page_drive.mjs"
SCRIPT = ROOT / "tests" / "hub_presets_drive.js"
TEXTS = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))


class AsHttps:
    """ASGI wrapper for a test server that has no certificate: the Hub's changes accept only an Origin of https://<host>
    (setup_page._origin_ok), so the browser's http origin is sent on as that (the shipped code is untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope["headers"]).get(b"host", b"")
            scope["headers"] = [(k, b"https://" + host if k == b"origin" else v) for k, v in scope["headers"]]
        await self.app(scope, receive, send)


@pytest.fixture
def hub(hub_app):  # noqa: F811
    running = _serve(AsHttps(hub_app[0]), hub_app[1])
    try:
        yield running.url + "/setup"
    finally:
        running.stop()


def T(key: str, **v) -> str:
    """A catalogue text with its variables filled in (the plural form by `count`, as SW.t)."""
    text = TEXTS[key]
    if isinstance(text, dict):
        text = text["one" if v.get("count") == 1 else "other"]
    for name, value in v.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _drive(url: str, tmp_path: Path, script: str | None = None, width: int = 1280) -> dict:
    node = _node()
    if not node:
        _missing("the page driver needs Node 22 or later")
    file = tmp_path / "drive.js"
    file.write_text((script or SCRIPT.read_text(encoding="utf-8")).replace("__CODE__", CODE), encoding="utf-8")
    run = subprocess.run([node, str(DRIVER), "--url", url, "--script", str(file), "--width", str(width)], capture_output=True, text=True, timeout=300)
    if run.returncode == 2 and "no Chrome, Edge or Chromium" in run.stderr:
        _missing("the page driver needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if run.returncode == 3:
        _missing("page driver: " + run.stderr.strip().replace("AUT-5: ", "", 1))
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout)


CHOSEN = [{"line_id": "l1", "target": "bambu", "name": "Generic PLA @BBL X1C", "file": "p.json", "keys": list("abcdefg")},
          {"line_id": "l2", "target": "orca", "name": "Polymaker PLA", "file": None, "keys": ["x"]}]


def test_every_control_of_the_section_reaches_its_hub_route(hub, monkeypatch, tmp_path):
    seen: list = []
    real_parent, real_status = cli.set_parent_checked, profiles_api._status_view
    refused = []

    def status_view():
        """The Hub's status with Slicer Sync reported in and two updates waiting (the section reads this)."""
        return {**real_status(), "pc": {"last_upload": None}, "updates": {"count": 2, "lines": 2, "accepted": 0, "yours": 1}}

    def apply_updates(line_id=None, all_=False, dry_run=True, only=None, expect_stamp=None):
        if dry_run:
            seen.append(("dry run", line_id, all_))
            return {"stamp": "s1", "chosen": CHOSEN}
        if not refused:
            refused.append(1)                                        # a build came after the first list: the 409, once
            seen.append(("accept refused", sorted(only), expect_stamp))
            raise builds.UpdatesChanged()
        seen.append(("accept", line_id, all_, sorted(only), expect_stamp))
        return {"stamp": "s1", "chosen": CHOSEN}

    def set_parent_checked(line_id, parent, orca=False):
        seen.append(("set parent", line_id, parent, orca))
        return real_parent(line_id, parent, orca=orca)

    monkeypatch.setattr(builds, "request_rebuild", lambda reason: seen.append(("build", reason)))
    monkeypatch.setattr(builds, "restore_deleted_next", lambda: seen.append(("restore flag",)))
    monkeypatch.setattr(builds, "apply_updates", apply_updates)
    monkeypatch.setattr(cli, "set_parent_checked", set_parent_checked)
    monkeypatch.setattr(profiles_api, "_status_view", status_view)
    monkeypatch.setattr(profiles_api, "_parents", lambda material: {"parents": ["Bambu PLA Basic", "Generic PLA"], "synced": True})

    page = _drive(hub, tmp_path)

    names = sorted(c["name"] for c in CHOSEN)
    assert seen[:7] == [("build", "asked for on the setup page"),                       # Build now
                        ("restore flag",), ("build", "restore presets deleted in Bambu Studio"),   # Bring back deleted presets
                        ("dry run", None, True),                                         # Show what would change
                        ("accept refused", names, "s1"),                                 # Accept these: out of date, once
                        ("dry run", None, True),
                        ("accept", None, True, names, "s1")], seen                      # what the list showed, and its build
    assert seen[7][:3] == ("set parent", page["lineId"], "Generic PLA") and seen[7][3] is False and seen[8][0] == "build" and len(seen) == 9, seen

    # the section's own words, from the catalogue
    assert page["title"] == T("nav_slicer_presets")
    assert page["cards"] == [T("presets_build_title"), T("presets_updates_title"), T("presets_lines_title")]
    assert page["head"][1] == T("presets_build_now") and T("presets_meta_sync") in page["head"][0]
    assert page["slicerSync"] == f"{T('status_ok')} {T('presets_sync_ok')}"
    assert page["columns"][1:] == [T("common_field_line"), T("common_field_material"), T("presets_col_presets"),
                                   T("common_field_bambu_parent"), *([T("presets_col_orca_parent")] if len(page["columns"]) == 7 else []), T("common_actions")]
    assert page["build"] == T("presets_build_asked")
    assert page["restore"] == T("presets_restore_asked")
    assert page["shown"]["result"].startswith(T("presets_updates_would", count=2))
    assert page["shown"]["items"] == [
        T("presets_updates_line", target=T("presets_target_bambu"), name=CHOSEN[0]["name"], file="p.json", keys="a, b, c, d, e, f, …"),
        T("presets_updates_line_nofile", target=T("presets_target_orca"), name=CHOSEN[1]["name"], keys="x")]
    assert page["stale"] == T("presets_updates_stale") and page["staleAcceptLeft"] is False
    assert page["accepted"] == T("presets_updates_accepted_result", count=2)
    assert page["menu"][0] == T("presets_target_bambu")
    assert page["dialogTitle"].startswith(T("presets_parent_title", line="").strip()) and page["dialogLabel"] == T("presets_parent_label")
    assert page["options"] == ["Bambu PLA Basic", "Generic PLA"]
    assert page["parentSaved"] == T("presets_parent_saved")
    assert page["parentShown"].startswith(T("common_field_bambu_parent") + "Generic PLA")


WAIT = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 100; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
location.hash = "#presets";
"""


def test_on_a_phone_the_parents_are_in_the_rows_expansion(hub, tmp_path):
    page = _drive(hub, tmp_path, WAIT + """
await until(() => $(".coll--lines .coll__item"), "the product lines");
const item = $(".coll--lines .coll__item"), expand = $(".coll__expand", item), detail = $(".detail", item);
const before = { hidden: detail.hidden, shown: !!detail.getClientRects().length, parentCells: [...item.querySelectorAll('[data-prio="3"]')].some((c) => c.getClientRects().length) };
expand.click();
await until(() => !detail.hidden, "the expansion");
return { before, expanded: expand.getAttribute("aria-expanded"), facts: [...detail.querySelectorAll(".kv__key")].map(text), shown: !!detail.getClientRects().length };
""", width=320)
    assert page["before"] == {"hidden": True, "shown": False, "parentCells": False}       # the parents are not in the row itself
    assert page["expanded"] == "true" and page["shown"] is True and page["facts"][0] == T("common_field_bambu_parent")


def test_switched_off_the_section_says_so_and_offers_features(hub_app, tmp_path):
    from filament_kit import config
    cfg = config.load()
    cfg["modules"]["presets"] = False
    config.save(cfg)
    running = _serve(*hub_app)
    try:
        page = _drive(running.url + "/setup", tmp_path, WAIT + """
await until(() => $(".empty"), "the switched off state");
return { title: text($(".empty__title")), text: text($(".empty__text")), link: $(".empty a").getAttribute("href"),
  build: !!$('[data-action="build"]'), cards: document.querySelectorAll("main .card").length };
""")
    finally:
        running.stop()
    assert page == {"title": T("presets_off_title"), "text": T("presets_off_text"), "link": "#features", "build": False, "cards": 0}
