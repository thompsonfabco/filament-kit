// The Settings section's Storage locations group (DECISIONS R79; 03 10.4). Loaded after setup.js and setup_settings.js;
// everything from the Hub goes in through textContent. The list is ONE ordered list: the page edits a copy of it (adds, edits,
// moves and removes change only that copy and the "Where a new spool goes" panel) and one Save sends the whole list.
"use strict";

// ----- the data: the only two functions that talk to the Hub for this group -----
// TODO SL2: this is a STUB with the shapes of R79 section 4. Swap loadStorage() for the Hub's read of the list (the page's twin of
// GET api/storage) and saveStorage() for api("settings/storage", { locations, code: theCode() }) (P settings/storage); nothing
// else in this file knows where the list lives. Contract points this page needs that R79 section 4 does not spell out are marked
// "TODO SL2" below (per-row errors, the rename result, numbers in use, the converted flag).
let stStub = null;
let stNextId = 0;
const stClone = (x) => JSON.parse(JSON.stringify(x));
// the Hub's work, here only so the stub answers like the Hub: the whole set of containers, in number order
const stSet = (prefix, count, taken) => Array.from({ length: count }, (_, i) => ({ name: prefix + String(i + 1).padStart(2, "0"), number: i + 1, taken: taken.includes(i + 1) }));
const stLoc = (o) => ({ id: "loc-" + (++stNextId), type: "bulk", limit: null, count: null, used: 0, fill: "none", materials: [], overflow: false,
  default_overflow: false, sealed: false, ...o });
