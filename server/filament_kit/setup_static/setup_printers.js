// The console's Printers section (03 5; 09 S2.4). Loaded after setup.js; everything from the server goes in through textContent, as there.
// A Klipper printer has no Access Code and a Bambu printer no API key: each family's words and controls appear only with its module on.
// The collection, its rows and the drawers are this file's, and so are the Add a printer drawer (03 5.6), the scan (5.4, 5.8) and the Klipper add-on card.
"use strict";

const PRINTERS = "printers";       // the section's name in TABS; its catalogue keys start with it
const printerPath = (p, what) => `printers/${encodeURIComponent(p.serial)}/${what}`;
const nice = (s) => String(s).replace(/_/g, " ");
const hostPort = (p) => `${p.host.includes(":") ? `[${p.host}]` : p.host}:${p.port}`;
const X = (...args) => SW.h(...args);     // the shared element builder: it leaves out what is null (the shared scripts load after this one)
// E(tag, class, [attributes,] ...kids)
const E = (tag, cls, ...kids) => {
  const props = kids[0] && kids[0].constructor === Object ? kids.shift() : {};
  return X(tag, { class: cls, ...props }, ...kids);
};
// a line under a result: a shape and a sentence, in the kind's colour
const line = (kind, shape, text) => E("div", "printers-line", E("span", "status status--" + kind, SW.shape(shape), text));
const klipperOf = (p) => p.family === "klipper";
const lockedNow = () => SW.lock.state === "locked";
// what names a row in the page (data-id, ids, the lane choice): never the serial, which is hidden while Locked (03 2.1); the map stays in this script
const rowKeys = new Map();
const keyOf = (serial) => { if (!rowKeys.has(serial)) rowKeys.set(serial, "p" + (rowKeys.size + 1)); return rowKeys.get(serial); };
const serialOfKey = (key) => { for (const [serial, k] of rowKeys) if (k === key) return serial; return null; };
// a Hub text with the printer's address and serial taken out while Locked
const scrub = (p, text) => (lockedNow() ? [p.ip, p.host, p.serial].filter(Boolean).reduce((t, s) => t.split(s).join(SW.t("common_hidden_locked")), String(text)) : text);
// the address of a row or drawer, as the person may see it: none while Locked
const addressHash = (p, what) => (lockedNow() ? "#printers" : `#printers/${encodeURIComponent(p.serial)}${what ? "/" + what : ""}`);
const addressOf = (p) => (klipperOf(p) ? hostPort(p) : p.ip || "");
const sentence = (s) => { const t = nice(s).trim(); return t ? t[0].toUpperCase() + t.slice(1) + "." : t; };
const laneWord = (m) => SW.t(m === "auto" ? "printers_lane_auto" : m === "on" ? "status_on" : "status_off");

// ----- what the section knows beyond the Hub's list: the last read of `printers/states` (03 2.7), by serial -----
let live = null;
let pollTimer = 0;
const expanded = new Set();        // the rows that are open: kept across the redraw a change brings
let rowViews = new Map();          // the parts of a drawn row that a read patches
let listEl = null;                 // the collection's region
let addonOut = null;               // the add-on card's commands: kept across a redraw of the cards (made when first wanted: SW loads after this script)
let drawnLocked = false;           // whether the list on the page was drawn Locked (addresses and serials left out)
const stateOf = (p) => (live && live[p.serial] ? live[p.serial].state : p.state);
const slotsOf = (p) => (live && live[p.serial] && live[p.serial].slots ? live[p.serial].slots.flatMap((u) => u.slots || []) : null);
const hexOf = (s) => (/^[0-9A-Fa-f]{6}$/.test(s.color_hex || "") ? "#" + s.color_hex : "");
const slotName = (s) => (s.spool && s.spool.name) || s.type || "";

// ----- the state of a printer: the badge and under it the sentence (02 7.1) -----
const FIX = { offline: "printers_fix_offline", wrong_code: "printers_fix_wrong_code", needs_developer_mode: "printers_fix_developer_mode",
  cert_changed: "printers_fix_cert_changed", unauthorized: "printers_fix_unauthorized", klippy_not_ready: "printers_fix_klippy" };
function stateWord(p) {
  const st = p.configured === false ? "not_configured" : stateOf(p);
  return st === "unknown_model" ? "connected" : st;
}
function stateBlock(p) {
  const st = p.configured === false ? "not_configured" : stateOf(p);
  if (st === "connecting") return [E("span", "printers-connecting", SW.spinner(), SW.t("common_connecting"))];
  if (st === "connected" || st === "unknown_model") {
    return [SW.status("connected"), st === "unknown_model" ? E("span", "status status--info status--s", SW.shape("s-diamond"), SW.t("printers_note_unknown_model")) : null];
  }
  if (st === "offline") return [SW.status("offline"), E("span", "coll__sub", SW.t(FIX.offline))];
  if (st === "not_configured") return [SW.status("not_configured"), E("span", "coll__sub", SW.t(klipperOf(p) ? "printers_fix_not_configured_klipper" : "printers_fix_not_configured"))];
  return [SW.status("needs_look"), E("span", "coll__sub", FIX[st] ? SW.t(FIX[st]) : sentence(st))];
}
// a word of the vocabulary for a state the Hub reports after a test
const badgeFor = (st) => SW.status(st === "connected" || st === "unknown_model" ? "connected" : st === "offline" ? "offline" : st === "not_configured" ? "not_configured" : "needs_look");

// ----- slots: the strip in the row and the lines in the expansion -----
function slotStrip(p) {
  const slots = slotsOf(p), st = stateWord(p);
  if (p.configured === false) return [];
  if (st === "offline") return [E("span", "muted", SW.t("printers_slots_offline"))];
  if (!slots || !slots.length) return [E("span", "muted", SW.t("printers_slots_none"))];
  const loaded = slots.filter((s) => s.present).length;
  return [E("div", "slot-strip slot-strip--compact",
    E("span", "slot-strip__swatches", { "aria-hidden": "true" }, slots.map((s) => SW.swatch(hexOf(s), { empty: !s.present }))),
    E("span", "sr", slots.map((s) => (s.present ? `${s.label} ${slotName(s)} ${hexOf(s)}` : SW.t("printers_slot_sr_empty", { slot: s.label }))).join("; ") + "."),
    E("span", "slot-strip__count mono", { "aria-hidden": "true" }, SW.t("slot_count", { loaded, total: slots.length })))];
}
function slotLines(p) {
  const slots = slotsOf(p);
  if (!slots || !slots.length) return E("p", "muted", SW.t(stateWord(p) === "offline" ? "printers_slots_offline" : "printers_slots_none"));
  return X("ul", { class: "slot-strip", "aria-label": SW.t("slot_list_label", { name: p.name }) }, slots.map((s) => X("li", { class: "slot-strip__row", data: { state: s.active ? "active" : null } },
    E("span", "slot-strip__label mono", s.label), SW.swatch(hexOf(s), { empty: !s.present }),
    E("span", "slot-strip__name", s.present ? [slotName(s), " ", E("span", "mono muted", hexOf(s))] : E("span", "muted", SW.t("common_empty"))),
    E("span", "slot-strip__level", s.present && s.spool && s.spool.remaining_weight != null ? E("span", "mono", SW.t("printers_slot_grams", { grams: Math.round(s.spool.remaining_weight) })) : null),
    E("span", "slot-strip__use", s.active ? SW.t("slot_in_use") : ""))));
}

// ----- the result texts of a test (03 5.8): the Hub's sentence read back into the catalogue's; any other text is shown as sent -----
function testResult(p, r) {
  const t = String(r.text || ""), m = (re) => re.exec(t);
  let x, kind = r.reachable;
  // Locked: the same sentence without the address (keys "printers_result_locked_..."); `vars` still carries it and is not shown
  const say1 = (key, vars) => SW.t(lockedNow() ? key.replace("printers_result_", "printers_result_locked_") : key, vars);
  if (klipperOf(p)) {
    if ((x = m(/^Moonraker at (.+):(\d+) answers; Klipper is (.+)$/))) return [say1("printers_result_klipper_ok", { host: x[1], port: x[2], state: x[3] }), true];
    if ((x = m(/^Moonraker at (.+):(\d+) answers but wants an API key/))) return [say1("printers_result_klipper_key", { host: x[1], port: x[2] }), "warn"];
    if ((x = m(/^no answer from Moonraker at (.+):(\d+)/))) return [say1("printers_result_klipper_none", { host: x[1], port: x[2] }), false];
    if ((x = m(/^(.+):(\d+) answers, but not as Moonraker/))) return [say1("printers_result_klipper_other", { host: x[1], port: x[2] }), false];
  } else {
    if ((x = m(/^(.+) answers; its certificate matches the pinned one$/))) return [say1("printers_result_bambu_pinned", { address: x[1] }), true];
    if ((x = m(/^(.+) answers; its certificate not pinned yet/))) return [say1("printers_result_bambu_new", { address: x[1] }), true];
    if ((x = m(/^(.+) answers; its certificate differs/))) return [say1("printers_result_bambu_differs", { address: x[1] }), false];
    if ((x = m(/^no answer from (.+):8883 \((.+)\)/))) return [say1("printers_result_bambu_none", { address: x[1], error_type: x[2] }), false];
  }
  return [hubText(scrub(p, t)), kind];
}
const lastTest = {};
async function testConnection(p, box, button) {
  if (lastTest[p.serial] && Date.now() - lastTest[p.serial] < 3000) { say(box, SW.t("printers_test_wait"), "warn"); return; }
  lastTest[p.serial] = Date.now();
  working(box, testingText(p));
  if (button) SW.busy(button, SW.t("common_testing"));
  try {
    const r = await api(printerPath(p, "test"), {}), [text, kind] = testResult(p, r);
    say(box, [text, " ", badgeFor(r.state)], kind);
  } catch (e) { say(box, scrub(p, e.message), false); } finally { if (button) SW.idle(button); }
}
const testingText = (p) => (lockedNow() ? SW.t("printers_testing_name", { name: p.name }) : SW.t("printers_testing_address", { address: addressOf(p) }));

