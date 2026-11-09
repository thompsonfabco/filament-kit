"""Map by loading filament on a Klipper printer (bridge/klipper/manual.py): the owner makes each slot active, the printer
reports which one it is, the owner confirms; the answers relabel the printer's slots."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing
from filament_kit.api import create_app
from filament_kit.bridge import family, manual as bambu_manual, registry
from filament_kit.bridge.klipper import manual as kmanual
from filament_kit.bridge.klipper.adapters.base import SlotState, UnitState
from filament_kit.bridge.klipper.manager import KlipperFamily

PID = "m1d"


# ---------------------------------------------------------------- a stub family: what the session reads
class _Conn:
    def __init__(self):
        self.state = "connected"
        self.sub = type("Sub", (), {"connected": True})()


class StubFamily:
    """Seven tools as the M1D entry names them; `active` is the printer's own label of the active tool."""

    def __init__(self, labels=("L", "C1", "C2", "C3"), kind="toolchanger"):
        self.labels, self.kind, self.active, self.job = list(labels), kind, None, "standby"
        self.conn = _Conn()

    def _conn(self, pid):
        return self.conn

    def raw_slots(self, pid):
        u = UnitState(0, "tools", "toolhead", [SlotState(x, active=(x == self.active)) for x in self.labels])
        return [u], self.kind, self.job

    def forget_slot_map(self, pid):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    yield


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(kmanual.time, "time", lambda: now["t"])
    return now


@pytest.fixture
def tc(env):
    return StubFamily()


def settle(clock):
    clock["t"] += kmanual.SETTLE


def test_the_flow_names_each_tool_and_confirms_what_the_printer_reports(tc, clock):
    mm = kmanual.KlipperManualMaps(tc)
    s = mm.start(PID)
    assert s["open"] and s["step"]["position"]["label"] == "L" and s["reports_loads"] is True
    assert s["step"]["say"] == "Make L the active tool on the printer, then wait."
    assert s["step"]["seen"] is None and s["dual_nozzle"] is False and s["offer_report"] is False
    tc.active = "L"
    v = mm.view(PID)
    assert v["step"]["seen"] == {"reported": {"label": "L"}, "reported_label": "L", "nozzle": None,
                                 "nozzle_reported": False, "settled": False} and v["step"]["ask"] is None
    settle(clock)
    v = mm.view(PID)
    assert v["step"]["ask"] == "The printer now reports L active. Is that the L you loaded?"
    v = mm.confirm(PID, s["session"], "L", v["step"]["seen"]["reported"])
    assert v["positions"][0]["status"] == "confirmed" and v["step"]["position"]["label"] == "C1"
    assert kmanual.load_map(PID)["L"]["by"] == "user"            # same name: kept as a confirmation, nothing moves


def test_no_i_loaded_another_swaps_the_two_names(tc, clock):
    """The owner's C1 is what the data file calls C3: the two labels swap, so every tool keeps one name."""
    mm = kmanual.KlipperManualMaps(tc)
    s = mm.start(PID)
    mm.skip(PID, s["session"], "L")
    tc.active = "C3"
    mm.view(PID)
    settle(clock)
    v = mm.view(PID)
    assert v["step"]["ask"] == "The printer now reports C3 active. Is that the C1 you loaded?"
    v = mm.confirm(PID, s["session"], "C1", v["step"]["seen"]["reported"])
    m = kmanual.load_map(PID)
    assert m["C1"]["printer"] == "C3" and m["C1"]["by"] == "user"
    assert m["C3"]["printer"] == "C1" and m["C3"]["by"] is None           # moved, not confirmed
    assert kmanual.mapping(m, tc.labels) == {"L": "L", "C1": "C3", "C2": "C2", "C3": "C1"}


def test_the_relabelling_is_what_the_kit_shows_and_uses(tc, clock):
    mm = kmanual.KlipperManualMaps(tc)
    s = mm.start(PID)
    mm.skip(PID, s["session"], "L")
    tc.active = "C3"
    mm.view(PID)
    settle(clock)
    mm.confirm(PID, s["session"], "C1", {"label": "C3"})
    m = kmanual.load_map(PID)
    units = kmanual.relabel(tc.raw_slots(PID)[0], m)
    assert [x.label for x in units[0].slots] == ["L", "C3", "C2", "C1"]   # the printer's C1 shows as the owner's C3
    assert units[0].slots[3].active                                      # the printer's C3 is active: the owner's C1
    assert kmanual.printer_label(m, "C1", tc.labels) == "C3"


