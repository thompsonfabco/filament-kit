// Test driver for tests/test_aut5_connect.py: the AUT-5 runner leaves no browser process behind. Runs the real runner
// against a tiny local page with a private temp folder (so every profile folder is this driver's own), then
//   1. a normal run: no process mentions its profile folder afterwards;
//   2. a run whose node is killed hard (no tree kill, no exit handler) leaves browser processes; the next run ends them.
// Prints "ok <name>" lines; exits 1 on a failed expectation, 3 when no browser can run headless here.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { aut5Processes, endTree } from "./aut5_run.mjs";

const RUNNER = join(dirname(fileURLToPath(import.meta.url)), "aut5_run.mjs");
const priv = mkdtempSync(join(tmpdir(), "fkorph-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const env = { ...process.env, TEMP: priv, TMP: priv, TMPDIR: priv };
const mine = () => aut5Processes().filter((p) => p.cmd.includes(priv));
let failed = false;
const expect = (name, ok, detail = "") => { console.log(`${ok ? "ok" : "FAIL"} ${name} ${detail}`); failed ||= !ok; };

const page = createServer((q, r) => { r.setHeader("content-type", "text/html"); r.end("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content=width=device-width><title>t</title></head><main id=main tabindex=-1><h1>t</h1></main>"); });
await new Promise((res) => page.listen(0, "127.0.0.1", res));
const url = `http://127.0.0.1:${page.address().port}/`;
const runnerArgs = (...more) => [RUNNER, "--url", url, "--views", "#a", "--widths", "1280", "--schemes", "light", ...more];

// asynchronous: the page server above lives in this process and must keep answering while the runner works
const run = (...more) => new Promise((res) => {
  const c = spawn(process.execPath, runnerArgs(...more), { env, stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  c.stderr.on("data", (d) => { stderr += d; });
  const t = setTimeout(() => c.kill(), 90000);
  c.on("exit", (status) => { clearTimeout(t); res({ status, stderr }); });
});
const profiles = () => readdirSync(priv).filter((n) => n.startsWith("aut5-")).map((n) => join(priv, n));
let code = 0;
try {
  const first = await run();
  if (first.status === 3 || first.status === 2) { console.log("no browser here: " + first.stderr.trim()); code = 3; }
  else {
    // the browser may still be closing when the runner exits: look for up to 10 s; what remains after that is a leak
    for (let i = 0; i < 40 && mine().length; i++) await sleep(250);
    expect("a normal run leaves no browser process", mine().length === 0, JSON.stringify(mine().map((p) => `${p.pid} ${p.cmd.slice(0, 120)}`)));
    expect("a normal run removes its profile folder", profiles().length === 0, profiles().join(","));

    // a run held in the page by --ready, then its node killed hard: no cleanup runs, the browser keeps running
    const held = spawn(process.execPath, runnerArgs("--ready", "new Promise(r => setTimeout(r, 120000))"), { env, stdio: "ignore" });
    let dir = null;
    for (let i = 0; i < 200 && !dir; i++) {
      await sleep(150);
      const d = profiles()[0];
      if (d && aut5Processes().some((p) => p.cmd.includes(d) && p.pid !== held.pid)) { await sleep(1500); dir = d; }
    }
    expect("the held run has a browser", !!dir);
    let rec = {};
    try { rec = JSON.parse(readFileSync(join(dir, "aut5-runner.pids"), "utf8")); } catch { /* reported below */ }
    expect("the runner records its pid and the browser's", rec.runner === held.pid && Number.isInteger(rec.browser), JSON.stringify(rec));
    // Edge's own children exit when its main process does (measured on this machine), so a renderer that outlives the
    // runner is simulated: a detached process with the profile folder in its command line
    const decoy = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)", "--", `--user-data-dir=${dir}`], { detached: true, stdio: "ignore" });
    decoy.unref();
    await sleep(500);
    process.kill(held.pid, "SIGKILL");      // node only: no /T, no exit handler
    await sleep(1500);
    const left = aut5Processes().filter((p) => p.cmd.includes(dir)).length;
    expect("a process of the dead run's profile outlives the dead runner", left > 0, `processes=${left}`);

    const second = await run();
    expect("the next run ran", second.status === 0 || second.status === 1, `status=${second.status} ${second.stderr.slice(-300)}`);
    const after = dir ? aut5Processes().filter((p) => p.cmd.includes(dir)) : [];
    expect("the next run ended the first run's browser processes", after.length === 0, JSON.stringify(after.map((p) => p.pid)));
    expect("the next run removed the first run's profile folder", profiles().length === 0, profiles().join(","));
  }
} finally {
  for (const p of mine()) endTree(p.pid);      // whatever this driver started and a failed expectation left
  page.close();
  rmSync(priv, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
process.exit(code || (failed ? 1 : 0));
