"""The theme picker on the web (design 09 S6.2, 02 3.4, 03 10.2, 04 9.2), in a real headless browser: theme-init.js applies the
device's stored look (or the Hub's default) and sets the two theme-color metas to that look's surface, on the Hub page and in
the web app; the Appearance group (Hub Settings) and the web app's Settings sheet hold the picker with one tile, Console,
selected; a device that has not chosen stays on the Hub's default (Console unless the Hub says otherwise). The AUT-5 audit of
the picker at 320 px with a long Hub name. The same skip rules as the page audit: no Node 22 or no browser is a skip (a
failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from filament_kit import config

from test_hub_page_audit import _run, hub_app, hub_change  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_web_app_audit import served  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
TOKENS = json.loads((ROOT / "tokens" / "tokens.json").read_text(encoding="utf-8"))["themes"]
LIGHT, DARK = "(prefers-color-scheme: light)", "(prefers-color-scheme: dark)"


def _surfaces(look):
    t = TOKENS[look]
    return [t["light"]["surface"].lower(), t["dark"].get("surface", t["light"]["surface"]).lower()]


# shared by the Hub page and the web app: the metas, and theme-init.js run again by a script element (as a page load runs it)
PRELUDE = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
const metas = () => [...document.querySelectorAll('meta[name="theme-color"]')].map((m) => [m.getAttribute("media"), m.content]);
const root = document.documentElement;
const initSrc = [...document.scripts].map((s) => s.src).find((s) => s.includes("/theme-init.js"));
// a page as the server renders it (the default look on the root, the two metas, theme-init.js), loaded as a new document
const load = (look) => new Promise((res, rej) => { const f = document.createElement("iframe");
  f.srcdoc = `<!doctype html><html data-look="${look}"><meta charset="utf-8"><meta name="theme-color" content="#000001" media="(prefers-color-scheme: light)">`
    + `<meta name="theme-color" content="#000002" media="(prefers-color-scheme: dark)"><script src="${initSrc}"><\\/script>`;
  f.onload = () => { const d = f.contentDocument, r = d.documentElement;
    res({ look: r.getAttribute("data-look"), theme: r.getAttribute("data-theme"), metas: [...d.querySelectorAll("meta[name=theme-color]")].map((m) => [m.getAttribute("media"), m.content]) }); f.remove(); };
  f.onerror = () => rej(new Error("frame")); document.body.append(f); });
const picker = () => { const tiles = [...document.querySelectorAll(".theme-picker__tile")]; return { tiles: tiles.length, checked: tiles.filter((t) => $("input", t).checked).map((t) => $(".theme-picker__name", t).textContent),
  line: tiles.map((t) => text($(".theme-picker__line", t))), legend: text($(".theme-picker legend")) }; };
"""

# the Hub's default look is on the root; a device that chose workbench and dark, light, then system; an unknown stored look
INIT = PRELUDE + """
const out = {};
out.notChosen = await load("__DEFAULT__");
localStorage.setItem("spoolwarden.look", "workbench"); localStorage.setItem("spoolwarden.appearance", "dark");
out.chosenDark = await load("__DEFAULT__");
localStorage.setItem("spoolwarden.appearance", "light");
out.chosenLight = await load("__DEFAULT__");
localStorage.removeItem("spoolwarden.appearance");
out.chosenSystem = await load("__DEFAULT__");
localStorage.setItem("spoolwarden.look", "nonsense");
out.unknown = await load("__DEFAULT__");
localStorage.removeItem("spoolwarden.look");
return out;
"""


def _check_init(page, default):
    (d_l, d_d), (w_l, w_d) = _surfaces(default), _surfaces("workbench")
    assert page["notChosen"] == {"look": default, "theme": None, "metas": [[LIGHT, d_l], [DARK, d_d]]}
    assert page["chosenDark"] == {"look": "workbench", "theme": "dark", "metas": [[LIGHT, w_d], [DARK, w_d]]}
    assert page["chosenLight"] == {"look": "workbench", "theme": "light", "metas": [[LIGHT, w_l], [DARK, w_l]]}
    assert page["chosenSystem"] == {"look": "workbench", "theme": None, "metas": [[LIGHT, w_l], [DARK, w_d]]}
    assert page["unknown"] == page["notChosen"]


