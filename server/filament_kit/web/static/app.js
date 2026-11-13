// Spool intake phone app: add spools by hand or (with AI intake) from label photos, link a tapped NFC tag, refresh
// slicer presets.
// Talks only to <base>/api/* on the same origin (session cookie); no data from the server is put into
// innerHTML, everything goes through textContent / element properties.
"use strict";
const BASE = document.body.dataset.base;
const LOCATIONS = JSON.parse(document.body.dataset.locations);
const SEALED = document.body.dataset.sealed;      // the sealed-stock location
const AUTO = document.body.dataset.auto;          // what a blank location means (the placement rules)
const PICKS = JSON.parse(document.body.dataset.picks); // extra places offered when opening a spool
const AI = document.body.dataset.ai === "1";       // a label reader (ai_intake or local_intake) is on: photos can be read
// typical densities (g/cm3), filled in for a spool added by hand while its density is still blank
const DENSITY = { PLA: 1.24, PETG: 1.27, ABS: 1.04, ASA: 1.07, TPU: 1.21, PA: 1.14, PC: 1.2, PCTG: 1.23, PVA: 1.23, HIPS: 1.04 };
// a material with no entry of its own ("PLA+", "PLA Silk", "PETG-CF") takes the longest known one it starts with
function densityFor(material) {
  const m = String(material ?? "").trim().toUpperCase();
  if (!m) return undefined;
  if (m in DENSITY) return DENSITY[m];
  const key = Object.keys(DENSITY).filter((k) => m.startsWith(k)).sort((x, y) => y.length - x.length)[0];
  return key ? DENSITY[key] : undefined;
}
const MAX_EDGE = 1568, QUALITY = 0.85; // Claude reads labels well at this size; keeps uploads ~300 KB per photo
const app = document.getElementById("app");

// The phone's status bar and the home-screen manifest follow the active appearance (F5, 08 13): both theme-color metas
// take the computed --surface, and the manifest link points at the light or dark manifest, at load, whenever the
// appearance attribute changes (a stored or new choice) and whenever the phone's own setting changes.
const darkQuery = matchMedia("(prefers-color-scheme: dark)");
function followAppearance() {
  const root = document.documentElement, chosen = root.getAttribute("data-theme");
  const active = chosen === "light" || chosen === "dark" ? chosen : (darkQuery.matches ? "dark" : "light");
  const surface = getComputedStyle(root).getPropertyValue("--surface").trim();
  if (surface) for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.content = surface;
  const link = document.querySelector('link[rel="manifest"]');
  if (link) link.href = `${BASE}/manifest-${active}.webmanifest`;
}
followAppearance();
darkQuery.addEventListener("change", followAppearance);
new MutationObserver(followAppearance).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-look"] });

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k in el && k !== "list" && k !== "style") el[k] = v;
    else el.setAttribute(k, v);
  }
  // the main button look (CON-9) for a button left without a class (checked after the props: class "" counts as none)
  if (tag === "button" && !el.className) el.className = "btn--primary";
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? "POST" : "GET"), credentials: "same-origin", headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch(BASE + "/api/" + path, init);
  let data;
  try { data = await r.json(); } catch { data = { error: `HTTP ${r.status}` }; }
  if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

const out = (res) => {
  const text = typeof res === "string" ? res : (res.output ?? JSON.stringify(res, null, 1));
  return h("pre", { class: res && res.exit_code ? "err" : "ok", textContent: text });
};
const fail = (e) => h("pre", { class: "err", textContent: e.message || String(e) });
const more = (shown, n) => n > shown ? h("p", { class: "muted", textContent: `Showing ${shown} of ${n}: narrow the search.` }) : null;
const busy = (text) => h("p", {}, h("span", { class: "spin" }), text);
async function run(box, label, fn) {
  box.setAttribute("role", "status");   // a live region: a screen reader hears the spinner text and the result
  box.replaceChildren(busy(label));
  try { const node = await fn(); box.replaceChildren(...[node].flat().filter(Boolean)); }
  catch (e) { box.replaceChildren(fail(e)); }
}

// ---------- History: the intake history (the newest spool additions, their photos, revise, edit, undo) ----------
const HIST_FIELDS = [["vendor", "Brand"], ["name", "Name"], ["material", "Material"], ["color_hex", "Colour (hex)"],
  ["net", "Net g"], ["tare", "Spool g"], ["density", "Density"], ["nozzle", "Nozzle °C"], ["bed", "Bed °C"],
  ["nozzle_range", "Nozzle range"], ["bed_range", "Bed range"], ["price_per_kg", "Price per kg"], ["line", "Line"]];
