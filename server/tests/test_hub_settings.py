"""Settings on the Hub page (design 09 S2.19, 03 section 10), in a real headless browser: nine groups in a fixed order with
the sub-navigation, one Save per group that sends its changed keys in one request (N2), the unsaved marks and the leave
guard, the restart question, and on a phone the list of groups and one group at a time. The AUT-5 audit passes on every
group at 320 and 1280 px, light and dark. The page is served with the data of test_hub_page_audit.py. The same skip rules
as the page audit: no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import json
import os

from filament_kit import config, setup_helper, storage

from test_hub_page_audit import _run, hub_app, hub_change  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401

GROUPS = ["appearance", "general", "storage", "label-reader", "backups", "network", "passphrase", "catalog", "voice"]
NAMES = ["Appearance", "General", "Storage locations", "Label Reader", "Backups and restore", "Network and addresses",
         "Web passphrase", "Filament Catalog", "Weigh Station voice"]

PRELUDE = """const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) { for (let i = 0; i < 300; i++) { const v = look(); if (v) return v; await sleep(100); } throw new Error("waited for " + what + "; the page shows: " + document.querySelector("main").innerText.slice(0, 300)); }
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\\s+/g, " ") : null);
const shown = (el) => !!el && el.getClientRects().length > 0;
const loaded = () => until(() => !$(".chip--lock .skeleton__line") && !$('main [aria-busy="true"]:not(button)') && $(".settings__group form, .settings__group section"), "the groups to load");
const type = (form, name, value) => { const c = form.elements[name]; c.value = value; c.dispatchEvent(new Event("input", { bubbles: true })); };
// Unlocking makes the Backups group read its list with the code; a save sent at the same moment would write the lock's
// file at the same time as that read does, which a Windows file system refuses, so the test waits for the list first
const unlock = async () => {
  SW.setLock("unlocked", { code: "__CODE__" });
  await until(() => $('.settings__group[data-id="backups"] :is(.coll, p.muted, .result[data-state])'), "the backups list");
};
location.hash = "#settings";
"""


def _switch_on(*names):
    cfg = config.load()
    cfg["modules"].update({n: True for n in names})
    config.save(cfg)


def test_the_groups_are_in_their_order_and_one_save_sends_the_changed_keys_in_one_request(hub, monkeypatch, tmp_path):
    _switch_on("ai_intake", "local_intake")
    seen: list = []
    real = setup_helper.OPS["general_group"]
    monkeypatch.setitem(setup_helper.OPS, "general_group", lambda req: (seen.append(("group", dict(req["values"]))), real(req))[1])
    monkeypatch.setitem(setup_helper.OPS, "general", lambda req: seen.append(("one", req["key"])) or {"key": req["key"], "restarts": False, "applies": False})
    page = _drive(hub, tmp_path, PRELUDE + """
