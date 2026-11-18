"""Settings > Backups and restore on the Hub page: the backup password, "Encrypted" in the list and the restore dialog's password
(DECISIONS R84 sections 7 and 9.3), in a real headless browser. The Hub side of those routes (HD4) is not built yet, so the page
runs against a stub Hub in the page itself (fetch and XMLHttpRequest answer the routes of 9.3: backups/list, backups/password,
backups/password/remove, restore/upload, restore/password, job); every other route is the Hub's real one. Also the group in all
four looks at 1280 and on a phone (390 px). The same skip rules as the page audit: no Node 22 or no browser is a skip (a failure
with AUT5_REQUIRED=1)."""
from __future__ import annotations

import pytest

from test_hub_page_audit import hub_app  # noqa: F401
from test_hub_presets_ui import _drive, T, hub  # noqa: F401
from test_hub_settings import PRELUDE

# the texts the page holds itself until the catalogue has them (setup_backup.js BK_TEXT)
WARNING = "Write this password down. Without it these backups cannot be restored, and Spoolwarden cannot recover it."
WRONG = "Wrong password, or the file is damaged. Nothing was changed."

STUB = r"""
const hub = { set: false, minimum: 10, refuse: false, calls: [], needs: true, rows: [
  { name: "a", at: "2026-11-16 03:00", kind: "daily", size: 5242880, download: "a.zip.enc", encrypted: true },
  { name: "b", at: "2026-11-15 03:00", kind: "daily", size: 5242880, download: "b.zip", encrypted: false },
  { name: "c", at: "2026-11-14 11:20", kind: "here", size: 3145728, download: "c.zip", encrypted: false }] };
window.__hub = hub;
const reply = (status, data) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const realFetch = window.fetch.bind(window);
window.fetch = async (u, init) => {
  const path = String(u).replace(/^.*\/setup\/api\//, ""), body = init && init.body ? JSON.parse(init.body) : {};
  const mine = ["backups/list", "backups/password", "backups/password/remove", "restore/password", "job", "restore/forget"].includes(path);
  if (!mine) return realFetch(u, init);
  if (hub.refuse || body.code !== "__CODE__") return reply(403, { error: "wrong code", field: "code" });
  hub.calls.push({ path, password: body.password, name: body.name, sha256: body.sha256, confirm: body.confirm });
  if (path === "backups/list") return reply(200, { backups: hub.rows, keep_days: 14, folder: "/var/backups/filament-kit", password_set: hub.set });
  if (path === "backups/password") {
    if (body.password.length < hub.minimum) return reply(400, { error: "too_short", text: "The server wants at least " + hub.minimum + " characters." });
    hub.set = true; hub.last = body.password;
    return reply(200, { set: true });
  }
  if (path === "backups/password/remove") { hub.set = false; return reply(200, { set: false }); }
  if (path === "restore/password") return body.password === "right password" ? reply(200, { ok: true }) : reply(400, { error: "wrong_password", text: "Wrong password, or the file is damaged. Nothing was changed." });
  if (path === "restore/forget") return reply(200, { ok: true });
  return reply(200, { job: "restore" });
};
window.XMLHttpRequest = class {
  constructor() { this.upload = {}; this.status = 0; this.responseText = ""; }
  open(m, u) { this.url = u; }
  setRequestHeader() {}
  send() {
    hub.calls.push({ path: "restore/upload" });
    setTimeout(() => {
      this.status = 200;
      this.responseText = JSON.stringify(hub.needs ? { needs_password: true, sha256: "ab".repeat(32) }
        : { host: "hub", created: "2026-11-16", kit: "1.0", files: 4, spoolman: false, modules: ["backup"], replaces_data: true, other_host: false, sha256: "cd".repeat(32) });
      this.onload();
    }, 20);
  }
};
"""