// ----- Klipper: what it is -----
async function detect(p, box, button) {
  working(box, SW.t("printers_detecting", { name: p.name }));
  if (button) SW.busy(button, SW.t("printers_detecting", { name: p.name }));
  try {
    const d = await api(printerPath(p, "detect"), {});
    if (!d.ok) { say(box, hubText(scrub(p, d.message)), false); return; }
    const model = d.model || SW.t("common_klipper"), slots = (d.slots || []).join(", ");
    const head = SW.t(slots ? (d.verified ? "printers_detected" : "printers_detected_unconfirmed") : (d.verified ? "printers_detected_bare" : "printers_detected_bare_unconfirmed"), { model, slots });
    const warn = d.spoolman && d.spoolman.warning;
    say(box, [head, warn ? line("warn", "s-triangle", hubText(scrub(p, warn))) : null, d.message ? line("info", "s-diamond", hubText(scrub(p, d.message))) : null], true);
  } catch (e) { say(box, scrub(p, e.message), false); } finally { if (button) SW.idle(button); }
}

// a change with its own working text: the code first (as change()), no redraw of the region
async function act(box, label, path, body, done) {
  let out = null;
  await needCode(async () => {
    working(box, label);
    try { out = await api(path, { ...body, code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      say(box, hubText(e.message), false);
      return;
    }
    box._said = null;
    done(out);
  });
  return out;
}
// a result with one button in it (03 8.6)
function sayWith(box, kind, text, action) {
  box._said = [kind, text];
  return SW.result(box, kind, text, { action });
}

// ----- the dialogs of 03 5.5 -----
// `kind`: bambu or klipper (Forget printer), dismiss (a scanned Klipper printer not in use)
function forgetPrinter(p, box, kind) {
  const o = kind === "dismiss" ? destroy("printers_dismiss_title", "printers_dismiss_body", "common_dismiss", { name: p.name })
    : destroy("printers_forget_title", "printers_forget_body_" + kind, "printers_forget", { name: p.name });
  // the row leaves with it: its result is a toast (02 8.7)
  return asking(box, printerPath(p, "forget"), o, undefined,
    () => say(box, SW.t(kind === "dismiss" ? "printers_dismissed" : "printers_forgotten", { name: p.name }), true));
}
const renamePrinter = (p, box) => asking(box, printerPath(p, "rename"), {
  kind: "entry", title: SW.t("printers_rename_title"), confirm: SW.t("common_rename"),
  fields: [entryField({ label: SW.t("common_field_name"), name: "name", value: p.name }, "common_error_name")],
}, ([name]) => ({ name: name.trim() }));
// Bambu Lab: 03 5.5 and 15: the new address takes the Access Code with it, as in the web app and the app
function changeAddress(p, box) {
  const bambu = !klipperOf(p);
  let typed = "";
  return asking(box, printerPath(p, "address"), {
    kind: "entry", title: SW.t("printers_change_address_title", { name: p.name }), confirm: SW.t("printers_change_address"),
    fields: [entryField({ label: SW.t(bambu ? "printers_field_address" : "common_address"), name: "address", value: lockedNow() ? "" : bambu ? p.ip || "" : p.host, mono: true,
      hint: bambu ? SW.t("printers_change_address_hint_bambu") : SW.t("printers_change_address_hint_klipper", { port: p.port }) }, "common_error_address"),
    ...(bambu ? [entryField({ type: "secret", label: SW.t("common_field_access_code"), name: "access_code", mono: true,
      hint: SW.t("printers_change_address_code_hint") }, "common_error_access_code")] : [])],
  }, ([address, access]) => { typed = address.trim(); return { address: typed, ...(bambu ? { access_code: access } : {}) }; },
  (r) => say(box, SW.t("printers_address_changed", { address: typed, note: r.note ? hubText(r.note) : "" }).replace(/\s+/g, " "), true));
}
const accessCode = (p, box) => asking(box, printerPath(p, "code"), {
  kind: "entry", title: SW.t("printers_access_code_title", { name: p.name }), confirm: SW.t(p.configured ? "printers_replace_access_code" : "common_connect"),
  fields: [entryField({ type: "secret", label: SW.t("common_field_access_code"), name: "access_code", mono: true, hint: SW.t("printers_access_code_hint") }, "common_error_access_code")],
}, ([code]) => ({ access_code: code }));
const apiKey = (p, box) => asking(box, printerPath(p, "api_key"), {
  kind: "entry", title: SW.t("printers_key_title", { name: p.name }), confirm: SW.t("common_save_key"),
  fields: [entryField({ type: "secret", label: SW.t("common_moonraker_key"), name: "key", mono: true, hint: SW.t("printers_key_hint") }, "printers_error_key")],
}, ([key]) => ({ key: key.trim() }));
const clearKey = (p, box) => asking(box, printerPath(p, "api_key"),
  destroy("printers_clear_key_title", "printers_clear_key_body", "printers_clear_key_confirm", { name: p.name }), () => ({ key: "" }));
const forgetCertificate = (p, box) => asking(box, printerPath(p, "unpin"), {
  ...destroy("printers_forget_cert_title", "printers_forget_cert_body", "printers_forget_cert", { name: p.name, address: p.ip }),
  fields: [entryField({ type: "secret", label: SW.t("common_field_access_code"), name: "access_code", mono: true, hint: SW.t("printers_forget_cert_hint") }, "common_error_access_code")],
}, ([access]) => ({ access_code: access }));
// a scanned printer goes into use: its key is optional
function usePrinter(p, box) {
  const key = SW.field({ type: "secret", label: SW.t("common_moonraker_key"), optional: true, name: "api_key", mono: true, hint: SW.t("printers_key_hint") });
  return asking(box, printerPath(p, "connect"), { kind: "entry", title: SW.t("printers_use_title", { name: p.name }),
    text: SW.t("printers_use_body", { host: p.host, port: p.port }), confirm: SW.t("printers_use"), fields: [key] },
  ([k]) => ({ api_key: k.trim() }));
}

// ----- printer reports: one XML file, made from an allow-list, for an issue; kept on the server, the last five -----
const reporting = new Set();       // the printers a report is being made for: a second press while it runs sends nothing
async function collectReport(p, box) {
  if (reporting.has(p.serial)) return null;
  reporting.add(p.serial);
  try {
    const inside = () => drawer && drawer.kind === "reports" && drawer.serial === p.serial;
    const r = await act(box, SW.t("printers_reporting", { name: p.name }), printerPath(p, "report"), {}, () => {});
    if (!r) return null;
    await refresh(listEl || box);      // the row is drawn again: "Needs a look" ends with the report
    const text = SW.t("printers_report_saved", { report: r.name, note: r.note || "" }).trim();
    if (inside()) { say(box, text, true); drawer.reload(); }
    else sayWith(box, "ok", text, { label: SW.t("printers_saved_reports"), name: SW.t("printers_reports_title", { name: p.name }), run: () => openReports(p) });
    return r;
  } finally { reporting.delete(p.serial); }
}

// ----- slot mapping: the server's own connection does it, and this follows it in the printer's message row (03 5.7) -----
const mapping = {};
async function startMap(p, box) {
  if (!(await SW.ask({ title: SW.t("printers_map_title", { name: p.name }), text: SW.t("printers_map_body"), confirm: SW.t("printers_map_slots") }))) return;
  const r = await act(box, SW.t("printers_mapping"), printerPath(p, "map"), {}, () => {});
  if (r) { followMap(p, box); return; }
  try { if ((await api(printerPath(p, "map"))).state === "running") followMap(p, box); } catch (e) { /* the refusal is already in the box */ }
}
// the lines under a mapping's end: problems as errors, notes as Notes, the reason a report would help as a warn line
const mapLines = (v) => [...(v.problems || []).map((t) => line("bad", "s-octagon", hubText(t))),
  ...(v.notes || []).map((t) => line("info", "s-diamond", hubText(t))),
  v.report_why ? line("warn", "s-triangle", hubText(v.report_why)) : null];
// the progress and its Stop have a result slot of their own, in the printer's message row beside the printer's other results (a test, a
// detect): they stay for the whole mapping. Leaving the section clears every result on the page, so a row drawn again puts them back (noteRow)
const mapSlots = {}, mapShown = {};
const mapSlot = (p) => mapSlots[p.serial] || (mapSlots[p.serial] = slot());
const showProgress = (p) => { const m = mapShown[p.serial]; if (m) SW.result(mapSlot(p), "run", m.textEl, { action: m.stop }); };
function followMap(p, box) {
  if (mapping[p.serial]) return;
  mapping[p.serial] = true;
  const prog = mapSlot(p);
  const textEl = E("span", null, SW.t("printers_mapping"));     // updated in place: the Stop button beside it keeps its focus
  let shown = false;
  const stop = { label: SW.t("common_stop"), name: SW.t("common_stop") + ": " + p.name,
    run: () => act(box, SW.t("common_working"), printerPath(p, "map/stop"), {}, () => { if (mapping[p.serial]) SW.result(box, null); }) };
  const tick = async () => {
    let v;
    try { v = await api(printerPath(p, "map")); } catch (e) {
      mapping[p.serial] = false;
      delete mapShown[p.serial];
      SW.result(prog, null);
      say(box, scrub(p, e.message), false);
      return;
    }
    if (v.state === "running") {
      textEl.textContent = v.step ? `${SW.t("printers_mapping")} ${v.step}` : SW.t("printers_mapping");
      if (!shown) {
        shown = true;
        if (box.dataset.state === "run") { box._said = null; SW.result(box, null); }      // the working text of the press that started it
        mapShown[p.serial] = { textEl, stop };
        showProgress(p);
      }
      setTimeout(tick, 1500);
      return;
    }
    mapping[p.serial] = false;
    delete mapShown[p.serial];
    SW.result(prog, null);
    if (!v.state || v.state === "none") return;
    const failed = v.state === "failed", slots = (v.slots || []).map((s) => s.label).join(", ");
    const lines = mapLines(v);
    if (failed) sayWith(box, "bad", [SW.t("printers_map_failed"), ...lines, E("div", "muted", SW.t("printers_map_failed_hint"))],
      { label: SW.t("printers_map_loading"), name: SW.t("printers_map_loading") + ": " + p.name, run: () => manualMap(p, box) });
    else say(box, [v.state === "done" ? SW.t("printers_mapped", { slots }) : SW.t("printers_map_state", { state: nice(v.state) }), ...lines], v.state === "done" ? true : "neutral");
  };
  tick();
}

// ----- the drawers (03 5.7): the detail region in a drawer dialog of its own, in every look (SW.openDetail leaves it in place under Panes,
// where a drawer has no place); the dialog is made for each opening and removed when it closes, so nothing typed in it stays in the page -----
let drawer = null;                 // { kind, serial, region, body, running(), reload(), end() }
function openDrawer(kind, p, title, body, foot, o = {}) {
  const id = `drawer-${kind}-${keyOf(p.serial)}`;
  const close = SW.iconBtn("close", SW.t("detail_close", { name: title }), { cls: "detail__close", run: (e) => { e.stopPropagation(); requestClose(); } });
  const region = X("section", { class: "detail detail--drawer", id, "aria-labelledby": id + "-title" },
    E("header", "detail__head", X("h2", { class: "detail__title", id: id + "-title", tabindex: "-1", text: title }), close),
    E("div", "drawer__body", body), foot ? E("div", "detail__foot", foot) : null);
  const dlg = X("dialog", { class: "dialog dialog--drawer", "aria-labelledby": id + "-title" }, region);
  const address = o.address || `#printers/${encodeURIComponent(p.serial)}/${kind}`, back = o.back || addressHash(p);
  drawer = { kind, serial: p.serial, address, region, running: () => false, busy: () => false, dirty: () => 0, reload() {}, end() {}, ...o };
  setTitle(title);
  SW.modal(dlg, { temp: true, scrim: true });
  dlg.addEventListener("cancel", (e) => {       // Escape and the scrim ask first while a mapping runs, or a form has changes
    if (drawer && drawer.region === region && (drawer.running() || drawer.busy() || drawer.dirty())) { e.preventDefault(); requestClose(); }
    else if (region.querySelector('form[data-state="dirty"]')) { e.preventDefault(); SW.closeDetail(region); }
  });
  dlg.addEventListener("close", () => {
    for (const f of dlg.querySelectorAll("input[type=password]")) f.value = "";      // a secret typed here is gone with the drawer
    const d = drawer;
    if (!d || d.region !== region) return;
    d.end();
    drawer = null;
    if (location.hash === address) {      // closed by the person: the address goes back to the row (or the section)
      history.replaceState(null, "", back);
      setTitle(expandedTitle());
    }
  }, { once: true });
  SW.openModal(dlg, o.opener);
  region.querySelector(".detail__title").focus({ preventScroll: true });
  return drawer;
}
// the drawer host closes with an event of its own, a moment after close(): a drawer opened before it would be taken for the closed one
function closeDrawerAsync() {
  if (!drawer) return Promise.resolve();
  const d = drawer, dlg = d.region.closest("dialog");
  d.end();
  if (!dlg) { drawer = null; return Promise.resolve(); }      // already gone with its dialog
  return new Promise((done) => { dlg.addEventListener("close", () => setTimeout(done), { once: true }); dlg.close(); });
}
// closing a running mapping asks first (03 5.7): the positions confirmed so far are kept
async function requestClose() {
  const d = drawer;
  if (!d) return;
  if (d.busy()) { say(d.result, SW.t("common_busy_wait"), "warn"); return; }
  if (d.running()) {
    const p = (S.printers.list.find((x) => x.serial === d.serial)) || { name: d.serial };
    const stopIt = await SW.ask({ kind: "destructive", title: SW.t("printers_load_stop_title", { name: p.name }), text: SW.t("printers_load_stop_body"),
      confirm: SW.t("printers_load_stop"), cancel: SW.t("printers_load_keep") });
    if (!stopIt) return;
    if (d.stop) await d.stop();
  } else if (d.dirty() && !(await SW.leaveAsk(SW.t("form_leave_first", { count: d.dirty(), group: SW.t("printers_add") })))) return;
  if (drawer === d) SW.closeDetail(d.region);
}
// the address names a place inside the section: a row, a drawer on it
function addressNow() {
  const [section, id, what] = location.hash.slice(1).split("/").map((s) => { try { return decodeURIComponent(s); } catch { return s; } });
  return section === PRINTERS ? { id: id || "", what: what || "" } : { id: "", what: "" };
}
// while Locked the serial is not put into the address: a drawer opened then has none (Saved reports shows the locked note)
function pushAddress(p, what) { if (!lockedNow()) history.pushState(null, "", addressHash(p, what)); }

// ----- Saved reports -----
async function openReports(p) {
  await closeDrawerAsync();
  if (location.hash !== `#printers/${encodeURIComponent(p.serial)}/reports`) pushAddress(p, "reports");
  const list = E("div"), never = E("p", "muted"), result = E("p", "result result--block", { role: "status" });
  const title = SW.t("printers_reports_title", { name: p.name });
  const load = async () => {
    const v = await api(printerPath(p, "reports"), { code: theCode() });
    never.textContent = v.never || "";
    list.replaceChildren(v.reports.length ? reportTable(p, v.reports, result) : E("p", "muted", SW.t("printers_reports_empty")));
  };
  const body = E("div", null, codeRead("printers_reports_locked", list, load), never);
  const collect = SW.btn(SW.t("printers_collect_report"), { cls: "btn--primary", run: () => collectReport(p, result) });
  const d = openDrawer("reports", p, title, body, [result, collect], { opener: document.activeElement });
  d.reload = () => { if (SW.lock.state !== "locked") load().catch((e) => say(list, e.message, false)); };
}
function reportTable(p, reports, result) {
  const cols = [["report", "printers_reports_col_report"], ["size", "common_col_size"], ["actions", "common_actions"]];
  return X("div", { class: "coll coll--reports", role: "table", "aria-label": SW.t("printers_reports_title", { name: p.name }) },
    E("div", "coll__head", { role: "rowgroup" }, E("div", "coll__row", { role: "row" }, cols.map(([col, key]) =>
      X("div", { class: "coll__cell", role: "columnheader", "data-col": col }, col === "actions" ? E("span", "sr", SW.t(key)) : SW.t(key))))),
    reports.map((r) => E("div", "coll__item", { role: "rowgroup", "data-id": r.name }, E("div", "coll__row", { role: "row" },
      pcell("report", [E("span", "mono", r.name), r.at ? E("span", "coll__sub", `${SW.t("printers_reports_made")} ${new Date(r.at * 1000).toLocaleString()}`) : null], SW.t("printers_reports_col_report")),
      pcell("size", SW.t("printers_reports_size", { size: Math.max(1, Math.round(r.size / 1024)) }), SW.t("common_col_size")),
      pcell("actions", SW.btn(SW.t("common_download"), { cls: "btn--ghost", name: `${SW.t("common_download")}: ${r.name}`,
        run: () => coded(result, () => download(printerPath(p, `reports/${encodeURIComponent(r.name)}`), { code: theCode() }, r.name)) }))))));
}
const pcell = (col, content, key) => X("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": col === "address" || col === "connection" ? 3 : 1 },
  key ? E("span", "coll__key", { "aria-hidden": "true" }, key) : null, content);

// ----- Map by loading filament: the owner loads each slot, the printer says which one it sees -----
const manualOn = {};
const starting = new Set();        // the printers a session is being started for: a second press while it starts sends nothing
// `start`: the button was pressed (the Hub starts the session, with the code); otherwise the address opened it, and a session that is
// running shows as it is, with a Start button when none is
async function manualMap(p, box, start = true) {
  const base = printerPath(p, "manual-map");
  let v = null;
  if (start) {
    if (starting.has(p.serial)) return;
    starting.add(p.serial);
  }
  try {
    if (start) await coded(box, async () => { v = await api(base + "/start", { code: theCode() }); });
    else {
      try { v = await api(base); } catch (e) { if (e.status !== 404 && e.status !== 409) throw e; }
    }
    if (start && !v) return;
    await closeDrawerAsync();
    openLoadDrawer(p, box, v);
  } finally { if (start) starting.delete(p.serial); }
}
function openLoadDrawer(p, box, first) {
  const base = printerPath(p, "manual-map");
  if (location.hash !== `#printers/${encodeURIComponent(p.serial)}/load-map`) pushAddress(p, "load-map");
  const sheet = E("div"), note = E("p", "result result--block", { role: "status" });
  let v = first || { open: false, positions: [], summary: "" }, shown = { pos: null, vals: {} }, picks = {}, timer = 0, ended = false;
  const send = (what, body) => coded(note, async () => { v = await api(`${base}/${what}`, { session: v.session, code: theCode(), ...body }); draw(); });
  const offer = (share) => coded(note, async () => {      // its answer is a line, not the session: the part is redrawn from v
    const r = await api(`${base}/offer`, { session: v.session, code: theCode(), share }); v.offer_report = false; draw(); say(note, r.message, true);
  });
  const begin = async () => {
    if (starting.has(p.serial)) return;
    starting.add(p.serial);
    try { await coded(note, async () => { v = await api(base + "/start", { code: theCode() }); draw(); loop(); }); } finally { starting.delete(p.serial); }
  };
  const stop = () => (v && v.open ? send("stop", {}) : Promise.resolve());
  openDrawer("load-map", p, SW.t("printers_load_title", { name: p.name }), [sheet, note], null,
    { opener: document.activeElement, running: () => !!(v && v.open), stop, end: () => { ended = true; clearTimeout(timer); manualOn[p.serial] = false; } });
  const status = (q) => (q.status === "confirmed" ? SW.status("done", { text: SW.t(q.nozzle ? "printers_load_confirmed" : "printers_load_confirmed_plain", { label: q.reported_label, nozzle: q.nozzle }) })
    : q.status === "by_hand" ? SW.status("note", { text: SW.t("printers_load_by_hand", { label: q.reported_label }) })
    : !q.status || q.status === "pending" || q.status === "waiting" ? SW.status("not_set", { text: SW.t("printers_load_waiting") }) : SW.status("off", { text: sentence(q.status).replace(/\.$/, "") }));
  // a redraw rebuilds the selects: a choice the owner is making survives it while the same position is asked
  const keep = (k, f) => {
    picks[k] = f._control;
    if (shown.vals[k] !== undefined && [...f._control.options].some((o) => o.value === shown.vals[k])) f._control.value = shown.vals[k];
    return f;
  };
  const draw = () => {
    if (ended) return;
    const st = v.step, pos = st ? st.position.id : null;
    shown = { pos, vals: shown.pos === pos ? Object.fromEntries(Object.entries(picks).map(([k, e]) => [k, e.value])) : {} };
    picks = {};
    let ask = null;
    if (st && st.seen && st.ask) {
      const other = keep("other", SW.field({ type: "select", label: SW.t("printers_load_no"), name: "other", options: v.positions.map((q) => ({ value: q.id, label: q.label })), value: st.position.id }));
      const noz = v.dual_nozzle && !st.seen.nozzle_reported ? keep("noz", SW.field({ type: "select", label: SW.t("common_field_nozzle"), name: "nozzle",
        options: [{ value: "right", label: SW.t("printers_load_nozzle_right") }, { value: "left", label: SW.t("printers_load_nozzle_left") }] })) : null;
      const nozzle = () => (st.seen.nozzle_reported ? st.seen.nozzle : noz ? noz._control.value : null);
      ask = E("div", "printers-ask", E("p", null, st.ask), noz,
        E("div", "actions", SW.btn(SW.t("common_yes"), { cls: "btn--primary", run: () => send("confirm", { position: st.position.id, reported: st.seen.reported, nozzle: nozzle() }) })),
        E("div", "printers-ask__other", other, SW.btn(SW.t("printers_load_save"), { run: () => send("confirm", { position: other._control.value, reported: st.seen.reported, nozzle: nozzle() }) })));
    } else if (st && !v.reports_loads) {
      const pick = keep("pick", SW.field({ type: "select", label: SW.t("printers_load_slot"), name: "slot", options: (v.choices || []).map((c, i) => ({ value: String(i), label: c.label })) }));
      ask = E("div", "printers-ask", pick, E("div", "actions", SW.btn(SW.t("printers_load_save_unchecked"), { cls: "btn--primary",
        run: () => send("confirm", { position: st.position.id, reported: v.choices[Number(pick._control.value)].reported, by_hand: true }) })));
    } else if (st && st.seen && !st.seen.settled) {
      ask = E("p", "muted", SW.spinner(), SW.t("printers_load_settling"));
    }
    const positions = X("div", { class: "coll coll--load", role: "table", "aria-label": SW.t("printers_manual_positions") },
      E("div", "coll__head", { role: "rowgroup" }, E("div", "coll__row", { role: "row" },
        ["position", "status"].map((c) => X("div", { class: "coll__cell", role: "columnheader", "data-col": c }, SW.t(c === "position" ? "printers_load_col_position" : "common_field_status"))))),
      v.positions.map((q) => E("div", "coll__item", { role: "rowgroup", "data-id": q.id }, E("div", "coll__row", { role: "row" },
        pcell("position", E("span", "mono", q.label), SW.t("printers_load_col_position")), pcell("status", status(q), SW.t("common_field_status"))))));
    const idle = !st && !v.open && !v.summary;
    sheet.replaceChildren(...[
      E("p", null, st ? st.say : v.summary || SW.t("printers_load_idle")),
      ask,
      st ? E("div", "actions",
        SW.btn(SW.t("printers_load_skip", { position: st.position.label }), { cls: "btn--ghost", run: () => send("skip", { position: st.position.id }) }),
        SW.btn(SW.t("printers_load_stop"), { run: () => send("stop", {}) })) : null,
      st && v.summary ? E("p", "muted", v.summary) : null,
      idle ? E("div", "actions", SW.btn(SW.t("printers_manual_start"), { cls: "btn--primary", run: begin })) : positions,
      !v.open && v.offer_report ? E("div", "printers-offer", E("p", null, SW.t("printers_load_offer")),
        E("div", "actions", SW.btn(SW.t("printers_load_offer_yes"), { cls: "btn--primary", run: () => offer(true) }), SW.btn(SW.t("printers_load_offer_no"), { run: () => offer(false) }))) : null,
    ].filter(Boolean));
  };
  const loop = () => {
    clearTimeout(timer);
    manualOn[p.serial] = true;
    const tick = async () => {
      if (ended) return;
      if (!v || !v.open) { manualOn[p.serial] = false; return; }
      const was = JSON.stringify(v);
      try { v = await api(base); } catch (e) { manualOn[p.serial] = false; say(note, e.message, false); return; }
      if (JSON.stringify(v) !== was) draw();     // unchanged: an open list or a choice being made stays as it is
      timer = setTimeout(tick, 2000);
    };
    timer = setTimeout(tick, 2000);
  };
  draw();
  if (v.open) loop();
}
// the section's own button in the message row after a failed mapping, and the menu, start the session
const loadByHand = (p, box) => manualMap(p, box, true);

// ----- the row's actions: one list for the buttons of the expansion and the overflow menu (03 5.3) -----
function actionsOf(p, box) {
  const klip = klipperOf(p), why = !klip && p.report_why;
  const act1 = [], change1 = [], remove1 = [];
  if (!klip && !p.configured) act1.push({ label: SW.t("common_connect"), primary: true, run: () => accessCode(p, box) });
  else if (klip) {
    act1.push({ label: SW.t("printers_detect"), primary: true, run: (b) => detect(p, box, b) });
    act1.push({ label: SW.t("printers_map_loading"), run: () => loadByHand(p, box) });
  } else {
    act1.push({ label: SW.t("printers_map_slots"), primary: !why, run: () => startMap(p, box) });
    act1.push({ label: SW.t("printers_map_loading"), run: () => loadByHand(p, box) });
  }
  change1.push({ label: SW.t("common_rename"), run: () => renamePrinter(p, box) }, { label: SW.t("printers_change_address"), run: () => changeAddress(p, box) });
  if (klip) {
    change1.push({ label: SW.t(p.api_key ? "printers_replace_key" : "printers_set_key"), run: () => apiKey(p, box) });
    if (p.api_key) change1.push({ label: SW.t("printers_clear_key"), run: () => clearKey(p, box) });
  } else if (p.configured) {
    change1.push({ label: SW.t("printers_replace_access_code"), run: () => accessCode(p, box) },
      { label: SW.t("printers_collect_report"), run: () => collectReport(p, box) },
      { label: SW.t("printers_saved_reports"), run: () => openReports(p) });
    if (p.pinned) remove1.push({ label: SW.t("printers_forget_cert"), danger: true, run: () => forgetCertificate(p, box) });
  }
  remove1.push({ label: SW.t("printers_forget"), danger: true, run: () => forgetPrinter(p, box, klip ? "klipper" : "bambu") });
  return { act1, change1, remove1 };
}
const actionButton = (a) => {
  const b = SW.btn(a.label, { cls: a.primary ? "btn--primary" : "" });
  b.addEventListener("click", () => a.run(b));
  return b;
};
const ghostButton = (a) => {
  const b = SW.btn(a.label, { cls: "btn--ghost" });
  b.addEventListener("click", () => a.run(b));
  return b;
};
const dangerButton = (a) => {
  const b = SW.btn(a.label, { cls: "btn--danger" });
  b.addEventListener("click", () => a.run(b));
  return b;
};

// ----- the expansion of a row (03 5.3) -----
function kv(rows) {
  return X("dl", { class: "kv" }, rows.map(([key, value, o = {}]) => E("div", "kv__row", E("dt", "kv__key", key),
    E("dd", "kv__value", o.node ? o.node : value == null ? E("span", "muted", SW.t("common_empty")) : E("span", o.mono ? "mono" : null, value), o.badge || null))));
}
function laneChoice(p, box) {
  const fs = SW.segmented({ legend: SW.t("printers_fact_lane_data"), name: "lane-" + keyOf(p.serial), value: p.lane_data || "auto", write: true, result: box, wide: false,
    options: ["auto", "on", "off"].map((m) => ({ value: m, label: laneWord(m) })),
    apply: async (mode) => {
      await api(printerPath(p, "lane_data"), { mode, code: theCode() });
      await refresh(box);
      say(box, SW.t("printers_lane_saved", { mode: laneWord(mode) }), true);
    } });
  return E("div", "printers-lane", fs, E("p", "field__hint", SW.t("printers_lane_hint")));
}
function facts(p, box) {
  const hidden = lockedNow(), h_ = E("span", "muted", SW.t("common_hidden_locked"));
  if (klipperOf(p)) return kv([[SW.t("common_address"), hidden ? null : hostPort(p), { mono: true, node: hidden ? h_ : null }],
    [SW.t("common_moonraker_key"), null, { badge: SW.status(p.api_key ? "set" : "not_set"), node: E("span") }],
    [SW.t("printers_fact_lane_data"), null, { node: laneChoice(p, box) }]]);
  return kv([[SW.t("common_address"), hidden ? null : p.ip || SW.t("printers_no_address"), { mono: true, node: hidden ? h_ : null }],
    [SW.t("printers_fact_serial"), hidden ? null : p.serial, { mono: true, node: hidden ? E("span", "muted", SW.t("common_hidden_locked")) : null }],
    [SW.t("common_field_access_code"), null, { node: E("span", null, p.configured ? SW.t("common_saved_hidden") : null), badge: p.configured ? null : SW.status("not_set") }],
    [SW.t("printers_fact_certificate"), SW.t(p.pinned ? "printers_cert_pinned_short" : "printers_cert_not_pinned_short")]]);
}
function detailRegion(p, box, acts) {
  const id = "detail-" + keyOf(p.serial), slotsBox = E("div", "printers-slots");
  slotsBox.append(slotLines(p));
  rowViews.get(p.serial).detailSlots = slotsBox;
  const back = SW.iconBtn("chevron", SW.t("detail_back", { name: SW.t("nav_printers") }), { cls: "detail__back" });
  const close = SW.iconBtn("close", SW.t("detail_close", { name: p.name }), { cls: "detail__close" });
  const testBtn = SW.btn(SW.t("printers_test"), { cls: "btn panes-only", name: SW.t("printers_test_name", { name: p.name }), run: (e) => testConnection(p, box, e.currentTarget) });
  const region = X("section", { class: "detail", id, "aria-labelledby": id + "-title", hidden: !expanded.has(p.serial) },
    E("header", "detail__head", back, X("h2", { class: "detail__title", id: id + "-title", tabindex: "-1", text: p.name }), rowViews.get(p.serial).detailStatus = E("span", null, stateBlock(p)[0]), close),
    E("div", "detail__body",
      E("div", "detail__section", E("h3", "detail__heading", SW.t(klipperOf(p) ? "printers_slots_tool" : "printers_slots_ams")), slotsBox, facts(p, box)),
      E("div", "detail__section",
        E("h3", "detail__heading", SW.t("printers_group_actions")), E("div", "actions", [testBtn, ...acts.act1.map(actionButton)]),
        E("h3", "detail__heading", SW.t("printers_group_change")), E("div", "actions actions--list", acts.change1.map(ghostButton)),
        E("div", "detail__remove", E("h3", "detail__heading", SW.t("printers_group_remove")), E("div", "actions", acts.remove1.map(dangerButton))))));
  region.addEventListener("sw:detail-close", () => {
    expanded.delete(p.serial);
    if (!drawer && location.hash === addressHash(p)) history.replaceState(null, "", "#printers");
    setTitle(expandedTitle());
  });
  return region;
}

// ----- a printer's row: the main row, its message row and its expansion (03 5.2) -----
function tagOf(p) { return S.printers.bambu && S.printers.klipper ? E("span", "printers-tag", SW.t(klipperOf(p) ? "common_klipper" : "common_bambu_lab")) : null; }
function addressCell(p) {
  if (lockedNow()) return [E("span", "muted", SW.t("common_hidden_locked"))];
  const sub = klipperOf(p) ? SW.t("printers_moonraker") : p.serial ? SW.t("printers_serial_line", { serial: p.serial }) : null;
  return [p.ip || p.host ? E("span", "mono", addressOf(p)) : E("span", "muted", SW.t("printers_no_address")), sub ? E("span", "coll__sub", sub) : null];
}
function connectionCell(p) {
  if (klipperOf(p)) return [E("span", null, SW.t("common_moonraker_key"), " ", SW.status(p.api_key ? "set" : "not_set", { small: true })),
    E("span", "coll__sub", SW.t("printers_lane_data_line", { mode: laneWord(p.lane_data || "auto") }))];
  const mapped = live && live[p.serial] && live[p.serial].mapped;
  return [E("span", null, SW.t(p.pinned ? "printers_cert_pinned" : "printers_cert_not_pinned")), mapped ? E("span", "coll__sub", SW.t("printers_slots_mapped")) : null];
}
function setCell(c, ...kids) {
  if (c.contains(document.activeElement)) return;
  const key = c.querySelector(":scope > .coll__key");
  c.replaceChildren(...(key ? [key] : []), ...kids.flat().filter(Boolean));
}
// the message row: the problem line of a printer that needs a report, and under it the printer's latest result
function noteRow(p, box) {
  const why = !klipperOf(p) && p.configured ? p.report_why : "";
  const problem = why ? E("div", "printers-problem", E("span", "status status--warn", SW.shape("s-triangle"), SW.t("printers_needs_look", { reason: why.replace(/\.$/, "") })),
    SW.btn(SW.t("printers_collect_report"), { cls: "btn--primary", name: SW.t("printers_collect_name", { name: p.name }), run: () => collectReport(p, box) })) : null;
  const prog = mapSlot(p);      // a mapping's progress and Stop: the same slot each time the row is drawn
  showProgress(p);
  const row = E("div", "coll__row coll__row--note", { role: "row" }, X("div", { class: "coll__cell", role: "cell", "aria-colspan": 7 }, problem, prog, box));
  watchNote(row, [box, prog], () => !!(why || box.dataset.state || prog.dataset.state));
  return row;
}
// the message row shows while anything is in it; one observer for the row, dropped when the list is drawn again
const watchers = new Set();
function watchNote(row, slots, shown) {
  const sync = () => { row.hidden = !shown(); };
  sync();
  const o = new MutationObserver(sync);
  for (const s of slots) o.observe(s, { attributes: true, attributeFilter: ["data-state"] });
  watchers.add(o);
}
function printerItem(p) {
  const box = boxFor("printer:" + p.serial), acts = actionsOf(p, box), id = "detail-" + keyOf(p.serial), open = expanded.has(p.serial) && SW.profile().detail !== "sheet";
  rowViews.set(p.serial, {});
  const view = rowViews.get(p.serial);
  if (p.mapping) followMap(p, box);      // a job already running (a reload, another browser): progress and Stop again
  const test = SW.btn([E("span", "printers-long", SW.t("printers_test")), E("span", "printers-short", SW.t("printers_test_short"))], { name: SW.t("printers_test_name", { name: p.name }), run: (e) => testConnection(p, box, e.currentTarget) });
  const more = SW.iconBtn("more", SW.t("common_more_actions_for", { name: p.name }), {});
  SW.menu(more, () => [...acts.act1.map(menuItem), { separator: true }, ...acts.change1.map(menuItem), { separator: true }, ...acts.remove1.map(menuItem)].filter((it, i, all) => !(it.separator && (i === 0 || all[i - 1].separator))), { label: SW.t("common_actions_for", { name: p.name }) });
  const expand = X("button", { class: "btn btn--ghost btn--icon coll__expand", type: "button", "aria-expanded": String(open), "aria-controls": id, "aria-label": SW.t("detail_for", { name: p.name }) },
    SW.icon("chevron"), E("span", "printers-expand__label", SW.t("common_details")));
  const st = E("div", "printers-state"), sl = E("div", "printers-slots-cell");
  st.replaceChildren(...stateBlock(p).filter(Boolean));
  sl.replaceChildren(...slotStrip(p));
  const cells = {
    title: X("div", { class: "coll__cell", role: "cell", "data-col": "title", "data-prio": 1, "data-sort": p.name },
      X("a", { class: "coll__title", href: addressHash(p), text: p.name }), tagOf(p), p.model ? E("span", "coll__sub", p.model) : null),
    address: X("div", { class: "coll__cell", role: "cell", "data-col": "address", "data-prio": 3, "data-sort": lockedNow() ? "" : addressOf(p) }, E("span", "coll__key", { "aria-hidden": "true" }, SW.t("common_address")), addressCell(p)),
    status: X("div", { class: "coll__cell", role: "cell", "data-col": "status", "data-prio": 1, "data-sort": stateWord(p) }, st),
    slots: X("div", { class: "coll__cell", role: "cell", "data-col": "slots", "data-prio": 1 }, E("span", "coll__key", { "aria-hidden": "true" }, SW.t("printers_col_slots")), sl),
    connection: X("div", { class: "coll__cell", role: "cell", "data-col": "connection", "data-prio": 3 }, E("span", "coll__key", { "aria-hidden": "true" }, SW.t("printers_col_connection")), connectionCell(p)),
  };
  Object.assign(view, { p, statusEl: st, slotsEl: sl, statusCell: cells.status, addressCell: cells.address, connectionCell: cells.connection });
  const detail = detailRegion(p, box, acts);
  return X("div", { class: "coll__item", role: "rowgroup", "data-id": keyOf(p.serial) },
    E("div", "coll__row", { role: "row" },
      X("div", { class: "coll__cell", role: "cell", "data-col": "expand" }, expand),
      cells.title, cells.address, cells.status, cells.slots, cells.connection,
      X("div", { class: "coll__cell", role: "cell", "data-col": "actions" }, E("div", "actions", test, more))),
    noteRow(p, box),
    E("div", "coll__row coll__row--detail", { role: "row", hidden: !open }, X("div", { class: "coll__cell", role: "cell", "aria-colspan": 7 }, detail)));
}
const menuItem = (a) => ({ label: a.label, danger: a.danger, run: () => a.run(null) });

// a printer a scan found and nobody has put into use (03 5.2): Use this printer, Test connection, Dismiss
function foundItem(p) {
  const box = boxFor("printer:" + p.serial);
  const test = SW.btn([E("span", "printers-long", SW.t("printers_test")), E("span", "printers-short", SW.t("printers_test_short"))], { name: SW.t("printers_test_name", { name: p.name }), run: (e) => testConnection(p, box, e.currentTarget) });
  const row = E("div", "coll__row", { role: "row" },
    X("div", { class: "coll__cell", role: "cell", "data-col": "expand" }),
    X("div", { class: "coll__cell", role: "cell", "data-col": "title", "data-prio": 1 }, E("span", "coll__title-text", p.name), tagOf(p)),
    X("div", { class: "coll__cell", role: "cell", "data-col": "address", "data-prio": 3 }, E("span", "coll__key", { "aria-hidden": "true" }, SW.t("common_address")),
      lockedNow() ? E("span", "muted", SW.t("common_hidden_locked")) : [E("span", "mono", hostPort(p)), E("span", "coll__sub", SW.t("printers_moonraker"))]),
    X("div", { class: "coll__cell", role: "cell", "data-col": "status", "data-prio": 1 }, E("div", "printers-state", SW.status("not_configured"))),
    X("div", { class: "coll__cell", role: "cell", "data-col": "slots", "data-prio": 1 }),
    X("div", { class: "coll__cell", role: "cell", "data-col": "connection", "data-prio": 3 }),
    X("div", { class: "coll__cell", role: "cell", "data-col": "actions" }, E("div", "actions",
      SW.btn(SW.t("printers_use"), { cls: "btn--primary", name: SW.t("printers_use_name", { name: p.name }), run: () => usePrinter(p, box) }), test,
      SW.btn(SW.t("common_dismiss"), { cls: "btn--ghost", name: SW.t("printers_dismiss_name", { name: p.name }), run: () => forgetPrinter(p, box, "dismiss") }))));
  const note = E("div", "coll__row coll__row--note", { role: "row" }, X("div", { class: "coll__cell", role: "cell", "aria-colspan": 7 }, box));
  watchNote(note, [box], () => !!box.dataset.state);
  return X("div", { class: "coll__item", role: "rowgroup", "data-id": keyOf(p.serial), data: { state: "off" } }, row, note);
}

// ----- the collection (03 5.2) -----
const COLUMNS = [["expand", "common_details", 0, true], ["title", "printers_col_printer", 1], ["address", "common_address", 3], ["status", "common_field_state", 1],
  ["slots", "printers_col_slots", 1], ["connection", "printers_col_connection", 3], ["actions", "common_actions", 1, true]];
function printerTable(found, configured) {
  const head = E("div", "coll__head", { role: "rowgroup" }, E("div", "coll__row", { role: "row" }, COLUMNS.map(([col, key, prio, hiddenName]) => {
    const label = SW.t(key);
    return X("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio || null },
      hiddenName ? E("span", "sr", label) : ["title", "address", "status"].includes(col) ? X("button", { class: "coll__sort", type: "button", "data-sort": col }, label, SW.icon("chevron", "icon--s")) : label);
  })));
  const group = found.length ? E("div", "printers-found", E("div", "coll__item", { role: "rowgroup" }, E("div", "coll__row", { role: "row" },
    X("div", { class: "coll__cell", role: "cell", "aria-colspan": 7 }, E("strong", null, SW.t("printers_found_group"))))), found.map(foundItem)) : null;
  const table = X("div", { class: "coll coll--printers", role: "table", "aria-label": SW.t("nav_printers") }, head, configured.map(printerItem), group);
  SW.collection(table, { name: "printers", sort: "title:ascending", emptyPane: SW.t("printers_pane_empty") });
  if (group) table.append(group);
  table.addEventListener("click", (e) => {
    const t = e.target.closest(".coll__sort");
    if (t && group) queueMicrotask(() => table.append(group));       // the found group stays last when the sort puts the items back
    const link = e.target.closest("a.coll__title");
    const btn = e.target.closest(".coll__expand") || (link && link.closest(".coll__item").querySelector(".coll__expand"));
    if (!btn) return;
    if (link) { e.preventDefault(); btn.click(); return; }
    const serialOf = (b) => serialOfKey(b.getAttribute("aria-controls").replace(/^detail-/, ""));
    const id = serialOf(btn), open = btn.getAttribute("aria-expanded") === "true";
    if (open) {
      if (SW.phone()) for (const o of table.querySelectorAll('.coll__expand[aria-expanded="true"]')) if (o !== btn) { expanded.delete(serialOf(o)); o.click(); }
      expanded.add(id);
    } else expanded.delete(id);
    // an address the person typed that already names this row stays as it is, also while Locked
    if (!drawer && /^#printers(\/[^/]*)?$/.test(location.hash) && !(open && addressNow().id === id)) history.replaceState(null, "", open ? addressHash({ serial: id }) : "#printers");
    setTitle(expandedTitle());
  });
  return table;
}
// the document title of an open row (03 1.2): "<name> · <hub>"
function expandedTitle() {
  const a = addressNow(), p = a.id && !a.what && S.printers.list.find((x) => x.serial === a.id);
  return p ? p.name : null;
}
let titleOverride = null;
function setTitle(page) {
  titleOverride = page ? SW.t("shell_title", { page, hub: S.server_name }) : null;
  if (titleOverride) document.title = titleOverride;
  else if (typeof shellView !== "undefined" && shellView) shellView.paint(false);
}
new MutationObserver(() => { if (titleOverride && tabNow() === PRINTERS && document.title !== titleOverride) document.title = titleOverride; })
  .observe(document.querySelector("title") || document.head, { childList: true, characterData: true, subtree: true });
window.addEventListener("hashchange", () => { if (tabNow() !== PRINTERS) { titleOverride = null; if (addonOut) addonOut.replaceChildren(); } });

// the live printer view is the web app's Printers tab, served by the same Hub
const liveUrl = () => location.pathname.replace(/\/(setup)?\/?$/, "") + "/intake#printers";
// the header: what is there, and the three ways to the rest (03 5.1)
function printersMeta(list, found) {
  const on = list.filter((p) => p.configured), up = on.filter((p) => stateOf(p) === "connected").length;
  const parts = [E("span", null, SW.t("printers_meta_total", { count: on.length })),
    on.length ? SW.status("connected", { text: SW.t("printers_meta_connected", { count: up }) }) : null,
    on.length - up > 0 ? SW.status("offline", { text: SW.t("printers_meta_offline", { count: on.length - up }) }) : null,
    found.length ? SW.status("note", { text: SW.t("printers_meta_found", { count: found.length }) }) : null];
  return E("p", "page-head__meta printers-meta", parts.filter(Boolean));
}
const regionOfMake = (make) => [...sections.children].find((r) => r._make === make);
function goTo(make) {
  const r = regionOfMake(make);
  if (!r) return;
  r.scrollIntoView({ block: "start", behavior: "smooth" });
  const f = r.querySelector("input, select");
  if (f) f.focus({ preventScroll: true });
}
function header(found) {
  const P = S.printers;
  const url = liveUrl();
  const find = P.klipper ? SW.btn(SW.t("printers_find"), { run: () => goTo(toolCards) }) : null;
  return E("div", "printers-head", printersMeta(P.list, found),
    E("div", "page-head__actions",
      P.bambu ? X("a", { class: "btn btn--ghost", href: url, target: "_blank", rel: "noopener" }, SW.icon("camera", "icon--s"), SW.t("printers_live_view")) : null,
      find, SW.btn([SW.icon("plus", "icon--s"), SW.t("printers_add")], { cls: "btn--primary", run: () => openAdd() })));
}

function drawList(body) {
  const P = S.printers, found = P.list.filter((p) => klipperOf(p) && !p.configured), configured = P.list.filter((p) => !(klipperOf(p) && !p.configured));
  rowViews = new Map();
  for (const o of watchers) o.disconnect();
  watchers.clear();
  body._drawn = true;
  drawnLocked = lockedNow();
  if (!P.list.length) {
    body.replaceChildren(E("div", "printers-head", E("div", "page-head__actions", P.bambu ? X("a", { class: "btn btn--ghost", href: liveUrl(), target: "_blank", rel: "noopener" },
      SW.icon("camera", "icon--s"), SW.t("printers_live_view")) : null)),
    SW.empty({ icon: "printer", title: SW.t("printers_empty_title"), text: [P.bambu ? SW.t("printers_empty_bambu") : null, P.klipper ? SW.t("printers_empty_klipper") : null].filter(Boolean).join(" "),
      level: 2, actions: [SW.btn(SW.t("printers_add"), { cls: "btn--primary", run: () => openAdd() }), P.klipper ? SW.btn(SW.t("printers_find"), { run: () => goTo(toolCards) }) : null].filter(Boolean) }));
    return;
  }
  body.replaceChildren(header(found), printerTable(found, configured));
  if (pendingScroll) { const it = body.querySelector(`.coll__item[data-id="${CSS.escape(rowKeys.get(pendingScroll) || "")}"]`); pendingScroll = null; if (it) it.scrollIntoView({ block: "start" }); }
}
let pendingScroll = null;
// a read of printers/states: the badges, the strips and the lines are patched in place; a different set of printers draws the list again
function paintLive(body, r) {
  const ids = (list) => list.map((p) => p.serial).sort().join();
  live = Object.fromEntries(r.printers.map((p) => [p.serial, p]));
  if (!body._drawn) { drawList(body); return; }
  if (ids(r.printers) !== ids(S.printers.list)) { refresh(body); return; }
  for (const v of rowViews.values()) {
    const p = v.p;
    if (v.statusEl.isConnected) { v.statusEl.replaceChildren(...stateBlock(p).filter(Boolean)); v.statusCell.dataset.sort = stateWord(p); }
    if (v.slotsEl.isConnected) v.slotsEl.replaceChildren(...slotStrip(p));
    if (v.detailSlots && !v.detailSlots.contains(document.activeElement)) v.detailSlots.replaceChildren(slotLines(p));
    if (v.detailStatus) v.detailStatus.replaceChildren(stateBlock(p)[0]);
    setCell(v.connectionCell, E("span", "coll__key", { "aria-hidden": "true" }, SW.t("printers_col_connection")), connectionCell(p));
  }
  const meta = body.querySelector(".printers-meta");
  if (meta) meta.replaceWith(printersMeta(S.printers.list, S.printers.list.filter((p) => klipperOf(p) && !p.configured)));
}
function printersList() {
  const body = E("div", "printers-list");
  listEl = body;
  if (live) { body._loaded = true; drawList(body); }
  later(readRegion(body, PRINTERS, () => api("printers/states"), (r) => paintLive(body, r)));
  return body;
}
// the states again every 10 s while the section is shown (03 2.7); a hidden tab waits and reads at once when it is shown
function poll() {
  clearTimeout(pollTimer);
  if (tabNow() !== PRINTERS) return;
  pollTimer = setTimeout(async () => {
    if (tabNow() !== PRINTERS) return;
    if (!document.hidden && listEl && listEl.isConnected) { try { paintLive(listEl, await api("printers/states")); } catch (e) { /* the next read tells */ } }
    poll();
  }, 10000);
}
// Lock now and Unlock draw the list again at once: addresses and serials go away or come back (03 2.1). An address that names a printer
// (#printers/<serial>) still opens its row while Locked, as the person typed it; the serial is never written into the page or the address by this script then
document.addEventListener("sw:lock", () => {
  if (tabNow() !== PRINTERS || !listEl || !listEl.isConnected || !listEl._drawn || lockedNow() === drawnLocked) return;
  drawList(listEl);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden || tabNow() !== PRINTERS || !listEl || !listEl.isConnected) return;
  api("printers/states").then((r) => paintLive(listEl, r), () => {});
  poll();
});

// ----- Add a printer (03 5.6): a drawer at #printers/add; its fields are the field component's, so a refusal shows at the field it names -----
const needed = (key) => (v) => (v.trim() ? null : SW.t(key));
const portCheck = (v) => (/^\d+$/.test(v.trim()) && Number(v) >= 1 && Number(v) <= 65535 ? null : SW.t("common_error_port"));
const secretAttrs = { autocapitalize: "off", spellcheck: "false" };
const addressAttrs = { inputmode: "url", autocapitalize: "off", autocorrect: "off", spellcheck: "false" };
// the Hub's refusals of an add, in the words of 03 5.6; any other text is shown as sent
function addError(field, message) {
  let x;
  if ((x = /^the printer at (.+) names itself (.+), not (.+): check the address$/.exec(message))) return SW.t("printers_add_error_itself", { address: x[1], reported: x[2], expected: x[3] });
  if (field === "serial" && /type the serial number/.test(message)) return SW.t("printers_add_error_serial");
  if ((x = /^(.+) \(on the printer: Settings > Network\)$/.exec(message))) return `${hubText(x[1])} ${SW.t("printers_add_error_network")}`;
  return hubText(message);
}
function openAdd() {
  const opener = document.activeElement;
  if (location.hash !== "#printers/add") history.pushState(null, "", "#printers/add");
  return closeDrawerAsync().then(() => openAddDrawer(opener));
}
function openAddDrawer(opener) {
  const P = S.printers, id = SW.uid("add");
  let family = P.bambu ? "bambu" : "klipper", adding = false, sending = false;
  const f = {
    address: SW.field({ label: SW.t("printers_field_address"), name: "address", mono: true, placeholder: SW.t("printers_add_address_placeholder"), attrs: addressAttrs, check: needed("common_error_address") }),
    access_code: SW.field({ type: "secret", label: SW.t("common_field_access_code"), name: "access_code", mono: true, hint: SW.t("printers_access_code_hint"), attrs: secretAttrs, check: needed("common_error_access_code") }),
    serial: SW.field({ label: SW.t("printers_fact_serial"), optional: true, name: "serial", mono: true, hint: SW.t("printers_add_serial_hint"), attrs: { autocapitalize: "characters", spellcheck: "false" } }),
    host: SW.field({ label: SW.t("common_address"), name: "host", mono: true, placeholder: SW.t("printers_add_klipper_placeholder"), attrs: addressAttrs, check: needed("common_error_address") }),
    port: SW.field({ type: "number", label: SW.t("printer_field_port"), name: "port", mono: true, short: true, value: "7125", attrs: { pattern: "[0-9]*" }, check: portCheck }),
    api_key: SW.field({ type: "secret", label: SW.t("common_moonraker_key"), optional: true, name: "api_key", mono: true, hint: SW.t("printers_key_hint"), attrs: secretAttrs }),
    name: SW.field({ label: SW.t("common_field_name"), optional: true, name: "name" }),
  };
  const bambuOnly = [f.address, f.access_code, f.serial], klipperOnly = [f.host, f.port, f.api_key];
  const visible = () => (family === "klipper" ? [f.host, f.port, f.name, f.api_key] : [f.address, f.access_code, f.name, f.serial]);
  const paint = () => { for (const x of bambuOnly) x.hidden = family !== "bambu"; for (const x of klipperOnly) x.hidden = family !== "klipper"; };
  const type = P.bambu && P.klipper ? SW.segmented({ legend: SW.t("printers_add_type"), name: "add-type", value: family,
    options: [{ value: "bambu", label: SW.t("common_bambu_lab") }, { value: "klipper", label: SW.t("common_klipper") }] }) : null;
  if (type) type.addEventListener("change", (e) => { family = e.target.value; paint(); });
  paint();
  const all = [...bambuOnly, ...klipperOnly, f.name], was = new Map(all.map((x) => [x, x._control.value]));
  const dirty = () => all.filter((x) => x._control.value !== was.get(x)).length;
  const result = E("p", "result result--block", { role: "status" });
  const form = X("form", { class: "printers-add", id, novalidate: true, on: { submit: (e) => { e.preventDefault(); submit(); } } },
    type, f.address, f.access_code, f.host, f.port, f.name, f.serial, f.api_key);
  const add = SW.btn(SW.t("common_add_printer"), { cls: "btn--primary", type: "submit" });
  add.setAttribute("form", id);
  const cancel = SW.btn(SW.t("common_cancel"), { run: () => requestClose() });
  async function submit() {
    if (sending) return;      // from the press until the answer: guard() starts the add a moment later, and a second press must not send another
    SW.result(result, null);
    const mine = visible(), bad = mine.filter((x) => { const err = x._check && x._check(); SW.fieldError(x, err || null); return !!err; });
    if (bad.length) { bad[0]._control.focus(); return; }
    const v = (x) => x._control.value.trim();
    const [path, body] = family === "klipper" ? ["printers/klipper", { host: v(f.host), port: v(f.port), name: v(f.name), api_key: v(f.api_key) }]
      : ["printers", { address: v(f.address), access_code: f.access_code._control.value, name: v(f.name), serial: v(f.serial) }];
    let r = null;
    sending = true;
    try { await SW.guard(SW.t("common_add_printer").toLowerCase(), async () => {
      adding = true;
      SW.busy(add, SW.t("common_working"));
      for (const x of mine) x._control.readOnly = true;
      try { r = await api(path, { ...body, code: theCode() }); } catch (e) {
        if (e.locked) throw e;
        const at = e.data && e.data.field && mine.find((x) => x._control.name === e.data.field);
        if (at) { SW.fieldError(at, addError(e.data.field, e.message)); at._control.focus(); } else SW.result(result, "bad", addError(e.data && e.data.field, e.message));
      } finally { adding = false; SW.idle(add); for (const x of mine) x._control.readOnly = false; }
    }); } finally { sending = false; }
    if (r) await afterAdd(r);
  }
  const d = openDrawer("add", { serial: "add" }, SW.t("printers_add"), form, [result, cancel, add],
    { opener, address: "#printers/add", back: "#printers", busy: () => adding, dirty, result });
  visible()[0]._control.focus();
  return d;
}
// 03 5.6 Success: the drawer closes, a toast, the new row open with its message and Test connection focused
async function afterAdd(r) {
  if (SW.phone()) expanded.clear();
  expanded.add(r.serial);
  history.replaceState(null, "", `#printers/${encodeURIComponent(r.serial)}`);
  await closeDrawerAsync();
  await refresh(listEl && listEl.isConnected ? listEl : undefined);
  const p = S.printers.list.find((x) => x.serial === r.serial);
  SW.toast(SW.t("printers_added", { name: p ? p.name : r.serial }), "ok");
  say(boxFor("printer:" + r.serial), SW.t("printers_added_connecting") + (r.note ? " " + hubText(r.note) : ""), true);
  setTitle(expandedTitle());
  const it = listEl && listEl.querySelector(`.coll__item[data-id="${CSS.escape(r.serial)}"]`);
  if (!it) return;
  it.scrollIntoView({ block: "nearest" });
  const test = it.querySelector('.coll__cell[data-col="actions"] .btn');
  if (test) test.focus({ preventScroll: true });
}

// ----- Find Klipper printers (03 5.4, 5.8): one scan; what it finds joins the list's found group -----
function scanRefused(box, subnet, e) {
  const m = e.message, d = e.data || {};
  let x;
  if (e.status === 429 && /^a scan is running/.test(m)) say(box, SW.t("printers_result_scan_running"), "warn");
  else if (e.status === 429 && (x = /^wait (\d+) s between scans/.exec(m))) say(box, SW.t("printers_result_scan_soon", { count: Number(x[1]) }), "warn");
  else if (d.field === "subnet") {
    SW.fieldError(subnet, /^can't tell/.test(m) ? hubText(m) : SW.t("printers_result_scan_refused"));
    subnet._control.focus();
  } else say(box, hubText(m), false);
}
async function runScan(box, subnet, button) {
  const typed = subnet._control.value.trim();
  let out = null;
  SW.fieldError(subnet, null);
  await needCode(async () => {
    if (!SW.busy(button, SW.t("common_working"))) return;
    working(box, typed ? SW.t("printers_scanning", { subnet: typed }) : SW.t("printers_scanning_own"));
    try { out = await api("printers/scan", { subnet: typed, code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      SW.result(box, null);
      scanRefused(box, subnet, e);
    } finally { SW.idle(button); }
  });
  if (!out) return;
  if (listEl && listEl.isConnected) await refresh(listEl);       // what it found joins the found group
  const fresh = out.found.filter((r) => !r.configured).map((r) => S.printers.list.find((p) => p.serial === r.serial)).filter(Boolean);
  if (!out.found.length) { say(box, SW.t("printers_result_scan_none", { subnet: out.subnet }), "info"); return; }
  say(box, [SW.t("printers_result_scan_found", { subnet: out.subnet, found: out.found.map(hostPort).join(", ") }),
    fresh.length ? E("div", "actions", fresh.map((p) => SW.btn(SW.t("printers_use"), { name: SW.t("printers_use_name", { name: p.name }), run: () => usePrinter(p, boxFor("printer:" + p.serial)) }))) : null], true);
}
function scanBlock() {
  const box = boxFor("printer-scan");
  const subnet = SW.field({ label: SW.t("printers_subnet_label"), name: "subnet", mono: true, placeholder: SW.t("printers_subnet_placeholder"), hint: SW.t("printers_subnet_hint"),
    attrs: { autocapitalize: "off", spellcheck: "false", "aria-required": "false" } });
  const go = SW.btn(SW.t("printers_scan"), { run: () => runScan(box, subnet, go) });
  subnet._control.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } });
  return card(SW.t("printers_find"), E("p", "muted", SW.t("printers_find_text")), subnet, E("div", "actions", go), box);
}

// ----- the Klipper add-on card: the commands, checked against the signed release, in a code block with Copy -----
async function showCommands(box, button) {
  if (!addonOut) addonOut = E("div", "printers-addon");
  if (!SW.busy(button, SW.t("common_checking"))) return;
  SW.result(box, null);
  addonOut.replaceChildren(E("div", "code", E("p", "code__wait", { role: "status" }, SW.spinner(), SW.t("code_checking_release"))));
  try {
    const r = await api("printers/pack", {}), cap = SW.uid("addon"), text = r.lines.join("\n");
    // the caption and Copy sit above the block, not in it: the block scrolls, and its bar would scroll away with the lines
    const copy = SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: "copy", name: SW.t("printers_addon_copy_name") });
    copy.dataset.copy = text;
    addonOut.replaceChildren(E("div", "printers-addon__bar", E("span", "code__caption mono", { id: cap }, SW.t("printers_addon_caption", { version: r.version })),
      E("span", "result", { role: "status" }), copy),
    E("div", "code", X("pre", { class: "code__text", tabindex: "0", "aria-labelledby": cap, text })));
  } catch (e) {
    addonOut.replaceChildren();
    const m = e.status === 409 && e.data && typeof e.data.reason === "string" && [null, e.data.reason];
    if (m) sayWith(box, "bad", SW.t("printers_result_addon_unavailable", { reason: hubText(m[1]) }),
      { label: SW.t("common_try_again"), name: `${SW.t("common_try_again")}: ${SW.t("printers_addon_title")}`, run: () => showCommands(box, button) });
    else say(box, hubText(e.message), false);
  } finally { SW.idle(button); }
}
function addonBlock() {
  const box = boxFor("printer-addon");
  const show = SW.btn(SW.t("printers_addon_show"), { run: () => showCommands(box, show) });
  return card(SW.t("printers_addon_title"), E("p", "muted", SW.t("printers_addon_text")), E("div", "actions", show), box, addonOut || (addonOut = E("div", "printers-addon")));
}
// the two tool cards, side by side on a desktop (03 5.1); only with Klipper on
function toolCards() {
  return S.printers.klipper ? E("div", "printers-tools", scanBlock(), addonBlock()) : null;
}

