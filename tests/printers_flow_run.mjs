// Printers flow runner (S3.11 review fixes): drives the phone web app's Printers screen through one flow in a headless
// Chromium-family browser already on the machine (same launch and DevTools-over-WebSocket way as tests/aut5_run.mjs; Node 22+).
// Test-only: never shipped, never run on a Hub.
//
//   node tests/printers_flow_run.mjs --url http://127.0.0.1:8799/intake --flow add-found|add-klipper|forget [--width 375]
//        [--browser <path>]
//
// Prints one JSON object: { flow, width, hash, title, h1, events, errors, ...flow facts }. Exit 0 when the run itself worked
// (the facts are for the test to judge), 2 when it did not (no browser, a call timed out), 3 when the browser cannot run here.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.exitCode = 2;
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) =>
  a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : "1"]] : acc, []));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findBrowser() {
  if (args.browser) return args.browser;
  if (process.env.AUT5_BROWSER) return process.env.AUT5_BROWSER;
  const env = process.env;
  const roots = [env["ProgramFiles(x86)"], env.ProgramFiles, env.LOCALAPPDATA,
    ...["C:", "D:", "G:"].flatMap((d) => [`${d}\\Program Files (x86)`, `${d}\\Program Files`])].filter(Boolean);
  const win = roots.flatMap((r) => [`${r}\\Microsoft\\Edge\\Application\\msedge.exe`, `${r}\\Google\\Chrome\\Application\\chrome.exe`]);
  const nix = ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/microsoft-edge", "/snap/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"];
  return [...win, ...nix].find((p) => existsSync(p));
}

