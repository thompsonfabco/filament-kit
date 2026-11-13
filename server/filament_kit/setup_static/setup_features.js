// The Features section: the mode presets, the modules and applying again.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

// ----- the mode presets -----
function modesCard() {
  const box = boxFor("modes");
  async function ask(m) {
    working(box, "…");
    let p;
    try { p = await api(`modules/preview?mode=${encodeURIComponent(m.name)}`); } catch (e) { say(box, e.message, false); return; }
    if (p.refused) { say(box, p.refused, false); return; }
    const inputs = p.needs.map((n) => ({ key: n.key, el: h("input", { placeholder: n.prompt }) }));
    fill(box,
      h("p", { textContent: `Set the mode to ${m.name}.` }),
      ...p.notes.map((n) => h("p", { class: "muted", textContent: n })),
      h("p", { class: "muted", textContent: "On afterwards: " + (p.after.join(", ") || "nothing") }),
      ...inputs.map((i) => h("label", {}, i.el)),
      h("div", { class: "row" },
        h("button", { textContent: "Apply", on: { click: async () => {
          const settings = Object.fromEntries(inputs.map((i) => [i.key, i.el.value]));
          const r = await change(box, "modules/mode", { mode: m.name, settings }, (x) => say(box, x.changed ? "Saved; applying…" : "Unchanged.", true));
          if (r && r.changed) followApply(true);
        } } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => fill(box) } })));
  }
  return card(`Mode: ${S.mode}`,
    h("div", { class: "row" }, ...S.modes.map((m) => h("button", {
      class: m.name === S.mode ? "" : "secondary", textContent: m.name, disabled: !m.here,
      title: m.here ? "" : "A machine in this mode has no setup page",
      on: { click: () => ask(m) } }))),
    S.modes.some((m) => !m.here) ? h("p", { class: "muted", textContent: "Station mode has no server and so no setup page: at the server, sudo filament-kit modules set station --server <the kit server's address>." }) : null,
    box);
}

// ----- modules -----
function modulesCard() {
  // the preview and its result open under the module's own row
  async function ask(m, box) {
    working(box, "…");
    let p;
    try { p = await api(`modules/preview?name=${encodeURIComponent(m.name)}`); } catch (e) { say(box, e.message, false); return; }
    if (p.refused) { say(box, p.refused, false); return; }
    const inputs = p.needs.map((n) => ({ key: n.key, el: h("input", { placeholder: n.prompt }) }));
    fill(box,
      h("p", { textContent: `${p.on ? "Turn on" : "Turn off"} ${m.name}.` }),
      ...p.notes.map((n) => h("p", { class: "muted", textContent: n })),
      h("p", { class: "muted", textContent: "On afterwards: " + (p.after.join(", ") || "nothing") }),
      ...inputs.map((i) => h("label", {}, i.el)),
      h("div", { class: "row" },
        h("button", { textContent: "Apply", on: { click: async () => {
          const settings = Object.fromEntries(inputs.map((i) => [i.key, i.el.value]));
          const r = await change(box, "modules", { name: m.name, on: p.on, settings }, (x) => say(box, x.changed ? "Saved; applying…" : "Unchanged.", true));
          if (r && r.changed) followApply();
        } } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => fill(box) } })));
  }
  return card(`Modules (mode: ${S.mode})`,
    ...S.modules.map((m) => { const box = boxFor("module:" + m.name); return h("div", { class: "row item", "data-key": m.name },
      h("span", {}, pill(m.on, "on", "off"), ` ${m.name}: ${m.description}`, m.needs.length ? h("span", { class: "muted", textContent: ` · needs: ${m.needs.join(", ")}` }) : null,
        m.optional_ai ? h("span", { class: "muted", textContent: " · OPTIONAL AI" }) : null),
      h("button", { class: "secondary", textContent: m.on ? "Turn off" : "Turn on", on: { click: () => ask(m, box) } }), box); }));
}

// ----- applying again (the job strip is SW_JOBS', wired in setup_tabs.js) -----
function applyCard() {
  const box = boxFor("apply");
  return card("Apply", h("p", { class: "muted", textContent: "Module and address changes are applied in the background (sudo filament-kit modules apply)." }),
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Apply again", on: { click: async () => {
      const r = await change(box, "apply", {}, () => say(box, "Applying…", "info"));
      if (r) followApply(true);
    } } })), box);
}
