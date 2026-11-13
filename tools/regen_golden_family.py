"""Rewrite server/tests/data/golden/family/ (build.zip, current.json, deleted.json) from the code as it is now.

The golden family build is what an install without the Orca target made. Run this only when that output is meant to
change, then read `git diff` on the three files: the tests compare against them, so a regeneration that is not
reviewed makes the guard pass by definition. It runs test_regenerate_golden_family from server/tests/test_builds_orca.py,
which does nothing under a normal test run.

    python tools/regen_golden_family.py
(needs the server's test environment: tools/testenv.sh or tools/testenv.ps1 builds one)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server"


class _WriteGolden:
    def pytest_addoption(self, parser):
        parser.addoption("--write-golden", action="store_true", default=False)


if __name__ == "__main__":
    sys.path.insert(0, str(SERVER))
    sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "--rootdir", str(SERVER), "--write-golden",
                          str(SERVER / "tests" / "test_builds_orca.py::test_regenerate_golden_family")],
                         plugins=[_WriteGolden()]))
