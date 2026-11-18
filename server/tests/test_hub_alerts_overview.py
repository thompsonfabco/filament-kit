"""EA6 phase A, the Overview's two alert places (03 4.2, 4.3): the Running low card and its "Running low" dialog
(#overview/running-low), and the Storage row with its "Storage use" panel (#overview/storage-use), in a real headless browser. The Hub is
the stub of hub_alerts_stub.py (spools/low and storage-use are the server step's); the page is the real Hub page with the new modules
loaded. The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import pytest

from hub_alerts_stub import drive, full_disk, hub_app, hub_stub, spool, storage_state  # noqa: F401

LOOKS = ["console", "workbench", "palette", "panes"]

HELPERS = r"""
// the Overview drawn again from the stub's state: another section, then back
const again = async () => { location.hash = "#devices"; await sleep(400); location.hash = "#overview"; await sleep(900); };
const card = () => $(".low");
const cardIn = () => until(() => card(), "the card");
const lowRows = () => $$(".low__row", card());
const rowInfo = (r) => ({ name: text($(".low__name", r)), meta: $$(".low__meta > span", r).map(text), stock: text($(".low__stock, .status", r)), badge: !!$(".status", r) });
const titleOf = (i) => text($(".coll__cell[data-col=title]", i)) || "";
const storageRow = () => $$(".coll--checks .coll__item").find((i) => titleOf(i).startsWith("Storage"));
"""


def _spools(n, **last):
    out = [spool(10 + i, 40 + 10 * i) for i in range(n)]
    if out and last:
        out[-1].update(last)
    return out


def test_the_running_low_card_shows_up_to_five_rows_and_leaves_with_nothing_low(hub_stub, tmp_path):
    app, _ = hub_stub
    app.state["low"] = {"threshold_g": 150, "spools": []}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
out.none = { card: !!card(), host: shown($(".overview__low")) };
// one spool, and it is the last one
await stub({ low: { threshold_g: 150, spools: [{ id: 12, filament: "Sunlu PLA Black", material: "PLA", color: "111111", remaining_g: 35, location: "Dry shelf", in_stock: 0, last_one: true }] } });
await again();
await cardIn();
out.one = { count: lowRows().length, title: text($("h2", card())), badge: text($(".overview__head .status", card())), row: rowInfo(lowRows()[0]),
            all: !!$('[data-action="low-show-all"]'), swatch: getComputedStyle($(".swatch", card())).getPropertyValue("--swatch"),
            beforeTiles: $(".overview__low").nextElementSibling === $(".tiles") };
// three spools: the least filament first, as the Hub sent them; "n more in stock" for the first
await stub({ low: { threshold_g: 150, spools: [{ id: 3, filament: "A", material: "PLA", color: "FF0000", remaining_g: 20, location: "Rack 1", in_stock: 2, last_one: false },
  { id: 4, filament: "B", material: "PLA", color: "00FF00", remaining_g: 60, location: "", in_stock: 1, last_one: false },
  { id: 5, filament: "C", material: "PETG", color: null, remaining_g: 90, location: "Rack 2", in_stock: 0, last_one: true }] } });
await again();
await sleep(500);
out.three = lowRows().map(rowInfo);
out.threeBadge = text($(".overview__head .status", card()));
""")
    assert page["none"] == {"card": False, "host": False}
    one = page["one"]
    assert one["count"] == 1 and one["title"] == "Running low" and one["badge"] == "1" and not one["all"]
    assert one["row"] == {"name": "Sunlu PLA Black", "meta": ["Spool 12", "35 g left", "Dry shelf"], "stock": "Last one", "badge": True}
    assert one["swatch"].strip() == "#111111"
    assert one["beforeTiles"] is True
    assert page["three"] == [
        {"name": "A", "meta": ["Spool 3", "20 g left", "Rack 1"], "stock": "2 more in stock", "badge": False},
        {"name": "B", "meta": ["Spool 4", "60 g left"], "stock": "1 more in stock", "badge": False},
        {"name": "C", "meta": ["Spool 5", "90 g left", "Rack 2"], "stock": "Last one", "badge": True}]
    assert page["threeBadge"] == "3"


