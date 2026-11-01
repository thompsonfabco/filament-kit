import json
from datetime import datetime
from pathlib import Path

from filament_kit.bridge import status

DATA = Path(__file__).parent / "data"
NOW = 1_762_000_000.0


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))["print"]


def spool(sid, location, vendor="Acme", name="Matte Red", material="PLA"):
    return {"id": sid, "location": location, "remaining_weight": 812.4,
            "filament": {"name": name, "material": material, "color_hex": "cc2222", "vendor": {"name": vendor}}}


def test_merge_keeps_untouched_keys_and_replaces_lists():
    full, delta = load("h2d_pushall.json"), load("h2d_delta.json")
    merged = status.merge(full, delta)
    assert merged["mc_percent"] == 43 and merged["layer_num"] == 121
    assert merged["gcode_state"] == "RUNNING"                     # untouched key kept
    assert merged["device"] == full["device"]                     # untouched subtree kept
    assert merged["ams"]["tray_now"] == "1"                       # untouched key inside a merged dict
    assert merged["ams"]["ams"] == delta["ams"]["ams"]            # list replaced as sent
    assert merged["ams"]["ams"][0]["tray"][0]["remain"] == 89
    assert full["mc_percent"] == 42 and full["hms"]               # inputs untouched


def test_merge_lists_replace_and_scalars_override():
    assert status.merge({"a": [1, 2, 3]}, {"a": [9]}) == {"a": [9]}
    assert status.merge({"u": [{"id": "0", "x": 1}]}, {"u": [{"id": "0", "y": 2}]}) == {"u": [{"id": "0", "y": 2}]}
    assert status.merge({"a": {"b": 1}}, {"a": 5}) == {"a": 5}


def test_delta_empties_slot():
    full = load("h2d_pushall.json")
    units = json.loads(json.dumps(full["ams"]["ams"]))
    units[0]["tray"][1] = {"id": "1"}                             # spool A2 pulled out
    merged = status.merge(full, {"ams": {"ams": units}})
    a2 = status.summarize(merged, [], now=NOW)["ams"][0]["slots"][1]
    assert (a2["label"], a2["type"], a2["color_hex"]) == ("A2", "", "")
    assert "tray_type" not in merged["ams"]["ams"][0]["tray"][1]


def test_hms_cleared_by_empty_list():
    full = load("h2d_pushall.json")
    assert status.summarize(full, [], now=NOW)["hms"]
    merged = status.merge(full, {"hms": []})
    assert merged["hms"] == [] and status.summarize(merged, [], now=NOW)["hms"] == []


def test_summarize_stage_progress_eta_temps():
    s = status.summarize(load("h2d_pushall.json"), [], updated=NOW - 3, now=NOW)
    assert s["gcode_state"] == "RUNNING"
    assert s["stage"] == "Heatbed preheating"
    assert s["job"] == "bracket_v3"
    assert (s["percent"], s["layer"], s["total_layers"], s["remaining_min"]) == (42, 120, 300, 75)
    assert datetime.fromisoformat(s["eta"]).timestamp() == NOW + 75 * 60 - (NOW + 75 * 60) % 60
    assert s["temps"]["nozzle"] == [{"current": 218, "target": 220}, {"current": 31, "target": 0}]
    assert s["temps"]["bed"] == {"current": 64, "target": 65}
    assert s["temps"]["chamber"] == {"current": 35, "target": 0}
    assert s["light"] == "on"
    assert s["hms"] == [{"code": "0700_8200_0002_0001", "text": "Printer alert HMS 0700_8200_0002_0001"}]
    assert s["updated"] == int(NOW - 3)


def test_summarize_ams_labels_and_spool_join():
    spools = [spool(7, "Office H2D – AMS A2", name="Basic Black", material="PETG"),
              spool(8, "Office H2D – AMS HT-A", name="PA-CF"),
              spool(9, "Shed X1 – AMS A1"),            # another printer's slot
              spool(10, "Office H2D - AMS A1")]           # hyphen, not the en dash: no match
    s = status.summarize(load("h2d_pushall.json"), spools, printer_name="Office H2D", now=NOW)
    a, ht = s["ams"]
    assert (a["unit"], a["label"], a["kind"]) == (0, "A", "ams")
    assert [x["label"] for x in a["slots"]] == ["A1", "A2", "A3", "A4"]
    assert (ht["unit"], ht["label"], ht["kind"]) == (128, "HT-A", "ams_ht")
    assert [x["label"] for x in ht["slots"]] == ["HT-A"]
    a1, a2, a3 = a["slots"][:3]
    assert (a1["type"], a1["color_hex"], a1["spool"]) == ("PLA", "FF0000", None)
    assert a2["spool"] == {"id": 7, "name": "Acme Basic Black", "material": "PETG", "color_hex": "cc2222",
                           "remaining_weight": 812.4}
    assert a2["active"] is True and a1["active"] is False      # tray_now 1 = unit 0, tray 1
    assert (a3["type"], a3["color_hex"], a3["spool"]) == ("", "", None)   # empty slot
    assert ht["slots"][0]["spool"]["id"] == 8


def test_labels_for_more_units():
    assert status.unit_label(3) == ("D", "ams")
    assert status.slot_label(3, 3) == "D4"
    assert status.unit_label(130) == ("HT-C", "ams_ht")
    assert status.slot_label(130, 0) == "HT-C"
    assert status.tray_now_tag("129") == "129:0"
    assert status.tray_now_tag(254) == "ext" and status.tray_now_tag(255) is None
    assert status.tray_now_tag("6") == "1:2"


def test_summarize_idle_and_older_printers():
    report = {"gcode_state": "IDLE", "stg_cur": 0, "mc_remaining_time": 0, "nozzle_temper": 25.5,
              "nozzle_target_temper": 0, "bed_temper": 24.0, "bed_target_temper": 0, "chamber_temper": 26}
    s = status.summarize(report, [], now=NOW)
    assert s["stage"] == "" and s["eta"] is None and s["job"] == ""
    assert s["temps"] == {"nozzle": [{"current": 25.5, "target": 0}], "bed": {"current": 24.0, "target": 0},
                          "chamber": {"current": 26, "target": None}}
    assert s["ams"] == [] and s["hms"] == [] and s["light"] is None and s["updated"] is None


def test_summarize_empty_report():
    s = status.summarize({}, [])
    assert s["gcode_state"] == "UNKNOWN" and s["temps"]["nozzle"] == [] and s["temps"]["chamber"] is None
