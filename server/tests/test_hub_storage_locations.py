"""Settings > Storage locations on the Hub page (DECISIONS R79 section 3, 03 10.4), in a real headless browser: the list of
locations in fill order with Add, Edit, Move up and down, Make default overflow, Sealed spools go here and Remove, the
"Where a new spool goes" panel built from the unsaved list, one Save with the dirty mark, the field and dialog texts of R79
section 5, and the list readable in all four looks at 1280, 1776, 1024, 768 and 390 px (no summary squeezed to a sliver or
wrapped past two lines, no sideways scrolling: the lesson of the Panes summary-width finding). The page runs against the Hub's
real routes and storage.xml (R79 section 4 shapes) with spools in the fake Spoolman. The same skip rules as the page audit:
no Node 22 or no browser is a skip (a failure with AUT5_REQUIRED=1)."""
from __future__ import annotations

import httpx
import pytest

from filament_kit import storage
from filament_kit.storage import ANY, CONTAINERS, MATERIALS, Location, Storage
from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_hub_settings import PRELUDE

# the stub's list (setup_storage.js stStubInit), in fill order; the set of containers is a PREFIXED one: its name is not its prefix
# ("Storage box "), and its containers ("Storage box 01" to "Storage box 12") are named by the data, never by the page
START = ["Sealed stock", "Rack 1", "Rack 2", "Storage box (containers)", "Overflow", "Dry shelf"]

HELPERS = r"""
const rowEls = () => [...document.querySelectorAll("#set-storage .coll--storage > .coll__item[data-id]:not([data-id=new])")];
const names = () => rowEls().map((r) => text($(".storage__name", r)));
const rowOf = (name) => rowEls().find((r) => text($(".storage__name", r)) === name);
const panel = () => [...document.querySelectorAll("#set-storage .storage__places li")].map(text);
const badges = (name) => [...rowOf(name).querySelectorAll(".storage__badges .status")].map(text);
const cells = (name) => ({ full: text($('[data-col="full"] .storage__text', rowOf(name))), takes: text($('[data-col="takes"] .storage__text', rowOf(name))), type: text($(".storage__type", rowOf(name))) });
const form = () => $(".storage__form");
const fieldOf = (f, name) => f.elements[name].closest(".field");
const err = (f, name) => { const e = $(".field__error", fieldOf(f, name)); return e && !e.hidden ? text(e) : null; };
const setField = (f, name, value) => { const c = f.elements[name]; c.value = value; c.dispatchEvent(new Event("input", { bubbles: true })); c.dispatchEvent(new Event("change", { bubbles: true })); };
const pick = (f, name, value) => f.querySelector(`input[name="${name}"][value="${value}"]`).click();
const submit = async (f) => { f.requestSubmit(); await sleep(150); };
const openEdit = async (name) => { $(".btn:not(.btn--icon)", rowOf(name)).click(); await until(() => form(), "the editor"); await sleep(150); return form(); };
const openAdd = async () => { $("#set-storage .storage__bar .btn--primary").click(); await until(() => form(), "the editor"); await sleep(150); return form(); };
const menuItem = async (name, label) => {
  $('[aria-haspopup="menu"]', rowOf(name)).click();
  const item = await until(() => [...document.querySelectorAll(".menu__item")].find((b) => text(b) === label), "the menu item " + label);
  item.click();
  await sleep(150);
};
const menuLabels = async (name) => {
  $('[aria-haspopup="menu"]', rowOf(name)).click();
  await until(() => $(".menu__item"), "the menu");
  const out = [...document.querySelectorAll(".menu__item")].map(text);
  $('[aria-haspopup="menu"]', rowOf(name)).click();
  await sleep(100);
  return out;
};
const moveBtn = (name, dir) => $(`[aria-label="Move ${name} ${dir}"]`);
const dirty = () => ({ form: $("#set-storage").dataset.state || null, link: shown($('.subnav__link[data-id="storage"] .subnav__dirty')), foot: shown($("#set-storage .group__dirty")) });
const settled = () => sleep(700);                         // the preview of the unsaved list answers after a short wait
const ready = async () => {
  await loaded();
  location.hash = "#settings/storage";
  await until(() => rowEls().length, "the locations");
  await sleep(200);
};
"""


@pytest.fixture(autouse=True)
def stock(hub_app, spoolman_url):  # noqa: F811
    """The Hub's real storage list (storage.xml) and spools in the fake Spoolman: the page reads and saves through the real routes.
    The set of containers is a PREFIXED one (its name is not its prefix) and the list is flagged as converted."""
    storage.save(Storage([
        Location("Sealed stock", sealed=True),
        Location("Rack 1", limit=20, fill=MATERIALS, materials=["PLA"]),
        Location("Rack 2", fill=MATERIALS, materials=["PETG", "ABS"]),
        Location("Storage box (containers)", CONTAINERS, count=12, prefix="Storage box ", fill=ANY),
        Location("Overflow", overflow=True, default_overflow=True),
        Location("Dry shelf", limit=10, overflow=True)], converted=True))
    places = ["Sealed stock"] * 4 + ["Rack 1"] * 17 + ["Rack 2"] * 7 + [f"Storage box {n:02d}" for n in (1, 2, 3, 4, 5, 6, 7, 11, 12)] + ["Overflow"] * 2
    with httpx.Client() as c:
        filament = c.get(spoolman_url + "/api/v1/filament").json()[0]["id"]        # the spool of the audit data is the 18th at Rack 1
        for place in places:
            c.post(spoolman_url + "/api/v1/spool", json={"filament_id": filament, "location": place, "remaining_weight": 500}).raise_for_status()


