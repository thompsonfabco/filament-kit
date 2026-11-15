// The Settings section (03 10): nine groups in a fixed order, each a form group (02 5.11) with one Save that sends its
// changed keys. Loaded after setup.js; everything from the server goes in through textContent, as there.
// The section is one region. Its groups read their data once when it opens (settings/general is read once for all of
// them), and a save reads only its own group again, so what is typed in another group stays. The Backups group is in
// setup_backup.js.
"use strict";

// id (the address #settings/<id>), catalogue key of the name, icon, builder, the read it needs
const SET_GROUPS = [
  ["appearance", "settings_group_appearance", "half-circle", groupAppearance, null],
  ["general", "settings_group_general", "settings", groupGeneral, "general"],
  ["storage", "settings_group_storage", "spool", groupStorage, "general"],
  ["label-reader", "settings_group_label_reader", "camera", groupLabelReader, "general"],
  ["backups", "settings_group_backups", "download", (d) => backupsGroup(d), null],
  ["network", "settings_group_network", "plug", groupNetwork, "general"],
  ["passphrase", "settings_group_passphrase", "lock", groupPassphrase, null],
  ["catalog", "settings_group_catalog", "tag", groupCatalog, "library"],
  ["voice", "settings_group_voice", "scale", groupVoice, "general"],
];
const SET_KEY = Object.fromEntries(SET_GROUPS.map((g) => [g[0], g[1]]));
const SET_ICON = Object.fromEntries(SET_GROUPS.map((g) => [g[0], g[2]]));

let setEl = null;                 // the section's region, kept while Settings stays open
let setGeneral = null;            // the one read of settings/general
const setSeen = { g: null, lib: null };
let setHashMove = false;          // the address moved inside Settings: the groups are not read again
let setScrollOn = false;
const FRESH_MS = 5000;

const readGeneral = (fresh) => (!fresh && setGeneral) || (setGeneral = api("settings/general").catch((e) => { setGeneral = null; throw e; }));
const wrapOf = (id) => (setEl ? setEl.querySelector(`.settings__group[data-id="${id}"]`) : null);
const dirtyIn = (el) => !!el.querySelector('form[data-state="dirty"]');
const settingsGroupName = () => (setGroupId() ? SW.t(SET_KEY[setGroupId()]) : "");
function setGroupId() {
  let id = "";
  try { id = decodeURIComponent(location.hash.slice(1).split("/")[1] || ""); } catch { /* a broken address opens the list */ }
  return SET_KEY[id] ? id : "";
}

// ----- small builders -----
// a result slot of a control that is not part of the group's Save
const sbox = () => h("p", { class: "result", role: "status" });
const badge = (nameKey, word, o) => h("span", { class: "settings__badge" }, SW.t(nameKey), " ", SW.status(word, { small: true, ...o }));
const offNote = (key) => SW.banner({ kind: "info", inline: true, text: SW.t(key),
  actions: [h("a", { class: "btn btn--primary", href: "#features", textContent: SW.t("common_go_to_features") })] });
const heading = (key) => h("h3", { class: "settings__heading" }, SW.t(key));
const whole = (min, max, key) => (v) => (/^\d+$/.test(v.trim()) && +v >= min && (max == null || +v <= max) ? null : SW.t(key));
const plainField = (o) => SW.field({ row: true, ...o, attrs: { ...(o.optional === false ? {} : { "aria-required": "false" }), ...o.attrs } });
const requiredField = (o) => SW.field({ row: true, ...o });
const megabytes = (n) => (n < 1048576 ? Math.max(1, Math.ceil(n / 1024)) + " KB" : (n / 1048576).toFixed(1) + " MB");
const codeBlock = (text, name) => h("div", { class: "code" },
  h("div", { class: "code__bar" }, h("span", { class: "result", role: "status" }), SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: "copy" })),
  h("pre", { class: "code__text", tabindex: "0", "aria-label": name, textContent: text }));

// a group: head (icon, title, description, badges), body, and a foot with the result and the Save when it has one
function setGroup(id, o) {
  const tid = "set-" + id + "-title", saves = !!o.save;
  const dirty = SW.status("needs_look", { small: true, cls: "settings__dirty", text: SW.t("common_unsaved_changes") });
  dirty.hidden = true;
  const head = h("div", { class: "group__head" }, SW.icon(SET_ICON[id], "icon--s"),
    h("div", {}, h("h2", { class: "group__title", id: tid, tabindex: "-1", textContent: SW.t(SET_KEY[id]) }),
      o.desc ? h("p", { class: "group__desc", textContent: o.desc }) : null),
    h("div", { class: "settings__badges" }, ...(o.badges || []), dirty));
  const foot = saves ? h("div", { class: "group__foot" }, sbox(), h("button", { class: "btn btn--primary", type: "submit", textContent: o.save })) : null;
  return h(saves ? "form" : "section", { class: "group", id: "set-" + id, "aria-labelledby": tid, novalidate: saves ? true : undefined },
    head, h("div", { class: "group__body" }, ...o.body), foot);
}

