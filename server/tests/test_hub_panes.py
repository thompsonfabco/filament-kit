"""Panes on the web (design 09 S6.8, 02 1.3 and 2.3, 08 9 and test 4 of 08), in a real headless browser where it matters: the three
profile groups `nav=list`, `collection=rows` and `detail=pane` of components.css are keyed on Panes only (no other look's group
mentions it, Panes' hold no unqualified rule or another look's); the Hub page and the web app show Panes (the section list as the
left pane from tablet up, rows with a chevron, an open detail as the third column on a desktop and covering its list below that)
and Console, Workbench and Palette are the same after a visit to Panes; on a phone the list of sections is the first page, a
section drills in and Back returns with focus on the row it was left from, and a printer drilled into closes with focus back on
its row; an address (#printers/<id>) opens the same thing as in Console; the picker offers the Panes tile in both interfaces; a
stored Panes look is applied by theme-init.js; and AUT-5 passes on both in Panes, light and dark, at 320, 768 and 1280 px. The
same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os
import re

from test_hub_page_audit import ALLOW as HUB_ALLOW, VIEWS as HUB_VIEWS, _run, hub_app, hub_change  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_hub_theme_picker import DARK, LIGHT, PRELUDE, _set_default, _surfaces
from test_hub_workbench import CSS, SERVED_CSS, _groups, _workbench_allow
from test_web_app_audit import VIEWS as WEB_VIEWS, served  # noqa: F401

PANES = ':root[data-look="panes"]'


def test_the_three_panes_groups_are_keyed_on_panes_and_the_other_groups_are_not():
    for css in (CSS, SERVED_CSS):                                # the served copy is the one the Hub sends
        groups = _groups(css)
        for group in (("nav", "list"), ("collection", "rows"), ("detail", "pane")):
            assert groups.get(group), f"no profile group {group}"
            leaks = [s for s in groups[group] if not s.startswith(PANES + " ")]
            assert not leaks, (group, "a rule not keyed on Panes", leaks[:3])
        for group in (("nav", "rail"), ("collection", "table"), ("detail", "inline"), ("nav", "sidebar"), ("collection", "cards"), ("detail", "card"),
                      ("nav", "pills"), ("collection", "tiles"), ("detail", "sheet")):
            assert groups[group], group
            assert not [s for s in groups[group] if "panes" in s], (group, "Panes in another look's group")


def test_the_looks_keyed_are_workbench_palette_and_panes_each_in_its_own_groups():
    groups = _groups(CSS)
    seen = {m for sels in groups.values() for s in sels for m in re.findall(r'data-look="([a-z]+)"', s)}
    assert seen == {"workbench", "palette", "panes"}
    assert [g for g, sels in groups.items() if any("panes" in s for s in sels)] == [("nav", "list"), ("collection", "rows"), ("detail", "pane")]


def test_the_core_stylesheet_stays_under_60_kb_with_panes():
    assert len(CSS.encode("utf-8")) < 60_000 and CSS == SERVED_CSS


def test_the_shared_script_has_the_panes_tile_and_only_the_navigation_part_grew():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "web-shared" / "components.js").read_text(encoding="utf-8")
    assert 'const THEMES = ["console", "workbench", "palette", "panes"];' in js
    assert (Path(__file__).resolve().parents[2] / "server" / "filament_kit" / "shared_static" / "components.js").read_text(encoding="utf-8") == js


# the metrics of the Hub page under each look at one width (the driver opens the page at that width, so its media queries answer);
# Console, Workbench and Palette are measured before and after Panes
STYLES = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement;
function metrics(look) {
  if (look) r.setAttribute("data-look", look); else r.removeAttribute("data-look");
  const $ = (s) => d.querySelector(s), cs = (el, p) => getComputedStyle(el, p), box = (el) => el.getBoundingClientRect();
  const shell = $(".shell"), nav = $(".shell > .nav"), item = $(".shell .nav__item"), group = $(".shell .nav__group"), heading = $(".shell .nav__heading");
  const coll = $(".coll--printers"), row = $(".coll--printers .coll__item > .coll__row"), p3 = $('.coll--printers .coll__cell[data-prio="3"]'), expand = $(".coll--printers .coll__expand");
  const current = $('.shell .nav__item[aria-current="page"]');
  return { cols: cs(shell).gridTemplateColumns, navPos: cs(nav).position, navDisplay: cs(nav).display, navW: Math.round(box(nav).width), itemDisplay: cs(item).display,
    itemH: Math.round(box(item).height), itemDir: cs(item).flexDirection, headingW: Math.round(box(heading).width), groupRadius: cs(group).borderTopLeftRadius,
    groupBorder: cs(group).borderTopWidth, currentBg: current ? cs(current).backgroundColor : null, collDisplay: cs(coll).display, collBorder: cs(coll).borderTopWidth,
    collRadius: cs(coll).borderTopLeftRadius, rowDisplay: cs(row).display, rowPad: cs(row).paddingTop, p3: cs(p3).display, expandShown: box(expand).width > 0,
    key: cs($(".coll--printers .coll__key"), "::after").content, drill: shell.getAttribute("data-drill"), vw: r.clientWidth };
}
location.hash = "#printers";
await until(() => d.querySelector(".coll--printers .coll__item"), "the printers list");
await sleep(300);
const first = { console: metrics(null), workbench: metrics("workbench"), palette: metrics("palette") };
const panes = metrics("panes");
return { first, panes, after: { console: metrics("console"), workbench: metrics("workbench"), palette: metrics("palette") }, unknown: metrics("nonesuch"), none: metrics(null) };
"""


