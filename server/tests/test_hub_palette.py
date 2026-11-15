"""Palette on the web (design 09 S6.6, 02 1.3, 08 9 and test 4 of 08), in a real headless browser where it matters: the three
profile groups `nav=pills`, `collection=tiles` and `detail=sheet` of components.css are keyed on Palette only (Console's and
Workbench's groups do not mention it, Palette's do not hold an unqualified rule or a Workbench one); the Hub page and the web app
show Palette (pills under the top bar from tablet up, the bottom bar on a phone, tiles in a grid, the rounded system font, an open
detail in the sheet) and Console and Workbench are the same after a visit to Palette; the picker offers the Palette tile in both
interfaces; and AUT-5 passes on both in Palette, light and dark, at 320, 768 and 1280 px. The same skip rules as the page audit:
no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os
import re

from test_hub_page_audit import ALLOW as HUB_ALLOW, VIEWS as HUB_VIEWS, _run, hub_app, hub_change  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_hub_theme_picker import _surfaces
from test_hub_workbench import CSS, SERVED_CSS, _groups, _workbench_allow
from test_web_app_audit import VIEWS as WEB_VIEWS, served  # noqa: F401

PAL = ':root[data-look="palette"]'


def test_the_three_palette_groups_are_keyed_on_palette_and_the_other_groups_are_not():
    for css in (CSS, SERVED_CSS):                                # the served copy is the one the Hub sends
        groups = _groups(css)
        for group in (("nav", "pills"), ("collection", "tiles"), ("detail", "sheet")):
            assert groups.get(group), f"no profile group {group}"
            leaks = [s for s in groups[group] if not s.startswith(PAL + " ")]
            assert not leaks, (group, "a rule not keyed on Palette", leaks[:3])
        for group in (("nav", "rail"), ("collection", "table"), ("detail", "inline"), ("nav", "sidebar"), ("collection", "cards"), ("detail", "card")):
            assert groups[group], group
            assert not [s for s in groups[group] if "palette" in s], (group, "Palette in another theme's group")


def test_a_palette_rule_stays_in_its_own_group_and_the_looks_keyed_are_workbench_and_palette():
    groups = _groups(CSS)
    seen = {m for sels in groups.values() for s in sels for m in re.findall(r'data-look="([a-z]+)"', s)}
    assert seen == {"workbench", "palette", "panes"}
    assert [g for g, sels in groups.items() if any("workbench" in s for s in sels)] == [("nav", "sidebar"), ("collection", "cards"), ("detail", "card")]
    assert [g for g, sels in groups.items() if any("palette" in s for s in sels)] == [("nav", "pills"), ("collection", "tiles"), ("detail", "sheet")]


def test_the_core_stylesheet_stays_under_60_kb_with_palette():
    assert len(CSS.encode("utf-8")) < 60_000 and CSS == SERVED_CSS


# the Hub page's metrics under each look at one width (the driver opens the page at that width, so its media queries answer)
STYLES = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement;
const all = (list) => [...list].flatMap((x) => (x.selectorText ? [x] : x.cssRules ? all(x.cssRules) : []));
const sans = (look) => { const sel = look === "palette" ? ':root[data-look="palette"]' : ":root";            // the stylesheet's own value (the driver pins the page's font for the audit)
  return all([...d.styleSheets].flatMap((s) => [...s.cssRules])).filter((x) => x.selectorText === sel).map((x) => x.style.getPropertyValue("--sans")).filter(Boolean).join("|"); };
function metrics(look) {
  if (look) r.setAttribute("data-look", look); else r.removeAttribute("data-look");
  const $ = (s) => d.querySelector(s), cs = (el, p) => getComputedStyle(el, p), box = (el) => el.getBoundingClientRect();
  const nav = $(".shell > .nav"), item = $(".shell .nav__item"), heading = $(".shell .nav__heading"), coll = $(".coll--printers");
  const card = $(".coll--printers .coll__item"), title = $(".coll--printers .coll__title"), top = $(".topbar");
  const lefts = [...d.querySelectorAll(".coll--printers > .coll__item")].map((i) => Math.round(box(i).left));
  const current = $('.shell .nav__item[aria-current="page"]');
  return { navPos: cs(nav).position, itemDir: cs(item).flexDirection, itemJustify: cs(item).justifyContent, headingW: Math.round(box(heading).width),
    itemRadius: cs(item).borderTopLeftRadius, currentBg: current ? cs(current).backgroundColor : null, currentMark: current ? cs(current, "::before").content : null,
    navBelowTop: Math.round(box(nav).top) >= Math.round(box(top).bottom) - 1, navW: Math.round(box(nav).width),
    cols: cs($(".shell")).gridTemplateColumns, collDisplay: cs(coll).display, collBorder: cs(coll).borderTopWidth,
    cardDisplay: cs(card).display, cardBorder: cs(card).borderTopWidth, cardPad: cs(card).paddingTop, cardRadius: cs(card).borderTopLeftRadius,
    titleSize: cs(title).fontSize, titleWeight: cs(title).fontWeight, columns: new Set(lefts).size, tileCount: lefts.length, font: sans(look), rail: cs(r).getPropertyValue("--rail").trim(),
    hiddenPrio2: [...d.querySelectorAll('.coll--printers .coll__cell[data-prio="2"]')].every((c) => cs(c).display === "none"), hasPrio2: !!$('.coll--printers .coll__cell[data-prio="2"]'),
    key: cs($(".coll--printers .coll__key"), "::after").content };
}
location.hash = "#printers";
await until(() => d.querySelector(".coll--printers .coll__item"), "the printers list");
await sleep(300);
const first = metrics(null);
return { first, palette: metrics("palette"), wb: metrics("workbench"), back: metrics("console"), unknown: metrics("nonesuch"), none: metrics(null) };
"""


