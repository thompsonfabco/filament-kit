// The Hub page's "Flash a device" section (03 11). Loaded after setup.js; everything from the server goes in through
// textContent, and its words are the catalogue's (flash_*). Two ways to write the Hub's own firmware (it comes with the Hub,
// never from the internet) to an ESP32-C3:
//  - into a board plugged into this computer: the browser writes it over Web Serial with esptool-js (esptool.bundle.js,
//    loaded only then), then, for a Tag Reader, sends its settings over the same USB port (FK? / FK-SET, reader
//    settings.h) and waits for its own report of the Wi-Fi and the Hub;
//  - into a board plugged into the Hub: the Hub does the same (`reader setup`) as a background job, which this page
//    follows with the job strip.
// The Wi-Fi password and the reader token go only to the board (and, the Hub way, to the Hub): never shown, logged, or put
// in an address; the password fields are cleared once sent.
"use strict";

const FLASH_BAUD = 460800;
const ESPRESSIF_VID = 0x303a;
const webSerialOk = () => "serial" in navigator && window.isSecureContext;
const nap = (ms) => new Promise((res) => setTimeout(res, ms));
const quietTerminal = { clean() {}, writeLine() {}, write() {} };
// the Hub's two devices: its id for the firmware, the address place (#flash/<place>), the catalogue key of its name, and the
// steps of a write (flash_step_*; the display has no settings to send and no report to wait for)
const FLASH_DEVICES = {
  "printer-station": { place: "tag-reader", name: "common_reader_tag_reader", steps: ["connecting", "writing", "restarting", "sending", "report"] },
  "intake-panel": { place: "display", name: "flash_device_display", steps: ["connecting", "writing", "restarting"] },
};
let flashPick = { device: null, where: null };    // what was chosen on this page; null: the address, then the first device
let flashRun = null;                              // the write on this page: { id, steps, at, failed, done, running, pct, stop, ssid }
let flashHost = null;                             // where the step list of that write is drawn
let flashWatching = false;                        // the Hub's job is being followed
let flashClear = () => {};                        // empties the password fields of the section on the page now
let flashSync = () => {};                         // draws the section's buttons again for the run's state

// the Stop button was pressed
class FlashStopped extends Error {}

// The reader's answer to FK?: FK-READER <build> configured=<0|1> wifi=<ok|fail|-> server=<ok|fail|unauth|->
function parseHello(line) {
  const p = line.trim().split(/\s+/);
  if (p.length < 2 || p[0] !== "FK-READER" || !/^[0-9]+$/.test(p[1])) return null;
  const kv = {};
  for (const x of p.slice(2)) { const i = x.indexOf("="); if (i > 0) kv[x.slice(0, i)] = x.slice(i + 1); }
  return { build: Number(p[1]), configured: kv.configured === "1", wifi: kv.wifi || "-", server: kv.server || "-" };
}

// One open serial port, read as lines. A port that goes away (the board restarting) ends as `closed`.
class SerialLines {
  constructor(port) { this.port = port; this.buf = ""; this.waiters = []; this.closed = false; this.dec = new TextDecoder(); }
  async open() {
    await this.port.open({ baudRate: 115200 });
    // DTR and RTS low, as the kit opens these boards: never held in reset or in the ROM's download mode
    try { await this.port.setSignals({ dataTerminalReady: false, requestToSend: false }); } catch { /* not every port has them */ }
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this.pump = this.pumpLoop();
    return this;
  }
  async pumpLoop() {
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        this.buf += this.dec.decode(value, { stream: true });
        this.wake();
      }
    } catch { /* the port went away */ }
    this.closed = true;
    this.wake();
  }
  wake() { const w = this.waiters; this.waiters = []; for (const f of w) f(); }
  async line(ms) {
    const end = Date.now() + ms;
    for (;;) {
      const i = this.buf.indexOf("\n");
      if (i >= 0) { const l = this.buf.slice(0, i).replace(/\r$/, ""); this.buf = this.buf.slice(i + 1); return l; }
      const left = end - Date.now();
      if (this.closed || left <= 0) return null;
      await new Promise((res) => { const t = setTimeout(res, left); this.waiters.push(() => { clearTimeout(t); res(); }); });
    }
  }
  async write(bytes) { await this.writer.write(bytes); }
  async close() {
    try { await this.reader.cancel(); } catch { /* gone already */ }
    try { await this.pump; } catch { /* ended */ }
    try { this.reader.releaseLock(); } catch { /* released */ }
    try { this.writer.releaseLock(); } catch { /* released */ }
    try { await this.port.close(); } catch { /* gone already */ }
  }
}