def _check_styles(wide, tablet, phone):
    for w, got in ((1280, wide), (768, tablet), (320, phone)):
        assert got["after"] == got["first"], (w, "Console, Workbench or Palette is not the same after Panes")
        assert got["unknown"] == got["first"]["console"] and got["none"] == got["first"]["console"], (w, "an unknown or missing look is Console's arrangement")
        pan, con = got["panes"], got["first"]["console"]
        assert pan["collDisplay"] == "block" and pan["collBorder"] == "1px" and pan["collRadius"] == "10px" and pan["rowDisplay"] == "flex", (w, pan)
        assert pan["p3"] == "none" and pan["expandShown"], (w, pan)                   # a row keeps the first-priority fields and the chevron
        if w > 600:
            assert con["collDisplay"] == "grid" and con["rowDisplay"] == "grid", (w, con)
    for w, got in ((1280, wide["panes"]), (768, tablet["panes"])):
        assert got["itemDisplay"] == "grid" and got["headingW"] > 50 and got["groupRadius"] == "10px" and got["groupBorder"] == "1px", (w, got)
        assert got["navPos"] == "sticky" and got["cols"].count(" ") == 1, (w, got)
        assert abs(float(got["cols"].split(" ")[0][:-2]) - min(360, 0.4 * got["vw"])) < 1.5, (w, got["cols"], got["vw"])     # the section pane: --list-w, at most 40 %
        assert got["currentBg"] not in (None, "rgba(0, 0, 0, 0)") and got["itemH"] >= 52, (w, got)
    assert wide["first"]["console"]["itemDisplay"] == "flex" and wide["first"]["console"]["itemDir"] == "column"        # Console's rail
    assert phone["panes"]["navDisplay"] == "none" and phone["panes"]["drill"] == "page"      # a section is open: the list is not drawn behind it
    assert phone["first"]["console"]["navPos"] == "fixed"                                       # the bottom bar of Console, unchanged


def test_panes_shows_in_the_hub_page_at_three_widths_and_the_other_looks_are_unchanged(hub, tmp_path):
    _check_styles(*(_drive(hub, tmp_path, STYLES, width=w) for w in (1280, 768, 320)))


