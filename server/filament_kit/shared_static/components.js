// Spoolwarden shared components (docs/design/02-components.md 1.4): the one script the Hub page and the web app load
// after strings/strings.js, holding the element builder, the Hub request helper, guard(), profile(), announce(), the
// dialog, the toast, the inline result and the behaviour of the other components; their markup is as 02 shows it.
// Texts come from window.SW_TEXT or the caller; text from the Hub goes in as textContent, never as markup.
(() => {
"use strict";
const doc = document, root = doc.documentElement;
const conf = { base: "api/", fetch: (u, i) => window.fetch(u, i), lock: true, hub: "", version: "",
  checkPath: "overview", trustPath: "trust" };
const configure = (o) => Object.assign(conf, o);

// ----- texts, elements, small helpers -----
const plural = new Intl.PluralRules("en");
function t(key, vars) {
  let v = (window.SW_TEXT || {})[key];
  if (v == null) return key;
  if (typeof v === "object") v = v[plural.select(vars && vars.count != null ? Number(vars.count) : 0)] || v.other;
  return vars ? v.replace(/\{([a-z][a-z0-9_]*)\}/g, (m, n) => (vars[n] != null ? String(vars[n]) : m)) : v;
}
const NS = "http://www.w3.org/2000/svg", SVG = new Set(["svg", "use", "circle"]);
// h(tag, props, ...kids): props are properties or attributes; text = textContent, data = dataset, on = listeners
function h(tag, props, ...kids) {
  const svg = SVG.has(tag), el = svg ? doc.createElementNS(NS, tag) : doc.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "text") el.textContent = v;
    else if (k === "data") { for (const [d, x] of Object.entries(v)) if (x != null) el.dataset[d] = x; }
    else if (!svg && k in el && k !== "list" && k !== "form" && typeof el[k] !== "object") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const E = (tag, cls, ...kids) => h(tag, { class: cls }, ...kids);
const $ = (s, r = doc) => r.querySelector(s), $$ = (s, r = doc) => [...r.querySelectorAll(s)];
const on = (el, ev, fn, o) => el.addEventListener(ev, fn, o);
const attr = (el, k, v) => (v == null ? el.removeAttribute(k) : el.setAttribute(k, v));
let seq = 0;
const uid = (p) => `sw-${p}-${++seq}`;
const AH = { "aria-hidden": "true" }, HID = { ...AH, focusable: "false" };
const icon = (name, cls) => h("svg", { class: "icon" + (cls ? " " + cls : ""), ...HID }, h("use", { href: "#i-" + name }));
const shape = (id) => h("svg", { class: "status__shape", ...HID }, h("use", { href: "#" + id }));
const mq = (q) => matchMedia(q).matches;
const phone = () => mq("(max-width: 600px)");
const reduced = () => mq("(prefers-reduced-motion: reduce)");
const pad = (n) => String(n).padStart(2, "0");
const hm = (d) => pad(d.getHours()) + ":" + pad(d.getMinutes());
const clamp01 = (v) => Math.min(1, Math.max(0, Number(v) || 0));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } },
  del(k) { try { localStorage.removeItem(k); return true; } catch (e) { return false; } },
};
const focusTitle = () => { const t1 = $("main h1"); if (t1) t1.focus({ preventScroll: true }); };
const returnFocus = (el) => (el && el.isConnected && el.getClientRects().length ? el.focus({ preventScroll: true }) : focusTitle());

// ----- profile() (foundations 6.1) and announce() (1.4) -----
const PROFILES = {
  console: { nav: "rail", collection: "table", detail: "inline" },
  workbench: { nav: "sidebar", collection: "cards", detail: "card" },
  palette: { nav: "pills", collection: "tiles", detail: "sheet" },
  panes: { nav: "list", collection: "rows", detail: "pane" },
};
const profile = () => PROFILES[root.getAttribute("data-look")] || PROFILES.console;
function announce(text) {
  let el = doc.getElementById("announcer");
  if (!el) doc.body.append(el = h("div", { class: "sr", id: "announcer", "aria-live": "polite" }));
  el.textContent = "";
  setTimeout(() => { el.textContent = text; }, 30);
}

// ----- status badge (7.1), confidence mark (7.2), spinner (8.1) -----
const WORDS = {
  connected: ["s-filled", "ok", "status_connected"], offline: ["s-hollow", "bad", "status_offline"],
  not_configured: ["s-hollow", "muted", "status_not_configured"], on: ["s-filled", "ok", "status_on"],
  off: ["s-hollow", "muted", "status_off"], set: ["s-filled", "ok", "status_set"],
  not_set: ["s-hollow", "muted", "status_not_set"], ok: ["s-filled", "ok", "status_ok"],
  needs_look: ["s-triangle", "warn", "status_needs_look"], note: ["s-diamond", "info", "status_note"],
  as_detected: ["s-hollow", "muted", "status_as_detected"], revised_ai: ["i-info", "info", "status_revised_ai"],
  edited: ["i-pencil", "info", "status_edited"], running: ["s-half", "run", "status_running"],
  done: ["s-filled", "ok", "status_done"], failed: ["s-octagon", "bad", "status_failed"],
  high: ["s-filled", "ok", "confidence_high"], medium: ["s-triangle", "warn", "confidence_medium"],
  low: ["s-octagon", "bad", "confidence_low"], not_on_label: ["s-hollow", "muted", "confidence_not_on_label"],
};
// status(word, {small, cls, text, count, prefix}): a word of the vocabulary or a confidence level
function status(word, o = {}) {
  const [id, kind, key] = WORDS[word];
  return E("span", `status status--${kind}${o.small ? " status--s" : ""}${o.cls ? " " + o.cls : ""}`, shape(id),
    o.prefix ? E("span", "sr", t("status_prefix")) : null, o.text || t(key), o.count != null ? " " + o.count : null);
}
const KIND_SHAPE = { ok: "s-filled", bad: "s-octagon", warn: "s-triangle", info: "s-diamond", neutral: "s-hollow" };
const spinner = (alone) => (alone ? h("span", { class: "spinner spinner--alone", role: "status" }, E("span", "sr", t("common_working")))
  : h("span", { class: "spinner", ...AH }));

// ----- tooltip (4.3): inside an icon button (aria-hidden), else after its target -----
function tooltip(target, text) {
  const tip = h("span", { class: "tooltip", role: "tooltip", id: uid("tip"), hidden: true, text });
  let node = target, timer = 0;
  if (target.tagName === "BUTTON") { attr(tip, "aria-hidden", "true"); target.append(tip); }
  else { node = E("span", "tip", target, tip); attr(target, "aria-describedby", tip.id); }
  const show = () => {
    clearTimeout(timer); tip.hidden = false;
    tip.dataset.place = target.getBoundingClientRect().top < tip.offsetHeight + 16 ? "below" : "above";
  };
  const hide = () => { clearTimeout(timer); tip.hidden = true; };
  const later = (fn, ms) => () => { clearTimeout(timer); timer = setTimeout(fn, ms); };
  on(target, "mouseenter", later(show, 500)); on(target, "mouseleave", later(hide, 100));
  on(tip, "mouseenter", () => clearTimeout(timer)); on(tip, "mouseleave", hide);
  on(target, "focus", () => { if (target.matches(":focus-visible")) show(); });
  on(target, "blur", hide); on(target, "click", hide);
  on(target, "keydown", (e) => { if (e.key === "Escape" && !tip.hidden) { hide(); e.stopPropagation(); } });
  return node;
}

// ----- buttons (4.1) -----
const btn = (label, o = {}) => h("button", { class: "btn" + (o.cls ? " " + o.cls : ""), type: o.type || "button",
  "aria-label": o.name, data: { action: o.action }, on: o.run ? { click: o.run } : null }, o.icon ? icon(o.icon, "icon--s") : null, label);
