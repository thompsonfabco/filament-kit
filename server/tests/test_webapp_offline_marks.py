"""S3.17 (design 04 10.3, third point): while the Hub cannot be reached every screen of the web app keeps its last data with
"Last update <age>: the Hub did not answer.", and every button that needs the Hub gets aria-disabled and the reason "Needs the
Hub." ("Read labels" and "Preview" say "The Hub cannot be reached."). Run in a headless Chrome, Edge or Chromium already on the
machine (tests/page_drive.mjs for the presses, tests/aut5_run.mjs for the audit), with the Hub stopped by the page itself: its
fetch refuses every /api/ request. Example data only. Skipped when Node 22+ or a browser is missing (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json

import pytest

from test_web_app_audit import ALLOW, _drive, _node, _run, served_printers, served_web  # noqa: F401  (the fixtures)
from test_web_printers import SERIAL

# What every script starts with: the helpers, a log of the requests the page makes to the Hub, and the Hub that can be stopped.
PRELUDE = r"""
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const log = [];                                              // every request to the Hub the page makes: "METHOD path"
const realFetch = window.fetch;
let down = false;
window.fetch = (u, o) => {
  if (String(u).includes("/api/")) {
    log.push(((o && o.method) || "GET") + " " + String(u).split("/api/")[1]);
    if (down) return Promise.reject(new TypeError("Failed to fetch"));
  }
  return realFetch(u, o);
};
const posts = () => log.filter((x) => x.startsWith("POST")).length;
async function lose() { down = true; api("vendors").catch(() => {}); await until(() => $(".offline-banner"), "the offline banner"); }
async function regain() { down = false; press("Try now").click(); await until(() => !$(".offline-banner"), "the banner to go"); }
const whys = (b) => (b.getAttribute("aria-describedby") || "").split(" ").map((i) => document.getElementById(i)).filter(Boolean).map((e) => text(e));
const marked = (b, reason) => !!b && b.getAttribute("aria-disabled") === "true" && whys(b).includes(reason);
const NEEDS = "Needs the Hub.", REACH = "The Hub cannot be reached.";
const age = (el) => { const m = /^Last update (\d+) s ago: the Hub did not answer\.$/.exec(text(el)); return m ? Number(m[1]) : null; };
const typeIn = (el, v) => { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); };
const marks = () => $$("[data-hub-why]").length, ages = () => $$(".hub-age").length;
const seen = {};
"""

# The screens that need no printer: Add spools, Spools (with its sheet), Recently added (with a record), Slicer presets.
SCREENS = PRELUDE + r"""
await until(() => $(".add__bar"), "the Add spools screen");
// ---- online first: each screen reads its data, and nothing is marked ----
location.hash = "#spools";
await until(() => $(".spools__results .spools__row"), "the spools list");
const rowsBefore = $$(".spools__results .spools__row").length;
location.hash = "#recent";
await until(() => $(".coll__item"), "the Recently added list");
const itemsBefore = $$(".coll__item").length;
location.hash = "#recent/__HID__";
await until(() => $(".detail__body"), "the record");
location.hash = "#presets";
await until(() => $("[data-action=build]"), "the presets");
seen.cleanOnline = marks() === 0 && ages() === 0 && $$("[data-needs-hub]").every((b) => b.getAttribute("aria-disabled") !== "true" || b._reason);
seen.sentBeforeLoss = log.length;
// the first spool's sheet is open when the Hub stops
location.hash = "#spools";
await until(() => $(".spools__results .spools__row"), "the spools list");
$(".spools__results .spools__row").click();
await until(() => $("dialog[open] .spools__sum-text") && !$("dialog[open] .skeleton"), "the spool sheet");
await lose();

// ---- the open sheet: its buttons that need the Hub ----
{
  const sheet = $("dialog[open]"), mine = $$("[data-needs-hub]", sheet);
  const previews = mine.filter((b) => text(b) === "Preview");
  seen.sheet = { count: mine.length, allMarked: mine.every((b) => marked(b, b.dataset.needsHub === "reach" ? REACH : NEEDS)),
    preview: previews.length > 0 && previews.every((b) => marked(b, REACH)), link: marked(mine.find((b) => text(b).startsWith("Link")), NEEDS) };
  const before = log.length;
  mine.find((b) => text(b).startsWith("Link")).click();      // a press on a marked button does nothing
  await sleep(300);
  seen.sheet.pressSent = log.length - before;
}