# an open detail: the third column on a desktop (fixed below the top bar, own scroll, 22rem), covering its list below that; the top bar
# of a tablet keeps the light/dark switch on one row; the section list and the top bar stay in view while the page scrolls; and an
# address opens the same printer
DETAIL = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s) => d.querySelector(s), box = (el) => el.getBoundingClientRect(), vis = (el) => !!el && el.getClientRects().length > 0;
r.setAttribute("data-look", "panes");
location.hash = "#printers";
await until(() => $(".coll--printers .coll__expand"), "the printers list");
await sleep(300);
d.body.style.minHeight = "3000px";                                    // a page long enough to scroll
const tops = [...d.querySelectorAll(".topbar .appearance .segmented__option")].filter((o) => o.offsetParent).map((o) => Math.round(box(o).top));
const out = { topbarH: Math.round(box($(".topbar")).height), segTops: tops, scrollW: r.scrollWidth, clientW: r.clientWidth, rows: d.querySelectorAll(".coll--printers > .coll__item").length };
const x = $(".coll--printers .coll__expand");
x.click();
await until(() => $(".coll--printers .coll__row--detail:not([hidden]) .detail"), "the detail");
await sleep(500);
const region = $(".coll--printers .coll__row--detail:not([hidden]) .detail"), pane = region.closest(".coll__row--detail"), coll = $(".coll--printers");
out.pane = { left: Math.round(box(pane).left), width: Math.round(box(pane).width), top: Math.round(box(pane).top), bottom: Math.round(box(pane).bottom), vw: r.clientWidth, vh: innerHeight,
  position: getComputedStyle(pane).position, overflowY: getComputedStyle(pane).overflowY, topbar: Math.round(box($(".topbar")).bottom), cols: getComputedStyle(region.querySelector(".detail__body")).gridTemplateColumns.split(" ").length };