def _drive_storage(hub, tmp_path, body, width=1280, look="console"):
    script = PRELUDE + HELPERS + f'document.documentElement.setAttribute("data-look", "{look}");\nawait ready();\nconst out = {{}};\n' + body + "\nreturn out;\n"
    return _drive(hub, tmp_path, script, width=width)


def test_the_group_lists_the_locations_in_fill_order_with_how_full_what_they_take_and_the_marks(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
out.names = names();
out.summary = text($('.settings__row[data-id="storage"] .settings__state'));
out.desc = text($("#set-storage .group__desc"));
out.heading = text($("#set-storage .storage__bar .settings__heading"));
out.add = text($("#set-storage .storage__bar .btn--primary"));
out.cells = Object.fromEntries(names().map((n) => [n, cells(n)]));
out.badges = Object.fromEntries(names().map((n) => [n, badges(n)]));
out.position = rowEls().map((r) => text($(".storage__pos", r)));
out.edit = rowEls().map((r) => $(".btn:not(.btn--icon)", r).getAttribute("aria-label"));
out.up = rowEls().map((r) => $(".storage__move--up", r).getAttribute("aria-label"));
out.down = rowEls().map((r) => $(".storage__move--down", r).getAttribute("aria-label"));
out.disabled = rowEls().map((r) => [$(".storage__move--up", r).getAttribute("aria-disabled"), $(".storage__move--down", r).getAttribute("aria-disabled")]);
out.panel = panel();
out.notice = { shown: shown($("#set-storage .banner[data-notice=\"default_overflow_no_limit\"]")), text: text($("#set-storage .banner[data-notice=\"default_overflow_no_limit\"]")) };
out.converted = !!$("#set-storage .banner--info");
out.panelTitle = text($("#set-storage .storage__panel .settings__heading"));
out.save = text($("#set-storage [type=submit]"));
out.dirty = dirty();
""")
    assert page["names"] == START and page["summary"] == T("settings_state_storage", count=6)
    assert page["desc"] == T("settings_storage_desc") and page["heading"] == T("settings_storage_locations") and page["add"] == T("storage_add_location")
    bulk, containers = T("storage_type_bulk"), T("storage_type_containers")
    assert page["cells"] == {
        "Sealed stock": {"full": T("storage_used_plain", count=4), "takes": T("storage_takes_none"), "type": bulk},
        "Rack 1": {"full": "18 of 20 spools", "takes": "PLA", "type": bulk},
        "Rack 2": {"full": "7 spools", "takes": "PETG, ABS", "type": bulk},
        "Storage box (containers)": {"full": "9 of 12 containers used", "takes": T("storage_fill_any"), "type": containers},
        "Overflow": {"full": "2 spools", "takes": T("storage_takes_none"), "type": bulk},
        "Dry shelf": {"full": "0 of 10 spools", "takes": T("storage_takes_none"), "type": bulk},
    }
    over, default, sealed = T("storage_badge_overflow"), T("storage_badge_default_overflow"), T("storage_badge_sealed")
    assert page["badges"] == {"Sealed stock": [sealed], "Rack 1": [], "Rack 2": [], "Storage box (containers)": [], "Overflow": [over, default], "Dry shelf": [over]}
    assert page["position"] == ["1", "2", "3", "4", "5", "6"]
    assert page["edit"] == [T("settings_storage_edit_name", name=n) for n in START]
    assert page["up"] == [T("storage_move_up", name=n) for n in START] and page["down"] == [T("storage_move_down", name=n) for n in START]
    assert page["disabled"] == [["true", "false"]] + [["false", "false"]] * 4 + [["false", "true"]]
    # the panel: one line per material named in the list, then everything else
    assert page["panelTitle"] == T("storage_panel_title")
    assert page["panel"] == ["PLA: Rack 1, then Overflow, then Dry shelf", "PETG: Rack 2, then Overflow, then Dry shelf", "ABS: Rack 2, then Overflow, then Dry shelf",
                             "Everything else: Storage box (containers), then Overflow, then Dry shelf"]
    # R79 C1: two overflow places and no limit on the default: the notice says the other one is never reached
    assert page["notice"] == {"shown": True, "text": T("storage_notice_default_overflow_no_limit")} and page["converted"] is True
    assert page["save"] == T("settings_storage_save") and page["dirty"] == {"form": None, "link": False, "foot": False}


def test_add_and_edit_open_the_detail_region_and_check_each_field_with_the_texts_of_the_catalogue(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
// Add: a form that starts on Bulk storage, and says what is wrong at the field
let f = await openAdd();
out.addTitle = text($(".detail__title", f)); out.addButton = text($("[type=submit]", f)); out.typeStart = f.elements.type.value;
out.legends = [...f.querySelectorAll("legend, .field__label")].map((e) => text(e).replace(" (optional)", "")).filter(Boolean);
out.hints = [...f.querySelectorAll(".field__hint, .check__desc")].filter(shown).map(text);
out.limitHidden = [fieldOf(f, "limit").hidden, fieldOf(f, "count").hidden, fieldOf(f, "materials").hidden];
await submit(f);
out.errName = err(f, "name");
setField(f, "name", "rack 1");                                   // case ignored
await submit(f);
out.errTaken = err(f, "name");
setField(f, "name", "Dry box"); setField(f, "limit", "0");
await submit(f);
out.errLimit = err(f, "limit");
setField(f, "limit", "12x");
await submit(f);
out.errLimit2 = err(f, "limit");
setField(f, "limit", "");
pick(f, "fill", "materials");
out.materialsShown = !fieldOf(f, "materials").hidden;
await submit(f);
out.errMaterials = err(f, "materials");
pick(f, "type", "containers");
out.containersShown = [fieldOf(f, "limit").hidden, !fieldOf(f, "count").hidden];
out.typeHint = text($(".storage__typehint", f));
await submit(f);
out.errCount = err(f, "count");
setField(f, "count", "1000");
await submit(f);
out.errCount2 = err(f, "count");
// a valid one: three materials with a variant and a duplicate, then it is the last row, with the focus on its Edit
pick(f, "type", "bulk");
setField(f, "limit", "5"); setField(f, "materials", "PETG, pla+ , PETG");
// R79 C2: ticking overflow while "Any material" is chosen moves to "Nothing"; "Any material" is then off and says why
pick(f, "fill", "any");
$("input[name=overflow]", f).click();
out.anyToNone = { fill: f.elements.fill.value, disabled: f.querySelector('input[name="fill"][value="any"]').disabled, hint: shown($(".storage__anyhint", f)) && text($(".storage__anyhint", f)) };
$("input[name=overflow]", f).click();
out.anyBack = { disabled: f.querySelector('input[name="fill"][value="any"]').disabled, fill: f.elements.fill.value, hint: shown($(".storage__anyhint", f)) };
pick(f, "fill", "materials");
$("input[name=overflow]", f).click();
await submit(f);
await until(() => !form(), "the editor to close");
out.afterAdd = names();
out.dryBox = { ...cells("Dry box"), badges: badges("Dry box"), takes: undefined };
out.dryBoxTakes = cells("Dry box").takes;
out.focus = document.activeElement.getAttribute("aria-label");
out.dirtyAfterAdd = dirty();
await settled();
out.panelAfterAdd = panel();
out.summary = text($('.settings__row[data-id="storage"] .settings__state'));

// Edit: a location with spools keeps its type; a rename keeps its place; fewer containers than numbers in use is refused
f = await openEdit("Rack 2");
out.editTitle = text($(".detail__title", f)); out.editButton = text($("[type=submit]", f));
out.typeFixed = [...f.querySelectorAll('input[name="type"]')].map((i) => i.disabled);
out.typeFixedHint = [...f.querySelectorAll(".storage__fixed")].map(text);
setField(f, "name", "Rack two");
await submit(f);
await until(() => !form(), "the editor to close");
out.afterRename = names();
f = await openEdit("Storage box (containers)");
out.containersTitle = text($(".detail__title", f));
setField(f, "count", "10");
await submit(f);
out.errInUse = err(f, "count");
setField(f, "count", "13");
await submit(f);
await until(() => !form(), "the editor to close");
out.boxFull = cells("Storage box (containers)").full;
// the default overflow cannot be switched off; a plain one can; a limit on it is allowed (R79 C1) and ends the notice
f = await openEdit("Overflow");
out.defaultLimitShown = !fieldOf(f, "limit").hidden;
$("input[name=overflow]", f).click();
await submit(f);
out.errDefault = err(f, "overflow");
$("input[name=overflow]", f).click();
setField(f, "limit", "30");
await submit(f);
await until(() => !form(), "the editor to close");
await settled();
out.noticeAfter = shown($("#set-storage .banner[data-notice=\"default_overflow_no_limit\"]"));
""")
    assert page["addTitle"] == T("storage_add_location") and page["addButton"] == T("storage_add_submit") and page["typeStart"] == "bulk"
    for word in ("storage_field_name", "storage_field_type", "storage_field_limit", "storage_field_fill"):
        assert T(word) in page["legends"], (word, page["legends"])
    assert T("storage_type_bulk_hint") in page["hints"] and T("storage_field_limit_hint") in page["hints"] and T("storage_field_overflow_hint") in page["hints"]
    assert page["limitHidden"] == [False, True, True]
    assert page["errName"] == T("storage_error_name") and page["errTaken"] == T("storage_error_name_taken", name="rack 1")
    assert page["errLimit"] == page["errLimit2"] == T("storage_error_whole") == "Enter a whole number, 1 or more."
    assert page["materialsShown"] and page["errMaterials"] == T("storage_error_materials") == "Enter at least one material, e.g. PLA."
    assert page["containersShown"] == [True, True] and page["typeHint"] == T("storage_type_containers_hint").replace("{product}", "Spoolwarden")
    assert page["errCount"] == page["errCount2"] == T("storage_error_whole")
    assert page["afterAdd"] == START + ["Dry box"] and page["dryBoxTakes"] == "PETG, pla+"
    assert page["dryBox"]["full"] == "0 of 5 spools" and page["dryBox"]["badges"] == [T("storage_badge_overflow")]
    assert page["focus"] == T("settings_storage_edit_name", name="Dry box")
    assert page["dirtyAfterAdd"] == {"form": "dirty", "link": True, "foot": True} and page["summary"] == T("settings_state_storage", count=6)     # the summary is the saved list's
    assert page["panelAfterAdd"][-1] == "Everything else: Storage box (containers), then Overflow, then Dry shelf, then Dry box"
    assert "PETG: Rack 2, then Dry box, then Overflow, then Dry shelf" in page["panelAfterAdd"]     # an overflow place that names a material is an own place (R79 C2)
    assert "pla+: Dry box, then Overflow, then Dry shelf" in page["panelAfterAdd"] and any(line.startswith("pla+: ") for line in page["panelAfterAdd"])
    assert page["editTitle"] == "Rack 2" and page["editButton"] == T("storage_save_location")
    assert page["typeFixed"] == [False, True] and page["typeFixedHint"] == [T("storage_error_type_fixed")]
    assert page["afterRename"] == ["Sealed stock", "Rack 1", "Rack two", "Storage box (containers)", "Overflow", "Dry shelf", "Dry box"]
    assert page["errInUse"] == "Storage box 11 and Storage box 12 hold spools. Move them first, or keep at least 12."
    assert page["boxFull"] == "9 of 13 containers used"
    assert page["anyToNone"] == {"fill": "none", "disabled": True, "hint": T("storage_fill_any_overflow_hint")}
    assert page["anyBack"] == {"disabled": False, "fill": "none", "hint": False}       # unticking does not put "Any material" back, but allows it again
    assert page["defaultLimitShown"] is True and page["noticeAfter"] is False
    assert page["errDefault"] == T("storage_error_remove_default_overflow") == "Make another location the default overflow first."


