// Printers tab: live status (SSE), camera (MJPEG in an <img>), controls, filament per AMS unit with load / unload,
// usage with undo, re-map, optional Web Push. Loaded before app.js (which calls printersTab() when the printers module is on).
// Everything from the server goes in through textContent / element properties, never innerHTML.
"use strict";
function printersTab() {
  const PUSH = document.body.dataset.push === "1";
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
  const slotMsg = h("div");
  const usageBox = h("div");
  const mapBox = h("div");
  const msg = h("div");
  const conn = h("p", { class: "muted" });
  const pushBox = h("div");
  const el = h("section", { class: "hidden" },
    h("h1", { textContent: "Printers" }), picker, head, conn, alerts, controls, camBtn, camBox, msg,
    h("h2", { textContent: "Filament" }), units, slotMsg, loadBox,
    h("h2", { textContent: "Usage" }), usageBox,
    h("h2", { textContent: "Slots" }), mapBox, pushBox);

  async function pj(path, body) {
    return api(path ? "printers/" + path : "printers", body === undefined ? {} : { method: "POST", body });
  }
  function say(text, ok) { msg.replaceChildren(h("pre", { class: ok ? "ok" : "err", textContent: text })); }

  async function load() {
    try {
      printers = (await pj("")).printers;
    } catch (e) { head.replaceChildren(fail(e)); return; }
    picker.replaceChildren(...printers.map((p) => h("option", { value: p.id, textContent: p.name || p.id })));
    picker.classList.toggle("hidden", printers.length < 2);
    if (!printers.length) { head.replaceChildren(h("p", { class: "muted", textContent: "No printer is set up on the server yet." })); return; }
    let want = null;
    try { want = localStorage.getItem("printer"); } catch {}
    choose(printers.some((p) => p.id === want) ? want : printers[0].id);
  }

  function choose(id) {
    current = id; picker.value = id;
    try { localStorage.setItem("printer", id); } catch {}
    camera(false); camBtn.classList.toggle("hidden", !camKind()); closeLoad(); slotMsg.replaceChildren();
    stream(); loadUsage(); loadMap();
  }
  // "mjpeg" (an <img>) or "hls" (a <video>); null: this model has no camera we can show
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
      if (d.error) { conn.textContent = d.error; return; }
      conn.textContent = ""; lastStatus = d; render(d);
    };
    es.onopen = () => { conn.textContent = ""; };
    es.onerror = () => { conn.textContent = "Reconnecting…"; };
  }
  function stopStream() { if (es) { es.close(); es = null; } }

  function fmtMin(m) { return m > 0 ? (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`) : ""; }
  function render(d) {
    const s = d.status || {}, p = d.printer || {};
    const live = ["RUNNING", "PAUSE", "PREPARE"].includes(s.gcode_state);
    head.replaceChildren(
      h("h3", {}, p.name || current, h("span", { class: "pill", textContent: p.state === "connected" ? (s.gcode_state || "") : (p.state || "") })),
      s.job ? h("p", { textContent: s.job }) : null,
      live ? h("progress", { max: 100, value: s.percent || 0 }) : null,
      live ? h("p", { class: "muted", textContent: [`${s.percent || 0}%`, s.stage, s.total_layers ? `layer ${s.layer ?? "?"}/${s.total_layers}` : "", fmtMin(s.remaining_min)].filter(Boolean).join(" · ") }) : null,
      h("p", { class: "muted", textContent: (s.temps || []).map((t) => `${t.name} ${t.cur ?? "-"}${t.tgt ? "/" + t.tgt : ""}°`).join(" · ") }));
    const a = [];
    for (const x of s.hms || []) a.push(h("p", { class: "err", textContent: x.text || `HMS ${x.code}` }));
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
  async function cmd(action, confirm) {
    say("Sending…", true);
    try {
      const r = await pj(`${encodeURIComponent(current)}/command`, confirm ? { action, confirm: true } : { action });
      const inner = r.reply || {};
      if (inner.ok === false) say("The printer said no: " + JSON.stringify((inner.reply || {}).reason || inner.reply || ""), false);
      else say("Done.", true);
    } catch (e) { say(e.message, false); }
  }
  function stop() {
    if (window.confirm("Stop this print? It cannot be resumed.")) cmd("stop", true);
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
      camBox.append(h("p", { class: "err", textContent: "This browser cannot play the printer's camera (it needs HLS: use Safari on iPhone or Mac)." }));
      return;
    }
    v.addEventListener("error", () => camFail());
    camBox.append(v);
    v.src = `${base}/camera/index.m3u8`;
    v.play().catch(() => {});
  }
  function camFail() {
    if (!camOn) return;
    camBox.replaceChildren(h("p", { class: "err", textContent: "The camera did not start. Check that the printer is on, LAN mode liveview is enabled, and not too many views are open." }));
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
  function slotSay(lines, ok) { slotMsg.replaceChildren(h("pre", { class: ok ? "ok" : "err", textContent: [lines].flat().join("\n") })); }
  function spoolTitle(s) { return `${s.vendor || ""} ${s.name || ""}`.trim() || `spool #${s.id}`; }

  function openLoad(sl) {
    loadSlot = sl.label; loadSpool = null; slotMsg.replaceChildren();
    const q = h("input", { type: "search", placeholder: "Search: brand, colour, material", enterKeyHint: "search",
                           on: { keydown: (e) => { if (e.key === "Enter") search(); } } });
    const results = h("div", { class: "list" });
    const plan = h("div");
    const go = h("button", { textContent: "Load", disabled: true, on: { click: () => doLoad(false, plan, go) } });
    const picked = h("p", { class: "muted", textContent: "Pick a spool: tap its tag on a reader, or search." });
    function pick(s, btn) {
      for (const b of results.querySelectorAll(".pick")) b.classList.toggle("on", b === btn);
      loadSpool = s; go.disabled = true; plan.replaceChildren();
      picked.textContent = `S${s.id} ${spoolTitle(s)} (${s.location || "?"}${s.remaining_g != null ? ", " + Math.round(s.remaining_g) + " g" : ""})`;
      doLoad(true, plan, go);           // the dry run first: the user sees the plan before anything is sent
    }
    function row(s) {
      const b = h("button", { class: "pick", on: { click: () => pick(s, b) } }, h("strong", { textContent: `S${s.id} ` }), spoolTitle(s),
        h("div", { class: "muted", textContent: `${s.location || "?"} · ${s.remaining_g ?? "?"} g` }));
      return b;
    }
    async function lastTap() {
      try {
        const t = await pj("tagged");
        if (!t.spool) {
          results.replaceChildren(h("p", { class: "muted", textContent: t.nfc_id ? `Tag ${t.nfc_id} is not linked to a spool.` : "No tag read yet: tap one." }));
          return;
        }
        const b = row(t.spool);
        results.replaceChildren(b); pick(t.spool, b);
      } catch (e) { results.replaceChildren(fail(e)); }
    }
    async function search() {
      try {
        const res = await api(`find?q=${encodeURIComponent(q.value)}&sealed=0`);
        const rows = res.filaments.flatMap((f) => f.spools.map((s) => ({ id: s.spool_id, vendor: f.vendor, name: f.name, location: s.location, remaining_g: s.remaining_g })));
        results.replaceChildren(...(rows.length ? rows.slice(0, 60).map(row) : [h("p", { class: "muted", textContent: "No spools match." })]));
      } catch (e) { results.replaceChildren(fail(e)); }
    }
    loadBox.replaceChildren(
      h("h3", { textContent: `Load into ${sl.label}` }),
      h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Use the last tapped tag", on: { click: lastTap } })),
      h("div", { class: "row" }, q, h("button", { class: "fit", textContent: "Search", on: { click: search } })),
      results, picked, plan,
      h("div", { class: "row" }, go, h("button", { class: "secondary", textContent: "Cancel", on: { click: closeLoad } })));
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
    slotBusy = true; go.disabled = true;
    plan.replaceChildren(h("p", { class: "muted", textContent: dry ? "Checking…" : "Loading…" }));
    try {
      const r = await pj(`${slotPath(label)}/load`, dry ? { spool_id: s.id, dry_run: true } : { spool_id: s.id, dry_run: false });
      if (loadSpool !== s) return;      // another spool was picked meanwhile
      const moved = (r.moved_back || []).filter((m) => m.id !== s.id)
        .map((m) => `Spool #${m.id ?? "?"} now in ${label} goes back to ${m.location || "its previous place"}`);
      if (dry) {
        const nozzle = r.nozzle_assumed ? `Nozzle size not reported by the printer; assuming ${r.nozzle_mm ?? 0.4} mm`
          : (r.nozzle_mm ? `Nozzle: ${r.nozzle_mm} mm` : "");
        plan.replaceChildren(h("pre", { class: "ok", textContent: [`Load ${spoolTitle(s)} into ${label}`,
          "Preset: " + ((r.preset && r.preset.name) || "none"), nozzle, ...moved, ...(r.problems || [])].filter(Boolean).join("\n") }));
        go.disabled = false;
      } else {
        closeLoad();
        slotSay([r.confirmed ? `Loaded into ${label}` : `Sent to ${label}`,
          r.confirmed ? "" : "The printer accepted it but hasn't shown the change yet", ...moved, ...(r.problems || [])].filter(Boolean), true);
      }
    } catch (e) {
      if (loadSpool === s) plan.replaceChildren(fail(e));
    } finally { slotDone(); }
  }

  // Spoolman only (the printer's slot setting stays): the dry run says where the spool goes, then a confirm
  async function unload(sl, sp) {
    if (slotBusy) return;
    slotBusy = true; slotMsg.replaceChildren(h("p", { class: "muted", textContent: "Checking…" }));
    try {
      const plan = await pj(`${slotPath(sl.label)}/unload`, { dry_run: true });
      const where = plan.location || ((plan.moved_back || [])[0] || {}).location || "its previous place";
      const name = sp.name || `spool #${sp.id}`;
      slotMsg.replaceChildren();
      if (!window.confirm(`Unload ${name} from ${sl.label}? It goes back to ${where}.`)) return;
      const r = await pj(`${slotPath(sl.label)}/unload`, { dry_run: false });
      slotSay([`Unloaded ${name} from ${sl.label}.`,
        ...(r.moved_back || []).map((m) => `Moved back: #${m.id ?? "?"} → ${m.location || "its previous place"}`)], true);
    } catch (e) { slotSay(e.message, false); } finally { slotDone(); }
  }

  // ----- usage + re-map -----
  async function loadUsage() {
    const id = current;
    try {
      const r = await pj(`${encodeURIComponent(id)}/usage`);
      if (id !== current) return;
      const rows = (r.entries || []).slice(0, 20).map((e) => h("div", { class: "row" },
        h("span", { textContent: `${(e.at || "").replace("T", " ").slice(0, 16)} · ${e.job || "job"} · ${e.slot || ""} · ${e.grams ?? "?"} g${e.undone ? " (undone)" : ""}` }),
        e.undone ? null : h("button", { class: "secondary", textContent: "Undo", on: { click: () => undo(e) } })));
      usageBox.replaceChildren(...(rows.length ? rows : [h("p", { class: "muted", textContent: "Nothing recorded in the last days." })]));
    } catch (e) { usageBox.replaceChildren(fail(e)); }
  }
  async function undo(e) {
    if (!window.confirm(`Put ${e.grams ?? "?"} g back on the spool?`)) return;
    try { await pj(`${encodeURIComponent(current)}/usage/${encodeURIComponent(e.id)}/undo`, {}); say("Undone.", true); } catch (x) { say(x.message, false); }
    loadUsage();
  }
  let mapTimer = null;
  async function loadMap() {
    clearTimeout(mapTimer);
    const id = current;
    try {
      const m = await pj(`${encodeURIComponent(id)}/map`);
      if (id !== current) return;
      const running = m.state === "running";
      mapBox.replaceChildren(
        h("p", { class: "muted", textContent: m.outcome_text ? `${m.outcome_text}${running && m.step ? " " + m.step : ""}`
          : `${m.calibrated ? "Mapped" : "Not mapped yet"} · ${m.state}${m.step ? " · " + m.step : ""}${m.stale ? " · layout changed" : ""}` }),
        ...(m.next_step && !running ? [h("p", { textContent: m.next_step })] : []),
        ...(m.problems_old && (m.problems || []).length ? [h("p", { class: "muted", textContent: "From an earlier mapping, it may be fixed by now. Re-map the slots to check:" })] : []),
        ...(m.problems || []).map((t) => h("p", { class: m.problems_old ? "muted" : "err", textContent: t })),
        ...(m.notes || []).map((t) => h("p", { class: "muted", textContent: t })),
        ...(m.report_wanted ? [h("p", { class: "muted", textContent: m.report_why || "A printer report would help." }),
          h("button", { class: "secondary", textContent: "Collect a report", on: { click: collectReport } })] : []),
        h("button", { class: "secondary", textContent: running ? "Mapping…" : "Re-map slots", disabled: running, on: { click: remap } }));
      if (running) mapTimer = setTimeout(loadMap, 3000);
    } catch (e) { mapBox.replaceChildren(fail(e)); }
  }
  // The report holds no serial, address, name or account id: the server builds it from an allow-list.
  async function collectReport() {
    try {
      const r = await pj(`${encodeURIComponent(current)}/report`, {});
      const url = URL.createObjectURL(new Blob([r.xml], { type: "application/xml" }));
      const a = h("a", { href: url, download: r.name, textContent: `Save ${r.name}, then attach it to a "Printer report" issue on the project's GitHub` });
      mapBox.append(h("p", {}, a));
    } catch (e) { say(e.message, false); }
  }
  async function remap() {
    if (!window.confirm("Re-map the slots? The printer loads each slot briefly; do it when it is idle.")) return;
    try { await pj(`${encodeURIComponent(current)}/map`, {}); } catch (e) { say(e.message, false); }
    loadMap();
  }

  // ----- Web Push (only when the server has web.push on) -----
  function pushUi() {
    if (!PUSH) return;
    const ok = "serviceWorker" in navigator && "PushManager" in window;
    pushBox.replaceChildren(h("h2", { textContent: "Alerts" }), ok
      ? h("div", { class: "row" },
        h("button", { class: "secondary", textContent: "Notify this phone", on: { click: subscribe } }),
        h("button", { class: "secondary", textContent: "Stop", on: { click: unsubscribe } }),
        h("button", { class: "secondary", textContent: "Test", on: { click: () => pj("push/test", {}).then(() => say("Sent.", true), (e) => say(e.message, false)) } }))
      : h("p", { class: "muted", textContent: "This browser cannot receive push alerts (on iPhone, add the app to the home screen first)." }));
  }
  function b64(s) {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  async function subscribe() {
    try {
      if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications are blocked for this site.");
      const reg = await navigator.serviceWorker.register(BASE + "/sw.js");
      await navigator.serviceWorker.ready;
      const key = (await pj("push/key")).key;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
      await pj("push/subscribe", { subscription: sub.toJSON() });
      say("This phone will get print alerts.", true);
    } catch (e) { say(e.message, false); }
  }
  async function unsubscribe() {
    try {
      const reg = await navigator.serviceWorker.getRegistration(BASE + "/");
      const sub = reg && (await reg.pushManager.getSubscription());
      if (sub) { await pj("push/unsubscribe", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
      say("Alerts off for this phone.", true);
    } catch (e) { say(e.message, false); }
  }

  document.addEventListener("visibilitychange", () => {
    if (el.classList.contains("hidden")) return;
    if (document.hidden) { stopStream(); camera(false); } else if (current) stream();
  });
  let loaded = false;
  return {
    el,
    enter() { if (!loaded) { loaded = true; pushUi(); load(); } else if (current) { stream(); loadUsage(); loadMap(); } },
    leave() { stopStream(); camera(false); clearTimeout(mapTimer); closeLoad(); },
  };
}
