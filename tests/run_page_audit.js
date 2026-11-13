// Runs the page audit (AUT-5, tests/page_audit.js) on the component sample page in headless Microsoft Edge or Chrome,
// at 1280 px and 320 px wide, light and dark (09 S0.11 "Check"). No library: the browser is driven over the DevTools
// protocol with Node's own WebSocket, and the repository root is served by Node's http module on 127.0.0.1.
//   node tests/run_page_audit.js <browser executable>   prints {"<width> <scheme>": [findings], ...} as JSON
// The browser runs in a new empty profile that is removed afterwards; only the process this script starts is stopped.
"use strict";
const fs = require("fs"), os = require("os"), path = require("path"), http = require("http"), { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
const VIEWS = [[1280, "light"], [1280, "dark"], [320, "light"], [320, "dark"]];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function serve() {
  const server = http.createServer((req, res) => {
    const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!file.startsWith(ROOT + path.sep)) { res.writeHead(403); return res.end(); }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
      res.end(data);
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

// withBrowser(exe, async (page) => ...): page.open(url, {width, scheme}) and page.eval(expression)
async function withBrowser(exe, fn) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "sw-audit-"));
  const server = await serve();
  const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + profile, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-sync", "about:blank"], { stdio: "ignore" });
  let ws = null;
  try {
    const portFile = path.join(profile, "DevToolsActivePort");
    for (let i = 0; i < 150 && !fs.existsSync(portFile); i++) await sleep(100);
    const [port, wsPath] = fs.readFileSync(portFile, "utf8").split("\n");
    ws = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
    await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
    let id = 0;
    const waiting = new Map();
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data), w = waiting.get(msg.id);
      if (!w) return;
      waiting.delete(msg.id);
      if (msg.error) w.reject(new Error(JSON.stringify(msg.error))); else w.resolve(msg.result);
    };
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      waiting.set(++id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    const s = (method, params) => send(method, params, sessionId);
    const page = {
      async open(url, o = {}) {
        const narrow = (o.width || 1280) <= 600;
        await s("Emulation.setDeviceMetricsOverride", { width: o.width || 1280, height: o.height || 900, deviceScaleFactor: 1, mobile: false });
        await s("Emulation.setTouchEmulationEnabled", narrow ? { enabled: true, maxTouchPoints: 5 } : { enabled: false });
        await s("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: o.scheme || "light" }] });
        await s("Page.navigate", { url: /^https?:/.test(url) ? url : `http://127.0.0.1:${server.address().port}/${url}` });
      },
      async eval(expression) {
        const r = await s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
        if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception ? r.exceptionDetails.exception.description : r.exceptionDetails.text);
        return r.result.value;
      },
      async until(expression, ms = 30000) {
        for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) {
          const v = await page.eval(expression).catch(() => null);
          if (v != null) return v;
        }
        throw new Error("timed out waiting for " + expression);
      },
    };
    return await fn(page);
  } finally {
    if (ws) { try { ws.send(JSON.stringify({ id: 0, method: "Browser.close" })); } catch (e) { /* already gone */ } }
    for (let i = 0; i < 50 && proc.exitCode == null; i++) await sleep(100);
    if (proc.exitCode == null) proc.kill();
    server.close();
    for (let i = 0; i < 20; i++) { try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch (e) { await sleep(250); } }
  }
}

async function audit(exe) {
  return withBrowser(exe, async (page) => {
    const out = {};
    for (const [width, scheme] of VIEWS) {
      await page.open("tests/components-sample.html?audit", { width, scheme });
      const found = JSON.parse(await page.until('(document.getElementById("audit-result") || {}).textContent || null'));
      const seen = await page.eval(`[innerWidth, matchMedia("(prefers-color-scheme: dark)").matches, matchMedia("(pointer: coarse)").matches]`);
      out[`${width} ${scheme}`] = { innerWidth: seen[0], dark: seen[1], coarse: seen[2], findings: found };
    }
    return out;
  });
}

module.exports = { withBrowser, audit };
if (require.main === module) {
  audit(process.argv[2]).then((r) => { process.stdout.write(JSON.stringify(r, null, 1) + "\n"); },
    (e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exitCode = 1; });
}