const HIST_NUM = new Set(["net", "tare", "density", "nozzle", "bed", "price_per_kg"]);
const HIST_STATE = { detected: "as detected", revised_ai: "revised by AI", edited: "edited by hand" };
function historyTab() {
  const box = h("div");
  const el = h("section", { class: "hidden" }, box);
  const hp = (id, what) => `history/${encodeURIComponent(id)}${what ? "/" + what : ""}`;
  function photoImg(id, n) {
    const img = h("img", { src: `${BASE}/api/${hp(id, "photos/" + n)}`, alt: `Photo ${n}`, loading: "lazy", class: "thumb" });
    img.addEventListener("click", () => img.classList.toggle("big"));     // tap to enlarge
    return img;
  }
  async function load() {
    await run(box, "Loading…", async () => {
      const d = await api("history");
      return [h("p", { class: "muted", textContent: `The newest ${d.keep} additions, with their photos. The number is in the setup page's Settings.` }),
        ...(d.records.length ? d.records.map((r) => row(r, d.ai)) : [h("p", { textContent: "Nothing added since the history started." })])];
    });
  }
  function row(r, ai) {
    const det = h("div");
    det.mark = h("span", { textContent: HIST_STATE[r.state] || r.state });   // the state mark, redrawn after a change
    const names = [...new Set(r.spools.map((s) => `${s.vendor} ${s.name}`))].join(", ");
    return h("div", { class: "card" },
      h("div", { class: "row" }, ...(r.photos ? [photoImg(r.id, 1)] : []),
        h("p", {}, h("b", { textContent: names }), ` · ${(r.at || "").slice(0, 16).replace("T", " ")} · `, det.mark)),
      h("button", { class: "secondary", textContent: "Open", on: { click: () => detail(r.id, ai, det) } }), det);
  }
  async function detail(id, ai, det) {
    await run(det, "Loading…", async () => {
      const rec = await api(hp(id));
      const msg = h("div");
      const parts = [];
      if (rec.photos > 1) parts.push(h("div", { class: "row" }, ...Array.from({ length: rec.photos - 1 }, (_, i) => photoImg(id, i + 2))));
      for (const s of rec.saved) {
        const ins = {};
        const fields = HIST_FIELDS.map(([k, label]) => {
          ins[k] = h("input", { value: s.values[k] ?? "", "aria-label": label });
          return h("label", {}, label, ins[k]);
        });
        const note = h("textarea", { rows: 2, placeholder: "e.g. brand is Polymaker", disabled: !ai });
        parts.push(h("div", { class: "card" },
          h("p", { class: "muted", textContent: `Spool ${s.spool_ids.join(", ")}${s.spool_ids.length > 1 ? ": a change applies to all of them" : ""}` }),
          ...fields,
          h("button", { textContent: "Save changes", on: { click: () => save(id, ai, det, msg, s, ins) } }),
          note, h("button", { class: "secondary", textContent: "Ask the AI to correct it", disabled: !ai,
                              on: { click: () => revise(id, ai, det, msg, s, note) } }),
          ai ? null : h("p", { class: "muted", textContent: "Label reading is off on this server: edit by hand." })));
      }
      const live = rec.revisions.filter((v) => !v.undone);
      const last = live[live.length - 1];
      for (const v of rec.revisions) parts.push(h("p", { class: "muted", textContent: `Revision ${v.n} by ${v.by === "ai" ? "the AI" : "hand"}${v.undone ? " (undone)" : ""}: ${[...new Set(v.changes.map((c) => `${c.field} ${c.old} → ${c.new}`))].join("; ")}${v.note ? " · " + v.note : ""}` }));
      if (last) parts.push(h("button", { class: "secondary", textContent: `Undo revision ${last.n}`, on: { click: () => act(id, ai, det, msg, "undo", { revision: last.n }) } }));
      parts.push(msg);
      return parts;
    });
  }
  async function act(id, ai, det, msg, what, body) {
    await run(msg, "Saving…", async () => {
      const r = await api(hp(id, what), { body });
      if (det.mark) det.mark.textContent = HIST_STATE[r.state] || r.state;
      const v = r.revisions[r.revisions.length - 1] || {}, fl = v.filaments || {};
      await detail(id, ai, det);
      det.append(h("pre", { class: "ok", textContent: what === "undo" ? "Undone." : "Saved."
        + (fl.to !== fl.from ? ` The spools now use filament ${fl.to}${fl.created ? " (new)" : ""}.` : "")
        + (fl.orphaned && fl.orphaned.length ? ` Filament ${fl.orphaned.join(", ")} has no spools left; it was not deleted.` : "") }));
      return [];
    });
  }
  function save(id, ai, det, msg, s, ins) {
    const values = {};
    for (const [k] of HIST_FIELDS) {
      const was = s.values[k] == null ? "" : String(s.values[k]), now = ins[k].value.trim();
      if (now !== was) values[k] = now === "" ? null : (HIST_NUM.has(k) ? Number(now) : now);
    }
    if (!Object.keys(values).length) { msg.replaceChildren(h("p", { class: "muted", textContent: "Nothing changed." })); return; }
    act(id, ai, det, msg, "apply", { item: s.item, values });
  }
  async function revise(id, ai, det, msg, s, note) {
    await run(msg, "Asking the AI… (up to a minute)", async () => {
      const p = await api(hp(id, "revise"), { body: { item: s.item, note: note.value } });
      if (!p.changes.length) return [h("p", { textContent: "The AI changed nothing." })];
      return [h("p", { textContent: "The AI suggests:" }),
        ...p.changes.map((k) => h("p", { textContent: `${k}: ${p.before[k]} → ${p.after[k]}` })),
        p.no_photo ? h("p", { class: "muted", textContent: "No photo was kept: it worked from the saved values and your note." }) : null,
        p.reader ? h("p", { class: "muted", textContent: `Read again by ${p.reader === "local" ? "the local reader" : "Claude"}${p.confidence != null ? ", " + Math.round(p.confidence * 100) + " % sure" : ""}${p.note ? " (" + p.note + ")" : ""}.` }) : null,
        h("div", { class: "row" },
          h("button", { textContent: "Accept", on: { click: () => act(id, ai, det, msg, "apply", { proposal: p.proposal }) } }),
          h("button", { class: "secondary", textContent: "Discard", on: { click: () => msg.replaceChildren() } }))];
    });
  }
  return { el, enter: load };
}

// ---------- the shell (04 2 and 9): top bar, bottom bar (a rail on tablets), More, Settings; the places and their addresses ----------
const PRINTERS = document.body.dataset.printers === "1";   // the printers module is on (printers.js is loaded)
const HISTORY = document.body.dataset.history === "1";     // the kit's own page: the intake history is here
const PRESETS = document.body.dataset.presets === "1";     // Slicer presets are on
const PUSH = document.body.dataset.push === "1";           // print alerts can be offered
const HUB = document.body.dataset.hub || "";               // the Hub's name; empty until the Hub reports one
const HUB_PAGE = document.body.dataset.hubPage || "";      // the Hub page's address; absent on the public address
const PRODUCT = SW.t("app_name");
SW.configure({ lock: false, hub: HUB || PRODUCT });          // no lock in the web app: the home network is the gate (04 1.1)

// a destination whose Feature is off, or that this address does not serve, opens a page that says so (04 6.10, 7.4)
const hubLink = () => HUB_PAGE ? h("a", { class: "btn", href: HUB_PAGE }, SW.t("common_open_hub_page")) : null;
const notice = (icon, title, text, link) => ({ el: h("section", { class: "hidden" }, SW.empty({ icon, title, text, actions: link ? hubLink() : null })) });
const settingsPage = h("section", { class: "hidden" });    // Settings as a page, from 601 px (04 2.3)
const tabs = {
  add: addTab(),
  spools: openTab(),
  printers: PRINTERS ? printersTab() : notice("printer", SW.t("common_feature_off_title", { feature: SW.t("nav_printers") }), SW.t("common_feature_off_hint"), true),
  recent: HISTORY ? historyTab() : notice("recent", SW.t("web_recent_public_title"), SW.t("web_recent_public_text", { product: PRODUCT })),
  presets: PRESETS ? presetsTab() : notice("presets", SW.t("presets_off_title"), SW.t("presets_off_text"), true),
  settings: { el: settingsPage, enter: () => settingsPage.replaceChildren(...settingsBody(true)), leave: () => settingsPage.replaceChildren() },
};
const PLACES = ["add", "spools", "printers", "recent", "presets"];    // what `spoolwarden.place` can hold
const TITLES = { add: "web_add_title", spools: "nav_spools", printers: "nav_printers", recent: "nav_recently_added", presets: "nav_slicer_presets", settings: "nav_settings" };
const ALIAS = { open: "spools", history: "recent" };                  // the old addresses, and the old `tab` values
const PLACE_KEY = "spoolwarden.place";

