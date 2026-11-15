// Ends the browser a test run started, and only that one: its whole process tree (the browser's helper processes
// outlive a plain kill on Windows), and only while the browser is still running. Shared by the AUT-5 runner and the
// page driver; no other process or folder is looked at.
import { spawnSync } from "node:child_process";

function killTree(proc) {
  if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
  else proc.kill("SIGKILL");
}

// `tree` is replaceable so a test can see whether it was called
export function endOwnBrowser(proc, tree = killTree) {
  if (!proc || !proc.pid || proc.exitCode !== null || proc.signalCode !== null) return false;   // never started, or gone
  try { tree(proc); } catch { /* gone meanwhile */ }
  return true;
}
