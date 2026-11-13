// The kit server's setup console: everything after the install, by tab, without the command line. This file is the
// shell and the tabs that were the setup page's; setup_tabs.js has the console's own.
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
  const r = await fetch("/setup/api/" + path, init);
  let data;
  try { data = await r.json(); } catch { data = { error: `HTTP ${r.status}` }; }
  if (!r.ok || data.error) throw hubError(r.status, data);
  return data;
}
// an error reply; `locked`: refused for its setup code (none, wrong, too many tries, trust gone), so the lock asks again
function hubError(status, data) {
  if (data.trust_gone) trustGone();
  const e = new Error(data.error || `HTTP ${status}`);
  Object.assign(e, { data, status, locked: !!data.trust_gone || ((status === 403 || status === 429) && data.field === "code") });
  return e;
}

// ----- the lock (02 3.1, 3.2; 03 2.1): the code typed in the unlock dialog is held by the shared script in a variable,
// for this tab only, never stored; Lock now, reloading or closing the tab locks again. It goes as `code` in the body.
const theCode = () => SW.lock.code || "";
// the unlock dialog names the change in the words of the control that asked ("To revoke, enter …")
function asked() {
  const b = document.activeElement, w = b && b.matches("main button") ? b.textContent.trim() : "";
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
    Promise.resolve(paint(open)).catch((e) => (e.locked ? SW.setLock("locked") : say(el, e.message, false)));
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
const say = (box, text, ok) => box.replaceChildren(h("pre", { class: ok ? "ok" : "err", textContent: text }));
function secret(placeholder) {
  return h("input", { type: "password", autocomplete: "new-password", placeholder });
}
// A change: sends the code (and `body`), says the result in `box`, clears the secret inputs, reloads the page's state.
// Resolves with the reply, or null when it failed or the unlock dialog was cancelled.
async function change(box, path, body, done, clear) {
  let out = null;
  await needCode(async () => {
    box.replaceChildren(h("p", { class: "muted", textContent: "Saving…" }));
    try {
      const r = await api(path, { ...body, code: theCode() });
      for (const inp of clear || []) inp.value = "";
      if (done) done(r); else say(box, "Saved.", true);
      refresh();
      out = r;
    } catch (e) { if (e.locked) { box.replaceChildren(); throw e; } say(box, e.message, false); }
  });
  return out;
}
// replaceChildren would print a null as the word "null" (h() skips it, this one does not)
const fill = (el, ...kids) => el.replaceChildren(...kids.filter(Boolean));
const pill = (on, yes, no) => h("span", { class: "pill " + (on ? "ok" : "no"), textContent: on ? yes : no });
const card = (title, ...kids) => h("section", { class: "card" }, h("h2", {}, title), ...kids);

let S = null;
// result boxes outlive a re-render (every change reloads the state), so a token shown once or a QR code stays
const boxes = {};
const boxFor = (key) => boxes[key] || (boxes[key] = h("div", { role: "status" }));   // a live region: "Saving…" and the result are read out
const sections = h("div");

// ----- the sections (F8), at the page's own addresses (03 1.2): #<section>[/<place>]; Back and Forward move between them -----
// [catalogue key of the name, icon, the view]; the first five are the Everyday group, the rest the System group
const TABS = {
  overview: ["nav_overview", "overview", () => overviewTab()],
  printers: ["nav_printers", "printer", () => printersTab()],
  recent: ["nav_recently_added", "recent", () => intakeTab()],
  devices: ["nav_devices", "devices", () => [pairCard(), stationAsksCard(), webAppCard(), readersCard(), trustCard()]],
  presets: ["nav_slicer_presets", "presets", () => presetsTab()],
  features: ["nav_features", "features", () => [modesCard(), modulesCard(), applyCard()]],
  settings: ["nav_settings", "settings", () => [generalCard(), readerCard(), backupCard(), keyCard(), passphraseCard(), tokenCard(), libraryCard(), addressCard(), remoteCard()]],
  flash: ["nav_flash_device", "flash", () => flashTab()],
  updates: ["nav_updates", "updates", () => updatesTab()],
  logs: ["nav_logs", "logs", () => logsTab()],
};
const GROUPS = [["everyday", "nav_everyday", 0, 5], ["system", "nav_system", 5, 10]];
const BAR = new Set(["overview", "printers", "recent", "settings"]);   // the phone bottom bar (02 2.4); the rest are in More
const MOVED = { modules: "features", intake: "recent" };              // the tabs' old addresses
const tabNow = () => { const t = location.hash.slice(1).split(/[/?]/)[0]; return Object.hasOwn(TABS, t) ? t : "overview"; };

function render() {
  const now = tabNow();
  page.dataset.section = now;
  pageTitle.textContent = SW.t(TABS[now][0]);
  sections.replaceChildren(...TABS[now][2]().filter(Boolean));
  summaries();
}

async function refresh() {
  try { S = await api("state"); } catch (e) {
    if (!S) { hubName.parentElement.dataset.state = "error"; hubName.replaceChildren(SW.shape("s-octagon"), SW.t("topbar_hub_unreachable")); }
    sections.replaceChildren(h("p", { class: "err", textContent: e.message }));
    return;
  }
  hubName.replaceChildren(S.server_name);
  hubVersion.replaceChildren(SW.h("span", { class: "sr", text: SW.t("topbar_version_prefix") }), S.version);
  SW.configure({ hub: S.server_name, noCode: !S.code_set });
  render();
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
    h("div", { class: "topbar__tools" }, SW_LOCK.lockChip({ loading: true }), appearanceControl(), appearanceButton()));
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

// ----- Anthropic key -----
function keyCard() {
  const a = S.anthropic, box = boxFor("key"), inp = secret("sk-ant-…");
  return card(["Anthropic API key ", pill(a.set, "set", "not set")],
    h("p", { class: "muted", textContent: a.ai_intake ? "Used for AI label reading (ai_intake)." : "Only for AI label reading: the ai_intake module is off (see Modules)." }),
    h("div", { class: "row" }, inp,
      h("button", { textContent: a.set ? "Replace" : "Set", on: { click: () => change(box, "key", { key: inp.value }, null, [inp]) } }),
      a.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => { if (window.confirm("Remove the Anthropic key?")) change(box, "key/remove", {}); } } }) : null,
      h("button", { class: "secondary", textContent: "Check", on: { click: async () => {
        box.replaceChildren(h("p", { class: "muted", textContent: "Checking…" }));
        try { const r = await api("key/check", {}); say(box, r.text, r.ok); } catch (e) { say(box, e.message, false); }
      } } })),
    box);
}

