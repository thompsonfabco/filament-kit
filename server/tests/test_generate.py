import json
import shutil
from pathlib import Path

import pytest

from filament_kit import library
from filament_kit.profiles import bbl, generate as G, inapp, lines

LIB = Path(__file__).parent / "data" / "library"
STD, HF = "Direct Drive Standard", "Direct Drive High Flow"
H2D, P1S = "Bambu Lab H2D", "Bambu Lab P1S"
MODELS = ["O1D", "C12"]
NOW = 1_800_000_000.0


def cp(printer, *nozzles):
    return [f"{printer} {n} nozzle" for n in nozzles]


def presets() -> dict:
    return {
        "fdm_filament_pla": {
            "filament_type": ["PLA"], "filament_vendor": ["Generic"], "nozzle_temperature": ["220"],
            "nozzle_temperature_initial_layer": ["220"], "nozzle_temperature_range_low": ["190"],
            "nozzle_temperature_range_high": ["240"], "temperature_vitrification": ["45"],
            "filament_density": ["1.24"], "filament_flow_ratio": ["0.98"], "filament_wipe_distance": ["nil"],
            "chamber_temperatures": ["60"], "hot_plate_temp": ["55"], "version": "2.8.0.6",
            "filament_notes": "parent notes"},
        "fdm_filament_petg": {
            "inherits": "fdm_filament_pla", "filament_type": ["PETG"], "nozzle_temperature": ["250"],
            "nozzle_temperature_initial_layer": ["250"], "nozzle_temperature_range_low": ["230"],
            "nozzle_temperature_range_high": ["270"], "temperature_vitrification": ["70"]},
        "Bambu PLA Tough+ @base": {"inherits": "fdm_filament_pla", "filament_vendor": ["Bambu Lab"],
                                   "filament_id": "GFA09", "instantiation": "false"},
        "Bambu PLA Tough+ @BBL H2D": {
            "inherits": "Bambu PLA Tough+ @base", "instantiation": "true", "setting_id": "GFSA09_01",
            "type": "filament", "description": "x", "filament_extruder_variant": [STD, HF],
            "nozzle_temperature": ["220", "230"], "nozzle_temperature_initial_layer": ["220", "230"],
            "filament_flow_ratio": ["0.98", "nil"], "compatible_printers": cp(H2D, "0.4", "0.6", "0.8")},
        "Bambu PLA Tough+ @BBL H2D 0.2 nozzle": {
            "inherits": "Bambu PLA Tough+ @BBL H2D", "instantiation": "true",
            "compatible_printers": cp(H2D, "0.2")},
        "Bambu PLA Tough+ @BBL P1S": {
            "inherits": "Bambu PLA Tough+ @base", "instantiation": "true", "compatible_printers": cp(P1S, "0.4")},
        "Generic PLA @BBL H2D": {
            "inherits": "fdm_filament_pla", "instantiation": "true", "filament_id": "GFL99",
            "filament_extruder_variant": [STD, HF], "nozzle_temperature": ["220", "230"],
            "nozzle_temperature_initial_layer": ["220", "230"], "compatible_printers": cp(H2D, "0.4", "0.6")},
        "Generic PLA-CF @BBL H2D": {
            "inherits": "fdm_filament_pla", "instantiation": "true", "filament_id": "GFL98",
            "filament_type": ["PLA-CF"], "compatible_printers": cp(H2D, "0.2", "0.4", "0.6", "0.8")},
        "Generic PETG-CF @BBL H2D": {
            "inherits": "fdm_filament_petg", "instantiation": "true", "filament_id": "GFG98",
            "filament_type": ["PETG-CF"], "compatible_printers": cp(H2D, "0.4")},
        "Generic PETG @BBL H2D": {   # gated only by a condition: never a build parent
            "inherits": "fdm_filament_petg", "instantiation": "true", "filament_id": "GFG99",
            "compatible_printers": [], "compatible_printers_condition": "printer_model == \"H2D\""},
    }


def make_lib(*local) -> library.Library:
    idx = json.loads((LIB / "index.json").read_text(encoding="utf-8"))
    return library.Library(LIB, idx, "bundled", list(local))


