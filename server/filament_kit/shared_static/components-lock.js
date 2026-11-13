// Spoolwarden shared components, the lock addition (02-components.md 3.1, 3.2): loaded after components.js, only by the
// Hub page (the web app has no lock). It adds window.SW_LOCK: the lock chip and the unlock dialog; the lock's state,
// setLock() and guard() stay in components.js.
(() => {
"use strict";
const SW = window.SW, { t, h, lock } = SW;
const AH = { "aria-hidden": "true" };
const LOCK = {
  locked: ["lock", "lock_locked", "lock_hint_locked", "lock_name_locked"],
  unlocked: ["lock-open", "lock_unlocked", "lock_hint_unlocked", "lock_name_unlocked"],
  trusted: ["shield", "lock_trusted", "lock_hint_trusted", "lock_name_trusted"],
};
function paintLock(chip, loading) {
  const [ic, word, hint, name] = LOCK[lock.state];
  chip.dataset.state = lock.state;
  chip.setAttribute("aria-label", t(name));
  chip.replaceChildren(SW.icon(ic, "icon--s"), h("span", { class: "chip__word" }, t(word)), loading
    ? h("span", { class: "chip__hint skeleton__line", ...AH }) : h("span", { class: "chip__hint", ...AH, text: t(hint) }));
}
function lockChip(o = {}) {
  const chip = h("button", { class: "chip chip--lock", type: "button", "aria-haspopup": "dialog", on: { click: () => lockOptions(chip) } });
  chip._paint = () => paintLock(chip);   // setLock() repaints every chip
  paintLock(chip, o.loading);
  return chip;
}
async function lockOptions(chip) {
  if (lock.state === "locked") return unlock(null, null, null, chip);
  if (lock.state === "unlocked") {
    if (await SW.ask({ title: t("lock_unlocked"), text: t("lock_unlocked_body"), cancel: t("common_close"), confirm: t("lock_now"), opener: chip })) {
      SW.setLock("locked"); SW.toast(t("lock_toast_locked"));
    }
    return;
  }
  const ok = await SW.ask({ title: t("lock_trusted"), text: t("lock_trusted_body", { date: lock.until }), opener: chip,
    body: h("p", null, h("a", { href: "#devices/trusted", text: t("lock_trusted_link") })), cancel: t("common_close"),
    confirm: t("lock_trusted_stop"), style: "", run: () => SW.api(`${SW.setting("trustPath")}/${encodeURIComponent(lock.trustId)}/revoke`, { method: "POST" }).then(() => true) });
  if (ok) { SW.setLock("locked"); SW.toast(t("lock_toast_untrusted")); }
}
// unlock(change, run, onCancel): change names the pending change ("forget Workshop X1"), null from the chip
function unlock(change, run, onCancel, opener) {
  const code = SW.field({ type: "secret", name: "code", label: t("unlock_field_label"), hint: t("unlock_field_hint"),
    short: true, mono: true, attrs: { inputmode: "numeric" } });
  const trust = lock.trustOffered ? SW.check({ label: t("unlock_trust"), name: "trust" }) : null;
  return SW.ask({ kind: "entry", title: t("unlock_title"), opener, text: SW.setting("noCode") ? t("lock_no_code") : change ? t("unlock_text_change", { change }) : t("unlock_text_chip"),
    fields: [code], after: trust, confirm: t(run ? "unlock_continue" : "unlock_button"), busy: t("common_checking"),
    run: async () => {
      const digits = code._control.value.replace(/\D/g, "");
      const no = (text) => { SW.fieldError(code, text); code._control.focus(); return false; };
      if (!digits) return no(t("unlock_error_empty"));
      if (digits.length !== 8) return no(t("unlock_error_length", { count: digits.length }));
      try { await SW.api(SW.setting("checkPath"), { method: "POST", body: { code: digits }, code: false }); }
      catch (err) {
        // TIM-3: tries left after a wrong code, the time a lockout ends; else the Hub's own words
        const d = err.data || {}, at = d.retry_at && !d.tries_left ? d.retry_at.slice(11) : "";
        return no(err.unreachable ? t("unlock_error_unreachable") : at ? t("unlock_error_lockout", { time: at })
          : d.tries_left != null ? t("unlock_error_tries", { count: d.tries_left }) : err.status === 403 ? t("unlock_error_wrong") : err.text(t("unlock_error_wrong")));
      }
      SW.fieldError(code, null);
      if (trust && trust._control.checked) {
        const r = await SW.api(SW.setting("trustPath"), { method: "POST", body: { code: digits }, code: false });
        SW.setLock("trusted", { trustId: r.id, until: r.until || "" });
        SW.toast(t("unlock_toast_trusted"));
      } else { SW.setLock("unlocked", { code: digits }); SW.toast(t("unlock_toast_unlocked")); }
      return true;
    },
  }).then((ok) => (ok ? run && SW.guard(change, run, onCancel) : onCancel && onCancel()));
}

window.SW_LOCK = Object.freeze({ lockChip, unlock });
})();
