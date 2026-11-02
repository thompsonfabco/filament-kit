"""Task 6: the Orca Slicer target of the generator (`orca/` beside `base/`).

Names match filament-ops gen.py so the owner's existing Orca presets are adopted: `<line> @SV08 MAX <n>` for a
configured (non-Bambu) printer, `<line> @H2D <n>` for a Bambu printer when `presets_orca` is on.
"""
import copy
import json
from pathlib import Path

import pytest

from filament_kit.profiles import bbl, generate as G, inapp, lines, orca

import test_generate as TG

ORCA_INDEX = Path(__file__).parent / "data" / "orca" / "system" / "OrcaFilamentLibrary" / "index.json"
STD, HF = TG.STD, TG.HF
SV08 = {"name": "Sovol SV08 MAX", "slicer": "orca", "nozzles": ["0.4", "0.6", "1.0"],
        "compatible_printers": {"0.4": "Sovol SV08 MAX", "0.6": "Sovol SV08 MAX 0.6",
                                "1.0": "Sovol SV08 MAX 1.0"}}
OUSER = "f790a1c6-01c4-42b9-97ab-bd37fc89c553"
LID = "sunlu--pla-plus-2-0"


def orca_bbl() -> dict:
    """Orca's BBL system presets: the Bambu Studio fixture with setting ids and G-code (Orca's carry both)."""
    p = copy.deepcopy(TG.presets())
    p["Bambu PLA Tough+ @BBL H2D"]["setting_id"] = "GFSA09_01"
    p["Bambu PLA Tough+ @BBL H2D 0.2 nozzle"]["setting_id"] = "GFSA09_02"
    p["Bambu PLA Tough+ @BBL P1S"]["setting_id"] = "GFSA09_03"
    p["fdm_filament_pla"]["filament_start_gcode"] = ["; filament start gcode\n"]
    return p


def ostore(bbl_presets=None) -> orca.OrcaStore:
    library, problems = orca.OrcaStore._parse_index(ORCA_INDEX.read_bytes())
    assert problems == []
    return orca.OrcaStore(bbl.Store(bbl_presets or orca_bbl()), library)


def target(tmp_path, *, store="default", slicer=(SV08,), presets_orca=False, models=TG.MODELS, live=None,
           snapshot=None, partial=None, deleted_before=(), owner_edits=None, bambu_nozzles=None):
    printers, problems = G.orca_printers(models if presets_orca else [], list(slicer), bambu_nozzles=bambu_nozzles)
    return G.OrcaTarget(store=ostore() if store == "default" else store, printers=printers, problems=problems,
                        live=live, snapshot=snapshot, partial=partial, deleted_before=set(deleted_before),
                        owner_edits=owner_edits)


def build(tmp_path, filaments=TG.SUNLU, *, t=None, line_set=None, out="out", restore=False, **kw):
    t = t if t is not None else target(tmp_path, **kw)
    return G.build_all(filaments=filaments, models=TG.MODELS, store=bbl.Store(TG.presets()), library=TG.make_lib(),
                       lines=line_set if line_set is not None else {}, live=None, snapshot=None,
                       deleted_before=set(), restore_deleted=restore, out_dir=tmp_path / out, now=TG.NOW,
                       orca=t)


def oread(tmp_path, name, out="out"):
    return json.loads((tmp_path / out / "orca" / f"{name}.json").read_text(encoding="utf-8"))


def oinfo(tmp_path, name, out="out"):
    text = (tmp_path / out / "orca" / f"{name}.info").read_text(encoding="utf-8")
    return dict(line.split(" = ", 1) if " = " in line else (line.rstrip(" ="), "") for line in text.splitlines())


def onames(manifest):
    return sorted(p["name"] for p in manifest["presets"] if p.get("target") == "orca")


def sv08(n):
    return f"SUNLU PLA+ 2.0 @SV08 MAX {n}"


def h2d(n):
    return f"SUNLU PLA+ 2.0 @H2D {n}"