HELPERS = r"""
const OLD = () => shown($('.settings__group[data-id="backups"] .group__body > .banner'));
const pane = () => $("#set-backups-password");
const pwField = (name) => pane().elements[name].closest(".field");
const setPw = (name, value) => { const c = pane().elements[name]; c.value = value; c.dispatchEvent(new Event("input", { bubbles: true })); c.dispatchEvent(new Event("change", { bubbles: true })); };
const fieldErr = (name) => { const e = $(".field__error", pwField(name)); return e && !e.hidden ? text(e) : null; };
const paneText = () => text($(".backup-password > p"));
const press = async (label) => { [...pane().querySelectorAll("button")].find((b) => text(b) === label).click(); await sleep(250); };
const paneResult = () => text($(".result__text", pane()));
const rowsOf = () => [...document.querySelectorAll('.coll--backups > .coll__item[data-id]')];
const marked = () => rowsOf().map((r) => [r.dataset.id, !!$(".status", $('[data-col="title"]', r))]);
const calls = () => window.__hub.calls.map((c) => c.path);
const ready = async () => {
  await loaded();
  location.hash = "#settings/backups";
  await unlock();
  await until(() => pane(), "the backup password");
  await sleep(200);
};
"""


def _drive_backups(hub, tmp_path, body, width=1280, look="console", before=""):
    script = (PRELUDE + HELPERS + STUB.replace("hub.", "window.__hub.") * 0 + "const sleep2 = 0;\n"
              + STUB + f'document.documentElement.setAttribute("data-look", "{look}");\n' + before + "\nawait ready();\nconst out = {};\n" + body + "\nreturn out;\n")
    return _drive(hub, tmp_path, script, width=width)


def test_a_password_is_set_with_the_checks_the_sentence_and_the_old_warning_goes(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, r"""
out.start = { state: paneText(), heading: text($(".backup-password .settings__heading")), warning: shown($(".backup-password .banner")) && text($(".backup-password .banner")),
              oldWarning: OLD(),
              button: text(pane().querySelector("[type=submit]")), remove: !![...pane().querySelectorAll("button")].find((b) => text(b) === "Remove the backup password"),
              types: [pane().elements.backup_password.type, pane().elements.backup_password_again.type] };
await press("Set a backup password");                          // nothing typed
out.empty = fieldErr("backup_password");
setPw("backup_password", "short"); await press("Set a backup password");
out.short = fieldErr("backup_password");
setPw("backup_password", "long enough pw"); setPw("backup_password_again", "long enough px"); await press("Set a backup password");
out.mismatch = fieldErr("backup_password_again");
out.callsBefore = calls();
// the Hub's own minimum (the stub wants 12): its refusal is shown at the field and nothing is set
window.__hub.minimum = 12;
setPw("backup_password", "elevenchars"); setPw("backup_password_again", "elevenchars"); await press("Set a backup password");
out.refused = { err: fieldErr("backup_password"), set: window.__hub.set };
window.__hub.minimum = 10;
setPw("backup_password", "long enough pw"); setPw("backup_password_again", "long enough pw"); await press("Set a backup password");
await until(() => pane() && paneResult(), "the result");
out.after = { state: paneText(), result: paneResult(), button: text(pane().querySelector("[type=submit]")), label: text(pwField("backup_password").querySelector(".field__label")),
              remove: !![...pane().querySelectorAll("button")].find((b) => text(b) === "Remove the backup password"), set: window.__hub.set, sent: window.__hub.last,
              values: [pane().elements.backup_password.value, pane().elements.backup_password_again.value],
              shown: document.body.innerText.includes("long enough pw"), oldWarning: OLD(),
              sentCalls: calls().filter((c) => c === "backups/password").length };
""")
    assert page["start"]["state"] == "No backup password is set. New backups are not encrypted."
    assert page["start"]["heading"] == "Backup password" and page["start"]["warning"].endswith(WARNING)
    assert page["start"]["oldWarning"] is True and page["start"]["remove"] is False and page["start"]["types"] == ["password", "password"]
    assert page["start"]["button"] == "Set a backup password"
    assert page["empty"] == "Use at least 10 characters." and page["short"] == "Use at least 10 characters."
    assert page["mismatch"] == "The two passwords do not match." and "backups/password" not in page["callsBefore"]
    assert page["refused"] == {"err": "The server wants at least 12 characters.", "set": False}
    after = page["after"]
    assert after["state"] == "A backup password is set. Every new backup is encrypted with it." and after["result"] == "The backup password is set. New backups are encrypted."
    assert after["button"] == "Change the backup password" and after["label"] == "New backup password" and after["remove"] is True
    assert after["set"] is True and after["sent"] == "long enough pw" and after["sentCalls"] == 2
    # never shown again: the fields are empty and the text is nowhere on the page
    assert after["values"] == ["", ""] and after["shown"] is False and after["oldWarning"] is False