// ----- web passphrase, library token -----
function passphraseCard() {
  const box = boxFor("passphrase"), one = secret("new passphrase, at least 12 characters"), two = secret("again");
  return card(["Web passphrase ", pill(S.passphrase.set, "set", "not set")],
    h("p", { class: "muted", textContent: "Approves Claude's connector on the web unit's sign-in page." + (S.passphrase.web ? "" : " The web module is off.") }),
    h("div", { class: "row" }, one, two, h("button", { textContent: S.passphrase.set ? "Replace" : "Set", on: { click: () => {
      if (one.value !== two.value) { say(box, "The two passphrases do not match.", false); return; }
      change(box, "passphrase", { passphrase: one.value }, null, [one, two]);
    } } })), box);
}

function tokenCard() {
  const box = boxFor("token"), inp = secret("GitHub token");
  return card(["Library token ", pill(S.library_token.set, "set", "not set")],
    h("p", { class: "muted", textContent: "Optional: lets the filament library download from a private repository." }),
    h("div", { class: "row" }, inp,
      h("button", { textContent: S.library_token.set ? "Replace" : "Set", on: { click: () => change(box, "library_token", { token: inp.value }, null, [inp]) } }),
      S.library_token.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => change(box, "library_token/remove", {}) } }) : null),
    box);
}

