// Runs in the Hub page (tests/page_drive.mjs): presses each control of the Slicer presets section and returns what the page
// then shows. The test (server/tests/test_hub_presets_ui.py) holds the server side: which Hub routes were reached, in order.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(look, what) {
  for (let i = 0; i < 150; i++) { const v = look(); if (v) return v; await sleep(100); }
  throw new Error("waited for " + what + ", it did not come; the page shows: " + JSON.stringify([...document.querySelectorAll(".result, .toast, dialog[open]")].map((e) => [e.className, e.dataset.state, e.textContent.trim().slice(0, 120)])));
}
const $ = (s, root = document) => root.querySelector(s);
const text = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : null);
const out = {};
const T = SW.t;

location.hash = "#presets";
await until(() => $('[data-action="build"]') && $('[data-action="restore-deleted"]') && $(".coll--lines .coll__item"), "the section");
await until(() => !$(".chip--lock .skeleton__line"), "the lock chip");      // the page has read its trust; then the code, as the unlock dialog leaves it
SW.setLock("unlocked", { code: "__CODE__" });
out.title = text($("h1"));
out.head = [text($(".page-head__meta")), text($(".page-head__actions"))];
out.cards = [...document.querySelectorAll("main .card > h2")].map(text);
out.slicerSync = text([...document.querySelectorAll("main .card p")].find((p) => p.textContent.includes(T("presets_sync_ok"))));
out.columns = [...document.querySelectorAll(".coll--lines .coll__head [role=columnheader]")].map(text);
out.rows = document.querySelectorAll(".coll--lines .coll__item").length;

// Build now (the header's primary button), then Bring back deleted presets: each says its result in the Build card
$('[data-action="build"]').click();
out.build = await until(() => text($('.result[data-state="ok"] .result__text')), "the result of Build now");
$('[data-action="restore-deleted"]').click();
out.restore = await until(() => { const r = text($('.result[data-state="ok"] .result__text')); return r && r !== out.build ? r : null; }, "the result of Bring back deleted presets");

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
out.accepted = await until(() => text($('#presets-updates .result[data-state="ok"] .result__text')), "the result of Accept these");

// Set parent: its menu, then the dialog
const set = $('[data-action="set-parent"]');
out.setParentName = set.getAttribute("aria-label");
out.lineId = set.closest(".coll__item").dataset.id;
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
out.parentShown = text($(`.coll--lines .coll__item[data-id="${out.lineId}"] .coll__cell[data-col="bambu_parent"]`));
return out;
