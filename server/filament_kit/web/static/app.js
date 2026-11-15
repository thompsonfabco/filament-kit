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
  } catch (e) { failed(line, e, o.again || (() => act(box, label, fn, o)), o); }   // o.again: Try again starts something larger than fn
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
  if (PLACES.includes(name)) { show(name); if (name === "spools") tabs.spools.address(raw.slice(head.length + 1), initial); return; }
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
// resolves once the Back a closed sheet asked for has landed: an address set before that would be taken back with it
function backSettled() {
  return new Promise((resolve) => {
    let waited = 0;
    const look = () => { if (settling > 0 && waited++ < 100) setTimeout(look, 20); else resolve(); };
    setTimeout(look, 0);                                     // the sheet's close event may not have run yet
  });
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
  shellView = SW.shell({ hub: HUB || PRODUCT, home: "add", titleOf: (s) => { const k = ALIAS[s] || s; return (s === "spools" && tabs.spools.sheetTitle()) || (tabs[k] && tabs[k].title && tabs[k].title()) || SW.t(TITLES[k] || TITLES[place]); }, onSection: () => route() });
  nav.append(moreBtn);                                       // after SW.shell: this More has its own sheet
  paintMore();
  matchMedia("(max-width: 600px)").addEventListener("change", () => route());   // Settings: a sheet or a page
}

