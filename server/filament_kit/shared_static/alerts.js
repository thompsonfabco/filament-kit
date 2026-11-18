// Spoolwarden shared alerts (DECISIONS R80 sections 3 to 5 and 8; docs/design/02-components.md 8.8): the alert banner host, the
// Alerts list, the events poller and the browser-notification helper. Loaded after components.js (window.SW) and, with
// alerts.css, by every interface that shows alerts. It adds window.SW_ALERTS. It reads GET api/events (R80 section 8) with
// SW.api; nothing here writes to the Hub. Texts: the `alert_*` keys of the string catalogue.
(() => {
"use strict";
const SW = window.SW, doc = document;
const { h, t, banner, btn, icon, toast, ask, openModal } = SW;
const E = (tag, cls, ...kids) => h(tag, { class: cls }, ...kids);
const DAY = 86400000, WEEK = 7 * DAY, KEEP = "spoolwarden.dismissed.alert.", FLAG = "spoolwarden.alerts.notifications";

// ----- CONTRACT NAMES TO CHECK AGAINST EA3 -----
// Names this file GUESSES because the design left them open; when EA3 lands, check each against the real event `data`.
// A list is tried in order, the first one present wins. Also guessed (keys of PLACES and HUB_HREF below): action.place values
// printer, storage-use (or storage), running-low, devices. Other data names read (settled): job, percent, reason, text, free,
// total, spool, filament, last_seen; subject.name is the printer or device name.
const CONTRACT = {
  data: {
    others: ["others", "in_stock"],              // spool.low: how many more of the filament are in stock
    grams: ["grams", "grams_left"],              // spool.low: what is left on the spool
    pausedWhy: ["reason_text", "stage"],         // print.paused: the sentence after "paused at n %"
    failedWhy: ["error", "error_text"],          // print.failed: the sentence after "stopped at n %" (reason "cancelled" has its own)
  },
};
const pick = (d, names) => { for (const n of names) if (d[n] != null && d[n] !== "") return d[n]; return null; };

// ----- texts: the catalogue's own (strings/en.json holds every alert_* key) -----
const tx = t;

// ----- what an event says: title, sentence and the place that fixes it (R80 section 5's table) -----
const num = (n) => (n == null || n === "" ? null : n);
const size = (n) => {
  const v = typeof n === "string" && /^\d+(\.\d+)?$/.test(n.trim()) ? Number(n) : n;          // a stored value is text
  if (typeof v !== "number") return n;
  for (const [unit, step] of [["TB", 1e12], ["GB", 1e9], ["MB", 1e6], ["kB", 1e3]]) if (v >= step) { const x = v / step; return (x >= 10 || step < 1e9 ? x.toFixed(0) : x.toFixed(1)) + " " + unit; }
  return v.toFixed(0) + " B";          // as the Hub writes a size (alerts_api.size_text)
};
const pad = (n) => String(n).padStart(2, "0");
let clock = () => Date.now();
const at = (e) => Date.parse(e.at) || 0;
function stamp(ms) {
  const d = new Date(ms), n = new Date(clock()), hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
  return d.toDateString() === n.toDateString() ? hm : d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + " " + hm;
}
function ago(ms) {
  const m = Math.max(0, Math.floor((clock() - ms) / 60000));
  if (m < 1) return tx("alert_just_now");
  if (m < 60) return tx("alert_minutes_ago", { count: m });
  if (m < 1440) return tx("alert_hours_ago", { count: Math.floor(m / 60) });
  return tx("alert_days_ago", { count: Math.floor(m / 1440) });
}
// [title key, title values, sentence parts]; a null value in a sentence falls back to the Hub's own built text
function words(e) {
  const d = e.data || {}, sub = (e.subject && e.subject.name) || null, bad = e.severity === "bad";
  const last = num(d.last_seen) != null ? Date.parse(d.last_seen) || at(e) : at(e);
  switch (e.kind) {
    case "print.runout": return [["alert_title_runout", { printer: sub }], [["alert_text_runout", { job: num(d.job), percent: num(d.percent) }]]];
    case "print.paused": return [["alert_title_paused", { printer: sub }], [["alert_text_paused", { job: num(d.job), percent: num(d.percent) }], pick(d, CONTRACT.data.pausedWhy)]];
    case "print.failed": return [["alert_title_failed", { printer: sub }], [["alert_text_failed", { job: num(d.job), percent: num(d.percent) }], pick(d, CONTRACT.data.failedWhy) || (d.reason === "cancelled" ? tx("alert_cancelled") : null)]];
    case "printer.error": return [["alert_title_error", { printer: sub }], [d.text || d.error || null]];
    case "print.finished": return [["alert_title_finished", { printer: sub }], [["alert_text_finished", { job: num(d.job) }]]];
    case "storage.low": return [[bad ? "alert_title_storage_bad" : "alert_title_storage_warn", {}],
      [[bad ? "alert_text_storage_bad" : "alert_text_storage_warn", { free: size(num(d.free)), total: size(num(d.total)), percent: num(d.percent) }]]];
    case "spool.low": {
      const more = num(pick(d, CONTRACT.data.others));
      return [["alert_title_low", { filament: num(d.filament) }], [["alert_text_low", { id: num(d.spool), grams: num(pick(d, CONTRACT.data.grams)) }],
        more == null ? null : more > 0 ? ["alert_text_low_more", { count: more }] : ["alert_text_low_last", {}]]];
    }
    case "device.down": return [["alert_title_device_down", { device: sub }], [["alert_text_device_down", { time: stamp(last) }]]];
    case "printer.offline": return [["alert_title_offline", { printer: sub }], [["alert_text_offline", { time: stamp(last) }]]];
    default: return null;
  }
}
const have = (vars) => Object.values(vars).every((v) => v != null);
function describe(e) {
  const w = words(e);
  let title = e.title || "", text = e.text || "";
  if (w && have(w[0][1])) {
    title = tx(w[0][0], w[0][1]);
    const parts = w[1].filter((p) => p != null);
    if (parts.length && parts.every((p) => typeof p === "string" || have(p[1]))) text = parts.map((p) => (typeof p === "string" ? p : tx(p[0], p[1]))).join(" ");
  }
  return { kind: e.severity === "bad" ? "bad" : e.severity === "ok" ? "ok" : e.severity === "info" ? "info" : "warn", title, text, action: actionOf(e) };
}
const PLACES = { printer: "alert_open_printer", "storage-use": "alert_show_storage", storage: "alert_show_storage", "running-low": "alert_show_low",
  devices: "alert_open_devices" };
const PLACE_OF = { "print.runout": "printer", "print.paused": "printer", "print.failed": "printer", "printer.error": "printer", "print.finished": "printer",
  "printer.offline": "printer", "storage.low": "storage-use", "spool.low": "running-low", "device.down": "devices" };
function actionOf(e) {
  const place = (e.action && e.action.place) || PLACE_OF[e.kind];
  if (!PLACES[place]) return null;
  return { place, id: (e.action && e.action.id) || (e.subject && e.subject.id) || null, label: tx(PLACES[place]) };
}
// where an action goes: the Hub page's addresses (R80 section 8); an interface with other places passes `href` or `open`
const HUB_HREF = { printer: "#printers", "storage-use": "#overview/storage-use", storage: "#overview/storage-use", "running-low": "#overview/running-low", devices: "#devices" };

// ----- state -----
const state = { cursor: null, events: new Map(), conditions: [], raised: new Set(), first: true, painted: false };
const opts = { host: null, interval: 10000, href: (a) => HUB_HREF[a.place] || null, open: null, limit: 200 };
let loaded = 0;                 // the clock when the page started polling; events from before it (less the clock skew allowed) never arrive as new
const SKEW = 10 * 60000;
let timer = 0, tick = 0, running = false, polling = false, host = null, dlg = null;
const shown = new Map();      // banner key -> {ver, el}
const rank = (s) => (s === "bad" ? 2 : s === "warn" ? 1 : 0);

// the banners wanted now: raised conditions (alert types that are on), then moments (warn or bad, at most 24 h old)
function candidates() {
  const out = [];
  for (const c of state.conditions) {
    if (c.alert === false || !c.condition) continue;
    out.push({ key: c.condition.key, ver: `${c.id}:${c.severity}`, e: c, at: at(c), condition: true });
  }
  for (const e of state.events.values()) {
    if (e.alert !== true || rank(e.severity) === 0 || (e.condition && e.condition.state !== "cleared") || clock() - at(e) > DAY) continue;
    out.push({ key: "e" + e.id, ver: `${e.id}:${e.severity}`, e, at: at(e), condition: false });
  }
  return out.sort((a, b) => rank(b.e.severity) - rank(a.e.severity) || b.at - a.at || b.e.id - a.e.id);
}
const dismissed = (c) => keep.get(KEEP + c.key) === c.ver;
const keep = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  keys() { try { return Object.keys(localStorage).filter((k) => k.startsWith(KEEP)); } catch (e) { return []; } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* none */ } } };
const hrefOf = (a) => (opts.href ? opts.href(a) : null);
function actionEl(a, name, primary) {
  if (!a) return null;
  const cls = "btn" + (primary ? " btn--primary" : "");
  if (opts.open) return btn(a.label, { cls, name: `${a.label}: ${name}`, run: () => { if (dlg && dlg.open) dlg.close(); opts.open(a); } });
  const href = hrefOf(a);
  return href ? h("a", { class: cls, href, "aria-label": `${a.label}: ${name}`, on: { click: () => { if (dlg && dlg.open) dlg.close(); } } }, a.label) : null;
}
const timeOf = (c) => (c.condition ? tx("alert_since", { time: stamp(c.at) }) : ago(c.at));

