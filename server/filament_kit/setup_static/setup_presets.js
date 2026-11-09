// The console's Presets tab. Loaded after setup.js; everything from the server goes in through textContent, as there.
// Add or accept only: the one thing here that replaces a preset in a slicer is Accept, and the PC sync does that.
"use strict";

let presetsBody = null;

function updatesList(box, r) {
  const what = r.chosen.map((u) => h("li", { textContent:
    `${u.target === "orca" ? "Orca Slicer" : "Bambu Studio"}: ${u.name}${u.file ? ` (in your file ${u.file})` : ""}: ${u.keys.slice(0, 6).join(", ")}${u.keys.length > 6 ? ", ..." : ""}` }));
  fill(box,
    h("p", { textContent: r.chosen.length ? `${r.chosen.length} update${r.chosen.length === 1 ? "" : "s"} ${r.dry_run ? "would be accepted; nothing was changed." : "accepted; the PC sync writes them at its next run, after its backup."}` : "No updates to accept." }),
    r.chosen.length ? h("ul", {}, ...what) : null,
    r.dry_run && r.chosen.length ? h("button", { textContent: "Accept these", on: { click: () => accept(box, r.chosen) } }) : null);
}

async function accept(box, chosen) {
  const lines = [...new Set(chosen.map((u) => u.line_id))];
  const all = lines.length > 1;
  const r = await change(box, "presets/updates", { dry_run: false, ...(all ? { all: true } : { line: lines[0] }) }, () => {});
  if (r) { updatesList(box, r); loadPresets(); }
}

function parentButton(line, target, box) {
  const words = target === "orca" ? "Orca parent" : "Bambu Studio parent";
  return h("button", { class: "secondary", textContent: `Set ${words}`, on: { click: async () => {
    box.replaceChildren(h("p", { class: "muted", textContent: "…" }));
    let p;
    try { p = await api(`presets/parents?material=${encodeURIComponent(line.material)}&target=${target}`); } catch (e) { say(box, e.message, false); return; }
    if (!p.parents.length) { say(box, "The PC sync has not reported any parents yet. It reports them when it runs.", false); return; }
    const now = target === "orca" ? line.orca_parent : line.bambu_parent;
    const pick = h("select", { ariaLabel: words }, ...p.parents.map((n) => h("option", { value: n, textContent: n, selected: n === now })));
    fill(box, h("label", {}, `${words} of ${line.vendor} ${line.product}: `, pick),
      h("div", { class: "row" },
        h("button", { textContent: "Save", on: { click: async () => {
          const r = await change(box, `presets/lines/${encodeURIComponent(line.line_id)}/parent`, { parent: pick.value, target }, () => say(box, "Saved. A build was asked for.", true));
          if (r) loadPresets();
        } } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => box.replaceChildren() } })));
  } } });
}

function lineRow(line, canOrca) {
  const box = h("div");
  const parent = line.bambu_parent ? `${line.bambu_parent} (${line.parent_source})` : "none";
  const orca = line.orca_parent ? `${line.orca_parent} (${line.orca_parent_source})` : "none";
  return h("div", { class: "item" },
    h("p", {}, h("b", { textContent: `${line.vendor} ${line.product}` }), ` · ${line.material} · ${line.presets} preset${line.presets === 1 ? "" : "s"}`),
    h("p", { class: "muted", textContent: `Bambu Studio parent: ${parent}${canOrca ? ` · Orca parent: ${orca}` : ""}` }),
    h("div", { class: "row" }, parentButton(line, "bambu", box), canOrca ? parentButton(line, "orca", box) : null),
    box);
}

function drawPresets(v) {
  if (!v.on) { fill(presetsBody, card("Presets", h("p", { textContent: "Turn on the presets module in Modules to use this tab." }))); return; }
  const box = boxFor("presets"), upBox = boxFor("presetUpdates");
  const a = v.last_attempt, b = v.build;
  const up = v.updates;
  fill(presetsBody,
    card("Build",
      h("p", { textContent: b ? `Last build ${b.stamp}: ${v.presets} presets${v.orca_presets != null ? `, ${v.orca_presets} for Orca Slicer` : ""}, ${b.problems || 0} problems.` : "No build yet." }),
      a && !a.ok ? h("p", { class: "muted", textContent: a.error }) : null,
      v.waiting_text ? h("p", { class: "muted", textContent: v.waiting_text }) : null,
      h("p", { class: "muted", textContent: v.pc ? "The PC sync has reported in." : "PC sync: not set up. Pair it on the Devices tab." }),
      v.problems.length ? h("ul", {}, ...v.problems.map((p) => h("li", { textContent: p }))) : null,
      ...v.stale.map((n) => h("p", { class: "muted", textContent: `Delete in Bambu Studio: ${n}` })),
      ...v.orca_stale.map((n) => h("p", { class: "muted", textContent: `Delete in Orca Slicer: ${n}` })),
      h("div", { class: "row" },
        h("button", { textContent: "Build now", on: { click: () => change(box, "presets/build", {}, () => say(box, "A build was asked for.", true)) } }),
        h("button", { class: "secondary", textContent: "Restore deleted presets", on: { click: () => change(box, "presets/restore_deleted", {}, () => say(box, "The next build brings back the presets deleted in Bambu Studio. A build was asked for.", true)) } })),
      box),
    card("Updates",
      h("p", { textContent: up.count ? `${up.count} update${up.count === 1 ? "" : "s"} available on ${up.lines} line${up.lines === 1 ? "" : "s"}${up.accepted ? `, ${up.accepted} accepted (the PC sync writes them next)` : ""}. Presets already in your slicers are never replaced unless you accept here.` : "No updates. Presets already in your slicers are never replaced on their own." }),
      up.yours ? h("p", { class: "muted", textContent: `${up.yours} generated preset${up.yours === 1 ? "" : "s"} differ from your own preset of the same name in Bambu Studio. Yours stay: rename or delete yours to get ours.` }) : null,
      up.count ? h("button", { class: "secondary", textContent: "Show what would be accepted", on: { click: () => change(upBox, "presets/updates", { all: true, dry_run: true }, (r) => updatesList(upBox, r)) } }) : null,
      upBox),
    card("Product lines",
      v.lines_error ? h("pre", { class: "err", textContent: v.lines_error }) : null,
      v.lines.length ? null : h("p", { class: "muted", textContent: "No lines yet. They are made from the Spoolman filaments at the next build or intake." }),
      ...v.lines.map((l) => lineRow(l, v.orca_presets != null))));
}

async function loadPresets() {
  try { drawPresets(await api("presets")); } catch (e) { say(presetsBody, e.message, false); }
}

function presetsTab() {
  presetsBody = h("div");
  loadPresets();
  return [presetsBody];
}
