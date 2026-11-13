// AUT-5 runner (docs/design/07-accessibility.md section 15): opens each view of a page in a headless Chromium-family
// browser (Chrome, Edge or Chromium already on the machine; nothing is downloaded), at each width and appearance, runs
// tests/page_audit.js in it and prints the findings as JSON. Test-only: never shipped, never run on a Hub.
//
//   node tests/aut5_run.mjs --url http://127.0.0.1:8799/intake --views "#add,#spools" [--widths 1280,320]
//        [--schemes light,dark] [--browser <path>] [--settle 100] [--allow tests/aut5_allowlist.txt] [--wide-font]
//
// Besides the audit's own checks, each pass fails on: sideways scroll (content wider than the layout viewport), a view
// that did not open (the address or title is not the one asked for), and an uncaught error in the page.
// --allow: findings of today's markup that a later step removes, one per line "<check> | <where> | <count> | <reason>";
// <count> is how many times that finding appears in the whole run (every view, width and appearance). A run that finds
// it more often fails (a new finding hides behind no line), and a line found less often is stale and fails too, so a
// rebuilt screen has to drop or lower its lines. A line may start with the view it belongs to ("#settings | <check> |
// ..."): it then matches that view only, so a finding that moves to another view fails; a line without a view matches
// in every view.
// After a view is opened the runner waits --settle ms (a floor), then until no region is aria-busy (at most 10 s; a
// region still busy after that is a finding of the audit). At 600 px or narrower the page is a touch device (mobile
// metrics and touch emulation, so (pointer: coarse) is true); "passes" in the output gives innerWidth, dark and coarse
// of every pass. --wide-font swaps the page's two font tokens (--sans, --mono) for wide faces (Verdana and Lucida
// Console, or DejaVu Sans and Sans Mono where those are installed): a Linux runner falls back to DejaVu, which is wider
// than the fonts a Windows or Mac machine has, so this shows there what a layout does when the text is wider. A
// "sideways scroll" finding names the widest element that reaches past the viewport.
// Exit 0: no findings; 1: findings, or allow-list counts that do not match (printed); 2: the run itself failed (no
// browser found, the browser closed, a call timed out); 3: a browser was found but could not start headless here
// (its last error lines are printed). The browser is driven over the DevTools protocol with Node's own
// WebSocket (Node 22 or later): no npm package.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

process.exitCode = 2;      // anything that ends the run early (a lost browser included) is a failed run, never a pass

const HERE = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) =>
  a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : "1"]] : acc, []));
const URL_BASE = args.url;
const VIEWS = (args.views || "").split(",").map((v) => v.trim()).filter(Boolean);
const WIDTHS = (args.widths || "1280,320").split(",").map(Number);
const SCHEMES = (args.schemes || "light,dark").split(",");
const SETTLE = Number(args.settle || 100);
// a constructed style sheet, not a <style> element: the page's content security policy refuses inline styles
const WIDE_FONT = "document.addEventListener('DOMContentLoaded', () => { const s = new CSSStyleSheet(); " +
  "s.replaceSync(':root{--sans:Verdana,\"DejaVu Sans\",sans-serif !important;" +
  "--mono:\"Lucida Console\",\"DejaVu Sans Mono\",\"Courier New\",monospace !important}'); " +
  "document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; });";
// the element that makes the page wider than the viewport: the one whose right edge goes furthest past it (selector
// path, how far, its text); elements inside a box that scrolls or clips on its own do not count
const WIDEST = `(() => {
  const vw = document.documentElement.clientWidth, name = (e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") +
    [...e.classList].slice(0, 2).map((c) => "." + c).join("");
  let best = null;
  for (const e of document.body.querySelectorAll("*")) {
    const r = e.getBoundingClientRect();
    if (!r.width || r.right <= vw + 0.5 || getComputedStyle(e).visibility === "hidden") continue;
    let clipped = false;
    for (let p = e.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      if (/auto|scroll|hidden|clip/.test(getComputedStyle(p).overflowX) && p.getBoundingClientRect().right <= vw + 0.5) { clipped = true; break; }
    }
    if (clipped) continue;
    if (!best || r.right > best.right) best = { e, right: r.right };
  }
  if (!best) return "";
  const path = []; for (let e = best.e; e && e !== document.body && path.length < 4; e = e.parentElement) path.unshift(name(e));
  return path.join(" > ") + " reaches " + Math.round(best.right) + " px: " + (best.e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
})()`;
const BUSY_LIMIT = 10000;
const CALL_TIMEOUT = 30000;
const PROFILE_PREFIX = "aut5-";
const AUDIT = readFileSync(join(HERE, "page_audit.js"), "utf8");

