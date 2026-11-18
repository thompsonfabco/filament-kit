// The Spools section of the Hub page (R83 sections 1 and 10.2; 03 section 5a): the spools as a Collection with a search field and
// four chips, 50 rows at a time, and a spool's detail with Update weight, Move, Link the last tapped tag and Mark empty. Every change
// shows what it would do first (the Hub's dry run) and is applied from that preview; looking needs no code, a change does.
// Loaded after setup.js (it uses its api, needCode, theCode and say); everything from the Hub goes in through textContent, as there.
// The section is `#spools`, one spool `#spools/<number>`. Its registration (a TABS entry, GROUPS, the script and style tags) is the
// registry step's: this file only offers `spoolsTab()`.
"use strict";
(() => {
const PAGE = 50;
const SECTION = "spools";

// ----- texts: the catalogue's own where it has the key, else this table (key -> English), as web-shared/alerts.js does -----
const STUB = {
  spools_count: { one: "{count} spool", other: "{count} spools" },
  spools_open_spoolman: "Open Spoolman",
  spools_search: "Find a spool",
  spools_search_hint: "Brand, name, material, place, number or tag.",
  spools_filters: "Show only",
  spools_chip_loaded: "In a printer",
  spools_chip_low: "Running low",
  spools_empty_title: "No spools yet.",
  spools_empty_text: "Add your first one from your phone.",
  spools_clear: "Clear the search and filter",
  spools_col_number: "Number",
  spools_col_colour: "Colour",
  spools_col_spool: "Spool",
  spools_col_left: "Left",
  spools_col_where: "Where",
  spools_no_place: "Not placed",
  spools_not_weighed: "Not weighed",
  spools_tagged: "Tagged",
  spools_untagged: "No tag",
  spools_low: "Running low",
  spools_unnamed: "Unnamed spool",
  spools_show_more: "Show more",
  spools_shown: "Showing {shown} of {total}",
  spools_more_failed: "Could not read more spools: {reason}",
  spools_error: "Could not read the spools",
  spools_pane_empty: "Choose a spool to see its details.",
  spools_fact_left: "Left",
  spools_fact_state: "State",
  spools_fact_last_use: "Last taken off",
  spools_last_use: "{grams} g on {printer}, {at}",
  spools_last_use_none: "Nothing yet",
  spools_group_change: "Change this spool",
  spools_group_empty: "When it is used up",
  spools_weight_hint: "What the scale shows with the empty spool on it, in grams.",
  spools_weight_error: "Enter the weight in grams, a number above 0.",
  spools_link_last: "Link the last tapped tag",
  spools_previewing: "Checking what would change…",
  spools_apply: "Apply",
  spools_apply_name: "Apply: {what}",
  spools_nothing: "Nothing would change.",
  spools_preview_weight: "Preview: {left} g left becomes {after} g.",
  spools_preview_move: "Preview: it moves from {before} to {after}.",
  spools_preview_link: "Preview: tag {tag} is linked to this spool.",
  spools_preview_link_opens: "It then counts as opened.",
  spools_preview_empty: "Preview: {left} g left becomes 0 g and the spool is marked empty.",
  spools_done_weight: "Updated: {grams} g left.",
  spools_done_empty: "Marked empty.",
  spools_ask_empty_title: "Mark spool {id} empty?",
  spools_ask_empty_text: "{name} is recorded as used up: 0 g left, and it leaves this list.",
};
const tx = (key, vars) => {
  if (window.SW_TEXT && window.SW_TEXT[key] != null) return SW.t(key, vars);
  let v = STUB[key];
  if (v == null) return key;
  if (typeof v === "object") v = v[new Intl.PluralRules("en").select(vars && vars.count != null ? Number(vars.count) : 0)] || v.other;
  return vars ? v.replace(/\{([a-z][a-z0-9_]*)\}/g, (m, n) => (vars[n] != null ? String(vars[n]) : m)) : v;
};
window.SPOOLS_TEXT_KEYS = Object.freeze(Object.keys(STUB));

// ----- small helpers -----
const X = (...args) => SW.h(...args);
const E = (tag, cls, ...kids) => {
  const props = kids[0] && kids[0].constructor === Object ? kids.shift() : {};
  return X(tag, { class: cls, ...props }, ...kids);
};
const name = (v) => [v.vendor, v.name].filter(Boolean).join(" ") || tx("spools_unnamed");
const hexOf = (v) => (/^[0-9A-Fa-f]{6}$/.test(v.color_hex || "") ? "#" + v.color_hex : "");
const num = (n) => (typeof n === "number" && Number.isFinite(n) ? n : null);
const grams = (n) => (num(n) == null ? null : Math.round(n * 10) / 10);
const levelOf = (v) => (num(v.remaining_g) != null && num(v.net_g) > 0 ? v.remaining_g / v.net_g : null);
const pad2 = (n) => String(n).padStart(2, "0");
const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? String(iso || "") : `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
const ago = (iso) => {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : when(iso);
};
const slotBox = () => E("p", "result result--block", { role: "status" });
const addressOf = (id) => `#${SECTION}${id != null ? "/" + id : ""}`;
const addressId = () => { const m = /^#spools\/(\d+)$/.exec(location.hash); return m ? Number(m[1]) : null; };

// ----- what the section knows -----
const st = { q: "", filter: "", rows: [], total: 0, more: false, url: null, ready: false };
const wanted = new Set();            // the rows that are open: kept across a new read
const views = new Map();             // spool number -> {v, update(v), ...}: the parts of a drawn row that a change patches
let box = null;                      // the section's region
let parts = null;                    // {head, list, foot}
let seq = 0;                         // the newest read: an older answer that comes later is dropped
let storage = null;                  // the storage list for Move, read once per section drawing

const queryOf = (offset) => `spools?${new URLSearchParams({ ...(st.q ? { q: st.q } : {}), ...(st.filter ? { filter: st.filter } : {}), offset, limit: PAGE })}`;

// ----- the list -----
const COLUMNS = [["expand", "common_details", 1, true], ["visual", "spools_col_colour", 1, true], ["number", "spools_col_number", 1], ["title", "spools_col_spool", 1],
  ["material", "common_field_material", 2], ["left", "spools_col_left", 1], ["where", "spools_col_where", 3], ["state", "common_field_state", 1]];
const cell = (col, prio, ...kids) => X("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio }, ...kids);
const key = (k) => E("span", "coll__key", { "aria-hidden": "true" }, tx(k));

function cellsOf(v) {
  const left = grams(v.remaining_g);
  return {
    visual: [SW.swatch(hexOf(v), { level: levelOf(v) })],
    number: [E("span", "mono", `#${v.id}`)],
    title: [name(v)],
    material: [key("common_field_material"), v.material || null],
    left: [key("spools_col_left"), left == null ? E("span", "muted", tx("spools_not_weighed")) : E("span", "mono", tx("common_grams", { grams: left }))],
    where: [key("spools_col_where"), v.location ? v.location : E("span", "muted", tx("spools_no_place"))],
    state: [SW.status(v.state === "sealed" ? "note" : v.state === "opened" ? "ok" : "off", { small: true, text: tx(v.state === "sealed" ? "common_sealed" : v.state === "opened" ? "spool_state_opened" : "common_empty") }),
      v.low ? SW.status("needs_look", { small: true, text: tx("spools_low") }) : null,
      E("span", "coll__sub", tx(v.tag ? "spools_tagged" : "spools_untagged"))],
  };
}
function setCell(c, kids) {
  const k = c.querySelector(":scope > .coll__key");
  c.replaceChildren(...(k && !kids.some((x) => x && x.classList && x.classList.contains("coll__key")) ? [k] : []), ...kids.flat().filter((x) => x != null && x !== false));
}

function item(v) {
  const id = `spool-detail-${v.id}`, open = wanted.has(v.id) && SW.profile().detail !== "sheet";
  const view = { v };
  views.set(v.id, view);
  const expand = X("button", { class: "btn btn--ghost btn--icon coll__expand", type: "button", "aria-expanded": String(open), "aria-controls": id, "aria-label": tx("detail_for", { name: name(v) }) },
    SW.icon("chevron"), E("span", "spools-expand__label", tx("common_details")));
  const title = X("div", { class: "coll__cell", role: "cell", "data-col": "title", "data-prio": 1 }, X("a", { class: "coll__title", href: addressOf(v.id) }));
  const c = { title, visual: cell("visual", 1), number: cell("number", 1), material: cell("material", 2), left: cell("left", 1), where: cell("where", 3), state: cell("state", 1) };
  const region = detail(v, view, id);
  view.update = (nv) => {
    view.v = v = nv;
    const k = cellsOf(nv);
    title.querySelector("a").textContent = k.title[0];
    for (const col of ["visual", "number", "material", "left", "where", "state"]) setCell(c[col], k[col]);
    it.dataset.state = nv.state === "empty" ? "off" : "";
    if (!it.dataset.state) delete it.dataset.state;
    view.paintDetail(nv);
  };
  const it = X("div", { class: "coll__item", role: "rowgroup", "data-id": String(v.id) },
    E("div", "coll__row", { role: "row" }, cell("expand", 1, expand), c.visual, c.number, title, c.material, c.left, c.where, c.state),
    E("div", "coll__row coll__row--detail", { role: "row", hidden: !open }, X("div", { class: "coll__cell", role: "cell", "aria-colspan": 8 }, region)));
  const k = cellsOf(v);
  title.querySelector("a").textContent = k.title[0];
  for (const col of ["visual", "number", "material", "left", "where", "state"]) setCell(c[col], k[col]);
  if (v.state === "empty") it.dataset.state = "off";
  return it;
}

function table(rows) {
  const head = E("div", "coll__head", { role: "rowgroup" }, E("div", "coll__row", { role: "row" }, COLUMNS.map(([col, k, prio, hidden]) => X("div",
    { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio }, hidden ? E("span", "sr", tx(k)) : tx(k)))));
  views.clear();
  const el = X("div", { class: "coll coll--spools", role: "table", "aria-label": tx("nav_spools") }, head, rows.map((v) => item(v)));
  SW.collection(el, { name: SECTION, total: st.total, first: 0, emptyPane: tx("spools_pane_empty") });
  el.addEventListener("click", (e) => {
    const link = e.target.closest("a.coll__title"), btn = e.target.closest(".coll__expand") || (link && link.closest(".coll__item").querySelector(".coll__expand"));
    if (!btn) return;
    if (link) { e.preventDefault(); btn.click(); return; }
    const id = Number(btn.getAttribute("aria-controls").replace("spool-detail-", "")), open = btn.getAttribute("aria-expanded") === "true";
    if (open) {
      if (SW.phone()) for (const o of el.querySelectorAll('.coll__expand[aria-expanded="true"]')) if (o !== btn) { wanted.delete(Number(o.getAttribute("aria-controls").replace("spool-detail-", ""))); o.click(); }
      wanted.add(id);
    } else wanted.delete(id);
    if (/^#spools(\/\d*)?$/.test(location.hash)) history.replaceState(null, "", open ? addressOf(id) : addressOf());
  });
  return el;
}

// ----- the header, the search and the chips -----
function header() {
  const meta = E("p", "page-head__meta spools-head", E("span", "spools-count", tx("spools_count", { count: st.total })));
  if (st.url) meta.append(X("a", { class: "btn btn--ghost spools-link", href: st.url, target: "_blank", rel: "noopener" }, tx("spools_open_spoolman")));
  return meta;
}
const CHIPS = [["sealed", "common_sealed"], ["opened", "spool_state_opened"], ["loaded", "spools_chip_loaded"], ["low", "spools_chip_low"]];
function toolbar() {
  const search = SW.field({ type: "search", label: tx("spools_search"), name: "q", hint: tx("spools_search_hint"), value: st.q, onSearch: (q) => { st.q = q; reload(); } });
  const group = E("div", "spools-chips", { role: "group", "aria-label": tx("spools_filters") }, CHIPS.map(([f, k]) => X("button", {
    class: "chip spools-chip", type: "button", "aria-pressed": String(st.filter === f), "data-filter": f,
    on: { click: (e) => { st.filter = st.filter === f ? "" : f; for (const b of group.children) b.setAttribute("aria-pressed", String(b.dataset.filter === st.filter)); reload(); } } }, tx(k))));
  return E("div", "coll__toolbar spools-toolbar", search, group);
}

function paint() {
  parts.head.replaceChildren(header());
  if (!st.rows.length) {
    views.clear();
    const filtered = st.q || st.filter;
    parts.list.replaceChildren(filtered
      ? SW.empty({ icon: "spool", title: tx("spools_empty_filtered"), actions: [SW.btn(tx("spools_clear"), { run: () => { st.q = ""; st.filter = ""; box.replaceWith(region()); } })] })
      : SW.empty({ icon: "spool", title: tx("spools_empty_title"), text: tx("spools_empty_text") }));
    parts.foot.replaceChildren();
    return;
  }
  parts.list.replaceChildren(table(st.rows));
  paintFoot();
}
function paintFoot() {
  parts.foot.replaceChildren(E("p", "muted spools-shown", tx("spools_shown", { shown: st.rows.length, total: st.total })),
    st.more ? SW.btn(tx("spools_show_more"), { run: (e) => more(e.currentTarget) }) : null);
}

// ----- reads -----
async function reload() {
  const mine = ++seq;
  parts.list.setAttribute("aria-busy", "true");
  try {
    const r = await api(queryOf(0));
    if (mine !== seq) return;
    Object.assign(st, { rows: r.spools, total: r.total, more: r.has_more, url: r.spoolman_url || null, ready: true });
    parts.list.removeAttribute("aria-busy");
    paint();
    SW.announce(tx("spools_count", { count: st.total }));
  } catch (e) {
    if (mine !== seq) return;
    parts.list.removeAttribute("aria-busy");
    SW.toast(hubText(e.message), "bad");
  }
}
async function more(button) {
  SW.busy(button, tx("common_working"));
  const mine = seq;
  try {
    const r = await api(queryOf(st.rows.length));
    if (mine !== seq) return;
    const known = new Set(st.rows.map((v) => v.id));
    st.rows.push(...r.spools.filter((v) => !known.has(v.id)));
    Object.assign(st, { total: r.total, more: r.has_more });
    const tableEl = parts.list.querySelector(".coll--spools");
    if (tableEl) for (const v of r.spools) if (!known.has(v.id)) tableEl.append(item(v));
    tableEl && SW.collection(tableEl, { name: SECTION, total: st.total, first: 0 });
    parts.head.replaceChildren(header());
    paintFoot();
    const first = tableEl && tableEl.querySelector(`.coll__item[data-id="${r.spools[0] && r.spools[0].id}"] .coll__title`);
    if (first) first.focus({ preventScroll: true });
  } catch (e) {
    SW.idle(button);
    SW.toast(tx("spools_more_failed", { reason: hubText(e.message) }), "bad");
  }
}
// the places Move offers: the storage list, then Automatic
async function places() {
  if (!storage) storage = api("settings/storage").then((s) => (s.locations || []).map((l) => l.name), () => []);
  return storage;
}

// ----- one spool: the facts and the four changes (03 section 5a) -----
function kv(rows) {
  return X("dl", { class: "kv" }, rows.map(([k, value, o = {}]) => E("div", "kv__row", E("dt", "kv__key", k),
    E("dd", "kv__value", value == null ? E("span", "muted", tx("common_empty")) : E("span", o.mono ? "mono" : null, value)))));
}
function factsOf(v, use) {
  const left = grams(v.remaining_g), net = grams(v.net_g);
  return kv([
    [tx("spools_col_number"), `#${v.id}`, { mono: true }], [tx("common_field_brand"), v.vendor], [tx("common_field_name"), v.name], [tx("common_field_material"), v.material],
    [tx("common_field_colour"), v.color_hex ? "#" + v.color_hex : null, { mono: true }],
    [tx("spools_fact_left"), left == null ? tx("spools_not_weighed") : net ? `${tx("common_grams", { grams: left })} / ${tx("common_grams", { grams: net })}` : tx("common_grams", { grams: left }), { mono: true }],
    [tx("spools_fact_state"), [tx(v.state === "sealed" ? "common_sealed" : v.state === "opened" ? "spool_state_opened" : "common_empty"), v.low ? ", " + tx("spools_low") : ""].join("")],
    [tx("common_field_location"), v.location], [tx("spool_field_tag"), v.tag, { mono: true }], [tx("common_field_lot"), v.lot],
    [tx("spools_fact_last_use"), use === undefined ? "…" : use ? tx("spools_last_use", { grams: grams(use.grams) ?? "?", printer: use.printer, at: when(use.at) }) : tx("spools_last_use_none")]]);
}

// A change: the press asks the Hub what it would do (the code first), the answer is shown beside the button with Apply, and Apply sends
// it for real. `make(dry)` gives the request; `say(r)` the preview sentence (null: nothing would change); `done(r)` the result sentence.
function change(view, out, o) {
  const send = (dry) => api(`spools/${view.v.id}${o.path || ""}`, { ...o.body(), dry_run: dry, code: theCode() });
  const fail = (e) => { if (e.locked) { SW.result(out, null); throw e; } out._said = null; SW.result(out, "bad", hubText(e.message)); };
  const apply = async () => {
    if (o.ask && !(await SW.ask(o.ask(view.v)))) return;
    await needCode(async () => {
      SW.result(out, "run", tx("common_working"));
      let r;
      try { r = await send(false); } catch (e) { fail(e); return; }
      view.update(r.spool);
      if (o.after) o.after(r);
      SW.result(out, "ok", o.done(r));
    });
  };
  return async () => {
    await needCode(async () => {
      SW.result(out, "run", tx("spools_previewing"));
      let r;
      try { r = await send(true); } catch (e) { fail(e); return; }
      const text = o.say(r);
      if (!text) SW.result(out, "neutral", tx("spools_nothing"));
      else SW.result(out, "info", text, { action: { label: o.applyLabel || tx("spools_apply"), name: tx("spools_apply_name", { what: o.applyLabel || o.label }), run: apply } });
    });
  };
}

function detail(v0, view, id) {
  let use;            // undefined: not read yet; null: nothing
  const facts = E("div", "spools-facts");
  const paintFacts = (v) => facts.replaceChildren(factsOf(v, use));
  const back = SW.iconBtn("chevron", tx("detail_back", { name: tx("nav_spools") }), { cls: "detail__back" });
  const closeBtn = SW.iconBtn("close", tx("detail_close", { name: name(v0) }), { cls: "detail__close" });
  const title = X("h2", { class: "detail__title", id: id + "-title", tabindex: "-1", text: name(v0) });

  // Update weight
  const weightBox = slotBox(), weight = SW.field({ type: "number", decimal: true, label: tx("common_field_weight_with_spool"), name: "gross", unit: "g", short: true, mono: true,
    hint: tx("spools_weight_hint"), check: (s) => { const n = Number(String(s).replace(",", ".")); return String(s).trim() && Number.isFinite(n) && n > 0 ? null : tx("spools_weight_error"); } });
  const weightGo = SW.btn(tx("spool_update_weight"), { cls: "btn--primary", name: `${tx("spool_update_weight")}: ${name(v0)}` });
  weightGo.addEventListener("click", () => {
    const bad = weight._check(); SW.fieldError(weight, bad);
    if (bad) { weight._control.focus(); return; }
    change(view, weightBox, { label: tx("spool_update_weight"), body: () => ({ gross: Number(weight._control.value.replace(",", ".")) }),
      say: (r) => (r.spool.remaining_g === r.before.remaining_g ? null : tx("spools_preview_weight", { left: grams(r.before.remaining_g) ?? "?", after: grams(r.spool.remaining_g) })),
      done: (r) => tx("spools_done_weight", { grams: grams(r.spool.remaining_g) }) })();
  });

  // Move
  const moveBox = slotBox(), move = SW.field({ type: "select", label: tx("spool_move_title"), name: "location", options: [{ value: "", label: tx("storage_automatic") }] });
  places().then((names) => { for (const n of names) move._control.append(X("option", { value: n, text: n })); if (v0.location && names.includes(v0.location)) move._control.value = v0.location; });
  const moveGo = SW.btn(tx("spool_move"), { cls: "btn--primary", name: `${tx("spool_move")}: ${name(v0)}` });
  moveGo.addEventListener("click", change(view, moveBox, { label: tx("spool_move"), body: () => (move._control.value ? { location: move._control.value } : { auto_location: true }),
    say: (r) => (r.spool.location === r.before.location ? null : tx("spools_preview_move", { before: r.before.location || tx("spools_no_place"), after: r.spool.location })),
    done: (r) => tx("spool_result_moved", { location: r.spool.location }) }));

  // Link the last tapped tag
  const linkBox = slotBox(), linkGo = SW.btn(tx("spools_link_last"), { name: `${tx("spools_link_last")}: ${name(v0)}` });
  let tapped = null;
  linkGo.addEventListener("click", async () => {
    let last;
    try { last = await api("spools/last-tag"); } catch (e) { SW.result(linkBox, "bad", hubText(e.message)); return; }
    if (!last.tag) { SW.result(linkBox, "warn", tx("spool_sheet_no_tag")); return; }
    tapped = last.tag;
    change(view, linkBox, { label: tx("spools_link_last"), path: "/link", body: () => ({ tag: tapped.uid }),
      say: (r) => (r.spool.tag === r.before.tag ? null : [tx("spools_preview_link", { tag: r.spool.tag }), r.before.state === "sealed" && r.spool.state === "opened" ? " " + tx("spools_preview_link_opens") : ""].join("")),
      done: () => tx("spool_result_tag_linked") })();
  });

  // Mark empty: apart, and it asks first
  const emptyBox = slotBox(), emptyGo = SW.btn(tx("spool_mark_empty"), { cls: "btn--danger", name: `${tx("spool_mark_empty")}: ${name(v0)}` });
  emptyGo.addEventListener("click", change(view, emptyBox, { label: tx("spool_mark_empty"), applyLabel: tx("spool_mark_empty"), body: () => ({ empty: true }),
    say: (r) => (r.before.state === "empty" ? null : tx("spools_preview_empty", { left: grams(r.before.remaining_g) ?? 0 })),
    ask: (v) => ({ kind: "destructive", title: tx("spools_ask_empty_title", { id: v.id }), text: tx("spools_ask_empty_text", { name: name(v) }), confirm: tx("spool_mark_empty") }),
    done: () => tx("spools_done_empty") }));

  const actions = (field, button, out) => E("div", "spools-act", E("div", "spools-act__row", field, button), out);
  view.paintDetail = (nv) => { title.textContent = name(nv); paintFacts(nv); };
  paintFacts(v0);
  api(`spools/${v0.id}`).then((r) => { use = r.last_use || null; paintFacts(view.v); }, () => { use = null; paintFacts(view.v); });
  const region = X("section", { class: "detail", id, "aria-labelledby": id + "-title", hidden: true }, E("header", "detail__head", back, title, closeBtn),
    E("div", "detail__body",
      E("div", "detail__section", E("h3", "detail__heading", tx("spools_fact_state")), facts),
      E("div", "detail__section",
        E("h3", "detail__heading", tx("spools_group_change")),
        actions(weight, weightGo, weightBox), actions(move, moveGo, moveBox), E("div", "spools-act", E("div", "spools-act__row", linkGo), linkBox),
        E("div", "detail__remove", E("h3", "detail__heading", tx("spools_group_empty")), E("div", "spools-act", E("div", "spools-act__row", emptyGo), emptyBox)))));
  region.addEventListener("sw:detail-close", () => {
    wanted.delete(view.v.id);
    if (location.hash === addressOf(view.v.id)) history.replaceState(null, "", addressOf());
  });
  return region;
}

// ----- the section -----
function region() {
  box = E("div", "spools");
  parts = { head: E("div", "spools-headbox"), list: E("div", "spools-listbox"), foot: E("div", "spools-foot") };
  box.append(parts.head, toolbar(), parts.list, parts.foot);
  const L = SW.loading(parts.list, { thing: tx("nav_spools"), items: 3, onTry: () => { start(); }, title: tx("spools_error") });
  const mine = ++seq;
  start();
  async function start() {
    try {
      const at = addressId();
      const [r, one] = await Promise.all([api(queryOf(0)), at != null ? api(`spools/${at}`).catch(() => null) : null]);
      if (mine !== seq) return;
      Object.assign(st, { rows: r.spools, total: r.total, more: r.has_more, url: r.spoolman_url || null, ready: true });
      if (one && !st.rows.some((v) => v.id === one.spool.id)) st.rows.unshift(one.spool);
      if (at != null) wanted.add(at);
      L.done();
      paint();
      if (at != null) { const it = parts.list.querySelector(`.coll__item[data-id="${at}"]`); if (it) it.scrollIntoView({ block: "start" }); }
    } catch (e) {
      if (mine !== seq) return;
      L.done(SW.errorState({ title: tx("spools_error"), text: hubText(e.message), onTry: start }));
    }
  }
  storage = null;
  return box;
}

window.spoolsTab = () => [region];
})();
