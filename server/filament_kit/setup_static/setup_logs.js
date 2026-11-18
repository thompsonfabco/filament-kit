// The console's Logs section (03 13; R84 2, 3.3, 8). Loaded after setup.js; everything from the server goes in through textContent, as there.
// Logs hold addresses and serial numbers, so reading them takes the setup code; nothing is kept on the page once it locks.
// It opens on Activity (what was done on this Hub: it holds no addresses or serials, so reading it needs no code); Service logs
// are the logs as they were, behind the code. Undo and Collect a Hub report change something or hand a file out: they take the code.
"use strict";

// The texts of this part that the catalogue does not hold yet (only HD2 opens strings/): the catalogue's text wins once it has the key.
const ACT_TEXT = {
  logs_view: "Logs view", logs_activity: "Activity", logs_service_logs: "Service logs",
  activity_who: "Who", activity_kind: "What kind",
  activity_who_any: "Anyone", activity_who_page: "The Hub page", activity_who_cli: "The command line", activity_who_hub: "The Hub itself",
  activity_who_device: "A paired device", activity_who_connector: "The Claude connector",
  activity_kind_any: "Everything", activity_kind_spools: "Spool changes", activity_kind_usage: "Filament used",
  activity_kind_printers: "Printers", activity_kind_devices: "Devices", activity_kind_settings: "Settings and catalog",
  activity_kind_backups: "Backups and restores", activity_kind_hub: "Hub start and updates", activity_kind_records: "Recently added",
  activity_table: "Activity", activity_col_when: "When", activity_col_who: "Who", activity_col_what: "What", activity_col_thing: "Where",
  activity_col_undo: "Undo", activity_open: "Open",
  activity_undo: "Undo", activity_undo_of: "Undo: {what}", activity_put_back: "Put back.",
  activity_undone: "Undone.", activity_put_back_row: "This put an earlier change back.",
  activity_why_changed_since: "This changed again since, so it cannot be undone.",
  activity_why_too_old: "This is too old to undo. Changes can be undone for 7 days.",
  activity_why_already_undone: "This was already undone.",
  activity_show_more: "Show more", activity_showing: "Showing {count} entries.",
  activity_empty_title: "No activity yet", activity_empty_text: "What is done on this Hub is listed here.",
  activity_empty_filtered: "Nothing matches these choices.", activity_error: "Could not read the activity.",
  report_text: "One text file with the versions, checks, settings and recent logs. Addresses, serial numbers and names are left out, so it can be sent with a problem report.",
  report_collect: "Collect a Hub report", report_download: "Download the latest report",
};
const actT = (key, vars) => {
  const v = SW.t(key, vars);
  if (v !== key || !ACT_TEXT[key]) return v;
  return ACT_TEXT[key].replace(/\{([a-z][a-z0-9_]*)\}/g, (m, n) => (vars && vars[n] != null ? String(vars[n]) : m));
};
// Who: the `actor` the Hub page route takes (a type); What kind: the `kinds` it takes, a list of the kinds of R84 section 1
const ACT_WHO = [["", "activity_who_any"], ["page", "activity_who_page"], ["cli", "activity_who_cli"], ["hub", "activity_who_hub"],
  ["device", "activity_who_device"], ["connector", "activity_who_connector"]];
const ACT_KINDS = {
  "": ["activity_kind_any", ""],
  spools: ["activity_kind_spools", "spool.weighed,spool.moved,spool.emptied,spool.opened,spool.loaded,spool.unloaded,slot.cleared"],
  usage: ["activity_kind_usage", "usage.recorded,usage.undone"],
  printers: ["activity_kind_printers", "printer.added,printer.changed,printer.removed"],
  devices: ["activity_kind_devices", "device.paired,device.removed"],
  settings: ["activity_kind_settings", "settings.changed,catalog.changed,location.renamed"],
  backups: ["activity_kind_backups", "backup.finished,backup.failed,hub.restored"],
  hub: ["activity_kind_hub", "hub.started,hub.updated"],
  records: ["activity_kind_records", "record.changed"],
};
const ACT_PAGE = 50;
// the filters and how many rows are asked for stay while the section is drawn again (a job ended, the lock changed)
const actState = { who: "", kind: "", limit: ACT_PAGE };
let logsShows = null;