// The board again after a restart: the browser keeps its permission, so it is among getPorts() once it is back.
async function openBoard(info, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const ports = (await navigator.serial.getPorts()).filter((p) => {
      const i = p.getInfo();
      return i.usbVendorId === info.usbVendorId && i.usbProductId === info.usbProductId;
    });
    for (const p of ports) {
      try { return await new SerialLines(p).open(); } catch { /* not back yet, or busy */ }
    }
    await nap(500);
  }
  return null;
}

// FK? until an answer `done` accepts, for up to `ms`; null when none (or the port went away).
async function askHello(s, ms, done = () => true) {
  const end = Date.now() + ms;
  const ask = new TextEncoder().encode("FK?\n");
  while (Date.now() < end && !s.closed) {
    try { await s.write(ask); } catch { return null; }
    const l = await s.line(Math.min(1000, Math.max(1, end - Date.now())));
    const h = l == null ? null : parseHello(l);
    if (h && done(h)) return h;
    if (!h) await nap(300);
  }
  return null;
}

// The settings to the freshly written Tag Reader, then its own report of its first start. Mirrors reader_flash.setup on the
// server: the same steps. `step(name)` says which of the page's steps starts (restarting, sending, report). Resolves with
// { ok: true } or { ok: false, code, reason }: `code` is the page's text (back, answer, refused, report, wifi, hub_refused,
// hub_unreachable); the words are the catalogue's, said by the caller.
async function provisionOverSerial(info, settings, step) {
  step("restarting");
  let s = await openBoard(info, 20000);
  if (!s) return { ok: false, code: "back" };
  try {
    if (!(await askHello(s, 8000))) return { ok: false, code: "answer" };
    step("sending");
    const line = new TextEncoder().encode("FK-SET " + JSON.stringify(settings) + "\n");
    for (let i = 0; i < line.length; i += 256) { await s.write(line.slice(i, i + 256)); await nap(20); }
    const end = Date.now() + 5000;
    let got = null;
    while (Date.now() < end) {
      const l = await s.line(end - Date.now());
      if (l == null) break;
      if (l === "FK-OK" || l.startsWith("FK-ERR")) { got = l; break; }
    }
    if (got == null) return { ok: false, code: "answer" };
    if (got !== "FK-OK") return { ok: false, code: "refused", reason: got.slice(6).trim() || "?" };
  } catch (e) {
    if (e instanceof FlashStopped) throw e;
    return { ok: false, code: "answer" };
  } finally {
    await s.close();
  }
  step("report");
  // done once it has tried: with no Wi-Fi it never tries the Hub, so server stays "-"
  const done = (h) => h.configured && (h.wifi === "fail" || (h.wifi !== "-" && h.server !== "-"));
  const end = Date.now() + 60000;
  let h = null;
  while (!h && Date.now() < end) {
    s = await openBoard(info, end - Date.now());
    if (!s) break;
    try { h = await askHello(s, end - Date.now(), done); } finally { await s.close(); }
  }
  if (!h) return { ok: false, code: "report" };
  if (h.wifi !== "ok") return { ok: false, code: "wifi" };
  if (h.server === "unauth") return { ok: false, code: "hub_refused" };
  if (h.server !== "ok") return { ok: false, code: "hub_unreachable" };
  return { ok: true };
}

