"""EA6 phase A, the alert banners on the Hub page (03 2.8): the banner host mounted once in the page frame above the page header and
below the "Cannot reach the Hub" banner, the toast with its action for an alert that arrives while the page is open, `G events` every
10 s with the browser id, and the places an alert's action goes to. The Hub is the stub of hub_alerts_stub.py (the server step is not in
this tree); the page is the real Hub page with the new modules loaded. The same skip rules as the page audit: no Node 22 or no browser is
a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import pytest

from hub_alerts_stub import drive, hub_app, hub_stub  # noqa: F401

LOOKS = ["console", "workbench", "palette", "panes"]


def test_the_host_is_mounted_once_above_the_page_header_and_below_the_unreachable_banner(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, r"""
const main = $("main");
out.first = [...main.children].slice(0, 2).map((c) => c.className.split(" ")[0]);
out.hosts = $$(".alert-host").length;
await stub({ events: [ev(1, "print.failed", { severity: "bad", data: { job: "a.3mf", percent: 12, reason: "cancelled" } })] });
await SW_ALERTS.poll();
await until(() => $(".alert-host .banner"), "the banner");
out.above = $(".alert-host").getBoundingClientRect().bottom <= $(".page-head").getBoundingClientRect().top + 1;
hubJobs().down();
await sleep(100);
out.withDown = [...main.children].slice(0, 3).map((c) => c.className.split(" ")[0]);
hubJobs().up();
// the host stays through the sections: one element, the same banner
const host = $(".alert-host"), banner = $(".alert-host .banner");
out.kept = [];
for (const hash of ["#printers", "#settings/general", "#devices", "#overview"]) {
  location.hash = hash;
  await sleep(500);
  out.kept.push([hash, $(".alert-host") === host, $(".alert-host .banner") === banner, $$(".alert-host").length]);
}
""")
    assert page["first"] == ["alert-host", "page"] and page["hosts"] == 1 and page["above"]
    assert page["withDown"] == ["banner", "alert-host", "page"]
    assert page["kept"] == [[h, True, True, 1] for h in ("#printers", "#settings/general", "#devices", "#overview")]


def test_a_new_alert_shows_a_toast_with_its_action_once_and_history_shows_none(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, r"""
// an alert from before the page opened is history: a banner, no toast
out.toastsAtOpen = $$(".toasts .toast").length;
await stub({ events: [ev(1, "print.runout", { at: new Date(Date.now() - 3600e3).toISOString() })] });
await SW_ALERTS.poll();
await sleep(200);
out.history = { banners: $$(".alert-host .banner").length, toasts: $$(".toasts .toast").length };
// a new one: a banner and one toast with its action, which goes to the printer
await stub({ events: [ev(1, "print.runout", { at: new Date(Date.now() - 3600e3).toISOString() }), ev(2, "print.paused", { severity: "warn" })] });
await SW_ALERTS.poll();
await until(() => $(".toasts .toast"), "the toast");
const toast = $(".toasts .toast");
out.toast = { text: text($(".toast__text", toast)), action: text($(".btn", toast)), count: $$(".toasts .toast").length };
await SW_ALERTS.poll(); await SW_ALERTS.poll();
out.once = $$(".toasts .toast").length;
out.banners = $$(".alert-host .banner").map((b) => text($(".banner__text b", b)));
out.href = $$(".alert-host .banner a.btn").map((a) => a.getAttribute("href"));
$(".btn", toast).click();
await sleep(300);
out.hash = location.hash;
""")
    assert page["toastsAtOpen"] == 0 and page["history"] == {"banners": 1, "toasts": 0}
    assert page["toast"] == {"text": "Workshop X1 is paused", "action": "Show", "count": 1} and page["once"] == 1
    assert page["banners"] == ["Workshop X1 is paused", "Filament ran out on Workshop X1"]
    assert page["href"] == ["#printers/00M00A000000001"] * 2 and page["hash"] == "#printers/00M00A000000001"


def test_events_are_read_every_10_seconds_with_the_browser_id(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, r"""
await sleep(10600);
const all = await calls("events");
out.queries = all.map((c) => c.query);
out.client = localStorage.getItem("spoolwarden.browser");
out.gap = all.length > 1 ? (all[all.length - 1].at - all[all.length - 2].at) : null;
""")
    first, later = page["queries"][0], page["queries"][1:]
    assert page["client"] and len(page["client"]) >= 8
    assert "since_at=" in first and "since=" not in first.replace("since_at=", "")
    assert all(f"alert=1&wait=0&client={page['client']}" in q for q in page["queries"])
    assert later and all(q.startswith("since=") for q in later), page["queries"]
    assert len(page["queries"]) >= 2 and 9 <= page["gap"] <= 12, page


def test_the_actions_go_to_the_page_s_own_addresses(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, r"""
await stub({ events: [
  ev(1, "storage.low", { severity: "warn", subject: null, data: { free: 9e9, total: 100e9, percent: 91 }, action: { place: "storage-use" } }),
  ev(2, "spool.low", { severity: "warn", subject: { type: "spool", id: "7", name: "Spool 7" }, data: { filament: "PolyTerra PLA", spool: 7, grams: 80, others: 0 }, action: { place: "running-low" } }),
  ev(3, "device.down", { severity: "bad", subject: { type: "device", id: "d1", name: "Bench scale" }, action: { place: "devices" } })] });
await SW_ALERTS.poll();
await until(() => $$(".alert-host .banner").length === 2, "the banners");
out.shown = $$(".alert-host .banner a.btn").map((a) => [text(a), a.getAttribute("href")]);
const more = $(".alert-host .alert-more button");
out.more = text(more);
more.click();
const dlg = await until(() => $("dialog[open] .alert-list"), "the Alerts list");
out.list = $$(".alert-row", dlg).map((r) => [text($(".alert-row__title", r)), $("a.btn", r) && $("a.btn", r).getAttribute("href")]);
""")
    assert page["shown"] == [["Open Devices", "#devices"], ["Show running low", "#overview/running-low"]]
    assert page["more"] == "1 more alert"
    assert sorted(x[1] for x in page["list"]) == ["#devices", "#overview/running-low", "#overview/storage-use"]


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("look", LOOKS)
def test_the_banners_read_in_each_look(hub_stub, tmp_path, look, width):
    page = drive(hub_stub, tmp_path, r"""
await stub({ events: [ev(1, "print.failed", { severity: "bad", data: { job: "a-very-long-job-name-for-the-wide-print-of-the-month.3mf", percent: 12, reason: "cancelled" } }),
  ev(2, "storage.low", { severity: "warn", subject: null, data: { free: 9e9, total: 100e9, percent: 91 }, action: { place: "storage-use" } }),
  ev(3, "device.down", { severity: "bad", subject: { type: "device", id: "d1", name: "Bench scale" }, action: { place: "devices" } })] });
await SW_ALERTS.poll();
await until(() => $$(".alert-host .banner").length === 2, "the banners");
await sleep(300);
const host = $(".alert-host").getBoundingClientRect(), head = $(".page-head").getBoundingClientRect();
out.rows = $$(".alert-host .banner, .alert-host .alert-more").map((b) => { const r = b.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), Math.round(r.height)]; });
out.above = host.bottom <= head.top + 1;
out.page = pageW();
out.vw = innerWidth;
""", width=width, look=look)
    assert page["above"] and page["page"]["sw"] <= page["page"]["cw"], page
    assert all(0 <= left and right <= page["vw"] + 1 and height > 0 for left, right, height in page["rows"]), page
