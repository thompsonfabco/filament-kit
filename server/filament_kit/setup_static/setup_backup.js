// The console's Backups card (Settings). Loaded after setup.js; everything from the server goes in through textContent.
// A backup holds every secret of the kit: listing, downloading and restoring take the setup code (or this computer's
// trust, as every change does).
"use strict";

// A reply that is a file: saved by the browser under the name the server gives.
async function download(path, body, fallback) {
  const r = await fetch("/setup/api/" + path, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { let d = {}; try { d = await r.json(); } catch { /* not JSON */ } throw new Error(d.error || `HTTP ${r.status}`); }
  const m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
  const url = URL.createObjectURL(await r.blob());
  const a = h("a", { href: url, download: m ? m[1] : fallback });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

// A request whose body is a file; the code goes in a header, never in the address.
async function upload(path, file, code) {
  const r = await fetch("/setup/api/" + path, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/zip", "X-Setup-Code": code }, body: file });
  let d;
  try { d = await r.json(); } catch { d = { error: `HTTP ${r.status}` }; }
  if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

function backupCard() {
  const body = h("div"), box = boxFor("backup"), rbox = boxFor("restore");
  const list = h("div");
  const show = async () => {
    try {
      const r = await api("backups/list", { code: codeIn.value });
      offerTrust();
      const days = h("input", { type: "number", min: 1, max: 365, value: String(r.keep_days), ariaLabel: "Days to keep" });
      fill(list,
        r.backups.length ? null : h("p", { class: "muted", textContent: `No backups in ${r.folder} yet.` }),
        ...r.backups.map((b) => h("div", { class: "row item" },
          h("span", { textContent: `${b.at} · ${b.kind === "daily" ? "nightly" : b.kind === "pre-restore" ? "before a restore" : "made here"} · ${Math.max(1, Math.round(b.size / 1024))} KiB` }),
          h("button", { class: "secondary", textContent: "Download", on: { click: async () => {
            say(box, "Preparing the zip…", true);
            try { await download("backups/download", { name: b.name, code: codeIn.value }, b.download); box.replaceChildren(); } catch (e) { say(box, e.message, false); }
          } } }))),
        h("div", { class: "row" }, h("label", {}, "Keep nightly backups for ", days, " days"),
          h("button", { class: "secondary", textContent: "Save", on: { click: () => change(box, "backups/keep", { days: Number(days.value) }, (x) => say(box, `Backups are kept for ${x.days} days.`, true)) } })));
    } catch (e) { say(list, e.message, false); }
  };
  const file = h("input", { type: "file", accept: ".zip,application/zip", ariaLabel: "Backup zip" });
  const restore = async () => {
    if (!file.files.length) { say(rbox, "Choose the backup zip first.", false); return; }
    say(rbox, "Uploading and checking…", true);
    let s;
    try { s = await upload("restore/upload", file.files[0], codeIn.value); offerTrust(); } catch (e) { say(rbox, e.message, false); return; }
    const word = h("input", { ariaLabel: "Type restore", placeholder: "restore" });
    fill(rbox,
      h("p", { textContent: `Backup of ${s.host || "a kit"} made ${s.created} by filament-kit ${s.kit}: ${s.files} files${s.spoolman ? " and the Spoolman database" : ""}. Modules: ${s.modules.join(", ") || "none"}.` }),
      s.replaces_data ? h("p", { class: "err", textContent: "This replaces the spools, settings, printers and pairings on this machine. What is here now is kept as a backup first." }) : null,
      s.other_host ? h("p", { class: "muted", textContent: "The backup is from another computer name: the server gets a new certificate, so phones and the PC sync pair again." }) : null,
      h("p", { class: "muted", textContent: "Afterwards the setup code is the one from the backup." }),
      h("div", { class: "row" }, h("label", {}, "Type restore to go on: ", word),
        h("button", { textContent: "Restore", on: { click: () => change(rbox, "job", { name: "restore", confirm: word.value.trim() }, () => { rbox.replaceChildren(); followApply(true); }) } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => change(rbox, "restore/forget", {}, () => rbox.replaceChildren()) } })));
  };
  fill(body,
    h("p", { class: "muted", textContent: "One zip with everything the kit keeps: spools, settings, printers, pairings and the certificate. Keep it somewhere safe: it holds every secret of the kit." }),
    h("div", { class: "row" },
      h("button", { textContent: "Back up now", on: { click: () => startJob(box, "backup") } }),
      h("button", { class: "secondary", textContent: "Show the backups", on: { click: show } })),
    list,
    h("p", { class: "muted", textContent: "Restore: bring this machine to the state in a backup zip, from this computer or another." }),
    h("div", { class: "row" }, file, h("button", { class: "secondary", textContent: "Upload and check", on: { click: restore } })),
    rbox);
  return card("Backups", body, box);
}
