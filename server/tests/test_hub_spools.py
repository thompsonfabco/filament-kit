"""The Spools section of the Hub page (R83 sections 1 and 10.2; 03 section 5a), in a real headless browser. The section is new files
only: its routes (setup_console/spools_tab.py) are mounted on the page's own guard here and its script, style and the registry's
three lines (a TABS entry after Printers, GROUPS 6 and 5) are added to the served page by a wrapper, as the registry step will add
them for good. The routes answer from the fake Spoolman of the page audit's data plus a stock of 62 spools: 3 sealed, 2 running low,
2 in a printer, one with a tag, the rest opened, and one empty (not listed). Covered: the list (header count, the Open Spoolman
link, the 50 rows, Show more, search, each chip, the empty states), the detail and each change (the preview first, then Apply,
the code asked while the page is locked, Spoolman holding the result), and the section in the four looks at 1280 and 390 px. The
same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from filament_kit import inventory, setup_console
from filament_kit.setup_console import spools_tab
from test_hub_page_audit import hub_app, _serve  # noqa: F401
from test_hub_presets_ui import AsHttps, _drive, T  # noqa: F401

STATIC = Path(spools_tab.__file__).parents[1] / "setup_static"
SHIM = """// what the registry step adds (R83 section 12, EV5): the Spools entry after Printers, and the group sizes of the navigation
(() => {
  const entries = Object.entries(TABS);
  for (const [k] of entries) delete TABS[k];
  for (const [k, v] of entries) { TABS[k] = v; if (k === "printers") TABS.spools = ["nav_spools", "spool", () => spoolsTab()]; }
  GROUPS[0][3] = 6; GROUPS[1][2] = 6; GROUPS[1][3] = 11;
})();
"""
SERVED = {"/setup/setup_spools.js": ("text/javascript", (STATIC / "setup_spools.js").read_bytes()),
          "/setup/setup_spools.css": ("text/css", (STATIC / "setup_spools.css").read_bytes()),
          "/setup/spools_shim.js": ("text/javascript", SHIM.encode())}


class Mounted(AsHttps):
    """The page with the Spools section added: its files are served, and the page's HTML names them."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in SERVED:
            kind, body = SERVED[scope["path"]]
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", kind.encode()), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        page = scope["type"] == "http" and scope["path"] == "/setup"

        async def out(message):
            if page and message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message["headers"] if k.lower() != b"content-length"]
            elif page and message["type"] == "http.response.body":
                message["body"] = (message["body"].replace(b"<body>", b"<link rel=stylesheet href='/setup/setup_spools.css'><body>")
                                   .replace(b"</body>", b"<script src='/setup/setup_spools.js'></script><script src='/setup/spools_shim.js'></script></body>"))
            await send(message)
        await super().__call__(scope, receive, out)


@pytest.fixture(autouse=True)
def mounted(monkeypatch):
    """The section's routes join the page's own (before the app is built)."""
    real = setup_console.routes
    monkeypatch.setattr(setup_console, "routes", lambda page: real(page) + spools_tab.routes(page))


@pytest.fixture
def hub(hub_app):  # noqa: F811
    running = _serve(Mounted(hub_app[0]), hub_app[1])
    try:
        yield running.url + "/setup"
    finally:
        running.stop()


SEALED = [2, 3, 4]                       # the ids the stock makes (the audit data's own spool is number 1)
LOW = [5, 6]
LOADED = [7, 8]
TAGGED = 9
EMPTY = 10
TOTAL = 62                                # every spool that is not empty
PLAIN = TOTAL - 1 - len(SEALED) - len(LOW) - len(LOADED) - 1      # opened, in Rack 1, no tag (numbers 11 on)
OPENED = TOTAL - len(SEALED)


@pytest.fixture
def stock(spoolman_url, hub_app):  # noqa: F811
    """62 listed spools and one empty, made through Spoolman's own API (numbers 2 to 63)."""
    with httpx.Client() as c:
        fil = c.get(spoolman_url + "/api/v1/filament").json()[0]["id"]
        make = lambda **kw: c.post(spoolman_url + "/api/v1/spool", json={"filament_id": fil, **kw}).raise_for_status().json()["id"]  # noqa: E731
        for _ in SEALED:
            make(location="Sealed stock", remaining_weight=1000, comment=inventory.SEALED_COMMENT)
        for _ in LOW:
            make(location="Rack 2", remaining_weight=40)
        for slot in ("A1", "A2"):
            make(location=f"Workshop X1 – AMS {slot}", remaining_weight=500)
        make(location="Rack 2", remaining_weight=500, extra={"nfc_id": json.dumps("4:a1:b2:c3")})
        make(location="Rack 2", remaining_weight=0, archived=True)
        for _ in range(PLAIN):
            make(location="Rack 1", remaining_weight=500)
    return spoolman_url