const LOG_LINES = [50, 100, 200];
let logBlocks = 0;

// `#logs/<service>` shows that service once the page is open
const wantedUnit = () => {
  try { return decodeURIComponent(location.hash.slice(1).split("/")[1] || ""); } catch { return ""; }
};

function logsView(units) {
  const want = units.includes(wantedUnit()) ? wantedUnit() : "";
  const unit = SW.field({ label: SW.t("logs_service"), type: "select", mono: true, value: want || units[0],
    options: units.map((u) => ({ value: u, label: u })) });
  const lines = SW.segmented({ legend: SW.t("logs_lines"), name: "logs-lines", value: "100",
    options: LOG_LINES.map((n) => ({ value: String(n), label: String(n) })) });
  const show = SW.btn(SW.t("common_show"), { cls: "btn--primary", run: () => read() });
  const locked = h("div", { role: "status" });
  const out = h("div", { class: "logs__out" });
  const controls = h("div", { class: "logs__controls" }, unit, lines, show);
  let seen = false, running = false, again = false;

  const label = () => { show.textContent = SW.t(seen ? "logs_show_again" : SW.lock.state === "locked" ? "logs_unlock_show" : "common_show"); };
  const block = (service, text) => {
    const id = "log-" + ++logBlocks;
    const copy = SW.btn(SW.t("common_copy"), { cls: "btn--ghost", icon: "copy", action: text ? "copy" : null });
    if (!text) SW.disable(copy, SW.t("code_nothing"));
    return h("div", { class: "code" },
      h("div", { class: "code__bar" }, h("span", { class: "code__caption mono", id: id + "-name", textContent: service }),
        h("span", { class: "result", role: "status" }), copy),
      h("pre", { class: "code__text", tabindex: "0", "aria-labelledby": id + "-name", textContent: text || SW.t("logs_empty") }));
  };
  const read = () => needCode(async () => {
    if (running) { again = true; return; }
    running = true;
    SW.busy(show, SW.t("common_reading"));
    const sent = { unit: unit._control.value, lines: Number(lines.querySelector("input:checked").value) };
    try {
      const r = await api("logs", { ...sent, code: theCode() });
      if (SW.lock.state === "locked") return;      // locked while it was read: the reply is dropped, not written back
      seen = true;
      out.replaceChildren(block(sent.unit, r.text),
        r.truncated ? h("p", { class: "muted", textContent: SW.t("logs_truncated") }) : null);
    } catch (e) {
      if (e.locked) { again = false; throw e; }
      out.replaceChildren(h("div", { class: "code" }, SW.errorState({ title: SW.t("logs_read_error"), text: hubText(e.message), level: 3,
        onTry: () => read() })));
    } finally {
      running = false;
      SW.idle(show);
      label();
    }
    if (again) { again = false; read(); }
  });
  // Unlocked or Trusted, a new choice shows its log at once; Locked, Show asks for the code first
  controls.addEventListener("change", () => { if (SW.lock.state !== "locked") read(); });
  whenOpen(controls, (open) => {
    if (open) {
      locked.replaceChildren();
      if (want && !seen) read();
    } else {
      seen = false;
      out.replaceChildren();
      locked.replaceChildren(h("div", { class: "banner banner--info banner--inline" }, SW.icon("lock", "icon--s"),
        h("p", { class: "banner__text", textContent: SW.t("logs_locked") })));
    }
    label();
  });
  return h("div", { class: "logs" }, locked, controls, out);
}

// ----- Activity (R84 2): time, who, what, a link to the thing; an undoable row keeps Undo while the Hub allows it -----
const ACT_ALIAS = { printer: "printers", spool: "spools", storage: "overview/storage-use", "storage-use": "overview/storage-use",
  "running-low": "overview/running-low", record: "recent" };