@pytest.mark.parametrize("n", [5, 7])
def test_five_rows_and_a_button_for_the_rest_which_opens_the_full_list_at_its_address(hub_stub, tmp_path, n):
    app, _ = hub_stub
    app.state["low"] = {"threshold_g": 120, "spools": _spools(n, last_one=True, in_stock=0)}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await cardIn();
out.rows = lowRows().length;
const all = $('[data-action="low-show-all"]');
out.button = all ? text(all) : null;
if (all) {
  all.click();
  const dlg = await until(() => $("dialog[open] .low__list"), "the dialog");
  out.hash = location.hash;
  const d = $("dialog[open]");
  out.dialog = { title: text($(".dialog__title", d)), rows: $$(".low__row", d).length, foot: text($(".low__foot", d)), link: $(".low__foot a", d).getAttribute("href"),
                 last: $$(".low__row .status", d).map(text), close: text($('[data-action="confirm"]', d)) };
  $('[data-action="confirm"]', d).click();
  await until(() => !$("dialog[open]"), "the dialog to close");
  await sleep(100);
  out.after = { hash: location.hash, focus: document.activeElement.matches('[data-action="low-show-all"]') };
  // the address opens it again, also from outside (an alert's action)
  location.hash = "#overview/running-low";
  await until(() => $("dialog[open] .low__list"), "the dialog by its address");
  out.byAddress = $$("dialog[open] .low__row").length;
  $("dialog[open] .low__foot a").click();
  await sleep(500);
  out.link = { hash: location.hash, open: !!$("dialog[open]") };
}
""")
    assert page["rows"] == 5
    if n == 5:
        assert page["button"] is None
        return
    assert page["button"] == "Show all 7"
    assert page["hash"] == "#overview/running-low"
    d = page["dialog"]
    assert d["title"] == "Running low" and d["rows"] == 7 and d["foot"].startswith("Spools at or under 120 g that are opened.") and d["link"] == "#settings/alerts"
    assert d["last"] == ["Last one"] and d["close"] == "Close"
    assert page["after"] == {"hash": "#overview", "focus": True}
    assert page["byAddress"] == 7 and page["link"] == {"hash": "#settings/alerts", "open": False}


def test_the_card_is_left_out_when_the_hub_cannot_say_and_the_dialog_says_why(hub_stub, tmp_path):
    app, _ = hub_stub
    app.state["low"] = {"threshold_g": 150, "spools": _spools(2)}
    app.state["fail"] = {"spools/low": 500}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
out.card = !!card();
location.hash = "#overview/running-low";
await until(() => $("dialog[open] .error-state"), "the error state");
out.error = { title: text($("dialog[open] .error-state__title")), text: text($("dialog[open] .error-state__text")) };
await stub({ fail: {} });
$("dialog[open] [data-action=try-again]").click();
await until(() => $("dialog[open] .low__row"), "the rows after Try again");
out.rows = $$("dialog[open] .low__row").length;
""")
    assert page["card"] is False
    assert page["error"] == {"title": "Could not read what is running low.", "text": "The stub says no."}
    assert page["rows"] == 2


def test_the_storage_row_says_how_full_the_hub_is_and_the_fix_opens_the_panel(hub_stub, tmp_path, monkeypatch):
    """The row is the Hub's own check row (status key hub.storage, action storage_use) from the disk alerts.py measures."""
    full_disk(monkeypatch, 91)
    page = drive(hub_stub, tmp_path, HELPERS + r"""
const row = await until(() => storageRow(), "the Storage row");
out.warn = { text: titleOf(row), state: row.dataset.state, status: text($('[data-col="status"]', row)), fix: text($('[data-col="fix"] .btn', row)) };
""")
    assert page["warn"] == {"text": "Storage: 9.0 GB free of 100 GB (91 % used)", "state": "fail", "status": "State: Needs a look", "fix": "Show storage use"}


def test_the_storage_use_panel_loads_shows_each_part_and_says_when_it_cannot_read(hub_stub, tmp_path, monkeypatch):
    full_disk(monkeypatch, 91)
    app, _ = hub_stub
    app.state["storage"] = storage_state("warn", 91.0)
    app.state["delay"] = {"storage-use": 0}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await until(() => storageRow(), "the Storage row");