await loaded();
await unlock();
const out = {};
out.groups = [...document.querySelectorAll(".settings__group")].map((g) => g.dataset.id);
out.nav = [...document.querySelectorAll(".subnav__link")].map((a) => a.childNodes[0].textContent.trim());
out.titles = [...document.querySelectorAll(".group__head .group__title")].map(text);
out.saves = [...document.querySelectorAll(".settings__group form .group__foot [type=submit]")].map(text);
// Storage locations: the list is edited as a whole (R79); a move is a change, and one Save sends the list (setup_storage.js)
const form = $("#set-storage");
await until(() => $('[aria-label^="Move Rack 1 "]'), "the locations");
$('[aria-label^="Move Rack 1 "]:not([aria-disabled="true"])').click();
await until(() => form.dataset.state === "dirty", "the dirty state");
const link = $('.subnav__link[data-id="storage"] .subnav__dirty');
out.dirty = { link: shown(link) && text(link), title: shown($("#set-storage .settings__dirty")), foot: text($("#set-storage .group__dirty")), other: shown($('.subnav__link[data-id="general"] .subnav__dirty')) };
$("#set-storage [type=submit]").click();
await until(() => $("#set-storage") !== form && text($("#set-storage .group__foot .result__text")), "the saved result");
out.saved = text($("#set-storage .group__foot .result__text"));
out.after = { dirty: $("#set-storage").dataset.state || null, link: shown($('.subnav__link[data-id="storage"] .subnav__dirty')) };
// Enter with nothing changed
$("#set-storage [type=submit]").click();
out.nothing = await until(() => { const r = text($("#set-storage .group__foot .result__text")); return r && r !== out.saved ? r : null; }, "Nothing changed");
// the leave guard: General is edited, then another section is asked for
const general = $("#set-general");
type(general, "server_name", "Garage hub");
await until(() => general.dataset.state === "dirty", "General dirty");
location.hash = "#devices";
const dlg = await until(() => $("dialog[open]"), "the leave question");
out.leave = { title: text($(".dialog__title", dlg)), body: text($(".dialog__text", dlg)), stayed: location.hash.startsWith("#settings") };
$('[data-action="cancel"]', dlg).click();
await until(() => !$("dialog[open]"), "the question to close");
out.kept = { hash: location.hash, value: $("#set-general").elements.server_name.value, dirty: $("#set-general").dataset.state };
// Label Reader: a new model restarts the Hub, so Save asks first; Cancel sends nothing
const reader = $("#set-label-reader");
type(reader, "model", "claude-example");
await until(() => reader.dataset.state === "dirty", "Label Reader dirty");
$("#set-label-reader [type=submit]").click();
const ask = await until(() => $("dialog[open]"), "the restart question");
out.restart = { title: text($(".dialog__title", ask)), body: text($(".dialog__text", ask)), buttons: [...ask.querySelectorAll(".dialog__foot .btn")].map(text) };
$('[data-action="cancel"]', ask).click();
await until(() => !$("dialog[open]"), "the restart question to close");
out.cancelled = $("#set-label-reader").dataset.state;
return out;
""")
    assert page["groups"] == GROUPS and page["nav"] == NAMES and page["titles"] == NAMES
    assert page["saves"][:2] == [T("settings_general_save"), T("settings_storage_save")] and T("settings_reader_save") in page["saves"]
    assert page["dirty"] == {"link": T("common_unsaved"), "title": True, "foot": T("common_unsaved_changes"), "other": False}
    # the storage list does not go through settings/general any more: it is saved whole by setup_storage.js (a stub until SL2)
    assert seen == [], seen
    assert page["saved"] == T("settings_storage_saved")
    assert page["after"] == {"dirty": None, "link": False}
    assert page["nothing"] == T("common_nothing_changed")
    assert page["leave"] == {"title": T("common_leave_title"), "stayed": True,
                             "body": T("form_leave_body", changes=T("form_leave_first", count=1, group=T("settings_group_general")))}
    assert page["kept"] == {"hash": "#settings", "value": "Garage hub", "dirty": "dirty"}
    assert page["restart"] == {"title": T("settings_restart_title"), "body": T("settings_restart_body"),
                               "buttons": [T("common_cancel"), T("settings_restart_confirm")]}
    assert page["cancelled"] == "dirty"


def test_a_refused_key_shows_its_reason_at_its_own_field_and_changes_nothing(hub, monkeypatch, tmp_path):
    seen: list = []
    real = setup_helper.OPS["general_group"]
    monkeypatch.setitem(setup_helper.OPS, "general_group", lambda req: (seen.append(dict(req["values"])), real(req))[1])
    before = config.load()["server_name"]
    page = _drive(hub, tmp_path, PRELUDE + """
await loaded();
await unlock();
const form = $("#set-general");
type(form, "server_name", "x".repeat(150));
$("#set-general [type=submit]").click();
const field = form.elements["server_name"].closest(".field");
await until(() => !field.hidden && text($(".field__error", field)) && text($("#set-general .group__foot .result__text")), "the refusal");
return { error: text($(".field__error", field)), result: text($("#set-general .group__foot .result__text")), state: form.dataset.state };
""")
    assert len(seen) == 1 and set(seen[0]) == {"server_name"}
    assert config.load()["server_name"] == before                       # nothing was saved
    assert page["error"] and page["state"] == "dirty"
    assert page["result"] and page["result"] != T("common_nothing_changed")


def test_theme_for_new_devices_saves_with_its_own_button_only_while_it_differs_and_shows_after_a_reload(hub, tmp_path):
    assert config.look(config.load()) == "console"
    page = _drive(hub, tmp_path, PRELUDE + """
await loaded();
await unlock();
const sel = $('#set-appearance select[name="appearance.theme"]'), btn = $('#set-appearance [data-action="save-theme"]');
const out = { label: text($("label", sel.closest(".field"))), hint: text($(".field__hint", sel.closest(".field"))), options: [...sel.options].map((o) => o.value),
  start: { value: sel.value, disabled: btn.getAttribute("aria-disabled") }, button: text(btn) };
