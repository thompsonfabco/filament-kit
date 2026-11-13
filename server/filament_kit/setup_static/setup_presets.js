// The Slicer presets section (03 8). Loaded after setup.js; everything from the server goes in through textContent, as there.
// Add or accept only: the one thing here that replaces a preset in a slicer is Accept, and Slicer Sync does that.
"use strict";

// the section's one region; a change draws it again and waits for its read (later) before it says the result
let presetsBody = null;
const PRESETS = "presets";       // the section's name in TABS; its catalogue keys start with it
const TARGET = { bambu: "presets_target_bambu", orca: "presets_target_orca" };
const LIST_KEYS = 6;             // keys named per update in the change list

// A control that is pressed again while its change is under way does nothing (one request per press)
const once = (run) => { let on = false; return async (e) => { if (on) return; on = true; try { await run(e); } finally { on = false; } }; };

// a line of the change list: "<slicer>: <name> (in your file <file>): <up to 6 keys>, …"
function updateLine(u) {
  const keys = u.keys.slice(0, LIST_KEYS).join(", ") + (u.keys.length > LIST_KEYS ? ", …" : "");
  return SW.t(u.file ? "presets_updates_line" : "presets_updates_line_nofile",
    { target: SW.t(TARGET[u.target === "orca" ? "orca" : "bambu"]), name: u.name, file: u.file, keys });
}

// what Show what would change found: the list, and under it Accept these (a dry run changes nothing)
function updatesList(box, r) {
  if (!r.chosen.length) { say(box, SW.t("presets_updates_nothing"), "info"); return; }
  say(box, [h("p", {}, SW.t("presets_updates_would", { count: r.chosen.length })),
    h("ul", {}, ...r.chosen.map((u) => h("li", {}, updateLine(u)))),
    SW.btn(SW.t("presets_updates_accept"), { cls: "btn--primary", action: "accept", run: once(() => accept(box, r)) })], "info");
}

