// The Settings section's Storage locations group (DECISIONS R79; 03 10.4). Loaded after setup.js and setup_settings.js;
// everything from the Hub goes in through textContent. The list is ONE ordered list: the page edits a copy of it (adds, edits,
// moves and removes change only that copy and the "Where a new spool goes" panel) and one Save sends the whole list.
"use strict";

// ----- the data: the Hub's own routes (SL2, storage_api.py) -----
// GET settings/storage answers {locations, order_by_material, everything_else, notices}; POST settings/storage/preview (no code, writes
// nothing) answers the same for the unsaved list; POST settings/storage (code) saves the whole list.
const loadStorage = () => api("settings/storage");
const previewStorage = (list) => api("settings/storage/preview", { locations: list });
async function saveStorage(list) {
  const r = await api("settings/storage", { locations: list, code: theCode() });
  if (r.saved !== false) return r;
  // more than 20 spools to rename: a job, and the list is written when the spools are renamed
  for (;;) {
    await new Promise((done) => setTimeout(done, 600));
    const j = await api("settings/storage/job");
    if (j.state === "done") return { ...(await loadStorage()), text: j.text || "" };
    if (j.state === "failed" || j.state === "none") throw new Error(j.error || j.text || SW.t("common_hub_no_answer"));
  }
}

// ----- the rows' words -----
function stFull(r) {
  const used = r.used || 0;
  if (r.type === "containers") return SW.t("storage_used_containers", { used, count: r.count || 0 });
  return r.limit ? SW.t("storage_used_limit", { used, limit: r.limit }) : SW.t("storage_used_plain", { count: used });
}
const stTakesText = (r) => (r.fill === "any" ? SW.t("storage_fill_any") : r.fill === "materials" ? (r.materials || []).join(", ") : SW.t("storage_takes_none"));
// what is sent: the unsaved list without what the Hub works out (how full, free, position, the containers)
const stPayload = (rows) => rows.map((r) => ({ id: r.id || null, name: r.name, type: r.type, limit: r.type === "bulk" ? r.limit : null,
  count: r.type === "containers" ? r.count : null, fill: r.fill, materials: r.fill === "materials" ? r.materials : [], overflow: !!r.overflow,
  default_overflow: !!r.default_overflow, sealed: !!r.sealed }));
