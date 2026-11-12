import importlib.util
from pathlib import Path

from filament_kit.profiles import inapp

PC_SYNC_INAPP = Path(__file__).resolve().parents[2] / "pc-sync" / "fksync" / "inapp.py"


def pc_sync_inapp():
    spec = importlib.util.spec_from_file_location("pc_sync_fksync_inapp", PC_SYNC_INAPP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


INSTALLED = {"name": "A @Bambu Lab H2D 0.4 nozzle", "filament_id": "P1234567", "updated_time": "1",
             "filament_flow_ratio": ["0.98"], "nozzle_temperature": ["220", "230"], "filament_notes": "x",
             "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"], "filament_cost": "20"}
LIVE = {"name": "A @Bambu Lab H2D 0.4 nozzle", "filament_id": "P7654321", "updated_time": "2",
        "filament_flow_ratio": ["0.95"], "nozzle_temperature": [220, 230], "filament_notes": "y",
        "compatible_printers": ["Bambu Lab H2D 0.6 nozzle"], "filament_cost": 20, "pressure_advance": ["0.02"],
        "setting_id": "GFSA04", "inherits": "", "user_id": "1"}


def test_diff_ignores_bookkeeping():
    assert inapp.diff(INSTALLED, LIVE) == {"filament_flow_ratio": ["0.95"], "pressure_advance": ["0.02"]}
    assert "compatible_printers" in inapp.IGNORE


def test_same_as_pc_sync_copy():
    pc = pc_sync_inapp()
    assert pc.IGNORE == inapp.IGNORE
    for v in (["1", 2, 3.5], "x", 7, 0.98, None, [], True):
        assert pc.norm(v) == inapp.norm(v)
    pairs = [(INSTALLED, LIVE), (LIVE, INSTALLED), ({}, LIVE), (INSTALLED, {}), (INSTALLED, dict(INSTALLED))]
    for a, b in pairs:
        assert pc.diff(a, b) == inapp.diff(a, b)
    sets = [(set(), set()), ({"a", "b", "c", "d"}, {"a", "b", "c"}), ({"a", "b", "c", "d"}, {"a", "b"}),
            ({"A", "b"}, {"a"}), ({f"p{i}" for i in range(8)}, {f"p{i}" for i in range(5)})]
    for snap, live in sets:
        assert pc.is_reset(snap, live) == inapp.is_reset(snap, live)


def test_user_notes_below_mark_without_ids():
    installed = {"filament_notes": "One profile for every A colour.\nManufacturer specs: x."}
    live = {"filament_notes": "One profile for every A colour.\nManufacturer specs: x.\nmy own line\n"
                              f"{inapp.MARK}\nkeep me\nSpoolman filament ids: 1, 2\nand me"}
    assert inapp.user_notes(installed, live) == ["keep me", "and me", "my own line"]
    live2 = {"filament_notes": ["One profile for every A colour.", "Spoolman filament ids: 3", "typed here"]}
    assert inapp.user_notes(installed, live2) == ["typed here"]
    assert inapp.user_notes({}, {}) == []


def test_keep_edits_copies_changed_value():
    cfg = {"name": "A @Bambu Lab H2D 0.4 nozzle", "filament_flow_ratio": ["0.98"], "pressure_advance": ["0.02"],
           "filament_notes": "Summary\nSpoolman filament ids: 1, 2"}
    live = dict(LIVE, filament_notes=f"Summary\n{inapp.MARK}\nmine")
    log = []
    keys = inapp.keep_edits(cfg, dict(INSTALLED, filament_notes="Summary"), live, log)
    assert keys == {"filament_flow_ratio": ["0.95"]}         # pressure_advance equals the generated value (S27)
    assert cfg["filament_flow_ratio"] == ["0.95"]
    assert any("filament_flow_ratio" in line and "(your in-app value, kept)" in line for line in log)
    assert not any("pressure_advance" in line and "in-app value" in line for line in log)  # same value: no log
    assert cfg["filament_notes"] == f"Summary\n{inapp.MARK}\nmine\nSpoolman filament ids: 1, 2"
    cfg2 = {"name": "x", "filament_notes": "Summary"}
    inapp.keep_edits(cfg2, dict(INSTALLED, filament_notes="Summary"), live, [])
    assert cfg2["filament_notes"] == f"Summary\n{inapp.MARK}\nmine"


