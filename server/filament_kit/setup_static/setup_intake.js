// The Recently added section (03 6; 02 6.1 to 6.3, 7.2, 7.6, 7.9, 7.10): the newest spool additions with the photos that were
// taken, to check them, correct a record by hand or with the Label Reader, and undo a correction. Loaded after setup.js;
// everything from the Hub goes in through textContent, as there. The list is `#recent`, one record `#recent/<id>`.
//
// The rule for the Label Reader's answers (one rule, no counters of changes): an answer, pending or shown, is valid for as long as the
// data of the record it was asked about is unchanged. Every write (a Save, an Accept, an Undo, a change of item) gets a send number,
// `view.sent`, when it is sent. An Ask is asked at the highest number sent so far. It is dropped, and says so once, when a write sent
// AFTER the Ask has SUCCEEDED (`view.maxOk` past it); a write sent before it never drops it (the Ask was of the changed record), and a
// write that failed changed nothing, so it drops nothing. A shown suggestion goes by the same test. An answer that arrives while a
// write sent after the Ask is still out waits (`view.held`) for that write's result, then is shown or dropped by the rule. The Hub's
// reply to an Ask carries no revision, so this is the client's side of it; Accept still asks the Hub, whose refusal of an answer it no
// longer holds (409 stale, 404 not found) is shown in words and takes the suggestion off the page (FA-168 is the Hub's side).
"use strict";

// [field, catalogue key of its name, group, name of its form field, kind]: the order is the order of the rows in a group
const REC_FIELDS = [
  ["vendor", "common_field_brand", "identity", "vendor", "brand"], ["name", "common_field_name", "identity", "name", "name"],
  ["material", "common_field_material", "identity", "material", "material"], ["color_hex", "common_field_colour", "identity", "colour", "colour"],
  ["net", "common_field_net_weight", "weights", "net_weight", "g"], ["tare", "common_field_empty_spool_weight", "weights", "empty_weight", "g"],
  ["density", "common_field_density", "weights", "density", "density"],
  ["nozzle", "common_field_nozzle", "temps", "nozzle", "c"], ["bed", "common_field_bed", "temps", "bed", "c"],
  ["nozzle_range", "common_field_nozzle_range", "temps", "nozzle_range", "range"], ["bed_range", "common_field_bed_range", "temps", "bed_range", "range"],
  ["price_per_kg", "common_field_price_per_kg", "other", "price_per_kg", "price"], ["line", "common_field_line", "other", "line", "line"]];
const REC_GROUPS = [["identity", "common_group_identity"], ["weights", "recent_group_weights"], ["temps", "common_group_temperatures"], ["other", "common_group_other"]];
const REC_UNIT = { g: "unit_g", density: "unit_g_cm3", c: "unit_c", range: "unit_c" };
const REC_STATE = { detected: "as_detected", revised_ai: "revised_ai", edited: "edited" };     // the status badge words
const REC_LEVELS = ["low", "not_rated", "medium", "not_on_label"];                           // the lowest level first (02 7.2)
const REC_PAGE = 50;
const REC_FIELD = Object.fromEntries(REC_FIELDS.map((f) => [f[0], f]));
let recentFilter = "all";           // the list's filter: all, or the records to check
let recentAt = null;                // the record open (its results are cleared when another opens)
let recentView = null;              // what belongs to the record open (the item, an edit in progress, the note, a suggestion): it lasts while the page redraws
const recFlight = new Set();        // the writes on their way, by path: one press is one request
// the data of the record changed (a write succeeded, or the item changed): a suggestion asked of the earlier data goes
const recDataChanged = (view, n) => { view.maxOk = Math.max(view.maxOk || 0, n); if (view.proposal && n > view.proposal._asked) view.proposal = null; };
// an answer that arrives: held while a write sent after its Ask is out, else shown or dropped by the rule at the top
function recAnswer(view, box, p, asked) {
  if ([...(view.out || [])].some((n) => n > asked)) { view.held = { p, asked, box }; return; }
  if (box.dataset.state === "run" || box.dataset.state === "neutral") SW.result(box, null);      // the "Asking…" or "Still working" is over; a result that came since stays
  if (recentView !== view || (view.maxOk || 0) > asked) {      // the data it was asked about changed, or the record was left: said once, where the record is now
    const now = recentView && recentView.id === view.id ? recentView : view;
    if (now.dropped) now.dropped();
    return;
  }
  p._asked = asked;
  view.proposal = p;
  if (view.late) view.late(p);           // into the card as it is drawn now; the record is not drawn again, so an open form keeps what was typed
}
function recRelease(view) {
  const h = view.held;
  if (!h || [...view.out].some((n) => n > h.asked)) return;
  view.held = null;
  recAnswer(view, h.box, h.p, h.asked);
}
const recentMedia = new Promise((done) => {          // the thumbnails' look (components-media.css): only this section needs it
  const css = h("link", { rel: "stylesheet", href: "/setup/shared/components-media.css" });
  css.addEventListener("load", done); css.addEventListener("error", done);
  document.head.append(css);
});

