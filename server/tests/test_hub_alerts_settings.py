"""EA6 phase A, Settings > Alerts on the Hub page (03 10.13): the eight switches, last-spool-only, Running low under, Storage warning at,
one Save ("Saved: <field names>."), the unsaved-changes guard, and the part "On this device" (the browser switch kept in this browser with
its Blocked and cannot-show states, Send a test alert, Recent alerts), in a real headless browser. The Hub is the stub of
hub_alerts_stub.py (api/alerts, settings/alerts and alerts/test are the server step's); the group is registered by the page-side stand-in
of the later mount. The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import pytest

from hub_alerts_stub import KEYS, T, alerts_state, drive, hub_app, hub_stub  # noqa: F401

LOOKS = ["console", "workbench", "palette", "panes"]

HELPERS = r"""
const group = () => $("#set-alerts");
const open = async () => { location.hash = "#settings/alerts"; await until(() => $("#set-alerts"), "the Alerts group"); await sleep(400); };
const sw = (key) => group().elements[key];
const labelOf = (key) => text($(".toggle__label", sw(key).closest(".toggle")));
const field = (key) => sw(key).closest(".field");
const err = (key) => { const e = $(".field__error", field(key)); return e && !e.hidden ? text(e) : null; };
const setField = (key, value) => { const c = sw(key); c.value = value; c.dispatchEvent(new Event("input", { bubbles: true })); c.dispatchEvent(new Event("change", { bubbles: true })); };
const flip = (key) => { sw(key).click(); };
const dirty = () => ({ form: group().dataset.state || null, link: shown($('.subnav__link[data-id="alerts"] .subnav__dirty')), foot: shown($("#set-alerts .group__dirty")) });
const result = () => text($("#set-alerts .group__foot .result__text"));
const unlockAll = async () => { unlock(); await until(() => $('.settings__group[data-id="backups"] :is(.coll, p.muted, .result[data-state])'), "the backups list"); };
const device = () => $("#set-alerts .alerts__device");
const devNote = () => text($(".alerts__state", device()));
const notifySwitch = () => $(".toggle__input", device());
"""


def test_the_group_is_fourth_and_reads_the_hub_s_alert_settings(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
out.order = $$(".subnav__link").map((a) => a.dataset.id);
out.title = text($(".group__title", group()));
out.desc = text($(".group__desc", group()));
out.badge = text($(".alerts__count", group()));
out.switches = ["runout", "paused", "failed", "printer_error", "finished", "storage", "running_low", "last_spool_only", "device_down"].map((k) => [k, labelOf(k), sw(k).checked, text($(".toggle__word", sw(k).closest(".toggle")))]);
out.sub = group().querySelector(".alerts__sub") === sw("last_spool_only").closest(".toggle");
out.hint = text($(".toggle__hint", sw("device_down").closest(".toggle")));
out.numbers = ["running_low_g", "storage_warn_percent"].map((k) => [text($(".field__label", field(k))), sw(k).value, text($(".field__unit", field(k))), text($(".field__hint", field(k)))]);
out.save = text($("[type=submit]", group()));
out.deviceHeading = text($(".settings__heading", device()));
out.device = [text($(".toggle__label", device())), notifySwitch().checked, text($(".toggle__hint", device())), $$(".actions .btn", device()).map(text)];
out.list = text($('.settings__row[data-id="alerts"] .settings__state'));
out.dirty = dirty();
out.reads = (await calls("alerts")).length;
""")
    assert page["order"][:5] == ["appearance", "general", "storage", "alerts", "label-reader"]
    assert page["title"] == "Alerts" and page["desc"] == "What Spoolwarden warns you about, and where." and page["badge"] == "6 of 8 on"
    assert page["switches"] == [["runout", "Filament ran out", True, "On"], ["paused", "Print paused", True, "On"], ["failed", "Print failed or stopped", True, "On"],
                                ["printer_error", "Printer error", True, "On"], ["finished", "Print finished", False, "Off"], ["storage", "Storage almost full", True, "On"],
                                ["running_low", "Spool running low", True, "On"],
                                ["last_spool_only", "Only when it is the last spool of that filament", False, "Off"], ["device_down", "Device stopped answering", False, "Off"]]
    assert page["sub"] is True and page["hint"] == "A Weigh Station or a printer stopped answering."
    assert page["numbers"] == [["Running low under", "150", "g", "Opened spools at or under this are listed as running low."],
                               ["Storage warning at", "85", "% used", "The Hub treats 95 % used, and always less than 1 GB free, as bad."]]
    assert page["save"] == "Save alerts" and page["deviceHeading"] == "On this device"
    assert page["device"][1:] == [False, "Shown while a Spoolwarden tab is open in this browser. With the tab in the background they can arrive up to a minute late.",
                                  ["Send a test alert", "Recent alerts"]]
    assert page["list"] == "6 of 8 on" and page["dirty"] == {"form": None, "link": False, "foot": False} and page["reads"] == 1


