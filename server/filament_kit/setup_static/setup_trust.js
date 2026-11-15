// Trusted computers: a browser that needs no setup code. Loaded after setup.js; everything from the server goes in through
// textContent, as there. The token is in an HttpOnly cookie: this script never sees it.
"use strict";

let T = { enabled: false, trusted: false, id: null, name: null, expires: null };
const day = (t) => { const d = new Date(t * 1000), p = (n) => String(n).padStart(2, "0"); return t ? `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` : ""; };

// The lock chip follows `GET trust` (02 3.1): Trusted computer while the cookie holds; otherwise Locked, or Unlocked while
// this tab holds the code. "Trust this computer" is offered in the unlock dialog only while the feature is on. Until the
// first answer the chip shows Locked with a loading hint; if the Hub does not answer, it stays Locked and works.
let trustKnown = false;
async function loadTrust() {
  try { T = await api("trust"); } catch {
    // as it is now: nothing changes on a failed read
    T = { ...T, trusted: SW.lock.state === "trusted" };
    SW.setLock(SW.lock.state, { quiet: true });
    return;
  }
  // the state is read after the answer: an unlock made while the read was out stays unlocked
  const now = SW.lock.state;
  SW.lock.trustOffered = !!T.enabled;
  SW.setLock(T.trusted ? "trusted" : now === "trusted" ? "locked" : now, { trustId: T.id, until: day(T.expires), quiet: !trustKnown });
  trustKnown = true;
}
// trusted or no longer trusted from the unlock dialog or the chip: the Devices card and the expiry follow
document.addEventListener("sw:lock", (e) => { if (trustKnown && (e.detail === "trusted") !== !!T.trusted) loadTrust().then(() => { if (S) render(); }); });

// the server refused the cookie (revoked, run out, or the feature turned off): Locked, and the change that was refused
// asks for the code (SW.guard)
function trustGone() {
  T = { ...T, trusted: false, id: null, name: null };
  if (SW.lock.state !== "trusted") return;
  SW.setLock("locked");
  SW.toast(SW.t("lock_trust_gone"), "warn");
}

// each listed computer, Revoke all and the switches row say their result under their own row
function trustCard() {
  const box = boxFor("trust"), list = boxFor("trust-list"), all = boxFor("trust:all");
  async function show() {
    working(list, SW.t("common_reading"));
    let r;
    try { r = await api("trust/list", { code: theCode() }); } catch (e) { if (e.locked) throw e; say(list, e.message, false); return; }
    fill(list,
      ...r.devices.map((d) => { const at = boxFor("trust:" + d.id); return h("div", { class: "row item", "data-key": d.id },
        h("span", { textContent: `${d.name}${d.id === r.this ? " (this computer)" : ""} · made ${fmtDate(d.created)} · last seen ${fmtDate(d.last_seen)} at ${d.last_address === "loopback" ? "the server itself" : d.last_address} · runs out ${fmtDate(d.expires)}` }),
        h("button", { class: "secondary", textContent: "Rename", on: { click: async () => {
          await asking(at, `trust/${d.id}/rename`, { kind: "entry", title: SW.t("devices_rename_title", { name: d.name }), confirm: SW.t("common_rename"),
            fields: [entryField({ label: SW.t("common_field_name"), name: "name", value: d.name }, "common_error_name")] }, ([name]) => ({ name: name.trim() }));
        } } }),
        h("button", { class: "secondary", textContent: "Revoke", on: { click: async () => {
          if (await asking(at, `trust/${d.id}/revoke`, destroy("devices_revoke_one_title", "devices_revoke_one_body", "devices_revoke_one_confirm", { name: d.name }))) loadTrust();
        } } }), at); }),
      r.devices.length ? h("div", { class: "row" }, h("button", { class: "danger", textContent: "Revoke all", on: { click: async () => {
        if (await asking(all, "trust/revoke_all", destroy("devices_revoke_all_title", "devices_revoke_all_body", "devices_trusted_revoke_all"))) loadTrust();
      } } }), all) : h("p", { class: "muted", textContent: "No computer is trusted." }));
  }
  const pills = pill(T.enabled, "on", "off");
  return card(["Trusted computers ", pills],
    h("p", { class: "muted", textContent: "After the setup code works, a browser can be trusted so it isn't asked again; it can be revoked here at any time, and it never skips a question like \"Roll back?\". A new setup code (sudo filament-kit setup-code --new) keeps trusted computers trusted; revoke them here, or add --revoke-trusted." }),
    T.trusted ? h("p", {}, `This computer is trusted (${T.name}).`) : null,
    h("div", { class: "row" },
      T.trusted ? h("button", { class: "secondary", textContent: "Stop trusting this computer", on: { click: async () => {
        if (await asking(box, `trust/${T.id}/revoke`, destroy("devices_stop_trusting_title", "devices_stop_trusting_body", "devices_stop_trusting_confirm"))) {
          T = { ...T, trusted: false, id: null, name: null };
          SW.setLock("locked");
          SW.toast(SW.t("lock_toast_untrusted"));
        }
      } } }) : null,
      h("button", { class: "secondary", textContent: T.enabled ? "Turn trusted computers off" : "Turn trusted computers on", on: { click: async () => {
        const r = await (T.enabled ? asking(box, "trust/enabled", destroy("devices_off_title", "devices_off_body", "common_turn_off"), () => ({ enabled: false }))
          : change(box, "trust/enabled", { enabled: true }));
        if (r) { await loadTrust(); render(); }
      } } }), box),
    T.enabled ? codeRead("common_list_locked", list, show) : null);
}