def test_theme_init_sets_the_metas_of_the_stored_look_on_the_hub_page(hub, tmp_path):
    cfg = config.load()
    cfg["appearance"] = {"theme": "palette"}                    # the Hub's default is another look than the device's choice
    config.save(cfg)
    _check_init(_drive(hub, tmp_path, INIT.replace("__DEFAULT__", "palette")), "palette")


def test_theme_init_sets_the_metas_of_the_stored_look_in_the_web_app(served, tmp_path):  # noqa: F811
    _check_init(_drive(served, tmp_path, INIT.replace("__DEFAULT__", "console")), "console")


def test_theme_init_carries_the_surface_of_every_theme_in_light_and_dark():
    text = (ROOT / "server" / "filament_kit" / "shared_static" / "theme-init.js").read_text(encoding="utf-8")
    for look in TOKENS:
        assert f'"{look}": {json.dumps(_surfaces(look))}' in text


# the picker: one tile, Console, selected; choosing keeps the look on this device and says so; leaving and coming back keeps it
PICKER = PRELUDE + """
const out = {};
localStorage.removeItem("spoolwarden.look");
location.hash = "__HASH__";
await until(() => $(".theme-picker"), "the picker");
out.start = picker();
out.stored = localStorage.getItem("spoolwarden.look");
$(".theme-picker__input").dispatchEvent(new Event("change", { bubbles: true }));       // the one radio is already on: the change is the shared script's
await sleep(300);                                                                      // the result shows 30 ms after the change
out.chose = { stored: localStorage.getItem("spoolwarden.look"), look: root.getAttribute("data-look"),
  result: text($(".theme-picker").parentElement.querySelector(":scope > .result .result__text")), metas: metas() };
location.hash = "__AWAY__";
await until(() => !$(".theme-picker"), "the picker to go");
location.hash = "__HASH__";
await until(() => $(".theme-picker"), "the picker again");
out.again = picker();
out.legendHidden = $(".theme-picker legend").classList.contains("sr");
localStorage.removeItem("spoolwarden.look");
return out;
"""


def _check_picker(page, hidden):
    console = _surfaces("console")
    assert page["start"]["tiles"] == 1 and page["start"]["checked"] == [T("theme_console_name")]
    assert page["start"]["line"] == [T("theme_console_line")] and page["start"]["legend"] == T("appearance_theme_title")
    assert page["stored"] is None                                # nothing is written until the device chooses
    assert page["chose"]["stored"] == "console" and page["chose"]["look"] == "console"
    assert page["chose"]["result"] == T("appearance_theme_saved", name=T("theme_console_name"))
    assert [m[1] for m in page["chose"]["metas"]] in ([console[0]] * 2, [console[1]] * 2)
    assert page["again"] == page["start"]
    assert page["legendHidden"] is hidden


def test_the_hub_settings_appearance_group_holds_the_picker_with_console_selected(hub, tmp_path):
    page = _drive(hub, tmp_path, PICKER.replace("__HASH__", "#settings/appearance").replace("__AWAY__", "#overview"))
    _check_picker(page, hidden=False)


def test_the_web_app_settings_holds_the_picker_with_console_selected(served, tmp_path):  # noqa: F811
    page = _drive(served, tmp_path, PICKER.replace("__HASH__", "#settings").replace("__AWAY__", "#add"))
    _check_picker(page, hidden=True)


def test_the_picker_is_audited_at_320_px_with_a_long_hub_name(hub):
    cfg = config.load()
    cfg["server_name"] = "The-Workshop-Hub-in-the-garage-behind-the-house-north-wing"
    config.save(cfg)
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else []
    ready = """(async () => { location.hash = "#settings/appearance";
      for (let i = 0; i < 300 && !document.querySelector(".theme-picker"); i++) await new Promise((r) => setTimeout(r, 100)); })()"""
    run = _run("--url", hub, "--views", "#settings/appearance", "--ready", ready, *fonts)
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == 4 and out["failing"] == 0