// ----- saving (02 5.11, N2) -----
// The keys that go through settings/general are sent together, one request for the keys of one effect (none, then the
// ones that restart the Hub, as the Hub page's order is: plain, applies, restarts); `own` names the keys with an
// endpoint of their own. The shared form group calls this once per changed key, in its order.
const effectOf = (form, key) => { const c = form.elements[key]; return (c && c.dataset && c.dataset.effect) || ""; };
function valueOf(form, key) {
  const c = form.elements[key];
  return !c ? "" : c.type === "checkbox" ? c.checked : c.value;
}
function setRefusal(form, e) {
  if (e.locked) return e;
  const errs = e.data && e.data.errors;
  if (errs) {
    const keys = Object.keys(errs), say1 = (k) => hubText(errs[k].startsWith(k + " ") ? errs[k].slice(k.length + 1) : errs[k]);
    for (const k of keys) { const c = form.elements[k]; if (c && c.closest && c.closest(".field")) SW.fieldError(c.closest(".field"), say1(k)); }
    e.field = keys[0];
    e.text = () => say1(keys[0]);
  } else {
    e.field = e.data && e.data.field;
    e.text = () => hubText(e.message);
  }
  return e;
}
function sender(getForm, getGroup, own, conv = {}) {
  let plan = {};
  const send = async (key, value) => {
    if (own[key]) return own[key](value);
    const form = getForm(), fx = effectOf(form, key);
    if (!plan[fx]) {
      const keys = getGroup().changed().filter((k) => !own[k] && effectOf(form, k) === fx), values = {};
      for (const k of keys) values[k] = conv[k] ? conv[k](valueOf(form, k)) : valueOf(form, k);
      plan[fx] = { left: keys, reply: null };
      try { plan[fx].reply = await api("settings/general", { values, code: theCode() }); } catch (e) { delete plan[fx]; throw setRefusal(form, e); }
    }
    const p = plan[fx];
    p.left = p.left.filter((k) => k !== key);
    return p.left.length ? {} : p.reply;
  };
  send.reset = () => { plan = {}; };
  return send;
}
// the form group of a form, with its sender; `before(keys)` may stop the save (a dialog); `done(text)` words the result
function wireGroup(form, id, o) {
  let keys = [];
  const g = SW.formGroup(form, { title: SW.t(SET_KEY[id]), send: o.send, onSaved: (saved) => {
    if (saved.length === keys.length) setTimeout(() => settled(form, id, o), 60);
  } });
  const save0 = g.save;
  g.save = async () => {
    keys = o.keys = g.changed();
    if (keys.length && o.before && !(await o.before(keys))) return;
    if (o.send.reset) o.send.reset();
    return save0();
  };
  if (o.after) o.after(g);
  o.group = g;
  return g;
}
// after a save: only this group is read again, and says what the save said
function settled(form, id, o) {
  const res = form.querySelector(".group__foot .result"), kind = res && res.dataset.state;
  const text = res && res.querySelector(".result__text") ? res.querySelector(".result__text").textContent : null;
  loadGroup(id, { quiet: true, fresh: true, result: kind && kind !== "run" && text ? [kind, o.done ? o.done(text) : text] : null });
}

