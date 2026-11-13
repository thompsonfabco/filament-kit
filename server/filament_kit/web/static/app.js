// Spool intake phone app: add spools by hand or (with AI intake) from label photos, link a tapped NFC tag, refresh
// slicer presets.
// Talks only to <base>/api/* on the same origin (session cookie); no data from the server is put into
// innerHTML, everything goes through textContent / element properties.
"use strict";
const BASE = document.body.dataset.base;
const LOCATIONS = JSON.parse(document.body.dataset.locations);
const SEALED = document.body.dataset.sealed;      // the sealed-stock location
const AUTO = document.body.dataset.auto;          // what a blank location means (the placement rules)
const PICKS = JSON.parse(document.body.dataset.picks); // extra places offered when opening a spool
const AI = document.body.dataset.ai === "1";       // a label reader (ai_intake or local_intake) is on: photos can be read
// typical densities (g/cm3), filled in for a spool added by hand while its density is still blank
const DENSITY = { PLA: 1.24, PETG: 1.27, ABS: 1.04, ASA: 1.07, TPU: 1.21, PA: 1.14, PC: 1.2, PCTG: 1.23, PVA: 1.23, HIPS: 1.04 };
// a material with no entry of its own ("PLA+", "PLA Silk", "PETG-CF") takes the longest known one it starts with
function densityFor(material) {
  const m = String(material ?? "").trim().toUpperCase();
  if (!m) return undefined;
  if (m in DENSITY) return DENSITY[m];
  const key = Object.keys(DENSITY).filter((k) => m.startsWith(k)).sort((x, y) => y.length - x.length)[0];
  return key ? DENSITY[key] : undefined;
}
const MAX_EDGE = 1568, QUALITY = 0.85; // Claude reads labels well at this size; keeps uploads ~300 KB per photo
const app = document.getElementById("app");

// The phone's status bar and the home-screen manifest follow the active appearance (F5, 08 13): both theme-color metas
// take the computed --surface, and the manifest link points at the light or dark manifest, at load, whenever the
// appearance attribute changes (a stored or new choice) and whenever the phone's own setting changes.
const darkQuery = matchMedia("(prefers-color-scheme: dark)");
function followAppearance() {
  const root = document.documentElement, chosen = root.getAttribute("data-theme");
  const active = chosen === "light" || chosen === "dark" ? chosen : (darkQuery.matches ? "dark" : "light");
  const surface = getComputedStyle(root).getPropertyValue("--surface").trim();
  if (surface) for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.content = surface;
  const link = document.querySelector('link[rel="manifest"]');
  if (link) link.href = `${BASE}/manifest-${active}.webmanifest`;
}
followAppearance();
darkQuery.addEventListener("change", followAppearance);
new MutationObserver(followAppearance).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-look"] });

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k in el && k !== "list" && k !== "style") el[k] = v;
    else el.setAttribute(k, v);
  }
  // the main button look (CON-9) for a button left without a class (checked after the props: class "" counts as none)
  if (tag === "button" && !el.className) el.className = "btn--primary";
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

// The Hub request helper is the shared one (SW.api, base set with SW.configure below). A request that gets no answer within the
// time of 04 3.6 (30 s; 90 s for a label read; 180 s for a preset build) is a request that cannot reach the Hub.
const waitFor = (path) => (/^read$|\/revise$/.test(path) ? 90000 : path === "generate" ? 180000 : 30000);
async function api(path, opts = {}) {
  const stop = new AbortController(), timer = setTimeout(() => stop.abort(), waitFor(path));
  try { return await SW.api(path, { ...opts, signal: stop.signal }); }
  catch (e) { throw e && e.name === "AbortError" ? new SW.HubError({ unreachable: true }) : e; }
  finally { clearTimeout(timer); }
}

const more = (shown, n) => n > shown ? h("p", { class: "muted", textContent: `Showing ${shown} of ${n}: narrow the search.` }) : null;
const ago = (s) => s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;

// ---------- results, errors, reasons and loading in place (04 3.2 to 3.6) ----------
// The inline result line (02 8.6) is under the control that asked; it exists before it is written, as a live region.
const resultLine = () => h("p", { class: "result result--block", role: "status" });
// The Hub's own text under the line that sums it up (04 3.2): a code block that wraps and scrolls inside itself (02 7.7).
const codeBlock = (text) => h("figure", { class: "code" },
  h("pre", { class: "code__text code__text--log", tabindex: "0", "aria-label": SW.t("common_result_hub_text"), textContent: text }));
function answer() {                                          // the line, and room for the Hub's text under it
  const line = resultLine(), code = h("div");
  return { el: h("div", {}, line, code), line, code };
}
// A failed request as a sentence (04 3.6). What the Hub says is shown as it came; only an answer without text, a crash and
// a request that did not reach the Hub get the page's own words. `kept`: a 502 from a label read adds that nothing is lost.
function says(e, o = {}) {
  let text;
  if (!(e instanceof SW.HubError)) text = (e && e.message) || String(e);
  else if (e.unreachable) text = SW.t("common_hub_unreachable");
  else if (e.status === 403 && e.error === "bad origin") text = SW.t("shell_error_bad_origin");
  else if (e.status === 500) text = SW.t("shell_error_internal");
  else text = e.text("") || SW.t("shell_error_status", { status: e.status });
  return o.kept && e instanceof SW.HubError && e.status === 502 ? `${text} ${SW.t("add_read_kept")}` : text;
}
// what to offer beside it: Try again when trying again can help, Reload for a page opened from another address
function offer(e, again) {
  if (!(e instanceof SW.HubError)) return undefined;
  if (e.status === 403 && e.error === "bad origin") return { label: SW.t("common_reload"), run: () => location.reload() };
  if (again && (e.unreachable || e.status >= 500 || !e.text(""))) return { label: SW.t("common_try_again"), run: again };
  return undefined;
}
function failed(line, e, again, o = {}) {
  line.setAttribute("role", o.alert ? "alert" : "status");   // a failed destructive action interrupts (02 8.6)
  SW.result(line, "bad", says(e, o), { action: offer(e, again) });
}
// A line that keeps its place while the same thing is said again (a poll must not be announced every time).
function put(line, kind, text) {
  if (line.dataset.state === kind && line._said === text) return;
  line._said = text;
  SW.result(line, kind, text);
}
const clear = (line) => { if (line.dataset.state) { line._said = null; SW.result(line, null); } };
// live data that stopped arriving keeps what was shown and says how old it is (04 3.5); `at` is when it last arrived
function stale(line, at) {
  const text = SW.t("common_last_update", { age: ago(Math.round((Date.now() - at) / 1000)) }), said = line.querySelector(".result__text");
  if (line.dataset.state === "warn" && said) { said.textContent = text; line._said = text; } else put(line, "warn", text);
}
// A press that talks to the Hub (04 3.2, 3.5): its button shows the working form, `box` (a result line, or answer()) says what is
// under way and then what came of it. fn gives nothing (the line is cleared), a text or node (it worked), or
// { kind, text, code, action } (code: the Hub's own text). A failure is the Hub's words and, where it helps, Try again.
async function act(box, label, fn, o = {}) {
  const line = box.line || box, b = o.button;
  if (b && !SW.busy(b, o.busy || label)) return;                     // a second press while it works does nothing
  if (box.code) box.code.replaceChildren();
  line.setAttribute("role", "status");
  SW.result(line, "run", label);
  try {
    const r = await fn();
    if (!r) SW.result(line, null);
    else {
      const d = typeof r === "string" || r instanceof Node ? { text: r } : r;
      if (o.alert && d.kind === "bad") line.setAttribute("role", "alert");
      SW.result(line, d.kind || "ok", d.text, d.action ? { action: d.action } : {});
      if (d.code && box.code) box.code.replaceChildren(codeBlock(d.code));
    }
  } catch (e) { failed(line, e, () => act(box, label, fn, o), o); }
  finally { if (b) SW.idle(b); }
}
// Data that loads for a block (04 3.5): a skeleton until the first data (none when `quiet`: the old data stays until the new
// arrives), then the content; a failure is a line with Try again. A later load of the same region wins.
async function fill(region, thing, fn, o = {}) {
  if (region._load && !region._load.quiet) region._load.done();   // a skeleton still showing: its timers stop
  const load = region._load = o.quiet ? { quiet: true, done: (...kids) => region.replaceChildren(...kids) } : SW.loading(region, { thing, items: o.items || 3 });
  const mine = () => region._load === load;
  try { const kids = [await fn()].flat().filter(Boolean); if (mine()) { region._load = null; load.done(...kids); } }
  catch (e) {
    if (!mine()) return;
    region._load = null;
    const line = resultLine();
    load.done(line); failed(line, e, () => fill(region, thing, fn, o));
  }
}
// A button that cannot be pressed yet keeps its place and says why (04 3.4); pressing it moves focus to what blocks it.
function disabled(b, reason, blocker) {
  b._blocker = blocker || null;
  SW.disable(b, reason);
}
window.addEventListener("click", (e) => {                    // in the capture phase before the shared script drops the press
  const b = e.target.closest && e.target.closest('[aria-disabled="true"]');
  const to = b && b._reason && b.getAttribute("aria-busy") !== "true" && b._blocker && b._blocker();
  if (to) to.focus();
}, true);
// a short state sentence that starts with its shape (04 3.3): never colour alone
const note = (kind, text) => h("p", { class: "result", role: "status", "data-state": kind }, SW.shape({ ok: "s-filled", bad: "s-octagon", warn: "s-triangle", info: "s-diamond", neutral: "s-hollow" }[kind]),
  h("span", { class: "result__text" }, text));

// ---------- Recently added (04 7): the newest additions with their photos; check, correct by hand or by the Label Reader, undo ----------
// The fields of a record in the four groups of 04 7.2. kind: text (required: the Hub wants it), colour, range, whole, number.
const REC_FIELDS = [
  { key: "vendor", label: "common_field_brand", group: "identity", kind: "text", required: true },
  { key: "name", label: "common_field_name", group: "identity", kind: "text", required: true },
  { key: "material", label: "common_field_material", group: "identity", kind: "text", required: true },
  { key: "color_hex", label: "common_field_colour", group: "identity", kind: "colour" },
  { key: "line", label: "common_field_line", group: "identity", kind: "text" },
  { key: "net", label: "common_field_net_weight", group: "weights", kind: "number", unit: "unit_g", bad: "field_error_grams" },
  { key: "tare", label: "common_field_empty_spool_weight", group: "weights", kind: "number", unit: "unit_g", bad: "field_error_grams" },
  { key: "density", label: "common_field_density", group: "weights", kind: "number", unit: "unit_g_cm3", bad: "add_review_error_density" },
  { key: "nozzle", label: "common_field_nozzle", group: "temperatures", kind: "whole", unit: "unit_c", example: "220" },
  { key: "bed", label: "common_field_bed", group: "temperatures", kind: "whole", unit: "unit_c", example: "60" },
  { key: "nozzle_range", label: "common_field_nozzle_range", group: "temperatures", kind: "range", unit: "unit_c", example: "190-230" },
  { key: "bed_range", label: "common_field_bed_range", group: "temperatures", kind: "range", unit: "unit_c", example: "50-60" },
  { key: "price_per_kg", label: "common_field_price_per_kg", group: "other", kind: "number", bad: "recent_error_number" },
];
const REC_GROUPS = [["identity", "common_group_identity"], ["weights", "recent_group_weights"],
  ["temperatures", "common_group_temperatures"], ["other", "common_group_other"]];
