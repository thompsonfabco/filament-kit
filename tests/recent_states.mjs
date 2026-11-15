// The states of Recently added that the flow does not reach, run by tests/hub_drive.mjs: `empty`, `off` (the Label Reader switched
// off), `nophoto` (the only engine needs a photo), `paging` (55 records: 50 on a page, the pager, the second page) and `error` (the list cannot be read: Try again).
// The argument is JSON: {ids: {one: a record id}, scenario}. Test-only.
export default async (p) => {
  const { ids, scenario } = JSON.parse(p.arg);
  // a check waits for its answer (a page under load draws late), then fails with its name
  const ok = (js, what) => p.waitFor(`(() => { try { return ${js}; } catch { return false; } })()`, what, 10000);
  if (scenario === "empty") {
    await p.go("#recent");
    await ok(`document.querySelector(".empty__title").textContent === "Nothing added yet"`, "the empty state");
    await ok(`!document.querySelector(".coll--recent") && !document.querySelector("[name=recent-filter]")`, "no list and no filter");
  } else if (scenario === "off") {
    await p.go("#recent");
    await ok(`document.querySelector(".page-head__meta").textContent.includes("Label Reader") && document.querySelector(".page-head__meta .status").textContent.includes("Off")`, "the Label Reader badge says Off");
    await p.go("#recent/" + ids.one);
    await ok(`document.querySelector("#recent-ask").closest(".card").textContent.includes("The Label Reader is switched off. Correct by hand, or switch it on in Features on the Hub page.")`, "the off state of the Ask card");
    await ok(`!document.querySelector("textarea[name=note]")`, "no note field while it is off");
    await ok(`[...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Edit by hand")`, "Edit by hand still works");
    await p.click("#recent-ask ~ .actions a", "Features");
    await p.waitFor(`location.hash === "#features"`, "the link to Features");
  } else if (scenario === "nophoto") {
    await p.go("#recent/" + ids.one);
    await p.type("textarea[name=note]", "brand is Polymaker");
    await p.click("button", "Ask the Label Reader");
    await p.waitFor(`document.querySelector("dialog[open] input[name=code]")`, "the unlock dialog");
    await p.type("dialog[open] input[name=code]", JSON.parse(p.arg).code);
    await p.click("dialog[open] [data-action=confirm]");
    await p.waitFor(`[...document.querySelectorAll(".result__text")].some((e) => e.textContent === "No photo was kept for this record, and the On this Hub engine needs one. Switch on Cloud in Features, or correct the fields by hand.")`, "the no photo text", 20000);
    await ok(`!document.querySelector(".changes__title")`, "no suggestion");
  } else if (scenario === "paging") {
    await p.go("#recent");
    await ok(`document.querySelectorAll(".coll--recent .coll__item").length === 50`, "50 rows on the first page");
    await ok(`document.querySelector(".coll--recent").getAttribute("aria-rowcount") === "56"`, "the row count is every record and the header");
    await ok(`!document.querySelector(".coll__sort")`, "a paged list offers no sort of its own");
    await ok(`document.querySelector(".coll__pager .mono").textContent === "1–50 of 55"`, "the pager range");
    await p.click(".coll__pager button", "Next");
    await p.waitFor(`location.hash === "#recent?page=2" && document.querySelectorAll(".coll--recent .coll__item").length === 5`, "the second page");
    await ok(`document.activeElement.classList.contains("coll__title")`, "focus on the first title of the page");
    await ok(`document.querySelector(".coll__pager .mono").textContent === "51–55 of 55"`, "the second range");
    await p.click(".coll__pager button", "Previous");
    await p.waitFor(`location.hash === "#recent" && document.querySelectorAll(".coll--recent .coll__item").length === 50`, "back to the first page");
  } else if (scenario === "error") {
    await p.go("#recent");
    await ok(`document.querySelector(".error-state__title").textContent === "Could not read the additions."`, "the error state");
    await ok(`document.querySelector(".error-state__text").textContent.includes("The history is unreadable")`, "the Hub's text");
    await p.click("button", "Try again");
    await p.waitFor(`document.querySelector(".error-state__title")`, "the error state after Try again");
  } else throw new Error("no scenario " + scenario);
};