sel.value = "palette";
sel.dispatchEvent(new Event("change", { bubbles: true }));
out.differs = btn.getAttribute("aria-disabled");
btn.click();
await until(() => text($('#set-appearance .settings__choice:last-child .result__text')) === "__SAVED__", "the saved result");
out.saved = text($('#set-appearance .settings__choice:last-child .result__text'));
out.after = { disabled: btn.getAttribute("aria-disabled"), state: S.appearance.theme };
sel.value = "console";
sel.dispatchEvent(new Event("change", { bubbles: true }));
out.back = btn.getAttribute("aria-disabled");
return out;
""".replace("__SAVED__", T("common_saved")))
    assert page["label"] == T("appearance_theme_default_title") and page["hint"] == T("settings_appearance_new_devices_hint")
    assert page["options"] == ["console", "workbench", "palette", "panes"] and page["button"] == T("settings_appearance_save")
    assert page["start"] == {"value": "console", "disabled": "true"} and page["differs"] is None
    assert page["saved"] == T("common_saved") and page["after"] == {"disabled": "true", "state": "palette"}
    assert page["back"] is None
    assert config.look(config.load()) == "palette"
    again = _drive(hub, tmp_path, PRELUDE + """
await loaded();
return { value: $('#set-appearance select[name="appearance.theme"]').value };
""")
    assert again == {"value": "palette"}


def test_on_a_phone_settings_opens_on_the_list_of_groups_and_a_group_on_its_own_page(hub, tmp_path):
    page = _drive(hub, tmp_path, PRELUDE + """
await loaded();
const out = {};
out.list = { shown: shown($(".settings__list")), rows: [...document.querySelectorAll(".settings__row .settings__name")].map(text), groups: shown($(".settings__main")), nav: shown($(".subnav")) };
out.states = Object.fromEntries([...document.querySelectorAll(".settings__row")].map((a) => [a.dataset.id, text($(".settings__state", a))]));
$('.settings__row[data-id="storage"]').click();
await until(() => location.hash === "#settings/storage" && shown($('.settings__group[data-id="storage"]')), "the Storage group");
out.group = { hash: location.hash, list: shown($(".settings__list")), back: text($(".settings__back")), visible: [...document.querySelectorAll(".settings__group")].filter(shown).map((g) => g.dataset.id) };
$(".settings__back").click();
await until(() => location.hash === "#settings" && shown($(".settings__list")), "the list again");
out.back = { groups: shown($(".settings__main")) };
return out;
""", width=320)
    assert page["list"] == {"shown": True, "rows": NAMES, "groups": False, "nav": False}
    assert page["states"]["storage"] == T("settings_state_storage", count=len(storage.peek().locations))
    assert page["states"]["general"] == "Workshop hub"
    assert page["group"] == {"hash": "#settings/storage", "list": False, "back": T("nav_settings"), "visible": ["storage"]}
    assert page["back"] == {"groups": False}


def test_on_a_wide_screen_the_address_of_a_group_scrolls_to_it_and_marks_it_current(hub, tmp_path):
    page = _drive(hub, tmp_path, "location.hash = '#settings/catalog';\n" + PRELUDE.replace('location.hash = "#settings";\n', "") + """
await loaded();
await until(() => $('.subnav__link[data-id="catalog"]').getAttribute("aria-current") === "true", "the current group");
const inView = () => { const t = $('[data-id="catalog"] .group__title').getBoundingClientRect(); return t.top >= 0 && t.top < innerHeight; };
await until(inView, "the group to scroll into view");
return { current: [...document.querySelectorAll('.subnav__link[aria-current="true"]')].map((a) => a.dataset.id), top: inView(), list: shown($(".settings__list")) };
""")
    assert page == {"current": ["catalog"], "top": True, "list": False}


def test_the_audit_passes_on_every_group_at_320_and_1280_px_in_light_and_dark(hub):
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else []
    views = ",".join(["#settings", *("#settings/" + g for g in GROUPS)])
    run = _run("--url", hub, "--views", views, "--ready", WAIT_GROUPS + "waitGroups()", *fonts)      # no allow-list: nothing of Settings is allowed any more
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["views"] == len(GROUPS) * 4 + 4 and out["failing"] == 0


# the groups are read once when Settings opens: the audit starts after that (a loaded machine reads them slowly)
WAIT_GROUPS = """const waitGroups = async () => {
  location.hash = "#settings";
  const until = async (f) => { for (let i = 0; i < 300 && !f(); i++) await new Promise((r) => setTimeout(r, 100)); };
  await until(() => document.querySelectorAll(".settings__group").length === 9 && !document.querySelector('main [aria-busy="true"]:not(button)')
    && document.querySelector('.settings__group[data-id="voice"] .group'));
};
"""

UNLOCK = WAIT_GROUPS + """(async () => {
  const until = async (f) => { for (let i = 0; i < 100 && !f(); i++) await new Promise((r) => setTimeout(r, 100)); };
  await until(() => !document.querySelector(".chip--lock .skeleton__line") && !document.querySelector('[aria-busy="true"]:not(button)'));
  SW.setLock("unlocked", { code: "12345678" });
  await waitGroups();
})()"""


def test_the_audit_passes_on_the_groups_that_read_more_once_unlocked(hub_change, monkeypatch):
    _switch_on("ai_intake", "local_intake", "station", "remote", "web")
    fonts = ["--font-dir", os.environ["AUT5_FONT_DIR"]] if os.environ.get("AUT5_FONT_DIR") else []
    run = _run("--url", hub_change, "--views", "#settings/backups,#settings/label-reader,#settings/network,#settings/voice,#settings/catalog",
               "--ready", UNLOCK, *fonts)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["views"] == 20 and json.loads(run.stdout)["failing"] == 0


def test_a_second_submit_during_a_save_changes_nothing_and_the_save_reports_what_it_did(hub, monkeypatch, tmp_path):
    """R332 HIGH 2: the second press used to empty the plan of the save under way, which then reported a saved group as failed."""
    import time
    seen: list = []
    real = setup_helper.OPS["general_group"]

    def slow(req):
        seen.append(dict(req["values"]))
        time.sleep(1.2)
        return real(req)
    monkeypatch.setitem(setup_helper.OPS, "general_group", slow)
    page = _drive(hub, tmp_path, PRELUDE + """