def _check_styles(wide, tablet, phone):
    for w, got in ((1280, wide), (768, tablet), (320, phone)):
        console, pal = got["first"], got["palette"]
        assert got["back"] == console, (w, "Console is not the same after Palette")
        assert got["unknown"] == console and got["none"] == console, (w, "an unknown or missing look is Console's arrangement")
        assert pal["cardDisplay"] == "flex" and pal["cardBorder"] == "1px" and pal["cardPad"] == "16px" and pal["cardRadius"] == "14px", (w, pal)
        assert pal["collDisplay"] == "grid" and pal["collBorder"] == "0px" and pal["titleSize"] == "20px" and pal["titleWeight"] == "750", (w, pal)
        assert pal["hiddenPrio2"] and pal["key"] == '": "', (w, pal)                  # tiles show the first-priority fields, with their field names
        assert "ui-rounded" in pal["font"] and "ui-rounded" not in console["font"], (w, pal["font"], console["font"])
        assert console["cardPad"] != "16px" and console["titleSize"] != pal["titleSize"], (w, console)
        assert got["wb"]["cardRadius"] != pal["cardRadius"] and got["wb"]["font"] != pal["font"], (w, "Workbench and Palette differ")
    for w, got in ((1280, wide["palette"]), (768, tablet["palette"])):
        assert got["itemDir"] == "row" and got["navPos"] == "sticky" and got["navBelowTop"] and got["navW"] >= w - 32, (w, got)       # pills under the top bar, full width
        assert got["cols"].count(" ") == 0 and got["headingW"] <= 1 and got["itemRadius"] == "20px", (w, got)
        assert got["currentBg"] not in (None, "rgba(0, 0, 0, 0)") and got["currentMark"] in ("none", "normal"), (w, got)
    assert wide["first"]["itemDir"] == "column" and wide["first"]["cols"].split(" ")[0] == wide["first"]["rail"]
    assert phone["palette"]["navPos"] == "fixed" == phone["first"]["navPos"]                  # phone: the bottom bar, as every look
    assert wide["palette"]["columns"] == 2 and phone["palette"]["columns"] == 1               # two printers: two tiles wide, one tile on a phone


