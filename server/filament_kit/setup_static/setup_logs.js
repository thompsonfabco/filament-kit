// The console's Logs tab. Loaded after setup.js; everything from the server goes in through textContent, as there.
// Logs hold addresses and serial numbers, so reading them takes the setup code; nothing is kept on the page.
"use strict";

function logsTab() {
  const body = h("div");
  const box = boxFor("logs");
  const unit = h("select", { ariaLabel: "Service" });
  const lines = h("select", { ariaLabel: "Lines" }, ...[50, 100, 200].map((n) => h("option", { value: String(n), textContent: `last ${n} lines`, selected: n === 100 })));
  // the one Show left (03 2.1): the service and the lines are chosen first; while Locked it asks for the code in place
  const show = () => coded(box, async () => {
    box.replaceChildren(h("p", { class: "muted", textContent: "Reading…" }));
    try {
      const r = await api("logs", { unit: unit.value, lines: Number(lines.value), code: theCode() });
      fill(box,
        r.truncated ? h("p", { class: "muted", textContent: "Only the end is shown: the rest is too long for this page." }) : null,
        h("pre", { textContent: r.text || "Nothing logged." }));
    } catch (e) { if (e.locked) box.replaceChildren(); throw e; }
  });
  api("logs/units").then((r) => {
    if (!r.units.length) { fill(body, h("p", { class: "muted", textContent: "No services are on." })); return; }
    unit.replaceChildren(...r.units.map((u) => h("option", { value: u, textContent: u })));
    fill(body,
      h("p", { class: "muted", textContent: "Logs hold addresses and serial numbers, so this takes the setup code." }),
      h("div", { class: "row" }, unit, lines, h("button", { textContent: "Show", on: { click: show } })),
      box);
  }).catch((e) => say(body, e.message, false));
  return [card("Logs", body)];
}
