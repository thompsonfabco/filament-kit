// The Overview section (03 4): the header meta line, Still to do, the four tiles and the checks in groups.
// Loaded after setup.js; everything from the server goes in through textContent, as there.
"use strict";

const OVERVIEW = "overview";      // the section's name in TABS; its catalogue keys start with it
const CHECK_STATUS = { ok: "ok", fail: "needs_look" };      // anything else is a note
const CHECK_ORDER = { fail: 0, info: 1, ok: 2 };
// a fix that is a command (the Hub writes "run: sudo …" or "sudo …") is shown as a code block with Copy
const FIX_COMMAND = /^(?:run: )?((?:sudo|filament-kit) .+)$/;

// how long ago, as the catalogue says it; a day or more is the date
function ovAgo(ms) {
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (s < 60) return SW.t("common_age_seconds", { count: s });
  if (s < 3600) return SW.t("common_age_minutes", { count: Math.floor(s / 60) });
  return s < 172800 ? SW.t("common_age_hours", { count: Math.floor(s / 3600) }) : fmtDate(ms / 1000);
}
const ovExact = (ms) => new Date(ms).toLocaleString();
// the relative time as a <time> with its exact time on hover; it keeps itself right while it is on the page
function ovTime(ms, text) {
  const t = h("time", { datetime: new Date(ms).toISOString(), textContent: text(ms) });
  const timer = setInterval(() => { if (t.isConnected) t.textContent = text(ms); else clearInterval(timer); }, 15000);
  return SW.tooltip(t, ovExact(ms));
}

// a command with Copy (02 7.7): `name` is what Copy says it copies
function ovCode(command) {
  const cap = SW.uid("cap");
  return h("figure", { class: "code" },
    h("pre", { class: "code__text", tabindex: "0", "aria-labelledby": cap }, h("code", { textContent: command })),
    h("figcaption", { class: "code__bar" }, h("span", { class: "code__caption mono", id: cap, textContent: SW.t("overview_command") }),
      h("span", { class: "result", role: "status" }),
      h("button", { class: "btn btn--ghost", type: "button", "data-action": "copy",
        "aria-label": SW.t("common_copy_named", { name: SW.t("overview_command_name"), value: command }) }, SW.icon("copy", "icon--s"), SW.t("common_copy"))));
}

// ----- Still to do (03 4.2): a warn mark, one sentence, one default button to the exact place -----
function todoItems() {
  const go = (key, label, to) => ({ text: SW.t(key), go: [label, to] });
  const todo = [];
  if (!S.code_set) todo.push({ text: SW.t("overview_todo_setup_code"), code: SW.t("common_setup_code_command") });
  if (S.printers.on && !S.printers.list.length) todo.push(go("overview_todo_printer", "overview_todo_printer_button", "#printers/add"));
  if (!S.devices.length) todo.push(go("overview_todo_phone", "overview_todo_phone_button", "#devices/pair"));
  if (!S.devices.length && !S.printers.list.length) todo.push(go("overview_todo_restore", "overview_todo_restore_button", "#settings/backups"));
  if (S.anthropic.ai_intake && !S.anthropic.set) todo.push(go("overview_todo_key", "common_open_settings", "#settings/label-reader"));
  if (S.passphrase.web && !S.passphrase.set) todo.push(go("overview_todo_passphrase", "common_open_settings", "#settings/passphrase"));
  return todo;
}
function todoCard() {
  const todo = todoItems();
  if (!todo.length) return null;
  return h("section", { class: "card overview__todo", "aria-labelledby": "overview-todo-title" },
    h("div", { class: "overview__head" }, h("h2", { id: "overview-todo-title", textContent: SW.t("overview_todo_title") }),
      SW.status("needs_look", { small: true, text: String(todo.length) })),
    h("ul", { class: "todo" }, ...todo.map((t) => h("li", { class: "todo__item" },
      h("span", { class: "status status--warn" }, SW.shape("s-triangle"), h("span", { class: "sr", textContent: SW.t("status_needs_look") })),
      h("div", { class: "todo__text" }, h("p", { textContent: t.text }), t.code ? ovCode(t.code) : null),
      t.go ? h("a", { class: "btn", href: t.go[1], textContent: SW.t(t.go[0]) }) : null))));
}

