// The live printer view of the Printers section (DECISIONS R83 section 2 and 3, the 20:58 ruling point 3): what an open printer shows in
// its Detail region. Loaded after setup.js; everything from the Hub goes in through textContent. It exports ONE function, printerLive(p, ctx),
// which returns the view's element; the printer detail puts it in its region. The view asks `printers/{serial}/live` every 2 s while it
// is on the page and the tab is visible, and stops by itself when it leaves the page. Looking (state, slots, usage) needs nothing; the
// camera, the controls and every slot action go through needCode(), so a Locked page opens the unlock dialog first.
//   ctx (all optional): path(what) the page route of a printer; api(path, body) the Hub call; pickSpool(slot) a spool picker (-> spool | null)
(() => {
"use strict";

const POLL_MS = 2000;
const ACTIVE = ["RUNNING", "PAUSE", "PREPARE", "SLICING"];
const UP = ["connected", "unknown_model"];
const FIX = { offline: "printers_fix_offline", wrong_code: "printers_fix_wrong_code", needs_developer_mode: "printers_fix_developer_mode",
  cert_changed: "printers_fix_cert_changed", unauthorized: "printers_fix_unauthorized", klippy_not_ready: "printers_fix_klippy" };
const JOB = { RUNNING: ["printer_state_printing", "info", "s-diamond"], PAUSE: ["printer_state_paused", "warn", "s-triangle"],
  FINISH: ["printer_state_finished", "ok", "s-filled"], FAILED: ["printer_state_failed", "bad", "s-octagon"],
  PREPARE: ["printer_state_preparing", "info", "s-diamond"], SLICING: ["printer_state_preparing", "info", "s-diamond"] };
const JOB_WORD = { RUNNING: "printer_job_printing", PAUSE: "printer_job_paused", FINISH: "printer_job_finished", FAILED: "printer_job_failed",
  PREPARE: "printer_job_preparing", SLICING: "printer_job_slicing", IDLE: "printer_job_idle" };
const DONE = { pause: "printer_result_paused", resume: "printer_resumed_line", stop: "printer_stopped_line", light_on: "printer_light_on_line",
  light_off: "printer_result_light_off" };

// The texts the catalogue does not have yet (EV2 adds them): the catalogue's text wins once it has the key.
const STUB = {
  live_head: "Live view", live_alerts: "Printer alerts", live_locked: "Unlock the page to use the camera, the controls and the slot actions.",
  live_load_slot: "Load into slot {slot}", live_unload_slot: "Unload slot {slot}", live_clear_slot: "Clear slot {slot}", live_clear: "Clear slot",
  live_slots: "Filament",
  live_clear_title: "Clear slot {slot}?",
  live_clear_body: "Clear slot {slot}? The Hub forgets the spool recorded here.",
  live_clear_body_spool: "Clear slot {slot}? The Hub forgets the spool recorded here. {name} goes back to {location}.",
  live_clear_body_spool_noplace: "Clear slot {slot}? The Hub forgets the spool recorded here. {name} goes back to its previous place.",
  live_clear_waiting: "The spool waiting for this slot is no longer waiting.",
  live_clear_done: "Slot {slot} cleared.", live_clear_printer: "The slot's setting on the printer is cleared too.",
  live_unload_waiting: "The assignment waiting for this slot ends.",
  live_load_waiting: "Waiting for the spool to load in {slot}.", live_load_done: "Loaded {name} into {slot}.", live_load_sent: "Sent to {slot}.",
  live_pick_title: "Load into slot {slot}", live_pick_none: "Pick a spool first.", live_pick_failed: "The spools could not be listed.",
  live_plan: "Load {name} into {slot}.",
  live_not_supported: "This printer has no such control.",
  live_too_many: "Too many camera views are open. Close one first."
};
const fill = (text, vars) => (vars ? String(text).replace(/\{([a-z][a-z0-9_]*)\}/g, (m, n) => (vars[n] != null ? String(vars[n]) : m)) : String(text));
const t = (key, vars) => {
  const v = SW.t(key, vars);
  return v !== key || !(key in STUB) ? v : fill(STUB[key], vars);
};
const h = SW.h;
const E = (tag, cls, ...kids) => h(tag, { class: cls }, ...kids);
const enc = encodeURIComponent;
const hexOf = (s) => (/^[0-9A-Fa-f]{6}$/.test(s.color_hex || "") ? "#" + s.color_hex : "");
const num = (v) => (v == null || v === "" || Number.isNaN(Number(v)) ? "–" : String(Math.round(Number(v))));
const timeLeft = (min) => (!min || min < 1 ? "" : min >= 60 ? t("printer_time_hours", { hours: Math.floor(min / 60), minutes: min % 60 }) : t("printer_time_minutes", { minutes: min }));
const clockOf = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
const stamp = (at) => String(at || "").replace("T", " ").slice(0, 16);
const spoolName = (s) => `${s.vendor || ""} ${s.name || ""}`.trim() || t("spool_title", { id: s.id });
const sentence = (kind, shape, text) => E("span", "status status--" + kind, SW.shape(shape), text);

function printerLive(p, ctx = {}) {
  const path = (what) => (ctx.path ? ctx.path(what) : `printers/${enc(p.serial)}/${what}`);
  const call = ctx.api || api;
  const S = { live: null, usage: null, sig: {}, ctl: "", camOn: false, busy: false, timer: 0, tries: 0, seen: false, wasActive: false,
    noLight: false, results: new Map(), undone: new Map() };
  const head = E("div", "plive__state"), job = E("div", "plive__job"), bar = SW.progress({ value: 0, name: t("printer_progress_name") });
  const pct = E("span", "plive__pct mono"), prog = E("div", "plive__prog", bar, pct), detail = E("p", "plive__detail muted"), temps = E("p", "plive__temps mono");
  const alerts = E("div", "plive__alerts"), notes = E("div", "plive__notes"), msg = h("p", { class: "result plive__msg", role: "status" });
  const locked = E("div", "plive__locked");
  const controls = E("div", "plive__controls actions"), camBtn = SW.btn(t("printer_camera_show"), { icon: "camera", action: "camera", run: () => cameraToggle() });
  const camBox = h("div", { class: "plive__cam", hidden: true });
  const units = E("div", "plive__units"), usageBox = E("div", "plive__log"), usageMsg = h("p", { class: "result", role: "status" });
  const titled = (key, ...kids) => { const id = SW.uid("pl"); return h("section", { class: "plive__group", "aria-labelledby": id }, h("h3", { class: "plive__title", id }, t(key)), ...kids); };
  const root = h("section", { class: "plive", "aria-label": t("live_head"), data: { printer: p.serial != null ? "live" : null } },
    locked, head, job, prog, detail, temps, alerts, notes, controls, msg, E("div", "plive__camrow", camBtn), camBox,
    titled("live_slots", units), titled("printer_usage_title", usageBox, usageMsg));
  prog.hidden = detail.hidden = temps.hidden = true;
  camBtn.hidden = true;

  // ----- the looks of one read -----
  const up = () => !!S.live && UP.includes(S.live.state);
  const gcode = () => (S.live && S.live.status && S.live.status.gcode_state) || "";
  const active = () => up() && ACTIVE.includes(gcode());
  function paintState() {
    const L = S.live, s = (L && L.status) || {}, st = L ? L.state : "";
    if (!L) { head.replaceChildren(E("span", "muted", t("printer_waiting"))); return; }
    const word = st === "offline" ? SW.status("offline") : up() ? SW.status("connected") : SW.status("needs_look");
    head.replaceChildren(word, ...(!up() ? [E("span", "muted", FIX[st] ? t(FIX[st]) : String(st).replace(/_/g, " "))] : []));
    const g = gcode(), jt = up() && g ? JOB[g] : null;
    job.replaceChildren(...(up() && g ? [jt ? sentence(jt[1], jt[2], s.job ? t(jt[0], { job: s.job }) : t(JOB_WORD[g])) : E("span", "muted", t(JOB_WORD[g] || "printer_job_idle"))] : []));
    const live = active();
    prog.hidden = !live;
    if (live) {
      const pc = Math.max(0, Math.min(100, Number(s.percent) || 0));
      SW.setProgress(bar, pc / 100, t("printer_percent", { percent: pc }));
      pct.textContent = t("printer_percent", { percent: pc });
    }
    const left = timeLeft(s.remaining_min), clock = s.eta ? clockOf(s.eta) : "";
    const layer = s.total_layers ? t("printer_progress_layer", { layer: s.layer ?? "?", layers: s.total_layers }) : "";
    detail.textContent = live ? [layer, left ? t("printer_progress_left", { time: left }) : "", clock ? t("printer_progress_done", { clock }) : "", s.stage].filter(Boolean).join(" · ") : "";
    detail.hidden = !detail.textContent;
    const tp = s.temps || {}, lines = [];
    (tp.nozzle || []).forEach((n, i) => lines.push(t(tp.nozzle.length > 1 ? "printer_temp_nozzle_n" : "printer_temp_nozzle", { n: i + 1, now: num(n.current), target: num(n.target) })));
    if (tp.bed) lines.push(t("printer_temp_bed", { now: num(tp.bed.current), target: num(tp.bed.target) }));
    if (tp.chamber) lines.push(t("printer_temp_chamber", { now: num(tp.chamber.current) }));
    temps.textContent = up() ? lines.join(" · ") : "";
    temps.hidden = !temps.textContent;
    const hms = s.hms || [], err = s.print_error;
    alerts.replaceChildren(...(up() ? [...hms.map((x) => sentence("bad", "s-octagon", x.text || t("printer_alert_code", { code: x.code }))),
      ...(err && !hms.length ? [sentence("bad", "s-octagon", t("printer_alert_code", { code: err }))] : [])] : []));
    alerts.setAttribute("aria-label", t("live_alerts"));
    notes.replaceChildren(...[...(s.notes || []), s.spoolman_warning].filter((n) => typeof n === "string" && n).map((n) => E("p", "muted", n)));
    camBtn.hidden = !S.camOn && !(L.camera && L.camera.kind);
  }

  // ----- the controls -----
  function paintControls() {
    const L = S.live, s = (L && L.status) || {}, g = gcode(), light = (L && L.controls && L.controls.light) && !S.noLight;
    const sig = [up(), g, s.light, light, SW.lock.state === "locked"].join("|");
    locked.replaceChildren(...(SW.lock.state === "locked" ? [E("p", "muted", t("live_locked"), " ", unlockToShow())] : []));
    if (sig === S.ctl) return;
    S.ctl = sig;
    const ctl = (action, key, cls) => { const b = SW.btn(t(key), { cls, action, run: () => command(action, b) }); return b; };
    const row = [];
    if (up() && g === "RUNNING") row.push(ctl("pause", "printer_pause", ""));
    if (up() && g === "PAUSE") row.push(ctl("resume", "printer_resume", "btn--primary"));
    if (up() && light) {
      if (s.light === "on" || s.light === "off") row.push(ctl(s.light === "on" ? "light_off" : "light_on", s.light === "on" ? "printer_light_off" : "printer_light_on", "btn--ghost"));
      else row.push(ctl("light_on", "printer_light_on", "btn--ghost"), ctl("light_off", "printer_light_off", "btn--ghost"));
    }
    if (active()) { const b = SW.btn(t("printer_stop"), { cls: "btn--danger", action: "stop", run: () => stop(b) }); row.push(b); }
    controls.replaceChildren(...row);
  }
  const post = (what, body) => call(path(what), { ...body, code: theCode() });
  // a change goes through the lock: Locked opens the unlock dialog and the work carries on after the code
  const unlocked = (run) => needCode(run);
  async function command(action, button, confirm) {
    await unlocked(async () => {
      if (S.busy) return;
      S.busy = true;
      SW.busy(button, t("common_working"));
      SW.result(msg, "run", t("common_working"));
      try {
        await post("command", confirm ? { action, confirm: true } : { action });
        SW.result(msg, "ok", t(DONE[action]));
        S.ctl = "";
        refresh();
      } catch (e) {
        if (e.locked) throw e;
        if (e.data && e.data.code === "not_supported") { S.noLight = S.noLight || action.startsWith("light"); S.ctl = ""; SW.result(msg, "warn", t("live_not_supported")); paintControls(); }
        else SW.result(msg, "bad", e.data && e.data.code === "refused" && typeof e.message === "string" ? t("printer_said_no", { error: e.message }) : e.message);
      } finally { S.busy = false; SW.idle(button); }
    });
  }
  // asked first, and the page is unlocked before the question, so a Locked page is not asked twice
  const stop = (button) => unlocked(async () => {
    const job_ = ((S.live || {}).status || {}).job, printer = p.name || (S.live && S.live.name) || "";
    const go = await SW.ask({ kind: "destructive", title: t("printer_stop_dialog_title"), opener: button, cancel: t("printer_stop_keep"), confirm: t("printer_stop"),
      text: job_ ? t("printer_stop_dialog_body", { job: job_, printer }) : t("printer_stop_dialog_body_nojob", { printer }) });
    if (go) await command("stop", button, true);
  });

  // ----- the camera: an image request carries no code, so a trusted computer asks directly (its cookie goes along) and any other
  // gets a ticket first (POST camera/ticket, with the code). The FIRST camera address carries ?ticket=; the Hub then keeps a camera
  // session (a cookie for this printer's camera routes, 10 minutes from the last request), so the playlist's segments need no
  // ticket. The page ends the session (POST camera/close) when the camera is closed -----
  async function firstAddress(file) {
    const base = "/setup/api/" + path(file);
    if (SW.lock.state === "trusted") return base;
    const r = await post("camera/ticket", {});
    S.session = true;
    return `${base}?ticket=${enc(r.ticket)}`;
  }
  function closeSession() {
    if (!S.session) return;
    S.session = false;
    // keepalive: it still goes when the page is being left; the answer is of no interest
    fetch("/setup/api/" + path("camera/close"), { method: "POST", credentials: "same-origin", keepalive: true, headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
  }
  function cameraStop() {
    for (const m of camBox.querySelectorAll("img, video")) { m.removeAttribute("src"); if (m.load) m.load(); }   // drops the connection: the camera stops
    camBox.replaceChildren();
    camBox.hidden = true;
    S.camOn = false;
    camBtn.replaceChildren(SW.icon("camera", "icon--s"), t("printer_camera_show"));
    closeSession();
  }
  function cameraFail(text) {
    camBox.hidden = false;
    camBox.replaceChildren(E("div", "plive__camtext", E("p", "", text), SW.btn(t("common_try_again"), { action: "try-again", run: () => cameraStart() })));
  }
  async function cameraStart() {
    const kind = S.live && S.live.camera && S.live.camera.kind, name = p.name || (S.live && S.live.name) || "";
    closeSession();                                          // Try again: the old session goes before a new ticket is asked
    S.camOn = true;
    camBtn.replaceChildren(SW.icon("camera", "icon--s"), t("printer_camera_hide"));
    camBox.hidden = false;
    camBox.replaceChildren(E("div", "plive__camtext", SW.spinner(), t("printer_camera_starting")));
    try {
      if (kind === "hls") {
        const v = h("video", { class: "plive__video", playsInline: true, muted: true, autoplay: true, controls: true, "aria-label": t("printer_camera_alt", { printer: name }) });
        if (!v.canPlayType("application/vnd.apple.mpegurl")) { cameraFail(t("printer_camera_no_hls")); return; }
        const src = await firstAddress("camera/index.m3u8");
        if (!S.camOn) return;
        v.addEventListener("error", () => { if (S.camOn) cameraFail(t("printer_camera_failed")); });
        v.src = src;                                         // its segments are asked with the session's cookie
        camBox.replaceChildren(v);
        return;
      }
      const src = await firstAddress("camera.mjpeg");
      if (!S.camOn) return;
      const img = h("img", { class: "plive__img", alt: t("printer_camera_alt", { printer: name }) });
      img.addEventListener("load", () => camBox.querySelector(".plive__camtext")?.remove(), { once: true });
      img.addEventListener("error", () => { if (S.camOn) cameraFail(t("printer_camera_failed")); });
      camBox.append(img);                                   // the starting line stays until the first picture
      img.src = src;
    } catch (e) {
      if (e.locked) { cameraStop(); throw e; }
      cameraFail(e.data && e.data.code === "too_many_views" ? t("live_too_many") : e.message);
    }
  }
  function cameraToggle() {
    if (S.camOn) { cameraStop(); return; }
    return unlocked(() => cameraStart());
  }

  // ----- slots -----
  const lineOf = (label) => {
    const el = h("div", { class: "result plive__slotline", role: "status", data: { slot: label } }), r = S.results.get(label);
    if (r) SW.result(el, r[0], r[1].cloneNode ? r[1].cloneNode(true) : r[1]);
    return el;
  };
  const slotSay = (label, kind, lines) => {
    const body = E("span", "plive__lines", [].concat(lines).filter(Boolean).map((x, i) => E("span", "plive__linetext", x)));
    S.results.set(label, [kind, body]);
    const el = units.querySelector(`.plive__slotline[data-slot="${CSS.escape(label)}"]`);
    if (el) SW.result(el, kind, body.cloneNode(true));
  };
  function paintSlots() {
    const L = S.live, st = (L && L.status) || {}, list = st.ams || [], key = JSON.stringify([list, up()]);
    if (key === S.sig.slots) return;
    S.sig.slots = key;
    const focus = document.activeElement && units.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const unitNode = (u) => h("div", { class: "plive__unit" },
      h("h4", { class: "plive__unittitle" }, [u.label, u.type_name].filter(Boolean).join(" · ")),
      h("ul", { class: "slot-strip plive__slots", "aria-label": t("slot_list_label", { name: p.name || (L && L.name) || "" }) }, (u.slots || []).map((sl) => {
        const sp = sl.spool, waiting = sl.pending, hex = hexOf(sl), grams = sp && sp.remaining_weight != null ? Math.round(sp.remaining_weight) : null;
        const mk = (what, key_, run, cls) => { const b = SW.btn(t(key_), { action: what, cls, name: t(`live_${what}_slot`, { slot: sl.label }), run: () => run(b) }); b.dataset.key = `${what}:${sl.label}`; return b; };
        const load = mk("load", "common_load", (b) => slotLoad(sl, b));
        const unload = sp ? mk("unload", "common_unload", (b) => slotUnload(sl, b)) : null;
        const clear = mk("clear", "live_clear", (b) => slotClear(sl, b));
        if (!up()) for (const b of [load, unload, clear]) if (b) SW.disable(b, t("slot_load_disabled"));
        const what = waiting && !sp && !sl.type ? null : sl.present === false ? E("span", "muted", t("common_empty")) : [sp ? spoolName(sp) : sl.type || t("printer_slot_unknown"), " ", E("span", "mono muted", hex)];
        return h("li", { class: "slot-strip__row plive__slot", data: { state: waiting ? "waiting" : sl.active ? "active" : null, slot: sl.label } },
          E("span", "slot-strip__label mono", sl.label), SW.swatch(hex, { empty: sl.present === false && !waiting }),
          E("span", "slot-strip__name plive__what", what, waiting ? E("span", "plive__waiting", t("slot_waiting"), waiting.spool_id != null ? [" ", E("span", "mono", "#" + waiting.spool_id)] : "") : null),
          E("span", "slot-strip__level", grams != null ? E("span", "mono", t("printer_slot_left", { left: grams })) : null),
          E("span", "slot-strip__use", sl.active ? t("slot_in_use") : ""),
          E("span", "actions plive__actions", load, unload, clear), lineOf(sl.label));
      })));
    units.replaceChildren(...(list.length ? list.map(unitNode) : [E("p", "muted", t(!L ? "printer_waiting" : up() ? "spool_load_no_slots" : "slot_none_offline"))]));
    if (focus) { const b = units.querySelector(`[data-key="${CSS.escape(focus)}"]`); if (b) b.focus(); }
  }
  const slotPost = (sl, what, body) => post(`slots/${enc(sl.label)}/${what}`, body);
  const whereOf = (r) => r.location || ((r.moved_back || [])[0] || {}).location || (typeof r.moved_back === "string" ? r.moved_back : "");
  async function runSlot(sl, button, work) {
    await unlocked(async () => {
      if (S.busy) return;
      S.busy = true;
      const line = units.querySelector(`.plive__slotline[data-slot="${CSS.escape(sl.label)}"]`);
      try { await work(line); } catch (e) {
        if (e.locked) throw e;
        S.results.set(sl.label, ["bad", e.message]);
        if (line) SW.result(line, "bad", e.message);
      } finally { S.busy = false; }
    });
    refresh();
  }
  // the dry run first: what would change is said before anything is sent; the confirmation then sends the same with dry_run false
  const slotUnload = (sl, button) => runSlot(sl, button, async (line) => {
    if (line) SW.result(line, "run", t("common_checking"));
    const plan = await slotPost(sl, "unload", { dry_run: true });
    if (line) SW.result(line, null);
    const name = (sl.spool && sl.spool.name) || t("spool_title", { id: (plan.spool || {}).id ?? "?" }), where = whereOf(plan);
    const done = await SW.ask({ kind: "confirm", title: t("printer_unload_title", { slot: sl.label }), opener: button, confirm: t("common_unload"),
      text: where ? t("printer_unload_body", { name, slot: sl.label, location: where }) : t("printer_unload_body_noplace", { name, slot: sl.label }),
      run: () => slotPost(sl, "unload", { dry_run: false }) });
    if (!done) { S.results.delete(sl.label); return; }
    slotSay(sl.label, "ok", [t("printer_unload_line", { name, slot: sl.label }), ...(done.moved_back || []).map((m) => (m.location ? t("printer_unload_moved_back", { id: m.id ?? "?", location: m.location }) : t("printer_unload_moved_back_noplace", { id: m.id ?? "?" }))),
      done.waiting_ended ? t("live_unload_waiting") : ""]);
  });
  const slotClear = (sl, button) => runSlot(sl, button, async (line) => {
    if (line) SW.result(line, "run", t("common_checking"));
    const plan = await slotPost(sl, "clear", { dry_run: true });
    if (line) SW.result(line, null);
    const sp = plan.spool, where = plan.moved_back || "";
    const text = !sp ? t("live_clear_body", { slot: sl.label }) : where ? t("live_clear_body_spool", { slot: sl.label, name: spoolName(sp), location: where })
      : t("live_clear_body_spool_noplace", { slot: sl.label, name: spoolName(sp) });
    const done = await SW.ask({ kind: "confirm", title: t("live_clear_title", { slot: sl.label }), opener: button, confirm: t("live_clear"), text,
      body: plan.waiting_ended ? E("p", "", t("live_clear_waiting")) : null, run: () => slotPost(sl, "clear", { dry_run: false }) });
    if (!done) { S.results.delete(sl.label); return; }
    slotSay(sl.label, "ok", [t("live_clear_done", { slot: sl.label }), done.waiting_ended ? t("live_clear_waiting") : "", done.printer_cleared ? t("live_clear_printer") : "", done.text || ""]);
  });
  // Load: a spool is picked (ctx.pickSpool, else the search below), the dry run says what would happen, then Load sends it
  async function pickSpool(sl, button) {
    if (ctx.pickSpool) return ctx.pickSpool(sl);
    let chosen = null;
    const results = h("div", { class: "plive__picks" }), note = h("p", { class: "result", role: "status" });
    const find = SW.field({ type: "search", label: t("common_search"), placeholder: t("common_search_placeholder"), onSearch: (q) => search(q) });
    let asked = 0;
    const row = (s) => h("button", { class: "btn plive__pick", type: "button", "aria-pressed": "false", data: { spool: s.id }, on: { click: (ev) => {
      chosen = s;
      for (const b of results.children) b.setAttribute("aria-pressed", String(b === ev.currentTarget));
    } } }, t("printer_load_row_id", { id: s.id }) + " " + spoolName(s), " ",
    E("span", "muted", t("printer_load_row_where", { location: s.location || "?", grams: s.remaining_g != null ? Math.round(s.remaining_g) : "?" })));
    const search = async (q) => {
      const mine = ++asked;
      try {
        const r = await call(`spools?q=${enc(q)}&limit=12`);
        if (mine !== asked) return;
        SW.result(note, null);
        results.replaceChildren(...((r.spools || []).length ? r.spools.map(row) : [E("p", "muted", t("spools_empty_filtered"))]));
      } catch (e) { if (mine === asked) SW.result(note, "bad", t("live_pick_failed")); }
    };
    search("");
    const picked = await SW.ask({ kind: "confirm", title: t("live_pick_title", { slot: sl.label }), opener: button, confirm: t("common_load"), body: [find, results, note],
      run: () => { if (!chosen) { SW.result(note, "warn", t("live_pick_none")); return false; } return chosen; } });
    return picked || null;
  }
  const slotLoad = (sl, button) => runSlot(sl, button, async (line) => {
    const sp = await pickSpool(sl, button);
    if (!sp) return;
    if (line) SW.result(line, "run", t("common_checking"));
    const plan = await slotPost(sl, "load", { spool_id: sp.id, dry_run: true });
    if (line) SW.result(line, null);
    const moved = (plan.moved_back || []).filter((m) => m.id !== sp.id).map((m) => (m.location ? t("spool_load_plan_goes_back", { id: m.id ?? "?", slot: sl.label, location: m.location }) : t("spool_load_plan_goes_back_noplace", { id: m.id ?? "?", slot: sl.label })));
    const done = await SW.ask({ kind: "confirm", title: t("spool_load_title", { slot: sl.label }), opener: button, confirm: t("common_load"),
      text: t("live_plan", { name: spoolName(sp), slot: sl.label }), body: [plan.preset && plan.preset.name ? E("p", "", t("printer_load_preset", { name: plan.preset.name })) : null, ...moved.map((m) => E("p", "", m)),
        ...(plan.problems || []).map((x) => E("p", "", x))], run: () => slotPost(sl, "load", { spool_id: sp.id, dry_run: false }) });
    if (!done) return;
    slotSay(sl.label, "ok", [done.pending ? t("live_load_waiting", { slot: sl.label }) : t(done.confirmed ? "live_load_done" : "live_load_sent", { name: spoolName(sp), slot: sl.label }), ...moved, ...(done.problems || [])]);
  });

  // ----- Filament used, with Undo per entry -----
  async function loadUsage() {
    try {
      const r = await call(path("usage?days=7"));
      S.usage = [...(r.entries || [])].sort((a, b) => String(b.at || "").localeCompare(String(a.at || ""))).slice(0, 20);
    } catch (e) { SW.result(usageMsg, "bad", e.message); return; }
    SW.result(usageMsg, null);
    usageBox.replaceChildren(S.usage.length ? h("ul", { class: "plive__usage" }, S.usage.map(usageRow)) : E("p", "muted", t("printer_usage_empty")));
  }
  function usageNote(e) {
    if (e.undone) return t("printer_usage_note_undone");
    if (e.observe) return t("printer_usage_note_logged");
    if (e.spool_id == null) return t("printer_usage_note_no_spool");
    if (e.error) { const k = "printer_usage_reason_" + e.error; return t("printer_usage_note_not_taken", { reason: SW.t(k) !== k ? t(k) : String(e.error).replace(/_/g, " ") }); }
    return "";
  }
  function usageRow(e) {
    const line = h("div", { class: "result", role: "status" }), said = S.undone.get(e.id);
    if (said) SW.result(line, "ok", said);
    const counted = !e.undone && !e.observe && e.spool_id != null && !e.error && !String(e.id).startsWith("k-");
    const b = counted ? SW.btn(t("common_undo"), { action: "undo", name: t("printer_used_undo_name", { grams: e.grams ?? "?", job: e.job || t("printer_used_job_default") }), run: () => undo(e, b, line) }) : null;
    const from = e.spool ? t("printer_used_from_spool", { id: e.spool.id, name: spoolName(e.spool) }) : e.spool === null && e.spool_id != null ? t("printer_used_spool_gone") : "";
    return h("li", { class: "plive__used", data: { state: e.undone ? "undone" : null, entry: e.id } },
      E("span", "plive__grams mono", t("common_grams", { grams: e.grams ?? "?" })), E("span", "plive__what", [e.job || t("printer_used_job_default"), e.slot].filter(Boolean).join(" · ")),
      E("span", "plive__when mono muted", stamp(e.at)), E("span", "plive__from muted", [from, usageNote(e)].filter(Boolean).join(" · ")), b, line);
  }
  async function undo(e, button, line) {
    await unlocked(async () => {
      const back = await SW.ask({ kind: "confirm", title: t("printer_usage_undo_title"), opener: button, cancel: t("common_keep"), confirm: t("printer_usage_undo_confirm"),
        text: t("printer_usage_undo_body", { grams: e.grams ?? "?", job: e.job || "?", slot: e.slot || "?", time: stamp(e.at) }), run: () => call(`usage/${enc(e.id)}/undo`, { code: theCode() }) });
      if (!back) return;
      S.undone.set(e.id, t("printer_usage_undone", { grams: e.grams ?? "?", id: e.spool_id ?? "?" }));
      loadUsage();
    });
  }

  // ----- the read, every 2 s while this is on the page and the tab is visible -----
  async function refresh() {
    try { S.live = await call(path("live")); } catch (e) { SW.result(msg, "bad", e.message); return; }
    const was = S.wasActive;
    S.wasActive = active();
    paintState(); paintControls(); paintSlots();
    if (!S.usage || (was && !S.wasActive)) loadUsage();           // a job ended: its entry is new
  }
  function schedule(ms) {
    clearTimeout(S.timer);
    S.timer = setTimeout(tick, ms);
  }
  async function tick() {
    if (!root.isConnected) {
      if (S.seen || ++S.tries > 40) { teardown(); return; }       // never put on the page, or taken off it: stop
      schedule(50); return;
    }
    S.seen = true;
    if (!root.getClientRects().length) {                           // the detail is closed (or the tab is another): no read, no picture
      if (S.camOn) cameraStop();
      schedule(POLL_MS / 5); return;
    }
    if (!document.hidden) await refresh();
    schedule(POLL_MS);
  }
  function teardown() {
    clearTimeout(S.timer);
    cameraStop();
    document.removeEventListener("visibilitychange", onVisible);
    document.removeEventListener("sw:lock", onLock);
    window.removeEventListener("pagehide", closeSession);
  }
  function onVisible() { if (!document.hidden && root.isConnected) { clearTimeout(S.timer); tick(); } else if (document.hidden) cameraStop(); }
  function onLock() { S.ctl = ""; if (S.live) paintControls(); }                 // a running picture is not cut by a lock: the next Show camera asks for the code
  document.addEventListener("visibilitychange", onVisible);
  document.addEventListener("sw:lock", onLock);
  window.addEventListener("pagehide", closeSession);
  paintState(); paintSlots(); paintControls();
  schedule(0);
  root.stop = teardown;
  return root;
}

window.printerLive = printerLive;
})();
