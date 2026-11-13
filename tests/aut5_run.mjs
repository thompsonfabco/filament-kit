// AUT-5 runner (docs/design/07-accessibility.md section 15): opens each view of a page in a headless Chromium-family
// browser (Chrome, Edge or Chromium already on the machine; nothing is downloaded), at each width and appearance, runs
// tests/page_audit.js in it and prints the findings as JSON. Test-only: never shipped, never run on a Hub.
//
//   node tests/aut5_run.mjs --url http://127.0.0.1:8799/intake --views "#add,#spools" [--widths 1280,320]
//        [--schemes light,dark] [--browser <path>] [--settle 400] [--allow tests/aut5_allowlist.txt]
//
// --allow: findings of today's markup that a later step removes, one per line "<check> | <where> | <reason>"; a line
// that matches nothing in the run is stale and fails it, so a rebuilt screen has to drop its lines.
// Exit 0: no findings; 1: findings or stale allow-list lines (printed); 2: the run itself failed.
// The browser is driven over the DevTools protocol with Node's own WebSocket (Node 22 or later): no npm package.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) =>
  a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : "1"]] : acc, []));
const URL_BASE = args.url;
const VIEWS = (args.views || "").split(",").map((v) => v.trim()).filter(Boolean);
const WIDTHS = (args.widths || "1280,320").split(",").map(Number);
const SCHEMES = (args.schemes || "light,dark").split(",");
const SETTLE = Number(args.settle || 400);
const AUDIT = readFileSync(join(HERE, "page_audit.js"), "utf8");
const ALLOW = new Map((args.allow ? readFileSync(args.allow, "utf8").split(/\r?\n/) : [])
  .filter((l) => l.trim() && !l.startsWith("#")).map((l) => l.split("|").map((x) => x.trim()))
  .map(([check, where]) => [`${check} | ${where}`, 0]));

function findBrowser() {
  if (args.browser) return args.browser;
  if (process.env.AUT5_BROWSER) return process.env.AUT5_BROWSER;
  const roots = ["C:", "D:", "G:"].flatMap((d) => [`${d}\\Program Files (x86)`, `${d}\\Program Files`]);
  const win = roots.flatMap((r) => [`${r}\\Microsoft\\Edge\\Application\\msedge.exe`, `${r}\\Google\\Chrome\\Application\\chrome.exe`]);
  const nix = ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/microsoft-edge",
    "/snap/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"];
  return [...win, ...nix].find((p) => existsSync(p));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  if (!URL_BASE || !VIEWS.length) { console.error("usage: --url <page> --views <#a,#b>"); return 2; }
  const exe = findBrowser();
  if (!exe) { console.error("AUT-5: no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); return 2; }
  const profile = mkdtempSync(join(tmpdir(), "aut5-"));
  const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  try {
    let port;
    for (let i = 0; i < 100 && !port; i++) {
      await sleep(100);
      try { port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { /* not yet */ }
    }
    if (!port) { console.error("AUT-5: the browser did not open its DevTools port"); return 2; }
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const page = targets.find((t) => t.type === "page");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let id = 0;
    const waiting = new Map(), events = [];
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && waiting.has(msg.id)) { const [res, rej] = waiting.get(msg.id); waiting.delete(msg.id); msg.error ? rej(new Error(msg.error.message)) : res(msg.result); }
      else if (msg.method) events.push(msg);
    };
    const send = (method, params = {}) => new Promise((res, rej) => { const n = ++id; waiting.set(n, [res, rej]); ws.send(JSON.stringify({ id: n, method, params })); });
    const loaded = async () => {
      for (let i = 0; i < 100; i++) {
        const r = await send("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
        if (r.result.value === "complete") return;
        await sleep(50);
      }
    };
    await send("Page.enable");
    await send("Runtime.enable");
    const report = [];
    for (const scheme of SCHEMES) {
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
      for (const width of WIDTHS) {
        await send("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width <= 600 });
        // a fresh load per width and appearance; views of one load share the audit's title memory (SR-2)
        await send("Page.navigate", { url: URL_BASE + VIEWS[0] });
        await loaded();
        for (const view of VIEWS) {
          await send("Runtime.evaluate", { expression: `location.hash = ${JSON.stringify(view)}` });
          await sleep(SETTLE);
          // page_audit.js is one expression statement whose value is the findings list
          const r = await send("Runtime.evaluate", { expression: AUDIT, returnByValue: true });
          if (r.exceptionDetails) throw new Error(`${view}: ${r.exceptionDetails.text}`);
          const s = await send("Runtime.evaluate", { returnByValue: true,
            expression: "({ sideways: document.documentElement.scrollWidth > innerWidth, title: document.title })" });
          const v = { findings: r.result.value || [], ...s.result.value };
          const all = [...v.findings, ...(v.sideways ? [{ check: "sideways scroll", where: "page", detail: `${width} px` }] : [])];
          const findings = all.filter((f) => {
            const key = `${f.check} | ${f.where}`;
            if (!ALLOW.has(key)) return true;
            ALLOW.set(key, ALLOW.get(key) + 1);
            return false;
          });
          report.push({ view, width, scheme, title: v.title, findings });
        }
      }
    }
    ws.close();
    const bad = report.filter((r) => r.findings.length);
    const stale = [...ALLOW].filter(([, n]) => !n).map(([k]) => k);
    console.log(JSON.stringify({ views: report.length, failing: bad.length, allowed: [...ALLOW.values()].reduce((a, b) => a + b, 0),
      stale: stale.length ? stale : undefined, report: bad.length ? bad : undefined }, null, 1));
    return bad.length || stale.length ? 1 : 0;
  } finally {
    proc.kill();
    await sleep(300);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* the browser may still hold a file */ }
  }
}

main().then((code) => process.exit(code), (e) => { console.error("AUT-5:", e.message); process.exit(2); });
