// Test driver for tests/test_aut5_browser_end.py: endOwnBrowser (tests/aut5_browser_end.mjs) on real child processes.
// Prints "ok <name>" lines; exits 1 on a failed expectation.
import { spawn } from "node:child_process";
import { endOwnBrowser } from "./aut5_browser_end.mjs";

let failed = false;
const expect = (name, ok, detail = "") => { console.log(`${ok ? "ok" : "FAIL"} ${name} ${detail}`); failed ||= !ok; };
const gone = (p) => new Promise((res) => (p.exitCode !== null || p.signalCode !== null ? res() : p.once("exit", res)));

{   // a browser that has already exited: the tree kill is not called
  const p = spawn(process.execPath, ["-e", "0"], { stdio: "ignore" });
  await gone(p);
  let calls = 0;
  const ended = endOwnBrowser(p, () => { calls++; });
  expect("no tree kill after the browser exited", calls === 0 && ended === false, `calls=${calls}`);
}
{   // a process that never started
  let calls = 0;
  const p = spawn("aut5-no-such-program-x", [], { stdio: "ignore" });
  p.on("error", () => {});
  expect("no tree kill when it never started", !endOwnBrowser(p, () => { calls++; }) && calls === 0);
}
{   // a running browser: the default tree kill ends it
  const p = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], { stdio: "ignore" });
  await new Promise((r) => setTimeout(r, 300));
  const ended = endOwnBrowser(p);
  const died = await Promise.race([gone(p).then(() => true), new Promise((r) => setTimeout(() => r(false), 5000))]);
  expect("ends a running browser", ended === true && died, `ended=${ended}`);
  try { p.kill(); } catch { /* gone */ }
}
process.exit(failed ? 1 : 0);