// ---------- Add spools (04 4) ----------
// What is being added is `items`, one object per card, in the shape the Hub takes (keys that start with "_" are the page's own
// and never leave it). Each card is drawn once and an edit changes only what it touches, so a field in use is never redrawn.
// Nothing is written until the person previews and then adds; the unfinished add is kept on the phone as a draft (04 4.7).
function addTab() {
  // the constants and helpers are inside: this function runs while the page's script is still building the tabs, before the
  // top-level constants below it exist
  const ADD_MAX_PHOTOS = 8, ADD_PAGE = 50, ADD_FIND_LIMIT = 60;
  const ADD_DRAFT = "spoolwarden.draft.add", ADD_NEW = "spoolwarden.draft.add-new";   // the second slot holds work started while a draft waits
  // the fields a read rates that the card shows, in the order of the card; and the names of the fields in sentences
  const ADD_RATED = "vendor name material color_hex net tare density nozzle bed price_per_kg".split(" "), COL = ADD_RATED[3];
  const ADD_LABEL = { vendor: "common_field_brand", name: "common_field_name", material: "common_field_material", color_hex: "common_field_colour",
    count: "common_field_spools", density: "common_field_density", net: "common_field_net_weight", tare: "common_field_empty_spool_weight",
    gross: "common_field_weight_with_spool", nozzle: "common_field_nozzle", bed: "common_field_bed", price_per_kg: "common_field_price_per_kg",
    lot: "common_field_lot", line: "common_field_line", note: "common_field_note", location: "common_field_location" };
  const ADD_REQUIRED = ["vendor", "name", "material", "count", "net"];     // a label without "(optional)"
  const ADD_NUMBER = new Set(["count", "net", "tare", "density", "nozzle", "bed", "gross", "price_per_kg"]);
  const ADD_HEX = /^#?([0-9a-f]{6}|[0-9a-f]{8})$/i;                  // 6 digits, or 8 with the alpha pair last, as the Hub takes them
  const addHexFull = (s) => { const m = ADD_HEX.exec(String(s || "")); return m ? "#" + m[1].toUpperCase() : ""; };   // as typed and sent
  const addHex = (s) => { const m = ADD_HEX.exec(String(s || "")); return m ? "#" + m[1].slice(0, 6).toUpperCase() : ""; };   // for a swatch
  const ADD_GRAMS = new Set(["net", "tare", "gross"]), ADD_WHOLE = new Set(["count", "nozzle", "bed"]);
  // "1,000" g is a thousand (a group of three after 1 to 3 digits, the first not 0), "0,500" is a half; in a decimal field (density, price)
  // the comma is the decimal point; a whole-number field takes no comma
  const addParse = (text, key) => {
    let t = String(text).trim();
    if (ADD_WHOLE.has(key) && t.includes(",")) return NaN;
    t = ADD_GRAMS.has(key) && /^[1-9]\d{0,2}(,\d{3})+(\.\d+)?$/.test(t) ? t.replace(/,/g, "") : t.replace(",", ".");
    const n = Number(t);
    return t !== "" && Number.isFinite(n) ? n : NaN;
  };
  const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);

  // the record summary of 02 7.2, for the levels of one or more items: the level, then the fields at each level
  function addSummary(levelsList) {
    const out = { low: [], medium: [], not_on_label: [] };
    let unrated = false, any = false;
    for (const lv of levelsList) {
      for (const k of ADD_RATED) {
        const v = lv[k];
        if (!(k in lv)) continue;
        any = true;
        if (v == null) unrated = true;
        else if (v in out && !out[v].includes(k)) out[v].push(k);
      }
    }
    if (!any) return null;
    const level = out.low.length ? "low" : unrated ? "not_rated" : out.medium.length ? "medium" : out.not_on_label.length ? "not_on_label" : "high";
    return { level, ...out };
  }
  // the line of a summary: "High", or the levels' marks and fields in the order low, medium, not on the label, joined by " · "
  function addSummaryLine(sum) {
    if (!sum) return null;
    const names = (keys) => keys.map((k) => SW.t(ADD_LABEL[k])).join(", ");
    const parts = [];
    if (sum.level === "high") parts.push(SW.status("high", { small: true }));
    if (sum.low.length) parts.push(SW.status("low", { small: true, text: SW.t("confidence_summary_low", { fields: names(sum.low) }) }));
    if (sum.level === "not_rated") parts.push(h("span", { class: "muted", textContent: SW.t("add_found_not_rated") }));
    if (sum.medium.length) parts.push(SW.status("medium", { small: true, text: SW.t("confidence_summary_medium", { fields: names(sum.medium) }) }));
    if (sum.not_on_label.length) parts.push(SW.status("not_on_label", { small: true, text: SW.t("confidence_summary_not_on_label", { fields: names(sum.not_on_label) }) }));
    const line = h("p", { class: "add__summary" });
    parts.forEach((p, i) => line.append(...(i ? [" · ", p] : [p])));
    return parts.length ? line : null;
  }

  const tabId = (() => {                                        // which tab wrote the draft (04 4.7)
    try { let v = sessionStorage.getItem("spoolwarden.tab"); if (!v) sessionStorage.setItem("spoolwarden.tab", v = Math.random().toString(36).slice(2)); return v; }
    catch { return Math.random().toString(36).slice(2); }
  })();
  let items = [], photos = [], readId = null, tag = null, found = null;      // photos: { blob, url }
  let previewed = false, edited = null, problemsShown = false, working = null, hubDown = false, hubTimer = 0;   // working: read, preview, add
  let rev = 0, started = 0, changedAt = 0, pending = null, keeping = true, wrote = false, saveTimer = 0, nextId = 1, memo = null;
  const cards = new Map();                                      // item _id -> its card
  let vendorTare = new Map();                                   // vendor name (lower case) -> empty spool weight
  let rows = [], more = false, page = 1, findStamp = 0;                       // the filament search results, and the page shown

  // ---- the page: title area, groups, list, action bar ----
  const lines = h("div", { class: "add__notes" });              // this add is open in another tab; no draft can be kept
  const draftBox = h("div", { class: "add__draft" });
  const addedBox = h("div", { class: "add__added" });           // the result of an Add stays at the top until a new add starts
  const photoGroup = h("section", { class: "group add__group" });
  const handGroup = h("section", { class: "group add__group" });
  const foundBox = h("div");
  const listHead = h("h2", { class: "group__title", tabindex: "-1", id: SW.uid("list") });
  const count = h("span", { class: "mono add__count" });
  const empty = SW.empty({ icon: "spool", title: SW.t("add_empty"), level: 3 });
  const listBox = h("div", { class: "add__cards" });
  const previewBox = h("div");
  const vendorList = h("datalist", { id: "addVendors" });
  const ans = answer();                                         // the answer to Preview and Add: the line, and the Hub's own text under it
  const itemsBox = h("div", { class: "add__results" });         // what the preview says each spool does (04 4.6)
  const extras = h("div", { class: "add__extras" });            // the buttons after an Add
  ans.el.insertBefore(itemsBox, ans.code);
  ans.el.append(extras);

  // the line that starts with its shape and is not cleared when the person leaves the page (04 3.3); `result` lines are
  const line = (kind, text) => h("p", { class: "add__line", "data-state": kind },
    SW.shape({ ok: "s-filled", bad: "s-octagon", warn: "s-triangle", info: "s-diamond", neutral: "s-hollow" }[kind]), h("span", {}, text));
  const group = (title, ...kids) => { const id = SW.uid("g"); return h("section", { class: "group add__group", "aria-labelledby": id }, h("header", { class: "group__head" },
    h("h2", { class: "group__title", id }, title)), h("div", { class: "group__body" }, ...kids)); };
  const heldOf = (list) => spoolsOf(list) || list.length;      // what a waiting draft holds: its spools, or its cards when none has a count
  const spoolsOf = (list = items) => list.reduce((n, it) => n + (Number.isInteger(Number(it.count)) && Number(it.count) > 0 ? Number(it.count) : 0), 0);

  // ---- the Hub, and what it does to the action bar when it does not answer ----
  async function call(path, opts) {
    try { const r = await api(path, opts); if (hubDown) { hubDown = false; paintBar(); } return r; }
    catch (e) {
      if (e instanceof SW.HubError && e.unreachable) { hubDown = true; clearTimeout(hubTimer); hubTimer = setTimeout(() => { hubDown = false; paintBar(); }, 15000); paintBar(); }
      throw e;
    }
  }
  window.addEventListener("online", () => { if (hubDown) { hubDown = false; paintBar(); } });

  // ============ the card's values: what is missing and what is wrong ============
  const textOf = (it, k) => String(k in it._text ? it._text[k] : it[k] ?? "").trim();
  function missing(it) { return ADD_REQUIRED.filter((k) => textOf(it, k) === ""); }
  // the sentence for a value that is not right (null when it is fine or empty and optional)
  function wrong(it, k) {
    const t = textOf(it, k), n = ADD_NUMBER.has(k) ? addParse(t, k) : 0;
    if (k === COL) return t === "" || ADD_HEX.test(t) ? null : SW.t("add_card_colour_error");
    if (!ADD_NUMBER.has(k) || t === "") return null;
    if (k === "count") return Number.isInteger(n) && n >= 1 ? null : SW.t("add_card_spools_error");
    if (k === "density") return n > 0 ? null : SW.t("add_review_error_density");
    if (k === "nozzle" || k === "bed") return Number.isInteger(n) && n > 0 ? null : SW.t("add_review_error_degrees");
    if (k === "price_per_kg") return n > 0 ? null : SW.t("add_card_price_error");
    if (ADD_GRAMS.has(k) && /^\d+\.\d{3}$|^\d+[.,]0{4,}$/.test(t)) return SW.t("add_card_grams_plain");
    return n > 0 ? null : SW.t(k === "gross" ? "field_error_grams" : "common_error_grams");
  }
  const sentence = (it, k) => it._problems[k] || wrong(it, k);
  const invalid = (it) => [...ADD_REQUIRED, "density", "tare", "gross", "nozzle", "bed", "price_per_kg", COL].filter((k) => (k === "gross" && (it.sealed || Number(it.count) > 1) ? false : wrong(it, k)));
  // the first spool that cannot be previewed yet, and why
  function firstBlock() {
    const needs = items.filter((it) => missing(it).length);
    if (needs.length) return { kind: "missing", it: needs[0], keys: missing(needs[0]), many: needs.length };
    for (const it of items) { const bad = invalid(it); if (bad.length) return { kind: "wrong", it, keys: bad }; }
    return null;
  }
  const wire = (it) => {                                        // what the Hub gets: the item without the page's own keys
    const w = Object.fromEntries(Object.entries(it).filter(([k]) => k[0] !== "_"));
    if (Number(w.count) > 1 || w.sealed !== false) delete w.gross;   // a weight with the spool counts for one opened spool only (04 4.5)
    return w;
  };
  // what the local reader said about the colour, as a read fact (02 7.2); it goes when the colour is edited
  const colourFact = (it) => {
    if (!it.color_name && !it.color_family) return "";
    const name = it.color_name && it.color_name !== "unknown" ? it.color_name : "";
    return !name ? SW.t("add_read_colour_none") : it.color_family ? SW.t("add_read_colour_family", { name, family: it.color_family }) : SW.t("add_read_colour_name", { name });
  };
  const adopt = (it, read) => {
    const levels = it.confidence_levels || {};
    delete it.confidence_levels; delete it.confidence_filled;
    return Object.assign(it, { _id: it._id || nextId++, _levels: { ...levels }, _est: [...(it.estimates || [])], _fill: {}, _text: {}, _problems: {},
      _open: undefined, _read: !!read, _edited: false, _fact: colourFact(it) });
  };

  // ============ the draft (04 4.7) ============
  const store = {
    get(key = ADD_DRAFT) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : null; } catch { return null; } },
    put(text, key = ADD_DRAFT) { try { localStorage.setItem(key, text); return true; } catch { return false; } },
    drop(key = ADD_DRAFT) { try { localStorage.removeItem(key); } catch { /* nothing to drop */ } },
    works() { try { localStorage.setItem(ADD_DRAFT + ".probe", "1"); localStorage.removeItem(ADD_DRAFT + ".probe"); return true; } catch { return false; } },
  };
  // a stored draft is only used when it has the shape this page writes; whatever else is in it is left out (04 4.7)
  // one stored item: the text fields are text (null is empty), a number field is a number or stays as typed in `_text`
  function tidy(it) {
    const out = { ...it }, typed = isObj(it._text) ? { ...it._text } : {};
    for (const k of ["vendor", "name", "material"]) out[k] = typeof it[k] === "string" ? it[k] : it[k] == null || typeof it[k] === "object" || typeof it[k] === "boolean" ? "" : String(it[k]);
    for (const k of ADD_NUMBER) {
      const v = out[k];
      if (v == null || v === "" || (typeof v === "number" && Number.isFinite(v))) continue;
      if (typeof v === "string") {
        if (!(k in typed)) typed[k] = v;
        const n = addParse(v, k);
        out[k] = Number.isFinite(n) ? n : null;                 // an unparsable text stays as typed and is checked at Preview
      } else out[k] = null;
    }
    out._text = typed;
    return out;
  }
  function clean(d) {
    if (!isObj(d) || d.v !== 1 || !Array.isArray(d.items)) return null;
    const its = d.items.filter(isObj).map(tidy), note = typeof d.note === "string" ? d.note : "";
    if (!its.length && !note.trim()) return null;
    const f = isObj(d.found) ? d.found : null, list = (v) => (Array.isArray(v) ? v : []), sum = f && isObj(f.summary) ? f.summary : null;
    return { ...d, items: its, note, readId: typeof d.readId === "string" ? d.readId : null, tag: isObj(d.tag) ? d.tag : null,
      found: f && { ...f, count: Number(f.count) || 0, photos: Number(f.photos) || 0, reader: String(f.reader || ""), model: String(f.model || ""), tier: String(f.tier || ""),
        note: typeof f.note === "string" ? f.note : "", questions: list(f.questions).filter((q) => typeof q === "string"), tag: isObj(f.tag) ? f.tag : null,
        scale: isObj(f.scale) ? f.scale : null, usage: isObj(f.usage) ? f.usage : null,
        summary: sum && ["low", "medium", "not_on_label"].every((k) => Array.isArray(sum[k])) ? sum : null } };
  }
  function noStorage(on) {
    lines.querySelector(".add__nostore")?.remove();
    if (on) lines.append(Object.assign(line("warn", SW.t("add_draft_no_storage")), { className: "add__line add__nostore" }));
  }
  function save() {
    clearTimeout(saveTimer);
    if (!keeping) return;
    const slot = pending ? ADD_NEW : ADD_DRAFT;                  // a draft that waits for Restore or Discard is never written over
    if (!items.length && !noteField._control.value.trim()) { if (wrote) store.drop(slot); paintBadge(); return; }   // a tab that never wrote leaves another one's draft alone
    started = started || Date.now(); changedAt = Date.now();
    const ok = store.put(JSON.stringify({ v: 1, tab: tabId, started, changed: changedAt, items, note: noteField._control.value, readId, tag, found }), slot);
    if (ok && !pending) store.drop(ADD_NEW);
    wrote = wrote || ok;
    noStorage(!ok);
    paintBadge();
  }
  const saveSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(save, 400); };
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") save(); });
  window.addEventListener("pagehide", save);
  window.addEventListener("storage", (e) => {                   // another tab keeps the draft now
    if ((e.key !== ADD_DRAFT && e.key !== ADD_NEW) || e.storageArea !== localStorage || !keeping) return;
    keeping = false;
    lines.append(Object.assign(line("warn", SW.t("add_draft_other_tab")), { className: "add__line add__other" }));
  });
  const clearDraft = () => { started = 0; if (keeping) store.drop(pending ? ADD_NEW : ADD_DRAFT); paintBadge(); };
  function ageText(ms) {
    const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 3600) return SW.t("common_age_minutes", { count: Math.max(1, Math.round(s / 60)) });
    if (s < 86400) return SW.t("common_age_hours", { count: Math.round(s / 3600) });
    return s < 172800 ? SW.t("home_draft_yesterday") : new Date(ms).toLocaleDateString();
  }
  function drawDraft() {
    draftBox.replaceChildren();
    if (!pending) return;
    const n = heldOf(pending.items || []);
    draftBox.append(SW.banner({ kind: "info", inline: true, text: SW.t("add_draft_banner", { age: ageText(pending.changed || pending.started || Date.now()), count: n }),
      actions: [SW.btn(SW.t("common_restore_them"), { cls: "btn--primary", run: restore }), SW.btn(SW.t("common_discard"), { run: discard })] }));
  }
  function restore() {
    if (working === "add" || !pending) return;
    const d = pending; pending = null; draftBox.replaceChildren();
    const mine = items;
    items = [];
    for (const raw of d.items || []) {
      const it = Object.assign(raw, { _id: nextId++, _problems: {}, _levels: isObj(raw._levels) ? raw._levels : {}, _fill: isObj(raw._fill) ? raw._fill : {}, _text: isObj(raw._text) ? raw._text : {},
        _est: Array.isArray(raw._est) ? raw._est : Array.isArray(raw.estimates) ? raw.estimates : [] });
      items.push(it);
    }
    items.push(...mine);
    listBox.replaceChildren(...items.map((it) => (cards.get(it._id) || addCard(it)).el));
    if (d.note && !noteField._control.value.includes(d.note)) noteField._control.value = [d.note, noteField._control.value].filter(Boolean).join("\n");
    if (!found && !readId && !tag) { found = d.found || null; readId = d.readId || null; tag = d.tag || null; }
    started = d.started || Date.now();
    if (d.readId || d.found) draftBox.append(line("info", SW.t("add_draft_photos_not_kept")));
    drawFound(); drawList(); changed(); save();
    SW.announce(SW.t("add_draft_banner", { age: ageText(d.changed || started), count: heldOf(d.items || []) }));
  }
  async function discard(e) {
    if (working === "add" || !pending) return;
    const ok = await SW.ask({ kind: "destructive", title: SW.t("home_draft_discard_title"), text: SW.t("add_draft_discard_body", { count: heldOf(pending.items || []) }),
      confirm: SW.t("common_discard"), cancel: SW.t("common_keep"), open: openHere, opener: e && e.currentTarget });
    if (!ok) return;
    pending = null; store.drop(); draftBox.replaceChildren(); paintBadge();
    SW.toast(SW.t("add_draft_discarded"));
    if (items.length || noteField._control.value) save();
  }
  // the badge on the Add destination while an add is unfinished (04 2.1)
  function paintBadge() {
    const a = document.querySelector('.nav__item[href="#add"]');
    if (!a) return;
    const n = spoolsOf() + (pending ? heldOf(pending.items || []) : 0);
    a.querySelector(".nav__badge")?.remove();
    if (n > 0) { a.append(h("span", { class: "nav__badge", "aria-hidden": "true", textContent: String(n) })); a.setAttribute("aria-label", SW.t("nav_add_waiting", { count: n })); }
    else a.removeAttribute("aria-label");
  }

  // ============ an edit, an added or removed card, a new read: the preview is out of date ============
  function changed(it) {
    rev++;
    if (previewed) { if (working !== "add") { previewBox.replaceChildren(); memo = null; } edited = it ? it._id : null; }   // only an Add under way keeps its result
    else if (working && it) edited = it._id;
    previewed = false; problemsShown = false;
    changedAt = Date.now();
    paintBar(); saveSoon(); paintBadge();
  }

  // ============ From label photos (04 4.3) ============
  const takeIn = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true, "aria-labelledby": "add-take-label", on: { change: () => addFiles(takeIn) } });
  const pickIn = h("input", { type: "file", accept: "image/*", multiple: true, hidden: true, "aria-labelledby": "add-pick-label", on: { change: () => addFiles(pickIn) } });
  const takeBtn = SW.btn(SW.t("add_photos_take"), { icon: "camera", run: () => takeIn.click() });
  takeBtn.id = "add-take-label";
  const pickBtn = SW.btn(SW.t("add_choose_photos"), { run: () => pickIn.click() });
  pickBtn.id = "add-pick-label";
  const photoCount = h("span", { class: "add__photo-count mono" });
  const strip = h("div", { class: "add__strip" });
  const photoLimit = h("p", { class: "add__limit muted", id: SW.uid("limit"), hidden: true });
  const photoNote = h("p", { class: "add__line", "data-state": "warn", hidden: true });
  const noteField = SW.field({ type: "textarea", label: SW.t("add_note_label"), optional: true, placeholder: SW.t("add_note_placeholder"), max: 2000 });
  noteField._control.addEventListener("input", saveSoon);
  const readBtn = SW.btn(SW.t("add_read_labels"), { run: read });
  const readBox = answer();                                     // the Label Reader's answer under its button
  const photoBody = AI ? [h("div", { class: "add__buttons" }, takeBtn, pickBtn, takeIn, pickIn), photoLimit, h("div", { class: "add__photos" }, strip, photoCount), photoNote,
    noteField, h("div", { class: "add__read" }, readBtn, readBox.el)] : null;
  if (AI) photoGroup.replaceChildren(h("header", { class: "group__head" }, h("h2", { class: "group__title", textContent: SW.t("add_group_photos") })),
    h("div", { class: "group__body" }, ...photoBody));
  else photoGroup.replaceChildren(h("div", { class: "group__body" }, SW.banner({ kind: "info", inline: true, text: SW.t("home_label_reader_off") })));

  // a photo is shrunk on the phone before it is sent: at most MAX_EDGE px on the long side, as JPEG
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
  async function addFiles(input) {
    const files = [...input.files]; input.value = "";
    photoNote.hidden = true;
    for (const f of files) {
      if (photos.length >= ADD_MAX_PHOTOS) break;
      try { const blob = await shrink(f); photos.push({ blob, url: URL.createObjectURL(blob) }); }
      catch { photoNote.replaceChildren(SW.shape("s-triangle"), h("span", {}, SW.t("add_photo_unreadable", { name: f.name }))); photoNote.hidden = false; }
    }
    drawPhotos();
    saveSoon();
  }
  function drawPhotos(focusIndex) {
    const full = photos.length >= ADD_MAX_PHOTOS;
    strip.replaceChildren(...photos.map((p, i) => {
      const args = { number: i + 1, count: photos.length };
      const thumb = h("button", { class: "add__thumb", type: "button", "aria-label": SW.t("add_photo_enlarge", args), on: { click: (e) => openPhoto(i, e.currentTarget) } },
        h("img", { src: p.url, alt: "" }), h("span", { class: "add__thumb-n mono", "aria-hidden": "true", textContent: String(i + 1) }));
      const off = SW.iconBtn("close", SW.t("add_photo_remove", args), { run: () => removePhoto(i) });
      return h("div", { class: "add__photo" }, thumb, off);
    }));
    photoCount.textContent = photos.length ? SW.t("add_photo_count", { count: photos.length, max: ADD_MAX_PHOTOS }) : "";
    for (const b of [takeBtn, pickBtn]) {                       // a full set: both buttons say why (04 3.4)
      if (full) { b.setAttribute("aria-disabled", "true"); b.setAttribute("aria-describedby", photoLimit.id); }
      else { b.removeAttribute("aria-disabled"); b.removeAttribute("aria-describedby"); }
    }
    photoLimit.hidden = !full; photoLimit.textContent = full ? SW.t("add_photo_limit", { count: ADD_MAX_PHOTOS }) : "";
    takeBtn.classList.toggle("btn--primary", !photos.length);   // the filled button is the next step: a photo, then Read labels
    readBtn.classList.toggle("btn--primary", photos.length > 0);
    readable();
    if (focusIndex != null) {
      const spot = strip.querySelectorAll(".add__photo .btn")[Math.min(focusIndex, photos.length - 1)];
      (spot || takeBtn).focus();
    }
  }
  function removePhoto(i) {
    const [p] = photos.splice(i, 1);
    const drop = setTimeout(() => URL.revokeObjectURL(p.url), 11000);       // the Undo toast lasts 10 s
    drawPhotos(i);
    SW.toast(SW.t("add_photos_removed"), "ok", { action: { label: SW.t("common_undo"), run: () => {
      clearTimeout(drop); if (photos.length < ADD_MAX_PHOTOS) { photos.splice(i, 0, p); drawPhotos(i); } else URL.revokeObjectURL(p.url);
    } } });
  }
  function openPhoto(i, opener) {                               // the photo large, with Remove and Close (04 4.3)
    const p = photos[i];
    const dlg = SW.sheet({ title: SW.t("photo_position", { number: i + 1, total: photos.length }),
      body: h("img", { class: "add__big", src: p.url, alt: "" }),
      foot: [SW.btn(SW.t("add_photo_remove_this"), { cls: "btn--danger", run: () => { dlg.close(); removePhoto(i); } }),
        SW.btn(SW.t("common_close"), { run: () => dlg.close() })] });
    openHere(dlg, opener);
  }
  function readable() { disabled(readBtn, photos.length ? null : SW.t("add_reason_photo_first"), () => takeBtn); }

  async function read() {
    if (working) return;
    const old = items.filter((it) => it._read);
    if (old.some((it) => it._edited)) {
      const ok = await SW.ask({ kind: "confirm", title: SW.t("add_replace_title"), text: SW.t("add_replace_body", { count: old.filter((it) => it._edited).length }),
        confirm: SW.t("add_replace_confirm"), cancel: SW.t("add_replace_keep"), open: openHere, opener: readBtn });
      if (!ok) return;
    }
    const fd = new FormData();
    photos.forEach((p, i) => fd.append("photos", p.blob, `photo${i}.jpg`));
    fd.append("hint", noteField._control.value);
    working = "read"; paintBar();
    await act(readBox, SW.t("add_reading", { count: photos.length }), async () => {
      let res;
      try { res = await call("read", { form: fd }); }
      catch (e) { if (e instanceof SW.HubError && e.status === 429) e.message = `${e.text("")} ${SW.t("add_daily_limit")}`; throw e; }
      for (const it of old) dropCard(it);
      items = items.filter((it) => !it._read);                  // a new read replaces the last read, not the spools added by hand
      tag = res.tag || null; readId = res.read_id || null;
      const got = res.items.map((raw) => adopt({ price_per_kg: "", ...raw, location: raw.sealed ? SEALED : "" }, true));
      const eng = res.engine || {};
      found = { count: got.length, photos: photos.length, reader: eng.reader || res.reader, model: eng.model || (res.usage && res.usage.model) || "", tier: eng.tier || res.tier || "",
        rated: !!res.confidence_rated, summary: addSummary(got.map((it) => it._levels)), questions: res.questions || [], tag: res.tag || null, scale: res.scale || null,
        usage: res.usage || null, note: res.note || "", filled: got.length === 1 && got[0].gross != null };
      for (const it of got) { it._open = needsLook(it); items.push(it); addCard(it); }
      addedBox.replaceChildren();
      drawFound(); drawList(); changed();
      return null;
    }, { button: readBtn, kept: true, busy: SW.t("common_reading"), again: read });
    working = null; paintBar(); readable();
  }
  // what the Label Reader said, above the cards (04 4.4)
  function drawFound() {
    if (!found) { foundBox.replaceChildren(); return; }
    const f = found, kids = [line(f.count ? "ok" : "warn", f.count ? SW.t("add_found_result", { count: f.count, photos: f.photos }) : SW.t("add_found_none"))];
    const tier = String(f.tier || "").toLowerCase(), cpuGpu = tier === "cpu" ? SW.t("add_found_tier_cpu") : tier === "gpu" ? SW.t("add_found_tier_gpu") : "";
    const engine = f.reader === "local" ? SW.t("add_found_engine_local") : SW.t("add_found_engine_cloud"), model = f.reader === "local" ? cpuGpu : f.model;
    kids.push(h("p", { class: "muted", textContent: model ? SW.t("add_found_reader", { engine, model }) : SW.t("add_found_reader_only", { engine }) }));
    const sum = addSummaryLine(f.summary);
    if (sum) kids.push(sum);
    if (f.count && !f.rated) kids.push(h("p", { class: "muted", textContent: SW.t("add_found_not_rated_hint") }));
    if ((f.questions || []).length) kids.push(h("div", { class: "add__asks" }, h("h3", { class: "add__asks-title", textContent: SW.t("add_found_questions") }),
      h("ul", {}, ...(f.questions || []).map((q) => h("li", { textContent: q })))));
    if (f.tag) kids.push(SW.banner({ kind: "info", inline: true, text: SW.t("add_found_tag_notice", { tag: f.tag.nfc_id, seconds: f.tag.age_seconds,
      reader: SW.t(/^station$/.test(f.tag.reader) ? "common_reader_the_weigh_station" : "common_reader_the_tag_reader") }) }));
    if (f.scale) kids.push(SW.banner({ kind: "info", inline: true, text: SW.t(f.filled ? "add_found_scale_used" : "add_found_scale_unused", { grams: f.scale.grams, seconds: f.scale.age_seconds }) }));
    if (f.note) kids.push(h("p", { class: "muted", textContent: f.note }));
    const u = f.usage, used = u && u.input_tokens != null ? SW.t("add_found_usage", { tokens_in: u.input_tokens, tokens_cached: u.cached || 0, tokens_out: u.output_tokens || 0 })
      : u && u.ms != null ? SW.t("add_found_usage_time", { seconds: (u.ms / 1000).toFixed(1) }) : "";
    if (used) kids.push(h("details", { class: "add__details" }, h("summary", { textContent: SW.t("common_details") }), h("p", { class: "mono", textContent: used })));
    foundBox.replaceChildren(group(SW.t("add_found_title"), ...kids));
  }

  // ============ By hand (04 4.2) ============
  const searchField = SW.field({ type: "search", label: SW.t("add_search_label"), placeholder: SW.t("common_search_placeholder"), onSearch: (q) => find(q) });
  searchField.classList.add("add__search");
  searchField.querySelector(".field__box").append(SW.iconBtn("search", SW.t("common_search"), { run: () => find(searchField._control.value.trim()) }));
  const findLine = resultLine();
  const findBox = h("div", { class: "add__finds" });
  const newBtn = () => SW.btn(SW.t("add_new_filament"), { icon: "plus", run: () => addItem(blankItem()) });
  handGroup.replaceChildren(h("header", { class: "group__head" }, h("h2", { class: "group__title", textContent: SW.t("add_group_hand") })),
    h("div", { class: "group__body" }, searchField, findLine, findBox, h("div", {}, newBtn()), vendorList));
  api("vendors").then((res) => {
    vendorTare = new Map(res.vendors.map((v) => [v.name.toLowerCase(), v.tare]));
    vendorList.replaceChildren(...res.vendors.map((v) => h("option", { value: v.name })));
    if ([...cards.values()].map((c) => c.refill()).includes(true)) changed();      // a brand typed before the list came gets its empty spool weight now
  }).catch(() => {});                                           // no list: the brand is typed in

  const blankItem = () => ({ vendor: "", name: "", material: "", count: 1, net: 1000, tare: null, density: null, color_hex: "",
    sealed: true, location: SEALED, price_per_kg: "", photos: [], estimates: [], match: "new filament", hand: true });
  function addItem(raw) {
    const it = adopt(raw, false);
    it._open = needsLook(it);
    items.push(it); const c = addCard(it);
    addedBox.replaceChildren();
    drawList(); changed(it);
    c.el.scrollIntoView({ behavior: "smooth", block: "start" });
    c.el.focus({ preventScroll: true });
  }
  async function find(q) {
    const stamp = ++findStamp;
    if (q.length < 2) { rows = []; findBox.replaceChildren(); clear(findLine); return; }
    searchField._busy(true);
    SW.announce(SW.t("common_searching"));
    try {
      const res = await call(`filaments?q=${encodeURIComponent(q)}&limit=${ADD_FIND_LIMIT}`);
      if (stamp !== findStamp) return;
      clear(findLine); rows = res.filaments; more = !!res.has_more || (res.total != null && res.total > rows.length); page = 1; drawRows(false);
      if (!rows.length) SW.announce(SW.t("add_picker_none"));
    } catch (e) { if (stamp === findStamp) { rows = []; findBox.replaceChildren(); failed(findLine, e, () => find(q)); } }
    finally { if (stamp === findStamp) searchField._busy(false); }
  }
  function drawRows(focus) {
    if (!rows.length) { findBox.replaceChildren(h("p", { class: "add__none" }, SW.t("add_picker_none") + " ", newBtn())); return; }
    const shown = rows.slice((page - 1) * ADD_PAGE, page * ADD_PAGE), kids = [];
    kids.push(h("ul", { class: "add__rows" }, ...shown.map((f) => h("li", {}, h("button", { class: "add__row", type: "button", on: { click: () => addItem({ ...blankItem(), vendor: f.vendor, name: f.name, material: f.material || "",
        net: f.net ?? 1000, tare: f.tare, density: f.density, color_hex: f.color_hex || "", nozzle: f.nozzle, bed: f.bed, existing_filament_id: f.id, match: "existing filament" }) } },
      SW.swatch(addHex(f.color_hex)),
      h("span", { class: "add__row-text" }, h("b", { textContent: [f.vendor || SW.t("add_row_no_brand"), f.name].join(" ") }),
        h("span", { class: "muted", textContent: SW.t("add_row_detail", { material: f.material || "?", net: f.net ?? "?", count: f.spools }) })),
      h("span", { class: "add__row-id mono", textContent: SW.t("common_filament_number", { id: f.id }) }),
      h("span", { class: "sr", textContent: SW.t("a11y_swatch", { hex: addHex(f.color_hex) || SW.t("common_no_colour") }) }))))));
    if (rows.length > ADD_PAGE) kids.push(SW.pager({ from: (page - 1) * ADD_PAGE + 1, to: Math.min(rows.length, page * ADD_PAGE), total: rows.length, page, pages: Math.ceil(rows.length / ADD_PAGE),
      go: (p) => { page = p; drawRows(true); } }));
    if (more) kids.push(h("p", { class: "muted", textContent: SW.t("add_results_cut", { count: rows.length }) }));
    findBox.replaceChildren(...kids);
    if (focus) findBox.querySelector(".add__row")?.focus();
  }

  // ============ The spool list and its cards (04 4.5) ============
  const needsLook = (it) => missing(it).length > 0 || ["low", "medium"].some((l) => Object.values(it._levels).includes(l));
  function drawList() {
    count.textContent = items.length ? String(spoolsOf()) : "";
    empty.hidden = items.length > 0; listBox.hidden = !items.length;
    paintBar();
  }
  const addCard = (it) => { const c = buildCard(it); cards.set(it._id, c); listBox.append(c.el); return c; };
  const dropCard = (it) => { const c = cards.get(it._id); if (c) { c.el.remove(); cards.delete(it._id); } };
  const deferred = [];                                          // removed cards whose Undo was pressed while an Add was written
  function removeItem(it) {
    if (working === "add") return;
    const at = items.indexOf(it), c = cards.get(it._id);
    items.splice(at, 1); c.el.remove(); cards.delete(it._id);
    drawList(); changed();
    listHead.focus();
    offerUndo(it, at, c);
  }
  function offerUndo(it, at, c) {
    SW.toast(SW.t("add_review_removed"), "ok", { action: { label: SW.t("common_undo"), run: () => {
      if (working === "add") { deferred.push({ it, at, c }); return; }    // it would be dropped with the sent cards: offered again when the Add is done
      if (items.includes(it)) return;
      const to = Math.min(at, items.length);
      items.splice(to, 0, it); cards.set(it._id, c); listBox.insertBefore(c.el, listBox.children[to] || null);
      drawList(); changed();
    } } });
  }

  function buildCard(it) {
    const id = SW.uid("spool"), fields = {};
    const sw = SW.swatch(""), toolSw = SW.swatch(""), title = h("h3", { class: "add__title", id: id + "-title" }), chips = h("span", { class: "add__chips" });
    const sum = h("p", { class: "add__sum muted" }), att = h("div", { class: "add__att" });
    const body = h("div", { class: "add__body", id: id + "-body" });
    const expand = h("button", { class: "btn btn--ghost btn--icon add__expand", type: "button", "aria-controls": body.id, on: { click: () => open(body.hidden) } }, SW.icon("chevron"));
    const el = h("article", { class: "add__card", tabindex: "-1", "aria-labelledby": title.id }, h("header", { class: "add__head" }, sw,
      h("div", { class: "add__main" }, title, chips, sum, att), expand), body);
    const paintSwatch = () => { const hex = addHex(it.color_hex); for (const s of [sw, toolSw]) { SW.paint(s, hex); s.classList.toggle("swatch--none", !hex); } };
    function open(on) { it._open = on; body.hidden = !on; expand.setAttribute("aria-expanded", String(on)); el.classList.toggle("add__card--open", on); if (on) saveSoon(); }

    // one field: its label, mark and hint follow the item's values; an edit clears the mark and the hint of a reading
    const mk = (key, o = {}) => {
      const f = SW.field({ label: SW.t(o.label || ADD_LABEL[key]), optional: o.optional, hint: "", mono: o.mono, unit: o.unit, decimal: o.decimal, type: o.type || "text",
        value: ADD_NUMBER.has(key) ? (key in it._text ? it._text[key] : it[key] ?? "") : o.value ?? it[key] ?? "", placeholder: o.placeholder, attrs: o.attrs, options: o.options, row: false });
      fields[key] = f;
      const control = f._control;
      control.addEventListener("input", () => edit(key, control.value));
      control.addEventListener("change", () => SW.fieldError(f, sentence(it, key)));
      return f;
    };
    function edit(key, value) {
      if (ADD_NUMBER.has(key)) { it._text[key] = value; const n = addParse(value, key); it[key] = value.trim() === "" || Number.isNaN(n) ? null : n; }
      else if (key === COL) it.color_hex = value.trim().replace(/^#/, "");
      else it[key] = value;
      it._edited = true; delete it._levels[key]; delete it._fill[key]; delete it._problems[key];
      if (key === COL) it._fact = "";
      it._est = it._est.filter((x) => x !== key);
      if (key === "material") fill("density", densityFor(it.material), it.material.trim());
      if (key === "vendor") fill("tare", vendorTare.get(it.vendor.trim().toLowerCase()), "brand");
      if (fields[key]._error && fields[key].dataset.state === "error") SW.fieldError(fields[key], sentence(it, key));
      if (key === "count") paintGross();
      paint(); changed(it);
    }
    function fill(key, value, why) {                             // a known default for a field left blank
      if (value == null || textOf(it, key) !== "") return;
      it[key] = value; fields[key]._control.value = String(value); it._fill[key] = why;
    }
    const mark = (key) => { const lv = it._levels[key]; return lv === "medium" || lv === "low" || lv === "not_on_label" ? SW.status(lv, { small: true, cls: "add__mark" }) : null; };
    const hintOf = (key) => {
      const base = hintBase(key);
      return key === COL && it._fact ? [base, it._fact].filter(Boolean).join(" ") : base;
    };
    const hintBase = (key) => {
      if (it._fill[key]) return it._fill[key] === "brand" ? SW.t("add_hint_from_brand_list") : SW.t("add_hint_typical_for", { material: it._fill[key] });
      if (it._est.includes(key)) return SW.t("add_hint_estimated");
      if (it._levels[key] === "medium" || it._levels[key] === "low") return SW.t("confidence_unsure_hint");
      if (key === "name") return SW.t("add_card_name_help");
      if (key === "line") return SW.t("add_card_line_help");
      if (key === "note") return SW.t("add_card_note_help");
      if (key === "price_per_kg") return it.price_line ? SW.t("add_card_price_help", { price_line: it.price_line.replace(/^Price: /, "") }) : "";
      if (key === "gross") return Number(it.count) > 1 ? SW.t("add_card_gross_single") : SW.t("common_hint_leave_empty_full");
      return "";
    };
    function paintGross() {
      const f = fields.gross; if (!f) return;
      f.hidden = !!it.sealed;
      const one = Number(it.count) > 1;
      f._control.readOnly = one; f._control.setAttribute("aria-disabled", String(one)); if (!one) f._control.removeAttribute("aria-disabled");
    }
    function paint() {                                          // the summary, the attention line, every mark and hint
      const name = `${it.vendor} ${it.name}`.trim() || SW.t("add_card_new_spool");
      title.textContent = name;
      expand.setAttribute("aria-label", SW.t("add_card_expand", { title: name }));
      expand.setAttribute("aria-expanded", String(!body.hidden));
      paintSwatch();
      chips.replaceChildren(h("span", { class: "add__chip", textContent: it.existing_filament_id ? SW.t("add_existing_filament", { id: SW.t("common_filament_number", { id: it.existing_filament_id }) }) : SW.t("add_new_filament") }),
        ...(Number(it.count) > 1 ? [h("span", { class: "add__chip mono", textContent: SW.t("add_card_chip_count", { count: it.count }) })] : []));
      const hex = addHexFull(it.color_hex);
      sum.textContent = [it.material, hex || SW.t("common_no_colour"), it.net != null ? SW.t("common_grams", { grams: it.net }) : "",
        it.sealed ? SW.t("common_sealed") : it.gross != null ? SW.t("add_card_opened", { grams: it.gross }) : SW.t("add_preview_opened"),
        it.location || SW.t("common_option_automatic")].filter(Boolean).join(" · ");
      const miss = missing(it), kids = [];
      if (miss.length) kids.push(line("bad", SW.t("add_review_needs", { fields: miss.map((k) => SW.t(ADD_LABEL[k])).join(", ") })));
      const conf = addSummaryLine(addSummary([it._levels]));
      if (conf && Object.values(it._levels).some((v) => v === "low" || v === "medium" || v === "not_on_label")) kids.push(conf);
      for (const [k, msg] of Object.entries(it._problems)) if (!fields[k] || fields[k].closest("[hidden]")) kids.push(line("bad", msg));
      att.replaceChildren(...kids);
      for (const [key, f] of Object.entries(fields)) {
        f._hint.textContent = hintOf(key);
        const label = f.querySelector(".field__label");
        label.querySelector(".add__mark")?.remove();
        const m = mark(key); if (m) label.append(" ", m);
      }
    }
    function problems(list) {                                   // the Hub's sentences at their fields (04 4.6)
      it._problems = {};
      for (const p of list) it._problems[p.field || "_"] = p.message;
      for (const [k, f] of Object.entries(fields)) SW.fieldError(f, sentence(it, k));
      paint();
    }
    function showErrors() { for (const [k, f] of Object.entries(fields)) SW.fieldError(f, sentence(it, k)); }

    // ---- the fields, in the six groups of the Android app ----
    const colourField = mk(COL, { optional: true, mono: true, unit: "#", placeholder: SW.t("add_card_colour_placeholder"), value: it.color_hex ? addHexFull(it.color_hex) : "" });
    const picker = h("input", { class: "add__picker", type: "color", value: addHex(it.color_hex).toLowerCase() || "#808080", "aria-labelledby": id + "-pick",
      on: { input: (e) => { colourField._control.value = e.target.value.toUpperCase(); edit(COL, colourField._control.value); SW.fieldError(colourField, sentence(it, COL)); } } });
    const box = colourField.querySelector(".field__box");        // the swatch and the picker sit inside the field's box, at its right
    box.querySelector(".field__unit").remove();
    box.append(h("span", { class: "add__colour-tools" }, toolSw, h("span", { class: "sr", id: id + "-pick", textContent: SW.t("add_card_colour_pick") }), picker));
    colourField.classList.add("add__colour");
    const pair = (...kids) => h("div", { class: "add__pair" }, ...kids);
    const set = (name, ...kids) => h("fieldset", { class: "add__set" }, h("legend", { class: "add__legend", textContent: name }), ...kids);
    const locations = [...LOCATIONS]; if (SEALED && !locations.includes(SEALED)) locations.push(SEALED);
    const location = mk("location", { type: "select", value: it.location || "", options: [{ value: "", label: SW.t("add_card_location_automatic_rule", { rule: AUTO }) }, ...locations.map((l) => ({ value: l, label: l }))] });
    location._control.value = it.location || "";
    location._control.setAttribute("aria-required", "false");
    const sealed = SW.toggle({ label: SW.t("common_still_sealed"), checked: !!it.sealed, hint: it.sealed_reason ? SW.t("add_review_reader_reason", { reason: it.sealed_reason }) : undefined });
    sealed._control.addEventListener("change", () => {
      it.sealed = sealed._control.checked; it.location = it.sealed ? SEALED : ""; location._control.value = it.location;
      it._edited = true; paintGross(); paint(); changed(it);
    });
    const gross = mk("gross", { optional: true, decimal: true, unit: "g" }); paintGross();
    body.append(h("div", { class: "add__sets" },
      set(SW.t("common_group_identity"), mk("vendor", { attrs: { list: "addVendors", autocapitalize: "words" } }), mk("name"), mk("material"),
        colourField, mk("line", { optional: true })),
      set(SW.t("add_group_amount"), pair(mk("count", { type: "number" }), mk("density", { type: "number", optional: true, decimal: true, unit: "g/cm³" })),
        pair(mk("net", { type: "number", decimal: true, unit: "g" }), mk("tare", { type: "number", optional: true, decimal: true, unit: "g" }))),
      set(SW.t("add_group_state"), sealed, gross),
      set(SW.t("add_group_print"), pair(mk("nozzle", { type: "number", optional: true, unit: "°C" }), mk("bed", { type: "number", optional: true, unit: "°C" }))),
      set(SW.t("add_group_storage"), location),
      set(SW.t("common_group_other"), mk("lot", { optional: true, mono: true }), mk("price_per_kg", { type: "number", optional: true, decimal: true }), mk("note", { optional: true }))),
      h("div", { class: "add__foot" }, SW.btn(SW.t("common_remove"), { cls: "btn--ghost", icon: "trash", run: () => removeItem(it) })));
    open(it._open === undefined ? needsLook(it) : it._open);
    paint();
    // the vendor list arrived after the brand was typed: fill a blank empty spool weight, as typing it now would
    function refill() {
      if (textOf(it, "tare") !== "") return false;
      const v = vendorTare.get(it.vendor.trim().toLowerCase());
      if (v == null) return false;
      fill("tare", v, "brand"); paint();
      return true;
    }
    return { el, open, problems, showErrors, paint, refill, control: (k) => (fields[k] ? fields[k]._control : null) };
  }

  // ============ The action bar: Preview, then Add (04 4.6) ============
  const barText = h("p", { class: "add__bar-text", id: SW.uid("bar") });
  const barBtn = h("button", { class: "btn btn--primary add__bar-btn", type: "button", "aria-describedby": barText.id, on: { click: () => (previewed && !working ? submit(false) : submit(true)) } }, SW.t("common_preview"));
  const bar = h("div", { class: "add__bar" }, barText, barBtn);
  // how many fields the Label Reader was not sure of, over all the cards
  const toCheck = () => items.reduce((n, it) => n + ADD_RATED.filter((k) => it._levels[k] === "low" || it._levels[k] === "medium").length, 0);
  function paintBar() {
    const n = spoolsOf(), block = items.length ? firstBlock() : null;
    let text, label = SW.t("common_preview"), off = false, plain = false;
    if (working === "read") { text = SW.t("add_wait_reader"); off = true; }
    else if (!items.length) { text = SW.t("add_bar_empty"); off = true; }
    else if (block) {
      const num = items.indexOf(block.it) + 1;
      if (block.kind === "missing") text = block.many > 1 ? SW.t("add_bar_missing_many", { count: block.many, number: num }) : SW.t("add_bar_missing", { number: num, fields: block.keys.map((k) => SW.t(ADD_LABEL[k])).join(", ") });
      else { const k = block.keys[0]; text = ["net", "tare", "gross"].includes(k) && wrong(block.it, k) !== SW.t("add_card_grams_plain") ? SW.t("add_bar_invalid", { number: num, field: SW.t(ADD_LABEL[k]) })
        : SW.t("add_bar_field_error", { number: num, field: SW.t(ADD_LABEL[k]), message: wrong(block.it, k) }); }
      off = true;
    } else if (hubDown) { text = SW.t("add_bar_offline"); off = true; }
    else if (working === "preview") text = SW.t("add_preview_checking");
    else if (working === "add") text = SW.t("add_preview_adding");
    else if (problemsShown) text = SW.t("add_bar_problems");
    else if (previewed) { text = SW.t("add_bar_previewed", { count: n }); label = SW.t("add_preview_add", { count: n }); plain = true; }
    else if (edited && cards.has(edited)) { text = SW.t("add_bar_changed", { number: items.findIndex((it) => it._id === edited) + 1 }); }
    else { text = SW.t("add_bar_ready", { count: n }); plain = true; }
    const check = toCheck();
    if (check && (plain || previewed)) text = `${SW.t("add_bar_to_check", { count: check })} · ${text}`;
    barText.textContent = text;
    if (barBtn.getAttribute("aria-busy") !== "true") barBtn.textContent = label;
    barBtn._blocker = off && block ? () => { const c = cards.get(block.it._id); c.open(true); c.showErrors(); return c.control(block.keys[0]); } : null;
    barBtn._reason = off ? barText : null;
    if (off || working) barBtn.setAttribute("aria-disabled", "true"); else barBtn.removeAttribute("aria-disabled");
    if (working && working !== "read") barBtn.setAttribute("aria-disabled", "true");
  }
  // what the preview says each spool does: existing or new filament, how many spools, where (04 4.6, N18)
  function drawResults(list) {
    itemsBox.replaceChildren(...list.map((r) => {
      const where = (r.placements || []).map((p) => (r.placements.length > 1 ? SW.t("add_preview_placement", { spools: p.spools, location: p.location }) : p.location)).join(", ") || r.location;
      return h("p", { class: "add__result-row" }, h("b", { textContent: [r.vendor, r.name].join(" ") }), " · ",
        r.filament === "new" ? SW.t("add_new_filament") : SW.t("add_existing_filament", { id: SW.t("common_filament_number", { id: r.filament_id }) }), " · ",
        SW.t("add_review_summary_spools", { count: r.spools }), " · ", r.opened ? SW.t("add_preview_opened") : SW.t("common_sealed"), " · ", where,
        r.new_vendor ? [" · ", SW.t("add_preview_new_vendor")] : null);
    }));
  }
  function showProblems(list) {                                 // every sentence at its field; the first spool that has one opens (04 4.6)
    const by = new Map();
    for (const p of list) { const it = items[p.item]; if (it) by.set(it, [...(by.get(it) || []), p]); }
    for (const it of items) cards.get(it._id).problems(by.get(it) || []);
    const first = items.find((it) => by.has(it));
    if (first) { const c = cards.get(first._id); c.open(true); const key = by.get(first)[0].field; (c.control(key) || c.el).focus(); }
    problemsShown = true;
  }
  async function submit(dry) {
    if (working || barBtn.getAttribute("aria-disabled") === "true") return;
    working = dry ? "preview" : "add"; edited = null; previewed = false; paintBar();   // only a preview that answers well makes the bar offer Add
    ans.code.replaceChildren(); itemsBox.replaceChildren(); extras.replaceChildren();
    const mine = resultGroup(dry ? SW.t("add_preview_title") : SW.t("common_add"), dry), sent = rev;
    previewBox.replaceChildren(mine);
    for (const part of [inputs, foundBox, listGroup, draftBox]) part.inert = !dry;     // while an Add is written nothing is edited
    const n = spoolsOf(), sentItems = items.slice();
    try {
      await act(ans, dry ? SW.t("add_preview_checking") : SW.t("add_preview_adding"), async () => {
        let res;
        try { res = await call("add", { body: { items: items.map(wire), dry_run: dry, link_tag: tag ? tag.nfc_id : null, read_id: readId } }); }
        catch (e) {
          if (e instanceof SW.HubError && e.data && Array.isArray(e.data.problems)) {
            if (rev !== sent) { previewBox.replaceChildren(); memo = null; return null; }      // edited since: these sentences are about the old cards
            showProblems(e.data.problems);
            return shown({ kind: "bad", text: SW.t(dry ? "add_summary_error_preview" : "add_summary_error_change") });
          }
          if (e instanceof SW.HubError && e.status === 409) e.message = `${e.text("")} ${SW.t("add_tag_conflict")}`;
          throw e;
        }
        if (res.exit_code) { previewed = false; problemsShown = true; return shown({ kind: "bad", text: SW.t(dry ? "add_summary_error_preview" : "add_summary_error_change"), code: res.output }); }
        if (dry) {
          if (rev !== sent) { previewBox.replaceChildren(); memo = null; return null; }          // edited while it was checked: not previewed
          previewed = true; problemsShown = false;
          for (const it of items) cards.get(it._id).problems([]);
          drawResults(res.items || []);
          return shown({ text: SW.t("add_summary_preview_ok"), code: res.output });
        }
        const ids = res.spool_ids || [], made = (res.items || []).filter((r) => r.filament === "new").length;
        previewBox.replaceChildren(); addedBox.replaceChildren(mine);
        mine.querySelector(".group__title").textContent = SW.t("add_done_title");
        mine.querySelector(".add__sub")?.remove();
        everything(sentItems); SW.toast(SW.t("add_added_toast", { count: ids.length || n }));
        if (HISTORY && res.history_id) extras.append(SW.btn(SW.t("add_added_check_recent"), { run: () => { location.hash = "#recent/" + encodeURIComponent(res.history_id); } }));
        if (made || !res.items) extras.append(h("p", {}, made ? SW.t("add_added_new_filaments", { count: made }) : null),
          SW.btn(SW.t("add_added_set_up_presets"), { run: () => { location.hash = "#presets"; } }));
        mine.scrollIntoView({ behavior: "smooth", block: "start" });
        return shown({ text: ids.length ? SW.t("add_summary_added", { count: ids.length, ids: ids.join(", ") }) : SW.t("add_done_none"), code: res.output });
      }, { button: barBtn, busy: dry ? SW.t("common_checking") : SW.t("common_adding"), again: () => submit(true) });
    } finally {
      working = null; paintBar();
      for (const part of [inputs, foundBox, listGroup, draftBox]) part.inert = false;
      for (const d of deferred.splice(0)) offerUndo(d.it, d.at, d.c);
      if (previewBox.firstElementChild) previewBox.firstElementChild.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
  const shown = (r) => { memo = r; return r; };
  // the group of the answer: its title, "Nothing is saved yet." for a preview, then the line, the spools and the Hub's text
  function resultGroup(title, dry) {
    const g = group(title, dry ? h("p", { class: "add__sub muted", textContent: SW.t("add_preview_nothing_saved") }) : null, ans.el);
    return g;
  }
  // everything of the add is cleared after an Add: cards, photos, note, tag, search (04 4.6)
  function everything(sent) {
    for (const it of sent) dropCard(it);
    items = items.filter((it) => !sent.includes(it));          // a card that was not sent stays
    previewed = false; problemsShown = false; edited = null;
    if (items.length) { drawList(); paintBar(); save(); return; }
    tag = null; readId = null; found = null;
    photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url));
    noteField._control.value = ""; searchField._control.value = ""; rows = []; findBox.replaceChildren(); clear(findLine);
    drawFound(); drawPhotos(); drawList(); clearDraft();
  }

  // ---- put the page together ----
  const intro = h("p", { class: "muted add__intro", textContent: SW.t("add_intro") });
  const inputs = h("div", { class: "add__inputs" }, ...(AI ? [photoGroup, handGroup] : [handGroup, photoGroup]));
  const listGroup = h("section", { class: "group add__group", "aria-labelledby": listHead.id }, h("header", { class: "group__head" }, listHead),
    h("div", { class: "group__body" }, empty, listBox));
  listHead.replaceChildren(SW.t("add_group_list"), " ", count);
  const el = h("section", { class: "add hidden" }, intro, lines, draftBox, addedBox, inputs, foundBox, listGroup, previewBox, bar);
  if (!store.works()) noStorage(true);
  const stored = store.get();
  pending = clean(stored);
  if (!pending && !(isObj(stored) && stored.v === 1 && Array.isArray(stored.items) && stored.items.length)) store.drop();   // a draft that is no draft at all; one with odd items is left alone
  const extra = clean(store.get(ADD_NEW));
  if (extra) {                                                  // work started while a draft waited, in an earlier visit: it joins that draft
    pending = pending ? { ...pending, items: [...pending.items, ...extra.items], note: [pending.note, extra.note].filter(Boolean).join("\n"), changed: extra.changed || pending.changed,
      found: extra.found || pending.found, readId: extra.readId || pending.readId, tag: extra.tag || pending.tag } : extra;
    if (store.put(JSON.stringify(pending))) store.drop(ADD_NEW);
  } else store.drop(ADD_NEW);
  drawDraft(); drawPhotos(); drawList(); paintBar();
  setTimeout(paintBadge, 0);                                    // the bottom bar is built after this tab
  return { el, enter: () => {
    if (memo && !ans.line.dataset.state) SW.result(ans.line, memo.kind || "ok", memo.text);       // the result lines are cleared when the person leaves the page
  } };
}