def test_a_map_that_no_longer_fits_is_ignored_whole(env):
    m = {"C1": {"printer": "C3", "by": "user", "at": None}, "C3": {"printer": "C1", "by": None, "at": None}}
    assert kmanual.mapping(m, ["L", "C1", "C2"]) == {"L": "L", "C1": "C1", "C2": "C2"}       # C3 is gone
    broken = {"C1": {"printer": "C3", "by": "user", "at": None}}                              # not a permutation
    assert kmanual.mapping(broken, ["C1", "C2", "C3"]) == {"C1": "C1", "C2": "C2", "C3": "C3"}


def test_the_slot_already_active_needs_a_change_first(tc, clock):
    """Nothing to see when the owner's first tool is the one already active: the page says what to do."""
    tc.active = "L"
    mm = kmanual.KlipperManualMaps(tc)
    s = mm.start(PID)
    assert "The printer has L active now" in s["step"]["say"]
    settle(clock)
    assert mm.view(PID)["step"]["seen"] is None
    tc.active = "C2"
    mm.view(PID)
    tc.active = "L"
    v = mm.view(PID)
    settle(clock)
    v = mm.view(PID)
    assert v["step"]["seen"]["reported_label"] == "L" and v["step"]["ask"]


def test_a_confirm_needs_what_the_printer_still_reports(tc, clock):
    mm = kmanual.KlipperManualMaps(tc)
    s = mm.start(PID)
    tc.active = "C1"
    mm.view(PID)
    settle(clock)
    mm.view(PID)
    tc.active = "C2"
    with pytest.raises(bambu_manual.ManualError) as e:
        mm.confirm(PID, s["session"], "L", {"label": "C1"})
    assert e.value.code == "stale"
    with pytest.raises(bambu_manual.ManualError) as e:
        mm.confirm("m1d", "old", "L", {"label": "C2"})
    assert e.value.code == "stale"
    with pytest.raises(bambu_manual.ManualError) as e:
        mm.confirm(PID, s["session"], "L", {"label": "T9"})
    assert e.value.status == 400
    with pytest.raises(bambu_manual.ManualError) as e:
        mm.confirm(PID, s["session"], "L", {"label": "C2"}, nozzle="left")
    assert e.value.status == 400


@pytest.mark.parametrize("kind", ["single", "lanedata"])
def test_a_printer_that_reports_no_active_slot_gets_the_by_hand_form(env, kind):
    f = StubFamily(labels=("L0", "L1"), kind=kind)
    f.active = "L1"                                     # single marks the slot active while printing: not a load
    mm = kmanual.KlipperManualMaps(f)
    s = mm.start(PID)
    assert s["reports_loads"] is False and s["choices"] == [{"reported": {"label": "L0"}, "label": "L0"},
                                                            {"reported": {"label": "L1"}, "label": "L1"}]
    assert "does not say which slot is active" in s["step"]["say"] and s["step"]["seen"] is None
    v = mm.confirm(PID, s["session"], "L0", {"label": "L1"}, by_hand=True)
    assert v["positions"][0]["status"] == "by_hand"
    assert kmanual.load_map(PID)["L0"] == {"printer": "L1", "by": "user-unverified", "at": kmanual.load_map(PID)["L0"]["at"]}


def test_no_report_for_a_minute_offers_the_by_hand_form(tc, clock):
    mm = kmanual.KlipperManualMaps(tc)
    mm.start(PID)
    clock["t"] += kmanual.NO_REPORT_AFTER
    v = mm.view(PID)
    assert v["reports_loads"] is False and len(v["choices"]) == 4


def test_busy_or_offline_printers_are_refused(tc):
    mm = kmanual.KlipperManualMaps(tc)
    tc.job = "printing"
    with pytest.raises(bambu_manual.ManualError) as e:
        mm.start(PID)
    assert e.value.code == "printer_busy"
    tc.job, tc.conn.sub.connected = "standby", False
    with pytest.raises(bambu_manual.ManualError) as e:
        mm.start(PID)
    assert e.value.code == "printer_offline"


