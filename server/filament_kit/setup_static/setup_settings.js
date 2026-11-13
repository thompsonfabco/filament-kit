// The Settings section's cards: General, the filament library, the label reader, the remote certificate, keys and the address.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

// ----- the filament library (Settings) -----
function libraryCard() {
  const body = h("div"), box = boxFor("library"), job = boxFor("library:job");
  const entry = h("textarea", { rows: 4, ariaLabel: "Library entry JSON", placeholder: "One library entry, as JSON" });
  const el = card("Filament library", body,
    h("div", { class: "row" },
      h("button", { textContent: "Update now", on: { click: () => startJob(job, "library_update") } }),
      h("button", { class: "secondary", textContent: "Go back to the version before", on: { click: () => startJob(job, "library_rollback",
        destroy("settings_catalog_back_title", "settings_catalog_back_body", "settings_catalog_back_confirm")) } }), job),
    h("p", { class: "muted", textContent: "Add your own entry. It is checked as `filament-kit library add` checks it, and a preset build follows." }),
    entry,
    h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Add entry", on: { click: () => change(box, "library/add", { entry: entry.value }, (r) => { say(box, `Added ${r.vendor} ${r.product}.`, true); entry.value = ""; }) } })),
    box);
  later(api("library").then((v) => {
    const c = v.last_check;
    fill(body,
      h("p", { textContent: v.source === "none" ? "The library is not downloaded yet." : `Library version ${v.version} (${v.source}), ${v.local} local addition${v.local === 1 ? "" : "s"}.` }),
      h("p", { class: "muted", textContent: c ? `Last check ${c.at}: ${c.ok ? "ok" : c.error}` : "Last check: never." }),
      v.skipped ? h("p", { class: "muted", textContent: v.skipped }) : null);
  }).catch((e) => say(body, e.message, false)));
  return el;
}