// ---------- Open spool, now Spools (04 5): the last tag, search, and the spool sheet ----------
function openTab() {
  const EDIT = document.body.dataset.spoolEdit === "1";      // the Hub offers spool editing to the web app (04 14)
  const SEALED_KEY = "spoolwarden.sealedOnly", PAGE = 50;
  let sealedOnly = true;
  try { sealedOnly = localStorage.getItem(SEALED_KEY) !== "0"; } catch {}   // on by default; a browser without storage keeps the default
  let shown = false, timer = null, polling = false, lastKey = null, tagAt = null, lastTag = null, tagStamp = 0, tagLoad = null, ageEl = null;
  let sheet = null;                                          // the open spool sheet: { id, dlg, rec, tag(t, fresh) }
  let changed = false;                                       // a sheet changed a spool: the list is searched again when it closes
  let rows = [], page = 1, cut = false, asked = false, lastQ = "", findStamp = 0, firstLoad = null;
  const hexOf = (v) => (/^[0-9A-Fa-f]{6}$/.test(v || "") ? "#" + v : "");
  const group = (title, ...kids) => { const id = SW.uid("g"); return h("section", { class: "group", "aria-labelledby": id },
    h("header", { class: "group__head" }, h("h2", { class: "group__title", id }, title)), h("div", { class: "group__body" }, ...kids)); };
  const ageText = (s) => SW.t(s < 60 ? "common_age_seconds" : s < 3600 ? "common_age_minutes" : "common_age_hours", { count: s < 60 ? s : s < 3600 ? Math.floor(s / 60) : Math.floor(s / 3600) });
  const atStation = (t) => t.reader === "station";             // the Weigh Station; any other reader is a Tag Reader
  const onScale = (t) => atStation(t) && !!t.scale;             // a tap on the Weigh Station that came with a scale reading
  const readerOf = (t, the) => SW.t(atStation(t) ? (the ? "common_reader_the_weigh_station" : "common_reader_weigh_station")
    : (the ? "common_reader_the_tag_reader" : "common_reader_tag_reader"));
  const lines = (list) => list.flatMap((t, i) => (i ? [h("br"), t] : [t]));       // a result of several lines
  const num = (f) => f._control.value.trim().replace(",", ".");                    // what the Hub reads: a number as text, or blank
  const grams = (v) => Math.round(Number(v) || 0);
  const nameOf = (v) => [v.vendor, v.name].filter(Boolean).join(" ");

  // ----- Last tag (04 5.2): GET tag every 3 s while the screen is on show and the page is visible -----
  const tagBody = h("div", { class: "spools__tag" }), tagLine = resultLine(), tagFirst = resultLine();
  const linkedBox = h("div", { class: "spools__linked" });
  const tagKids = (t) => {
    if (!t.nfc_id) { ageEl = null; return [h("p", { class: "spools__state" }, SW.shape("s-hollow"), h("span", { textContent: SW.t("common_no_tag_yet") }))]; }
    ageEl = h("span", { class: "spools__age muted" });
    const meta = [readerOf(t), t.scale ? SW.t("spools_tag_scale", { grams: t.scale.grams }) : null].filter(Boolean).join(" · ");
    return [h("p", { class: "spools__tagline" }, SW.icon("tag"), h("span", { class: "mono spools__tagid", textContent: t.nfc_id }), ageEl),
      h("p", { class: "muted spools__meta", textContent: meta }), h("p", { class: "spools__hub", textContent: t.text || "" }), linkedBox];
  };
  async function showLinked(t, stamp) {                      // the spool this tag belongs to (the Printers Feature's route has it)
    linkedBox.replaceChildren();
    if (!PRINTERS || !t.nfc_id) return;
    try {
      const r = await api("printers/tagged");
      if (stamp !== tagStamp || !r.spool) return;
      const s = r.spool;
      linkedBox.replaceChildren(h("p", { textContent: SW.t("spools_tag_linked", { id: s.id, name: nameOf(s) }) }),
        SW.btn(SW.t("spools_show", { id: s.id }), { run: (e) => openSheet(s.id, e.currentTarget) }));
    } catch { /* the tag stays without its link line */ }
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const t = await api("tag");
      tagAt = Date.now(); clear(tagLine);
      const key = `${t.nfc_id}|${t.read_at}`, fresh = key !== lastKey;
      if (fresh) {
        lastKey = key;
        const kids = tagKids(t);
        if (tagLoad) { const l = tagLoad; tagLoad = null; l.done(...kids); } else tagBody.replaceChildren(...kids);
        showLinked(t, ++tagStamp);
      }
      lastTag = t;
      if (ageEl && t.age_seconds != null) ageEl.textContent = ageText(t.age_seconds);   // text in place, nothing redrawn
      if (sheet) sheet.tag(t, fresh, key);
    } catch (e) {
      if (tagAt != null) stale(tagLine, tagAt);                // the last tag stays on screen
      else if (tagFirst._said !== says(e)) {                   // nothing to keep yet; said once, not at every poll
        tagFirst._said = says(e);
        if (tagLoad) { const l = tagLoad; tagLoad = null; l.done(tagFirst); }
        failed(tagFirst, e, poll);
      }
    } finally { polling = false; }
  }
  const stopPoll = () => { clearInterval(timer); timer = null; };
  const startPoll = () => { stopPoll(); poll(); timer = setInterval(poll, 3000); };
  document.addEventListener("visibilitychange", () => { if (shown) { if (document.hidden) stopPoll(); else startPoll(); } });   // not while the page is hidden or the phone locked

  // ----- Search (04 5.3) -----
  const searchField = SW.field({ type: "search", label: SW.t("spools_find_label"), placeholder: SW.t("common_search_placeholder"), onSearch: (q) => find(q) });
  searchField.classList.add("spools__search");
  searchField.querySelector(".field__label").classList.add("sr");
  searchField.querySelector(".field__box").append(SW.iconBtn("search", SW.t("common_search"), { run: () => find(searchField._control.value.trim()) }));
  const sealedBox = SW.check({ label: SW.t("spools_sealed_only"), checked: sealedOnly });
  sealedBox._control.addEventListener("change", () => {
    sealedOnly = sealedBox._control.checked;
    try { localStorage.setItem(SEALED_KEY, sealedOnly ? "1" : "0"); } catch { /* not remembered here */ }
    find(searchField._control.value.trim());
  });
  const findLine = resultLine(), resultsBox = h("div", { class: "spools__results" });
  async function find(q) {
    lastQ = q;
    const mine = ++findStamp;
    if (!asked && !firstLoad) firstLoad = SW.loading(resultsBox, { thing: SW.t("nav_spools"), items: 3 });
    searchField._busy(true);
    await act(findLine, SW.t("common_searching"), async () => {
      try {
        const res = await api(`find?q=${encodeURIComponent(q)}&sealed=${sealedOnly ? 1 : 0}`);
        if (mine !== findStamp) return null;
        rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ f, s })));
        cut = !!res.truncated; page = 1; asked = true;
        if (firstLoad) { firstLoad.done(); firstLoad = null; }
        drawResults(false);
      } catch (e) { if (firstLoad && mine === findStamp) { firstLoad.done(); firstLoad = null; } throw e; }
      return null;
    });
    if (mine === findStamp) searchField._busy(false);
  }
  function rowButton(f, s) {
    const net = Number(f.net_g), level = net > 0 && s.remaining_g != null ? s.remaining_g / net : null, colour = hexOf(f.color_hex);
    const detail = [s.location || "?", SW.t("common_grams", { grams: s.remaining_g == null ? "?" : grams(s.remaining_g) }), s.sealed ? SW.t("common_sealed") : null,
      s.tagged ? SW.t("spools_row_tag") : null, s.lot ? SW.t("spools_row_lot", { lot: s.lot }) : null].filter(Boolean).join(" · ");
    return h("button", { class: "spools__row", type: "button", on: { click: (e) => openSheet(s.spool_id, e.currentTarget) } },
      SW.swatch(colour, { level }),
      h("span", { class: "spools__row-text" }, h("b", { class: "mono", textContent: SW.t("spool_title", { id: s.spool_id }) }), h("span", { class: "muted", textContent: detail })),
      SW.icon("chevron", "icon--s spools__chevron"), h("span", { class: "sr", textContent: SW.t("a11y_swatch", { hex: colour || SW.t("common_no_colour") }) }));
  }
  function drawResults(focus) {
    if (!rows.length) { resultsBox.replaceChildren(h("p", { class: "spools__none", textContent: SW.t(sealedOnly ? "spools_empty_sealed" : "spools_empty_filtered") })); return; }
    const pages = Math.ceil(rows.length / PAGE), kids = [];
    page = Math.min(page, pages);
    let cur = null, list = null;
    for (const { f, s } of rows.slice((page - 1) * PAGE, page * PAGE)) {
      if (!cur || cur.filament_id !== f.filament_id) {
        cur = f; list = h("ul", { class: "spools__rows" });
        kids.push(h("div", { class: "spools__fil" }, h("h3", { class: "spools__fil-name", textContent: nameOf(f) }),
          h("p", { class: "muted spools__fil-meta", textContent: [f.material, SW.t("common_filament_number", { id: f.filament_id })].filter(Boolean).join(" · ") })), list);
      }
      list.append(h("li", {}, rowButton(f, s)));
    }
    if (rows.length > PAGE) kids.push(SW.pager({ from: (page - 1) * PAGE + 1, to: Math.min(rows.length, page * PAGE), total: rows.length, page, pages,
      go: (p) => { page = p; drawResults(true); } }));
    if (cut) kids.push(h("p", { class: "muted", textContent: SW.t("spools_cut") }));
    resultsBox.replaceChildren(...kids);
    if (focus) resultsBox.querySelector(".spools__row")?.focus();
  }

  // ----- The spool sheet (04 5.4): address #spools/<id>; how: "push" (a row was pressed), "entry" (the address is already in
  // the history), "direct" (the page was loaded at it) -----
  function closeSheet() { if (sheet) { sheet.rec.popped = true; sheet.dlg.close(); } }
  function openSheet(id, opener, how = "push") {
    if (sheet && sheet.id === id) return;
    closeSheet();
    let view = null, previewed = false, problem = false, weightTyped = false, spentKey = null, undoStamp = 0;
    const part = (title, ...kids) => h("section", { class: "spools__part" }, h("h3", { class: "spools__part-title", textContent: title }), ...kids);

    // -- the summary at the top, read from GET spools/<id> --
    const sum = h("div", { class: "spools__sum" });
    const sumKids = (v) => {
      const state = v.state === "sealed" ? SW.t("common_sealed") : v.state === "empty" ? SW.t("common_empty") : SW.t("spool_state_opened");
      const detail = [v.location || "?", SW.t("spool_left_grams", { grams: v.remaining_g == null ? "?" : grams(v.remaining_g) }), state, v.tag ? SW.t("spools_row_tag") : null,
        v.lot ? SW.t("spools_row_lot", { lot: v.lot }) : null].filter(Boolean).join(" · ");
      return [SW.swatch(hexOf(v.color_hex), { size: "l" }), h("div", { class: "spools__sum-text" }, h("b", { textContent: nameOf(v) }),
        h("span", { class: "muted", textContent: detail }))];
    };
    const applyView = (v) => { view = v; sum.replaceChildren(...sumKids(v)); paintActions(); };
    const refresh = () => fill(sum, SW.t("spool_title", { id }), async () => {
      try { const r = await api(`spools/${id}`); view = r.view; const kids = sumKids(view); paintActions(); return kids; }
      catch (e) { if (e instanceof SW.HubError && e.status === 404) { openPart.hidden = true; if (other) other.hidden = true; } throw e; }
    }, { quiet: !!view, items: 1 });

    // -- Open it and link the tag --
    const tagText = h("p", { class: "spools__sheet-tag" });
    const paintTag = (t) => { tagText.textContent = t && t.nfc_id ? SW.t("spool_sheet_tag_line", { tag: t.nfc_id, age: t.age_seconds != null ? ageText(t.age_seconds) : "", reader: readerOf(t, true) })
      : SW.t("spool_sheet_no_tag"); };
    const within = (lo, hi) => (v) => { const n = Number(v.trim().replace(",", ".")); return !v.trim() || (n >= lo && n <= hi) ? null : ""; };
    const weight = SW.field({ type: "number", decimal: true, label: SW.t("common_field_weight_with_spool"), optional: true, unit: "g", hint: "",
      check: (v) => (within(Number.MIN_VALUE, Infinity)(v) === null ? null : SW.t("field_error_grams")) });
    const loc = SW.field({ label: SW.t("common_field_location"), optional: true, hint: SW.t("common_hint_leave_empty_auto"), attrs: { list: "spools-locs" } });
    const hum = SW.field({ label: SW.t("spool_sheet_humidity"), optional: true, unit: SW.t("common_unit_percent"), hint: "", attrs: { inputmode: "decimal" },   // a text field: the number field is short, the placeholder is long
      placeholder: SW.t("spool_sheet_humidity_placeholder"), check: (v) => (within(0, 100)(v) === null ? null : SW.t("spool_sheet_humidity_error")) });
    const ans = answer();             // the answer to Preview and Link: the line, and the Hub's own text under it
    const previewBtn = SW.btn(SW.t("common_preview"), { run: (e) => submit(true, e.currentTarget) });
    const linkBtn = SW.btn(SW.t("spool_sheet_link"), { cls: "btn--primary", run: (e) => submit(false, e.currentTarget) });
    // Link waits for a Preview of what is on the form; an edit makes the last Preview stale (04 3.4)
    // rev counts what changes the form or the tag; a Preview answer counts only if rev is what it was when the Preview went out, and
    // Link sends exactly the body that was previewed (R345)
    let linkKey = "spool_sheet_reason_preview_first", rev = 0, working = false, shot = null;   // shot: { rev, body } of the last good Preview
    const gone = () => !!view && view.state === "empty";
    const link = (key) => { linkKey = key; disabled(linkBtn, gone() ? SW.t("spool_sheet_reason_empty") : key ? SW.t(key) : null, () => previewBtn); };
    const outOfDate = (edit) => { rev++; const was = previewed || problem; previewed = false; link(edit && was ? "spool_sheet_reason_weight_changed" : "spool_sheet_reason_preview_first"); };
    weight._control.addEventListener("input", () => { weightTyped = true; weight._hint.textContent = ""; outOfDate(true); problem = false; });
    for (const f of [loc, hum]) f._control.addEventListener("input", () => { outOfDate(false); problem = false; });
    async function submit(dry, button) {
      if (working) return;                                     // one request at a time: Preview and Link
      let body;
      if (dry) {
        const bad = [weight, hum].filter((f) => { const err = f._check(); SW.fieldError(f, err || null); return !!err; });
        if (bad.length) return bad[0]._control.focus();
        body = { spool: id, gross: num(weight), location: loc._control.value, humidity: num(hum), dry_run: true };
      } else {
        if (!shot || shot.rev !== rev) { link("spool_sheet_reason_weight_changed"); return; }
        body = { ...shot.body, dry_run: false };              // what was previewed, not what the fields say now
      }
      const mine = rev;
      working = true;
      try {
        await act(ans, SW.t(dry ? "common_checking" : "common_working"), async () => {
          let res;
          try { res = await api("open", { body }); }
          catch (e) { if (dry && mine === rev) { previewed = false; problem = true; link("spool_sheet_reason_problem"); } throw e; }
          if (dry && mine !== rev) { link("spool_sheet_reason_weight_changed"); return null; }   // an edit or a newer tag came meanwhile: this answer is for what was
          previewed = dry && !res.exit_code; problem = !!res.exit_code;
          shot = previewed ? { rev: mine, body } : null;
          link(previewed ? null : problem ? "spool_sheet_reason_problem" : "spool_sheet_reason_preview_first");
          if (res.exit_code) return { kind: "bad", text: SW.t(dry ? "add_summary_error_preview" : "add_summary_error_change"), code: res.output };
          if (dry) return { text: SW.t("add_summary_preview_ok"), code: res.output };
          rev++; shot = null;
          for (const f of [weight, loc, hum]) f._control.value = "";
          weightTyped = false; spentKey = lastKey; lastKey = null; changed = true;   // the tag is spent; the next poll draws it again with its new text
          SW.toast(SW.t("spool_sheet_opened_toast", { id }));
          refresh();
          return { text: SW.t("spool_sheet_opened", { id }), code: res.output };
        }, { button });
      } finally { working = false; }
      link(linkKey);                                           // the busy button gave back the state it had before the press
    }
    const openPart = part(SW.t("spool_sheet_open_title"), tagText, weight, loc, hum, h("div", { class: "spools__buttons" }, previewBtn, linkBtn), ans.el);
    link(linkKey);

    // -- Other actions: Update weight, Move, Load into a printer, and Mark empty kept apart --
    const actAns = resultLine();      // the answer to Move, Mark empty and Load; Update weight has its own line while it is open
    const weightBtn = SW.btn(SW.t("spool_update_weight"), { run: () => showWeight(weightForm.hidden) });
    const moveBtn = SW.btn(SW.t("spool_move"), {});
    const loadBtn = SW.btn(SW.t("spool_load"), { run: () => pickPrinter() });
    const emptyBtn = SW.btn(SW.t("spool_mark_empty"), { cls: "btn--danger", run: (e) => markEmpty(e.currentTarget) });
    function paintActions() {
      const empty = gone(), why = SW.t("spool_sheet_reason_empty");
      disabled(previewBtn, empty ? why : null); link(linkKey);   // an empty spool is not opened
      if (!other) return;
      other.hidden = false;
      disabled(weightBtn, empty ? why : null); disabled(emptyBtn, empty ? why : null); disabled(loadBtn, empty ? why : null);
      disabled(moveBtn, LOCATIONS.length ? null : SW.t("spool_move_none"));
      if (empty) showWeight(false);
    }
    // Update weight: a small form in place; Preview says what the remaining weight becomes, then Save weight
    const wf = SW.field({ type: "number", decimal: true, label: SW.t("common_field_weight_with_spool"), unit: "g", hint: SW.t("spool_weight_hint"),
      check: (v) => (within(Number.MIN_VALUE, Infinity)(v) === null && v.trim() ? null : SW.t("common_error_grams")) });
    const wAns = resultLine();
    const wPreview = SW.btn(SW.t("common_preview"), { run: (e) => weightGo(true, e.currentTarget) });
    const wSave = SW.btn(SW.t("spool_weight_save"), { cls: "btn--primary", run: (e) => weightGo(false, e.currentTarget) });
    const weightForm = h("div", { class: "spools__form", hidden: true }, wf, h("div", { class: "spools__buttons" }, wPreview, wSave), wAns);
    let wWas = false, wKey = "spool_weight_need_preview", wRev = 0, wWorking = false, wShot = null;   // wWas: a Preview has run; wKey: why Save weight waits; wShot: { rev, value } of the last good Preview
    const wLock = (key) => { wKey = key; disabled(wSave, key ? SW.t(key) : null, () => (wf._control.value.trim() ? wPreview : wf._control)); };
    wLock(wKey);
    wf._control.addEventListener("input", () => { wRev++; wLock(wWas ? "spool_sheet_reason_weight_changed" : "spool_weight_need_preview"); clear(wAns); });
    function showWeight(open) {
      weightForm.hidden = !open; weightBtn.setAttribute("aria-expanded", String(open));
      if (open) wf._control.focus();
    }
    async function weightGo(dry, button) {
      if (wWorking) return;
      let value;
      if (dry) {
        const err = wf._check(); SW.fieldError(wf, err || null);
        if (err) return wf._control.focus();
        value = num(wf);
      } else {
        if (!wShot || wShot.rev !== wRev) { wLock("spool_sheet_reason_weight_changed"); return; }
        value = wShot.value;                                   // what was previewed, not what the field says now
      }
      const mine = wRev;
      wWorking = true;
      try {
        await act(wAns, SW.t(dry ? "common_checking" : "common_working"), async () => {
          let r;
          try { r = await api(`spools/${id}`, { body: { gross: value, dry_run: dry } }); }
          catch (e) { if (e && e.field === "gross") SW.fieldError(wf, says(e)); throw e; }
          const left = grams(r.view.remaining_g);
          if (dry) {
            if (mine !== wRev) { wLock("spool_sheet_reason_weight_changed"); return null; }   // edited while the Preview was out
            wWas = true; wShot = { rev: mine, value }; wLock(null);
            return SW.t("spool_sheet_weight_changes", { from: grams(r.before.remaining_g), to: left });
          }
          changed = true; applyView(r.view); wf._control.value = ""; wWas = false; wShot = null; wRev++; wLock("spool_weight_need_preview"); showWeight(false);
          SW.toast(SW.t("spool_result_weight", { left })); SW.result(actAns, "ok", SW.t("spool_result_weight", { left }));
          return null;
        }, { button });
      } finally { wWorking = false; }
      wLock(wKey);
    }
    // Move: a menu of locations; choosing one moves the spool at once, with Undo for 5 s
    SW.menu(moveBtn, () => LOCATIONS.map((l) => { const here = !!view && l === view.location;
      return { label: l, disabled: here, reason: here ? SW.t("spool_move_here") : null, run: () => moveTo(l, false) }; }), { label: SW.t("spool_move_title") });
    let moving = false, undoFrom = null;                       // undoFrom: the place before the first move of the Undo window
    async function moveTo(l, back) {
      if (moving || (!back && view && l === view.location)) return;   // one move at a time; not to where it is
      moving = true;
      try {
        await act(actAns, SW.t("spool_move_moving"), async () => {
          const r = await api(`spools/${id}`, { body: { location: l, dry_run: false } });
          const text = SW.t("spool_result_moved", { location: l }), stamp = ++undoStamp;
          if (!back && undoFrom == null) undoFrom = r.before.location || null;   // a second move in the window keeps the first place
          changed = true; applyView(r.view);
          if (back || !undoFrom) { undoFrom = null; return text; }
          setTimeout(() => { if (stamp === undoStamp) { undoFrom = null; if (actAns.querySelector(".btn")) SW.result(actAns, "ok", text); } }, 5000);   // Undo goes after 5 s
          return { text, action: { label: SW.t("common_undo"), run: () => moveTo(undoFrom, true) } };
        });
      } finally { moving = false; }
    }
    // Mark empty: asks first (04 12.1)
    async function markEmpty(opener) {
      const name = view ? nameOf(view) : SW.t("spool_title", { id });
      const done = await SW.ask({ open: openHere, kind: "destructive", title: SW.t("spool_empty_title", { id }), text: SW.t("spool_sheet_empty_body", { name }),
        confirm: SW.t("spool_mark_empty"), opener, run: async () => {
          try { const r = await api(`spools/${id}`, { body: { empty: true, dry_run: false } }); changed = true; applyView(r.view); return true; }
          catch (e) { throw Object.assign(e, { text: () => says(e) }); }
        } });
      if (done) { SW.toast(SW.t("spool_result_empty")); SW.result(actAns, "ok", SW.t("spool_result_empty")); }
    }
    // Load into a printer: the printers, then the slots, then the plan and Load (the routes of the load sheet of 04 6.5)
    const loadBox = h("div", { class: "spools__load", hidden: true });
    const enc = encodeURIComponent;
    const closeLoad = () => { loadBox.hidden = true; loadBox.replaceChildren(); loadBtn.focus(); };
    const stepFoot = (back) => h("div", { class: "spools__buttons" }, SW.btn(SW.t("common_back"), { run: back }), back === closeLoad ? null : SW.btn(SW.t("common_cancel"), { run: closeLoad }));
    const pickRow = (kids, run) => h("li", {}, h("button", { class: "spools__row", type: "button", on: { click: run } }, ...kids, SW.icon("chevron", "icon--s spools__chevron")));
    const wordOf = (state) => (state === "connected" ? "connected" : state === "offline" ? "offline" : state === "not_configured" ? "not_configured" : "needs_look");
    function pickPrinter() {
      loadBox.hidden = false;
      return fill(loadBox, SW.t("nav_printers"), async () => {
        const { printers } = await api("printers");
        const head = h("h4", { class: "spools__step", textContent: SW.t("spool_sheet_load_which_printer") });
        if (!printers.length) return [head, h("p", { class: "muted", textContent: SW.t("spool_load_no_printers") }), stepFoot(closeLoad)];
        return [head, h("ul", { class: "spools__rows" }, printers.map((p) => pickRow([h("span", { class: "spools__row-text" }, h("b", { textContent: p.name || p.id })),
          SW.status(wordOf(p.state), { small: true })], () => pickSlot(p)))), stepFoot(closeLoad)];
      }, { items: 2 });
    }
    function pickSlot(p) {
      return fill(loadBox, SW.t("nav_printers"), async () => {
        const r = await api(`printers/${enc(p.id)}/state`);
        const slots = ((r.status || {}).ams || []).flatMap((u) => u.slots || []);
        const head = h("h4", { class: "spools__step", textContent: SW.t("spool_load_which_slot", { printer: p.name || p.id }) });
        if (!slots.length) return [head, h("p", { class: "muted", textContent: SW.t("spool_load_no_slots") }), stepFoot(pickPrinter)];
        return [head, h("ul", { class: "spools__rows" }, slots.map((sl) => pickRow([SW.swatch(hexOf(sl.color_hex)),
          h("span", { class: "spools__row-text" }, h("b", { class: "mono", textContent: sl.label }),
            h("span", { class: "muted", textContent: sl.spool ? [sl.spool.name, sl.spool.remaining_weight != null ? SW.t("common_grams", { grams: grams(sl.spool.remaining_weight) }) : null].filter(Boolean).join(" · ")
              : (sl.type || SW.t("spool_sheet_slot_empty")) }))], () => plan(p, sl)))), stepFoot(pickPrinter)];
      }, { items: 2 });
    }
    function plan(p, sl) {
      const line = resultLine(), go = SW.btn(SW.t("common_load"), { cls: "btn--primary", run: (e) => send(false, e.currentTarget) });
      loadBox.replaceChildren(h("h4", { class: "spools__step", textContent: SW.t("spool_load_title", { slot: sl.label }) }), line, go, stepFoot(() => pickSlot(p)));
      disabled(go, SW.t("spool_load_working_out"));
      async function send(dry, button) {
        await act(line, SW.t(dry ? "spool_load_working_out" : "common_load_wait"), async () => {
          let r;
          try { r = await api(`printers/${enc(p.id)}/slots/${enc(sl.label)}/load`, { body: { spool_id: id, dry_run: dry } }); }
          catch (e) { if (dry) disabled(go, SW.t("spool_load_see_above")); throw e; }
          const back = (r.moved_back || []).filter((m) => m.id !== id)
            .map((m) => SW.t("spool_load_plan_goes_back", { id: m.id ?? "?", slot: sl.label, location: m.location || SW.t("spool_load_previous_place") }));
          if (dry) {
            const nozzle = r.nozzle_assumed ? SW.t("spool_load_plan_nozzle_assumed", { mm: r.nozzle_mm ?? 0.4 }) : (r.nozzle_mm ? SW.t("spool_load_plan_nozzle", { mm: r.nozzle_mm }) : "");
            disabled(go, (r.problems || []).length ? SW.t("spool_load_see_above") : null);
            return { kind: (r.problems || []).length ? "warn" : "ok", text: h("span", {}, ...lines([SW.t("spool_load_plan", { spool: view ? nameOf(view) : SW.t("spool_title", { id }), slot: sl.label }),
              SW.t("spool_load_plan_preset", { preset: (r.preset && r.preset.name) || SW.t("common_value_none") }), nozzle, ...back, ...(r.problems || [])].filter(Boolean))) };
          }
          closeLoad(); changed = true; refresh();
          SW.toast(SW.t(r.confirmed ? "spool_load_loaded_toast" : "spool_load_sent_toast", { slot: sl.label }));
          SW.result(actAns, "ok", h("span", {}, ...lines([SW.t(r.confirmed ? "spool_load_loaded_toast" : "spool_load_sent_line", { slot: sl.label }), ...back, ...(r.problems || [])])));
          return null;
        }, { button });
      }
      send(true);                                              // the plan first: nothing is sent until Load
    }
    const other = EDIT || PRINTERS ? part(SW.t("spool_sheet_other_actions"),
      h("div", { class: "spools__buttons" }, EDIT ? weightBtn : null, EDIT ? moveBtn : null, PRINTERS ? loadBtn : null), weightForm, loadBox,
      EDIT ? h("div", { class: "spools__danger" }, emptyBtn) : null, actAns) : null;
    if (other) other.hidden = true;                            // until the spool is read: its state decides which actions can be pressed

    const dlg = SW.sheet({ title: SW.t("spool_title", { id }), body: h("div", { class: "spools__sheet" }, sum, openPart, other), onClose: () => {
      if (sheet && sheet.dlg === dlg) sheet = null;            // a sheet that was replaced by another one closes after the new one is set
      if (changed) { changed = false; if (shown && asked) find(lastQ); }
      if (shellView) shellView.paint(false);
    } });
    if (how === "push") history.pushState({ sheet: true }, "", `#spools/${id}`);
    const rec = track(dlg, "address", how === "direct");
    sheet = { id, dlg, rec, tag(t, fresh, key) {
      paintTag(t);
      if (!fresh) return;
      if (key !== spentKey && onScale(t) && !weightTyped) {   // a new station tap: that spool is on the scale (04 5.2)
        weight._control.value = t.scale.grams; weight._hint.textContent = SW.t("spools_scale_filled", { seconds: t.scale.age_seconds });
      }
      outOfDate(false);
    } };
    paintTag(lastTag);
    if (lastTag && onScale(lastTag)) { weight._control.value = lastTag.scale.grams; weight._hint.textContent = SW.t("spools_scale_filled", { seconds: lastTag.scale.age_seconds }); }
    SW.openModal(dlg, opener);
    if (shellView) shellView.paint(false);
    refresh();
  }

  const el = h("section", { class: "hidden" }, h("div", { class: "spools" },
    h("p", { class: "muted", textContent: SW.t("spools_intro") }),
    group(SW.t("spools_last_tag"), tagBody, tagLine),
    h("div", { class: "spools__find" }, searchField, sealedBox, findLine), resultsBox,
    h("datalist", { id: "spools-locs" }, ...[...new Set([...PICKS, ...LOCATIONS])].map((l) => h("option", { value: l })))));
  return {
    el,
    enter() {
      shown = true;
      if (!tagLoad && tagAt == null && !tagFirst.dataset.state) {   // the first time: a skeleton and the line, until the first answer
        tagLoad = SW.loading(tagBody, { thing: SW.t("spools_last_tag"), items: 1 });
        const run = resultLine(); SW.result(run, "run", SW.t("spools_last_tag_loading")); tagBody.append(run);
      }
      if (!document.hidden) startPoll();
      find(asked ? lastQ : "");
    },
    leave() { shown = false; stopPoll(); closeSheet(); },
    address(more, initial) {                                   // #spools or #spools/<id> (04 2.4)
      const id = /^\d+$/.test(more) ? Number(more) : null;
      if (id == null) closeSheet(); else openSheet(id, null, initial ? "direct" : "entry");
    },
    sheetTitle: () => (sheet ? SW.t("spool_title", { id: sheet.id }) : null),
  };
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
