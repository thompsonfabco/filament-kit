// The component sample (tests/components-sample.html): every component of docs/design/02-components.md sections 2 to
// 10 in its states, built with the shared script and the fake data of mockups/CONTENT-SPEC.md. The Hub is faked: any
// eight digits unlock (00000000 is refused), and the writes answer after a short wait. ?view=loading adds the
// loading states (their regions stay aria-busy on purpose).
(() => {
"use strict";
const { h, t } = SW;
const E = (tag, cls, ...kids) => h(tag, { class: cls }, ...kids);
const query = new URLSearchParams(location.search);
const loadingView = query.get("view") === "loading";
if (["light", "dark"].includes(query.get("theme"))) document.documentElement.setAttribute("data-theme", query.get("theme"));
const wait = (ms) => new Promise((res) => setTimeout(res, ms));
const page = document.getElementById("sample");
page.classList.add("sample");

// ----- the fake Hub -----
const answer = (status, data) => ({ ok: status < 400, status, json: async () => data });
function route(path, body) {
  if (path === "overview") return /^\d{8}$/.test(body.code) && body.code !== "00000000" ? answer(200, { ok: true }) : answer(403, { error: "wrong_code" });
  if (path === "trust") return answer(200, { id: "t1", until: "2027-02-10" });
  if (path === "settings/general" && body.key === "boxes") return answer(500, { error: "busy" });
  if (path === "settings/general" && body.key === "reads") return answer(200, { ok: true, restarts: true });
  if (path === "printers/p3/pause") return answer(409, { error: "refused", message: "Study A1 mini did not accept Pause. Try again." });
  return answer(200, { ok: true });
}
SW.configure({ base: "api/", hub: "Workshop hub", fetch: async (url, init) => {
  await wait(700);
  return route(url.replace(/^api\//, ""), init.body && typeof init.body === "string" ? JSON.parse(init.body) : {});
} });

// ----- the icon sprite: inserted as the first child of body -----
fetch("../icons/sprite.svg").then((r) => r.text()).then((text) => {
  const svg = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
  document.body.prepend(document.importNode(svg, true));
});

// ----- page parts -----
let sec = 0;
function section(title, ...kids) {
  const id = "sec-" + ++sec;
  page.append(h("section", { class: "sample-section", "aria-labelledby": id }, h("h2", { id, text: title }), ...kids));
}
const state = (label, ...kids) => E("div", "sample-state", E("h3", "sample-label", label), ...kids);
const row = (...kids) => E("div", "sample-row", ...kids);
const grid = (...kids) => E("div", "sample-grid", ...kids);
const resultSlot = (block) => h("p", { class: "result" + (block ? " result--block" : ""), role: "status" });
const ic = (name, cls) => SW.icon(name, cls);

// ----- top bar tools: job chip, lock chip, appearance (2.2, 3.1, 3.3) -----
const tools = document.getElementById("tools");
// the chip's name starts with its visible title (SR-7); topbar_job_name puts "Background job" first, so it is not used here
const jobName = (state) => `${t("job_title_backup")}, ${state}. ${t("job_label")}. Show the job panel.`;
const jobChip = h("button", { class: "chip chip--job", type: "button", "aria-controls": "job", "aria-expanded": "false",
  "aria-label": jobName(t("status_running")) },
SW.spinner(), E("span", "chip__word", t("job_title_backup")));
const appearanceValue = document.documentElement.getAttribute("data-theme") || "system";
const appearanceOptions = [["light", "sun", "appearance_light"], ["dark", "moon", "appearance_dark"], ["system", "half-circle", "appearance_system"]]
  .map(([value, icon, key]) => ({ value, icon, label: t(key) }));
tools.append(jobChip, SW_LOCK.lockChip(),
  SW.segmented({ legend: t("appearance_title"), legendSr: true, cls: "appearance", value: appearanceValue, options: appearanceOptions }),
  h("button", { class: "btn btn--ghost btn--icon appearance appearance--menu", type: "button",
    "aria-label": t("appearance_name", { choice: t("appearance_system") }) }, ic("half-circle")));

// ----- page header (2.6) -----
const addPrinter = SW.btn(t("printers_add"), { cls: "btn--primary", action: "add" });
page.append(h("header", { class: "page-head" },
  E("div", "page-head__text",
    h("nav", { class: "page-head__crumbs", "aria-label": t("common_breadcrumb") }, h("a", { href: "#overview", text: "workshop-hub" }), " / ",
      h("span", { "aria-current": "page", text: "components" })),
    h("h1", { class: "page-head__title", tabindex: "-1", text: loadingView ? "Component sample: loading" : "Component sample" }),
    E("p", "page-head__meta", E("span", "mono", "3 printers"), SW.status("connected", { count: 2 }), SW.status("offline", { count: 1 }))),
  E("div", "page-head__actions", SW.btn(t("printers_find"), { action: "find" }), addPrinter)));

// ----- 2 App shell: More sheet, top bar states -----
section("2 App shell",
  row(state("More sheet (phones; opened here from any width)", SW.btn(t("nav_more_sections"), { run: () => document.querySelector(".nav__more").click() })),
    state("Top bar: Hub not reachable", E("span", "topbar__hub", h("span", { "data-state": "error", class: "status status--bad" }, SW.shape("s-octagon"), t("topbar_hub_unreachable")))),
    state("Top bar: Hub name loading", E("span", "skeleton__line")),
    state("Background job chip", h("button", { class: "chip", type: "button", "aria-label": jobName(t("status_done")) },
      SW.shape("s-filled"), E("span", "chip__word", t("job_title_backup"))))));

// ----- 3 Lock and appearance -----
const lockDemo = (st, ic2, word, hint, name) => h("button", { class: "chip chip--lock", type: "button", "aria-haspopup": "dialog", "data-state": st,
  "aria-label": t(name) }, ic(ic2, "icon--s"), E("span", "chip__word", t(word)), h("span", { class: "chip__hint", "aria-hidden": "true", text: t(hint) }));
const appearanceResult = resultSlot();
const themeResult = resultSlot();
const looks = ["console", "workbench", "palette", "panes"];
const themeTiles = h("fieldset", { class: "theme-picker" }, E("legend", "theme-picker__legend", t("appearance_theme_title")),
  looks.map((look) => {
    const off = look !== "console", lineId = "look-" + look + "-line";
    return E("label", "theme-picker__tile",
      h("input", { class: "theme-picker__input", type: "radio", name: "look", value: look, checked: look === (document.documentElement.getAttribute("data-look") || "console"),
        disabled: off, "aria-describedby": lineId }),
      h("span", { class: "theme-picker__preview", "aria-hidden": "true", "data-preview": look, "data-look": look }, E("span", "theme-picker__bar"), E("span", "theme-picker__nav")),
      ic("check", "icon--s theme-picker__check"), E("span", "theme-picker__name", t(`theme_${look}_name`)),
      h("span", { class: "theme-picker__line", id: lineId }, off ? [SW.shape("s-hollow"), t("theme_unavailable_line")] : t(`theme_${look}_line`)));
  }));
section("3 Lock and appearance",
  row(state("Lock chip: Locked, Unlocked, Trusted computer", row(lockDemo("locked", "lock", "lock_locked", "lock_hint_locked", "lock_name_locked"),
    lockDemo("unlocked", "lock-open", "lock_unlocked", "lock_hint_unlocked", "lock_name_unlocked"),
    lockDemo("trusted", "shield", "lock_trusted", "lock_hint_trusted", "lock_name_trusted"))),
  state("Lock chip loading", (() => { const c = SW_LOCK.lockChip({ loading: true }); return c; })()),
  state("Connection chip: Offline, Connecting", row(
    h("button", { class: "chip chip--connection", type: "button", "data-state": "offline", "aria-label": t("connection_name_offline") }, ic("wifi-off", "icon--s"), E("span", "chip__word", t("status_offline"))),
    h("button", { class: "chip chip--connection", type: "button", "data-state": "connecting", "aria-disabled": "true", "aria-label": t("connection_name_connecting") }, SW.spinner(), E("span", "chip__word", t("common_connecting")))))),
  state("Unlock dialog with a pending change (try 00000000 for the refusal)", SW.btn(t("printers_forget"), { cls: "btn--danger", run: (e) => SW.guard("forget Workshop X1", async () => SW.toast("Workshop X1 forgotten.")) })),
  state("Locked placeholder and hidden-values note (1.4)", E("div", "banner banner--info banner--inline", ic("lock"), E("p", "banner__text", t("lock_hidden_note")), E("div", "actions", SW.btn(t("common_unlock_to_show"))))),
  E("div", "group", E("div", "group__head", ic("sun", "icon--s"), E("div", null, E("h3", "group__title", t("appearance_title")), E("p", "group__desc", t("appearance_note")))),
    E("div", "group__body",
      E("div", null, SW.segmented({ legend: t("appearance_title"), cls: "appearance", value: appearanceValue, options: appearanceOptions }), appearanceResult),
      E("div", null, themeTiles, themeResult))));

// ----- 4 Actions -----
const testBtn = SW.btn(t("printers_test"), { icon: "refresh", name: "Test connection to Workshop X1" });
const testResult = resultSlot();
testBtn.addEventListener("click", async () => {
  if (!SW.busy(testBtn, t("common_testing"))) return;
  SW.result(testResult, "run", t("common_testing"));
  await wait(1200);
  SW.idle(testBtn);
  SW.result(testResult, "ok", t("printers_result_bambu_pinned", { address: "192.0.2.40" }));
});
const disabledBtn = SW.btn(t("printers_map_slots"));
const loadingBtn = SW.btn(t("printers_test"), { cls: "btn--primary" });
const menuBtn = SW.iconBtn("more", t("common_more_actions_for", { name: "Workshop X1" }));
SW.menu(menuBtn, [
  { heading: "Workshop X1" },
  { label: t("printers_rename_title"), icon: "pencil", run: () => renameDialog(menuBtn) },
  { label: "Change address", icon: "plug" },
  { label: t("printers_map_slots"), icon: "refresh", disabled: true, reason: t("slot_load_disabled") },
  { label: t("printers_saved_reports"), icon: "download" },
  { label: "Show the job panel", icon: "logs" },
  { separator: true },
  { label: t("printers_forget"), icon: "trash", danger: true, run: () => forgetDialog(menuBtn) }], { label: t("common_actions_for", { name: "Workshop X1" }) });
const when = h("time", { class: "mono", datetime: "2026-11-12T14:05" }, "3 minutes ago");
section("4 Actions",
  row(state("Variants", E("div", "actions", SW.btn("Default"), SW.btn(t("printers_map_slots"), { cls: "btn--primary" }), SW.btn(t("common_cancel"), { cls: "btn--ghost" }),
    SW.btn(t("printers_forget"), { cls: "btn--danger" }), SW.btn(t("printers_forget"), { cls: "btn--danger btn--solid" }), SW.iconBtn("close", t("common_close")))),
  state("With icon, loading and its result", E("div", "actions", testBtn), testResult),
  state("Disabled, the reason beside it", E("div", "actions", disabledBtn)),
  state("Loading", E("div", "actions", loadingBtn)),
  state("Two-column list of ghost buttons", h("div", { class: "actions actions--list" }, ["Rename", "Change address", "Replace Access Code", "Lane data"].map((l) => SW.btn(l, { cls: "btn--ghost" }))))),
  row(state("Overflow menu (Enter, arrows, Home, End, letters, Escape)", E("div", "actions", menuBtn)),
    state("Tooltip on a relative date (hover or focus)", SW.tooltip(when, "2026-11-12 14:05")), state("Tooltip on an icon button", SW.iconBtn("copy", t("common_copy")))));
SW.disable(disabledBtn, "Available when the printer is idle.");
SW.busy(loadingBtn, t("common_testing"));

// ----- 5 Fields and forms -----
const address = SW.field({ label: "IP address or name", name: "address", mono: true, placeholder: "e.g. 192.0.2.40 or printer.local",
  attrs: { inputmode: "url", autocapitalize: "off", autocorrect: "off", spellcheck: "false" },
  check: (v) => (v.trim() ? "" : t("common_error_address")) });
const addressError = SW.field({ label: "IP address or name", name: "address", mono: true, value: "192.0.2", attrs: { inputmode: "url", autocapitalize: "off", autocorrect: "off", spellcheck: "false" } });
SW.fieldError(addressError, "Enter the printer's whole address, e.g. 192.0.2.42.");
const nameField = SW.field({ label: t("common_field_name"), name: "name", optional: true, hint: "Shown in lists. Empty uses the printer's own name." });
const disabledField = SW.field({ label: "Subnet", name: "subnet", value: "192.0.2.0/24", disabled: true, hint: "Label Reader is switched off. Turn it on in Features.",
  attrs: { autocapitalize: "off", spellcheck: "false" } });
const secret = SW.field({ type: "secret", label: t("common_field_access_code"), name: "access_code", mono: true, hint: t("common_hint_access_code"),
  attrs: { autocapitalize: "off", spellcheck: "false" } });
const keyRow = E("div", "key-row actions", SW.status("set"), E("span", "muted", t("common_saved_hidden")),
  SW.btn(t("common_check")), SW.btn(t("common_replace")), SW.btn(t("common_remove"), { cls: "btn--danger" }));
const days = SW.field({ type: "number", label: "Keep nightly backups for", name: "days", unit: t("unit_days"), hint: "1 to 365. " + t("settings_backups_keep_hint") });
const weight = SW.field({ type: "number", decimal: true, label: t("common_field_net_weight"), name: "net_weight", unit: t("unit_g") });
const service = SW.field({ type: "select", label: "Service", name: "service", options: ["spoolwarden-hub", "spoolman", "weigh-station"].map((v) => ({ value: v, label: v })) });
const location2 = SW.field({ type: "select", label: t("common_field_location"), name: "location", options: [{ value: "", label: t("common_automatic", { name: "Shelf A (PLA rack)" }) }, { value: "b", label: "Shelf B" }] });
const failedSelect = SW.field({ type: "select", label: "Bambu Studio parent", name: "parent", options: [] });
SW.fieldError(failedSelect, t("common_list_load_failed"));
failedSelect.querySelector(".field__error").append(" ", SW.btn(t("common_try_again")));
const search = SW.field({ type: "search", label: t("common_search"), name: "search", placeholder: t("common_search_placeholder"), onSearch: (q) => SW.result(searchResult, "info", q ? `${q.length > 3 ? 0 : 4} spools found` : "") });
const searchResult = resultSlot();
const file = SW.field({ type: "file", label: "Backup zip", name: "restore", accept: ".zip,application/zip" });
const note = SW.field({ type: "textarea", label: "What is wrong?", name: "note", max: 200, placeholder: "e.g. brand is Polymaker",
  hint: "The Label Reader reads the photos again with your note and suggests changes. Nothing changes until you accept." });
const nightly = SW.toggle({ label: "Follow nightly builds", hint: "Nightly builds are untested and unsigned.",
  confirm: (on) => (on ? { title: "Follow nightly builds?", text: "Nightly builds are untested and unsigned.", confirm: "Follow nightly builds" } : null),
  apply: async (on) => { await wait(800); return on ? "On: each new nightly build is installed after the current one." : "Off: signed releases only."; } });
const trusted = SW.toggle({ label: "Trusted computers", checked: true, hint: "Browsers you trust need no code for 90 days.",
  apply: async () => { await wait(800); throw new SW.HubError({ unreachable: true }); } });
const offToggle = SW.toggle({ label: "Print alerts on this phone", disabled: true, hint: "Available on the home network." });
const security = SW.toggle({ heading: "Security", security: true, checked: false, label: "Check the fingerprint when pairing by address",
  hint: "When this is off, the app trusts the certificate a Hub presents when you pair by typing its address. A scanned QR code is always checked.",
  confirm: (on) => (on ? null : { kind: "destructive", title: "Skip the fingerprint check?", text: "Only do this on a network you trust.", confirm: "Skip the check" }),
  apply: async (on) => (on ? "On: the fingerprint is checked." : "Off: the fingerprint is not checked.") });
const laneResult = resultSlot();
const kind = SW.segmented({ legend: "Printer type", name: "kind", wide: true, value: "bambu", options: [{ value: "bambu", label: t("common_bambu_lab") }, { value: "klipper", label: t("common_klipper") }] });
const lane = SW.segmented({ legend: "Lane data", value: "auto", write: true, result: laneResult,
  options: [{ value: "auto", label: "Auto", icon: "refresh" }, { value: "on", label: t("status_on"), icon: "check" }, { value: "off", label: t("status_off"), icon: "close" }],
  apply: async (v) => { await wait(700); if (v === "off") throw new SW.HubError({ message: "Garage Voron did not accept the change. Try again." }); } });
const filter = SW.segmented({ legend: "Show", legendSr: true, value: "all", options: [{ value: "all", label: "All", count: 5 }, { value: "check", label: "To check", count: 2 }, { value: "none", label: "Hidden", disabled: true }] });
section("5 Fields and forms",
  grid(state("Text field, empty", address), state("Error", addressError), state("Optional, with hint", nameField), state("Disabled, reason in the hint", disabledField),
    state("Secret entry (Show and Hide)", secret), state("Saved secret", keyRow), state("Number with unit", days), state("Decimal with unit", weight),
    state("Select", service), state("Select with the automatic choice", location2), state("Select whose options failed", failedSelect),
    state("Search", search, searchResult), state("File", file), state("Text area", note)),
  grid(state("Toggle: confirm first", nightly), state("Toggle: the Hub does not answer", trusted), state("Toggle: disabled", offToggle), state("Toggle that guards security", security)),
  grid(state("Segmented choice in a form", kind), state("Applies at once, with the lock (Off fails)", lane, laneResult), state("Filter with counts, one disabled", filter),
    state("Checkboxes", SW.check({ label: t("common_still_sealed"), name: "sealed", desc: "A sealed spool is stored as full." }),
      SW.check({ label: t("unlock_trust"), name: "trust", checked: true }), SW.check({ label: "Keep the photos", name: "photos", disabled: true, desc: "Available when Recently added keeps photos." }))));

// form groups and the saving model (5.11), with the Settings sub-navigation (6.4)
function group(id, title, desc, fields, send) {
  const form = h("form", { class: "group", id: "set-" + id, "aria-labelledby": "set-" + id + "-title", novalidate: true, "data-group": id },
    E("div", "group__head", ic("settings", "icon--s"), E("div", null, h("h3", { class: "group__title", id: "set-" + id + "-title", tabindex: "-1", text: title }), E("p", "group__desc", desc))),
    E("div", "group__body", fields), E("div", "group__foot", resultSlot(), SW.btn(t("common_save_group", { group: title.toLowerCase() }), { cls: "btn--primary", type: "submit", action: "save" })));
  return { form, g: SW.formGroup(form, { title, send }) };
}
const send = (key, value) => SW.api("settings/general", { body: { key, value } });
const general = group("general", "General", "The Hub's name and how often the Label Reader may read.", [
  SW.field({ label: "Display name", name: "display", value: "Workshop hub", row: true, check: (v) => (v.trim() ? "" : t("common_error_name")) }),
  SW.field({ type: "number", label: "Label reads per day", name: "reads", value: "40", row: true, effect: "restarts", hint: t("field_hint_restarts") })], send);
const storage = group("storage", "Storage locations", "Where spools are put away.", [
  SW.field({ label: "Locations", name: "locations", value: "Shelf A, Shelf B", row: true }),
  SW.field({ type: "number", label: "Number of storage boxes", name: "boxes", value: "4", row: true })], send);
const off = group("reader", "Label Reader", "Reads spool labels from photos.", [
  E("div", "banner banner--warn banner--inline", ic("warning"), E("p", "banner__text", "Label Reader is switched off. Turn it on in Features."), E("div", "actions", h("a", { class: "btn", href: "#features", text: t("common_open_features") }))),
  SW.field({ label: "Model", name: "model", value: "Cloud (Claude)", row: true, disabled: true })], send);
SW.disable(off.form.querySelector("[type=submit]"), "Label Reader is switched off.");
const temps = ["Nozzle", "Bed", "Nozzle low", "Nozzle high", "Bed low", "Bed high", "Chamber"].map((l, i) =>
  SW.field({ type: "number", label: l, name: "t" + i, value: i < 2 ? "x" : "200", unit: t("unit_c"), row: true, check: (v) => (/^\d+$/.test(v) ? "" : t("field_error_range", { min: 0, max: 350 })) }));
const temperatures = group("temperatures", "Temperatures", "Seven fields; two errors show the summary.", temps, send);
const subnav = h("nav", { class: "subnav", "aria-label": t("subnav_label") }, E("ul", "subnav__list",
  [["general", "General"], ["storage", "Storage locations"], ["reader", "Label Reader"], ["temperatures", "Temperatures"]].map(([id, label], i) =>
    h("li", null, h("a", { class: "subnav__link", href: "#settings/" + id, "aria-current": i === 0 ? "true" : null }, label)))));
section("5.11 Form groups and 6.4 sub-navigation (edit a value to see the dirty state; Save asks for the setup code)",
  E("div", "sample-settings", subnav, E("div", null, general.form, storage.form, off.form, temperatures.form)));
temperatures.form.querySelector("[name=t2]").value = "190";
temperatures.form.dispatchEvent(new Event("input"));
temperatures.g.save();
if (document.activeElement) document.activeElement.blur();
window.scrollTo(0, 0);
subnav.addEventListener("click", (e) => {   // moving between groups keeps the page (the shared subnav behaviour is S2.19's)
  const a = e.target.closest(".subnav__link");
  if (!a) return;
  e.preventDefault();
  const g = document.querySelector(`[data-group="${a.hash.split("/").pop()}"]`);
  g.scrollIntoView({ block: "start" });
  g.querySelector(".group__title").focus({ preventScroll: true });
  for (const l of subnav.querySelectorAll(".subnav__link")) l.toggleAttribute("aria-current", l === a);
  a.setAttribute("aria-current", "true");
});
storage.form.addEventListener("sw:dirty", (e) => {
  const link = subnav.querySelector('[href="#settings/storage"]'), mark = link.querySelector(".subnav__dirty");
  if (e.detail && !mark) link.append(SW.status("needs_look", { small: true, cls: "subnav__dirty", text: t("common_unsaved") }));
  if (!e.detail && mark) mark.remove();
});

// ----- 6 Collections and detail -----
const slotsX1 = [
  { label: "A1", hex: "#2B2B2E", name: "Polymaker PolyTerra PLA", colour: "Charcoal Black", level: 0.62, active: true },
  { label: "A2", hex: "#F2762E", name: "Bambu Lab PETG HF", colour: "Orange", level: 0.88 },
  { label: "A3", hex: "#F4F4F2", name: "eSUN ABS+", colour: "White", level: 0.35 },
  { label: "A4", empty: true }];
const slotsVoron = [{ label: "T0", hex: "#8D9199", name: "Prusament PLA", colour: "Galaxy Silver", level: 0.47 }, { label: "T1", hex: "#2E6FD9", name: "Overture TPU", colour: "Blue", level: 0.71 }];
const pct = (v) => `${Math.round(v * 100)} %`;
function compact(slots) {
  return E("div", "slot-strip slot-strip--compact",
    h("span", { class: "slot-strip__swatches", "aria-hidden": "true" }, slots.map((s) => SW.swatch(s.hex, { level: s.level || 0, empty: s.empty }))),
    E("span", "sr", slots.map((s) => (s.empty ? `${s.label} empty` : `${s.label} ${s.name} ${s.colour} ${pct(s.level)}`)).join("; ") + "."),
    h("span", { class: "slot-strip__count mono", "aria-hidden": "true", text: t("slot_count", { loaded: slots.filter((s) => !s.empty).length, total: slots.length }) }));
}
function full(slots, printer, actions) {
  return h("ul", { class: "slot-strip", "aria-label": t("slot_list_label", { name: printer }) }, slots.map((s) => h("li", { class: "slot-strip__row", "data-state": s.active ? "active" : null },
    E("span", "slot-strip__label mono", s.label), SW.swatch(s.hex, { empty: s.empty }),
    E("span", "slot-strip__name", s.empty ? E("span", "muted", t("common_empty")) : s.reading ? [SW.spinner(), t("common_reading")] : [s.name, " ", E("span", "muted", s.colour)]),
    E("span", "slot-strip__level", s.empty || s.reading ? null : [SW.progress({ value: s.level, decorative: true }), E("span", "mono", pct(s.level))]),
    E("span", "slot-strip__use", s.active ? t("slot_in_use") : ""), actions ? E("span", "slot-strip__actions actions", actions(s)) : null)));
}
const kvRows = (rows) => h("dl", { class: "kv" }, rows.map(([key, value, o = {}]) => E("div", "kv__row", E("dt", "kv__key", key),
  E("dd", "kv__value", value == null ? E("span", "muted", t("common_empty")) : E("span", o.mono ? "mono" : null, value), o.badge || null,
    o.copy ? [h("button", { class: "btn btn--ghost btn--icon kv__copy", type: "button", "data-action": "copy", "data-copy": o.copy,
      "aria-label": t("common_copy_named", { name: key.toLowerCase(), value: o.copy }) }, ic("copy")), h("span", { class: "result", role: "status" })] : null))));
function detail(id, name) {
  const menu2 = h("button", { class: "btn btn--icon detail__menu", type: "button", "aria-label": t("common_more_actions_for", { name }) }, ic("more"));
  SW.menu(menu2, [{ label: t("printers_rename_title"), icon: "pencil" }, { separator: true }, { label: t("printers_forget"), icon: "trash", danger: true, run: () => forgetDialog(menu2) }], { label: t("common_actions_for", { name }) });
  return h("section", { class: "detail", id, "aria-labelledby": id + "-title" },
    h("header", { class: "detail__head" }, h("h2", { class: "detail__title", id: id + "-title", tabindex: "-1", text: name }), SW.status("connected"), menu2),
    E("div", "detail__body",
      E("div", "detail__section", E("h3", "detail__heading", "AMS slots"), full(slotsX1, name),
        kvRows([[t("common_address"), "192.0.2.40", { mono: true, copy: "192.0.2.40" }], ["Serial", "00M00A000000001", { mono: true, copy: "00M00A000000001" }],
          [t("common_field_access_code"), t("common_saved_hidden")], ["Price per kg", null, { badge: SW.status("not_on_label", { small: true, cls: "confidence" }) }]])),
      E("div", "detail__section", E("h3", "detail__heading", t("common_actions")), E("div", "actions", SW.btn(t("printers_map_slots"), { cls: "btn--primary", run: (e) => mapDialog(e.currentTarget) })),
        E("h3", "detail__heading", t("common_change")), h("div", { class: "actions actions--list" }, ["Rename", "Change address", "Replace Access Code", "Lane data"].map((l) => SW.btn(l, { cls: "btn--ghost" }))),
        E("div", "detail__remove", E("h3", "detail__heading", t("common_remove")), E("div", "actions", SW.btn(t("printers_forget"), { cls: "btn--danger", run: (e) => forgetDialog(e.currentTarget) }))))));
}
const cols = [["expand", "Details", null, true], ["title", "Printer", 1], ["address", t("common_address"), 2], ["status", "State", 1], ["slots", "Slots", 2], ["connection", "Connection", 3], ["actions", t("common_actions"), 1, true]];
function cell(col, prio, kids, key) {
  return h("div", { class: "coll__cell", role: "cell", "data-col": col, "data-prio": prio }, key ? h("span", { class: "coll__key", "aria-hidden": "true", text: key }) : null, kids);
}
function item(p) {
  const n = cols.length, detailRegion = p.detail ? detail("detail-" + p.id, p.name) : null;
  if (detailRegion) detailRegion.hidden = !p.open;
  const res = h("p", { class: "result result--block", role: "status" });
  const it = h("div", { class: "coll__item", role: "rowgroup", "data-id": p.id, "data-state": p.state },
    h("div", { class: "coll__row", role: "row" },
      cell("expand", null, p.detail ? h("button", { class: "btn btn--ghost btn--icon coll__expand", type: "button", "aria-expanded": String(!!p.open), "aria-controls": "detail-" + p.id,
        "aria-label": t("detail_for", { name: p.name }) }, ic("chevron")) : null),
      cell("title", 1, [h("a", { class: "coll__title", href: "#printers/" + p.id, text: p.name }), E("span", "coll__sub", p.kind)]),
      cell("address", 2, E("span", "mono", p.address), t("common_address")), cell("status", 1, SW.status(p.status)),
      cell("slots", 2, p.slots ? compact(p.slots) : E("span", "muted", "None"), "Slots"), cell("connection", 3, p.connection, "Connection"),
      cell("actions", 1, E("div", "actions", p.actions))),
    h("div", { class: "coll__row coll__row--result", role: "row", hidden: true }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": n }, res)),
    detailRegion ? h("div", { class: "coll__row coll__row--detail", role: "row", hidden: !p.open }, h("div", { class: "coll__cell", role: "cell", "aria-colspan": n }, detailRegion)) : null);
  if (p.result) SW.result(res, ...p.result);
  return it;
}
const testRow = (name) => SW.btn("Test", { name: "Test connection to " + name });
const coll = h("div", { class: "coll coll--printers", role: "table", "aria-label": "Printers" },
  h("div", { class: "coll__head", role: "rowgroup" }, h("div", { class: "coll__row", role: "row" }, cols.map(([col, label, prio, sr]) =>
    h("div", { class: "coll__cell", role: "columnheader", "data-col": col, "data-prio": prio },
      sr ? E("span", "sr", label) : ["title", "address", "status"].includes(col) ? h("button", { class: "coll__sort", type: "button", "data-sort": col }, label, ic("chevron", "icon--s")) : label)))),
  item({ id: "p1", name: "Workshop X1", kind: "Bambu Lab X1 Carbon", address: "192.0.2.40", status: "connected", slots: slotsX1, connection: "Certificate pinned", detail: true, open: true, actions: [testRow("Workshop X1")] }),
  item({ id: "p2", name: "Garage Voron", kind: "Klipper (Voron 2.4)", address: "voron.example:7125", status: "connected", slots: slotsVoron, connection: "API key set", detail: true, actions: [testRow("Garage Voron")] }),
  item({ id: "p3", name: "Study A1 mini", kind: "Bambu Lab A1 mini", address: "192.0.2.41", status: "offline", connection: "Certificate pinned", detail: true,
    actions: [SW.btn(t("printers_collect_report"), { cls: "btn--primary", name: "Collect a report for Study A1 mini" }), testRow("Study A1 mini")],
    result: ["bad", "Test failed: no answer from 192.0.2.41:8883. Check that it is on. The last slot mapping stopped twice; a report would help."] }),
  item({ id: "p4", name: "mainsailos", kind: "Found on the network, not added", address: "192.0.2.57:7125", status: "not_configured", connection: "", state: "off",
    actions: [SW.btn(t("printers_use"), { cls: "btn--primary", name: "Use this printer: mainsailos" }), SW.btn(t("common_dismiss"), { name: "Dismiss mainsailos" })] }));
const collResult = resultSlot();
// page 2 of the pager below: 214 printers in all, 50 before this page (aria-rowcount, aria-rowindex)
SW.collection(coll, { name: "sample-printers", result: collResult, total: 214, first: 50 });
const addRegion = h("section", { class: "detail", id: "add-printer", "aria-labelledby": "add-printer-title", hidden: true },
  h("header", { class: "detail__head" }, h("h2", { class: "detail__title", id: "add-printer-title", tabindex: "-1", text: t("printers_add") }),
    SW.iconBtn("close", t("detail_close", { name: t("printers_add") }), { cls: "detail__close" })),
  h("form", { class: "detail__body", novalidate: true },
    SW.segmented({ legend: "Printer type", wide: true, value: "bambu", options: [{ value: "bambu", label: t("common_bambu_lab") }, { value: "klipper", label: t("common_klipper") }] }),
    SW.field({ label: "IP address or name", name: "address", mono: true, placeholder: "e.g. 192.0.2.42 or printer.local", attrs: { inputmode: "url", autocapitalize: "off", autocorrect: "off", spellcheck: "false" } }),
    SW.field({ type: "secret", label: t("common_field_access_code"), name: "access_code", mono: true, hint: t("common_hint_access_code"), attrs: { autocapitalize: "off", spellcheck: "false" } }),
    SW.field({ label: t("common_field_name"), name: "name", optional: true }),
    SW.field({ label: "Serial number", name: "serial", optional: true, mono: true, attrs: { autocapitalize: "characters", spellcheck: "false" } }),
    E("div", "detail__foot", resultSlot(), SW.btn(t("common_cancel"), { cls: "btn--ghost", run: () => SW.closeDetail(addRegion) }), SW.btn(t("common_add_printer"), { cls: "btn--primary", type: "submit" }))));
addPrinter.addEventListener("click", () => SW.openDetail(addRegion, { opener: addPrinter }));
addRegion.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); SW.result(addRegion.querySelector(".result"), "ok", "Added: Workshop X2."); });
const pagerHost = E("div", null);
const paint = (p) => pagerHost.replaceChildren(SW.pager({ from: (p - 1) * 50 + 1, to: Math.min(p * 50, 214), total: 214, page: p, pages: 5, go: paint }));
paint(2);
const record = kvRows([["Brand", "Polymaker"], [t("common_field_name"), "PolyTerra PLA Charcoal Black"], ["Material", "PLA"],
  ["Colour", "#2B2B2E", { mono: true, badge: SW.status("medium", { small: true, cls: "confidence" }) }], ["Net weight", "1000 g", { mono: true }], ["Price per kg", null, { badge: SW.status("not_on_label", { small: true, cls: "confidence" }) }]]);
section("6 Collections and detail (sort the columns, expand a row, open Add a printer)",
  E("div", "coll__toolbar", SW.field({ type: "search", label: t("common_search"), name: "search", onSearch: () => {} }), collResult),
  coll, addRegion, pagerHost,
  grid(state("Key-value list (hover for Copy)", record),
    state("Grouped", h("div", { class: "kv kv--groups" }, [["Identity", [["Brand", "Polymaker"], ["Material", "PLA"]]], ["Temperatures", [["Nozzle", "210 °C"], ["Bed", "55 °C"]]]].map(([hd, rows]) =>
      E("section", "kv__group", E("h3", "kv__heading", hd), kvRows(rows))))),
    state("Item that cannot be acted on now", E("p", "muted", "mainsailos above is dimmed (data-state=\"off\") with its actions."))));

// ----- 7 Showing data and status -----
const words = ["connected", "offline", "not_configured", "on", "off", "set", "not_set", "ok", "needs_look", "note", "as_detected", "revised_ai", "edited", "running", "done", "failed"];
const svgQr = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 29 29"><rect width="29" height="29" fill="#fff"/><path d="M4 4h7v7H4zM18 4h7v7h-7zM4 18h7v7H4zM14 14h3v3h-3zM20 20h3v3h-3z" fill="#000"/></svg>';
const changes = (items, compactList) => h("ul", { class: "changes__list" + (compactList ? " changes changes--compact" : "") }, items.map(([key, was, now]) => E("li", "changes__item",
  E("span", "changes__key", key), E("span", "changes__old mono", E("span", "sr", t("changes_was")), was), h("span", { "aria-hidden": "true", text: "→" }),
  E("span", "changes__new mono", E("span", "sr", t("changes_becomes")), now))));
const proposalRes = resultSlot(true);
const proposal = h("section", { class: "changes", "aria-labelledby": "prop-title" }, h("h3", { class: "changes__title", id: "prop-title", text: t("changes_title", { count: 2 }) }),
  changes([["Name", "PolyTerra PLA Black", "PolyTerra PLA Charcoal Black"], ["Nozzle range", "190-230 °C", "190-220 °C"]]), E("p", "changes__note", t("changes_note")), proposalRes,
  E("div", "actions", SW.btn(t("common_discard"), { run: () => SW.result(proposalRes, "neutral", t("changes_discarded")) }),
    SW.btn(t("common_accept"), { cls: "btn--primary", run: () => SW.result(proposalRes, "ok", t("changes_accepted", { count: 2, number: 2 })) })));
const revRes = resultSlot();
const revisions = h("section", { class: "revisions", "aria-labelledby": "rev-title" }, h("h3", { class: "revisions__title", id: "rev-title", tabindex: "-1", text: t("revision_heading") }),
  h("ol", { class: "revisions__list", reversed: true },
    E("li", "revisions__item", E("p", null, E("b", null, t("revision_title", { number: 2 })), ", ", E("span", "mono", "2026-11-12 14:09"), ", ", t("revision_by_reader")),
      changes([["Nozzle range", "190-230 °C", "190-220 °C"]], true), E("p", "muted", "note: brand is Polymaker"),
      SW.btn(t("revision_undo", { number: 2 }), { icon: "undo", action: "undo", run: () => SW.result(revRes, "ok", t("revision_undone_result", { number: 2, field: "Nozzle range", value: "190-230 °C" })) })),
    h("li", { class: "revisions__item", "data-state": "undone" }, E("p", null, E("b", null, t("revision_title", { number: 1 })), ", ", E("span", "mono", "2026-11-12 14:06"), ", ", t("revision_by_hand"), " ", t("recent_revision_undone")),
      changes([["Empty spool weight", "150 g", "140 g"]], true))), revRes);
const code = (text, caption, copyName, log, cap = SW.uid("cap")) => h("figure", { class: "code" },
  h("pre", { class: "code__text" + (log ? " code__text--log" : ""), tabindex: "0", "aria-labelledby": caption ? cap : null, "aria-label": caption ? null : t("job_log_label") }, h("code", { text })),
  caption ? E("figcaption", "code__bar", h("span", { class: "code__caption mono", id: cap, text: caption }), h("span", { class: "result", role: "status" }),
    h("button", { class: "btn btn--ghost", type: "button", "data-action": "copy", "aria-label": copyName }, ic("copy", "icon--s"), t("common_copy"))) : null);
const emptyCopy = h("button", { class: "btn btn--ghost", type: "button", "data-action": "copy", "aria-label": "Copy the reader token" }, ic("copy", "icon--s"), t("common_copy"));
const thumbFail = h("button", { class: "thumb", type: "button", "aria-label": t("photo_enlarge", { number: 1, total: 1 }) }, h("img", { class: "thumb__img", src: "missing-photo.jpg", alt: "", width: 44, height: 44 }));
const thumbPhoto = (size, n, total, count) => h("button", { class: "thumb" + (size ? " thumb--" + size : ""), type: "button", "aria-label": t("photo_enlarge", { number: n, total }), "data-action": "photo", "data-photo": String(n - 1) },
  h("img", { class: "thumb__img", src: "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 3"><rect width="4" height="3" fill="#2B2B2E"/></svg>'), alt: "", width: 44, height: 44 }),
  count ? h("span", { class: "thumb__count mono", "aria-hidden": "true", text: String(count) }) : null);
const expired = resultSlot(true);
section("7 Showing data and status",
  state("Status badges (the sixteen words), small, with a count and a prefix", row(...words.map((w) => SW.status(w))), row(...words.slice(0, 8).map((w) => SW.status(w, { small: true }))),
    row(SW.status("connected", { count: 2 }), SW.status("offline", { prefix: true }))),
  grid(state("Confidence marks", row(...["high", "medium", "low", "not_on_label"].map((l) => SW.status(l, { small: true, cls: "confidence" })))),
    state("Confidence summary", E("p", "confidence__summary", SW.status("low", { text: "Low: check" }), " Material, Net weight", " · ", SW.status("medium", { text: "Medium:" }), " Colour"),
      E("p", "confidence__summary", E("span", "muted", t("confidence_not_read")))),
    state("Swatches: small, medium, large, level, empty, no colour", row(SW.swatch("#2B2B2E", { size: "s" }), SW.swatch("#F2762E"), SW.swatch("#F4F4F2", { size: "l" }),
      SW.swatch("#2E6FD9", { level: 0.62 }), SW.swatch(null, { empty: true }), SW.swatch("not-a-colour"), E("span", null, "Charcoal Black ", E("span", "mono muted", "#2B2B2E"))))),
  grid(state("Slot strip, compact", compact(slotsX1)), state("Slot strip, full", full(slotsX1, "Workshop X1")),
    state("Slot strip with Load and Unload (web app); one reading", full([...slotsVoron, { label: "T2", reading: true }], "Garage Voron", (s) => (s.reading ? null : [SW.btn(t("common_load"), { name: `Load ${s.label}` }), SW.btn(t("common_unload"), { name: `Unload ${s.label}` })]))),
    state("Slot strip without data", E("p", "slot-strip__none muted", t("slot_none_offline")))),
  grid(state("Thumbnails: small with a count, medium, none, failed", row(thumbPhoto(null, 1, 2, 2), thumbPhoto("m", 1, 3, 3), h("span", { class: "thumb thumb--none" }, ic("camera", "icon--s"), E("span", "sr", t("photo_none"))), thumbFail)),
    state("Code block with Copy", code("curl -fsSL https://kit.example/install.sh -o install.sh\nsudo sh install.sh --printer 192.0.2.40", "shell · run on the printer", "Copy the install commands")),
    state("Log output", code("2026-11-12 14:05 backup started\n2026-11-12 14:05 copying the Spoolman database\n2026-11-12 14:06 backup written: 14.2 MB", null, "log", true)),
    state("Copy disabled until there is text; loading", h("figure", { class: "code" }, h("p", { class: "result code__wait", role: "status" }, SW.spinner(), t("code_checking_release")),
      E("figcaption", "code__bar", h("span", { class: "code__caption mono", text: "token" }), h("span", { class: "result", role: "status" }), emptyCopy)))),
  grid(state("QR block", E("div", "qr", SW_MEDIA.qrImage(svgQr, t("qr_alt_pair")), E("div", "qr__text", E("p", null, t("qr_scan_or_type")),
    E("p", "qr__code mono", E("span", "sr", t("qr_code_prefix")), "123 456"), E("p", "qr__fingerprint mono", "1111 2222 3333 4444 5555 6666 7777 8888"),
    E("p", null, t("qr_check_groups")), E("p", "qr__expiry", t("qr_expires", { minutes: 9 }))))),
    state("QR block: the Hub draws no QR", E("div", "qr", E("div", "qr__text", E("p", "qr__none", t("qr_unavailable")), E("p", "qr__code mono", "123 456")))),
    state("QR block: expired", E("div", "qr", E("div", "qr__text", expired, SW.btn(t("qr_new_code"), { cls: "btn--primary" }))))),
  grid(state("Before-and-after change list", proposal), state("Revisions with undo", revisions)));
SW.disable(emptyCopy, t("code_nothing"));
SW.result(expired, "warn", t("qr_expired"));

// ----- 8 Progress and feedback -----
const steps = (current, failed) => h("ol", { class: "steps" }, ["Choose a zip", "Upload and check", "Type restore to go on"].map((title, i) => {
  const n = i + 1, st = n < current ? "done" : n > current ? "later" : failed ? "failed" : "current";
  return h("li", { class: "steps__step", "data-state": st, "aria-current": n === current ? "step" : null },
    E("span", "steps__num", n < current ? [ic("check", "icon--s"), E("span", "sr", " " + t("steps_done"))] : st === "failed" ? SW.shape("s-octagon") : String(n)),
    E("div", "steps__body", E("h4", "steps__title", title), n === current ? (failed ? (() => { const r = resultSlot(); SW.result(r, "bad", "This is not a zip file. Choose the backup zip."); return r; })() : h("p", { class: "result", role: "status" }, SW.spinner(), "Uploading and checking…"))
      : n > current ? (() => { const b = SW.btn("Restore"); setTimeout(() => SW.disable(b, t("steps_do_first", { number: current }))); return b; })() : null));
}));
const job = (st, title, line, opts = {}) => h("section", { class: "job", "aria-label": t("job_label"), "data-state": st },
  E("div", "job__head", E("div", "job__text", E("span", "job__badge", SW.status(opts.word || st)), " ", E("span", "job__title", title), E("span", "job__step mono", line)),
    opts.log !== false ? h("button", { class: "btn btn--ghost btn--icon job__toggle", type: "button", "aria-expanded": "false", "aria-controls": "log-" + st, "aria-label": t("job_log_show") }, ic("chevron")) : null,
    SW.iconBtn("close", t(st === "running" ? "job_hide" : "job_close"))),
  opts.lost ? E("p", "job__lost", SW.shape("s-triangle"), t("job_lost_touch")) : null,
  SW.progress({ name: t("job_progress_label", { title }), value: opts.value || 0, indeterminate: opts.indeterminate, failed: st === "failed", valuetext: opts.valuetext }),
  opts.log !== false ? h("pre", { class: "job__log", id: "log-" + st, tabindex: "0", "aria-label": t("job_log_label"), hidden: true }, "==> step 1 of 3 Copying the Spoolman database\n==> step 2 of 3 Collecting the settings and pairings") : null,
  opts.foot ? E("div", "job__foot", opts.foot) : null);
const results = ["run", "ok", "bad", "warn", "info", "neutral"].map((k) => [k, resultSlot(), resultSlot(true)]);
const resultText = { run: "Saving…", ok: "Saved: Display name.", bad: "Test failed: no answer from 192.0.2.41:8883. Check that it is on.", warn: "A job is already running: Backup. Wait for it to finish.", info: "Sorted by Address, A to Z", neutral: t("common_nothing_changed") };
const toastBtns = E("div", "actions", SW.btn("Toast: done", { run: () => SW.toast("Workshop X1 forgotten.") }), SW.btn("Toast: failed", { run: () => SW.toast(t("job_failed_toast", { title: t("job_title_backup") }), "bad") }),
  SW.btn("Toast with an action", { run: () => SW.toast("12 g taken from spool 214.", "ok", { action: { label: t("common_undo"), name: "Undo: put 12 g back on spool 214", run: () => SW.toast("12 g put back on spool 214.") } }) }),
  SW.btn("Announce", { run: () => SW.announce("Unlocked.") }));
const dismissable = SW.banner({ kind: "info", title: "Spoolwarden 0.5.3 is available.", text: "It fixes the slot mapping of the A1 mini.", dismiss: "sample-update", version: "0.5.3",
  actions: [h("a", { class: "btn btn--primary", href: "#updates", text: "Open Updates" })] });
section("8 Progress and feedback",
  grid(state("Inline spinner and alone (reduced motion shows the word)", h("p", { class: "result", role: "status" }, SW.spinner(), "Testing the connection to ", E("span", "mono", "192.0.2.40"), "…"), SW.spinner(true)),
    state("Numbered steps: done, current, later", steps(2)), state("Failed step", steps(2, true)),
    state("Determinate bar, failed, indeterminate", SW.progress({ label: [t("field_file_uploading", { percent: 42 })], value: 0.42 }),
      SW.progress({ label: t("progress_uploading_failed", { percent: 42 }), value: 0.42, failed: true }), SW.progress({ indeterminate: true }), (() => { const r = resultSlot(); SW.result(r, "run", "Mapping… step 2 of 4: reading the slots", { bar: 0.25, barText: t("progress_step", { step: 2, total: 4 }) }); return r; })())),
  grid(state("Job strip: running, counted", job("running", t("job_title_backup"), t("job_step", { step: 2, total: 3, text: "Collecting the settings and pairings" }), { value: 1 / 3, valuetext: t("progress_step", { step: 2, total: 3 }) })),
    state("Job strip: not counted, lost touch", job("running", t("job_title_check"), "Asking for the newest release", { indeterminate: true, lost: true, log: false })),
    state("Job strip: done", job("done", t("job_title_backup"), t("job_done", { title: t("job_title_backup") }), { value: 1, foot: [SW.btn(t("job_show_whole_log")), E("p", "job__note muted", t("job_hidden_note"))] })),
    state("Job strip: failed", job("failed", t("job_title_restore"), t("job_failed_stopped", { title: t("job_title_restore") }), { value: 0.5 })),
    state("The Hub is restarting", job("restarting", t("restart_title"), t("restart_line"), { word: "running", indeterminate: true, log: false })),
    state("Not back after 2 minutes", job("late", t("restart_timeout_title"), t("restart_timeout_line"), { word: "needs_look", indeterminate: true, log: false, foot: [SW.btn(t("restart_reload"))] }))),
  grid(...results.map(([k, plain, block]) => state("Inline result: " + k, plain, block))),
  grid(state("Toasts and the announcer", toastBtns, E("div", "toast", SW.shape("s-filled"), E("span", "toast__text", "Workshop X1 forgotten."))),
    state("Banners", SW.banner({ kind: "bad", title: t("common_offline_title"), text: t("common_banner_unreachable"), actions: [SW.btn(t("common_try_now"))] }),
      SW.banner({ kind: "warn", title: "The backup is not encrypted.", text: "Anyone with the zip can read the setup code." }),
      SW.banner({ kind: "ok", text: "The Hub is back." }), dismissable || E("p", "muted", "The dismissed banner stays away for this version."),
      SW.banner({ kind: "info", inline: true, text: t("form_draft_banner", { time: "10 min ago" }), actions: [SW.btn(t("common_restore_them"), { cls: "btn--primary" }), SW.btn(t("common_discard"))] }))));
for (const [k, plain, block] of results) {
  SW.result(plain, k, resultText[k]);
  SW.result(block, k, resultText[k], k === "bad" ? { action: { label: t("printers_collect_report"), name: "Collect a report for Study A1 mini", run: () => {} } } : {});
}

// ----- 9 Dialogs and sheets -----
function forgetDialog(opener) {
  return SW.ask({ kind: "destructive", title: "Forget Workshop X1?", opener, write: true, busy: "Forgetting…",
    text: "Spoolwarden stops connecting to it and deletes its Access Code. To use it again, add it again.", confirm: t("printers_forget"),
    run: async () => { await SW.api("printers/p1/forget", { method: "POST" }); SW.toast("Workshop X1 forgotten."); } });
}
function mapDialog(opener) {
  return SW.ask({ title: t("printers_map_title", { name: "Workshop X1" }), opener, confirm: t("printers_map_slots"),
    text: "The printer changes its slot colours briefly and runs a job with no motion; the colours are put back." });
}
function renameDialog(opener) {
  return SW.ask({ kind: "entry", title: t("printers_rename_title"), opener, confirm: "Rename", fields: [SW.field({ label: t("common_field_name"), name: "name", value: "Workshop X1", check: (v) => (v.trim() ? "" : t("common_error_name")) })] });
}
const dialogs = E("div", "actions",
  SW.btn("Confirm", { run: (e) => mapDialog(e.currentTarget) }),
  SW.btn("Destructive", { run: (e) => forgetDialog(e.currentTarget) }),
  SW.btn("Typed word", { run: (e) => SW.ask({ kind: "typed", title: t("settings_restore_title"), word: "restore", opener: e.currentTarget, confirm: "Restore",
    text: "Backup of workshop-hub made 2026-11-12 03:00. This replaces the spools, settings, printers and pairings on this Hub. What is here now is saved as a backup first." }) }),
  SW.btn("Text entry", { run: (e) => renameDialog(e.currentTarget) }),
  SW.btn("Text entry, two fields", { run: (e) => SW.ask({ kind: "entry", title: "Change address: Garage Voron", opener: e.currentTarget, confirm: "Change address",
    fields: [SW.field({ label: "IP address or name", name: "address", value: "voron.example", attrs: { inputmode: "url", autocapitalize: "off", autocorrect: "off", spellcheck: "false" } }),
      SW.field({ label: "Port", name: "port", value: "7125", attrs: { inputmode: "numeric", pattern: "[0-9]*" } })] }) }),
  SW.btn("Information", { run: (e) => SW.ask({ kind: "info", title: t("printers_reports_title", { name: "Study A1 mini" }), opener: e.currentTarget, confirm: t("common_close"), body: E("p", "mono", "report-2026-11-12-0915.zip · 212 KiB") }) }),
  SW.btn("Refused by the printer", { run: (e) => SW.ask({ title: "Pause the print?", opener: e.currentTarget, confirm: "Pause", busy: "Pausing…", text: "Pause bracket-v3.3mf on Study A1 mini?",
    run: () => SW.api("printers/p3/pause", { method: "POST" }) }) }),
  SW.btn("Bottom sheet", { run: (e) => SW.openModal(SW.sheet({ title: t("common_actions_for", { name: "Workshop X1" }), body: E("div", "actions actions--list", SW.btn("Rename", { cls: "btn--ghost" }), SW.btn("Change address", { cls: "btn--ghost" })) }), e.currentTarget) }));
section("9 Dialogs and sheets (phones draw every dialog as a bottom sheet)", dialogs);

// ----- 10 Page states -----
section("10 Page states",
  grid(state("Empty: first use", SW.empty({ icon: "printer", title: t("printers_empty_title"), text: "Printers on the network appear here once they announce themselves.", level: 3,
    actions: [SW.btn(t("printers_find")), SW.btn(t("printers_add"), { cls: "btn--primary" })] })),
  state("Empty: feature off", SW.empty({ icon: "presets", title: t("common_feature_off_title", { feature: "Slicer presets" }), text: "Turn it on in Features to build presets for Bambu Studio and Orca Slicer.", level: 3,
    actions: [h("a", { class: "btn btn--primary", href: "#features", text: t("common_open_features") })] })),
  state("Empty: nothing matches", SW.empty({ icon: "search", title: 'No spools match "galaxy"', text: "Check the spelling, or search by brand, material or colour.", level: 3, actions: [SW.btn(t("common_clear_search"))] })),
  state("Empty: all done", SW.empty({ icon: "check", title: "Nothing to check", text: "Every record was read with high confidence.", level: 3, actions: [SW.btn("Show all")] })),
  state("Error state", SW.errorState({ title: "Could not load the printers", level: 3, details: "GET printers\nerror: timeout", onTry: () => wait(1000) }))));

// ----- the loading states (?view=loading) -----
if (loadingView) {
  const region = h("div", { class: "coll" });
  SW.loading(region, { thing: "printers", onTry: () => {} });
  const busyField = SW.field({ label: "Display name", name: "display" });
  busyField._control.setAttribute("aria-busy", "true");
  section("Loading states",
    grid(state("Collection skeleton (slow line at 10 s, error at 30 s)", region), state("Field before its value arrives", busyField),
      state("Badge, swatch and summary skeletons", E("span", "skeleton__line"), E("span", "skeleton__line skeleton__line--title"))));
}

// ----- the shell -----
if (!location.hash) history.replaceState(null, "", "#printers");
SW.shell({ hub: "Workshop hub", home: "printers", titleOf: () => document.querySelector("main h1").textContent });
})();