out.regionW = Math.round(box(region).width); out.collW = Math.round(box(coll).width);
out.visibleRows = [...d.querySelectorAll(".coll--printers .coll__item")].filter(vis).length;
out.mainMargin = getComputedStyle($(".shell__main")).marginRight;
out.rowCurrent = getComputedStyle($(".coll--printers .coll__item:has(.coll__row--detail:not([hidden])) > .coll__row")).backgroundColor;
scrollTo(0, 400); await sleep(400);
out.navGap = Math.round(box($(".shell > .nav")).top - box($(".topbar")).bottom); out.scrolled = Math.round(scrollY);
out.paneAfter = { top: Math.round(box(pane).top), bottom: Math.round(box(pane).bottom) };
x.click(); await sleep(300);
out.closed = { expanded: x.getAttribute("aria-expanded"), shown: vis($(".coll--printers .coll__row--detail:not([hidden])")), rows: [...d.querySelectorAll(".coll--printers .coll__item")].filter(vis).length };
// the address a person types (the Hub does not write a printer's serial into the address while it is locked): Workshop X1, in Panes and in Console
const deep = async (look) => {
  r.setAttribute("data-look", look);
  location.hash = "#overview"; await sleep(600);
  location.hash = "#printers/00M00A000000001";
  await until(() => $(".coll--printers .coll__expand[aria-expanded=true]"), "the printer the address names");
  const t = $(".coll--printers .coll__item:has(.coll__row--detail:not([hidden])) .coll__title").textContent.trim();
  $(".coll--printers .coll__expand[aria-expanded=true]").click(); await sleep(300);
  return t;
};
out.deep = { panes: await deep("panes"), console: await deep("console") };
return out;
"""


def test_an_open_detail_is_the_third_column_on_a_desktop_and_covers_its_list_on_a_tablet(hub, tmp_path):
    wide = _drive(hub, tmp_path, DETAIL, width=1280)
    pane = wide["pane"]
    assert pane["position"] == "fixed" and pane["width"] == 352 and pane["left"] == pane["vw"] - 352 and abs(pane["top"] - pane["topbar"]) <= 1, wide   # 22rem, below the top bar
    assert pane["bottom"] == pane["vh"] and pane["overflowY"] in ("auto", "scroll") and pane["cols"] == 1, wide
    assert wide["mainMargin"] == "352px" and wide["visibleRows"] == wide["rows"], wide          # the list stays beside it
    assert abs(wide["navGap"]) <= 1 and wide["scrolled"] > 100 and wide["paneAfter"] == {"top": pane["top"], "bottom": pane["bottom"]}, wide   # sticky bars
    assert wide["rowCurrent"] not in ("rgba(0, 0, 0, 0)", "transparent") and wide["closed"]["expanded"] == "false" and not wide["closed"]["shown"], wide
    assert wide["deep"] == {"panes": "Workshop X1", "console": "Workshop X1"}, wide             # the address opens the same printer
    for width in (768, 320):
        got = _drive(hub, tmp_path, DETAIL, width=width)
        assert got["pane"]["position"] != "fixed" and got["visibleRows"] == 1 < got["rows"], (width, got)     # the open row alone: it covers the list
        assert got["regionW"] >= got["collW"] - 48 and got["scrollW"] <= got["clientW"], (width, got)       # full width of the list; no sideways scroll
        assert got["closed"]["rows"] == got["rows"] and got["deep"]["panes"] == "Workshop X1", (width, got)
    tablet = _drive(hub, tmp_path, DETAIL, width=768)
    assert len(tablet["segTops"]) == 3 and len(set(tablet["segTops"])) == 1 and tablet["topbarH"] <= 80, tablet   # the three options on one row


# a phone: the list of sections is the first page; a section drills in; Back (the top bar's, then the phone's) returns with focus on the row
DRILL = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, r = d.documentElement, $ = (s) => d.querySelector(s), vis = (el) => !!el && el.getClientRects().length > 0;
const at = () => { const a = d.activeElement; return a ? { tag: a.tagName, href: a.getAttribute("href"), expand: a.classList.contains("coll__expand") } : null; };
const snap = () => ({ look: r.getAttribute("data-look"), drill: $(".shell").getAttribute("data-drill"), nav: vis($(".shell > .nav")), main: vis($(".shell__main")), back: vis($(".topbar__back")),
  more: vis($(".shell .nav__more")), items: [...d.querySelectorAll(".shell .nav__item")].filter(vis).length, hash: location.hash, len: history.length, active: at(), scrollW: r.scrollWidth, clientW: r.clientWidth });
const item = (s) => $(`.shell .nav__item[href="#${s}"]`);
await until(() => $(".shell .nav__item") && $(".shell").getAttribute("data-drill"), "the navigation");
await sleep(500);
const out = { start: snap() };
__STEPS__
return out;
"""

HUB_STEPS = """
item("printers").click();
await until(() => $(".shell").getAttribute("data-drill") === "page" && $(".coll--printers .coll__item"), "the printers section");
await sleep(300);
out.printers = { ...snap(), h1: d.activeElement === $("main h1") };
$(".coll--printers .coll__title").click();
await until(() => $(".coll--printers .coll__expand[aria-expanded=true]"), "the printer to open");
await sleep(400);
const expand = $(".coll--printers .coll__expand[aria-expanded=true]"), title = $(".coll--printers .coll__item:has(.coll__row--detail:not([hidden])) .coll__title").textContent.trim();
out.open = { ...snap(), shown: [...d.querySelectorAll(".coll--printers .coll__item")].filter(vis).length, detail: vis($(".coll--printers .coll__row--detail:not([hidden]) .detail")) };
$(".topbar__back").click();
await sleep(500);
out.closed = { ...snap(), expanded: expand.getAttribute("aria-expanded"), onRow: d.activeElement === expand, shown: [...d.querySelectorAll(".coll--printers .coll__item")].filter(vis).length };
$(".topbar__back").click();
await until(() => $(".shell").getAttribute("data-drill") === "list", "the list");
await sleep(300);
out.list = snap();
location.hash = "#printers/00M00A000000001";                         // the address a person types (it is not written while the Hub is locked)
await until(() => $(".shell").getAttribute("data-drill") === "page" && $(".coll--printers .coll__expand[aria-expanded=true]"), "the printer the address names");
await sleep(300);
out.deep = { ...snap(), title: $(".coll--printers .coll__item:has(.coll__row--detail:not([hidden])) .coll__title").textContent.trim(), first: title };
"""

