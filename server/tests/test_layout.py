"""P2: the shared unit builder (`bridge.layout`): any AMS layout (16 units mixed with HT), labels without limit,
external holders from `vir_slot[]` / `vt_tray`, presence bits with fallback, module codes, layout fingerprint."""
import json
from pathlib import Path

import pytest

from filament_kit.bridge import ams, hardware, layout, status

DATA = Path(__file__).parent / "data"


def tray(i, t="PLA", color="FF0000FF", idx="GFA00"):
    return {"id": str(i), "tray_type": t, "tray_color": color, "tray_info_idx": idx}


def unit(uid, n=4, **kw):
    return {"id": str(uid), "tray": [tray(i) for i in range(n)], **kw}


def ext(i, t="", color="00000000"):
    return {"id": str(i), "tray_type": t, "tray_color": color, "tray_info_idx": ""}


def big_report():
    """16 AMS units (ids 0-15), 8 AMS HT units (128-135), two external holders: a synthetic H2D-style report."""
    units = [unit(i) for i in range(16)] + [unit(128 + i, 1) for i in range(8)]
    return {"ams": {"ams": units, "tray_now": "255", "tray_exist_bits": "ffffffff", "tray_reading_bits": "0"},
            "vir_slot": [ext(254, "TPU", "FFFFFFFF"), ext(255)]}


def labels(lay):
    return [s.label for u in lay.units for s in u.slots]


