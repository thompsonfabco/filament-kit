// Page driver for tests that press the real controls of a page in a headless Chrome, Edge or Chromium already on the
// machine (nothing is downloaded; test-only, never shipped, never run on a Hub). It opens --url at --width, runs the
// script file --script in the page (one async function body; its return value is printed as JSON) and exits 0, or 1 when
// the script threw (its message is printed) or the page raised an uncaught error. Exit 2: no browser or the run itself
// failed; 3: a browser was found but cannot run headless here. Same browser rules as tests/aut5_run.mjs.
//
//   node tests/page_drive.mjs --url http://127.0.0.1:8799/setup --script tests/hub_presets_drive.js [--width 1280] [--browser <path>]
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.exitCode = 2;      // anything that ends the run early is a failed run, never a pass

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
  if (!args.url || !args.script) { console.error("usage: --url <page> --script <file>"); return 2; }
  const exe = findBrowser();
  if (!exe) { console.error("AUT-5: no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); return 2; }
  const script = readFileSync(args.script, "utf8");
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
    if (!port) {
      console.error(`AUT-5: the browser could not start (${exe}; ${browserExit === null ? "no DevTools port after 30 s" : "it exited: " + browserExit})\n${browserErr.trim().split("\n").slice(-8).join("\n")}`);
      return 3;
    }
    const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("could not reach the browser")); });
    let id = 0;
    const waiting = new Map(), errors = [];
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && waiting.has(msg.id)) {
        const [res, rej, timer] = waiting.get(msg.id);
        waiting.delete(msg.id);
        clearTimeout(timer);
        msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
      } else if (msg.method === "Runtime.exceptionThrown") {
        const d = msg.params.exceptionDetails;
        errors.push((d.exception && d.exception.description) || d.text);
      }
    };
    ws.onclose = () => { for (const [, [, rej, timer]] of waiting) { clearTimeout(timer); rej(new Error("the browser closed")); } waiting.clear(); };
    const send = (method, params = {}, limit = 30000) => new Promise((res, rej) => {
      if (ws.readyState !== WebSocket.OPEN) { rej(new Error("the browser closed")); return; }
      const n = ++id;
      const timer = setTimeout(() => { waiting.delete(n); rej(new Error(`${method} timed out`)); }, limit);
      waiting.set(n, [res, rej, timer]);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
    await send("Page.enable");
    await send("Runtime.enable");
    const width = Number(args.width || 1280);
    await send("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width <= 600 });
    await send("Page.navigate", { url: args.url });
    for (let i = 0; i < 100; i++) {
      if ((await send("Runtime.evaluate", { expression: "document.readyState", returnByValue: true })).result.value === "complete") break;
      await sleep(50);
    }
    const r = await send("Runtime.evaluate", { expression: `(async () => {\n${script}\n})()`, awaitPromise: true, returnByValue: true }, 120000);
    ws.close();
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      console.error("page script failed:", (d.exception && (d.exception.description || d.exception.value)) || d.text);
      return 1;
    }
    console.log(JSON.stringify(r.result.value));
    if (errors.length) { console.error("page error:", errors[0].split("\n")[0]); return 1; }
    return 0;
  } finally {
    cleanup();
  }
}

main().then((code) => { process.exitCode = code; }, (e) => { console.error("AUT-5:", e.message); process.exitCode = 2; });