def test_one_save_sends_the_whole_group_and_says_which_fields_were_saved(hub_stub, tmp_path):
    app, _ = hub_stub
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
await unlockAll();
flip("runout"); flip("finished"); flip("last_spool_only"); setField("running_low_g", "200");
await until(() => group().dataset.state === "dirty", "the dirty state");
out.dirty = dirty();
$("#set-alerts [type=submit]").click();
await until(() => result() && result().startsWith("Saved"), "the saved result");
out.saved = result();
await sleep(500);
out.calls = (await calls("settings/alerts")).map((c) => c.body);
out.after = { dirty: dirty(), runout: sw("runout").checked, finished: sw("finished").checked, last: sw("last_spool_only").checked, low: sw("running_low_g").value, badge: text($(".alerts__count", group())),
              result: result() };
// Enter with nothing changed
$("#set-alerts [type=submit]").click();
out.nothing = await until(() => { const r = result(); return r && r !== out.saved && r !== out.after.result ? r : null; }, "Nothing changed");
out.calls2 = (await calls("settings/alerts")).length;
""")
    assert page["dirty"] == {"form": "dirty", "link": True, "foot": True}
    assert page["saved"] == "Saved: Filament ran out, Print finished, Only when it is the last spool of that filament, Running low under."
    (sent,) = page["calls"]
    assert sent["code"] == "12345678" and sent["running_low_g"] == 200 and sent["storage_warn_percent"] == 85 and sent["last_spool_only"] is True
    assert [(t["key"], t["on"]) for t in sent["types"]] == [("runout", False), ("paused", True), ("failed", True), ("printer_error", True), ("finished", True),
                                                          ("storage", True), ("running_low", True), ("device_down", False)]
    after = page["after"]
    assert after["dirty"] == {"form": None, "link": False, "foot": False} and (after["runout"], after["finished"], after["last"], after["low"]) == (False, True, True, "200")
    assert after["badge"] == "6 of 8 on" and page["nothing"] == "Nothing changed." and page["calls2"] == 1
    assert app.state["alerts"]["running_low_g"] == 200


def test_a_value_out_of_range_is_refused_at_its_field_and_so_is_the_hub_s_refusal(hub_stub, tmp_path):
    app, _ = hub_stub
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
await unlockAll();
setField("running_low_g", "5"); setField("storage_warn_percent", "95");
$("#set-alerts [type=submit]").click();
await sleep(500);
out.client = { low: err("running_low_g"), warn: err("storage_warn_percent"), sent: (await calls("settings/alerts")).length };
setField("running_low_g", "2000"); setField("storage_warn_percent", "94");
await stub({ refuse: { error: "running_low_g must be at most 1500", errors: { running_low_g: "running_low_g must be at most 1500" }, field: "running_low_g" } });
$("#set-alerts [type=submit]").click();
await until(() => $("#set-alerts .group__foot .result[data-state=bad]"), "the refusal");
out.hub = { low: err("running_low_g"), warn: err("storage_warn_percent"), result: text($("#set-alerts .group__foot .result")), dirty: dirty().form, value: sw("running_low_g").value };
""")
    assert page["client"] == {"low": T("alerts_error_whole", low=10, high=2000), "warn": T("alerts_error_whole", low=1, high=94), "sent": 0}
    assert page["hub"]["low"] == "Must be at most 1500." and page["hub"]["warn"] is None
    assert "Must be at most 1500." in page["hub"]["result"] and page["hub"]["dirty"] == "dirty" and page["hub"]["value"] == "2000"


