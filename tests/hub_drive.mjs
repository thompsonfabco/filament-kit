// Drives the Hub page in a headless Chrome, Edge or Chromium already on the machine, for a test that needs real clicks and typing
// (tests/aut5_run.mjs only audits). Test-only: never shipped, never run on a Hub.
//
//   node tests/hub_drive.mjs --url http://127.0.0.1:8799/setup --steps tests/recent_flow.mjs [--width 1280] [--scheme light]
//        [--browser <path>] [--font-dir <dir>] [--out <dir>] [--arg <text>]
//
// --steps is a module whose default export is `async (page) => { ... }`; it throws to fail. `page` has go(hash), eval(js),
// click(selector, text?), type(selector, text), press(key), waitFor(js, what), text(selector), shot(name), arg, out. Clicks and
// typing are real input events at the element's centre, so an element that is covered or too small is not clicked. Output
// on stdout: {ok: true, log: [...]}; exit 0 passed, 1 the steps failed or the page did not open, 2 the run itself failed, 3 no browser could start here.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

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

// the DejaVu files of --font-dir as the page's two font tokens (as aut5_run.mjs does)
function dejavu(dir) {
  const face = (family, file, weight) => `faces.push(new FontFace(${JSON.stringify(family)}, Uint8Array.from(atob("${
    readFileSync(join(dir, file)).toString("base64")}"), (c) => c.charCodeAt(0)).buffer, { weight: "${weight}" }));`;
  return `(() => { const faces = [];
    ${face("DejaVu Sans", "DejaVuSans.ttf", 400)} ${face("DejaVu Sans", "DejaVuSans-Bold.ttf", 700)}
    ${face("DejaVu Sans Mono", "DejaVuSansMono.ttf", 400)} ${face("DejaVu Sans Mono", "DejaVuSansMono-Bold.ttf", 700)}
    window.__fonts = Promise.all(faces.map((f) => f.load().then(() => document.fonts.add(f))));
    document.addEventListener("DOMContentLoaded", () => { const s = new CSSStyleSheet();
      s.replaceSync(':root{--sans:"DejaVu Sans",sans-serif !important;--mono:"DejaVu Sans Mono",monospace !important}');
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; }); })();`;
}