// ---- Spools: the list stays, says how old it is, the search says why it waits ----
location.hash = "#spools";
await until(() => !$("dialog[open]"), "the sheet to close");
await sleep(300);
{
  const res = $(".spools__results"), line = $(".hub-age .hub-age__text", res);
  seen.spools = { rows: $$(".spools__row", res).length === rowsBefore, line: age(line) !== null, search: marked($(".spools__search .field__box button"), NEEDS),
    lineFirst: res.firstElementChild === $(".hub-age", res) };
  const first = age(line);
  await sleep(2300);                                          // the age moves on by itself
  seen.spools.ageMoves = age($(".hub-age .hub-age__text", res)) > first;
  tabs.spools.enter();                                        // the list is asked for again while the Hub is away: what is shown stays, marked
  await sleep(600);
  seen.spools.afterRedraw = $$(".spools__row", $(".spools__results")).length === rowsBefore && age($(".hub-age .hub-age__text", $(".spools__results"))) !== null
    && marked($(".spools__search .field__box button"), NEEDS);
}

// ---- Add spools: photos, cards and fields keep working; Read labels and Preview say the Hub cannot be reached ----
location.hash = "#add";
await until(() => $(".add__bar") && !$(".add__bar").closest(".hidden"), "the Add spools screen");
{
  const read = press("Read labels"), bar = $(".add__bar-btn"), find = $(".add__search .field__box button");
  seen.add = { read: marked(read, REACH), preview: marked(bar, REACH), search: marked(find, NEEDS),
    hand: !!$(".add__search").closest(".add__group").querySelector(".hub-age"),
    photoButtons: ["Take photo", "Choose photos", "New filament"].map((l) => { const b = press(l); return !!b && b.getAttribute("aria-disabled") !== "true"; }) };
  // a photo: the strip takes it (the Read labels button redraws, and stays marked)
  const png = await new Promise((r) => { const c = document.createElement("canvas"); c.width = 8; c.height = 8; c.getContext("2d").fillRect(0, 0, 8, 8); c.toBlob(r, "image/png"); });
  const dt = new DataTransfer(); dt.items.add(new File([png], "label.png", { type: "image/png" }));
  const pick = $("input[type=file][multiple]"); pick.files = dt.files; pick.dispatchEvent(new Event("change", { bubbles: true }));
  await until(() => $$(".add__strip *").length > 0, "the photo in the strip");
  seen.add.photo = true;
  seen.add.readAfterPhoto = marked(read, REACH) && !read._reason;          // its own reason went (a photo is there); the mark is what keeps it off
  // a card and a field: typed text is kept
  press("New filament").click();
  await until(() => $(".add__card"), "a card");
  const brand = $$(".add__card .field").find((f) => text($(".field__label", f)).startsWith("Brand"))._control;
  typeIn(brand, "Polymaker");
  await sleep(200);
  seen.add.typed = brand.value === "Polymaker";
  seen.add.barAfterCard = marked($(".add__bar-btn"), REACH);
  const before = log.length, sent = posts();
  read.click(); $(".add__bar-btn").click();
  await sleep(300);
  seen.add.pressSent = posts() - sent;
  seen.add.brand = brand;
}

// ---- Slicer presets ----
location.hash = "#presets";
await until(() => $("[data-action=build]") && !$("[data-action=build]").closest(".hidden"), "the presets");
{
  const build = $("[data-action=build]"), mine = $$("[data-action=create-line], [data-action=add-to-line]");
  const sent = posts();
  build.click();
  await sleep(300);
  seen.presets = { build: marked(build, NEEDS), cards: mine.length, cardsMarked: mine.every((b) => marked(b, NEEDS)), pressSent: posts() - sent,
    line: !!build.closest(".group").querySelector(":scope > .group__body > .hub-age") };
}