PRELUDE = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what + "; the page shows: " + document.querySelector("main").innerText.slice(0, 300)); }
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
const shown = (el) => !!el && el.getClientRects().length > 0;
const unlock = async () => { SW.setLock("unlocked", { code: "__CODE__" }); await sleep(300); };
const rows = () => $$(".coll--spools > .coll__item");
const rowOf = (id) => $(`.coll--spools > .coll__item[data-id="${id}"]`);
const cells = (row) => Object.fromEntries($$(".coll__row:first-child > .coll__cell[data-col]", row).map((c) => [c.dataset.col, text(c)]));
const ready = async (look) => {
  if (look) document.documentElement.setAttribute("data-look", look);
  location.hash = "#spools";
  await until(() => rows().length || $(".empty"), "the spools");
  await sleep(300);
};
const search = $.bind(null, ".spools-toolbar input[type=search]");
const type = async (value) => { const c = $(".spools-toolbar input[type=search]"); c.value = value; c.dispatchEvent(new Event("input", { bubbles: true })); await sleep(900); };
const chip = (f) => $(`.spools-chip[data-filter="${f}"]`);
const settle = async (check, what) => { await until(check, what); await sleep(150); };
"""


def _go(hub, tmp_path, body, width=1280, look="console"):
    script = PRELUDE + f'const out = {{}};\nawait ready("{look}");\n' + body + "\nreturn out;\n"
    return _drive(hub, tmp_path, script, width=width)


def test_the_list_has_the_count_the_spoolman_link_and_fifty_rows_then_show_more(hub, stock, tmp_path):
    port = urlparse(stock).port
    page = _go(hub, tmp_path, r"""
out.count = text($(".spools-count"));
out.link = $(".spools-link") && { text: text($(".spools-link")), href: $(".spools-link").getAttribute("href"), target: $(".spools-link").target, rel: $(".spools-link").rel };
out.title = text($("h1"));
out.nav = $$(".nav__group").map((g) => $$(".nav__item", g).map((a) => a.getAttribute("href")));
out.rows = rows().length;
out.first = cells(rowOf(1));
out.sealed = cells(rowOf(2)); out.low = cells(rowOf(5)); out.loaded = cells(rowOf(7)); out.tagged = cells(rowOf(9));
out.ids = rows().slice(0, 12).map((r) => r.dataset.id);
out.headers = $$(".coll--spools .coll__head [role=columnheader]").map(text);
out.swatch = shown($(".swatch", rowOf(1))) && getComputedStyle($(".swatch", rowOf(1))).getPropertyValue("--swatch").trim();
out.level = $(".swatch", rowOf(1)).style.getPropertyValue("--level");
out.shownLine = text($(".spools-shown"));
out.locked = $(".chip--lock").dataset.state;
const more = $$(".spools-foot .btn").find((b) => text(b) === "Show more");
out.more = !!more;
more.click();
await settle(() => rows().length > 50, "more rows");
out.afterRows = rows().length; out.afterCount = text($(".spools-count")); out.afterShown = text($(".spools-shown"));
out.moreGone = !$$(".spools-foot .btn").length;
out.rowcount = $(".coll--spools").getAttribute("aria-rowcount");
""")
    assert page["count"] == f"{TOTAL} spools" and page["title"] == T("nav_spools")
    assert page["link"] == {"text": "Open Spoolman", "href": f"http://127.0.0.1:{port}", "target": "_blank", "rel": "noopener"}
    assert page["nav"][0][:3] == ["#overview", "#printers", "#spools"] and "#spools" not in page["nav"][1]
    assert page["rows"] == 50 and page["more"] and page["shownLine"] == f"Showing 50 of {TOTAL}"
    assert page["ids"] == [str(n) for n in (*range(1, EMPTY), *range(EMPTY + 1, EMPTY + 4))]       # the empty spool is not listed
    assert page["headers"] == ["Details", "Colour", "Number", "Spool", T("common_field_material"), "Left", "Where", T("common_field_state")]
    assert page["first"]["number"] == "#1" and page["first"]["title"] == "Polymaker PolyTerra PLA Charcoal Black" and page["first"]["material"].endswith("PLA")
    assert page["first"]["left"].endswith("620 g") and page["first"]["where"].endswith("Rack 1") and page["first"]["state"].startswith(T("spool_state_opened"))
    assert T("common_sealed") in page["sealed"]["state"] and page["sealed"]["where"].endswith("Sealed stock")
    assert "Running low" in page["low"]["state"] and page["low"]["left"].endswith("40 g")
    assert page["loaded"]["where"].endswith("Workshop X1 – AMS A1")
    assert "Tagged" in page["tagged"]["state"] and "No tag" in page["first"]["state"]
    assert page["swatch"] == "#2B2B2E" and float(page["level"]) == pytest.approx(0.62)
    assert page["afterRows"] == TOTAL and page["afterCount"] == f"{TOTAL} spools" and page["afterShown"] == f"Showing {TOTAL} of {TOTAL}" and page["moreGone"]
    assert page["locked"] == "locked"                 # looking at the list needed no code


def test_search_and_each_chip_narrow_the_list_and_the_empty_states_say_what_to_do(hub, stock, spoolman_url, tmp_path):
    page = _go(hub, tmp_path, r"""