// A request with the code that says its result in `box` and does not draw anything again
async function act(box, path, body, done, clear) {
  await needCode(async () => {
    working(box, SW.t("common_saving"));
    let r;
    try { r = await api(path, { ...body, code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      say(box, hubText(e.message), false);
      return;
    }
    for (const i of clear || []) i.value = "";
    if (done) done(r); else say(box, SW.t("common_saved"), true);
  });
}
// the same behind a dialog (`q`: SW.ask's options); resolves with the reply or null
async function confirmed(q, path, body, done) {
  const out = await SW.ask({ ...q, run: async (values, { result }) => {
    let r = null;
    await needCode(async () => {
      try { r = await api(path, { ...(typeof body === "function" ? body(values) : body), code: theCode() }); } catch (e) {
        if (e.locked) throw e;
        SW.result(result, "bad", hubText(e.message));
      }
    });
    return r || false;
  } });
  if (out && done) done(out);
  return out;
}
// a background job: its strip follows it; `q` asks first
function runJob(box, name, q) {
  const started = () => { SW.result(box, null); followApply(true); };
  if (q) return confirmed(q, "job", { name }, started);
  return act(box, "job", { name }, started);
}

// ----- the section -----
function settingsTab() {
  pageHead(h("p", { class: "page-head__meta", textContent: SW.t("settings_intro") }));
  if (setEl && setEl.isConnected) {                 // Settings stays open: a group that is not being edited reads again
    applyHash();
    // a group read a moment ago is as new as a read now; the others read again (a job ended, the Hub came back)
    if (!setHashMove) { setGeneral = null; for (const [id] of SET_GROUPS) if (Date.now() - (wrapOf(id)._readAt || 0) > FRESH_MS) loadGroup(id, { quiet: true }); }
    return setEl;
  }
  setGeneral = null;
  setSeen.g = setSeen.lib = null;
  const link = ([id, key]) => h("li", {}, h("a", { class: "subnav__link", href: "#settings/" + id, "data-id": id, on: { click: jump } },
    SW.t(key), SW.status("needs_look", { small: true, cls: "subnav__dirty", text: SW.t("common_unsaved") })));
  const row = ([id, key]) => h("li", {}, h("a", { class: "settings__row", href: "#settings/" + id, "data-id": id },
    h("span", { class: "settings__name", textContent: SW.t(key) }), h("span", { class: "settings__state" }), SW.icon("chevron", "icon--s")));
  setEl = h("div", { class: "settings" },
    h("nav", { class: "subnav", "aria-label": SW.t("settings_groups_label") }, h("ul", { class: "subnav__list" }, SET_GROUPS.map(link))),
    h("ul", { class: "settings__list" }, SET_GROUPS.map(row)),
    h("div", { class: "settings__main" },
      h("a", { class: "btn btn--ghost settings__back", href: "#settings" }, SW.icon("chevron", "icon--s"), SW.t("nav_settings")),
      h("div", { class: "settings__groups" }, SET_GROUPS.map(([id]) => h("div", { class: "settings__group", "data-id": id })))));
  for (const d of setEl.querySelectorAll(".subnav__dirty")) d.hidden = true;
  setEl.addEventListener("sw:dirty", markDirty);
  applyHash();
  paintList();
  const loads = SET_GROUPS.map(([id]) => loadGroup(id));
  later(Promise.all(loads));
  const first = setGroupId();
  Promise.all(loads).then(() => { if (first && setEl && !SW.phone()) scrollTo(first, false, true); });
  if (!setScrollOn) { setScrollOn = true; window.addEventListener("scroll", onScroll, { passive: true }); }
  markCurrent(first || SET_GROUPS[0][0]);
  return setEl;
}

function loadGroup(id, o = {}) {
  const wrap = wrapOf(id), def = SET_GROUPS.find((g) => g[0] === id);
  if (!wrap || (o.quiet && wrap._hold)) return Promise.resolve();
  const retry = () => loadGroup(id, { fresh: true });
  const L = o.quiet ? null : SW.loading(wrap, { thing: SW.t(def[1]), items: 3, onTry: retry, title: SW.t("settings_read_error", { reason: "" }).trim() });
  return (async () => {
    try {
      if (o.fresh) { setGeneral = null; try { S = await api("state"); } catch { /* the page keeps what it has */ } }
      const data = {};
      if (def[4] === "general") data.g = setSeen.g = await readGeneral(o.fresh);
      if (def[4] === "library") data.lib = setSeen.lib = await api("library");
      if (o.quiet && (dirtyIn(wrap) || wrap._hold || !wrap.isConnected)) { paintList(); return; }
      wrap._readAt = Date.now();
      const had = wrap.contains(document.activeElement), el = def[3](data, o);
      if (L) L.done(el); else wrap.replaceChildren(el);
      if (o.result) { const r = el.querySelector(".group__foot .result"); if (r) SW.result(r, o.result[0], o.result[1]); }
      if (had) { const t1 = el.querySelector(".group__title"); if (t1) t1.focus({ preventScroll: true }); }
    } catch (e) {
      if (L) L.done();
      if (e.locked) return;
      if (!o.quiet) readFailed(wrap, "settings_read_error", e, retry);
    }
    markDirty();
    paintList();
  })();
}

// the unsaved marks of the sub-navigation and of the group titles
function markDirty() {
  if (!setEl) return;
  for (const [id] of SET_GROUPS) {
    const w = wrapOf(id), d = !!(w && dirtyIn(w)), m = setEl.querySelector(`.subnav__link[data-id="${id}"] .subnav__dirty`), t1 = w && w.querySelector(".settings__dirty");
    if (m) m.hidden = !d;
    if (t1) t1.hidden = !d;
  }
}

// the one-line state of each group, on the phone's list (03 10.1)
function listState(id) {
  const g = setSeen.g, v = g && g.values, lib = setSeen.lib;
  if (id === "appearance") return SW.t("settings_state_appearance", { mode: SW.t("appearance_" + appearanceNow()),
    theme: SW.t("theme_" + (document.documentElement.getAttribute("data-look") || "console") + "_name") });
  if (id === "passphrase") return SW.t(S.passphrase.set ? "status_set" : "status_not_set");
  if (id === "network") return S.web.public_set ? SW.t("status_set") : SW.t("settings_state_no_public");
  if (id === "backups") return S.backup && S.backup.last ? SW.t("settings_state_backups", { time: S.backup.last })
    : SW.lock.state === "locked" ? SW.t("common_unlock_to_show") : SW.t("common_none");
  if (id === "catalog") return lib ? (lib.source === "none" ? SW.t("settings_state_catalog_none") : String(lib.version)) : "";
  if (!g) return "";
  if (id === "general") return String(v.server_name || "");
  if (id === "storage") return SW.t("settings_state_storage", { count: (v.locations || []).length });
  if (id === "label-reader") {
    if (g.ai_intake_on && g.local_intake_on) return SW.t("settings_reader_order_" + ({ auto: "auto", "local-then-cloud": "local_cloud", "cloud-then-local": "cloud_local",
      cloud: "cloud", local: "local" }[v["intake.reader"] || "auto"]));
    return g.ai_intake_on ? SW.t("settings_reader_order_cloud") : g.local_intake_on ? SW.t("settings_reader_order_local") : SW.t("settings_state_off");
  }
  if (id === "voice") return g.station_on ? SW.t(v["station.tts"] === "espeak" ? "settings_voice_espeak" : "settings_voice_piper") : SW.t("settings_state_off");
  return "";
}
function paintList() {
  if (!setEl) return;
  for (const [id] of SET_GROUPS) { const s = setEl.querySelector(`.settings__row[data-id="${id}"] .settings__state`); if (s) s.textContent = listState(id); }
}

// ----- the sub-navigation and the address (03 10.1) -----
function markCurrent(id) {
  if (!setEl) return;
  for (const a of setEl.querySelectorAll(".subnav__link")) { if (a.dataset.id === id) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); }
}
function onScroll() {
  if (!setEl || !setEl.isConnected) { setScrollOn = false; window.removeEventListener("scroll", onScroll); return; }
  if (SW.phone()) return;
  let cur = SET_GROUPS[0][0];
  for (const [id] of SET_GROUPS) { const w = wrapOf(id); if (w && w.getBoundingClientRect().top <= window.innerHeight / 3) cur = id; }
  markCurrent(cur);
}
function scrollTo(id, focus, instant) {
  const w = wrapOf(id);
  if (!w) return;
  w.scrollIntoView({ behavior: instant || matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  const t1 = w.querySelector(".group__title");
  if (focus && t1) t1.focus({ preventScroll: true });
  markCurrent(id);
}
function jump(e) {
  const id = e.currentTarget.dataset.id;
  e.preventDefault();
  if (SW.phone()) { location.hash = "#settings/" + id; return; }
  history.replaceState(null, "", "#settings/" + id);
  scrollTo(id, true);
  if (shellView) shellView.paint(false);
}
// the phone shows the list or one group; the wide layouts show them all (the CSS decides by the width)
function applyHash() {
  const id = setGroupId();
  if (id) setEl.dataset.open = id; else delete setEl.dataset.open;
  for (const w of setEl.querySelectorAll(".settings__group")) w.toggleAttribute("data-shown", w.dataset.id === id);
  if (id) markCurrent(id);
}
window.addEventListener("hashchange", () => {
  setHashMove = true;
  setTimeout(() => { setHashMove = false; }, 0);
  if (setEl && setEl.isConnected && tabNow() === "settings") {
    const id = setGroupId();
    if (id && !SW.phone() && setEl.dataset.open !== id) scrollTo(id, true);
  }
});

// ----- Appearance (03 10.2): this device, applied at once; Theme arrives with S6.2 and S6.10 -----
function groupAppearance() {
  const res = sbox(), hint = h("p", { class: "field__hint", textContent: SW.t("settings_appearance_mode_hint") });
  const choice = SW.segmented({ legend: SW.t("settings_appearance_mode"), cls: "appearance", name: "appearance-device", value: appearanceNow(),
    options: APPEARANCE.map(([value, icon]) => ({ value, icon, label: SW.t("appearance_" + value) })) });
  choice.addEventListener("change", () => setTimeout(paintList, 0));
  return setGroup("appearance", { desc: SW.t("settings_appearance_desc"), body: [h("div", { class: "settings__choice" }, choice, hint, res)] });
}

// ----- General (03 10.3) -----
function groupGeneral({ g }) {
  const v = g.values;
  const fields = [requiredField({ name: "server_name", label: SW.t("settings_general_name"), value: v.server_name == null ? "" : String(v.server_name),
    check: (x) => (x.trim() ? null : SW.t("settings_general_name_required")) })];
  if (g.spoolman_external) fields.push(plainField({ name: "spoolman", label: SW.t("settings_general_spoolman"), mono: true, value: g.spoolman_url || "",
    placeholder: SW.t("settings_general_spoolman_placeholder"), hint: SW.t("settings_general_spoolman_hint"), effect: "applies" }));
  const el = setGroup("general", { desc: SW.t("settings_general_desc"), save: SW.t("settings_general_save"), body: fields });
  const own = {
    spoolman: async (value) => {
      const f = el.elements.spoolman.closest(".field"), was = f._hint.textContent;
      f._hint.textContent = SW.t("settings_general_spoolman_checking");
      try { await api("settings/spoolman", { url: value.trim(), code: theCode() }); } catch (e) { throw setRefusal(el, Object.assign(e, { data: { ...(e.data || {}), field: "spoolman" } })); } finally { f._hint.textContent = was; }
      return { applies: true };
    },
  };
  const o = { send: null };
  o.send = sender(() => el, () => o.group, own);
  wireGroup(el, "general", o);
  return el;
}

// ----- Storage locations (03 10.4) -----
function groupStorage({ g }) {
  const v = g.values, text = (k) => (v[k] == null ? "" : String(v[k]));
  const fields = [
    plainField({ name: "locations", label: SW.t("settings_storage_locations"), value: (v.locations || []).join(", "), hint: SW.t("settings_storage_locations_hint") }),
    requiredField({ name: "placement.pla_location", label: SW.t("settings_storage_pla"), value: text("placement.pla_location"), hint: SW.t("settings_storage_pla_hint") }),
    requiredField({ name: "placement.box_prefix", label: SW.t("settings_storage_prefix"), value: text("placement.box_prefix"), hint: SW.t("settings_storage_prefix_hint") }),
    requiredField({ name: "placement.box_count", type: "number", mono: true, label: SW.t("settings_storage_boxes"), value: text("placement.box_count"),
      check: whole(0, 999, "settings_storage_boxes_error") }),
    requiredField({ name: "placement.overflow", label: SW.t("settings_storage_overflow"), value: text("placement.overflow"), hint: SW.t("settings_storage_overflow_hint") }),
  ];
  const el = setGroup("storage", { desc: SW.t("settings_storage_desc"), save: SW.t("settings_storage_save"), body: fields });
  const o = { send: null };
  o.send = sender(() => el, () => o.group, {}, {
    locations: (x) => x.split(",").map((s) => s.trim()).filter(Boolean),
    "placement.box_count": (x) => Number(x),
  });
  wireGroup(el, "storage", o);
  return el;
}

// ----- Label Reader (03 10.5) -----
const ORDERS = [["auto", "auto"], ["local-then-cloud", "local_cloud"], ["cloud-then-local", "cloud_local"], ["cloud", "cloud"], ["local", "local"]];
function groupLabelReader({ g }) {
  const v = g.values, cloud = !!g.ai_intake_on, local = !!g.local_intake_on, hist = g.intake_history || {};
  const body = [];
  const badges = [];
  if (cloud) badges.push(badge("settings_reader_badge_cloud", S.anthropic.set ? "set" : "not_set"));
  const localBadge = h("span", { class: "settings__badge" });
  if (local) badges.push(localBadge);
  if (!cloud && !local) body.push(offNote("settings_reader_off"));
  else if (cloud && local) body.push(plainField({ name: "intake.reader", type: "select", label: SW.t("settings_reader_order"), hint: SW.t("settings_reader_order_hint"),
    value: v["intake.reader"] || "auto", optional: false, options: ORDERS.map(([k, w]) => ({ value: k, label: SW.t("settings_reader_order_" + w) })) }));
  else body.push(h("p", { textContent: SW.t("settings_reader_order_single", { engine: SW.t(cloud ? "settings_reader_engine_cloud" : "settings_reader_group_local") }) }));

  let keyField = null;
  if (cloud) {
    const kbox = sbox();
    keyField = SW.field({ row: true, name: "key", type: "secret", mono: true, label: SW.t("settings_reader_key_new"), placeholder: SW.t("settings_reader_key_placeholder"),
      attrs: { "aria-required": "false", autocomplete: "new-password" } });
    const cancel = SW.btn(SW.t("common_cancel"), { cls: "btn--ghost", action: "cancel-key" });
    const entry = h("div", { class: "settings__entry" }, keyField, cancel);
    entry.hidden = true;
    const open = SW.btn(SW.t(S.anthropic.set ? "common_replace" : "settings_reader_key_set"), { action: "replace-key", run: () => { entry.hidden = false; open.hidden = true; keyField._control.focus(); } });
    cancel.addEventListener("click", () => { keyField._control.value = ""; keyField._control.dispatchEvent(new Event("change", { bubbles: true })); entry.hidden = true; open.hidden = false; open.focus(); });
    const checkBtn = SW.btn(SW.t("common_check"), { action: "check-key", run: async () => {
      working(kbox, SW.t("settings_reader_key_checking"));
      try { const r = await api("key/check", {}); say(kbox, r.text, r.ok); } catch (e) { say(kbox, e.status === 429 ? SW.t("settings_reader_key_wait") : hubText(e.message), false); }
    } });
    const remove = S.anthropic.set ? SW.btn(SW.t("common_remove"), { cls: "btn--ghost btn--danger", action: "remove-key", run: (e) => confirmed(
      { ...destroy("settings_key_remove_title", "settings_key_remove_body", "settings_key_remove_confirm"), opener: e.currentTarget }, "key/remove", {},
      () => loadGroup("label-reader", { quiet: true, fresh: true })) }) : null;
    body.push(heading("settings_reader_group_cloud"),
      h("div", { class: "settings__keyrow" }, h("p", { class: "field__label" }, SW.t("settings_reader_key"), " ", SW.status(S.anthropic.set ? "set" : "not_set", { small: true })),
        h("div", { class: "actions" }, checkBtn, open, remove)),
      kbox, entry,
      plainField({ name: "model", mono: true, label: SW.t("settings_reader_model"), value: v.model == null ? "" : String(v.model), placeholder: SW.t("settings_reader_model_placeholder"),
        hint: SW.t("settings_reader_model_hint"), effect: "restarts" }),
      requiredField({ name: "reads_per_day", type: "number", mono: true, label: SW.t("settings_reader_reads"), value: String(v.reads_per_day == null ? "" : v.reads_per_day),
        unit: SW.t("settings_reader_reads_unit"), hint: SW.t("settings_reader_reads_hint"), effect: "restarts", check: whole(1, 100000, "settings_reader_reads_error") }));
  } else if (local) body.push(h("p", { class: "muted", textContent: SW.t("settings_reader_key_cloud_off") }));

  if (local) {
    const saved = v["local_intake.url"] || "", out = slot();
    const addr = requiredField({ name: "local_intake.url", mono: true, label: SW.t("settings_reader_address"), value: saved, placeholder: SW.t("settings_reader_address_placeholder"),
      hint: SW.t("settings_reader_address_hint") });
    const tier = SW.segmented({ legend: SW.t("settings_reader_tier"), name: "local_intake.tier", value: v["local_intake.tier"] || "auto",
      options: [["auto", SW.t("settings_reader_tier_auto")], ["cpu", SW.t("settings_reader_tier_cpu")], ["gpu", SW.t("settings_reader_tier_gpu")]]
        .map(([value, label]) => ({ value, label })) });
    const test = SW.btn(SW.t("settings_reader_test"), { action: "test-reader", run: () => testReader(out, addr, tier, saved) });
    body.push(heading("settings_reader_group_local"), h("div", { class: "settings__withbtn" }, addr, test), out,
      h("div", { class: "settings__choice" }, tier, h("p", { class: "field__hint", textContent: SW.t("settings_reader_tier_hint") })),
      readerInstall(g));
    readerBadge(localBadge);
  }
  body.push(heading("settings_reader_group_recent"),
    requiredField({ name: "intake.history_keep", type: "number", mono: true, label: SW.t("settings_reader_keep"), value: String(v["intake.history_keep"] == null ? 20 : v["intake.history_keep"]),
      hint: SW.t("settings_reader_keep_hint", { count: hist.count || 0, size: megabytes(hist.photo_bytes || 0) }), check: whole(0, 500, "settings_reader_keep_error") }));
  if (cloud) body.push(SW.banner({ kind: "warn", inline: true, text: SW.t("settings_reader_restart_warn") }));

  const el = setGroup("label-reader", { desc: SW.t("settings_reader_desc"), save: SW.t("settings_reader_save"), badges, body });
  const o = { send: null };
  const own = { key: async (value) => {
    try { await api("key", { key: value, code: theCode() }); } catch (e) { throw setRefusal(el, Object.assign(e, { data: { ...(e.data || {}), field: "key" } })); }
    return {};
  } };
  o.send = sender(() => el, () => o.group, own, { "intake.history_keep": (x) => Number(x), reads_per_day: (x) => Number(x) });
  o.before = async (keys) => !(keys.includes("model") || keys.includes("reads_per_day")) || !!(await SW.ask({ kind: "confirm", title: SW.t("settings_restart_title"),
    text: SW.t("settings_restart_body"), confirm: SW.t("settings_restart_confirm") }));
  o.done = (text) => (o.keys.includes("key") ? text + " " + SW.t("settings_reader_key_saved") : text);
  wireGroup(el, "label-reader", o);
  return el;
}
// the badge of the reader on this Hub: whether it answers now
function readerBadge(into) {
  api("settings/local-intake").then((r) => into.replaceChildren(SW.t("settings_reader_badge_local"), " ", r.ok ? SW.status("ok", { small: true }) : SW.status("needs_look", { small: true }), r.ok ? "" : " " + SW.t("settings_reader_local_down")),
    () => into.replaceChildren(SW.t("settings_reader_badge_local"), " ", SW.status("needs_look", { small: true }), " " + SW.t("settings_reader_local_down")));
}
// Test (03 10.5): the saved address without the code; an address typed and not saved after unlocking in place, saved nowhere
async function testReader(out, addr, tier, saved) {
  const url = addr._control.value.trim();
  const show = (r) => {
    const tiers = Object.entries(r.tiers || {}).filter(([, t1]) => t1.usable).map(([k]) => k.toUpperCase());
    const list = new Intl.ListFormat("en", { type: "conjunction" }).format(tiers);
    if (!r.ok) { say(out, SW.t("settings_reader_test_none", { address: url }), false); return; }
    if (r.degraded) { say(out, SW.t("settings_reader_test_degraded", { reason: String(r.error || "").replace(/[.]$/, "") }), "warn"); return; }
    say(out, SW.t("settings_reader_test_ok", { version: r.version || "?", api: r.api_version, tiers: list, corrections: SW.t(r.revise ? "settings_reader_corrections_yes" : "settings_reader_corrections_no") }), true);
  };
  const failed = (e) => say(out, e.status === 409 ? SW.t("settings_reader_test_off") : hubText(e.message), false);
  working(out, SW.t("settings_reader_testing"));
  if (url === saved) { try { show(await api("settings/local-intake")); } catch (e) { failed(e); } return; }
  const picked = tier.querySelector("input:checked");
  await needCode(async () => {
    try { show(await api("settings/local-intake/test", { url, tier: picked ? picked.value : "auto", code: theCode() })); } catch (e) { if (e.locked) throw e; failed(e); }
  }, () => SW.result(out, null));
}

// the reader that runs on this machine: install, upgrade, remove, and its token (jobs and one setting; not part of the Save)
function readerInstall(g) {
  const have = g.local_intake_installed, box = sbox(), install = sbox(), tokBox = sbox(), out = h("div");
  const check = () => runJob(box, "local_intake_plan");
  api("settings/local-intake/plan").then((r) => {
    const s = r.saved;
    if (!s) return;
    const p = s.plan, t1 = p.tiers[p.tier], label = SW.t(p.upgrade ? "settings_reader_plan_upgrade" : p.same ? "settings_reader_plan_reinstall" : "settings_reader_plan_install");
    const name = SW.t("settings_reader_plan_button", { label, version: p.version, tier: p.tier });
    fill(out, h("p", { class: "muted", textContent: SW.t("settings_reader_plan_checked", { when: new Date(s.at * 1000).toLocaleString() }) }),
      ...s.text.map((line) => h("p", { textContent: line })),
      t1 && s.fresh && !p.downgrade ? SW.btn(name, { cls: "btn--primary", action: "install-reader", run: (e) => runJob(install, "local_intake_install", { kind: "confirm",
        title: SW.t("settings_local_install_title", { version: p.version }), text: s.text.filter((l) => !l.startsWith("Installed") && !l.startsWith("Other")).join(" "),
        confirm: name, opener: e.currentTarget }) }) : null,
      install,
      !s.fresh ? h("p", { class: "muted", textContent: SW.t("settings_reader_plan_old") }) : null,
      h("p", { class: "muted", textContent: SW.t("settings_reader_plan_tier") }));
  }).catch((e) => say(out, hubText(e.message), false));
  const tok = SW.field({ row: true, type: "secret", label: SW.t("settings_reader_token"), attrs: { "aria-required": "false" } }), set = S.local_intake_token && S.local_intake_token.set;
  const tokSet = SW.btn(SW.t(set ? "common_replace" : "settings_reader_token_set"), { action: "set-token", run: () => act(tokBox, "local_intake_token", { token: tok._control.value },
    () => loadGroup("label-reader", { quiet: true, fresh: true }), [tok._control]) });
  tok._control.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); tokSet.click(); } });
  return h("div", { class: "settings__reader" },
    h("p", { class: "muted", textContent: have ? SW.t("settings_reader_local_installed", { version: have.version, tier: have.tier }) : SW.t("settings_reader_local_not_installed") }),
    h("div", { class: "actions" },
      SW.btn(SW.t(have ? "settings_reader_check_upgrade" : "settings_reader_check_install"), { action: "check-reader", run: check }),
      have ? SW.btn(SW.t("settings_reader_local_remove"), { cls: "btn--ghost btn--danger", action: "remove-reader", run: (e) => runJob(box, "local_intake_remove", { ...destroy("settings_local_remove_title",
        "settings_local_remove_body", "common_remove"), opener: e.currentTarget }) }) : null), box, out,
    h("p", { class: "field__label" }, SW.t("settings_reader_token"), " ", SW.status(set ? "set" : "not_set", { small: true })),
    h("p", { class: "muted", textContent: SW.t("settings_reader_token_hint") }),
    tok, h("div", { class: "actions" }, tokSet,
      set ? SW.btn(SW.t("common_remove"), { cls: "btn--ghost btn--danger", action: "remove-token", run: () => act(tokBox, "local_intake_token/remove", {}, () => loadGroup("label-reader", { quiet: true, fresh: true })) }) : null), tokBox);
}

