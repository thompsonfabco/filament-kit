"""AF1: the pure parts of tools/e2e's scenario i (the installer's port): the /proc/<pid>/status reader, the scenario's
registration, and the run holding 443 so every other scenario's Hub installs on 8710. The scenario itself runs on a
real host in the batch gate."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parents[2] / "tools" / "e2e"

STATUS_443 = """Name:\tpython
Uid:\t999\t999\t999\t999
NoNewPrivs:\t1
CapInh:\t0000000000000400
CapPrm:\t0000000000000400
CapEff:\t0000000000000400
CapBnd:\t0000000000000400
CapAmb:\t0000000000000400
"""


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


def test_the_status_reader(e2e):
    caps = e2e.parse_proc_status(STATUS_443)
    assert caps["CapEff"] == caps["CapBnd"] == caps["CapAmb"] == e2e.CAP_NET_BIND_SERVICE_BIT == 0x400
    assert caps["NoNewPrivs"] == 1
    empty = e2e.parse_proc_status(STATUS_443.replace("0000000000000400", "0000000000000000"))
    assert empty["CapEff"] == 0 and "Uid" not in empty
    assert e2e.parse_proc_status("") == {}


def test_scenario_i_is_registered_and_needs_a_clean_host(e2e):
    assert e2e.SCENARIOS["i"][1] == "i_install_port" and hasattr(e2e.E2E, "i_install_port")
    assert e2e.NEEDS["i"] == "clean"


def test_the_run_holds_443_and_scenario_i_lets_go(e2e, monkeypatch):
    held = []

    class FakeSocket:
        def __init__(self):
            self.closed = False

        def setsockopt(self, *a):
            pass

        def bind(self, addr):
            held.append(addr)

        def listen(self):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr(e2e.socket, "socket", FakeSocket)      # restored after the test
    run = e2e.E2E.__new__(e2e.E2E)
    run._port443 = None
    run.hold443()
    first = run._port443
    run.hold443()                                         # holding twice is one hold
    assert held == [("0.0.0.0", 443)] and run._port443 is first
    run.release443()
    assert first.closed and run._port443 is None
    run.release443()


def test_run_sh_checks_443_and_names_scenario_i():
    text = (E2E_DIR / "run.sh").read_text(encoding="utf-8")
    assert "for port in 443 7912 8101 8710 8883" in text and "g,h,i]" in text
