"""Test guard: no pc-sync test may see the real %APPDATA% / %LOCALAPPDATA% / %ProgramFiles%.

Every test gets APPDATA and LOCALAPPDATA pointed at its own tmp_path, so code that
falls back to the environment can only ever reach a fixture tree.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # studio_fixture

# Captured at import, before any test runs, only so the guard self-test can prove the
# fixture replaced it. Never used to read anything.
REAL_ENV = {k: os.environ.get(k) for k in ("APPDATA", "LOCALAPPDATA")}


@pytest.fixture(autouse=True)
def _fake_appdata(tmp_path, monkeypatch):
    appdata, local = tmp_path / "appdata", tmp_path / "local"
    appdata.mkdir()
    local.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):   # the Orca Slicer install search
        monkeypatch.setenv(var, str(tmp_path / "programfiles"))
    yield
