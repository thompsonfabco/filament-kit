// Printers (04 6): the list of printers with the ones found on the network (#printers), and one printer (#printers/<id>):
// status in words (live stream), controls, camera, slots with Load and Unload, Filament used with Put it back, slot mapping
// with Map by loading filament, Printer settings; adding a printer. Loaded before app.js (which calls printersTab() when
// the printers module is on). Everything from the Hub goes in through textContent / element properties, never innerHTML.
"use strict";
function printersTab() {
  const API = BASE + "/api/printers";
  const KEY = "spoolwarden.printer";                  // the printer opened last (04 2.4)
  const HEX = /^[0-9A-Fa-f]{6}$/;
  const t = SW.t;
  const enc = encodeURIComponent;
  let active = false;                                 // the Printers place is on show
  let printers = [], manageList = [], changes = true; // the Hub's lists: set up printers; every printer it knows; may this address change them
  const snaps = new Map();                            // printer id -> its last {printer, status} (list cards)
  let current = null, addedId = null;                 // the printer on show; the one just added (its line says so)
  let listAt = null, listTimer = 0, stateTimer = 0, listLoad = null;
  let autoOpened = false, autoTried = false;          // tablets: the printer opened last is expanded when the list opens without an address for one (04 6.1)
  let pageLoad = null;                                // the skeleton of a printer page whose lists are not read yet
  let page = null;                                    // the open printer's nodes and state, made by buildPage()

  // ----- small helpers -----
  const words = (s) => { const w = String(s).replace(/_/g, " "); return w.charAt(0).toUpperCase() + w.slice(1); };
  const isUp = (p) => p.state === "connected" || p.state === "unknown_model";
  const isLive = (s) => ["RUNNING", "PAUSE", "PREPARE"].includes((s || {}).gcode_state);
  const meta = (id) => manageList.find((x) => x.id === id) || {};
  const known = (id) => printers.find((x) => x.id === id) || null;
  const nameOf = (id) => { const p = known(id) || meta(id); return (p && p.name) || id; };
  const timeLeft = (m) => (m > 0 ? (m >= 60 ? t("printer_time_hours", { hours: Math.floor(m / 60), minutes: m % 60 }) : t("printer_time_minutes", { minutes: m })) : "");
  const SHAPE = { run: "s-half", warn: "s-triangle", ok: "s-filled", bad: "s-octagon", neutral: "s-hollow", info: "s-diamond" };
  // a state as a sentence that starts with its shape (04 3.3): never colour alone
  const sentence = (kind, text) => h("p", { class: "pstate", "data-state": kind }, SW.shape(SHAPE[kind]), h("span", { class: "pstate__text" }, text));
  const JOB = { RUNNING: ["printer_job_printing", "run"], PAUSE: ["printer_job_paused", "warn"], PREPARE: ["printer_job_preparing", "run"],
    FINISH: ["printer_job_finished", "ok"], FAILED: ["printer_job_failed", "bad"], IDLE: ["printer_job_idle", "neutral"], SLICING: ["printer_job_slicing", "run"] };
  function jobWord(s) { const j = JOB[s.gcode_state]; return j ? t(j[0]) : words(s.gcode_state); }
  const jobKind = (s) => (JOB[s.gcode_state] || [0, "neutral"])[1];
  const jobText = (s) => (s.job ? t("printer_state_job", { state: jobWord(s), job: s.job }) : jobWord(s));
  const FIX = { offline: "printers_fix_offline", not_configured: "printers_fix_not_configured", wrong_code: "printers_fix_wrong_code",
    unauthorized: "printers_fix_unauthorized", needs_developer_mode: "printers_fix_developer_mode", cert_changed: "printers_fix_cert_changed",
    klippy_not_ready: "printers_fix_klippy_not_ready" };
  // the badge and what is said under it for a printer's `state` (02 7.1, printer states): the same words in every interface
  function connection(p) {
    const s = p.state;
    if (s === "connecting") return { badge: h("span", { class: "status" }, SW.spinner(), t("common_connecting")) };
    if (s === "connected") return { badge: SW.status("connected") };
    if (s === "unknown_model") return { badge: SW.status("connected"), note: t("printers_note_unknown_model") };
    if (s === "offline") return { badge: SW.status("offline"), fix: t(FIX.offline) };
    if (s === "not_configured") return { badge: SW.status("not_configured"), fix: t(p.family === "klipper" ? "printers_fix_not_configured_klipper" : FIX.not_configured) };
    return { badge: SW.status("needs_look"), fix: FIX[s] ? t(FIX[s]) : words(s || "") };
  }
  const modelText = (p) => {
    const m = meta(p.id), name = m.model_name || p.model_name || (p.family === "klipper" ? "" : p.model) || "";
    return p.family === "klipper" ? (name ? t("printer_list_model_klipper", { model: name }) : t("common_klipper"))
      : (name ? t("printer_list_model_bambu", { model: name }) : t("common_bambu_lab"));
  };
  const slotsOf = (s) => ((s && s.ams) || []).flatMap((u) => u.slots || []);
  const loadedSlot = (sl) => sl.present !== false && !!(sl.spool || sl.type || HEX.test(sl.color_hex || ""));
  const hexOf = (sl) => (HEX.test(sl.color_hex || "") ? "#" + sl.color_hex.toUpperCase() : "");
  const slotName = (sl) => (sl.spool ? sl.spool.name : sl.type || (sl.present === false ? t("common_empty") : sl.reading ? t("common_reading") : t("printer_slot_unknown")));
  const grams = (sl) => (sl.spool && sl.spool.remaining_weight != null ? Math.round(sl.spool.remaining_weight) : null);
  // the slot as one sentence for a screen reader (the swatches are hidden): "A1 Polymaker PolyTerra PLA #2B2B2E, 620 g left" (04 6.1)
  function slotSr(sl) {
    if (sl.present === false) return t("printers_slot_sr_empty", { slot: sl.label });
    const g = grams(sl), name = slotName(sl), hex = hexOf(sl);
    return g != null ? t("printers_slot_sr_grams", { slot: sl.label, name, hex, grams: g }).replace(/\s+,/, ",") : `${sl.label} ${name} ${hex}`.trim();
  }
  function slotStrip(s) {
    const slots = slotsOf(s);
    if (!slots.length) return null;
    const n = slots.filter(loadedSlot).length;
    return h("div", { class: "slot-strip slot-strip--compact" },
      h("span", { class: "slot-strip__swatches", "aria-hidden": "true" }, slots.map((sl) => SW.swatch(hexOf(sl), { level: 1, empty: sl.present === false }))),
      h("span", { class: "sr" }, slots.map(slotSr).join("; ") + ". " + t("printers_slots_loaded_of", { loaded: n, count: slots.length })),
      h("span", { class: "slot-strip__count mono", "aria-hidden": "true" }, t("slot_count", { loaded: n, total: slots.length })));
  }
  // an answer to a press that went to the Hub is the sheets' and result lines' job (app.js); a sheet asks through openHere
  function sheetAsk(o) {
    const run = o.run;
    return SW.ask({ open: openHere, ...o, run: run && (async (v, c) => { try { return await run(v, c); } catch (e) { throw Object.assign(e, { text: () => says(e) }); } }) });
  }
  async function pj(path, body) { return api(path ? "printers/" + path : "printers", body === undefined ? {} : { method: "POST", body }); }
  const lineNodes = (lines) => [lines].flat().flatMap((x, i) => (i ? [h("br"), x] : [x]));   // a result of several lines
  const needs = (key) => (v) => (v.trim() ? null : t(key));
  const codeField = (hint) => SW.field({ type: "secret", label: t("common_field_access_code"), hint, check: needs("common_error_access_code") });
  function parsePort(v) { const n = /^\d{1,5}$/.test(v) ? Number(v) : 0; return n >= 1 && n <= 65535 ? n : null; }   // 1 to 65535, or null
  const addressField = (label, hint, value) => SW.field({ label, hint, value, mono: true, check: needs("common_error_address"), attrs: { autocapitalize: "off", spellcheck: "false" } });
  const portField = (value, optional) => SW.field({ type: "number", label: t("printer_field_port"), hint: optional ? t("printer_set_port_hint") : undefined, value, optional,
    check: (v) => (optional && !v.trim() ? null : parsePort(v.trim()) === null ? t("common_error_port") : null) });
  const keyField = (o) => SW.field({ type: "secret", label: t("common_moonraker_key"), ...o });

  // ----- the page: a list, and one printer under it (on phones instead of it) -----
  const listLine = resultLine();      // a refresh that fails keeps the cards and says how old they are (04 3.5)
  const cards = h("ul", { class: "pcards", "aria-label": t("nav_printers") });
  const foundBox = h("div");
  const countBox = h("p", { class: "printers__count" });
  const noteBox = h("div");
  const addBtn = SW.btn(t("common_add"), { icon: "plus", cls: "btn--ghost", name: t("printers_add"), action: "add" });
  const addKlipper = SW.btn(t("common_add_klipper_printer"), { action: "add-klipper", run: () => addKlipperSheet(addKlipper) });
  const listAdd = h("p", { class: "printers__more" }, addKlipper);
  const listView = h("div", { class: "printers" },
    h("div", { class: "printers__bar" }, countBox, addBtn), noteBox, listLine, cards, foundBox, listAdd);
  const pageView = h("div", { class: "printer", hidden: true });
  const el = h("section", { class: "hidden" }, listView, pageView);
  SW.menu(addBtn, () => [
    ...foundBambu().map((p) => ({ label: t("printers_menu_bambu"), reason: `${p.model_name || p.model || ""} · ${p.ip}`.replace(/^ · /, ""), run: () => addBambuSheet(p, addBtn) })),
    { label: t("printers_menu_klipper"), run: () => addKlipperSheet(addBtn) }], { label: t("printers_add") });
  const foundBambu = () => manageList.filter((p) => !p.configured && p.family !== "klipper" && p.ip);

  const title = () => (current && !autoOpened ? nameOf(current) : null);               // the document's title while a printer is open (app.js asks)
  const heading = () => (current && !autoOpened && SW.phone() ? nameOf(current) : null);   // the page's h1 while one printer fills the page; on tablets it stays "Printers"
  function retitle() {
    const h1 = document.querySelector(".page-head__title");
    if (h1 && active) { h1.textContent = heading() || t("nav_printers"); document.title = t("shell_title", { page: title() || t("nav_printers"), hub: HUB || PRODUCT }); }
  }
  const routeId = () => {
    const [sec, id] = location.hash.slice(1).split("?")[0].split("/");
    return sec === "printers" && id ? decodeURIComponent(id) : null;
  };
  const wantList = () => active && !document.hidden && (!current || !SW.phone());

  // ----- the list (04 6.1) -----
  async function loadAll() {
    const [l, m] = await Promise.all([pj(""), pj("manage")]);
    printers = l.printers; manageList = m.printers; changes = m.changes; listAt = Date.now();
  }
  async function startList() {
    clearTimeout(listTimer); clearTimeout(stateTimer);
    if (!printers.length && !listLoad) listLoad = SW.loading(cards, { thing: t("nav_printers"), items: 2 });
    try { await loadAll(); clear(listLine); }
    catch (e) {
      if (listLoad) { const line = resultLine(); listLoad.done(line); listLoad = null; failed(line, e, startList); } else stale(listLine, listAt ?? Date.now());
      schedule();
      return;
    }
    if (listLoad) { listLoad.done(); listLoad = null; }
    drawList();
    if (current && !page) openPrinter(current);
    else if (!current && !autoTried && !SW.phone() && !routeId()) {
      autoTried = true;
      let want = null;
      try { want = localStorage.getItem(KEY) || localStorage.getItem("printer"); } catch (e) { /* none remembered */ }   // "printer" is the key before S3.3
      if (want && known(want)) { autoOpened = true; openPrinter(want); }
    }
    retitle(); schedule();
  }
  // the 5 s list read and the 10 s state reads run while the list is on show and the page is visible (04 6.1)
  function schedule() {
    clearTimeout(listTimer); clearTimeout(stateTimer);
    if (!wantList() || !listAt) return;
    listTimer = setTimeout(pollList, 5000);
    pollStates();
  }
  async function pollList() {
    clearTimeout(listTimer);
    if (!wantList()) return;
    try { printers = (await pj("")).printers; listAt = Date.now(); clear(listLine); drawList(); }
    catch (e) { stale(listLine, listAt ?? Date.now()); }
    if (wantList()) listTimer = setTimeout(pollList, 5000);
  }
  async function pollStates() {
    clearTimeout(stateTimer);
    if (!wantList()) return;
    await Promise.all(printers.filter(isUp).map(async (p) => { try { snaps.set(p.id, await pj(`${enc(p.id)}/state`)); } catch (e) { /* the card keeps its last data */ } }));
    drawList();
    if (wantList()) stateTimer = setTimeout(pollStates, 10000);
  }
  function cardHref(id) { return "#printers/" + enc(id) === location.hash && !SW.phone() ? "#printers" : "#printers/" + enc(id); }
  function cardNode(p) {
    const s = (snaps.get(p.id) || {}).status, info = connection(p), up = isUp(p), live = up && isLive(s);
    const pc = live ? Math.max(0, Math.min(100, Number(s.percent) || 0)) : 0, left = live ? timeLeft(s.remaining_min) : "";
    const alerts = up && s ? (s.hms || []).map((x) => sentence("bad", x.text || t("printer_alert_code", { code: x.code }))) : [];
    return h("li", { class: "pitem", "data-id": p.id }, h("div", { class: "pcard", "data-open": p.id === current && !SW.phone() ? "true" : undefined },
      h("div", { class: "pcard__head" }, h("a", { class: "pcard__name", href: cardHref(p.id) }, p.name || p.id), info.badge),
      h("p", { class: "pcard__model muted" }, modelText(p)),
      up && s && s.gcode_state ? sentence(jobKind(s), [jobText(s), live ? t("printer_percent", { percent: pc }) : "", left ? t("printer_progress_left", { time: left }) : ""].filter(Boolean).join(" · ")) : null,
      live ? SW.progress({ value: pc / 100, name: t("printer_progress_name"), valuetext: t("printer_percent", { percent: pc }) }) : null,
      info.fix ? sentence("warn", info.fix) : null, info.note ? sentence("info", info.note) : null,
      up && s ? slotStrip(s) : null, ...alerts,
      SW.icon("chevron", "icon--s pcard__go")));
  }
  function drawList() {
    const up = printers.filter(isUp).length, off = printers.filter((p) => p.state === "offline").length;
    const look = printers.filter((p) => !isUp(p) && p.state !== "offline" && p.state !== "connecting" && p.state !== "not_configured").length;
    countBox.replaceChildren(t("printers_meta_total", { count: printers.length }),
      ...(printers.length ? [" · ", SW.status("connected", { small: true, count: up }), " · ", SW.status("offline", { small: true, count: off }),
        ...(look ? [" · ", SW.status("needs_look", { small: true, count: look })] : [])] : []));
    addBtn.hidden = addKlipper.hidden = !changes;
    noteBox.replaceChildren(...(changes ? [] : [SW.banner({ kind: "info", text: t("printer_set_readonly"), inline: true })]));
    // a card that holds focus is left as it is; the others are drawn again from the newest data
    const have = new Map([...cards.children].map((c) => [c.dataset.id, c]));
    cards.replaceChildren(...printers.map((p) => { const old = have.get(p.id); return old && old.contains(document.activeElement) ? old : cardNode(p); }));
    const found = foundBambu();
    foundBox.replaceChildren(...(found.length ? [h("h2", { class: "printers__heading" }, t("printers_found_group")),
      h("ul", { class: "pfound" }, found.map((p) => h("li", { class: "pfound__row" },
        h("span", { class: "pfound__name" }, p.model_name || p.model || t("common_bambu_lab")), h("span", { class: "mono muted" }, p.ip),
        changes ? SW.btn(t("common_add"), { action: "add-found", name: t("printer_add_title", { model: p.model_name || p.model || p.ip }), run: (e) => addBambuSheet(p, e.currentTarget) }) : null)))] : []));
    if (!printers.length && !found.length) {
      cards.replaceChildren(SW.empty({ icon: "printer", title: t("home_printers_empty"), text: t("printer_list_empty_text"), actions: changes ? SW.btn(t("common_add_klipper_printer"), { action: "add-klipper", run: (e) => addKlipperSheet(e.currentTarget) }) : null }));
    }
    listAdd.hidden = !changes || (!printers.length && !found.length);
    layout();
  }

  // ----- adding a printer (04 6.9, 12.2); a change is asked for in a sheet, its refusal shows inside it -----
  async function change(o, send, after) {
    let r = null, done = "";
    const ok = await sheetAsk({ kind: "entry", busy: t("common_saving"), ...o, run: async (v) => {
      const [path, body, text] = send(v.map((x) => x.trim()));
      r = await pj(path, body); done = text;
    } });
    if (ok) await after(r, done);
  }
  async function added(r) {                              // the new printer opens, and its status line says so
    addedId = (r.printer && r.printer.id) || null;
    try { await loadAll(); drawList(); } catch (e) { /* the list reads again by itself */ }
    if (addedId) location.hash = "#printers/" + enc(addedId);
  }
  function addBambuSheet(p, opener) {
    const model = p.model_name || p.model || p.ip;
    change({ title: t("printer_add_title", { model }), text: t("add_model_found", { address: p.ip }), confirm: t("common_add_printer"), busy: t("printer_add_connecting"), opener,
      fields: [codeField(t("common_hint_access_code")), SW.field({ label: t("common_field_name_optional"), placeholder: model })] },
    ([c, n]) => ["add", { serial: p.id, access_code: c, name: n || p.name || model }, ""], added);
  }
  function addKlipperSheet(opener) {
    change({ title: t("common_add_klipper_printer"), confirm: t("common_add_printer"), busy: t("printer_add_connecting"), opener,
      fields: [addressField(t("common_address"), t("printer_address_klipper_help"), ""), portField("7125"), SW.field({ label: t("common_field_name_optional") })] },
    ([host, port, n]) => ["add", { family: "klipper", host, port: parsePort(port), ...(n ? { name: n } : {}) }, ""], added);
  }

  // ----- one printer (04 6.2): its nodes are made again for every printer opened -----
  const group = (titleKey, ...kids) => {
    const hid = SW.uid("ph"), title = h("h2", { class: "group__title", id: hid }, t(titleKey));
    const body = h("div", { class: "group__body" }, ...kids), head = h("header", { class: "group__head" }, title);
    return { el: h("section", { class: "group", "aria-labelledby": hid }, head, body), body, head };
  };
  function buildPage() {
    const g = {};     // the nodes and state of this printer
    page = g;
    const id = current;
    g.id = id; g.lastSnap = null; g.camOn = false; g.slotBusy = false; g.es = null; g.mapTimer = 0; g.mapAt = null; g.reportUrl = null; g.manual = null;
    g.slotLines = new Map(); g.undone = new Map(); g.paused = false; g.calibrated = true; g.reportWanted = false; g.sig = "";
    g.back = h("a", { class: "printer__back", href: "#printers" }, SW.icon("chevron", "icon--s printer__back-icon"), t("nav_printers"));
    g.facts = h("p", { class: "printer__facts muted" });
    g.conn = h("div", { class: "printer__conn" });
    g.job = h("div"); g.progBar = SW.progress({ value: 0, name: t("printer_progress_name") });
    g.pct = h("span", { class: "printer__pct mono" });
    g.progRow = h("div", { class: "printer__prog", hidden: true }, g.progBar, g.pct);
    g.detail = h("p", { class: "muted" }); g.temps = h("p", { class: "mono printer__temps" });
    g.alerts = h("div"); g.notes = h("div"); g.stream = h("p", { class: "result", role: "status" });
    g.statusBox = h("div", { class: "printer__live" });
    g.controls = h("div", { class: "printer__controls" });
    g.msg = resultLine();
    g.camBtn = SW.btn(t("printer_camera_show"), { icon: "camera", action: "camera", run: () => camera(!g.camOn) });
    g.camBox = h("div", { class: "pcam", hidden: true });
    g.units = h("div"); g.slotsBox = h("div");
    g.usageBox = h("div"); g.usageLine = resultLine();
    g.mapBox = h("div"); g.mapLine = resultLine(); g.repLine = resultLine(); g.reportBox = h("div");
    g.manualLine = resultLine();
    g.setLine = resultLine(); g.setBox = h("div");
    const top = h("div", { class: "group" },
      h("div", { class: "group__body" }, g.facts, g.conn, g.statusBox, g.stream, g.controls, g.msg, h("div", {}, g.camBtn), g.camBox));
    g.slots = group("printers_col_slots", g.slotsBox);
    g.used = group("printer_group_used", g.usageBox, g.usageLine);
    g.used.head.append(h("span", { class: "muted printer__days" }, t("printer_used_last_days")));
    g.map = group("printer_map_title_bambu", g.mapBox, g.mapLine, g.reportBox, g.repLine, g.manualLine);
    g.set = group("printer_settings_title", g.setBox, g.setLine);
    pageView.replaceChildren(g.back, top, g.slots.el, g.used.el, g.map.el, g.set.el);
    g.statusLoad = SW.loading(g.statusBox, { thing: nameOf(id), items: 2 });
    g.slotsLoad = SW.loading(g.slotsBox, { thing: t("printers_col_slots"), items: 2 });
    g.statusNodes = [g.job, g.progRow, g.detail, g.temps, g.alerts, g.notes];
    g.camKind = () => { const k = (known(id) || {}).camera; return k && (k.kind === "mjpeg" || k.kind === "hls") ? k.kind : null; };
    g.isKlipper = () => (known(id) || meta(id)).family === "klipper";
    return g;
  }
  function openPrinter(id) {
    closePrinter(true);
    current = id;
    try { localStorage.setItem(KEY, id); } catch (e) { /* the choice is not kept */ }
    if (!listAt) {                                       // deep link: the lists are not read yet; startList opens the page when they are
      pageLoad = SW.loading(pageView, { thing: t("nav_printers"), items: 2 });
      layout(); return;
    }
    if (pageLoad) { pageLoad.done(); pageLoad = null; }
    if (!known(id) && !meta(id).id) {                    // an address for a printer this Hub does not have
      pageView.replaceChildren(h("a", { class: "printer__back", href: "#printers" }, SW.icon("chevron", "icon--s printer__back-icon"), t("nav_printers")),
        SW.empty({ icon: "printer", title: t("printer_unknown_title"), text: t("printer_unknown_text"),
          actions: SW.btn(t("nav_printers"), { cls: "btn--primary", run: () => { location.hash = "#printers"; } }) }));
      layout(); retitle(); return;
    }
    buildPage();
    layout(); retitle();
    paintHead(); drawSettings();
    stream(); loadUsage(); loadMap();
  }
  function closePrinter(keepId) {
    if (page) { stopStream(); camera(false); clearTimeout(page.mapTimer); manualStop(); clearReport(); }
    if (pageLoad) { pageLoad.done(); pageLoad = null; }
    page = null;
    if (!keepId) { current = null; pageView.replaceChildren(); layout(); retitle(); }
  }
  // where the printer's page sits: under its card on tablets, in place of the list on phones (04 2.3)
  function layout() {
    const wide = !SW.phone(), open = !!current;
    pageView.hidden = !open;
    listView.hidden = open && !wide;
    const item = open && wide ? [...cards.children].find((c) => c.dataset.id === current) : null;
    if (item) { if (pageView.parentNode !== item) item.append(pageView); } else if (pageView.parentNode !== el) listView.after(pageView);
    pageView.classList.toggle("printer--inline", !!item);
    const back = pageView.querySelector(".printer__back"); if (back) back.hidden = wide;
  }
  function sync() {
    if (!active) return;
    const id = routeId();
    if (id && id !== current) openPrinter(id);
    else if (!id && current && !autoOpened) closePrinter();
    else layout();
    if (listAt) drawList();
    retitle(); schedule();
  }

  // ----- live status (04 6.3): the printer's stream; closed when the screen is left or hidden -----
  function stream() {
    const g = page;
    stopStream();
    g.es = new EventSource(`${API}/${enc(g.id)}/events`);
    g.es.onmessage = (ev) => {
      if (page !== g) return;
      let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d.error) {                                    // the Hub's own text, said once while it stays the same
        g.tooMany = /^too many open views/.test(d.error);
        put(g.stream, "warn", g.tooMany ? t("printer_too_many_views") : d.error);
        return;
      }
      g.tooMany = false;
      const was = g.lastSnap && isLive(g.lastSnap.status);
      clear(g.stream); g.lastSnap = d; render(d);
      if (was && !isLive(d.status)) loadUsage();        // a job ended: its usage entry is new
    };
    g.es.onopen = () => { if (!g.tooMany) clear(g.stream); };
    g.es.onerror = () => { if (page === g && !g.tooMany) put(g.stream, "run", t("printer_reconnecting")); };
  }
  function stopStream() { if (page && page.es) { page.es.close(); page.es = null; } }

  function render(d) {
    const g = page, p = { ...(known(g.id) || {}), ...(d.printer || {}) }, s = d.status || {};
    if (g.statusLoad) { g.statusLoad.done(...g.statusNodes); g.slotsLoad.done(g.units); g.statusLoad = g.slotsLoad = null; }
    paintHead(p); paintStatus(p, s); paintControls(p, s); paintSlots(p, s); paintFilled();
  }
  function paintHead(state) {
    const g = page, p = { ...(known(g.id) || {}), ...(state || {}), id: g.id }, m = meta(g.id);
    const addr = (p.family || m.family) === "klipper" ? m.host : m.ip;
    g.facts.replaceChildren(modelText(p), ...(addr ? [" · ", h("span", { class: "mono" }, addr)] : []));
    const info = connection(p);
    g.conn.replaceChildren(info.badge, ...(info.fix ? [sentence("warn", info.fix)] : []), ...(info.note ? [sentence("info", info.note)] : []),
      ...(addedId === g.id && !isUp(p) ? [sentence("ok", t("printers_added_connecting"))] : []));
    if (addedId === g.id && isUp(p)) addedId = null;
    g.up = isUp(p);
  }
  function paintStatus(p, s) {
    const g = page, up = isUp(p), live = up && isLive(s);
    g.job.replaceChildren(...(up && s.gcode_state ? [sentence(jobKind(s), jobText(s))] : []));
    g.progRow.hidden = !live;
    if (live) {
      const pc = Math.max(0, Math.min(100, Number(s.percent) || 0));
      SW.setProgress(g.progBar, pc / 100, t("printer_percent", { percent: pc })); g.pct.textContent = t("printer_percent", { percent: pc });
    }
    const left = timeLeft(s.remaining_min);
    const layer = s.total_layers ? t(left ? "printer_progress" : "printer_layer", { layer: s.layer ?? "?", total: s.total_layers, time: left }) : left ? t("printer_progress_left", { time: left }) : "";
    g.detail.textContent = live ? [layer, s.stage].filter(Boolean).join(" · ") : "";
    g.detail.hidden = !g.detail.textContent;
    g.temps.textContent = up ? (s.temps || []).map((x) => t("printer_temperature", { name: x.name, current: x.cur ?? "–", target: x.tgt || "–" })).join(" · ") : "";
    g.temps.hidden = !g.temps.textContent;
    g.alerts.replaceChildren(...(up ? (s.hms || []).map((x) => sentence("bad", x.text || t("printer_alert_code", { code: x.code }))) : []));
    g.notes.replaceChildren(...(s.notes || []).map((n) => h("p", { class: "muted" }, n)));
  }

  // ----- controls and camera (04 6.4) -----
  // what each command is called, and the sentence that says it was done (04 3.2)
  const COMMANDS = { pause: ["printer_pause", "printer_result_paused"], resume: ["printer_resume", "printer_resumed_line"],
    stop: ["printer_stop", "printer_stopped_line"], light_on: ["printer_light_on", "printer_light_on_line"],
    light_off: ["printer_light_off", "printer_result_light_off"] };
  function paintControls(p, s) {
    const g = page, up = isUp(p), live = up && isLive(s), st = s.gcode_state;
    g.paused = up && st === "PAUSE";
    const sig = [up, st, s.light].join("|");
    if (sig === g.sig) return;                          // the buttons are as they were: one that works or holds focus stays
    g.sig = sig;
    const ctl = (action, key, cls) => { const b = SW.btn(t(key), { cls, action, run: () => cmd(action, false, b) }); return b; };
    const row = [];
    if (up && st === "RUNNING") row.push(ctl("pause", "printer_pause", ""));
    if (g.paused) row.push(ctl("resume", "printer_resume", "btn--primary"));
    if (up && s.light) row.push(ctl(s.light === "on" ? "light_off" : "light_on", s.light === "on" ? "printer_light_off" : "printer_light_on", "btn--ghost"));
    if (live) { const b = SW.btn(t("printer_stop"), { cls: "btn--danger", action: "stop", run: () => stop(b) }); row.push(h("div", { class: "printer__stop" }, b)); }
    g.controls.replaceChildren(...row);
  }
  async function cmd(action, confirm, button) {
    const g = page, [name, done] = COMMANDS[action];
    await act(g.msg, t("common_working"), async () => {
      const r = await pj(`${enc(g.id)}/command`, confirm ? { action, confirm: true } : { action });
      const inner = r.reply || {}, why = (inner.reply || {}).reason;
      if (inner.ok === false) {                         // the printer refused: its reason as sent, else our own sentence
        return { kind: "bad", text: typeof why === "string" && why ? t("printer_said_no", { error: why }) : t("common_result_refused", { name: nameOf(g.id), action: t(name) }) };
      }
      SW.toast(t(done));
      return t(done);
    }, { alert: action === "stop", button });
  }
  async function stop(button) {
    const g = page, job = ((g.lastSnap || {}).status || {}).job, printer = nameOf(g.id);
    const go = await sheetAsk({ kind: "destructive", title: t("printer_stop_dialog_title"), opener: button,
      text: job ? t("printer_stop_dialog_body", { job, printer }) : t("printer_stop_dialog_body_nojob", { printer }), cancel: t("printer_stop_keep"), confirm: t("printer_stop") });
    if (go && page === g) cmd("stop", true, button);
  }
  function camera(on) {
    const g = page;
    if (!g) return;
    const kind = g.camKind();
    for (const m of g.camBox.querySelectorAll("img, video")) { m.removeAttribute("src"); if (m.load) m.load(); }   // drops the connection: the camera stops
    g.camBox.replaceChildren();
    if (!kind) on = false;
    g.camOn = on;
    g.camBtn.replaceChildren(SW.icon("camera", "icon--s"), t(on ? "printer_camera_hide" : "printer_camera_show"));
    g.camBtn.hidden = !kind;
    g.camBox.hidden = !on;
    if (!on) return;
    const base = `${API}/${enc(g.id)}`;
    const start = h("div", { class: "pcam__wait" }, SW.spinner(), t("printer_camera_starting"));
    const up = () => { if (start.isConnected) start.remove(); };
    g.camBox.append(start);
    if (kind === "mjpeg") {
      g.camBox.append(h("img", { class: "cam", alt: t("printer_camera_alt", { printer: nameOf(g.id) }), on: { load: up, error: () => camFail(`${base}/camera.mjpeg`) }, src: `${base}/camera.mjpeg` }));
      return;
    }
    const v = h("video", { class: "cam", playsInline: true, muted: true, autoplay: true, controls: true, "aria-label": t("printer_camera_alt", { printer: nameOf(g.id) }) });
    v.muted = true;
    if (!v.canPlayType("application/vnd.apple.mpegurl")) { g.camBox.replaceChildren(h("p", { class: "pcam__text" }, t("printer_camera_no_hls"))); return; }
    v.addEventListener("playing", up);
    v.addEventListener("error", () => camFail(`${base}/camera/index.m3u8`));
    g.camBox.append(v);
    v.src = `${base}/camera/index.m3u8`;
    v.play().catch(() => {});
  }
  // The picture did not come. A request tells too many views (429) from the rest; its body is dropped at once.
  async function camFail(url) {
    const g = page;
    if (!g || !g.camOn) return;
    let many = false;
    try { const stop = new AbortController(), r = await fetch(url, { credentials: "same-origin", signal: stop.signal }); many = r.status === 429; stop.abort(); } catch (e) { /* the general text */ }
    if (page !== g || !g.camOn) return;
    for (const m of g.camBox.querySelectorAll("img, video")) { m.removeAttribute("src"); if (m.load) m.load(); }
    g.camBox.replaceChildren(h("div", { class: "pcam__text" }, h("p", {}, t(many ? "printer_camera_too_many" : "printer_camera_failed")),
      SW.btn(t("common_try_again"), { action: "try-again", run: () => camera(true) })));
  }

  // ----- slots, load and unload (04 6.5; the kit's slot routes, the same refusals as the Android app) -----
  function slotLine(label) {
    const g = page;
    if (!g.slotLines.has(label)) g.slotLines.set(label, resultLine());
    return g.slotLines.get(label);
  }
  function paintSlots(p, s) {
    const g = page, up = isUp(p), units = s.ams || [];
    const sig = JSON.stringify([units, up]);
    if (sig === g.slotSig) return;
    g.slotSig = sig;
    const focus = document.activeElement && g.units.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const unitNode = (u) => {
      const rows = (u.slots || []).map((sl) => {
        const sp = sl.spool, key = (what) => `${what}:${sl.label}`, gr = grams(sl), hex = hexOf(sl);
        const load = SW.btn(t("common_load"), { action: "load", name: t("spool_load_title", { slot: sl.label }), run: () => openLoad(sl, load) });
        const unload = sp ? SW.btn(t("common_unload"), { action: "unload", name: t("printer_unload_title", { slot: sl.label }), run: () => unloadSlot(sl, sp, unload) }) : null;
        load.dataset.key = key("load"); if (unload) unload.dataset.key = key("unload");
        const actions = h("div", { class: "pslot__actions" }, load, unload);
        if (!up) { disabled(load, t("slot_load_disabled")); if (unload) disabled(unload, t("slot_load_disabled")); }
        const detail = sl.present === false ? t("common_empty") : sl.reading ? t("common_reading")
          : [hex, gr != null ? t("spool_left_grams", { grams: gr }) : ""].filter(Boolean).join(" · ");
        return h("li", { class: "slot-strip__row pslot", "data-state": sl.active ? "active" : undefined },
          h("span", { class: "mono pslot__label" }, sl.label), SW.swatch(hex, { empty: sl.present === false }),
          h("div", { class: "pslot__text" }, h("span", { class: "pslot__name" }, sl.present === false ? t("common_empty") : slotName(sl)), detail && sl.present !== false ? h("span", { class: "muted" }, detail) : null),
          sl.active ? h("span", { class: "slot-strip__use" }, t("slot_in_use")) : null, actions, slotLine(sl.label));
      });
      return h("div", { class: "punit" }, h("h3", { class: "punit__title" }, [u.label, u.type_name].filter(Boolean).join(" · ")),
        h("ul", { class: "slot-strip", "aria-label": units.length > 1 ? u.label : t("slot_list_label", { name: nameOf(g.id) }) }, rows));
    };
    g.units.replaceChildren(...(units.length ? units.map(unitNode) : [h("p", { class: "muted" }, t(up ? "spool_load_no_slots" : "slot_none_offline"))]));
    if (focus) { const b = g.units.querySelector(`[data-key="${CSS.escape(focus)}"]`); if (b) b.focus(); }
  }
  const slotPath = (g, label) => `${enc(g.id)}/slots/${enc(label)}`;
  const spoolTitle = (s) => `${s.vendor || ""} ${s.name || ""}`.trim() || t("spool_title", { id: s.id });
  const slotSay = (label, lines, kind) => SW.result(slotLine(label), kind, lineNodes(lines));

  // Load into <slot>: pick a spool (last tapped tag, or search), see the plan from a dry run, then Load sends it for real
  function openLoad(sl, opener) {
    const g = page, label = sl.label;
    let spool = null, dryAgain = false;
    clear(slotLine(label));
    const line = resultLine(), plan = resultLine(), results = h("div", { class: "list" });
    const hint = h("p", { class: "muted" }, t("spool_load_pick_hint"));
    const find = SW.field({ type: "search", label: t("common_search"), placeholder: t("common_search_placeholder"), onSearch: (text) => search(text) });
    const picked = h("div", { class: "pload__picked", hidden: true });
    const search_ = h("div", { class: "pload__search" }, find, line, results, hint);
    const cancel = SW.btn(t("common_cancel"), { action: "cancel", run: () => dlg.close() });
    const go = SW.btn(t("common_load"), { cls: "btn--primary", action: "load", run: () => doLoad(false) });
    const tap = SW.btn(t("spool_load_last_tag"), { action: "last-tag", run: () => lastTap() });
    disabled(go, t("spool_load_pick_first"), () => find._control);
    const dlg = SW.sheet({ title: t("spool_load_title", { slot: label }), foot: [cancel, go],
      body: h("div", { class: "pload" }, tap, h("p", { class: "muted pload__or" }, t("spool_load_or")), search_, picked, plan) });
    openHere(dlg, opener);
    function row(s) {
      const b = h("button", { class: "pick", type: "button", on: { click: () => pick(s) } }, h("strong", {}, `S${s.id} `), spoolTitle(s),
        h("div", { class: "muted" }, `${s.location || "?"} · ${s.remaining_g ?? "?"} g`));
      return b;
    }
    async function search(text) {
      if (find._busy) find._busy(true);
      try {
        const res = await api(`find?q=${enc(text)}&sealed=0`);
        const rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ id: s.spool_id, vendor: f.vendor, name: f.name, location: s.location, remaining_g: s.remaining_g })));
        clear(line);
        results.replaceChildren(...(rows.length ? rows.slice(0, 60).map(row) : [h("p", { class: "muted" }, t("spools_empty_filtered"))]));
      } catch (e) { failed(line, e, () => search(text)); } finally { if (find._busy) find._busy(false); }
    }
    async function lastTap() {
      await act(line, t("common_working"), async () => {
        const r = await pj("tagged");
        if (!r.spool) { results.replaceChildren(h("p", { class: "muted" }, r.nfc_id ? t("spool_load_tag_unlinked", { tag: r.nfc_id }) : t("spool_load_no_tag"))); return null; }
        pick(r.spool);
        return null;
      }, { button: tap });
    }
    function pick(s) {
      spool = s; clear(plan); disabled(go, t("spool_load_working_out"));
      search_.hidden = true;
      picked.hidden = false;
      picked.replaceChildren(h("p", {}, t("spool_load_picked", { id: s.id, name: spoolTitle(s), location: s.location || "?", grams: s.remaining_g != null ? Math.round(s.remaining_g) : "?" })),
        SW.btn(t("common_change"), { cls: "btn--ghost", action: "change", run: () => { spool = null; picked.hidden = true; search_.hidden = false; clear(plan); disabled(go, t("spool_load_pick_first"), () => find._control); find._control.focus(); } }));
      doLoad(true);                                     // the dry run first: the plan is shown before anything is sent
    }
    // dry: the plan (preset, nozzle, spools going back); then Load sends `dry_run: false`
    async function doLoad(dry) {
      if (!spool) return;
      if (g.slotBusy) { if (dry) dryAgain = true; return; }     // not dropped: runs for the latest pick when the call under way ends
      const s = spool;
      g.slotBusy = true; disabled(go, t(dry ? "spool_load_working_out" : "common_load_wait"));
      SW.result(plan, "run", t(dry ? "spool_load_working_out" : "common_load_wait"));
      try {
        const r = await pj(`${slotPath(g, label)}/load`, { spool_id: s.id, dry_run: dry });
        if (spool !== s) return;                         // another spool was picked meanwhile
        const moved = (r.moved_back || []).filter((m) => m.id !== s.id)
          .map((m) => t("spool_load_plan_goes_back", { id: m.id ?? "?", slot: label, location: m.location || t("spool_load_previous_place") }));
        const problems = (r.problems || []).map((x) => sentence("bad", x));
        if (dry) {
          const nozzle = r.nozzle_assumed ? t("spool_load_plan_nozzle_assumed", { mm: r.nozzle_mm ?? 0.4 }) : (r.nozzle_mm ? t("spool_load_plan_nozzle", { mm: r.nozzle_mm }) : "");
          SW.result(plan, problems.length ? "warn" : "ok", [lineNodes([t("spool_load_plan", { spool: spoolTitle(s), slot: label }),
            t("spool_load_plan_preset", { preset: (r.preset && r.preset.name) || t("common_value_none") }), nozzle, ...moved].filter(Boolean)), ...problems]);
          disabled(go, null);
        } else {
          dlg.close();
          SW.toast(t(r.confirmed ? "spool_load_loaded_toast" : "spool_load_sent_toast", { slot: label }));
          slotSay(label, [t(r.confirmed ? "spool_load_loaded_toast" : "spool_load_sent_line", { slot: label }), ...moved, ...(r.problems || [])], "ok");
        }
      } catch (e) {
        if (spool === s) { failed(plan, e, () => doLoad(dry)); disabled(go, dry ? t("spool_load_see_above") : null); }   // a refused Load can be pressed again; a failed plan has to be picked again
      } finally {
        g.slotBusy = false;
        if (dryAgain && spool && dlg.isConnected) { dryAgain = false; doLoad(true); }
      }
    }
  }
  // Spoolman only (the printer's slot setting stays): the dry run says where the spool goes, then a sheet asks
  async function unloadSlot(sl, sp, button) {
    const g = page, label = sl.label, line = slotLine(label);
    if (g.slotBusy) return;
    g.slotBusy = true;
    try {
      let plan = null;
      await act(line, t("common_checking"), async () => { plan = await pj(`${slotPath(g, label)}/unload`, { dry_run: true }); return null; }, { button });
      if (!plan) return;                                // the line says why
      const where = plan.location || ((plan.moved_back || [])[0] || {}).location || t("spool_load_previous_place");
      const name = sp.name || t("spool_title", { id: sp.id });
      const r = await sheetAsk({ kind: "confirm", title: t("printer_unload_title", { slot: label }), opener: button,
        text: t("printer_unload_body", { name, slot: label, location: where }), confirm: t("common_unload"),
        run: () => pj(`${slotPath(g, label)}/unload`, { dry_run: false }) });
      if (!r) return;
      SW.toast(t("printer_unload_line", { name, slot: label }));
      slotSay(label, [t("printer_unload_line", { name, slot: label }),
        ...(r.moved_back || []).map((m) => t("printer_unload_moved_back", { id: m.id ?? "?", location: m.location || t("spool_load_previous_place") }))], "ok");
    } finally { g.slotBusy = false; }
  }

  // ----- Filament used (04 6.6) -----
  const stamp = (at) => (at || "").replace("T", " ").slice(0, 16);
  async function loadUsage() {
    const g = page;
    if (!g) return;
    await fill(g.usageBox, t("printer_group_used"), async () => {
      const r = await pj(`${enc(g.id)}/usage?days=7`);
      if (page !== g) return null;
      const list = [...(r.entries || [])].sort((a, b) => String(b.at || "").localeCompare(String(a.at || ""))).slice(0, 20);
      return list.length ? h("ul", { class: "pused" }, list.map((e) => usageRow(g, e))) : h("p", { class: "muted" }, t("printer_used_empty"));
    }, { quiet: g.usageBox.childElementCount > 0 });    // a refresh after a job keeps what is shown until the new list arrives
  }
  function usageRow(g, e) {
    const line = resultLine(), said = g.undone.get(e.id);
    if (said) SW.result(line, "ok", said);
    const from = e.spool === null ? t("printer_used_spool_gone") : e.spool ? t("printer_used_from_spool", { id: e.spool.id, name: spoolTitle(e.spool) }) : "";
    const b = e.undone ? null : SW.btn(t("common_undo"), { action: "undo", name: t("printer_used_undo_name", { grams: e.grams ?? "?", job: e.job || t("printer_used_job_default") }), run: () => undo(e, b) });
    return h("li", { class: "pused__row", "data-state": e.undone ? "undone" : undefined },
      h("span", { class: "pused__grams mono" }, t("common_grams", { grams: e.grams ?? "?" })),
      h("span", { class: "pused__what" }, [e.job || t("printer_used_job_default"), e.slot].filter(Boolean).join(" · "), e.undone ? " " + t("recent_revision_undone") : ""),
      h("span", { class: "pused__when mono muted" }, stamp(e.at)), from ? h("span", { class: "pused__from muted" }, from) : null, b, line);
  }
  async function undo(e, button) {
    const g = page;
    const back = await sheetAsk({ kind: "confirm", title: t("printer_usage_undo_title"), cancel: t("common_keep"), confirm: t("printer_usage_undo_confirm"), opener: button,
      text: t("printer_usage_undo_body", { grams: e.grams ?? "?", job: e.job || "?", slot: e.slot || "?", time: stamp(e.at) }),
      run: () => pj(`${enc(g.id)}/usage/${enc(e.id)}/undo`, {}) });
    if (!back || page !== g) return;
    const text = t("printer_used_put_back", { grams: e.grams ?? "?" });
    g.undone.set(e.id, text);
    SW.toast(text);
    loadUsage();
  }

  // ----- Slot mapping (04 6.7) -----
  const mapPath = (g, what) => `${enc(g.id)}/${what}`;
  function mapNodes(g, m) {
    const running = m.state === "running";
    g.calibrated = !!m.calibrated; g.reportWanted = !!m.report_wanted;
    const mapBtn = SW.btn(running ? [SW.spinner(), t("printers_mapping")] : t("printers_map_slots"), { action: "map", run: () => remap() });
    const byLoad = SW.btn(t("printers_map_loading"), { action: "map-by-loading", run: () => openManual(byLoad) });
    const report = SW.btn(t("printers_collect_report"), { action: "report", run: () => collectReport(report) });
    g.mapBtns = { map: mapBtn, report };
    disabled(mapBtn, running ? t("printers_map_running_reason") : null);
    disabled(byLoad, running ? t("printers_map_running_reason") : null);
    const badge = running ? SW.status("running", { small: true }) : m.state === "done" ? SW.status("done", { small: true }) : m.state === "failed" ? SW.status("failed", { small: true }) : null;
    const hubWords = [m.state, m.step].filter(Boolean).join(" · ");
    return [
      m.outcome_text ? h("p", {}, `${m.outcome_text}${running && m.step ? " " + m.step : ""}`, badge ? [" ", badge] : null)
        : h("div", {}, sentence(m.calibrated ? "ok" : "neutral", t(m.calibrated ? "printer_slots_mapped" : "printer_slots_not_mapped")), hubWords ? h("p", { class: "muted" }, hubWords, badge ? [" ", badge] : null) : null),
      m.stale ? sentence("warn", t("printer_slots_layout_changed")) : null,
      m.next_step && !running ? h("p", {}, m.next_step) : null,
      m.problems_old && (m.problems || []).length ? h("p", { class: "muted" }, t("printers_map_earlier")) : null,
      ...(m.problems || []).map((x) => (m.problems_old ? h("p", { class: "muted" }, x) : sentence("bad", x))),
      ...(m.notes || []).map((x) => h("p", { class: "muted" }, x)),
      m.report_wanted ? h("p", { class: "muted" }, m.report_why || t("printers_map_report_wanted")) : null,
      h("div", { class: "printer__buttons" }, mapBtn, byLoad, report)];
  }
  // poll: the 2 s refresh while a mapping runs; a poll that fails keeps the map and says how old it is (04 3.5)
  async function loadMap(poll) {
    const g = page;
    if (!g) return;
    clearTimeout(g.mapTimer);
    if (g.isKlipper()) {                                // the kit's slot map and report are for Bambu printers; Klipper has only Map by loading filament
      const byLoad = SW.btn(t("printers_map_loading"), { action: "map-by-loading", run: () => openManual(byLoad) });
      g.mapBtns = null;
      g.mapBox.replaceChildren(byLoad);
      return;
    }
    const again = () => { g.mapTimer = setTimeout(() => loadMap(true), 2000); };
    const draw = async () => {
      const m = await pj(mapPath(g, "map"));
      if (page !== g) return null;
      g.mapAt = Date.now(); clear(g.mapLine);
      if (m.state === "running") again();
      return mapNodes(g, m);
    };
    if (!poll) { g.mapAt = null; await fill(g.mapBox, t("printer_map_title_bambu"), draw); paintFilled(); return; }
    try { const kids = await draw(); if (kids && page === g) { g.mapBox.replaceChildren(...kids); paintFilled(); } }
    catch (e) { if (page === g) { stale(g.mapLine, g.mapAt ?? Date.now()); again(); } }
  }
  // one filled button on the printer (04 6.2): Resume while paused; else Map slots while not mapped; else Collect a report when it would help
  function paintFilled() {
    const g = page;
    if (!g || !g.mapBtns) return;
    const f = g.paused ? "resume" : !g.calibrated ? "map" : g.reportWanted ? "report" : null;
    g.mapBtns.map.classList.toggle("btn--primary", f === "map");
    g.mapBtns.report.classList.toggle("btn--primary", f === "report");
  }
  async function remap() {
    const g = page;
    const go = await sheetAsk({ kind: "confirm", title: t("printers_map_title", { name: nameOf(g.id) }), text: t("printers_map_body"), opener: g.mapBtns && g.mapBtns.map,
      confirm: t("printers_map_slots"), run: () => pj(mapPath(g, "map"), {}) });
    if (go && page === g) loadMap();
  }
  // The report holds no serial, address, name or account id: the Hub builds it from an allow-list.
  function clearReport() { if (page && page.reportUrl) URL.revokeObjectURL(page.reportUrl); if (page) { page.reportUrl = null; page.reportBox.replaceChildren(); } }
  async function collectReport(button) {
    const g = page;
    await act(g.repLine, t("common_working"), async () => {
      const r = await pj(mapPath(g, "report"), {});
      if (page !== g) return null;
      clearReport();                                    // one link at a time; the old one's object URL is freed
      g.reportUrl = URL.createObjectURL(new Blob([r.xml], { type: "application/xml" }));
      g.reportBox.replaceChildren(...(r.live === false ? [h("p", { class: "muted" }, t("printers_map_report_offline"))] : []),
        h("p", {}, h("a", { class: "btn", href: g.reportUrl, download: r.name }, SW.icon("download", "icon--s"), t("printers_map_report_download"))),
        h("p", { class: "muted" }, t("printers_map_report_attach")));
      return t("printers_map_report_ready");
    }, { button });
  }

  // ----- Map by loading filament (04 6.7.1): a sheet; the owner loads each slot, the printer says which one it sees (the
  // kit's session, shared with the Hub page and the Android app; nothing is sent to the printer) -----
  function manualStop() { if (page && page.manual) { clearTimeout(page.manual.timer); page.manual = null; } }
  const mpath = (id, what) => `${enc(id)}/manual-map${what ? "/" + what : ""}`;
  function openManual(opener) {
    const g = page, id = g.id;
    const body = h("div", { class: "pmanual" }), foot = h("div", { class: "pmanual__foot" }), line = resultLine();
    const dlg = SW.sheet({ title: t("printers_map_loading"), cls: "sheet--detail", body: [body, line], foot,
      onClose: () => { if (g.manual) manualStop(); if (page === g) loadMap(); } });
    openHere(dlg, opener);
    const start = SW.btn(t("printers_manual_start"), { cls: "btn--primary", action: "start", run: async () => {
      await act(line, t("common_working"), async () => {
        const v = await pj(mpath(id, "start"), {});
        manualStop();
        g.manual = { id, v, timer: 0, shown: null, picks: {}, fails: 0, okAt: Date.now() };
        draw();
        g.manual.timer = setTimeout(tick, 2000);
        return null;
      }, { button: start });
    } });
    body.replaceChildren(h("p", {}, t("printers_map_loading_intro")), start);
    async function send(what, extra) {
      const m = g.manual;
      if (!m) return;
      try {
        const r = await pj(mpath(m.id, what), { session: m.v.session, ...extra });
        if (m !== g.manual) return;
        clear(line);
        if (what === "offer") { m.v.offer_report = false; draw(); SW.result(line, "ok", r.message); return; }
        m.v = r; draw();
      } catch (e) { if (m === g.manual) failed(line, e); }
    }
    async function tick() {
      const m = g.manual;
      if (!m) return;
      if (!m.v.open) { draw(); return; }
      const was = JSON.stringify(m.v);
      try { m.v = await pj(mpath(m.id)); m.okAt = Date.now(); } catch (e) {
        if (m !== g.manual) return;
        // a Wi-Fi blip: the session is still open on the Hub, so keep asking, slower each time; what is shown stays, with how old it is (04 3.5)
        if (++m.fails >= 8) { body.replaceChildren(); foot.replaceChildren(); failed(line, e, () => dlg.close()); g.manual = null; return; }
        stale(line, m.okAt);
        m.timer = setTimeout(tick, Math.min(2000 * 2 ** m.fails, 20000));
        return;
      }
      if (m !== g.manual) return;
      if (m.fails) clear(line);
      if (JSON.stringify(m.v) !== was || m.fails) { m.fails = 0; draw(); }     // unchanged: a choice being made stays as it is
      m.timer = setTimeout(tick, 2000);
    }
    function draw() {
      const m = g.manual, v = m.v, st = v.step;
      // a redraw rebuilds the selects: a choice the owner is making survives it while the same position is asked
      const pos = st ? st.position.id : null;
      const prev = pos === m.shown ? Object.fromEntries(Object.entries(m.picks).map(([k, f]) => [k, f._control.value])) : {};
      m.shown = pos; m.picks = {};
      const keep = (k, f) => {
        if (!f) return f;
        m.picks[k] = f;
        if (prev[k] !== undefined && [...f._control.options].some((o) => o.value === prev[k])) f._control.value = prev[k];
        return f;
      };
      const word = (q) => q.status === "confirmed" ? (q.nozzle ? t("printers_load_confirmed", { label: q.reported_label, nozzle: q.nozzle }) : t("printers_map_confirmed", { slot: q.reported_label }))
        : q.status === "by_hand" ? t("printers_load_by_hand", { label: q.reported_label }) : q.status === "pending" ? t("printers_load_waiting") : q.status;
      const kind = (q) => (q.status === "confirmed" ? "ok" : q.status === "by_hand" ? "info" : "neutral");
      let ask = null;
      if (st && st.seen && st.ask) {
        const other = keep("other", SW.field({ type: "select", label: t("printers_load_no"), options: v.positions.map((q) => ({ value: q.id, label: q.label })) }));
        other._control.value = st.position.id;
        const noz = keep("noz", v.dual_nozzle && !st.seen.nozzle_reported ? SW.field({ type: "select", label: t("common_field_nozzle"),
          options: [{ value: "right", label: t("printers_load_nozzle_right") }, { value: "left", label: t("printers_load_nozzle_left") }] }) : null);
        const nozzle = () => (st.seen.nozzle_reported ? st.seen.nozzle : noz ? noz._control.value : null);
        const yes = SW.btn(t("common_yes"), { cls: "btn--primary", action: "yes", run: () => send("confirm", { position: st.position.id, reported: st.seen.reported, nozzle: nozzle() }) });
        const save = SW.btn(t("printers_load_save"), { action: "save", run: () => send("confirm", { position: other._control.value, reported: st.seen.reported, nozzle: nozzle() }) });
        ask = h("div", { class: "pmanual__ask" }, h("p", {}, st.ask), noz, yes, other, save);
      } else if (st && !v.reports_loads) {
        const pick = keep("pick", SW.field({ type: "select", label: t("printers_load_slot"), options: (v.choices || []).map((c, i) => ({ value: String(i), label: c.label })) }));
        ask = h("div", { class: "pmanual__ask" }, pick, SW.btn(t("printers_load_save_unchecked"), { cls: "btn--primary", action: "save-unchecked",
          run: () => send("confirm", { position: st.position.id, reported: v.choices[Number(pick._control.value)].reported, by_hand: true }) }));
      } else if (st && st.seen && !st.seen.settled) {
        ask = sentence("run", t("printers_load_settling"));
      }
      body.replaceChildren(h("p", {}, st ? st.say : v.summary), ask,
        h("h3", { class: "pmanual__heading" }, t("printers_manual_positions")),
        h("ul", { class: "pmanual__rows" }, v.positions.map((q) => h("li", {}, sentence(kind(q), t("printers_map_position_row", { position: q.label, status: word(q) }))))),
        !v.open && v.offer_report ? h("div", { class: "pmanual__offer" }, h("p", {}, t("printers_load_offer")),
          h("div", { class: "printer__buttons" }, SW.btn(t("printer_mbl_share_yes"), { action: "share", run: () => send("offer", { share: true }) }),
            SW.btn(t("printers_load_offer_no"), { action: "no-share", run: () => send("offer", { share: false }) }))) : null);
      foot.replaceChildren(...(st ? [SW.btn(t("printers_load_skip", { position: st.position.label }), { action: "skip", run: () => send("skip", { position: st.position.id }) }),
        SW.btn(t("common_stop"), { action: "stop", run: () => send("stop", {}) })] : []));
      if (!v.open) clearTimeout(m.timer);
    }
  }

  // ----- Printer settings (04 6.8): from the Hub's own printer list; every change in a sheet (12.2) -----
  const settingsRow = (label, value, ...buttons) => h("div", { class: "kv__row" }, h("span", { class: "kv__key" }, label), h("div", { class: "kv__value" }, value, ...buttons));
  const sbtn = (key, setting, run) => SW.btn(t(key), { action: "change", name: t("printer_set_button_name", { action: t(key), setting }), run });
  // After a change the sheet has closed: the lists are read again and the group says what happened.
  async function changed(done) {
    const g = page;
    try { await loadAll(); drawList(); } catch (e) { /* the next read of the list will show it */ }
    if (page !== g) return;
    paintHead(); retitle(); drawSettings();
    SW.result(g.setLine, "ok", done);
  }
  function drawSettings() {
    const g = page, p = meta(g.id), name = p.name || nameOf(g.id), bambu = p.family !== "klipper", id = enc(g.id);
    const where = bambu ? p.ip : p.host;
    const edit = (body, done) => [`${id}/edit`, body, done];
    const rows = [settingsRow(t("common_field_name"), h("span", {}, name), changes ? sbtn("common_rename", t("common_field_name"), (e) =>
      change({ title: t("printers_rename_title"), confirm: t("common_rename"), opener: e.currentTarget,
        fields: [SW.field({ label: t("common_field_name"), value: name, check: needs("common_error_name") })] },
      ([n]) => edit({ name: n }, t("printer_set_renamed", { name: n })), (r, done) => changed(done))) : null)];
    rows.push(settingsRow(t("common_address"), where ? h("span", { class: "mono" }, where) : h("span", { class: "muted" }, t("printers_no_address")),
      changes ? sbtn(where ? "common_change" : "status_set", t("common_address"), (e) => {
        // an address change asks for the Access Code again, pinned or not; a Klipper printer's stored key goes only to the new address,
        // so it is asked for too (an empty one means none)
        const addr = bambu ? addressField(t("printer_address_bambu_label"), t("printer_address_bambu_help"), where || "") : addressField(t("common_address"), t("printer_address_klipper_help"), where || "");
        const port = bambu ? null : portField("", true);
        const code = bambu ? codeField(t("printer_address_code_help")) : null;
        const key = bambu ? null : keyField({ optional: true, hint: t("printer_address_key_help") });
        change({ title: t("printers_change_address_title", { name }), confirm: t("printers_change_address"), opener: e.currentTarget, fields: [addr, port, code, key].filter(Boolean) },
          (v) => { const a = v[0], rest = bambu ? v.slice(1) : v.slice(2); const pn = bambu ? null : parsePort(v[1]);
            return edit({ address: a, ...(pn ? { port: pn } : {}), ...(bambu ? { access_code: rest[0] } : { api_key: rest[0] }) }, t("printer_set_address_changed", { address: a })); },
          (r, done) => changed(done));
      }) : null));
    if (bambu) {
      rows.push(settingsRow(t("common_field_access_code"), p.configured ? SW.status("set") : SW.status("not_set"), changes ? sbtn("common_replace", t("common_field_access_code"), (e) =>
        change({ title: t("printers_access_code_title", { name }), confirm: t("printers_replace_access_code"), opener: e.currentTarget, fields: [codeField(t("common_hint_access_code"))] },
          ([c]) => edit({ access_code: c }, t("printer_set_code_replaced")), (r, done) => changed(done))) : null));
      rows.push(settingsRow(t("printers_fact_certificate"), h("span", {}, t(p.pinned ? "printers_cert_pinned_short" : "printer_set_not_pinned")), changes && p.pinned ? sbtn("common_forget", t("printers_fact_certificate"), (e) =>
        change({ kind: "destructive", title: t("printers_forget_cert_title", { name }), text: t("printer_set_cert_text", { name }), confirm: t("printers_forget_cert"), opener: e.currentTarget,
          fields: [codeField(t("common_hint_access_code"))] }, ([c]) => edit({ unpin: true, access_code: c }, t("printer_set_cert_forgotten")), (r, done) => changed(done))) : null));
    } else {
      // the Hub does not say whether a key is saved: only a refused key (state unauthorized) is known to be missing or wrong
      rows.push(settingsRow(t("common_moonraker_key"), p.state === "unauthorized" ? SW.status("not_set") : h("span", { class: "muted" }, "–"), changes ? sbtn(p.state === "unauthorized" ? "status_set" : "common_replace", t("common_moonraker_key"), (e) =>
        change({ title: t("printers_key_title", { name }), confirm: t("common_save_key"), opener: e.currentTarget, fields: [keyField({ check: needs("printers_error_key") })] },
          ([k]) => edit({ api_key: k }, t("printer_set_key_saved")), (r, done) => changed(done))) : null));
    }
    const forget = changes ? SW.btn(t("printers_forget"), { icon: "trash", cls: "btn--danger", action: "forget", run: async () => {
      const ok = await sheetAsk({ kind: "destructive", title: t("printers_forget_title", { name }), opener: forget, busy: t("common_working"),
        text: t(bambu ? "printers_forget_body_bambu" : "printers_forget_body_klipper", { product: t("app_name") }), confirm: t("printers_forget"),
        run: async () => { await pj(`${id}/forget`, {}); } });
      if (!ok) return;
      SW.toast(t("printers_forgotten", { name }));
      location.hash = "#printers";
      try { await loadAll(); drawList(); } catch (e) { /* the list reads again by itself */ }
    } }) : null;
    g.setBox.replaceChildren(
      changes ? h("p", { class: "muted" }, t("printer_set_home_note")) : SW.banner({ kind: "info", text: t("printer_set_readonly"), inline: true }),
      h("div", { class: "kv pset" }, rows), forget ? h("div", { class: "detail__remove" }, forget) : null);
  }

  // ----- the place: shown, left, hidden, resized -----
  window.addEventListener("hashchange", () => { if (active && /^#printers(\/|\?|$)/.test(location.hash)) { autoOpened = false; sync(); } });
  document.addEventListener("visibilitychange", () => {
    if (!active) return;
    if (document.hidden) { stopStream(); if (page) camera(false); clearTimeout(listTimer); clearTimeout(stateTimer); }
    else { if (page) stream(); schedule(); }
  });
  matchMedia("(max-width: 600px)").addEventListener("change", () => { if (active) sync(); });
  return {
    el, title, heading,
    enter() { active = true; autoTried = autoOpened = false; sync(); startList(); },
    leave() { active = false; clearTimeout(listTimer); clearTimeout(stateTimer); closePrinter(); },
  };
}


// ----- Print alerts on this phone (04 9.2): the group of the Settings sheet; the Hub's push/key, push/subscribe,
// push/unsubscribe and push/test, as when it was on the Printers tab. Called by app.js only when print alerts are offered. -----
function alertsPanel(addToHome) {
  const ok = "serviceWorker" in navigator && "PushManager" in window;
  const pj = (path, body) => api("printers/" + path, body === undefined ? {} : { method: "POST", body });
  const said = (e) => Object.assign(e, { text: () => says(e) });          // SW.toggle and SW.result show err.text()
  const line = h("p", { class: "alerts__state" });
  const testBox = h("p", { class: "result", role: "status" });
  const setState = (word, text) => line.replaceChildren(SW.status(word, text ? { text } : {}));
  const b64 = (s) => {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  async function subscribe() {
    if ((await Notification.requestPermission()) !== "granted") { paint(false); throw said(new Error(SW.t("settings_alerts_blocked"))); }
    const reg = await navigator.serviceWorker.register(BASE + "/sw.js");
    await navigator.serviceWorker.ready;
    const key = (await pj("push/key")).key;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
    await pj("push/subscribe", { subscription: sub.toJSON() });
  }
  async function unsubscribe() {
    const reg = await navigator.serviceWorker.getRegistration(BASE + "/");
    const sub = reg && (await reg.pushManager.getSubscription());
    if (sub) { await pj("push/unsubscribe", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
  }
  function paint(on) {
    if (!ok) setState("note", SW.t("settings_alerts_unsupported", { product: SW.t("app_name") }));
    else if (window.Notification && Notification.permission === "denied") setState("needs_look", SW.t("settings_alerts_blocked"));
    else if (on) setState("on", SW.t("settings_alerts_on"));
    else setState("off");
  }
  paint(false);
  if (!ok) {                                                  // an iPhone in the browser: the way to a Home Screen app (04 10.1)
    return h("div", { class: "alerts" }, line, addToHome ? SW.btn(SW.t("nav_more_home_screen"), { run: addToHome, action: "home" }) : null);
  }
  const makeToggle = (checked) => SW.toggle({ label: SW.t("settings_alerts_toggle"), checked,
    apply: async (on) => {
      try { if (on) await subscribe(); else await unsubscribe(); } catch (e) { paint(!on); throw said(e); }
      paint(on);
      return on ? SW.t("settings_alerts_on") : SW.t("status_off");
    } });
  const slot = h("div", {}, makeToggle(false));
  navigator.serviceWorker.getRegistration(BASE + "/").then((reg) => reg && reg.pushManager.getSubscription()).then((sub) => {
    if (sub) { slot.replaceChildren(makeToggle(true)); paint(true); }     // this phone is already subscribed
  }).catch(() => {});
  const test = SW.btn(SW.t("settings_alerts_test"), { action: "test", run: async () => {
    SW.busy(test, SW.t("common_working"));
    try { await pj("push/test", {}); SW.result(testBox, "ok", SW.t("settings_alerts_sent")); }
    catch (e) { SW.result(testBox, "bad", says(e)); }
    finally { SW.idle(test); }
  } });
  return h("div", { class: "alerts" }, line, slot, test, testBox);
}
