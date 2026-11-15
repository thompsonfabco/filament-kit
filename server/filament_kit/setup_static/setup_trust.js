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

// ----- Trusted computers (03 7.6): a card that follows the trust state in place (a switch pressed here does not redraw it, so its
// result stays), a list read once the page is open, and each row and Revoke all say their result under their own control -----
function trustCard() {
  const box = boxFor("trust"), all = boxFor("trust:all");
  const badge = h("span", { class: "devices__badge" }), off = h("p", { class: "muted" }), mine = h("div"), note = h("div", { role: "status" });
  const list = h("div"), foot = h("div", { class: "row" });
  let me = 0, loaded = false, L = null;
  const paintTop = () => {
    badge.replaceChildren(SW.status(T.enabled ? "on" : "off"));
    off.hidden = T.enabled;
    off.textContent = T.enabled ? "" : SW.t("devices_trusted_off");
    mine.replaceChildren(...(T.trusted ? [h("p", { textContent: SW.t("devices_trusted_this", { name: T.name }) }),
      h("div", { class: "row" }, SW.btn(SW.t("devices_trusted_stop"), { action: "stop-trusting", run: async () => {
        if (await asking(box, `trust/${T.id}/revoke`, destroy("devices_stop_trusting_title", "devices_stop_trusting_body", "devices_stop_trusting_confirm"))) {
          T = { ...T, trusted: false, id: null, name: null };
          SW.setLock("locked");
          SW.toast(SW.t("lock_toast_untrusted"));
        }
      } }))] : []));
  };
  const rows = (r) => r.devices.map((d) => {
    const at = boxFor("trust:" + d.id);
    return devRow(d.id, at, 5,
      devCell("title", 1, null, h("span", { class: "devices__name", textContent: d.name }), d.id === r.this ? [" ", h("span", { class: "muted", textContent: SW.t("devices_trusted_this_tag") })] : null),
      devCell("made", 3, SW.t("devices_trusted_col_made"), devStamp(d.created) || SW.t("common_unknown")),
      devCell("seen", 2, SW.t("devices_col_last_seen"), d.last_seen ? SW.t("devices_trusted_seen", { time: devStamp(d.last_seen),
        address: d.last_address === "loopback" ? SW.t("devices_trusted_hub_itself") : d.last_address }) : SW.t("common_never")),
      devCell("expires", 2, SW.t("devices_trusted_col_expires"), devStamp(d.expires) || SW.t("common_unknown")),
      devCell("actions", 1, null, h("div", { class: "actions" },
        SW.btn(SW.t("common_rename"), { cls: "btn--ghost", name: SW.t("devices_rename_title", { name: d.name }), action: "rename", run: async () => {
          const ok = await asking(at, `trust/${d.id}/rename`, { kind: "entry", title: SW.t("devices_rename_title", { name: d.name }), confirm: SW.t("common_rename"),
            fields: [entryField({ label: SW.t("common_field_name"), name: "name", value: d.name }, "common_error_name")] }, ([name]) => ({ name: name.trim() }));
          if (ok && d.id === T.id) { await loadTrust(); await refresh(at); }       // this computer's own name is in the line above
        } }),
        SW.btn(SW.t("devices_trusted_revoke"), { cls: "btn--ghost", name: SW.t("devices_trusted_revoke_named", { name: d.name }), action: "revoke", run: async () => {
          if (await asking(at, `trust/${d.id}/revoke`, destroy("devices_revoke_one_title", "devices_revoke_one_body", "devices_revoke_one_confirm", { name: d.name }),
            undefined, () => say(at, SW.t("devices_trusted_revoked", { name: d.name }), true))) loadTrust();
        } }))));
  });
  const failed = (e) => SW.errorState({ title: SW.t("devices_trusted_error", { reason: "" }).trim(), text: hubText(e.message), level: 3, onTry: devRetry(() => paintList(true)) });
  // a read that is not the newest is dropped, and so is one that comes after the page locked or the switch was turned off
  async function show() {
    const n = me;
    if (!loaded && !L) L = SW.loading(list, { thing: SW.t("devices_trusted_title"), items: 2, onTry: devRetry(() => paintList(true)), title: SW.t("devices_trusted_error", { reason: "" }).trim() });
    let r;
    try { r = await api("trust/list", { code: theCode() }); } catch (e) {
      if (e.locked) throw e;
      if (n !== me) return;
      if (L) { L.done(); L = null; }
      fill(list, failed(e));
      return;
    }
    if (n !== me) return;
    if (L) { L.done(); L = null; }
    loaded = true;
    devTrusted = r.devices.length;
    devMeta();
    fill(list, r.devices.length ? devTable("coll--trusted", SW.t("devices_trusted_title"), [devHead("title", SW.t("common_field_name")), devHead("made", SW.t("devices_trusted_col_made"), 3),
      devHead("seen", SW.t("devices_col_last_seen"), 2), devHead("expires", SW.t("devices_trusted_col_expires"), 2), devActionsHead()], rows(r))
      : h("p", { class: "muted", textContent: SW.t("devices_trusted_empty") }));
    foot.replaceChildren(...(r.devices.length ? [h("div", {}, SW.btn(SW.t("devices_trusted_revoke_all"), { cls: "btn--danger", action: "revoke-all", run: async () => {
      if (await asking(all, "trust/revoke_all", destroy("devices_revoke_all_title", "devices_revoke_all_body", "devices_trusted_revoke_all"),
        undefined, () => say(all, SW.t("devices_trusted_all_revoked"), true))) loadTrust();
    } }), all)] : []));
  }
  // the list follows the switch and the lock: read when on and open, the locked line when on and Locked, nothing when off
  function paintList(open) {
    me++;
    L = null;
    loaded = false;
    list.removeAttribute("aria-busy");
    foot.replaceChildren();
    devTrusted = null;
    devMeta();
    if (!T.enabled) { list.replaceChildren(); note.replaceChildren(); return; }
    if (!open) { list.replaceChildren(); note.replaceChildren(lockNote("common_list_locked")); return; }
    note.replaceChildren();
    return show();
  }
  const toggle = SW.toggle({ label: SW.t("devices_trusted_title"), checked: T.enabled,
    confirm: (on) => (on ? null : { ...destroy("devices_off_title", "devices_off_body", "common_turn_off") }),
    apply: async (on) => {
      try { await api("trust/enabled", { enabled: on, code: theCode() }); } catch (e) { throw new SW.HubError({ message: e.message, locked: e.locked }); }
      await loadTrust();
      paintTop();
      paintList(SW.lock.state !== "locked");
      return SW.t(on ? "devices_trusted_on_done" : "devices_trusted_off_done");
    } });
  paintTop();
  devWhenOpen(list, paintList);
  return card([SW.t("devices_trusted_title"), " ", badge],
    h("p", { class: "muted", textContent: SW.t("devices_trusted_explain") }), off, mine, box, note, list, foot, toggle);
}
