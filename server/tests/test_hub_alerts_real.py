"""EA6 phase B: the Hub page's alert places mounted in the real page and answered by the real routes of setup_console/alerts_tab.py
(the same code as the kit routes: alerts_api), in a real headless browser. The wrapper of hub_alerts_stub.py stubs nothing here
(`stubbed` is empty). Events are written by the event store, a failed save and a low spool come from the real Hub, the test alert
arrives once. The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import httpx
import pytest

from filament_kit import alerts, events
from hub_alerts_stub import drive, full_disk, hub_app, hub_stub  # noqa: F401

LOOKS = ["console", "workbench", "palette", "panes"]
HELPERS = r"""
const group = () => $("#set-alerts");
const open = async () => { location.hash = "#settings/alerts"; await until(() => $("#set-alerts"), "the Alerts group"); await sleep(400); };
const sw = (key) => group().elements[key];
const unlockAll = async () => { unlock(); await until(() => $('.settings__group[data-id="backups"] :is(.coll, p.muted, .result[data-state])'), "the backups list"); };
const result = () => text($("#set-alerts .group__foot .result__text"));
const again = async () => { location.hash = "#devices"; await sleep(400); location.hash = "#overview"; await sleep(900); };
const titleOf = (i) => text($(".coll__cell[data-col=title]", i)) || "";
const storageRow = () => $$(".coll--checks .coll__item").find((i) => titleOf(i).startsWith("Storage"));
"""


def real(app):
    app.state["stubbed"] = []


def write_events():
    store = events.store()
    hub = {"type": "hub"}
    store.write("storage.low", hub, hub, {"free": 9_000_000_000, "total": 100_000_000_000, "percent": 91, "direction": "up"}, severity="warn")
    store.write("print.failed", {"type": "printer", "id": "00M00A000000001", "name": "Workshop X1"}, hub,
                {"job": "gear.3mf", "percent": 12, "reason": "cancelled"}, severity="bad")


def low_spools(spoolman_url, grams=(40, 120)):
    with httpx.Client() as c:
        filament = c.get(spoolman_url + "/api/v1/filament").json()[0]["id"]
        for g in grams:
            c.post(spoolman_url + "/api/v1/spool", json={"filament_id": filament, "location": "Rack 1", "remaining_weight": g}).raise_for_status()


def test_events_the_store_wrote_are_banners_with_the_real_words_and_places(hub_stub, tmp_path):
    real(hub_stub[0])
    write_events()
    page = drive(hub_stub, tmp_path, r"""
await until(() => $$(".alert-host .banner").length === 2, "the banners");
out.banners = $$(".alert-host .banner").map((b) => [text($(".banner__text b", b)), $("a.btn", b) && text($("a.btn", b)), $("a.btn", b) && $("a.btn", b).getAttribute("href")]);
out.toasts = $$(".toasts .toast").length;
$$(".alert-host .banner a.btn").find((a) => a.getAttribute("href") === "#overview/storage-use").click();
await until(() => $("dialog[open] .stuse__item"), "the real Storage use panel");
out.panel = { hash: location.hash, title: text($(".dialog__title", $("dialog[open]"))), items: $$(".stuse__item .stuse__title").map(text),
              bar: text($(".progress__label", $("dialog[open]"))) };
""")
    assert page["banners"] == [["Print stopped on Workshop X1", "Open the printer", "#printers/00M00A000000001"],
                               ["Storage on the Hub is almost full", "Show storage use", "#overview/storage-use"]] and page["toasts"] == 0
    assert page["panel"]["hash"] == "#overview/storage-use" and page["panel"]["title"] == "Storage use"
    assert page["panel"]["items"] == ["Backups", "Photos of recently added spools", "Label Reader on this Hub", "Events", "Logs"]
    assert page["panel"]["bar"] == "The Hub's disk"


def test_the_test_alert_arrives_once_and_a_saved_change_is_the_hub_s(hub_stub, tmp_path):
    real(hub_stub[0])
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
await unlockAll();
$('[data-action="alerts-test"]', group()).click();
await until(() => $(".toasts .toast"), "the test alert");
out.toast = text($(".toast__text"));
await SW_ALERTS.poll(); await SW_ALERTS.poll();
out.toasts = $$(".toasts .toast").length;
sw("finished").click(); sw("running_low_g").value = "300"; sw("running_low_g").dispatchEvent(new Event("input", { bubbles: true }));
$("#set-alerts [type=submit]").click();
await until(() => result() && result().startsWith("Saved"), "the saved result");
out.saved = result();
await sleep(600);
out.after = { finished: sw("finished").checked, low: sw("running_low_g").value, badge: text($(".alerts__count", group())) };
// the Hub's refusal of a value: its field and its words
const r = await fetch("/setup/api/settings/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ running_low_g: 5000, code: "12345678" }) });
out.refused = [r.status, await r.json()];
""")
    assert page["toast"] == "Test alert" and page["toasts"] == 1
    assert page["saved"] == "Saved: Print finished, Running low under." and page["after"] == {"finished": True, "low": "300", "badge": "7 of 8 on"}
    status, body = page["refused"]
    assert status == 400 and list(body["errors"]) == ["running_low_g"] and body["field"] == "running_low_g"
    assert alerts.load()["running_low_g"] == 300 and alerts.load()["types"]["finished"] is True