def test_keep_edits_without_both_sides():
    cfg = {"name": "x", "filament_flow_ratio": ["0.98"]}
    assert inapp.keep_edits(cfg, None, LIVE, []) == {}
    assert inapp.keep_edits(cfg, INSTALLED, None, []) == {}
    assert cfg == {"name": "x", "filament_flow_ratio": ["0.98"]}


def test_recorded_edits_last_and_drop_when_generated_again():
    cfg = {"name": "x", "filament_flow_ratio": ["0.98"], "pressure_advance": ["0.02"], "hot_plate_temp": ["55"]}
    installed = {"filament_flow_ratio": ["0.91"], "pressure_advance": ["0.04"], "hot_plate_temp": ["55"]}
    recorded = {"filament_flow_ratio": ["0.91"], "pressure_advance": ["0.04"], "name": "ignored"}
    # flow untouched since (kept from the record); pressure_advance set back to the generated value (dropped);
    # hot_plate_temp changed now (a fresh edit)
    live = {"filament_flow_ratio": ["0.91"], "pressure_advance": ["0.02"], "hot_plate_temp": ["60"]}
    log = []
    got = inapp.keep_edits(dict(cfg), installed, live, log, recorded=recorded)
    assert got == {"filament_flow_ratio": ["0.91"], "hot_plate_temp": ["60"]}
    assert any("pressure_advance is the generated value again" in line for line in log)
    # changed again: the live value wins over the record
    got = inapp.keep_edits(dict(cfg), installed, dict(live, filament_flow_ratio=["0.93"]), [], recorded=recorded)
    assert got["filament_flow_ratio"] == ["0.93"]
    # the live preset is gone (an app reset rebuilds it): the record is still his
    out = dict(cfg)
    assert inapp.keep_edits(out, installed, None, [], recorded=recorded) == {"filament_flow_ratio": ["0.91"],
                                                                            "pressure_advance": ["0.04"]}
    assert out["filament_flow_ratio"] == ["0.91"]


def test_recorded_edit_survives_a_coinciding_generated_value():
    """Fix round 1: a key only in the record is never dropped because the generated value happens to match."""
    recorded = {"nozzle_temperature": ["220"]}
    b2 = {"nozzle_temperature": ["220"]}                    # B2 carried the owner's 220
    live = {"nozzle_temperature": ["220"]}
    rec3 = inapp.keep_edits({"name": "x", "nozzle_temperature": ["220"]}, b2, live, [], recorded=recorded)
    assert rec3 == {"nozzle_temperature": ["220"]}          # B3 generates 220 too: still his
    cfg4 = {"name": "x", "nozzle_temperature": ["230"]}
    assert inapp.keep_edits(cfg4, b2, live, [], recorded=rec3) == {"nozzle_temperature": ["220"]}
    assert cfg4["nozzle_temperature"] == ["220"]            # B4 generates 230: his 220 wins


def test_partial_build_values_are_not_edits():
    cfg = {"name": "x", "filament_density": ["1.35"], "filament_flow_ratio": ["0.98"]}
    installed = {"filament_density": ["1.24"], "filament_flow_ratio": ["0.98"]}
    partial = {"filament_density": ["1.31"], "filament_flow_ratio": ["0.98"]}
    live = {"filament_density": ["1.31"], "filament_flow_ratio": ["0.9"]}
    assert inapp.keep_edits(dict(cfg), installed, live, [], partial=partial) == {"filament_flow_ratio": ["0.9"]}
    assert inapp.keep_edits(dict(cfg), installed, live, []) == {"filament_density": ["1.31"],
                                                               "filament_flow_ratio": ["0.9"]}


def test_is_reset():
    snap = {f"p{i}" for i in range(8)}
    assert inapp.is_reset(snap, snap - {"p0", "p1", "p2"}) is True
    assert inapp.is_reset(snap, snap - {"p0", "p1"}) is False
    assert inapp.is_reset(set(), set()) is False


def test_deleted():
    snap, live = {"A @H2D 0.4", "B @H2D 0.4"}, {"B @H2D 0.4"}
    assert inapp.deleted("A @H2D 0.4", snapshot=snap, live=live, before=set(), reset=True, restore=False) is False
    assert inapp.deleted("a @h2d 0.4", snapshot=snap, live=live, before=set(), reset=False, restore=False) is True
    assert inapp.deleted("A @H2D 0.4", snapshot=snap, live=live, before=set(), reset=False, restore=True) is False
    assert inapp.deleted("B @H2D 0.4", snapshot=snap, live=live, before=set(), reset=False, restore=False) is False
    assert inapp.deleted("C @H2D 0.4", snapshot=snap, live=live, before={"c @h2d 0.4"}, reset=False,
                         restore=False) is True
    assert inapp.deleted("C @H2D 0.4", snapshot=snap, live=live, before=set(), reset=False, restore=False) is False


