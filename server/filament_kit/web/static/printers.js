// Printers tab: live status (SSE), camera (MJPEG in an <img>), controls, filament per AMS unit with load / unload,
// usage with undo, re-map, optional Web Push. Loaded before app.js (which calls printersTab() when the printers module is on).
// Everything from the server goes in through textContent / element properties, never innerHTML.
"use strict";
function printersTab() {
  const API = BASE + "/api/printers";
  const HEX = /^[0-9A-Fa-f]{6}$/;
  let printers = [], current = null, es = null, lastStatus = null, camOn = false;

  const picker = h("select", { on: { change: () => choose(picker.value) } });
  const head = h("div", { class: "card" });
  const alerts = h("div");
  const controls = h("div", { class: "row" });
  const camBox = h("div", { class: "card hidden" });
  const camBtn = h("button", { class: "secondary", textContent: "Show camera", on: { click: () => camera(!camOn) } });
  const units = h("div");
  const loadBox = h("div", { class: "card hidden" });   // the load picker: outside `units`, which every update redraws
  const slotMsg = resultLine();   // the answer to Load and Unload
  const usageBox = h("div");
  const mapBox = h("div");
  const mapLine = resultLine();   // a map poll that fails keeps the map and says how old it is (04 3.5)
  const reportBox = h("div");     // the saved report's link: outside mapBox, which loadMap redraws
  const repLine = resultLine();   // the answer to Collect a report
  const manualBox = h("div");     // Map by loading filament: outside mapBox, which loadMap redraws
  const manualLine = resultLine();   // its notes and refusals, and a poll that fails: outside manualBox, which every step redraws
  const msg = resultLine();       // the answer to Pause, Resume, Stop and the light
  const conn = h("p", { class: "result", role: "status" });   // the live stream: Reconnecting…
  const manageBox = h("div");     // Manage printers: add, rename, address, Access Code, certificate, forget
  const manageNote = resultLine();   // what a change in Manage printers did
  const el = h("section", { class: "hidden" },
    picker, head, conn, alerts, controls, camBtn, camBox, msg,
    h("h2", { textContent: "Filament" }), units, slotMsg, loadBox,
    h("h2", { textContent: "Usage" }), usageBox,
    h("h2", { textContent: "Slots" }), mapBox, mapLine, reportBox, repLine, manualBox, manualLine,
    h("h2", { textContent: "Manage printers" }), manageBox, manageNote);

  async function pj(path, body) {
    return api(path ? "printers/" + path : "printers", body === undefined ? {} : { method: "POST", body });
  }
  // A confirmation or a question is a sheet (04 12), never window.confirm / window.prompt. openHere (app.js) gives it the
  // same-address history entry, so the phone's Back closes it. A refusal from run() shows inside the sheet (SW.ask asks err.text()),
  // in the words of 04 3.6 (the Hub's own text as given).
  function sheetAsk(o) {
    const run = o.run;
    return SW.ask({ open: openHere, ...o, run: run && (async (v, c) => { try { return await run(v, c); } catch (e) { throw Object.assign(e, { text: () => says(e) }); } }) });
  }
  const lineNodes = (lines) => [lines].flat().flatMap((t, i) => (i ? [h("br"), t] : [t]));   // a result of several lines
  const needs = (key) => (v) => (v.trim() ? null : SW.t(key));
  const codeField = (hint) => SW.field({ type: "secret", label: SW.t("common_field_access_code"), hint, check: needs("common_error_access_code") });
  const printerName = () => { const p = printers.find((x) => x.id === current); return (p && p.name) || current; };

  async function load() {
    const loading = SW.loading(head, { thing: SW.t("nav_printers"), items: 1 });
    try {
      printers = (await pj("")).printers;
      loading.done();
    } catch (e) { const line = resultLine(); loading.done(line); failed(line, e, load); return; }
    picker.replaceChildren(...printers.map((p) => h("option", { value: p.id, textContent: p.name || p.id })));
    picker.classList.toggle("hidden", printers.length < 2);
    manageClosed();
    if (!printers.length) { head.replaceChildren(h("p", { class: "muted", textContent: "No printer is set up on the server yet: add one under Manage printers." })); manage(); return; }
    let want = null;
    try { want = localStorage.getItem("spoolwarden.printer") || localStorage.getItem("printer"); } catch {}   // "printer" is the key before S3.3
    choose(printers.some((p) => p.id === want) ? want : printers[0].id);
  }

  function choose(id) {
    current = id; picker.value = id;
    try { localStorage.setItem("spoolwarden.printer", id); } catch {}
    camera(false); camBtn.classList.toggle("hidden", !camKind()); closeLoad(); clear(slotMsg); clear(msg);
    usageBox.replaceChildren(); mapBox.replaceChildren(); clear(mapLine); clear(repLine);   // the last printer's data must not show for this one
    stream(); loadUsage(); loadMap(); manualStop(); manualBox.replaceChildren(); clear(manualLine); clearReport();
  }
  // "mjpeg" (an <img>) or "hls" (a <video>); null: this model has no camera we can show
  const isKlipper = () => (printers.find((x) => x.id === current) || {}).family === "klipper";
  function camKind() {
    const p = printers.find((x) => x.id === current);
    const k = p && p.camera && p.camera.kind;
    return k === "mjpeg" || k === "hls" ? k : null;
  }

  // ----- live status -----
  function stream() {
    if (es) es.close();
    if (!current) return;
    lastStatus = null;
    es = new EventSource(`${API}/${encodeURIComponent(current)}/events`);
    es.onmessage = (ev) => {
      let d; try { d = JSON.parse(ev.data); } catch { return; }
      if (d.error) { put(conn, "warn", d.error); return; }   // the Hub's own text, said once while it stays the same
      const was = lastStatus && isLive(lastStatus.status);
      clear(conn); lastStatus = d; render(d);
      if (was && !isLive(d.status)) loadUsage();      // a job ended: its usage entry is new
    };
    es.onopen = () => { clear(conn); };
    es.onerror = () => { put(conn, "run", SW.t("printer_reconnecting")); };
  }
  function stopStream() { if (es) { es.close(); es = null; } }

  const isLive = (s) => ["RUNNING", "PAUSE", "PREPARE"].includes((s || {}).gcode_state);
  function fmtMin(m) { return m > 0 ? (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`) : ""; }
  function render(d) {
    const s = d.status || {}, p = d.printer || {};
    const live = isLive(s);
    head.replaceChildren(
      h("h3", {}, p.name || current, h("span", { class: "pill", textContent: p.state === "connected" ? (s.gcode_state || "") : (p.state || "") })),
      s.job ? h("p", { textContent: s.job }) : null,
      live ? h("progress", { max: 100, value: s.percent || 0 }) : null,
      live ? h("p", { class: "muted", textContent: [`${s.percent || 0}%`, s.stage, s.total_layers ? `layer ${s.layer ?? "?"}/${s.total_layers}` : "", fmtMin(s.remaining_min)].filter(Boolean).join(" · ") }) : null,
      h("p", { class: "muted", textContent: (s.temps || []).map((t) => `${t.name} ${t.cur ?? "-"}${t.tgt ? "/" + t.tgt : ""}°`).join(" · ") }));
    const a = [];
    for (const x of s.hms || []) a.push(note("bad", x.text || SW.t("printer_alert_code", { code: x.code })));
    for (const n of s.notes || []) a.push(h("p", { class: "muted", textContent: n }));
    alerts.replaceChildren(...a);
    drawControls(s, live);
    drawUnits(s);
  }

  function drawControls(s, live) {
    const b = [];
    if (s.gcode_state === "RUNNING") b.push(h("button", { class: "secondary", textContent: "Pause", on: { click: () => cmd("pause") } }));
    if (s.gcode_state === "PAUSE") b.push(h("button", { textContent: "Resume", on: { click: () => cmd("resume") } }));
    if (live) b.push(h("button", { class: "danger", textContent: "Stop print", on: { click: stop } }));
    if (s.light) b.push(h("button", { class: "secondary", textContent: s.light === "on" ? "Light off" : "Light on", on: { click: () => cmd(s.light === "on" ? "light_off" : "light_on") } }));
    controls.replaceChildren(...b);
  }
  // what each command is called, and the sentence that says it was done (04 3.2)
  const COMMANDS = { pause: ["printer_pause", "printer_result_paused"], resume: ["printer_resume", "printer_resumed_line"],
    stop: ["printer_stop", "printer_stopped_line"], light_on: ["printer_light_on", "printer_light_on_line"],
    light_off: ["printer_light_off", "printer_result_light_off"] };
  async function cmd(action, confirm) {
    const [name, done] = COMMANDS[action];
    await act(msg, SW.t("common_working"), async () => {
      const r = await pj(`${encodeURIComponent(current)}/command`, confirm ? { action, confirm: true } : { action });
      const inner = r.reply || {}, why = (inner.reply || {}).reason;
      if (inner.ok === false) {                                  // the printer refused: its reason as sent, else our own sentence
        return { kind: "bad", text: typeof why === "string" && why ? SW.t("printer_said_no", { error: why }) : SW.t("common_result_refused", { name: printerName(), action: SW.t(name) }) };
      }
      SW.toast(SW.t(done));
      return SW.t(done);
    }, { alert: action === "stop" });
  }
  async function stop() {
    const job = ((lastStatus || {}).status || {}).job, printer = printerName();
    const go = await sheetAsk({ kind: "destructive", title: SW.t("printer_stop_dialog_title"),
      text: job ? SW.t("printer_stop_dialog_body", { job, printer }) : SW.t("printer_stop_dialog_body_nojob", { printer }),
      cancel: SW.t("printer_stop_keep"), confirm: SW.t("printer_stop") });
    if (go) cmd("stop", true);
  }

  // ----- camera -----
  function camera(on) {
    const kind = camKind();
    for (const m of camBox.querySelectorAll("img, video")) { m.removeAttribute("src"); if (m.load) m.load(); }  // drops the connection: the camera stops
    camBox.replaceChildren();
    if (on && !kind) on = false;
    camOn = on;
    camBtn.textContent = on ? "Hide camera" : "Show camera";
    camBox.classList.toggle("hidden", !on);
    if (!on) return;
    const base = `${API}/${encodeURIComponent(current)}`;
    if (kind === "mjpeg") {
      camBox.append(h("img", { class: "cam", alt: "Printer camera", on: { error: () => camFail() }, src: `${base}/camera.mjpeg` }));
      return;
    }
    const v = h("video", { class: "cam", playsInline: true, muted: true, autoplay: true, controls: true });
    v.muted = true;
    if (!v.canPlayType("application/vnd.apple.mpegurl")) {
      camBox.append(note("bad", SW.t("printer_camera_no_hls")));
      return;
    }
    v.addEventListener("error", () => camFail());
    camBox.append(v);
    v.src = `${base}/camera/index.m3u8`;
    v.play().catch(() => {});
  }
  function camFail() {
    if (!camOn) return;
    camBox.replaceChildren(note("bad", SW.t("printer_camera_failed")));
  }

  // ----- filament per unit -----
  function drawUnits(s) {
    const cards = [];
    for (const u of s.ams || []) {
      const rows = (u.slots || []).map((sl) => {
        const sp = sl.spool;
        const col = HEX.test(sl.color_hex || "") ? "#" + sl.color_hex : "transparent";
        const state = sl.present === false ? "empty" : sl.reading ? "reading" : "";
        const sw = h("span", { class: "sw" });
        sw.style.background = col;      // CSSOM, not a style attribute (the CSP allows no inline style)
        return h("div", { class: "slot" + (sl.active ? " active" : "") },
          sw,
          h("b", { textContent: sl.label }),
          h("span", { textContent: sp ? sp.name : (sl.type || (state || "unknown")) }),
          h("span", { class: "muted", textContent: sp && sp.remaining_weight != null ? `${Math.round(sp.remaining_weight)} g` : state }),
          h("button", { class: "secondary fit", textContent: "Load", on: { click: () => openLoad(sl) } }),
          sp ? h("button", { class: "secondary fit", textContent: "Unload", on: { click: () => unload(sl, sp) } }) : null);
      });
      cards.push(h("div", { class: "card" }, h("h3", { textContent: u.type_name ? `${u.label} · ${u.type_name}` : u.label }), ...rows));
    }
    units.replaceChildren(...(cards.length ? cards : [h("p", { class: "muted", textContent: "No AMS units reported." })]));
  }

  // ----- load / unload (the kit's slot routes; the same refusals as the Android app) -----
  // dryAgain: a dry run asked for while another slot call ran; the latest pick's runs when that call ends
  let slotBusy = false, loadSlot = null, loadSpool = null, dryAgain = null;
  const slotPath = (label) => `${encodeURIComponent(current)}/slots/${encodeURIComponent(label)}`;
  function slotSay(lines, kind) { SW.result(slotMsg, kind, lineNodes(lines)); }
  function spoolTitle(s) { return `${s.vendor || ""} ${s.name || ""}`.trim() || `spool #${s.id}`; }

  function openLoad(sl) {
    loadSlot = sl.label; loadSpool = null; clear(slotMsg);
    const q = h("input", { type: "search", placeholder: "Search: brand, colour, material", enterKeyHint: "search",
                           on: { keydown: (e) => { if (e.key === "Enter") search(); } } });
    const results = h("div", { class: "list" });
    const line = resultLine();         // the answer to Use the last tapped tag and to Search
    const plan = resultLine();         // the plan of a pick, or why it failed
    const go = h("button", { textContent: "Load", on: { click: () => doLoad(false, plan, go) } });
    const picked = h("p", { class: "muted", textContent: "Pick a spool: tap its tag on a reader, or search." });
    function pick(s, btn) {
      for (const b of results.querySelectorAll(".pick")) b.classList.toggle("on", b === btn);
      loadSpool = s; clear(plan); disabled(go, SW.t("spool_load_working_out"));
      picked.textContent = `S${s.id} ${spoolTitle(s)} (${s.location || "?"}${s.remaining_g != null ? ", " + Math.round(s.remaining_g) + " g" : ""})`;
      doLoad(true, plan, go);           // the dry run first: the user sees the plan before anything is sent
    }
    function row(s) {
      const b = h("button", { class: "pick", on: { click: () => pick(s, b) } }, h("strong", { textContent: `S${s.id} ` }), spoolTitle(s),
        h("div", { class: "muted", textContent: `${s.location || "?"} · ${s.remaining_g ?? "?"} g` }));
      return b;
    }
    async function lastTap(button) {
      await act(line, SW.t("common_working"), async () => {
        const t = await pj("tagged");
        if (!t.spool) {
          results.replaceChildren(h("p", { class: "muted", textContent: t.nfc_id ? `Tag ${t.nfc_id} is not linked to a spool.` : "No tag read yet: tap one." }));
          return null;
        }
        const b = row(t.spool);
        results.replaceChildren(b); pick(t.spool, b);
        return null;
      }, { button });
    }
    async function search(button) {
      await act(line, SW.t("common_searching"), async () => {
        const res = await api(`find?q=${encodeURIComponent(q.value)}&sealed=0`);
        const rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ id: s.spool_id, vendor: f.vendor, name: f.name, location: s.location, remaining_g: s.remaining_g })));
        results.replaceChildren(...(rows.length ? rows.slice(0, 60).map(row) : [h("p", { class: "muted", textContent: "No spools match." })]));
        return null;
      }, { button });
    }
    loadBox.replaceChildren(
      h("h3", { textContent: `Load into ${sl.label}` }),
      h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Use the last tapped tag", on: { click: (e) => lastTap(e.currentTarget) } })),
      h("div", { class: "row" }, q, h("button", { class: "fit", textContent: "Search", on: { click: (e) => search(e.currentTarget) } })),
      line, results, picked, plan,
      h("div", { class: "row" }, go, h("button", { class: "secondary", textContent: "Cancel", on: { click: closeLoad } })));
    disabled(go, SW.t("spool_load_pick_first"), () => q);          // until a spool is picked and its plan is shown
    loadBox.classList.remove("hidden");
    loadBox.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function closeLoad() { loadSlot = loadSpool = null; dryAgain = null; loadBox.classList.add("hidden"); loadBox.replaceChildren(); }
  function slotDone() {
    slotBusy = false;
    const again = dryAgain; dryAgain = null;
    if (again && loadSpool) doLoad(true, again.plan, again.go);
  }

  // dry: the plan (preset, nozzle, spools going back); then Load sends `dry_run: false`
  async function doLoad(dry, plan, go) {
    if (!loadSpool || !loadSlot) return;
    if (slotBusy) { if (dry) dryAgain = { plan, go }; return; }   // not dropped: runs for the latest pick after
    const s = loadSpool, label = loadSlot;
    slotBusy = true; disabled(go, SW.t(dry ? "spool_load_working_out" : "common_load_wait"));
    SW.result(plan, "run", SW.t(dry ? "spool_load_working_out" : "common_load_wait"));
    try {
      const r = await pj(`${slotPath(label)}/load`, dry ? { spool_id: s.id, dry_run: true } : { spool_id: s.id, dry_run: false });
      if (loadSpool !== s) return;      // another spool was picked meanwhile
      const moved = (r.moved_back || []).filter((m) => m.id !== s.id)
        .map((m) => SW.t("spool_load_plan_goes_back", { id: m.id ?? "?", slot: label, location: m.location || SW.t("spool_load_previous_place") }));
      if (dry) {
        const nozzle = r.nozzle_assumed ? SW.t("spool_load_plan_nozzle_assumed", { mm: r.nozzle_mm ?? 0.4 })
          : (r.nozzle_mm ? SW.t("spool_load_plan_nozzle", { mm: r.nozzle_mm }) : "");
        SW.result(plan, (r.problems || []).length ? "warn" : "ok", lineNodes([SW.t("spool_load_plan", { spool: spoolTitle(s), slot: label }),
          SW.t("spool_load_plan_preset", { preset: (r.preset && r.preset.name) || SW.t("common_value_none") }), nozzle, ...moved, ...(r.problems || [])].filter(Boolean)));
        disabled(go, null);
      } else {
        closeLoad();
        SW.toast(SW.t(r.confirmed ? "spool_load_loaded_toast" : "spool_load_sent_toast", { slot: label }));
        slotSay([SW.t(r.confirmed ? "spool_load_loaded_toast" : "spool_load_sent_line", { slot: label }), ...moved, ...(r.problems || [])], "ok");
      }
    } catch (e) {
      if (loadSpool === s) {
        failed(plan, e, () => doLoad(dry, plan, go));
        disabled(go, dry ? SW.t("spool_load_see_above") : null);   // a refused Load can be pressed again; a failed plan has to be picked again
      }
    } finally { slotDone(); }
  }

  // Spoolman only (the printer's slot setting stays): the dry run says where the spool goes, then a confirm
  async function unload(sl, sp) {
    if (slotBusy) return;
    slotBusy = true; SW.result(slotMsg, "run", SW.t("common_checking"));
    try {
      const plan = await pj(`${slotPath(sl.label)}/unload`, { dry_run: true });
      const where = plan.location || ((plan.moved_back || [])[0] || {}).location || SW.t("spool_load_previous_place");
      const name = sp.name || `spool #${sp.id}`;
      clear(slotMsg);
      const r = await sheetAsk({ kind: "confirm", title: SW.t("printer_unload_title", { slot: sl.label }),
        text: SW.t("printer_unload_body", { spool: name, slot: sl.label, location: where }), confirm: SW.t("common_unload"),
        run: () => pj(`${slotPath(sl.label)}/unload`, { dry_run: false }) });
      if (!r) return;
      SW.toast(SW.t("printer_unload_line", { name, slot: sl.label }));
      slotSay([SW.t("printer_unload_line", { name, slot: sl.label }),
        ...(r.moved_back || []).map((m) => SW.t("printer_unload_moved_back", { id: m.id ?? "?", location: m.location || SW.t("spool_load_previous_place") }))], "ok");
    } catch (e) { failed(slotMsg, e, () => unload(sl, sp)); } finally { slotDone(); }
  }

  // ----- usage + re-map -----
  async function loadUsage() {
    const id = current;
    await fill(usageBox, SW.t("printer_group_used"), async () => {
      const r = await pj(`${encodeURIComponent(id)}/usage`);
      if (id !== current) return null;
      const rows = (r.entries || []).slice(0, 20).map((e) => h("div", { class: "row" },
        h("span", { textContent: `${(e.at || "").replace("T", " ").slice(0, 16)} · ${e.job || "job"} · ${e.slot || ""} · ${e.grams ?? "?"} g${e.undone ? " (undone)" : ""}` }),
        e.undone ? null : h("button", { class: "secondary", textContent: "Undo", on: { click: () => undo(e) } })));
      return rows.length ? rows : [h("p", { class: "muted", textContent: "Nothing recorded in the last days." })];
    }, { quiet: usageBox.childElementCount > 0 });      // a refresh after a job keeps what is shown until the new list arrives
  }
  async function undo(e) {
    const when = (e.at || "").replace("T", " ").slice(0, 16);
    const back = await sheetAsk({ kind: "confirm", title: SW.t("printer_usage_undo_title"), cancel: SW.t("common_keep"), confirm: SW.t("printer_usage_undo_confirm"),
      text: SW.t("printer_usage_undo_body", { grams: e.grams ?? "?", job: e.job || "?", slot: e.slot || "?", time: when }),
      run: () => pj(`${encodeURIComponent(current)}/usage/${encodeURIComponent(e.id)}/undo`, {}) });
    if (!back) return;
    SW.toast(SW.t("printer_used_put_back", { grams: e.grams ?? "?" }));
    SW.result(msg, "ok", SW.t("printer_used_put_back", { grams: e.grams ?? "?" }));
    loadUsage();
  }
  let mapTimer = null, mapAt = null;      // mapAt: when the map last arrived
  // the map as the Hub gave it; Re-map and Map by loading filament wait while a mapping runs, and say so
  function mapNodes(m) {
    const running = m.state === "running";
    const collect = h("button", { class: m.report_wanted ? "" : "secondary", textContent: "Collect a report", on: { click: (e) => collectReport(e.currentTarget) } });
    const remapBtn = h("button", { class: "secondary", textContent: running ? "Mapping…" : "Re-map slots", on: { click: remap } });
    const byLoad = h("button", { class: "secondary", textContent: "Map by loading filament", on: { click: (e) => manualMap(e.currentTarget) } });
    const buttons = h("div", { class: "row" }, collect, remapBtn, byLoad);
    disabled(remapBtn, running ? SW.t("printers_map_running_reason") : null);
    disabled(byLoad, running ? SW.t("printers_map_running_reason") : null);
    return [
      h("p", { class: "muted", textContent: m.outcome_text ? `${m.outcome_text}${running && m.step ? " " + m.step : ""}`
        : `${m.calibrated ? "Mapped" : "Not mapped yet"} · ${m.state}${m.step ? " · " + m.step : ""}${m.stale ? " · layout changed" : ""}` }),
      ...(m.next_step && !running ? [h("p", { textContent: m.next_step })] : []),
      ...(m.problems_old && (m.problems || []).length ? [h("p", { class: "muted", textContent: "From an earlier mapping, it may be fixed by now. Re-map the slots to check:" })] : []),
      ...(m.problems || []).map((t) => (m.problems_old ? h("p", { class: "muted", textContent: t }) : note("bad", t))),
      ...(m.notes || []).map((t) => h("p", { class: "muted", textContent: t })),
      ...(m.report_wanted ? [h("p", { class: "muted", textContent: m.report_why || "A printer report would help." })] : []),
      // every printer (interface parity, 2026-11-10); it stands out when the kit says a report would help
      buttons];
  }
  // poll: the 3 s refresh while a mapping runs; a poll that fails keeps the map and says how old it is (04 3.5)
  async function loadMap(poll) {
    clearTimeout(mapTimer);
    const id = current;
    if (isKlipper()) {      // the kit's slot map and report are for Bambu printers; Klipper has only Map by loading filament
      mapBox.replaceChildren(h("button", { class: "secondary", textContent: "Map by loading filament", on: { click: (e) => manualMap(e.currentTarget) } }));
      return;
    }
    const again = () => { mapTimer = setTimeout(() => loadMap(true), 3000); };
    const draw = async () => {
      const m = await pj(`${encodeURIComponent(id)}/map`);
      if (id !== current) return null;
      mapAt = Date.now(); clear(mapLine);
      if (m.state === "running") again();
      return mapNodes(m);
    };
    if (!poll) { mapAt = null; await fill(mapBox, SW.t("printer_map_title_bambu"), draw); return; }
    try { const kids = await draw(); if (kids && id === current) mapBox.replaceChildren(...kids); }
    catch (e) { if (id === current) { stale(mapLine, mapAt ?? Date.now()); again(); } }
  }
  // The report holds no serial, address, name or account id: the server builds it from an allow-list.
  let reportUrl = null;
  function clearReport() { if (reportUrl) URL.revokeObjectURL(reportUrl); reportUrl = null; reportBox.replaceChildren(); }
  async function collectReport(button) {
    await act(repLine, SW.t("common_working"), async () => {
      const r = await pj(`${encodeURIComponent(current)}/report`, {});
      clearReport();      // one link at a time; the old one's object URL is freed
      reportUrl = URL.createObjectURL(new Blob([r.xml], { type: "application/xml" }));
      const a = h("a", { href: reportUrl, download: r.name, textContent: `Save ${r.name}, then attach it to a "Printer report" issue on the project's GitHub` });
      reportBox.replaceChildren(
        ...(r.live === false ? [h("p", { class: "muted", textContent: "The printer could not be reached: this report is built from what the kit saved." })] : []),
        h("p", {}, a));
      return null;
    }, { button });
  }
  // ----- Map by loading filament: the owner loads each slot, the printer says which one it sees (the kit's session,
  // shared with the setup page and the Android app; nothing is sent to the printer) -----
  let manual = null;      // {id, v, timer, shown, picks}
  function manualStop() { if (manual) clearTimeout(manual.timer); manual = null; }
  const mpath = (id, what) => `${encodeURIComponent(id)}/manual-map${what ? "/" + what : ""}`;
  async function manualMap(button) {
    const id = current;
    await act(manualLine, SW.t("common_working"), async () => {
      const v = await pj(mpath(id, "start"), {});
      if (id !== current) return null;
      manualStop();
      manual = { id, v, timer: null, shown: null, picks: {}, fails: 0, okAt: Date.now() };
      drawManual();
      manual.timer = setTimeout(manualTick, 2000);
      return null;
    }, { button });
  }
  async function manualSend(what, body) {
    const m = manual;
    if (!m) return;
    try {
      const r = await pj(mpath(m.id, what), { session: m.v.session, ...body });
      if (m !== manual) return;
      clear(manualLine);
      if (what === "offer") { m.v.offer_report = false; drawManual(); SW.result(manualLine, "ok", r.message); return; }
      m.v = r; drawManual();
    } catch (e) { if (m === manual) failed(manualLine, e); }
  }
  async function manualTick() {
    const m = manual;
    if (!m) return;
    if (!m.v.open) { drawManual(); return; }
    const was = JSON.stringify(m.v);
    try { m.v = await pj(mpath(m.id)); m.okAt = Date.now(); } catch (e) {
      if (m !== manual) return;
      // a Wi-Fi blip: the session is still open on the kit, so keep asking, slower each time (like the Android screen);
      // what is on the screen stays, with how old it is (04 3.5)
      if (++m.fails >= 8) { manualBox.replaceChildren(); failed(manualLine, e, () => manualMap()); manual = null; return; }
      stale(manualLine, m.okAt);
      m.timer = setTimeout(manualTick, Math.min(2000 * 2 ** m.fails, 20000));
      return;
    }
    if (m !== manual) return;
    if (m.fails) clear(manualLine);
    if (JSON.stringify(m.v) !== was || m.fails) { m.fails = 0; drawManual(); }   // unchanged: a choice being made stays as it is
    m.timer = setTimeout(manualTick, 2000);
  }
  function drawManual() {
    const m = manual, v = m.v, st = v.step;
    // a redraw rebuilds the selects: a choice the owner is making survives it while the same position is asked
    const pos = st ? st.position.id : null;
    const prev = pos === m.shown ? Object.fromEntries(Object.entries(m.picks).map(([k, e]) => [k, e.value])) : {};
    m.shown = pos; m.picks = {};
    const keep = (k, el) => {
      if (!el) return el;
      m.picks[k] = el;
      if (prev[k] !== undefined && [...el.options].some((o) => o.value === prev[k])) el.value = prev[k];
      return el;
    };
    const status = (q) => q.status === "confirmed" ? `confirmed (${q.reported_label}${q.nozzle ? ", " + q.nozzle + " nozzle" : ""})`
      : q.status === "by_hand" ? `entered by hand (${q.reported_label})` : q.status;
    let ask = null;
    if (st && st.seen && st.ask) {
      const other = keep("other", h("select", { ariaLabel: "The position you loaded" }, ...v.positions.map((q) => h("option", { value: q.id, textContent: q.label, selected: q.id === st.position.id }))));
      const noz = keep("noz", v.dual_nozzle && !st.seen.nozzle_reported ? h("select", { ariaLabel: "Nozzle" }, h("option", { value: "right", textContent: "right nozzle" }), h("option", { value: "left", textContent: "left nozzle" })) : null);
      const nozzle = () => (st.seen.nozzle_reported ? st.seen.nozzle : noz ? noz.value : null);
      ask = h("div", {},
        h("p", { textContent: st.ask }),
        h("div", { class: "row" }, noz,
          h("button", { textContent: "Yes", on: { click: () => manualSend("confirm", { position: st.position.id, reported: st.seen.reported, nozzle: nozzle() }) } })),
        h("div", { class: "row" }, h("label", {}, "No, I loaded ", other),
          h("button", { class: "secondary", textContent: "Save that", on: { click: () => manualSend("confirm", { position: other.value, reported: st.seen.reported, nozzle: nozzle() }) } })));
    } else if (st && !v.reports_loads) {
      const pick = keep("pick", h("select", { ariaLabel: "The slot it is in" }, ...(v.choices || []).map((c, i) => h("option", { value: String(i), textContent: c.label }))));
      ask = h("div", { class: "row" }, pick, h("button", { textContent: "Save (not checked by the printer)", on: { click: () => manualSend("confirm", { position: st.position.id, reported: v.choices[Number(pick.value)].reported, by_hand: true }) } }));
    } else if (st && st.seen && !st.seen.settled) {
      ask = h("p", { class: "muted", textContent: "The printer reports a change; waiting for it to settle…" });
    }
    manualBox.replaceChildren(h("div", { class: "card" },
      h("h3", { textContent: "Map by loading filament" }),
      h("p", { textContent: st ? st.say : v.summary }),
      ask,
      st ? h("div", { class: "row" },
        h("button", { class: "secondary", textContent: `Skip ${st.position.label}`, on: { click: () => manualSend("skip", { position: st.position.id }) } }),
        h("button", { class: "secondary", textContent: "Stop", on: { click: () => manualSend("stop", {}) } })) : null,
      st ? h("p", { class: "muted", textContent: v.summary }) : null,
      h("ul", {}, ...v.positions.map((q) => h("li", { textContent: `${q.label}: ${status(q)}` }))),
      !v.open && v.offer_report ? h("div", {},
        h("p", { textContent: "Share this map in a printer report, so other owners of this model benefit? Nothing is sent unless you choose to." }),
        h("div", { class: "row" },
          h("button", { class: "secondary", textContent: "Yes, how do I share it?", on: { click: () => manualSend("offer", { share: true }) } }),
          h("button", { class: "secondary", textContent: "No thanks", on: { click: () => manualSend("offer", { share: false }) } }))) : null));
    if (!v.open) loadMap();
  }
  // ----- Manage printers: the kit's own printer list (what the setup page's Printers tab edits), changed here too -----
  function manageClosed() {
    if (!manageBox.firstChild) manageBox.replaceChildren(h("button", { class: "secondary", textContent: "Add or change printers", on: { click: () => manage() } }));
  }
  // After a change the sheet has closed: the list and the page are read again.
  async function manageAfter(done, r) {
    await manage(`${done}${r && r.note ? " " + r.note : ""}`, true);
    const was = current;
    await load();
    if (printers.some((p) => p.id === was)) choose(was);
  }
  // A change asked for in a sheet (04 12): send(values) gives [path, body, done text]; it is sent from the sheet, so a
  // refusal shows inside it with the typed values kept; the lists are read again once it has closed.
  async function change(o, send) {
    let r = null, done = "";
    const ok = await sheetAsk({ kind: "entry", busy: SW.t("common_saving"), ...o, run: async (v) => {
      const [path, body, text] = send(v.map((x) => x.trim()));
      r = await pj(path, body); done = text;
    } });
    if (ok) await manageAfter(done, r);
  }
  // a whole number from 1 to 65535, or null
  function parsePort(t) { const n = /^\d{1,5}$/.test(t) ? Number(t) : 0; return n >= 1 && n <= 65535 ? n : null; }
  const addressField = (label, hint, value) => SW.field({ label, hint, value, mono: true, check: needs("common_error_address"), attrs: { autocapitalize: "off", spellcheck: "false" } });
  const portField = (value) => SW.field({ type: "number", label: SW.t("printer_field_port"), value, check: (v) => (parsePort(v.trim()) === null ? SW.t("common_error_port") : null) });
  const keyField = (o) => SW.field({ type: "secret", label: SW.t("common_moonraker_key"), ...o });
  function manageRow(p, changes) {
    const bambu = p.family !== "klipper", id = encodeURIComponent(p.id), name = p.name || p.id;
    const where = bambu ? p.ip : p.host;
    const edit = (body, done) => [`${id}/edit`, body, done];
    const buttons = !changes ? [] : p.configured ? [
      h("button", { class: "secondary", textContent: "Rename", on: { click: () =>
        change({ title: SW.t("printers_rename_title"), confirm: SW.t("common_rename"),
          fields: [SW.field({ label: SW.t("common_field_name"), value: name, check: needs("common_error_name") })] },
        ([n]) => edit({ name: n }, SW.t("printer_set_renamed", { name: n }))) } }),
      h("button", { class: "secondary", textContent: "Address", on: { click: () => {
        // an address change asks for the Access Code again, pinned or not (staging 2026-11-12); a Klipper printer's stored key
        // goes only to the new address, so it is asked for too (review R103; empty means none)
        const addr = bambu ? addressField(SW.t("printer_address_bambu_label"), SW.t("printer_address_bambu_help"), where || "")
          : addressField(SW.t("common_address"), SW.t("printer_address_klipper_help"), where || "");
        const code = bambu ? codeField(SW.t("printer_address_code_help")) : null;
        const key = bambu ? null : keyField({ optional: true, hint: SW.t("printer_address_key_help") });
        change({ title: SW.t("printers_change_address_title", { printer: name }), confirm: SW.t("printers_change_address"), fields: [addr, code, key].filter(Boolean) },
          ([a, c]) => edit({ address: a, ...(bambu ? { access_code: c } : { api_key: c }) }, SW.t("printer_set_address_changed", { address: a })));
      } } }),
      bambu ? h("button", { class: "secondary", textContent: "Access Code", on: { click: () =>
        change({ title: SW.t("printers_access_code_title", { printer: name }), confirm: SW.t("printers_replace_access_code"), fields: [codeField(SW.t("common_hint_access_code"))] },
          ([c]) => edit({ access_code: c }, SW.t("printer_set_code_replaced"))) } }) : null,
      bambu && p.pinned ? h("button", { class: "secondary", textContent: "Forget certificate", on: { click: () =>
        change({ kind: "destructive", title: SW.t("printers_forget_cert_title", { printer: name }), text: SW.t("printer_set_cert_text", { printer: name }),
          confirm: SW.t("printers_forget_cert"), fields: [codeField(SW.t("common_hint_access_code"))] },
          ([c]) => edit({ unpin: true, access_code: c }, SW.t("printer_set_cert_forgotten"))) } }) : null,
      bambu ? null : h("button", { class: "secondary", textContent: "API key", on: { click: () =>
        change({ title: SW.t("printers_key_title", { printer: name }), confirm: SW.t("common_save_key"),
          fields: [keyField({ check: needs("printers_error_key") })] },
          ([k]) => edit({ api_key: k }, SW.t("printer_set_key_saved"))) } }),
      h("button", { class: "secondary", textContent: "Forget", on: { click: async () => {
        let r = null;
        const ok = await sheetAsk({ kind: "destructive", title: SW.t("printers_forget_title", { printer: name }),
          text: SW.t(bambu ? "printers_forget_body_bambu" : "printers_forget_body_klipper", { product: SW.t("app_name") }), confirm: SW.t("printers_forget"),
          busy: SW.t("common_working"), run: async () => { r = await pj(`${id}/forget`, {}); } });
        if (ok) await manageAfter(SW.t("printers_forgotten", { printer: name }), r);
      } } }),
    ] : bambu && p.ip ? [
      h("button", { textContent: "Add", on: { click: () => {
        const model = p.model_name || name;
        change({ title: SW.t("printer_add_title", { model }), text: SW.t("add_model_found", { address: p.ip }), confirm: SW.t("common_add_printer"),
          busy: SW.t("printer_add_connecting"),
          fields: [codeField(SW.t("common_hint_access_code")), SW.field({ label: SW.t("common_field_name_optional"), placeholder: model })] },
          ([c, n]) => ["add", { serial: p.id, access_code: c, name: n || name }, SW.t("printers_added_connecting")]);
      } } }),
    ] : [];
    return h("div", { class: "card" },
      h("p", {}, h("b", { textContent: name }), ` · ${p.model_name || p.model || (bambu ? "Bambu" : "Klipper")} · ${where || "no address yet"} · ${p.configured ? String(p.state).replace(/_/g, " ") : "seen on the network, not added"}`),
      h("div", { class: "row" }, ...buttons));
  }
  async function manage(note, ok) {
    let list, changes;
    const loading = SW.loading(manageBox, { thing: SW.t("nav_printers"), items: 2 });
    try { ({ printers: list, changes } = await pj("manage")); loading.done(); }
    catch (e) { const line = resultLine(); loading.done(line); failed(line, e, () => manage(note, ok)); return; }
    const klipperAdd = h("button", { class: "secondary", textContent: "Add a Klipper printer", on: { click: () =>
      change({ title: SW.t("common_add_klipper_printer"), confirm: SW.t("common_add_printer"), busy: SW.t("printer_add_connecting"),
        fields: [addressField(SW.t("common_address"), SW.t("printer_address_klipper_help"), ""), portField("7125"), SW.field({ label: SW.t("common_field_name_optional") })] },
        ([host, port, n]) => ["add", { family: "klipper", host, port: parsePort(port), ...(n ? { name: n } : {}) }, SW.t("printers_added_connecting")]) } });
    if (note) SW.result(manageNote, ok ? "ok" : "bad", note); else clear(manageNote);
    manageBox.replaceChildren(
      h("p", { class: "muted", textContent: changes
        ? "A Bambu printer on the network shows up here by itself; add it with its Access Code. Anyone on the home network can use this page."
        : "Read-only here: printer changes from the public address are off. Open this page on the home network to add, change or forget a printer, or turn them on in the setup page's Settings." }),
      ...list.map((p) => manageRow(p, changes)), ...(changes ? [h("div", { class: "row" }, klipperAdd)] : []));
  }
  async function remap() {
    const go = await sheetAsk({ kind: "confirm", title: SW.t("printers_map_title", { printer: printerName() }), text: SW.t("printers_map_body"),
      confirm: SW.t("printers_map_slots"), run: () => pj(`${encodeURIComponent(current)}/map`, {}) });
    if (go) loadMap();
  }

  document.addEventListener("visibilitychange", () => {
    if (el.classList.contains("hidden")) return;
    if (document.hidden) { stopStream(); camera(false); } else if (current) stream();
  });
  let loaded = false;
  return {
    el,
    enter() { if (!loaded) { loaded = true; load(); } else if (current) { stream(); loadUsage(); loadMap(); } },
    leave() { stopStream(); camera(false); clearTimeout(mapTimer); closeLoad(); },
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
