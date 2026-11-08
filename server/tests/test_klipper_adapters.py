"""bridge.klipper.adapters: Moonraker status → units/slots, and the gcode that assigns a spool."""
import json
from pathlib import Path

import pytest

from filament_kit.bridge.klipper import adapters
from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper.adapters.base import UnknownSlot

DATA = Path(__file__).parent / "data" / "klipper"


@pytest.fixture(autouse=True)
def etc(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path))
    kh._reset_cache()
    yield
    kh._reset_cache()


def status(name):
    return json.loads((DATA / name / "status.json").read_text())


def ctx(model_key, system_key):
    hw = kh.load()
    return hw.model(model_key), hw.system(system_key), hw


# ---- single -----------------------------------------------------------------------------------------------------

def test_single_from_SV08_fixture():
    m, s, hw = ctx("SOVOL-SV08-MAX", "single")
    a = adapters.get("single")
    units = a.read(status("SV08-MAX"), 7, None, m, s, hw)
    assert len(units) == 1
    u = units[0]
    assert (u.unit, u.label, u.kind) == (0, "T0", "toolhead")
    assert [(x.label, x.spool_id, x.active) for x in u.slots] == [("T0", 7, False)]
    assert u.slots[0].say == ["tool zero"]


def test_single_active_while_printing():
    m, s, hw = ctx("SOVOL-SV08-MAX", "single")
    st = status("SV08-MAX")
    st["print_stats"]["state"] = "printing"
    assert adapters.get("single").read(st, None, None, m, s, hw)[0].slots[0].active is True


def test_single_generic_label_T0():
    m, s, hw = ctx("generic", "single")
    assert adapters.get("single").read({}, None, None, m, s, hw)[0].slots[0].label == "T0"


def test_single_set_and_clear_gcode():
    m, s, hw = ctx("SOVOL-SV08-MAX", "single")
    a = adapters.get("single")
    assert a.set_gcode("T0", 7, m, s, hw) == "SET_ACTIVE_SPOOL ID=7"
    assert a.clear_gcode("T0", m, s, hw) == "CLEAR_ACTIVE_SPOOL"
    assert a.spool_on({"print_stats": {}}, 7, None, "T0", m, s) == 7
    assert a.publishes_lane_data is False


def test_unknown_label_raises():
    m, s, hw = ctx("SOVOL-SV08-MAX", "single")
    with pytest.raises(UnknownSlot):
        adapters.get("single").set_gcode("T9", 1, m, s, hw)


# ---- toolchanger ------------------------------------------------------------------------------------------------

def m1d_status(**spools):
    return {"print_stats": {"state": "standby"}, "toolhead": {"extruder": "extruder5"},
            "gcode_macro _FK_TOOL_SPOOLS": {f"t{k[1:]}": v for k, v in spools.items()}}


def test_toolchanger_seven_tools_m1d():
    m, s, hw = ctx("sovol-m1d", "tool-macros")
    a = adapters.get("toolchanger")
    units = a.read(m1d_status(t0=3, t5=9, t2=0), None, None, m, s, hw)
    by = {u.label: u for u in units}
    assert list(by) == ["L", "C1", "C2", "C3", "C4", "C5", "C6"]
    assert all(u.kind == "toolhead" for u in units)
    assert by["L"].slots[0].spool_id == 3 and by["L"].slots[0].active is False
    assert by["C5"].slots[0].spool_id == 9 and by["C5"].slots[0].active is True
    assert by["C2"].slots[0].spool_id is None and by["C3"].slots[0].spool_id is None
    assert by["C1"].slots[0].say == ["changer one"]


def test_toolchanger_set_gcode_c3():
    m, s, hw = ctx("sovol-m1d", "tool-macros")
    a = adapters.get("toolchanger")
    assert a.set_gcode("C3", 12, m, s, hw) == "FK_SET_TOOL_SPOOL TOOL=3 ID=12"
    assert a.clear_gcode("L", m, s, hw) == "FK_SET_TOOL_SPOOL TOOL=0 ID=0"
    assert a.spool_on(m1d_status(t3=12), None, None, "C3", m, s) == 12
    assert a.publishes_lane_data is True


def test_toolchanger_subscribes_to_its_macro():
    m, s, hw = ctx("sovol-m1d", "tool-macros")
    objs = adapters.get("toolchanger").objects(m, s)
    assert "gcode_macro _FK_TOOL_SPOOLS" in objs and "toolhead" in objs


def test_toolchanger_bad_spool_value_is_none():
    m, s, hw = ctx("sovol-m1d", "tool-macros")
    units = adapters.get("toolchanger").read(m1d_status(t0="junk", t1=-4), None, None, m, s, hw)
    assert units[0].slots[0].spool_id is None and units[1].slots[0].spool_id is None


def test_unknown_adapter():
    with pytest.raises(KeyError):
        adapters.get("nope")