def local(vendor, product, material, parent=None, fields=None, ranges=None) -> dict:
    e = {"schema_version": 1, "vendor": vendor, "product": product, "material": material,
         "fields": fields or {}}
    if parent:
        e["bambu_parent"] = parent
    if ranges:
        e["published_ranges"] = ranges
    return e


def fil(fid, name, vendor="SUNLU", material="PLA", **kw) -> dict:
    f = {"id": fid, "name": name, "material": material, "vendor": {"id": 1, "name": vendor}, "extra": {},
         "density": 1.24}
    f.update(kw)
    return f


SUNLU = [fil(17, "PLA+ 2.0 Grey"), fil(3, "PLA+ 2.0 Red")]


def build(tmp_path, filaments, *, lib=None, store_presets=None, line_set=None, live=None, snapshot=None,
          deleted_before=(), restore=False, out="out", models=MODELS):
    store = bbl.Store(store_presets or presets())
    return G.build_all(filaments=filaments, models=models, store=store, library=lib or make_lib(),
                       lines=line_set if line_set is not None else {}, live=live, snapshot=snapshot,
                       deleted_before=set(deleted_before), restore_deleted=restore, out_dir=tmp_path / out,
                       now=NOW)


def names(manifest):
    return sorted(p["name"] for p in manifest["presets"])


def read(tmp_path, name, out="out"):
    return json.loads((tmp_path / out / "base" / f"{name}.json").read_text(encoding="utf-8"))


def read_info(tmp_path, name, out="out"):
    text = (tmp_path / out / "base" / f"{name}.info").read_text(encoding="utf-8")
    return dict(line.split(" = ", 1) for line in text.splitlines())


def sunlu(printer, nozzle):
    return f"SUNLU PLA+ 2.0 @{printer} {nozzle} nozzle"


# ---------- the brief's tests ----------

def test_one_preset_per_line_printer_nozzle(tmp_path):
    manifest, ls = build(tmp_path, SUNLU)
    assert names(manifest) == sorted([sunlu(H2D, n) for n in ("0.2", "0.4", "0.6", "0.8")] + [sunlu(P1S, "0.4")])
    assert G.preset_name(ls["sunlu--pla-plus-2-0"], H2D, "0.4") == sunlu(H2D, "0.4")
    row = next(p for p in manifest["presets"] if p["name"] == sunlu(H2D, "0.4"))
    assert row["printer"] == H2D and row["nozzle"] == "0.4" and row["line_id"] == "sunlu--pla-plus-2-0"
    assert row["spoolman_ids"] == [3, 17] and row["filament_type"] == "PLA"
    assert manifest["lines"]["sunlu--pla-plus-2-0"] == {
        "filament_id": ls["sunlu--pla-plus-2-0"].filament_id, "spoolman_ids": [3, 17], "vendor": "SUNLU",
        "product": "PLA+ 2.0"}
    assert manifest["library_version"] == 3
    cfg = read(tmp_path, sunlu(H2D, "0.4"))
    assert cfg["compatible_printers"] == [f"{H2D} 0.4 nozzle"]
    assert cfg["filament_vendor"] == ["SUNLU"] and cfg["filament_settings_id"] == [sunlu(H2D, "0.4")]
    assert cfg["from"] == "User" and cfg["version"] == "2.8.0.6" and cfg["compatible_prints"] == []
    assert cfg["compatible_printers_condition"] == "" and cfg["compatible_prints_condition"] == ""
    for k in ("type", "instantiation", "setting_id", "description"):
        assert k not in cfg


def test_notes_end_with_spoolman_ids(tmp_path):
    build(tmp_path, SUNLU)
    notes = read(tmp_path, sunlu(H2D, "0.4"))["filament_notes"].splitlines()
    assert notes[-1] == "Spoolman filament ids: 3, 17"
    assert notes[0].startswith("One profile for every SUNLU PLA+ 2.0 colour in Spoolman")
    assert any(line.startswith("Manufacturer specs: nozzle 205-245 C") for line in notes)


