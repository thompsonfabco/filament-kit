"""Map by loading filament (bridge/manual.py): the owner loads each slot, the printer reports it, the owner confirms."""
from __future__ import annotations

import copy

import pytest

from filament_kit.bridge import ams, manual, mapping, registry

SERIAL = "0948ZZ0A0000001"


def tray(tid, kind="PLA"):
    return {"id": str(tid), "tray_type": kind, "tray_color": "FF0000FF", "tray_info_idx": "Pa111111"}


BASE = {"gcode_state": "IDLE",
        "ams": {"tray_now": "255", "ams": [{"id": "0", "tray": [tray(0), tray(1), tray(2), tray(3)]}]},
        "vt_tray": {"id": "254", "tray_type": "PLA", "tray_color": "FFFFFFFF"}}


class FakeManager:
    def __init__(self, report):
        self.report = report
        self.st = "connected"

    def state(self, serial):
        return self.st

    def wait_report(self, serial, predicate, timeout):
        return copy.deepcopy(self.report)


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(manual.time, "time", lambda: now["t"])
    return now


@pytest.fixture
def x1c(env):
    registry.upsert(registry.Printer(SERIAL, "Shop X1C", "BL-P001", "10.0.0.6", "13572468", True))
    return FakeManager(copy.deepcopy(BASE))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    yield
    mapping.manual_end(SERIAL)


def load(m, tray_now):
    m.report["ams"]["tray_now"] = str(tray_now)


def test_the_flow_names_each_position_and_confirms_what_the_printer_reports(x1c, clock):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    assert s["open"] and s["step"]["position"]["label"] == "A1" and s["step"]["say"] == "Load A1 to the nozzle, then wait."
    assert s["step"]["seen"] is None and s["reports_loads"] is True
    load(x1c, 1)                                        # the owner loaded what the printer calls A2
    v = mm.view(SERIAL)
    assert v["step"]["seen"]["settled"] is False and v["step"]["ask"] is None
    clock["t"] += manual.SETTLE
    v = mm.view(SERIAL)
    assert v["step"]["ask"] == "The printer now reports A2 loaded. Is that the A1 you loaded?"
    # "No, I loaded A2": the pair goes to A2, and A1 is still to do
    v = mm.confirm(SERIAL, s["session"], "A2", v["step"]["seen"]["reported"])
    assert {p["label"]: p["status"] for p in v["positions"]}["A2"] == "confirmed"
    assert v["step"]["position"]["label"] == "A1"
    m = ams.load_map(SERIAL)
    assert m.slots["A2"]["ams_id"] == 0 and m.slots["A2"]["tray_id"] == 1 and m.by_user["A2"]["by"] == "user"
    assert m.calibrated is False and m.observe is True       # which slot is which; the numbering is not proven


def test_yes_skip_and_stop_and_the_summary(x1c, clock):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    load(x1c, 0)
    mm.view(SERIAL)
    clock["t"] += manual.SETTLE
    v = mm.view(SERIAL)
    v = mm.confirm(SERIAL, s["session"], "A1", v["step"]["seen"]["reported"])
    v = mm.skip(SERIAL, s["session"], "A2")
    assert v["step"]["position"]["label"] == "A3"
    v = mm.stop(SERIAL, s["session"])
    assert v["open"] is False and v["step"] is None
    assert v["summary"].startswith("1 of 5 positions confirmed; skipped: A2.") and "Not mapped: A3, A4, Ext." in v["summary"]
    assert "filament use stays logged only" in v["summary"]
    assert v["offer_report"] is True
    assert mm.answer_offer(SERIAL, False) == {"share": False, "message": "Noted: this map is not shared."}
    assert mm.view(SERIAL)["offer_report"] is False


def test_the_share_question_is_asked_once(x1c, clock):
    mm = manual.ManualMaps(x1c)
    for _ in range(2):
        s = mm.start(SERIAL)
        load(x1c, 0)
        mm.view(SERIAL)
        clock["t"] += manual.SETTLE
        v = mm.view(SERIAL)
        mm.confirm(SERIAL, s["session"], "A1", v["step"]["seen"]["reported"])
        v = mm.stop(SERIAL, s["session"])
        if _ == 0:
            assert v["offer_report"] is True
            r = mm.answer_offer(SERIAL, True)
            assert r["share"] is True and f"printer report {SERIAL}" in r["message"] and "sends nothing" in r["message"]
        else:
            assert v["offer_report"] is False
        load(x1c, 255)


