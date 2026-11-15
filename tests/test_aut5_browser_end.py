"""AUT-5 runner and page driver end only their own browser (tests/aut5_browser_end.mjs endOwnBrowser): the tree kill runs
while the browser is still running and not after it has exited. The driver runs the real function on real child processes."""
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
def test_cleanup_ends_only_a_running_browser():
    r = subprocess.run([_node(), str(TESTS / "aut5_browser_end_check.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ok ") == 3, r.stdout