// ----- readers -----
function readersCard() {
  const R = S.readers, box = boxFor("readers"), name = h("input", { placeholder: "reader name, e.g. printer-station" });
  return card("NFC readers",
    R.error ? h("p", { class: "err", textContent: R.error }) : null,
    ...R.list.map((t) => h("div", { class: "row item" }, h("span", { textContent: `${t.id} · ${t.name} · made ${t.created}` }),
      h("button", { class: "secondary", textContent: "Revoke", on: { click: () => { if (window.confirm(`Revoke ${t.id}? A reader using it is refused from now on.`)) change(box, `readers/${encodeURIComponent(t.id)}/revoke`, {}); } } }))),
    R.list.length ? null : h("p", { class: "muted", textContent: "No reader tokens." }),
    h("div", { class: "row" }, name, h("button", { textContent: "Make a token", on: { click: () => change(box, "readers", { name: name.value },
      (r) => box.replaceChildren(h("p", { textContent: `New reader token ${r.id} (${r.name}):` }), h("pre", { class: "ok", textContent: r.token }), h("p", { class: "muted", textContent: r.note }))) } })),
    box);
}

// ----- pairing -----
let qrUrl = null;
let pairWatch = 0;      // the newest pairing shown; an older watch stops
// Says when a pairing shown in `box` is claimed: a device that `known` does not hold has appeared. Stops at `seconds`.
function watchPaired(box, known, seconds) {
  const me = ++pairWatch;
  const until = Date.now() + seconds * 1000;
  const tick = async () => {
    if (me !== pairWatch || Date.now() > until) return;
    let s = null;
    try { s = await api("state"); } catch { /* the server may be restarting: the next try tells */ }
    if (me !== pairWatch) return;
    const fresh = s && s.devices.find((d) => !known.has(d.id));
    if (fresh) { say(box, `Paired: ${fresh.name}.`, true); refresh(); return; }
    setTimeout(tick, 3000);
  };
  setTimeout(tick, 3000);
}
function pairCard() {
  const box = boxFor("pair");
  async function start(kind) {
    const known = new Set(S.devices.map((d) => d.id));
    const r = await change(box, "pair", { kind }, () => {});
    if (!r) return;
    watchPaired(box, known, r.expires_in);
    if (qrUrl) URL.revokeObjectURL(qrUrl);
    qrUrl = r.qr_svg ? URL.createObjectURL(new Blob([r.qr_svg], { type: "image/svg+xml" })) : null;
    fill(box,
      kind === "phone" ? h("p", { textContent: "Open the filament-kit app and scan this code, or type the pairing code." }) :
        h("p", { textContent: kind === "pc" ? "Paste this link into filament-kit-sync when it asks:" : "On the station PC run: sudo filament-kit station pair, then paste this link:" }),
      qrUrl ? h("img", { class: "qr", alt: "Pairing QR code", src: qrUrl }) : null,
      kind === "phone" ? null : h("pre", { class: "ok", textContent: r.link }),
      h("p", {}, "Pairing code: ", h("b", { textContent: r.code })),
      h("p", { class: "muted", textContent: `Certificate fingerprint (${kind === "phone" ? "the phone asks for two groups of it" : "check it matches"}): ${r.fingerprint}` }),
      h("p", { class: "muted", textContent: `Expires in ${Math.round(r.expires_in / 60)} min.` }));
  }
  return card("Phones, PC and station",
    ...S.devices.map((d) => h("div", { class: "row item" }, h("span", { textContent: `${d.name} · paired ${d.paired || "?"} · last seen ${d.last_seen || "never"}` }),
      d.built_in ? h("span", { class: "muted", textContent: "built in: this server's own pairing" })
        : h("button", { class: "secondary", textContent: "Revoke", on: { click: () => { if (window.confirm(`Unpair ${d.name}?`)) change(box, `devices/${encodeURIComponent(d.id)}/revoke`, {}); } } }))),
    S.devices.length ? null : h("p", { class: "muted", textContent: "Nothing paired yet." }),
    h("div", { class: "row" },
      h("button", { textContent: "Pair a phone", on: { click: () => start("phone") } }),
      h("button", { class: "secondary", textContent: "Link for the PC sync", on: { click: () => start("pc") } }),
      h("button", { class: "secondary", textContent: "Link for the station", on: { click: () => start("station") } }),
      S.modules.some((m) => m.name === "station" && m.on) ? h("button", { class: "secondary", textContent: "Pair the station on this machine", on: { click: () => startJob(box, "station_pair") } }) : null),
    box);
}