def test_running_low_comes_from_spoolman_and_the_storage_row_from_the_disk(hub_stub, tmp_path, monkeypatch, spoolman_url):
    real(hub_stub[0])
    low_spools(spoolman_url)
    full_disk(monkeypatch)
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await until(() => $(".low"), "the card");
out.card = { title: text($(".low h2")), rows: $$(".low__row").map((r) => [text($(".low__name", r)), $$(".low__meta > span", r).map(text).slice(0, 2)]) };
const row = await until(() => storageRow(), "the Storage row");
out.row = { text: titleOf(row), state: row.dataset.state, fix: text($('[data-col="fix"] .btn', row)) };
$(".btn", row).click();
await until(() => $("dialog[open] .stuse__item"), "the panel");
out.panel = { hash: location.hash, line: text($("dialog[open] .stuse__line")), state: $("dialog[open] .stuse__fs").dataset.state };
""")
    assert page["card"]["title"] == "Running low" and [r[1][1] for r in page["card"]["rows"]] == ["40 g left", "120 g left"]
    assert page["row"]["state"] == "fail" and page["row"]["text"].startswith("Storage: 4.0 GB free of 100 GB (96 % used)")
    assert page["row"]["fix"] == "Show storage use"
    assert page["panel"] == {"hash": "#overview/storage-use", "line": "4.0 GB free of 100 GB (96 % used)", "state": "bad"}


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("look", LOOKS)
def test_the_mounted_page_reads_in_each_look(hub_stub, tmp_path, monkeypatch, spoolman_url, look, width):
    real(hub_stub[0])
    write_events()
    low_spools(spoolman_url, (30, 60, 90, 100, 110, 120, 130))
    full_disk(monkeypatch)
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await until(() => $(".low") && storageRow() && $$(".alert-host .banner").length === 2, "the Overview");
await sleep(300);
out.card = { rows: $$(".low__row").length, all: text($('[data-action="low-show-all"]')) };
out.overview = pageW();
const fix = $(".btn", storageRow()).getBoundingClientRect();
out.fix = { w: Math.round(fix.width), inside: fix.right <= innerWidth + 1 };
out.host = (() => { const h = $(".alert-host").getBoundingClientRect(), p = $(".page-head").getBoundingClientRect(); return h.bottom <= p.top + 1 && h.right <= innerWidth + 1; })();
// the banners are on every section
out.sections = [];
for (const hash of ["#printers", "#devices", "#updates", "#settings/alerts"]) {
  location.hash = hash; await sleep(500);
  out.sections.push([hash, $$(".alert-host .banner").length, pageW().sw <= pageW().cw]);
}
await until(() => $("#set-alerts"), "the group");
const g = group().getBoundingClientRect();
out.group = [Math.round(g.left), Math.round(g.right), Math.round(g.width), innerWidth];
// the unsaved-changes guard
sw("finished").click();
await until(() => group().dataset.state === "dirty", "dirty");
location.hash = "#devices";
const dlg = await until(() => $("dialog[open]"), "the leave question");
out.guard = { title: text($(".dialog__title", dlg)), stayed: location.hash.startsWith("#settings") };
$('[data-action="cancel"]', dlg).click();
""", width=width, look=look)
    assert page["card"] == {"rows": 5, "all": "Show all 7"} and page["overview"]["sw"] <= page["overview"]["cw"] and page["host"]
    assert page["fix"]["inside"] and page["fix"]["w"] >= 32
    assert page["sections"] == [[h, 2, True] for h in ("#printers", "#devices", "#updates", "#settings/alerts")]
    left, right, w, vw = page["group"]
    assert left >= 0 and right <= vw + 1 and w >= (480 if look == "panes" and width >= 1280 else 300), page["group"]
    assert page["guard"]["title"] == "Leave without saving?" or page["guard"]["title"], page["guard"]
    assert page["guard"]["stayed"]