async function main() {
  if (!args.url || !args.steps) { console.error("usage: --url <page> --steps <module>"); return 2; }
  const exe = findBrowser();
  if (!exe) { console.error("no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); return 2; }
  const width = Number(args.width || 1280), scheme = args.scheme || "light", out = args.out ? resolve(args.out) : null;
  if (out) mkdirSync(out, { recursive: true });
  const profile = mkdtempSync(join(tmpdir(), "fk-drive-"));
  const linux = process.platform === "linux" ? ["--no-sandbox", "--disable-dev-shm-usage"] : [];
  const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-gpu",
    // a headless window that is not in front is not throttled, so a run beside others keeps its timers (a call that waited 30 s)
    "--disable-renderer-backgrounding", "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows", ...linux, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  let err = "", gone = null;
  proc.stderr.on("data", (d) => { err = (err + d).slice(-2000); });
  proc.on("exit", (code, signal) => { gone = signal || code; });
  proc.on("error", (e) => { gone = e.code || e.message; });
  const cleanup = () => { try { proc.kill(); } catch { /* gone */ } try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* held */ } };
  process.once("exit", cleanup);
  try {
    let port;
    for (let i = 0; i < 300 && !port && gone === null; i++) {
      await sleep(100);
      try { port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { /* not yet */ }
    }
    if (!port) { console.error(`the browser could not start (${exe}; ${gone === null ? "no DevTools port after 30 s" : "it exited: " + gone})\n${err.trim()}`); return 3; }
    const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("could not reach the browser")); });
    let id = 0, api_last = "start";
    const waiting = new Map(), errors = [], log = [];
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && waiting.has(msg.id)) { const [res, rej] = waiting.get(msg.id); waiting.delete(msg.id); msg.error ? rej(new Error(msg.error.message)) : res(msg.result); }
      else if (msg.method === "Runtime.exceptionThrown") { const d = msg.params.exceptionDetails; errors.push((d.exception && d.exception.description) || d.text); }
    };
    const send = (method, params = {}) => new Promise((res, rej) => {
      const n = ++id, timer = setTimeout(() => { waiting.delete(n); rej(new Error(`${method} timed out (last step: ${api_last})`)); }, 30000);
      waiting.set(n, [(r) => { clearTimeout(timer); res(r); }, (e) => { clearTimeout(timer); rej(e); }]);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
    const evaluate = async (expression) => {
      const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
      return r.result.value;
    };
    await send("Page.enable"); await send("Runtime.enable");
    if (args["font-dir"]) await send("Page.addScriptToEvaluateOnNewDocument", { source: dejavu(args["font-dir"]) });
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
    await send("Emulation.setDeviceMetricsOverride", { width, height: Number(args.height || 900), deviceScaleFactor: 1, mobile: width <= 600 });
    await send("Emulation.setTouchEmulationEnabled", { enabled: width <= 600, maxTouchPoints: 1 });
    const settled = async () => {      // no region is busy, twice 100 ms apart
      for (let t = 0, calm = 0; t < 10000 && calm < 2; t += 100) { calm = await evaluate(`!!document.querySelector('[aria-busy="true"]:not(button)')`) ? 0 : calm + 1; await sleep(100); }
    };
    const waitFor = async (js, what = js, ms = 8000) => {
      api_last = `wait for ${what}`;
      for (let t = 0; t < ms; t += 50) { if (await evaluate(`!!(${js})`)) return; await sleep(50); }
      throw new Error(`timed out waiting for ${what}`);
    };
    const centre = async (selector, text) => {
      let box = null;
      for (let t = 0; t < 1500; t += 100) {      // a dialog or a sheet that is still moving in is waited for
        box = await look(selector, text);
        if (box && box.ok) return box;
        await sleep(100);
      }
      if (!box) throw new Error(`nothing to press: ${selector} ${text || ""}`);
      throw new Error(`covered, not pressable: ${selector} ${text || ""}`);
    };
    const look = (selector, text) => evaluate(`(() => { const all = [...document.querySelectorAll(${JSON.stringify(selector)})]
        .filter((e) => ${JSON.stringify(text || "")} === "" || e.textContent.trim().startsWith(${JSON.stringify(text || "")}));
        const e = all.find((x) => x.getClientRects().length && !x.closest("[hidden]")); if (!e) return null;
        e.scrollIntoView({ block: "center", behavior: "instant" }); const r = e.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return { x: r.x + r.width / 2, y: r.y + r.height / 2, ok: e === hit || e.contains(hit) || (hit && hit.contains(e)) }; })()`);
    const api = {
      arg: args.arg, out, width, scheme, log: (x) => log.push(x),
      eval: evaluate, waitFor, settled,
      async go(hash) { api_last = `go ${hash}`; await evaluate(`location.hash = ${JSON.stringify(hash)}`); await sleep(100); await settled(); },
      async click(selector, text) {
        api_last = `click ${selector} ${text || ""}`;
        const c = await centre(selector, text);
        for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: c.x, y: c.y, button: "left", clickCount: 1 });
        await sleep(50);
      },
      async type(selector, text) {
        api_last = `type ${selector}`;      // focus, then the text as typed: a field's own buttons may sit over its centre, so no click
        await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); e.scrollIntoView({ block: "center", behavior: "instant" }); e.focus(); if (e.select) e.select(); })()`);
        await send("Input.insertText", { text });
      },
      async press(key) {
        api_last = `press ${key}`;
        const code = { Enter: 13, Escape: 27, ArrowLeft: 37, ArrowRight: 39, Tab: 9, Home: 36, End: 35 }[key];
        for (const type of ["rawKeyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key, code: key, windowsVirtualKeyCode: code });
      },
      text: (selector) => evaluate(`(document.querySelector(${JSON.stringify(selector)}) || {}).textContent`),
      async shot(name) {
        if (!out) return;
        const m = await send("Page.getLayoutMetrics");
        const w = Math.ceil(m.cssContentSize.width), h = Math.min(Math.ceil(m.cssContentSize.height), 6000);
        const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width: w, height: h, scale: 1 } });
        writeFileSync(join(out, name + ".png"), Buffer.from(r.data, "base64"));
      },
    };
    try {      // a browser that does not answer while the page opens is started again (launch), as one that exits at once
      const url = new URL(args.url);
      url.searchParams.set("drive", String(Date.now()));
      await send("Page.navigate", { url: url.href + (args.hash || "") });
      for (let i = 0; i < 100 && (await evaluate("document.readyState")) !== "complete"; i++) await sleep(50);
      if (args["font-dir"]) await evaluate("window.__fonts");
      await settled();
    } catch (e) { console.error(`the browser did not answer while the page opened (${e.message})`); return 4; }
    let failure = null;
    try { await (await import(pathToFileURL(resolve(args.steps)).href)).default(api); } catch (e) { failure = e; }
    const problems = errors.splice(0);
    if (failure || problems.length) {
      console.log(JSON.stringify({ ok: false, error: failure ? String(failure.message || failure) : undefined, pageErrors: problems, pid: proc.pid, log }, null, 1));
      return 1;
    }
    console.log(JSON.stringify({ ok: true, pid: proc.pid, log }, null, 1));
    return 0;
  } finally { cleanup(); }
}
// a browser that exits at once (another one holds its profile, the machine is loaded) is started again, twice, as aut5_run.mjs does
async function launch() {
  let code = 3;
  for (let attempt = 0; attempt < 3 && (code === 3 || code === 4); attempt++) { if (attempt) await sleep(2000); code = await main(); }
  return code === 4 ? 1 : code;      // a page that never opened is a failure; only a browser that cannot start is exit 3 (a skip unless AUT5_REQUIRED=1)
}
launch().then((code) => { process.exitCode = code; }, (e) => { console.error("drive:", e.message); process.exitCode = 2; });