// ---- Recently added: the list stays; a record keeps its groups; the edit form's Save waits for the Hub ----
location.hash = "#recent";
await until(() => $(".coll__item") && !$(".coll__item").closest(".hidden"), "the list");
seen.recent = { items: $$(".coll__item").length === itemsBefore, line: age($(".hub-age .hub-age__text", $(".coll__item").closest("section"))) !== null };
location.hash = "#recent/__HID__";
await until(() => $(".detail__body") && !$(".detail__body").closest(".hidden"), "the record");
seen.recent.groups = $$(".detail__body [data-hub-group]").length;
seen.recent.groupLines = $$(".detail__body [data-hub-group] > .group__body > .hub-age").length;
{
  press("Edit by hand").click();
  await until(() => $('[data-action="save"]'), "the edit form");
  const save = $('[data-action="save"]'), field = $$("input", save.closest("form")).find((i) => i.type === "text" && !i.disabled);
  typeIn(field, "Typed offline");
  seen.recent.save = marked(save, NEEDS);
  seen.recent.ask = $('[data-action="ask"]') ? marked($('[data-action="ask"]'), NEEDS) : null;
  const sent = posts();
  save.click();
  await sleep(300);
  seen.recent.pressSent = posts() - sent;
  seen.recent.kept = field.value === "Typed offline";
  seen.recent.field = field;
}

// ---- the Hub answers again (the edit form is still open: the Recently added screen keeps it): every mark goes, what was typed stays ----
await regain();
await sleep(300);
seen.back = { marks: marks(), ages: ages(), stuck: $$("[data-needs-hub]").filter((b) => b.getAttribute("aria-disabled") === "true" && !b._reason && b.getAttribute("aria-busy") !== "true").map((b) => text(b)),
  typed: seen.recent.field.isConnected && seen.recent.field.value === "Typed offline" && seen.add.brand.value === "Polymaker",
  save: $('[data-action="save"]').getAttribute("aria-disabled") !== "true",
  read: $$("button").filter((b) => text(b) === "Read labels").every((b) => b.getAttribute("aria-disabled") !== "true") };
