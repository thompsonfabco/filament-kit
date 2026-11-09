// The console's own tabs: Overview, the mode presets, Updates, and the panel that follows a background job.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

const fmtDate = (t) => (t ? new Date(t * 1000).toLocaleString() : null);
const link = (tab, text) => h("a", { href: "#" + tab, textContent: text });

// ----- a background job (apply, update, rollback, check): it outlives the server, so the page waits for it -----
const jobState = h("p", { class: "muted" });
const jobOut = h("pre");
const jobNote = h("div");
const jobPanel = h("section", { class: "card job hidden" }, h("h2", { textContent: "Background job" }), jobState, jobOut, jobNote);
const JOB_TITLE = { apply: "Applying the changes", update: "Updating", rollback: "Rolling back", check: "Checking for updates" };
let jobFrom = 0, jobName = null, jobLive = false;     // jobLive: one poll loop at a time, or lines would come twice

function followApply(fresh) {
  if (fresh) { jobFrom = 0; jobName = null; jobOut.textContent = ""; }
  jobPanel.classList.remove("hidden");
  if (jobLive) return;
  jobLive = true;
  jobTick();
}

async function jobTick() {
  let r;
  try {
    r = await api(`job?from=${jobFrom}`);
  } catch (e) {
    // the server restarts during an apply, an update or a rollback. A release without this route answers 404: reload.
    if (e.status === 404) { location.reload(); return; }
    jobState.textContent = "The server is restarting; waiting for it to come back…";
    setTimeout(jobTick, 2000);
    return;
  }
  if (S && r.version !== S.version) { location.reload(); return; }        // the new release's own page
  if (r.next < jobFrom || (jobName && r.name && r.name !== jobName)) {    // another job started over
    jobFrom = 0; jobOut.textContent = ""; jobName = r.name;
    setTimeout(jobTick, 200);
    return;
  }
  jobName = r.name;
  jobOut.textContent += r.text; jobFrom = r.next;
  jobOut.scrollTop = jobOut.scrollHeight;
  const title = JOB_TITLE[r.name] || "Working";
  jobState.textContent = r.running ? `${title}…` :
    r.lost ? `${title}: it stopped without finishing. See the log, or at the server: sudo journalctl -u filament-kit-setup-job` :
    r.exit === 0 ? `${title}: done.` : r.exit == null ? "" : `${title}: failed (exit ${r.exit}). See the lines above.`;
  // the whole log counts in bytes and this view in its own text, so they don't mix: offered once the job has ended
  if (!r.running) jobNote.replaceChildren(
    h("p", { class: "muted", textContent: "Addresses and serials are hidden here." }),
    h("button", { class: "secondary", textContent: "Show the whole log", on: { click: showWholeLog } }));
  if (r.running || r.text) { setTimeout(jobTick, 1000); return; }
  jobLive = false;
  refresh();
}

async function showWholeLog() {
  const box = h("div");
  jobNote.replaceChildren(box);
  try {
    let at = 0, text = "";
    for (;;) {
      const r = await api("job/log", { from: at, code: codeIn.value });
      text += r.text;
      if (r.next === at) break;
      at = r.next;
    }
    jobOut.textContent = text;
  } catch (e) { say(box, e.message, false); }
}

// ----- Overview -----
const ROW_MARK = { ok: ["ok", "OK"], fail: ["bad", "needs a look"], info: ["", "note"] };
function rowEl(r) {
  if (r.state === "detail") return h("p", { class: "muted indent", textContent: r.text });
  const [cls, word] = ROW_MARK[r.state] || ROW_MARK.info;
  const box = h("div");
  return h("div", { class: "item" },
    h("p", {}, h("span", { class: "pill " + cls, textContent: word }), " ", r.text),
    r.state === "fail" && r.fix ? h("p", { class: "muted indent", textContent: `Fix: ${r.fix}` }) : null,
    r.action === "ensure_fields" ? h("div", { class: "row" }, h("button", { textContent: "Make the fields", on: { click: () => change(box, "fields", {}, () => say(box, "Done.", true)) } })) : null,
    box);
}

function checklist() {
  const todo = [];
  if (!S.code_set) todo.push("No setup code yet: at the server, sudo filament-kit setup-code");
  if (S.printers.on && !S.printers.list.length) todo.push(["Printers: none yet → ", link("printers", "Printers")]);
  if (!S.devices.length) todo.push(["Phone: not paired → ", link("devices", "Devices")]);
  if (S.anthropic.ai_intake && !S.anthropic.set) todo.push(["Anthropic key: not set → ", link("settings", "Settings")]);
  if (S.passphrase.web && !S.passphrase.set) todo.push(["Web passphrase: not set → ", link("settings", "Settings")]);
  return todo.length ? card("Still to do", h("ul", {}, ...todo.map((t) => h("li", {}, t)))) : null;
}

