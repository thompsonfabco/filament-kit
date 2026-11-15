"""Workbench on the web (design 09 S6.4, 02 1.3, 08 9 and test 4 of 08), in a real headless browser where it matters: the three
profile groups `nav=sidebar`, `collection=cards` and `detail=card` of components.css are keyed on Workbench only (Console's groups
do not mention it, Workbench's do not hold an unqualified rule); the Hub page and the web app show Workbench (sidebar on a wide
screen, the rail on a tablet, the bottom bar on a phone, cards in a grid) and Console is the same after a visit to Workbench;
the picker offers the Workbench tile in both interfaces; and AUT-5 passes on both in Workbench, light and dark, at 320, 768 and
1280 px. The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from test_hub_page_audit import ALLOW as HUB_ALLOW, VIEWS as HUB_VIEWS, _run, hub_app, hub_change  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_hub_theme_picker import _surfaces
from test_web_app_audit import ALLOW as WEB_ALLOW, VIEWS as WEB_VIEWS, served  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "web-shared" / "components.css").read_text(encoding="utf-8")
SERVED_CSS = (ROOT / "server" / "filament_kit" / "shared_static" / "components.css").read_text(encoding="utf-8")
WB = ':root[data-look="workbench"]'
GROUP = re.compile(r"/\*\s*profile:\s*([a-z-]+)=([a-z-]+)[^*]*\*/")


def _groups(css):
    """{(key, choice): [selector, ...]} of every `/* profile: key=choice */` group (a group runs to the next one)."""
    marks = list(GROUP.finditer(css))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(css)
        body = re.sub(r"/\*.*?\*/", "", css[m.end():end], flags=re.S)
        heads = [h for h in re.findall(r"([^{}]+)\{", body) if not h.strip().startswith("@")]
        out[m.groups()] = [s.strip() for h in heads for s in h.split(",") if s.strip()]
    return out


def test_the_three_workbench_groups_are_keyed_on_workbench_and_console_groups_are_not():
    for css in (CSS, SERVED_CSS):                                # the served copy is the one the Hub sends
        groups = _groups(css)
        for group in (("nav", "sidebar"), ("collection", "cards"), ("detail", "card")):
            assert groups.get(group), f"no profile group {group}"
            leaks = [s for s in groups[group] if not s.startswith(WB + " ")]
            assert not leaks, (group, "a rule not keyed on Workbench", leaks[:3])
        for group in (("nav", "rail"), ("collection", "table"), ("detail", "inline")):
            assert groups[group], group
            assert not [s for s in groups[group] if "workbench" in s], (group, "Workbench in a Console group")


def test_every_rule_of_the_workbench_groups_is_inside_a_group_of_a_profile_choice_and_no_other_theme_is_keyed():
    groups = _groups(CSS)
    seen = {m for sels in groups.values() for s in sels for m in re.findall(r'data-look="([a-z]+)"', s)}
    assert seen == {"workbench"}                                  # Palette and Panes arrive with S6.6 and S6.8


def test_the_card_width_is_18rem_so_cards_grow_with_the_text_size():
    for css in (CSS, SERVED_CSS):
        cards = " ".join(_groups(css)[("collection", "cards")])
        assert "minmax(min(100%,18rem),1fr)" in re.sub(r"\s+", "", css) and "calc(var(--s7) * 6)" not in css
        assert ".coll__row--result>.coll__cell" not in cards                     # the card's own cell rule already sets that padding


# the sidebar is the Hub page's (04 2.3: the web app keeps its tablet layout above 1024 px): the web app's body carries data-ai
APP_NAV = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const r = document.documentElement;
await until(() => document.querySelector(".shell > .nav .nav__item"), "the navigation");
const m = (look) => { r.setAttribute("data-look", look); const cs = (el) => getComputedStyle(el), item = document.querySelector(".shell .nav__item");
  return { cols: cs(document.querySelector(".shell")).gridTemplateColumns, dir: cs(item).flexDirection, rail: cs(r).getPropertyValue("--rail").trim(),
    heading: Math.round(document.querySelector(".shell .nav__heading").getBoundingClientRect().width) }; };
return { console: m("console"), workbench: m("workbench"), hubPage: !!document.body.hasAttribute("data-ai") === false };
"""


def test_the_web_app_keeps_its_rail_at_1280_px_in_workbench(served, tmp_path):  # noqa: F811
    app = _drive(served, tmp_path, APP_NAV, width=1280)
    assert app["workbench"]["dir"] == "column" and app["workbench"]["cols"].split(" ")[0] == app["workbench"]["rail"]
    assert app["workbench"]["heading"] <= 1 and app["hubPage"] is False


def test_the_hub_page_gets_the_sidebar_at_1280_px_in_workbench(hub, tmp_path):
    page = _drive(hub, tmp_path, APP_NAV, width=1280)
    assert page["workbench"]["dir"] == "row" and page["workbench"]["cols"].split(" ")[0] == "256px" and page["workbench"]["heading"] > 50
    assert page["console"]["dir"] == "column" and page["hubPage"] is True