// ----- Network and addresses (03 10.7) -----
function groupNetwork({ g }) {
  const v = g.values, web = !!g.web_on, setPublic = S.web.public_set;
  const fields = [
    plainField({ name: "web.public_url", mono: true, label: SW.t("settings_network_public"), placeholder: setPublic ? SW.t("settings_network_public_hidden") : SW.t("settings_network_public_placeholder"),
      hint: SW.t(web ? "settings_network_public_hint" : "settings_network_public_hint_off"), effect: "applies" }),
    plainField({ name: "station.url", mono: true, label: SW.t("settings_network_station"), value: S.station.url || "", placeholder: SW.t("settings_network_station_placeholder"),
      hint: SW.t("settings_network_station_hint"), effect: "applies" }),
    plainField({ name: "setup.hosts", mono: true, label: SW.t("settings_network_hosts"), value: (v["setup.hosts"] || []).join(" "), placeholder: SW.t("settings_network_hosts_placeholder"),
      hint: SW.t("settings_network_hosts_hint") }),
  ];
  if (web) fields.push(SW.check({ name: "web.printer_changes", label: SW.t("settings_network_changes"), desc: SW.t("settings_network_changes_hint"), checked: v["web.printer_changes"] === true }));
  fields.push(heading("settings_network_remote"), remoteBlock(g));
  const el = setGroup("network", { desc: SW.t("settings_network_desc"), save: SW.t("settings_network_save"), body: fields });
  const one = (key) => async (value) => {
    try { await api("settings", { key, value: value.trim(), code: theCode() }); } catch (e) { throw setRefusal(el, Object.assign(e, { data: { ...(e.data || {}), field: key } })); }
    return { applies: true };
  };
  const o = { send: null };
  o.send = sender(() => el, () => o.group, { "web.public_url": one("web.public_url"), "station.url": one("station.url") }, { "setup.hosts": (x) => x.split(/[\s,]+/).filter(Boolean) });
  wireGroup(el, "network", o);
  return el;
}
function remoteBlock(g) {
  if (!g.remote_on) return h("p", { class: "muted" }, SW.t("settings_network_remote_off"));
  const box = sbox(), rules = h("div");
  return h("div", { class: "settings__remote" }, h("p", { class: "muted", textContent: SW.t("settings_network_remote_text") }),
    h("div", { class: "actions" },
      SW.btn(SW.t("settings_network_firewall"), { action: "firewall", run: () => act(box, "remote/firewall", {}, (r) => { SW.result(box, null); rules.replaceChildren(codeBlock(r.text, SW.t("settings_network_firewall"))); }) }),
      SW.btn(SW.t("settings_network_certificate"), { action: "certificate", run: (e) => runJob(box, "remote_issue", { kind: "confirm", title: SW.t("settings_certificate_title"),
        text: SW.t("settings_certificate_body"), confirm: SW.t("settings_network_certificate"), opener: e.currentTarget }) })), box, rules);
}