// where an event's action goes: the Hub page's own addresses; a place this page does not have has no link
function actPlace(action) {
  if (!action || !action.place) return null;
  const place = ACT_ALIAS[action.place] || action.place;
  if (!Object.hasOwn(TABS, place.split("/")[0]) && place !== "spools") return null;
  return "#" + place + (action.id && !place.includes("/") ? "/" + encodeURIComponent(action.id) : "");
}
const actWhen = (at) => {
  const d = new Date(at), ok = !Number.isNaN(d.getTime());
  return h("time", { datetime: ok ? d.toISOString() : "", textContent: ok ? d.toLocaleString() : String(at) });
};
const actWhy = (why) => (why && why !== "not_undoable" && ACT_TEXT["activity_why_" + why] ? actT("activity_why_" + why) : "");
const actNewest = (a, b) => (String(b.at) < String(a.at) ? -1 : String(b.at) > String(a.at) ? 1 : (Number(b.id) || 0) - (Number(a.id) || 0));

function activityView() {
  const who = SW.field({ label: actT("activity_who"), type: "select", value: actState.who,
    options: ACT_WHO.map(([value, key]) => ({ value, label: actT(key) })) });
  const kind = SW.field({ label: actT("activity_kind"), type: "select", value: actState.kind,
    options: Object.entries(ACT_KINDS).map(([value, [key]]) => ({ value, label: actT(key) })) });
  const controls = h("div", { class: "logs__controls" }, who, kind);
  const said = h("div", { class: "result result--block", role: "status" });
  const out = h("div", { class: "logs__out" });
  let turn = 0;

  const cell = (col, key, ...content) => h("div", { class: "coll__cell", role: "cell", "data-col": col },
    key ? h("span", { class: "coll__key", "aria-hidden": "true", textContent: actT(key) }) : null, ...content);
  const row = (ev) => {
    const what = ev.text || ev.title || "";
    const note = ev.undone ? actT("activity_undone") : ev.undo_of ? actT("activity_put_back_row")
      : ev.undo && !ev.undo.possible ? actWhy(ev.undo.why_not) : "";
    const href = actPlace(ev.action), name = ev.subject && ev.subject.name;
    const undo = ev.undo && ev.undo.possible && !ev.undone
      ? SW.btn(actT("activity_undo"), { cls: "btn--ghost", icon: "undo", action: "undo", name: actT("activity_undo_of", { what }),
        run: () => undoEvent(ev) })
      : null;
    return h("div", { class: "coll__item", role: "rowgroup", "data-id": String(ev.id), tabindex: "-1" }, h("div", { class: "coll__row", role: "row" },
      cell("when", "activity_col_when", actWhen(ev.at)),
      cell("who", "activity_col_who", (ev.actor && ev.actor.name) || ""),
      cell("what", "activity_col_what", h("span", { textContent: what }), note ? h("span", { class: "coll__sub", textContent: note }) : null),
      cell("thing", "activity_col_thing", href ? h("a", { href, textContent: name || actT("activity_open") }) : name || ""),
      cell("actions", null, undo)));
  };
  const table = (events) => h("div", { class: "coll coll--activity", role: "table", "aria-label": actT("activity_table") },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
      [["when", "activity_col_when"], ["who", "activity_col_who"], ["what", "activity_col_what"], ["thing", "activity_col_thing"], ["actions", "activity_col_undo"]]
        .map(([col, key]) => h("div", { class: "coll__cell", role: "columnheader", "data-col": col },
          col === "actions" ? h("span", { class: "sr", textContent: actT(key) }) : actT(key))))),
    events.map(row));

  const show = (events) => {
    const list = [...events].sort(actNewest);
    const filtered = !!(actState.who || actState.kind);
    const more = list.length >= actState.limit
      ? SW.btn(actT("activity_show_more"), { cls: "btn--ghost", action: "show-more", run: () => { actState.limit += ACT_PAGE; return load(list.length); } })
      : null;
    out.replaceChildren(list.length ? table(list) : SW.empty({ icon: "logs", level: 3,
      title: actT(filtered ? "activity_empty_filtered" : "activity_empty_title"), text: filtered ? null : actT("activity_empty_text") }), more);
    return list;
  };
  // asks for the newest `limit` rows; `from`: how many rows were there before Show more, the focus goes to the first new one
  async function load(from) {
    const mine = ++turn;
    const q = new URLSearchParams({ limit: String(actState.limit) });
    if (actState.who) q.set("actor", actState.who);
    if (actState.kind) q.set("kinds", ACT_KINDS[actState.kind][1]);
    const first = !out._loaded, L = first ? SW.loading(out, { thing: actT("logs_activity"), items: 3 }) : null;
    out.setAttribute("aria-busy", "true");
    try {
      const r = await api("activity?" + q);
      if (mine !== turn) return;
      if (L) L.done();
      out._loaded = true;
      const list = show(r.events || []);
      if (from != null && list.length > from) {
        const next = out.querySelectorAll(".coll__item")[from] || out.querySelector(".coll__item");
        if (next) next.focus();
        SW.announce(actT("activity_showing", { count: list.length }));
      }
    } catch (e) {
      if (mine !== turn) return;
      if (L) L.done();
      out._loaded = false;
      out.replaceChildren(SW.errorState({ title: actT("activity_error"), text: hubText(e.message), level: 3, onTry: () => load() }));
    } finally {
      if (mine === turn) out.removeAttribute("aria-busy");
    }
  }
  // Undo: the Hub answers {undone, event, note?}, or 409 {error, text}; either way the list is read again, as the Hub's state moved
  const undoEvent = (ev) => needCode(async () => {
    const id = String(ev.id);
    try {
      const r = await api(`events/${encodeURIComponent(id)}/undo`, { code: theCode() });
      say(said, [actT("activity_put_back"), r.note ? hubText(r.note) : ""].filter(Boolean).join(" "), true);
    } catch (e) {
      if (e.locked) throw e;
      say(said, hubText((e.data && e.data.text) || actWhy(e.data && e.data.error) || e.message), false);
    }
    await load();
    const mine = [...out.querySelectorAll(".coll__item")].find((r) => r.dataset.id === id);
    if (mine) mine.focus();
  });

  controls.addEventListener("change", () => {
    actState.who = who._control.value;
    actState.kind = kind._control.value;
    actState.limit = ACT_PAGE;
    SW.result(said, null);
    load();
  });
  later(load());
  return h("div", { class: "logs__activity" }, controls, said, out);
}