def test_priority_spoolman_over_library_over_parent(tmp_path):
    lib = make_lib(local("Acme", "PLA", "PLA", "Bambu PLA Tough+",
                         {"nozzle_temperature_range_low": ["200"], "nozzle_temperature_range_high": ["220"]}))
    manifest, _ = build(tmp_path, [fil(5, "PLA Blue", vendor="Acme", settings_extruder_temp=210)], lib=lib)
    cfg = read(tmp_path, f"Acme PLA @{H2D} 0.4 nozzle")
    assert cfg["nozzle_temperature"] == ["210", "220"]
    assert cfg["nozzle_temperature_range_low"] == ["200"] and cfg["nozzle_temperature_range_high"] == ["220"]


def test_never_generic_id_and_no_nil(tmp_path):
    fs = SUNLU + [fil(8, "PLA-CF Black", vendor="Generic", material="PLA-CF")]
    manifest, ls = build(tmp_path, fs)
    files = sorted((tmp_path / "out" / "base").glob("*.json"))
    assert len(files) == len(manifest["presets"]) > 5
    for p in files:
        text = p.read_text(encoding="utf-8")
        cfg = json.loads(text)
        assert G.ID_RE.fullmatch(cfg["filament_id"]), p.name
        assert '"nil"' not in text, p.name
        assert cfg["inherits"] == ""
    assert {p["filament_id"] for p in manifest["presets"]} == {l.filament_id for l in ls.values()}
    # the parent's ["0.98", "nil"] list is filled, the all-"nil" key is dropped
    cfg = read(tmp_path, sunlu(H2D, "0.4"))
    assert cfg["filament_flow_ratio"] == ["0.98", "0.98"]
    assert "filament_wipe_distance" not in cfg


def test_temps_always_present(tmp_path):
    manifest, _ = build(tmp_path, SUNLU + [fil(8, "PLA-CF Black", vendor="Generic", material="PLA-CF")])
    assert manifest["presets"]
    for p in manifest["presets"]:
        assert isinstance(p["nozzle_temp_min"], int) and isinstance(p["nozzle_temp_max"], int)
        assert p["nozzle_temp_min"] <= p["nozzle_temp_max"]
    row = next(p for p in manifest["presets"] if p["name"] == sunlu(H2D, "0.4"))
    assert (row["nozzle_temp_min"], row["nozzle_temp_max"]) == (205, 245)


def test_line_without_parent_is_skipped_with_problem(tmp_path):
    manifest, _ = build(tmp_path, SUNLU + [fil(9, "PEEK Natural", vendor="Acme", material="PEEK")])
    assert any("acme--peek-natural" in p for p in manifest["problems"])
    assert not any(p["line_id"] == "acme--peek-natural" for p in manifest["presets"])
    assert len(manifest["presets"]) == 5


def test_odd_spoolman_values_do_not_break_build(tmp_path):
    fs = [fil(1, "PLA+ 2.0 A", settings_extruder_temp=None, density=None),
          fil(2, "PLA+ 2.0 B", settings_extruder_temp="0", density=None, settings_bed_temp="abc"),
          fil(4, "PLA+ 2.0 C", settings_extruder_temp="abc", density=None, extra={"line": "{not json"}),
          fil(6, "PLA+ 2.0 D", density=None, extra={"line": "null", "nozzle_range": "\"oops\""})]
    manifest, _ = build(tmp_path, fs)
    assert sunlu(H2D, "0.4") in names(manifest)
    cfg = read(tmp_path, sunlu(H2D, "0.4"))
    assert cfg["nozzle_temperature"] == ["220", "230"]          # the parent's, inside the library 205-245
    assert cfg["filament_density"] == ["1.21"]                  # the library's
    assert cfg["hot_plate_temp"] == ["55"]


def test_abrasive_skips_02(tmp_path):
    manifest, _ = build(tmp_path, [fil(8, "PLA-CF Black", vendor="Generic", material="PLA-CF")])
    got = names(manifest)
    assert got == sorted(f"Generic PLA-CF Black @{H2D} {n} nozzle" for n in ("0.4", "0.6", "0.8"))
    cfg = read(tmp_path, got[0])
    assert cfg["required_nozzle_HRC"] == ["40"] and cfg["filament_type"] == ["PLA-CF"]


