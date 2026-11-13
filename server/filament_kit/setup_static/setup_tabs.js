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
  if (!S.devices.length && !S.printers.list.length) todo.push(["Moving from another computer? Restore its backup → ", link("settings", "Settings")]);
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
    fill(rowsBox,
      u.half_install && !r.job.running ? h("p", { textContent: `The last install or update stopped halfway. To repair it, run on the server: ${u.half_install}` }) : null,
      ...r.rows.map(rowEl),
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

// ----- the filament library (Settings) -----
function libraryCard() {
  const body = h("div"), box = boxFor("library");
  const entry = h("textarea", { rows: 4, ariaLabel: "Library entry JSON", placeholder: "One library entry, as JSON" });
  const el = card("Filament library", body,
    h("div", { class: "row" },
      h("button", { textContent: "Update now", on: { click: () => startJob(box, "library_update") } }),
      h("button", { class: "secondary", textContent: "Go back to the version before", on: { click: () => startJob(box, "library_rollback", "Go back to the library version before the last update?") } })),
    h("p", { class: "muted", textContent: "Add your own entry. It is checked as `filament-kit library add` checks it, and a preset build follows." }),
    entry,
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Add entry", on: { click: () => change(box, "library/add", { entry: entry.value }, (r) => { say(box, `Added ${r.vendor} ${r.product}.`, true); entry.value = ""; }) } })),
    box);
  api("library").then((v) => {
    const c = v.last_check;
    fill(body,
      h("p", { textContent: v.source === "none" ? "The library is not downloaded yet." : `Library version ${v.version} (${v.source}), ${v.local} local addition${v.local === 1 ? "" : "s"}.` }),
      h("p", { class: "muted", textContent: c ? `Last check ${c.at}: ${c.ok ? "ok" : c.error}` : "Last check: never." }),
      v.skipped ? h("p", { class: "muted", textContent: v.skipped }) : null);
  }).catch((e) => say(body, e.message, false));
  return el;
}

// ----- general settings (Settings) -----
function generalCard() {
  const body = h("div"), box = boxFor("general");
  const save = (key, value) => change(box, "settings/general", { key, value }, (r) => {
    if (r.applies) { box.replaceChildren(); followApply(true); return; }
    say(box, r.restarts ? "Saved. The server restarts now; this page comes back by itself." : "Saved.", true);
  });
  const text = (label, key, v) => {
    const inp = h("input", { value: v == null ? "" : String(v), ariaLabel: label });
    return h("div", { class: "row" }, h("label", {}, `${label}: `, inp), h("button", { class: "secondary", textContent: "Save", on: { click: () => save(key, inp.value) } }));
  };
  const count = (label, key, v) => {
    const inp = h("input", { type: "number", value: String(v), ariaLabel: label });
    return h("div", { class: "row" }, h("label", {}, `${label}: `, inp), h("button", { class: "secondary", textContent: "Save", on: { click: () => save(key, Number(inp.value)) } }));
  };
  const el = card("General", body, box);
  api("settings/general").then((g) => {
    const v = g.values;
    const places = h("input", { value: (v.locations || []).join(", "), ariaLabel: "Locations" });
    const names = h("input", { value: (v["setup.hosts"] || []).join(" "), ariaLabel: "Names for this page", placeholder: "kit.example.net" });
    const url = h("input", { placeholder: "http://spoolman.example:7912", ariaLabel: "Spoolman address" });
    fill(body,
      text("Display name", "server_name", v.server_name),
      h("div", { class: "row" }, h("label", {}, "Locations, comma separated: ", places), h("button", { class: "secondary", textContent: "Save", on: { click: () => save("locations", places.value.split(",").map((s) => s.trim()).filter(Boolean)) } })),
      text("PLA rack", "placement.pla_location", v["placement.pla_location"]),
      text("Box location prefix", "placement.box_prefix", v["placement.box_prefix"]),
      count("Number of storage boxes", "placement.box_count", v["placement.box_count"]),
      text("Overflow location", "placement.overflow", v["placement.overflow"]),
      h("div", { class: "row" }, h("label", {}, "Names for this page, space separated: ", names), h("button", { class: "secondary", textContent: "Save", on: { click: () => save("setup.hosts", names.value.split(/[\s,]+/).filter(Boolean)) } })),
      h("p", { class: "muted", textContent: "Its own names and addresses always work, and so does a local name of your DNS (one word, .local, .lan, .home.arpa, or your network's own domain) that points at this server. Add any other name here." }),
      g.web_on ? h("div", { class: "row" }, h("label", {},
        h("input", { type: "checkbox", checked: v["web.printer_changes"] === true, on: { change: (e) => save("web.printer_changes", e.target.checked) } }),
        " Allow printer changes from the public address")) : null,
      g.web_on ? h("p", { class: "muted", textContent: "Off: the phone web app at the web module's public address shows printers but cannot add, change or forget them. On the home network it always can." }) : null,
      (g.ai_intake_on && g.local_intake_on) ? h("div", { class: "row" }, h("label", {}, "Label reader: ",
        h("select", { on: { change: (e) => save("intake.reader", e.target.value) } },
          ...[["auto", "Local first, Claude when unsure (default)"],
              ["cloud-then-local", "Claude first, local when Claude fails"], ["local", "Local reader only"], ["cloud", "Claude only"]]
            .map(([k, t]) => h("option", { value: k, textContent: t, selected: (v["intake.reader"] || "auto") === k }))))) : null,
      g.local_intake_on ? localReaderRows(v, save) : null,
      text("Claude model", "model", v.model),
      count("Label reads per day", "reads_per_day", v.reads_per_day),
      count("Intake records kept", "intake.history_keep", v["intake.history_keep"] ?? 20),
      h("p", { class: "muted", textContent: `The intake history keeps the newest spool additions with their photos (0 keeps none). Now: ${(g.intake_history || {}).count || 0} records, ${Math.ceil(((g.intake_history || {}).photo_bytes || 0) / 1024)} KB of photos; a record with photos takes about 0.5 to 2 MB.` }),
      h("p", { class: "muted", textContent: "Changing the model or the reads per day restarts the server." }),
      g.station_on ? h("div", { class: "row" }, "Station voice: ",
        h("button", { class: "secondary", textContent: "Piper (natural; a 60-80 MB download)", on: { click: () => save("station.tts", "auto") } }),
        h("button", { class: "secondary", textContent: "espeak-ng (robotic; no download)", on: { click: () => save("station.tts", "espeak") } })) : null,
      g.spoolman_external ? h("div", {},
        h("p", { class: "muted", textContent: `Spoolman in use: ${g.spoolman_url}. A new address must answer as Spoolman before it is saved, and the kit then uses that database for everything.` }),
        h("div", { class: "row" }, url, h("button", { class: "secondary", textContent: "Change", on: { click: () => change(box, "settings/spoolman", { url: url.value }, () => { box.replaceChildren(); followApply(true); }) } }))) : null);
  }).catch((e) => say(body, e.message, false));
  return el;
}

// the local label reader (local_intake): its address, its tier, and a test of /v1/health
function localReaderRows(v, save) {
  const url = h("input", { value: v["local_intake.url"] || "", placeholder: "http://127.0.0.1:7915", ariaLabel: "Local reader address" });
  const out = h("div");
  const test = () => {
    out.replaceChildren(h("p", { class: "muted", textContent: "Asking the local reader…" }));
    api("settings/local-intake").then((r) => {
      const tiers = Object.entries(r.tiers || {}).map(([k, t]) => `${k} ${t.usable ? "usable" : "not usable" + (t.reason ? " (" + t.reason + ")" : "")}`).join(", ");
      say(out, r.ok
        ? `Answering: version ${r.version || "?"}, API ${r.api_version}; ${tiers || "no tiers listed"}${r.revise ? "; can revise readings" : ""}${r.degraded ? ". " + r.error : ""}.`
        : `Not usable: ${r.error}`, r.ok);
    }).catch((e) => say(out, e.message, false));
  };
  return h("div", {},
    h("div", { class: "row" }, h("label", {}, "Local reader address: ", url),
      h("button", { class: "secondary", textContent: "Save", on: { click: () => save("local_intake.url", url.value.trim()) } }),
      h("button", { class: "secondary", textContent: "Test", on: { click: test } })),
    h("div", { class: "row" }, h("label", {}, "Local reader tier: ",
      h("select", { on: { change: (e) => save("local_intake.tier", e.target.value) } },
        ...[["auto", "Auto: CPU, then GPU when unsure"], ["cpu", "CPU only"], ["gpu", "GPU only"]]
          .map(([k, t]) => h("option", { value: k, textContent: t, selected: (v["local_intake.tier"] || "auto") === k }))))),
    h("p", { class: "muted", textContent: "The reader may run on another computer on your network (one with a GPU). The label photos and your filament list go to this address (plain HTTP unless it starts with https), so give one you trust. Only Claude's reads count against the reads per day." }),
    out);
}

// ----- the local label reader: install, upgrade, remove (Settings) -----
// Sizes and time come from the release's signed manifest and are shown before the owner confirms; the install runs
// as a job (filament-kit local-intake install --yes, tier: local_intake.tier). A reader on another machine needs no
// install: switch local_intake on in Modules and give its address under General.
function readerCard() {
  const body = h("div"), box = boxFor("local_intake");
  const el = card("Local label reader", body, box);
  api("settings/general").then((g) => {
    const have = g.local_intake_installed;
    const out = h("div");
    // the check runs as a job (the server does not reach GitHub); what it saved is shown here, and Install takes
    // exactly that version (the job refuses a plan older than an hour)
    const check = () => startJob(box, "local_intake_plan");
    api("settings/local-intake/plan").then((r) => {
      const s = r.saved;
      if (!s) return;
      const p = s.plan, t = p.tiers[p.tier];
      const when = new Date(s.at * 1000).toLocaleString();
      const label = p.upgrade ? "Upgrade" : p.same ? "Reinstall" : "Install";
      fill(out, h("p", { class: "muted", textContent: `Checked ${when}:` }), ...s.text.map((line) => h("p", { textContent: line })),
        t && s.fresh && !p.downgrade ? h("button", { textContent: `${label} ${p.version} (${p.tier} tier)`, on: { click: () => startJob(box, "local_intake_install",
          `${s.text.filter((l) => !l.startsWith("Installed") && !l.startsWith("Other")).join(" ")} Go ahead?`) } }) : null,
        !s.fresh ? h("p", { class: "muted", textContent: "That check is over an hour old: check again to install." }) : null,
        h("p", { class: "muted", textContent: "The tier is the one under General (Local reader tier); change it there, then check again." }));
    }).catch((e) => say(out, e.message, false));
    const tok = secret("Local reader token"), tokBox = h("div");
    const tokenRow = h("div", {},
      h("p", { class: "muted", textContent: `Reader token: ${S.local_intake_token && S.local_intake_token.set ? "set" : "not set"}. Only for a reader installed with a token (one on another machine, usually); it is sent with each read, never shown again.` }),
      h("div", { class: "row" }, tok,
        h("button", { class: "secondary", textContent: S.local_intake_token && S.local_intake_token.set ? "Replace" : "Set", on: { click: () => change(tokBox, "local_intake_token", { token: tok.value }, null, [tok]) } }),
        S.local_intake_token && S.local_intake_token.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => change(tokBox, "local_intake_token/remove", {}) } }) : null),
      tokBox);
    fill(body,
      h("p", { class: "muted", textContent: have
        ? `Installed on this machine: version ${have.version}, ${have.tier} tier.`
        : "Not installed on this machine. It reads label photos without the cloud; a reader on another machine (one with a GPU) works too: switch local_intake on in Modules and give its address under General." }),
      h("div", { class: "row" },
        h("button", { class: "secondary", textContent: have ? "Check for an upgrade" : "Check what an install needs", on: { click: check } }),
        have ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => startJob(box, "local_intake_remove",
          "Remove the local label reader from this machine and switch local_intake off? Its settings are kept.") } }) : null),
      out, tokenRow);
  }).catch((e) => say(body, e.message, false));
  return el;
}

// ----- the remote module's certificate (Settings) -----
function remoteCard() {
  const body = h("div"), box = boxFor("remote");
  const el = card("Remote access", body, box);
  api("settings/general").then((g) => {
    if (!g.remote_on) { fill(body, h("p", { class: "muted", textContent: "Turn on the remote module in Modules to use a public name." })); return; }
    fill(body,
      h("p", { class: "muted", textContent: "The kit never changes your firewall or router. Getting the certificate needs port 80 to reach this computer while certbot runs." }),
      h("div", { class: "row" },
        h("button", { class: "secondary", textContent: "Show the firewall rules", on: { click: () => change(box, "remote/firewall", {}, (r) => say(box, r.text, true)) } }),
        h("button", { textContent: "Get the certificate", on: { click: () => startJob(box, "remote_issue", "Get the certificate now? Port 80 must reach this computer.") } })));
  }).catch((e) => say(body, e.message, false));
  return el;
}

function updatesTab() {
  const out = h("div", {}, h("p", { class: "muted", textContent: "Reading…" }));
  const box = boxFor("updates");
  api("updates").then((u) => {
    fill(out,
      card("Version",
        h("p", {}, `Installed: ${u.installed_text || u.installed}`),
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