// ----- general settings (Settings) -----
// every setting saves on its own, and its result is under its own row (02 8.6)
function generalCard() {
  const body = h("div"), at = (key) => boxFor("general:" + key);
  const save = (key, value) => change(at(key), "settings/general", { key, value }, (r) => {
    if (r.applies) { fill(at(key)); followApply(true); return; }
    if (!r.restarts) { say(at(key), "Saved.", true); return; }
    say(at(key), SW.t("form_saved_restarts"), "run");
    hubJobs().restart(() => say(at(key), SW.t("restart_saved"), true));
  });
  const text = (label, key, v) => {
    const inp = h("input", { value: v == null ? "" : String(v), ariaLabel: label });
    return h("div", { class: "row" }, h("label", {}, `${label}: `, inp), h("button", { class: "secondary", textContent: "Save", on: { click: () => save(key, inp.value) } }), at(key));
  };
  const count = (label, key, v) => {
    const inp = h("input", { type: "number", value: String(v), ariaLabel: label });
    return h("div", { class: "row" }, h("label", {}, `${label}: `, inp), h("button", { class: "secondary", textContent: "Save", on: { click: () => save(key, Number(inp.value)) } }), at(key));
  };
  const el = card("General", body);
  later(api("settings/general").then((g) => {
    const v = g.values;
    const places = h("input", { value: (v.locations || []).join(", "), ariaLabel: "Locations" });
    const names = h("input", { value: (v["setup.hosts"] || []).join(" "), ariaLabel: "Names for this page", placeholder: "kit.example.net" });
    const url = h("input", { placeholder: "http://spoolman.example:7912", ariaLabel: "Spoolman address" });
    fill(body,
      text("Display name", "server_name", v.server_name),
      h("div", { class: "row" }, h("label", {}, "Locations, comma separated: ", places), h("button", { class: "secondary", textContent: "Save", on: { click: () => save("locations", places.value.split(",").map((s) => s.trim()).filter(Boolean)) } }), at("locations")),
      text("PLA rack", "placement.pla_location", v["placement.pla_location"]),
      text("Box location prefix", "placement.box_prefix", v["placement.box_prefix"]),
      count("Number of storage boxes", "placement.box_count", v["placement.box_count"]),
      text("Overflow location", "placement.overflow", v["placement.overflow"]),
      h("div", { class: "row" }, h("label", {}, "Names for this page, space separated: ", names), h("button", { class: "secondary", textContent: "Save", on: { click: () => save("setup.hosts", names.value.split(/[\s,]+/).filter(Boolean)) } }), at("setup.hosts")),
      h("p", { class: "muted", textContent: "Its own names and addresses always work, and so does a local name of your DNS (one word, .local, .lan, .home.arpa, or your network's own domain) that points at this server. Add any other name here." }),
      g.web_on ? h("div", { class: "row" }, h("label", {},
        h("input", { type: "checkbox", checked: v["web.printer_changes"] === true, on: { change: (e) => save("web.printer_changes", e.target.checked) } }),
        " Allow printer changes from the public address"), at("web.printer_changes")) : null,
      g.web_on ? h("p", { class: "muted", textContent: "Off: the phone web app at the web module's public address shows printers but cannot add, change or forget them. On the home network it always can." }) : null,
      (g.ai_intake_on && g.local_intake_on) ? h("div", { class: "row" }, h("label", {}, "Label reader: ",
        h("select", { on: { change: (e) => save("intake.reader", e.target.value) } },
          ...[["auto", "Local first, Claude when unsure (default)"],
              ["cloud-then-local", "Claude first, local when Claude fails"], ["local", "Local reader only"], ["cloud", "Claude only"]]
            .map(([k, t]) => h("option", { value: k, textContent: t, selected: (v["intake.reader"] || "auto") === k })))), at("intake.reader")) : null,
      g.local_intake_on ? localReaderRows(v, save, at) : null,
      text("Claude model", "model", v.model),
      count("Label reads per day", "reads_per_day", v.reads_per_day),
      count("Intake records kept", "intake.history_keep", v["intake.history_keep"] ?? 20),
      h("p", { class: "muted", textContent: `The intake history keeps the newest spool additions with their photos (0 keeps none). Now: ${(g.intake_history || {}).count || 0} records, ${Math.ceil(((g.intake_history || {}).photo_bytes || 0) / 1024)} KB of photos; a record with photos takes about 0.5 to 2 MB.` }),
      h("p", { class: "muted", textContent: "Changing the model or the reads per day restarts the server." }),
      g.station_on ? h("div", { class: "row" }, "Station voice: ",
        h("button", { class: "secondary", textContent: "Piper (natural; a 60-80 MB download)", on: { click: () => save("station.tts", "auto") } }),
        h("button", { class: "secondary", textContent: "espeak-ng (robotic; no download)", on: { click: () => save("station.tts", "espeak") } }), at("station.tts")) : null,
      g.spoolman_external ? h("div", {},
        h("p", { class: "muted", textContent: `Spoolman in use: ${g.spoolman_url}. A new address must answer as Spoolman before it is saved, and the kit then uses that database for everything.` }),
        h("div", { class: "row" }, url, h("button", { class: "secondary", textContent: "Change", on: { click: () => change(at("spoolman"), "settings/spoolman", { url: url.value }, () => { fill(at("spoolman")); followApply(true); }) } }), at("spoolman"))) : null);
  }).catch((e) => say(body, e.message, false)));
  return el;
}