const keep = (await (await fetch("/setup/api/settings/general")).json()).values["intake.history_keep"] ?? 20;
out.keep = keep;
// the panel loads: the skeleton first
await stub({ delay: { "storage-use": 1.5 } });
$(".btn", storageRow()).click();
await until(() => $("dialog[open] .skeleton"), "the loading skeleton");
out.skeleton = text($("dialog[open] .skeleton .sr"));
out.hash = location.hash;
const d = await until(() => $("dialog[open] .stuse__item") && $("dialog[open]"), "the panel");
out.title = text($(".dialog__title", d));
out.bar = { label: text($(".progress__label", d)), now: $(".progress__track", d).getAttribute("aria-valuenow"), line: text($(".stuse__line", d)) };
out.items = $$(".stuse__item", d).map((i) => ({ title: text($(".stuse__title", i)), size: text($(".stuse__size", i)), where: text($(".stuse__where", i)),
  link: $(".stuse__where a", i) && $(".stuse__where a", i).getAttribute("href") }));
$('[data-action="confirm"]', d).click();
await until(() => !$("dialog[open]"), "the panel to close");
await sleep(150);
out.after = location.hash;
// Open Backups goes there and closes the panel
$(".btn", storageRow()).click();
await until(() => $("dialog[open] .stuse__item"), "the panel again");
$("dialog[open] .stuse__where a.btn").click();
await sleep(500);
out.backups = { hash: location.hash, open: !!$("dialog[open]") };
// the panel cannot read: the error state with Try again
location.hash = "#overview";
await sleep(300);
await stub({ delay: {}, fail: { "storage-use": 500 } });
location.hash = "#overview/storage-use";
await until(() => $("dialog[open] .error-state"), "the error state");
out.error = { title: text($("dialog[open] .error-state__title")), text: text($("dialog[open] .error-state__text")) };
await stub({ fail: {} });
$("dialog[open] [data-action=try-again]").click();
await until(() => $("dialog[open] .stuse__item"), "the parts after Try again");
out.retry = $$("dialog[open] .stuse__item").length;
""")
    assert page["skeleton"] == "Loading Storage use…" and page["hash"] == "#overview/storage-use" and page["title"] == "Storage use"
    assert page["bar"] == {"label": "The Hub's disk", "now": "91", "line": "9.0 GB free of 100 GB (91 % used)"}
    keep = page["keep"]
    assert page["items"] == [
        {"title": "Backups", "size": "4.2 GB", "where": "Open Backups", "link": "#settings/backups"},
        {"title": "Photos", "size": "310 MB", "where": f"Recently added keeps the last {keep}", "link": None},
        {"title": "Label Reader", "size": "1.9 GB", "where": "Settings > Label Reader", "link": "#settings/label-reader"},
        {"title": "Events and logs", "size": "52 MB", "where": "", "link": None}]
    assert page["after"] == "#overview" and page["backups"] == {"hash": "#settings/backups", "open": False}
    assert page["error"] == {"title": "Could not read the storage use.", "text": "The stub says no."} and page["retry"] == 4


def test_an_alert_s_action_opens_its_place_over_overview_and_a_phone_gets_a_sheet(hub_stub, tmp_path):
    app, _ = hub_stub
    app.state["low"] = {"threshold_g": 150, "spools": _spools(2)}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await stub({ events: [ev(1, "storage.low", { severity: "warn", subject: null, data: { free: 9e9, total: 100e9, percent: 91 }, action: { place: "storage-use" } }),
  ev(2, "spool.low", { severity: "warn", subject: { type: "spool", id: "7", name: "Spool 7" }, data: { filament: "PolyTerra PLA", spool: 7, grams: 80, others: 1 }, action: { place: "running-low" } })] });
await SW_ALERTS.poll();
await until(() => $$(".alert-host .banner").length === 2, "the banners");
const act = (label) => $$(".alert-host .banner a.btn").find((a) => text(a) === label);
act("Show storage use").click();
const sheet = await until(() => $("dialog.sheet[open] .stuse__item") && $("dialog.sheet[open]"), "the sheet");
out.sheet = { hash: location.hash, title: text($(".sheet__title", sheet)), dialog: !!$("dialog.dialog[open]"), inView: sheet.getBoundingClientRect().right <= innerWidth + 1 };
$(".sheet__head [data-action=close]", sheet).click();
await until(() => !$("dialog[open]"), "the sheet to close");
await sleep(150);
out.after = location.hash;
act("Show running low").click();
await until(() => $("dialog[open] .low__list"), "the list");
out.low = { hash: location.hash, rows: $$("dialog[open] .low__row").length };
""", width=390)
    assert page["sheet"] == {"hash": "#overview/storage-use", "title": "Storage use", "dialog": False, "inView": True}
    assert page["after"] == "#overview" and page["low"] == {"hash": "#overview/running-low", "rows": 2}


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("look", LOOKS)
def test_the_card_the_row_and_the_panel_read_in_each_look(hub_stub, tmp_path, monkeypatch, look, width):
    full_disk(monkeypatch, 91)
    app, _ = hub_stub
    app.state["storage"] = storage_state("warn", 91.0)
    long = "A very long filament name for the widest spools that anyone ever put on a shelf in the workshop"
    app.state["low"] = {"threshold_g": 150, "spools": [spool(i, 30 + i, filament=long, location="Storage box 12 behind the printer") for i in range(1, 8)]}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