const recTime = (at) => (at || "").slice(0, 16).replace("T", " ");
const recSize = (n) => SW.t(n >= 1048576 ? "recent_size_mb" : "recent_size_kb", { value: n >= 1048576 ? (n / 1048576).toFixed(1) : Math.ceil(n / 1024) });
const recPhoto = (id, n) => "/setup/api/" + histPath(id, `photos/${n}`);
const histPath = (id, what) => `intake/history/${encodeURIComponent(id)}${what ? "/" + what : ""}`;
const recLabel = (k) => SW.t(REC_FIELD[k] ? REC_FIELD[k][1] : k);
const recNames = (spools) => [...new Set(spools.map((s) => `${s.vendor} ${s.name}`))].join(", ");
// the Hub writes phone, web and station: a phone or web addition with a photo is "From a phone photo", one without is typed in
const REC_FROM = { phone: "recent_source_phone", web: "recent_source_phone", station: "recent_source_station" };
const recByHand = (r) => REC_FROM[r.source] !== "recent_source_station" && !r.photos;
const recSource = (r) => (recByHand(r) || r.source === "cli" ? SW.t("recent_source_hand") : REC_FROM[r.source] ? SW.t(REC_FROM[r.source]) : r.source);
const recSpools = (ids) => SW.t("recent_spool_label", { count: ids.length, ids: ids.join(", ") });
const recToCheck = (r) => !!(r.confidence && (r.confidence.low.length || r.confidence.medium.length));
const recAddress = () => {
  const m = location.hash.slice(1).match(/^recent(?:\/([^/?]+))?(?:\?(.*))?$/);
  return { id: m && m[1] ? decodeURIComponent(m[1]) : null, page: Math.max(1, Number(new URLSearchParams((m && m[2]) || "").get("page")) || 1) };
};
// a value as it is read: null when the record has none; the colour with its #, a unit after a number
function recShow(kind, v) {
  if (v == null || v === "") return null;
  if (kind === "colour") return "#" + String(v).replace(/^#/, "").toUpperCase();
  return REC_UNIT[kind] ? SW.t("recent_value_unit", { value: v, unit: SW.t(REC_UNIT[kind]) }) : String(v);
}
// what a field is typed with and what is sent: {value} or {error}; an empty optional field is sent empty
function recParse(kind, text) {
  const t = text.trim(), n = Number(t.replace(",", "."));
  if (kind === "brand" || kind === "name" || kind === "material") return t ? { value: t } : { error: SW.t({ brand: "recent_error_brand", name: "common_error_name", material: "recent_error_material" }[kind]) };
  if (!t) return { value: null };
  if (kind === "colour") return /^#?[0-9a-f]{6}$/i.test(t) ? { value: t.replace(/^#/, "").toUpperCase() } : { error: SW.t("recent_error_colour") };
  if (kind === "range") return /^\d{2,3}\s*[-–]\s*\d{2,3}$/.test(t) ? { value: t } : { error: SW.t("common_error_range") };
  if (kind === "line") return { value: t };
  if (kind === "c") return Number.isInteger(n) && n > 0 && n < 500 ? { value: n } : { error: SW.t(n >= 500 ? "recent_error_degrees_max" : "add_review_error_degrees") };
  if (Number.isFinite(n) && n > 0) return { value: n };
  return { error: SW.t({ g: "common_error_grams", density: "add_review_error_density", price: "recent_error_price" }[kind]) };
}
// the item's reading: {levels: field -> level, filled, sure} from the read the Hub kept (a high that was never measured is no level)
function recReading(rec, item) {
  const read = rec.read && Array.isArray(rec.read.items) ? rec.read.items[item] : null;
  if (!read || !read.confidence_levels) return null;
  const rated = rec.read.confidence_rated !== false;
  const levels = {};
  for (const [k, v] of Object.entries(read.confidence_levels)) levels[k] = v === "high" && !rated ? null : v;
  return { levels, rated, filled: read.confidence_filled || [], sure: typeof read.confidence === "number" ? Math.round(read.confidence * 100) : null };
}
// a fields's mark (02 7.2): none for a high or unrated one, and none once a revision changed the field
function recMark(reading, field, changed) {
  const lv = reading && !changed.has(field) ? reading.levels[field] : null;
  if (!lv || lv === "high") return null;
  if (lv === "medium" && reading.filled.includes(field)) return SW.status("medium", { small: true, text: SW.t("recent_mark_filled") });
  return SW.status(lv, { small: true });
}
const recChanged = (rec) => new Set((rec.revisions || []).filter((v) => !v.undone).flatMap((v) => v.changes.map((c) => c.field)));

// ----- the section -----
function intakeTab() {
  const body = h("div"), at = recAddress();
  later(readRegion(body, "recent", async () => {
    await recentMedia;                               // the thumbnails' look is in before the section is drawn
    const d = await api("intake/history");
    if (!at.id) return { d };
    try { return { d, rec: await api(histPath(at.id)) }; } catch (e) { if (e.status === 404) return { d, gone: true }; throw e; }
  }, (r) => { if (at.id) recordPage(body, r.d, r.rec, at.id); else listPage(body, r.d, at.page); }));
  return [body];
}

// ----- the list (03 6.2) -----
function listPage(body, d, page) {
  recentAt = null;
  recentView = null;
  const all = d.records, conf = all.some((r) => r.confidence !== undefined), check = all.filter(recToCheck).length;
  if (!conf) recentFilter = "all";
  const settings = h("a", { class: "btn btn--ghost", href: "#settings/label-reader" }, SW.t("recent_meta_change"));
  const meta = h("p", { class: "page-head__meta" },
    h("span", {}, d.keep ? SW.t("recent_meta_kept", { count: d.keep, size: recSize(d.photo_bytes) }) : SW.t("recent_keep_none")), settings,
    h("span", {}, SW.t("common_label_reader"), " ", SW.status(d.ai ? "on" : "off", { small: true })));
  const filter = conf && all.length ? SW.segmented({ legend: SW.t("recent_col_filament"), legendSr: true, name: "recent-filter", value: recentFilter,
    options: [{ value: "all", label: SW.t("recent_filter_all", { count: all.length }) }, { value: "check", label: SW.t("recent_filter_check", { count: check }) }] }) : null;
  const list = h("div");
  if (filter) filter.addEventListener("change", (e) => { recentFilter = e.target.value; paint(); });
  const paint = () => {
    const recs = recentFilter === "check" ? all.filter(recToCheck) : all;
    if (!all.length) { fill(list, SW.empty({ icon: "spool", title: SW.t("recent_empty_title"), text: SW.t("recent_empty_text") })); return; }
    const pages = Math.max(1, Math.ceil(recs.length / REC_PAGE)), now = Math.min(page, pages), shown = recs.slice((now - 1) * REC_PAGE, now * REC_PAGE);
    const table = recCollection(shown, recs.length > REC_PAGE ? { total: recs.length, first: (now - 1) * REC_PAGE } : null);
    fill(list, table, pages > 1 ? SW.pager({ from: (now - 1) * REC_PAGE + 1, to: (now - 1) * REC_PAGE + shown.length, total: recs.length, page: now, pages,
      go: (p) => { location.hash = p > 1 ? "#recent?page=" + p : "#recent"; } }) : null);
  };
  fill(body, meta, filter ? h("div", { class: "coll__toolbar" }, filter) : null, list);
  paint();
  if (page > 1) { const a = list.querySelector(".coll__title"); if (a) a.focus({ preventScroll: true }); }      // another page: its first title (02 6.1)
}

function recCollection(recs, paged) {
  const head = (col, kids, o = {}) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": o.prio, "aria-sort": o.sort }, kids);
  const sorter = (col, name) => (paged ? name : h("button", { class: "coll__sort", type: "button", "data-sort": col }, name, SW.icon("chevron", "icon--s")));
  const el = h("div", { class: "coll coll--recent", role: "table", "aria-labelledby": "recent-title" },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
      head("visual", SW.t("recent_col_photo")),
      head("title", sorter("title", SW.t("recent_col_filament"))),
      head("added", sorter("added", SW.t("recent_col_added")), { prio: 2 }),
      head("status", SW.t("common_field_state")),
      head("spool", SW.t("recent_col_spool"), { prio: 3 }),
      head("confidence", SW.t("recent_col_confidence"), { prio: 2 }),
      head("go", h("span", { class: "sr" }, SW.t("a11y_action_open"))))),
    ...recs.map(recRow));
  el.setAttribute("aria-label", SW.t("nav_recently_added"));
  el.removeAttribute("aria-labelledby");
  SW.collection(el, paged ? { name: "recent", ...paged } : { name: "recent", sort: "added:descending" });
  return el;
}

