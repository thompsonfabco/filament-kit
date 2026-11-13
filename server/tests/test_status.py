import json
from datetime import datetime
from pathlib import Path

import pytest

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
    assert s["hms"] == [{"code": "0700_8200_0002_0001", "text": status.hms_text("0700_8200_0002_0001")}]
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


def test_summarize_lists_the_external_spool_holder():
    report = {"ams": {"ams": [], "tray_now": "254"},
              "vt_tray": {"id": "254", "tray_type": "PETG", "tray_color": "00FF00FF", "tray_info_idx": "GFG00"}}
    s = status.summarize(report, [spool(5, "Office H2D – AMS Ext", name="PETG Green")], printer_name="Office H2D")
    (ext,) = s["ams"]
    assert (ext["unit"], ext["label"], ext["kind"]) == (254, "Ext", "ext")
    (slot,) = ext["slots"]
    assert (slot["label"], slot["type"], slot["color_hex"], slot["active"]) == ("Ext", "PETG", "00FF00", True)
    assert slot["spool"]["id"] == 5
    # no vt_tray in the report: no Ext unit; an odd id falls back to 254
    assert status.summarize({"ams": {"ams": []}}, [])["ams"] == []
    assert status.summarize({"vt_tray": {"id": "x"}}, [])["ams"][0]["unit"] == 254

def test_labels_for_more_units():
    # one label builder (final review M3): layout.label_for; status's id-only helpers are gone
    from filament_kit.bridge import layout
    assert not hasattr(status, "unit_label") and not hasattr(status, "slot_label")
    assert layout.label_for(3, 3) == "D4"
    assert layout.label_for(130, 0) == "HT-C"
    assert status.tray_now_tag("129") == "129:0"
    assert status.tray_now_tag(254) == "254:0" and status.tray_now_tag(255) is None
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


# ---------- final review: odd report items never raise ----------

ODD_REPORTS = [
    None, [], "text", {"gcode_state": ["RUNNING"]}, {"gcode_state": {"x": 1}},
    {"hms": [{"attr": "x", "code": None}, {"attr": -1, "code": 2 ** 40}, "str", 5]},
    {"hms": "not a list"}, {"hms": {"attr": 1}},
    {"lights_report": 7}, {"lights_report": [{"node": ["a"], "mode": "on"}, "x"]},
    {"device": "x"}, {"device": {"extruder": "x"}}, {"device": {"extruder": {"info": "x"}}},
    {"device": {"extruder": {"info": [5, None, {"id": "a", "temp": "hot"}, {"id": [1], "temp": 2 ** 40}]}}},
    {"device": {"bed": "x", "ctc": {"info": 3}}}, {"device": {"bed": {"info": {"temp": float("inf")}}}},
    {"ams": "x"}, {"ams": {"ams": "x"}}, {"ams": {"ams": [5, None, {"id": "z"}, {"id": 10 ** 9, "tray": []}]}},
    {"ams": {"ams": [{"id": -3, "tray": [{"id": 0}]}, {"id": 0, "tray": "x"}]}},
    {"ams": {"ams": [{"id": 0, "tray": [None, 7, {"id": 1, "tray_type": 5, "tray_color": 123}]}]}},
    {"ams": {"tray_now": [1]}},
    {"gcode_state": "RUNNING", "mc_remaining_time": 10 ** 15, "mc_percent": float("inf"), "stg_cur": "x"},
    {"gcode_state": "RUNNING", "mc_remaining_time": float("nan"), "layer_num": float("inf")},
    {"subtask_name": 7}, {"subtask_name": ["x"]},
]


@pytest.mark.parametrize("report", ODD_REPORTS)
def test_summarize_never_raises_on_odd_reports(report):
    spools = [{"id": "x", "location": 5, "filament": "x"}, None, {"id": 2, "filament": {"vendor": "v"}}]
    s = status.summarize(report, spools, printer_name="Shop")
    assert set(s) >= {"gcode_state", "percent", "remaining_min", "ams", "hms", "temps"}
    assert isinstance(s["gcode_state"], str) and isinstance(s["percent"], int)


def test_hms_text_known_code_is_a_sentence_unknown_gets_the_link():
    known = status.hms_text("0300_0100_0001_0001")
    assert known.startswith("Heatbed temperature is abnormal") and "0300_0100_0001_0001" in known
    assert "http" not in known
    unknown = status.hms_text("0700_8200_0002_0001")
    assert unknown.startswith("Printer alert HMS 0700_8200_0002_0001")
    assert unknown.endswith(status.HMS_URL + "0700_8200_0002_0001")
    s = status.summarize({"hms": [{"attr": 0x03000100, "code": 0x00010001}]}, [], now=NOW)
    assert s["hms"][0]["text"] == known


def test_hms_code_tolerates_bad_values():
    assert status.hms_code({"attr": "x", "code": None}) == "0000_0000_0000_0000"
    assert status.hms_code({"attr": -1, "code": 0}) == "FFFF_FFFF_0000_0000"


# ---------------------------------------------------------------- I2: a new job never inherits the last job's mapping

def test_job_start_drops_the_previous_jobs_mapping_and_plate():
    full = {"gcode_state": "FINISH", "subtask_name": "fk-calib-X", "mapping": [0, 1], "plate_idx": 1}
    out = status.merge_report(full, {"gcode_state": "PREPARE", "subtask_name": "bracket"})
    assert "mapping" not in out and "plate_idx" not in out and out["subtask_name"] == "bracket"
    assert full["mapping"] == [0, 1]                                    # input untouched


def test_job_start_keeps_a_mapping_the_same_delta_carries():
    out = status.merge_report({"gcode_state": "IDLE", "mapping": [0]},
                              {"gcode_state": "RUNNING", "mapping": [1, 128], "plate_idx": 2})
    assert out["mapping"] == [1, 128] and out["plate_idx"] == 2


def test_mapping_survives_deltas_within_one_job():
    full = status.merge_report({"gcode_state": "IDLE"}, {"gcode_state": "PREPARE"})
    full = status.merge_report(full, {"mapping": [1, 128]})
    full = status.merge_report(full, {"gcode_state": "RUNNING", "mc_percent": 5})   # PREPARE -> RUNNING
    full = status.merge_report(full, {"gcode_state": "FINISH"})
    assert full["mapping"] == [1, 128]


def test_status_lines_for_hardware_data(tmp_path, monkeypatch, capsys):
    from filament_kit import cli
    from filament_kit.bridge import hardware
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir(exist_ok=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    hardware._reset_cache()
    try:
        assert cli._hardware_lines() is True
        assert "printer hardware data" in capsys.readouterr().out
        (tmp_path / "etc" / "bambu_hardware.xml").write_text("<bambu-hardware version='9'/>", "utf-8")
        assert cli._hardware_lines() is False
        out = capsys.readouterr().out
        assert "FAIL" in out and "bambu_hardware.xml" in out
    finally:
        hardware._reset_cache()


def test_status_fails_on_a_refused_klipper_override(capsys):
    from filament_kit import cli
    from filament_kit.bridge.klipper import hardware as kh
    kh._reset_cache()
    try:
        assert cli._hardware_lines() is True
        assert "Klipper hardware data" not in capsys.readouterr().out      # nothing to say, on a Bambu-only kit too
        path = kh.override_path()
        path.write_text("<klipper-hardware version='9'><nope", "utf-8")
        assert cli._hardware_lines() is False
        out = capsys.readouterr().out
        assert "Klipper hardware data" in out and str(path) in out
    finally:
        kh._reset_cache()