// Stations on other computers that ask to pair: Pair only when the station's screen shows the same six digits.
function stationAsksCard() {
  const body = h("div"), box = boxFor("stationAsks");
  const show = async () => {
    try {
      const r = await api("stations/requests", { code: theCode() });
      fill(body,
        r.requests.length ? null : h("p", { class: "muted", textContent: "No station is asking to pair." }),
        ...r.requests.map((q) => h("div", { class: "item" },
          h("p", {}, `${q.name} at ${q.address} asks to pair. Its screen shows `, h("b", { textContent: `${q.code.slice(0, 3)} ${q.code.slice(3)}` }), "."),
          h("p", { class: "muted", textContent: "Pair only if the station shows the same six digits. If not, refuse: someone else asked." }),
          h("div", { class: "row" },
            h("button", { textContent: "Pair", on: { click: () => change(box, `stations/requests/${q.id}/pair`, {}, () => { say(box, `Paired ${q.name}. It picks up its pairing within a few seconds.`, true); show(); }) } }),
            h("button", { class: "secondary", textContent: "Refuse", on: { click: () => change(box, `stations/requests/${q.id}/refuse`, {}, () => { box.replaceChildren(); show(); }) } })))));
    } catch (e) { if (e.locked) throw e; say(body, e.message, false); }
  };
  return card("Stations asking to pair", h("p", { class: "muted", textContent: "An intake station on another computer asks from its own screen." }),
    codeRead("devices_requests_locked", body, show), box);
}

let webQrUrls = [];
// The iPhone is not paired: it opens the phone web app in Safari, served by this server at home (and by the web
// module at its public address, when that is on).
function webAppCard() {
  const body = h("div");
  const note = h("div", { role: "status" });     // the hidden-values note; the card (home address, QR) stays
  const el = card("iPhone: the web app", body, note);
  const load = (whole) => (whole ? api("webapp", { code: theCode() }) : api("webapp")).then((r) => {
    note.replaceChildren(...(r.public_hidden ? [lockNote("lock_hidden_note")] : []));
    webQrUrls.forEach((u) => URL.revokeObjectURL(u));
    webQrUrls = [];
    const qr = (svg, alt) => {
      if (!svg) return null;
      const u = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
      webQrUrls.push(u);
      return h("img", { class: "qr", alt, src: u });
    };
    fill(body,
      h("p", {}, "At home, open this address in Safari: ", h("b", { textContent: r.url })),
      qr(r.qr_svg, "QR code of the web app's home address"),
      h("p", { class: "muted", textContent: "Safari warns once about the server's own certificate: accept it to go on. It works on the home network only." }),
      r.public_url ? h("p", {}, "Away from home too (the web module): ", h("b", { textContent: r.public_url })) : null,
      r.public_url ? qr(r.public_qr_svg, "QR code of the web app's public address") : null,
      h("p", { textContent: "To keep it on the iPhone: tap Share, then Add to Home Screen." }));
  });
  whenOpen(body, load);
  return el;
}