// ----- the four tiles (03 4.2): each a link to its section; "Switched off" when the feature is off -----
function tile(name, to, value, line, off) {
  return h("li", {}, h("a", { class: "tile", href: to, "data-state": off ? "off" : undefined },
    h("span", { class: "tile__name", textContent: name }),
    h("span", { class: "tile__value" + (off ? " muted" : ""), textContent: off ? SW.t("common_switched_off") : null }, off ? null : value),
    off || !line ? null : h("span", { class: "tile__line muted", textContent: line })));
}
function printersTile() {
  const P = S.printers.on ? S.printers.list.filter((p) => p.configured) : [];
  const up = P.filter((p) => p.state === "connected").length, down = P.length - up;
  const missing = S.printers.list.length - P.length;
  const word = up ? "connected" : down ? "offline" : "not_configured";
  const line = down ? SW.t("overview_tile_printers_offline", { count: down })
    : missing ? SW.t("overview_tile_printers_not_configured", { count: missing }) : P.length ? "" : SW.t("overview_tile_printers_none");
  return tile(SW.t("nav_printers"), "#printers", SW.status(word, { text: SW.t("overview_tile_printers_connected", { count: up }) }), line, !S.printers.on);
}
function recentTile() {
  const t = tile(SW.t("nav_recently_added"), "#recent", h("span", { class: "skeleton__line", "aria-hidden": "true" }), "", false);
  const value = t.querySelector(".tile__value");
  const none = (key) => { value.textContent = SW.t(key); value.classList.add("muted"); };
  later(api("intake/history").then((d) => {
    const newest = d.records.find((r) => r.spools.length);
    if (!newest) { none("recent_empty_title"); return; }
    value.textContent = SW.t("spool_title", { id: newest.spools[0].spool_id });
    const at = Date.parse(newest.at);
    if (at) t.querySelector("a").append(h("span", { class: "tile__line muted" }, ovTime(at, ovAgo)));
  }, () => none("overview_tile_recent_error")));
  return t;
}
function tiles() {
  const readers = S.readers.list.length;
  const cloud = S.cloud_reads;
  return h("ul", { class: "tiles", "aria-label": SW.t("overview_tiles_label") },
    printersTile(), recentTile(),
    tile(SW.t("nav_devices"), "#devices", SW.t("overview_tile_devices_paired", { count: S.devices.length }),
      SW.t("overview_tile_devices_readers", { count: readers }), false),
    tile(SW.t("common_label_reader"), "#settings/label-reader", SW.t("overview_tile_reader_value", { used: cloud.used, limit: cloud.limit }),
      SW.t("overview_tile_reader_line"), !S.anthropic.ai_intake));
}

// ----- the header meta line (03 4.2): the version, the setup, an update, the job, and when it was checked -----
const SETUP_NAME = { server: "overview_setup_hub", "all-in-one": "features_setup_all_in_one", station: "features_setup_station" };
function jobTitle(name) {
  const key = "job_title_" + name;
  return SW.t(SW.t(key) === key ? "job_title_other" : key);
}
function metaLine(r, checkedAt) {
  const u = r.update;
  const job = r.job && r.job.running ? h("a", { href: "#job", textContent: SW.t("overview_job_running", { job_title: jobTitle(r.job.name) }),
    on: { click: (e) => { e.preventDefault(); hubJobs().chip.click(); } } }) : null;
  return h("p", { class: "page-head__meta" },
    h("span", { textContent: SW.t("overview_meta_version", { version: r.version_text || r.version }) }),
    h("span", { textContent: SW.t("common_setup_line", { setup: SW.t(SETUP_NAME[S.mode] || "features_setup_custom") }) }),
    u.newer ? h("a", { href: "#updates" }, SW.status("note", { text: SW.t("nav_summary_updates_available", { latest: u.latest }) })) : null,
    job,
    h("span", { class: "overview__checked" }, ...SW.t("overview_meta_checked", { time: "\u0001" }).split("\u0001").flatMap((x, i) => (i ? [ovTime(checkedAt, ovAgo), x] : [x]))));
}

// the half-install banner (03 4.2): when the last install stopped halfway and no job runs
function halfBanner(r) {
  const u = r.update;
  if (!(u.half_install && !r.job.running)) return null;
  const b = SW.banner({ kind: "warn", title: SW.t("overview_half_title"), text: SW.t("overview_half_body"), inline: true });
  b.classList.add("overview__half");
  b.append(ovCode(u.half_install));
  return b;
}

// ----- the checks (03 4.2): the Hub's rows in groups, a detail row under the row before it -----
function checkItems(rows) {
  const out = [];
  for (const r of rows) {
    if (r.state === "detail" && out.length) out[out.length - 1].details.push(r.text);
    else out.push({ ...r, state: r.state === "detail" ? "info" : r.state, details: [], group: r.group || "" });
  }
  return out;
}
// the fix column: the row's action button, else its fix (a command as a code block)
function fixCell(r) {
  if (r.state === "ok") return null;
  if (r.action === "ensure_fields") {
    const box = boxFor("check:" + r.action);
    return h("div", { class: "actions" }, SW.btn(SW.t("overview_make_fields"), { cls: "btn--primary", run: () => change(box, "fields", {}, (d) => say(box,
      d.made.length ? SW.t("overview_made_fields", { made: d.made.join(", ") }) : SW.t("overview_fields_present"), true)) }));
  }
  if (!r.fix) return null;
  const m = FIX_COMMAND.exec(r.fix);
  if (!m) return h("p", { textContent: hubText(r.fix) });
  const [command, ...rest] = m[1].split(/\s{2,}/);
  return h("div", {}, ovCode(command), rest.length ? h("p", { class: "muted", textContent: rest.join(" ") }) : null);
}
const checkCell = (col, prio, kids, key) => h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio },
  key ? h("span", { class: "coll__key", "aria-hidden": "true", textContent: key }) : null, kids);