// allow-list: "view | check | where" -> { want, seen }; a line without a view has an empty view (matches in every view)
const ALLOW = new Map();
for (const line of args.allow ? readFileSync(args.allow, "utf8").split(/\r?\n/) : []) {
  if (!line.trim() || /^#(\s|$)/.test(line)) continue;      // "# ..." is a comment, "#view | ..." a line
  const f = line.split("|").map((x) => x.trim());
  const [view, check, where, count] = f[0].startsWith("#") ? f : ["", ...f];
  if (!/^\d+$/.test(count || "")) throw new Error(`allow-list line without a count: ${line}`);
  ALLOW.set(`${view} | ${check} | ${where}`, { want: Number(count), seen: 0 });
}

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

// profiles of earlier runs that ended without cleaning up (a killed run): ours by prefix, older than an hour
function sweepOldProfiles() {
  const cutoff = Date.now() - 3600_000;
  for (const name of readdirSync(tmpdir())) {
    if (!name.startsWith(PROFILE_PREFIX)) continue;
    const dir = join(tmpdir(), name);
    try { if (statSync(dir).mtimeMs < cutoff) rmSync(dir, { recursive: true, force: true }); } catch { /* in use */ }
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  if (!URL_BASE || !VIEWS.length) { console.error("usage: --url <page> --views <#a,#b>"); return 2; }
  const exe = findBrowser();
  if (!exe) { console.error("AUT-5: no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); return 2; }
  sweepOldProfiles();
  const profile = mkdtempSync(join(tmpdir(), PROFILE_PREFIX));
  // Linux CI runners (ubuntu-24.04) refuse the browser's sandbox (no unprivileged user namespaces) and have a small
  // /dev/shm; the page under test is the test's own local server, so the sandbox adds nothing here
  const linux = process.platform === "linux" ? ["--no-sandbox", "--disable-dev-shm-usage"] : [];
  const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-gpu", ...linux, "about:blank"],
    { stdio: ["ignore", "ignore", "pipe"] });
  let browserErr = "";
  proc.stderr.on("data", (d) => { browserErr = (browserErr + d).slice(-2000); });
  let browserExit = null;
  proc.on("exit", (code, signal) => { browserExit = signal || code; });
  proc.on("error", (e) => { browserExit = e.code || e.message; });     // could not be started at all
  const cleanup = () => {
    try { proc.kill(); } catch { /* gone */ }
    try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* still held */ }
  };
  process.once("exit", cleanup);
  for (const sig of ["SIGINT", "SIGTERM"]) process.once(sig, () => { cleanup(); process.exit(2); });
  try {
    let port;
    for (let i = 0; i < 300 && !port && browserExit === null; i++) {
      await sleep(100);
      try { port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { /* not yet */ }
    }
    if (!port) {      // exit 3: this machine's browser cannot run headless here (the tests skip on it unless required)
      console.error(`AUT-5: the browser could not start (${exe}; ${browserExit === null ? "no DevTools port after 30 s"
        : "it exited: " + browserExit})\n${browserErr.trim().split("\n").slice(-8).join("\n")}`);
      return 3;
    }
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const page = targets.find((t) => t.type === "page");
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
    ws.onclose = () => {      // the browser went away: every call still waiting fails the run
      for (const [, [, rej, timer]] of waiting) { clearTimeout(timer); rej(new Error("the browser closed")); }
      waiting.clear();
    };
    const send = (method, params = {}) => new Promise((res, rej) => {
      if (ws.readyState !== WebSocket.OPEN) { rej(new Error("the browser closed")); return; }
      const n = ++id;
      const timer = setTimeout(() => { waiting.delete(n); rej(new Error(`${method} timed out`)); }, CALL_TIMEOUT);
      waiting.set(n, [res, rej, timer]);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
    const evaluate = async (expression) => {
      const r = await send("Runtime.evaluate", { expression, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
      return r.result.value;
    };
    const loaded = async () => {
      for (let i = 0; i < 100; i++) {
        if (await evaluate("document.readyState") === "complete") return;
        await sleep(50);
      }
      throw new Error("the page did not finish loading");
    };
    // wait until no region is aria-busy (two looks 100 ms apart), so a section that loads its data is ready; the bound
    // only stops a region that never finishes (the audit then reports it)
    const settled = async () => {
      const busy = `!!document.querySelector('[aria-busy="true"]:not(button)')`;
      for (let t = 0, calm = 0; t < BUSY_LIMIT && calm < 2; t += 100) {
        calm = await evaluate(busy) ? 0 : calm + 1;
        await sleep(100);
      }
    };
    await send("Page.enable");
    await send("Runtime.enable");
    if (args["wide-font"]) await send("Page.addScriptToEvaluateOnNewDocument", { source: WIDE_FONT });
    const report = [], passes = [];
    let pass = 0;
    for (const scheme of SCHEMES) {
      await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
      for (const width of WIDTHS) {
        await send("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width <= 600 });
        await send("Emulation.setTouchEmulationEnabled", { enabled: width <= 600, maxTouchPoints: 1 });
        // a fresh load for each width and appearance (a new query string, so the browser really loads the page again);
        // the views of one load share the audit's title memory (SR-2)
        const url = new URL(URL_BASE);
        url.searchParams.set("aut5", String(++pass));
        errors.length = 0;
        await send("Page.navigate", { url: url.href + VIEWS[0] });
        await loaded();
        for (const view of VIEWS) {
          // errors are taken when the view is reported: what the page threw while loading is the first view's, and
          // what arrives later belongs to the view open at that time
          await evaluate(`location.hash = ${JSON.stringify(view)}`);
          await sleep(SETTLE);
          await settled();
          const found = (await evaluate(AUDIT)) || [];      // page_audit.js: one expression, the findings list
          const page = await evaluate(`({ hash: location.hash, title: document.title,
            sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            width: document.documentElement.clientWidth, innerWidth: innerWidth,
            dark: matchMedia("(prefers-color-scheme: dark)").matches, coarse: matchMedia("(pointer: coarse)").matches })`);
          const extra = [];
          if (page.hash !== view) extra.push({ check: "view did not open", where: "page", detail: `asked ${view}, shows ${page.hash}` });
          if (page.sideways) {
            const widest = await evaluate(WIDEST);
            extra.push({ check: "sideways scroll", where: "page", detail: `${page.width} px${widest ? "; " + widest : ""}` });
          }
          for (const e of errors.splice(0)) extra.push({ check: "page error", where: "page", detail: String(e).split("\n")[0] });
          const findings = [...found, ...extra].filter((f) => {
            const a = ALLOW.get(`${view} | ${f.check} | ${f.where}`) || ALLOW.get(` | ${f.check} | ${f.where}`);
            if (!a) return true;
            a.seen += 1;
            return false;
          });
          report.push({ view, width, scheme, title: page.title, findings });
          passes.push({ view, width, scheme, innerWidth: page.innerWidth, dark: page.dark, coarse: page.coarse });
        }
      }
    }
    ws.close();
    const bad = report.filter((r) => r.findings.length);
    const counts = [...ALLOW].filter(([, a]) => a.seen !== a.want).map(([k, a]) => `${k.replace(/^ \| /, "")}: allowed ${a.want}, found ${a.seen}`);
    console.log(JSON.stringify({ views: report.length, failing: bad.length,
      allowed: [...ALLOW.values()].reduce((n, a) => n + a.seen, 0), passes, counts: counts.length ? counts : undefined,
      report: bad.length ? bad : undefined }, null, 1));
    return bad.length || counts.length ? 1 : 0;
  } finally {
    cleanup();
  }
}

main().then((code) => { process.exitCode = code; }, (e) => { console.error("AUT-5:", e.message); process.exitCode = 2; });