def test_deleted_class_folds_once_and_agrees_with_the_function():
    """FA-055: `Deleted` answers like `deleted` for every combination, restore chosen per call."""
    snap, live, before = {"A @H2D 0.4", "B @H2D 0.4"}, {"B @H2D 0.4"}, {"c @h2d 0.4"}
    for reset in (False, True):
        gone = inapp.Deleted(snapshot=snap, live=live, before=before, reset=reset)
        for name in ("a @h2d 0.4", "B @H2D 0.4", "C @H2D 0.4", "D @H2D 0.4"):
            for restore in (False, True):
                assert gone(name, restore=restore) is inapp.deleted(
                    name, snapshot=snap, live=live, before=before, reset=reset, restore=restore)


def test_app_reset_keeps_note_lines_below_mark():
    """Final review C1: the live preset is gone (app reset): the owner's lines below MARK come from the installed
    copy (filament_notes is in IGNORE, so the edit record never carries them)."""
    installed = {"filament_notes": f"Old summary\n{inapp.MARK}\nmine\nalso mine\nSpoolman filament ids: 1"}
    cfg = {"name": "x", "filament_notes": "New summary\nSpoolman filament ids: 1, 2"}
    log = []
    inapp.keep_edits(cfg, installed, None, log)
    assert cfg["filament_notes"] == f"New summary\n{inapp.MARK}\nmine\nalso mine\nSpoolman filament ids: 1, 2"
    assert any("2 line(s) you wrote" in line for line in log)
    # only the MARK section: the installed copy's generated lines are not theirs
    cfg2 = {"name": "x", "filament_notes": "New summary\nSpoolman filament ids: 1, 2"}
    inapp.keep_edits(cfg2, {"filament_notes": "Old summary\nSpecs\nSpoolman filament ids: 1"}, None, [])
    assert cfg2["filament_notes"] == "New summary\nSpoolman filament ids: 1, 2"


def test_partial_build_note_lines_are_not_the_owners():
    """Final review I1: the half-finished install wrote that build's summary/spec lines into live; they are not
    the owner's lines, while a line they typed (or their lines below MARK) still are."""
    installed = {"filament_notes": "Old summary\nSpoolman filament ids: 1"}
    half = {"filament_notes": f"New summary\nSpecs\n{inapp.MARK}\nmine\nSpoolman filament ids: 1, 2"}
    gen = "Newer summary\nSpecs\nSpoolman filament ids: 1, 2"
    cfg = {"name": "x", "filament_notes": gen}
    inapp.keep_edits(cfg, installed, dict(half), [], partial=half)
    assert cfg["filament_notes"] == f"Newer summary\nSpecs\n{inapp.MARK}\nmine\nSpoolman filament ids: 1, 2"
    typed = {"filament_notes": "New summary\nSpecs\ntyped later\nSpoolman filament ids: 1, 2"}
    cfg = {"name": "x", "filament_notes": gen}
    inapp.keep_edits(cfg, installed, typed, [], partial=dict(typed, filament_notes="New summary\nSpecs\n"
                                                                                    "Spoolman filament ids: 1, 2"))
    assert cfg["filament_notes"] == f"Newer summary\nSpecs\n{inapp.MARK}\ntyped later\nSpoolman filament ids: 1, 2"
    # without the partial copy the half-install's lines look typed (the bug)
    assert inapp.user_notes(installed, half) == ["mine", "New summary", "Specs"]
    assert inapp.user_notes(installed, half, partial=half) == ["mine"]


def test_kept_notes_without_an_installed_copy():
    """Ruling S34: with no installed copy (a re-paired PC) the owner's saved note lines are carried."""
    cfg = {"name": "x", "filament_notes": "Summary\nSpoolman filament ids: 1"}
    inapp.keep_edits(cfg, None, {"filament_notes": "anything"}, [], notes=["mine", "Spoolman filament ids: 9"])
    assert cfg["filament_notes"] == f"Summary\n{inapp.MARK}\nmine\nSpoolman filament ids: 1"