const pageTitle = h("h1", { class: "page-head__title", tabindex: "-1" });
const page = h("section", { class: "page" }, h("header", { class: "page-head" }, h("div", { class: "page-head__text" }, pageTitle)),
  ...Object.values(tabs).map((t) => t.el));
let place = null, shellView = null;                          // the place on show; SW.shell's handle

function storedPlace() {
  let v = null;
  try { v = localStorage.getItem(PLACE_KEY) || localStorage.getItem("tab"); } catch {}   // "tab" is the key before S3.3
  v = ALIAS[v] || v;
  return PLACES.includes(v) ? v : null;
}
function show(key) {
  if (key !== place) {
    for (const [k, t] of Object.entries(tabs)) { t.el.classList.toggle("hidden", k !== key); (k === key ? t.enter : t.leave)?.(); }
    window.scrollTo(0, 0);
  }
  place = key;
  page.dataset.section = key;
  pageTitle.textContent = SW.t(TITLES[key]);
  if (key !== "settings") { try { localStorage.setItem(PLACE_KEY, key); } catch {} }   // #settings is never the stored place (04 2.4)
  paintMore();
}

// ----- addresses (04 2.4): #<place>[/<more>]; #settings is a sheet over the place on phones and a page from 601 px -----
function route(initial) {
  const raw = location.hash.slice(1), head = raw.split(/[/?]/)[0], name = ALIAS[head] || head;
  if (name !== head) history.replaceState(history.state, "", "#" + name + raw.slice(head.length));
  if (name === "settings") {
    if (SW.phone()) {
      if (!place || place === "settings") show(storedPlace() || "add");
      openSettings(initial);
    } else { closeSettings(); show("settings"); }
    return;
  }
  closeSettings();
  if (PLACES.includes(name)) return show(name);
  const keep = storedPlace() || "add";                       // no address, or one the page does not know: the last place
  history.replaceState(history.state, "", "#" + keep);
  show(keep);
}

// ----- sheets: Back closes them (04 2.4). More and the other sheets keep the address and push a same-address entry;
// the Settings sheet is a place of its own, so its entry is the #settings one. -----
const sheets = [];
let settling = 0, settingsRec = null;
function track(dlg, mode, direct) {
  const rec = { dlg, mode, direct, popped: false };
  sheets.push(rec);
  dlg.addEventListener("close", () => {
    sheets.splice(sheets.indexOf(rec), 1);
    if (rec === settingsRec) settingsRec = null;
    paintMore();
    if (rec.popped) return;                                  // Back, or a link, already moved the address
    if (direct) history.replaceState(history.state, "", "#" + place);   // #settings was the first entry: no page of ours to go back to
    else { settling++; history.back(); }
  });
  return rec;
}
function openHere(dlg, opener, reuse) {                      // reuse: the entry of a sheet that just closed
  if (!reuse) history.pushState({ sheet: true }, "", location.href);
  const rec = track(dlg, "same");
  SW.openModal(dlg, opener);
  return rec;
}
window.addEventListener("popstate", () => {
  if (settling) { settling--; return; }
  const top = sheets[sheets.length - 1];
  if (top) { top.popped = true; top.dlg.close(); }
});
function openSettings(direct) {
  if (settingsRec) return;
  const dlg = SW.sheet({ title: SW.t("nav_settings"), body: settingsBody(false) });
  settingsRec = track(dlg, "address", direct);
  SW.openModal(dlg, moreBtn);
  paintMore();
}
function closeSettings() {
  if (!settingsRec) return;
  settingsRec.popped = true;
  settingsRec.dlg.close();
}
// leaving a sheet for an address: the sheet's own history entry becomes that address
function goFrom(rec, hash) {
  rec.popped = true; rec.dlg._noReturn = true;
  history.replaceState(null, "", hash);
  rec.dlg.close();
  route();
  shellView.paint(true);
}

// ----- appearance (02 3.3, F5): the three choices on this device, applied at once and kept by the shared script -----
const APPEARANCE = [["light", "sun"], ["dark", "moon"], ["system", "half-circle"]];
const appearanceNow = () => { const v = document.documentElement.getAttribute("data-theme"); return v === "light" || v === "dark" ? v : "system"; };
const appearanceControl = (o = {}) => SW.segmented({ legend: SW.t("appearance_title"), legendSr: true, cls: "appearance", value: appearanceNow(),
  options: APPEARANCE.map(([value, icon]) => ({ value, icon, label: SW.t("appearance_" + value) })), ...o });
function appearanceButton() {                               // the phone form: an icon button; SW.shell gives it its menu
  const [v, icon] = APPEARANCE.find(([x]) => x === appearanceNow());
  return h("button", { class: "btn btn--ghost btn--icon appearance appearance--menu", type: "button",
    "aria-label": SW.t("appearance_name", { choice: SW.t("appearance_" + v) }) }, SW.icon(icon));
}
window.addEventListener("storage", (e) => {                 // another tab chose: follow it
  if (e.key !== "spoolwarden.appearance" && e.key !== null) return;
  const v = e.key === null ? null : e.newValue;
  SW.setAppearance(v === "light" || v === "dark" ? v : "system");
});

