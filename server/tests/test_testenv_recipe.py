"""tools/testenv.sh on a small tree of its own: what its exit code and FLAKY lines say must be true."""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("xdist")
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("flock"), reason="the recipe is a Linux script")

REPO = Path(__file__).resolve().parents[2]

# Fails under xdist, passes without it: what "fails only in the crowd" means here, without a real race.
FLAKE = """
import os
def test_flake():
    assert not os.environ.get("PYTEST_XDIST_WORKER")
"""
REAL = """
def test_real():
    assert False
"""
GOOD = """
def test_good():
    pass
"""


@pytest.fixture
def recipe(tmp_path):
    root = tmp_path / "tree"
    for part in ("server/tests", "pc-sync/tests", "tools"):
        (root / part).mkdir(parents=True)
    (root / "server/pyproject.toml").write_text('[project]\nname = "s"\n')
    (root / "pc-sync/pyproject.toml").write_text('[project]\nname = "p"\n')
    shutil.copy(REPO / "tools/testenv.sh", root / "tools/testenv.sh")
    shutil.copytree(REPO / "tools/testenv_plugin", root / "tools/testenv_plugin")
    # The recipe's own venv is this test's Python: nothing to build, nothing downloaded.
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin/python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(python.stat().st_mode | stat.S_IEXEC)
    (venv / ".done").touch()

    def run(tests, *args):
        for name, text in tests.items():
            (root / "server/tests" / name).write_text(text)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "PYTHONPATH"))}
        env.update(FK_TEST_VENV=str(venv), HOME=str(tmp_path))
        return subprocess.run(
            ["bash", str(root / "tools/testenv.sh"), "--only", "server", "--workers", "2", *args],
            capture_output=True, text=True, env=env, timeout=120,
        )

    return run


def _flaky(result):
    return [line for line in result.stdout.splitlines() if line.startswith("FLAKY ")]


def test_a_test_that_passes_alone_passes_the_suite_and_is_named(recipe):
    r = recipe({"test_a.py": FLAKE, "test_b.py": GOOD})
    assert r.returncode == 0, r.stdout + r.stderr
    assert _flaky(r) == ["FLAKY tests/test_a.py::test_flake"]
    assert "1 passed only alone" in r.stdout


def test_a_flake_is_named_beside_a_real_failure(recipe):
    r = recipe({"test_a.py": FLAKE, "test_b.py": REAL})
    assert r.returncode == 1, r.stdout + r.stderr
    assert _flaky(r) == ["FLAKY tests/test_a.py::test_flake"]


def test_a_real_failure_is_not_retried_away_when_the_crash_limit_stopped_the_run(recipe):
    crash = """
import os
def test_crash():
    if os.environ.get("PYTEST_XDIST_WORKER"):
        os._exit(1)
"""
    tests = {"test_a.py": crash, **{f"test_n{i}.py": GOOD for i in range(12)}, "test_z.py": REAL}
    r = recipe(tests, "--workers", "1", "--", "--max-worker-restart=0")
    assert r.returncode == 1, r.stdout + r.stderr
    assert _flaky(r) == []
    assert "stopped early" in r.stdout


def test_a_test_that_only_skips_alone_did_not_pass(recipe):
    skip_alone = """
import os, pytest
def test_it():
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.skip("alone")
    assert False
"""
    r = recipe({"test_a.py": skip_alone})
    assert r.returncode == 1, r.stdout + r.stderr
    assert _flaky(r) == []


def test_a_flake_that_logged_an_error_still_gets_its_second_try(recipe):
    logged = """
import logging, os
def test_logged():
    logging.getLogger("x").error("boom")
    assert not os.environ.get("PYTEST_XDIST_WORKER")
"""
    r = recipe({"test_a.py": logged})
    assert r.returncode == 0, r.stdout + r.stderr
    assert _flaky(r) == ["FLAKY tests/test_a.py::test_logged"]


def test_a_parameter_with_spaces_and_a_dash_keeps_its_id(recipe):
    param = """
import os, pytest
@pytest.mark.parametrize("v", ["a - b"])
def test_p(v):
    assert not os.environ.get("PYTEST_XDIST_WORKER")
"""
    r = recipe({"test_a.py": param})
    assert r.returncode == 0, r.stdout + r.stderr
    assert _flaky(r) == ["FLAKY tests/test_a.py::test_p[a - b]"]


def test_a_collection_error_gets_no_second_try(recipe):
    r = recipe({"test_a.py": "import no_such_module_here\n", "test_b.py": GOOD})
    assert r.returncode != 0, r.stdout + r.stderr
    assert _flaky(r) == []


@pytest.mark.parametrize("only", ["servr", "server,pcsync", ""])
def test_a_suite_name_it_does_not_know_is_refused(only, tmp_path):
    r = subprocess.run(["bash", str(REPO / "tools/testenv.sh"), "--only", only], capture_output=True, text=True,
                       env={**os.environ, "HOME": str(tmp_path)}, timeout=30)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "--only" in r.stderr