// ----- the write's step list (02 8.2, 8.3; 03 11.3): kept here, so a redraw of the section shows it again -----
const flashJobTitle = (name) => { const t = SW.t("job_title_" + name); return t === "job_title_" + name ? SW.t("job_title_other") : t; };
function flashStepList(dev) {
  const keys = FLASH_DEVICES[dev].steps, run = flashRun && flashRun.id === dev ? flashRun : null;
  const items = keys.map((k, i) => {
    const failed = !!run && run.failed === i, done = !!run && !failed && (run.done || i < run.at);
    const now = !!run && run.running && !failed && !done && i === run.at;
    const num = h("span", { class: "steps__num" }, done ? [SW.icon("check", "icon--s"), h("span", { class: "sr", textContent: SW.t("steps_done") })]
      : failed ? SW.shape("s-octagon") : String(i + 1));
    const bar = now && k === "writing" && run.pct != null ? run.bar = SW.progress({ label: SW.t("flash_writing_percent", { percent: run.pct }), value: run.pct / 100 }) : null;
    return h("li", { class: "steps__step", "data-state": failed ? "failed" : done ? "done" : now ? undefined : "later", "aria-current": now ? "step" : undefined },
      num, h("div", { class: "steps__body" }, h("span", { class: "steps__title", textContent: SW.t("flash_step_" + k) }), bar));
  });
  return h("ol", { class: "steps flash-steps", "aria-label": SW.t("flash_step_write") }, ...items);
}
function drawRun(dev) {
  if (!flashHost || !flashHost.isConnected) return;
  if (flashRun) flashRun.bar = null;
  flashHost.replaceChildren(flashStepList(dev || (flashRun && flashRun.id)));
}
// the percentage of the write: the bar in place, not drawn again for each report
function runPercent(p) {
  const r = flashRun;
  if (!r || r.pct === p) return;
  r.pct = p;
  if (r.bar && r.bar.isConnected) {
    SW.setProgress(r.bar, p / 100);
    const l = r.bar.querySelector(".progress__label");
    if (l) l.textContent = SW.t("flash_writing_percent", { percent: p });
  } else drawRun();
}
function runStep(name) {
  const r = flashRun, i = FLASH_DEVICES[r.id].steps.indexOf(name);
  if (r.stop) throw new FlashStopped();
  r.at = i; r.pct = null;
  drawRun();
}
const stopCheck = () => { if (flashRun && flashRun.stop) throw new FlashStopped(); };

// the words of a failure of provisionOverSerial
function provisionText(r, ssid, base) {
  const key = { back: "flash_error_back", answer: "flash_error_answer", refused: "flash_error_refused", report: "flash_error_report",
    wifi: "flash_error_wifi", hub_refused: "flash_error_hub_refused", hub_unreachable: "flash_error_hub_unreachable" }[r.code];
  return SW.t(key, { reason: r.reason, wifi: ssid, address: base });
}

// The browser way, for one device. `a`: a Tag Reader's answers (null for the display); `sent()` runs when the password has
// gone to the board. Resolves with { ok, text } for the result slot, or { stopped, text }, or { note, text } (no board).
async function flashHere(dev, a, sent) {
  const info = FLASH_DEVICES[dev.id], tag = !!a;
  let port;
  try {
    port = await navigator.serial.requestPort({ filters: [{ usbVendorId: ESPRESSIF_VID }] });
  } catch {
    return { note: true, text: SW.t("flash_no_board") };
  }
  const usb = port.getInfo();
  let tok = null, half = false;
  try {
    runStep("connecting");
    if (tag) {         // its token first: with none, nothing is written
      tok = await api("flash/provision", { code: theCode(), name: a.name || undefined });
    }
    stopCheck();
    const r = await fetch(`/setup/api/firmware/${dev.id}.bin`, { credentials: "same-origin" });
    if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { writing: true });
    const data = new Uint8Array(await r.arrayBuffer());
    const { ESPLoader, Transport } = await import("/setup/esptool.bundle.js");
    const transport = new Transport(port, false);
    try {
      const loader = new ESPLoader({ transport, baudrate: FLASH_BAUD, terminal: quietTerminal });
      await loader.main();
      runStep("writing");
      runPercent(0);
      half = true;
      await loader.writeFlash({
        fileArray: [{ data, address: 0 }], flashMode: "keep", flashFreq: "keep", flashSize: "keep",
        eraseAll: false, compress: true,
        reportProgress: (_i, written, total) => { if (flashRun.stop) throw new FlashStopped(); runPercent(Math.floor((written * 100) / total)); },
      });
      half = false;
      stopCheck();
      runStep("restarting");
      await loader.after("hard_reset");
    } catch (e) {
      if (e instanceof FlashStopped) throw e;
      throw Object.assign(new Error(e.message || String(e)), { writing: true });
    } finally {
      try { await transport.disconnect(); } catch { /* closed already */ }
    }
    if (!tag) {
      flashRun.done = true;
      return { ok: true, text: SW.t("flash_done_display", { version: dev.version }) };
    }
    const settings = { ssid: a.ssid, pass: a.pass, base: tok.base, token: tok.token, buzzer_low: a.buzzer === "older" };
    const res = await provisionOverSerial(usb, settings, (name) => { runStep(name); if (name === "sending") sent(); });
    if (!res.ok) throw Object.assign(new Error(provisionText(res, a.ssid, tok.base)), { said: true });
    flashRun.done = true;
    return { ok: true, text: SW.t("flash_done_reader", { wifi: a.ssid }) };
  } catch (e) {
    let note = "";
    if (tok) {
      try { await api(`readers/${tok.id}/revoke`, { code: theCode() }); } catch { note = " " + SW.t("flash_token_kept", { id: tok.id }); }
    }
    if (e instanceof FlashStopped) return { stopped: true, text: SW.t(half ? "flash_stopped_half" : "flash_stopped") + note };
    flashRun.failed = flashRun.at;
    const text = e.writing ? SW.t("flash_error_write", { reason: e.message }) : e.message || String(e);
    return { ok: false, text: text + note };
  }
}

