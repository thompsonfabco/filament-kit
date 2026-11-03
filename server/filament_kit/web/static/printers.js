// Printers tab: live status (SSE), camera (MJPEG in an <img>), controls, filament per AMS unit, usage with undo,
// re-map, optional Web Push. Loaded before app.js (which calls printersTab() when the printers module is on).
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
  const usageBox = h("div");
  const mapBox = h("div");
  const msg = h("div");
  const pushBox = h("div");
  const el = h("section", { class: "hidden" },
    h("h1", { textContent: "Printers" }), picker, head, alerts, controls, camBtn, camBox, msg,
    h("h2", { textContent: "Filament" }), units,
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
    camera(false); stream(); loadUsage(); loadMap();
  }

  // ----- live status -----
  function stream() {
    if (es) es.close();
    if (!current) return;
    lastStatus = null;
    es = new EventSource(`${API}/${encodeURIComponent(current)}/events`);
    es.onmessage = (ev) => {
      let d; try { d = JSON.parse(ev.data); } catch { return; }
      if (d.error) { head.replaceChildren(h("p", { class: "err", textContent: d.error })); return; }
      lastStatus = d; render(d);
    };
    es.onerror = () => { head.append(h("p", { class: "muted", textContent: "Reconnecting…" })); };
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
    camOn = on;
    camBtn.textContent = on ? "Hide camera" : "Show camera";
    camBox.classList.toggle("hidden", !on);
    if (on) {
      camBox.replaceChildren(h("img", { class: "cam", alt: "Printer camera", src: `${API}/${encodeURIComponent(current)}/camera.mjpeg` }));
    } else {
      for (const i of camBox.querySelectorAll("img")) i.removeAttribute("src");   // drops the connection: the camera stops
      camBox.replaceChildren();
    }
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
          h("span", { class: "muted", textContent: sp && sp.remaining_weight != null ? `${Math.round(sp.remaining_weight)} g` : state }));
      });
      cards.push(h("div", { class: "card" }, h("h3", { textContent: u.type_name ? `${u.label} · ${u.type_name}` : u.label }), ...rows));
    }
    units.replaceChildren(...(cards.length ? cards : [h("p", { class: "muted", textContent: "No AMS units reported." })]));
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
        h("p", { class: "muted", textContent: `${m.calibrated ? "Mapped" : "Not mapped yet"} · ${m.state}${m.step ? " · " + m.step : ""}${m.stale ? " · layout changed" : ""}` }),
        ...(m.problems || []).map((t) => h("p", { class: "err", textContent: t })),
        h("button", { class: "secondary", textContent: running ? "Mapping…" : "Re-map slots", disabled: running, on: { click: remap } }));
      if (running) mapTimer = setTimeout(loadMap, 3000);
    } catch (e) { mapBox.replaceChildren(fail(e)); }
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
    leave() { stopStream(); camera(false); clearTimeout(mapTimer); },
  };
}