def test_closing_the_form_with_typed_values_asks_and_cancel_with_nothing_typed_does_not(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
let f = await openAdd();
$(".btn--ghost:not(.detail__close):not(.detail__back)", f).click();          // Cancel, nothing typed
await sleep(300);
out.plain = { open: !!form(), dialog: !!$("dialog[open]"), focus: document.activeElement === $("#set-storage .storage__bar .btn--primary") };
f = await openAdd();
setField(f, "name", "Typed");
$(".btn--ghost:not(.detail__close):not(.detail__back)", f).click();
const dlg = await until(() => $("dialog[open]"), "the leave question");
out.ask = { title: text($(".dialog__title", dlg)), buttons: [...dlg.querySelectorAll(".dialog__foot .btn")].map(text) };
$('[data-action="cancel"]', dlg).click();                                  // Stay
await until(() => !$("dialog[open]"), "the question to close");
out.stayed = { open: !!form(), value: form().elements.name.value };
$(".btn--ghost:not(.detail__close):not(.detail__back)", form()).click();
const dlg2 = await until(() => $("dialog[open]"), "the leave question");
$('[data-action="confirm"]', dlg2).click();                                // Leave without saving
await until(() => !form(), "the form to close");
out.left = { names: names(), dirty: dirty() };
""")
    assert page["plain"] == {"open": False, "dialog": False, "focus": True}
    assert page["ask"] == {"title": T("common_leave_title"), "buttons": [T("common_stay"), T("common_leave_without_saving")]}
    assert page["stayed"] == {"open": True, "value": "Typed"}
    assert page["left"] == {"names": START, "dirty": {"form": None, "link": False, "foot": False}}


def test_move_default_overflow_sealed_and_remove_change_the_unsaved_list_with_keyboard_reachable_buttons(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
// Move: the pressed button keeps its focus, the ends cannot move, the panel follows
const up = moveBtn("Rack 2", "up");
up.focus(); up.click(); await sleep(150);
await settled();
out.moved = { names: names(), focus: document.activeElement === up, panel: panel()[0], dirty: dirty() };
up.click(); await sleep(150);
out.movedTwice = names();
up.click(); await sleep(150);                                              // now first: aria-disabled, does nothing
out.atTop = { names: names(), disabled: up.getAttribute("aria-disabled"), focus: document.activeElement === up };
const down = moveBtn("Dry shelf", "down");
down.click(); await sleep(100);
out.atEnd = { names: names(), disabled: down.getAttribute("aria-disabled") };
// the keyboard: Enter on a focused button presses it (a button), so there is no drag-only path
moveBtn("Rack 1", "down").focus();
out.focusable = document.activeElement.getAttribute("aria-label");
// the menus
out.menus = { rack: await menuLabels("Rack 1"), box: await menuLabels("Storage box (containers)"), sealed: await menuLabels("Sealed stock"), over: await menuLabels("Overflow"), shelf: await menuLabels("Dry shelf") };
await menuItem("Dry shelf", "Make default overflow");
out.afterDefault = { shelf: badges("Dry shelf"), overflow: badges("Overflow") };
await menuItem("Rack 1", "Sealed spools go here");
out.afterSealed = { rack: badges("Rack 1"), stock: badges("Sealed stock") };
await settled();
out.panelAfter = panel();
// Remove: a dialog with the count; the focus goes to the row that took its place
$('[aria-haspopup="menu"]', rowOf("Rack 2")).click();
(await until(() => [...document.querySelectorAll(".menu__item")].find((b) => text(b) === "Remove"), "Remove")).click();
let dlg = await until(() => $("dialog[open]"), "the remove question");
out.removeAsk = { title: text($(".dialog__title", dlg)), text: text($(".dialog__text", dlg)), buttons: [...dlg.querySelectorAll(".dialog__foot .btn")].map(text),
  danger: dlg.querySelector('[data-action="confirm"]').className };
$('[data-action="confirm"]', dlg).click();
await until(() => !$("dialog[open]"), "the question to close"); await sleep(150);
out.afterRemove = { names: names(), focus: document.activeElement.getAttribute("aria-label") };
// no spools: the other text
$('[aria-haspopup="menu"]', rowOf("Overflow")).click();
(await until(() => [...document.querySelectorAll(".menu__item")].find((b) => text(b) === "Remove"), "Remove")).click();
dlg = await until(() => $("dialog[open]"), "the remove question");
out.noSpools = text($(".dialog__text", dlg));
$('[data-action="cancel"]', dlg).click();
await until(() => !$("dialog[open]"), "the question to close");
// refused: the default overflow and the sealed-spools location stay, the dialog says why
for (const name of ["Dry shelf", "Rack 1"]) {
  $('[aria-haspopup="menu"]', rowOf(name)).click();
  (await until(() => [...document.querySelectorAll(".menu__item")].find((b) => text(b) === "Remove"), "Remove")).click();
  dlg = await until(() => $("dialog[open]"), "the remove question");
  $('[data-action="confirm"]', dlg).click();
  const said = await until(() => text($(".dialog__result .result__text", dlg)), "the refusal");
  (out.refused = out.refused || {})[name] = { said, open: dlg.open, still: names().includes(name) };
  $('[data-action="cancel"]', dlg).click();
  await until(() => !$("dialog[open]"), "the question to close");
}
// removing the last one that was Overflow (not default now) works and leaves the panel without it
$('[aria-haspopup="menu"]', rowOf("Overflow")).click();
(await until(() => [...document.querySelectorAll(".menu__item")].find((b) => text(b) === "Remove"), "Remove")).click();
dlg = await until(() => $("dialog[open]"), "the remove question");
$('[data-action="confirm"]', dlg).click();
await until(() => !$("dialog[open]"), "the question to close"); await sleep(150);
await settled();
out.final = { names: names(), panel: panel(), dirty: dirty() };
""")
    assert page["moved"]["names"] == ["Sealed stock", "Rack 2", "Rack 1", "Storage box (containers)", "Overflow", "Dry shelf"] and page["moved"]["focus"] is True
    assert page["moved"]["panel"] == "PETG: Rack 2, then Overflow, then Dry shelf"
    assert page["moved"]["dirty"] == {"form": "dirty", "link": True, "foot": True}
    assert page["movedTwice"][0] == "Rack 2"
    assert page["atTop"] == {"names": ["Rack 2", "Sealed stock", "Rack 1", "Storage box (containers)", "Overflow", "Dry shelf"], "disabled": "true", "focus": True}
    assert page["atEnd"] == {"names": ["Rack 2", "Sealed stock", "Rack 1", "Storage box (containers)", "Overflow", "Dry shelf"], "disabled": "true"}
    assert page["focusable"] == T("storage_move_down", name="Rack 1")
    make_default, make_sealed, remove = T("storage_make_default_overflow"), T("storage_sealed_here"), T("common_remove")
    assert page["menus"] == {"rack": [make_sealed, remove], "box": [remove], "sealed": [remove], "over": [make_sealed, remove], "shelf": [make_default, make_sealed, remove]}
    assert page["afterDefault"] == {"shelf": [T("storage_badge_overflow"), T("storage_badge_default_overflow")], "overflow": [T("storage_badge_overflow")]}
    assert page["afterSealed"] == {"rack": [T("storage_badge_sealed")], "stock": []}
    assert page["removeAsk"]["title"] == T("storage_remove_title", name="Rack 2") == "Remove Rack 2?"
    assert page["removeAsk"]["text"] == ("7 spools are recorded there. They keep that location until you move them; it is no longer offered for new spools.")
    assert page["removeAsk"]["buttons"][-2:] == [T("common_cancel"), T("common_remove")] and "btn--danger" in page["removeAsk"]["danger"]
    assert page["afterRemove"]["names"] == ["Sealed stock", "Rack 1", "Storage box (containers)", "Overflow", "Dry shelf"]
    assert page["afterRemove"]["focus"] == T("settings_storage_edit_name", name="Rack 1") or page["afterRemove"]["focus"].startswith("Edit ")
    assert page["noSpools"] == "2 spools are recorded there. They keep that location until you move them; it is no longer offered for new spools."
    assert page["refused"] == {"Dry shelf": {"said": "Make another location the default overflow first.", "open": True, "still": True},
                               "Rack 1": {"said": "Choose another location for sealed spools first.", "open": True, "still": True}}
    assert page["final"]["names"] == ["Sealed stock", "Rack 1", "Storage box (containers)", "Dry shelf"]
    assert not any(line.startswith("PETG") for line in page["final"]["panel"]) and page["final"]["dirty"]["form"] == "dirty"