await loaded();
await unlock();
const form = $("#set-general");
type(form, "server_name", "Slow hub");
form.requestSubmit();
await sleep(500);
form.requestSubmit();                                   // while the first is still on its way
await until(() => $("#set-general") !== form && text($("#set-general .group__foot .result__text")), "the saved result");
return { result: text($("#set-general .group__foot .result__text")), state: $("#set-general").dataset.state || null };
""")
    assert len(seen) == 1, seen
    assert page["result"] == T("form_saved_fields", fields=T("settings_general_name")) and page["state"] is None


def test_label_reader_sends_the_key_after_records_kept_and_a_secret_does_not_stay_once_accepted(hub, monkeypatch, tmp_path):
    """R332 MED 1 and 2: a refused key does not turn the keys saved before it into 'not saved', and an accepted key leaves
    the entry field even when a later key (the model, which restarts the Hub) is refused."""
    _switch_on("ai_intake", "local_intake")
    order: list = []
    key_calls = []
    real = setup_helper.OPS["general_group"]

    def group(req):
        order.append(("group", sorted(req["values"])))
        if "model" in req["values"]:
            raise setup_helper.Refused(400, "model is not usable", errors={"model": "model is not usable"})
        return real(req)

    def key(req):
        order.append(("key",))
        key_calls.append(1)
        if len(key_calls) == 1:
            raise setup_helper.Refused(400, "the key was refused", field="key")
        return {}
    monkeypatch.setitem(setup_helper.OPS, "general_group", group)
    monkeypatch.setitem(setup_helper.OPS, "key_set", key)
    page = _drive(hub, tmp_path, PRELUDE + """
await loaded();
await unlock();
const form = $("#set-label-reader"), entry = () => $("#set-label-reader .settings__entry input");
$('#set-label-reader [data-action="replace-key"]').click();
const key = (v) => { const c = entry(); c.value = v; c.dispatchEvent(new Event("input", { bubbles: true })); };
type(form, "intake.history_keep", "31");
key("sk-ant-example-1");
form.requestSubmit();
const first = await until(() => text($("#set-label-reader .group__foot .result__text")), "the first result");
const out = { first, keptAfterRefusal: entry().value };
// the key is accepted now, the model is refused: the key leaves the page
type(form, "model", "claude-example");
await sleep(100);
form.requestSubmit();
const ask = await until(() => $("dialog[open]"), "the restart question");
$('[data-action="confirm"]', ask).click();
await until(() => { const r = text($("#set-label-reader .group__foot .result__text")); return r && r !== first ? r : null; }, "the second result");
out.second = text($("#set-label-reader .group__foot .result__text"));
out.keptAfterAccepted = entry().value;
out.dirty = form.dataset.state || null;
return out;
""")
    keys_first = order[:2]
    assert keys_first == [("group", ["intake.history_keep"]), ("key",)], order       # Records kept goes first, the key after it
    assert "Records kept" in page["first"].split("Not saved")[0] and "Address" not in page["first"], page["first"]
    assert page["keptAfterRefusal"] == "sk-ant-example-1"
    assert page["keptAfterAccepted"] == "" and page["dirty"] == "dirty", page
