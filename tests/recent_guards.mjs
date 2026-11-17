// NOT a test by itself: a steps module (it does nothing when run alone). tests/test_hub_recent.py::test_recently_added_keeps_what_belongs_to_a_record_and_sends_each_press_once runs it through tests/hub_drive.mjs; it fails there when a check fails.
// Steps of tests/test_hub_recent.py's guards test, run by tests/hub_drive.mjs: what belongs to one record stays with it (a typed note,
// an open edit form across a redraw of the page), a wrong value shows the catalogue's text and never a key, and one press is one
// request (Save, Undo, and an Ask asked again after the record was drawn again). Test-only; the argument is JSON {ids, code}.
export default async (p) => {
  const { ids, code } = JSON.parse(p.arg);
  const ok = (js, what) => p.waitFor(`(() => { try { return ${js}; } catch { return false; } })()`, what, 10000);
  const unlock = async () => {
    await p.waitFor(`document.querySelector("dialog[open] input[name=code]")`, "the unlock dialog");
    await p.type("dialog[open] input[name=code]", code);
    await p.click("dialog[open] [data-action=confirm]");
    await p.waitFor(`!document.querySelector("dialog[open]")`, "the unlock dialog closing");
  };
  const count = (path) => p.eval(`window.__reqs.filter(([u]) => u.endsWith(${JSON.stringify(path)})).length`);
  const twice = (label) => p.eval(`(() => { const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === ${JSON.stringify(label)}); b.click(); b.click(); })()`);
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const noKeys = (what) => ok(`!/\\b(recent|common|changes|revision|photo|confidence|status|add|detail)_[a-z_]+\\b/.test(document.querySelector("main").innerText)`, "no raw catalogue key on screen: " + what);

  // the raw-key check itself sees a key (in a template literal a plain backslash-b is a backspace and would match nothing)
  await p.eval(`document.querySelector("main").append(Object.assign(document.createElement("p"), { id: "probe-key", textContent: "recent_error_range" }))`);
  if (await p.eval(`!/\\b(recent|common)_[a-z_]+\\b/.test(document.querySelector("main").innerText)`)) throw new Error("the raw-key check does not see a key");
  await p.eval(`document.getElementById("probe-key").remove()`);

  // a note typed at one record does not move to the next one
  await p.go("#recent/" + ids.local);
  // one wrapper of fetch for the whole run: it records the writes, and (by window.__net) slows the reply of a Save or fails it
  await p.eval(`window.__reqs = []; window.__net = { applyDelay: 0, failSave: 0 }; window.__proposals = []; const f = window.fetch; window.fetch = async (u, i) => {
    u = String(u);
    if (i && i.body) window.__reqs.push([u, i.body]);
    const wait = (ms) => new Promise((d) => setTimeout(d, ms));
    if (u.endsWith("/apply") && i && i.body && JSON.parse(i.body).values && window.__net.failSave) {
      await wait(window.__net.failSave);
      return new Response(JSON.stringify({ error: "the Hub is out of order" }), { status: 500, headers: { "Content-Type": "application/json" } });
    }
    const r = await f(u, i);
    if (u.endsWith("/revise")) r.clone().json().then((j) => window.__proposals.push(j.proposal));
    if (u.endsWith("/apply") && window.__net.applyDelay) await wait(window.__net.applyDelay);
    return r;
  };`);
  const net = (o) => p.eval(`Object.assign(window.__net, { applyDelay: 0, failSave: 0 }, ${JSON.stringify(o)})`);
  await p.type("textarea[name=note]", "PROBE NOTE FOR THE FIRST RECORD");
  await p.eval(`document.querySelector("textarea[name=note]").dispatchEvent(new Event("change", { bubbles: true }))`);
  await p.click(".recent__older");
  await p.waitFor(`location.hash === "#recent/${ids.long}" && document.querySelector(".detail__title")`, "the older record");
  await ok(`document.querySelector("textarea[name=note]").value === ""`, "the note box of the next record is empty");

  // an open edit form and what was typed in it survive a redraw of the page (a job ended, the lock changed)
  await p.go("#recent/" + ids.local);
  await p.click("button", "Edit by hand");
  await unlock();
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields");
  await p.type("input[name=nozzle]", "999");
  await p.eval(`refresh()`);
  await pause(800);
  await ok(`document.querySelector("input[name=nozzle]") && document.querySelector("input[name=nozzle]").value === "999"`, "the form and its typed value after a redraw");

  // a wrong range shows the catalogue's text
  await p.type("input[name=nozzle]", "230");
  await p.type("input[name=nozzle_range]", "190 to 230");
  await p.click("button[type=submit]", "Save changes");
  await ok(`document.querySelector("input[name=nozzle_range]").closest(".field").querySelector(".field__error").textContent.includes("Enter a range like 190-230.")`, "the range error in words");
  await noKeys("the range error");

  // one press of Save is one request; one press of Undo is one request
  await p.type("input[name=nozzle_range]", "190-235");
  await twice("Save changes");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved"))`, "Saved");
  await pause(500);
  if ((await count("/apply")) !== 1) throw new Error("a double press of Save sent " + (await count("/apply")) + " requests");
  await twice("Undo revision 1");
  await ok(`[...document.querySelectorAll(".revisions .result__text")].some((e) => e.textContent.startsWith("Revision 1 undone."))`, "Revision 1 undone");
  await pause(500);
  if ((await count("/undo")) !== 1) throw new Error("a double press of Undo sent " + (await count("/undo")) + " requests");
  await noKeys("after Save and Undo");

  // Ask, Edit by hand, Ask again: one question; its answer shows in the record drawn again, with the Label Reader's own note
  await p.type("textarea[name=note]", "nozzle is 235");
  await p.eval(`window.__reqs = []`);
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields while asking");
  await p.click("button", "Cancel");
  await p.waitFor(`document.querySelector("textarea[name=note]")`, "the note box again");
  await p.click("button", "Ask the Label Reader");
  await ok(`document.querySelector(".changes__title")`, "the suggestion in the record drawn again");
  await pause(500);
  if ((await count("/revise")) !== 1) throw new Error("Ask, Edit by hand, Ask again sent " + (await count("/revise")) + " requests");
  await ok(`document.querySelector(".changes").textContent.includes("second look at the label")`, "the Label Reader's own note");

  // an answer that comes while a form is open does not redraw the record: what was typed stays, and so does the focus
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "nozzle is 235");
  await p.eval(`window.__reqs = []`);
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields while asking");
  await p.type("input[name=nozzle]", "999");
  await ok(`document.querySelector(".changes__title")`, "the late answer");
  await ok(`document.querySelector("input[name=nozzle]").value === "999"`, "the typed value after the late answer");
  await ok(`document.activeElement === document.querySelector("input[name=nozzle]")`, "the focus stays in the form after the late answer");

  // an answer that comes after a Save is out of date: no suggestion that the Hub would refuse
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "nozzle is 235");
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields while asking again");
  await p.type("input[name=nozzle]", String(240 + (Date.now() % 9)));
  await p.click("button[type=submit]", "Save changes");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved"))`, "Saved while asking");
  await pause(2500);
  await ok(`!document.querySelector(".changes__title")`, "no suggestion after a Save while asking");
  await ok(`document.querySelector("#recent-ask").closest(".card").textContent.includes("so its answer was not used")`, "the dropped answer says so");
  await noKeys("after the late answer");

  // a second question while one is asked says so; the note shown is not sent
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "first note");
  await p.eval(`window.__reqs = []`);
  await p.click("button", "Ask the Label Reader");
  await p.type("textarea[name=note]", "second note");
  await p.click("button", "Ask the Label Reader");
  await ok(`[...document.querySelectorAll(".result__text")].some((e) => e.textContent.includes("Still working. Wait for it to finish."))`, "the busy text");
  await ok(`document.querySelector(".changes__title")`, "the first answer");
  if ((await count("/revise")) !== 1 || JSON.parse(await p.eval(`window.__reqs.find(([u]) => u.endsWith("/revise"))[1]`)).note !== "first note") throw new Error("one question, with the first note");

  // Accept while the edit form is open is not offered: what was typed is not replaced without a word
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "nozzle is 235");
  await p.eval(`window.__reqs = []`);
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=vendor]")`, "the fields while asking (accept)");
  await p.type("input[name=vendor]", "PROBEVENDOR");
  await p.type("input[name=nozzle]", "999");
  await ok(`document.querySelector(".changes__title")`, "the answer while the form is open");
  await ok(`[...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Accept").getAttribute("aria-disabled") === "true"`, "Accept is not offered while editing");
  await ok(`document.querySelector(".recent__suggestion").textContent.includes("Save or cancel your edit first")`, "the reason is shown");
  await p.click("button", "Accept");
  await pause(600);
  if ((await count("/apply")) !== 0) throw new Error("Accept was sent while the form was open");
  await ok(`document.querySelector("input[name=vendor]").value === "PROBEVENDOR" && document.querySelector("input[name=nozzle]").value === "999"`, "what was typed is still there");
  await p.click("button", "Cancel");
  await ok(`[...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Accept").getAttribute("aria-disabled") !== "true"`, "Accept is offered again once the edit is closed");

  // an answer still on its way is dropped, and says so, by an Accept, an Undo and an item change (as by a Save)
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "first");
  await p.click("button", "Ask the Label Reader");
  await ok(`document.querySelector(".changes__title")`, "the first answer");
  await p.type("textarea[name=note]", "second");
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Accept");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Accepted."))`, "Accepted while asking again");
  await pause(2500);
  await ok(`!document.querySelector(".changes__title") && [...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Accepted."))`, "the second answer is dropped, the Accepted stays");
  await ok(`document.querySelector("#recent-ask").closest(".card").textContent.includes("so its answer was not used")`, "the second answer says it was dropped");

  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "third");
  await p.click("button", "Ask the Label Reader");
  await p.eval(`[...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("Undo revision")).click()`);
  await ok(`[...document.querySelectorAll(".revisions .result__text")].some((e) => e.textContent.includes("undone."))`, "Undone while asking");
  await pause(2500);
  await ok(`!document.querySelector(".changes__title") && document.querySelector("#recent-ask").closest(".card").textContent.includes("so its answer was not used")`, "the answer is dropped by an Undo, and says so");

  await p.go("#recent");
  await p.go("#recent/" + ids.cloud);
  await p.type("textarea[name=note]", "fourth");
  await p.click("button", "Ask the Label Reader");
  await p.click(".segmented__option", "Item 2");
  await pause(2500);
  await ok(`!document.querySelector(".changes__title") && document.querySelector("#recent-ask").closest(".card").textContent.includes("so its answer was not used")`, "the answer is dropped by an item change, and says so");

  // an Ask sent while a Save is on its way (its reply is slow) is asked of the changed record: its answer is shown
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields (slow save)");
  await p.type("input[name=nozzle]", String(250 + (Date.now() % 9)));
  await p.type("textarea[name=note]", "asked during the save");
  await net({ applyDelay: 500 });
  await p.click("button[type=submit]", "Save changes");
  await p.click("button", "Ask the Label Reader");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved"))`, "Saved (slow reply)");
  await ok(`document.querySelector(".changes__title")`, "the answer of an Ask sent during a Save");

  // an answer that arrives BEFORE a slow Save reply is kept (the Save was sent before the Ask)
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields (early answer)");
  await p.type("input[name=nozzle]", String(260 + (Date.now() % 9)));
  await p.type("textarea[name=note]", "answer before the save reply");
  await net({ applyDelay: 2600 });
  await p.click("button[type=submit]", "Save changes");
  await p.click("button", "Ask the Label Reader");
  await ok(`document.querySelector(".changes__title")`, "the answer before the Save reply");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved"))`, "Saved (slow reply)");
  await pause(500);
  await ok(`document.querySelector(".changes__title")`, "the answer is still there after the Save reply");

  // a write that failed changed nothing: a pending answer is kept
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "answer after a refused save");
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=material]")`, "the fields (refused save)");
  await p.type("input[name=material]", "x".repeat(101));
  await p.click("button[type=submit]", "Save changes");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.includes("material"))`, "the Hub refuses the Save");
  await ok(`document.querySelector(".changes__title")`, "the answer is kept after a refused Save");

  // a Save that fails, an Ask sent while it is out, then an Undo that succeeds: the answer is out of date (the failed Save counted as nothing)
  await net({});
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields (to make a revision)");
  await p.type("input[name=nozzle]", String(270 + (Date.now() % 9)));
  await p.click("button[type=submit]", "Save changes");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved"))`, "Saved (a revision to undo)");
  await net({ failSave: 1800 });
  await p.click("button", "Edit by hand");
  await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields (failing save)");
  await p.type("input[name=nozzle]", String(280 + (Date.now() % 9)));
  await p.type("textarea[name=note]", "asked while a save fails");
  await p.click("button[type=submit]", "Save changes");
  await p.click("button", "Ask the Label Reader");
  await p.eval(`[...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("Undo revision")).click()`);
  await ok(`[...document.querySelectorAll(".revisions .result__text")].some((e) => e.textContent.includes("undone."))`, "Undone while the Save is out");
  await pause(3200);
  await ok(`!document.querySelector(".changes__title") && !([...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Accept"))`, "no suggestion and no Accept after a failed Save and an Undo");
  await ok(`document.querySelector("#recent-ask").closest(".card").textContent.includes("so its answer was not used")`, "the answer says it was dropped");

  // the Hub cleared its proposals behind the page: Accept is refused (404), the refusal is in words and the suggestion leaves
  await net({});
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "the hub forgets this");
  await p.click("button", "Ask the Label Reader");
  await ok(`document.querySelector(".changes__title")`, "the suggestion to be refused");
  await p.eval(`fetch("/setup/api/intake/history/${ids.local}/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item: 0, values: { bed: ${61 + (Date.now() % 9)} }, code: SW.lock.code }) }).then((r) => r.status)`);
  await p.click("button", "Accept");
  await ok(`[...document.querySelectorAll(".result__text")].some((e) => e.textContent.includes("so its answer was not used"))`, "the refusal in words");
  await ok(`!document.querySelector(".changes__title") && !([...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Accept"))`, "the suggestion and its Accept leave after the refusal");
  await ok(`document.activeElement && document.activeElement.id === "recent-ask-note"`, "the focus goes to the note field after the refusal");
  await noKeys("after the refusal");

  // a second answer that arrives while an Accept is out is dropped, says so, and does not clear the Accept's "Saving..."
  await p.go("#recent");
  await p.go("#recent/" + ids.local);
  await p.type("textarea[name=note]", "first for a slow accept");
  await p.click("button", "Ask the Label Reader");
  await ok(`document.querySelector(".changes__title")`, "the suggestion for a slow Accept");
  await net({ applyDelay: 3000 });
  await p.type("textarea[name=note]", "second for a slow accept");
  await p.click("button", "Ask the Label Reader");
  await p.click("button", "Accept");
  await pause(1900);
  await ok(`[...document.querySelectorAll(".result__text")].some((e) => e.textContent.includes("Saving"))`, "the Accept still says Saving while the second answer has come");
  await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Accepted."))`, "Accepted");
  await ok(`document.querySelector("#recent-ask").closest(".card").textContent.includes("so its answer was not used") && !document.querySelector(".changes__title")`, "the second answer is dropped and says so");

  // an answer held back by a write is released after a newer question was asked: it never replaces the newer suggestion (the Save fails) ...
  // the typed values differ from every value saved before (a Save of the same value says "Nothing changed." and shows no "Saved"):
  // each round has its own pair, not a number taken from the clock, which repeats one time in nine
  for (const [round, [label, fail]] of [["a Save that fails", true], ["a Save that succeeds", false]].entries()) {
    await net({});
    await p.go("#recent");
    await p.go("#recent/" + ids.local);
    await p.click("button", "Edit by hand");        // a value the Label Reader would change (it answers nozzle 235)
    await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields (before " + label + ")");
    await p.type("input[name=nozzle]", String(300 + 20 * round));
    await p.click("button[type=submit]", "Save changes");
    await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved"))`, "Saved (before " + label + ")");
    await net(fail ? { failSave: 4200 } : { applyDelay: 4200 });
    await p.eval(`window.__proposals = []`);
    await p.type("textarea[name=note]", "first, to be held");
    await p.click("button", "Ask the Label Reader");
    await p.click("button", "Edit by hand");
    await p.waitFor(`document.querySelector("input[name=nozzle]")`, "the fields (" + label + ")");
    await p.type("input[name=nozzle]", String(290 + 20 * round));
    await p.click("button[type=submit]", "Save changes");
    await ok(`window.__proposals.length === 1`, "the first answer has come (" + label + ")");
    await pause(400);
    await p.type("textarea[name=note]", "second, newer");
    await p.click("button", "Ask the Label Reader");
    await ok(`window.__proposals.length === 2 && document.querySelector("section.changes[data-proposal]") && document.querySelector("section.changes").dataset.proposal === window.__proposals[1]`, "the newer suggestion is shown (" + label + ")");
    await pause(3800);
    await ok(`[...document.querySelectorAll(".recent__main .result__text")].some((e) => e.textContent.startsWith("Saved") || e.textContent.includes("out of order"))`, "the Save has ended (" + label + ")");
    await pause(600);
    await ok(`document.querySelector("section.changes") && document.querySelector("section.changes").dataset.proposal === window.__proposals[1]`, "the held older answer does not replace or wipe the newer suggestion (" + label + ")");
  }
};
