// The console's "Flash a device" tab (setup_console/flash_tab.py). Loaded after setup.js; everything from the server goes
// in through textContent. Two ways to write the kit's own firmware (from this kit, never the internet) to an ESP32-C3:
//  - into this computer: the browser writes it over Web Serial with esptool-js (esptool.bundle.js, loaded only then),
//    then, for the Printer Station, sends its settings over the same USB port (FK? / FK-SET, reader settings.h) and
//    waits for its own report of the Wi-Fi and the kit;
//  - into the server: the server does the same (`reader setup`) as a background job.
// The Wi-Fi password and the reader token go only to the board (and, the server way, to the server): never shown,
// logged, or put in an address; the inputs are cleared once sent.
"use strict";

const FLASH_BAUD = 460800;
const ESPRESSIF_VID = 0x303a;
const NO_SERIAL = "Writing from this computer needs Chrome or Edge on a desktop or laptop computer (phones and other " +
  "browsers can't reach USB from a page). Use one of those, or plug the device into the server.";
const webSerialOk = () => "serial" in navigator && window.isSecureContext;
const nap = (ms) => new Promise((res) => setTimeout(res, ms));
const quietTerminal = { clean() {}, writeLine() {}, write() {} };
let flashPick = { device: "printer-station", where: webSerialOk() ? "here" : "server" };

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

// The settings to the freshly written Printer Station, then its own report of its first start. Mirrors
// reader_flash.setup on the server: the same steps and the same plain reasons.
async function provisionOverSerial(info, settings, say_) {
  let s = await openBoard(info, 20000);
  if (!s) return { ok: false, message: "The board was written but did not come back on USB. Unplug it, plug it in again, then try again." };
  try {
    if (!(await askHello(s, 8000))) return { ok: false, message: "The board was written but does not answer as the Printer Station. Unplug it, plug it in again, then try again." };
    const line = new TextEncoder().encode("FK-SET " + JSON.stringify(settings) + "\n");
    for (let i = 0; i < line.length; i += 256) { await s.write(line.slice(i, i + 256)); await nap(20); }
    const end = Date.now() + 5000;
    let got = null;
    while (Date.now() < end) {
      const l = await s.line(end - Date.now());
      if (l == null) break;
      if (l === "FK-OK" || l.startsWith("FK-ERR")) { got = l; break; }
    }
    if (got == null) return { ok: false, message: "The Printer Station did not answer the settings. Unplug it, plug it in again, then try again." };
    if (got !== "FK-OK") return { ok: false, message: `The Printer Station refused the settings: ${got.slice(6).trim() || "no reason given"}.` };
  } catch (e) {
    return { ok: false, message: `Sending the settings failed (${e.message}). Unplug the board, plug it in again, then try again.` };
  } finally {
    await s.close();
  }
  say_("Settings written; the Printer Station is restarting and joining the Wi-Fi (up to a minute)…");
  // done once it has tried: with no Wi-Fi it never tries the kit, so server stays "-"
  const done = (h) => h.configured && (h.wifi === "fail" || (h.wifi !== "-" && h.server !== "-"));
  const end = Date.now() + 60000;
  let h = null;
  while (!h && Date.now() < end) {
    s = await openBoard(info, end - Date.now());
    if (!s) break;
    try { h = await askHello(s, end - Date.now(), done); } finally { await s.close(); }
  }
  const ssid = settings.ssid;
  if (!h) return { ok: false, message: "The Printer Station took its settings but did not report back within a minute. Watch its screen: it says whether it reached the Wi-Fi and the kit." };
  if (h.wifi !== "ok") return { ok: false, message: `The Printer Station could not join the Wi-Fi network "${ssid}": check the name and the password (and that it is a 2.4 GHz network), then try again.` };
  if (h.server === "unauth") return { ok: false, message: "The Printer Station reached the kit, but the kit did not accept its token. Try again to give it a new one." };
  if (h.server !== "ok") return { ok: false, message: `The Printer Station joined "${ssid}" but could not reach the kit at ${settings.base}: check the kit's public address (Settings) and that its network can reach it.` };
  return { ok: true, message: `Done. The Printer Station joined "${ssid}" and reached the kit. Unplug it and power it where it lives; it keeps its settings.` };
}