def no_nil(v):
    return not inapp.norm(v) == "nil" and not (isinstance(v, list) and "nil" in v)


def orca_live(tmp_path, files: dict, user=OUSER) -> G.Live:
    root = tmp_path / "olive"
    root.mkdir(exist_ok=True)
    for n, (cfg, info) in files.items():
        (root / f"{n}.json").write_text(json.dumps(cfg), encoding="utf-8")
        if info is not None:
            (root / f"{n}.info").write_text(info, encoding="utf-8")
    return G.Live(root, user, sub="")


# ---------- configured (non-Bambu) printers ----------

def test_sv08_presets_match_ops_names_and_inherit_the_library_parent(tmp_path):
    m, ls = build(tmp_path)
    assert onames(m) == [sv08("0.4"), sv08("0.6"), sv08("1.0")]
    assert ls[LID].orca_parent == "SUNLU PLA+ 2.0" and ls[LID].orca_parent_source == "brand"
    cfg = oread(tmp_path, sv08("0.4"))
    assert cfg["inherits"] == "SUNLU PLA+ 2.0 @System"
    assert cfg["compatible_printers"] == ["Sovol SV08 MAX"]
    assert oread(tmp_path, sv08("0.6"))["compatible_printers"] == ["Sovol SV08 MAX 0.6"]
    assert cfg["filament_extruder_variant"] == [STD]
    assert cfg["name"] == sv08("0.4") and cfg["filament_settings_id"] == [sv08("0.4")] and cfg["from"] == "User"
    assert cfg["filament_vendor"] == ["SUNLU"] and cfg["filament_type"] == ["PLA"]
    assert cfg["version"] == "2.4.0.16"
    assert cfg["filament_density"] == ["1.24"]
    notes = cfg["filament_notes"].splitlines()
    assert notes[0].startswith("One profile for every SUNLU PLA+ 2.0 colour") and notes[-1] == \
        "Spoolman filament ids: 3, 17"
    assert "filament_id" not in cfg                    # Orca presets keep the system filament id
    assert not [k for k in cfg if "gcode" in k.lower()]
    assert all(no_nil(v) for v in cfg.values())
    info = oinfo(tmp_path, sv08("0.4"))
    assert info["base_id"] == "8EZyKHm5JquwOtfP" and info["setting_id"] == "" and info["sync_info"] == ""
    assert info["updated_time"] == str(int(TG.NOW))
    row = next(p for p in m["presets"] if p["name"] == sv08("0.4"))
    assert row["target"] == "orca" and row["printer"] == "Sovol SV08 MAX" and row["nozzle"] == "0.4"
    assert row["line_id"] == LID and row["spoolman_ids"] == [3, 17] and row["filament_type"] == "PLA"
    assert all(p["target"] == "bambu_studio" for p in m["presets"] if not p["name"].startswith("SUNLU PLA+ 2.0 @SV"))
    assert m["orca_inapp"] == {} and m["orca_restored"] == [] and m["orca_deleted"] == []


def test_default_compatible_printer_and_label(tmp_path):
    m, _ = build(tmp_path, slicer=({"name": "Voron Trident", "nozzles": ["0.4"]},))
    assert onames(m) == ["SUNLU PLA+ 2.0 @Trident 0.4"]
    cfg = oread(tmp_path, "SUNLU PLA+ 2.0 @Trident 0.4")
    assert cfg["compatible_printers"] == ["Voron Trident 0.4 nozzle"]
    m, _ = build(tmp_path, slicer=({"name": "Voron Trident", "label": "VT", "nozzles": ["0.4"]},), out="o2")
    assert onames(m) == ["SUNLU PLA+ 2.0 @VT 0.4"]


@pytest.mark.parametrize("bad", [{"nozzles": ["0.4"]}, {"name": "X", "nozzles": "0.4"},
                                 {"name": "X", "slicer": "cura", "nozzles": ["0.4"]},
                                 {"name": "X", "nozzles": ["big"]}, "Sovol",
                                 {"name": "X", "nozzles": ["0.4"], "compatible_printers": ["a"]}])
