// The kit server's setup console: everything after the install, by tab, without the command line. This file is the
// shell and the tabs that were the setup page's; setup_tabs.js and the setup_<section>.js files have the console's own.
// Talks only to /setup/api/* on the same origin. Every change sends the setup code typed in the unlock dialog (or
// none, on a trusted computer: its cookie stands in); secret fields are write-only (the server says "set" / "not set", never a value) and are cleared once sent.
// Everything from the server goes in through textContent / element properties, never innerHTML.
"use strict";
const app = document.getElementById("app");

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "class") el.className = v;
    else if (k in el && k !== "list" && k !== "style") el[k] = v;
    else el.setAttribute(k, v);
  }
  if (tag === "button" && !el.className) el.className = "btn--primary";   // the main button look (CON-9), also for class ""
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

async function api(path, body) {
  const init = { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: {} };
  if (body !== undefined) { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
  let r;
  try { r = await fetch("/setup/api/" + path, init); } catch {
    hubJobs().down();                                       // nothing answered (03 3.7)
    throw Object.assign(new Error(SW.t("common_hub_no_answer")), { unreachable: true });
  }
  hubJobs().up();
  let data;
  try { data = await r.json(); } catch { data = { error: `HTTP ${r.status}` }; }
  if (!r.ok || data.error) throw Object.assign(hubError(r.status, data), { path });
  return data;
}
// an error reply; `locked`: refused for its setup code (none, wrong, too many tries, trust gone), so the lock asks again
function hubError(status, data) {
  if (data.trust_gone) trustGone();
  const e = new Error(data.error === "bad origin" ? SW.t("hub_bad_origin") : data.error || `HTTP ${status}`);
  Object.assign(e, { data, status, locked: !!data.trust_gone || ((status === 403 || status === 429) && data.field === "code") });
  return e;
}

// ----- the lock (02 3.1, 3.2; 03 2.1): the code typed in the unlock dialog is held by the shared script in a variable,
// for this tab only, never stored; Lock now, reloading or closing the tab locks again. It goes as `code` in the body.
const theCode = () => SW.lock.code || "";
// the unlock dialog names the change in the words of the control that asked ("To revoke, enter …")
function asked() {
  const b = document.activeElement, w = b && b.matches("main button, .dialog__foot button") ? b.textContent.trim() : "";
  return w ? w[0].toLowerCase() + w.slice(1) : null;
}
// a change or a read that needs the code: while Locked the unlock dialog opens in place first, and a refusal for the code
// opens it again; after a right code it carries on. Cancel drops it (onCancel).
const needCode = (run, onCancel) => SW.guard(asked(), run, onCancel);
// the same for a request outside change(): run() may throw; any other error is said in `box`
const coded = (box, run, onCancel) => needCode(async () => {
  try { await run(); } catch (e) { if (e.locked) throw e; say(box, e.message, false); }
}, onCancel);
// reads that need the code (02 1.4; 03 2.1): paint(open) runs now and each time the page opens (Unlocked or Trusted) or
// locks; `el` stays registered while it is on the page. A refusal for the code locks the page.
const places = new Set();
function whenOpen(el, paint) {
  for (const p of places) if (!p.el.isConnected) places.delete(p);
  const p = { el, open: null, paint() {
    const open = SW.lock.state !== "locked";
    if (open === p.open) return;
    p.open = open;
    later(Promise.resolve(paint(open)).catch((e) => (e.locked ? SW.setLock("locked") : say(el, e.message, false))));
  } };
  places.add(p);
  p.paint();
}
document.addEventListener("sw:lock", () => { for (const p of places) if (p.el.isConnected) p.paint(); else places.delete(p); });
// Unlock to show: the unlock dialog as the chip opens it; the places then read by themselves
const unlockToShow = () => SW.btn(SW.t("common_unlock_to_show"), { run: (e) => SW_LOCK.unlock(null, null, null, e.currentTarget) });
// the locked placeholder (`key`: its sentence) and the hidden-values note ("lock_hidden_note")
const lockNote = (key) => h("div", { class: "banner banner--info banner--inline" }, SW.icon("lock", "icon--s"),
  h("p", { class: "banner__text" }, SW.t(key)), h("div", { class: "actions" }, unlockToShow()));
// a code-only read: loaded once open; while Locked removed and replaced by the locked placeholder
function codeRead(key, body, load) {
  const note = h("div", { role: "status" });
  whenOpen(body, (open) => {
    if (open) { note.replaceChildren(); return load(); }
    body.replaceChildren();
    note.replaceChildren(lockNote(key));
  });
  return h("div", {}, note, body);
}
// A result (02 8.6): written into the control's own status region (boxFor), with its shape and the time it was written,
// so it is read out where it was asked. `ok`: true, false or a kind (run, warn, info, neutral); `text`: a sentence (a
// Hub text as sent) or the parts of a longer answer.
function say(box, text, ok) {
  const kind = ok === true ? "ok" : ok === false ? "bad" : ok;
  box._said = kind === "run" ? null : [kind, text];
  return SW.result(box, kind, text);
}
const working = (box, text) => say(box, text, "run");
// after a change: when its control left with its row (a forgotten printer, a revoked token), the result is a toast
// (02 8.7), and focus, lost with the row, goes to the page title
function gone(box) {
  if (box.isConnected || !box._said) return;
  SW.toast(box._said[1], box._said[0]);
  const a = document.activeElement;
  if (!a || a === document.body) pageTitle.focus({ preventScroll: true });
}
function secret(placeholder) {
  return h("input", { type: "password", autocomplete: "new-password", placeholder });
}
// the fields a change sends: the row (or the [data-group] form) of the control that started it. Its region's redraw
// shows them from the new state; what is typed anywhere else stays (capture).
const sentWith = (ctl) => (ctl && ctl.closest ? ctl.closest("[data-group], .row") : null);
// A change: sends the code (and `body`), clears the secret inputs, reads the state again and draws only the region of
// `box` (refresh), then says the result there: done(reply), or "Saved.". Resolves with the reply, or null when it
// failed or the unlock dialog was cancelled.
async function change(box, path, body, done, clear) {
  let out = null;
  const sent = sentWith(document.activeElement);
  await needCode(async () => {
    working(box, SW.t("common_saving"));
    let r;
    try { r = await api(path, { ...body, code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      say(box, e.message, false);
      return;
    }
    for (const inp of clear || []) inp.value = "";
    await refresh(box, sent);
    box._said = null;
    if (done) done(r); else say(box, "Saved.", true);
    gone(box);
    out = r;
  });
  return out;
}
// A change behind a dialog (02 9.1): `o` is SW.ask's (kind, title, text, fields, confirm), `body(values)` the request.
// Confirming passes the lock (the unlock dialog opens on top and returns); a refusal stays in the dialog with what was
// typed, at the field it names; a success closes it (focus back on its button), then draws the region again and says
// the result in `box` as change() does. Resolves with the reply, or null when cancelled.
async function asking(box, path, o, body = () => ({}), done) {
  const out = await SW.ask({ ...o, run: async (values, { result }) => {
    let r = null;
    await needCode(async () => {
      try { r = await api(path, { ...body(values), code: theCode() }); } catch (e) {
        if (e.locked) throw e;
        const at = (o.fields || []).find((f) => e.data && e.data.field && f._control.name === e.data.field);
        if (at) { SW.fieldError(at, e.message); at._control.focus(); } else SW.result(result, "bad", e.message);
      }
    });
    return r || false;
  } });
  if (!out) return null;
  await refresh(box);
  box._said = null;
  if (done) done(out); else say(box, "Saved.", true);
  gone(box);
  return out;
}
// the ask options of a destructive dialog, from its catalogue keys
const destroy = (title, text, confirm, vars) => ({ kind: "destructive", title: SW.t(title, vars), text: SW.t(text, vars), confirm: SW.t(confirm) });
// a field of an entry dialog, refused while empty with the catalogue's `error`
const entryField = (o, error) => SW.field({ ...o, check: (v) => (v.trim() ? null : SW.t(error)) });
// replaceChildren would print a null as the word "null" (h() skips it, this one does not). A result slot loses its
// result; a part of a region that is read later gets what was being typed in it (carry).
function fill(el, ...kids) {
  el._said = null;
  SW.result(el, null).replaceChildren(...kids.filter(Boolean));
  const r = regionOf(el);
  if (r) carry(r);
  return el;
}
// ----- standard states (02 10; 03 2.4, 2.5) -----
// a Hub text as it is shown: first letter upper case, a full stop at the end
const hubText = (m) => { const s = String(m || "").trim(); return s ? s[0].toUpperCase() + s.slice(1) + (/[.!?…]$/.test(s) ? "" : ".") : s; };
// the error state of a region that could not be read: `key` is the catalogue's "Could not read …" text, `retry` reads again
function readFailed(el, key, e, retry) {
  fill(el, SW.errorState({ title: SW.t(key, { reason: "" }).trim(), text: hubText(e.message), onTry: retry,
    details: (e.path ? `/setup/api/${e.path}
` : "") + (e.status ? `HTTP ${e.status}: ` : "") + e.message }));
}
// A region's read: the skeleton while the first read waits (a later one keeps what is shown), then show(reply); a
// failure is the error state with Try again, which reads again. `section` is the section's name in TABS: the screen
// reader hears the section's name, and "<section>_error" is the catalogue's "Could not read …" text. A refusal for the
// code is the caller's. Resolves when the region is settled.
function readRegion(el, section, read, show) {
  const key = section + "_error";
  const go = () => {
    const L = el._loaded ? null : SW.loading(el, { thing: SW.t(TABS[section][0]), items: 3, onTry: go, title: SW.t(key, { reason: "" }).trim() });
    return Promise.resolve().then(read).then((r) => {
      if (L) L.done();
      el._loaded = true;
      show(r);
    }, (e) => {
      if (L) L.done();
      if (e.locked) throw e;
      el._loaded = false;
      readFailed(el, key, e, go);
    });
  };
  return go();
}
// A section whose feature is switched off (03 2.5): the empty state with the hollow circle and the way to Features;
// its texts are "<section>_off_title" and "<section>_off_text"
const switchedOff = (section) => SW.empty({ shape: "s-hollow", title: SW.t(section + "_off_title"), text: SW.t(section + "_off_text"),
  actions: [h("a", { class: "btn btn--primary", href: "#features", textContent: SW.t("common_go_to_features") })] });
const pill = (on, yes, no) => h("span", { class: "pill " + (on ? "ok" : "no"), textContent: on ? yes : no });
const card = (title, ...kids) => h("section", { class: "card" }, h("h2", {}, title), ...kids);

let S = null;
// result slots (02 8.6; 07 SR-12): a status region in the page before a result is written into it. Kept by key while
// the section is open, so the redraw of a region after its change keeps the slot and the result is said where it was
// asked; leaving the section clears their results (render).
const slot = () => h("div", { class: "result result--block", role: "status" });
const boxes = {};
const boxFor = (key) => boxes[key] || (boxes[key] = slot());
const sections = h("div");
// A section's own parts of the page header (02 2.1): `meta`, a line under the title, and `actions`, its buttons at the right.
// Drawn again with the section's region; cleared when the section is drawn again or another opens.
let headParts = [];
function pageHead(meta, actions) {
  for (const el of headParts) el.remove();
  headParts = [meta, actions].filter(Boolean);
  if (meta) pageTitle.after(meta);
  if (actions) page.firstElementChild.append(actions);
}

// ----- regions (02 1.4 "Redraw only what changed"; 03 2.2, 2.7): each card of a section is drawn by its own builder.
// A change reads the state again and draws only its own region (and the one its builder names in `also`). What is
// typed there and not sent, and the focus, go to the new drawing by each control's place: its row (data-key), its kind
// and words, and how many like it come before. A part a region reads later gets them when it is filled.
// A region's own reads (later()) are awaited before its change says the result, so a slot in a part drawn from such a
// read is back in the page first (or gone with its row: a toast).
let reads = null;
const later = (p) => { if (reads) reads.push(Promise.resolve(p).catch(() => {})); return p; };
const CONTROLS = "button, a[href], input, select, textarea";
const TYPED = "input:not([type=checkbox], [type=radio], [type=file]), select, textarea";
function spots(root) {
  const n = {}, out = new Map();
  for (const el of root.querySelectorAll(CONTROLS)) {
    const row = el.closest("[data-key]");
    const k = [row && root.contains(row) ? row.dataset.key : "", el.tagName, el.type, el.getAttribute("aria-label"), el.placeholder,
      el.matches("button, a") ? el.textContent : ""].join("|");
    n[k] = (n[k] || 0) + 1;
    out.set(k + "|" + n[k], el);
  }
  return out;
}
// what is typed and not sent (`sent`: see sentWith) and the focused control, by place
function capture(root, sent) {
  const keep = new Map(), now = document.activeElement;
  for (const [k, el] of spots(root)) {
    const typed = el.matches(TYPED) && el._was !== undefined && el.value !== el._was && !(sent && sent.contains(el));
    if (typed || el === now) keep.set(k, { value: typed ? el.value : null, focus: el === now, sel: el === now && el.matches(TYPED) ? [el.selectionStart, el.selectionEnd] : null });
  }
  return keep;
}
// the value each field was drawn with, to tell a typed one
const stamp = (root) => { for (const f of root.querySelectorAll(TYPED)) if (f._was === undefined) f._was = f.value; };
// puts back what capture() kept into a region now in the page; the focus only when it was lost with the old drawing
function carry(root) {
  stamp(root);
  const keep = root._keep, a = document.activeElement;
  if (!keep || !keep.size) return;
  const lost = !a || a === document.body || a === pageTitle;
  for (const [k, el] of spots(root)) {
    const v = keep.get(k);
    if (!v) continue;
    keep.delete(k);
    if (v.value != null && (el.tagName !== "SELECT" || [...el.options].some((o) => o.value === v.value))) el.value = v.value;
    if (v.focus && lost) {
      el.focus({ preventScroll: true });
      try { if (v.sel && v.sel[0] != null) el.setSelectionRange(...v.sel); } catch { /* a field without a text selection */ }
    }
  }
}
function draw(make, key) {
  const mine = reads = [];
  let el;
  try { el = make(); } finally { reads = null; }
  if (Array.isArray(el)) el = h("div", {}, el);
  if (!el) return null;
  Object.assign(el, { _make: make, _key: key, _reads: Promise.all(mine) });
  stamp(el);
  return el;
}
const regionOf = (el) => { while (el && !el._make) el = el.parentElement; return el; };
// draws one region again from the new state, in its place; `sent`: see sentWith. Resolves once its reads are in (at
// most 5 s).
function redraw(r, sent) {
  const keep = capture(r, sent), fresh = draw(r._make, r._key);
  if (!fresh) { r.remove(); return Promise.resolve(); }
  r.replaceWith(fresh);
  fresh._keep = keep;
  carry(fresh);
  return Promise.race([fresh._reads, new Promise((done) => setTimeout(done, 5000))]);
}

// ----- the sections (F8), at the page's own addresses (03 1.2): #<section>[/<place>]; Back and Forward move between them -----
// [catalogue key of the name, icon, the builders of its regions]; the first five are the Everyday group, the rest the
// System group
const TABS = {
  overview: ["nav_overview", "overview", () => [overviewTab]],
  printers: ["nav_printers", "printer", () => printersTab()],
  recent: ["nav_recently_added", "recent", () => [intakeTab]],
  devices: ["nav_devices", "devices", () => [pairCard, stationAsksCard, webAppCard, readersCard, trustCard]],
  presets: ["nav_slicer_presets", "presets", () => [presetsTab]],
  features: ["nav_features", "features", () => [modesCard, modulesCard, applyCard]],
  settings: ["nav_settings", "settings", () => [generalCard, readerCard, backupCard, keyCard, passphraseCard, tokenCard, libraryCard, addressCard, remoteCard]],
  flash: ["nav_flash_device", "flash", () => [flashTab]],
  updates: ["nav_updates", "updates", () => [updatesTab]],
  logs: ["nav_logs", "logs", () => [logsTab]],
};
const GROUPS = [["everyday", "nav_everyday", 0, 5], ["system", "nav_system", 5, 10]];
const BAR = new Set(["overview", "printers", "recent", "settings"]);   // the phone bottom bar (02 2.4); the rest are in More
const MOVED = { modules: "features", intake: "recent" };              // the tabs' old addresses
const tabNow = () => { const t = location.hash.slice(1).split(/[/?]/)[0]; return Object.hasOwn(TABS, t) ? t : "overview"; };

// draws every region of the section; drawn again in the same section (a job ended, the lock changed), what is typed
// and the focus stay; on entering a section, the results left in its slots are cleared (02 8.6)
let shown = null;
function render() {
  const now = tabNow(), keep = new Map();
  if (now === shown) { for (const r of sections.children) if (r._key) keep.set(r._key, capture(r)); }
  else for (const b of Object.values(boxes)) if (b.dataset.state) SW.result(b, null);
  shown = now;
  pageHead();
  page.dataset.section = now;
  pageTitle.textContent = SW.t(TABS[now][0]);
  const regions = TABS[now][2]().filter(Boolean).map((m, i) => draw(m, m.name || "#" + i)).filter(Boolean);
  sections.replaceChildren(...regions);
  for (const r of regions) { r._keep = keep.get(r._key); carry(r); }
  summaries();
}

// Reads the state again. After a change (`at`: an element of its region; `sent`: see sentWith) only that region is
// drawn again, and the one its builder names in `also`; without `at` (the page opens, a job ends) the whole section is.
async function refresh(at, sent) {
  const r = at && regionOf(at);
  try { S = await api("state"); } catch (e) {
    if (!S) { hubName.parentElement.dataset.state = "error"; hubName.replaceChildren(SW.shape("s-octagon"), SW.t("topbar_hub_unreachable")); }
    if (!at) { const box = h("div"); readFailed(box, "overview_error", e, () => refresh()); sections.replaceChildren(box); shown = null; }
    return;
  }
  hubName.replaceChildren(S.server_name);
  hubVersion.replaceChildren(SW.h("span", { class: "sr", text: SW.t("topbar_version_prefix") }), S.version);
  SW.configure({ hub: S.server_name, noCode: !S.code_set });
  if (!at) render();
  else if (r && r.isConnected) {
    const also = r._make.also && [...sections.children].find((x) => x._make === r._make.also);
    const drawn = [redraw(r, sent), also && redraw(also)];
    summaries();
    await Promise.all(drawn);
  }
  if (shellView) shellView.paint(false);
  if (S.apply.running) followApply();
}

// ----- the shell (02 2.1-2.6; 03 3.1, 3.2, 3.8): top bar, navigation (a rail; on phones the bottom bar and the More
// sheet), the page frame. Its behaviour (current section, title, More, the bar hiding over the keyboard) is SW.shell's.
const hubName = h("span", {}, h("span", { class: "skeleton__line", "aria-hidden": "true" })), hubVersion = h("span", { class: "topbar__version mono" });
const pageTitle = h("h1", { class: "page-head__title", tabindex: "-1" });
const page = h("section", { class: "page" }, h("header", { class: "page-head" }, h("div", { class: "page-head__text" }, pageTitle)));
const navEl = h("nav", { class: "nav" });
let shellView = null;

function topBar() {
  const hub = h("span", { class: "topbar__hub" }, h("span", { "aria-hidden": "true" }, "/"), " ", hubName);
  return h("header", { class: "topbar" },
    h("a", { class: "topbar__brand", href: "#overview" }, SW.h("svg", { class: "topbar__mark", "aria-hidden": "true", focusable: "false" }, SW.h("use", { href: "#i-spoolwarden" })),
      h("span", { class: "topbar__name" }, SW.t("app_name")), " ", hub),
    hubVersion,
    h("div", { class: "topbar__tools" }, hubJobs().chip, SW_LOCK.lockChip({ loading: true }), appearanceControl(), appearanceButton()));
}

function navigation() {
  navEl.setAttribute("aria-label", SW.t("nav_label"));
  const names = Object.keys(TABS);
  for (const [group, key, from, to] of GROUPS) {
    navEl.append(h("h2", { class: "nav__heading", id: "nav-" + group }, SW.t(key)),
      h("ul", { class: "nav__group", "data-group": group, "aria-labelledby": "nav-" + group }, names.slice(from, to).map((s) => h("li", {}, navItem(s)))));
  }
  navEl.append(h("button", { class: "nav__more", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false" },
    SW.icon("more", "nav__icon"), h("span", { class: "nav__label" }, SW.t("nav_more")), h("span", { class: "sr nav__more-current" })));
  return navEl;
}
function navItem(s) {
  const [key, icon] = TABS[s];
  const label = s === "recent"          // the bottom bar shows the short name; the full one is read (02 2.4)
    ? h("span", { class: "nav__label" }, h("span", { class: "nav__label-full" }, SW.t(key)), h("span", { class: "nav__label-short", "aria-hidden": "true" }, SW.t("nav_recent")))
    : h("span", { class: "nav__label" }, SW.t(key));
  const a = h("a", { class: "nav__item", href: "#" + s }, SW.icon(icon, "nav__icon"), label, h("span", { class: "nav__summary" }),
    SW.icon("chevron", "icon--s nav__chevron"));
  if (BAR.has(s)) a.setAttribute("data-tab", "");
  return a;
}
// the live summaries of the More sheet, from the replies the page already has (02 12: a section without data shows none)
function summaries() {
  const put = (s, text) => { const el = navEl.querySelector(`a[href="#${s}"] .nav__summary`); if (el) el.textContent = text || ""; };
  const P = S.printers.on ? S.printers.list.filter((p) => p.configured) : [];
  const up = P.filter((p) => p.state === "connected").length;
  put("printers", P.length ? SW.t("nav_summary_printers", { connected: up, offline: P.length - up }) : "");
  put("devices", SW.t("nav_summary_devices", { paired: S.devices.length, count: S.readers.list.length }));
}
// an old or unknown address opens Overview (03 1.2); the address says so, so the navigation marks it
function settleAddress() {
  const t = location.hash.slice(1).split(/[/?]/)[0];
  if (t && !Object.hasOwn(TABS, t)) history.replaceState(null, "", MOVED[t] ? "#" + MOVED[t] + location.hash.slice(1 + t.length) : "#overview");
}

// ----- appearance (02 3.3, F5): the three choices on this device, applied at once and kept by the shared script -----
const APPEARANCE_KEY = "spoolwarden.appearance";
const APPEARANCE = [["light", "sun"], ["dark", "moon"], ["system", "half-circle"]];
const appearanceNow = () => { const v = document.documentElement.getAttribute("data-theme"); return v === "light" || v === "dark" ? v : "system"; };
// the wide form: the shared segmented choice (its change is handled by the shared script)
const appearanceControl = () => SW.segmented({ legend: SW.t("appearance_title"), legendSr: true, cls: "appearance", name: "appearance",
  value: appearanceNow(), options: APPEARANCE.map(([value, icon]) => ({ value, icon, label: SW.t("appearance_" + value) })) });
// the phone form: an icon button; SW.shell gives it its menu
function appearanceButton() {
  const [v, icon] = APPEARANCE.find(([x]) => x === appearanceNow());
  return h("button", { class: "btn btn--ghost btn--icon appearance appearance--menu", type: "button",
    "aria-label": SW.t("appearance_name", { choice: SW.t("appearance_" + v) }) }, SW.icon(icon));
}
window.addEventListener("storage", (e) => {                   // another tab chose: follow it
  if (e.key !== APPEARANCE_KEY && e.key !== null) return;
  const v = e.key === null ? null : e.newValue;
  SW.setAppearance(v === "light" || v === "dark" ? v : "system");
});

document.addEventListener("DOMContentLoaded", () => {
  SW.configure({ base: "/setup/api/", checkPath: "code/check" });
  settleAddress();
  const skip = h("a", { class: "skip", href: "#main" }, SW.t("common_skip_to_content"));
  const main = h("main", { class: "shell__main", id: "main", tabindex: "-1" }, page);
  skip.addEventListener("click", (e) => { e.preventDefault(); main.focus(); });   // the address keeps the section
  page.append(sections);
  app.replaceWith(skip, h("div", { class: "shell" }, topBar(), navigation(), main), hubJobs().strip,
    h("div", { class: "toasts", "aria-live": "polite" }), h("div", { class: "sr", id: "announcer", "aria-live": "polite" }));
  pageTitle.textContent = SW.t(TABS[tabNow()][0]);
  shellView = SW.shell({ hub: document.title, home: "overview", titleOf: () => SW.t(TABS[tabNow()][0]), onSection: () => {
    settleAddress();
    window.scrollTo(0, 0);
    if (S) render(); else pageTitle.textContent = SW.t(TABS[tabNow()][0]);
  } });
  loadTrust().then(refresh);
});