// The browser way, for one device. `a`: the Printer Station's answers (null for the panel).
async function flashHere(dev, a, box) {
  if (!webSerialOk()) { say(box, NO_SERIAL, false); return; }
  let port;
  try {
    port = await navigator.serial.requestPort({ filters: [{ usbVendorId: ESPRESSIF_VID }] });
  } catch {
    say(box, "No board picked. Plug it in with a data cable (a charge-only cable shows nothing), then press the button again and pick it.", false);
    return;
  }
  const info = port.getInfo();
  let tok = null;
  try {
    if (dev.settings) {         // its token first: with none, nothing is written
      say(box, "Making the Printer Station's token…", true);
      tok = await api("flash/provision", { code: codeIn.value, name: a.name || undefined });
      offerTrust();
    }
    say(box, "Getting the firmware from this kit…", true);
    const r = await fetch(`/setup/api/firmware/${dev.id}.bin`, { credentials: "same-origin" });
    if (!r.ok) throw new Error(`this kit did not give the firmware (HTTP ${r.status})`);
    const data = new Uint8Array(await r.arrayBuffer());
    const { ESPLoader, Transport } = await import("/setup/esptool.bundle.js");
    const transport = new Transport(port, false);
    try {
      const loader = new ESPLoader({ transport, baudrate: FLASH_BAUD, terminal: quietTerminal });
      say(box, "Connecting to the board…", true);
      await loader.main();
      await loader.writeFlash({
        fileArray: [{ data, address: 0 }], flashMode: "keep", flashFreq: "keep", flashSize: "keep",
        eraseAll: false, compress: true,
        reportProgress: (_i, written, total) => say(box, `Writing the ${dev.title} firmware: ${Math.floor((written * 100) / total)}%`, true),
      });
      await loader.after("hard_reset");
    } catch (e) {
      throw new Error(`writing the firmware failed (${e.message || e}). Unplug the board, plug it in again, then try again`);
    } finally {
      try { await transport.disconnect(); } catch { /* closed already */ }
    }
    if (!dev.settings) {
      say(box, `Done: the ${dev.title} firmware (${dev.version}) is written. Plug the panel into the station computer; the station finds it by itself.`, true);
      return;
    }
    say(box, "Written. Waiting for the Printer Station to start…", true);
    const settings = { ssid: a.ssid, pass: a.pass, base: tok.base, token: tok.token, buzzer_low: a.buzzer === "low" };
    const res = await provisionOverSerial(info, settings, (t) => say(box, t, true));
    if (!res.ok) throw new Error(res.message);
    say(box, `${res.message} (Reader token ${tok.id}; remove it on the Devices tab when the station is retired.)`, true);
  } catch (e) {
    let note = "";
    if (tok) {
      try { await api(`readers/${tok.id}/revoke`, { code: codeIn.value }); note = " The new reader token was removed."; } catch { note = ` Remove the reader token ${tok.id} on the Devices tab.`; }
    }
    say(box, (e.message || String(e)) + note, false);
  }
}