WEB_STEPS = """
const hereHash = location.hash;
item("add").click();                                                  // the section that is open behind the list: no address change, the page still drills in
await until(() => $(".shell").getAttribute("data-drill") === "page", "the page to drill in");
await sleep(300);
out.same = { ...snap(), hereHash };
$(".topbar__back").click();
await until(() => $(".shell").getAttribute("data-drill") === "list", "the list");
await sleep(300);
out.list = snap();
item("spools").click();
await until(() => $(".shell").getAttribute("data-drill") === "page" && location.hash.startsWith("#spools"), "the Spools page");
await sleep(300);
out.spools = { ...snap(), h1: d.activeElement === $("main h1") };
history.back();
await until(() => $(".shell").getAttribute("data-drill") === "list", "the list (the phone's Back)");
await sleep(300);
out.backToList = snap();
"""


def _check_list(s, row=None):
    assert s["look"] == "panes" and s["drill"] == "list" and s["nav"] and not s["main"] and not s["back"], s
    assert s["items"] >= 5 and s["scrollW"] <= s["clientW"], s
    if row:
        assert s["active"]["href"] == row, s                               # focus is on the row the person left


def _check_page(s, h1=None):
    assert s["drill"] == "page" and not s["nav"] and s["main"] and s["back"], s
    if h1 is not None:
        assert h1 is True, s


def test_on_a_phone_the_hub_page_opens_on_the_list_and_a_printer_drills_in_and_back_with_focus_on_the_row(hub, tmp_path):
    _set_default("panes")                                                 # a page served with Panes, as a stored look gives it
    got = _drive(hub, tmp_path, DRILL.replace("__STEPS__", HUB_STEPS), width=320)
    _check_list(got["start"])
    assert got["start"]["hash"] in ("", "#")
    _check_page(got["printers"], got["printers"]["h1"])                    # focus moves to the page's title
    assert got["printers"]["hash"] == "#printers" and got["printers"]["scrollW"] <= got["printers"]["clientW"]
    _check_page(got["open"])
    assert got["open"]["detail"] and got["open"]["shown"] == 1 and got["open"]["hash"] == "#printers"       # the printer covers its list
    _check_page(got["closed"])
    assert got["closed"]["expanded"] == "false" and got["closed"]["onRow"] is True and got["closed"]["active"]["expand"] is True      # focus is back on the row
    assert got["closed"]["shown"] > 1 and got["closed"]["hash"] == "#printers"
    _check_list(got["list"], "#printers")                                  # Back again: the list, focus on the Printers row
    assert got["list"]["len"] == got["closed"]["len"] and got["list"]["hash"] in ("", "#")     # the in-page Back went back through history: no entry left that reopens the page
    _check_page(got["deep"])
    assert got["deep"]["title"] == "Workshop X1" and got["deep"]["hash"] == "#printers/00M00A000000001"       # the address opens the printer it names


def test_on_a_phone_the_web_app_opens_on_the_list_and_a_section_drills_in_and_back(served, tmp_path):  # noqa: F811
    _set_default("panes")
    got = _drive(served, tmp_path, DRILL.replace("__STEPS__", WEB_STEPS), width=320)
    _check_list(got["start"])
    assert got["start"]["more"] is True                                    # More (Add to Home Screen, the Hub page) stays reachable
    _check_page(got["same"])
    _check_list(got["list"], "#" + got["same"]["hereHash"].lstrip("#").split("/")[0])
    _check_page(got["spools"], got["spools"]["h1"])
    _check_list(got["backToList"], "#spools")


