// The Settings section's Backups and restore group (03 10.6). Loaded after setup.js and setup_settings.js; everything from
// the server goes in through textContent. A backup holds every secret of the Hub: listing, downloading and restoring take
// the setup code (or this computer's trust, as every change does).
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

// A request whose body is a file; the code goes in a header, never in the address. `progress(share)` follows the upload.
function upload(path, file, code, progress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/setup/api/" + path);
    x.withCredentials = true;
    x.setRequestHeader("Content-Type", "application/zip");
    x.setRequestHeader("X-Setup-Code", code);
    if (progress) x.upload.onprogress = (e) => { if (e.lengthComputable && e.total) progress(e.loaded / e.total); };
    x.onload = () => {
      let d;
      try { d = JSON.parse(x.responseText); } catch { d = { error: `HTTP ${x.status}` }; }
      if (x.status < 200 || x.status >= 300 || d.error) reject(hubError(x.status, d)); else resolve(d);
    };
    x.onerror = () => reject(Object.assign(new Error(SW.t("common_hub_no_answer")), { unreachable: true }));
    x.send(file);
  });
}

const bkHead = (col, label, prio) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio }, label);
const bkCell = (col, prio, key, ...kids) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio },
  key ? h("span", { class: "coll__key", "aria-hidden": "true" }, key) : null, ...kids);
const bkKind = { daily: "settings_backups_kind_nightly", "pre-restore": "settings_backups_kind_before" };

// Backups on the Hub: a collection; each Download says its result under its own row
function backupRow(b) {
  const at = boxFor("backup:" + b.name);
  const get = SW.btn(SW.t("common_download"), { cls: "btn--ghost", icon: "download", name: SW.t("settings_backups_download_of", { name: b.at }), action: "download",
    run: () => coded(at, async () => {
      working(at, SW.t("settings_backups_preparing"));
      await download("backups/download", { name: b.name, code: theCode() }, b.download);
      SW.result(at, null);
    }) });
  return h("div", { class: "coll__item", role: "rowgroup", "data-key": b.name, "data-id": b.name },
    h("div", { class: "coll__row", role: "row" },
      bkCell("title", 1, null, h("span", { class: "coll__title mono", textContent: b.at })),
      bkCell("kind", 2, SW.t("settings_backups_col_kind"), SW.t(bkKind[b.kind] || "settings_backups_kind_here")),
      bkCell("size", 2, SW.t("settings_backups_col_size"), SW.t("settings_backups_size", { kib: Math.max(1, Math.round(b.size / 1024)) })),
      bkCell("actions", 1, null, h("div", { class: "actions" }, get))),
    h("div", { class: "coll__row coll__row--result", role: "row", hidden: !at.dataset.state }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": 4 }, at)));
}
function backupList(r) {
  if (!r.backups.length) return h("p", { class: "muted", textContent: SW.t("settings_backups_empty", { folder: r.folder }) });
  const table = h("div", { class: "coll coll--backups", role: "table", "aria-label": SW.t("settings_backups_list") },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
      bkHead("title", SW.t("settings_backups_col_made"), 1), bkHead("kind", SW.t("settings_backups_col_kind"), 2), bkHead("size", SW.t("settings_backups_col_size"), 2),
      h("div", { class: "coll__cell", role: "columnheader", "data-col": "actions" }, h("span", { class: "sr" }, SW.t("common_actions"))))),
    ...r.backups.map(backupRow));
  SW.collection(table, { name: "backups" });
  return table;
}

// Keep nightly backups for: its own small form group (the list it comes with needs the code), saved by the group's Save
function keepForm(r) {
  const days = SW.field({ row: true, type: "number", mono: true, name: "days", label: SW.t("settings_backups_keep"), value: String(r.keep_days),
    unit: SW.t("settings_backups_days"), hint: SW.t("settings_backups_keep_hint"), check: whole(1, 365, "settings_backups_keep_error") });
  const res = sbox();
  const form = h("form", { class: "group group--flat", id: "set-backups-keep", novalidate: true },
    h("span", { class: "group__title sr", textContent: SW.t(SET_KEY.backups) }), h("div", { class: "group__body" }, days),
    h("div", { class: "group__foot" }, res, h("button", { class: "btn btn--primary", type: "submit", textContent: SW.t("settings_backups_save") })));
  let kept = null;
  SW.formGroup(form, { title: SW.t(SET_KEY.backups), send: async (key, value) => {
    try { kept = (await api("backups/keep", { days: Number(value), code: theCode() })).days; } catch (e) { throw setRefusal(form, Object.assign(e, { data: { ...(e.data || {}), field: key } })); }
    return {};
  }, onSaved: () => { if (kept != null) setTimeout(() => SW.result(res, "ok", SW.t("settings_backups_keep_saved", { count: kept })), 60); } });
  return form;
}

