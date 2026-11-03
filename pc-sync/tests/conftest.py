"""Test guard: no pc-sync test may see the real %APPDATA% / %LOCALAPPDATA% / %ProgramFiles%, or on Linux the real
$HOME / $XDG_CONFIG_HOME / $XDG_DATA_HOME.

Every test gets APPDATA and LOCALAPPDATA (and HOME, XDG_CONFIG_HOME, XDG_DATA_HOME) pointed at its own tmp_path,
so code that falls back to the environment can only ever reach a fixture tree.
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
    monkeypatch.setenv("HOME", str(tmp_path / "home"))                 # Linux: the slicers' folders and the timer
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home" / ".local" / "share"))
    # Linux: the Orca install search (/var/lib/flatpak, /usr/share, /usr/local/share, /opt) only sees tmp_path
    # unless a test passes its own folders
    from fksync import studio
    real_from_env = studio.LinuxLayout.from_env.__func__

    def from_env(cls, env, **kw):
        kw.setdefault("system_flatpak", tmp_path / "sys" / "var-lib-flatpak")
        kw.setdefault("share_dirs", (tmp_path / "sys" / "usr-share", tmp_path / "sys" / "usr-local-share"))
        kw.setdefault("opt_dirs", (tmp_path / "sys" / "opt",))
        return real_from_env(cls, env, **kw)
    monkeypatch.setattr(studio.LinuxLayout, "from_env", classmethod(from_env))
    yield