def test_leaving_with_unsaved_alert_changes_asks_first(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
flip("finished");
await until(() => group().dataset.state === "dirty", "the dirty state");
location.hash = "#devices";
const dlg = await until(() => $("dialog[open]"), "the leave question");
out.leave = { title: text($(".dialog__title", dlg)), body: text($(".dialog__text", dlg)), stayed: location.hash.startsWith("#settings") };
$('[data-action="cancel"]', dlg).click();
await until(() => !$("dialog[open]"), "the question to close");
out.kept = { hash: location.hash, finished: sw("finished").checked, dirty: group().dataset.state };
""")
    assert page["leave"]["title"] == T("common_leave_title") and "Alerts" in page["leave"]["body"] and page["leave"]["stayed"]
    assert page["kept"] == {"hash": "#settings/alerts", "finished": True, "dirty": "dirty"}


@pytest.mark.parametrize("notif,say,hint", [
    ("denied", "Blocked in this browser's settings", "Allow notifications for this address in the browser's site settings, then switch this on again."),
    ("none", "This browser cannot show notifications", "Open the Hub at its public address, which has a certificate this browser trusts.")])
def test_the_browser_switch_says_when_it_is_blocked_or_cannot_show_notifications(hub_stub, tmp_path, notif, say, hint):
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
out.start = { on: notifySwitch().checked, note: devNote() };
notifySwitch().click();
await sleep(500);
out.after = { on: notifySwitch().checked, note: devNote(), flag: localStorage.getItem("spoolwarden.alerts.notifications"), dialog: !!$("dialog[open]") };
""", notif=notif)
    assert page["start"] == {"on": False, "note": f"{say} {hint}"}
    assert page["after"] == {"on": False, "note": f"{say} {hint}", "flag": None, "dialog": False}


def test_the_browser_switch_asks_the_browser_needs_no_code_and_is_kept_in_the_browser(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
out.locked = SW.lock.state;
// the browser says no when asked: the switch stays off and the words say why
window.__notifAnswer = "denied";
notifySwitch().click();
await until(() => devNote(), "the blocked words");
out.denied = { on: notifySwitch().checked, note: devNote(), flag: localStorage.getItem("spoolwarden.alerts.notifications") };
// the browser allows it (asked once more): on, kept here, nothing sent to the Hub, no setup code asked
window.__perm = "default"; window.__notifAnswer = "granted";
notifySwitch().click();
await until(() => notifySwitch().checked && text($(".result__text", device())), "the switch on");
out.on = { word: text($(".toggle__word", device())), flag: localStorage.getItem("spoolwarden.alerts.notifications"), result: text($(".result__text", device())), note: devNote(),
           dialog: !!$("dialog[open]"), posts: (await calls()).filter((c) => c.body).length, dirty: dirty().form };
notifySwitch().click();
await until(() => !notifySwitch().checked && (text($(".result__text", device())) || "").includes("off"), "the switch off");
out.off = { flag: localStorage.getItem("spoolwarden.alerts.notifications"), result: text($(".result__text", device())) };
""", notif="default")
    assert page["locked"] == "locked"
    assert page["denied"] == {"on": False, "flag": None, "note": "Blocked in this browser's settings Allow notifications for this address in the browser's site settings, then switch this on again."}
    assert page["on"] == {"word": "On", "flag": "1", "result": "Notifications are on in this browser.", "note": "", "dialog": False, "posts": 0, "dirty": None}
    assert page["off"] == {"flag": None, "result": "Notifications are off in this browser."}


def test_send_a_test_alert_asks_the_hub_with_the_browser_id_and_it_arrives_here_and_recent_alerts_opens_the_list(hub_stub, tmp_path):
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
notifySwitch().click();
await until(() => notifySwitch().checked, "the switch on");
const test = $('[data-action="alerts-test"]', device());
test.click();
await until(() => window.__notes.length, "the browser notification");
await until(() => $(".toasts .toast"), "the toast");
const posts = await calls("alerts/test");
out.test = { body: posts.map((c) => c.body), id: localStorage.getItem("spoolwarden.browser"), result: text($(".result__text", device())),
             note: window.__notes.map((n) => [n.title, n.body]), toast: text($(".toast__text")) };
$('[data-action="alerts-recent"]', device()).click();
const dlg = await until(() => $("dialog[open] .alert-list"), "the Alerts list");
out.recent = { title: text($(".dialog__title", $("dialog[open]"))), empty: text($(".alert-list__empty", dlg)) };
""", notif="granted")
    t = page["test"]
    assert t["body"] == [{"client": t["id"]}] and t["id"] and t["result"] == T("settings_alerts_sent")
    assert t["note"] == [["Test alert", "This is a test from the Hub."]] and t["toast"] == "Test alert"
    assert page["recent"] == {"title": "Alerts", "empty": "No alerts in the last 7 days."}