// ----- Web passphrase (03 10.8) -----
function groupPassphrase() {
  const set = S.passphrase.set, one = SW.field({ row: true, type: "secret", name: "passphrase", label: SW.t("settings_passphrase_new"), hint: SW.t("settings_passphrase_new_hint"),
    attrs: { autocomplete: "new-password", minlength: "12" }, check: (x) => (x.length >= 12 ? null : SW.t("settings_passphrase_new_error", { count: x.length })) });
  const two = SW.field({ row: true, type: "secret", name: "again", label: SW.t("settings_passphrase_again"), attrs: { autocomplete: "new-password" },
    check: (x) => (x === one._control.value ? null : SW.t("field_error_passphrase_mismatch")) });
  const el = setGroup("passphrase", { desc: SW.t("settings_passphrase_desc"), save: SW.t(set ? "settings_passphrase_replace" : "settings_passphrase_set"),
    badges: [SW.status(set ? "set" : "not_set", { small: true })],
    body: [S.passphrase.web ? null : h("p", {}, SW.status("note", { small: true }), " ", SW.t("settings_passphrase_web_off")), one, two] });
  const o = { send: async (key, value) => {
    if (key !== "passphrase") return {};
    try { await api("passphrase", { passphrase: value, code: theCode() }); } catch (e) { throw setRefusal(el, Object.assign(e, { data: { ...(e.data || {}), field: "passphrase" } })); }
    return {};
  }, done: () => SW.t("settings_passphrase_done") };
  wireGroup(el, "passphrase", o);
  return el;
}