def test_letters_spreadsheet_style_without_limit():
    assert [layout.letters(n) for n in (0, 1, 25, 26, 27, 51, 52, 701, 702)] == \
        ["A", "B", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"]


def test_sixteen_units_mixed_with_ht_and_two_externals_get_unique_labels():
    lay = layout.build(big_report(), "O1D")
    labs = labels(lay)
    assert len(labs) == len(set(labs)) == 16 * 4 + 8 + 2
    assert labs[:5] == ["A1", "A2", "A3", "A4", "B1"]
    assert "P4" in labs and "HT-A" in labs and "HT-H" in labs
    assert labs[-2:] == ["Ext-L", "Ext-R"]
    kinds = {u.label: u.kind for u in lay.units}
    assert kinds["A"] == "ams" and kinds["HT-C"] == "ams_ht" and kinds["Ext-L"] == kinds["Ext-R"] == "ext"
    assert {u.label: u.type_name for u in lay.units}["HT-A"] == "AMS HT"
    say = {s.label: s.say for u in lay.units for s in u.slots}
    assert say["Ext-L"] == ("external", "left") and say["HT-B"] == ("h", "t", "b") and say["P4"] == ("p", "4")
    # 16 units do not fit bits-v1 (ids 0-3 only): presence falls back to tray_type, status says so
    assert lay.presence == "tray_type"
    assert any("presence layout unknown" in n for n in lay.notes)
    assert all(s.present is True for u in lay.units if u.kind != "ext" for s in u.slots)
    assert all(s.reading is None for u in lay.units for s in u.slots)


def test_more_than_26_units_labels_keep_going():
    rep = {"ams": {"ams": [unit(i) for i in range(30)]}}
    lay = layout.build(rep, None)
    assert [u.label for u in lay.units][25:28] == ["Z", "AA", "AB"]
    assert len(set(labels(lay))) == 120


def test_presence_bits_h2d_layout():
    rep = json.loads((DATA / "h2d_pushall.json").read_text())["print"]
    rep["ams"]["ams"] += [unit(129, 1), unit(130, 1)]
    rep["ams"]["ams"][1]["tray"][0] = {"id": "0"}               # HT-A emptied
    rep["ams"]["tray_exist_bits"] = "6000b"                     # A1 A2 A4, HT-B, HT-C (bit 16 off: HT-A empty)
    rep["ams"]["tray_reading_bits"] = "40000"                   # HT-C reading
    lay = layout.build(rep, "H2D")
    got = {s.label: (s.present, s.reading) for u in lay.units for s in u.slots}
    assert got["A1"] == (True, False) and got["A3"] == (False, False) and got["A4"] == (True, False)
    assert got["HT-A"] == (False, False) and got["HT-B"] == (True, False) and got["HT-C"] == (True, True)
    assert lay.presence == "bits" and not lay.notes


def test_presence_collision_falls_back_to_tray_type():
    # a unit reporting more trays than bits-v1 gives it: unit 0 tray 4 would share bit 4 with unit 1 tray 0
    rep = {"ams": {"ams": [unit(0, 5), unit(1)], "tray_exist_bits": "1ff"}}
    rep["ams"]["ams"][1]["tray"][2] = {"id": "2"}
    lay = layout.build(rep, "X1C")
    assert lay.presence == "tray_type" and any("presence layout unknown" in n for n in lay.notes)
    got = {s.label: s.present for u in lay.units for s in u.slots}
    assert got["A5"] is True and got["B3"] is None              # empty tray_type: unknown, never "absent"


def test_presence_without_bits_in_report_is_unknown():
    lay = layout.build({"ams": {"ams": [unit(0)]}}, "X1C")
    assert lay.presence == "tray_type"
    lay = layout.build({"ams": {"ams": [unit(0)], "tray_exist_bits": "f"}}, None)   # unknown model: no layout
    assert lay.presence == "tray_type" and any("presence layout unknown" in n for n in lay.notes)


def test_module_codes_from_get_version():
    rep = {"ams": {"ams": [unit(0), unit(128, 1), unit(1)]},
           layout.MODULES: {"0": "N3F05", "128": "N3S05", "1": "Z9Q01"}}
    lay = layout.build(rep, "O1D")
    by = {u.ams_id: u for u in lay.units}
    assert (by[0].kind, by[0].type_name, by[0].module) == ("ams_2pro", "AMS 2 Pro", "N3F05")
    assert by[128].kind == "ams_ht"
    assert (by[1].kind, by[1].type_name, by[1].known) == ("generic", "Unknown AMS", False)
    assert by[1].label == "B" and [s.label for s in by[1].slots] == ["B1", "B2", "B3", "B4"]
    assert any("Z9Q01" in n and "unknown" in n for n in lay.notes)


def test_unknown_module_on_an_ht_id_keeps_the_ht_label():
    lay = layout.build({"ams": {"ams": [unit(129, 1)]}, layout.MODULES: {"129": "N3S07"}}, "O1D")
    (u,) = lay.units
    assert (u.kind, u.label, u.slots[0].label) == ("generic", "HT-B", "HT-B")


def test_no_module_code_resolves_by_id_range_and_tray_count():
    lay = layout.build({"ams": {"ams": [unit(0), unit(128, 1)]}}, "O1D")
    assert [u.kind for u in lay.units] == ["ams", "ams_ht"]
    lay = layout.build({"ams": {"ams": [unit(0)]}}, "A1")         # AMS Lite by printer model
    assert lay.units[0].kind == "ams_lite"


def test_unknown_model_is_generic_and_says_so():
    rep = {"ams": {"ams": [unit(0)]}, "vt_tray": ext(254, "PLA")}
    lay = layout.build(rep, "ZZ9")
    assert [u.label for u in lay.units] == ["A", "Ext"]
    assert any("ZZ9" in n for n in lay.notes)


def test_single_external_printer_keeps_ext():
    for rep in ({"vt_tray": ext(254, "PLA")}, {"vir_slot": [ext(254, "PLA")]}, {"vt_tray": ext(255)}):
        (u,) = layout.build(rep, "P1S").units
        assert (u.label, u.kind, u.slots[0].label, u.slots[0].tray_id) == ("Ext", "ext", "Ext", 0)
    assert layout.build({}, "P1S").units == []


def test_two_externals_on_h2d_from_vir_slot_and_vt_tray():
    lay = layout.build({"vir_slot": [ext(255), ext(254)]}, "O1D")
    assert [(u.ams_id, u.label) for u in lay.units] == [(254, "Ext-L"), (255, "Ext-R")]
    # vt_tray only (older firmware): one holder; both present: listed once
    assert [u.label for u in layout.build({"vt_tray": ext(254)}, "O1D").units] == ["Ext-L"]
    lay = layout.build({"vt_tray": ext(254), "vir_slot": [ext(254), ext(255)]}, "O1D")
    assert [u.label for u in lay.units] == ["Ext-L", "Ext-R"]
    # two holders on a printer the file knows with one (or not at all): still unique labels
    labs = [u.label for u in layout.build({"vir_slot": [ext(254), ext(255)]}, "P1S").units]
    assert len(set(labs)) == 2 and "Ext" in labs


def test_tray_now_marks_the_active_external():
    rep = {"ams": {"ams": [unit(0)], "tray_now": "254"}, "vt_tray": ext(254, "PLA")}
    s = status.summarize(rep, [])
    assert s["ams"][-1]["slots"][0]["active"] is True
    assert status.tray_now_tag(254) == "254:0" and status.tray_now_tag(255) is None


def test_status_and_ams_share_the_builder():
    rep = big_report()
    st = status.summarize(rep, [], model="O1D")
    us = ams.units(rep, "O1D")
    assert [s["label"] for u in st["ams"] for s in u["slots"]] == [s.label for u in us for s in u.slots]
    assert [u["kind"] for u in st["ams"]] == [u.kind for u in us]
    u0 = st["ams"][0]
    assert u0["type_name"] == "AMS" and u0["slots"][0]["say"] == ["a", "1"]
    assert u0["slots"][0]["present"] is True and "reading" in u0["slots"][0]
    assert st["presence"] == "tray_type" and st["notes"]


def test_status_spool_join_for_new_labels():
    rep = big_report()
    sp = [{"id": 9, "location": "Lab – AMS Ext-R", "filament": {"name": "x"}},
          {"id": 10, "location": "Lab – AMS HT-H", "filament": {"name": "y"}}]
    st = status.summarize(rep, sp, printer_name="Lab", model="O1D")
    got = {s["label"]: (s["spool"] or {}).get("id") for u in st["ams"] for s in u["slots"]}
    assert got["Ext-R"] == 9 and got["HT-H"] == 10


def test_raw_trays_include_every_external():
    rep = big_report()
    rep["vt_tray"] = ext(254, "PETG")
    t = layout.raw_trays(rep)
    assert t[(254, 0)]["tray_type"] == "TPU"               # vir_slot wins over vt_tray for the same id
    assert (255, 0) in t and (15, 3) in t and (135, 0) in t


def test_fingerprint_ignores_contents_and_unresolved_types():
    rep = big_report()
    a = layout.build(rep, "O1D").fingerprint
    rep2 = json.loads(json.dumps(rep))
    rep2["ams"]["ams"][0]["tray"][0]["tray_color"] = "00FF00FF"
    assert layout.same_layout(a, layout.build(rep2, "O1D").fingerprint)
    # a module code arriving later does not count as a change
    rep2[layout.MODULES] = {"0": "N3F05"}
    b = layout.build(rep2, "O1D").fingerprint
    assert layout.same_layout(a, b)
    # a unit added or removed does
    rep3 = json.loads(json.dumps(rep))
    rep3["ams"]["ams"].append(unit(16))
    assert not layout.same_layout(a, layout.build(rep3, "O1D").fingerprint)
    # a different module on the same id, both known by code, does
    rep4 = json.loads(json.dumps(rep2))
    rep4[layout.MODULES] = {"0": "Z9Q01"}
    assert not layout.same_layout(b, layout.build(rep4, "O1D").fingerprint)
    assert layout.same_layout(None, None) and not layout.same_layout(None, a)
    assert json.loads(json.dumps(a)) == a                  # stored as plain JSON in slotmap.json


def test_label_for_without_a_report():
    assert layout.label_for(0, 3) == "A4"
    assert layout.label_for(129, 0) == "HT-B"
    assert layout.label_for(254, 0, "O1D") == "Ext-L"
    assert layout.label_for(254, 0, "P1S") == "Ext"
    assert layout.label_for(40, 1) == "AO2"


def test_default_global_routes_through_the_first_numbering_scheme():
    assert ams.default_global(1, 3) == 7 and ams.default_global(129, 0) == 129      # no model: legacy
    assert ams.default_global(1, 3, "P1S") == 7
    assert ams.default_global(1, 3, "O1D") == (1 << 8) | 3                         # H2D: shift8 first
    assert ams.default_global(129, 0, "O1D") == 129 << 8


def test_status_legacy_label_helpers_have_no_limit():
    assert status.unit_label(40) == ("AO", "ams")
    assert status.unit_label(160) == ("HT-AG", "ams_ht")


def test_garbage_never_crashes():
    for rep in ({}, {"ams": "x"}, {"ams": {"ams": [{"id": "x"}, {"id": "-1"}, {"id": "3", "tray": "no"}]}},
                {"vir_slot": "x"}, {"vir_slot": [{"id": "abc"}, 5]}, {"vt_tray": []},
                {"ams": {"ams": [unit(0)], "tray_exist_bits": "zz"}}, {layout.MODULES: "x", "ams": {"ams": [unit(0)]}}):
        lay = layout.build(rep, "O1D")
        assert isinstance(lay.units, list)
        status.summarize(rep, [], model="O1D")


@pytest.mark.parametrize("model", ["O1D", "P1S", None, "nope"])
def test_h2d_fixture_every_model(model):
    rep = json.loads((DATA / "h2d_pushall.json").read_text())["print"]
    lay = layout.build(rep, model)
    assert labels(lay) == ["A1", "A2", "A3", "A4", "HT-A"]
    assert hardware.load().model(model).known == (model in ("O1D", "P1S"))


def test_usage_guess_label_uses_the_first_scheme_and_unlimited_labels():
    from filament_kit.bridge import usage
    assert usage._guess_label(6) == "B3" and usage._guess_label(129) == "HT-B"       # no model: legacy
    assert usage._guess_label(254) == "Ext" and usage._guess_label(255) is None
    assert usage._guess_label(4 * 30 + 1) == "AE2"                                   # unit 30: no 26 limit
    assert usage._guess_label((1 << 8) | 2, "O1D") == "B3"                          # H2D: shift8 first
    assert usage._guess_label(129 << 8, "O1D") == "HT-B"
    assert usage._guess_label(254 << 8, "O1D") == "Ext-L" and usage._guess_label(255 << 8, "O1D") == "Ext-R"