# a wide screen has no list-as-root: the section pane is beside the page at once, with the current section marked
WIDE = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const d = document, $ = (s) => d.querySelector(s), vis = (el) => !!el && el.getClientRects().length > 0;
await until(() => $(".shell .nav__item") && $(".shell").getAttribute("data-drill"), "the navigation");
await sleep(400);
const cur = $('.shell .nav__item[aria-current="page"]');
return { look: d.documentElement.getAttribute("data-look"), drill: $(".shell").getAttribute("data-drill"), nav: vis($(".shell > .nav")), main: vis($(".shell__main")), back: vis($(".topbar__back")),
  current: !!cur, tile: cur ? getComputedStyle($(".nav__icon", cur)).backgroundColor : null, label: cur ? getComputedStyle($(".nav__label", cur)).fontSize : null,
  more: vis($(".shell .nav__more")), scrollW: d.documentElement.scrollWidth, clientW: d.documentElement.clientWidth };
"""


def _check_wide(url, tmp_path):
    for width in (1280, 768):
        got = _drive(url, tmp_path, WIDE, width=width)
        assert got["look"] == "panes" and got["drill"] == "page" and got["nav"] and got["main"] and not got["back"] and got["current"], (width, got)
        assert got["tile"] not in (None, "rgba(0, 0, 0, 0)") and got["more"] is False and got["scrollW"] <= got["clientW"], (width, got)


def test_a_wide_screen_shows_the_section_pane_beside_the_page_on_the_hub_page(hub, tmp_path):
    _set_default("panes")
    _check_wide(hub, tmp_path)


def test_a_wide_screen_shows_the_section_pane_beside_the_page_in_the_web_app(served, tmp_path):  # noqa: F811
    _set_default("panes")
    _check_wide(served, tmp_path)


# the web app's body carries data-ai: the same pane, rows with a chevron on the pages that list things
APP = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what); }
const r = document.documentElement;
await until(() => document.querySelector(".shell > .nav .nav__item"), "the navigation");
const m = (look) => { r.setAttribute("data-look", look); const cs = (el) => getComputedStyle(el), item = document.querySelector(".shell .nav__item"), nav = document.querySelector(".shell > .nav");
  return { cols: cs(document.querySelector(".shell")).gridTemplateColumns, display: cs(item).display, navPos: cs(nav).position, chevron: cs(item, "::after").content,
    navW: Math.round(nav.getBoundingClientRect().width), radius: cs(document.querySelector(".shell .nav__group")).borderTopLeftRadius }; };
return { console: m("console"), panes: m("panes"), workbench: m("workbench"), palette: m("palette"), back: m("console"), ai: document.body.hasAttribute("data-ai") };
"""


def test_the_web_app_shows_the_panes_list_and_the_other_looks_are_the_same_after(served, tmp_path):  # noqa: F811
    for width in (1280, 768):
        app = _drive(served, tmp_path, APP, width=width)
        assert app["ai"] is True and app["back"] == app["console"] and app["console"]["display"] == "flex"
        assert app["panes"]["display"] == "grid" and app["panes"]["navPos"] == "sticky" and app["panes"]["radius"] == "10px", app
        assert app["panes"]["chevron"] != "none" and app["panes"]["cols"].count(" ") == 1, app            # the web app's items draw their own chevron
        assert app["workbench"]["display"] == "flex" and app["palette"]["display"] == "flex"
    phone = _drive(served, tmp_path, APP, width=320)
    assert phone["back"] == phone["console"] and phone["panes"]["navPos"] == "static"