const ids = () => rows().map((r) => Number(r.dataset.id));
const state = () => ({ ids: ids(), count: text($(".spools-count")), pressed: $$(".spools-chip").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.filter), more: !!$(".spools-foot .btn") });
out.chips = $$(".spools-chip").map(text);
out.group = $(".spools-chips").getAttribute("aria-label");
out.field = { label: text($(".spools-toolbar .field__label")), hint: text($(".spools-toolbar .field__hint")), type: $(".spools-toolbar input").type };
// the four chips, each alone
out.chip = {};
for (const f of ["sealed", "opened", "loaded", "low"]) {
  chip(f).click();
  await sleep(700);
  out.chip[f] = state();
}
chip("low").click(); await sleep(500);                  // the chip that is on, pressed again, is off
out.low_off = state();
// search: words match brand, name, material, place, number and tag
const q = {};
for (const w of ["sealed stock", "ams a1", "4:a1", "rack 2", "polymaker pla"]) { await type(w); q[w] = state(); }
out.q = q;
chip("low").click(); await sleep(600);
out.qlow = state();                                   // "polymaker pla" and low
await type("rack 2");
out.rack2low = state();
// nothing matches: the empty state, its way back
await type("zzzz");
out.none = { title: text($(".spools-listbox .empty__title")), clear: text($(".spools-listbox .empty .btn")), count: text($(".spools-count")), rows: rows().length };
$(".spools-listbox .empty .btn").click();
await settle(() => rows().length, "the list again");
out.back = { ...state(), field: $(".spools-toolbar input").value };
// the routes' shapes, read while the page is locked
const r1 = await api("spools?limit=2&offset=3");
out.page = { n: r1.spools.length, total: r1.total, offset: r1.offset, more: r1.has_more, url: !!r1.spoolman_url, keys: Object.keys(r1.spools[0]).sort() };
const r2 = await api("spools/5");
out.one = { low: r2.spool.low, loaded: r2.spool.loaded, state: r2.spool.state, use: r2.last_use };
out.loadedView = (await api("spools/7")).spool.loaded;
out.lastTag = await api("spools/last-tag");
out.badFilter = await api("spools?filter=nope").then(() => null, (e) => ({ status: e.status, message: e.message }));
out.gone = await api("spools/9999").then(() => null, (e) => ({ status: e.status, message: e.message }));
out.badOffset = await api("spools?offset=-1").then(() => null, (e) => ({ status: e.status, message: e.message }));
out.noCode = await fetch("/setup/api/spools/2", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ gross: 300, dry_run: true }) }).then(async (r) => ({ status: r.status, body: await r.json() }));
""")
    assert page["chips"] == [T("common_sealed"), T("spool_state_opened"), "In a printer", "Running low"] and page["group"] == "Show only"
    assert page["field"] == {"label": "Find a spool", "hint": "Brand, name, material, place, number or tag.", "type": "search"}
    assert page["chip"]["sealed"]["ids"] == SEALED and page["chip"]["sealed"]["pressed"] == ["sealed"] and page["chip"]["sealed"]["count"] == "3 spools"
    assert len(page["chip"]["opened"]["ids"]) == 50 and page["chip"]["opened"]["more"] and page["chip"]["opened"]["count"] == f"{OPENED} spools"
    assert page["chip"]["opened"]["ids"][:3] == [1, 5, 6] and not set(SEALED) & set(page["chip"]["opened"]["ids"])
    assert page["chip"]["loaded"]["ids"] == LOADED and page["chip"]["loaded"]["count"] == "2 spools"
    assert page["chip"]["low"]["ids"] == LOW and page["chip"]["low"]["pressed"] == ["low"]
    assert page["low_off"]["pressed"] == [] and page["low_off"]["count"] == f"{TOTAL} spools"
    assert page["q"]["sealed stock"]["ids"] == SEALED and page["q"]["ams a1"]["ids"] == [LOADED[0]] and page["q"]["4:a1"]["ids"] == [TAGGED]
    assert page["q"]["rack 2"]["ids"][:3] == [*LOW, TAGGED] and page["q"]["polymaker pla"]["count"] == f"{TOTAL} spools"
    assert page["qlow"]["ids"] == LOW and page["qlow"]["pressed"] == ["low"] and page["rack2low"]["ids"] == LOW
    assert page["none"] == {"title": T("spools_empty_filtered"), "clear": "Clear the search and filter", "count": "0 spools", "rows": 0}
    assert page["back"]["count"] == f"{TOTAL} spools" and page["back"]["pressed"] == [] and page["back"]["field"] == ""
    assert page["page"] == {"n": 2, "total": TOTAL, "offset": 3, "more": True, "url": True, "keys": sorted(
        ["id", "location", "remaining_g", "net_g", "tare_g", "tag", "state", "filament_id", "vendor", "name", "material", "color_hex", "lot", "loaded", "low"])}
    assert page["one"] == {"low": True, "loaded": None, "state": "opened", "use": None} and page["loadedView"]["printer"] == "Workshop X1" and page["loadedView"]["slot"] == "AMS A1"
    assert page["lastTag"] == {"tag": None}
    assert page["badFilter"]["status"] == 400 and page["gone"]["status"] == 404 and page["badOffset"]["status"] == 400
    assert page["noCode"]["status"] == 403                                    # a change needs the page unlocked


def test_the_empty_state_says_what_to_do_and_the_spoolman_link_stays(hub, spoolman_url, tmp_path):
    httpx.patch(spoolman_url + "/api/v1/spool/1", json={"archived": True}).raise_for_status()
    page = _go(hub, tmp_path, r"""