# Recently added: the chevron cell (`go`) is for rows only (02 6.1), so a card does not show it
GO = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const r = document.documentElement;
location.hash = "#recent";
const go = await until(() => document.querySelector('.coll__cell[data-col="go"]'), "a go cell");
await sleep(300);
const d = (look) => { r.setAttribute("data-look", look); return getComputedStyle(go).display; };
return { console: d("console"), workbench: d("workbench"), back: d("console") };
"""


def test_the_go_chevron_shows_in_rows_and_not_on_cards(hub, tmp_path):
    got = _drive(hub, tmp_path, GO)
    assert got["workbench"] == "none" and got["console"] != "none" and got["back"] == got["console"]


# the Hub page's metrics under each look at one width (the driver opens the page at that width, so its media queries answer)
STYLES = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement;
function metrics(look) {
  if (look) r.setAttribute("data-look", look); else r.removeAttribute("data-look");
  const $ = (s) => d.querySelector(s), cs = (el) => getComputedStyle(el);
  const nav = $(".shell > .nav"), item = $(".shell .nav__item"), heading = $(".shell .nav__heading"), coll = $(".coll--printers");
  const card = $(".coll--printers .coll__item"), title = $(".coll--printers .coll__title");
  const lefts = [...d.querySelectorAll(".coll--printers > .coll__item")].map((i) => Math.round(i.getBoundingClientRect().left));
  return { navPos: cs(nav).position, itemDir: cs(item).flexDirection, itemJustify: cs(item).justifyContent, headingW: Math.round(heading.getBoundingClientRect().width),
    cols: cs($(".shell")).gridTemplateColumns, collDisplay: cs(coll).display, collBorder: cs(coll).borderTopWidth,
    cardDisplay: cs(card).display, cardBorder: cs(card).borderTopWidth, cardPad: cs(card).paddingTop, cardRadius: cs(card).borderTopLeftRadius,
    titleSize: cs(title).fontSize, columns: new Set(lefts).size, sideW: cs(r).getPropertyValue("--side-w").trim(), rail: cs(r).getPropertyValue("--rail").trim() };
}
location.hash = "#printers";
await until(() => d.querySelector(".coll--printers .coll__item"), "the printers list");
await sleep(300);
const first = metrics(null);
return { first, wb: metrics("workbench"), back: metrics("console"), unknown: metrics("nonesuch"), none: metrics(null) };
"""


def _check_styles(wide, tablet, phone):
    for w, got in ((1280, wide), (768, tablet), (320, phone)):
        console, wb = got["first"], got["wb"]
        assert got["back"] == console, (w, "Console is not the same after Workbench")
        assert got["unknown"] == console and got["none"] == console, (w, "an unknown or missing look is Console's arrangement")
        assert wb["cardDisplay"] == "flex" and wb["cardBorder"] == "1px" and wb["cardPad"] == "16px", (w, wb)
        assert wb["collDisplay"] == "grid" and wb["collBorder"] == "0px" and wb["titleSize"] == "17px", (w, wb)
        assert console["cardPad"] != "16px" and console["titleSize"] != wb["titleSize"], (w, console)
    assert wide["wb"]["itemDir"] == "row" and wide["wb"]["itemJustify"] == "flex-start"        # wide: the labelled sidebar
    assert wide["wb"]["cols"].split(" ")[0] == wide["wb"]["sideW"] == "256px" and wide["wb"]["headingW"] > 50
    assert wide["first"]["itemDir"] == "column" and wide["first"]["cols"].split(" ")[0] == wide["first"]["rail"]
    assert wide["first"]["headingW"] <= 1
    assert tablet["wb"]["itemDir"] == "column" and tablet["wb"]["cols"].split(" ")[0] == tablet["wb"]["rail"] and tablet["wb"]["headingW"] <= 1   # the rail form
    assert phone["wb"]["navPos"] == "fixed" == phone["first"]["navPos"]                        # phone: the bottom bar
    assert wide["wb"]["columns"] == 2 and phone["wb"]["columns"] == 1                          # two printers: two cards wide, one card on a phone


def test_workbench_shows_in_the_hub_page_at_three_widths_and_console_is_unchanged(hub, tmp_path):
    _check_styles(*(_drive(hub, tmp_path, STYLES, width=w) for w in (1280, 768, 320)))


# the picker: Workbench is chosen, applies at once, is kept on this device, shows the Workbench surface in the status bar, and
# is still the chosen tile after leaving Settings and coming back (the picker is built again from the root's look)
CHOOSE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
const root = document.documentElement;
const tiles = () => [...document.querySelectorAll(".theme-picker__tile")].map((t) => ({ name: text($(".theme-picker__name", t)), on: $("input", t).checked, look: $("input", t).value,
  preview: $(".theme-picker__preview", t).getAttribute("data-look") }));