async function main() {
  const base = args.url, flow = args.flow, width = Number(args.width || 375);
  if (!base || !flow) { console.error("usage: --url <page> --flow add-found|add-klipper|forget"); return 2; }
  const exe = findBrowser();
  if (!exe) { console.error("AUT-5: no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); return 2; }
  const profile = mkdtempSync(join(tmpdir(), "aut5-"));
  const linux = process.platform === "linux" ? ["--no-sandbox", "--disable-dev-shm-usage"] : [];
  const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-gpu", ...linux, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  let browserErr = "", browserExit = null;
  proc.stderr.on("data", (d) => { browserErr = (browserErr + d).slice(-2000); });
  proc.on("exit", (code, signal) => { browserExit = signal || code; });
  proc.on("error", (e) => { browserExit = e.code || e.message; });
  const cleanup = () => {
    try { proc.kill(); } catch { /* gone */ }
    try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* still held */ }
  };
  process.once("exit", cleanup);
  try {
    let port;
    for (let i = 0; i < 300 && !port && browserExit === null; i++) {
      await sleep(100);
      try { port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { /* not yet */ }
    }
    if (!port) { console.error(`AUT-5: the browser could not start (${exe})\n${browserErr.trim()}`); return 3; }
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("could not reach the browser")); });
    let id = 0, origin = "";
    const waiting = new Map(), errors = [];
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && waiting.has(msg.id)) {
        const [res, rej, timer] = waiting.get(msg.id);
        waiting.delete(msg.id); clearTimeout(timer);
        msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
      } else if (msg.method === "Fetch.requestPaused") {
        const r = msg.params.request, post = r.method === "POST";
        send("Fetch.continueRequest", { requestId: msg.params.requestId,
          ...(post ? { headers: [...Object.entries(r.headers).filter(([k]) => k.toLowerCase() !== "origin"), ["Origin", origin]].map(([name, value]) => ({ name, value })) } : {}) }).catch(() => {});
      } else if (msg.method === "Runtime.exceptionThrown") {
        const d = msg.params.exceptionDetails;
        errors.push((d.exception && d.exception.description) || d.text);
      }
    };
    const send = (method, params = {}) => new Promise((res, rej) => {
      const n = ++id, timer = setTimeout(() => { waiting.delete(n); rej(new Error(`${method} timed out`)); }, 30000);
      waiting.set(n, [res, rej, timer]);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
    const evaluate = async (expression) => {
      const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) {      // say what was on the page
        const d = r.exceptionDetails, seen = await send("Runtime.evaluate", { expression: "location.href + ' | ' + document.body.innerText.slice(0, 300)", returnByValue: true });
        throw new Error(`${d.text} ${(d.exception && d.exception.description) || ""} in ${expression.slice(0, 60)} on ${seen.result.value}`);
      }
      return r.result.value;
    };
    await send("Page.enable"); await send("Runtime.enable");
    // the Hub accepts a change only from an https page of its own address; the test server speaks plain http, so a POST gets that Origin here
    await send("Fetch.enable", { patterns: [{ requestStage: "Request" }] });
    origin = "https://" + new URL(base).host;
    await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: width <= 600 });
    const load = async (hash) => {
      await send("Page.navigate", { url: base + hash });
      for (let i = 0; i < 100 && (await evaluate("document.readyState")) !== "complete"; i++) await sleep(50);
    };
    // what the page does with its address: every popstate and hashchange, in order
    const watch = `window.__ev = []; for (const k of ["popstate", "hashchange"]) addEventListener(k, () => __ev.push(k + ":" + location.hash)); 1`;
    const until = async (test, ms = 8000) => { for (let t = 0; t < ms; t += 100) { if (await evaluate(test)) return true; await sleep(100); } return false; };
    // a sheet field, set the way typing does
    const fill = (n, v) => evaluate(`(() => { const i = document.querySelectorAll("dialog[open] input:not([type=hidden]):not([type=search])")[${n}];
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(i, ${JSON.stringify(v)}); i.dispatchEvent(new Event("input", { bubbles: true })); return !!i; })()`);
    const click = (sel) => evaluate(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (b) b.click(); return !!b; })()`);
    const facts = {};

    await load("#printers");
    if (flow === "forget") {
      // the printer opened last is expanded when the list opens without an address for one (tablets); on a phone it is opened by address
      const serial = await evaluate(`new Promise((r) => { const l = setInterval(() => { const a = document.querySelector(".pcard__name"); if (a) { clearInterval(l); r(decodeURIComponent(a.getAttribute("href").split("/")[1] || "")); } }, 50); })`);
      facts.serial = serial;
      await evaluate(`localStorage.setItem("spoolwarden.printer", ${JSON.stringify(serial)})`);
      if (width > 600) { await send("Page.reload"); await sleep(300); for (let i = 0; i < 100 && (await evaluate("document.readyState")) !== "complete"; i++) await sleep(50); }
      else await load("#printers/" + serial);
    }
    await until(`!!document.querySelector(".pcard")`);
    await evaluate(watch);
    await sleep(500);

    if (flow === "add-found" || flow === "add-klipper") {
      // the sheet's Back lands late (as on a slow phone): an address set before it lands is taken back with it
      await evaluate(`{ const back = history.back.bind(history); history.back = () => { setTimeout(back, 700); }; 1 }`);
      facts.cardsBefore =await evaluate(`document.querySelectorAll(".pitem").length`);
      if (flow === "add-found") {
        facts.opened = await click(`[data-action="add-found"]`);
        await until(`!!document.querySelector("dialog[open]")`);
        await fill(0, "12345678");
      } else {
        facts.opened = await click(`[data-action="add-klipper"]`);
        await until(`!!document.querySelector("dialog[open]")`);
        await fill(0, "192.0.2.77");
      }
      await evaluate(`document.querySelector("dialog[open] button[type=submit]").click()`);
      await until(`!document.querySelector("dialog[open]")`);
      await sleep(1500);
      facts.sheetLeft = await evaluate(`(document.querySelector("dialog[open]") || {}).innerText || ""`);
      facts.added = await evaluate(`document.body.innerText.includes("Added.")`);
      facts.cardsAfter = await evaluate(`document.querySelectorAll(".pitem").length`);
    } else if (flow === "forget") {
      if (!(await until(`!!document.querySelector('[data-action="forget"]')`, 12000))) {
        throw new Error("no Forget button: " + await evaluate(`location.hash + " | " + document.body.innerText.slice(0, 600).replace(/\\s+/g, " ")`));
      }
      facts.hashBefore = await evaluate("location.hash");
      facts.openBefore = await evaluate(`!!document.querySelector(".printer") && !document.querySelector(".printer").hidden`);
      await evaluate(`document.querySelector('[data-action="forget"]').click()`);
      await until(`!!document.querySelector("dialog[open]")`);
      await evaluate(`document.querySelector("dialog[open] button[type=submit]").click()`);
      await until(`!document.querySelector("dialog[open]")`);
      await sleep(1500);
      facts.openAfter = await evaluate(`!!document.querySelector(".printer") && !document.querySelector(".printer").hidden && document.querySelector(".printer").childElementCount > 0`);
      facts.cardsAfter = await evaluate(`[...document.querySelectorAll(".pcard__name")].map((a) => a.textContent)`);
      facts.has404 = await evaluate(`document.body.innerText.includes("404")`);
    } else if (flow === "unknown") {
      await load("#printers/NOPE123");
      await sleep(1500);
    }
    const out = { flow, width, ...facts,
      hash: await evaluate("location.hash"), title: await evaluate("document.title"),
      h1: await evaluate(`(document.querySelector(".page-head__title") || {}).textContent`),
      events: await evaluate("window.__ev"), errors,
      sideways: await evaluate(`document.documentElement.scrollWidth > document.documentElement.clientWidth`),
      body: flow === "unknown" ? await evaluate("document.body.innerText") : undefined };
    console.log(JSON.stringify(out, null, 1));
    ws.close();
    return 0;
  } finally {
    cleanup();
  }
}

main().then((code) => { process.exitCode = code; }, (e) => { console.error("AUT-5:", e.message); process.exitCode = 2; });