def test_bad_slicer_printer_entries_are_problems(tmp_path, bad):
    m, _ = build(tmp_path, slicer=(bad, SV08))
    assert onames(m) == [sv08("0.4"), sv08("0.6"), sv08("1.0")]
    assert any("slicer_printers" in p for p in m["problems"]), m["problems"]


def test_missing_orca_parent_is_a_problem_and_the_preset_is_skipped(tmp_path):
    ls = lines.LineSet()
    lines.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=TG.make_lib(), store=bbl.Store(TG.presets()),
                 used_fids=set())
    lines.set_parent(ls, LID, "Nope PLA", target="orca")
    m, _ = build(tmp_path, line_set=ls)
    assert onames(m) == []
    assert not (tmp_path / "out" / "orca").exists() or not list((tmp_path / "out" / "orca").iterdir())
    assert any(sv08("0.4") in p and "Nope PLA @System" in p for p in m["problems"]), m["problems"]
    assert [p for p in m["presets"] if p["target"] == "bambu_studio"]        # Bambu Studio goes on


def test_no_orca_store_is_one_problem_and_no_orca_presets(tmp_path):
    m, _ = build(tmp_path, t=target(tmp_path, store=None))
    assert onames(m) == []
    assert any("Orca Slicer system presets" in p for p in m["problems"])
    assert [p for p in m["presets"] if p["target"] == "bambu_studio"]


def test_rechoose_orca_at_build_time(tmp_path):
    """A line intake made before the Orca store was uploaded (static `Generic PLA`, source material) gets the
    store-backed brand parent; a user-set Orca parent is kept."""
    ls = lines.LineSet()
    line = lines.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=TG.make_lib(),
                        store=bbl.Store(TG.presets()), used_fids=set())
    assert (line.orca_parent, line.orca_parent_source) == ("Generic PLA", "material")
    _m, out = build(tmp_path, line_set=ls)
    assert (out[LID].orca_parent, out[LID].orca_parent_source) == ("SUNLU PLA+ 2.0", "brand")
    lines.set_parent(ls, LID, "Generic PLA", target="orca")
    _m, out = build(tmp_path, line_set=ls, out="o2")
    assert (out[LID].orca_parent, out[LID].orca_parent_source) == ("Generic PLA", "user")
    assert oread(tmp_path, sv08("0.4"), out="o2")["inherits"] == "Generic PLA @System"


# ---------- Bambu printers (presets_orca) ----------

def test_bambu_printers_get_orca_presets_inheriting_the_bbl_system_preset(tmp_path):
    m, _ = build(tmp_path, slicer=(), presets_orca=True, bambu_nozzles=["0.2", "0.4", "0.6", "0.8"])     # 0.2 only when asked for
    assert onames(m) == sorted([h2d(n) for n in ("0.2", "0.4", "0.6", "0.8")] + ["SUNLU PLA+ 2.0 @P1S 0.4"])
    cfg = oread(tmp_path, h2d("0.4"))
    assert cfg["inherits"] == "Bambu PLA Tough+ @BBL H2D"
    assert oread(tmp_path, h2d("0.2"))["inherits"] == "Bambu PLA Tough+ @BBL H2D 0.2 nozzle"
    assert cfg["compatible_printers"] == ["Bambu Lab H2D 0.4 nozzle"]
    assert cfg["filament_extruder_variant"] == [STD, HF]
    assert cfg["version"] == "2.8.0.6"                               # the parent's
    assert not [k for k in cfg if "gcode" in k.lower()]               # the parent has G-code: inherited, not written
    assert "filament_flow_ratio" not in cfg                            # equal to the parent's: inherited
    assert "temperature_vitrification" not in cfg
    assert all(no_nil(v) for v in cfg.values())
    assert oinfo(tmp_path, h2d("0.4"))["base_id"] == "GFSA09_01"
    assert oinfo(tmp_path, h2d("0.2"))["base_id"] == "GFSA09_02"
    row = next(p for p in m["presets"] if p["name"] == h2d("0.4"))
    assert row["printer"] == "Bambu Lab H2D" and row["target"] == "orca"
    assert row["nozzle_temp_min"] == 205 and row["nozzle_temp_max"] == 245   # library range on the merged view