const REC_BY = Object.fromEntries(REC_FIELDS.map((f) => [f.key, f]));
const recLabel = (k) => (REC_BY[k] ? SW.t(REC_BY[k].label) : k);
// a value as the person reads it: "(empty)", the colour with its #, a number with its unit
function recShow(k, v) {
  if (v == null || v === "") return SW.t("common_field_empty_value");
  if (k === "color_hex") return "#" + String(v).replace("#", "").toUpperCase();
  return REC_BY[k] && REC_BY[k].unit ? `${v} ${SW.t(REC_BY[k].unit)}` : String(v);
}
const recInput = (f, v) => (v == null ? "" : f.kind === "colour" ? "#" + String(v).replace("#", "").toUpperCase() : String(v));
// what was typed as [true, the value to send (null: empty)] or [false, the sentence for the field]
function recParse(f, text) {
  const t = String(text).trim();
  if (f.kind === "text") return t || !f.required ? [true, t || null] : [false, SW.t("recent_error_required")];
  if (!t) return [true, null];
  if (f.kind === "colour") { const m = /^#?([0-9a-fA-F]{6})$/.exec(t); return m ? [true, m[1].toUpperCase()] : [false, SW.t("add_card_colour_error")]; }
  if (f.kind === "range") return /^\d{1,3}\s*-\s*\d{1,3}$/.test(t) ? [true, t] : [false, SW.t("common_error_range")];
  if (f.kind === "whole") { const n = /^\d{1,3}$/.test(t) ? Number(t) : 0; return n > 0 && n < 500 ? [true, n] : [false, SW.t("field_error_whole_number", { example: f.example })]; }
  const n = /^\d+([.,]\d+)?$/.test(t) ? Number(t.replace(",", ".")) : 0;
  return n > 0 ? [true, n] : [false, SW.t(f.bad)];
}
function recSame(f, was, now) {
  if (f.kind === "colour") return String(was ?? "").replace("#", "").toUpperCase() === String(now ?? "");
  if (f.kind === "number" || f.kind === "whole") return was == null ? now == null : Number(was) === now;
  return (was || null) === (now || null);
}
const recWhen = (at) => String(at || "").slice(0, 16).replace("T", " ");
// the relative time of the list (04 7.1); a day or more shows the date
function recAge(at) {
  const s = Math.round((Date.now() - Date.parse(at)) / 1000);
  if (!(s >= 0)) return recWhen(at);
  if (s < 60) return SW.t("common_age_seconds", { count: s });
  if (s < 3600) return SW.t("common_age_minutes", { count: Math.floor(s / 60) });
  if (s < 86400) return SW.t("common_age_hours", { count: Math.floor(s / 3600) });
  return recWhen(at);
}
// where it came from in words; a source the page has no word for is shown as the Hub gave it
function recSource(r) {
  const src = r.source === "web" ? (r.photos ? "phone" : "hand") : r.source;
  const key = { phone: "recent_source_phone", hand: "recent_source_hand", station: "recent_source_station" }[src];
  return key ? SW.t(key) : String(r.source || "");
}
// "<Brand> <Name>" of each filament, and "x<n>" for several spools
function recNames(spools) {
  const base = [...new Set(spools.map((s) => [s.vendor, s.name].filter(Boolean).join(" ")))].join(", ") || SW.t("recent_no_spools");
  return spools.length > 1 ? SW.t("recent_name_many", { name: base, count: spools.length }) : base;
}
const recSpools = (ids) => (ids.length ? SW.t("recent_spool_label", { count: ids.length, ids: ids.join(", ") }) : SW.t("recent_no_spools"));
// the state of a record is a status badge: a shape and a word (04 3.3); a state the badges do not know is shown as the Hub gave it
const HIST_WORD = { detected: "as_detected", revised_ai: "revised_ai", edited: "edited" };
const histMark = (state) => (HIST_WORD[state] ? SW.status(HIST_WORD[state], { small: true }) : h("span", { textContent: state }));
// what a change did to the filaments, as the sentences of 04 7.2 (an undo puts the spools back on the filament they had)
function recFilaments(what, rev) {
  const fl = rev.filaments || {};
  const use = (id, isNew) => SW.t(isNew ? "recent_result_filament_new" : "recent_now_use", isNew ? { filament: id } : { id });
  const left = (ids) => (ids && ids.length ? SW.t("recent_result_filament_empty", { ids: ids.join(", ") }) : "");
  if (what === "undo") return [fl.undo_to || fl.to !== fl.from ? use(fl.undo_to || fl.from, !!fl.undo_to) : "", left(fl.orphaned_by_undo)];
  return [fl.to !== fl.from ? use(fl.to, fl.created) : "", left(fl.orphaned)];
}
// the changes of a revision, one per field
const recChanges = (rev) => [...new Map((rev.changes || []).map((c) => [c.field, c])).values()];

function historyTab() {
  const intro = h("p", { class: "muted" });
  const missing = h("div");                                   // "no longer kept" for an address that names a record the Hub dropped
  const list = h("div");
  const el = h("section", { class: "hidden" }, intro, missing, list);
  const hp = (id, what) => `history/${encodeURIComponent(id)}${what ? "/" + what : ""}`;
  const photo = (id, n) => `${BASE}/api/${hp(id, "photos/" + n)}`;
  let records = [], reader = false, keep = 0;                 // the list as the Hub last gave it; whether the Label Reader is on
  let addr = "", ready = Promise.resolve();                   // the record the address names; the list being read
  const item = (id) => list.querySelector(`.coll__item[data-id="${CSS.escape(id)}"]`);

  // ----- the list (7.1) -----
  async function load() {
    missing.replaceChildren();
    await fill(list, SW.t("nav_recently_added"), async () => {
      const d = await api("history");
      records = d.records; reader = !!d.ai; keep = d.keep;
      intro.textContent = SW.t("recent_intro", { count: d.keep, size: SW.t("recent_size_mb", { value: (d.photo_bytes / 1048576).toFixed(1) }) });
      return records.length ? table() : SW.empty({ icon: "recent", title: SW.t("recent_empty_title"), text: SW.t("recent_empty_text") });
    });
  }
  function table() {
    const col = (name, label, hidden) => h("div", { class: "coll__cell", role: "columnheader", "data-col": name }, h("span", { class: hidden ? "sr" : "", textContent: label }));
    const box = h("div", { class: "coll coll--recent", role: "table", "aria-label": SW.t("nav_recently_added") },
      h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
        col("expand", SW.t("common_details"), true), col("visual", SW.t("recent_col_photo")), col("title", SW.t("recent_col_added")),
        col("status", SW.t("common_field_state")), col("spool", SW.t("recent_col_spool")))),
      ...records.map(row));
    SW.collection(box, { name: "recent" });
    // the expand button and the address say the same thing (04 2.4): opening a record names it, closing it leaves it
    new MutationObserver((ms) => {
      for (const m of ms) {
        const x = m.target, it = x.closest(".coll__item");
        if (!it || !x.matches(".coll__expand")) continue;
        const id = it.dataset.id, shown = x.getAttribute("aria-expanded") === "true";
        if (shown) { ensure(it); if (location.hash !== "#recent/" + id) location.hash = "#recent/" + id; }
        else if (location.hash === "#recent/" + id) location.hash = "#recent";
      }
    }).observe(box, { subtree: true, attributes: true, attributeFilter: ["aria-expanded"] });
    return box;
  }
  // the first photo small, with its count; a dashed box when no photo was kept
  const listThumb = (r) => (r.photos
    ? h("span", { class: "thumb" }, h("img", { class: "thumb__img", alt: "", loading: "lazy", src: photo(r.id, 1) }),
      r.photos > 1 ? h("span", { class: "thumb__count mono", "aria-hidden": "true", textContent: String(r.photos) }) : null)
    : h("span", { class: "thumb thumb--none" }, SW.icon("camera", "icon--s"), h("span", { class: "sr", textContent: SW.t("photo_none") })));
  function row(r) {
    const id = r.id, name = recNames(r.spools);
    const cell = (c, prio, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": c, "data-prio": prio }, ...kids);
    const x = h("button", { class: "btn btn--ghost btn--icon coll__expand", type: "button", "aria-expanded": "false", "aria-controls": "detail-" + id,
      "aria-label": SW.t("detail_for", { name }) }, SW.icon("chevron"));
    const main = h("div", { class: "coll__row", role: "row" },
      cell("expand", "1", x), cell("visual", "1", listThumb(r)),
      cell("title", "1", h("a", { class: "coll__title", href: "#recent/" + id, textContent: name }),
        h("span", { class: "coll__sub" }, recSource(r), " · ", h("time", { datetime: r.at, title: recWhen(r.at), textContent: recAge(r.at) }))),
      cell("status", "1", histMark(r.state)),
      cell("spool", "2", h("span", { class: "mono", textContent: recSpools(r.spools.map((s) => s.spool_id)) })));
    const reg = detail(r, name);
    const it = h("div", { class: "coll__item", role: "rowgroup", "data-id": id }, main,
      h("div", { class: "coll__row coll__row--detail", role: "row", hidden: true }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": "5" }, reg)));
    it._reg = reg;                                            // a dialog profile moves the region out of the row: keep the way back to it
    main.addEventListener("click", (e) => { if (!e.target.closest("a, button")) location.hash = "#recent/" + id; });   // the whole card opens it
    return it;
  }
  // the state badge of a record changed: in its row and in its head
  function setState(id, state) {
    const it = item(id), r = records.find((x) => x.id === id);
    if (r) r.state = state;
    if (it) for (const c of [...it.querySelectorAll('[data-col="status"]'), ...it._reg.querySelectorAll(".recent__state")]) c.replaceChildren(histMark(state));
  }
  function retitle(id, spools) {
    const it = item(id), r = records.find((x) => x.id === id), name = recNames(spools);
    if (r) r.spools = spools;
    if (!it) return;
    it.querySelector(".coll__title").textContent = it._reg.querySelector(".detail__title").textContent = name;
    it.querySelector(".coll__expand").setAttribute("aria-label", SW.t("detail_for", { name }));
    it.querySelector('[data-col="spool"] .mono').textContent = recSpools(spools.map((s) => s.spool_id));
  }

  // ----- one record (7.2): the detail region of its row -----
  function detail(r, name) {
    const id = r.id, at = records.findIndex((x) => x.id === id);
    const step = (to) => () => { if (to) location.hash = "#recent/" + to.id; };
    const newer = SW.iconBtn("chevron", SW.t("recent_newer_addition"), { cls: "recent__newer", run: step(records[at - 1]) });
    const older = SW.iconBtn("chevron", SW.t("recent_older_addition"), { cls: "recent__older", run: step(records[at + 1]) });
    if (!records[at - 1]) newer.setAttribute("aria-disabled", "true");
    if (!records[at + 1]) older.setAttribute("aria-disabled", "true");
    const reg = h("section", { class: "detail", id: "detail-" + id, "aria-labelledby": `detail-${id}-title`, hidden: true },
      h("header", { class: "detail__head" },
        SW.iconBtn("chevron", SW.t("detail_back", { name: SW.t("nav_recently_added") }), { cls: "detail__back" }),
        h("h2", { class: "detail__title", id: `detail-${id}-title`, tabindex: "-1", textContent: name }),
        h("span", { class: "recent__state" }, histMark(r.state)), newer, older,
        SW.iconBtn("close", SW.t("detail_close", { name }), { cls: "detail__close" })),
      h("p", { class: "page-head__meta" }, h("time", { class: "mono", datetime: r.at, textContent: recWhen(r.at) }),
        h("span", { textContent: recSource(r) }), h("span", { class: "mono", textContent: recSpools(r.spools.map((s) => s.spool_id)) })));
    reg._body = h("div");
    reg.append(reg._body);
    return reg;
  }
  // the edit forms of the list with unsaved values; reloading the list drops them, so it asks first (the shell's guard, 6.1)
  const dirtySlots = () => [...list.querySelectorAll(".coll__item")].flatMap((it) => (it._reg && it._reg._ctx ? it._reg._ctx.slots.filter((s) => s.dirty()) : []));
  async function leaveOk() {
    const ds = dirtySlots();
    return !ds.length || SW.leaveAsk(ds.map((s, i) => SW.t(i ? "form_leave_next" : "form_leave_first",
      { count: s.g.changed().length, group: recSpools(s.s.spool_ids) })).join(", "));
  }
  const ensure = (it) => {                                    // read the record the first time it opens
    const reg = it._reg;
    if (!reg._loaded) { reg._loaded = true; loadRecord(it.dataset.id, reg); }
  };
  const goneNote = () => h("div", {}, note("warn", SW.t("recent_not_found", { keep })),
    h("p", {}, SW.btn(SW.t("recent_back_to_list"), { action: "back", run: async () => { if (!(await leaveOk())) return; location.hash = "#recent"; ready = load(); } })));
  async function loadRecord(id, reg) {
    await fill(reg._body, SW.t("nav_recently_added"), async () => {
      let rec;
      try { rec = await api(hp(id)); }
      catch (e) { if (e instanceof SW.HubError && e.status === 404) return goneNote(); throw e; }
      return recordBody({ id, rec, reg, slots: [], res: resultLine(), list: h("div"), count: h("span", { class: "mono" }) });
    }, { items: 2 });
  }
  // c: the record on show: its id, the Hub's reply, its slots (one per saved item) and the revisions' result line
  function recordBody(c) {
    const { id, rec } = c;
    const photos = h("div", { class: "group" }, h("div", { class: "group__head" },
      h("h3", { class: "group__title" }, SW.t("recent_record_photos"), " ", h("span", { class: "mono", textContent: String(rec.photos) }))),
      h("div", { class: "group__body" }, rec.photos
        ? h("div", { class: "photos" }, ...Array.from({ length: rec.photos }, (_, i) => {
          const b = h("button", { class: "thumb thumb--m", type: "button", "aria-label": SW.t("photo_enlarge", { number: i + 1, total: rec.photos }) },
            h("img", { class: "thumb__img", alt: "", loading: "lazy", src: photo(id, i + 1) }));
          b.addEventListener("click", () => viewer(c, i + 1, b));
          return b;
        }))
        : h("span", { class: "thumb thumb--none" }, SW.icon("camera", "icon--s"), h("span", { class: "sr", textContent: SW.t("photo_none") }))));
    c.slots = rec.saved.map((s) => slotFor(c, s));
    c.reg._ctx = c;
    revisions(c);
    return [h("div", { class: "detail__body" },
      h("div", { class: "detail__section" }, photos, ...c.slots.map((s) => s.group)),
      h("div", { class: "detail__section" }, ...(reader ? c.slots.map((s) => askGroup(c, s)) : [note("info", SW.t("recent_ask_off"))]),
        h("div", { class: "group" }, h("div", { class: "group__head" }, h("h3", { class: "group__title", id: `rev-${id}`, tabindex: "-1" }, SW.t("revision_heading"), " ", c.count)),
          h("div", { class: "group__body" }, c.list, c.res))))];
  }
  // a change came back from the Hub (it sends the whole record): the groups it touched, the revisions and the badges follow;
  // a group being edited with unsaved values is left alone
  function applied(c, r, force) {
    c.rec = r;
    if (r.saved.length !== c.slots.length) { c.reg._body.replaceChildren(...recordBody(c)); }
    else for (const slot of c.slots) {
      const now = r.saved.find((x) => x.item === slot.s.item);
      if (now && (slot === force || (JSON.stringify(now) !== JSON.stringify(slot.s) && !slot.dirty()))) { slot.s = now; slot.show(); }
    }
    revisions(c);
    setState(c.id, r.state);
    retitle(c.id, r.spools);
  }

  // ----- the fields of one saved item: shown, then edited in place (7.2) -----
  function slotFor(c, s) {
    const slot = { s, g: null, group: null, say: () => {} };
    slot.dirty = () => !!(slot.g && slot.group.isConnected && slot.g.dirty());
    slot.show = () => { slot.g = null; slot.set(viewGroup(c, slot)); };
    slot.set = (g) => { if (slot.group) slot.group.replaceWith(g); slot.group = g; };
    slot.group = viewGroup(c, slot);
    return slot;
  }
  const spoolsHead = (s) => [h("h3", { class: "group__title", textContent: recSpools(s.spool_ids) }),
    s.spool_ids.length > 1 ? h("p", { class: "group__desc", textContent: SW.t("recent_all_apply") }) : null];
  function viewGroup(c, slot) {
    const s = slot.s, res = resultLine();
    const foot = h("div", { class: "group__foot", hidden: true }, res);
    slot.say = (kind, text) => { foot.hidden = false; SW.result(res, kind, text); };
    const edit = SW.btn(SW.t("recent_edit"), { icon: "pencil", action: "edit", run: () => {
      slot.set(editGroup(c, slot));
      slot.group.querySelector(".field__control").focus();
    } });
    const row = (f) => {
      const v = s.values[f.key], empty = v == null || v === "";
      return h("div", { class: "kv__row" }, h("dt", { class: "kv__key", textContent: SW.t(f.label) }),
        h("dd", { class: "kv__value" }, empty ? h("span", { class: "muted", textContent: SW.t("common_field_empty_value") })
          : f.kind === "colour" ? [SW.swatch("#" + String(v).replace("#", "")), h("span", { class: "mono", textContent: recShow(f.key, v) })]
            : h("span", { class: f.kind === "text" ? "" : "mono", textContent: recShow(f.key, v) })));
    };
    return h("div", { class: "group" }, h("div", { class: "group__head" }, h("div", {}, ...spoolsHead(s)), edit),
      h("div", { class: "group__body" }, ...REC_GROUPS.map(([gk, label]) => h("div", { class: "detail__section" },
        h("h4", { class: "detail__heading", textContent: SW.t(label) }), h("dl", { class: "kv" }, ...REC_FIELDS.filter((f) => f.group === gk).map(row))))), foot);
  }
  function editGroup(c, slot) {
    const s = slot.s, res = resultLine(), fields = {}, title = recSpools(s.spool_ids);
    const field = (f) => fields[f.key] = SW.field({ label: SW.t(f.label), name: f.key, value: recInput(f, s.values[f.key]), mono: f.kind !== "text",
      unit: f.unit ? SW.t(f.unit) : undefined, type: f.kind === "number" || f.kind === "whole" ? "number" : "text", decimal: f.kind === "number",
      placeholder: f.kind === "range" ? f.example : undefined, check: (text) => { if (text === recInput(f, s.values[f.key])) return ""; const p = recParse(f, text); return p[0] ? "" : p[1]; } });
    const cancel = SW.btn(SW.t("common_cancel"), { action: "cancel", run: async () => {
      if (slot.g.dirty() && !(await SW.leaveAsk(SW.t("form_leave_first", { count: slot.g.changed().length, group: title })))) return;
      slot.show();
      slot.group.querySelector('[data-action="edit"]').focus();
    } });
    const save = SW.btn(SW.t("common_save_changes"), { type: "submit", cls: "btn--primary", action: "save" });
    const form = h("form", { class: "group", novalidate: true },
      h("div", { class: "group__head" }, h("div", {}, ...spoolsHead(s))),
      h("div", { class: "group__body" }, ...REC_GROUPS.map(([gk, label]) => h("div", { class: "detail__section" },
        h("h4", { class: "detail__heading", textContent: SW.t(label) }), ...REC_FIELDS.filter((f) => f.group === gk).map(field)))),
      h("div", { class: "group__foot" }, res, cancel, save));
    // only the changed fields are sent, in one request, so one save is one revision: this handler runs before the shared group's own
    form.addEventListener("submit", (e) => { e.preventDefault(); e.stopImmediatePropagation(); store(); });
    slot.g = SW.formGroup(form, { title });
    async function store() {
      const values = {}, bad = [];
      for (const f of REC_FIELDS) {
        const text = fields[f.key]._control.value;
        if (text === recInput(f, s.values[f.key])) { SW.fieldError(fields[f.key], null); continue; }   // untouched: a value the Hub kept stays as it is
        const [ok, v] = recParse(f, text);
        SW.fieldError(fields[f.key], ok ? null : v);
        if (!ok) bad.push(fields[f.key]);
        else if (!recSame(f, s.values[f.key], v)) values[f.key] = v;
      }
      if (bad.length) { bad[0]._control.focus(); return; }
      if (!Object.keys(values).length) { SW.result(res, "neutral", SW.t("common_nothing_changed")); return; }
      const controls = REC_FIELDS.map((f) => fields[f.key]._control);
      for (const e of controls) e.readOnly = true;            // what is typed while the save runs would be lost
      await act(res, SW.t("common_saving"), async () => {
        try { return await send(); } finally { for (const e of controls) e.readOnly = false; }
      }, { button: save });
      async function send() {
        const r = await api(hp(c.id, "apply"), { body: { item: s.item, values } });
        const rev = r.revisions[r.revisions.length - 1] || {}, names = recChanges(rev).map((x) => recLabel(x.field));
        slot.g = null;
        applied(c, r, slot);
        slot.say("ok", [SW.t("recent_saved", { count: names.length, fields: names.join(", ") }), ...recFilaments("apply", rev)].filter(Boolean).join(" "));
        return null;
      }
    }
    return form;
  }

  // ----- ask the Label Reader to correct it (7.2) -----
  function askGroup(c, slot) {
    const res = resultLine(), prop = h("div");
    const text = SW.field({ type: "textarea", label: SW.t("recent_ask_label"), hint: SW.t("recent_ask_hint"), placeholder: SW.t("recent_ask_placeholder") });
    const send = SW.btn(SW.t("recent_ask_button"), { action: "ask", run: () => ask() });
    const sync = () => disabled(send, text._control.value.trim() ? null : SW.t("recent_ask_reason"), () => text._control);
    const group = h("div", { class: "group" }, h("div", { class: "group__head" }, h("div", {},
      h("h3", { class: "group__title", textContent: SW.t("recent_ask_title") }),
      c.rec.saved.length > 1 ? h("p", { class: "group__desc", textContent: recSpools(slot.s.spool_ids) }) : null)),
      h("div", { class: "group__body" }, text, h("div", {}, send), res, prop));
    text._control.addEventListener("input", sync);
    sync();
    async function ask() {
      await act(res, SW.t("changes_asking"), async () => {
        prop.replaceChildren();
        let p;
        try { p = await api(hp(c.id, "revise"), { body: { item: slot.s.item, note: text._control.value.trim() } }); }
        catch (e) {
          if (e instanceof SW.HubError && e.data && e.data.code === "ai_off") { group.replaceWith(note("info", SW.t("recent_ask_off"))); return null; }
          throw e;
        }
        if (!p.changes.length) return { kind: "neutral", text: SW.t("changes_none") };
        prop.replaceChildren(proposal(c, p, res, prop, text));
        prop.querySelector('[data-action="accept"]').focus();
        return null;
      }, { button: send, busy: SW.t("common_working"), kept: true });
    }
    return group;
  }
  // the before-and-after change list (02 7.9): nothing changes until Accept
  function proposal(c, p, res, prop, text) {
    const tid = SW.uid("prop");
    const sr = (key) => h("span", { class: "sr", textContent: SW.t(key) });
    const accept = SW.btn(SW.t("common_accept"), { cls: "btn--primary", action: "accept", run: (e) =>
      act(res, SW.t("common_accepting"), async () => {
        const r = await api(hp(c.id, "apply"), { body: { proposal: p.proposal } });
        const rev = r.revisions[r.revisions.length - 1] || {};
        prop.replaceChildren();
        applied(c, r);
        return [SW.t("changes_accepted", { count: p.changes.length, number: rev.n }), ...recFilaments("apply", rev)].filter(Boolean).join(" ");
      }, { button: e.currentTarget }) });
    const discard = SW.btn(SW.t("common_discard"), { action: "discard", run: () => {
      prop.replaceChildren();
      SW.result(res, "neutral", SW.t("changes_discarded"));
      text._control.focus();
    } });
    return h("section", { class: "changes", "aria-labelledby": tid },
      h("h4", { class: "changes__title", id: tid, textContent: SW.t("changes_title", { count: p.changes.length }) }),
      h("ul", { class: "changes__list" }, ...p.changes.map((k) => h("li", { class: "changes__item" },
        h("span", { class: "changes__key", textContent: recLabel(k) }),
        h("span", { class: "changes__old mono" }, sr("changes_was"), recShow(k, p.before[k])),
        h("span", { "aria-hidden": "true", textContent: "→" }),
        h("span", { class: "changes__new mono" }, sr("changes_becomes"), recShow(k, p.after[k]))))),
      p.no_photo ? h("p", { class: "muted", textContent: SW.t("recent_ask_no_photo") }) : null,
      h("p", { class: "changes__note", textContent: SW.t("changes_note") }),
      h("div", { class: "actions" }, discard, accept));
  }

  // ----- revisions with undo (7.2, 02 7.10) -----
  function revisions(c) {
    const live = c.rec.revisions.filter((v) => !v.undone), last = live[live.length - 1];
    const one = (v) => {
      const changes = recChanges(v);
      const undo = last && last.n === v.n ? SW.btn(SW.t("revision_undo", { number: v.n }), { icon: "undo", action: "undo", run: (e) =>
        act(c.res, SW.t("common_working"), async () => {
          const r = await api(hp(c.id, "undo"), { body: { revision: v.n } });
          const done = r.revisions.find((x) => x.n === v.n) || v;
          applied(c, r);
          return [SW.t("recent_result_undone", { number: v.n }), ...recChanges(done).map((x) => SW.t("recent_revision_value_again", { field: recLabel(x.field), value: recShow(x.field, x.old) })),
            ...recFilaments("undo", done)].filter(Boolean).join(" ");
        }, { button: e.currentTarget, alert: true }) }) : null;
      return h("li", { class: "revisions__item", "data-state": v.undone ? "undone" : null },
        h("p", {}, SW.t(v.by === "ai" ? "recent_revision_ai" : "recent_revision_hand", { number: v.n, time: recWhen(v.at), changes: changes.map((x) => recLabel(x.field)).join(", ") }),
          v.undone ? " " + SW.t("recent_revision_undone") : ""),
        h("div", { class: "changes changes--compact" }, h("ul", { class: "changes__list" }, ...changes.map((x) => h("li", { class: "changes__item" },
          h("span", { class: "changes__key", textContent: recLabel(x.field) }),
          h("span", { class: "changes__old mono" }, h("span", { class: "sr", textContent: SW.t("changes_was") }), recShow(x.field, x.old)),
          h("span", { "aria-hidden": "true", textContent: "→" }),
          h("span", { class: "changes__new mono" }, h("span", { class: "sr", textContent: SW.t("changes_becomes") }), recShow(x.field, x.new)))))),
        v.note ? h("p", { class: "muted", textContent: SW.t("recent_revision_note", { note: v.note }) }) : null, undo);
    };
    c.count.textContent = String(c.rec.revisions.length);
    c.list.replaceChildren(c.rec.revisions.length ? h("ol", { class: "revisions__list" }, ...c.rec.revisions.map(one))
      : h("p", { class: "muted", textContent: SW.t("revision_empty") }));
  }

  // ----- the photo viewer (02 7.6): one photo, Previous and Next, Escape closes -----
  function viewer(c, from, opener) {
    const total = c.rec.photos, name = recNames(c.rec.spools);
    let n = from;
    const img = h("img", { class: "viewer__img", alt: "" }), problem = h("div");
    const prev = SW.btn(SW.t("common_previous"), { action: "previous", run: () => move(-1) });
    const next = SW.btn(SW.t("common_next"), { action: "next", run: () => move(1) });
    const dlg = SW.sheet({ title: SW.t("photo_position", { number: n, total }), cls: "viewer", body: [img, problem],
      foot: [prev, next, SW.btn(SW.t("common_close"), { action: "close", run: () => dlg.close() })] });
    function paint() {
      const position = SW.t("photo_position", { number: n, total });
      problem.replaceChildren();
      img.alt = SW.t("photo_viewer_alt", { number: n, total, name });
      img.src = photo(c.id, n);
      dlg.querySelector(".sheet__title").textContent = position;
      prev.setAttribute("aria-disabled", String(n === 1)); next.setAttribute("aria-disabled", String(n === total));
      SW.announce(position);
    }
    function move(by) { if (n + by >= 1 && n + by <= total) { n += by; paint(); } }
    img.addEventListener("error", () => problem.replaceChildren(note("warn", SW.t("photo_load_failed")), h("p", {}, SW.btn(SW.t("common_try_again"), { action: "try-again", run: paint }))));
    dlg.addEventListener("keydown", (e) => {
      const to = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
      if (to) move(to);
      else if (e.key === "Home" && n !== 1) { n = 1; paint(); } else if (e.key === "End" && n !== total) { n = total; paint(); }
    });
    paint();
    SW.openModal(dlg, opener);
  }

  // ----- the address (04 2.4): #recent/<id> opens the record in place under its row -----
  async function open(id) {
    const it = item(id);
    if (!it) { missing.replaceChildren(goneNote()); return; }
    const reg = it._reg;
    if (reg.hidden) SW.openDetail(reg, { opener: it.querySelector(".coll__expand"), focusTitle: false });
    ensure(it);
    it.scrollIntoView({ block: "start" });
    reg.querySelector(".detail__title").focus({ preventScroll: true });
    shellView.paint(false);                                   // the page title names the record (04 2.4)
  }
  async function go(rest) {
    missing.replaceChildren();
    if (!rest) {                                              // back to the list: the record the address named closes
      const was = addr && item(addr);
      addr = "";
      if (was && !was._reg.hidden) await SW.closeDetail(was._reg);
      return;
    }
    const was = addr && addr !== rest && item(addr);          // Newer and Older: the record before closes
    addr = rest;
    if (was && !was._reg.hidden) await SW.closeDetail(was._reg);
    await ready;
    await open(rest);
  }
  // the page title of the record the address names ("Spool 214 · Workshop"), once the list is known
  const title = () => {
    let id = "";
    try { id = decodeURIComponent(location.hash.split("/")[1] || ""); } catch {}   // a malformed address names no record
    const r = records.find((x) => x.id === id);
    return r && r.spools.length ? recSpools(r.spools.map((x) => x.spool_id)) : "";
  };
  return { el, go, title, enter(rest) { if (!dirtySlots().length) ready = load(); return go(rest); }, leave() { addr = ""; } };
}

// ---------- the shell (04 2 and 9): top bar, bottom bar (a rail on tablets), More, Settings; the places and their addresses ----------
const PRINTERS = document.body.dataset.printers === "1";   // the printers module is on (printers.js is loaded)
const HISTORY = document.body.dataset.history === "1";     // the kit's own page: the intake history is here
const PRESETS = document.body.dataset.presets === "1";     // Slicer presets are on
const PUSH = document.body.dataset.push === "1";           // print alerts can be offered
const HUB = document.body.dataset.hub || "";               // the Hub's name; empty until the Hub reports one
const HUB_PAGE = document.body.dataset.hubPage || "";      // the Hub page's address; absent on the public address
const PRODUCT = SW.t("app_name");
SW.configure({ lock: false, hub: HUB || PRODUCT, base: BASE + "/api/" });   // no lock in the web app: the home network is the gate (04 1.1)

// a destination whose Feature is off, or that this address does not serve, opens a page that says so (04 6.10, 7.4)
const hubLink = () => HUB_PAGE ? h("a", { class: "btn", href: HUB_PAGE }, SW.t("common_open_hub_page")) : null;
const notice = (icon, title, text, link) => ({ el: h("section", { class: "hidden" }, SW.empty({ icon, title, text, actions: link ? hubLink() : null })) });
const settingsPage = h("section", { class: "hidden" });    // Settings as a page, from 601 px (04 2.3)
const tabs = {
  add: addTab(),
  spools: openTab(),
  printers: PRINTERS ? printersTab() : notice("printer", SW.t("common_feature_off_title", { feature: SW.t("nav_printers") }), SW.t("common_feature_off_hint"), true),
  recent: HISTORY ? historyTab() : notice("clock", SW.t("recent_public_title"), SW.t("recent_public_text", { product: PRODUCT })),
  presets: PRESETS ? presetsTab() : notice("presets", SW.t("presets_off_title"), SW.t("presets_off_text"), true),
  settings: { el: settingsPage, enter: () => settingsPage.replaceChildren(...settingsBody(true)), leave: () => settingsPage.replaceChildren() },
};
const PLACES = ["add", "spools", "printers", "recent", "presets"];    // what `spoolwarden.place` can hold
const TITLES = { add: "home_add_title", spools: "nav_spools", printers: "nav_printers", recent: "nav_recently_added", presets: "nav_slicer_presets", settings: "nav_settings" };
const ALIAS = { open: "spools", history: "recent" };                  // the old addresses, and the old `tab` values
const PLACE_KEY = "spoolwarden.place";

const pageTitle = h("h1", { class: "page-head__title", tabindex: "-1" });
const page = h("section", { class: "page" }, h("header", { class: "page-head" }, h("div", { class: "page-head__text" }, pageTitle)),
  ...Object.values(tabs).map((t) => t.el));
let place = null, shellView = null;                          // the place on show; SW.shell's handle

function storedPlace() {
  let v = null;
  try { v = localStorage.getItem(PLACE_KEY) || localStorage.getItem("tab"); } catch {}   // "tab" is the key before S3.3
  v = ALIAS[v] || v;
  return PLACES.includes(v) ? v : null;
}
function show(key) {
  const raw = location.hash.slice(1), head = raw.split(/[/?]/)[0];
  const rest = (ALIAS[head] || head) === key && raw.charAt(head.length) === "/" ? raw.slice(head.length + 1) : "";   // #recent/<id>: what follows the place
  if (key !== place) {
    for (const [k, t] of Object.entries(tabs)) { t.el.classList.toggle("hidden", k !== key); (k === key ? t.enter : t.leave)?.(rest); }
    window.scrollTo(0, 0);
  } else tabs[key].go?.(rest);
  place = key;
  page.dataset.section = key;
  pageTitle.textContent = (tabs[key].heading && tabs[key].heading()) || SW.t(TITLES[key]);   // one printer fills the page: its name (04 6.2)
  if (key !== "settings") { try { localStorage.setItem(PLACE_KEY, key); } catch {} }   // #settings is never the stored place (04 2.4)
  paintMore();
}

// ----- addresses (04 2.4): #<place>[/<more>]; #settings is a sheet over the place on phones and a page from 601 px -----
function route(initial) {
  const raw = location.hash.slice(1), head = raw.split(/[/?]/)[0], name = ALIAS[head] || head;
  if (name !== head) history.replaceState(history.state, "", "#" + name + raw.slice(head.length));
  if (name === "settings") {
    if (SW.phone()) {
      if (!place || place === "settings") show(storedPlace() || "add");
      openSettings(initial);
    } else { closeSettings(); show("settings"); }
    return;
  }
  closeSettings();
  if (PLACES.includes(name)) return show(name);
  const keep = storedPlace() || "add";                       // no address, or one the page does not know: the last place
  history.replaceState(history.state, "", "#" + keep);
  show(keep);
}

// ----- sheets: Back closes them (04 2.4). More and the other sheets keep the address and push a same-address entry;
// the Settings sheet is a place of its own, so its entry is the #settings one. -----
const sheets = [];
let settling = 0, settingsRec = null;
function track(dlg, mode, direct) {
  const rec = { dlg, mode, direct, popped: false };
  sheets.push(rec);
  dlg.addEventListener("close", () => {
    sheets.splice(sheets.indexOf(rec), 1);
    if (rec === settingsRec) settingsRec = null;
    paintMore();
    if (rec.popped) return;                                  // Back, or a link, already moved the address
    if (direct) history.replaceState(history.state, "", "#" + place);   // #settings was the first entry: no page of ours to go back to
    else { settling++; history.back(); }
  });
  return rec;
}
function openHere(dlg, opener, reuse) {                      // reuse: the entry of a sheet that just closed
  if (!reuse) history.pushState({ sheet: true }, "", location.href);
  const rec = track(dlg, "same");
  SW.openModal(dlg, opener);
  return rec;
}
window.addEventListener("popstate", () => {
  if (settling) { settling--; return; }
  const top = sheets[sheets.length - 1];
  if (top) { top.popped = true; top.dlg.close(); }
});
function openSettings(direct) {
  if (settingsRec) return;
  const dlg = SW.sheet({ title: SW.t("nav_settings"), body: settingsBody(false) });
  settingsRec = track(dlg, "address", direct);
  SW.openModal(dlg, moreBtn);
  paintMore();
}
function closeSettings() {
  if (!settingsRec) return;
  settingsRec.popped = true;
  settingsRec.dlg.close();
}
// leaving a sheet for an address: the sheet's own history entry becomes that address
function goFrom(rec, hash) {
  rec.popped = true; rec.dlg._noReturn = true;
  history.replaceState(null, "", hash);
  rec.dlg.close();
  route();
  shellView.paint(true);
}

// ----- appearance (02 3.3, F5): the three choices on this device, applied at once and kept by the shared script -----
const APPEARANCE = [["light", "sun"], ["dark", "moon"], ["system", "half-circle"]];
const appearanceNow = () => { const v = document.documentElement.getAttribute("data-theme"); return v === "light" || v === "dark" ? v : "system"; };
const appearanceControl = (o = {}) => SW.segmented({ legend: SW.t("appearance_title"), legendSr: true, cls: "appearance", value: appearanceNow(),
  options: APPEARANCE.map(([value, icon]) => ({ value, icon, label: SW.t("appearance_" + value) })), ...o });
function appearanceButton() {                               // the phone form: an icon button; SW.shell gives it its menu
  const [v, icon] = APPEARANCE.find(([x]) => x === appearanceNow());
  return h("button", { class: "btn btn--ghost btn--icon appearance appearance--menu", type: "button",
    "aria-label": SW.t("appearance_name", { choice: SW.t("appearance_" + v) }) }, SW.icon(icon));
}
window.addEventListener("storage", (e) => {                 // another tab chose: follow it
  if (e.key !== "spoolwarden.appearance" && e.key !== null) return;
  const v = e.key === null ? null : e.newValue;
  SW.setAppearance(v === "light" || v === "dark" ? v : "system");
});

// ----- the Settings sheet or page (04 9.2) -----
const installed = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
let installPrompt = null;                                    // a browser that offers installing (04 10.1)
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; });
// wide: Settings as a page, which also holds "Add to Home Screen" (the More sheet is not there)
function settingsBody(wide) {
  const group = (title, ...kids) => h("section", { class: "settings__group" }, h("h2", { class: "settings__title" }, title), ...kids);
  const live = () => h("p", { class: "result", role: "status" });   // the choice's own sentence goes here (shared script)
  const hubPageLink = () => HUB_PAGE ? h("a", { class: "btn", href: HUB_PAGE }, SW.t("common_open_hub_page")) : null;
  return [h("div", { class: "settings" },
    group(SW.t("appearance_title"), appearanceControl({ wide: true, name: null }), h("p", { class: "muted" }, SW.t("settings_saved_on_phone")), live()),
    group(SW.t("appearance_theme_title"), SW.themePicker(), h("p", { class: "muted" }, SW.t("settings_theme_help")), live()),
    PUSH && typeof alertsPanel === "function" ? group(SW.t("settings_alerts_title"), alertsPanel(() => installSheet())) : null,
    group(SW.t("settings_this_hub"), HUB ? h("p", { class: "settings__hub" }, HUB) : null,
      h("p", { class: "settings__address" }, location.origin + location.pathname), hubPageLink()),
    wide && !installed() ? group(SW.t("nav_more_home_screen"), h("p", { class: "muted" }, SW.t("nav_more_home_screen_summary", { product: PRODUCT })),
      h("p", {}, h("button", { class: "btn", type: "button", on: { click: (e) => addToHome(e.currentTarget) } }, installPrompt ? SW.t("nav_more_install") : SW.t("nav_more_home_screen")))) : null)];
}
function addToHome(opener) {
  if (installPrompt) { installPrompt.prompt(); installPrompt = null; } else installSheet(opener);
}
function installSheet(opener, reuse) {                       // the steps for an iPhone (04 10.1)
  const dlg = SW.sheet({ title: SW.t("install_title", { product: PRODUCT }),
    body: [h("ol", { class: "install" }, [1, 2, 3].map((n) => h("li", {}, SW.t("install_step_" + n)))),
      SW.banner({ kind: "info", text: SW.t("install_note"), inline: true })],
    foot: SW.btn(SW.t("status_done"), { cls: "btn--primary", action: "done", run: () => dlg.close() }) });
  openHere(dlg, opener, reuse);
}