// The Hub job's own step sentences (`reader setup`: cli.py, reader_flash.setup) and the page's step each belongs to. The
// settings are sent after "Checking what was written" with no sentence of their own, so a failure there is that step's: it is
// the page's "Sending the settings" (the restart before it is done by then); "Joining the Wi-Fi" is "Waiting for its report"
const HUB_STEPS = { "Finding the board": "connecting", "Writing the program": "writing", "Keeping the program that is on the board": "writing",
  "Checking what was written": "sending", "Writing the settings": "sending", "Joining the Wi-Fi": "report", "Reaching the Hub": "report" };

// A write on this page: `hub` when the Hub does it (then its job is followed), `ssid` for the done text
const newRun = (id, extra) => (flashRun = { id, at: 0, failed: -1, done: false, running: true, pct: null, stop: false, ...extra });

// The Hub's job (reader_setup) as the page's step list: its numbered steps follow the list in order. Stops when the job has
// ended or the page left the section; a visit later takes it up again. A job this page just started may not have written its
// log yet: an older or other job is ignored for 15 s.
async function followHubJob() {
  if (flashWatching) return;
  flashWatching = true;
  try {
    while (tabNow() === "flash") {
      let r;
      try { r = await api("job?from=999999999"); } catch { await nap(2000); continue; }
      const run = flashRun && flashRun.hub ? flashRun : newRun("printer-station", { hub: true, seen: true, since: Date.now() });
      const mine = r.name === "reader_setup" && (r.running || run.seen);
      if (!mine) {
        if (Date.now() - run.since > 15000) { run.running = false; drawRun(); return; }
        await nap(1000);
        continue;
      }
      run.seen = true;
      const n = FLASH_DEVICES["printer-station"].steps.length;
      if (r.step) {       // by the job's own sentence; a sentence not known keeps the place, never goes back
        const at = FLASH_DEVICES["printer-station"].steps.indexOf(HUB_STEPS[r.step.text]);
        if (at >= run.at) run.at = Math.min(n - 1, at);
      }
      if (!r.running) {
        run.running = false;
        if (r.exit === 0 && !r.lost) run.done = true; else { run.failed = run.at; fill(boxFor("flash")); }
        drawRun();
        if (run.done && run.ssid) say(boxFor("flash"), SW.t("flash_done_reader", { wifi: run.ssid }), true);
        flashSync();
        return;
      }
      drawRun();
      await nap(1000);
    }
  } finally { flashWatching = false; }
}

// radio choices as wrapping cards (device, buzzer): the shared segmented choice, its options allowed to wrap (setup.css); `onPick(value)`
function flashChoice(name, legend, options, value, onPick, legendSr) {
  const fs = SW.segmented({ legend, legendSr, name, value, wide: true, cls: "flash-choice", options });
  fs.addEventListener("change", (e) => onPick(e.target.value));
  return fs;
}