def test_undo_restores_the_list_and_save_sends_the_whole_list_once_and_says_what_was_renamed(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(800);
// Undo changes brings the list back as it was read
moveBtn("Rack 1", "up").click(); await sleep(100);
await menuItem("Rack 2", "Sealed spools go here");
out.beforeUndo = { names: names(), dirty: dirty() };
$('#set-storage [data-action="undo-changes"]').click(); await sleep(300);
out.afterUndo = { names: names(), dirty: dirty(), badges: badges("Sealed stock"), panel: panel().length };
// rename a location that holds spools, move another, add one; one Save
let f = await openEdit("Rack 1");
setField(f, "name", "PLA rack 1");
await submit(f);
await until(() => !form(), "the editor to close");
moveBtn("Dry shelf", "up").click(); await sleep(100);
f = await openAdd(); setField(f, "name", "Spare"); await submit(f);
await until(() => !form(), "the editor to close");
out.beforeSave = { names: names(), dirty: dirty() };
$("#set-storage [type=submit]").click();
await until(() => $("#set-storage") && $("#set-storage .group__foot .result__text") && text($("#set-storage .group__foot .result__text")).startsWith("Storage locations saved"), "the saved result");
await sleep(500);
out.saved = text($("#set-storage .group__foot .result__text"));
out.after = { names: names(), dirty: dirty(), summary: text($('.settings__row[data-id="storage"] .settings__state')), rack: cells("PLA rack 1").full, spare: cells("Spare").full };
// nothing changed: the form group says so
$("#set-storage [type=submit]").click(); await sleep(300);
out.nothing = text($("#set-storage .group__foot .result__text"));
""")
    assert page["beforeUndo"]["names"] == ["Sealed stock", "Rack 1", "Rack 2", "Storage box (containers)", "Overflow", "Dry shelf"][:0] + ["Rack 1", "Sealed stock", "Rack 2", "Storage box (containers)", "Overflow", "Dry shelf"]
    assert page["beforeUndo"]["dirty"]["form"] == "dirty"
    assert page["afterUndo"] == {"names": START, "dirty": {"form": None, "link": False, "foot": False}, "badges": [T("storage_badge_sealed")], "panel": 4}
    assert page["beforeSave"]["names"] == ["Sealed stock", "PLA rack 1", "Rack 2", "Storage box (containers)", "Dry shelf", "Overflow", "Spare"]
    assert page["saved"] == "Storage locations saved. Renamed Rack 1 to PLA rack 1. 18 spools updated."
    assert page["after"]["dirty"] == {"form": None, "link": False, "foot": False}
    assert page["after"]["names"] == ["Sealed stock", "PLA rack 1", "Rack 2", "Storage box (containers)", "Dry shelf", "Overflow", "Spare"]
    assert page["after"]["summary"] == T("settings_state_storage", count=7) and page["after"]["rack"] == "18 of 20 spools" and page["after"]["spare"] == "0 spools"
    assert page["nothing"] == T("common_nothing_changed")


def test_the_converted_notice_shows_for_a_set_named_with_containers_in_brackets_and_goes_when_it_is_renamed(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(800);
out.before = text($("#set-storage .banner--info"));
const f = await openEdit("Storage box (containers)");
setField(f, "name", "Boxes");
await submit(f);
await until(() => !form(), "the editor to close");
$("#set-storage [type=submit]").click();
await until(() => text($("#set-storage .group__foot .result__text")) && text($("#set-storage .group__foot .result__text")).startsWith("Storage locations saved"), "the saved result");
await sleep(500);
out.after = !!$("#set-storage .banner--info");
out.names = names();
""")
    assert page["before"] == T("storage_notice_converted") == "Storage locations were converted. Check them."
    assert page["after"] is False and page["names"][3] == "Boxes"