function recThumb(r) {
  if (!r.photos) return h("span", { class: "thumb thumb--none" }, SW.icon("camera", "icon--s"), h("span", { class: "sr" }, SW.t("photo_none")));
  return h("span", { class: "thumb" }, h("img", { class: "thumb__img", src: recPhoto(r.id, 1), alt: "", width: 44, height: 44, loading: "lazy" }),
    r.photos > 1 ? h("span", { class: "thumb__count mono", "aria-hidden": "true" }, r.photos) : null);
}

function recRow(r) {
  const cell = (col, key, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": { added: 2, spool: 3, confidence: 2 }[col] || 1,
    "data-sort": col === "added" ? r.at : null }, key ? h("span", { class: "coll__key", "aria-hidden": "true" }, key) : null, ...kids);
  const ids = r.spools.map((s) => s.spool_id), names = recNames(r.spools);
  return h("div", { class: "coll__item", role: "rowgroup", "data-id": r.id }, h("div", { class: "coll__row", role: "row" },
    cell("visual", null, recThumb(r)),
    cell("title", null,
      h("a", { class: "coll__title" + (names ? "" : " muted"), href: "#recent/" + encodeURIComponent(r.id) }, names || SW.t("recent_no_spools")),
      r.spools.length > 1 ? [" ", h("span", { class: "mono" }, SW.t("recent_times", { count: r.spools.length }))] : null,
      h("span", { class: "coll__sub muted" }, recSource(r))),
    cell("added", SW.t("recent_col_added"), h("span", { class: "mono" }, recTime(r.at))),
    cell("status", null, SW.status(REC_STATE[r.state] || "as_detected", { text: REC_STATE[r.state] ? null : r.state })),
    cell("spool", SW.t("recent_col_spool"), ids.length ? h("span", { class: "mono" }, recSpools(ids)) : h("span", { class: "muted" }, SW.t("common_none"))),
    cell("confidence", SW.t("recent_col_confidence"), recSummary(r)),
    cell("go", null, SW.icon("chevron", "icon--s"))));
}

