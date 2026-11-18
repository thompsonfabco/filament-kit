// Assumption 1 of DECISIONS R80 section 10 (EA5): a browser shows notifications for a page served with the Hub's own self-signed
// certificate once the person has accepted it. Test-only. A local HTTPS server takes the certificate of the Hub's make_cert; a
// headless Chrome, Edge or Chromium opens it, shows the certificate warning, and the page is taken through it the way a person does
// it (Advanced, Proceed) or with --ignore-certificate-errors. Headless has no permission prompt (it answers "denied"), so the
// person's "Allow" is stood in for by Browser.grantPermissions: what is observed is the page's secure context, the permission after
// the grant, that a Notification object is created and has its show handler attached; with --show 1 also that it fires "show" (the OS
// has to display it, so that part is opt-in). The browser's own prompt is not seen.
//   node https_notify.mjs --cert cert.pem --key key.pem --mode interstitial|flag [--show 1] [--browser <path>]
// Prints one JSON object. Exit 0; 2: no browser or the run failed; 3: the browser cannot run headless here.
import https from "node:https";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { endOwnBrowser } from "../../../tests/aut5_browser_end.mjs";

process.exitCode = 2;
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc, []));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const env = process.env;
const exe = args.browser || env.AUT5_BROWSER || [env["ProgramFiles(x86)"], env.ProgramFiles, env.LOCALAPPDATA].filter(Boolean)
  .flatMap((r) => [`${r}\\Microsoft\\Edge\\Application\\msedge.exe`, `${r}\\Google\\Chrome\\Application\\chrome.exe`]).concat(["/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/microsoft-edge"]).find((p) => existsSync(p));
if (!exe) { console.error("AUT-5: no Chrome, Edge or Chromium found (set AUT5_BROWSER)"); process.exit(2); }

const server = https.createServer({ key: readFileSync(args.key), cert: readFileSync(args.cert) }, (q, r) => {
  r.setHeader("content-type", "text/html"); r.end("<!doctype html><title>hub</title><h1>Hub</h1>");
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `https://localhost:${server.address().port}`;
const profile = mkdtempSync(join(tmpdir(), "aut5-https-"));
const linux = process.platform === "linux" ? ["--no-sandbox", "--disable-dev-shm-usage"] : [];
const proc = spawn(exe, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "--no-default-browser-check",
  ...(args.mode === "flag" ? ["--ignore-certificate-errors"] : []), ...linux, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
let err = "", gone = null;
proc.stderr.on("data", (d) => { err = (err + d).slice(-1500); });
proc.on("exit", (c, s) => { gone = s || c; });
proc.on("error", (e) => { gone = e.code || e.message; });
const cleanup = () => { endOwnBrowser(proc); server.close(); try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* held */ } };
process.once("exit", cleanup);
try {
  let port;
  for (let i = 0; i < 300 && !port && gone === null; i++) { await sleep(100); try { port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch { /* not yet */ } }
  if (!port) { console.error(`AUT-5: the browser could not start (${exe}; ${gone === null ? "no DevTools port after 30 s" : "it exited: " + gone})\n${err.trim().split("\n").slice(-6).join("\n")}`); process.exit(3); }
  const connect = async (url) => {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("could not reach the browser")); });
    let id = 0; const waiting = new Map();
    ws.onmessage = (m) => { const x = JSON.parse(m.data); if (x.id && waiting.has(x.id)) { waiting.get(x.id)(x); waiting.delete(x.id); } };
    return (method, params = {}) => new Promise((res) => { const n = ++id; waiting.set(n, res); ws.send(JSON.stringify({ id: n, method, params })); });
  };
  let page, version;
  for (let i = 0; i < 100 && !page; i++) {
    try { version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch { /* not yet */ }
    if (!page) await sleep(100);
  }
  const browser = await connect(version.webSocketDebuggerUrl), tab = await connect(page.webSocketDebuggerUrl);
  const ev = async (expression) => { const r = (await tab("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result; return r.exceptionDetails ? "EXC " + (r.exceptionDetails.exception && r.exceptionDetails.exception.description) : r.result.value; };
  await tab("Page.enable"); await tab("Runtime.enable");
  const out = { mode: args.mode };
  await tab("Page.navigate", { url: origin + "/" }); await sleep(1500);
  if (args.mode === "interstitial") {       // the certificate warning page; Advanced, then Proceed
    out.warning = await ev("document.title");
    await ev("document.getElementById('details-button').click(); document.getElementById('proceed-link').click(); 'clicked'");
    await sleep(1500);
  }
  out.page = await ev("document.title + ' | ' + location.href.split(':')[0]");
  out.secureContext = await ev("window.isSecureContext");
  out.hasNotification = await ev("'Notification' in window");
  out.permissionAtStart = await ev("Notification.permission");
  out.requestWithoutGrant = await ev("Notification.requestPermission()");       // headless: no prompt, so it answers for the person
  const grant = await browser("Browser.grantPermissions", { origin, permissions: ["notifications"] });
  out.grant = grant.error ? grant.error.message : "ok";
  out.permissionAfterGrant = await ev("Notification.permission");
  // required: the Notification is CREATED without throwing and the show handler is attached (nothing about the OS is asked)
  out.created = await ev(`(() => { try { const n = new Notification("Test", { body: "body", tag: "t" }); n.onshow = () => { window.__shown = true; };
    window.__note = n; return "created"; } catch (e) { return "threw " + e; } })()`);
  out.wired = await ev("typeof window.__note.onshow === 'function'");
  // opt-in (--show 1): the browser fires "show"; that needs the OS to display a toast, which some machines (notification or focus settings) do not
  out.shown = args.show === "1" ? await ev(`new Promise((res) => { const n = window.__note; n.onshow = () => res("show"); n.onerror = () => res("error");
    if (window.__shown) res("show"); setTimeout(() => res("created, no event in 3 s"), 3000); })`) : "not requested";
  await ev("try { window.__note.close(); } catch (e) {} 'closed'");
  console.log(JSON.stringify(out));
  browser("Browser.close");
  process.exitCode = 0;
} finally { cleanup(); }