localStorage.removeItem("spoolwarden.look"); localStorage.removeItem("spoolwarden.appearance");
location.hash = "__HASH__";
await until(() => $(".theme-picker"), "the picker");
const out = { start: tiles() };
const radio = [...document.querySelectorAll(".theme-picker__input")].find((i) => i.value === "workbench");
radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true }));
await sleep(300);
out.chose = { stored: localStorage.getItem("spoolwarden.look"), look: root.getAttribute("data-look"), tiles: tiles(),
  result: text($(".theme-picker").parentElement.querySelector(":scope > .result .result__text")),
  metas: [...document.querySelectorAll('meta[name="theme-color"]')].map((m) => m.content.toLowerCase()), surface: getComputedStyle(root).getPropertyValue("--surface").trim().toLowerCase() };
location.hash = "__AWAY__";
await until(() => !$(".theme-picker"), "the picker to go");
location.hash = "__HASH__";
await until(() => $(".theme-picker"), "the picker again");
out.again = tiles();
const back = [...document.querySelectorAll(".theme-picker__input")].find((i) => i.value === "console");
back.checked = true; back.dispatchEvent(new Event("change", { bubbles: true }));
await sleep(300);
out.console = { stored: localStorage.getItem("spoolwarden.look"), look: root.getAttribute("data-look"), tiles: tiles() };
localStorage.removeItem("spoolwarden.look");
return out;
"""


def _check_choose(page):
    names = [T("theme_console_name"), T("theme_workbench_name")]
    assert page["start"] == [{"name": names[0], "on": True, "look": "console", "preview": "console"},
                             {"name": names[1], "on": False, "look": "workbench", "preview": "workbench"}]
    chose = page["chose"]
    assert chose["stored"] == "workbench" and chose["look"] == "workbench"
    assert [t["on"] for t in chose["tiles"]] == [False, True]
    assert chose["result"] == T("appearance_theme_saved", name=names[1])
    assert chose["metas"] == [chose["surface"]] * 2 and chose["surface"] in _surfaces("workbench")
    assert [t["on"] for t in page["again"]] == [False, True]                      # the choice survives the redraw
    assert page["console"]["stored"] == "console" and page["console"]["look"] == "console"
    assert [t["on"] for t in page["console"]["tiles"]] == [True, False]


def test_the_hub_settings_picker_offers_workbench_and_keeps_the_choice(hub, tmp_path):
    _check_choose(_drive(hub, tmp_path, CHOOSE.replace("__HASH__", "#settings/appearance").replace("__AWAY__", "#overview")))


def test_the_web_app_settings_picker_offers_workbench_and_keeps_the_choice(served, tmp_path):  # noqa: F811
    _check_choose(_drive(served, tmp_path, CHOOSE.replace("__HASH__", "#settings").replace("__AWAY__", "#add")))


# AUT-5 in Workbench: the device's choice is stored the way the picker stores it, then every view is audited, light and dark
WORKBENCH = """(async () => {
  document.documentElement.setAttribute("data-look", "workbench");
  const all = (list) => [...list].flatMap((r) => (r.selectorText ? [r] : r.cssRules ? all(r.cssRules) : []));          // a rule inside a media query too
  const rules = [...document.styleSheets].flatMap((s) => all(s.cssRules)).filter((r) => r.selectorText && r.selectorText.startsWith(':root[data-look="workbench"]'));
  for (const part of [".nav__item", ".coll__item", ".detail"]) if (!rules.some((r) => r.selectorText.includes(part))) throw new Error("no Workbench rule for " + part);
})()"""


def _audit(url, views, allow, per_scheme):
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else []
    run = _run("--url", url, "--views", views, "--allow", str(allow), "--widths", "1280,768,320", "--schemes", "light,dark",
               "--ready", WORKBENCH, *fonts)
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == per_scheme * 3 * 2 and out["failing"] == 0         # three widths, light and dark


def test_the_hub_page_passes_the_audit_in_workbench_light_and_dark_at_three_widths(hub):
    _audit(hub, HUB_VIEWS, HUB_ALLOW, len(HUB_VIEWS.split(",")))


def _workbench_allow(tmp_path):
    """The web app's allow-list (counts of the findings a later step removes, for 1280 and 320 px) as it reads for 1280, 768 and 320:
    a finding that is there at every width counts half as often again; one that Console's 40 px controls cause at 1280 px is not
    there in Workbench (its controls are 44 px). It follows the shipped list, so a screen rebuilt by S3.8 or S3.10 lowers both."""
    out = []
    for line in "".join(p.read_text(encoding="utf-8") for p in sorted(WEB_ALLOW.glob("*.txt"))).splitlines():
        if line.strip() and not line.startswith("#"):
            check, where, count, reason = (x.strip() for x in line.split("|"))
            if "at 1280 px" in reason:
                assert check.startswith("hit area under 44"), line
                continue
            assert int(count) % 2 == 0, line
            out.append(f"{check} | {where} | {int(count) * 3 // 2} | {reason}")
    (tmp_path / "workbench.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    return tmp_path


def test_the_web_app_passes_the_audit_in_workbench_light_and_dark_at_three_widths(served, tmp_path):  # noqa: F811
    _audit(served, WEB_VIEWS, _workbench_allow(tmp_path), len(WEB_VIEWS.split(",")))