// ----- the Settings sheet or page (04 9.2) -----
const LOOKS = ["console", "workbench", "palette", "panes"];
const installed = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
let installPrompt = null;                                    // a browser that offers installing (04 10.1)
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; });
function themePicker() {
  const now = document.documentElement.getAttribute("data-look");
  const fs = h("fieldset", { class: "theme-picker" }, h("legend", { class: "sr" }, SW.t("appearance_theme_title")));
  for (const look of LOOKS) {
    const line = SW.uid("look");
    fs.append(h("label", { class: "theme-picker__tile" },
      h("input", { class: "theme-picker__input", type: "radio", name: "look", value: look, checked: look === (LOOKS.includes(now) ? now : "console"), "aria-describedby": line }),
      h("span", { class: "theme-picker__preview", "data-preview": look, "aria-hidden": "true" },
        h("span", { class: "theme-picker__bar" }), h("span", { class: "theme-picker__nav" }), h("span", { class: "theme-picker__rows" })),
      h("span", { class: "theme-picker__name" }, SW.t(`theme_${look}_name`)),
      h("span", { class: "theme-picker__line", id: line }, SW.t(`theme_${look}_line`)),
      SW.icon("check", "icon--s theme-picker__check")));
  }
  return fs;
}
// wide: Settings as a page, which also holds "Add to Home Screen" (the More sheet is not there)
function settingsBody(wide) {
  const group = (title, ...kids) => h("section", { class: "settings__group" }, h("h2", { class: "settings__title" }, title), ...kids);
  const live = () => h("p", { class: "result", role: "status" });   // the choice's own sentence goes here (shared script)
  const hubPageLink = () => HUB_PAGE ? h("a", { class: "btn", href: HUB_PAGE }, SW.t("common_open_hub_page")) : null;
  return [h("div", { class: "settings" },
    group(SW.t("appearance_title"), appearanceControl({ wide: true, name: null }), h("p", { class: "muted" }, SW.t("web_settings_saved")), live()),
    group(SW.t("appearance_theme_title"), themePicker(), h("p", { class: "muted" }, SW.t("web_settings_theme_help")), live()),
    PUSH && typeof alertsPanel === "function" ? group(SW.t("web_settings_alerts_title"), alertsPanel(() => installSheet())) : null,
    group(SW.t("web_settings_this_hub"), HUB ? h("p", { class: "settings__hub" }, HUB) : null,
      h("p", { class: "settings__address" }, location.origin + location.pathname), hubPageLink()),
    wide && !installed() ? group(SW.t("web_more_home_screen"), h("p", { class: "muted" }, SW.t("web_more_home_screen_summary", { product: PRODUCT })),
      h("p", {}, h("button", { class: "btn", type: "button", on: { click: (e) => addToHome(e.currentTarget) } }, installPrompt ? SW.t("web_more_install") : SW.t("web_more_home_screen")))) : null)];
}
function addToHome(opener) {
  if (installPrompt) { installPrompt.prompt(); installPrompt = null; } else installSheet(opener);
}
function installSheet(opener, reuse) {                       // the steps for an iPhone (04 10.1)
  const dlg = SW.sheet({ title: SW.t("web_install_title", { product: PRODUCT }),
    body: [h("ol", { class: "install" }, [1, 2, 3].map((n) => h("li", {}, SW.t("web_install_step_" + n)))),
      SW.banner({ kind: "info", text: SW.t("web_install_note"), inline: true })],
    foot: SW.btn(SW.t("common_done"), { cls: "btn--primary", action: "done", run: () => dlg.close() }) });
  openHere(dlg, opener, reuse);
}