function makeBanner(c, late) {
  const d = describe(c.e), time = E("span", "alert__time", timeOf(c));
  const el = banner({ kind: d.kind === "bad" ? "bad" : "warn", title: d.title, text: [d.text, " ", time], late,
    actions: actionEl(d.action, d.title, true), dismiss: "alert." + c.key, version: c.ver });
  if (!el) return null;
  el.dataset.alert = c.key;
  if (late) setTimeout(() => el.removeAttribute("role"), 4000);       // announced once; later time changes are not
  return el;
}
function paint() {
  if (!host) return;
  const all = candidates(), live = new Set(all.map((c) => c.key));
  for (const k of keep.keys()) if (!live.has(k.slice(KEEP.length))) keep.del(k);
  const vis = all.filter((c) => !dismissed(c)), top = vis.slice(0, 2), els = [];
  for (const [k, s] of [...shown]) if (!top.some((c) => c.key === k && c.ver === s.ver)) shown.delete(k);
  for (const c of top) {
    let s = shown.get(c.key);
    if (!s || !s.el.isConnected) {
      const el = makeBanner(c, state.painted);
      if (!el) continue;
      shown.set(c.key, s = { ver: c.ver, el });
    }
    const tm = s.el.querySelector(".alert__time"), now = timeOf(c);
    if (tm && tm.textContent !== now) tm.textContent = now;
    els.push(s.el);
  }
  if (vis.length > top.length) {
    let more = host.querySelector(".alert-more");
    const label = tx("alert_more", { count: vis.length - top.length });
    if (!more) more = E("p", "alert-more", btn(label, { cls: "btn--ghost", action: "alerts-more", run: (ev) => openList(ev.currentTarget) }));
    const b = more.querySelector("button");
    if (b.textContent !== label) b.textContent = label;
    els.push(more);
  }
  if (els.length !== host.children.length || els.some((el, i) => host.children[i] !== el)) host.replaceChildren(...els);
  state.painted = true;
}

