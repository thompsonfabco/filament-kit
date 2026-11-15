// Browser walk of the Hub page's Flash a device section (design 09 S2.16), driven by server/tests/test_hub_page_audit.py: opens
// the page in a headless Chrome, Edge or Chromium already on the machine, with a fake Web Serial board and a fake esptool-js (the page's
// own provisioning code runs against them), and prints { checks: [{ ok, what }], audit: [{ state, findings }] } as JSON. Every state
// it reaches is also audited with tests/page_audit.js. Test-only: never shipped, never run on a Hub.
//   node tests/flash_walk.mjs <page url> <control file> <setup code> [<screenshot folder>]
// The control file ({"boards": n, "jobfail": bool}) is how the test's fake Hub is told what is plugged in and how its job ends.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const [, , BASE, CTL, CODE, SHOTS] = process.argv;
const HERE = dirname(fileURLToPath(import.meta.url));
const AUDIT = readFileSync(join(HERE, "page_audit.js"), "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const env = process.env;
const roots = [env["ProgramFiles(x86)"], env.ProgramFiles, env.LOCALAPPDATA, ...["C:", "D:", "G:"].flatMap((d) => [`${d}\\Program Files (x86)`, `${d}\\Program Files`])].filter(Boolean);
const exe = env.AUT5_BROWSER || [...roots.flatMap((r) => [`${r}\\Microsoft\\Edge\\Application\\msedge.exe`, `${r}\\Google\\Chrome\\Application\\chrome.exe`]),
  "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/microsoft-edge", "/snap/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
if (!exe) { console.error("AUT-5: no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); process.exit(2); }
const profile = mkdtempSync(join(tmpdir(), "aut5-flash-"));
const linux = process.platform === "linux" ? ["--no-sandbox", "--disable-dev-shm-usage"] : [];
const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", ...linux, "about:blank"], { stdio: "ignore" });
const cleanup = () => { try { proc.kill(); } catch { /* gone */ } try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* held */ } };
process.on("exit", cleanup);
const checks = [], audit = [];
const check = (ok, what) => checks.push({ ok: !!ok, what });

// the fake board speaks the firmware's lines (settings.h) and restarts after FK-SET; the fake esptool "writes" in ten reports
const FAKE_PAGE = String.raw`(() => {
  const enc = new TextEncoder(), dec = new TextDecoder();
  const f = window.__fake = { scenario: { wifi: "ok", server: "ok" }, settings: null, picked: true, wdelay: 250, events: [], mute: false };
  const origFetch = window.fetch;
  window.fetch = (u, o) => { const s = String(u); if (/flash\/provision|firmware\/|\/revoke/.test(s)) f.events.push(s.replace(/^.*\/api\//, "")); return origFetch(u, o); };
  const board = { gone: false };
  const makePort = () => {
    let ctl = null, buf = "";
    const say = (t) => { if (ctl) ctl.enqueue(enc.encode(t)); };
    return {
      getInfo: () => ({ usbVendorId: 0x303a, usbProductId: 0x1001 }),
      async open() {
        if (board.gone) throw new Error("not there");
        this.readable = new ReadableStream({ start(c) { ctl = c; } });
        this.writable = new WritableStream({ write(chunk) {
          buf += dec.decode(chunk);
          let i;
          while ((i = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, i); buf = buf.slice(i + 1);
            if (line === "FK?") {
              if (f.mute) continue;
              const done = f.settings !== null;
              say("FK-READER 1794501335 configured=" + (done ? 1 : 0) + " wifi=" + (done ? f.scenario.wifi : "-") + " server=" + (done ? f.scenario.server : "-") + "\n");
            } else if (line.startsWith("FK-SET ")) {
              f.settings = JSON.parse(line.slice(7));
              say("FK-OK\n");
              setTimeout(() => { board.gone = true; try { ctl.close(); } catch {} setTimeout(() => { board.gone = false; }, 800); }, 50);
            }
          }
        } });
      },
      async setSignals() {}, async close() {},
    };
  };
  const port = makePort();
  Object.defineProperty(navigator, "serial", { value: { requestPort: async () => { if (!f.picked) throw new Error("no port"); return port; }, getPorts: async () => [port] }, configurable: true });
})();`;
const FAKE_ESPTOOL = `
export class Transport { constructor(port) {} async disconnect() {} }
export class ESPLoader { constructor(o) {} async main() { await new Promise((r) => setTimeout(r, 200)); }
  async writeFlash(o) { globalThis.__fake.events.push("write"); for (let i = 0; i <= 10; i++) { o.reportProgress(0, i * 10, 100); await new Promise((r) => setTimeout(r, globalThis.__fake.wdelay)); } }
  async after() {} }
`;

let cdpPort;
for (let i = 0; i < 300 && !cdpPort; i++) { await sleep(100); try { cdpPort = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { /* not yet */ } }
if (!cdpPort) { console.error("AUT-5: the browser could not start"); process.exit(3); }
const target = (await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json()).find((t) => t.type === "page");
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res) => { ws.onopen = res; });
let id = 0;
const waiting = new Map(), errors = [];
const send = (method, params = {}) => new Promise((res, rej) => { const n = ++id; waiting.set(n, [res, rej]); ws.send(JSON.stringify({ id: n, method, params })); });
ws.onmessage = async (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && waiting.has(msg.id)) { const [res, rej] = waiting.get(msg.id); waiting.delete(msg.id); msg.error ? rej(new Error(msg.error.message)) : res(msg.result); }
  else if (msg.method === "Runtime.exceptionThrown") errors.push((msg.params.exceptionDetails.exception || {}).description || msg.params.exceptionDetails.text);
  else if (msg.method === "Fetch.requestPaused") {
    if (msg.params.request.url.includes("/setup/esptool.bundle.js")) {
      await send("Fetch.fulfillRequest", { requestId: msg.params.requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "text/javascript" }],
        body: Buffer.from(FAKE_ESPTOOL).toString("base64") });
    } else await send("Fetch.continueRequest", { requestId: msg.params.requestId });
  }
};
const ev = async (expression) => { const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails.text)); return r.result.value; };
const waitFor = async (expr, ms = 15000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await ev(expr)) return true; await sleep(100); } return false; };
const ctl = (o) => writeFileSync(CTL, JSON.stringify({ ...JSON.parse(readFileSync(CTL, "utf8")), ...o }));
await send("Page.enable"); await send("Runtime.enable");
await send("Fetch.enable", { patterns: [{ urlPattern: "*esptool.bundle.js*" }] });
await send("Page.addScriptToEvaluateOnNewDocument", { source: FAKE_PAGE });