const measure = (root, label) => {
  const out1 = [];
  for (const el of $$(".low__name, .low__meta > span, .low__stock, .stuse__title, .stuse__size, .stuse__where, .stuse__line", root)) {
    if (!shown(el) || !el.textContent.trim()) continue;
    const cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4, box = el.getBoundingClientRect(), item = el.closest(".low__row, .stuse__item, .stuse__fs");
    out1.push({ label, text: el.textContent.trim().slice(0, 30), w: Math.round(box.width), lines: Math.round(box.height / lh), inside: !item || (box.right <= item.getBoundingClientRect().right + 1 && box.left >= item.getBoundingClientRect().left - 1) });
  }
  return out1;
};
await cardIn();
await until(() => storageRow(), "the Storage row");
out.card = measure(card(), "card");
const c = card().getBoundingClientRect();
out.cardBox = [Math.round(c.left), Math.round(c.right), innerWidth];
out.row = (() => { const r = $(".coll--checks .coll__item[data-state=fail]"); const b = $(".btn", storageRow()).getBoundingClientRect(); const i = storageRow().getBoundingClientRect(); return { inside: b.right <= i.right + 1 && b.left >= i.left - 1, w: Math.round(b.width) }; })();
out.page1 = pageW();
$('[data-action="low-show-all"]').click();
const d1 = await until(() => $("dialog[open] .low__row") && $("dialog[open]"), "the list");
out.list = measure(d1, "list");
const b1 = d1.getBoundingClientRect();
out.listBox = [Math.round(b1.left), Math.round(b1.right), Math.round(b1.top), Math.round(b1.bottom), innerWidth, innerHeight];
$('[data-action="confirm"]', d1).click();
await until(() => !$("dialog[open]"), "close");
$(".btn", storageRow()).click();
const d2 = await until(() => $("dialog[open] .stuse__item") && $("dialog[open]"), "the panel");
out.panel = measure(d2, "panel");
const b2 = d2.getBoundingClientRect();
out.panelBox = [Math.round(b2.left), Math.round(b2.right), innerWidth];
out.page2 = pageW();
""", width=width, look=look)
    seen = page["card"] + page["list"] + page["panel"]
    assert {c["label"] for c in seen} == {"card", "list", "panel"}
    bad = [(c["label"], c["text"], c["w"], c["lines"]) for c in seen if c["lines"] > 3 or (c["w"] < 60 and c["lines"] > 1)]
    assert not bad, (look, width, "a text squeezed to a sliver or wrapped past three lines", bad)
    assert all(c["inside"] for c in seen), (look, width, [c for c in seen if not c["inside"]])
    assert page["row"]["inside"] and page["row"]["w"] >= 32, page["row"]
    assert page["page1"]["sw"] <= page["page1"]["cw"] and page["page2"]["sw"] <= page["page2"]["cw"], (look, width, "the page scrolls sideways")
    assert page["cardBox"][0] >= 0 and page["cardBox"][1] <= page["cardBox"][2] + 1
    assert page["listBox"][0] >= 0 and page["listBox"][1] <= page["listBox"][4] + 1 and page["listBox"][2] >= 0, page["listBox"]
    assert page["panelBox"][0] >= 0 and page["panelBox"][1] <= page["panelBox"][2] + 1, page["panelBox"]