// ----- the Alerts list: raised conditions first, then the alert events of the last 7 days, newest first -----
function row(c) {
  const d = describe(c.e), name = d.title;
  const act = actionEl(d.action, name, false);
  return h("li", { class: `alert-row alert-row--${d.kind}` }, icon(d.kind === "bad" ? "error" : d.kind === "ok" ? "check" : d.kind === "info" ? "info" : "warning"),
    E("div", "alert-row__body", E("b", "alert-row__title", d.title), d.text ? E("span", "alert-row__text", d.text) : null,
      E("span", "alert-row__time", timeOf(c))), act);
}
function listBody() {
  const raised = state.conditions.filter((c) => c.condition).map((c) => ({ key: c.condition.key, e: c, at: at(c), condition: true }))
    .sort((a, b) => rank(b.e.severity) - rank(a.e.severity) || b.at - a.at);
  const ids = new Set(raised.map((c) => c.e.id));
  const events = [...state.events.values()].filter((e) => e.alert === true && !ids.has(e.id) && clock() - at(e) <= WEEK)
    .sort((a, b) => at(b) - at(a) || b.id - a.id).map((e) => ({ key: "e" + e.id, e, at: at(e), condition: false }));
  const group = (title, rows) => (rows.length ? [h("h3", { class: "alert-list__heading", text: title }), E("ul", "alert-list__items", rows.map(row))] : []);
  if (!raised.length && !events.length) return E("div", "alert-list", E("p", "alert-list__empty", tx("alert_list_empty")));
  return E("div", "alert-list", group(tx("alert_list_raised"), raised), group(tx("alert_list_earlier"), events));
}
function openList(opener) {
  return ask({ kind: "info", wide: true, title: tx("alert_list_title"), body: listBody(), opener, open: (d, op) => { dlg = d; openModal(d, op); } })
    .then((r) => { dlg = null; return r; });
}