const stWhole = (v, min, max) => /^\d+$/.test(v.trim()) && +v >= min && +v <= max;
const stNames = (list) => new Intl.ListFormat(document.documentElement.lang || "en", { style: "long", type: "conjunction" }).format(list);
const stRelabel = (b, label) => {
  b.setAttribute("aria-label", label);
  const tip = b.querySelector(".tooltip");
  if (tip) tip.textContent = label;
};
const STORAGE_NOTICES = { converted: ["info", "storage_notice_converted"], default_overflow_no_limit: ["warn", "storage_notice_default_overflow_no_limit"] };

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
  // what the Hub says about the list (the converted list; R79 C1: two or more overflow places and no limit on the default)
  const notices = h("div", { class: "storage__notices" });
  let panelData = st, previewing = 0, timer = 0;
  const add = SW.btn(SW.t("storage_add_location"), { cls: "btn--primary", icon: "plus", run: (e) => openEditor(null, e.currentTarget) });
  const body = [
    h("div", { class: "storage__bar" }, h("h3", { class: "settings__heading", textContent: SW.t("settings_storage_locations") }), add),
    table, notices,
    h("section", { class: "storage__panel", "aria-labelledby": "storage-panel-title" },
      h("h3", { class: "settings__heading", id: "storage-panel-title", textContent: SW.t("storage_panel_title") }), panel),
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
      return [...(r.overflow && !r.default_overflow && r.type === "bulk" ? [{ label: SW.t("storage_make_default_overflow"), run: () => mark(r, "default_overflow") }] : []),
        ...(r.type === "bulk" && !r.sealed ? [{ label: SW.t("storage_sealed_here"), run: () => mark(r, "sealed") }] : []),
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
    v.type.textContent = SW.t(row.type === "containers" ? "storage_type_containers" : "storage_type_bulk");
    v.badges.replaceChildren(...[row.overflow ? "storage_badge_overflow" : null, row.default_overflow ? "storage_badge_default_overflow" : null,
      row.sealed ? "storage_badge_sealed" : null].filter(Boolean).map((k) => SW.status("note", { small: true, text: SW.t(k) })));
    v.full.textContent = stFull(row);
    v.takes.textContent = stTakesText(row);
    v.edit.setAttribute("aria-label", SW.t("settings_storage_edit_name", { name: row.name }));
    stRelabel(v.up, SW.t("storage_move_up", { name: row.name }));
    stRelabel(v.down, SW.t("storage_move_down", { name: row.name }));
    stRelabel(v.more, SW.t("common_more_actions_for", { name: row.name }));
    // the first row cannot go up and the last cannot go down; the button keeps its focus (aria-disabled, not disabled)
    v.up.setAttribute("aria-disabled", String(i === 0)); v.down.setAttribute("aria-disabled", String(i === rows.length - 1));
    v.el.dataset.position = String(i + 1);
  };
  // the panel and the notices are the Hub's answer for the unsaved list (the preview), not worked out here
  const paintPanel = () => {
    const join = SW.t("storage_panel_join");
    panel.replaceChildren(...[...(panelData.order_by_material || []).map((m) => SW.t("storage_panel_line", { material: m.material, places: m.locations.join(join) })),
      SW.t("storage_panel_line", { material: SW.t("storage_panel_everything_else"), places: (panelData.everything_else || []).join(join) })].map((t1) => h("li", { textContent: t1 })));
    notices.replaceChildren(...(panelData.notices || []).filter((n) => STORAGE_NOTICES[n.code]).map((n) => {
      const b = SW.banner({ kind: STORAGE_NOTICES[n.code][0], inline: true, text: SW.t(STORAGE_NOTICES[n.code][1]) });
      b.dataset.notice = n.code;
      return b;
    }));
  };
  const preview = () => {
    clearTimeout(timer);
    const n = ++previewing;
    timer = setTimeout(async () => {
      try { const r = await previewStorage(stPayload(rows)); if (n === previewing) { panelData = r; paintPanel(); } } catch { /* the panel keeps what it shows */ }
    }, 120);
  };
  // every row drawn again from the list (the rows keep their elements; the order of the elements follows the list)
  const paint = () => {
    for (const [key, v] of items) if (!rows.some((r) => r._key === key)) { v.el.remove(); items.delete(key); }
    rows.forEach((r, i) => { paintRow(r, i); const el1 = items.get(r._key).el; if (el1.parentNode !== table) place(el1); });
    // elements are only moved when their place is wrong, so a button that has the focus keeps it
    const want = rows.map((r) => items.get(r._key).el), have = [...table.children].filter((c) => c.classList.contains("coll__item") && items.has(c.dataset.id));
    if (want.some((w, i) => w !== have[i])) for (const w of want) place(w);
    paintPanel();
  };
  // a row goes before the open "Add" form, which is always last
  const place = (el1) => { const tail = table.querySelector(':scope > .coll__item[data-id="new"]'); if (tail) table.insertBefore(el1, tail); else table.append(el1); };
  // the copy of the list is what the group's Save sends: the hidden field carries it, so the form group sees the change
  const commit = () => {
    for (const v of items.values()) v.errors.replaceChildren();
    paint();
    input.value = JSON.stringify(stPayload(rows));
    preview();
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
    SW.announce(row.name + ": " + SW.t(flag === "sealed" ? "storage_badge_sealed" : "storage_badge_default_overflow"));
  }
  async function remove(row, opener) {
    const refusal = row.default_overflow ? SW.t("storage_error_remove_default_overflow") : row.sealed ? SW.t("storage_error_remove_sealed") : null, n = row.used || 0;
    if (document.querySelector(`#storage-detail-${CSS.escape(row._key)}`) && !(await SW.closeDetail(document.querySelector(`#storage-detail-${CSS.escape(row._key)}`), { focus: false }))) return;
    const ok = await SW.ask({ kind: "destructive", title: SW.t("storage_remove_title", { name: row.name }), opener,
      text: n ? SW.t("storage_remove_body", { count: n }) : SW.t("storage_remove_body_none"), confirm: SW.t("common_remove"),
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
    f.name = SW.field({ name: "name", label: SW.t("storage_field_name"), value: cur.name, max: 100 });
    const hint = h("p", { class: "field__hint storage__typehint" });
    f.type = SW.segmented({ legend: SW.t("storage_field_type"), name: "type", value: cur.type, cls: "storage__type-choice",
      options: [["bulk", "storage_type_bulk"], ["containers", "storage_type_containers"]].map(([value, k]) => ({ value, label: SW.t(k), disabled: fixed && value !== cur.type })) });
    f.limit = SW.field({ name: "limit", type: "number", mono: true, optional: true, label: SW.t("storage_field_limit"), hint: SW.t("storage_field_limit_hint"), value: cur.limit == null ? "" : cur.limit });
    f.count = SW.field({ name: "count", type: "number", mono: true, label: SW.t("storage_field_count"), value: cur.count == null ? "" : cur.count });
    const fill = h("fieldset", { class: "storage__fill" }, h("legend", { class: "field__label", textContent: SW.t("storage_field_fill") }),
      ...["none", "any", "materials"].map((value) => h("label", { class: "check" }, h("input", { class: "check__input", type: "radio", name: "fill", value, checked: cur.fill === value }),
        h("span", { class: "check__label", textContent: SW.t("storage_fill_" + value) }))));
    f.materials = SW.field({ name: "materials", label: SW.t("storage_field_materials"), hint: SW.t("storage_field_materials_hint"), value: cur.materials.join(", ") });
    const anyHint = h("p", { class: "field__hint storage__anyhint", textContent: SW.t("storage_fill_any_overflow_hint") });
    const over = SW.check({ name: "overflow", label: SW.t("storage_field_overflow"), desc: SW.t("storage_field_overflow_hint"), checked: !!cur.overflow });
    f.overflow = h("div", { class: "field storage__overflow" }, over, h("p", { class: "field__error", id: id + "-overflow-error", hidden: true }));
    Object.assign(f.overflow, { _control: over._control, _error: f.overflow.lastChild });
    const typeNote = fixed ? h("p", { class: "field__hint storage__fixed", textContent: SW.t("storage_error_type_fixed") }) : null;
    const result = h("p", { class: "result", role: "status" });
    const submit = h("button", { class: "btn btn--primary", type: "submit", textContent: SW.t(isNew ? "storage_add_submit" : "storage_save_location") });
    const cancel = SW.btn(SW.t("common_cancel"), { cls: "btn--ghost", run: () => SW.closeDetail(region) });
    const form = h("form", { class: "storage__form", novalidate: true },
      h("header", { class: "detail__head" },
        SW.iconBtn("chevron", SW.t("detail_back", { name: SW.t("settings_group_storage") }), { cls: "detail__back" }),
        h("h2", { class: "detail__title group__title", id: id + "-title", tabindex: "-1", textContent: isNew ? SW.t("storage_add_location") : cur.name }),
        SW.iconBtn("close", SW.t("detail_close", { name: isNew ? SW.t("storage_add_location") : cur.name }), { cls: "detail__close" })),
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
        if (name && clash) return SW.t("storage_error_container_name", { name, set: clash.r.name });
        return !name ? SW.t("storage_error_name") : others().some((r) => r.name.trim().toLowerCase() === name.toLowerCase()) ? SW.t("storage_error_name_taken", { name }) : null;
      },
      limit: () => (typeNow() !== "bulk" || !val("limit").value.trim() || stWhole(val("limit").value, 1, 9999) ? null : SW.t("storage_error_whole")),
      count: () => {
        if (typeNow() !== "containers") return null;
        if (!stWhole(val("count").value, 1, 999)) return SW.t("storage_error_whole");
        const n = +val("count").value, used = (cur.containers || []).filter((c) => c.taken), high = Math.max(0, ...used.map((c) => c.number));
        const over = used.filter((c) => c.number > n);         // the container names are the Hub's: the page takes them from the data
        if (!over.length) return null;
        return over.length === 1 ? SW.t("storage_error_container_in_use", { name: over[0].name, least: high }) : SW.t("storage_error_containers_in_use", { names: stNames(over.map((c) => c.name)), least: high });
      },
      materials: () => (fillNow() !== "materials" || materialsNow().length ? null : SW.t("storage_error_materials")),
      overflow: () => (cur.default_overflow && !val("overflow").checked ? SW.t("storage_error_remove_default_overflow") : null),
    };
    const sync = () => {
      const containers = typeNow() === "containers";
      f.limit.hidden = containers; f.count.hidden = !containers; f.materials.hidden = fillNow() !== "materials";
      hint.textContent = SW.t(containers ? "storage_type_containers_hint" : "storage_type_bulk_hint");
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

    const g = SW.formGroup(form, { title: isNew ? SW.t("storage_add_location") : cur.name, send: async () => ({}) });
    for (const x of [form.querySelector('[data-action="undo-changes"]')]) if (x) x.remove();
    // this form only changes the unsaved list: no request, and what it holds is not "unsaved" once it has been taken
    g.save = async () => {
      const bad = Object.keys(check).filter((name) => { const text = check[name](); SW.fieldError(f[name], text); return !!text; });
      if (!bad.length && cur.type !== typeNow() && typeNow() === "containers" && (cur.default_overflow || cur.sealed)) {
        SW.result(result, "bad", SW.t(cur.default_overflow ? "storage_error_remove_default_overflow" : "storage_error_remove_sealed"));
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
  const savedText = () => [SW.t("settings_storage_saved"), lastReply && lastReply.text].filter(Boolean).join(" ");
  o.send = async (key, value) => {
    let reply;
    try { reply = await saveStorage(JSON.parse(value)); } catch (e) {
      if (e.locked) throw e;
      const errs = e.data && e.data.errors;
      if (errs && errs.length) {
        for (const v of items.values()) v.errors.replaceChildren();
        for (const x of errs) {
          const r = x.row == null ? null : rows[x.row], v = r && items.get(r._key);
          if (v) v.errors.append(SW.status("failed", { small: true, text: x.error }));
        }
        const first = errs.find((x) => x.row != null) || errs[0], fieldRow = first.row == null ? null : rows[first.row];
        // a refusal for a field is shown at the field: the form of that row opens with the Hub's text there
        if (fieldRow && ["name", "limit", "count", "materials"].includes(first.field)) setTimeout(() => {
          const open = document.querySelector(".storage__form") ? null : openEditor(fieldRow, items.get(fieldRow._key).edit);
          if (open) SW.fieldError(open.f[first.field], first.error);
        }, 100);
        e.text = () => hubText(e.message);
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
    panelData = st;
    paint();
  };
  rows.forEach((r) => build(r));
  paint();
  return el;
}