def test_a_name_that_is_a_container_name_is_refused_both_ways_with_the_names_taken_from_the_data(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(800);
// a bulk name equal to a container of the prefixed set ("Storage box 05"), checked at the Name field from the set's data
let f = await openAdd();
setField(f, "name", "storage box 05");
await submit(f);
out.clash = err(f, "name");
// the other way: "Storage box 13" is fine until the set grows to 13; the Hub then refuses, and the text is shown at the Name field
setField(f, "name", "Storage box 13");
await submit(f);
await until(() => !form(), "the editor to close");
out.added = names();
f = await openEdit("Storage box (containers)");
setField(f, "count", "13");
await submit(f);
await until(() => !form(), "the editor to close");
$("#set-storage [type=submit]").click();
await until(() => form() && err(form(), "name"), "the refusal at the Name field");
out.refusal = err(form(), "name");
out.title = text($(".detail__title", form()));
out.result = text($("#set-storage .group__foot .result__text"));
out.state = $("#set-storage").dataset.state;
""")
    set_name = "Storage box (containers)"
    assert page["clash"] == T("storage_error_container_name", name="storage box 05", set=set_name)
    assert page["added"][-1] == "Storage box 13"
    want = "Storage box 13 is the name of a container in Storage box (containers). Choose another name."
    assert page["refusal"] == want and page["title"] in (set_name, "Storage box 13") and page["state"] == "dirty"
    assert page["result"] and want in page["result"]


def test_a_refusal_of_the_hub_is_said_at_its_row_and_in_the_result_and_the_list_stays_unsaved(hub, tmp_path):
    page = _drive_storage(hub, tmp_path, r"""
SW.setLock("unlocked", { code: "__CODE__" });
await sleep(800);
// two rows with one name can only come from outside the form (the form checks it): the Hub's answer is what is shown
const input = $("#set-storage").elements.locations;
const list = JSON.parse(input.value);
list[2].name = list[1].name;
input.value = JSON.stringify(list);
input.dispatchEvent(new Event("change", { bubbles: true }));
await sleep(100);
$("#set-storage [type=submit]").click();
await until(() => text($("#set-storage .group__foot .result__text")), "the refusal");
await sleep(200);
out.result = text($("#set-storage .group__foot .result__text"));
out.rowErrors = rowEls().map((r) => text($(".storage__errors", r)));
out.state = $("#set-storage").dataset.state;
""")
    assert page["result"] == T("storage_error_name_taken", name="Rack 1") + " Nothing was saved."
    assert page["rowErrors"][2] and "There is already a location called" in page["rowErrors"][2] and not any(page["rowErrors"][i] for i in (0, 1, 3, 4, 5))
    assert page["state"] == "dirty"


# ----- readable in all four looks at every width -----
# every text a row draws (name, type, marks, how full, what it takes), measured as drawn and with long texts put in; and the
# form of Add, opened in each look: no sideways scrolling, fields not squeezed
MEASURE = r"""
const LONG = ["Garage shelf, left side, top row", "Individual containers and more", "PLA, PETG, ABS, ASA, TPU, PA-CF", "18 of 20 spools in this place"];
const readable = [];
const pageW = () => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth });
const TEXTS = '.storage__name, .storage__type, .storage__badges .status, .storage__text, .storage__places li';
const measure = (look, label) => {
  for (const el of document.querySelectorAll(TEXTS)) {
    if (!el.getClientRects().length || !el.textContent.trim()) continue;
    const cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4, box = el.getBoundingClientRect(), item = el.closest(".coll__item, .storage__panel");
    readable.push({ look, label, text: el.textContent.trim().slice(0, 40), w: Math.round(box.width), em: Math.round(box.width / parseFloat(cs.fontSize) * 10) / 10,
      lines: Math.round(box.height / lh), inside: !item || box.right <= item.getBoundingClientRect().right + 1 });
  }
  for (const b of document.querySelectorAll("#set-storage .coll--storage .actions .btn")) {
    const box = b.getBoundingClientRect(), item = b.closest(".coll__item").getBoundingClientRect();
    readable.push({ look, label, text: "button " + (b.getAttribute("aria-label") || ""), w: Math.round(box.width), em: 99, lines: 1, inside: box.right <= item.right + 1 && box.left >= item.left - 1 && box.width >= 32 });
  }
};
const forms = [];
for (const look of ["console", "workbench", "palette", "panes"]) {
  document.documentElement.setAttribute("data-look", look);
  location.hash = "#settings/storage";
  await sleep(600);
  measure(look, "real");
  const here = pageW();
  const saved = [...document.querySelectorAll("#set-storage .storage__name, #set-storage .storage__type, #set-storage .storage__text")].map((e) => [e, e.textContent]);
  let i = 0;
  for (const [e] of saved) e.textContent = LONG[i++ % LONG.length];
  await sleep(200);
  measure(look, "long");
  const long = pageW();
  for (const [e, t1] of saved) e.textContent = t1;
  // the form of a row with spools and the Add form
  const ed = (name) => $(".btn:not(.btn--icon)", rowOf(name));
  for (const what of ["edit", "add"]) {
    (what === "edit" ? ed("Rack 1") : $("#set-storage .storage__bar .btn--primary")).click();
    await until(() => form(), "the form");
    await sleep(500);
    const f = form(), name = f.elements.name.getBoundingClientRect(), box = f.getBoundingClientRect();
    forms.push({ look, what, nameW: Math.round(name.width), formW: Math.round(box.width), inView: box.left >= -1 && box.right <= innerWidth + 1, page: pageW(),
      foot: f.querySelector("[type=submit]").getBoundingClientRect().right <= innerWidth + 1 });
    $(".btn--ghost:not(.detail__close):not(.detail__back)", f).click();
    await until(() => !form() && !$("dialog[open]"), "the form to close");
    await sleep(200);
  }
  forms.push({ look, what: "pages", here, long });
}
out.readable = readable; out.forms = forms; out.vw = document.documentElement.clientWidth;
"""


@pytest.mark.parametrize("width", [1280, 1776, 1024, 768, 390])
def test_the_list_and_its_form_are_readable_in_all_four_looks(hub, tmp_path, width):
    page = _drive_storage(hub, tmp_path, MEASURE, width=width)
    seen = page["readable"]
    assert {c["look"] for c in seen} == {"console", "workbench", "palette", "panes"} and any(c["label"] == "long" for c in seen)
    assert len([c for c in seen if c["label"] == "real" and c["text"].startswith("button")]) >= 4 * 6 * 4
    bad = [(c["look"], c["label"], c["text"], c["w"], c["em"], c["lines"]) for c in seen if c["lines"] > 2 or (c["em"] < 8 and c["lines"] > 1)]
    assert not bad, (width, "a text squeezed to a sliver or wrapped past two lines", bad)
    outside = [(c["look"], c["label"], c["text"]) for c in seen if not c["inside"]]
    assert not outside, (width, "something drawn outside its row", outside)
    for entry in page["forms"]:
        if entry["what"] == "pages":
            for state in ("here", "long"):
                assert entry[state]["sw"] <= entry[state]["cw"], (width, entry["look"], state, "the page scrolls sideways", entry[state])
            continue
        assert entry["inView"] and entry["foot"] and entry["page"]["sw"] <= entry["page"]["cw"], (width, entry)
        assert entry["nameW"] >= 140, (width, entry, "the Name field is squeezed")


OPEN_WIDTH = r"""
const widths = [];
for (const look of ["console", "workbench", "palette", "panes"]) {
  document.documentElement.setAttribute("data-look", look);
  await sleep(300);
  for (const what of ["add", "edit"]) {
    if (what === "add") await openAdd(); else await openEdit("Rack 1");
    await sleep(400);
    const group = $("#set-storage").getBoundingClientRect(), coll = $("#set-storage .coll--storage").getBoundingClientRect();
    const edit = $(".btn:not(.btn--icon)", rowOf("Rack 2")).getBoundingClientRect();
    const list = $(".settings__list"), back = $(".settings__back");
    widths.push({ look, what, group: Math.round(group.width), coll: Math.round(coll.width), editH: Math.round(edit.height), visible: group.width > 0,
                  list: Math.round(list.getBoundingClientRect().width), back: getComputedStyle(back).display !== "none" });
    $(".btn--ghost:not(.detail__close):not(.detail__back)", form()).click();
    await until(() => !form() && !$("dialog[open]"), "the form to close");
    await sleep(200);
  }
}
out.widths = widths;
"""


@pytest.mark.parametrize("width", [1280, 1776])
def test_the_list_keeps_a_readable_width_with_the_add_or_edit_form_open(hub, tmp_path, width):
    """Review R462: in Panes the open editor sat beside Settings' own list and left the group 185 px (rows stacked as cards,
    buttons wrapped). With the form open every look keeps the group and its list wide, and the Edit button on one line."""
    seen = _drive_storage(hub, tmp_path, OPEN_WIDTH, width=width)["widths"]
    assert {(w["look"], w["what"]) for w in seen} == {(l, k) for l in ("console", "workbench", "palette", "panes") for k in ("add", "edit")}
    for w in seen:
        floor = (480, 300) if w["look"] == "panes" else (700, 600)
        assert w["group"] >= floor[0] and w["coll"] >= floor[1], (width, w, "the group is squeezed beside the open form")
        assert w["editH"] <= 48, (width, w, "the Edit button wrapped")
        if w["look"] == "panes":  # the list of groups stays while the group keeps its width, and gives way to Back only when it would not
            assert (w["list"] > 0) == (width >= 1776) and w["back"] == (width < 1776), (width, w, "the Settings list shows or hides wrongly")
