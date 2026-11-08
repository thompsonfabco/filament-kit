// The kit server's setup page: keys, codes, printers, pairings and modules without the command line.
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
  if (!r.ok || data.error) { const e = new Error(data.error || `HTTP ${r.status}`); e.data = data; throw e; }
  return data;
}

// ----- the setup code (sent with every change) -----
const codeIn = h("input", { type: "password", inputMode: "numeric", autocomplete: "off", placeholder: "1234-5678",
                            ariaLabel: "Setup code" });
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
    refresh();
    return r;
  } catch (e) { say(box, e.message, false); return null; }
}
const pill = (on, yes, no) => h("span", { class: "pill " + (on ? "ok" : "no"), textContent: on ? yes : no });
const card = (title, ...kids) => h("section", { class: "card" }, h("h2", {}, title), ...kids);

let S = null;
// result boxes outlive a re-render (every change reloads the state), so a token shown once or a QR code stays
const boxes = {};
const boxFor = (key) => boxes[key] || (boxes[key] = h("div"));
const sections = h("div");

async function refresh() {
  try { S = await api("state"); } catch (e) { sections.replaceChildren(h("p", { class: "err", textContent: e.message })); return; }
  sections.replaceChildren(keyCard(), printersCard(), passphraseCard(), tokenCard(), readersCard(), pairCard(),
    modulesCard(), addressCard(), applyCard());
  if (S.apply.running) followApply();
}

// ----- Anthropic key -----
function keyCard() {
  const a = S.anthropic, box = boxFor("key"), inp = secret("sk-ant-…");
  return card(["Anthropic API key ", pill(a.set, "set", "not set")],
    h("p", { class: "muted", textContent: a.ai_intake ? "Used for AI label reading (ai_intake)." : "Only for AI label reading: the ai_intake module is off (Modules below)." }),
    h("div", { class: "row" }, inp,
      h("button", { textContent: a.set ? "Replace" : "Set", on: { click: () => change(box, "key", { key: inp.value }, null, [inp]) } }),
      a.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => { if (window.confirm("Remove the Anthropic key?")) change(box, "key/remove", {}); } } }) : null,
      h("button", { class: "secondary", textContent: "Check", on: { click: async () => {
        box.replaceChildren(h("p", { class: "muted", textContent: "Checking…" }));
        try { const r = await api("key/check", {}); say(box, r.text, r.ok); } catch (e) { say(box, e.message, false); }
      } } })),
    box);
}

