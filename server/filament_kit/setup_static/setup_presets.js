// The console's Presets tab. Loaded after setup.js; everything from the server goes in through textContent, as there.
// Add or accept only: the one thing here that replaces a preset in a slicer is Accept, and the PC sync does that.
"use strict";

// the tab's one region; a change draws it again and waits for its read (later) before it says the result
let presetsBody = null;
const PRESETS = "presets";       // the section's name in TABS; its catalogue keys start with it

function updatesList(box, r) {
  const what = r.chosen.map((u) => h("li", { textContent:
    `${u.target === "orca" ? "Orca Slicer" : "Bambu Studio"}: ${u.name}${u.file ? ` (in your file ${u.file})` : ""}: ${u.keys.slice(0, 6).join(", ")}${u.keys.length > 6 ? ", ..." : ""}` }));
  say(box, [
    h("p", { textContent: r.chosen.length ? `${r.chosen.length} update${r.chosen.length === 1 ? "" : "s"} ${r.dry_run ? "would be accepted; nothing was changed." : "accepted; the PC sync writes them at its next run, after its backup."}` : "No updates to accept." }),
    r.chosen.length ? h("ul", {}, ...what) : null,
    r.dry_run && r.chosen.length ? h("button", { textContent: "Accept these", on: { click: () => accept(box, r) } }) : null], r.dry_run ? "info" : true);
}

// Accepts what the list showed, by name and build: the server refuses once a newer build has changed it. The change
// reads the tab again (its region).
async function accept(box, shown) {
  const r = await change(box, "presets/updates", { all: true, dry_run: false, stamp: shown.stamp, names: shown.chosen.map((u) => u.name) }, () => {});
  if (r) updatesList(box, r);
}

function parentButton(line, target, box) {
  const words = target === "orca" ? "Orca parent" : "Bambu Studio parent";
  return h("button", { class: "secondary", textContent: `Set ${words}`, on: { click: async () => {
    working(box, "…");
    let p;
    try { p = await api(`presets/parents?material=${encodeURIComponent(line.material)}&target=${target}`); } catch (e) { say(box, e.message, false); return; }
    if (!p.parents.length) { say(box, "The PC sync has not reported any parents yet. It reports them when it runs.", false); return; }
    const now = target === "orca" ? line.orca_parent : line.bambu_parent;
    const pick = h("select", { ariaLabel: words }, ...p.parents.map((n) => h("option", { value: n, textContent: n, selected: n === now })));
    fill(box, h("label", {}, `${words} of ${line.vendor} ${line.product}: `, pick),
      h("div", { class: "row" },
        h("button", { textContent: "Save", on: { click: () => change(box, `presets/lines/${encodeURIComponent(line.line_id)}/parent`, { parent: pick.value, target },
          () => say(box, "Saved. A build was asked for.", true)) } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => fill(box) } })));
  } } });
}

function lineRow(line, canOrca) {
  const box = boxFor(`line:${line.line_id}`);       // a message here outlives the redraw a change brings
  const parent = line.bambu_parent ? `${line.bambu_parent} (${line.parent_source})` : "none";
  const orca = line.orca_parent ? `${line.orca_parent} (${line.orca_parent_source})` : "none";
  return h("div", { class: "item", "data-key": line.line_id },
    h("p", {}, h("b", { textContent: `${line.vendor} ${line.product}` }), ` · ${line.material} · ${line.presets} preset${line.presets === 1 ? "" : "s"}`),
    h("p", { class: "muted", textContent: `Bambu Studio parent: ${parent}${canOrca ? ` · Orca parent: ${orca}` : ""}` }),
    h("div", { class: "row" }, parentButton(line, "bambu", box), canOrca ? parentButton(line, "orca", box) : null),
    box);
}

function drawPresets(v) {
  if (!v.on) { fill(presetsBody, switchedOff(PRESETS)); return; }
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
      up.yours ? h("p", { class: "muted", textContent: `${up.yours} generated preset${up.yours === 1 ? "" : "s"} ${up.yours === 1 ? "differs" : "differ"} from your own preset of the same name in Bambu Studio. Yours stay: rename or delete yours to get ours.` }) : null,
      up.count ? h("button", { class: "secondary", textContent: "Show what would be accepted", on: { click: () => change(upBox, "presets/updates", { all: true, dry_run: true }, (r) => updatesList(upBox, r)) } }) : null,
      upBox),
    card("Product lines",
      v.lines_error ? SW.errorState({ title: SW.t(PRESETS + "_lines_error", { reason: "" }).trim(), text: hubText(v.lines_error), level: 3, onTry: loadPresets }) : null,
      v.lines.length ? null : h("p", { class: "muted", textContent: "No lines yet. They are made from the Spoolman filaments at the next build or intake." }),
      ...v.lines.map((l) => lineRow(l, v.orca_presets != null))));
}

function loadPresets() {
  return readRegion(presetsBody, PRESETS, () => api("presets"), drawPresets);
}

function presetsTab() {
  presetsBody = h("div");
  later(loadPresets());
  return [presetsBody];
}