out.title = text($(".spools-listbox .empty__title")); out.text = text($(".spools-listbox .empty__text"));
out.count = text($(".spools-count")); out.link = !!$(".spools-link"); out.rows = rows().length; out.foot = !!$(".spools-foot .btn");
""")
    assert page == {"title": "No spools yet.", "text": "Add your first one from your phone.", "count": "0 spools", "link": True, "rows": 0, "foot": False}


TAGS = [None, "4:de:ad:be", "4:a1:b2:c3", "4:77:90:0e"]          # what the readers have last seen, one answer for each press of Link the last tapped tag


def test_a_spools_detail_shows_its_facts_and_each_change_previews_first_and_needs_the_code(hub, stock, spoolman_url, tmp_path, monkeypatch):
    import time
    from filament_kit import tagsources
    from filament_kit.bridge import usage
    taps = iter(TAGS)

    def latest(cfg):
        uid = next(taps)
        return None if uid is None else {"nfc_id": uid, "read_at_unix": time.time() - 30, "age_seconds": 30, "reader": "station", "held": False}

    monkeypatch.setattr(tagsources, "latest", latest)
    monkeypatch.setattr(usage, "entries", lambda serial, days=14: [{"id": "u1", "at": "2026-11-16T14:02:00+00:00", "job": "cube", "grams": 41.5, "spool_id": 1, "slot": "A1", "observe": False, "undone": False}])
    page = _go(hub, tmp_path, r"""