def test_palette_shows_in_the_hub_page_at_three_widths_and_console_is_unchanged(hub, tmp_path):
    _check_styles(*(_drive(hub, tmp_path, STYLES, width=w) for w in (1280, 768, 320)))


# the rework items: the tablet top bar keeps the light/dark switch on one row (02 4.3), an open in-row detail spans the grid, the pill
# row stays under the top bar while the page scrolls (02 2.3), and the active pill is not bolder than the others (02 2.3 table)
REWORK = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s) => d.querySelector(s), box = (el) => el.getBoundingClientRect();
r.setAttribute("data-look", "palette");
location.hash = "#printers";
await until(() => $(".coll--printers .coll__expand"), "the printers list");
await sleep(300);
const tops = [...d.querySelectorAll(".topbar .appearance .segmented__option")].filter((o) => o.offsetParent).map((o) => Math.round(box(o).top));
const cur = $('.shell .nav__item[aria-current="page"] .nav__label'), other = $('.shell .nav__item:not([aria-current]) .nav__label');
const out = { topbarH: Math.round(box($(".topbar")).height), segTops: tops, weights: [getComputedStyle(cur).fontWeight, getComputedStyle(other).fontWeight],
  scrollW: r.scrollWidth, clientW: r.clientWidth };
$(".coll--printers .coll__expand").click();
await sleep(500);
const region = $(".coll--printers .coll__row--detail:not([hidden]) .detail"), coll = $(".coll--printers");
out.detailW = Math.round(box(region).width); out.collW = Math.round(box(coll).width);
scrollTo(0, 400); await sleep(400);
out.navGap = Math.round(box($(".shell > .nav")).top - box($(".topbar")).bottom); out.scrolled = Math.round(scrollY);
return out;
"""


def test_the_palette_tablet_top_bar_stays_one_row_the_detail_spans_the_grid_and_the_pills_stay_with_the_top_bar(hub, tmp_path):
    tablet = _drive(hub, tmp_path, REWORK, width=768)
    assert len(tablet["segTops"]) == 3 and len(set(tablet["segTops"])) == 1, tablet           # the three options on one row
    assert tablet["topbarH"] <= 80 and tablet["scrollW"] <= tablet["clientW"], tablet          # not 139 px; no sideways scroll
    assert tablet["detailW"] >= tablet["collW"] - 48 and tablet["navGap"] in (0, 1) and tablet["scrolled"] > 100, tablet
    assert tablet["weights"][0] == tablet["weights"][1], tablet
    wide = _drive(hub, tmp_path, REWORK, width=1280)
    assert wide["detailW"] >= wide["collW"] - 48 and wide["navGap"] in (0, 1) and wide["scrolled"] > 100, wide


# the web app's body carries data-ai: pills under the top bar from tablet up (no side column at any width), the bottom bar on a phone
APP = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const r = document.documentElement;
await until(() => document.querySelector(".shell > .nav .nav__item"), "the navigation");
const all = (list) => [...list].flatMap((x) => (x.selectorText ? [x] : x.cssRules ? all(x.cssRules) : []));
const sans = (look) => { const sel = look === "palette" ? ':root[data-look="palette"]' : ":root";
  return all([...document.styleSheets].flatMap((s) => [...s.cssRules])).filter((x) => x.selectorText === sel).map((x) => x.style.getPropertyValue("--sans")).filter(Boolean).join("|"); };
const m = (look) => { r.setAttribute("data-look", look); const cs = (el) => getComputedStyle(el), item = document.querySelector(".shell .nav__item"), nav = document.querySelector(".shell > .nav");
  return { cols: cs(document.querySelector(".shell")).gridTemplateColumns, dir: cs(item).flexDirection, navPos: cs(nav).position, font: sans(look),
    navW: Math.round(nav.getBoundingClientRect().width), radius: cs(item).borderTopLeftRadius }; };
return { console: m("console"), palette: m("palette"), workbench: m("workbench"), back: m("console"), ai: document.body.hasAttribute("data-ai") };
"""