def test_a_password_is_changed_and_removed_after_the_question(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, r"""
window.__hub.set = true;
location.hash = "#settings"; await sleep(100); location.hash = "#settings/backups";
const again = $('.settings__group[data-id="backups"]');
SW.setLock("locked"); await sleep(100);
SW.setLock("unlocked", { code: "__CODE__" });
await until(() => pane() && paneText().startsWith("A backup"), "the list read again");
out.state = paneText();
setPw("backup_password", "another password"); setPw("backup_password_again", "another password"); await press("Change the backup password");
out.changed = { sent: window.__hub.last, result: paneResult() };
// Remove asks first: Cancel changes nothing
await press("Remove the backup password");
let dlg = await until(() => $("dialog[open]"), "the question");
out.ask = { title: text($(".dialog__title", dlg)), body: text($(".dialog__text", dlg)), role: dlg.getAttribute("role") };
$('[data-action="cancel"]', dlg).click();
await until(() => !$("dialog[open]"), "the question to close");
out.cancelled = { set: window.__hub.set, removes: calls().filter((c) => c === "backups/password/remove").length };
await press("Remove the backup password");
dlg = await until(() => $("dialog[open]"), "the question");
$('[data-action="confirm"]', dlg).click();
await until(() => !window.__hub.set && !$("dialog[open]"), "the removal");
await until(() => pane() && paneText().startsWith("No backup"), "the pane again");
out.removed = { state: paneText(), result: paneResult(), button: text(pane().querySelector("[type=submit]")), remove: !![...pane().querySelectorAll("button")].find((b) => text(b) === "Remove the backup password"),
                oldWarning: OLD() };
""")
    assert page["state"] == "A backup password is set. Every new backup is encrypted with it."
    assert page["changed"] == {"sent": "another password", "result": "The backup password is set. New backups are encrypted."}
    assert page["ask"]["title"] == "Remove the backup password?" and page["ask"]["role"] == "alertdialog"
    assert "Backups already made stay encrypted" in page["ask"]["body"]
    assert page["cancelled"] == {"set": True, "removes": 0}
    assert page["removed"] == {"state": "No backup password is set. New backups are not encrypted.", "result": "The backup password is removed. New backups are plain; backups already made stay encrypted.",
                               "button": "Set a backup password", "remove": False, "oldWarning": True}


def test_the_list_says_encrypted_on_the_files_that_are(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, r"""
out.some = marked();
out.badge = text($(".coll--backups .status"));
window.__hub.rows.forEach((r) => { r.encrypted = false; });
SW.setLock("locked"); await sleep(100);
SW.setLock("unlocked", { code: "__CODE__" });
await until(() => pane() && marked().length, "the list");
await sleep(200);
out.none = marked();
""")
    assert page["some"] == [["a", True], ["b", False], ["c", False]] and page["badge"] == "Encrypted"
    assert page["none"] == [["a", False], ["b", False], ["c", False]]


RESTORE = r"""
const choose = async () => {
  const input = $('.settings__group[data-id="backups"] input[type=file]');
  const dt = new DataTransfer(); dt.items.add(new File(["x"], "backup.zip.enc", { type: "application/zip" }));
  input.files = dt.files; input.dispatchEvent(new Event("change", { bubbles: true }));
  await sleep(150);
  [...document.querySelectorAll(".steps button")].find((b) => text(b) === "Upload and check").click();
  await until(() => [...document.querySelectorAll(".steps button")].find((b) => text(b) === "Restore…"), "the checked upload");
};
const askRestore = async () => {
  [...document.querySelectorAll(".steps button")].find((b) => text(b) === "Restore…").click();
  return until(() => $("dialog[open]"), "the restore question");
};
"""