def test_a_proven_numbering_makes_the_owners_map_count(x1c, clock):
    ams.save_map(SERIAL, ams.SlotMap(scheme="legacy", calibrated=True, observe=False))
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    load(x1c, 2)
    mm.view(SERIAL)
    clock["t"] += manual.SETTLE
    v = mm.view(SERIAL)
    mm.confirm(SERIAL, s["session"], "A3", v["step"]["seen"]["reported"])
    m = ams.load_map(SERIAL)
    assert m.calibrated is True and m.observe is False and m.slots["A3"]["global_id"] == 2


def test_a_printer_that_reports_no_load_gets_the_by_hand_form(env, clock):
    report = copy.deepcopy(BASE)
    del report["ams"]["tray_now"]
    registry.upsert(registry.Printer(SERIAL, "Shop X1C", "BL-P001", "10.0.0.6", "13572468", True))
    fm = FakeManager(report)
    mm = manual.ManualMaps(fm)
    s = mm.start(SERIAL)
    assert s["reports_loads"] is False and "does not say what is loaded" in s["step"]["say"]
    choice = next(c for c in s["choices"] if c["label"] == "A3")
    v = mm.confirm(SERIAL, s["session"], "A1", choice["reported"], by_hand=True)
    assert {p["label"]: p["status"] for p in v["positions"]}["A1"] == "by_hand"
    assert ams.load_map(SERIAL).by_user["A1"]["by"] == "user-unverified"


def test_a_load_field_that_never_changes_falls_back_to_the_form_after_a_minute(x1c, clock):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    assert s["reports_loads"] is True
    clock["t"] += manual.NO_REPORT_AFTER
    v = mm.view(SERIAL)
    assert v["reports_loads"] is False and v["choices"]


def test_a_load_that_no_longer_shows_is_not_confirmed(x1c, clock):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    load(x1c, 1)
    mm.view(SERIAL)
    clock["t"] += manual.SETTLE
    v = mm.view(SERIAL)
    load(x1c, 255)                                      # unloaded meanwhile
    mm.view(SERIAL)
    with pytest.raises(manual.ManualError) as e:
        mm.confirm(SERIAL, s["session"], "A1", v["step"]["seen"]["reported"])
    assert e.value.code == "stale"


@pytest.mark.parametrize("position,reported,code", [("Z9", {"ams_id": 0, "tray_id": 1}, "bad_request"),
                                                    ("A1", {"ams_id": 7, "tray_id": 3}, "bad_request"),
                                                    ("A1", "A2", "bad_request")])
def test_bad_answers_are_refused(x1c, clock, position, reported, code):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    with pytest.raises(manual.ManualError) as e:
        mm.confirm(SERIAL, s["session"], position, reported, by_hand=True)
    assert e.value.code == code


def test_an_old_session_id_is_stale(x1c):
    mm = manual.ManualMaps(x1c)
    mm.start(SERIAL)
    with pytest.raises(manual.ManualError) as e:
        mm.skip(SERIAL, "nope", "A1")
    assert e.value.code == "stale"


def test_a_second_device_joins_the_open_session(x1c):
    mm = manual.ManualMaps(x1c)
    assert mm.start(SERIAL)["session"] == mm.start(SERIAL)["session"]


def test_busy_or_offline_refuses(x1c):
    mm = manual.ManualMaps(x1c)
    x1c.report["gcode_state"] = "RUNNING"
    with pytest.raises(manual.ManualError) as e:
        mm.start(SERIAL)
    assert e.value.code == "printer_busy"
    x1c.report["gcode_state"] = "IDLE"
    x1c.st = "disconnected"
    with pytest.raises(manual.ManualError) as e:
        mm.start(SERIAL)
    assert e.value.code == "printer_offline"


def test_the_automatic_job_waits_while_the_owner_maps(x1c):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    with pytest.raises(mapping.ManualRunning):
        mapping.Mapper(x1c)._begin(SERIAL)
    mm.stop(SERIAL, s["session"])
    assert mapping.manual_begin(SERIAL) is True                 # free again
    mapping.manual_end(SERIAL)


def test_the_automatic_job_never_replaces_the_owners_entry():
    smap = ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 2, "global_id": 2},
                              "A3": {"ams_id": 0, "tray_id": 0, "global_id": 0}})
    owner = ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                        by_user={"A1": {"by": "user", "at": "2026-11-09T13:00:00-0500"}})
    ams.save_map(SERIAL, owner)
    problems = []
    mapping._keep_owner_entries(SERIAL, smap, problems)
    assert smap.slots["A1"]["tray_id"] == 0 and "A3" not in smap.slots and smap.by_user["A1"]["by"] == "user"
    assert len(problems) == 1 and "your entry stays" in problems[0]