def _install(tmp_path, out="out"):
    """A snapshot of the build in `out` and a live folder with the same presets."""
    snap, live = tmp_path / "snap", tmp_path / "live"
    for d in (snap, live):
        shutil.copytree(tmp_path / out / "base", d / "base")
    return snap, G.Live(live, "1234567890")


EIGHT = SUNLU + [fil(8, "PLA-CF Black", vendor="Generic", material="PLA-CF")]


def test_deleted_in_app_left_out_and_reset_rebuilds(tmp_path):
    first, ls = build(tmp_path, EIGHT)
    assert len(first["presets"]) == 8
    snap, live = _install(tmp_path)
    gone = sunlu(H2D, "0.6")
    (live.root / "base" / f"{gone}.json").unlink()
    second, ls2 = build(tmp_path, EIGHT, line_set=ls, live=live, snapshot=snap, out="o2")
    assert gone not in names(second) and len(second["presets"]) == 7
    assert second["deleted"] == [gone]
    assert not (tmp_path / "o2" / "base" / f"{gone}.json").exists()
    # stays deleted while listed in deleted_before, comes back on restore
    third, _ = build(tmp_path, EIGHT, line_set=ls2, live=live, snapshot=snap, deleted_before={gone.casefold()},
                     out="o3")
    assert gone not in names(third)
    restored, _ = build(tmp_path, EIGHT, line_set=ls2, live=live, snapshot=snap, deleted_before={gone},
                        restore=True, out="o4")
    assert len(restored["presets"]) == 8 and restored["deleted"] == []
    # three of eight gone at once: an app reset, all rebuilt
    for n in (sunlu(H2D, "0.4"), sunlu(H2D, "0.8")):
        (live.root / "base" / f"{n}.json").unlink()
    reset, _ = build(tmp_path, EIGHT, line_set=ls2, live=live, snapshot=snap, out="o5")
    assert len(reset["presets"]) == 8 and reset["deleted"] == []


def test_in_app_edit_kept_and_reported(tmp_path):
    _, ls = build(tmp_path, SUNLU)
    snap, live = _install(tmp_path)
    name = sunlu(H2D, "0.4")
    p = live.root / "base" / f"{name}.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert cfg["filament_flow_ratio"] == ["0.98", "0.98"]
    cfg["filament_flow_ratio"] = ["0.95", "0.98"]
    cfg["filament_notes"] = cfg["filament_notes"].replace("Spoolman filament ids", "dry first\nSpoolman filament ids")
    p.write_text(json.dumps(cfg), encoding="utf-8")
    manifest, _ = build(tmp_path, SUNLU, line_set=ls, live=live, snapshot=snap, out="o2")
    new = read(tmp_path, name, "o2")
    assert new["filament_flow_ratio"] == ["0.95", "0.98"]
    assert any(name in e and "filament_flow_ratio" in e for e in manifest["edits"])
    notes = new["filament_notes"].splitlines()
    assert notes[-1] == "Spoolman filament ids: 3, 17"
    assert notes[-3:-1] == [inapp.MARK, "dry first"]
    assert read(tmp_path, sunlu(H2D, "0.6"), "o2")["filament_flow_ratio"] == ["0.98", "0.98"]


def test_cloud_setting_id_reused(tmp_path):
    _, ls = build(tmp_path, SUNLU)
    snap, live = _install(tmp_path)
    name = sunlu(H2D, "0.4")
    (live.root / "base" / f"{name}.info").write_text(
        "sync_info = \nuser_id = 1234567890\nsetting_id = PFUS123\nbase_id = GFSA09_01\nupdated_time = 1\n",
        encoding="utf-8")
    build(tmp_path, SUNLU, line_set=ls, live=live, snapshot=snap, out="o2")
    info = read_info(tmp_path, name, "o2")
    assert info["setting_id"] == "PFUS123" and info["sync_info"] == "update" and info["base_id"] == "GFSA09_01"
    assert info["user_id"] == "1234567890" and info["updated_time"] == str(int(NOW))
    other = read_info(tmp_path, sunlu(H2D, "0.6"), "o2")
    assert other["setting_id"] == "" and other["sync_info"] == ""
    assert read_info(tmp_path, name)["user_id"] == ""               # first build had no live upload