def test_bambu_orca_parent_missing_for_a_nozzle_is_a_problem(tmp_path):
    p = orca_bbl()
    del p["Bambu PLA Tough+ @BBL H2D 0.2 nozzle"]
    p["Bambu PLA Tough+ @BBL H2D"]["compatible_printers"] = TG.cp(TG.H2D, "0.2", "0.4", "0.6", "0.8")
    m, _ = build(tmp_path, t=target(tmp_path, store=ostore(p), slicer=(), presets_orca=True,
                                       bambu_nozzles=["0.2", "0.4", "0.6", "0.8"]))
    assert h2d("0.2") in onames(m)
    p["Bambu PLA Tough+ @BBL H2D"]["inherits"] = "missing @base"           # the parent no longer resolves
    m, _ = build(tmp_path, t=target(tmp_path, store=ostore(p), slicer=(), presets_orca=True), out="o2")
    assert h2d("0.4") not in onames(m)
    assert any("Orca Slicer" in x and "Bambu PLA Tough+" in x for x in m["problems"]), m["problems"]


def test_orca_off_for_bambu_printers_by_default(tmp_path):
    m, _ = build(tmp_path)
    assert not [n for n in onames(m) if "@H2D" in n]


# ---------- adoption, edits, deletions ----------

def test_existing_orca_preset_is_adopted_with_its_ids(tmp_path):
    live = orca_live(tmp_path, {
        "sunlu pla+ 2.0 @SV08 MAX 0.4": ({"name": "sunlu pla+ 2.0 @SV08 MAX 0.4", "filament_id": "Pabc1234",
                                          "inherits": "Generic PLA @System"},
                                         "sync_info = \nuser_id = x\nsetting_id = PFUSabc\nbase_id = OLD\n")})
    m, _ = build(tmp_path, t=target(tmp_path, live=live))
    name = "sunlu pla+ 2.0 @SV08 MAX 0.4"                       # the live spelling (a twin would be a 2nd preset)
    assert name in onames(m) and sv08("0.4") not in onames(m)
    cfg = oread(tmp_path, name)
    assert cfg["name"] == name and cfg["filament_settings_id"] == [name] and cfg["filament_id"] == "Pabc1234"
    info = oinfo(tmp_path, name)
    assert info["setting_id"] == "PFUSabc" and info["sync_info"] == "update" and info["user_id"] == OUSER
    assert info["base_id"] == "8EZyKHm5JquwOtfP"


def test_orca_inapp_edits_are_carried_and_recorded_apart_from_bambu(tmp_path):
    m1, ls = build(tmp_path, out="b1")
    snap = tmp_path / "b1"
    (snap / "BUILD.json").write_text(json.dumps(m1), encoding="utf-8")
    cfg = oread(tmp_path, sv08("0.4"), out="b1")
    edited = dict(cfg, nozzle_temperature=["231"], filament_wipe_distance=["2", "nil"],
                  filament_notes=cfg["filament_notes"].replace("Spoolman filament ids", "dry first\nSpoolman filament ids"))
    files = {p.stem: (json.loads(p.read_text(encoding="utf-8")), None) for p in (snap / "orca").glob("*.json")}
    files[sv08("0.4")] = (edited, None)
    live = orca_live(tmp_path, files)
    m2, _ = build(tmp_path, line_set=ls, out="b2", t=target(tmp_path, live=live, snapshot=snap))
    assert m2["orca_inapp"] == {sv08("0.4"): {"nozzle_temperature": ["231"], "filament_wipe_distance": ["2", "nil"]}}
    assert m2["inapp"] == {}
    got = oread(tmp_path, sv08("0.4"), out="b2")
    assert got["nozzle_temperature"] == ["231"] and got["filament_wipe_distance"] == ["2", "2"]     # never nil
    notes = got["filament_notes"].splitlines()
    assert notes[-3:-1] == [inapp.MARK, "dry first"] and notes[-1].startswith("Spoolman filament ids:")