function flashTab() {
  const body = h("div"), box = boxFor("flash");
  const el = card("Flash a device", body, box);
  (async () => {
    let F;
    try { F = await api("firmware"); } catch (e) { say(body, e.message, false); return; }
    const devs = F.devices.filter((d) => d.bundled);
    if (!devs.length) { say(body, "This kit has no device firmware bundled. Update the kit (Updates).", false); return; }
    if (!devs.some((d) => d.id === flashPick.device)) flashPick.device = devs[0].id;
    const draw = () => {
      const dev = devs.find((d) => d.id === flashPick.device);
      const choose = (key, value, label) => h("button", {
        class: flashPick[key] === value ? "" : "secondary", textContent: label,
        on: { click: () => { flashPick[key] = value; box.replaceChildren(); draw(); } } });
      const kids = [
        h("p", { class: "muted", textContent: "Writes this kit's own firmware to the device's ESP32-C3 over USB, from the files of the installed kit version. Use a data cable (a charge-only one shows nothing)." }),
        h("div", { class: "row" }, h("span", { textContent: "Device: " }),
          ...devs.map((d) => choose("device", d.id, `${d.title} (${d.id === "printer-station" ? "build " : ""}${d.version})`))),
        h("div", { class: "row" }, h("span", { textContent: "Plugged into: " }),
          choose("where", "here", "This computer"), choose("where", "server", "The kit server")),
      ];
      if (flashPick.where === "here" && !webSerialOk()) kids.push(h("p", { class: "err", textContent: NO_SERIAL }));
      if (dev.id === "intake-panel") {
        if (flashPick.where === "here") {
          kids.push(h("p", { class: "muted", textContent: "The panel needs no settings: once written, it goes onto the station computer's USB." }),
            h("div", { class: "row" }, h("button", { textContent: "Connect and write", disabled: !webSerialOk(),
              on: { click: () => flashHere(dev, null, box) } })));
        } else {
          kids.push(h("p", { textContent: F.station_here
            ? "Plug the panel into this server: the station writes its firmware to it by itself when it finds the panel (within a minute), and the panel then shows the station's screen."
            : "The intake panel lives on the station computer, not on this server: plug it in there and the station writes its firmware to it by itself. Or write it from this computer's USB." }));
        }
      } else {
        const ssid = h("input", { ariaLabel: "Wi-Fi name", placeholder: "Wi-Fi name (2.4 GHz)", autocomplete: "off" });
        const pass = secret("Wi-Fi password"), again = secret("The password again");
        const buzzer = h("select", { ariaLabel: "Buzzer" },
          h("option", { value: "high", textContent: "High-triggered (behind a MOSFET, as in the parts list)" }),
          h("option", { value: "low", textContent: "Low-triggered (the older 3-pin module)" }));
        const name = h("input", { ariaLabel: "Name", placeholder: "Name (optional, e.g. bench)", autocomplete: "off" });
        const boards = F.server_boards || [];
        const portSel = boards.length > 1 ? h("select", { ariaLabel: "Board" },
          ...boards.map((b) => h("option", { value: b.port, textContent: `${b.port} (${b.product})` }))) : null;
        const answers = () => {
          if (!ssid.value.trim()) { say(box, "Type the Wi-Fi name.", false); return null; }
          if (pass.value !== again.value) { say(box, "The two passwords differ.", false); return null; }
          return { ssid: ssid.value.trim(), pass: pass.value, buzzer: buzzer.value, name: name.value.trim() };
        };
        kids.push(
          F.settings_ok ? null : h("p", { class: "err", textContent: `The Printer Station can't be set up yet: ${F.settings_why}` }),
          h("div", { class: "row" }, ssid, pass, again),
          h("div", { class: "row" }, h("label", {}, "Buzzer: ", buzzer), name));
        if (flashPick.where === "here") {
          kids.push(h("div", { class: "row" }, h("button", { textContent: "Connect and write", disabled: !webSerialOk() || !F.settings_ok,
            on: { click: () => { const a = answers(); if (!a) return; pass.value = again.value = ""; flashHere(dev, a, box); } } })));
        } else if (!boards.length) {
          kids.push(h("p", { class: "muted", textContent: "No ESP32 board on the server's USB right now. Plug the Printer Station in, then look again." }),
            h("div", { class: "row" }, h("button", { class: "secondary", textContent: "Look again", on: { click: () => render() } })));
        } else {
          kids.push(h("div", { class: "row" }, portSel || h("span", { class: "muted", textContent: `Board: ${boards[0].port} (${boards[0].product})` }),
            h("button", { textContent: "Write and set up", disabled: !F.settings_ok, on: { click: () => {
              const a = answers();
              if (!a) return;
              change(box, "flash/server", { ...a, port: portSel ? portSel.value : boards[0].port, name: a.name || undefined },
                () => { box.replaceChildren(); followApply(true); }, [pass, again]);
            } } })));
        }
      }
      fill(body, ...kids);
    };
    draw();
  })();
  return [el];
}