// the record's confidence in one line (02 7.2 "Record summary")
function recSummary(r) {
  const c = r.confidence;
  if (c === undefined) return null;
  if (c === null) return h("span", { class: "muted" }, SW.t("confidence_not_read_short"));
  if (c.level === "high") return SW.status("high", { small: true });
  const parts = REC_LEVELS.map((lv) => {
    const fields = (c[lv] || []).map(recLabel).join(", ");
    if (lv === "not_rated") return c.level === "not_rated" || r.confidence_rated === false ? h("span", { class: "muted" }, SW.t("recent_confidence_not_rated")) : null;
    if (!fields) return null;
    return SW.status(lv, { small: true, text: SW.t("confidence_summary_" + lv, { fields }) });
  }).filter(Boolean);
  return h("p", { class: "confidence__summary" }, parts.flatMap((p, i) => (i ? [" · ", p] : [p])));
}

// ----- one record (03 6.3) -----
function recordPage(body, d, rec, id) {
  if (recentAt !== id) {                             // another record: the results of the last one go
    for (const [k, b] of Object.entries(boxes)) if (k.startsWith("record:") && b.dataset.state) SW.result(b, null);
    recentAt = id;
  }
  const tab = (name) => { document.title = SW.t("shell_title", { page: `${name} · ${SW.t("nav_recently_added")}`, hub: S.server_name }); };   // each record has its own title (07 SR-2)
  if (!rec) { tab(SW.t("recent_record_title")); fill(body, recGone(d)); return; }
  tab(recNames(rec.spools) || SW.t("recent_no_spools"));
  const view = recentView && recentView.id === id ? Object.assign(recentView, { d }) : (recentView = { d, id, item: null, editing: false, proposal: null, note: "" });
  const host = h("div", { "data-key": "record:" + id });      // a typed value is carried to a redraw of this record only, never to another one
  fill(body, host);
  recDraw(host, view, rec, true);
}

function recGone(d) {
  return h("div", { class: "error-state" }, h("span", { class: "error-state__disc", "aria-hidden": "true" }, SW.shape("s-octagon")),
    h("h2", { class: "error-state__title", tabindex: "-1" }, SW.t("recent_not_found", { keep: d.keep })),
    h("div", { class: "actions" }, h("a", { class: "btn btn--primary", href: "#recent" }, SW.t("recent_back_to_list"))));
}

// draws the record from its reply; what is in the page that a change leaves (the choice of item, the note typed) is kept by view
function recDraw(host, view, rec, first) {
  const items = rec.saved || [], box = (k) => boxFor(`record:${view.id}:${k}`);
  if (!items.some((s) => s.item === view.item)) view.item = items.length ? items[0].item : null;
  const s = items.find((x) => x.item === view.item) || null;
  const redraw = (r) => recDraw(host, view, r, false);
  view.rec = rec;
  const names = recNames(rec.spools), ids = rec.spools.map((x) => x.spool_id);
  const at = view.d.records.findIndex((r) => r.id === view.id);
  const go = (to) => { location.hash = "#recent/" + encodeURIComponent(to.id); };
  const newer = at > 0 ? view.d.records[at - 1] : null, older = at >= 0 && at < view.d.records.length - 1 ? view.d.records[at + 1] : null;
  const step = (name, icon, other, cls) => { const b = SW.iconBtn(icon, SW.t(name), { cls, run: () => go(other) }); b.disabled = !other; return b; };
  const title = h("h2", { class: "detail__title", tabindex: "-1" }, names || SW.t("recent_no_spools"),
    rec.spools.length > 1 ? [" ", h("span", { class: "mono" }, SW.t("recent_times", { count: rec.spools.length }))] : null);
  const head = h("header", { class: "recent__head" },
    h("p", { class: "page-head__crumbs" }, h("a", { href: "#recent" }, SW.t("nav_recently_added")), " / ", ids.length ? recSpools(ids) : SW.t("recent_no_spools")),
    h("div", { class: "recent__bar" }, title, h("div", { class: "actions" },
      h("a", { class: "btn btn--ghost", href: "#recent" }, SW.t("common_back")),
      step("detail_newer", "chevron", newer, "recent__newer"), step("detail_older", "chevron", older, "recent__older"))),
    h("p", { class: "page-head__meta" }, h("span", { class: "mono" }, recTime(rec.at)), h("span", {}, recSource(rec)),
      SW.status(REC_STATE[rec.state] || "as_detected", { small: true, text: REC_STATE[rec.state] ? null : rec.state }),
      h("span", {}, ids.length ? recSpools(ids) : SW.t("recent_no_spools"))));
  const side = h("div", { class: "recent__side" }, recPhotos(rec, view.id, names), recRevisions(rec, view, box("undo"), redraw), recFacts(rec, s, ids));
  const main = h("div", { class: "recent__main" },
    items.length > 1 ? recItems(items, view, () => recDraw(host, view, rec, false)) : null,
    recFields(rec, s, view, box("fields"), redraw), recAsk(rec, s, view, box("ask"), redraw));
  const had = host.contains(document.activeElement);
  fill(host, head, h("div", { class: "recent__grid" }, main, side));
  if (first && !had && (document.activeElement === document.body || document.activeElement === pageTitle)) title.focus({ preventScroll: true });
}