// ----- More (04 9.1): Slicer presets, Settings, Add to Home Screen, Open the Hub page -----
const moreBtn = h("button", { class: "nav__more", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false" },
  SW.icon("more", "nav__icon"), h("span", { class: "nav__label" }, SW.t("nav_more")), h("span", { class: "sr nav__more-current" }));
function moreRow(icon, name, summary, props, run) {
  return h(props.href ? "a" : "button", { class: "more__row", ...(props.href ? {} : { type: "button" }), ...props, on: run ? { click: run } : undefined },
    SW.icon(icon, "more__icon"), h("span", { class: "more__name" }, name), summary ? h("span", { class: "more__summary" }, summary) : null,
    SW.icon("chevron", "icon--s more__chevron"));
}
moreBtn.addEventListener("click", () => {
  const cur = (k) => (place === k ? "page" : undefined);
  const standalone = installed();
  let rec = null;
  const to = (hash) => (e) => { e.preventDefault(); goFrom(rec, hash); };
  const rows = [
    moreRow("presets", SW.t("nav_slicer_presets"), "", { href: "#presets", "aria-current": cur("presets"),
      ...(PRESETS ? {} : { "data-state": "off", "aria-label": SW.t("nav_slicer_presets") + SW.t("nav_off_suffix") }) }, to("#presets")),
    moreRow("settings", SW.t("nav_settings"), SW.t("nav_more_settings_summary"), { href: "#settings" }, to("#settings")),
    standalone ? null : moreRow("plus", SW.t(installPrompt ? "nav_more_install" : "nav_more_home_screen"), SW.t("nav_more_home_screen_summary", { product: PRODUCT }), {},
      () => { rec.popped = true; rec.dlg._noReturn = true; rec.dlg.close(); if (installPrompt) { installPrompt.prompt(); installPrompt = null; settling++; history.back(); } else installSheet(moreBtn, true); }),
    HUB_PAGE ? moreRow("overview", SW.t("common_open_hub_page"), SW.t("nav_more_hub_page_summary"),
      { href: HUB_PAGE, ...(standalone ? { target: "_blank", rel: "noopener" } : {}) }) : null,
  ];
  const dlg = SW.sheet({ title: SW.t("nav_more"), bodyTag: "nav", bodyLabel: SW.t("nav_more_sections"), body: h("div", { class: "more" }, rows),
    onClose: () => moreBtn.setAttribute("aria-expanded", "false") });
  rec = openHere(dlg, moreBtn);
  moreBtn.setAttribute("aria-expanded", "true");
  const first = dlg.querySelector(".more__row");
  if (first) first.focus();
});
function paintMore() {                                       // More is current while Slicer presets or the Settings sheet is
  const key = settingsRec ? "settings" : place === "presets" ? "presets" : null, name = key ? SW.t(TITLES[key]) : "";
  moreBtn.querySelector(".nav__more-current").textContent = key ? ", " + name : "";
  if (key) { moreBtn.dataset.state = "current"; moreBtn.setAttribute("aria-label", SW.t("nav_more_current", { section: name })); }
  else { delete moreBtn.dataset.state; moreBtn.removeAttribute("aria-label"); }
}

// ----- the frame: skip link, top bar, navigation, the page -----
function topBar() {
  const hub = HUB ? h("span", { class: "topbar__hub" }, h("span", { "aria-hidden": "true" }, "/"), " ", HUB) : null;
  return h("header", { class: "topbar" },
    h("div", { class: "topbar__brand" }, SW.h("svg", { class: "topbar__mark", "aria-hidden": "true", focusable: "false" }, SW.h("use", { href: "#i-spoolwarden" })),
      h("span", { class: "topbar__name" }, PRODUCT), " ", hub),
    h("div", { class: "topbar__tools" }, appearanceControl({ name: "appearance" }), appearanceButton()));
}
function navItem([key, name, icon], tab) {
  const label = key === "recent"                             // the bar shows the short name; the full one is read (02 2.4)
    ? h("span", { class: "nav__label" }, h("span", { class: "nav__label-full" }, SW.t("nav_recently_added")), h("span", { class: "nav__label-short", "aria-hidden": "true" }, SW.t("nav_recent")))
    : h("span", { class: "nav__label" }, SW.t(name));
  const a = h("a", { class: "nav__item", href: "#" + key }, SW.icon(icon, "nav__icon"), label);
  if (tab) a.setAttribute("data-tab", "");
  const off = key === "printers" && !PRINTERS ? SW.t("nav_printers_off") : key === "recent" && !HISTORY ? SW.t("nav_recent_public")
    : key === "presets" && !PRESETS ? SW.t("nav_slicer_presets") + SW.t("nav_off_suffix") : null;
  if (off) { a.dataset.state = "off"; a.setAttribute("aria-label", off); }   // dimmed, and the name says why (04 2.1)
  return h("li", {}, a);
}
function navigation() {
  const main = [["add", "nav_add", "plus"], ["spools", "nav_spools", "spool"], ["printers", "nav_printers", "printer"], ["recent", "nav_recent", "recent"]];
  const rest = [["presets", "nav_slicer_presets", "presets"], ["settings", "nav_settings", "settings"]];   // in More on phones
  return h("nav", { class: "nav", "aria-label": SW.t("nav_label") },
    h("h2", { class: "nav__heading", id: "nav-main" }, SW.t("nav_everyday")), h("ul", { class: "nav__group", "aria-labelledby": "nav-main" }, main.map((i) => navItem(i, true))),
    h("h2", { class: "nav__heading", id: "nav-rest" }, SW.t("nav_more")), h("ul", { class: "nav__group", "aria-labelledby": "nav-rest" }, rest.map((i) => navItem(i, false))));
}
{
  const skip = h("a", { class: "skip", href: "#main" }, SW.t("common_skip_to_content"));
  const main = h("main", { class: "shell__main", id: "main", tabindex: "-1" }, page);
  skip.addEventListener("click", (e) => { e.preventDefault(); main.focus(); });   // the address keeps the place
  const nav = navigation();
  app.replaceWith(skip, h("div", { class: "shell" }, topBar(), nav, main),
    h("div", { class: "toasts", "aria-live": "polite" }), h("div", { class: "sr", id: "announcer", "aria-live": "polite" }));
  route(true);
  shellView = SW.shell({ hub: HUB || PRODUCT, home: "add", titleOf: (s) => { const k = ALIAS[s] || s; return (tabs[k] && tabs[k].title && tabs[k].title()) || SW.t(TITLES[k] || TITLES[place]); }, onSection: () => route() });
  nav.append(moreBtn);                                       // after SW.shell: this More has its own sheet
  paintMore();
  matchMedia("(max-width: 600px)").addEventListener("change", () => route());   // Settings: a sheet or a page
}

// ---------- Add spools ----------
function addTab() {
  let readId = null;
  const photos = []; // {blob, url}
  let items = [], checked = false, tag = null; // tag: unlinked tag tapped just before the photos (server links it)
  const thumbs = h("div", { class: "thumbs" });
  const hint = h("textarea", { placeholder: "Optional note for the label reader, e.g. \"3 of the grey ones\" or \"all the PETG is white\"" });
  const picker = h("input", { type: "file", accept: "image/*", multiple: true, on: { change: addFiles } });
  const readBtn = h("button", { textContent: "Read labels", on: { click: read } });
  const readBox = answer();       // the Label Reader's answer: the line, and what it found under it
  const readOut = h("div");
  const itemsBox = h("div");
  const actBox = h("div");
  const ans = answer();           // the answer to Check and Add: the line, and the Hub's own text under it
  let sending = false;
  // ---- by hand: pick an existing filament, or start a new one ----
  const fq = h("input", { type: "search", placeholder: "Existing filament: brand, colour, material", "aria-label": "Search existing filaments", enterKeyHint: "search",
                          on: { keydown: (e) => { if (e.key === "Enter") findFilaments(); } } });
  const filBox = h("div", { class: "list" });
  const filLine = resultLine();   // the search's own line: Searching…, or why it failed
  const vendorList = h("datalist", { id: "vendors" });
  let vendorTare = new Map(); // vendor name (lower case) -> empty spool weight
  const byHand = h("div", { class: "card" },
    h("h3", { textContent: "Add by hand" }),
    h("p", { class: "muted", textContent: "Pick a filament you already have, or start a new one; fill in the spool and check before saving." }),
    h("div", { class: "row" }, fq, h("button", { class: "fit", textContent: "Search", on: { click: (e) => findFilaments(e.currentTarget) } })),
    filLine, filBox,
    h("p", {}, h("button", { class: "secondary", textContent: "New filament (type it in)", on: { click: () => addItem(blankItem()) } })),
    vendorList);
  const photoPart = AI ? [
    h("h2", { textContent: "From label photos" }),
    h("p", { class: "muted", textContent: "Photograph each label (several photos of one spool are fine). The label reader (Claude or a local one) reads them; you check and edit before anything is saved." }),
    h("label", { class: "filebtn wide" }, h("button", { textContent: "Take or choose photos", tabIndex: -1 }), picker),
    thumbs, hint, h("p", {}, readBtn), readBox.el, readOut] : [];
  const el = h("section", {},
    byHand, ...photoPart, itemsBox, actBox);
  if (AI) readable();                                         // Read labels waits for a photo, and says so (04 3.4)
  api("vendors").then((res) => {
    vendorTare = new Map(res.vendors.map((v) => [v.name.toLowerCase(), v.tare]));
    vendorList.replaceChildren(...res.vendors.map((v) => h("option", { value: v.name })));
  }).catch(() => {}); // no list: the vendor is typed in

  function blankItem() {
    return { vendor: "", name: "", material: "", count: 1, net: 1000, tare: null, density: null, color_hex: "",
             sealed: true, location: SEALED, price_per_kg: "", photos: [], estimates: [], match: "new filament", hand: true };
  }
  function addItem(it) {
    items.push(it); drawItems(); dirty();
    itemsBox.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function findFilaments(button) {
    await act(filLine, SW.t("common_searching"), async () => {
      const res = await api(`filaments?q=${encodeURIComponent(fq.value)}`);
      if (!res.filaments.length) { filBox.replaceChildren(h("p", { class: "muted", textContent: "No filament matches: use New filament." })); return null; }
      filBox.replaceChildren(...[...res.filaments.slice(0, 60).map((f) => h("button", {
        class: "pick", on: { click: () => addItem({ ...blankItem(), vendor: f.vendor, name: f.name, material: f.material || "",
          net: f.net ?? 1000, tare: f.tare, density: f.density, color_hex: f.color_hex || "", nozzle: f.nozzle, bed: f.bed,
          existing_filament_id: f.id, match: "existing filament" }) } },
        h("strong", { textContent: `F${f.id} ` }), `${f.vendor || "(no vendor)"} ${f.name}`,
        h("div", { class: "muted", textContent: `${f.material || "?"} · ${f.net ?? "?"} g · ${f.spools} spool${f.spools === 1 ? "" : "s"}` }))),
        more(60, res.filaments.length)].filter(Boolean));
      return null;
    }, { button });
  }

  async function shrink(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = url; await img.decode();
      const s = Math.min(1, MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      return await new Promise((ok) => c.toBlob(ok, "image/jpeg", QUALITY));
    } finally { URL.revokeObjectURL(url); }
  }
  async function addFiles() {
    const files = [...picker.files]; picker.value = "";
    for (const f of files) {
      if (photos.length >= 8) { SW.result(readBox.line, "warn", SW.t("add_photo_limit", { count: 8 })); break; }
      try { const blob = await shrink(f); photos.push({ blob, url: URL.createObjectURL(blob) }); }
      catch (e) { SW.result(readBox.line, "warn", SW.t("add_photo_unreadable", { name: f.name })); }
    }
    drawThumbs();
  }
  function drawThumbs() {
    thumbs.replaceChildren(...photos.map((p, i) => h("figure", {}, h("img", { src: p.url, alt: `photo ${i + 1}` }),
      h("figcaption", { textContent: i + 1 }),
      h("button", { textContent: "✕", "aria-label": "remove photo", on: { click: () => { URL.revokeObjectURL(p.url); photos.splice(i, 1); drawThumbs(); } } }))));
    readable();
  }
  function readable() { disabled(readBtn, photos.length ? null : SW.t("add_reason_photo_first"), () => picker); }
  async function read() {
    const fd = new FormData();
    photos.forEach((p, i) => fd.append("photos", p.blob, `photo${i}.jpg`));
    fd.append("hint", hint.value);
    actBox.replaceChildren(); readOut.replaceChildren();
    await act(readBox, SW.t("add_reading", { count: photos.length }), async () => {
      const res = await api("read", { form: fd });
      tag = res.tag;
      readId = res.read_id || null;                      // the intake history keeps this read's photos with the save
      const got = res.items.map((it) => ({ price_per_kg: "", ...it, location: it.sealed ? SEALED : "" }));
      items = [...items.filter((it) => it.hand), ...got]; // a new read replaces the last read, not spools added by hand
      checked = false; drawItems();
      const filled = got.length === 1 && got[0].gross != null;
      readOut.replaceChildren(...[res.tag ? h("p", { class: "muted", textContent: `New tag ${res.tag.nfc_id} was tapped on the ${res.tag.reader} reader ${res.tag.age_seconds} s before the photos, so this spool counts as opened; Add links the tag to it (one opened spool only).` }) : null,
        res.scale ? h("p", { class: "muted", textContent: `Station scale: ${res.scale.grams} g, ${res.scale.age_seconds} s ago${filled ? " (filled in as the scale weight)" : " (not used: only for one opened spool)"}.` }) : null,
        res.questions.length ? h("div", { class: "card" }, h("h3", { textContent: res.reader === "local" ? "The local reader asks" : "Claude asks" }),
        ...res.questions.map((q) => h("p", { textContent: "• " + q }))) : null,
        res.note ? h("p", { class: "muted", textContent: "Note: " + res.note }) : null,
        h("p", { class: "muted", textContent: readerText(res) })].filter(Boolean));
      return got.length ? SW.t("add_found_result", { count: got.length, photos: photos.length }) : { kind: "warn", text: SW.t("add_found_none") };
    }, { button: readBtn, kept: true });
    readable();
  }
  function pct(c) { return Math.round(c * 100) + " %"; }
  function readerText(res) { // which reader answered, and how sure it was
    if (res.reader === "local") {
      return `read by the local reader (${res.tier || "?"} tier${res.escalated ? ", after the CPU tier" : ""})` +
        (res.confidence != null ? `, ${pct(res.confidence)} sure${res.unsure ? " (unsure: check the fields)" : ""}` : "") +
        (res.usage && res.usage.ms != null ? ` · ${(res.usage.ms / 1000).toFixed(1)} s` : "");
    }
    return `read by Claude · ${res.usage.model}, ${res.usage.input_tokens} in (${res.usage.cached} cached) / ${res.usage.output_tokens} out tokens`;
  }
  function colourText(it) { // the local reader's colour name and family, and its least sure fields
    const parts = [];
    if (it.color_name || it.color_family) {
      const name = it.color_name && it.color_name !== "unknown" ? it.color_name : "colour name not in the library";
      parts.push("colour: " + name + (it.color_family ? ` (${it.color_family})` : ""));
    }
    if (it.confidence != null) parts.push(pct(it.confidence) + " sure");
    const low = Object.entries(it.field_confidence || {}).filter(([, c]) => c < 0.78).map(([k]) => k);
    if (low.length) parts.push("least sure: " + low.join(", "));
    return parts.join(" · ");
  }
  function field(it, key, label, type = "text", extra = {}, ins = {}) {
    const inp = h("input", {
      type, value: it[key] ?? "", inputMode: type === "number" ? "decimal" : undefined, step: "any",
      list: key === "vendor" ? "vendors" : undefined,
      on: { input: (e) => { it[key] = type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value;
                            if (key === "color_hex") swatchFor(it);
                            if (key === "material") fillBlank(it, "density", densityFor(it.material), ins);
                            if (key === "vendor") fillBlank(it, "tare", vendorTare.get(it.vendor.trim().toLowerCase()), ins);
                            dirty(); } } });
    ins[key] = inp;
    return h("label", extra, label, inp);
  }
  function fillBlank(it, key, value, ins) { // a known default for a field the user left blank
    if (value == null || (it[key] != null && it[key] !== "")) return;
    it[key] = value; if (ins[key]) ins[key].value = value;
  }
  const swatches = new Map();
  function swatchFor(it) { const s = swatches.get(it); if (s) s.style.background = /^[0-9a-f]{6}$/i.test(it.color_hex || "") ? "#" + it.color_hex : "transparent"; }
  function drawItems() {
    swatches.clear();
    itemsBox.replaceChildren(...items.map((it, idx) => {
      const ins = {}; // this card's inputs by field, for filled-in defaults
      const f = (key, label, type, extra) => field(it, key, label, type, extra, ins);
      const sw = h("span", { class: "swatch" }); swatches.set(it, sw); swatchFor(it);
      const loc = h("select", { on: { change: (e) => { it.location = e.target.value; dirty(); } } },
        h("option", { value: "", textContent: "Auto: " + AUTO, selected: !it.location }),
        ...LOCATIONS.map((l) => h("option", { value: l, textContent: l, selected: l === it.location })));
      const sealed = h("input", { type: "checkbox", checked: it.sealed, on: { change: (e) => {
        it.sealed = e.target.checked;
        if (it.location === (it.sealed ? "" : SEALED)) { it.location = it.sealed ? SEALED : ""; loc.value = it.location; }
        dirty(); } } });
      return h("div", { class: "card" },
        h("h3", {}, sw, h("span", { textContent: `${it.vendor} ${it.name}`.trim() || "New spool" }),
          h("span", { class: "badge " + (it.existing_filament_id ? "ok" : "new"), textContent: it.match })),
        it.photos.length ? h("p", { class: "muted", textContent: `photos ${it.photos.map((n) => n + 1).join(", ")}${it.estimates.length ? " · estimated: " + it.estimates.join(", ") : ""}` }) : null,
        colourText(it) ? h("p", { class: "muted", textContent: colourText(it) }) : null,
        h("p", { class: "muted", textContent: it.price_line ? it.price_line.replace(/^Price: /, "") : "no price" }),
        h("div", { class: "grid" },
          f("vendor", "Vendor"), f("material", "Material"),
          f("name", "Name (with the colour)", "text", { class: "wide" }),
          f("count", "Spools", "number"), f("net", "Net g", "number"),
          f("tare", "Empty spool g", "number"), f("density", "Density", "number"),
          f("color_hex", "Colour hex"), f("lot", "Lot"),
          f("nozzle", "Nozzle °C", "number"), f("bed", "Bed °C", "number"),
          f("gross", "Opened: scale weight g (with spool, blank = full)", "number", { class: "wide" }),
          h("label", { class: "check wide" }, sealed, "Still sealed (in its bag or box)",
            it.sealed_reason ? h("span", { class: "muted", textContent: ` · ${it.sealed_reason}` }) : null),
          f("price_per_kg", "Price $/kg", "number"), h("label", {}, "Location", loc),
          f("note", "Note", "text", { class: "wide" })),
        h("p", {}, h("button", { class: "secondary", textContent: "Remove", on: { click: () => { items.splice(idx, 1); drawItems(); dirty(); } } })));
    }));
    drawActions();
  }
  function dirty() { if (checked) { checked = false; SW.result(ans.line, null); ans.code.replaceChildren(); drawActions(); } }   // an edit makes the last check stale
  const total = () => items.reduce((n, it) => n + (Number(it.count) || 0), 0);
  function drawActions() {
    if (!items.length) { actBox.replaceChildren(ans.el); return; }
    const check = h("button", { class: checked ? "secondary" : "", textContent: "Check (dry run)", on: { click: (e) => submit(true, e.currentTarget) } });
    const add = h("button", { textContent: `Add ${total()} spool${total() === 1 ? "" : "s"}`, on: { click: (e) => submit(false, e.currentTarget) } });
    actBox.replaceChildren(h("div", { class: "row" }, check, add), ans.el);
    disabled(add, checked ? null : SW.t("add_reason_check_first"), () => check);   // pressing it goes to Check
  }
  async function submit(dry, button) {
    if (sending) return;
    sending = true;
    try {
      await act(ans, dry ? SW.t("common_checking") : SW.t("add_preview_adding"), async () => {
        const n = total();
        const res = await api("add", { body: { items, dry_run: dry, link_tag: tag ? tag.nfc_id : null, read_id: readId } });
        checked = dry && !res.exit_code;
        if (res.exit_code) { drawActions(); return { kind: "bad", text: SW.t(dry ? "add_summary_error_preview" : "add_summary_error_change"), code: res.output }; }
        if (dry) { drawActions(); return { text: SW.t("add_summary_preview_ok"), code: res.output }; }
        const ids = res.spool_ids || [];
        items = []; tag = null; readId = null; itemsBox.replaceChildren(); filBox.replaceChildren(); photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url)); drawThumbs();
        drawActions();
        SW.toast(SW.t("add_added_toast", { count: ids.length || n }));
        return { text: ids.length ? SW.t("add_summary_added", { count: ids.length, ids: ids.join(", ") }) : SW.t("add_done_none"), code: res.output,
          action: { label: SW.t("add_added_set_up_presets"), run: () => { location.hash = "#presets"; } } };
      }, { button, busy: dry ? null : SW.t("common_adding") });
    } finally { sending = false; }
  }
  return { el };
}

