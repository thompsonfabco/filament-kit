"""The Hub page's trust read (setup_trust.js loadTrust) must not undo a lock change made while its answer was out.
setup_trust.js runs in Node's vm with a stand-in for the page (SW.lock, SW.setLock, api); the answer is held back by hand."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_setup_page import STATIC

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const [file, replyJson, change] = process.argv.slice(1);
const listeners = [];
const SW = { lock: { state: "locked", code: null, trustOffered: true } };
SW.setLock = (state, o = {}) => {
  Object.assign(SW.lock, o, { state });
  if (state !== "unlocked") SW.lock.code = null;
  for (const l of listeners) l({ detail: state });
};
let release;
const ctx = vm.createContext({ SW, S: null, render() {}, console,
  document: { addEventListener: (_, f) => listeners.push(f) },
  api: () => new Promise((resolve) => { release = () => resolve(JSON.parse(replyJson)); }) });
vm.runInContext(fs.readFileSync(file, "utf8") + "\nthis.loadTrust = loadTrust;", ctx);
(async () => {
  const done = ctx.loadTrust();
  if (change === "unlock") { SW.setLock("unlocked"); SW.lock.code = "123456"; }
  if (change === "trusted") SW.setLock("trusted");
  release();
  await done;
  await new Promise((r) => setTimeout(r, 10));
  console.log(JSON.stringify({ state: SW.lock.state, code: SW.lock.code }));
})();
"""


def _read(reply: dict, change: str = "", before: str = "locked") -> dict:
    node = shutil.which("node")
    if not node:
        if os.environ.get("AUT5_REQUIRED") == "1":
            pytest.fail("AUT5_REQUIRED=1 but Node is missing")
        pytest.skip("needs Node")
    harness = HARNESS.replace('const listeners = [];', f'const listeners = [];\nconst before = {json.dumps(before)};')
    harness = harness.replace('(async () => {', '(async () => {\n  if (before !== "locked") SW.setLock(before);')
    run = subprocess.run([node, "-e", harness, str(STATIC / "setup_trust.js"), json.dumps(reply), change],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


OFF = {"enabled": True, "trusted": False, "id": None, "name": None, "expires": None}


def test_an_unlock_made_while_the_first_read_is_out_stays_unlocked():
    assert _read(OFF, "unlock") == {"state": "unlocked", "code": "123456"}


def test_an_answer_of_not_trusted_with_no_unlock_stays_locked():
    assert _read(OFF)["state"] == "locked"


def test_a_trusted_answer_opens_the_page_trusted():
    assert _read({**OFF, "trusted": True, "id": "x", "expires": 1})["state"] == "trusted"


def test_a_revoked_or_run_out_answer_locks_a_trusted_page():
    assert _read(OFF, "trusted")["state"] == "locked"
    assert _read(OFF, before="trusted")["state"] == "locked"