def test_stop_keeps_what_was_confirmed_and_a_second_device_joins(tc, clock):
    mm = kmanual.KlipperManualMaps(tc)
    s = mm.start(PID)
    assert mm.start(PID)["session"] == s["session"]
    mm.confirm(PID, s["session"], "L", {"label": "C2"}, by_hand=True)
    v = mm.stop(PID, s["session"])
    assert v["open"] is False and v["step"] is None
    assert v["summary"].startswith("0 of 4 positions confirmed; 1 entered by hand") and "Not mapped: C1, C2, C3." in v["summary"]
    assert mm.view(PID)["open"] is False and kmanual.load_map(PID)["L"]["printer"] == "C2"
    assert mm.answer_offer(PID, True) == {"share": False}


def test_the_last_answer_closes_the_session(env, clock):
    f = StubFamily(labels=("T0", "T1"))
    mm = kmanual.KlipperManualMaps(f)
    s = mm.start(PID)
    mm.skip(PID, s["session"], "T0")
    v = mm.skip(PID, s["session"], "T1")
    assert v["open"] is False and v["step"] is None and v["summary"] == "0 of 2 positions confirmed; skipped: T0, T1."


def test_the_map_file_is_xml_and_survives_odd_text(env):
    kmanual.save_map(PID, {"C1": {"printer": "C3", "by": "user", "at": "2026-11-09T13:00:00-0500"},
                           "C3": {"printer": "C1"}})
    raw = (config.paths().state / "printers" / PID / kmanual.MAP_FILE).read_bytes()
    assert raw.startswith(b"<?xml") and b"<slot-map" in raw
    assert kmanual.load_map(PID)["C3"] == {"printer": "C1", "by": None, "at": None}
    (config.paths().state / "printers" / PID / kmanual.MAP_FILE).write_bytes(b"<not xml")
    assert kmanual.load_map(PID) == {}


# ---------------------------------------------------------------- the real family: shown and used under the owner's names
@pytest.fixture
def sm(spoolman_url):
    from filament_kit.spoolman import Spoolman
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def m1d(moonraker, sm):
    moonraker.objects = ["print_stats", "toolhead", "webhooks", "extruder", "extruder1", "extruder2",
                         "gcode_macro _FK_TOOL_SPOOLS", "gcode_macro FK_UNVERIFIED_M1D", "gcode_macro FK_SET_TOOL_SPOOL"]
    moonraker.status.update({"toolhead": {"extruder": "extruder"}, "extruder1": {}, "extruder2": {},
                             "gcode_macro _FK_TOOL_SPOOLS": {"t0": 0, "t1": 11, "t2": 0}})
    pid = registry.add_klipper("M1D", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    yield fam, pid, moonraker
    fam.stop()


def _labels(fam, pid):
    return [s.label for u in fam.slots(pid) for s in u.slots]


def test_the_family_shows_and_loads_under_the_owner_s_names(m1d, sm):
    """The owner's C1 is the printer's tool 2: its spool shows there, and a load of C1 sends TOOL=2."""
    fam, pid, fake = m1d
    assert fam.wait_settled(pid, 8) in ("connected", "unknown_model")
    model, system, adapter = fam.model(pid)
    if adapter.name != "toolchanger":
        pytest.skip("the M1D entry is not matched by this fake")            # guard: the detect rule may change
    labels = _labels(fam, pid)
    kmanual.save_map(pid, {"C1": {"printer": "C2", "by": "user", "at": "x"}, "C2": {"printer": "C1"}})
    after = {s.label: s.spool_id for u in fam.slots(pid) for s in u.slots}
    assert set(after) == set(labels) and after["C2"] == 11 and after.get("C1") is None
    assert fam.printer_label(pid, "C1", fake.status, None, None, model, system, adapter) == "C2"
    v = sm.post("vendor", {"name": "SUNLU"})
    f = sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA", "color_hex": "8a8c8e"})
    s = sm.post("spool", {"filament_id": f["id"], "location": "Shelf 2"})
    r = fam.load(sm, pid, "C1", s["id"], True, sealed_location="Sealed stock")
    assert r["command"] == {"gcode": f"FK_SET_TOOL_SPOOL TOOL=2 ID={s['id']}"}       # the printer's tool 2
    assert r["slot"]["label"] == "C1"                                                # the owner's name in Spoolman