// ---------- Open spool ----------
function openTab() {
  let timer = null, picked = null, lastKey = null, tagAt = null;   // tagAt: when the tag reader last answered
  const tagFirst = resultLine();    // the tag card's first line, until the first answer: reading, or why not
  const tagBox = h("div", { class: "card" }, tagFirst);
  const tagLine = resultLine();     // under the card: a poll that fails keeps the card and says how old it is (04 3.5)
  SW.result(tagFirst, "run", SW.t("spools_last_tag_loading"));
  const q = h("input", { type: "search", placeholder: "Search: brand, colour, material", "aria-label": "Search spools", enterKeyHint: "search",
                         on: { keydown: (e) => { if (e.key === "Enter") find(); } } });
  const sealed = h("input", { type: "checkbox", checked: true });
  const results = h("div", { class: "list" });
  const findLine = resultLine();    // the search's own line: Searching…, or why it failed
  const gross = h("input", { type: "number", inputMode: "decimal", step: "any", placeholder: "scale reading, g (optional)" });
  const loc = h("input", { placeholder: "blank = " + AUTO, list: "locs" });
  const hum = h("input", { type: "number", inputMode: "decimal", step: "any", placeholder: "box hygrometer % (optional)" });
  const ans = answer();             // the answer to Check and Link: the line, and the Hub's own text under it
  const checkBtn = h("button", { class: "secondary", textContent: "Check", on: { click: (e) => submit(true, e.currentTarget) } });
  const linkBtn = h("button", { textContent: "Link tag and open", on: { click: (e) => submit(false, e.currentTarget) } });
  const form = h("div", { class: "card hidden" }, h("h3", { textContent: "Selected spool" }), h("p", { class: "picked" }),
    h("div", { class: "grid" }, h("label", { class: "wide" }, "Gross weight (with spool)", gross),
      h("label", { class: "wide" }, "Location", loc), h("label", { class: "wide" }, "Humidity", hum)),
    h("div", { class: "row spaced" }, checkBtn, linkBtn),
    ans.el);
  // Link waits for a Check of what is on the form; an edit makes the last Check stale (04 3.4)
  const blockLink = (on) => disabled(linkBtn, on ? SW.t("add_reason_check_first_link") : null, () => checkBtn);
  blockLink(true);
  for (const inp of [gross, loc, hum]) inp.addEventListener("input", () => blockLink(true));
  const el = h("section", { class: "hidden" },
    h("p", { class: "muted", textContent: "Tap the spool's tag on a reader, pick the spool, weigh it (the station scale fills it in), link." }),
    tagBox, tagLine, h("datalist", { id: "locs" }, ...[...new Set([...PICKS, ...LOCATIONS])].map((l) => h("option", { value: l }))),
    h("h2", { textContent: "Which spool?" }), h("div", { class: "row" }, q, h("button", { class: "fit", textContent: "Search", on: { click: (e) => find(e.currentTarget) } })),
    findLine,
    h("label", { class: "check" }, sealed, "sealed spools only"),
    results, form);

  async function poll() {
    try {
      const t = await api("tag");
      tagAt = Date.now();
      clear(tagLine);
      const key = `${t.nfc_id}|${t.read_at}`;
      if (key !== lastKey) {
        lastKey = key; blockLink(true);
        if (t.reader === "station" && t.scale) gross.value = t.scale.grams; // a new station tap: that spool is on the scale
        tagBox.replaceChildren(h("h3", { textContent: t.nfc_id ? "Last tag: " + t.nfc_id : "No tag read yet: tap one" }),
          h("pre", { textContent: t.text }));
      }
      tagBox.querySelector(".age")?.remove();
      if (t.age_seconds != null) tagBox.append(h("p", { class: "muted age", textContent: `tapped ${ago(t.age_seconds)} on the ${t.reader} reader${t.scale ? ` · station scale ${t.scale.grams} g` : ""}` }));
    } catch (e) {
      if (tagAt != null) stale(tagLine, tagAt);                  // the card keeps the last tag
      else if (tagFirst._said !== says(e)) { tagFirst._said = says(e); failed(tagFirst, e, poll); }   // nothing to keep yet; said once, not at every poll
    }
  }
  async function find(button) {
    await act(findLine, SW.t("common_searching"), async () => {
      const res = await api(`find?q=${encodeURIComponent(q.value)}&sealed=${sealed.checked ? 1 : 0}`);
      const rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ f, s })));
      if (!rows.length) { results.replaceChildren(h("p", { class: "muted", textContent: "No spools match." })); return null; }
      results.replaceChildren(...[...rows.slice(0, 60).map(({ f, s }) => h("button", {
        class: "pick", on: { click: (e) => pick(e.currentTarget, f, s) } },
        h("strong", { textContent: `S${s.spool_id} ` }), `${f.vendor} ${f.name}`,
        h("div", { class: "muted", textContent: `${s.location || "?"} · ${s.remaining_g} g${s.sealed ? " · sealed" : ""}${s.tagged ? " · has a tag" : ""}${s.lot ? " · lot " + s.lot : ""}` }))),
        more(60, rows.length)].filter(Boolean));
      return null;
    }, { button });
  }
  function pick(btn, f, s) {
    for (const b of results.querySelectorAll(".pick")) b.classList.toggle("on", b === btn);
    picked = s.spool_id; blockLink(true); SW.result(ans.line, null); ans.code.replaceChildren();
    form.querySelector(".picked").textContent = `S${s.spool_id} ${f.vendor} ${f.name} (${s.location}, ${s.remaining_g} g)`;
    form.classList.remove("hidden"); form.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function submit(dry, button) {
    if (picked == null) return;
    const id = picked;
    await act(ans, dry ? SW.t("common_checking") : SW.t("common_working"), async () => {
      const res = await api("open", { body: { spool: id, gross: gross.value, location: loc.value, humidity: hum.value, dry_run: dry } });
      blockLink(!(dry && !res.exit_code));
      if (res.exit_code) return { kind: "bad", text: SW.t(dry ? "add_summary_error_preview" : "add_summary_error_change"), code: res.output };
      if (dry) return { text: SW.t("add_summary_preview_ok"), code: res.output };
      picked = null; gross.value = hum.value = loc.value = ""; lastKey = null;
      SW.toast(SW.t("spool_sheet_opened_toast", { id }));
      return { text: SW.t("spool_sheet_opened", { id }), code: res.output };
    }, { button });
  }
  return { el, enter() { poll(); timer = setInterval(() => { if (!document.hidden) poll(); }, 3000); },   // not while the page is hidden or the phone locked
    leave() { clearInterval(timer); timer = null; } };
}