function overviewTab() {
  const rowsBox = h("div", {}, h("p", { class: "muted", textContent: "Checking…" }));
  const head = h("div");
  const show = (r) => {
    const u = r.update;
    head.replaceChildren(h("p", {}, `filament-kit ${r.version_text || r.version} · mode ${S.mode} `,
      u.newer ? h("span", { class: "pill no", textContent: `${u.latest} is available` }) : null,
      " ", link("updates", u.newer ? "Update" : "Updates")));
    fill(rowsBox, ...r.rows.map(rowEl),
      r.redacted ? h("p", { class: "muted", textContent: "Addresses and serials are hidden until the setup code is given." }) : null);
  };
  const box = h("div");
  api("overview").then(show).catch((e) => say(rowsBox, e.message, false));
  return [checklist(), card("Status", head, rowsBox,
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Show addresses", on: { click: async () => {
      try { show(await api("overview", { code: codeIn.value })); box.replaceChildren(); } catch (e) { say(box, e.message, false); }
    } } })), box)];
}

// ----- the mode presets -----
function modesCard() {
  const box = boxFor("modes");
  async function ask(m) {
    box.replaceChildren(h("p", { class: "muted", textContent: "…" }));
    let p;
    try { p = await api(`modules/preview?mode=${encodeURIComponent(m.name)}`); } catch (e) { say(box, e.message, false); return; }
    if (p.refused) { say(box, p.refused, false); return; }
    const inputs = p.needs.map((n) => ({ key: n.key, el: h("input", { placeholder: n.prompt }) }));
    box.replaceChildren(
      h("p", { textContent: `Set the mode to ${m.name}.` }),
      ...p.notes.map((n) => h("p", { class: "muted", textContent: n })),
      h("p", { class: "muted", textContent: "On afterwards: " + (p.after.join(", ") || "nothing") }),
      ...inputs.map((i) => h("label", {}, i.el)),
      h("div", { class: "row" },
        h("button", { textContent: "Apply", on: { click: async () => {
          const settings = Object.fromEntries(inputs.map((i) => [i.key, i.el.value]));
          const r = await change(box, "modules/mode", { mode: m.name, settings }, (x) => say(box, x.changed ? "Saved; applying…" : "Unchanged.", true));
          if (r && r.changed) followApply(true);
        } } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => box.replaceChildren() } })));
  }
  return card(`Mode: ${S.mode}`,
    h("div", { class: "row" }, ...S.modes.map((m) => h("button", {
      class: m.name === S.mode ? "" : "secondary", textContent: m.name, disabled: !m.here,
      title: m.here ? "" : "A machine in this mode has no setup page",
      on: { click: () => ask(m) } }))),
    S.modes.some((m) => !m.here) ? h("p", { class: "muted", textContent: "Station mode has no server and so no setup page: at the server, sudo filament-kit modules set station --server <the kit server's address>." }) : null,
    box);
}

// ----- Updates -----
function startJob(box, name, question) {
  if (question && !window.confirm(question)) return;
  change(box, "job", { name }, () => { box.replaceChildren(); followApply(true); });
}

function updatesTab() {
  const out = h("div", {}, h("p", { class: "muted", textContent: "Reading…" }));
  const box = boxFor("updates");
  api("updates").then((u) => {
    fill(out,
      card("Version",
        h("p", {}, `Installed: ${u.installed}`),
        h("p", {}, u.latest ? `Latest release: ${u.latest}${u.newer ? "" : " (up to date)"}` : "Latest release: not checked yet"),
        u.checked_at ? h("p", { class: "muted", textContent: `Last checked ${fmtDate(u.checked_at)}.` }) : null,
        u.held && u.held === u.latest ? h("p", { class: "muted", textContent: `${u.held} was rolled back: the timer skips it, Update here installs it.` }) : null,
        u.failed && u.failed === u.latest ? h("p", { class: "muted", textContent: `Installing ${u.failed} failed before: the timer waits for a newer release, Update here tries it again.` }) : null,
        h("p", { class: "muted" }, u.module_on ? `Checked by itself ${u.schedule || ""} (the updates module).` : "Not checked by itself: the updates module is off. ", u.module_on ? null : link("modules", "Modules")),
        h("div", { class: "row" },
          h("button", { class: "secondary", textContent: "Check now", on: { click: () => startJob(box, "check") } }),
          u.newer ? h("button", { textContent: `Update to ${u.latest}`, disabled: !!u.update_refused, on: { click: () => startJob(box, "update", `Update to ${u.latest}? The kit stops while it installs and starts again by itself.`) } }) : null),
        u.newer && u.update_refused ? h("p", { class: "err", textContent: u.update_refused }) : null,
        box),
      u.notes ? card(u.newer ? `What ${u.latest} brings` : `Release notes of ${u.latest}`, h("pre", { textContent: u.notes })) : null,
      card("Roll back",
        u.previous ? h("p", {}, `Goes back to ${u.previous}, the version this one replaced. Settings and data stay.`) : h("p", { class: "muted", textContent: "No earlier version is kept, so there is nothing to roll back to." }),
        u.previous && u.going_back ? h("pre", { textContent: u.going_back }) : null,
        u.previous ? h("div", { class: "row" }, h("button", { class: "danger", textContent: `Roll back to ${u.previous}`, disabled: !!u.rollback_refused, on: { click: () => startJob(box, "rollback", `Roll back to ${u.previous}? The kit stops while it installs and starts again by itself.`) } })) : null,
        u.previous && u.rollback_refused ? h("p", { class: "err", textContent: u.rollback_refused }) : null),
      h("p", { class: "muted", textContent: "To remove the kit: at the server, sudo filament-kit uninstall." }));
  }).catch((e) => say(out, e.message, false));
  return [out];
}
