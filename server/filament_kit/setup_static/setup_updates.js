// The Updates section (03 12).
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

let updateCodes = 0;

// the Hub's job that is running now (state.apply), as its title: Update and Roll back wait for it (03 12.4)
const runningJob = () => {
  const a = S && S.apply;
  if (!a || !a.running) return null;
  const name = ["backup", "restore", "apply", "update", "rollback", "check", "library_update", "library_rollback", "remote_issue",
    "station_pair", "reader_setup"].includes(a.name) ? a.name : "other";
  return SW.t("job_title_" + name);
};

// a row of the Version list: the key, then the value (text, or nodes)
const versionRow = (key, ...value) => h("div", { class: "kv__row" }, h("dt", { class: "kv__key", textContent: SW.t(key) }), h("dd", { class: "kv__value" }, ...value));

// a command in a code block with Copy (02 7.7), `caption` says where to run it
function updatesCode(text, caption) {
  const id = "updates-code-" + ++updateCodes;
  return h("figure", { class: "code" },
    h("pre", { class: "code__text", tabindex: "0", "aria-labelledby": id + "-name" }, h("code", { textContent: text })),
    h("figcaption", { class: "code__bar" }, h("span", { class: "code__caption mono", id: id + "-name", textContent: caption }),
      h("span", { class: "result", role: "status" }), SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: "copy" })));
}

// Update and Roll back are refused by the Hub (`why`), or wait for the job that is running; the button stays in place, said and
// described, as a disabled button must be (02 4.1)
function held(button, why, line) {
  const job = runningJob();
  if (job) { SW.disable(button, SW.t("common_wait_for_job", { job_title: job })); return; }
  if (!why) return;
  button.setAttribute("aria-disabled", "true");
  if (line) button.setAttribute("aria-describedby", line.id);
  SW.tooltip(button, why);
}

function refusal(why) {
  if (!why) return null;
  const line = SW.banner({ kind: "bad", inline: true, text: why });
  line.id = SW.uid("updates-refused");
  return line;
}

function versionCard(u) {
  const latest = !u.latest ? SW.t("updates_not_checked") : u.newer ? SW.t("updates_latest_available", { latest: u.latest })
    : [h("span", { class: "mono", textContent: u.latest }), SW.status("ok")];
  return h("section", { class: "card" }, h("h2", {}, SW.t("updates_version_title")),
    u.half_install ? h("div", { class: "updates__half" },
      SW.banner({ kind: "warn", inline: true, title: SW.t("overview_half_title"), text: SW.t("overview_half_body") }),
      updatesCode(u.half_install, SW.t("updates_code_caption"))) : null,
    h("dl", { class: "kv" },
      versionRow("updates_installed", h("span", { class: "mono", textContent: u.installed_text || u.installed })),
      versionRow("updates_latest", ...[].concat(latest)),
      u.checked_at ? versionRow("updates_last_checked", fmtDate(u.checked_at)) : null,
      u.held && u.held === u.latest ? versionRow("updates_held_label", SW.t("updates_held", { version: u.held })) : null,
      u.failed && u.failed === u.latest ? versionRow("updates_failed_label", SW.t("updates_failed", { version: u.failed })) : null,
      versionRow("updates_schedule_label", ...(u.module_on ? [SW.t("updates_schedule", { schedule: u.schedule || "" })]
        : [SW.t("updates_schedule_off"), " ", h("a", { class: "btn btn--ghost", href: "#features", textContent: SW.t("nav_features") })]))));
}

function updatesTab() {
  const out = h("div");
  const box = boxFor("updates"), back = boxFor("updates:rollback");
  later(readRegion(out, "updates", () => api("updates"), (u) => {
    const replaced = (u.installed_text || u.installed) !== u.installed;      // a build from before the signed releases shows its own version text
    const check = SW.btn(SW.t("updates_check"), { run: () => startJob(box, "check") });
    const refused = refusal(u.newer ? u.update_refused : null);
    const update = u.newer ? SW.btn(SW.t("updates_update", { version: u.latest }), { cls: "btn--primary", run: () => startJob(box, "update", {
      title: SW.t("updates_dialog_update_title", { version: u.latest }),
      text: SW.t("updates_dialog_update_body") + (replaced ? " " + SW.t("updates_dialog_update_from_nightly", { latest: u.latest }) : ""),
      confirm: SW.t("updates_update", { version: u.latest }) }) }) : null;
    const rollRefused = refusal(u.previous ? u.rollback_refused : null);
    const roll = u.previous ? SW.btn(SW.t("updates_rollback_button", { previous: u.previous }), { cls: "btn--danger", run: () => startJob(back, "rollback",
      destroy("updates_dialog_rollback_title", "updates_dialog_rollback_body", "updates_roll_back", { version: u.previous })) }) : null;
    const job = runningJob();
    if (job) SW.disable(check, SW.t("common_wait_for_job", { job_title: job }));
    if (update) held(update, u.update_refused, refused);
    if (roll) held(roll, u.rollback_refused, rollRefused);
    const notesId = SW.uid("updates-notes");
    fill(out,
      h("div", { class: "page-head__actions updates__actions" }, check, update),
      refused, box,
      h("div", { class: "updates__cards" },
        versionCard(u),
        u.notes ? h("section", { class: "card updates__notes" },
          h("h2", { id: notesId, textContent: SW.t(u.newer ? "updates_notes_new" : "updates_notes_current", { version: u.latest }) }),
          h("div", { class: "code" }, h("pre", { class: "code__text code__text--log", tabindex: "0", "aria-labelledby": notesId, textContent: u.notes }))) : null,
        h("section", { class: "card" }, h("h2", {}, SW.t("updates_roll_back")),
          h("p", u.previous ? {} : { class: "muted" }, SW.t(u.previous ? "updates_rollback_text" : "updates_rollback_none", { previous: u.previous })),
          u.previous && u.going_back ? h("div", { class: "banner banner--info banner--inline" }, SW.icon("info", "icon--s"),
            h("p", { class: "banner__text updates__going", textContent: u.going_back })) : null,
          roll ? h("div", { class: "row" }, roll) : null,
          rollRefused, back)),
      h("div", { class: "updates__foot" },
        h("p", { textContent: SW.t("updates_remove_line") }),
        updatesCode(SW.t("updates_remove_command"), SW.t("updates_code_caption"))));
  }));
  return [out];
}