function iconBtn(name, label, o = {}) {
  const b = h("button", { class: "btn btn--ghost btn--icon" + (o.cls ? " " + o.cls : ""), type: "button", "aria-label": label,
    data: { action: o.action }, on: o.run ? { click: o.run } : null }, icon(name));
  tooltip(b, label);
  return b;
}
// busy(b, "Saving…"): the loading form; the width is kept (--btn-min)
function busy(b, label) {
  if (b.getAttribute("aria-busy") === "true") return false;
  b.style.setProperty("--btn-min", b.offsetWidth + "px");
  b._kept = { kids: [...b.childNodes], name: b.getAttribute("aria-label"), was: b.getAttribute("aria-disabled") };
  attr(b, "aria-busy", "true"); attr(b, "aria-disabled", "true");
  if (b._kept.name) attr(b, "aria-label", label);
  b.replaceChildren(spinner(), label);
  return true;
}
function idle(b) {
  const k = b._kept;
  if (!k) return;
  b.replaceChildren(...k.kids); b._kept = null;
  attr(b, "aria-busy", null); attr(b, "aria-disabled", k.was); attr(b, "aria-label", k.name);
  b.style.removeProperty("--btn-min");
}
// disable(b, reason): aria-disabled with its reason shown beside it; reason null enables it
function disable(b, reason) {
  let r = b._reason;
  const ids = (b.getAttribute("aria-describedby") || "").split(" ").filter((x) => x && (!r || x !== r.id));
  if (reason == null) {
    attr(b, "aria-disabled", null); attr(b, "aria-describedby", ids.join(" ") || null);
    if (r) r.remove();
    b._reason = null;
    return;
  }
  if (!r) { r = b._reason = h("span", { class: "btn__reason", id: uid("why") }); b.after(r); }
  r.textContent = reason;
  attr(b, "aria-disabled", "true"); attr(b, "aria-describedby", ids.concat(r.id).join(" "));
}
// a press on an aria-disabled control does nothing
on(doc, "click", (e) => {
  const b = e.target.closest && e.target.closest('[aria-disabled="true"]');
  if (b && b.matches("button, a, [role^=menuitem]")) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// ----- the Hub request helper: api(path, {method, body, form, code, signal}) -----
class HubError extends Error {
  constructor(o) { super(o.message || o.error || ""); Object.assign(this, o); }
  text(fallback) { return this.unreachable ? t("common_hub_no_answer") : this.message || this.error || fallback; }
}
const errText = (err, fallback) => (err && err.text ? err.text(fallback) : fallback);
async function api(path, o = {}) {
  const method = o.method || (o.body !== undefined || o.form ? "POST" : "GET");
  const init = { method, credentials: "same-origin", headers: {}, signal: o.signal };
  const code = method !== "GET" && o.code !== false ? lock.code : null;
  if (o.form) { if (code) o.form.set("code", code); init.body = o.form; }
  else if (o.body !== undefined || code) {
    init.body = JSON.stringify(code ? Object.assign({}, o.body, { code }) : o.body);
    init.headers["Content-Type"] = "application/json";
  }
  let r, data = null;
  try { r = await conf.fetch(conf.base + path, init); }
  catch (e) { if (e && e.name === "AbortError") throw e; throw new HubError({ unreachable: true }); }
  try { data = await r.json(); } catch (e) { data = null; }
  if (data && data.trust_gone && lock.state === "trusted") setLock("locked");
  if (!r.ok || !data || data.error) {
    throw new HubError({ status: r.status, error: data && data.error, message: data && data.message,
      field: data && data.field, data, locked: r.status === 401 });
  }
  return data;
}

// ----- the inline result (8.6) -----
const pending = new WeakMap();
// result(el, kind run|ok|bad|warn|info|neutral|null, content, {action: {label, name, run}, bar, barText})
function result(el, kind, content, o = {}) {
  clearTimeout(pending.get(el));
  el.replaceChildren();
  const row = el.closest(".coll__row--result");
  if (row) row.hidden = !kind;
  if (!kind) { attr(el, "data-state", null); return el; }
  el.dataset.state = kind;
  const d = new Date(), kids = [kind === "run" ? spinner() : shape(KIND_SHAPE[kind] || "s-hollow"), E("span", "result__text", content)];
  if (o.bar != null) kids.push(progress({ value: o.bar, valuetext: o.barText, name: o.barText }));
  if (kind !== "run") {
    const tm = h("time", { class: "result__time muted", datetime: d.toISOString() }, " · " + hm(d));
    kids.push(tooltip(tm, `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm(d)}`));
  }
  if (o.action) kids.push(btn(o.action.label, { name: o.action.name, run: o.action.run }));
  pending.set(el, setTimeout(() => el.append(...kids), 30));
  return el;
}
// results are cleared when the person leaves the section
on(window, "hashchange", (e) => {
  const sec = (u) => (u.split("#")[1] || "").split(/[/?]/)[0];
  if (sec(e.oldURL) !== sec(e.newURL)) for (const r of $$(".result[data-state]")) result(r, null);
});

// ----- the toast (8.7): toast(text, kind, {action: {label, name, run}}) -----
function toast(text, kind = "ok", o = {}) {
  let box = $(".toasts"), timer = 0, left = o.action ? 10000 : 5000, started = 0;
  if (!box) doc.body.append(box = h("div", { class: "toasts", "aria-live": "polite" }));
  const close = () => { clearTimeout(timer); el.remove(); };
  const el = h("div", { class: "toast", data: { state: kind } }, shape(KIND_SHAPE[kind] || "s-filled"), E("span", "toast__text", text));
  if (o.action) el.append(btn(o.action.label, { name: o.action.name, run: () => { o.action.run(); close(); } }),
    iconBtn("close", t("common_close"), { run: close }));
  const start = () => { clearTimeout(timer); started = Date.now(); timer = setTimeout(close, left); };
  const pause = () => { clearTimeout(timer); left = Math.max(1000, left - (Date.now() - started)); };
  for (const [ev, fn] of [["mouseenter", pause], ["mouseleave", start], ["focusin", pause], ["focusout", start]]) on(el, ev, fn);
  box.prepend(el);
  while (box.children.length > 3) box.lastElementChild.remove();
  start();
  return el;
}

// ----- dialogs and sheets (9.1, 9.2) -----
function openModal(dlg, opener) {
  if (!dlg.isConnected) doc.body.append(dlg);
  dlg._opener = opener || doc.activeElement;
  if (!dlg.open) dlg.showModal();
  return dlg;
}
// modal(dlg, {temp, scrim, onClose}): on closing, focus returns to the opener or the page title
function modal(dlg, o = {}) {
  on(dlg, "close", () => {
    if (!dlg._noReturn) returnFocus(dlg._opener);
    dlg._noReturn = false;
    if (o.temp) dlg.remove();
    if (o.onClose) o.onClose();
  });
  if (o.scrim) on(dlg, "click", (e) => { if (e.target === dlg && !dlg._busy) dlg.close(); });
  return dlg;
}
// ask({kind confirm|destructive|typed|entry|info, title, text, body, fields, after, confirm, cancel, style, word, busy,
// write, run(values, {result}) -> false stays open}): resolves with run's answer (or true), null on cancel
function ask(o) {
  return new Promise((resolve) => {
    const id = uid("dlg"), danger = o.kind === "destructive" || o.kind === "typed", fields = (o.fields || []).slice();
    let word = null, answer = null;
    if (o.kind === "typed") fields.push(word = field({ label: t("common_type_word", { word: o.word }), attrs: { autocapitalize: "off", spellcheck: "false" } }));
    const text = o.text != null ? h("p", { class: "dialog__text", id: id + "-text" }, o.text) : null;
    const res = h("p", { class: "result result--block dialog__result", role: "status" });
    const close = () => dlg.close();
    const cancel = o.kind === "info" ? null : btn(o.cancel || t("common_cancel"), { action: "cancel", run: close });
    const go = btn(o.confirm || t("common_close"), { type: "submit", action: "confirm",
      cls: o.style != null ? o.style : danger ? "btn--danger btn--solid" : "btn--primary" });
    const x = iconBtn("close", t("common_close"), { action: "cancel", run: close });
    const form = h("form", { class: "dialog__form", method: "dialog", novalidate: true },
      E("div", "dialog__head", h("h2", { class: "dialog__title", id: id + "-title", text: o.title }), x),
      E("div", "dialog__body", text, o.body, fields, o.after, res), E("div", "dialog__foot", o.extra, cancel, go));
    const dlg = h("dialog", { class: "dialog" + (o.wide ? " dialog--wide" : ""), role: danger ? "alertdialog" : null,
      "aria-labelledby": id + "-title", "aria-describedby": text ? id + "-text" : null }, form);
    const values = () => fields.map((f) => f._control.value), first = values().join("\n");
    if (word) { const sync = () => { go.disabled = word._control.value.trim() !== o.word; }; on(word._control, "input", sync); sync(); }
    const ro = (on) => { for (const f of fields) f._control.readOnly = on; };
    on(dlg, "cancel", (e) => {
      if (dlg._busy) return e.preventDefault();
      if (o.kind === "entry" && fields.length > 1 && values().join("\n") !== first) {
        e.preventDefault();
        leaveAsk(o.title).then((leave) => { if (leave) close(); });
      }
    });
    for (const b of [cancel, x]) if (b) on(b, "click", (e) => { if (dlg._busy) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
    on(form, "submit", (e) => {
      e.preventDefault();
      if (dlg._busy || go.disabled) return;
      const bad = fields.filter((f) => { const err = f._check && f._check(); fieldError(f, err || null); return !!err; });
      if (bad.length) return bad[0]._control.focus();
      if (!o.run) { answer = o.kind === "entry" ? values() : true; return close(); }
      const run = async () => {
        dlg._busy = true; busy(go, o.busy || t("common_working")); ro(true); result(res, null);
        try {
          const r = await o.run(values(), { result: res, dialog: dlg });
          if (r !== false) { answer = r === undefined ? true : r; dlg._busy = false; close(); }
        } catch (err) {
          if (err && err.locked) throw err;
          result(res, "bad", errText(err, o.failed || t("common_hub_no_answer")));
        } finally { dlg._busy = false; idle(go); ro(false); }
      };
      if (o.write) guard(o.title, run); else run();
    });
    modal(dlg, { temp: true, onClose: () => resolve(answer) });
    openModal(dlg, o.opener);
    const f1 = word || fields[0];
    if (f1 && (o.kind === "entry" || o.kind === "typed")) { f1._control.focus(); if (f1._control.select) f1._control.select(); }
    else (o.kind === "destructive" ? cancel : go).focus();
  });
}
const leaveAsk = (changes) => ask({ kind: "destructive", title: t("common_leave_title"), text: t("form_leave_body", { changes }),
  confirm: t("common_leave_without_saving"), cancel: t("common_stay") });
// sheet({title, body, foot, cls, bodyTag, bodyLabel, onClose}): removed when it closes
function sheet(o) {
  const id = uid("sheet");
  const dlg = h("dialog", { class: "sheet" + (o.cls ? " " + o.cls : ""), "aria-labelledby": id },
    h("div", { class: "sheet__handle", ...AH }),
    E("div", "sheet__head", h("h2", { class: "sheet__title", id, text: o.title }),
      iconBtn("close", t("common_close"), { action: "close", run: () => dlg.close() })),
    h(o.bodyTag || "div", { class: "sheet__body", "aria-label": o.bodyLabel }, o.body), o.foot ? E("div", "sheet__foot", o.foot) : null);
  return modal(dlg, { temp: true, scrim: true, onClose: o.onClose });
}

// ----- lock chip and unlock dialog (3.1, 3.2); guard() (1.4) -----
const lock = { state: "locked", code: null, trustId: null, until: "", trustOffered: true };
const LOCK = {
  locked: ["lock", "lock_locked", "lock_hint_locked", "lock_name_locked"],
  unlocked: ["lock-open", "lock_unlocked", "lock_hint_unlocked", "lock_name_unlocked"],
  trusted: ["shield", "lock_trusted", "lock_hint_trusted", "lock_name_trusted"],
};
function paintLock(chip, loading) {
  const [ic, word, hint, name] = LOCK[lock.state];
  chip.dataset.state = lock.state;
  attr(chip, "aria-label", t(name));
  chip.replaceChildren(icon(ic, "icon--s"), E("span", "chip__word", t(word)), loading
    ? h("span", { class: "chip__hint skeleton__line", ...AH }) : h("span", { class: "chip__hint", ...AH, text: t(hint) }));
}
function setLock(state, o = {}) {
  const was = lock.state;
  Object.assign(lock, o, { state });
  if (state !== "unlocked") lock.code = null;   // never stored
  for (const chip of $$(".chip--lock")) paintLock(chip);
  if (was !== state && !o.quiet) announce(t(state === "locked" ? "lock_announce_locked" : "lock_announce_unlocked"));
  doc.dispatchEvent(new CustomEvent("sw:lock", { detail: state }));
}
function lockChip(o = {}) {
  const chip = h("button", { class: "chip chip--lock", type: "button", "aria-haspopup": "dialog", on: { click: () => lockOptions(chip) } });
  paintLock(chip, o.loading);
  return chip;
}
async function lockOptions(chip) {
  if (lock.state === "locked") return unlock(null, null, null, chip);
  if (lock.state === "unlocked") {
    if (await ask({ title: t("lock_unlocked"), text: t("lock_unlocked_body"), cancel: t("common_close"), confirm: t("lock_now"), opener: chip })) {
      setLock("locked"); toast(t("lock_toast_locked"));
    }
    return;
  }
  const ok = await ask({ title: t("lock_trusted"), text: t("lock_trusted_body", { date: lock.until }), opener: chip,
    body: h("p", null, h("a", { href: "#devices/trusted", text: t("lock_trusted_link") })), cancel: t("common_close"),
    confirm: t("lock_trusted_stop"), style: "", run: () => api(`${conf.trustPath}/${lock.trustId}/revoke`, { method: "POST" }).then(() => true) });
  if (ok) { setLock("locked"); toast(t("lock_toast_untrusted")); }
}
// unlock(change, run, onCancel): change names the pending change ("forget Workshop X1"), null from the chip
function unlock(change, run, onCancel, opener) {
  const code = field({ type: "secret", name: "code", label: t("unlock_field_label"), hint: t("unlock_field_hint"),
    short: true, mono: true, attrs: { inputmode: "numeric" } });
  const trust = lock.trustOffered ? check({ label: t("unlock_trust"), name: "trust" }) : null;
  return ask({ kind: "entry", title: t("unlock_title"), opener, text: change ? t("unlock_text_change", { change }) : t("unlock_text_chip"),
    fields: [code], after: trust, confirm: t(change ? "unlock_continue" : "unlock_button"), busy: t("common_checking"),
    run: async () => {
      const digits = code._control.value.replace(/\D/g, "");
      const no = (text) => { fieldError(code, text); code._control.focus(); return false; };
      if (!digits) return no(t("unlock_error_empty"));
      if (digits.length !== 8) return no(t("unlock_error_length", { count: digits.length }));
      try { await api(conf.checkPath, { method: "POST", body: { code: digits }, code: false }); }
      catch (err) { return no(err.unreachable ? t("unlock_error_unreachable") : err.status === 429 ? err.text(t("unlock_error_wrong")) : t("unlock_error_wrong")); }
      fieldError(code, null);
      if (trust && trust._control.checked) {
        const r = await api(conf.trustPath, { method: "POST", body: { code: digits }, code: false });
        setLock("trusted", { trustId: r.id, until: r.until || "" });
        toast(t("unlock_toast_trusted"));
      } else { setLock("unlocked", { code: digits }); toast(t("unlock_toast_unlocked")); }
      return true;
    },
  }).then((ok) => (ok ? run && guard(change, run, onCancel) : onCancel && onCancel()));
}
// guard(what, run, onCancel): Locked opens the unlock dialog first; a write refused for its code (err.locked) asks again
const restarting = () => !!$('.shell[data-state="restarting"]');   // 8.5
function guard(what, run, onCancel) {
  if (restarting()) { announce(t("common_wait_hub_back")); if (onCancel) onCancel(); return Promise.resolve(); }
  if (conf.lock && lock.state === "locked") return unlock(what, run, onCancel);
  return Promise.resolve().then(run).catch((err) => {
    if (!(err && err.locked && conf.lock)) throw err;
    setLock("locked");
    return unlock(what, run, onCancel);
  });
}

// ----- appearance control and theme picker (3.3, 3.4): a choice applies at once -----
const APPEAR = { light: ["sun", "appearance_light"], dark: ["moon", "appearance_dark"], system: ["half-circle", "appearance_system"] };
const appearanceValue = () => { const v = root.getAttribute("data-theme"); return v === "light" || v === "dark" ? v : "system"; };
function setAppearance(v) {
  attr(root, "data-theme", v === "system" ? null : v);
  const kept = v === "system" ? store.del("spoolwarden.appearance") : store.set("spoolwarden.appearance", v);
  const surface = getComputedStyle(root).getPropertyValue("--surface").trim();
  for (const m of $$('meta[name^="theme-"]')) {
    if (m.dataset.was == null) m.dataset.was = m.content;
    m.content = v === "system" ? m.dataset.was : surface;
  }
  for (const i of $$(".appearance .segmented__input")) i.checked = i.value === v;
  for (const b of $$(".appearance--menu")) {
    attr(b, "aria-label", t("appearance_name", { choice: t(APPEAR[v][1]) }));
    attr($("use", b), "href", "#i-" + APPEAR[v][0]);
  }
  return kept;
}
const setLook = (look) => { attr(root, "data-look", look); return store.set("spoolwarden.look", look); };
on(doc, "change", (e) => {
  const i = e.target, fs = i.closest && i.closest(".appearance, .theme-picker");
  if (!fs) return;
  const look = fs.classList.contains("theme-picker"), kept = look ? setLook(i.value) : setAppearance(i.value);
  const res = fs.parentElement.querySelector(":scope > .result");
  if (res) result(res, kept ? "ok" : "warn", !kept ? t("appearance_storage_blocked") : look
    ? t("appearance_theme_saved", { name: $(".theme-picker__name", i.closest("label")).textContent }) : t("appearance_saved", { choice: t(APPEAR[i.value][1]) }));
});
// the phone form: an icon button with a menu of radio items
const appearanceMenu = (b) => menu(b, () => [{ heading: t("appearance_title") }, ...Object.entries(APPEAR).map(([v, [ic, key]]) =>
  ({ label: t(key), icon: ic, checked: appearanceValue() === v, run: () => setAppearance(v) }))], { label: t("appearance_title") });

// ----- overflow menu (4.2): menu(trigger, items | () => items, {label}) -----
// item: {label, icon, reason, disabled, danger, checked, action, run} | {heading} | {separator}
function menu(trigger, items, o = {}) {
  const id = uid("menu");
  let pop = null, typed = "", typedAt = 0;
  attr(trigger, "aria-haspopup", "menu"); attr(trigger, "aria-expanded", "false"); attr(trigger, "aria-controls", id);
  const build = () => (typeof items === "function" ? items() : items).map((it) => (it.heading
    ? h("p", { class: "menu__heading", role: "presentation", text: it.heading }) : it.separator
      ? h("div", { class: "menu__separator", role: "separator" })
      : h("button", { class: "menu__item" + (it.danger ? " menu__item--danger" : ""), type: "button", tabindex: "-1",
        role: it.checked != null ? "menuitemradio" : "menuitem", "aria-checked": it.checked != null ? String(!!it.checked) : null,
        "aria-disabled": it.disabled ? "true" : null, data: { action: it.action },
        on: { click: () => { if (!it.disabled) { close(true); if (it.run) it.run(); } } } },
      it.icon ? icon(it.icon, "icon--s") : null, E("span", "menu__label", it.label, it.reason ? E("span", "menu__desc", it.reason) : null),
      it.checked ? icon("check", "icon--s menu__check") : null)));
  const list = () => $$(".menu__item", pop);
  const move = (b) => b && b.focus();
  function open(at) {
    const kids = build(), many = kids.filter((k) => k.classList.contains("menu__item")).length > 4;
    const box = h("div", { class: "menu" + (many && phone() ? " menu--sheet" : ""), id, role: "menu", "aria-label": o.label }, kids);
    on(box, "keydown", keys);
    if (many && phone()) {
      pop = openModal(sheet({ title: o.label, body: box, onClose: () => { attr(trigger, "aria-expanded", "false"); pop = null; } }), trigger);
    } else {
      pop = box;
      trigger.parentElement.classList.add("menu-anchor");
      trigger.after(pop);
      const r = trigger.getBoundingClientRect(), p = pop.getBoundingClientRect();
      if (r.bottom + p.height > innerHeight && r.top > p.height) pop.dataset.place = "above";
      if (r.right - p.width < 0) pop.dataset.align = "start";
      setTimeout(() => on(doc, "click", outside, true));
    }
    attr(trigger, "aria-expanded", "true");
    const l = list();
    move(at === "last" ? l[l.length - 1] : l[0]);
  }
  function close(focus) {
    if (!pop) return;
    if (pop.tagName === "DIALOG") { pop._noReturn = !focus; pop.close(); return; }
    pop.remove(); pop = null;
    doc.removeEventListener("click", outside, true);
    attr(trigger, "aria-expanded", "false");
    if (focus) trigger.focus();
  }
  const outside = (e) => { if (pop && !pop.contains(e.target) && !trigger.contains(e.target)) close(false); };
  function keys(e) {
    const l = list(), i = l.indexOf(doc.activeElement), k = e.key;
    const to = { ArrowDown: (i + 1) % l.length, ArrowUp: (i - 1 + l.length) % l.length, Home: 0, End: l.length - 1 }[k];
    if (to != null) { e.preventDefault(); move(l[to]); }
    else if (k === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (k === "Tab") close(false);
    else if (k.length === 1 && /\S/.test(k)) {
      typed = (Date.now() - typedAt < 600 ? typed : "") + k.toLowerCase(); typedAt = Date.now();
      move(l.slice(i + 1).concat(l.slice(0, i + 1)).find((b) => b.textContent.trim().toLowerCase().startsWith(typed)));
    }
  }
  on(trigger, "click", () => (pop ? close(true) : open("first")));
  on(trigger, "keydown", (e) => {
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !pop) { e.preventDefault(); open(e.key === "ArrowUp" ? "last" : "first"); }
  });
  return { open, close };
}

// ----- fields (5.1 to 5.10) -----
// field(o): the one maker of inputs, selects and textareas, always with a visible label (AUT-4). o: type, label,
// optional, hint, unit, decimal, mono, row, short, options, value, placeholder, attrs, max, accept, effect, check, onSearch
function field(o) {
  if (!o || !o.label) throw new Error("field(): a field needs a visible label");
  const kind = o.type || "text", id = o.id || uid("f");
  const control = kind === "select" ? h("select", null, (o.options || []).map((op) => h("option", { value: op.value, text: op.label })))
    : kind === "textarea" ? h("textarea", { rows: 3 }) : h("input", { type: kind === "secret" ? "password" : kind === "number" ? "text" : kind });
  Object.assign(control, { className: "field__control" + (o.mono ? " mono" : ""), id });
  if (o.name) control.name = o.name;
  const a = Object.assign(kind === "select" || kind === "file" ? {} : { autocomplete: "off" },
    kind === "number" ? { inputmode: o.decimal ? "decimal" : "numeric" } : kind === "search" ? { inputmode: "search", enterkeyhint: "search" } : {}, o.attrs);
  for (const [k, v] of Object.entries(a)) control.setAttribute(k, v);
  if (o.accept) control.accept = o.accept;
  if (o.placeholder) control.placeholder = o.placeholder;
  if (o.value != null) control.value = o.value;
  if (o.max) control.maxLength = o.max;
  if (o.disabled) control.disabled = true;
  if (o.effect) control.dataset.effect = o.effect;
  const label = h("label", { class: "field__label", for: id }, o.label, o.optional ? [" ", E("span", "field__optional", t("common_optional"))] : null);
  const hint = o.hint != null || kind === "file" ? h("p", { class: "field__hint" + (kind === "file" ? " mono" : ""), id: id + "-hint" },
    o.hint != null ? o.hint : t("common_no_file")) : null;
  const unit = o.unit ? h("span", { class: "field__unit", id: id + "-unit", text: o.unit }) : null;
  const error = h("p", { class: "field__error", id: id + "-error", hidden: true });
  attr(control, "aria-describedby", [hint, unit, error].filter(Boolean).map((e) => e.id).join(" "));
  const mods = { secret: " field--secret", number: " field--number", select: " field--select", file: " field--file" }[kind] || "";
  const wrap = h("div", { class: "field" + mods + (o.row ? " field--row" : "") + (o.short ? " field--short" : ""),
    role: kind === "search" ? "search" : null });
  let box = E("div", "field__box", control);
  if (kind === "secret") {
    const show = h("button", { class: "btn btn--ghost field__action", type: "button", "aria-controls": id, "aria-pressed": "false" });
    const set = (on) => {
      control.type = on ? "text" : "password";
      attr(show, "aria-pressed", String(on));
      show.textContent = t(on ? "common_hide" : "common_show");
      attr(show, "aria-label", t(on ? "common_hide_named" : "common_show_named", { name: o.label }));
    };
    set(false);
    on(show, "click", () => set(control.type === "password"));
    box.append(show);
    on(box, "focusout", (e) => { if (!box.contains(e.relatedTarget)) set(false); });
  } else if (unit) box.append(unit);
  else if (kind === "select") box.append(icon("chevron", "icon--s field__chevron"));
  else if (kind === "file") box.classList.add("field__drop");
  else if (kind !== "search") box = control;
  wrap.append(...[label, box, hint, error].filter(Boolean));
  Object.assign(wrap, { _control: control, _error: error, _hint: hint, _check: o.check ? () => o.check(control.value) : null });
  on(control, "input", () => { if (wrap.dataset.state === "error" && wrap._check) fieldError(wrap, wrap._check() || null); });
  if (kind === "search" && o.onSearch) {
    let timer = 0;
    const go = () => { clearTimeout(timer); o.onSearch(control.value.trim()); };
    on(control, "input", () => { clearTimeout(timer); if (control.value.trim().length >= 2 || !control.value) timer = setTimeout(go, 300); });
    on(control, "keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); go(); } else if (e.key === "Escape" && control.value) { control.value = ""; go(); }
    });
    wrap._busy = (on) => { const s = $(".spinner", box); if (on && !s) box.append(spinner()); if (!on && s) s.remove(); };
  }
  if (kind === "file") {
    on(control, "change", () => {
      const f = control.files[0], n = f ? f.size : 0;
      hint.textContent = f ? `${f.name} · ${n < 1048576 ? Math.max(1, Math.round(n / 1024)) + " KiB" : (n / 1048576).toFixed(1) + " MB"}` : t("common_no_file");
    });
    for (const ev of ["dragenter", "dragover", "dragleave", "drop"]) on(box, ev, () => attr(box, "data-state", /enter|over/.test(ev) ? "drag" : null));
  }
  return wrap;
}
function fieldError(f, text) {
  f._error.replaceChildren(...(text ? [shape("s-octagon"), E("span", null, text)] : []));
  f._error.hidden = !text;
  attr(f._control, "aria-invalid", text ? "true" : null);
  attr(f, "data-state", text ? "error" : null);
}
function check(o) {
  const descId = o.desc ? uid("desc") : null;
  const input = h("input", { class: "check__input", type: "checkbox", name: o.name, checked: !!o.checked, disabled: !!o.disabled, "aria-describedby": descId });
  const el = E("label", "check", input, E("span", "check__label" + (o.sr ? " sr" : ""), o.label), o.desc ? h("span", { class: "check__desc", id: descId, text: o.desc }) : null);
  el._control = input;
  return el;
}
// toggle({label, hint, checked, apply(on) -> sentence, confirm(on) -> ask options, security, heading})
function toggle(o) {
  const hintId = uid("hint");
  const input = h("input", { class: "toggle__input", type: "checkbox", role: "switch", checked: !!o.checked, disabled: !!o.disabled,
    "aria-describedby": o.hint ? hintId : null });
  const word = h("span", { class: "toggle__word", ...AH });
  const badge = o.security ? status("needs_look", { small: true, cls: "toggle__badge" }) : null;
  const res = h("p", { class: "result", role: "status" });
  const el = E("div", "toggle" + (o.security ? " toggle--security" : ""), o.heading ? E("h3", "toggle__heading", o.heading) : null,
    E("label", "toggle__row", input, E("span", "toggle__label", o.label), word, badge),
    o.hint ? h("p", { class: "toggle__hint", id: hintId, text: o.hint }) : null, res);
  const paint = () => { word.textContent = t(input.checked ? "common_on" : "common_off"); if (badge) badge.hidden = input.checked; };
  paint();
  on(input, "click", (e) => { if (input.getAttribute("aria-busy") === "true") e.preventDefault(); });
  on(input, "change", async () => {
    const on = input.checked, back = () => { input.checked = !on; paint(); };
    paint();
    if (!o.apply) return;
    const c = o.confirm && o.confirm(on);
    if (c && !(await ask(Object.assign({ opener: input }, c)))) return back();
    guard(o.label, async () => {
      attr(input, "aria-busy", "true");
      result(res, "run", t("common_saving"));
      try { result(res, "ok", await o.apply(on)); }
      catch (err) { if (err && err.locked) throw err; back(); result(res, "bad", errText(err, t("field_toggle_error"))); }
      finally { attr(input, "aria-busy", null); }
    }, back);
  });
  Object.assign(el, { _control: input, _result: res });
  return el;
}
// segmented({legend, legendSr, options, value, wide, apply(value), write, result})
function segmented(o) {
  const name = o.name || uid("seg");
  const fs = E("fieldset", "segmented" + (o.wide ? " segmented--wide" : "") + (o.cls ? " " + o.cls : ""),
    E("legend", o.legendSr ? "sr" : "field__label", o.legend));
  let was = o.value;
  for (const op of o.options) {
    const id = uid("opt");
    const input = h("input", { class: "segmented__input", type: "radio", name, id, value: op.value, checked: op.value === o.value, disabled: !!op.disabled });
    const label = h("label", { class: "segmented__option", for: id }, op.icon ? icon(op.icon, "icon--s") : null,
      op.label, op.count != null ? [" ", E("span", "mono", op.count)] : null);
    fs.append(input, label);
    if (o.apply) on(input, "change", () => {
      const back = () => { for (const i of $$("input", fs)) i.checked = i.value === was; };
      const run = async () => {
        const ic = $(".icon", label), sp = spinner();
        attr(input, "aria-busy", "true");
        if (ic) ic.replaceWith(sp); else label.prepend(sp);
        try { await o.apply(input.value); was = input.value; }
        catch (err) { if (err && err.locked) throw err; back(); if (o.result) result(o.result, "bad", errText(err, t("field_toggle_error"))); }
        finally { attr(input, "aria-busy", null); sp.replaceWith(...(ic ? [ic] : [])); }
      };
      if (o.write) guard(o.legend, run, back); else run();
    });
  }
  return fs;
}

// ----- form group and the saving model (5.11) -----
const groups = new Set();
// formGroup(form, {title, send(key, value) -> reply, onSaved(keys)})
function formGroup(form, o = {}) {
  const foot = $(".group__foot", form), res = $(".result", foot), save = $('[type="submit"]', form);
  let undo = $('[data-action="undo-changes"]', foot), mark = $(".group__dirty", foot);
  if (!undo) save.before(undo = btn(t("common_undo_changes"), { cls: "btn--ghost", action: "undo-changes" }));
  if (!mark) res.before(mark = status("needs_look", { cls: "group__dirty", text: t("common_unsaved_changes") }));
  const controls = () => [...form.elements].filter((e) => e.name && !/^(submit|button|file)$/.test(e.type));
  const find = (k) => controls().find((c) => c.name === k);
  const read = () => {
    const v = {};
    for (const e of controls()) {
      if (e.type !== "radio") v[e.name] = e.type === "checkbox" ? e.checked : e.value;
      else if (e.checked || !(e.name in v)) v[e.name] = e.checked ? e.value : null;
    }
    return v;
  };
  const snap = read();
  const changed = () => { const cur = read(); return Object.keys(cur).filter((k) => cur[k] !== snap[k]); };
  const write = (vals) => {
    for (const e of controls()) if (e.name in vals) {
      if (e.type === "radio") e.checked = e.value === vals[e.name]; else if (e.type === "checkbox") e.checked = !!vals[e.name]; else e.value = vals[e.name];
    }
  };
  const labelOf = (k) => {
    const e = find(k), l = e && (e.type === "radio" ? $("legend", e.closest("fieldset")) : e.labels[0]);
    return l ? ($(".check__label, .toggle__label", l) || l).firstChild.textContent.trim() : k;
  };
  const effect = (k) => (find(k) && find(k).dataset.effect) || "";
  const g = { form, changed, dirty: () => changed().length > 0 };
  const paint = () => {
    const dirty = g.dirty();
    attr(form, "data-state", dirty ? "dirty" : form.dataset.state === "dirty" ? null : form.dataset.state);
    undo.hidden = mark.hidden = !dirty;
    form.dispatchEvent(new CustomEvent("sw:dirty", { bubbles: true, detail: dirty }));
  };
  g.reset = () => { write(snap); for (const f of $$(".field", form)) fieldError(f, null); paint(); };
  on(form, "input", paint);
  on(form, "change", paint);
  on(undo, "click", () => { g.reset(); result(res, null); });
  on(form, "submit", (e) => { e.preventDefault(); g.save(); });
  g.save = () => {
    if (save.getAttribute("aria-busy") === "true") return Promise.resolve();
    const keys = changed(), fields = $$(".field", form), old = $(".group__summary", form);
    if (!keys.length) return Promise.resolve(result(res, "neutral", t("common_nothing_changed")));
    const bad = fields.filter((f) => { const err = f._check && f._check(); fieldError(f, err || null); return !!err; });
    if (old) old.remove();
    if (bad.length) {
      if (fields.length > 6 && bad.length > 1) $(".group__body", form).prepend(h("div", { class: "group__summary", role: "alert" },
        h("p", { text: t("field_error_summary", { count: bad.length }) }), h("ul", null, bad.map((f) => h("li", null,
          h("a", { href: "#" + f._control.id, text: $(".field__label", f).firstChild.textContent,
            on: { click: (e) => { e.preventDefault(); f._control.focus(); } } }))))));
      bad[0]._control.focus();
      return Promise.resolve();
    }
    return guard(o.title || labelOf(keys[0]), () => send(keys));
  };
  // changed keys only, one at a time (02 12): plain, then applies (after each job), then restarts
  async function send(keys) {
    const order = ["", "applies", "restarts"].flatMap((fx) => keys.filter((k) => effect(k) === fx));
    const cur = read(), saved = [], names = (ks) => ks.map(labelOf).join(", ");
    let failed = null, restarted = false;
    busy(save, t("common_saving"));
    for (const e of controls()) e.readOnly = true;
    try {
      for (const k of order) {
        let reply;
        try { reply = await o.send(k, cur[k]); }
        catch (err) {
          if (err && err.locked) throw err;
          failed = err || {};
          const f = err && err.field && form.elements[err.field];
          if (f && f.closest) fieldError(f.closest(".field"), err.text(""));
          break;
        }
        saved.push(k); snap[k] = cur[k];
        if (reply && reply.restarts) {
          restarted = true;
          result(res, "run", saved.length < order.length ? t("form_saved_partial", { done: saved.length, total: order.length, name: labelOf(k) })
            : t("form_saved_restarts"));
          if (conf.waitHub) await conf.waitHub();
        } else if (reply && reply.applies) {
          result(res, "run", t("form_saved_applies"));
          const end = conf.waitJob && await conf.waitJob();
          if (end && end.state === "failed") { failed = {}; break; }
        }
      }
    } finally { idle(save); for (const e of controls()) e.readOnly = false; paint(); }
    const rest = order.filter((k) => !saved.includes(k));
    if (!failed) result(res, "ok", restarted ? t("restart_saved") : t("form_saved_fields", { fields: names(saved) }));
    else result(res, "bad", saved.length ? t("form_saved_not_saved", { saved: names(saved), not_saved: names(rest) })
      : errText(failed, t("common_hub_no_answer")));
    if (o.onSaved) o.onSaved(saved);
  }
  undo.hidden = mark.hidden = true;
  groups.add(g);
  return g;
}
const dirtyGroups = () => [...groups].filter((g) => g.form.isConnected && g.dirty());
const leaveText = (list = dirtyGroups()) => list.map((g, i) => t(i ? "form_leave_next" : "form_leave_first",
  { count: g.changed().length, group: $(".group__title", g.form).textContent })).join(", ");
// unsaved-changes guard
on(doc, "click", (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#"]');
  if (!a || a.closest(".subnav, dialog, .group") || !dirtyGroups().length) return;
  e.preventDefault();
  leaveAsk(leaveText()).then((ok) => { if (ok) { for (const g of dirtyGroups()) g.reset(); location.hash = a.hash; } });
}, true);
on(window, "beforeunload", (e) => { if (dirtyGroups().length) { e.preventDefault(); e.returnValue = ""; } });

// ----- collection (6.1): sort, expand, live patch; markup as 02 6.1 -----
function collection(el, o = {}) {
  const items = () => $$(":scope > .coll__item", el);
  const sortBy = (col, dir, quiet) => {
    const head = $(`.coll__head [data-col="${col}"]`, el);
    if (!head) return;
    for (const c of $$(".coll__head [role=columnheader]", el)) attr(c, "aria-sort", c === head ? dir : null);
    const key = (it) => { const c = $(`.coll__row [data-col="${col}"]`, it); return c ? (c.dataset.sort || c.textContent).trim() : ""; };
    for (const it of items().sort((a, b) => key(a).localeCompare(key(b), "en", { numeric: true }) * (dir === "ascending" ? 1 : -1))) el.append(it);
    store.set("spoolwarden.sort." + o.name, col + ":" + dir);
    if (quiet) return;
    const text = t(dir === "ascending" ? "coll_sorted_ascending" : "coll_sorted_descending", { column: $(".coll__sort", head).firstChild.textContent.trim() });
    if (o.result) result(o.result, "info", text); else announce(text);
  };
  const expand = (x, open) => {
    attr(x, "aria-expanded", String(open));
    const region = doc.getElementById(x.getAttribute("aria-controls"));
    if (region) region.hidden = region.closest(".coll__row--detail").hidden = !open;
  };
  on(el, "click", (e) => {
    const s = e.target.closest(".coll__sort"), x = e.target.closest(".coll__expand");
    if (s) sortBy(s.dataset.sort, s.closest("[role=columnheader]").getAttribute("aria-sort") === "ascending" ? "descending" : "ascending");
    if (x) {
      const open = x.getAttribute("aria-expanded") !== "true", region = doc.getElementById(x.getAttribute("aria-controls"));
      const dirty = region ? dirtyGroups().filter((g) => region.contains(g.form)) : [];
      if (open || !dirty.length) expand(x, open);
      else leaveAsk(leaveText(dirty)).then((ok) => { if (ok) { for (const g of dirty) g.reset(); expand(x, false); } });
    }
  });
  const kept = (store.get("spoolwarden.sort." + o.name) || o.sort || "").split(":");
  if (kept[0]) sortBy(kept[0], kept[1] || "ascending", true);
  return {
    sortBy,
    patch(id, col, content) {
      const it = $(`.coll__item[data-id="${CSS.escape(id)}"]`, el), cell = it && $(`.coll__row [data-col="${col}"]`, it);
      if (!cell || cell.contains(doc.activeElement)) return false;
      const key = $(".coll__key", cell);
      cell.replaceChildren(...(key ? [key] : []), content);
      return true;
    },
  };
}
// pager({from, to, total, page, pages, go(page)}): "51–100 of 214", Previous, Next
const pager = (o) => h("nav", { class: "coll__pager", "aria-label": t("coll_pages_label") },
  E("span", "mono", t("common_pager_range", { from: o.from, to: o.to, total: o.total })),
  [[o.page - 1, "common_previous"], [o.page + 1, "common_next"]].map(([p, key]) => (p >= 1 && p <= o.pages
    ? btn(t(key), { run: () => { o.go(p); announce(t("common_page_of", { page: p, pages: o.pages })); } }) : null)));

// ----- detail region and its hosts (6.2) -----
const HOSTS = { "detail-host": "sheet sheet--detail", "drawer-host": "dialog dialog--drawer", "form-host": "dialog dialog--wide" };
function host(id) {
  let el = doc.getElementById(id);
  if (!el) doc.body.append(el = h("dialog", { class: HOSTS[id], id }));
  if (el._wired) return el;
  el._wired = modal(el, { scrim: true });
  on(el, "cancel", (e) => { const r = $(".detail", el); if (r && $('form[data-state="dirty"]', r)) { e.preventDefault(); closeDetail(r); } });
  return el;
}
// openDetail(region, {opener, focusTitle}): in place, or moved into the profile's host
function openDetail(region, o = {}) {
  const p = profile().detail, row = region.closest(".coll__row--detail");
  const hostId = p === "sheet" ? "detail-host" : row || p === "pane" ? null : p === "card" ? "form-host" : "drawer-host";
  if (!hostId) {
    if (row) { row.hidden = false; const x = $(`[aria-controls="${region.id}"]`); if (x) attr(x, "aria-expanded", "true"); }
    region.hidden = false;
  } else {
    const dlg = host(hostId), home = [region.parentNode, region.nextSibling];
    dlg.append(region); region.hidden = false;
    attr(dlg, "aria-labelledby", region.getAttribute("aria-labelledby"));
    on(dlg, "close", () => { region.hidden = true; home[0].insertBefore(region, home[1]); }, { once: true });
    openModal(dlg, o.opener);
  }
  const tt = $(".detail__title", region);
  if (tt && o.focusTitle !== false) tt.focus({ preventScroll: true });
}
async function closeDetail(region) {
  const dirty = dirtyGroups().filter((g) => region.contains(g.form));
  if (dirty.length && !(await leaveAsk(leaveText(dirty)))) return false;
  for (const g of dirty) g.reset();
  const dlg = region.closest("dialog"), row = region.closest(".coll__row--detail"), x = $(`[aria-controls="${region.id}"]`);
  if (dlg) { dlg.close(); return true; }
  region.hidden = true;
  if (row) row.hidden = true;
  if (x) { attr(x, "aria-expanded", "false"); x.focus(); }
  return true;
}

// ----- copy (6.3, 7.7): data-action="copy" buttons -----
async function copy(text, res, source) {
  try {
    await navigator.clipboard.writeText(text);
    result(res, "ok", t("common_copied"));
    setTimeout(() => result(res, null), 3000);
  } catch (e) {
    if (source) getSelection().selectAllChildren(source);
    result(res, "warn", t("common_copy_blocked"));
  }
}
on(doc, "click", (e) => {
  const b = e.target.closest && e.target.closest('[data-action="copy"]');
  const d = e.target.closest && e.target.closest(".detail__close, .detail__back");
  if (d) closeDetail(d.closest(".detail"));
  if (!b) return;
  const code = b.closest(".code"), src = code ? $(".code__text", code) : b.closest(".kv__value");
  const res = (code || b.parentElement).querySelector(".result");
  if (res) copy(b.dataset.copy != null ? b.dataset.copy : src.textContent, res, src);
});

// ----- swatch and spool ring (7.3, 7.4): checked colour as --swatch, amount as --level -----
const HEX6 = /^#[0-9A-Fa-f]{6}$/;
function paint(el, hex, level) {
  const ok = HEX6.test(hex || "");
  if (ok) el.style.setProperty("--swatch", hex); else el.style.removeProperty("--swatch");
  if (level != null) el.style.setProperty("--level", String(clamp01(level)));
  return ok;
}
function swatch(hex, o = {}) {
  const el = h("span", { class: "swatch" + (o.size ? " swatch--" + o.size : "") + (o.level != null ? " swatch--level" : ""), ...AH },
    o.level != null && !o.empty ? E("span", "swatch__fill") : null);
  if (o.empty) el.classList.add("swatch--empty");
  else if (!paint(el, hex, o.level)) el.classList.add("swatch--none");
  return el;
}
// ----- QR block (7.8): the Hub's SVG through a Blob URL -----
const qrImage = (svgText, alt) => h("img", { class: "qr__image", alt, width: 224, height: 224,
  src: URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" })) });

// ----- determinate bar (8.3) -----
// progress({label, value, valuetext, name, indeterminate, decorative, failed})
function progress(o = {}) {
  const lid = uid("pl"), role = !(o.decorative || o.indeterminate);
  const el = h("div", { class: "progress" + (o.indeterminate ? " progress--indeterminate" : ""), "aria-hidden": role ? null : "true",
    data: { state: o.failed ? "failed" : null } }, o.label ? h("p", { class: "progress__label", id: lid }, o.label) : null,
  h("div", { class: "progress__track", role: role ? "progressbar" : null, "aria-valuemin": role ? "0" : null, "aria-valuemax": role ? "100" : null,
    "aria-labelledby": o.label ? lid : null, "aria-label": o.label ? null : o.name }, E("span", "progress__fill")));
  setProgress(el, o.value || 0, o.valuetext);
  return el;
}
function setProgress(el, v, text) {
  el.style.setProperty("--level", String(clamp01(v)));
  const tr = $(".progress__track", el);
  if (tr.getAttribute("role") !== "progressbar") return;
  attr(tr, "aria-valuenow", String(Math.round(clamp01(v) * 100)));
  attr(tr, "aria-valuetext", text || null);
}
// ----- banner, empty state, error state, loading skeleton (8.8, 10.1 to 10.3) -----
const BANNER_ICON = { info: "info", warn: "warning", bad: "error", ok: "check" };
// banner({kind, title, text, actions, inline, late, dismiss, version}); null when dismissed
function banner(o) {
  const key = o.dismiss ? "spoolwarden.dismissed." + o.dismiss : null, ver = String(o.version || 1);
  if (key && store.get(key) === ver) return null;
  const el = h("div", { class: `banner banner--${o.kind}` + (o.inline ? " banner--inline" : ""), role: o.late ? (o.kind === "bad" ? "alert" : "status") : null },
    icon(BANNER_ICON[o.kind]), E("p", "banner__text", o.title ? [E("b", null, o.title), " "] : null, o.text),
    o.actions ? E("div", "actions", o.actions) : null,
    key && !o.inline ? iconBtn("close", t("common_dismiss"), { action: "dismiss", run: () => { store.set(key, ver); el.remove(); focusTitle(); } }) : null);
  return el;
}
const empty = (o) => E("div", "empty", h("span", { class: "empty__disc", ...AH }, icon(o.icon || "info", "icon--l")),
  E("h" + (o.level || 2), "empty__title", o.title), E("p", "empty__text", o.text), o.actions ? E("div", "actions", o.actions) : null);
// errorState({title, text, details, onTry, alert, level})
function errorState(o) {
  const tb = o.onTry ? btn(t("common_try_again"), { cls: "btn--primary", action: "try-again" }) : null;
  if (tb) on(tb, "click", async () => { busy(tb, t("common_trying")); try { await o.onTry(); } finally { idle(tb); } });
  return h("div", { class: "error-state", role: o.alert ? "alert" : null }, h("span", { class: "error-state__disc", ...AH }, shape("s-octagon")),
    E("h" + (o.level || 2), "error-state__title", o.title), E("p", "error-state__text", o.text || t("common_hub_no_answer")), tb,
    o.details ? E("details", "error-state__details", E("summary", null, t("common_details")), E("pre", "mono", o.details)) : null);
}
// loading(region, {thing, items, onTry, title}) -> {done(...content)}; slow line at 10 s, error at 30 s
function loading(region, o = {}) {
  attr(region, "aria-busy", "true");
  const sk = E("div", "skeleton", E("span", "sr", t("common_loading_thing", { thing: o.thing || "" })),
    Array.from({ length: o.items || 5 }, () => h("div", { class: "skeleton__item", ...AH },
      E("span", "skeleton__line skeleton__line--title"), E("span", "skeleton__line"))));
  region.replaceChildren(sk);
  const slow = setTimeout(() => sk.append(E("p", "skeleton__slow", t("common_slow"), " ", o.onTry ? btn(t("common_try_again"), { run: o.onTry }) : null)), 10000);
  const late = setTimeout(() => done(errorState({ title: o.title || t("common_timeout"), text: t("common_timeout"), onTry: o.onTry })), 30000);
  function done(...content) { clearTimeout(slow); clearTimeout(late); attr(region, "aria-busy", "false"); region.replaceChildren(...content); }
  return { done };
}

// ----- the shell (2.1 to 2.5): shell({hub, home, titleOf(section), onSection(section)}) -----
function shell(o = {}) {
  const nav = $(".nav"), more = $(".nav__more", nav);
  if (o.hub != null) conf.hub = o.hub;
  const section = () => location.hash.slice(1).split(/[/?]/)[0] || o.home || "";
  const hidden = () => $$(".nav__group > li", nav).filter((li) => li.offsetParent === null);
  const paint = (focus) => {
    let cur = null;
    for (const a of $$(".nav__group .nav__item", nav)) { const is = a.hash === "#" + section(); attr(a, "aria-current", is ? "page" : null); if (is) cur = a; }
    if (more) {
      const inMore = cur && hidden().includes(cur.closest("li")), mc = $(".nav__more-current", more);
      const name = cur ? ($(".nav__label-full", cur) || $(".nav__label", cur)).textContent.trim() : "";
      if (mc) mc.textContent = inMore ? ", " + name : "";
      attr(more, "data-state", inMore ? "current" : null);
      attr(more, "aria-label", inMore ? t("nav_more_current", { section: name }) : null);
    }
    const h1 = $("main h1"), page = o.titleOf ? o.titleOf(section()) : h1 ? h1.textContent.trim() : "";
    if (page) doc.title = t("shell_title", { page, hub: conf.hub });
    if (focus) focusTitle();
  };
  on(window, "hashchange", () => { if (o.onSection) o.onSection(section()); paint(true); });
  on(nav, "click", (e) => {
    const a = e.target.closest(".nav__item");
    if (a && a.hash === location.hash) window.scrollTo({ top: 0, behavior: reduced() ? "auto" : "smooth" });
  });
  if (more) {
    attr(more, "aria-expanded", "false");
    on(more, "click", () => {
      const body = h("nav", { class: "sheet__body nav nav--sheet", "aria-label": t("nav_more_sections") });
      for (const ul of $$(".nav__group", nav)) {
        const lis = [...ul.children].filter((li) => hidden().includes(li)), hid = uid("more");
        if (lis.length) body.append(h("h3", { class: "nav__heading", id: hid, text: doc.getElementById(ul.getAttribute("aria-labelledby")).textContent }),
          h("ul", { class: "nav__group", "aria-labelledby": hid }, lis.map((li) => {
            const c = li.cloneNode(true);
            on($("a", c), "click", () => { dlg._noReturn = true; dlg.close(); });
            return c;
          })));
      }
      const dlg = sheet({ title: t("nav_more_sections"), body: [], onClose: () => attr(more, "aria-expanded", "false") });
      $(".sheet__body", dlg).replaceWith(body);
      attr(more, "aria-expanded", "true");
      openModal(dlg, more);
      const first = $("a", body); if (first) first.focus();
    });
  }
  on(doc, "focusin", (e) => { if (phone() && e.target.matches("input:not([type=checkbox]):not([type=radio]), textarea, select")) nav.dataset.state = "hidden"; });
  on(doc, "focusout", () => attr(nav, "data-state", null));
  matchMedia("(max-width: 600px)").addEventListener("change", () => paint(false));
  for (const b of $$(".appearance--menu")) appearanceMenu(b);
  paint(false);
  return { paint };
}

window.SW = Object.freeze({
  t, h, icon, shape, uid, profile, announce, configure, api, HubError, errText, guard, lock, setLock, lockChip, unlock,
  status, spinner, tooltip, btn, iconBtn, busy, idle, disable, result, toast, ask, sheet, openModal, modal,
  leaveAsk, setAppearance, setLook, appearanceMenu, menu, field, fieldError, check, toggle, segmented, formGroup,
  collection, pager, openDetail, closeDetail, copy, swatch, paint, qrImage, progress, setProgress, banner, empty, errorState, loading, shell, phone,
});
})();