// ----- Filament Catalog (03 10.9) -----
function groupCatalog({ lib }) {
  const on = S.library_token.library, c = lib.last_check, set = S.library_token.set, none = lib.source === "none";
  const badges = [];
  if (none) badges.push(h("span", { class: "settings__badge", textContent: SW.t("settings_catalog_none") }));
  else if (c && !c.ok) badges.push(h("span", { class: "settings__badge" }, SW.status("needs_look", { small: true }), " " + SW.t("settings_catalog_failed")));
  else badges.push(SW.status("ok", { small: true }));
  const state = h("div", { class: "settings__state-lines" }), box = sbox(), job = sbox(), entryBox = sbox();
  const paint = (l) => {
    const k = l.last_check;
    state.replaceChildren(...[h("p", { textContent: l.source === "none" ? SW.t("settings_catalog_none") : SW.t("settings_catalog_state", { version: l.version, source: l.source, count: l.local }) }),
      h("p", { class: k && !k.ok ? "" : "muted" }, k ? (k.ok ? SW.t("settings_catalog_check_ok", { at: k.at }) : SW.status("needs_look", { small: true, text: SW.t("settings_catalog_check_error", { at: k.at, error: k.error }) }))
        : SW.t("settings_catalog_check_never")),
      l.skipped && h("p", {}, SW.status("note", { small: true, text: l.skipped }))].filter(Boolean));
  };
  paint(lib);
  const token = SW.field({ row: true, type: "secret", name: "library_token", label: SW.t("settings_catalog_token"), hint: SW.t("settings_catalog_token_hint"), attrs: { "aria-required": "false" } });
  token.querySelector(".field__label").append(" ", SW.status(set ? "set" : "not_set", { small: true }));
  const entry = SW.field({ row: true, type: "textarea", mono: true, label: SW.t("settings_catalog_entry"), placeholder: SW.t("settings_catalog_entry_placeholder"), hint: SW.t("settings_catalog_entry_hint"),
    attrs: { "aria-required": "false" } });
  const add = SW.btn(SW.t("settings_catalog_entry_add"), { action: "add-entry", run: () => {
    const text = entry._control.value;
    try { JSON.parse(text); } catch { SW.fieldError(entry, SW.t("settings_catalog_entry_json")); entry._control.focus(); return; }
    SW.fieldError(entry, null);
    act(entryBox, "library/add", { entry: text }, (r) => {
      say(entryBox, SW.t("settings_catalog_entry_added", { line: `${r.vendor} ${r.product}` }), true);
      entry._control.value = "";
      api("library").then(paint, () => {});
    });
  } });
  const body = [];
  if (!on) body.push(offNote("settings_catalog_off"));
  else body.push(state, h("div", { class: "actions" },
    SW.btn(SW.t("settings_catalog_update"), { action: "update-catalog", run: () => runJob(job, "library_update") }),
    SW.btn(SW.t("settings_catalog_back"), { cls: "btn--ghost", action: "catalog-back", run: (e) => runJob(job, "library_rollback", { ...destroy("settings_catalog_back_title", "settings_catalog_back_body",
      "settings_catalog_back_confirm"), opener: e.currentTarget }) })), job);
  body.push(token);
  if (set) body.push(h("div", { class: "actions" }, SW.btn(SW.t("settings_catalog_token_remove"), { cls: "btn--ghost btn--danger", action: "remove-library-token", run: (e) => confirmed(
    { ...destroy("settings_token_remove_title", "settings_token_remove_body", "settings_catalog_token_remove"), opener: e.currentTarget }, "library_token/remove", {},
    () => loadGroup("catalog", { quiet: true, fresh: true })) })));
  body.push(entry, h("div", { class: "actions" }, add), entryBox);
  const el = setGroup("catalog", { desc: SW.t("settings_catalog_desc"), save: SW.t("settings_catalog_save"), badges, body });
  const o = { send: async (key, value) => {
    try { await api("library_token", { token: value, code: theCode() }); } catch (e) { throw setRefusal(el, Object.assign(e, { data: { ...(e.data || {}), field: key } })); }
    return {};
  } };
  wireGroup(el, "catalog", o);
  return el;
}