const detail = (id) => $(`#spool-detail-${id}`);
const open = async (id) => { $(".coll__title", rowOf(id)).click(); await until(() => shown(detail(id)), "the detail of " + id); await sleep(400); };
const facts = (id) => Object.fromEntries($$(".kv__row", detail(id)).map((r) => [text($(".kv__key", r)), text($(".kv__value", r))]));
const box = (id, n) => $$(".spools-act .result", detail(id))[n];
const said = async (id, n, what) => { await until(() => box(id, n).dataset.state && box(id, n).dataset.state !== "run" && text(box(id, n)), what); await sleep(100); return { kind: box(id, n).dataset.state, text: text($(".result__text", box(id, n))), action: text($(".btn", box(id, n))) }; };
const press = (id, label) => { for (const r of $$(".spools-act .result", detail(id))) SW.result(r, null); $$(".spools-act .btn", detail(id)).find((b) => text(b) === label).click(); };
const field = (id, name) => detail(id).querySelector(`[name="${name}"]`);
const set = (c, v) => { c.value = v; c.dispatchEvent(new Event("input", { bubbles: true })); c.dispatchEvent(new Event("change", { bubbles: true })); };
const apply = (id, n) => $(".btn", box(id, n)).click();
const dlg = async () => until(() => $("dialog[open]"), "a dialog");
const hubSays = async (id) => (await api("spools/" + id)).spool;

// looking: the detail opens while the page is locked
await open(1);
out.address = location.hash;
out.facts = facts(1);
out.titleOnOpen = text($(".detail__title", detail(1)));
out.actions = $$(".spools-act .btn", detail(1)).map(text);
out.moveOptions = $$("select option", detail(1)).map(text);
out.moveStart = field(1, "location").value;

// Update weight: a bad value is refused at the field, nothing is sent
press(1, "Update weight");
await sleep(300);
out.noWeight = text($(".field__error", field(1, "gross").closest(".field")));
set(field(1, "gross"), "abc"); press(1, "Update weight"); await sleep(300);
out.badWeight = text($(".field__error", field(1, "gross").closest(".field")));
// locked: the press asks for the code, and Cancel sends nothing
set(field(1, "gross"), "540");
press(1, "Update weight");
const ask = await dlg();
out.unlockAsked = !!$("input[type=password]", ask);
$('[data-action="cancel"]', ask).click();
await until(() => !$("dialog[open]"), "the dialog to close");
out.afterCancel = { result: box(1, 0).dataset.state || null, left: (await hubSays(1)).remaining_g };
// unlocked: the preview, then Apply
await unlock();
press(1, "Update weight");
out.weightPreview = await said(1, 0, "the weight preview");
out.beforeApply = (await hubSays(1)).remaining_g;
apply(1, 0);
await until(() => box(1, 0).dataset.state === "ok", "the weight saved");
out.weightDone = await said(1, 0, "the weight result");
out.afterWeight = { hub: (await hubSays(1)).remaining_g, cell: cells(rowOf(1)).left, facts: facts(1)["Left"] };

// Move: the same, to the first place of the list
const target = field(1, "location").options[1].value;
set(field(1, "location"), target);
press(1, "Move");
out.movePreview = await said(1, 1, "the move preview");
out.beforeMove = (await hubSays(1)).location;
apply(1, 1);
await until(() => box(1, 1).dataset.state === "ok", "the move done");
out.moveDone = await said(1, 1, "the move result");
out.target = target;
out.afterMove = { hub: (await hubSays(1)).location, cell: cells(rowOf(1)).where, facts: facts(1)["Location"] };
set(field(1, "location"), target);
press(1, "Move");
out.moveSame = await said(1, 1, "nothing to move");
set(field(1, "location"), "auto");
press(1, "Move");
out.moveAuto = await said(1, 1, "the automatic preview");

// Link the last tapped tag: no tag, then a tag (preview, apply), then a tag held by another spool
press(1, "Link the last tapped tag");
out.linkNone = await said(1, 2, "no tag read");
press(1, "Link the last tapped tag");
out.linkPreview = await said(1, 2, "the link preview");
out.tagBefore = (await hubSays(1)).tag;
apply(1, 2);
await until(() => box(1, 2).dataset.state === "ok", "the tag linked");
out.linkDone = await said(1, 2, "the link result");
out.afterLink = { hub: (await hubSays(1)).tag, facts: facts(1)["Tag"], state: text($('[data-col="state"]', rowOf(1))) };
await open(2);
press(2, "Link the last tapped tag");
out.linkConflict = await said(2, 2, "the conflict");
press(2, "Link the last tapped tag");
out.linkOpens = await said(2, 2, "the opening link preview");
apply(2, 2);
await until(() => box(2, 2).dataset.state === "ok", "the sealed spool linked");
out.afterOpen = { hub: await hubSays(2), state: text($('[data-col="state"]', rowOf(2))) };