// "Item 1", "Item 2": only when the record has several items; a change applies to all the spools of the item
function recItems(items, view, again) {
  const s = items.find((x) => x.item === view.item);
  const seg = SW.segmented({ legend: SW.t("recent_items_legend"), legendSr: true, name: "recent-item", value: String(view.item),
    options: items.map((x) => ({ value: String(x.item), label: SW.t("recent_item", { number: x.item + 1 }) })) });
  seg.addEventListener("change", (e) => { view.item = Number(e.target.value); view.editing = false; recDataChanged(view, view.sent = (view.sent || 0) + 1); again(); });
  return h("div", { class: "recent__items" }, seg, s ? h("p", { class: "muted" }, SW.t("recent_item_line", { ids: s.spool_ids.join(", "), filament: s.filament_id })) : null);
}

// the photos and the viewer (02 7.6)
function recPhotos(rec, id, name) {
  const n = rec.photos;
  const open = (i, opener) => recViewer(id, n, i, name, opener);
  return h("section", { class: "card", "aria-labelledby": "recent-photos" },
    h("h3", { class: "detail__heading", id: "recent-photos" }, SW.t("recent_photos_title", { count: n })),
    n ? h("div", { class: "recent__photos" }, Array.from({ length: n }, (_, i) => {
      const b = h("button", { class: "thumb thumb--m", type: "button", "aria-label": SW.t("photo_enlarge", { number: i + 1, total: n }),
        on: { click: () => open(i, b) } }, h("img", { class: "thumb__img", src: recPhoto(id, i + 1), alt: "", width: 96, height: 96, loading: "lazy" }));
      b.firstChild.addEventListener("error", () => b.replaceChildren(SW.icon("warning", "icon--s"), h("span", { class: "sr" }, SW.t("photo_load_failed"))));
      return b;
    })) : h("p", { class: "muted" }, SW.t(recByHand(rec) ? "recent_no_photo_hand" : "recent_photos_none")));
}
function recViewer(id, n, start, name, opener) {
  let i = start, dlg = null;
  const img = h("img", { class: "recent__viewer-img" });
  const again = SW.btn(SW.t("common_try_again"), { run: () => show(i) });
  const area = h("div", { class: "recent__viewer" }, img, h("p", { class: "recent__viewer-error" }, SW.icon("warning", "icon--s"), SW.t("photo_load_failed"), " ", again));
  const down = h("a", { class: "btn", download: "" }, SW.icon("download", "icon--s"), SW.t("common_download"));
  const prev = SW.btn(SW.t("common_previous"), { run: () => show(i - 1) }), next = SW.btn(SW.t("common_next"), { run: () => show(i + 1) });
  const show = (to) => {
    if (to < 0 || to >= n) return;
    i = to;
    img.src = down.href = recPhoto(id, i + 1);
    img.alt = SW.t("photo_viewer_alt", { number: i + 1, total: n, name });
    delete area.dataset.state;
    prev.disabled = i === 0; next.disabled = i === n - 1;
    if (dlg) { dlg.querySelector(".dialog__title").textContent = SW.t("photo_position", { number: i + 1, total: n }); SW.announce(SW.t("photo_position", { number: i + 1, total: n })); }
  };
  img.addEventListener("error", () => { area.dataset.state = "failed"; img.alt = SW.t("photo_load_failed"); });
  SW.ask({ kind: "info", wide: true, title: SW.t("photo_position", { number: i + 1, total: n }), body: area, extra: [prev, next, down], opener,
    open: (d, o) => {
      dlg = d; d.classList.add("viewer");
      d.addEventListener("keydown", (e) => {
        const to = { ArrowLeft: i - 1, ArrowRight: i + 1, Home: 0, End: n - 1 }[e.key];
        if (to != null) { e.preventDefault(); show(to); }
      });
      show(i);
      SW.openModal(d, o);
    } });
}

