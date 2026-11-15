"""AUT-5 runner start (tests/aut5_run.mjs connectToPage): it waits for the browser's DevTools endpoint.

Under load the browser writes its port file before the HTTP endpoint answers or a page exists; the runner once made a
single request and failed with "fetch failed". The driver runs the real function against a fake endpoint."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent


def _node():
    node = shutil.which("node")
    if not node:
        return None
    major = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0]
    return node if major.isdigit() and int(major) >= 22 else None


@pytest.mark.skipif(not _node(), reason="needs Node 22 or later")
def test_the_runner_waits_for_the_devtools_endpoint():
    r = subprocess.run([_node(), str(TESTS / "aut5_connect_check.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ok ") == 6, r.stdout


@pytest.mark.skipif(not _node(), reason="needs Node 22 or later")
def test_the_runner_leaves_no_browser_process_behind():
    # a node killed hard leaves its browser; the next run ends it by the profile folder in the command line
    r = subprocess.run([_node(), str(TESTS / "aut5_orphan_check.mjs")], capture_output=True, text=True, timeout=240)
    if r.returncode == 3 and os.environ.get("AUT5_REQUIRED") != "1":
        pytest.skip("no browser can run headless here: " + r.stdout.strip())
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ok ") == 8, r.stdout