// Mark empty: previews, asks first (Cancel keeps it), then does it
await open(3);
press(3, "Mark empty");
out.emptyPreview = await said(3, 3, "the empty preview");
apply(3, 3);
const sure = await dlg();
out.ask = { title: text($(".dialog__title", sure)), text: text($(".dialog__text", sure)), buttons: $$(".dialog__foot .btn", sure).map(text) };
$('[data-action="cancel"]', sure).click();
await until(() => !$("dialog[open]"), "the question to close");
out.keptSealed = (await hubSays(3)).state;
apply(3, 3);
const sure2 = await dlg();
$('[data-action="confirm"]', sure2).click();
await until(() => box(3, 3).dataset.state === "ok", "marked empty");
out.emptyDone = await said(3, 3, "the empty result");
out.afterEmpty = { hub: (await hubSays(3)).state, row: rowOf(3).dataset.state, cell: text($('[data-col="state"]', rowOf(3))) };
""")
    assert page["address"] == "#spools/1" and page["titleOnOpen"] == "Polymaker PolyTerra PLA Charcoal Black"
    assert page["facts"] == {"Number": "#1", "Brand": "Polymaker", "Name": "PolyTerra PLA Charcoal Black", "Material": "PLA", "Colour": "#2B2B2E", "Left": "620 g / 1000 g",
                             "State": "Opened", "Location": "Rack 1", "Tag": T("common_empty"), "Lot": T("common_empty"), "Last taken off": page["facts"]["Last taken off"]}
    assert page["facts"]["Last taken off"].startswith("41.5 g on ")
    assert page["actions"] == ["Update weight", "Move", "Link the last tapped tag", "Mark empty"]
    assert page["moveOptions"][0] == T("storage_automatic") and len(page["moveOptions"]) > 2
    assert page["noWeight"] == page["badWeight"] == "Enter the weight in grams, a number above 0."
    assert page["unlockAsked"] and page["afterCancel"] == {"result": None, "left": 620}
    assert page["weightPreview"] == {"kind": "info", "text": "Preview: 620 g left becomes 340 g.", "action": "Apply"} and page["beforeApply"] == 620    # 540 g on the scale less the spool's 200 g
    assert page["weightDone"]["text"] == "Updated: 340 g left." and page["weightDone"]["kind"] == "ok"
    assert page["afterWeight"]["hub"] == 340 and page["afterWeight"]["cell"].endswith(T("common_grams", grams=340)) and page["afterWeight"]["facts"] == "340 g / 1000 g"
    assert page["movePreview"] == {"kind": "info", "text": f"Preview: it moves from Rack 1 to {page['target']}.", "action": "Apply"} and page["beforeMove"] == "Rack 1"
    assert page["moveDone"]["text"] == T("spool_result_moved", location=page["target"])
    assert page["afterMove"]["hub"] == page["target"] and page["afterMove"]["cell"].endswith(page["target"]) and page["afterMove"]["facts"] == page["target"]
    assert page["moveSame"] == {"kind": "neutral", "text": "Nothing would change.", "action": None}
    assert page["moveAuto"]["kind"] in ("info", "neutral")
    assert page["linkNone"] == {"kind": "warn", "text": T("spool_sheet_no_tag"), "action": None}
    assert page["linkPreview"] == {"kind": "info", "text": "Preview: tag 4:de:ad:be is linked to this spool.", "action": "Apply"} and page["tagBefore"] is None
    assert page["linkDone"]["text"] == T("spool_result_tag_linked") and page["afterLink"]["hub"] == "4:de:ad:be" and page["afterLink"]["facts"] == "4:de:ad:be" and "Tagged" in page["afterLink"]["state"]
    assert page["linkConflict"]["kind"] == "bad" and "already linked" in page["linkConflict"]["text"]
    assert page["linkOpens"]["text"] == "Preview: tag 4:77:90:e is linked to this spool. It then counts as opened." and page["linkOpens"]["action"] == "Apply"
    assert page["afterOpen"]["hub"]["tag"] == "4:77:90:e" and page["afterOpen"]["hub"]["state"] == "opened" and T("spool_state_opened") in page["afterOpen"]["state"]
    assert page["emptyPreview"] == {"kind": "info", "text": "Preview: 1000 g left becomes 0 g and the spool is marked empty.", "action": "Mark empty"}
    assert page["ask"] == {"title": "Mark spool 3 empty?", "text": page["ask"]["text"], "buttons": ["Cancel", "Mark empty"]} and page["ask"]["text"].endswith("it leaves this list.")
    assert page["keptSealed"] == "sealed" and page["emptyDone"]["text"] == "Marked empty."
    assert page["afterEmpty"]["hub"] == "empty" and page["afterEmpty"]["row"] == "off" and T("common_empty") in page["afterEmpty"]["cell"]
    with httpx.Client() as c:                           # Spoolman holds what the page says
        first, sealed, emptied = (c.get(spoolman_url + f"/api/v1/spool/{n}").json() for n in (1, 2, 3))
    assert first["remaining_weight"] == 340 and first["location"] == page["target"] and json.loads(first["extra"]["nfc_id"]) == "4:de:ad:be"
    assert json.loads(sealed["extra"]["nfc_id"]) == "4:77:90:e" and inventory.SEALED_COMMENT not in (sealed["comment"] or "") and sealed["first_used"]
    assert emptied["archived"] is True and emptied["remaining_weight"] == 0


@pytest.mark.parametrize("look", ["console", "workbench", "palette", "panes"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_section_reads_in_every_look_without_sideways_scrolling_or_clipping(hub, stock, tmp_path, look, width):
    page = _go(hub, tmp_path, r"""
