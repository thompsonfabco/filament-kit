// Trusted computers: a browser that needs no setup code. Loaded after setup.js; everything from the server goes in through
// textContent, as there. The token is in an HttpOnly cookie: this script never sees it.
"use strict";

let T = { enabled: false, trusted: false, id: null, name: null };
let offered = false;              // the offer comes once per visit, after the code worked: it doesn't nag

function codeArea() {
  if (!T.trusted) {
    fill(codeCard, h("label", {}, "Setup code", codeIn), offerBox);
    return;
  }
  fill(codeCard, h("p", {}, `This computer is trusted (${T.name}): no setup code needed here. `, link("devices", "Trusted computers")));
}

async function loadTrust() {
  try { T = await api("trust"); } catch { T = { enabled: false, trusted: false, id: null, name: null }; }
  codeArea();
}

// the server refused the cookie (revoked, run out, or the feature turned off): back to the code
function trustGone() {
  T = { ...T, trusted: false, id: null, name: null };
  codeArea();
}

const offerBox = h("div");
function offerTrust() {
  if (offered || !T.enabled || T.trusted || !codeIn.value) return;
  offered = true;
  const box = h("div");
  fill(offerBox, h("p", { class: "muted", textContent: "Trust this computer? This browser then needs no setup code for 90 days after its last use, so anyone using it can change the kit." }),
    h("div", { class: "row" },
      h("button", { textContent: "Trust this computer", on: { click: async () => {
        const r = await change(box, "trust", {}, () => {});
        if (!r) return;
        offerBox.replaceChildren();
        codeIn.value = "";
        loadTrust();
      } } }),
      h("button", { class: "secondary", textContent: "Not now", on: { click: () => offerBox.replaceChildren() } })),
    box);
}

function trustCard() {
  const box = boxFor("trust"), list = boxFor("trust-list");
  async function show() {
    list.replaceChildren(h("p", { class: "muted", textContent: "Reading…" }));
    let r;
    try { r = await api("trust/list", { code: codeIn.value }); } catch (e) { say(list, e.message, false); return; }
    fill(list,
      ...r.devices.map((d) => h("div", { class: "row item" },
        h("span", { textContent: `${d.name}${d.id === r.this ? " (this computer)" : ""} · made ${fmtDate(d.created)} · last seen ${fmtDate(d.last_seen)} at ${d.last_address === "loopback" ? "the server itself" : d.last_address} · runs out ${fmtDate(d.expires)}` }),
        h("button", { class: "secondary", textContent: "Rename", on: { click: async () => {
          const name = window.prompt("A name for this computer:", d.name);
          if (name && name.trim() && await change(box, `trust/${d.id}/rename`, { name: name.trim() })) show();
        } } }),
        h("button", { class: "secondary", textContent: "Revoke", on: { click: async () => {
          if (await change(box, `trust/${d.id}/revoke`, {})) { loadTrust(); show(); }
        } } }))),
      r.devices.length ? h("div", { class: "row" }, h("button", { class: "danger", textContent: "Revoke all", on: { click: async () => {
        if (window.confirm("Revoke every trusted computer? Each then needs the setup code again.") && await change(box, "trust/revoke_all", {})) { loadTrust(); show(); }
      } } })) : h("p", { class: "muted", textContent: "No computer is trusted." }));
  }
  const pills = pill(T.enabled, "on", "off");
  return card(["Trusted computers ", pills],
    h("p", { class: "muted", textContent: "After the setup code works, a browser can be trusted so it isn't asked again; it can be revoked here at any time, and it never skips a question like \"Roll back?\"." }),
    T.trusted ? h("p", {}, `This computer is trusted (${T.name}).`) : null,
    h("div", { class: "row" },
      T.enabled ? h("button", { class: "secondary", textContent: "Show the list", on: { click: show } }) : null,
      T.trusted ? h("button", { class: "secondary", textContent: "Stop trusting this computer", on: { click: async () => {
        if (await change(box, `trust/${T.id}/revoke`, {})) { trustGone(); list.replaceChildren(); }
      } } }) : null,
      h("button", { class: "secondary", textContent: T.enabled ? "Turn trusted computers off" : "Turn trusted computers on", on: { click: async () => {
        if (T.enabled && !window.confirm("Turn trusted computers off? Every computer is forgotten, and each change needs the setup code.")) return;
        const r = await change(box, "trust/enabled", { enabled: !T.enabled });
        if (r) { await loadTrust(); render(); list.replaceChildren(); }
      } } })),
    list, box);
}