function stStubInit() {
  stNextId = 0;
  return [
    stLoc({ name: "Sealed stock", sealed: true, used: 4 }),
    stLoc({ name: "Rack 1", limit: 20, used: 18, fill: "materials", materials: ["PLA"] }),
    stLoc({ name: "Rack 2", used: 7, fill: "materials", materials: ["PETG", "ABS"] }),
    // a PREFIXED set (the name is not the prefix): its containers are named by the Hub, which the page never does (R79 22:10)
    stLoc({ name: "Storage box (containers)", type: "containers", count: 12, used: 9, fill: "any", prefix: "Storage box ", containers: stSet("Storage box ", 12, [1, 2, 3, 4, 5, 6, 7, 11, 12]) }),
    stLoc({ name: "Overflow", used: 2, overflow: true, default_overflow: true }),
    stLoc({ name: "Dry shelf", limit: 10, overflow: true }),
  ];
}
function stReply() {
  const locations = stStub.map((l, i) => ({ ...stClone(l), position: i + 1, prefix: l.prefix || null, containers: l.containers || null,
    free: l.type === "containers" ? l.containers.filter((c) => !c.taken).length : null }));
  const places = stPlaces(locations);
  return { locations, order_by_material: places.byMaterial, everything_else: places.rest, converted: false };   // TODO SL2: `converted` (R79 section 6.6)
}
async function loadStorage() {
  if (!stStub) stStub = stStubInit();
  return stReply();
}
// what the Hub would refuse: [{ row (0-based, as sent), field, text }]  (TODO SL2: the shape of "errors per row and field")
function stStubErrors(list, sets) {
  const out = [], seen = new Map();
  const bad = (row, field, key, vars) => out.push({ row, field, text: SW.t(key, vars) });
  list.forEach((l, i) => {
    const name = String(l.name || "").trim();
    if (!name || name.length > 100) bad(i, "name", "settings_storage_error_name");
    else if (seen.has(name.toLowerCase())) bad(i, "name", "settings_storage_error_name_taken", { name });
    seen.set(name.toLowerCase(), i);
    if (l.type === "bulk" && l.limit != null && !(Number.isInteger(l.limit) && l.limit >= 1 && l.limit <= 9999)) bad(i, "limit", "settings_storage_error_number");
    if (l.type === "containers" && !(Number.isInteger(l.count) && l.count >= 1 && l.count <= 999)) bad(i, "count", "settings_storage_error_number");
    if (l.fill === "any" && l.overflow) bad(i, "fill", "settings_storage_fill_any_hint");
    if (l.fill === "materials" && !(l.materials || []).length) bad(i, "materials", "settings_storage_error_materials");
  });
  // a name that is a container's name, and a set whose container names equal a name (R79 22:06): the Hub refuses both ways
  list.forEach((l, i) => {
    for (const set of sets) {
      if (set.i === i) continue;
      const clash = set.containers.find((c) => c.name.toLowerCase() === String(l.name || "").trim().toLowerCase());
      if (clash) bad(l.type === "bulk" && !set.changed ? i : set.i, "name", "settings_storage_error_container_name", { name: l.name.trim(), set: set.name });
    }
  });
  const def = list.findIndex((l) => l.default_overflow), seal = list.findIndex((l) => l.sealed);
  if (def < 0 || !list[def].overflow || list[def].type !== "bulk") bad(Math.max(def, 0), "overflow", "settings_storage_default_first");
  if (seal < 0 || list[seal].type !== "bulk") bad(Math.max(seal, 0), "sealed", "settings_storage_sealed_first");
  return out;
}
async function saveStorage(list) {
  const before = new Map(stStub.map((l) => [l.id, l]));
  const sets = list.map((l, i) => ({ l, i })).filter((x) => x.l.type === "containers").map(({ l, i }) => {
    const old = l.id && before.get(l.id), name = String(l.name || "").trim(), prefix = old && old.name === name ? old.prefix : name + " ";
    const taken = old && old.containers ? old.containers.filter((c) => c.taken).map((c) => c.number) : [];
    return { i, name, prefix, changed: !old || old.name !== name || old.count !== l.count, containers: stSet(prefix, l.count || 0, taken.filter((n) => n <= l.count)) };
  });
  const errors = stStubErrors(list, sets);
  if (errors.length) throw Object.assign(new Error(errors[0].text), { data: { errors } });
  const renamed = [];
  stStub = list.map((l, i) => {
    const old = l.id && before.get(l.id);
    if (old && old.name !== l.name.trim() && old.used) renamed.push({ from: old.name, to: l.name.trim(), count: old.used });
    return stLoc({ ...(old || {}), ...l, name: l.name.trim(), id: old ? old.id : "loc-" + (++stNextId), materials: l.materials || [],
      limit: l.type === "bulk" ? l.limit : null, count: l.type === "containers" ? l.count : null,
      ...(l.type === "containers" ? (() => { const set = sets.find((x) => x.i === i); return { prefix: set.prefix, containers: set.containers, used: set.containers.filter((c) => c.taken).length }; })()
        : { prefix: null, containers: null }) });
  });
  return { ...stReply(), renamed };      // TODO SL2: `renamed` [{from, to, count}] is this page's reading of "Renamed Rack 1 to PLA rack 1. 18 spools updated."
}

// ----- what the list means (R79 sections 1 and 2): the order a new spool tries the places in -----
// the length of the longest name of the location that the material starts with (case ignored); 0 when none does
const stTakes = (r, material) => (r.materials || []).reduce((best, m) => (material.toLowerCase().startsWith(m.toLowerCase()) ? Math.max(best, m.length) : best), 0);
const stUnique = (names) => names.filter((n, i) => names.indexOf(n) === i);
// one line per material named in the list, then everything else: own places (overflow ones included, R79 C2), else "Any material"
// places, then the overflow ones (the default first)
function stPlaces(rows) {
  const any = rows.filter((r) => !r.overflow && r.fill === "any");
  const overflow = [...rows.filter((r) => r.default_overflow), ...rows.filter((r) => r.overflow && !r.default_overflow)];
  const named = [];
  for (const r of rows) if (r.fill === "materials") for (const m of r.materials || []) if (!named.some((x) => x.toLowerCase() === m.toLowerCase())) named.push(m);
  const byMaterial = named.map((material) => {
    const hits = rows.filter((r) => r.fill === "materials" && stTakes(r, material) > 0), best = Math.max(0, ...hits.map((r) => stTakes(r, material)));
    const mine = hits.filter((r) => stTakes(r, material) === best);
    return { material, locations: stUnique([...(mine.length ? mine : any), ...overflow].map((r) => r.name)) };
  });
  return { byMaterial, rest: stUnique([...any, ...overflow].map((r) => r.name)) };
}