// ----- arrival: a toast and a browser notification per new alert; a condition only when it is raised, not while it lasts -----
function arrive(e) {
  if (e.alert !== true) return;
  if (e.condition && e.condition.state === "raised" && state.raised.has(e.condition.key)) return;
  const d = describe(e), a = d.action, href = a && hrefOf(a);
  toast(d.title, d.kind, a && (opts.open || href) ? { action: { label: t("common_show"), name: `${a.label}: ${d.title}`, run: () => { if (opts.open) opts.open(a); else location.href = href; } } } : {});
  notifications.show(e, d, href);
}
function ingest(res) {
  const first = state.first || res.gap === true, seen = state.events;      // a gap: older events were dropped, so resync from the conditions, no replay
  const list = (res.events || []).slice().sort((a, b) => a.id - b.id);
  // the first answers are the backfill of the last 7 days, oldest first: a full one means more follow, and all of it is history
  const full = state.first && res.gap !== true && list.length >= opts.limit;
  const fresh = [];
  for (const e of list) {
    if (seen.has(e.id)) continue;
    seen.set(e.id, e);
    if (!first && at(e) >= loaded - SKEW) fresh.push(e);          // an event from before the page opened is history, whatever its place in the answer
  }
  if (first && Array.isArray(res.conditions)) state.raised = new Set(res.conditions.filter((c) => c.condition).map((c) => c.condition.key));
  for (const e of fresh) {
    arrive(e);
    if (e.condition) state.raised[e.condition.state === "raised" ? "add" : "delete"](e.condition.key);
  }
  if (Array.isArray(res.conditions)) {
    state.conditions = res.conditions;
    state.raised = new Set(res.conditions.filter((c) => c.condition).map((c) => c.condition.key));
  }
  for (const e of list) if (e.condition && e.condition.state === "cleared") notifications.close(e.condition.key);
  notifications.sync(state.raised);
  if (res.gap === true && res.oldest != null) for (const id of [...seen.keys()]) if (id < res.oldest) seen.delete(id);
  if (res.test && (res.test.title || res.test.text)) {        // "Send a test alert": once, to this browser only
    const d = { kind: "ok", title: res.test.title || tx("alert_test_title"), text: res.test.text || "", action: null };
    toast(d.title, "ok");
    notifications.show({ id: "test" }, d, null);
  }
  const top = Math.max(0, ...[...seen.keys()]);
  if (full) state.cursor = Math.max(state.cursor || 0, list[list.length - 1].id);      // page on from the last id of this answer, not from `next`
  else state.cursor = Math.max(Number(res.next) || 0, state.cursor || 0, top);
  for (const [id, e] of seen) if (clock() - at(e) > WEEK) seen.delete(id);
  state.first = full;
  paint();
}
// the page's own id (random, kept in this browser; the Hub stores nothing about it)
function clientId() {
  let id = keep.get("spoolwarden.browser");
  if (!id) {
    id = (window.crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));
    try { localStorage.setItem("spoolwarden.browser", id); } catch (e) { /* none */ }
  }
  return id;
}
async function poll() {
  if (polling) return;
  polling = true;
  try {
    // the first call asks for the last 7 days by time, and pages on (since the last id, same limit) while the answer is full; the
    // next ones ask for what is after the cursor; `client` is this browser's own id
    for (let more = true; more;) {
      const before = state.cursor, lim = `&limit=${opts.limit}`;
      const from = state.cursor == null ? `since_at=${new Date(clock() - WEEK).toISOString().replace(/\.\d+Z$/, "Z")}${lim}` : `since=${state.cursor}${state.first ? lim : ""}`;
      const q = `${from}&alert=1&wait=0&client=${encodeURIComponent(clientId())}`;
      const res = await (opts.api || SW.api)("events?" + q);
      // the Hub's ids went back (restored from a backup, or reinstalled): our cursor is from another store, so start over as the first call does
      if (state.cursor != null && res && res.next != null && Number(res.next) < state.cursor) {
        Object.assign(state, { cursor: null, events: new Map(), first: true });
        more = true;
        continue;
      }
      ingest(res);
      more = state.first && state.cursor !== before;
      if (state.first && !more) state.first = false;          // a full answer that moved nothing: stop paging
    }
  } catch (err) {
    if (opts.onError) opts.onError(err);
  } finally { polling = false; }
}
function stop() { running = false; clearTimeout(timer); clearInterval(tick); }
// start({host, interval, href(action) -> address | null, open(action), api(path), now(), Notification, onError}): the first poll's promise
function start(o = {}) {
  stop();
  Object.assign(opts, { api: null, open: null, onError: null, Notification: null }, o);
  clock = opts.now || (() => Date.now());
  loaded = clock();
  notifications.held.clear();
  host = opts.host || doc.querySelector(".alert-host");
  if (!host) {
    const main = doc.querySelector("main");
    if (main) main.prepend(host = E("div", "alert-host"));
  }
  Object.assign(state, { cursor: null, events: new Map(), conditions: [], raised: new Set(), first: true, painted: false });
  shown.clear();
  if (host) {
    host.replaceChildren();
    host.onclick = (ev) => { if (ev.target.closest('[data-action="dismiss"]')) paint(); };     // the banner stored its dismissal first
  }
  running = true;
  const loop = () => { timer = setTimeout(async () => { await poll(); if (running) loop(); }, opts.interval); };
  const first = poll();
  first.then(() => { if (running) loop(); });
  tick = setInterval(paint, 30000);           // the times and the 24 h end
  return first;
}