// ----- the fields (03 6.3 "Fields") -----
function recFields(rec, s, view, box, redraw) {
  const reading = s ? recReading(rec, s.item) : null, changed = recChanged(rec);
  const group = (key, name, rows) => h("div", { class: "recent__group" }, h("h4", { class: "kv__heading" }, SW.t(name)), rows);
  const card = (actions, ...kids) => h("section", { class: "card", "aria-labelledby": "recent-fields" },
    h("div", { class: "recent__cardhead" }, h("h3", { class: "detail__heading", id: "recent-fields" }, SW.t("recent_fields_title")), actions), ...kids);
  if (!s) return card(null, h("p", { class: "muted" }, SW.t("recent_edit_gone")), box);
  const note = reading ? h("p", { class: "muted" }, SW.t(reading.rated ? "confidence_note" : "recent_confidence_note_unrated")) : null;
  if (!view.editing) {
    const edit = SW.btn(SW.t("recent_edit"), { icon: "pencil", run: () => coded(box, async () => { view.editing = true; redraw(rec); }) });
    const rows = (g) => h("dl", { class: "kv" }, REC_FIELDS.filter((f) => f[2] === g).map(([k, name, , , kind]) => {
      const text = recShow(kind, s.values[k]), mark = recMark(reading, k, changed);
      return h("div", { class: "kv__row" }, h("dt", { class: "kv__key" }, SW.t(name)),
        h("dd", { class: "kv__value" },
          kind === "colour" && text ? [SW.swatch(s.values[k]), " "] : null,
          text == null ? h("span", { class: "muted" }, SW.t("common_field_empty_value")) : h("span", { class: kind === "brand" || kind === "name" || kind === "material" || kind === "line" ? "" : "mono" }, text),
          mark ? [" ", mark] : null));
    }));
    return card(edit, note, h("div", { class: "kv kv--groups" }, REC_GROUPS.map(([g, name]) => group(g, name, rows(g)))), box);
  }
  // editing: the same rows as fields; only the changed ones are sent (one request = one revision)
  const fields = {};
  const form = h("form", { class: "recent__form", novalidate: true, on: { submit: (e) => { e.preventDefault(); save(); } } },
    h("div", { class: "kv kv--groups" }, REC_GROUPS.map(([g, name]) => group(g, name, REC_FIELDS.filter((f) => f[2] === g).map(([k, label, , formName, kind]) => {
      const v = s.values[k], text = v == null ? "" : kind === "colour" ? recShow("colour", v) : String(v);
      const required = kind === "brand" || kind === "name" || kind === "material";
      const f = fields[k] = SW.field({ type: ["g", "density", "price"].includes(kind) ? "number" : "text", decimal: kind === "density" || kind === "price" || kind === "g",
        label: SW.t(label), name: formName, value: text, unit: REC_UNIT[kind] ? SW.t(REC_UNIT[kind]) : null, mono: !["brand", "name", "material", "line"].includes(kind),
        attrs: { ...(required ? {} : { "aria-required": "false" }), ...(kind === "colour" ? { autocapitalize: "off", spellcheck: "false" } : {}) },
        hint: kind === "colour" ? SW.t("common_field_colour_hint") : null, check: (x) => recParse(kind, x).error || null });
      f._was = text;
      const mark = recMark(reading, k, changed);
      if (mark) f.querySelector(".field__label").append(" ", mark);
      return f;
    })))),
    h("div", { class: "recent__foot" }, box, h("div", { class: "actions" },
      SW.btn(SW.t("common_cancel"), { run: () => { view.editing = false; SW.result(box, null); redraw(rec); } }),
      SW.btn(SW.t("common_save_changes"), { type: "submit", cls: "btn--primary" }))));
  const save = () => {
    const values = {}, bad = [];
    for (const [k, , , , kind] of REC_FIELDS) {
      const f = fields[k], now = f._control.value;
      if (now.trim() === f._was.trim()) { SW.fieldError(f, null); continue; }
      const p = recParse(kind, now);
      SW.fieldError(f, p.error || null);
      if (p.error) bad.push(f); else values[k] = p.value;
    }
    if (bad.length) { bad[0]._control.focus(); return; }
    if (!Object.keys(values).length) { say(box, SW.t("common_nothing_changed"), "neutral"); return; }
    recPost(box, histPath(view.id, "apply"), { item: s.item, values }, (r) => {
      view.editing = false;
      redraw(r);
      say(box, recSaved(r, Object.keys(values)), true);
    }, view);
  };
  return card(null, note, form);
}

// "Saved 2 changes: Empty spool weight, Nozzle." and the filament sentences of the Hub (03 6.4)
function recSaved(rec, sent) {
  const f = recChanged1(rec, sent);      // what the revision changed (an edit that joins a filament changes more than was sent)
  return [SW.t("recent_saved", { count: f.length, fields: f.map(recLabel).join(", ") }), ...recFilament(rec)].join(" ");
}
// the fields the newest revision changed (once each); `sent` when the Hub names none
function recChanged1(rec, sent) {
  const v = (rec.revisions || [])[(rec.revisions || []).length - 1], f = [...new Set(((v && v.changes) || []).map((c) => c.field))];
  return f.length ? f : sent || [];
}
function recFilament(rec) {
  const v = (rec.revisions || [])[(rec.revisions || []).length - 1], fl = (v && v.filaments) || {}, out = [];
  if (fl.to != null && fl.to !== fl.from) out.push(SW.t(fl.created ? "recent_result_filament_new" : "recent_now_use", { filament: fl.to, id: fl.to }));
  if (fl.orphaned && fl.orphaned.length) out.push(SW.t("recent_result_filament_empty", { ids: fl.orphaned.join(", ") }));
  return out;
}

// A change on this section: the setup code as every write, but no region redraw (change() would reload every region, which
// would close the record being edited); the record redraws itself from the answer.
function recPost(box, path, body, done, view, fail) {      // `view`: a write that changes the record (see the rule at the top); `fail(e)`: what a refusal also does
  if (recFlight.has(path)) return Promise.resolve();      // pressed again while the first is on its way
  recFlight.add(path);
  return coded(box, async () => {
    working(box, SW.t(path.endsWith("/revise") ? "changes_asking" : "common_saving"));
    let r, n = 0;
    if (view) { n = view.sent = (view.sent || 0) + 1; (view.out = view.out || new Set()).add(n); }      // sent: its number
    try { r = await api(path, { ...body, code: theCode() }); } catch (e) {
      if (e.locked) SW.result(box, null);
      if (e.data && (e.data.reason === "stale" || e.data.reason === "not_found") && body.proposal) e.message = SW.t("recent_answer_dropped");      // the Hub no longer holds the answer it was asked to accept
      if (fail) fail(e);
      if (e.data && e.data.reason === "no_photo") e.message = SW.t("recent_error_no_photo");      // 409: only the On this Hub engine, and no photo kept (03 6.4)
      throw e;
    } finally { if (view) view.out.delete(n); }
    if (view) recDataChanged(view, n);           // it succeeded: the data changed
    done(r);
  }).finally(() => { recFlight.delete(path); if (view) recRelease(view); });
}