def test_the_test_button_is_hidden_when_the_hub_has_no_such_route(hub_stub, tmp_path):
    app, _ = hub_stub
    app.state["fail"] = {"alerts/test": 404}
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
const test = $('[data-action="alerts-test"]', device());
test.click();
await until(() => test.hidden, "the button to go");
out.hidden = { hidden: test.hidden, result: text($(".result__text", device())) };
""")
    assert page["hidden"] == {"hidden": True, "result": None}


@pytest.mark.parametrize("width", [1280, 1776, 390])
@pytest.mark.parametrize("look", LOOKS)
def test_the_group_reads_in_each_look_and_panes_does_not_squeeze_it(hub_stub, tmp_path, look, width):
    page = drive(hub_stub, tmp_path, HELPERS + r"""
await open();
const g = group().getBoundingClientRect();
out.group = [Math.round(g.left), Math.round(g.right), Math.round(g.width), innerWidth];
out.toggles = $$(".toggle", group()).map((t1) => { const r = t1.getBoundingClientRect(); const l = $(".toggle__label", t1).getBoundingClientRect(); return { w: Math.round(r.width), lines: Math.round(l.height / (parseFloat(getComputedStyle($(".toggle__label", t1)).lineHeight) || 20)), inside: r.right <= g.right + 1 && r.left >= g.left - 1 }; });
out.fields = ["running_low_g", "storage_warn_percent"].map((k) => { const r = sw(k).getBoundingClientRect(); return { w: Math.round(r.width), inside: r.right <= g.right + 1 }; });
const f = $(".group__foot [type=submit]", group()).getBoundingClientRect();
out.save = { inside: f.right <= innerWidth + 1 && f.left >= 0, w: Math.round(f.width) };
out.buttons = $$(".alerts__device .actions .btn", group()).map((b) => { const r = b.getBoundingClientRect(); return { inside: r.right <= g.right + 1, h: Math.round(r.height) }; });
// the words under the browser switch, in the blocked state, wrap inside the group
const note = $(".alerts__state", device());
note.replaceChildren(Object.assign(document.createElement("b"), { textContent: "Blocked in this browser's settings" }), " Allow notifications for this address in the browser's site settings, then switch this on again.");
await sleep(100);
const n = note.getBoundingClientRect();
out.note = { inside: n.right <= g.right + 1 && n.left >= g.left - 1, w: Math.round(n.width) };
out.page = pageW();
""", width=width, look=look)
    left, right, w, vw = page["group"]
    assert left >= 0 and right <= vw + 1, page["group"]
    floor = 480 if look == "panes" and width >= 1280 else 300
    assert w >= floor, (look, width, page["group"], "the group is squeezed")
    assert all(t["inside"] and t["lines"] <= 2 for t in page["toggles"]), (look, width, page["toggles"])
    assert all(f["inside"] and f["w"] >= 100 for f in page["fields"]), (look, width, page["fields"])
    assert page["save"]["inside"] and page["save"]["w"] >= 80
    assert all(b["inside"] and b["h"] <= 48 for b in page["buttons"]), (look, width, page["buttons"])
    assert page["note"]["inside"] and page["note"]["w"] >= 150
    assert page["page"]["sw"] <= page["page"]["cw"], (look, width, "the page scrolls sideways")


def test_the_phone_list_says_how_many_alerts_are_on(hub_stub, tmp_path):
    app, _ = hub_stub
    app.state["alerts"] = alerts_state(types=[{"key": k, "title": k, "on": k in ("runout", "finished")} for k in KEYS])
    page = drive(hub_stub, tmp_path, HELPERS + r"""
location.hash = "#settings";
await until(() => $('.settings__row[data-id="alerts"] .settings__state') && text($('.settings__row[data-id="alerts"] .settings__state')), "the state");
out.rows = $$(".settings__row").map((r) => [r.dataset.id, text($(".settings__name", r))]).slice(2, 5);
out.state = text($('.settings__row[data-id="alerts"] .settings__state'));
""", width=390)
    assert page["rows"] == [["storage", "Storage locations"], ["alerts", "Alerts"], ["label-reader", "Label Reader"]] and page["state"] == "2 of 8 on"