// ----- Collect a Hub report (R84 8): the job strip follows the job, Download hands the newest one over -----
function reportBar() {
  const box = boxFor("report");
  const collect = SW.btn(actT("report_collect"), { cls: "btn--primary", action: "collect-report", run: () => needCode(async () => {
    working(box, actT("report_collect"));
    try { await api("report", { code: theCode() }); } catch (e) {
      if (e.locked) { SW.result(box, null); throw e; }
      say(box, hubText(e.message), false);
      return;
    }
    fill(box);
    followApply(true);
  }) });
  const get = SW.btn(actT("report_download"), { cls: "btn--ghost", icon: "download", action: "download-report",
    run: () => coded(box, () => download("report/download", { code: theCode() }, "hub-report.txt")) });
  return h("div", { class: "logs__report" }, h("p", { class: "muted", textContent: actT("report_text") }),
    h("div", { class: "actions" }, collect, get), box);
}

function logsTab() {
  if (wantedUnit()) logsShows = "service";
  const shows = logsShows || (logsShows = "activity");
  const modes = SW.segmented({ legend: actT("logs_view"), legendSr: true, name: "logs-view", value: shows,
    options: [{ value: "activity", label: actT("logs_activity") }, { value: "service", label: actT("logs_service_logs") }] });
  const activity = h("div", { hidden: shows !== "activity" }, activityView());
  const service = h("div", { hidden: shows !== "service" });
  let serviceRead = false;
  // the units are read once Service logs is first chosen (or at once when the address names one)
  const readService = () => {
    if (serviceRead) return;
    serviceRead = true;
    later(readRegion(service, "logs", () => api("logs/units"), (r) => {
      if (!r.units.length) { fill(service, SW.empty({ icon: "logs", title: SW.t("logs_none"), level: 3 })); return; }
      fill(service, logsView(r.units));
    }));
  };
  if (shows === "service") readService();
  modes.addEventListener("change", () => {
    logsShows = modes.querySelector("input:checked").value;
    activity.hidden = logsShows !== "activity";
    service.hidden = logsShows !== "service";
    if (logsShows === "activity" && wantedUnit()) history.replaceState(null, "", "#logs");
    if (logsShows === "service") readService();
  });
  return [card(SW.t("nav_logs"), modes, activity, service), card(actT("report_collect"), reportBar())];
}