// ----- More (04 9.1): Slicer presets, Settings, Add to Home Screen, Open the Hub page -----
const moreBtn = h("button", { class: "nav__more", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false" },
  SW.icon("more", "nav__icon"), h("span", { class: "nav__label" }, SW.t("nav_more")), h("span", { class: "sr nav__more-current" }));
function moreRow(icon, name, summary, props, run) {
  return h(props.href ? "a" : "button", { class: "more__row", ...(props.href ? {} : { type: "button" }), ...props, on: run ? { click: run } : undefined },
    SW.icon(icon, "more__icon"), h("span", { class: "more__name" }, name), summary ? h("span", { class: "more__summary" }, summary) : null,
    SW.icon("chevron", "icon--s more__chevron"));
}
moreBtn.addEventListener("click", () => {
  const cur = (k) => (place === k ? "page" : undefined);
  const standalone = installed();
  let rec = null;
  const to = (hash) => (e) => { e.preventDefault(); goFrom(rec, hash); };
  const rows = [
    moreRow("presets", SW.t("nav_slicer_presets"), "", { href: "#presets", "aria-current": cur("presets"),
      ...(PRESETS ? {} : { "data-state": "off", "aria-label": SW.t("nav_slicer_presets") + SW.t("nav_off_suffix") }) }, to("#presets")),
    moreRow("settings", SW.t("nav_settings"), SW.t("web_more_presets_summary"), { href: "#settings" }, to("#settings")),
    standalone ? null : moreRow("plus", SW.t(installPrompt ? "web_more_install" : "web_more_home_screen"), SW.t("web_more_home_screen_summary", { product: PRODUCT }), {},
      () => { rec.popped = true; rec.dlg._noReturn = true; rec.dlg.close(); if (installPrompt) { installPrompt.prompt(); installPrompt = null; settling++; history.back(); } else installSheet(moreBtn, true); }),
    HUB_PAGE ? moreRow("overview", SW.t("common_open_hub_page"), SW.t("web_more_hub_page_summary"),
      { href: HUB_PAGE, ...(standalone ? { target: "_blank", rel: "noopener" } : {}) }) : null,
  ];
  const dlg = SW.sheet({ title: SW.t("nav_more"), bodyTag: "nav", bodyLabel: SW.t("nav_more_sections"), body: h("div", { class: "more" }, rows),
    onClose: () => moreBtn.setAttribute("aria-expanded", "false") });
  rec = openHere(dlg, moreBtn);
  moreBtn.setAttribute("aria-expanded", "true");
  const first = dlg.querySelector(".more__row");
  if (first) first.focus();
});
function paintMore() {                                       // More is current while Slicer presets or the Settings sheet is
  const key = settingsRec ? "settings" : place === "presets" ? "presets" : null, name = key ? SW.t(TITLES[key]) : "";
  moreBtn.querySelector(".nav__more-current").textContent = key ? ", " + name : "";
  if (key) { moreBtn.dataset.state = "current"; moreBtn.setAttribute("aria-label", SW.t("nav_more_current", { section: name })); }
  else { delete moreBtn.dataset.state; moreBtn.removeAttribute("aria-label"); }
}

// ----- the frame: skip link, top bar, navigation, the page -----
function topBar() {
  const hub = HUB ? h("span", { class: "topbar__hub" }, h("span", { "aria-hidden": "true" }, "/"), " ", HUB) : null;
  return h("header", { class: "topbar" },
    h("div", { class: "topbar__brand" }, SW.h("svg", { class: "topbar__mark", "aria-hidden": "true", focusable: "false" }, SW.h("use", { href: "#i-spoolwarden" })),
      h("span", { class: "topbar__name" }, PRODUCT), " ", hub),
    h("div", { class: "topbar__tools" }, appearanceControl({ name: "appearance" }), appearanceButton()));
}
function navItem([key, name, icon], tab) {
  const label = key === "recent"                             // the bar shows the short name; the full one is read (02 2.4)
    ? h("span", { class: "nav__label" }, h("span", { class: "nav__label-full" }, SW.t("nav_recently_added")), h("span", { class: "nav__label-short", "aria-hidden": "true" }, SW.t("nav_recent")))
    : h("span", { class: "nav__label" }, SW.t(name));
  const a = h("a", { class: "nav__item", href: "#" + key }, SW.icon(icon, "nav__icon"), label);
  if (tab) a.setAttribute("data-tab", "");
  const off = key === "printers" && !PRINTERS ? SW.t("nav_printers_off") : key === "recent" && !HISTORY ? SW.t("nav_recent_public")
    : key === "presets" && !PRESETS ? SW.t("nav_slicer_presets") + SW.t("nav_off_suffix") : null;
  if (off) { a.dataset.state = "off"; a.setAttribute("aria-label", off); }   // dimmed, and the name says why (04 2.1)
  return h("li", {}, a);
}
function navigation() {
  const main = [["add", "nav_add", "plus"], ["spools", "nav_spools", "spool"], ["printers", "nav_printers", "printer"], ["recent", "nav_recent", "recent"]];
  const rest = [["presets", "nav_slicer_presets", "presets"], ["settings", "nav_settings", "settings"]];   // in More on phones
  return h("nav", { class: "nav", "aria-label": SW.t("nav_label") },
    h("h2", { class: "nav__heading", id: "nav-main" }, SW.t("nav_everyday")), h("ul", { class: "nav__group", "aria-labelledby": "nav-main" }, main.map((i) => navItem(i, true))),
    h("h2", { class: "nav__heading", id: "nav-rest" }, SW.t("nav_more")), h("ul", { class: "nav__group", "aria-labelledby": "nav-rest" }, rest.map((i) => navItem(i, false))));
}
{
  const skip = h("a", { class: "skip", href: "#main" }, SW.t("shell_skip"));
  const main = h("main", { class: "shell__main", id: "main", tabindex: "-1" }, page);
  skip.addEventListener("click", (e) => { e.preventDefault(); main.focus(); });   // the address keeps the place
  const nav = navigation();
  app.replaceWith(skip, h("div", { class: "shell" }, topBar(), nav, main),
    h("div", { class: "toasts", "aria-live": "polite" }), h("div", { class: "sr", id: "announcer", "aria-live": "polite" }));
  route(true);
  shellView = SW.shell({ hub: HUB || PRODUCT, home: "add", titleOf: (s) => SW.t(TITLES[ALIAS[s] || s] || TITLES[place]), onSection: () => route() });
  nav.append(moreBtn);                                       // after SW.shell: this More has its own sheet
  paintMore();
  matchMedia("(max-width: 600px)").addEventListener("change", () => route());   // Settings: a sheet or a page
}

// ---------- Add spools ----------
function addTab() {
  let readId = null;
  const photos = []; // {blob, url}
  let items = [], checked = false, tag = null; // tag: unlinked tag tapped just before the photos (server links it)
  const thumbs = h("div", { class: "thumbs" });
  const hint = h("textarea", { placeholder: "Optional note for the label reader, e.g. \"3 of the grey ones\" or \"all the PETG is white\"" });
  const picker = h("input", { type: "file", accept: "image/*", multiple: true, on: { change: addFiles } });
  const readBtn = h("button", { textContent: "Read labels", disabled: true, on: { click: read } });
  const readBox = h("div");
  const itemsBox = h("div");
  const actBox = h("div");
  // ---- by hand: pick an existing filament, or start a new one ----
  const fq = h("input", { type: "search", placeholder: "Existing filament: brand, colour, material", "aria-label": "Search existing filaments", enterKeyHint: "search",
                          on: { keydown: (e) => { if (e.key === "Enter") findFilaments(); } } });
  const filBox = h("div", { class: "list" });
  const vendorList = h("datalist", { id: "vendors" });
  let vendorTare = new Map(); // vendor name (lower case) -> empty spool weight
  const byHand = h("div", { class: "card" },
    h("h3", { textContent: "Add by hand" }),
    h("p", { class: "muted", textContent: "Pick a filament you already have, or start a new one; fill in the spool and check before saving." }),
    h("div", { class: "row" }, fq, h("button", { class: "fit", textContent: "Search", on: { click: findFilaments } })),
    filBox,
    h("p", {}, h("button", { class: "secondary", textContent: "New filament (type it in)", on: { click: () => addItem(blankItem()) } })),
    vendorList);
  const photoPart = AI ? [
    h("h2", { textContent: "From label photos" }),
    h("p", { class: "muted", textContent: "Photograph each label (several photos of one spool are fine). The label reader (Claude or a local one) reads them; you check and edit before anything is saved." }),
    h("label", { class: "filebtn wide" }, h("button", { textContent: "Take or choose photos", tabIndex: -1 }), picker),
    thumbs, hint, h("p", {}, readBtn), readBox] : [];
  const el = h("section", {},
    byHand, ...photoPart, itemsBox, actBox);
  api("vendors").then((res) => {
    vendorTare = new Map(res.vendors.map((v) => [v.name.toLowerCase(), v.tare]));
    vendorList.replaceChildren(...res.vendors.map((v) => h("option", { value: v.name })));
  }).catch(() => {}); // no list: the vendor is typed in

  function blankItem() {
    return { vendor: "", name: "", material: "", count: 1, net: 1000, tare: null, density: null, color_hex: "",
             sealed: true, location: SEALED, price_per_kg: "", photos: [], estimates: [], match: "new filament", hand: true };
  }
  function addItem(it) {
    items.push(it); drawItems(); dirty();
    itemsBox.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function findFilaments() {
    await run(filBox, "Searching…", async () => {
      const res = await api(`filaments?q=${encodeURIComponent(fq.value)}`);
      if (!res.filaments.length) return h("p", { class: "muted", textContent: "No filament matches: use New filament." });
      return [...res.filaments.slice(0, 60).map((f) => h("button", {
        class: "pick", on: { click: () => addItem({ ...blankItem(), vendor: f.vendor, name: f.name, material: f.material || "",
          net: f.net ?? 1000, tare: f.tare, density: f.density, color_hex: f.color_hex || "", nozzle: f.nozzle, bed: f.bed,
          existing_filament_id: f.id, match: "existing filament" }) } },
        h("strong", { textContent: `F${f.id} ` }), `${f.vendor || "(no vendor)"} ${f.name}`,
        h("div", { class: "muted", textContent: `${f.material || "?"} · ${f.net ?? "?"} g · ${f.spools} spool${f.spools === 1 ? "" : "s"}` }))),
        more(60, res.filaments.length)];
    });
  }

  async function shrink(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = url; await img.decode();
      const s = Math.min(1, MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      return await new Promise((ok) => c.toBlob(ok, "image/jpeg", QUALITY));
    } finally { URL.revokeObjectURL(url); }
  }
  async function addFiles() {
    const files = [...picker.files]; picker.value = "";
    for (const f of files) {
      if (photos.length >= 8) { readBox.replaceChildren(fail(new Error("8 photos at a time"))); break; }
      try { const blob = await shrink(f); photos.push({ blob, url: URL.createObjectURL(blob) }); }
      catch (e) { readBox.replaceChildren(fail(new Error(`${f.name}: can't read this image`))); }
    }
    drawThumbs();
  }
  function drawThumbs() {
    thumbs.replaceChildren(...photos.map((p, i) => h("figure", {}, h("img", { src: p.url, alt: `photo ${i + 1}` }),
      h("figcaption", { textContent: i + 1 }),
      h("button", { textContent: "✕", "aria-label": "remove photo", on: { click: () => { URL.revokeObjectURL(p.url); photos.splice(i, 1); drawThumbs(); } } }))));
    readBtn.disabled = !photos.length;
  }
  async function read() {
    const fd = new FormData();
    photos.forEach((p, i) => fd.append("photos", p.blob, `photo${i}.jpg`));
    fd.append("hint", hint.value);
    readBtn.disabled = true; actBox.replaceChildren();
    await run(readBox, `Claude is reading ${photos.length} photo${photos.length > 1 ? "s" : ""}… (up to a minute)`, async () => {
      const res = await api("read", { body: fd });
      tag = res.tag;
      readId = res.read_id || null;                      // the intake history keeps this read's photos with the save
      const got = res.items.map((it) => ({ price_per_kg: "", ...it, location: it.sealed ? SEALED : "" }));
      items = [...items.filter((it) => it.hand), ...got]; // a new read replaces the last read, not spools added by hand
      checked = false; drawItems();
      const filled = got.length === 1 && got[0].gross != null;
      return [res.tag ? h("p", { class: "muted", textContent: `New tag ${res.tag.nfc_id} was tapped on the ${res.tag.reader} reader ${res.tag.age_seconds} s before the photos, so this spool counts as opened; Add links the tag to it (one opened spool only).` }) : null,
        res.scale ? h("p", { class: "muted", textContent: `Station scale: ${res.scale.grams} g, ${res.scale.age_seconds} s ago${filled ? " (filled in as the scale weight)" : " (not used: only for one opened spool)"}.` }) : null,
        res.questions.length ? h("div", { class: "card" }, h("h3", { textContent: res.reader === "local" ? "The local reader asks" : "Claude asks" }),
        ...res.questions.map((q) => h("p", { textContent: "• " + q }))) : null,
        res.note ? h("p", { class: "muted", textContent: "Note: " + res.note }) : null,
        h("p", { class: "muted", textContent: `${got.length} product${got.length === 1 ? "" : "s"} found · ${readerText(res)}` })];
    });
    readBtn.disabled = !photos.length;
  }
  function pct(c) { return Math.round(c * 100) + " %"; }
  function readerText(res) { // which reader answered, and how sure it was
    if (res.reader === "local") {
      return `read by the local reader (${res.tier || "?"} tier${res.escalated ? ", after the CPU tier" : ""})` +
        (res.confidence != null ? `, ${pct(res.confidence)} sure${res.unsure ? " (unsure: check the fields)" : ""}` : "") +
        (res.usage && res.usage.ms != null ? ` · ${(res.usage.ms / 1000).toFixed(1)} s` : "");
    }
    return `read by Claude · ${res.usage.model}, ${res.usage.input_tokens} in (${res.usage.cached} cached) / ${res.usage.output_tokens} out tokens`;
  }
  function colourText(it) { // the local reader's colour name and family, and its least sure fields
    const parts = [];
    if (it.color_name || it.color_family) {
      const name = it.color_name && it.color_name !== "unknown" ? it.color_name : "colour name not in the library";
      parts.push("colour: " + name + (it.color_family ? ` (${it.color_family})` : ""));
    }
    if (it.confidence != null) parts.push(pct(it.confidence) + " sure");
    const low = Object.entries(it.field_confidence || {}).filter(([, c]) => c < 0.78).map(([k]) => k);
    if (low.length) parts.push("least sure: " + low.join(", "));
    return parts.join(" · ");
  }
  function field(it, key, label, type = "text", extra = {}, ins = {}) {
    const inp = h("input", {
      type, value: it[key] ?? "", inputMode: type === "number" ? "decimal" : undefined, step: "any",
      list: key === "vendor" ? "vendors" : undefined,
      on: { input: (e) => { it[key] = type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value;
                            if (key === "color_hex") swatchFor(it);
                            if (key === "material") fillBlank(it, "density", densityFor(it.material), ins);
                            if (key === "vendor") fillBlank(it, "tare", vendorTare.get(it.vendor.trim().toLowerCase()), ins);
                            dirty(); } } });
    ins[key] = inp;
    return h("label", extra, label, inp);
  }
  function fillBlank(it, key, value, ins) { // a known default for a field the user left blank
    if (value == null || (it[key] != null && it[key] !== "")) return;
    it[key] = value; if (ins[key]) ins[key].value = value;
  }
  const swatches = new Map();
  function swatchFor(it) { const s = swatches.get(it); if (s) s.style.background = /^[0-9a-f]{6}$/i.test(it.color_hex || "") ? "#" + it.color_hex : "transparent"; }
  function drawItems() {
    swatches.clear();
    itemsBox.replaceChildren(...items.map((it, idx) => {
      const ins = {}; // this card's inputs by field, for filled-in defaults
      const f = (key, label, type, extra) => field(it, key, label, type, extra, ins);
      const sw = h("span", { class: "swatch" }); swatches.set(it, sw); swatchFor(it);
      const loc = h("select", { on: { change: (e) => { it.location = e.target.value; dirty(); } } },
        h("option", { value: "", textContent: "Auto: " + AUTO, selected: !it.location }),
        ...LOCATIONS.map((l) => h("option", { value: l, textContent: l, selected: l === it.location })));
      const sealed = h("input", { type: "checkbox", checked: it.sealed, on: { change: (e) => {
        it.sealed = e.target.checked;
        if (it.location === (it.sealed ? "" : SEALED)) { it.location = it.sealed ? SEALED : ""; loc.value = it.location; }
        dirty(); } } });
      return h("div", { class: "card" },
        h("h3", {}, sw, h("span", { textContent: `${it.vendor} ${it.name}`.trim() || "New spool" }),
          h("span", { class: "badge " + (it.existing_filament_id ? "ok" : "new"), textContent: it.match })),
        it.photos.length ? h("p", { class: "muted", textContent: `photos ${it.photos.map((n) => n + 1).join(", ")}${it.estimates.length ? " · estimated: " + it.estimates.join(", ") : ""}` }) : null,
        colourText(it) ? h("p", { class: "muted", textContent: colourText(it) }) : null,
        h("p", { class: "muted", textContent: it.price_line ? it.price_line.replace(/^Price: /, "") : "no price" }),
        h("div", { class: "grid" },
          f("vendor", "Vendor"), f("material", "Material"),
          f("name", "Name (with the colour)", "text", { class: "wide" }),
          f("count", "Spools", "number"), f("net", "Net g", "number"),
          f("tare", "Empty spool g", "number"), f("density", "Density", "number"),
          f("color_hex", "Colour hex"), f("lot", "Lot"),
          f("nozzle", "Nozzle °C", "number"), f("bed", "Bed °C", "number"),
          f("gross", "Opened: scale weight g (with spool, blank = full)", "number", { class: "wide" }),
          h("label", { class: "check wide" }, sealed, "Still sealed (in its bag or box)",
            it.sealed_reason ? h("span", { class: "muted", textContent: ` · ${it.sealed_reason}` }) : null),
          f("price_per_kg", "Price $/kg", "number"), h("label", {}, "Location", loc),
          f("note", "Note", "text", { class: "wide" })),
        h("p", {}, h("button", { class: "secondary", textContent: "Remove", on: { click: () => { items.splice(idx, 1); drawItems(); dirty(); } } })));
    }));
    drawActions();
  }
  function dirty() { if (checked) { checked = false; drawActions(); } }
  const total = () => items.reduce((n, it) => n + (Number(it.count) || 0), 0);
  function drawActions(result) {
    if (!items.length) { actBox.replaceChildren(); return; }
    const check = h("button", { class: checked ? "secondary" : "", textContent: "Check (dry run)", on: { click: () => submit(true) } });
    const add = h("button", { textContent: `Add ${total()} spool${total() === 1 ? "" : "s"}`, disabled: !checked, on: { click: () => submit(false) } });
    actBox.replaceChildren(h("div", { class: "row" }, check, add), result || h("p", { class: "muted", textContent: "Check first; any edit needs a new check." }));
  }
  async function submit(dry) {
    const box = h("div"); actBox.replaceChildren(box);
    await run(box, dry ? "Checking…" : "Adding to Spoolman…", async () => {
      const res = await api("add", { body: { items, dry_run: dry, link_tag: tag ? tag.nfc_id : null, read_id: readId } });
      checked = dry && !res.exit_code;
      if (!dry && !res.exit_code) {
        items = []; tag = null; readId = null; itemsBox.replaceChildren(); filBox.replaceChildren(); photos.splice(0).forEach((p) => URL.revokeObjectURL(p.url)); drawThumbs();
        return [out(res), h("p", {}, h("button", { textContent: "Next: presets for new filaments", on: { click: () => { location.hash = "#presets"; } } }))];
      }
      drawActions(out(res));
      return null;
    });
  }
  return { el };
}

// ---------- Open spool ----------
function openTab() {
  let timer = null, picked = null, lastKey = null;
  const tagBox = h("div", { class: "card" }, busy("Reading the tag reader…"));
  const q = h("input", { type: "search", placeholder: "Search: brand, colour, material", "aria-label": "Search spools", enterKeyHint: "search",
                         on: { keydown: (e) => { if (e.key === "Enter") find(); } } });
  const sealed = h("input", { type: "checkbox", checked: true });
  const results = h("div", { class: "list" });
  const gross = h("input", { type: "number", inputMode: "decimal", step: "any", placeholder: "scale reading, g (optional)" });
  const loc = h("input", { placeholder: "blank = " + AUTO, list: "locs" });
  const hum = h("input", { type: "number", inputMode: "decimal", step: "any", placeholder: "box hygrometer % (optional)" });
  const actBox = h("div");
  const linkBtn = h("button", { textContent: "Link tag and open", disabled: true, on: { click: () => submit(false) } });
  const form = h("div", { class: "card hidden" }, h("h3", { textContent: "Selected spool" }), h("p", { class: "picked" }),
    h("div", { class: "grid" }, h("label", { class: "wide" }, "Gross weight (with spool)", gross),
      h("label", { class: "wide" }, "Location", loc), h("label", { class: "wide" }, "Humidity", hum)),
    h("div", { class: "row spaced" }, h("button", { class: "secondary", textContent: "Check", on: { click: () => submit(true) } }), linkBtn),
    actBox);
  for (const inp of [gross, loc, hum]) inp.addEventListener("input", () => { linkBtn.disabled = true; });
  const el = h("section", { class: "hidden" },
    h("p", { class: "muted", textContent: "Tap the spool's tag on a reader, pick the spool, weigh it (the station scale fills it in), link." }),
    tagBox, h("datalist", { id: "locs" }, ...[...new Set([...PICKS, ...LOCATIONS])].map((l) => h("option", { value: l }))),
    h("h2", { textContent: "Which spool?" }), h("div", { class: "row" }, q, h("button", { class: "fit", textContent: "Search", on: { click: find } })),
    h("label", { class: "check" }, sealed, "sealed spools only"),
    results, form);

  async function poll() {
    try {
      const t = await api("tag");
      const key = `${t.nfc_id}|${t.read_at}`;
      if (key !== lastKey) {
        lastKey = key; linkBtn.disabled = true;
        if (t.reader === "station" && t.scale) gross.value = t.scale.grams; // a new station tap: that spool is on the scale
        tagBox.replaceChildren(h("h3", { textContent: t.nfc_id ? "Last tag: " + t.nfc_id : "No tag read yet: tap one" }),
          h("pre", { textContent: t.text }));
      }
      tagBox.querySelector(".age")?.remove();
      if (t.age_seconds != null) tagBox.append(h("p", { class: "muted age", textContent: `tapped ${ago(t.age_seconds)} on the ${t.reader} reader${t.scale ? ` · station scale ${t.scale.grams} g` : ""}` }));
    } catch (e) { tagBox.replaceChildren(fail(e)); }
  }
  const ago = (s) => s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
  async function find() {
    await run(results, "Searching…", async () => {
      const res = await api(`find?q=${encodeURIComponent(q.value)}&sealed=${sealed.checked ? 1 : 0}`);
      const rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ f, s })));
      if (!rows.length) return h("p", { class: "muted", textContent: "No spools match." });
      return [...rows.slice(0, 60).map(({ f, s }) => h("button", {
        class: "pick", on: { click: (e) => pick(e.currentTarget, f, s) } },
        h("strong", { textContent: `S${s.spool_id} ` }), `${f.vendor} ${f.name}`,
        h("div", { class: "muted", textContent: `${s.location || "?"} · ${s.remaining_g} g${s.sealed ? " · sealed" : ""}${s.tagged ? " · has a tag" : ""}${s.lot ? " · lot " + s.lot : ""}` }))),
        more(60, rows.length)];
    });
  }
  function pick(btn, f, s) {
    for (const b of results.querySelectorAll(".pick")) b.classList.toggle("on", b === btn);
    picked = s.spool_id; linkBtn.disabled = true; actBox.replaceChildren();
    form.querySelector(".picked").textContent = `S${s.spool_id} ${f.vendor} ${f.name} (${s.location}, ${s.remaining_g} g)`;
    form.classList.remove("hidden"); form.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function submit(dry) {
    if (picked == null) return;
    await run(actBox, dry ? "Checking…" : "Linking…", async () => {
      const res = await api("open", { body: { spool: picked, gross: gross.value, location: loc.value, humidity: hum.value, dry_run: dry } });
      linkBtn.disabled = !(dry && !res.exit_code);
      if (!dry && !res.exit_code) { picked = null; gross.value = hum.value = loc.value = ""; lastKey = null; }
      return out(res);
    });
  }
  return { el, enter() { poll(); timer = setInterval(() => { if (!document.hidden) poll(); }, 3000); },   // not while the page is hidden or the phone locked
    leave() { clearInterval(timer); timer = null; } };
}