# the picker: Panes is chosen, applies at once, is kept on this device, shows the Panes surface in the status bar, and is still the
# chosen tile after leaving Settings and coming back
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
const radio = [...document.querySelectorAll(".theme-picker__input")].find((i) => i.value === "panes");
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
    assert page["start"][3]["line"] == T("theme_panes_line")
    chose = page["chose"]
    assert chose["stored"] == "panes" and chose["look"] == "panes"
    assert [t["on"] for t in chose["tiles"]] == [False, False, False, True]
    assert chose["result"] == T("appearance_theme_saved", name=names[3])
    assert chose["metas"] == [chose["surface"]] * 2 and chose["surface"] in _surfaces("panes")
    assert [t["on"] for t in page["again"]] == [False, False, False, True]          # the choice survives the redraw
    assert page["console"]["stored"] == "console" and page["console"]["look"] == "console"
    assert [t["on"] for t in page["console"]["tiles"]] == [True, False, False, False]


def test_the_hub_settings_picker_offers_panes_and_keeps_the_choice(hub, tmp_path):
    _check_choose(_drive(hub, tmp_path, CHOOSE.replace("__HASH__", "#settings/appearance").replace("__AWAY__", "#overview")))


def test_the_web_app_settings_picker_offers_panes_and_keeps_the_choice(served, tmp_path):  # noqa: F811
    _check_choose(_drive(served, tmp_path, CHOOSE.replace("__HASH__", "#settings").replace("__AWAY__", "#add")))


# a device that chose Panes: a page load applies it (theme-init.js run as a page load runs it) and sets the two metas to its surface
RELOAD = PRELUDE + """
localStorage.setItem("spoolwarden.look", "panes");
const out = await load("console");
localStorage.removeItem("spoolwarden.look");
return out;
"""


def test_a_stored_panes_look_is_applied_by_a_page_load_on_the_hub_page(hub, tmp_path):
    light, dark = _surfaces("panes")
    assert _drive(hub, tmp_path, RELOAD) == {"look": "panes", "theme": None, "metas": [[LIGHT, light], [DARK, dark]]}


def test_a_stored_panes_look_is_applied_by_a_page_load_in_the_web_app(served, tmp_path):  # noqa: F811
    light, dark = _surfaces("panes")
    assert _drive(served, tmp_path, RELOAD) == {"look": "panes", "theme": None, "metas": [[LIGHT, light], [DARK, dark]]}


# AUT-5 in Panes: the look is set the way the picker sets it, then every view is audited, light and dark
READY = """(async () => {
  document.documentElement.setAttribute("data-look", "panes");
  const all = (list) => [...list].flatMap((r) => (r.selectorText ? [r] : r.cssRules ? all(r.cssRules) : []));          // a rule inside a media query too
  const rules = [...document.styleSheets].flatMap((s) => all(s.cssRules)).filter((r) => r.selectorText && r.selectorText.startsWith(':root[data-look="panes"]'));
  for (const part of [".nav__item", ".coll__item", ".coll__row--detail"]) if (!rules.some((r) => r.selectorText.includes(part))) throw new Error("no Panes rule for " + part);
})()"""


def _audit(url, views, allow, per_scheme):
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else []
    run = _run("--url", url, "--views", views, "--allow", str(allow), "--widths", "1280,768,320", "--schemes", "light,dark", "--ready", READY, *fonts)
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == per_scheme * 3 * 2 and out["failing"] == 0         # three widths, light and dark


def test_the_hub_page_passes_the_audit_in_panes_light_and_dark_at_three_widths(hub):
    _audit(hub, HUB_VIEWS, HUB_ALLOW, len(HUB_VIEWS.split(",")))


def test_the_web_app_passes_the_audit_in_panes_light_and_dark_at_three_widths(served, tmp_path):  # noqa: F811
    _audit(served, WEB_VIEWS, _workbench_allow(tmp_path), len(WEB_VIEWS.split(",")))