function checkItem(r, i) {
  const fix = fixCell(r);
  const box = r.action ? boxFor("check:" + r.action) : null;
  const item = h("div", { class: "coll__item", role: "rowgroup", "data-key": "check-" + i, "data-state": r.state },
    h("div", { class: "coll__row", role: "row" },
      checkCell("status", 1, SW.status(CHECK_STATUS[r.state] || "note", { small: true, prefix: true })),
      checkCell("title", 1, [h("span", { textContent: r.text }), ...r.details.map((d) => h("p", { class: "muted coll__detail", textContent: d }))]),
      fix ? checkCell("fix", 2, fix, SW.t("common_fix")) : null));
  if (box) item.append(h("div", { class: "coll__row coll__row--result", role: "row", hidden: !box.dataset.state },
    h("div", { class: "coll__cell", role: "cell", "aria-colspan": 3 }, box)));
  return item;
}
function checksTable(items, label) {
  const cols = [["status", "common_field_status", 1], ["title", "overview_col_check", 1], ["fix", "common_fix", 2]];
  const kids = [];
  let group = null;
  items.forEach((r) => {
    if (r.group && r.group !== group) {
      group = r.group;
      kids.push(h("div", { class: "coll__item coll__group", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" },
        h("div", { class: "coll__cell", role: "cell", "aria-colspan": 3, textContent: group }))));
    }
    kids.push(checkItem(r, r.index));
  });
  return h("div", { class: "coll coll--checks", role: "table", "aria-label": label },
    h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" }, cols.map(([col, key, prio]) =>
      h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio, textContent: SW.t(key) })))),
    kids);
}
// groups in the order of their first row; the worst state first within a group, and the groups with a problem first
function grouped(items) {
  const groups = new Map();
  for (const r of items) {
    if (!groups.has(r.group)) groups.set(r.group, []);
    groups.get(r.group).push(r);
  }
  const worst = (list) => Math.min(...list.map((r) => CHECK_ORDER[r.state] ?? 1));
  return [...groups.values()].sort((a, b) => worst(a) - worst(b))
    .flatMap((list) => [...list].sort((a, b) => (CHECK_ORDER[a.state] ?? 1) - (CHECK_ORDER[b.state] ?? 1)));
}
function checksView(rows) {
  const items = checkItems(rows).map((r, index) => ({ ...r, index }));
  const bad = items.filter((r) => r.state === "fail"), ok = items.filter((r) => r.state === "ok");
  const shown = items.filter((r) => r.state !== "ok");
  const label = SW.t("overview_checks_title");
  const fold = ok.length ? h("details", { class: "overview__ok", open: !bad.length },
    h("summary", { textContent: SW.t("overview_show_ok", { count: ok.length }) }), checksTable(grouped(ok), label)) : null;
  return { bad: bad.length, ok: ok.length, nodes: [!bad.length ? h("p", { class: "overview__clear", textContent: SW.t("overview_all_ok") }) : null,
    shown.length ? checksTable(grouped(shown), label) : null, fold] };
}

function overviewTab() {
  const banner = h("div"), body = h("div"), badges = h("span", { class: "overview__badges" });
  const note = h("div", { role: "status" });     // the hidden-values note
  let checkedAt = Date.now();
  const show = (r) => {
    checkedAt = Date.now();
    const view = checksView(r.rows);
    if (page.dataset.section === OVERVIEW) pageHead(metaLine(r, checkedAt), head);      // not once another section is open
    banner.replaceChildren(...[halfBanner(r)].filter(Boolean));
    const marks = [];
    if (view.bad) marks.push(SW.status("needs_look", { small: true, text: SW.t("overview_badge_look", { count: view.bad }) }));
    if (view.ok || !view.bad) marks.push(SW.status("ok", { small: true, text: view.ok ? SW.t("overview_badge_ok", { count: view.ok }) : undefined }));
    badges.replaceChildren(...marks);
    fill(body, ...view.nodes);
    note.replaceChildren(...(r.redacted ? [lockNote("lock_hidden_note")] : []));
  };
  // addresses and serials load by themselves once the page is open, and are read again without the code when it locks
  const read = (open) => {
    const done = readRegion(body, OVERVIEW, () => (open ? api("overview", { code: theCode() }) : api("overview")), show);
    const sr = body.querySelector(".skeleton .sr");
    if (sr) sr.textContent = SW.t("overview_loading");      // the skeleton says what 03 4.3 says
    return done;
  };
  let open = SW.lock.state !== "locked";
  const again = SW.btn(SW.t("overview_run_checks"), { cls: "btn--ghost", icon: "refresh", run: async () => {
    SW.busy(again, SW.t("common_checking"));
    try { await read(open); } finally { SW.idle(again); }
  } });
  const head = h("div", { class: "page-head__actions" }, again);      // Run the checks again, in the section header
  pageHead(null, head);
  whenOpen(body, (now) => { open = now; return read(now); });
  return [banner, todoCard(), tiles(),
    h("section", { class: "card overview__checks", "aria-labelledby": "overview-checks-title" },
      h("div", { class: "overview__head" }, h("h2", { id: "overview-checks-title", textContent: SW.t("overview_checks_title") }), badges),
      body), note];
}