// Accepts what the list showed, by name and build: the Hub refuses once a newer build has changed it (409): the list is then
// cleared and the person is asked to show it again. The change reads the section again (its region).
async function accept(box, shown) {
  await needCode(async () => {
    working(box, SW.t("common_saving"));
    let r;
    try { r = await api("presets/updates", { all: true, dry_run: false, stamp: shown.stamp, names: shown.chosen.map((u) => u.name), code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      if (e.status === 409 && /show them again/.test(e.message)) say(box, SW.t("presets_updates_stale"), "warn");     // not the module being off
      else say(box, hubText(e.message), false);
      return;
    }
    await refresh(box);
    say(box, SW.t("presets_updates_accepted_result", { count: r.chosen.length }), true);
  });
}

// Set parent: reads the parents Slicer Sync reported for the line's material, then asks in a dialog (03 8.2)
async function setParent(line, target, box, opener) {
  const name = SW.t("presets_line_title", { vendor: line.vendor, line: line.product });
  working(box, SW.t("common_reading"));
  let p;
  try { p = await api(`presets/parents?material=${encodeURIComponent(line.material)}&target=${target}`); } catch (e) { say(box, e.message, false); return; }
  SW.result(box, null);
  const o = { title: SW.t("presets_parent_title", { line: name }), text: SW.t("presets_parent_subline", { target: SW.t(TARGET[target]), material: line.material }), opener };
  if (!p.parents.length) { await SW.ask({ ...o, kind: "info", text: SW.t("presets_parent_empty"), body: h("p", { class: "muted" }, o.text) }); return; }
  const now = target === "orca" ? line.orca_parent : line.bambu_parent;
  const pick = SW.field({ type: "select", name: "parent", label: SW.t("presets_parent_label"), options: p.parents.map((n) => ({ value: n, label: n })),
    value: p.parents.includes(now) ? now : undefined });
  await asking(box, `presets/lines/${encodeURIComponent(line.line_id)}/parent`, { ...o, kind: "entry", fields: [pick], confirm: SW.t("presets_parent_save") },
    (values) => ({ parent: values[0], target }), () => say(box, SW.t("presets_parent_saved"), true));
}

// ----- the section header (02 2.1): a line under the title and the main action at the right -----
function drawHead(v) {
  if (!v.on) { pageHead(); return; }
  const b = v.build, orca = v.orca_presets;
  pageHead(h("p", { class: "page-head__meta" },
    h("span", { class: "mono" }, b ? (orca == null ? SW.t("presets_meta_build_plain", { stamp: b.stamp, count: v.presets })
      : SW.t("presets_meta_build", { stamp: b.stamp, count: v.presets, orca })) : SW.t("presets_build_none")),
    v.pc ? SW.status("ok", { text: SW.t("presets_meta_sync") }) : null),
    h("div", { class: "page-head__actions" },
      SW.btn(SW.t("presets_build_now"), { cls: "btn--primary", action: "build", run: once(() => buildNow()) })));
}
const buildNow = () => { const box = boxFor("presets"); return change(box, "presets/build", {}, () => say(box, SW.t("presets_build_asked"), true)); };

// ----- Build -----
function buildCard(v) {
  const box = boxFor("presets"), a = v.last_attempt, b = v.build;
  return card(SW.t("presets_build_title"),
    h("p", {}, b ? (v.orca_presets == null ? SW.t("presets_build_summary_plain", { stamp: b.stamp, presets: v.presets, count: b.problems || 0 })
      : SW.t("presets_build_summary", { stamp: b.stamp, presets: v.presets, orca: v.orca_presets, count: b.problems || 0 })) : SW.t("presets_build_none")),
    a && !a.ok ? h("p", {}, SW.status("failed", { text: SW.t("presets_build_failed", { error: a.error }) })) : null,
    v.waiting_text ? h("p", {}, SW.status("note", { text: v.waiting_text })) : null,
    v.pc ? h("p", {}, SW.status("ok"), " ", SW.t("presets_sync_ok"))
      : h("p", {}, SW.status("note", { text: SW.t("status_not_configured") }), " ", SW.t("presets_sync_not_set"), " ", h("a", { href: "#devices" }, SW.t("presets_sync_link"))),
    v.problems.length ? h("ul", { class: "problems" }, ...v.problems.map((p) => h("li", {}, SW.status("failed", { text: p })))) : null,
    v.stale.length || v.orca_stale.length ? h("h3", { class: "detail__heading" }, SW.t("presets_stale_title")) : null,
    ...v.stale.map((n) => h("p", { class: "muted" }, SW.t("presets_stale_bambu", { name: n }))),
    ...v.orca_stale.map((n) => h("p", { class: "muted" }, SW.t("presets_stale_orca", { name: n }))),
    h("div", { class: "row" },
      SW.btn(SW.t("presets_restore_deleted"), { cls: "btn--ghost", action: "restore-deleted", run: once(() => change(box, "presets/restore_deleted", {}, () => say(box, SW.t("presets_restore_asked"), true))) })),
    box);
}

// ----- Updates (address #presets/updates) -----
function updatesCard(v) {
  const up = v.updates, box = boxFor("presetUpdates");
  const el = card(SW.t("presets_updates_title"),
    h("p", {}, up.count ? SW.t("presets_updates_summary", { count: up.count, lines: up.lines,
      accepted: up.accepted ? SW.t("presets_updates_accepted", { count: up.accepted }) : "" }) : SW.t("presets_updates_none")),
    up.yours ? h("p", { class: "muted" }, SW.t("presets_updates_yours", { count: up.yours })) : null,
    up.count ? h("div", { class: "row" }, SW.btn(SW.t("presets_updates_show"), { action: "show-updates",
      run: once(() => change(box, "presets/updates", { all: true, dry_run: true }, (r) => updatesList(box, r))) })) : null,
    box);
  el.id = "presets-updates";
  return el;
}

// ----- Product lines: a collection (02 6.1); the parents of a narrow screen are in the row's expansion -----
const sortHead = (col, label) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "aria-sort": col === "title" ? "ascending" : undefined },
  h("button", { class: "coll__sort", type: "button", "data-sort": col }, label, SW.icon("chevron", "icon--s")));
const plainHead = (col, label, prio) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio }, label);
const cell = (col, prio, key, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio },
  key ? h("span", { class: "coll__key", "aria-hidden": "true" }, key) : null, ...kids);