# ---- AFC ---------------------------------------------------------------------------------------------------------

def test_afc_four_lanes():
    m, s, hw = ctx("generic", "afc")
    a = adapters.get("afc")
    units = a.read(status("afc"), None, None, m, s, hw)
    assert [(u.unit, u.label, u.kind) for u in units] == [(0, "Turtle_1", "lane")]
    slots = {x.label: x for x in units[0].slots}
    assert list(slots) == ["lane1", "lane2", "lane3", "lane4"]
    assert (slots["lane1"].spool_id, slots["lane1"].present, slots["lane1"].active) == (11, True, False)
    assert (slots["lane2"].spool_id, slots["lane2"].active, slots["lane2"].material) == (12, True, "PETG")
    assert (slots["lane3"].spool_id, slots["lane3"].present) == (None, False)
    assert slots["lane1"].color == "#FF0000"
    assert a.publishes_lane_data is False
    assert a.objects(m, s) == {"AFC": None}           # lanes come from the object list (objects_from)


def test_afc_objects_from_list():
    m, s, hw = ctx("generic", "afc")
    objs = json.loads((DATA / "afc" / "objects.json").read_text())["objects"]
    assert set(adapters.get("afc").objects_from(objs)) == {"AFC", "AFC_lane lane1", "AFC_lane lane2",
                                                          "AFC_lane lane3", "AFC_lane lane4"}


def test_afc_set_gcode():
    m, s, hw = ctx("generic", "afc")
    a = adapters.get("afc")
    st = status("afc")
    assert a.set_gcode("lane2", 30, m, s, hw, st) == "SET_SPOOL_ID LANE=lane2 SPOOL_ID=30"
    assert a.clear_gcode("lane2", m, s, hw, st) == "SET_SPOOL_ID LANE=lane2 SPOOL_ID="
    assert a.spool_on(st, None, None, "lane4", m, s) == 14


def test_afc_weird_lane_name_relabelled():
    m, s, hw = ctx("generic", "afc")
    st = {"AFC_lane my lane!": {"name": "my lane!", "unit": "U", "spool_id": 5, "load": True},
          "AFC_lane ok": {"name": "ok", "unit": "U", "spool_id": None, "load": False}}
    a = adapters.get("afc")
    labels = [x.label for x in a.read(st, None, None, m, s, hw)[0].slots]
    assert labels == ["L1", "ok"]
    with pytest.raises(UnknownSlot):          # the real name is not safe in gcode: refuse rather than send it
        a.set_gcode("L1", 9, m, s, hw, st)


# ---- Happy Hare --------------------------------------------------------------------------------------------------

def test_hh_gates():
    m, s, hw = ctx("generic", "happy-hare")
    a = adapters.get("happyhare")
    units = a.read(status("happyhare"), None, None, m, s, hw)
    assert [(u.label, u.kind) for u in units] == [("MMU", "lane")]
    g = {x.label: x for x in units[0].slots}
    assert list(g) == ["G0", "G1", "G2", "G3"]
    assert (g["G0"].spool_id, g["G0"].present, g["G0"].active) == (21, True, False)
    assert (g["G1"].spool_id, g["G1"].active, g["G1"].color) == (22, True, "#00FF00")
    st = status("happyhare")
    assert a.set_gcode("G2", 40, m, s, hw, st) == "MMU_GATE_MAP GATE=2 SPOOLID=40"
    assert a.clear_gcode("G2", m, s, hw, st) == "MMU_GATE_MAP GATE=2 SPOOLID=-1"
    assert a.spool_on(status("happyhare"), None, None, "G1", m, s) == 22


def test_hh_empty_gate_minus_one_is_none():
    m, s, hw = ctx("generic", "happy-hare")
    g = {x.label: x for x in adapters.get("happyhare").read(status("happyhare"), None, None, m, s, hw)[0].slots}
    assert (g["G2"].spool_id, g["G2"].present) == (None, False)
    assert (g["G3"].spool_id, g["G3"].present) == (None, None)        # gate_status -1 = unknown
    with pytest.raises(UnknownSlot):
        adapters.get("happyhare").set_gcode("G9", 1, m, s, hw, status("happyhare"))


# ---- lane_data ---------------------------------------------------------------------------------------------------

def test_lanedata_read_only():
    m, s, hw = ctx("generic", "lane-data")
    a = adapters.get("lanedata")
    db = {"lane0": {"lane": "0", "spool_id": 3, "material": "PLA", "color": "#112233"},
          "lane1": {"lane": "1", "spool_id": None}}
    units = a.read({}, None, db, m, s, hw)
    assert [(x.label, x.spool_id) for x in units[0].slots] == [("L0", 3), ("L1", None)]
    assert a.spool_on({}, None, db, "L0", m, s) == 3
    from filament_kit.bridge.klipper.adapters.base import NotSupported
    with pytest.raises(NotSupported):
        a.set_gcode("L0", 1, m, s, hw)