// the local label reader (local_intake): its address, its tier, and a test of /v1/health
function localReaderRows(v, save, at) {
  const urlKey = "local_intake.url", tierKey = "local_intake.tier";
  const url = h("input", { value: v[urlKey] || "", placeholder: "http://127.0.0.1:7915", ariaLabel: "Local reader address" });
  const out = slot();
  const test = () => {
    working(out, "Asking the local reader…");
    api("settings/local-intake").then((r) => {
      const tiers = Object.entries(r.tiers || {}).map(([k, t]) => `${k} ${t.usable ? "usable" : "not usable" + (t.reason ? " (" + t.reason + ")" : "")}`).join(", ");
      say(out, r.ok
        ? `Answering: version ${r.version || "?"}, API ${r.api_version}; ${tiers || "no tiers listed"}${r.revise ? "; can revise readings" : ""}${r.degraded ? ". " + r.error : ""}.`
        : `Not usable: ${r.error}`, r.ok);
    }).catch((e) => say(out, e.message, false));
  };
  return h("div", {},
    h("div", { class: "row" }, h("label", {}, "Local reader address: ", url),
      h("button", { class: "secondary", textContent: "Save", on: { click: () => save(urlKey, url.value.trim()) } }),
      h("button", { class: "secondary", textContent: "Test", on: { click: test } }), at(urlKey), out),
    h("div", { class: "row" }, h("label", {}, "Local reader tier: ",
      h("select", { on: { change: (e) => save(tierKey, e.target.value) } },
        ...[["auto", "Auto: CPU, then GPU when unsure"], ["cpu", "CPU only"], ["gpu", "GPU only"]]
          .map(([k, t]) => h("option", { value: k, textContent: t, selected: (v[tierKey] || "auto") === k })))), at(tierKey)),
    h("p", { class: "muted", textContent: "The reader may run on another computer on your network (one with a GPU). The label photos and your filament list go to this address (plain HTTP unless it starts with https), so give one you trust. Only Claude's reads count against the reads per day." }));
}

// ----- the local label reader: install, upgrade, remove (Settings) -----
// Sizes and time come from the release's signed manifest and are shown before the owner confirms; the install runs
// as a job (filament-kit local-intake install --yes, tier: local_intake.tier). A reader on another machine needs no
// install: switch local_intake on in Modules and give its address under General.
function readerCard() {
  const body = h("div"), box = boxFor("local_intake"), install = boxFor("reader-card:install"), tokBox = boxFor("reader-card:token");
  const el = card("Local label reader", body);
  later(api("settings/general").then((g) => {
    const have = g.local_intake_installed;
    const out = h("div");
    // the check runs as a job (the server does not reach GitHub); what it saved is shown here, and Install takes
    // exactly that version (the job refuses a plan older than an hour)
    const check = () => startJob(box, "local_intake_plan");
    const plan = api("settings/local-intake/plan").then((r) => {
      const s = r.saved;
      if (!s) return;
      const p = s.plan, t = p.tiers[p.tier];
      const when = new Date(s.at * 1000).toLocaleString();
      const label = p.upgrade ? "Upgrade" : p.same ? "Reinstall" : "Install";
      fill(out, h("p", { class: "muted", textContent: `Checked ${when}:` }), ...s.text.map((line) => h("p", { textContent: line })),
        t && s.fresh && !p.downgrade ? h("button", { textContent: `${label} ${p.version} (${p.tier} tier)`, on: { click: () => startJob(install, "local_intake_install",
          { title: SW.t("settings_local_install_title", { version: p.version }), text: s.text.filter((l) => !l.startsWith("Installed") && !l.startsWith("Other")).join(" "),
            confirm: `${label} ${p.version} (${p.tier} tier)` }) } }) : null,
        install,
        !s.fresh ? h("p", { class: "muted", textContent: "That check is over an hour old: check again to install." }) : null,
        h("p", { class: "muted", textContent: "The tier is the one under General (Local reader tier); change it there, then check again." }));
    }).catch((e) => say(out, e.message, false));
    const tok = secret("Local reader token");
    const tokenRow = h("div", {},
      h("p", { class: "muted", textContent: `Reader token: ${S.local_intake_token && S.local_intake_token.set ? "set" : "not set"}. Only for a reader installed with a token (one on another machine, usually); it is sent with each read, never shown again.` }),
      h("div", { class: "row" }, tok,
        h("button", { class: "secondary", textContent: S.local_intake_token && S.local_intake_token.set ? "Replace" : "Set", on: { click: () => change(tokBox, "local_intake_token", { token: tok.value }, null, [tok]) } }),
        S.local_intake_token && S.local_intake_token.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => change(tokBox, "local_intake_token/remove", {}) } }) : null, tokBox));
    fill(body,
      h("p", { class: "muted", textContent: have
        ? `Installed on this machine: version ${have.version}, ${have.tier} tier.`
        : "Not installed on this machine. It reads label photos without the cloud; a reader on another machine (one with a GPU) works too: switch local_intake on in Modules and give its address under General." }),
      h("div", { class: "row" },
        h("button", { class: "secondary", textContent: have ? "Check for an upgrade" : "Check what an install needs", on: { click: check } }),
        have ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => startJob(box, "local_intake_remove",
          destroy("settings_local_remove_title", "settings_local_remove_body", "common_remove")) } }) : null, box),
      out, tokenRow);
    return plan;
  }).catch((e) => say(body, e.message, false)));
  return el;
}