const vw = document.documentElement.clientWidth;
const wide = (root) => $$("*", root).filter((el) => shown(el) && el.getBoundingClientRect().right > vw + 1 && !el.closest(".sr, [aria-hidden=true], .tooltip")).slice(0, 5).map((el) => el.tagName + "." + el.className);
out.vw = vw;
out.list = { overflow: document.documentElement.scrollWidth > vw, wide: wide($(".spools")), rows: rows().length, title: shown($(".coll__title", rowOf(1))), search: shown($(".spools-toolbar input")), chips: $$(".spools-chip").every(shown), link: shown($(".spools-link")) };
out.nav = { item: !!$('.nav__item[href="#spools"]'), inBar: !!$('.nav__item[href="#spools"][data-tab]') };
out.cols = $$(":scope > .coll__row:first-child > .coll__cell", rowOf(1)).filter(shown).map((c) => c.dataset.col);
$(".coll__title", rowOf(1)).click();
await until(() => shown($("#spool-detail-1")), "the detail");
await sleep(500);
const d = $("#spool-detail-1");
out.detail = { overflow: document.documentElement.scrollWidth > vw, wide: wide(d), buttons: $$(".spools-act .btn", d).map((b) => shown(b)), inDialog: !!d.closest("dialog"), facts: $$(".kv__row", d).length, field: shown($('[name="gross"]', d)) };
""", width=width, look=look)
    assert page["list"]["overflow"] is False and page["list"]["wide"] == [], page["list"]
    assert page["list"]["rows"] == 50 and page["list"]["title"] and page["list"]["search"] and page["list"]["chips"] and page["list"]["link"]
    assert page["nav"]["item"] and not page["nav"]["inBar"]                     # Spools is in the More sheet on a phone, never in the bar
    assert page["detail"]["overflow"] is False and page["detail"]["wide"] == [], page["detail"]
    assert page["detail"]["buttons"] == [True] * 4 and page["detail"]["field"] and page["detail"]["facts"] == 11
    assert page["detail"]["inDialog"] is (look == "palette")                    # Palette's detail is a sheet; the others open it in the row
    assert {"title", "state", "number"} <= set(page["cols"])


@pytest.mark.parametrize("width", [1280, 1776, 1024, 768])
def test_in_panes_the_spools_summaries_stay_readable_blocks(hub, stock, tmp_path, width):
    from test_hub_panes_summary_width import MEASURE
    got = _drive(hub, tmp_path, MEASURE.replace("__SECTIONS__", '["spools"]'), width=width)
    seen = [(s, c) for s, cells in got["out"].items() for c in cells]
    assert any(c["label"] == "real" for _, c in seen) and any(c["label"] == "long" for _, c in seen), "no spool summary cell was found to measure"
    bad = [(c["label"], c["text"], c["w"], c["lines"]) for _, c in seen if c["lines"] > 2 or (c["em"] < 8 and c["lines"] > 1)]
    assert not bad, (width, "a summary squeezed to a sliver or wrapped past two lines", bad)