// ----- printers -----
function printersCard() {
  const P = S.printers;
  if (!P.on) return card("Printers", h("p", { class: "muted", textContent: "The printers module is off on this server (Modules below)." }));
  const rows = P.list.map((p) => {
    const box = boxFor("printer:" + p.serial), code = secret("new Access Code");
    return h("div", { class: "item" },
      h("p", {}, h("b", { textContent: p.name }), ` ${p.model || ""} · ${p.ip || "no IP yet"} · serial ${p.serial} `,
        pill(p.state === "connected", "connected", p.state.replace(/_/g, " "))),
      h("div", { class: "row" }, code,
        h("button", { textContent: p.configured ? "Replace code" : "Set code", on: { click: () => change(box, `printers/${encodeURIComponent(p.serial)}/code`, { access_code: code.value }, null, [code]) } }),
        h("button", { class: "secondary", textContent: "Test", on: { click: async () => {
          box.replaceChildren(h("p", { class: "muted", textContent: "Testing…" }));
          try { const r = await api(`printers/${encodeURIComponent(p.serial)}/test`, {}); say(box, `${r.text}\nconnection: ${r.state.replace(/_/g, " ")}`, r.reachable); } catch (e) { say(box, e.message, false); }
        } } }),
        h("button", { class: "secondary", textContent: "Forget", on: { click: () => { if (window.confirm(`Forget ${p.name}? Its Access Code is deleted.`)) change(box, `printers/${encodeURIComponent(p.serial)}/forget`, {}); } } })),
      box);
  });
  const ip = h("input", { placeholder: "IP address, e.g. 192.0.2.40", inputMode: "decimal" });
  const ac = secret("Access Code (printer: Settings > Network/LAN)");
  const name = h("input", { placeholder: "name (optional)" });
  const serial = h("input", { placeholder: "serial (optional: read from the printer)", autocapitalize: "characters" });
  const box = boxFor("printer-add");
  return card("Printers",
    ...(rows.length ? rows : [h("p", { class: "muted", textContent: "No printer yet. Printers on the network appear here once they announce themselves." })]),
    h("h2", { textContent: "Add a printer by IP" }),
    h("div", { class: "row" }, ip, ac), h("div", { class: "row" }, name, serial,
      h("button", { textContent: "Add", on: { click: () => change(box, "printers", { ip: ip.value, access_code: ac.value, name: name.value, serial: serial.value },
        (r) => say(box, `Added ${r.serial}.`, true), [ac]) } })),
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
function pairCard() {
  const box = boxFor("pair");
  async function start(kind) {
    const r = await change(box, "pair", { kind }, () => {});
    if (!r) return;
    if (qrUrl) URL.revokeObjectURL(qrUrl);
    qrUrl = r.qr_svg ? URL.createObjectURL(new Blob([r.qr_svg], { type: "image/svg+xml" })) : null;
    box.replaceChildren(
      kind === "phone" ? h("p", { textContent: "Open the filament-kit app and scan this code, or type the pairing code." }) :
        h("p", { textContent: kind === "pc" ? "Paste this link into filament-kit-sync when it asks:" : "On the station PC run: sudo filament-kit station pair, then paste this link:" }),
      qrUrl ? h("img", { class: "qr", alt: "Pairing QR code", src: qrUrl }) : null,
      kind === "phone" ? null : h("pre", { class: "ok", textContent: r.link }),
      h("p", {}, "Pairing code: ", h("b", { textContent: r.code })),
      h("p", { class: "muted", textContent: `Certificate fingerprint (check it matches): ${r.fingerprint}` }),
      h("p", { class: "muted", textContent: `Expires in ${Math.round(r.expires_in / 60)} min.` }));
  }
  return card("Phones, PC and station",
    ...S.devices.map((d) => h("div", { class: "row item" }, h("span", { textContent: `${d.name} · paired ${d.paired || "?"} · last seen ${d.last_seen || "never"}` }),
      h("button", { class: "secondary", textContent: "Revoke", on: { click: () => { if (window.confirm(`Unpair ${d.name}?`)) change(box, `devices/${encodeURIComponent(d.id)}/revoke`, {}); } } }))),
    S.devices.length ? null : h("p", { class: "muted", textContent: "Nothing paired yet." }),
    h("div", { class: "row" },
      h("button", { textContent: "Pair a phone", on: { click: () => start("phone") } }),
      h("button", { class: "secondary", textContent: "Link for the PC sync", on: { click: () => start("pc") } }),
      h("button", { class: "secondary", textContent: "Link for the station", on: { click: () => start("station") } })),
    box);
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

// ----- the background `modules apply` (polls its output; the server restarts during it, so errors are retried) -----
const applyOut = h("pre", { class: "hidden" });
const applyState = h("p", { class: "muted" });
let applyFrom = 0, applyTimer = null;
function applyCard() {
  const box = boxFor("apply");
  return card("Apply", h("p", { class: "muted", textContent: "Module and address changes are applied in the background (sudo filament-kit modules apply)." }),
    applyState, applyOut,
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Apply again", on: { click: async () => {
      const r = await change(box, "apply", {}, () => say(box, "Applying…", true));
      if (r) followApply(true);
    } } })), box);
}
function followApply(fresh) {
  if (fresh) applyFrom = 0;
  if (applyTimer) return;
  if (applyFrom === 0) applyOut.textContent = "";
  applyOut.classList.remove("hidden");
  const tick = async () => {
    applyTimer = null;
    let r;
    try { r = await api(`apply?from=${applyFrom}`); } catch { applyState.textContent = "Waiting for the server (it restarts during an apply)…"; applyTimer = setTimeout(tick, 2000); return; }
    if (r.next < applyFrom) { applyFrom = 0; applyOut.textContent = ""; }      // a new apply started over
    applyOut.textContent += r.text; applyFrom = r.next;
    applyOut.scrollTop = applyOut.scrollHeight;
    applyState.textContent = r.running ? "Applying…" : r.exit === 0 ? "Applied." : r.exit == null ? "" : `The apply failed (exit ${r.exit}): see the lines above.`;
    if (r.running || r.text) applyTimer = setTimeout(tick, 1000);
  };
  tick();
}

app.append(
  h("h1", { textContent: "filament-kit setup" }),
  h("p", { class: "muted", textContent: "Enter keys and codes here instead of on the command line. Viewing needs nothing; every change needs the setup code the installer showed (at the server: sudo filament-kit setup-code)." }),
  h("div", { class: "card code" }, h("label", {}, "Setup code", codeIn)),
  sections);
refresh();