def _kept(owner_slot, job_slots, calibrated, scheme=None):
    """The number a kept owner entry for A1 ends with, after a job that found `job_slots`."""
    smap = ams.SlotMap(slots=job_slots, calibrated=calibrated, scheme=scheme)
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": owner_slot},
                                     by_user={"A1": {"by": "user", "at": "2026-11-09T13:00:00-0500"}}))
    mapping._keep_owner_entries(SERIAL, smap, [])
    assert (smap.slots["A1"]["ams_id"], smap.slots["A1"]["tray_id"]) == (owner_slot["ams_id"], owner_slot["tray_id"])
    return smap.slots["A1"]["global_id"]


def test_a_kept_entry_takes_the_number_the_calibrated_job_proved_for_its_slot():
    # the job found A3 at the owner's A1 address and proved 7 for it: the owner's number (made before) is not kept
    assert _kept({"ams_id": 0, "tray_id": 0, "global_id": 256},
                 {"A1": {"ams_id": 0, "tray_id": 2, "global_id": 2}, "A3": {"ams_id": 0, "tray_id": 0, "global_id": 7}},
                 calibrated=True, scheme="legacy") == 7


def test_a_kept_entry_the_job_did_not_reach_takes_the_proven_schemes_number():
    assert _kept({"ams_id": 1, "tray_id": 0, "global_id": 256}, {"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                 calibrated=True, scheme="legacy") == ams.scheme_global(1, 0, "legacy") == 4


def test_a_kept_entry_has_no_number_when_the_calibrated_job_proved_no_scheme():
    assert _kept({"ams_id": 1, "tray_id": 0, "global_id": 256}, {}, calibrated=True) is None


def test_a_kept_external_holder_keeps_its_own_id():
    assert _kept({"ams_id": 254, "tray_id": 0, "global_id": 1}, {}, calibrated=True) == 254


def test_an_uncalibrated_map_keeps_the_owners_number():
    assert _kept({"ams_id": 1, "tray_id": 0, "global_id": 256},
                 {"A3": {"ams_id": 1, "tray_id": 0, "global_id": 4}}, calibrated=False) == 256


def test_a_dual_nozzle_printer_says_which_nozzle_when_it_reports_one(env, clock):
    registry.upsert(registry.Printer(SERIAL, "Office H2D", "O1D", "10.0.0.5", "13572468", True))
    report = copy.deepcopy(BASE)
    report["device"] = {"extruder": {"info": [{"id": 0, "snow": 0xFFFF}, {"id": 1, "snow": 0xFFFF}]}}
    fm = FakeManager(report)
    mm = manual.ManualMaps(fm)
    s = mm.start(SERIAL)
    assert s["dual_nozzle"] is True
    fm.report["device"]["extruder"]["info"][1]["snow"] = (0 << 8) | 3      # the left nozzle now holds A4
    mm.view(SERIAL)
    clock["t"] += manual.SETTLE
    v = mm.view(SERIAL)
    assert v["step"]["seen"]["nozzle"] == "left" and v["step"]["seen"]["nozzle_reported"] is True
    mm.confirm(SERIAL, s["session"], "A4", v["step"]["seen"]["reported"], nozzle="left")
    assert ams.load_map(SERIAL).by_user["A4"]["nozzle"] == "left"


def test_a_nozzle_on_a_single_nozzle_printer_is_refused(x1c):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    with pytest.raises(manual.ManualError):
        mm.confirm(SERIAL, s["session"], "A1", {"ams_id": 0, "tray_id": 0}, nozzle="left", by_hand=True)


def test_a_session_nobody_touches_closes_and_frees_the_automatic_job(x1c, clock):
    mm = manual.ManualMaps(x1c)
    s = mm.start(SERIAL)
    clock["t"] += manual.IDLE_CLOSE - 1
    mm.view(SERIAL)                                              # a poll keeps it open
    clock["t"] += manual.IDLE_CLOSE - 1
    assert mm.view(SERIAL)["open"] is True
    clock["t"] += manual.IDLE_CLOSE
    mm.expire(SERIAL)
    assert mm.view(SERIAL)["open"] is False
    with pytest.raises(manual.ManualError) as e:
        mm.skip(SERIAL, s["session"], "A1")
    assert e.value.code == "none"
    assert mapping.manual_begin(SERIAL) is True                  # the printer is free for an automatic job again
    mapping.manual_end(SERIAL)
    assert mm.start(SERIAL)["session"] != s["session"]           # and a new session can start