// ----- ask the Label Reader, the suggestion (03 6.3) -----
function recAsk(rec, s, view, box, redraw) {
  const card = (...kids) => h("section", { class: "card", "aria-labelledby": "recent-ask" }, h("h3", { class: "detail__heading", id: "recent-ask" }, SW.t("recent_ask_title")), ...kids);
  if (!view.d.ai) return card(h("p", { class: "muted" }, SW.t("recent_reader_off")), h("div", { class: "actions" }, h("a", { class: "btn", href: "#features" }, SW.t("nav_features"))), box);
  if (!s) return null;
  const note = SW.field({ type: "textarea", id: "recent-ask-note", label: SW.t("recent_ask_label"), name: "note", placeholder: SW.t("recent_ask_placeholder"), hint: SW.t("recent_ask_hint"), max: 500,
    value: view.note || "" });
  const sug = h("div", { class: "recent__suggestion", role: "status" });
  const ask = SW.btn(SW.t("recent_ask_button"), { run: () => {
    if (!note._control.value.trim()) { SW.fieldError(note, SW.t("recent_error_note")); note._control.focus(); return; }
    SW.fieldError(note, null);
    if (recFlight.has(histPath(view.id, "revise"))) { say(box, SW.t("common_busy_wait"), "neutral"); return; }      // one question at a time: the note shown is not sent
    view.note = note._control.value;
    view.held = null;                        // an older answer still held is out of date by this newer question: it is never shown after it
    const asked = view.sent || 0;            // asked after every write sent so far
    recPost(box, histPath(view.id, "revise"), { item: s.item, note: note._control.value }, (p) => recAnswer(view, box, p, asked));
  } });
  note._control.addEventListener("change", () => { view.note = note._control.value; });
  const showProposal = (p, focus) => {
    if (!p.changes.length) { fill(sug); say(box, SW.t("changes_none"), "neutral"); return; }
    const title = h("h4", { class: "changes__title", id: "recent-suggest", tabindex: "-1" }, SW.t("recent_suggest_title", { count: p.changes.length, engine: recEngine(p) }));
    const list = h("ul", { class: "changes__list" }, p.changes.map((k) => recChange(k, p.before[k], p.after[k])));
    const accept = SW.btn(SW.t("common_accept"), { cls: "btn--primary", run: () => {
      if (view.editing) return;
      SW.busy(accept, SW.t("common_accepting")); discard.disabled = true;
      recPost(box, histPath(view.id, "apply"), { proposal: p.proposal }, (r) => {
        redraw(r);
        say(box, [SW.t("changes_accepted", { count: recChanged1(r, p.changes).length, number: r.revisions.length }), ...recFilament(r)].join(" "), true);
        const t = document.getElementById("recent-ask-note"); if (t) t.focus();
      }, view, (e) => { if (e.data && (e.data.reason === "stale" || e.data.reason === "not_found")) { view.proposal = null; fill(sug); const t = document.getElementById("recent-ask-note"); if (t) t.focus(); } }).finally(() => { if (accept.isConnected) { SW.idle(accept); discard.disabled = false; } });
    } });
    const discard = SW.btn(SW.t("common_discard"), { run: () => { view.proposal = null; fill(sug); say(box, SW.t("recent_result_discarded"), "neutral"); } });
    fill(sug, h("section", { class: "changes", "aria-labelledby": "recent-suggest", "data-proposal": p.proposal }, title,
      p.no_photo ? h("p", { class: "muted" }, SW.t("recent_ask_no_photo")) : null,
      recReread(p), p.note ? h("p", { class: "muted" }, p.note) : null, list, h("p", { class: "changes__note" }, SW.t("changes_note")), h("div", { class: "actions" }, discard, accept)));
    if (view.editing) SW.disable(accept, SW.t("recent_accept_while_editing"));      // Accept writes the Hub's values over the form: what is typed is not lost without a word
    if (focus) accept.focus();           // when it arrives, not when the record is drawn again (02 7.9)
  };
  // an answer that comes later: it takes the focus only when the focus is not in another control (an edit form that is open keeps it)
  view.dropped = () => { if (!view.proposal) fill(sug, h("p", { class: "muted" }, SW.t("recent_answer_dropped"))); };      // into the card as it is drawn now; never over a suggestion that is shown
  view.late = (p) => { const a = document.activeElement; showProposal(p, !a || a === document.body || card_el.contains(a)); };
  const card_el = card(note, h("div", { class: "actions" }, ask), sug, box);
  if (view.proposal) showProposal(view.proposal);
  return card_el;
}
const recEngine = (p) => {
  const e = p.engine || {}, name = SW.t(e.reader === "local" || p.reader === "local" ? "settings_reader_badge_local" : "settings_reader_engine_cloud");
  return e.model ? SW.t("recent_engine", { engine: name, model: e.model }) : name;
};
const recReread = (p) => h("p", { class: "muted" }, SW.t(typeof p.confidence === "number" ? "recent_reread_sure" : "recent_reread", { engine: recEngine(p), percent: Math.round((p.confidence || 0) * 100) }));
// one change: the field, the old value struck through, the new one (02 7.9)
function recChange(k, before, after) {
  const f = REC_FIELD[k], kind = f ? f[4] : "line", old = recShow(kind, before), now = recShow(kind, after);
  return h("li", { class: "changes__item" }, h("span", { class: "changes__key" }, recLabel(k)),
    h("span", { class: "changes__old mono" }, h("span", { class: "sr" }, SW.t("changes_was")), old == null ? SW.t("common_field_empty_value") : old),
    h("span", { "aria-hidden": "true" }, SW.t("recent_arrow")),
    h("span", { class: "changes__new mono" }, h("span", { class: "sr" }, SW.t("changes_becomes")), now == null ? SW.t("common_field_empty_value") : now));
}