// Restore: three steps the person goes through (02 8.2)
function restoreSteps() {
  const rbox = boxFor("restore"), sum = h("div", { class: "settings__summary" }), actions = h("div", { class: "actions" });
  const file = SW.field({ type: "file", label: SW.t("settings_restore_file"), accept: ".zip,application/zip", attrs: { "aria-required": "false" } });
  const bar = SW.progress({ name: SW.t("settings_restore_uploading"), value: 0 });
  bar.hidden = true;
  const go = SW.btn(SW.t("settings_restore_step2"), { cls: "btn--primary", action: "upload-check", run: () => start() });
  const mk = (n, title, ...kids) => h("li", { class: "steps__step" }, h("span", { class: "steps__num" }, String(n), h("span", { class: "sr", hidden: true }, " " + SW.t("status_done"))),
    h("div", { class: "steps__body" }, h("h4", { class: "steps__title", textContent: title }), ...kids));
  const list = [mk(1, SW.t("settings_restore_step1"), file), mk(2, SW.t("settings_restore_step2"), go, bar, rbox), mk(3, SW.t("settings_restore_confirm"), sum, actions)];
  const steps = h("ol", { class: "steps" }, ...list);
  let stage = 1, summary = null;
  const paint = () => {
    const chosen = file._control.files.length > 0;
    list.forEach((li, i) => {
      if (i + 1 < stage) li.dataset.state = "done"; else delete li.dataset.state;
      if (i + 1 === stage) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
      li.querySelector(".steps__num .sr").hidden = !(i + 1 < stage);
    });
    SW.disable(go, chosen ? null : SW.t("settings_restore_first"));
    go._refused = () => file._control.focus();
    sum.hidden = actions.hidden = stage < 3;
  };
  const reset = () => { file._control.value = ""; file._control.dispatchEvent(new Event("change")); summary = null; sum.replaceChildren(); actions.replaceChildren(); stage = 1; SW.result(rbox, null); paint(); };
  file._control.addEventListener("change", () => { stage = file._control.files.length ? 2 : 1; summary = null; sum.replaceChildren(); actions.replaceChildren(); bar.hidden = true; SW.result(rbox, null); paint(); });
  const start = () => {
    if (!file._control.files.length) { say(rbox, SW.t("settings_restore_error_file"), false); return; }
    return coded(rbox, async () => {
      working(rbox, SW.t("settings_restore_uploading"));
      bar.hidden = false;
      SW.setProgress(bar, 0);
      let s;
      try { s = await upload("restore/upload", file._control.files[0], theCode(), (share) => SW.setProgress(bar, share, Math.round(share * 100) + " %")); } catch (e) {
        bar.hidden = true;
        if (e.locked) throw e;
        say(rbox, e.status === 413 ? SW.t("settings_restore_error_large") : hubText(e.message), false);
        return;
      }
      bar.hidden = true;
      SW.result(rbox, null);
      checked(s);
    });
  };
  const line = (key, vars, cls) => h("p", { class: cls || "", textContent: SW.t(key, vars) });
  const checked = (s) => {
    summary = s;
    stage = 3;
    sum.replaceChildren(...[
      line("settings_restore_summary_backup", { host: s.host || SW.t("settings_restore_summary_other_hub"), created: s.created, version: s.kit }),
      line(s.spoolman ? "settings_restore_summary_files_db" : "settings_restore_summary_files", { count: s.files }),
      line("settings_restore_summary_features", { list: s.modules.join(", ") || SW.t("common_none") }),
      s.replaces_data && h("p", {}, SW.status("needs_look", { small: true, text: SW.t("settings_restore_summary_replaces") })),
      s.other_host && h("p", {}, SW.status("note", { small: true, text: SW.t("settings_restore_summary_other_host") })),
      line("settings_restore_summary_code"),
      h("p", { class: "mono", textContent: SW.t("settings_restore_summary_sha", { hash: s.sha256 }) })].filter(Boolean));
    actions.replaceChildren(
      SW.btn(SW.t("settings_restore_button"), { cls: "btn--danger", action: "restore", run: (e) => confirmed({ kind: "typed", word: "restore", opener: e.currentTarget,
        title: SW.t("settings_restore_title"), text: SW.t("settings_restore_short", { host: s.host || SW.t("settings_restore_summary_other_hub"), created: s.created }),
        body: h("p", { class: "dialog__text", textContent: SW.t("settings_restore_body") }), confirm: SW.t("settings_restore_confirm") },
      "job", (values) => ({ name: "restore", confirm: values[values.length - 1].trim(), sha256: s.sha256 }), () => { reset(); followApply(true); }) }),
      SW.btn(SW.t("settings_restore_discard"), { cls: "btn--ghost", action: "discard-upload", run: () => act(rbox, "restore/forget", {}, () => reset()) }));
    paint();
    actions.querySelector("button").focus();
  };
  paint();
  return steps;
}

function backupsGroup() {
  const feature = S.modules.find((m) => m.name === "backup"), box = boxFor("backup"), list = h("div");
  const el = setGroup("backups", { desc: SW.t("settings_backups_desc"), badges: [badge("settings_backups_nightly", feature && feature.on ? "on" : "off")], body: [] });
  const body = el.querySelector(".group__body");
  const show = async () => {
    try {
      const r = await api("backups/list", { code: theCode() });
      list.replaceChildren(backupList(r), keepForm(r));
    } catch (e) { if (e.locked) throw e; say(list, hubText(e.message), false); }
  };
  // Back up now: the job's strip follows it; the list reads again when it has ended
  const now = SW.btn(SW.t("settings_backups_now"), { cls: "btn--primary", action: "backup-now", run: () => needCode(async () => {
    const wrap = el.closest(".settings__group");
    working(box, SW.t("settings_backups_running"));
    try { await api("job", { name: "backup", code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      say(box, hubText(e.message), false);
      return;
    }
    if (wrap) wrap._hold = true;
    const end = await SW.setting("waitJob")();
    if (wrap) wrap._hold = false;
    say(box, SW.t(end && end.state === "failed" ? "settings_backups_failed" : "settings_backups_done"), end && end.state === "failed" ? false : true);
    if (SW.lock.state !== "locked") await show();
  }) });
  body.append(SW.banner({ kind: "warn", inline: true, text: SW.t("settings_backups_warning") }),
    h("div", { class: "actions" }, now), box,
    heading("settings_backups_list"), codeRead("common_list_locked", list, show),
    heading("settings_restore_heading"), restoreSteps());
  return el;
}
