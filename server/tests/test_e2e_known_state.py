"""tools/e2e/e2e.py's known state after scenario f (review R201): f leaves the --previous tag's build, whose version
can equal this checkout's; the next scenario reinstalls the known state, its own check passes, and the stale printer,
pairing and spool of the old install are forgotten. Runs the runner's prepare() with the host stubbed (no install)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

E2E_DIR = Path(__file__).resolve().parents[2] / "tools" / "e2e"


@pytest.fixture
def e2e(monkeypatch):
    monkeypatch.syspath_prepend(str(E2E_DIR))
    spec = importlib.util.spec_from_file_location("e2e_under_test", E2E_DIR / "e2e.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 - a Linux-only import on this machine
        pytest.skip(f"tools/e2e/e2e.py does not load here ({type(e).__name__}: {e})")
    sys.modules.pop("e2e_under_test", None)
    return mod


class Run:
    def __init__(self):
        self.checks = []

    def check(self, sc, what, ok, detail=""):
        self.checks.append((what, bool(ok)))


class Printer:
    closed = False

    def close(self):
        self.closed = True


def _runner(e2e, monkeypatch, version="9.9.9"):
    state = {"version": version, "installs": 0}
    rel = SimpleNamespace(base_version=lambda: "9.9.9", built={}, api="http://x",
                          get_sh=lambda args, name: (state.__setitem__("installs", state["installs"] + 1),
                                                     state.__setitem__("version", "9.9.9"),
                                                     SimpleNamespace(returncode=0, stdout="", stderr=""))[-1])
    monkeypatch.setattr(e2e, "installed_version", lambda: state["version"])
    monkeypatch.setattr(e2e, "read_cfg", lambda: {"modules": {"server": True, "spoolman": True}})
    monkeypatch.setattr(e2e, "nothing_installed", lambda: [])
    monkeypatch.setattr(e2e, "uninstall", lambda *a, **k: None)
    monkeypatch.setattr(e2e, "wait_for", lambda *a, **k: True)
    run = Run()
    x = e2e.E2E(run, rel)
    monkeypatch.setattr(x, "_v1_on_server", lambda: None)
    monkeypatch.setattr(x, "_seed", lambda key: None)
    return x, run, state


def test_after_f_the_known_state_is_reinstalled_and_its_check_passes(e2e, monkeypatch):
    x, run, state = _runner(e2e, monkeypatch)
    x.printer, x.token, x.spool = Printer(), "tok", {"id": 1}
    stale = x.printer
    x.foreign_install = True                       # what f leaves, its build reporting this checkout's version
    x.prepare("g")
    assert state["installs"] == 1
    assert run.checks and all(ok for _what, ok in run.checks), run.checks
    assert x.foreign_install is False and x.printer is None and stale.closed and x.token is None


def test_without_f_the_known_state_is_kept(e2e, monkeypatch):
    x, run, state = _runner(e2e, monkeypatch)
    x.printer = Printer()
    x.prepare("c")
    assert state["installs"] == 0 and x.printer is not None and not run.checks