// ----- the remote module's certificate (Settings) -----
function remoteCard() {
  const body = h("div"), box = boxFor("remote");
  const el = card("Remote access", body, box);
  later(api("settings/general").then((g) => {
    if (!g.remote_on) { fill(body, h("p", { class: "muted", textContent: "Turn on the remote module in Modules to use a public name." })); return; }
    fill(body,
      h("p", { class: "muted", textContent: "The kit never changes your firewall or router. Getting the certificate needs port 80 to reach this computer while certbot runs." }),
      h("div", { class: "row" },
        h("button", { class: "secondary", textContent: "Show the firewall rules", on: { click: () => change(box, "remote/firewall", {}, (r) => say(box, r.text, true)) } }),
        h("button", { textContent: "Get the certificate", on: { click: () => startJob(box, "remote_issue",
          { title: SW.t("settings_certificate_title"), text: SW.t("settings_certificate_body"), confirm: SW.t("settings_network_certificate") }) } })));
  }).catch((e) => say(body, e.message, false)));
  return el;
}

// ----- Anthropic key -----
function keyCard() {
  const a = S.anthropic, box = boxFor("key"), inp = secret("sk-ant-…");
  return card(["Anthropic API key ", pill(a.set, "set", "not set")],
    h("p", { class: "muted", textContent: a.ai_intake ? "Used for AI label reading (ai_intake)." : "Only for AI label reading: the ai_intake module is off (see Modules)." }),
    h("div", { class: "row" }, inp,
      h("button", { textContent: a.set ? "Replace" : "Set", on: { click: () => change(box, "key", { key: inp.value }, null, [inp]) } }),
      a.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => asking(box, "key/remove", destroy("settings_key_remove_title", "settings_key_remove_body", "settings_key_remove_confirm")) } }) : null,
      h("button", { class: "secondary", textContent: "Check", on: { click: async () => {
        working(box, SW.t("common_checking"));
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
      S.library_token.set ? h("button", { class: "secondary", textContent: "Remove", on: { click: () => asking(box, "library_token/remove",
        destroy("settings_token_remove_title", "settings_token_remove_body", "settings_catalog_token_remove")) } }) : null),
    box);
}

// ----- addresses -----
function addressCard() {
  // each address has its own Save and its result under it
  const box = { "web.public_url": boxFor("address:web"), "station.url": boxFor("address:station") };
  // the state leaves the address out (owner data): a set one shows as a blank box that a blank Save does not clear
  const web = h("input", { placeholder: S.web.public_set ? "set (hidden); type a new address to replace it" : "https://mcp.example.com/filament" });
  const st = h("input", { value: S.station.url || "", placeholder: "http://station.local:5003 (blank: none)" });
  const save = (key, inp) => key === "web.public_url" && S.web.public_set && !inp.value.trim()
    ? say(box[key], "The address is hidden here: type the new one to replace it.", false)
    : change(box[key], "settings", { key, value: inp.value.trim() }, () => { say(box[key], "Saved; applying…", true); followApply(); });
  return card("Addresses",
    h("p", { class: "muted", textContent: "Web public address: the https address of the web app and Claude's connector." }),
    h("div", { class: "row" }, web, h("button", { textContent: "Save", on: { click: () => save("web.public_url", web) } }), box["web.public_url"]),
    h("p", { class: "muted", textContent: "Station address: where this server reads the intake station." }),
    h("div", { class: "row" }, st, h("button", { textContent: "Save", on: { click: () => save("station.url", st) } }), box["station.url"]));
}