// ----- Weigh Station voice (03 10.10): applies on choosing, no Save -----
function groupVoice({ g }) {
  if (!g.station_on) return setGroup("voice", { desc: SW.t("settings_voice_desc"), body: [offNote("settings_voice_off")] });
  const res = sbox(), was = g.values["station.tts"] === "espeak" ? "espeak" : "auto";
  const fs = SW.segmented({ legend: SW.t("settings_voice_label"), name: "station.tts", value: was, write: true, result: res,
    options: [{ value: "auto", label: SW.t("settings_voice_piper") }, { value: "espeak", label: SW.t("settings_voice_espeak") }],
    apply: async (value) => {
      try { await api("settings/general", { key: "station.tts", value, code: theCode() }); } catch (e) { throw Object.assign(e, { text: () => hubText(e.message) }); }
      say(res, SW.t(value === "auto" ? "settings_voice_saved_piper" : "settings_voice_saved_espeak"), true);
      if (setSeen.g) setSeen.g.values["station.tts"] = value;
      paintList();
      followApply(true);
    } });
  const lines = h("ul", { class: "settings__lines" }, h("li", { textContent: SW.t("settings_voice_piper") + ": " + SW.t("settings_voice_piper_line") }),
    h("li", { textContent: SW.t("settings_voice_espeak") + ": " + SW.t("settings_voice_espeak_line") }));
  return setGroup("voice", { desc: SW.t("settings_voice_desc"), body: [h("div", { class: "settings__choice" }, fs, lines, res)] });
}