def test_the_restore_dialog_asks_the_password_only_for_a_file_the_stored_one_does_not_open(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, RESTORE + r"""
out.accept = $('.settings__group[data-id="backups"] input[type=file]').accept;
await choose();
out.summary = text($(".settings__summary"));
let dlg = await askRestore();
const field = () => $('input[name="restore_password"]', dlg);
out.field = { there: !!field(), type: field().type, label: text($("label[for=" + field().id + "]", dlg)) };
const word = [...dlg.querySelectorAll("input")].find((i) => i !== field());
const confirm = async () => { $('[data-action="confirm"]', dlg).click(); await sleep(400); };
word.value = "restore"; word.dispatchEvent(new Event("input", { bubbles: true }));
await confirm();                                               // nothing typed
out.empty = text($(".field__error", field().closest(".field")));
field().value = "wrong one"; await confirm();
out.wrong = { result: text($(".dialog__result .result__text", dlg)), open: dlg.open, job: calls().includes("job"), focus: document.activeElement === field() };
field().value = "right password"; await confirm();
await until(() => !dlg.open, "the dialog to close");
await sleep(300);
out.right = { job: window.__hub.calls.filter((c) => c.path === "job").map((c) => [c.confirm, c.sha256]), order: calls().filter((c) => c === "restore/password" || c === "job") };
""")
    assert page["accept"] == ".zip,.enc,application/zip"
    assert page["summary"].startswith("This backup is encrypted.")
    assert page["field"] == {"there": True, "type": "password", "label": "Password of this backup"}
    assert page["empty"] == "Enter the password of this backup."
    assert page["wrong"] == {"result": WRONG, "open": True, "job": False, "focus": True}
    assert page["right"]["job"] == [["restore", "ab" * 32]] and page["right"]["order"] == ["restore/password", "restore/password", "job"]


def test_a_file_the_stored_password_opens_has_no_password_field(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, RESTORE + r"""
window.__hub.needs = false;
await choose();
const dlg = await askRestore();
out.fields = dlg.querySelectorAll("input").length;
const word = dlg.querySelector("input");
word.value = "restore"; word.dispatchEvent(new Event("input", { bubbles: true }));
$('[data-action="confirm"]', dlg).click();
await until(() => !dlg.open, "the dialog to close");
out.calls = calls().filter((c) => c === "restore/password" || c === "job");
""")
    assert page["fields"] == 1 and page["calls"] == ["job"]


def test_locked_the_group_shows_no_password_and_a_refusal_for_the_code_locks_again(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, r"""
setPw("backup_password", "long enough pw"); setPw("backup_password_again", "long enough pw");
window.__hub.refuse = true;
await press("Set a backup password");
await sleep(300);
out.refused = { lock: SW.lock.state, set: window.__hub.set, pane: !!pane() };
window.__hub.refuse = false;
await sleep(300);
out.lockedList = { pane: !!pane(), note: !![...document.querySelectorAll('.settings__group[data-id="backups"] .banner')].find((b) => /Unlock/.test(text(b))) };
""")
    assert page["refused"]["lock"] == "locked" and page["refused"]["set"] is False
    assert page["lockedList"] == {"pane": False, "note": True}


