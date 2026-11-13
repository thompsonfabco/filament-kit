// The Updates section.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

function updatesTab() {
  const out = h("div");
  const box = boxFor("updates"), back = boxFor("updates:rollback");
  later(readRegion(out, "updates", () => api("updates"), (u) => {
    fill(out,
      card("Version",
        h("p", {}, `Installed: ${u.installed_text || u.installed}`),
        h("p", {}, u.latest ? `Latest release: ${u.latest}${u.newer ? "" : " (up to date)"}` : "Latest release: not checked yet"),
        u.checked_at ? h("p", { class: "muted", textContent: `Last checked ${fmtDate(u.checked_at)}.` }) : null,
        u.held && u.held === u.latest ? h("p", { class: "muted", textContent: `${u.held} was rolled back: the timer skips it, Update here installs it.` }) : null,
        u.failed && u.failed === u.latest ? h("p", { class: "muted", textContent: `Installing ${u.failed} failed before: the timer waits for a newer release, Update here tries it again.` }) : null,
        h("p", { class: "muted" }, u.module_on ? `Checked by itself ${u.schedule || ""} (the updates module).` : "Not checked by itself: the updates module is off. ", u.module_on ? null : link("features", "Modules")),
        h("div", { class: "row" },
          h("button", { class: "secondary", textContent: "Check now", on: { click: () => startJob(box, "check") } }),
          u.newer ? h("button", { textContent: `Update to ${u.latest}`, disabled: !!u.update_refused, on: { click: () => startJob(box, "update", { title: SW.t("updates_dialog_update_title", { version: u.latest }),
            text: SW.t("updates_dialog_update_body"), confirm: SW.t("updates_update", { version: u.latest }) }) } }) : null),
        u.newer && u.update_refused ? h("p", { class: "err", textContent: u.update_refused }) : null,
        box),
      u.notes ? card(u.newer ? `What ${u.latest} brings` : `Release notes of ${u.latest}`, h("pre", { textContent: u.notes })) : null,
      card("Roll back",
        u.previous ? h("p", {}, `Goes back to ${u.previous}, the version this one replaced. Settings and data stay.`) : h("p", { class: "muted", textContent: "No earlier version is kept, so there is nothing to roll back to." }),
        u.previous && u.going_back ? h("pre", { textContent: u.going_back }) : null,
        u.previous ? h("div", { class: "row" }, h("button", { class: "danger", textContent: `Roll back to ${u.previous}`, disabled: !!u.rollback_refused, on: { click: () => startJob(back, "rollback",
          destroy("updates_dialog_rollback_title", "updates_dialog_rollback_body", "updates_roll_back", { version: u.previous })) } }), back) : null,
        u.previous && u.rollback_refused ? h("p", { class: "err", textContent: u.rollback_refused }) : null),
      h("p", { class: "muted", textContent: "To remove the kit: at the server, sudo filament-kit uninstall." }));
  }));
  return [out];
}
