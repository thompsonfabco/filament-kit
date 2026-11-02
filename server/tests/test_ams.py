import json
from pathlib import Path

import pytest

from filament_kit import config
from filament_kit.bridge import ams, status

DATA = Path(__file__).parent / "data" / "h2d_pushall.json"


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "paths", lambda: type("P", (), {"state": tmp_path, "etc": tmp_path})())
    return tmp_path


def tray(i, t="PLA", color="FF0000FF", idx="GFA00"):
    return {"id": str(i), "tray_type": t, "tray_color": color, "tray_info_idx": idx}


def unit(uid, n=4):
    return {"id": str(uid), "tray": [tray(i) for i in range(n)]}


def test_h2d_report():
    rep = json.loads(DATA.read_text())["print"]
    rep["ams"]["ams"] += [unit(129, 1), unit(130, 1)]
    us = ams.units(rep)
    assert [u.label for u in us] == ["A", "HT-A", "HT-B", "HT-C"]
    assert [u.kind for u in us] == ["ams", "ams_ht", "ams_ht", "ams_ht"]
    a = us[0]
    assert [s.label for s in a.slots] == ["A1", "A2", "A3", "A4"]
    assert [s.global_id for s in a.slots] == [0, 1, 2, 3]
    assert (a.slots[0].type, a.slots[0].color, a.slots[0].preset) == ("PLA", "FF0000FF", "GFA00")
    assert a.slots[2].type == "" and a.slots[2].preset == ""
    ht = us[1].slots[0]
    assert (ht.label, ht.tray_id, ht.global_id, ht.type) == ("HT-A", 0, 128, "PA-CF")
    assert [u.slots[0].global_id for u in us[2:]] == [129, 130]


def test_p1s_single_ams():
    us = ams.units({"ams": {"ams": [unit(0)]}})
    assert len(us) == 1 and [s.label for s in us[0].slots] == ["A1", "A2", "A3", "A4"]


def test_x1_two_ams():
    us = ams.units({"ams": {"ams": [unit(1), unit(0)]}})
    assert [s.label for u in us for s in u.slots] == [f"{c}{n}" for c in "AB" for n in range(1, 5)]
    assert us[1].slots[3].global_id == 7


def test_labels_match_status():
    rep = {"ams": {"ams": [unit(0), unit(1), unit(128, 1)]}, "vt_tray": {"id": "254"}}
    st = status.summarize(rep, [])["ams"]
    assert [s["label"] for u in st for s in u["slots"]] == [s.label for u in ams.units(rep) for s in u.slots]


def test_external_spool():
    rep = {"ams": {"ams": [unit(0)]}, "vt_tray": {"id": "254", "tray_type": "PETG", "tray_color": "00FF00FF",
                                                  "tray_info_idx": "GFG00"}}
    us = ams.units(rep)
    ext = us[-1]
    assert ext.label == "Ext" and ext.slots[0].label == "Ext" and ext.slots[0].global_id == 254
    assert ext.slots[0].type == "PETG"
    assert ams.units({"vt_tray": {"id": "255"}})[0].slots[0].global_id == 255
    assert ams.units({"vt_tray": {}})[0].slots[0].global_id == 254


def test_garbage_report():
    assert ams.units({}) == [] and ams.units({"ams": "x"}) == []


def test_default_global():
    assert ams.default_global(0, 2) == 2
    assert ams.default_global(1, 3) == 7
    assert ams.default_global(128, 0) == 128
    assert ams.default_global(129, 0) == 129


def test_map_roundtrip(state):
    m = ams.load_map("SER1")
    assert m.slots == {} and m.calibrated is False and m.observe is True
    m.slots["A1"] = {"ams_id": 0, "tray_id": 0, "global_id": 0}
    m.calibrated, m.observe = True, False
    ams.save_map("SER1", m)
    f = state / "printers" / "SER1" / "slotmap.json"
    assert f.exists() and not list(f.parent.glob("*.tmp"))
    m2 = ams.load_map("SER1")
    assert m2.slots == m.slots and m2.calibrated and not m2.observe and m2.updated
    assert ams.load_map("OTHER").slots == {}