// ---------- Presets ----------
function presetsTab() {
  const box = h("div");
  const genBox = h("div");
  const upBox = h("div");      // presets in the slicers that a newer build would change: shown, then accepted
  const el = h("section", { class: "hidden" },
    h("p", { class: "muted", textContent: "New filaments need a preset line before a build covers them. The desktop installs a build by itself the next time the slicers are closed." }),
    box, h("p", {}, h("button", { textContent: "Build presets now", on: { click: build } })), genBox, upBox);

  async function load() {
    await run(box, "Loading…", async () => {
      const st = await api("presets");
      const info = h("p", { class: "muted", textContent: `Last build ${st.last_build || "-"} · installed ${st.installed_build || "-"}${st.waiting_for_desktop ? " · waiting for the desktop" : ""} · ${st.lines} lines` });
      if (!st.uncovered_filaments.length) return [info, h("p", { textContent: "Every filament has a preset line." })];
      return [info, h("h2", { textContent: "Filaments without a preset line" }), ...st.uncovered_filaments.map(lineCard)];
    });
  }
  function lineCard(f) {
    const res = h("div");
    const card = h("div", { class: "card" }, h("h3", { textContent: `F${f.id} ${f.vendor} ${f.name}` }),
      h("p", { class: "muted", textContent: f.material || "" }));
    if (f.lines_for_vendor.length) {
      const sel = h("select", {}, ...f.lines_for_vendor.map((l) => h("option", { value: l, textContent: l })));
      card.append(h("label", {}, "Add to the line", sel), h("p", {}, h("button", { textContent: "Add to line", on: { click: () =>
        run(res, "Adding…", async () => { await api("line_add", { body: { line: sel.value, ids: [f.id] } }); load(); return null; }) } })));
    }
    const nm = h("input", { value: `${f.vendor} ${f.name.split(" ").slice(0, -1).join(" ") || f.name}` });
    const orca = h("select"), bs = h("select");
    const q = h("input", { value: f.material || "", placeholder: "search parents, e.g. PETG-CF" });
    async function parents() {
      try {
        const p = await api(`parents?q=${encodeURIComponent(q.value)}`);
        const fill = (sel, list, want) => sel.replaceChildren(...list.map((n) => h("option", { value: n, textContent: n, selected: n === want })));
        fill(orca, p.orca_parents, `Generic ${f.material}`); fill(bs, p.bs_templates, `Generic ${f.material}`);
      } catch (e) { res.replaceChildren(fail(e)); }
    }
    const details = h("details", {}, h("summary", { textContent: f.lines_for_vendor.length ? "…or a new line" : "New line (new brand or product line)" }),
      h("div", { class: "grid" }, h("label", { class: "wide" }, "Line name '<Brand> <Line>'", nm),
        h("label", { class: "wide" }, "Search parents", q), h("label", { class: "wide" }, "Orca parent", orca),
        h("label", { class: "wide" }, "Bambu Studio template", bs)),
      h("p", {}, h("button", { textContent: "Create line", on: { click: () =>
        run(res, "Creating…", async () => { await api("line_new", { body: { name: nm.value, vendor: f.vendor, ids: [f.id], orca_parent: orca.value, bs_template: bs.value } }); load(); return null; }) } })));
    q.addEventListener("change", parents);
    details.addEventListener("toggle", () => { if (details.open && !orca.options.length) parents(); });
    card.append(details, res);
    return card;
  }
  async function build() {
    await run(genBox, "Building presets… (a minute or two)", async () => { const r = await api("generate", { body: {} }); load(); return out(r); });
  }
  // Updates: the list names each preset and what changes; Accept takes exactly that list (the server refuses it once a
  // newer build has come, and the list is loaded again). The desktop writes accepted presets at its next sync.
  async function updates() {
    await run(upBox, "Loading updates…", async () => {
      const u = await api("updates");
      const restore = h("p", {}, h("button", { class: "secondary", textContent: "Restore presets deleted in Bambu Studio", on: { click: () =>
        run(upBox, "Asking for a build…", async () => { await api("restore_deleted", { body: {} }); setTimeout(updates, 3000); return h("p", { textContent: "The next build brings them back; the desktop installs it at its next sync." }); }) } }));
      const waiting = (u.updates || []).filter((x) => !x.accepted);
      if (!waiting.length) return [h("h2", { textContent: "Updates" }), h("p", { class: "muted", textContent: u.accepted ? `Nothing waiting; ${u.accepted} accepted, written at the next desktop sync.` : "No preset in your slicers needs an update." }), restore];
      const rows = waiting.map((x) => h("li", { textContent: `${x.name} (${x.target}): ${x.keys.join(", ")}` }));
      const accept = h("button", { textContent: `Accept ${waiting.length} update${waiting.length === 1 ? "" : "s"}`, on: { click: () =>
        run(upBox, "Accepting…", async () => {
          try {
            const r = await api("updates_accept", { body: { stamp: u.stamp, names: waiting.map((x) => x.name) } });
            setTimeout(updates, 3000);
            return h("p", { textContent: `${r.accepted.length} accepted: the desktop writes them over the presets at its next sync.` });
          } catch (e) { setTimeout(updates, 4000); throw e; }
        }) } });
      return [h("h2", { textContent: "Updates" }),
        h("p", { class: "muted", textContent: "A newer build would change these presets already in your slicers. Nothing is written over until you accept." }),
        h("ul", {}, ...rows), h("p", {}, accept),
        (u.yours || []).length ? h("p", { class: "muted", textContent: `Never written over (your own preset of that name): ${u.yours.join(", ")}` }) : null, restore];
    });
  }
  return { el, enter: () => { load(); updates(); } };
}
