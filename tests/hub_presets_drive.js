// Runs in the Hub page (tests/page_drive.mjs): presses each control of the Slicer presets section and returns what the page
// then shows. The test (server/tests/test_hub_presets_ui.py) holds the server side: which Hub routes were reached, in order.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) {
  for (let i = 0; i < 400; i++) { const v = look(); if (v) return v; await sleep(100); }
  throw new Error("waited for " + what + ", it did not come; the page shows: " + JSON.stringify([...document.querySelectorAll(".result, .toast, dialog[open]")].map((e) => [e.className, e.dataset.state, e.textContent.trim().slice(0, 120)])));
}
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
const out = {};
const T = SW.t;
let step = "opening the section";
// a redraw after a change reads the section again: until it has, its rows are not in the page
const settled = () => until(() => !$('main [aria-busy="true"]:not(button)'), "the section to finish reading");
try {

location.hash = "#presets";
await until(() => $('[data-action="build"]') && $('[data-action="restore-deleted"]') && $(".coll--lines .coll__item"), "the section");
// the page's first read of its trust (the lock chip stops loading) comes first: it writes the lock state, and a code given
// before it is undone; then the code, as the unlock dialog leaves it
await until(() => !$(".chip--lock .skeleton__line") && !$('[aria-busy="true"]:not(button)'), "the lock chip and the section to settle");
SW.setLock("unlocked", { code: "__CODE__" });
out.title = text($("h1"));
out.head = [text($(".page-head__meta")), text($(".page-head__actions"))];
out.cards = [...document.querySelectorAll("main .card > h2")].map(text);
out.slicerSync = text([...document.querySelectorAll("main .card p")].find((p) => p.textContent.includes(T("presets_sync_ok"))));
out.columns = [...document.querySelectorAll(".coll--lines .coll__head [role=columnheader]")].map(text);
out.rows = document.querySelectorAll(".coll--lines .coll__item").length;

step = "Build now";
// Build now (the header's primary button), then Bring back deleted presets: each says its result in the Build card
$('[data-action="build"]').click();
$('[data-action="build"]').click();                 // pressed again at once: one request only
out.build = await until(() => text($('.result[data-state="ok"] .result__text')), "the result of Build now");
$('[data-action="restore-deleted"]').click();
out.restore = await until(() => { const r = text($('.result[data-state="ok"] .result__text')); return r && r !== out.build ? r : null; }, "the result of Bring back deleted presets");

step = "Show what would change, Accept these";
// Show what would change, then Accept these: the first time the Hub says the list is out of date (409)
await until(() => $('[data-action="show-updates"]'), "Show what would change in: " + text($("#presets-updates")));
$('[data-action="show-updates"]').click();
await until(() => $('[data-action="accept"]'), "Accept these under the list");
out.shown = { result: text($("#presets-updates .result__text")), items: [...document.querySelectorAll("#presets-updates .result li")].map(text) };
$('[data-action="accept"]').click();
out.stale = await until(() => text($('#presets-updates .result[data-state="warn"] .result__text')), "the out of date warning");
out.staleAcceptLeft = !!$('[data-action="accept"]');
$('[data-action="show-updates"]').click();
await until(() => $('[data-action="accept"]'), "Accept these under the list again");
$('[data-action="accept"]').click();
$('[data-action="accept"]').click();
out.accepted = await until(() => text($('#presets-updates .result[data-state="ok"] .result__text')), "the result of Accept these");

step = "Set parent, Bambu Studio";
await settled();
const set = await until(() => $('[data-action="set-parent"]'), "a Set parent button");
out.setParentName = set.getAttribute("aria-label");
out.lineId = set.closest(".coll__item").dataset.id;
out.lineName = text($(".coll__title", set.closest(".coll__item")));
set.click();
const items = await until(() => { const l = [...document.querySelectorAll(".menu__item")]; return l.length ? l : null; }, "the Set parent menu");
out.menu = items.map(text);
items[0].click();
const dlg = await until(() => $("dialog[open]"), "the Set parent dialog");
out.dialogTitle = text($(".dialog__title", dlg));
out.dialogSub = text($(".dialog__text", dlg));
const pick = $("select", dlg);
out.options = [...pick.options].map((o) => o.value);
out.dialogLabel = text($("label", dlg));
pick.value = "Generic PLA";
$('[data-action="confirm"]', dlg).click();
await until(() => !$("dialog[open]"), "the dialog to close");
out.parentSaved = await until(() => text($('.coll__row--result .result[data-state="ok"] .result__text')), "the saved result");
out.parentShown = await until(() => text($(`.coll--lines .coll__item[data-id="${out.lineId}"] .coll__cell[data-col="bambu_parent"]`)), "the new parent in the row");

// the Orca Slicer parent: Cancel sends nothing, Save sends the pick with target orca
step = "Set parent, Orca Slicer";
const row = () => $(`.coll--lines .coll__item[data-id="${out.lineId}"]`);       // gone while the section is read again
const rowOf = () => until(row, "the row of the line");
const openOrca = async () => {
  await settled();
  (await rowOf()).querySelector('[data-action="set-parent"]').click();
  const m = await until(() => { const l = [...document.querySelectorAll(".menu__item")]; return l.length ? l : null; }, "the Set parent menu again");
  out.menuOrca = m.map(text);
  m[1].click();
  return await until(() => $("dialog[open]"), "the Orca Slicer dialog");
};
let d2 = await openOrca();
out.orcaSub = text($(".dialog__text", d2));
out.orcaOptions = [...$("select", d2).options].map((o) => o.value);
$('[data-action="cancel"]', d2).click();
await until(() => !$("dialog[open]"), "Cancel to close the dialog");
d2 = await openOrca();
$("select", d2).value = "Orca Basic";
$('[data-action="confirm"]', d2).click();
await until(() => !$("dialog[open]"), "the Orca dialog to close");
out.orcaSaved = await until(() => row() && text($('.coll__row--result .result[data-state="ok"] .result__text', row())), "the Orca saved result");
return out;
} catch (e) {
  throw new Error("in the step \"" + step + "\": " + e.message);
}
