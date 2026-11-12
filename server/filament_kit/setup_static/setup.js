// The kit server's setup console: everything after the install, by tab, without the command line. This file is the
// shell and the tabs that were the setup page's; setup_tabs.js has the console's own.
// Talks only to /setup/api/* on the same origin. Every change sends the setup code typed at the top; secret fields
// are write-only (the server says "set" / "not set", never a value) and are cleared once sent.
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
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

async function api(path, body) {
  const init = { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: {} };
  if (body !== undefined) { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch("/setup/api/" + path, init);
  let data;
  try { data = await r.json(); } catch { data = { error: `HTTP ${r.status}` }; }
  if (data.trust_gone) trustGone();
  if (!r.ok || data.error) { const e = new Error(data.error || `HTTP ${r.status}`); e.data = data; e.status = r.status; throw e; }
  return data;
}

// ----- the setup code (sent with every change) -----
const codeIn = h("input", { type: "password", inputMode: "numeric", autocomplete: "off", placeholder: "1234-5678",
                            ariaLabel: "Setup code" });
const codeCard = h("div", { class: "card code" });
const say = (box, text, ok) => box.replaceChildren(h("pre", { class: ok ? "ok" : "err", textContent: text }));
function secret(placeholder) {
  return h("input", { type: "password", autocomplete: "new-password", placeholder });
}
// A change: sends the code (and `body`), says the result in `box`, clears the secret inputs, reloads the page's state.
async function change(box, path, body, done, clear) {
  box.replaceChildren(h("p", { class: "muted", textContent: "Saving…" }));
  try {
    const r = await api(path, { ...body, code: codeIn.value });
    for (const inp of clear || []) inp.value = "";
    if (done) done(r); else say(box, "Saved.", true);
    offerTrust();
    refresh();
    return r;
  } catch (e) { say(box, e.message, false); return null; }
}
// replaceChildren would print a null as the word "null" (h() skips it, this one does not)
const fill = (el, ...kids) => el.replaceChildren(...kids.filter(Boolean));
const pill = (on, yes, no) => h("span", { class: "pill " + (on ? "ok" : "no"), textContent: on ? yes : no });
const card = (title, ...kids) => h("section", { class: "card" }, h("h2", {}, title), ...kids);

let S = null;
// result boxes outlive a re-render (every change reloads the state), so a token shown once or a QR code stays
const boxes = {};
const boxFor = (key) => boxes[key] || (boxes[key] = h("div"));
const sections = h("div");

// ----- the tabs: the page's own anchors (/setup#printers) -----
const TABS = {
  overview: ["Overview", () => overviewTab()],
  modules: ["Modules", () => [modesCard(), modulesCard(), applyCard()]],
  printers: ["Printers", () => printersTab()],
  devices: ["Devices", () => [pairCard(), stationAsksCard(), webAppCard(), readersCard(), trustCard()]],
  presets: ["Presets", () => presetsTab()],
  intake: ["Intake", () => intakeTab()],
  settings: ["Settings", () => [generalCard(), backupCard(), keyCard(), passphraseCard(), tokenCard(), libraryCard(), addressCard(), remoteCard()]],
  updates: ["Updates", () => updatesTab()],
  logs: ["Logs", () => logsTab()],
};
const tabNow = () => { const t = location.hash.slice(1); return t in TABS ? t : "overview"; };
const nav = h("nav", { class: "tabs", ariaLabel: "Console sections" });

function render() {
  const now = tabNow();
  nav.replaceChildren(...Object.entries(TABS).map(([k, [title]]) => h("a", { href: "#" + k, textContent: title, "aria-current": k === now ? "page" : undefined })));
  sections.replaceChildren(...TABS[now][1]().filter(Boolean));
}

async function refresh() {
  try { S = await api("state"); } catch (e) { sections.replaceChildren(h("p", { class: "err", textContent: e.message })); return; }
  render();
  if (S.apply.running) followApply();
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
  const R = S.readers, box = boxFor("readers"), name = h("input", { placeholder: "reader name, e.g. bench" });
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
      const r = await api("stations/requests", { code: codeIn.value });
      offerTrust();
      fill(body,
        r.requests.length ? null : h("p", { class: "muted", textContent: "No station is asking to pair." }),
        ...r.requests.map((q) => h("div", { class: "item" },
          h("p", {}, `${q.name} at ${q.address} asks to pair. Its screen shows `, h("b", { textContent: `${q.code.slice(0, 3)} ${q.code.slice(3)}` }), "."),
          h("p", { class: "muted", textContent: "Pair only if the station shows the same six digits. If not, refuse: someone else asked." }),
          h("div", { class: "row" },
            h("button", { textContent: "Pair", on: { click: () => change(box, `stations/requests/${q.id}/pair`, {}, () => { say(box, `Paired ${q.name}. It picks up its pairing within a few seconds.`, true); show(); }) } }),
            h("button", { class: "secondary", textContent: "Refuse", on: { click: () => change(box, `stations/requests/${q.id}/refuse`, {}, () => { box.replaceChildren(); show(); }) } })))));
    } catch (e) { say(body, e.message, false); }
  };
  return card("Stations asking to pair", h("p", { class: "muted", textContent: "An intake station on another computer asks from its own screen." }),
    h("button", { class: "secondary", textContent: "Show requests", on: { click: show } }), body, box);
}

let webQrUrls = [];
// The iPhone is not paired: it opens the phone web app in Safari, served by this server at home (and by the web
// module at its public address, when that is on).
function webAppCard() {
  const body = h("div");
  const el = card("iPhone: the web app", body);
  api("webapp").then((r) => {
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
  }).catch((e) => say(body, e.message, false));
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
  const web = h("input", { value: S.web.public_url || "", placeholder: "https://mcp.example.com/filament" });
  const st = h("input", { value: S.station.url || "", placeholder: "http://station.local:5003 (blank: none)" });
  const save = (key, inp) => change(box, "settings", { key, value: inp.value.trim() }, () => { say(box, "Saved; applying…", true); followApply(); });
  return card("Addresses",
    h("p", { class: "muted", textContent: "Web public address: the https address of the web app and Claude's connector." }),
    h("div", { class: "row" }, web, h("button", { textContent: "Save", on: { click: () => save("web.public_url", web) } })),
    h("p", { class: "muted", textContent: "Station address: where this server reads the intake station." }),
    h("div", { class: "row" }, st, h("button", { textContent: "Save", on: { click: () => save("station.url", st) } })),
    box);
}

// ----- applying again (the job's own panel is in setup_tabs.js) -----
function applyCard() {
  const box = boxFor("apply");
  return card("Apply", h("p", { class: "muted", textContent: "Module and address changes are applied in the background (sudo filament-kit modules apply)." }),
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Apply again", on: { click: async () => {
      const r = await change(box, "apply", {}, () => say(box, "Applying…", true));
      if (r) followApply(true);
    } } })), box);
}

window.addEventListener("hashchange", () => { if (S) render(); });
document.addEventListener("DOMContentLoaded", () => {
  app.append(
    h("h1", { textContent: "filament-kit" }),
    h("p", { class: "muted", textContent: "Everything after the install is here; the command line is the fallback. Viewing needs nothing; every change needs the setup code the installer showed (at the server: sudo filament-kit setup-code), unless this computer is trusted (Devices)." }),
    h("div", { class: "sticky" }, codeCard, nav),
    jobPanel, sections);
  codeArea();
  loadTrust().then(refresh);
});