def test_chamber_only_h2d(tmp_path):
    lib = make_lib(local("SUNLU", "PLA+ 2.0", "PLA", "Bambu PLA Tough+", ranges={"chamber_temperatures": "25-45"}))
    manifest, _ = build(tmp_path, SUNLU, lib=lib)
    assert read(tmp_path, sunlu(H2D, "0.4"))["chamber_temperatures"] == ["45"]
    assert read(tmp_path, sunlu(P1S, "0.4"))["chamber_temperatures"] == ["60"]
    assert any("chamber_temperatures 60 -> 45" in c for c in manifest["clamps"])


# ---------- review notes ----------

def test_pipeline_spoolman_beats_library_and_hardened_without_entry(tmp_path):
    fs = [fil(3, "PLA+ 2.0 Red", density=1.25, extra={"nozzle_range": json.dumps("200-230")}),
          fil(11, "PETG-CF Black", vendor="Acme", material="PETG-CF")]
    manifest, ls = build(tmp_path, fs)
    cfg = read(tmp_path, sunlu(H2D, "0.4"))
    assert cfg["filament_density"] == ["1.25"]                 # library says 1.21
    assert cfg["nozzle_temperature_range_low"] == ["200"] and cfg["nozzle_temperature_range_high"] == ["230"]
    pcf = read(tmp_path, f"Acme PETG-CF Black @{H2D} 0.4 nozzle")
    assert pcf["required_nozzle_HRC"] == ["40"]
    assert ls["acme--petg-cf-black"].parent_source == "material"


def test_condition_gated_parent_is_a_visible_problem(tmp_path):
    manifest, _ = build(tmp_path, SUNLU + [fil(12, "PETG Clear", vendor="Acme", material="PETG")])
    assert any("acme--petg-clear" in p for p in manifest["problems"])
    assert len(manifest["presets"]) == 5


def test_user_parent_without_system_preset_for_a_printer_is_reported(tmp_path):
    ls = lines.LineSet()
    used = set()
    lines.ensure(ls, "Acme", "Odd", "PLA", bambu_parent="Generic PLA", library=make_lib(), store=None,
                 used_fids=used)
    manifest, _ = build(tmp_path, [fil(13, "Odd", vendor="Acme", extra={"line": json.dumps("Odd")})], line_set=ls)
    assert names(manifest) == [f"Acme Odd @{H2D} 0.4 nozzle", f"Acme Odd @{H2D} 0.6 nozzle"]
    assert any("acme--odd" in p and P1S in p for p in manifest["problems"])


def test_rechoose_at_build_time(tmp_path):
    ls = lines.LineSet()
    line = lines.ensure(ls, "Acme", "Basic", "PLA", bambu_parent=None, library=make_lib(), store=None,
                        used_fids=set())
    line.bambu_parent, line.parent_source = "Generic PLA-OLD", "material"   # proposed with no store
    manifest, out = build(tmp_path, [fil(14, "Basic", vendor="Acme", extra={"line": json.dumps("Basic")})],
                          line_set=ls)
    assert out["acme--basic"].bambu_parent == "Generic PLA"
    assert len(manifest["presets"]) == 2


def test_parent_nil_through_clamped_list_and_vitrification_untouched(tmp_path):
    ps = presets()
    ps["Bambu PLA Tough+ @BBL H2D"]["nozzle_temperature"] = ["260", "nil"]   # clamp 260 -> 245, nil stays nil
    manifest, _ = build(tmp_path, SUNLU, store_presets=ps)
    cfg = read(tmp_path, sunlu(H2D, "0.4"))
    assert "nil" not in cfg["nozzle_temperature"]
    assert cfg["temperature_vitrification"] == ["45"]


