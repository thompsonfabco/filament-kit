// The console's Backups card (Settings). Loaded after setup.js; everything from the server goes in through textContent.
// A backup holds every secret of the kit: listing, downloading and restoring take the setup code (or this computer's
// trust, as every change does).
"use strict";

// A reply that is a file: saved by the browser under the name the server gives.
async function download(path, body, fallback) {
  const r = await fetch("/setup/api/" + path, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { let d = {}; try { d = await r.json(); } catch { /* not JSON */ } throw hubError(r.status, d); }
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
  if (!r.ok || d.error) throw hubError(r.status, d);
  return d;
}

function backupCard() {
  const body = h("div"), box = boxFor("backup"), rbox = boxFor("restore");
  const list = h("div");
  const show = async () => {
    try {
      const r = await api("backups/list", { code: theCode() });
      const days = h("input", { type: "number", min: 1, max: 365, value: String(r.keep_days), ariaLabel: "Days to keep" });
      fill(list,
        r.backups.length ? null : h("p", { class: "muted", textContent: `No backups in ${r.folder} yet.` }),
        ...r.backups.map((b) => h("div", { class: "row item" },
          h("span", { textContent: `${b.at} · ${b.kind === "daily" ? "nightly" : b.kind === "pre-restore" ? "before a restore" : "made here"} · ${Math.max(1, Math.round(b.size / 1024))} KiB` }),
          h("button", { class: "secondary", textContent: "Download", on: { click: () => coded(box, async () => {
            working(box, "Preparing the zip…");
            await download("backups/download", { name: b.name, code: theCode() }, b.download);
            fill(box);
          }) } }))),
        h("div", { class: "row" }, h("label", {}, "Keep nightly backups for ", days, " days"),
          h("button", { class: "secondary", textContent: "Save", on: { click: () => change(box, "backups/keep", { days: Number(days.value) }, (x) => say(box, `Backups are kept for ${x.days} days.`, true)) } })));
    } catch (e) { if (e.locked) throw e; say(list, e.message, false); }
  };
  const file = h("input", { type: "file", accept: ".zip,application/zip", ariaLabel: "Backup zip" });
  const restore = () => {
    if (!file.files.length) { say(rbox, "Choose the backup zip first.", false); return; }
    coded(rbox, async () => {
      working(rbox, "Uploading and checking…");
      checked(await upload("restore/upload", file.files[0], theCode()));
    });
  };
  const checked = (s) => {
    const word = h("input", { ariaLabel: "Type restore", placeholder: "restore" });
    fill(rbox,
      h("p", { textContent: `Backup of ${s.host || "a kit"} made ${s.created} by filament-kit ${s.kit}: ${s.files} files${s.spoolman ? " and the Spoolman database" : ""}. Modules: ${s.modules.join(", ") || "none"}.` }),
      s.replaces_data ? h("p", { class: "err", textContent: "This replaces the spools, settings, printers and pairings on this machine. What is here now is kept as a backup first." }) : null,
      s.other_host ? h("p", { class: "muted", textContent: "The backup is from another computer name: the server gets a new certificate, so phones and the PC sync pair again." }) : null,
      h("p", { class: "muted", textContent: "Afterwards the setup code is the one from the backup." }),
      h("p", { class: "muted", textContent: `Checked copy: SHA-256 ${s.sha256}. Only this copy is restored.` }),
      h("div", { class: "row" }, h("label", {}, "Type restore to go on: ", word),
        h("button", { textContent: "Restore", on: { click: () => change(rbox, "job", { name: "restore", confirm: word.value.trim(), sha256: s.sha256 }, () => { fill(rbox); followApply(true); }) } }),
        h("button", { class: "secondary", textContent: "Cancel", on: { click: () => change(rbox, "restore/forget", {}, () => fill(rbox)) } })));
  };
  fill(body,
    h("p", { class: "muted", textContent: "One zip with everything the kit keeps: spools, settings, printers, pairings and the certificate. The zip is not encrypted and holds the setup secrets (the keys, Access Codes and certificate): store it somewhere safe." }),
    h("div", { class: "row" }, h("button", { textContent: "Back up now", on: { click: () => startJob(box, "backup") } })),
    codeRead("common_list_locked", list, show),
    h("p", { class: "muted", textContent: "Restore: bring this machine to the state in a backup zip, from this computer or another." }),
    h("div", { class: "row" }, file, h("button", { class: "secondary", textContent: "Upload and check", on: { click: restore } })),
    rbox);
  return card("Backups", body, box);
}