def test_the_web_app_shows_palette_pills_and_font_and_console_is_the_same_after(served, tmp_path):  # noqa: F811
    for width in (1280, 768):
        app = _drive(served, tmp_path, APP, width=width)
        assert app["ai"] is True and app["back"] == app["console"] and app["console"]["dir"] == "column"
        assert app["palette"]["dir"] == "row" and app["palette"]["navPos"] == "sticky" and app["palette"]["cols"].count(" ") == 0
        assert app["palette"]["navW"] >= width - 32 and app["palette"]["radius"] == "20px" and "ui-rounded" in app["palette"]["font"]
        assert app["workbench"]["font"] != app["palette"]["font"] and app["workbench"]["cols"].count(" ") == 1
    phone = _drive(served, tmp_path, APP, width=320)
    assert phone["palette"]["navPos"] == "fixed" == phone["console"]["navPos"] and phone["back"] == phone["console"]


# an open detail region is drawn in the detail host, as a sheet (the shared script's openDetail; no Hub screen opens one yet, the
# printers page draws its own drawers): on a phone from the top bar's height to the bottom edge, at the right edge on a wide screen;
# under Console it stays in its row
SHEET = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const d = document, r = d.documentElement;
const open = async (look) => {
  r.setAttribute("data-look", look);
  const row = d.createElement("div"), region = d.createElement("section");
  row.className = "coll__row coll__row--detail";
  region.className = "detail"; region.id = "probe-" + look; region.setAttribute("aria-labelledby", "probe-title-" + look); region.hidden = true;
  region.innerHTML = '<header class="detail__head"><h2 class="detail__title" id="probe-title-' + look + '" tabindex="-1">Workshop X1</h2></header><div class="detail__body">Body</div>';
  row.append(region); d.querySelector("main").append(row);
  SW.openDetail(region, {});
  await sleep(600);
  const host = d.getElementById("detail-host"), box = host ? host.getBoundingClientRect() : { top: -1, bottom: -1, left: -1, width: -1 };
  const out = { hostOpen: !!host && host.open, inHost: !!host && host.contains(region), inRow: row.contains(region), top: Math.round(box.top), bottom: Math.round(box.bottom), left: Math.round(box.left),
    width: Math.round(box.width), vh: innerHeight, vw: d.documentElement.clientWidth, radius: host ? getComputedStyle(host).borderTopLeftRadius : null, topbar: Math.round(d.querySelector(".topbar").getBoundingClientRect().bottom) };
  if (host && host.open) host.close();
  await sleep(300);
  row.remove();
  return out;
};
const palette = await open("palette");
const console_ = await open("console");
return { palette, console: console_ };
"""


def test_an_open_detail_is_a_sheet_in_palette_and_stays_in_its_row_in_console(hub, tmp_path):
    wide = _drive(hub, tmp_path, SHEET, width=1280)["palette"]
    assert wide["hostOpen"] and wide["inHost"] and not wide["inRow"] and wide["width"] == 420 and wide["left"] == wide["vw"] - 420 and wide["top"] == 0 and wide["bottom"] == wide["vh"], wide
    both = _drive(hub, tmp_path, SHEET, width=320)
    phone = both["palette"]
    assert phone["hostOpen"] and phone["inHost"] and phone["width"] == phone["vw"] and phone["bottom"] == phone["vh"], phone
    assert phone["top"] == 68 and phone["radius"] == "20px", phone               # from --top (68 px) down, rounded top corners
    assert not both["console"]["hostOpen"] and both["console"]["inRow"] and not both["console"]["inHost"], both["console"]


# the picker: Palette is chosen, applies at once, is kept on this device, shows the Palette surface in the status bar, and is
# still the chosen tile after leaving Settings and coming back
CHOOSE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
const root = document.documentElement;
const tiles = () => [...document.querySelectorAll(".theme-picker__tile")].map((t) => ({ name: text($(".theme-picker__name", t)), line: text($(".theme-picker__line", t)), on: $("input", t).checked, look: $("input", t).value,
  preview: $(".theme-picker__preview", t).getAttribute("data-look") }));
localStorage.removeItem("spoolwarden.look"); localStorage.removeItem("spoolwarden.appearance");
location.hash = "__HASH__";
await until(() => $(".theme-picker"), "the picker");
const out = { start: tiles() };
const radio = [...document.querySelectorAll(".theme-picker__input")].find((i) => i.value === "palette");
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
    names = [T("theme_console_name"), T("theme_workbench_name"), T("theme_palette_name"), T("theme_panes_name")]
    assert [(t["name"], t["on"], t["look"], t["preview"]) for t in page["start"]] == [(names[0], True, "console", "console"), (names[1], False, "workbench", "workbench"),
                                                                                       (names[2], False, "palette", "palette"), (names[3], False, "panes", "panes")]
    assert page["start"][2]["line"] == T("theme_palette_line")
    chose = page["chose"]
    assert chose["stored"] == "palette" and chose["look"] == "palette"
    assert [t["on"] for t in chose["tiles"]] == [False, False, True, False]
    assert chose["result"] == T("appearance_theme_saved", name=names[2])
    assert chose["metas"] == [chose["surface"]] * 2 and chose["surface"] in _surfaces("palette")
    assert [t["on"] for t in page["again"]] == [False, False, True, False]               # the choice survives the redraw
    assert page["console"]["stored"] == "console" and page["console"]["look"] == "console"
    assert [t["on"] for t in page["console"]["tiles"]] == [True, False, False, False]


def test_the_hub_settings_picker_offers_palette_and_keeps_the_choice(hub, tmp_path):
    _check_choose(_drive(hub, tmp_path, CHOOSE.replace("__HASH__", "#settings/appearance").replace("__AWAY__", "#overview")))


def test_the_web_app_settings_picker_offers_palette_and_keeps_the_choice(served, tmp_path):  # noqa: F811
    _check_choose(_drive(served, tmp_path, CHOOSE.replace("__HASH__", "#settings").replace("__AWAY__", "#add")))


# AUT-5 in Palette: the look is set the way the picker sets it, then every view is audited, light and dark
READY = """(async () => {
  document.documentElement.setAttribute("data-look", "palette");
  const all = (list) => [...list].flatMap((r) => (r.selectorText ? [r] : r.cssRules ? all(r.cssRules) : []));          // a rule inside a media query too
  const rules = [...document.styleSheets].flatMap((s) => all(s.cssRules)).filter((r) => r.selectorText && r.selectorText.startsWith(':root[data-look="palette"]'));
  for (const part of [".nav__item", ".coll__item", ".sheet--detail"]) if (!rules.some((r) => r.selectorText.includes(part))) throw new Error("no Palette rule for " + part);
})()"""


def _audit(url, views, allow, per_scheme):
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else []
    run = _run("--url", url, "--views", views, "--allow", str(allow), "--widths", "1280,768,320", "--schemes", "light,dark", "--ready", READY, *fonts)
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == per_scheme * 3 * 2 and out["failing"] == 0         # three widths, light and dark


def test_the_hub_page_passes_the_audit_in_palette_light_and_dark_at_three_widths(hub):
    _audit(hub, HUB_VIEWS, HUB_ALLOW, len(HUB_VIEWS.split(",")))


def test_the_web_app_passes_the_audit_in_palette_light_and_dark_at_three_widths(served, tmp_path):  # noqa: F811
    _audit(served, WEB_VIEWS, _workbench_allow(tmp_path), len(WEB_VIEWS.split(",")))