// ----- the revisions and undo (02 7.10) -----
function recRevisions(rec, view, box, redraw) {
  const revs = rec.revisions || [], live = revs.filter((v) => !v.undone), last = live[live.length - 1];
  const list = h("ol", { class: "revisions__list", reversed: true, "aria-labelledby": "recent-revisions" }, [...revs].reverse().map((v) => {
    const seen = new Set(), changes = (v.changes || []).filter((c) => !seen.has(c.field) && seen.add(c.field));
    // the filament left without spools: by the revision, or (once undone) by the undo, which puts the spools back
    const empty = v.filaments ? (v.undone ? v.filaments.orphaned_by_undo : v.filaments.orphaned) || [] : [];
    return h("li", { class: "revisions__item", "data-state": v.undone ? "undone" : null },
      h("p", {}, h("b", {}, SW.t("revision_title", { number: v.n })), ", ", h("span", { class: "mono" }, recTime(v.at)), ", ", SW.t(v.by === "ai" ? "revision_by_reader" : "revision_by_hand"),
        v.undone ? [" ", SW.t("recent_revision_undone")] : null),
      changes.length ? h("ul", { class: "changes changes--compact" }, changes.map((c) => recChange(c.field, c.old, c.new))) : null,
      v.note ? h("p", { class: "muted" }, SW.t("recent_revision_note", { note: v.note })) : null,
      v.device ? h("p", { class: "muted" }, SW.t("recent_revision_device", { device: v.device })) : null,
      empty.length ? h("p", { class: "muted" }, SW.t("recent_revision_no_spools", { ids: empty.join(", ") })) : null,
      last && v.n === last.n ? SW.btn(SW.t("revision_undo", { number: v.n }), { icon: "undo", run: () => recPost(box, histPath(view.id, "undo"), { revision: v.n }, (r) => {
        redraw(r);
        const gone = ((r.revisions.find((x) => x.n === v.n) || {}).filaments || {}).orphaned_by_undo || [];
        const c = changes[0];
        say(box, [c ? SW.t("revision_undone_result", { number: v.n, field: recLabel(c.field), value: recShow((REC_FIELD[c.field] || [])[4], c.old) || SW.t("common_field_empty_value") })
          : SW.t("recent_result_undone", { number: v.n }), ...(gone.length ? [SW.t("recent_result_filament_empty", { ids: gone.join(", ") })] : [])].join(" "), true);
        const t = document.getElementById("recent-revisions"); if (t) t.focus();
      }, view) }) : null);
  }));
  return h("section", { class: "card revisions", "aria-labelledby": "recent-revisions" },
    h("h3", { class: "detail__heading revisions__title", id: "recent-revisions", tabindex: "-1" }, SW.t("recent_revisions_title", { count: revs.length })),
    revs.length ? list : h("p", { class: "muted" }, SW.t("revision_empty")), box);
}

// the Record card and the read facts (02 7.2 "Read facts"): plain lines, left out when the Hub does not give their value
function recFacts(rec, s, ids) {
  const reading = s ? recReading(rec, s.item) : null, lines = [];
  if (reading) {
    const least = Object.keys(reading.levels).filter((k) => reading.levels[k] === "low" || reading.levels[k] === "medium");
    const bits = [reading.sure != null ? SW.t("recent_read_sure", { percent: reading.sure }) : null, least.length ? SW.t("recent_read_least_sure", { fields: least.map(recLabel).join(", ") }) : null].filter(Boolean);
    if (bits.length) lines.push(SW.t("recent_when_read", { details: bits.join(" · ") }));
  }
  const weighed = [rec.weight != null ? SW.t("recent_weighed", { weight: recShow("g", rec.weight) }) : null, rec.tag ? SW.t("recent_tag_read") : null].filter(Boolean);
  if (weighed.length) lines.push(weighed.join(" · "));
  const row = (k, ...v) => h("div", { class: "kv__row" }, h("dt", { class: "kv__key" }, k), h("dd", { class: "kv__value" }, ...v));
  return h("section", { class: "card", "aria-labelledby": "recent-record" }, h("h3", { class: "detail__heading", id: "recent-record" }, SW.t("recent_record_title")),
    h("dl", { class: "kv" }, row(SW.t("recent_col_added"), h("span", { class: "mono" }, recTime(rec.at))), row(SW.t("recent_record_source"), recSource(rec)),
      row(SW.t("common_field_state"), SW.status(REC_STATE[rec.state] || "as_detected", { small: true, text: REC_STATE[rec.state] ? null : rec.state })),
      row(SW.t("recent_record_spools", { count: ids.length }), ids.length ? h("span", { class: "mono" }, ids.join(", ")) : h("span", { class: "muted" }, SW.t("common_none"))),
      row(SW.t("recent_record_photos"), h("span", { class: "mono" }, rec.photos))),
    ...lines.map((t) => h("p", { class: "muted" }, t)));
}