def test_inapp_nil_or_vitrification_never_written(tmp_path):
    _, ls = build(tmp_path, SUNLU)
    snap, live = _install(tmp_path)
    name = sunlu(H2D, "0.4")
    p = live.root / "base" / f"{name}.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["filament_flow_ratio"] = ["0.95", "nil"]
    cfg["temperature_vitrification"] = ["60"]
    p.write_text(json.dumps(cfg), encoding="utf-8")
    manifest, _ = build(tmp_path, SUNLU, line_set=ls, live=live, snapshot=snap, out="o2")
    new = read(tmp_path, name, "o2")
    assert new["filament_flow_ratio"] == ["0.95", "0.95"]
    assert new["temperature_vitrification"] == ["45"]
    assert any("temperature_vitrification" in e for e in manifest["edits"])


def test_adopts_existing_wizard_filament_id(tmp_path):
    live_root = tmp_path / "live"
    (live_root / "base").mkdir(parents=True)
    name = sunlu(H2D, "0.4")
    (live_root / "base" / f"{name}.json").write_text(json.dumps({"name": name, "filament_id": "Pabc1234"}),
                                                     encoding="utf-8")
    manifest, ls = build(tmp_path, SUNLU, live=G.Live(live_root, "u1"))
    assert ls["sunlu--pla-plus-2-0"].filament_id == "Pabc1234"
    assert all(p["filament_id"] == "Pabc1234" for p in manifest["presets"])
    assert any("Pabc1234" in e for e in manifest["edits"])


def test_stale_lists_snapshot_names_no_longer_built(tmp_path):
    _, ls = build(tmp_path, EIGHT)
    snap, live = _install(tmp_path)
    manifest, _ = build(tmp_path, SUNLU, line_set=ls, live=live, snapshot=snap, out="o2")
    assert manifest["stale"] == sorted(f"Generic PLA-CF Black @{H2D} {n} nozzle" for n in ("0.4", "0.6", "0.8"))


def test_unsupported_nozzles_skipped(tmp_path):
    lib = make_lib(local("SUNLU", "PLA+ 2.0", "PLA", "Bambu PLA Tough+", ranges={"_not_supported": "0.2, 0.8"}))
    manifest, _ = build(tmp_path, SUNLU, lib=lib)
    assert names(manifest) == sorted([sunlu(H2D, "0.4"), sunlu(H2D, "0.6"), sunlu(P1S, "0.4")])


def test_check_preset():
    parent = {"temperature_vitrification": ["45"]}
    good = {"name": "A B @Bambu Lab H2D 0.4 nozzle", "filament_id": "P0123abc", "inherits": "",
            "nozzle_temperature_range_low": ["190"], "nozzle_temperature_range_high": ["230"],
            "filament_notes": "x\nSpoolman filament ids: 1", "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"],
            "temperature_vitrification": ["45"]}
    assert G.check_preset(good, parent) == []
    for bad in ({"filament_id": "GFL99"}, {"inherits": "Generic PLA"}, {"nozzle_temperature_range_low": ["x"]},
                {"nozzle_temperature_range_high": None}, {"filament_notes": "Spoolman filament ids: 1\nx"},
                {"compatible_printers": ["a", "b"]}, {"temperature_vitrification": ["60"]},
                {"name": "A/B @Bambu Lab H2D 0.4 nozzle"}, {"hot_plate_temp": ["nil"]}):
        cfg = {**good, **bad}
        if bad.get("nozzle_temperature_range_high", 1) is None:
            del cfg["nozzle_temperature_range_high"]
        assert G.check_preset(cfg, parent), bad


def test_live_reads_presets_and_info(tmp_path):
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "X.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "base" / "X.info").write_text("setting_id = PF1\nsync_info = \n", encoding="utf-8")
    (tmp_path / "base" / "Y.json").write_text("{bad", encoding="utf-8")
    live = G.Live(tmp_path, "u")
    assert live.names() == {"X", "Y"}
    assert live.preset("X") == ({"a": 1}, {"setting_id": "PF1", "sync_info": ""})
    assert live.preset("Y") == (None, {})
    assert live.preset("Z") == (None, {})