let width = 1280, scheme = "light";
async function view(w, s) {
  width = w; scheme = s;
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: s }] });
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: w <= 600 });
  await send("Emulation.setTouchEmulationEnabled", { enabled: w <= 600, maxTouchPoints: 1 });
}
async function open(hash) {
  const u = new URL(BASE); u.searchParams.set("t", String(Date.now()));
  await send("Page.navigate", { url: u.href + hash });
  await waitFor("document.readyState === 'complete'");
  await waitFor("!!document.querySelector('.steps') || !!document.querySelector('.empty')", 20000);
  await sleep(300);
}
const click = (sel, text) => ev(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})].find((b) => b.offsetParent !== null && (!${JSON.stringify(text || "")} || b.textContent.trim().startsWith(${JSON.stringify(text || "")}))); if (!e) return false; e.click(); return true; })()`);
const setField = (label, value) => ev(`(() => { const f = [...document.querySelectorAll(".field")].find((x) => x.querySelector(".field__label").firstChild.textContent.trim() === ${JSON.stringify(label)});
  if (!f) return false; f._control.value = ${JSON.stringify(value)}; f._control.dispatchEvent(new Event("input", { bubbles: true })); f._control.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
const radio = (name, value) => ev(`(() => { const r = document.querySelector('input[name="${name}"][value="${value}"]'); if (!r || r.disabled) return false; r.click(); return true; })()`);
async function unlock() {
  await click(".chip--lock");
  await waitFor("!!document.querySelector('.dialog input[name=code]')", 8000);
  await ev(`(() => { const i = document.querySelector('.dialog input[name=code]'); i.value = ${JSON.stringify(CODE)}; i.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await click(".dialog__foot button", "Unlock");
  await waitFor("!document.querySelector('.dialog[open]')", 8000);
  await sleep(300);
}
async function openUnlocked(hash) { await open(hash); await unlock(); }
// the page draws the section again, and its data is read again: wait until the form is back
async function redraw() { await ev("render()"); await sleep(300); await waitFor(`!!document.querySelector('input[name="flash-buzzer"]') && !document.querySelector('[aria-busy="true"]:not(button)')`, 10000); }
const result = () => ev(`(document.querySelector(".flash-write .result") || {}).textContent || ""`);
const states = () => ev(`[...document.querySelectorAll(".flash-steps .steps__step")].map((li) => li.dataset.state || (li.getAttribute("aria-current") ? "current" : ""))`);
const writeButton = (text) => ev(`(() => { const b = [...document.querySelectorAll(".flash-write button")].find((x) => x.textContent.trim().startsWith(${JSON.stringify(text)})); return b ? { shown: !b.hidden, busy: b.getAttribute("aria-disabled") === "true" } : null; })()`);
// the page audit in the state the page is in now
async function audited(state) {
  audit.push({ state: `${state} (${width} px, ${scheme})`, findings: ((await ev(AUDIT)) || []).filter((f) => f.check !== "title unchanged between views") });
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    const m = await send("Page.getLayoutMetrics");
    const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(Math.ceil(m.cssContentSize.height), 4000), scale: 1 } });
    writeFileSync(join(SHOTS, `s216-${state.replace(/\W+/g, "-")}-${width}-${scheme}.png`), Buffer.from(r.data, "base64"));
  }
}
const fill3 = async (ssid = "Workshop", pass = "hunter22") => { await setField("Wi-Fi name", ssid); await setField("Wi-Fi password", pass); await setField("Password again", pass); };

try {
  // ---- the states of the section, audited ----
  for (const [w, s] of [[1280, "dark"], [320, "light"]]) {       // the page's other tests audit the section light and dark at both widths
    await view(w, s);
    await open("#flash/tag-reader"); await audited("tag-reader");
    await open("#flash/display"); await audited("display");
  }
  await view(1280, "light");
  await open("#flash/display"); await radio("flash-where", "hub"); await audited("display-on-the-hub");
  await open("#flash/tag-reader"); await radio("flash-where", "hub"); await audited("hub-no-board");
  ctl({ boards: 1 });
  check(await waitFor(`(() => { const b = [...document.querySelectorAll('.flash-write button')].find((x) => x.textContent.startsWith('Write on the Hub')); return b && b.getAttribute('aria-disabled') !== 'true'; })()`, 8000), "a board plugged into the Hub is seen by itself");
  await audited("hub-one-board");
  ctl({ boards: 2 });
  await open("#flash/tag-reader"); await radio("flash-where", "hub"); await audited("hub-two-boards");
  await click(".flash-write button", "Write on the Hub");
  await audited("hub-field-errors");
  await view(320, "light");
  await open("#flash/tag-reader"); check(await ev(`document.querySelector('input[name=flash-where][value=computer]').disabled`), "on a phone This computer is disabled"); await audited("phone");
  await view(1280, "light");

  // ---- the Hub way: the buzzer choice reaches the Hub as high or low, the job's own steps mark the failed step ----
  for (const [pick, want] of [["older", "low"], ["high", "high"]]) {
    ctl({ boards: 1, jobfail: false });
    await openUnlocked("#flash/tag-reader"); await radio("flash-where", "hub");
    await fill3(); await radio("flash-buzzer", pick);
    await redraw();                           // any redraw (a job ended, the lock changed) keeps the choice
    check(await ev(`document.querySelector('input[name="flash-buzzer"][value="${pick}"]').checked`), `Hub way (${pick}): the buzzer choice survives a redraw`);
    await click(".flash-write button", "Write on the Hub");
    check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('has started')`, 10000), `Hub way (${pick}): the job starts`);
    check(await waitFor(`!!document.querySelector('.flash-steps .steps__step[aria-current=step]')`, 8000), `Hub way (${pick}): the step list follows the job`);
    check((await writeButton("Write on the Hub")).busy, `Hub way (${pick}): Write on the Hub is disabled while the job runs`);
    check(await waitFor(`document.querySelectorAll('.flash-steps .steps__step[data-state=done]').length === 5`, 25000), `Hub way (${pick}): the job's five steps end done`);
    await sleep(500);
    check(!(await writeButton("Write on the Hub")).busy, `Hub way (${pick}): the button is free again`);
    await audited(`hub-done-${pick}`);
  }
  ctl({ jobfail: true });
  await openUnlocked("#flash/tag-reader"); await radio("flash-where", "hub"); await fill3();
  await click(".flash-write button", "Write on the Hub");
  check(await waitFor(`document.querySelectorAll('.flash-steps .steps__step[data-state=failed]').length === 1`, 25000), "Hub way: a failed job marks one failed step");
  const st = await states();
  check(JSON.stringify(st) === JSON.stringify(["done", "done", "done", "done", "failed"]), "Hub way: the job failed at Joining the Wi-Fi, so Waiting for its report is the failed step: " + st.join(","));
  check(!(await result()).includes("has started"), "Hub way: a failed job leaves no 'has started' text");
  check(!(await writeButton("Write on the Hub")).busy, "Hub way: the button is free after a failed job");
  await audited("hub-failed");
  ctl({ jobfail: false });

  // ---- a Hub job that ends before the page looks: the section is not left stuck ----
  ctl({ jobfail: true, instant: true });
  await openUnlocked("#flash/tag-reader"); await radio("flash-where", "hub"); await fill3();
  await click(".flash-write button", "Write on the Hub");
  check(await waitFor(`document.querySelectorAll('.flash-steps .steps__step[data-state=failed]').length === 1`, 25000), "fast failing Hub job: the failed step is marked");
  check(!(await writeButton("Write on the Hub")).busy, "fast failing Hub job: the button is free");
  check(!(await result()).includes("has started"), "fast failing Hub job: no 'has started' text is left");
  ctl({ jobfail: false, instant: false });

  // ---- Locked: nothing is asked of the Hub or the board before the code ----
  await sleep(1500);
  await open("#flash/tag-reader");
  await ev("window.__fake.events.length = 0"); await fill3();
  await click(".flash-write button", "Connect and write");
  check(await waitFor("!!document.querySelector('.dialog input[name=code]')", 8000), "Locked: Connect and write asks for the code");
  check((await ev("window.__fake.events")).length === 0, "Locked: no request was made before the code");
  await audited("locked-dialog");
  await click(".dialog__foot button", "Cancel");

  // ---- this computer: the token before the write, a redraw during the run, revoke on failure, Stop ----
  await sleep(1500);
  await openUnlocked("#flash/tag-reader");
  await fill3(); await radio("flash-buzzer", "older");
  await redraw();
  check(await ev(`document.querySelector('input[name="flash-buzzer"][value="older"]').checked`), "this computer: the buzzer choice survives a redraw");
  const n0 = await ev("api('state').then((s) => s.readers.list.length)");
  await ev("window.__fake.wdelay = 300");
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`!!document.querySelector('.flash-steps .progress')`, 10000), "this computer: a bar shows while writing");
  await audited("computer-writing");
  await ev("render()");                       // the page draws the section again mid-run (a job ended, the lock changed)
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('Done.')`, 40000), "this computer: the write finishes after a redraw");
  await sleep(300);
  const ev1 = await ev("window.__fake.events"), at = ev1.findIndex((e) => e.startsWith("flash/provision"));
  check(at >= 0 && ev1.indexOf("write") > at, "this computer: the token is made before anything is written: " + ev1.join(" > "));
  const after = await writeButton("Connect and write");
  check(after && !after.busy, "this computer: after a redraw during the run the button is free again");
  check(await ev(`[...document.querySelectorAll('.flash-write button')].filter((b) => b.textContent.trim() === 'Stop').every((b) => b.hidden)`), "this computer: Stop is hidden after the run");
  check((await ev(`document.querySelector('input[name=pass]').value + document.querySelector('input[name=again]').value`)) === "", "this computer: the Wi-Fi password is not left in the form");
  check((await ev("window.__fake.settings.token.length")) > 20, "this computer: the settings reached the board with a token");
  check((await ev("window.__fake.settings.buzzer_low")) === true, "this computer: the older buzzer is written as buzzer_low");
  check((await result()).includes("Reader token"), "this computer: the done text names the reader token");
  await audited("computer-done");
  const n1 = await ev("api('state').then((s) => s.readers.list.length)");
  check(n1 === n0 + 1, `this computer: a successful run keeps its token (${n0} to ${n1})`);

  await openUnlocked("#flash/tag-reader");
  await ev(`window.__fake.scenario = { wifi: "fail", server: "-" }; window.__fake.settings = null; window.__fake.wdelay = 20; window.__fake.events.length = 0`);
  await fill3("Workshop", "x");
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('could not join')`, 40000), "this computer: a Wi-Fi failure is said");
  await sleep(600);
  check((await ev("window.__fake.events")).some((e) => /readers\/.*\/revoke/.test(e)), "this computer: a failed run revokes its token");
  check((await result()).includes("The new Tag Reader token was removed."), "this computer: the failed run says its token was removed");
  check((await ev("api('state').then((s) => s.readers.list.length)")) === n1, "this computer: and no token is left");
  await audited("computer-failed");

  await openUnlocked("#flash/tag-reader");
  await ev(`window.__fake.scenario = { wifi: "ok", server: "ok" }; window.__fake.settings = null; window.__fake.wdelay = 400; window.__fake.events.length = 0`);
  await fill3();
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`!!document.querySelector('.flash-steps .progress')`, 10000), "Stop: the write is running");
  await click(".flash-write button", "Stop");
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('half written')`, 10000), "Stop while writing says the board is half written");
  await sleep(600);
  check((await ev("window.__fake.events")).some((e) => /readers\/.*\/revoke/.test(e)), "Stop: the token is revoked");
  await audited("computer-stopped");

  // Stop works while the page waits for the restarted board to answer
  await openUnlocked("#flash/tag-reader");
  await ev(`window.__fake.scenario = { wifi: "ok", server: "ok" }; window.__fake.settings = null; window.__fake.wdelay = 20; window.__fake.mute = true; window.__fake.events.length = 0`);
  await fill3();
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`document.querySelectorAll('.flash-steps .steps__step')[2] && document.querySelectorAll('.flash-steps .steps__step')[2].getAttribute('aria-current') === 'step'`, 15000), "Stop in the wait for the board: the page waits for the restarted board");
  await sleep(1500);
  await click(".flash-write button", "Stop");
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('Stopped before the next step')`, 4500), "Stop in the wait for the board ends the run at once");
  await ev(`window.__fake.mute = false`);

  // a Hub job running elsewhere does not take over a write from this computer
  ctl({ boards: 1, jobfail: false });
  await openUnlocked("#flash/tag-reader");
  await ev(`window.__fake.scenario = { wifi: "ok", server: "ok" }; window.__fake.settings = null; window.__fake.wdelay = 600; window.__fake.events.length = 0`);
  await fill3();
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`!!document.querySelector('.flash-steps .progress')`, 10000), "Hub job elsewhere: the write from this computer runs");
  await ev(`api("flash/server", { ssid: "Elsewhere", pass: "x", buzzer: "high", code: theCode() })`);
  await sleep(1500);
  await ev("render()");
  await sleep(1500);
  check(await ev("!!flashRun && flashRun.running && !flashRun.hub"), "Hub job elsewhere: a redraw leaves the run of this computer in place");
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('Done.')`, 40000), "Hub job elsewhere: the write from this computer finishes");
  check(await waitFor(`api("job?from=999999999").then((j) => !j.running)`, 30000), "Hub job elsewhere: the Hub's job ends");
  await ev(`window.__fake.wdelay = 20`);

  // the display from this computer needs no token and no settings
  await openUnlocked("#flash/display");
  await ev("window.__fake.events.length = 0");
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('Weigh Station display firmware')`, 20000), "display from this computer: done text");
  const evd = await ev("window.__fake.events");
  check(!evd.some((e) => e.startsWith("flash/provision")) && evd.includes("write"), "display from this computer: no token is made, the firmware is written: " + evd.join(" > "));
  await audited("display-done");

  await openUnlocked("#flash/tag-reader");
  await ev(`window.__fake.picked = false`); await setField("Wi-Fi name", "Workshop");
  await click(".flash-write button", "Connect and write");
  check(await waitFor(`(document.querySelector('.flash-write .result') || {}).textContent?.includes('No board was chosen.')`, 8000), "no board chosen is a note");
  check(errors.length === 0, "no page errors: " + errors.join(" | "));
} catch (e) {
  check(false, "the walk threw: " + e.message);
}
console.log(JSON.stringify({ checks, audit }));
ws.close(); cleanup();
process.exit(0);