// ----- the rows' words -----
function stFull(r) {
  const used = r.used || 0;
  if (r.type === "containers") return SW.t("settings_storage_full_containers", { used, count: r.count || 0 });
  return r.limit ? SW.t("settings_storage_full_limit", { used, count: r.limit }) : SW.t("settings_storage_full_open", { count: used });
}
const stTakesText = (r) => (r.fill === "any" ? SW.t("settings_storage_fill_any") : r.fill === "materials" ? (r.materials || []).join(", ") : SW.t("settings_storage_takes_none"));
// what is sent: the unsaved list without what the Hub works out (how full, free, position)
const stPayload = (rows) => rows.map((r) => ({ id: r.id || undefined, name: r.name, type: r.type, limit: r.type === "bulk" ? r.limit : null,
  count: r.type === "containers" ? r.count : null, fill: r.fill, materials: r.fill === "materials" ? r.materials : [], overflow: !!r.overflow,
  default_overflow: !!r.default_overflow, sealed: !!r.sealed }));
const stWhole = (v, min, max) => /^\d+$/.test(v.trim()) && +v >= min && +v <= max;
const stNames = (list) => new Intl.ListFormat(document.documentElement.lang || "en", { style: "long", type: "conjunction" }).format(list);
const stRelabel = (b, label) => {
  b.setAttribute("aria-label", label);
  const tip = b.querySelector(".tooltip");
  if (tip) tip.textContent = label;
};

