// The steps of tests/test_hub_page_audit.py's Recently added flow, run by tests/hub_drive.mjs in a real browser: the list and its
// filter, a record opened from its title, the photo viewer, Edit by hand (asking for the setup code in place, a field error, Save
// changes), Ask the Label Reader with Discard and Accept, a suggestion that a Save makes stale, Accept and Undo asking for the code
// again when the page is Locked, Undo down to the filament that is empty, Newer and Older, and a record that is no longer kept.
// The requests the page sends are recorded and read. The argument is JSON: {ids: {name: record id}, code: the setup code}. Test-only.
export default async (p) => {
  const { ids, code } = JSON.parse(p.arg);
  // a check waits for its answer (a page under load draws late), then fails with its name
  const ok = (js, what) => p.waitFor(`(() => { try { return ${js}; } catch { return false; } })()`, what, 10000);
  const said = (box, text) => p.waitFor(`[...document.querySelectorAll("${box} .result__text")].some((e) => e.textContent.includes(${JSON.stringify(text)}))`, `"${text}"`, 20000);
  const unlock = async () => {
    await p.waitFor(`document.querySelector("dialog[open] input[name=code]")`, "the unlock dialog");
    await p.type("dialog[open] input[name=code]", code);
    await p.click("dialog[open] [data-action=confirm]");
    await p.waitFor(`!document.querySelector("dialog[open]")`, "the unlock dialog closing");
  };
  const lock = () => p.eval(`SW.setLock("locked")`);
  const body = (path) => p.eval(`(() => { const r = window.__reqs.filter(([u]) => u.endsWith(${JSON.stringify(path)})).pop(); return r && JSON.parse(r[1]); })()`);
  const revisions = () => p.eval(`document.querySelectorAll(".revisions__item").length`);
  const ask = async (note) => {
    await p.type("textarea[name=note]", note);
    await p.click("button", "Ask the Label Reader");
    await p.waitFor(`document.querySelector(".changes__title")`, "the suggestion");
  };

  // the list: four records, the newest first, the filter, the sources in words, the open record
  await p.go("#recent");
  await ok(`document.querySelectorAll(".coll--recent .coll__item").length === 4`, "four rows in the list");
  await ok(`document.querySelector(".coll--recent .coll__item .coll__title").textContent.trim() === "Polymaker PolyTerra PLA Charcoal Black"`, "the newest record first");
  await ok(`document.querySelector(".coll--recent .coll__item .thumb__count").textContent === "2"`, "the photo count on the thumbnail");
  await ok(`document.querySelector(".coll--recent .coll__item .confidence__summary").textContent.includes("Low: check Net weight")`, "the confidence summary");
  await ok(`document.querySelector("[data-id='${ids.cloud}'] [data-col=status]").textContent.includes("Edited by hand")`, "the state badge of a revised record");
  await ok(`document.querySelector("[data-id='${ids.cloud}'] [data-col=title]").textContent.includes("From a phone photo")`, "a web addition with a photo");
  await ok(`document.querySelector("[data-id='${ids.hand}'] [data-col=title]").textContent.includes("Added by hand")`, "a phone addition without a photo is typed in");
  await ok(`document.querySelector("[data-id='${ids.long}'] [data-col=title]").textContent.includes("From the Weigh Station")`, "the Weigh Station");
  await p.click(".segmented__option", "To check");
  await ok(`document.querySelectorAll(".coll--recent .coll__item").length === 1`, "the To check filter");
  await p.click(".segmented__option", "All");
  await ok(`document.querySelectorAll(".coll--recent .coll__item").length === 4`, "All again");
  await p.click(".coll__sort", "Filament");
  await ok(`document.querySelector("[role=columnheader][aria-sort=ascending]")`, "sorted by Filament");
  await p.click(".coll__title", "Polymaker PolyTerra PLA Charcoal");
  await p.waitFor(`location.hash === "#recent/${ids.local}" && document.querySelector(".detail__title")`, "the record");
  await ok(`document.activeElement.classList.contains("detail__title")`, "focus on the record's title");
  await p.eval(`window.__reqs = []; const f = window.fetch; window.fetch = (u, i) => { if (i && i.body) window.__reqs.push([String(u), i.body]); return f(u, i); };`);

  // the record: marks next to the values, the viewer
  await ok(`document.querySelector(".kv__value .status--warn").textContent.includes("Medium: filled in by the Hub")`, "the medium mark");
  await ok(`document.querySelector(".kv__value .status--bad").textContent.includes("Low: check this")`, "the low mark");
  await p.click(".thumb--m");
  await p.waitFor(`document.querySelector("dialog.viewer[open] .dialog__title").textContent === "Photo 1 of 2"`, "the photo viewer");
  await p.press("ArrowRight");
  await p.waitFor(`document.querySelector("dialog.viewer[open] .dialog__title").textContent === "Photo 2 of 2"`, "the next photo");
  await p.press("Escape");
  await p.waitFor(`!document.querySelector("dialog[open]")`, "the viewer closing");
  await ok(`document.activeElement.classList.contains("thumb--m")`, "focus back on the thumbnail");

  // Edit by hand: asks for the code in place, a field error, only the changed fields are sent, the Hub's filament sentence
  await p.click("button", "Edit by hand");
  await unlock();
  await p.waitFor(`document.querySelector("input[name=empty_weight]")`, "the fields");
  await p.type("input[name=empty_weight]", "150");
  await p.type("input[name=nozzle]", "abc");
  await p.click("button[type=submit]", "Save changes");
  await ok(`document.querySelector("input[name=nozzle]").getAttribute("aria-invalid") === "true"`, "the field error");
  await ok(`!window.__reqs.some(([u]) => u.endsWith("/apply"))`, "nothing is saved while a field is wrong");
  await p.type("input[name=nozzle]", "230");
  await p.click("button[type=submit]", "Save changes");
  await said(".recent__main", "Saved 2 changes: Empty spool weight, Nozzle.");
  const sent = await body("/apply");
  if (JSON.stringify(sent.values) !== JSON.stringify({ tare: 150, nozzle: 230 }) || sent.item !== 0 || sent.proposal !== undefined) throw new Error("the apply body: " + JSON.stringify(sent));
  const made = await p.eval(`(document.querySelector(".recent__main .result__text").textContent.match(/filament (\\d+) \\(new\\)/) || [])[1]`);
  if (!made) throw new Error("the filament sentence of the Hub is missing");
  await ok(`document.querySelector(".revisions__item b").textContent === "Revision 1"`, "Revision 1 in the list");

  // Ask the Label Reader: the empty note, the suggestion naming the engine, Discard, a Save that makes it stale
  await p.click("button", "Ask the Label Reader");
  await ok(`document.querySelector("textarea[name=note]").getAttribute("aria-invalid") === "true"`, "the empty note is refused");
  await ask("nozzle is 235");
  await ok(`document.querySelector(".changes__title").textContent === "The Label Reader (On this Hub · label-reader) suggests 1 change"`, "the suggestion names the engine");
  await ok(`document.querySelector(".changes__item").textContent.includes("230 °C") && document.querySelector(".changes__item").textContent.includes("235 °C")`, "the before-and-after change");
  const asked = await body("/revise");
  if (asked.note !== "nozzle is 235" || asked.item !== 0) throw new Error("the revise body: " + JSON.stringify(asked));
  await p.click("button", "Discard");
  await said(".recent__main", "Suggestion discarded. Nothing changed.");
  await ask("nozzle is 235");
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=bed]")`, "the fields again");
  await p.type("input[name=bed]", "58");
  await p.click("button[type=submit]", "Save changes");
  await said(".recent__main", "Saved 1 change: Bed.");
  await ok(`!document.querySelector(".changes__title")`, "a Save drops the suggestion the Hub no longer holds");
  await ok(`document.activeElement.textContent.trim() !== "Accept"`, "focus is not on a stale Accept");

  // Accept and Undo ask for the code again when the page is Locked
  await ask("nozzle is 235");
  await lock();
  await p.click("button", "Accept");
  await unlock();
  await said(".recent__main", "Accepted. 1 field changed; revision 3 keeps the old values.");
  const accepted = await body("/apply");
  if (!accepted.proposal || accepted.values !== undefined) throw new Error("the accept body: " + JSON.stringify(accepted));
  await ok(`document.querySelectorAll(".revisions__item").length === 3`, "three revisions");
  await lock();
  await p.click("button", "Undo revision 3");
  await unlock();
  await said(".revisions", "Revision 3 undone. Nozzle is 230 °C again.");
  const undone = await body("/undo");
  if (undone.revision !== 3) throw new Error("the undo body: " + JSON.stringify(undone));
  await ok(`[...document.querySelectorAll(".revisions__item")][0].dataset.state === "undone"`, "revision 3 struck through");

  // Undo down to Revision 1: the filament that is empty after the undo is the one that was made, in the message and in the list
  await p.click("button", "Undo revision 2");
  await said(".revisions", "Revision 2 undone.");
  await p.click("button", "Undo revision 1");
  await said(".revisions", `Filament ${made} has no spools left; it was not deleted.`);
  await ok(`[...document.querySelectorAll(".revisions__item")].pop().textContent.includes("Filament ${made} has no spools left (not deleted)")`, "the empty filament in the revision list");
  await ok(`document.querySelectorAll(".revisions__item[data-state=undone]").length === 3`, "all three revisions undone");

  // Newer and Older, and a record that is no longer kept
  await p.click(".recent__older");
  await p.waitFor(`location.hash === "#recent/${ids.long}"`, "the older record");
  await p.go("#recent/000000000000");
  await ok(`document.querySelector(".error-state__title").textContent.startsWith("This record is no longer kept.")`, "the record that is gone");
  await p.click("a.btn", "Back to Recently added");
  await p.waitFor(`location.hash === "#recent" && document.querySelector(".coll--recent")`, "back to the list");
};