def test_orca_preset_deleted_in_the_app_stays_deleted_until_restored(tmp_path):
    five = ({**SV08, "nozzles": ["0.2", "0.4", "0.6", "0.8", "1.0"]},)    # one of five gone: not an app reset

    def target(tmp_path, **kw):
        return globals()["target"](tmp_path, slicer=five, **kw)

    m1, ls = build(tmp_path, out="b1", t=target(tmp_path))
    snap = tmp_path / "b1"
    (snap / "BUILD.json").write_text(json.dumps(m1), encoding="utf-8")
    files = {p.stem: (json.loads(p.read_text(encoding="utf-8")), None) for p in (snap / "orca").glob("*.json")
             if p.stem != sv08("1.0")}
    live = orca_live(tmp_path, files)
    m2, _ = build(tmp_path, line_set=ls, out="b2", t=target(tmp_path, live=live, snapshot=snap))
    assert sv08("1.0") not in onames(m2) and m2["orca_deleted"] == [sv08("1.0")]
    assert m2["deleted"] == []
    m3, _ = build(tmp_path, line_set=ls, out="b3", t=target(tmp_path, live=live, snapshot=snap,
                                                            deleted_before=m2["orca_deleted"]))
    assert sv08("1.0") not in onames(m3)
    m4, _ = build(tmp_path, line_set=ls, out="b4", restore=True,
                  t=target(tmp_path, live=live, snapshot=snap, deleted_before=m2["orca_deleted"]))
    assert sv08("1.0") in onames(m4) and m4["orca_restored"] == [sv08("1.0")] and m4["restored"] == []


def test_gcode_only_when_equal_to_the_live_value(tmp_path):
    """A recorded in-app G-code edit is written only while the live preset still holds that exact value."""
    m1, ls = build(tmp_path, out="b1")
    snap = tmp_path / "b1"
    m1["orca_inapp"] = {sv08("0.4"): {"filament_start_gcode": ["G28 ; mine\n"]},
                        sv08("0.6"): {"filament_start_gcode": ["G28 ; old\n"]}}
    (snap / "BUILD.json").write_text(json.dumps(m1), encoding="utf-8")
    files = {p.stem: (json.loads(p.read_text(encoding="utf-8")), None) for p in (snap / "orca").glob("*.json")}
    files[sv08("0.4")][0]["filament_start_gcode"] = ["G28 ; mine\n"]
    files[sv08("0.6")][0]["filament_start_gcode"] = ["G28 ; newer\n"]
    snapcfg = json.loads((snap / "orca" / f"{sv08('0.6')}.json").read_text(encoding="utf-8"))
    snapcfg["filament_start_gcode"] = ["G28 ; newer\n"]          # not changed since the install: no fresh edit
    (snap / "orca" / f"{sv08('0.6')}.json").write_text(json.dumps(snapcfg), encoding="utf-8")
    live = orca_live(tmp_path, files)
    m2, _ = build(tmp_path, line_set=ls, out="b2", t=target(tmp_path, live=live, snapshot=snap))
    assert oread(tmp_path, sv08("0.4"), out="b2")["filament_start_gcode"] == ["G28 ; mine\n"]
    assert "filament_start_gcode" not in oread(tmp_path, sv08("0.6"), out="b2")
    assert any(sv08("0.6") in p and "filament_start_gcode" in p for p in m2["problems"]), m2["problems"]