// ----- modules -----
function modulesCard() {
  const box = boxFor("modules");
  async function ask(m) {
    box.replaceChildren(h("p", { class: "muted", textContent: "…" }));
    let p;
    try { p = await api(`modules/preview?name=${encodeURIComponent(m.name)}`); } catch (e) { say(box, e.message, false); return; }
    if (p.refused) { say(box, p.refused, false); return; }
    const inputs = p.needs.map((n) => ({ key: n.key, el: h("input", { placeholder: n.prompt }) }));
    box.replaceChildren(
      h("p", { textContent: `${p.on ? "Turn on" : "Turn off"} ${m.name}.` }),
      ...p.notes.map((n) => h("p", { class: "muted", textContent: n })),
      h("p", { class: "muted", textContent: "On afterwards: " + (p.after.join(", ") || "nothing") }),
      ...inputs.map((i) => h("label", {}, i.el)),
      h("div", { class: "row" },
        h("button", { textContent: "Apply", on: { click: async () => {
          const settings = Object.fromEntries(inputs.map((i) => [i.key, i.el.value]));
          const r = await change(box, "modules", { name: m.name, on: p.on, settings }, (x) => say(box, x.changed ? "Saved; applying…" : "Unchanged.", true));
          if (r && r.changed) followApply();
        } } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => box.replaceChildren() } })));
  }
  return card(`Modules (mode: ${S.mode})`,
    ...S.modules.map((m) => h("div", { class: "row item" },
      h("span", {}, pill(m.on, "on", "off"), ` ${m.name}: ${m.description}`, m.needs.length ? h("span", { class: "muted", textContent: ` · needs: ${m.needs.join(", ")}` }) : null,
        m.optional_ai ? h("span", { class: "muted", textContent: " · OPTIONAL AI" }) : null),
      h("button", { class: "secondary", textContent: m.on ? "Turn off" : "Turn on", on: { click: () => ask(m) } }))),
    box);
}

// ----- addresses -----
function addressCard() {
  const box = boxFor("address");
  // the state leaves the address out (owner data): a set one shows as a blank box that a blank Save does not clear
  const web = h("input", { placeholder: S.web.public_set ? "set (hidden); type a new address to replace it" : "https://mcp.example.com/filament" });
  const st = h("input", { value: S.station.url || "", placeholder: "http://station.local:5003 (blank: none)" });
  const save = (key, inp) => key === "web.public_url" && S.web.public_set && !inp.value.trim()
    ? say(box, "The address is hidden here: type the new one to replace it.", false)
    : change(box, "settings", { key, value: inp.value.trim() }, () => { say(box, "Saved; applying…", true); followApply(); });
  return card("Addresses",
    h("p", { class: "muted", textContent: "Web public address: the https address of the web app and Claude's connector." }),
    h("div", { class: "row" }, web, h("button", { textContent: "Save", on: { click: () => save("web.public_url", web) } })),
    h("p", { class: "muted", textContent: "Station address: where this server reads the intake station." }),
    h("div", { class: "row" }, st, h("button", { textContent: "Save", on: { click: () => save("station.url", st) } })),
    box);
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

// ----- applying again (the job's own panel is in setup_tabs.js) -----
function applyCard() {
  const box = boxFor("apply");
  return card("Apply", h("p", { class: "muted", textContent: "Module and address changes are applied in the background (sudo filament-kit modules apply)." }),
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Apply again", on: { click: async () => {
      const r = await change(box, "apply", {}, () => say(box, "Applying…", true));
      if (r) followApply(true);
    } } })), box);
}

document.addEventListener("DOMContentLoaded", () => {
  SW.configure({ base: "/setup/api/", checkPath: "code/check" });
  settleAddress();
  const skip = h("a", { class: "skip", href: "#main" }, SW.t("common_skip_to_content"));
  const main = h("main", { class: "shell__main", id: "main", tabindex: "-1" }, page);
  skip.addEventListener("click", (e) => { e.preventDefault(); main.focus(); });   // the address keeps the section
  page.append(jobPanel, sections);
  app.replaceWith(skip, h("div", { class: "shell" }, topBar(), navigation(), main),
    h("div", { class: "toasts", "aria-live": "polite" }), h("div", { class: "sr", id: "announcer", "aria-live": "polite" }));
  pageTitle.textContent = SW.t(TABS[tabNow()][0]);
  shellView = SW.shell({ hub: document.title, home: "overview", titleOf: () => SW.t(TABS[tabNow()][0]), onSection: () => {
    settleAddress();
    window.scrollTo(0, 0);
    if (S) render(); else pageTitle.textContent = SW.t(TABS[tabNow()][0]);
  } });
  loadTrust().then(refresh);
});