// ---------- Presets (04 8) ----------
function presetsTab() {
  const box = h("div");
  const gen = answer();        // the answer to Build presets now: the line, and the Hub's own text under it
  const upBox = h("div");      // presets in the slicers that a newer build would change: shown, then accepted
  const upLine = resultLine(); // the answer to Restore and Accept; kept in the list, so it stays while the list is read again
  const buildBtn = SW.btn(SW.t("presets_build"), { cls: "btn--primary", action: "build", run: (e) => build(e.currentTarget) });
  upBox.className = "presets__updates";
  const el = h("section", { class: "hidden" }, h("p", { class: "muted", textContent: SW.t("presets_intro") }), box, upBox);

  const kvRow = (key, ...value) => h("div", { class: "kv__row" }, h("dt", { class: "kv__key", textContent: key }), h("dd", { class: "kv__value" }, ...value));
  const when = (stamp) => stamp ? h("span", { class: "mono", textContent: stamp }) : h("span", { class: "muted", textContent: SW.t("common_never") });
  const group = (title, ...body) => h("div", { class: "group" }, h("div", { class: "group__head" }, h("h2", { class: "group__title", textContent: title })),
    h("div", { class: "group__body" }, ...body));

  async function load(quiet) {
    await fill(box, SW.t("nav_slicer_presets"), async () => {
      const st = await api("presets");
      const status = group(SW.t("presets_build_title"),
        h("dl", { class: "kv" }, kvRow(SW.t("presets_field_last_build"), when(st.last_build)), kvRow(SW.t("updates_installed"), when(st.installed_build)),
          kvRow(SW.t("presets_lines_label"), SW.t("presets_built_lines", { count: st.lines }))),
        st.waiting_for_desktop ? note("warn", SW.t("presets_waiting")) : null,
        ...(st.problems || []).map((p) => note("bad", String(p))),
        st.note ? h("p", { class: "muted", textContent: st.note }) : null,
        buildBtn, gen.el);
      if (!st.uncovered_filaments.length) return [status, note("ok", SW.t("presets_all_done"))];
      return [status, h("h2", {}, SW.t("presets_without_line"), " ", h("span", { class: "muted mono", textContent: String(st.uncovered_filaments.length) })),
        h("div", { class: "cards" }, ...st.uncovered_filaments.map(lineCard))];
    }, { quiet });
  }
  function lineCard(f) {
    const addRes = resultLine(), newRes = resultLine();
    const lines = f.lines_for_vendor, material = f.material || "";
    const head = h("div", { class: "group__head" }, h("div", {}, h("h3", { class: "group__title", textContent: SW.t("presets_filament_name", { brand: f.vendor, name: f.name }) }),
      h("p", { class: "group__desc", textContent: SW.t(material ? "presets_card_sub" : "presets_card_sub_no_material", { material, id: f.id }) })));
    const body = h("div", { class: "group__body" });
    let add = null;
    if (lines.length) {
      const sel = SW.field({ type: "select", label: SW.t("presets_add_select"), options: lines.map((l) => ({ value: l, label: l })) });
      add = SW.btn(SW.t("presets_add_button"), { cls: "btn--primary", action: "add-to-line", run: (e) =>
        act(addRes, SW.t("common_adding"), async () => {
          await api("line_add", { body: { line: sel._control.value, ids: [f.id] } });
          SW.toast(SW.t("presets_added", { line: sel._control.value })); load(true);      // the card goes: the list is read again
          return null;
        }, { button: e.currentTarget }) });
      body.append(sel, h("div", {}, add), addRes);
    }
    const nm = SW.field({ label: SW.t("presets_line_name"), hint: SW.t("presets_line_name_help"),
      value: [f.vendor, f.name.split(" ").slice(0, -1).join(" ") || f.name].join(" ") });
    const orca = SW.field({ type: "select", label: SW.t("presets_col_orca_parent"), options: [] });
    const bs = SW.field({ type: "select", label: SW.t("presets_bs_template"), options: [] });
    const fillSel = (field, list, want) => field._control.replaceChildren(...list.map((n) => h("option", { value: n, textContent: n, selected: n === want })));
    async function parents(text) {
      try {
        const p = await api(`parents?q=${encodeURIComponent(text)}`);
        const want = SW.t("presets_orca_default", { material });
        fillSel(orca, p.orca_parents, want); fillSel(bs, p.bs_templates, want);
        if (p.note && (!p.orca_parents.length || !p.bs_templates.length)) {   // no parents to pick yet: the Hub says why, and Create waits
          put(newRes, "warn", p.note); disabled(create, p.note, () => q._control);
        } else { clear(newRes); disabled(create, null); }
      } catch (e) { failed(newRes, e, () => parents(text)); }
    }
    const q = SW.field({ type: "search", label: SW.t("presets_parent"), hint: SW.t("presets_parent_help"), value: material, onSearch: parents });
    const create = SW.btn(SW.t("presets_create"), { cls: add ? "" : "btn--primary", action: "create-line", run: (e) => {
      if (!nm._control.value.trim()) { SW.fieldError(nm, SW.t("presets_line_name_needed")); nm._control.focus(); return; }
      SW.fieldError(nm, null);
      return act(newRes, SW.t("presets_creating"), async () => {
        const name = nm._control.value.trim();
        await api("line_new", { body: { name, vendor: f.vendor, ids: [f.id], orca_parent: orca._control.value, bs_template: bs._control.value } });
        SW.toast(SW.t("presets_created", { name })); load(true);
        return null;
      }, { button: e.currentTarget });
    } });
    const details = h("details", { class: "disclosure" }, h("summary", {}, h("span", { textContent: SW.t(lines.length ? "presets_new_line_with_lines" : "presets_new_line_none") }),
      SW.icon("chevron", "icon--s disclosure__chevron")),
      h("div", { class: "disclosure__body" }, nm, q, orca, bs, h("div", {}, create), newRes));
    details.addEventListener("toggle", () => {       // while the disclosure is open, Create line is the card's only filled button
      if (add) add.classList.toggle("btn--primary", !details.open);
      create.classList.toggle("btn--primary", details.open || !add);
      if (details.open && !orca._control.options.length) parents(q._control.value);
    });
    body.append(details);
    return h("div", { class: "group" }, head, body);
  }
  async function build(button) {
    await act(gen, SW.t("presets_building"), async () => {
      const r = await api("generate", { body: {} });
      load(true);
      return r.exit_code ? { kind: "bad", text: SW.t("add_summary_error_change"), code: r.output } : { text: SW.t("presets_result_build_requested"), code: r.output };
    }, { button });
  }
  // Updates: the list names each preset and what changes; Accept takes exactly that list (the server refuses it once a
  // newer build has come, and the list is loaded again). Slicer Sync writes accepted presets at its next run.
  async function updates(quiet) {
    await fill(upBox, SW.t("presets_updates_title"), async () => {
      const u = await api("updates");
      const waiting = (u.updates || []).filter((x) => !x.accepted);
      const summary = u.count ? SW.t("presets_updates_summary", { count: u.count, lines: u.lines,
        accepted: u.accepted ? SW.t("presets_updates_accepted", { count: u.accepted }) : "" }) : SW.t("presets_updates_none");
      const restore = SW.btn(SW.t("presets_restore_deleted"), { cls: "btn--ghost", action: "restore", run: (e) =>
        act(upLine, SW.t("common_working"), async () => {
          await api("restore_deleted", { body: {} }); setTimeout(() => updates(true), 3000);
          return SW.t("presets_restore_asked");
        }, { button: e.currentTarget }) });
      const shown = h("div"), shownLine = resultLine();     // the change list, with Accept under it, once asked for
      const accept = SW.btn(SW.t("presets_updates_accept"), { cls: "btn--primary", action: "accept-updates", run: (e) =>
        act(upLine, SW.t("common_working"), async () => {
          try {
            const r = await api("updates_accept", { body: { stamp: u.stamp, names: waiting.map((x) => x.name) } });
            setTimeout(() => updates(true), 3000);
            return SW.t("presets_updates_accepted_result", { count: r.accepted.length });
          } catch (err) {
            if (!(err instanceof SW.HubError) || err.status !== 409) { setTimeout(() => updates(true), 4000); throw err; }
            updates(true);                                    // a newer build came: the list is read again
            return { kind: "warn", text: SW.t("presets_updates_stale") };
          }
        }, { button: e.currentTarget }) });
      const keys = (x) => x.keys.slice(0, 6).join(", ") + (x.keys.length > 6 ? ", …" : "");
      const show = SW.btn(SW.t("presets_updates_show"), { action: "show-updates", run: () => {
        shown.replaceChildren(...(waiting.length ? [h("ul", {}, ...waiting.map((x) => h("li", { textContent: SW.t("presets_updates_line",
          { target: x.target, name: x.name, file: x.file || `${x.name}.json`, keys: keys(x) }) }))), h("div", {}, accept)] : []));
        SW.result(shownLine, "ok", SW.t(waiting.length ? "presets_updates_would" : "presets_updates_nothing", { count: waiting.length }));
      } });
      return group(SW.t("presets_updates_title"),
        h("p", { class: "muted", textContent: summary }),
        (u.yours || []).length ? h("p", { class: "muted", textContent: SW.t("presets_updates_yours", { count: u.yours.length }) }) : null,
        h("div", {}, show), shownLine, shown, h("div", {}, restore), upLine);
    }, { quiet });
  }
  return { el, enter: () => { load(); updates(); } };
}