def test_orca_nozzle_rules_follow_the_bambu_ones(tmp_path):
    """Abrasive lines skip 0.2 and a nozzle the manufacturer does not support is skipped."""
    cf = [TG.fil(40, "PLA-CF Black", vendor="Acme", material="PLA-CF")]
    sv = ({"name": "Sovol SV08 MAX", "nozzles": ["0.2", "0.4"]},)
    m, ls = build(tmp_path, cf, slicer=sv)
    assert onames(m) == []                                      # no Generic PLA-CF @System in the index
    assert any("Acme PLA-CF Black @SV08 MAX 0.4: no Orca parent" in p for p in m["problems"]), m["problems"]
    assert not any("@SV08 MAX 0.2" in p for p in m["problems"])
    ls = lines.LineSet(ls)
    lines.set_parent(ls, "acme--pla-cf-black", "Generic PLA", target="orca")
    m, _ = build(tmp_path, cf, slicer=sv, line_set=ls, out="o2")
    assert onames(m) == ["Acme PLA-CF Black @SV08 MAX 0.4"]                    # 0.2: abrasive


def test_local_library_orca_parent_wins_in_the_merged_entry():
    from filament_kit.profiles import values
    from filament_kit.library import Lookup
    lib = {"vendor": "SUNLU", "product": "PLA+ 2.0", "orca_parent": "Generic PLA", "fields": {}}
    loc = {"vendor": "SUNLU", "product": "PLA+ 2.0", "orca_parent": "SUNLU PLA+ 2.0", "fields": {}}
    assert values.merged_entry(Lookup(lib, loc))["orca_parent"] == "SUNLU PLA+ 2.0"


def test_bambu_orca_nozzles_skip_0_2_unless_configured(tmp_path):
    m, _ = build(tmp_path, slicer=(), presets_orca=True)
    assert h2d("0.2") not in onames(m) and h2d("0.4") in onames(m)
    printers, problems = G.orca_printers(TG.MODELS, [], bambu_nozzles=["0.2", "0.8"])
    assert problems == []
    m, _ = build(tmp_path, out="o2", t=G.OrcaTarget(store=ostore(), printers=printers, problems=problems))
    assert onames(m) == [h2d("0.2"), h2d("0.8")]
    _p, problems = G.orca_printers(TG.MODELS, [], bambu_nozzles=["big"])
    assert any("presets_orca_nozzles" in p for p in problems)


def test_info_user_id_without_an_orca_live_upload(tmp_path):
    """M4: with no Orca live folder the .info user_id is the one the PC sync reported (meta orca_user_id)."""
    t = target(tmp_path)
    t.user_id = OUSER
    build(tmp_path, t=t)
    assert oinfo(tmp_path, sv08("0.4"))["user_id"] == OUSER


def test_presets_orca_nozzles_empty_or_excluding_everything_is_a_clear_problem(tmp_path):
    _p, problems = G.orca_printers(TG.MODELS, [], bambu_nozzles=[])
    assert any("presets_orca_nozzles must be a non-empty list" in p for p in problems)
    m, _ = build(tmp_path, slicer=(), presets_orca=True, bambu_nozzles=["1.0"])
    assert onames(m) == []
    assert any("config presets_orca_nozzles (1.0) leaves out" in p
               and "Bambu Lab H2D only with nozzle 0.2, 0.4, 0.6, 0.8" in p for p in m["problems"]), m["problems"]
    only02 = orca_bbl()
    for n in ("Bambu PLA Tough+ @BBL H2D 0.2 nozzle", "Bambu PLA Tough+ @BBL P1S"):
        del only02[n]
    only02["Bambu PLA Tough+ @BBL H2D"]["compatible_printers"] = TG.cp(TG.H2D, "0.2")
    m, _ = build(tmp_path, out="o2", t=target(tmp_path, store=ostore(only02), slicer=(), presets_orca=True))
    assert any("leave out by default (all but 0.2)" in p and "presets_orca_nozzles" not in p
               for p in m["problems"]), m["problems"]