delete seen.add.brand; delete seen.recent.field;
return seen;
"""

PRINTERS = PRELUDE + r"""
location.hash = "#printers";
await until(() => $$(".printers__more [data-needs-hub]").length >= 1, "the Printers list");
seen.list = { before: $$("[data-needs-hub]").length };
location.hash = "#printers/__SERIAL__";
await until(() => $$("[data-needs-hub]").length >= 3 && $$("[data-hub-group]").length >= 1, "the printer page");
await sleep(1500);
seen.page = { buttons: $$("[data-needs-hub]").length, groups: $$("[data-hub-group]").length, cleanOnline: marks() === 0 && ages() === 0 };
await lose();
{
  const mine = $$("[data-needs-hub]").filter((b) => !b.closest(".hidden, [hidden]") && b.getAttribute("aria-busy") !== "true");
  seen.page.marked = mine.filter((b) => marked(b, NEEDS)).length;
  seen.page.unmarked = mine.filter((b) => !marked(b, NEEDS)).map((b) => text(b) + "/" + b.getAttribute("aria-disabled"));
  const groups = $$("[data-hub-group].group");                // the printer page's own groups (the other screens' are built too)
  seen.page.groups = groups.length;
  seen.page.lines = groups.length >= 3 && groups.every((g) => g.querySelector(":scope > .group__body > .hub-age"));
  const sent = posts(), btn = mine.find((b) => marked(b, NEEDS));
  btn.click();
  await sleep(300);
  seen.page.pressSent = posts() - sent;
  // a marked button that is hidden (a printer without a camera) takes its reason with it; nothing shows a reason without its button
  const visible = (e) => e.getClientRects().length > 0;
  const ghost = needsHub(SW.btn("Ghost")); ghost.hidden = true; document.body.append(ghost);
  await sleep(100);
  const why = ghost.nextElementSibling;
  seen.page.ghostHidden = !!why && why.hasAttribute("data-hub-why") && !visible(why);
  ghost.hidden = false; await sleep(100);
  seen.page.ghostShown = visible(ghost.nextElementSibling);
  const gw = ghost.nextElementSibling; ghost.remove(); if (gw) gw.remove();
  seen.page.orphans = $$("[data-hub-why]").filter(visible).filter((r) => { const b = r.previousElementSibling; return !(b && b.matches("[data-needs-hub]") && visible(b)); }).map((r) => text(r));
}
location.hash = "#printers";
await sleep(600);
seen.list.found = $$('[data-action="add-found"]').length;
seen.list.foundMarked = $$('[data-action="add-found"]').every((b) => marked(b, NEEDS));
seen.list.addVisible = $$(".add__bar-btn, .add__search, .add__card").some((e) => e.getClientRects().length > 0);   // 6: does the Add screen show on this screen?
seen.list.marked = $$(".printers__more [data-needs-hub]").length >= 1 && $$(".printers__more [data-needs-hub]").every((b) => marked(b, NEEDS));
await regain();
await sleep(300);
seen.back = { marks: marks(), ages: ages() };
return seen;
"""

# Add spools: a search typed while the Hub is away keeps the results; the bar follows the shell on reconnect; the Move menu stays shut.
SEARCH = PRELUDE + r"""
const typeSearch = (q) => { const c = $(".add__search .field__control"); typeIn(c, q); c.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); };
// a spool in the list (an existing filament), then results on show
typeSearch("galaxy");
await until(() => $(".add__row"), "a filament row");
$(".add__row").click();
await until(() => $(".add__bar-text").textContent.includes("not previewed"), "the spool ready to preview");
typeSearch("pla");
await until(() => $$(".add__row").length >= 2, "the results");
const rows = $$(".add__row").length;
// the Hub stops without the page knowing; Preview is pressed and learns it
down = true;
$(".add__bar-btn").click();
await until(() => $(".offline-banner"), "the offline banner");
await until(() => $(".add__bar-text").textContent.includes("cannot be reached"), "the bar says so");
// a search typed now: nothing is asked, the results stay
const before = log.length;
typeSearch("PET");
await sleep(900);
seen.search = { rows: $$(".add__row").length === rows, none: !$(".add__none"), asked: log.slice(before).filter((x) => x.includes("filaments")).length };
// typed again just before the Hub answers: the typing delay is still running when the replay goes out
typeIn($(".add__search .field__control"), "PET");
// the Hub answers: the question typed while it was away is asked now, and the list is the answer to what the field says
await regain();
await until(() => $$(".add__row, .add__none").length > 0 && log.slice(before).some((x) => x.includes("filaments?q=PET")), "the pending search to run", 4000);
await sleep(600);                                           // the typing delay (300 ms) would have fired a second request by now
seen.pending = { asked: log.slice(before).filter((x) => x.includes("filaments?q=PET")).length, field: $(".add__search .field__control").value };
await sleep(500);
seen.bar = { text: $(".add__bar-text").textContent, disabled: $(".add__bar-btn").getAttribute("aria-disabled") };
// the shared menu: a trigger that is off opens nothing by key
const trigger = SW.btn("Menu probe"); document.body.append(trigger);
const ran = []; SW.menu(trigger, [{ label: "Rack 1", run: () => ran.push("Rack 1") }], { label: "probe" });
trigger.setAttribute("aria-disabled", "true");
for (const key of ["ArrowDown", "ArrowUp", "Enter", " "]) trigger.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
await sleep(100);
seen.menu = { opened: $$("[role=menu]").length, ran: ran.length };
trigger.removeAttribute("aria-disabled");
trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
await sleep(100);
seen.menu.opensWhenOn = $$("[role=menu]").length === 1;
// a menu open when the Hub goes: it closes with the focus back on its trigger, and an item pressed in the same moment does nothing
trigger.focus(); trigger.removeAttribute("aria-disabled");
$("[role=menu] .menu__item").focus();
trigger.setAttribute("aria-disabled", "true");
await sleep(50);
seen.menu.closedWhenOff = $$("[role=menu]").length === 0;
seen.menu.focusBack = document.activeElement === trigger;
trigger.removeAttribute("aria-disabled");
trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
await sleep(50);
const item = $("[role=menu] .menu__item");
trigger.setAttribute("aria-disabled", "true");
item.click();
await sleep(50);
seen.menu.ranWhenOff = ran.length;
return seen;
"""

# AUT-5 with the Hub stopped: each screen reads its data online, then the Hub goes and the audit sees the marked screens.
READY_OFFLINE = r"""(async () => {
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (what, fn, ms = 10000) => { const t0 = Date.now(); for (;;) { const v = fn(); if (v) return v; if (Date.now() - t0 > ms) throw new Error('offline marks: ' + what); await sleep(50); } };
const $ = (s) => document.querySelector(s);
location.hash = '#spools'; await until('spools', () => $('.spools__results .spools__row'));
location.hash = '#recent'; await until('recent', () => $('.coll__item'));
location.hash = '#presets'; await until('presets', () => $('[data-action=build]'));
location.hash = '#add'; await sleep(200);
const real = window.fetch;
window.fetch = (u, o) => (String(u).includes('/api/') ? Promise.reject(new TypeError('Failed to fetch')) : real(u, o));
api('vendors').catch(() => {});
await until('the offline banner', () => $('.offline-banner'));
await until('the age lines', () => document.querySelectorAll('.hub-age').length >= 3);
return true;
})()"""


def _node_or_skip():
    if not _node():
        pytest.skip("the page driver needs Node 22 or later")


def _all(out: dict, checks: list) -> None:
    """Every check is made and every one that fails is named."""
    bad = [what for what, ok in checks if not ok]
    assert not bad, f"{bad}: {json.dumps(out, indent=1)}"


def _need(out: dict, what: str, ok: bool) -> None:
    assert ok, f"{what}: {json.dumps(out, indent=1)}"


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
def test_every_screen_marks_what_needs_the_hub_and_keeps_its_last_data(served_web, tmp_path):
    out = _drive(served_web.url, tmp_path, SCREENS.replace("__HID__", served_web.hid), 1280, "light")
    _need(out, "nothing is marked while the Hub answers", out["cleanOnline"])
    # the open spool sheet
    s = out["sheet"]
    _need(out, "the sheet's buttons that need the Hub are marked, Preview with the other reason", s["count"] >= 2 and s["allMarked"] and s["preview"] and s["link"])
    assert s["pressSent"] == 0                                   # a press on a marked button sends nothing
    # Spools
    sp = out["spools"]
    _need(out, "Spools keeps its list, dated, first in its group, and the search waits", sp["rows"] and sp["line"] and sp["lineFirst"] and sp["search"])
    _need(out, "the age moves on by itself, and a new request while away keeps list and marks", sp["ageMoves"] and sp["afterRedraw"])
    # Add spools
    a = out["add"]
    _need(out, "Read labels and Preview say the Hub cannot be reached; the search needs the Hub", a["read"] and a["preview"] and a["search"] and a["hand"])
    _need(out, "photos, cards and fields still work", a["photoButtons"] == [True, True, True] and a["photo"] and a["typed"])
    _need(out, "a redraw keeps the marks", a["readAfterPhoto"] and a["barAfterCard"])
    assert a["pressSent"] == 0
    # Recently added
    r = out["recent"]
    _need(out, "the list stays with its line", r["items"] and r["line"])
    _need(out, "the record's groups carry the line", r["groups"] >= 2 and r["groupLines"] == r["groups"])
    _need(out, "Save changes waits, what was typed stays, a press sends nothing", r["save"] and r["kept"] and r["pressSent"] == 0 and r["ask"] in (True, None))
    # Slicer presets
    p = out["presets"]
    _need(out, "Build presets now waits with its group dated", p["build"] and p["line"] and p["cards"] >= 1 and p["cardsMarked"] and p["pressSent"] == 0)
    # the Hub answers again
    b = out["back"]
    _need(out, "every mark goes, nothing stays disabled that had no reason of its own, drafts kept", b["marks"] == 0 and b["ages"] == 0 and b["stuck"] == [] and b["typed"] and b["save"] and b["read"])


@pytest.mark.parametrize("width,scheme", [(360, "light")])
def test_the_printers_screen_marks_what_needs_the_hub(served_printers, tmp_path, width, scheme):
    out = _drive(served_printers, tmp_path, PRINTERS.replace("__SERIAL__", SERIAL), width, scheme, "marks-printers")
    print("ADD SCREEN VISIBLE ON #printers:", out["list"]["addVisible"])
    _all(out, [("a hidden button takes its reason with it and no reason shows without its button", out["page"]["ghostHidden"] and out["page"]["ghostShown"] and out["page"]["orphans"] == []),
               ("the found printer's Add needs the Hub", out["list"]["found"] >= 1 and out["list"]["foundMarked"])])
    pg = out["page"]
    _need(out, "the printer page has buttons and groups that need the Hub, none marked while it answers", pg["buttons"] >= 3 and pg["groups"] >= 1 and pg["cleanOnline"])
    _need(out, "every button on show is marked and every group dated", pg["marked"] >= 3 and pg["unmarked"] == [] and pg["lines"])
    assert pg["pressSent"] == 0
    _need(out, "the list's buttons are marked", out["list"]["marked"])
    assert out["back"] == {"marks": 0, "ages": 0}


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
def test_the_page_audit_passes_on_four_screens_with_the_hub_stopped(served_web):
    """AUT-5 (07 section 15) with the Hub stopped on Add spools, Spools, Recently added and Slicer presets: 4 views x 1280/320 x light/dark."""
    run = _run("--url", served_web.url, "--views", "#add,#spools,#recent,#presets", "--allow", str(ALLOW), "--ready", READY_OFFLINE, "--settle", "300")
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == 4 * 2 * 2 and out["failing"] == 0


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
def test_a_search_typed_offline_keeps_its_results_the_bar_follows_the_shell_and_a_disabled_menu_stays_shut(served_web, tmp_path):
    out = _drive(served_web.url, tmp_path, SEARCH, 1280, "light")
    _all(out, [("the results stay and nothing is asked", out["search"]["rows"] and out["search"]["none"] and out["search"]["asked"] == 0),
               ("the bar drops its own offline text when the Hub answers", "cannot be reached" not in out["bar"]["text"] and out["bar"]["disabled"] != "true"),
               ("a trigger with aria-disabled opens no menu by key, and one without does", out["menu"]["opened"] == 0 and out["menu"]["ran"] == 0 and out["menu"]["opensWhenOn"]),
               ("an open menu closes when its trigger goes off, focus goes back to the trigger, and its items then do nothing", out["menu"]["closedWhenOff"] and out["menu"]["focusBack"] and out["menu"]["ranWhenOff"] == 0),
               ("the search typed offline is asked once when the Hub answers", out["pending"]["asked"] == 1 and out["pending"]["field"] == "PET")])


# A silent Hub stop: the page does not know yet; the first screen opened must keep its content when its reload cannot reach the Hub.
SILENT = PRELUDE + r"""
location.hash = "#recent";
await until(() => $(".coll__item"), "the Recently added list");
const items = $$(".coll__item").length;
location.hash = "#presets";
await until(() => $("[data-action=build]"), "the presets");
const groups = $$("[data-action=build]").length;
location.hash = "#settings";
await sleep(300);
down = true;                                                // the Hub stops; nothing has told the page yet
location.hash = "#recent";
await until(() => $(".offline-banner"), "the offline banner");
await sleep(500);
seen.recent = { items: $$(".coll__item").length === items, visible: !$(".coll__item").closest(".hidden"), failure: !!$(".coll__item").closest("section").querySelector(".result[data-state=bad]") };
location.hash = "#settings";
await sleep(200);
log.length = 0; down = false; await regain(); await sleep(300);
down = true;
location.hash = "#presets";
await sleep(800);
seen.presets = { build: $$("[data-action=build]").length === groups, marked: marked($("[data-action=build]"), NEEDS) };
return seen;
"""


@pytest.mark.parametrize("served_web", ["waiting"], indirect=True)
def test_the_first_screen_opened_after_a_silent_hub_stop_keeps_its_content(served_web, tmp_path):
    out = _drive(served_web.url, tmp_path, SILENT, 1280, "light")
    _all(out, [("Recently added keeps its items and shows no failure line in place of them", out["recent"]["items"] and out["recent"]["visible"] and not out["recent"]["failure"]),
               ("Slicer presets keeps Build presets", out["presets"]["build"] and out["presets"]["marked"])])