// ----- browser notifications: only while a page tab is open; the Hub's own address needs its certificate accepted -----
const Note = () => opts.Notification || window.Notification;
const notifications = {
  // "unsupported" | "denied" | "granted" | "default"
  permission() { const N = Note(); return !N || window.isSecureContext === false ? "unsupported" : N.permission; },
  on() { return SW_FLAG.get() && this.permission() === "granted"; },
  // the device switch: asks the browser once; on only when it said yes; answers the permission
  async set(on) {
    if (!on) { SW_FLAG.set(false); return this.permission(); }
    let p = this.permission();
    if (p === "default") { try { p = await Note().requestPermission(); } catch (e) { p = "denied"; } }
    SW_FLAG.set(p === "granted");
    return p;
  },
  // the words under the switch: null when nothing is to be said
  say() {
    const p = this.permission();
    return p === "denied" ? { text: tx("alert_notify_blocked"), hint: tx("alert_notify_blocked_hint") }
      : p === "unsupported" ? { text: tx("alert_notify_unsupported"), hint: tx("alert_notify_unsupported_hint") } : null;
  },
  held: new Map(),            // condition key -> its notification, so the clearing event can close it
  // a raised condition is tagged by its key (the clearing event finds it again), a moment by its event id
  show(e, d, href) {
    if (!this.on()) return null;
    const key = e.condition && e.condition.state === "raised" ? e.condition.key : null;
    try {
      const n = new (Note())(d.title, { body: d.text, tag: key ? "sw-condition-" + key : "sw-event-" + e.id });
      n.onclick = () => { try { window.focus(); n.close(); } catch (x) { /* none */ } if (href) location.href = href; };
      if (key) { this.held.set(key, n); n.onclose = () => { if (this.held.get(key) === n) this.held.delete(key); }; }
      return n;
    } catch (err) { return null; }
  },
  // where the platform allows: close what a cleared condition showed (nothing new is sent)
  close(key) {
    const n = this.held.get(key);
    this.held.delete(key);
    if (n) try { n.close(); } catch (err) { /* none */ }
  },
  sync(raised) { for (const key of [...this.held.keys()]) if (!raised.has(key)) this.close(key); },
};
const SW_FLAG = { get() { try { return localStorage.getItem(FLAG) === "1"; } catch (e) { return false; } },
  set(on) { try { on ? localStorage.setItem(FLAG, "1") : localStorage.removeItem(FLAG); } catch (e) { /* none */ } } };

window.SW_ALERTS = Object.freeze({ start, stop, poll, ingest, paint, openList, describe, notifications, clientId, state: () => ({
  cursor: state.cursor, events: [...state.events.values()], conditions: state.conditions.slice() }) });
})();