function drawFlash(body, F, J) {
  const devs = F.devices.filter((d) => d.bundled && FLASH_DEVICES[d.id]);
  if (!devs.length) { fill(body, SW.empty({ icon: "flash", title: SW.t("flash_empty_title"), text: SW.t("flash_empty_text") })); return; }
  const place = location.hash.slice(1).split("/")[1];
  const fromAddress = devs.find((d) => FLASH_DEVICES[d.id].place === place);
  if (fromAddress) flashPick.device = fromAddress.id;
  else if (!devs.some((d) => d.id === flashPick.device)) flashPick.device = devs[0].id;
  const phone = SW.phone();
  if (!flashPick.where || (phone && flashPick.where === "computer")) flashPick.where = webSerialOk() && !phone ? "computer" : "hub";
  const box = boxFor("flash");
  const state = () => ({ dev: devs.find((d) => d.id === flashPick.device), here: flashPick.where === "computer" });
  const running = () => !!flashRun && flashRun.running;
  const hubBusy = () => !!(J && J.running && J.name !== "reader_setup");

  // 1 device
  const deviceEl = flashChoice("flash-device", SW.t("flash_step_device"), devs.map((d) => ({ value: d.id, label: SW.t(FLASH_DEVICES[d.id].name),
    count: SW.t("flash_firmware", { version: d.version }) })), flashPick.device, (v) => {
    flashPick.device = v;
    history.replaceState(null, "", "#flash/" + FLASH_DEVICES[v].place);
    if (!running()) { flashRun = null; fill(box); }
    sync();
  }, true);
  // 2 plugged into
  const whereEl = SW.segmented({ legend: SW.t("flash_step_plugged"), legendSr: true, name: "flash-where", value: flashPick.where, options: [
    { value: "computer", label: SW.t("flash_plugged_computer"), disabled: phone }, { value: "hub", label: SW.t("flash_plugged_hub") }] });
  whereEl.addEventListener("change", (e) => { flashPick.where = e.target.value; if (!running()) { flashRun = null; fill(box); } sync(); });
  const phoneNote = phone ? h("p", { class: "muted", textContent: SW.t("flash_phone_note") }) : null;
  // 3 settings (a Tag Reader)
  const ssid = SW.field({ label: SW.t("flash_wifi_name"), name: "ssid", check: (v) => (v.trim() ? null : SW.t("flash_wifi_name_error")) });
  const pass = SW.field({ label: SW.t("flash_wifi_password"), type: "secret", name: "pass", hint: SW.t("flash_wifi_password_hint"), optional: true });
  const again = SW.field({ label: SW.t("flash_wifi_again"), type: "secret", name: "again", optional: true,
    check: (v) => (v === pass._control.value ? null : SW.t("flash_wifi_mismatch")) });
  const buzzer = flashChoice("flash-buzzer", SW.t("flash_buzzer"), [{ value: "high", label: SW.t("flash_buzzer_high") }, { value: "older", label: SW.t("flash_buzzer_older") }], "high", () => {});
  const name = SW.field({ label: SW.t("flash_name"), name: "name", optional: true, hint: SW.t("flash_name_hint") });
  const boards = () => F.server_boards || [];
  const board = SW.field({ label: SW.t("flash_board"), type: "select", name: "board", options: boards().map((b) => ({ value: b.port, label: SW.t("flash_board_option", { port: b.port, product_name: b.product }) })) });
  const settingsEl = h("div", { class: "flash-form" }, ssid, pass, again, buzzer, name, board);
  // 4 write
  const goHere = SW.btn(SW.t("flash_connect_write"), { cls: "btn--primary" });
  const goHub = SW.btn(SW.t("flash_write_hub"), { cls: "btn--primary" });
  const stop = SW.btn(SW.t("common_stop"));
  const hint = h("p", { class: "muted", textContent: SW.t("flash_connect_hint") });
  const displayHub = h("p", { textContent: SW.t("flash_display_hub") });
  flashHost = h("div", { class: "flash-run" });
  const writeEl = h("div", { class: "flash-write" }, displayHub, h("div", { class: "row" }, goHere, goHub, stop, hint), flashHost, box);

  const answers = () => {
    const bad = [[ssid, ssid._check()], [again, again._check()]].filter(([f, e]) => (SW.fieldError(f, e), e));
    if (bad.length) { bad[0][0]._control.focus(); return null; }
    return { ssid: ssid._control.value.trim(), pass: pass._control.value, buzzer: buzzer.querySelector("input:checked").value, name: name._control.value.trim() };
  };
  const noPublic = () => {
    if (F.settings_ok) return false;
    say(box, [h("p", { textContent: SW.t("flash_no_public") }), h("a", { href: "#settings/network", textContent: SW.t("nav_settings") })], false);
    return true;
  };
  goHere.addEventListener("click", () => {
    const { dev, here } = state();
    if (!here || running() || goHere.getAttribute("aria-disabled") === "true") return;
    const tag = dev.id === "printer-station", a = tag ? answers() : null;
    if (tag && (!a || noPublic())) return;
    needCode(async () => {
      fill(box);
      newRun(dev.id, { ssid: a && a.ssid });
      drawRun(dev.id);
      sync();
      const r = await flashHere(dev, a, () => flashClear());      // the section may have been drawn again: the live one is cleared
      flashRun.running = false;
      if (r.note || r.stopped) flashRun = r.stopped ? flashRun : null;
      drawRun(dev.id);
      say(box, r.text, r.note ? "info" : r.stopped ? "warn" : r.ok);
      flashSync();
    });
  });
  stop.addEventListener("click", () => { if (flashRun) flashRun.stop = true; stop.disabled = true; });
  goHub.addEventListener("click", () => {
    if (running() || goHub.getAttribute("aria-disabled") === "true") return;
    const a = answers();
    if (!a || noPublic()) return;
    const port = boards().length > 1 ? board._control.value : boards()[0].port;
    change(box, "flash/server", { ssid: a.ssid, pass: a.pass, buzzer: a.buzzer === "older" ? "low" : "high", port, name: a.name || undefined }, () => {
      newRun("printer-station", { hub: true, ssid: a.ssid, since: Date.now() });
      flashSync();
      say(box, SW.t("flash_hub_started"), "info");
      followApply(true);
      followHubJob();
    }, [pass._control, again._control]);
  });

  // what shows for the choices made; runs again when a choice, a run or the Hub's boards change
  const sync = () => {
    const { dev, here } = state(), tag = dev.id === "printer-station", busy = running();
    settingsEl.hidden = !tag;
    settingsStep.hidden = !tag;
    board.hidden = !(tag && !here && boards().length > 1);
    for (const i of deviceEl.elements) i.disabled = busy;
    for (const i of whereEl.elements) i.disabled = busy || (phone && i.value === "computer");
    for (const i of [...buzzer.elements, ...settingsEl.querySelectorAll(".field__control")]) i.disabled = busy;
    goHere.hidden = !here;
    goHub.hidden = here || !tag;
    stop.hidden = !(here && busy);
    stop.disabled = !!(flashRun && flashRun.stop);
    hint.hidden = !here || busy;
    displayHub.hidden = here || tag;
    flashHost.hidden = !(here || tag);
    // a reason stays beside its button only while the button shows
    SW.disable(goHere, !here ? null : busy ? SW.t("common_busy_wait") : !webSerialOk() ? SW.t("flash_no_serial") : null);
    SW.disable(goHub, here || !tag ? null : busy || (flashRun && flashRun.hub && flashRun.running) ? SW.t("common_busy_wait")
      : hubBusy() ? SW.t("flash_wait_job", { title: flashJobTitle(J.name) }) : !boards().length ? SW.t("flash_no_boards") : null);
    // the steps count what is shown
    let n = 0;
    for (const li of stepsEl.children) if (!li.hidden) li.querySelector(".steps__num").textContent = String(++n);
    drawRun(dev.id);
  };

  const step = (title, ...kids) => h("li", { class: "steps__step" }, h("span", { class: "steps__num" }),
    h("div", { class: "steps__body" }, h("span", { class: "steps__title", textContent: title }), ...kids));
  const settingsStep = step(SW.t("flash_step_settings"), settingsEl);
  const stepsEl = h("ol", { class: "steps" }, step(SW.t("flash_step_device"), deviceEl),
    step(SW.t("flash_step_plugged"), whereEl, phoneNote, h("p", { class: "muted", textContent: SW.t("flash_plugged_hint") })),
    settingsStep, step(SW.t("flash_step_write"), writeEl));
  flashSync = sync;
  flashClear = () => { pass._control.value = again._control.value = ""; };
  fill(body, h("p", { class: "muted", textContent: SW.t("flash_intro") }), stepsEl);
  sync();
  // the Hub's boards, read again every 3 s while a Tag Reader on the Hub waits for one
  const poll = setInterval(async () => {
    if (!body.isConnected) { clearInterval(poll); return; }
    const { dev, here } = state();
    if (here || dev.id !== "printer-station" || boards().length || running()) return;
    try { const f = await api("firmware"); F.server_boards = f.server_boards; } catch { return; }
    if (!boards().length) return;
    board._control.replaceChildren(...boards().map((b) => h("option", { value: b.port, textContent: SW.t("flash_board_option", { port: b.port, product_name: b.product }) })));
    sync();
  }, 3000);
  if (flashRun && flashRun.hub && flashRun.running || J && J.running && J.name === "reader_setup") followHubJob();
}

function flashTab() {
  const body = h("div");
  later(readRegion(body, "flash", () => Promise.all([api("firmware"), api("job?from=999999999")]), ([F, J]) => drawFlash(body, F, J)));
  return [h("section", { class: "card" }, body)];
}