// ----- the group -----
function storageGroup({ st }) {
  let rows = st.locations.slice().sort((a, b) => a.position - b.position).map((l) => ({ ...l, materials: (l.materials || []).slice(), _key: l.id }));
  let newKeys = 0, lastReply = null;
  const items = new Map();                         // key -> the drawn parts of a row
  // the form group reads `labels[0]` of every named field, and a hidden input has no `labels`: it gets an empty list
  const input = h("input", { type: "hidden", name: "locations", value: JSON.stringify(stPayload(rows)) });
  Object.defineProperty(input, "labels", { value: [] });
  const panel = h("ul", { class: "storage__places" });
  const table = h("div", { class: "coll coll--storage", role: "table", "aria-label": SW.t("settings_storage_locations") },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
      ...[["title", "settings_storage_col_location"], ["full", "settings_storage_col_full"], ["takes", "settings_storage_col_takes"]]
        .map(([col, key]) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": 1, textContent: SW.t(key) })),
      h("div", { class: "coll__cell", role: "columnheader", "data-col": "actions" }, h("span", { class: "sr", textContent: SW.t("common_actions") })))));
  // R79 C1: with two or more overflow places and no limit on the default, the others are never reached
  const notice = SW.banner({ kind: "warn", inline: true, text: SW.t("settings_storage_overflow_unused") });
  notice.classList.add("storage__notice");
  const add = SW.btn(SW.t("settings_storage_add"), { cls: "btn--primary", icon: "plus", run: (e) => openEditor(null, e.currentTarget) });
  const body = [
    st.converted || rows.some((r) => r.type === "containers" && (/ \(containers\)$/.test(r.name) || r.name === "Container")) ? SW.banner({ kind: "info", inline: true, text: SW.t("settings_storage_converted") }) : null,
    h("div", { class: "storage__bar" }, h("h3", { class: "settings__heading", textContent: SW.t("settings_storage_locations") }), add),
    table, notice,
    h("section", { class: "storage__panel", "aria-labelledby": "storage-panel-title" },
      h("h3", { class: "settings__heading", id: "storage-panel-title", textContent: SW.t("settings_storage_panel") }), panel),
    input,
  ];
  const el = setGroup("storage", { desc: SW.t("settings_storage_desc"), save: SW.t("settings_storage_save"), body });

  // the row's cell
  const cell = (col, key, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": 1 },
    key ? h("span", { class: "coll__key", "aria-hidden": "true", textContent: SW.t(key) }) : null, ...kids);
  const rowOf = (key) => rows.find((r) => r._key === key);
  const build = (row) => {
    const v = { pos: h("span", { class: "storage__pos mono" }), name: h("span", { class: "coll__title-text storage__name" }), type: h("span", { class: "coll__sub storage__type" }),
      badges: h("span", { class: "storage__badges" }), errors: h("span", { class: "storage__errors" }), full: h("span", { class: "storage__text" }), takes: h("span", { class: "storage__text" }) };
    v.edit = SW.btn(SW.t("common_edit"), { run: (e) => openEditor(rowOf(row._key), e.currentTarget) });
    v.up = SW.iconBtn("chevron", "", { cls: "storage__move storage__move--up", run: () => move(row._key, -1) });
    v.down = SW.iconBtn("chevron", "", { cls: "storage__move storage__move--down", run: () => move(row._key, 1) });
    v.more = SW.iconBtn("more", "", {});
    SW.menu(v.more, () => {
      const r = rowOf(row._key);
      return [...(r.overflow && !r.default_overflow && r.type === "bulk" ? [{ label: SW.t("settings_storage_make_default"), run: () => mark(r, "default_overflow") }] : []),
        ...(r.type === "bulk" && !r.sealed ? [{ label: SW.t("settings_storage_make_sealed"), run: () => mark(r, "sealed") }] : []),
        { separator: true }, { label: SW.t("common_remove"), danger: true, run: () => remove(r, v.more) }];
    }, { get label() { return SW.t("common_actions_for", { name: rowOf(row._key).name }); } });
    v.el = h("div", { class: "coll__item", role: "rowgroup", "data-id": row._key },
      h("div", { class: "coll__row", role: "row" },
        h("div", { class: "coll__cell", role: "cell", "data-col": "title", "data-prio": 1 }, h("span", { class: "storage__head" }, v.pos, v.name), v.type, v.badges, v.errors),
        cell("full", "settings_storage_col_full", v.full), cell("takes", "settings_storage_col_takes", v.takes),
        h("div", { class: "coll__cell", role: "cell", "data-col": "actions" }, h("div", { class: "actions" }, v.edit, v.up, v.down, v.more))));
    items.set(row._key, v);
    return v;
  };
  // the row's words from its data: called for every row after each change
  const paintRow = (row, i) => {
    const v = items.get(row._key) || build(row);
    v.pos.textContent = String(i + 1);
    v.name.textContent = row.name || "";
    v.type.textContent = SW.t(row.type === "containers" ? "settings_storage_type_containers" : "settings_storage_type_bulk");
    v.badges.replaceChildren(...[row.overflow ? "settings_storage_badge_overflow" : null, row.default_overflow ? "settings_storage_badge_default" : null,
      row.sealed ? "settings_storage_badge_sealed" : null].filter(Boolean).map((k) => SW.status("note", { small: true, text: SW.t(k) })));
    v.full.textContent = stFull(row);
    v.takes.textContent = stTakesText(row);
    v.edit.setAttribute("aria-label", SW.t("settings_storage_edit_name", { name: row.name }));
    stRelabel(v.up, SW.t("settings_storage_move_up", { name: row.name }));
    stRelabel(v.down, SW.t("settings_storage_move_down", { name: row.name }));
    stRelabel(v.more, SW.t("common_more_actions_for", { name: row.name }));
    // the first row cannot go up and the last cannot go down; the button keeps its focus (aria-disabled, not disabled)
    v.up.setAttribute("aria-disabled", String(i === 0)); v.down.setAttribute("aria-disabled", String(i === rows.length - 1));
    v.el.dataset.position = String(i + 1);
  };
  const paintPanel = () => {
    const p = stPlaces(rows), join = SW.t("settings_storage_panel_join");
    panel.replaceChildren(...[...p.byMaterial.map((m) => SW.t("settings_storage_panel_line", { material: m.material, places: m.locations.join(join) })),
      SW.t("settings_storage_panel_line", { material: SW.t("settings_storage_panel_else"), places: p.rest.join(join) })].map((t1) => h("li", { textContent: t1 })));
  };
  // every row drawn again from the list (the rows keep their elements; the order of the elements follows the list)
  const paint = () => {
    for (const [key, v] of items) if (!rows.some((r) => r._key === key)) { v.el.remove(); items.delete(key); }
    rows.forEach((r, i) => { paintRow(r, i); const el1 = items.get(r._key).el; if (el1.parentNode !== table) place(el1); });
    // elements are only moved when their place is wrong, so a button that has the focus keeps it
    const want = rows.map((r) => items.get(r._key).el), have = [...table.children].filter((c) => c.classList.contains("coll__item") && items.has(c.dataset.id));
    if (want.some((w, i) => w !== have[i])) for (const w of want) place(w);
    paintPanel();
    const def = rows.find((r) => r.default_overflow);
    notice.hidden = !(rows.filter((r) => r.overflow).length >= 2 && def && !def.limit);
  };
  // a row goes before the open "Add" form, which is always last
  const place = (el1) => { const tail = table.querySelector(':scope > .coll__item[data-id="new"]'); if (tail) table.insertBefore(el1, tail); else table.append(el1); };
  // the copy of the list is what the group's Save sends: the hidden field carries it, so the form group sees the change
  const commit = () => {
    for (const v of items.values()) v.errors.replaceChildren();
    paint();
    input.value = JSON.stringify(stPayload(rows));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };

  function move(key, by) {
    const i = rows.findIndex((r) => r._key === key), j = i + by;
    if (j < 0 || j >= rows.length) return;
    const a = items.get(rows[i]._key).el, b = items.get(rows[j]._key).el;
    [rows[i], rows[j]] = [rows[j], rows[i]];
    if (by < 0) a.after(b); else b.after(a);       // the neighbour moves, so the row that was pressed keeps its focus
    commit();
    SW.announce(SW.t("settings_storage_moved", { name: rows[j].name, position: j + 1, total: rows.length }));
  }
  function mark(row, flag) {
    for (const r of rows) r[flag] = r === row;
    if (flag === "default_overflow") row.overflow = true;
    commit();
    SW.announce(row.name + ": " + SW.t(flag === "sealed" ? "settings_storage_badge_sealed" : "settings_storage_badge_default"));
  }
  async function remove(row, opener) {
    const refusal = row.default_overflow ? SW.t("settings_storage_default_first") : row.sealed ? SW.t("settings_storage_sealed_first") : null, n = row.used || 0;
    if (document.querySelector(`#storage-detail-${CSS.escape(row._key)}`) && !(await SW.closeDetail(document.querySelector(`#storage-detail-${CSS.escape(row._key)}`), { focus: false }))) return;
    const ok = await SW.ask({ kind: "destructive", title: SW.t("settings_storage_remove_title", { name: row.name }), opener,
      text: n ? SW.t("settings_storage_remove_text", { count: n }) : SW.t("settings_storage_remove_none"), confirm: SW.t("common_remove"),
      run: refusal ? async (_, { result }) => { SW.result(result, "bad", refusal); return false; } : undefined });
    if (!ok) return;
    const i = rows.indexOf(row);
    rows = rows.filter((r) => r !== row);
    commit();
    const next = rows[Math.min(i, rows.length - 1)], v = next && items.get(next._key);
    (v ? v.edit : add).focus();                    // the focus goes to the row that took its place
  }

  // ----- Add and Edit: the theme's detail region (as a printer's), holding its own small form group -----
  function openEditor(row, opener) {
    const isNew = !row, key = isNew ? "new" : row._key, id = "storage-detail-" + key;
    const was = document.getElementById(id);
    if (was) { SW.openDetail(was, { opener }); return; }
    const cur = row ? { ...row, materials: row.materials.slice() } : { type: "bulk", name: "", limit: null, count: null, fill: "none", materials: [], overflow: false };
    const fixed = !isNew && (row.used || 0) > 0;
    const others = () => rows.filter((r) => r !== row);
    const f = {};
    f.name = SW.field({ name: "name", label: SW.t("settings_storage_name"), value: cur.name, max: 100 });
    const hint = h("p", { class: "field__hint storage__typehint" });
    f.type = SW.segmented({ legend: SW.t("settings_storage_type"), name: "type", value: cur.type, cls: "storage__type-choice",
      options: [["bulk", "settings_storage_type_bulk"], ["containers", "settings_storage_type_containers"]].map(([value, k]) => ({ value, label: SW.t(k), disabled: fixed && value !== cur.type })) });
    f.limit = SW.field({ name: "limit", type: "number", mono: true, optional: true, label: SW.t("settings_storage_limit"), hint: SW.t("settings_storage_limit_hint"), value: cur.limit == null ? "" : cur.limit });
    f.count = SW.field({ name: "count", type: "number", mono: true, label: SW.t("settings_storage_count"), value: cur.count == null ? "" : cur.count });
    const fill = h("fieldset", { class: "storage__fill" }, h("legend", { class: "field__label", textContent: SW.t("settings_storage_fill") }),
      ...["none", "any", "materials"].map((value) => h("label", { class: "check" }, h("input", { class: "check__input", type: "radio", name: "fill", value, checked: cur.fill === value }),
        h("span", { class: "check__label", textContent: SW.t("settings_storage_fill_" + value) }))));
    f.materials = SW.field({ name: "materials", label: SW.t("settings_storage_materials"), hint: SW.t("settings_storage_materials_hint"), value: cur.materials.join(", ") });
    const anyHint = h("p", { class: "field__hint storage__anyhint", textContent: SW.t("settings_storage_fill_any_hint") });
    const over = SW.check({ name: "overflow", label: SW.t("settings_storage_overflow"), desc: SW.t("settings_storage_overflow_hint"), checked: !!cur.overflow });
    f.overflow = h("div", { class: "field storage__overflow" }, over, h("p", { class: "field__error", id: id + "-overflow-error", hidden: true }));
    Object.assign(f.overflow, { _control: over._control, _error: f.overflow.lastChild });
    const typeNote = fixed ? h("p", { class: "field__hint storage__fixed", textContent: SW.t("settings_storage_type_fixed") }) : null;
    const result = h("p", { class: "result", role: "status" });
    const submit = h("button", { class: "btn btn--primary", type: "submit", textContent: SW.t(isNew ? "settings_storage_add_confirm" : "settings_storage_save_location") });
    const cancel = SW.btn(SW.t("common_cancel"), { cls: "btn--ghost", run: () => SW.closeDetail(region) });
    const form = h("form", { class: "storage__form", novalidate: true },
      h("header", { class: "detail__head" },
        SW.iconBtn("chevron", SW.t("detail_back", { name: SW.t("settings_group_storage") }), { cls: "detail__back" }),
        h("h2", { class: "detail__title group__title", id: id + "-title", tabindex: "-1", textContent: isNew ? SW.t("settings_storage_add") : cur.name }),
        SW.iconBtn("close", SW.t("detail_close", { name: isNew ? SW.t("settings_storage_add") : cur.name }), { cls: "detail__close" })),
      h("div", { class: "detail__body" },
        h("div", { class: "detail__section" }, f.name, f.type, hint, typeNote),
        h("div", { class: "detail__section" }, f.limit, f.count, fill, anyHint, f.materials, f.overflow)),
      h("div", { class: "group__foot" }, result, cancel, submit));
    const region = h("section", { class: "detail storage__detail", id, "aria-labelledby": id + "-title", hidden: true }, form);
    const drow = h("div", { class: "coll__row coll__row--detail", role: "row", hidden: true }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": 4 }, region));
    const host = isNew ? h("div", { class: "coll__item", role: "rowgroup", "data-id": "new" }) : items.get(key).el;
    host.append(drow);
    if (isNew) table.append(host);

    const val = (name) => form.elements[name];
    const pick0 = (value) => form.querySelector(`input[name="fill"][value="${value}"]`);
    const typeNow = () => val("type").value, fillNow = () => val("fill").value;
    const materialsNow = () => [...new Map(val("materials").value.split(",").map((s) => s.trim()).filter(Boolean).map((s) => [s.toLowerCase(), s])).values()];
    // the checks of each field: a sentence, or null
    const check = {
      name: () => {
        const name = val("name").value.trim();
        const clash = typeNow() === "bulk" && others().flatMap((r) => (r.containers || []).map((c) => ({ c, r }))).find((x) => x.c.name.toLowerCase() === name.toLowerCase());
        if (name && clash) return SW.t("settings_storage_error_container_name", { name, set: clash.r.name });
        return !name ? SW.t("settings_storage_error_name") : others().some((r) => r.name.trim().toLowerCase() === name.toLowerCase()) ? SW.t("settings_storage_error_name_taken", { name }) : null;
      },
      limit: () => (typeNow() !== "bulk" || !val("limit").value.trim() || stWhole(val("limit").value, 1, 9999) ? null : SW.t("settings_storage_error_number")),
      count: () => {
        if (typeNow() !== "containers") return null;
        if (!stWhole(val("count").value, 1, 999)) return SW.t("settings_storage_error_number");
        const n = +val("count").value, used = (cur.containers || []).filter((c) => c.taken), high = Math.max(0, ...used.map((c) => c.number));
        const over = used.filter((c) => c.number > n);         // the container names are the Hub's: the page takes them from the data
        return over.length ? SW.t("settings_storage_count_in_use", { count: over.length, highest: high, names: stNames(over.map((c) => c.name)) }) : null;
      },
      materials: () => (fillNow() !== "materials" || materialsNow().length ? null : SW.t("settings_storage_error_materials")),
      overflow: () => (cur.default_overflow && !val("overflow").checked ? SW.t("settings_storage_default_first") : null),
    };
    const sync = () => {
      const containers = typeNow() === "containers";
      f.limit.hidden = containers; f.count.hidden = !containers; f.materials.hidden = fillNow() !== "materials";
      hint.textContent = SW.t(containers ? "settings_storage_type_containers_hint" : "settings_storage_type_bulk_hint");
      // an overflow place takes any material by being overflow: "Any material" is off while it is ticked
      const anyOff = val("overflow").checked;
      pick0("any").disabled = anyOff; anyHint.hidden = !anyOff;
    };
    for (const [name, fn] of Object.entries(check)) {
      const fld = f[name];
      const run = () => SW.fieldError(fld, fn());
      for (const c of form.querySelectorAll(`[name="${name}"]`)) {
        c.addEventListener("change", run);
        c.addEventListener("input", () => { if (fld.dataset.state === "error") run(); });
      }
    }
    val("overflow").addEventListener("change", () => { if (val("overflow").checked && fillNow() === "any") pick0("none").checked = true; });
    form.addEventListener("change", sync);
    if (cur.overflow && cur.fill === "any") cur.fill = "none";
    sync();

    const g = SW.formGroup(form, { title: isNew ? SW.t("settings_storage_add") : cur.name, send: async () => ({}) });
    for (const x of [form.querySelector('[data-action="undo-changes"]')]) if (x) x.remove();
    // this form only changes the unsaved list: no request, and what it holds is not "unsaved" once it has been taken
    g.save = async () => {
      const bad = Object.keys(check).filter((name) => { const text = check[name](); SW.fieldError(f[name], text); return !!text; });
      if (!bad.length && cur.type !== typeNow() && typeNow() === "containers" && (cur.default_overflow || cur.sealed)) {
        SW.result(result, "bad", SW.t(cur.default_overflow ? "settings_storage_default_first" : "settings_storage_sealed_first"));
        return;
      }
      if (bad.length) { f[bad[0]]._control.focus(); return; }
      const next = { ...cur, name: val("name").value.trim(), type: typeNow(), fill: fillNow(), materials: fillNow() === "materials" ? materialsNow() : [],
        overflow: val("overflow").checked, limit: typeNow() === "bulk" && val("limit").value.trim() ? +val("limit").value : null,
        count: typeNow() === "containers" ? +val("count").value : null };
      if (!next.overflow) next.default_overflow = false;
      let target = row;
      if (isNew) { target = Object.assign(next, { _key: "n" + (++newKeys), id: undefined, used: 0, free: null }); rows.push(target); } else Object.assign(row, next);
      g.reset();                                   // the typed values are taken: nothing to ask about when it closes
      commit();
      await SW.closeDetail(region, { focus: false });
      items.get(target._key).edit.focus();
    };
    form.addEventListener("submit", (e) => e.stopPropagation());     // it is not the group's own Save
    form.addEventListener("sw:dirty", (e) => e.stopPropagation());
    region.addEventListener("sw:detail-close", () => {
      drow.remove();
      if (isNew) host.remove();
      el.dispatchEvent(new CustomEvent("sw:dirty", { bubbles: true }));       // the group's unsaved mark is read again without this form
      if (!isNew && items.get(key)) items.get(key).edit.removeAttribute("aria-controls");
      if (isNew) add.removeAttribute("aria-controls");
    });
    (isNew ? add : items.get(key).edit).setAttribute("aria-controls", id);
    SW.openDetail(region, { opener });
    return { form, f };
  }

  // ----- the group's own Save: the whole list in one request -----
  const o = { send: null, done: () => savedText() };
  const savedText = () => [SW.t("settings_storage_saved"), ...((lastReply && lastReply.renamed) || []).map((r) => SW.t("settings_storage_renamed", r))].join(" ");
  o.send = async (key, value) => {
    let reply;
    try { reply = await saveStorage(JSON.parse(value)); } catch (e) {
      if (e.locked) throw e;
      const errs = e.data && e.data.errors;
      if (errs && errs.length) {
        const sent = JSON.parse(value);
        for (const v of items.values()) v.errors.replaceChildren();
        for (const x of errs) {
          const r = rows[x.row], v = r && items.get(r._key);
          if (v) v.errors.append(SW.status("failed", { small: true, text: x.text }));
        }
        const first = errs[0], fieldRow = rows[first.row];
        // a refusal for a field is shown at the field: the form of that row opens with the Hub's text there
        if (fieldRow && ["name", "limit", "count", "materials"].includes(first.field)) setTimeout(() => {
          const open = document.querySelector(".storage__form") ? null : openEditor(fieldRow, items.get(fieldRow._key).edit);
          if (open) SW.fieldError(open.f[first.field], first.text);
        }, 100);
        e.text = () => SW.t("settings_storage_row_error", { name: (sent[first.row] || {}).name || "", text: first.text });
      } else e.text = () => hubText(e.message);
      throw e;
    }
    lastReply = reply;
    return reply;
  };
  const g = wireGroup(el, "storage", o);
  // Undo changes puts the list back as it was read
  const undone = g.reset;
  g.reset = () => {
    undone();
    rows = (JSON.parse(input.value) || []).map((p, i) => {
      const was = st.locations.find((l) => l.id === p.id);
      return was ? { ...was, ...p, materials: p.materials.slice(), _key: was.id } : { ...p, materials: p.materials.slice(), used: 0, free: null, _key: "n" + (++newKeys) };
    });
    for (const r of document.querySelectorAll(".storage__detail")) SW.closeDetail(r, { focus: false });
    for (const v of items.values()) v.el.remove();
    items.clear();
    paint();
  };
  rows.forEach((r) => build(r));
  paint();
  return el;
}