MEASURE = r"""
const view = [];
for (const look of ["console", "workbench", "palette", "panes"]) {
  document.documentElement.setAttribute("data-look", look);
  await sleep(300);
  for (const state of ["plain", "set"]) {
    window.__hub.set = state === "set";
    SW.setLock("locked"); await sleep(60);
    SW.setLock("unlocked", { code: "__CODE__" });
    await until(() => pane() && paneText().startsWith(state === "set" ? "A backup" : "No backup"), "the pane");
    await sleep(200);
    pane().scrollIntoView();
    const rows = (el) => { const r = document.createRange(); r.selectNodeContents(el); return new Set([...r.getClientRects()].filter((q) => q.width > 0).map((q) => Math.round(q.top / 4))).size; };
    const lines = (el) => { const cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4; return Math.round(el.getBoundingClientRect().height / lh); };
    const box = pane().getBoundingClientRect();
    view.push({ look, state, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
      fields: [...pane().querySelectorAll(".field__control")].map((c) => Math.round(c.getBoundingClientRect().width)),
      paneW: Math.round(box.width), warn: lines($(".backup-password .banner__text")), btn: [...pane().querySelectorAll(".actions .btn")].map((b) => [text(b), rows(b), shown(b)]),
      titles: rowsOf().map((r) => lines($(".coll__title", r))),
      badge: rowsOf().slice(0, 1).map((r) => { const b = $(".status", r).getBoundingClientRect(), rr = r.getBoundingClientRect(); return b.left >= rr.left - 1 && b.right <= rr.right + 1 && b.width > 20; }),
      oldWarning: OLD() });
  }
}
out.view = view;
"""


@pytest.mark.parametrize("width", [1280, 390])
def test_the_group_reads_in_all_four_looks(hub, tmp_path, width):
    page = _drive_backups(hub, tmp_path, MEASURE, width=width)
    assert {v["look"] for v in page["view"]} == {"console", "workbench", "palette", "panes"} and len(page["view"]) == 8
    for v in page["view"]:
        tag = (width, v["look"], v["state"])
        assert v["sw"] <= v["cw"], (tag, "the page scrolls sideways", v)
        assert all(w >= 180 for w in v["fields"]) and len(v["fields"]) == 2, (tag, "a password field is squeezed", v)
        assert v["warn"] <= 3, (tag, "the sentence is squeezed", v)
        assert all(shown_ and lines <= 2 for _, lines, shown_ in v["btn"]), (tag, v["btn"])
        assert [b[0] for b in v["btn"]] == (["Change the backup password", "Remove the backup password"] if v["state"] == "set" else ["Set a backup password"]), tag
        assert all(n <= 2 for n in v["titles"]) and v["badge"] == [True], (tag, "the list row is squeezed", v)
        assert v["oldWarning"] is (v["state"] == "plain"), tag


EDGE = r"""
const view = [];
await until(() => pane() && paneText().startsWith("No backup"), "the pane");
const box = $(".backup-password");
for (const look of ["console", "palette"]) {
  document.documentElement.setAttribute("data-look", look);
  for (const w of [330, 360]) {
    box.style.width = w + "px"; box.style.maxWidth = "none";           // the group's own width, either side of the 344 px edge
    await sleep(200);
    const ban = $(".banner", box), icon = $(".icon", ban), t = $(".banner__text", ban);
    const cs = getComputedStyle(t), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4;
    view.push({ look, w, box: Math.round(box.getBoundingClientRect().width), above: icon.getBoundingClientRect().bottom <= t.getBoundingClientRect().top + 1,
      beside: t.getBoundingClientRect().left >= icon.getBoundingClientRect().right - 1 && Math.abs(t.getBoundingClientRect().top - icon.getBoundingClientRect().top) < 8,
      full: Math.round(t.getBoundingClientRect().width), banner: Math.round(ban.getBoundingClientRect().width), lines: Math.round(t.getBoundingClientRect().height / lh) });
  }
}
out.view = view;
"""


def test_the_warning_sentence_changes_place_at_the_344_px_edge(hub, tmp_path):
    page = _drive_backups(hub, tmp_path, EDGE, width=1280)
    assert len(page["view"]) == 4
    for v in page["view"]:
        tag = (v["look"], v["w"])
        assert v["box"] == v["w"], (tag, v)
        assert v["lines"] <= 3, (tag, "the sentence is squeezed", v)
        if v["w"] < 344:      # under the edge: icon above, the sentence has the banner's full width inside its padding
            assert v["above"] and not v["beside"] and v["full"] >= v["banner"] - 2 * 12 - 1, (tag, v)
        else:                 # over it: icon and sentence share a row
            assert v["beside"] and not v["above"] and v["full"] < v["banner"] - 20 - 12 - 2 * 12 + 1, (tag, v)