// only one family is on: the other one's words are not on the page, and one quiet line says so (03 5.9)
function familyNote() {
  const P = S.printers;
  if (P.bambu && P.klipper) return null;
  return E("p", "muted printers-note", SW.t(P.bambu ? "printers_klipper_off" : "printers_bambu_off"), " ", X("a", { href: "#features", text: SW.t("common_open_features") }));
}

function printersOff() {
  return switchedOff("printers");
}
// where the address points: a row open, a drawer on it (03 1.2); the address is read after the regions are in the page
async function followAddress() {
  const a = addressNow(), p = a.id && S.printers.list.find((x) => x.serial === a.id), wantsAdd = a.id === "add";
  if (p) {
    expanded.add(p.serial);
    const it = listEl && listEl.querySelector(`.coll__item[data-id="${CSS.escape(keyOf(p.serial))}"]`);
    const x = it && it.querySelector(".coll__expand");
    const reg = document.getElementById("detail-" + keyOf(p.serial));
    if (SW.profile().detail === "sheet" && !a.what && !drawer && reg && !reg.closest("dialog")) SW.openDetail(reg, { opener: x || it, focusTitle: true });
    else if (x && x.getAttribute("aria-expanded") !== "true") x.click();
    if (it && !a.what && !drawer) it.scrollIntoView({ block: "start" });
  } else {
    const openDlg = document.querySelector("#detail-host .detail");
    if (openDlg) SW.closeDetail(openDlg);
  }
  if (drawer && !(wantsAdd && drawer.kind === "add") && (!p || a.what !== drawer.kind || p.serial !== drawer.serial)) {
    if (drawer.running() || drawer.busy() || drawer.dirty()) { history.pushState(null, "", drawer.address); requestClose(); return; }
    await closeDrawerAsync();
  }
  if (wantsAdd) { if (!drawer) openAddDrawer(document.activeElement); return; }
  if (a.id === "find") { goTo(toolCards); return; }
  if (p && a.what === "load-map" && !drawer && p.configured) manualMap(p, boxFor("printer:" + p.serial), false).catch(() => {});
  else if (p && a.what === "reports" && !drawer && !klipperOf(p)) openReports(p);
  else if (!drawer) setTitle(expandedTitle());
}
// the builders of the section's regions; adding a printer or a scan changes the list too
function printersTab() {
  const P = S.printers;
  clearTimeout(pollTimer);
  if (!P.on) return [printersOff];
  const a = addressNow();
  if (a.id && a.id !== "add" && a.id !== "find") { expanded.add(a.id); pendingScroll = a.what ? null : a.id; }
  poll();
  setTimeout(followAddress);
  return [printersList, toolCards, familyNote];
}