function lineItem(line, canOrca, cols) {
  const box = boxFor(`line:${line.line_id}`), id = "preset-line-" + line.line_id;       // a message here outlives the redraw a change brings
  const name = SW.t("presets_line_title", { vendor: line.vendor, line: line.product });
  const parentText = (p, source) => (p ? SW.t("presets_parent_value", { name: p, source }) : SW.t("common_none"));
  const bambu = parentText(line.bambu_parent, line.parent_source), orca = parentText(line.orca_parent, line.orca_parent_source);
  const expand = SW.iconBtn("chevron", SW.t("detail_for", { name }), { cls: "coll__expand" });
  expand.setAttribute("aria-expanded", "false");
  expand.setAttribute("aria-controls", id);
  const more = SW.btn(SW.t("presets_set_parent"), { name: SW.t("presets_set_parent_for", { name }), icon: "chevron", action: "set-parent" });
  const targets = [["bambu", true], ["orca", canOrca]].filter((t) => t[1]).map(([target]) => ({ label: SW.t(TARGET[target]), run: () => setParent(line, target, box, more) }));
  SW.menu(more, targets, { label: SW.t("presets_set_parent") });
  const facts = h("dl", { class: "kv" },
    h("div", { class: "kv__row" }, h("dt", { class: "kv__key" }, SW.t("common_field_bambu_parent")), h("dd", { class: "kv__value" }, bambu)),
    canOrca ? h("div", { class: "kv__row" }, h("dt", { class: "kv__key" }, SW.t("presets_col_orca_parent")), h("dd", { class: "kv__value" }, orca)) : null);
  return h("div", { class: "coll__item", role: "rowgroup", "data-key": line.line_id, "data-id": line.line_id },
    h("div", { class: "coll__row", role: "row" },
      cell("expand", undefined, null, expand),
      cell("title", 1, null, h("span", { class: "coll__title" }, name)),
      cell("material", 2, SW.t("common_field_material"), line.material),
      cell("presets", 1, SW.t("presets_col_presets"), String(line.presets)),
      cell("bambu_parent", 3, SW.t("common_field_bambu_parent"), bambu),
      canOrca ? cell("orca_parent", 3, SW.t("presets_col_orca_parent"), orca) : null,
      cell("actions", 1, null, h("div", { class: "actions" }, more))),
    h("div", { class: "coll__row coll__row--result", role: "row", hidden: !box.dataset.state }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": cols }, box)),
    h("div", { class: "coll__row coll__row--detail", role: "row", hidden: true }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": cols },
      h("section", { class: "detail", id, hidden: true, "aria-label": name }, facts))));
}

function linesCard(v) {
  const canOrca = v.orca_presets != null, cols = canOrca ? 7 : 6;
  if (v.lines_error) return card(SW.t("presets_lines_title"), SW.errorState({ title: SW.t(PRESETS + "_lines_error", { reason: "" }).trim(), text: hubText(v.lines_error), level: 3, onTry: loadPresets }));
  if (!v.lines.length) return card(SW.t("presets_lines_title"), h("p", { class: "muted" }, SW.t("presets_lines_none")));
  const table = h("div", { class: "coll coll--lines" + (canOrca ? "" : " coll--lines-one"), role: "table", "aria-label": SW.t("presets_lines_title") },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
      h("div", { class: "coll__cell", role: "columnheader", "data-col": "expand" }, h("span", { class: "sr" }, SW.t("common_details"))),
      sortHead("title", SW.t("common_field_line")),
      plainHead("material", SW.t("common_field_material"), 2),
      plainHead("presets", SW.t("presets_col_presets"), 1),
      plainHead("bambu_parent", SW.t("common_field_bambu_parent"), 3),
      canOrca ? plainHead("orca_parent", SW.t("presets_col_orca_parent"), 3) : null,
      h("div", { class: "coll__cell", role: "columnheader", "data-col": "actions" }, h("span", { class: "sr" }, SW.t("common_actions"))))),
    ...v.lines.map((l) => lineItem(l, canOrca, cols)));
  SW.collection(table, { name: "presets-lines", sort: "title:ascending" });
  return card(SW.t("presets_lines_title"), table);
}

// #presets/updates scrolls to the Updates card once each time the address is opened, not at every redraw
let scrolled = false;
window.addEventListener("hashchange", () => { scrolled = false; });

// `body` is the region this read belongs to: one that left the page (another section opened, or a newer drawing took its
// place) draws nothing, and above all leaves the page header alone
function drawPresets(body, v) {
  if (!body.isConnected) return;
  drawHead(v);
  if (!v.on) { fill(body, switchedOff(PRESETS)); return; }
  fill(body, h("div", { class: "presets-pair" }, buildCard(v), updatesCard(v)), linesCard(v));
  if (!scrolled && location.hash === "#presets/updates") { scrolled = true; document.getElementById("presets-updates").scrollIntoView(); }
}

function loadPresets(body = presetsBody) {
  return readRegion(body, PRESETS, () => api("presets"), (v) => drawPresets(body, v));
}

function presetsTab() {
  const body = presetsBody = h("div");
  later(loadPresets(body));
  return [body];
}
