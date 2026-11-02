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
    assert keys == {"filament_flow_ratio", "pressure_advance"}
    assert cfg["filament_flow_ratio"] == ["0.95"]
    assert any("filament_flow_ratio" in line and "(your in-app value, kept)" in line for line in log)
    assert not any("pressure_advance" in line and "in-app value" in line for line in log)  # same value: no log
    assert cfg["filament_notes"] == f"Summary\n{inapp.MARK}\nmine\nSpoolman filament ids: 1, 2"
    cfg2 = {"name": "x", "filament_notes": "Summary"}
    inapp.keep_edits(cfg2, dict(INSTALLED, filament_notes="Summary"), live, [])
    assert cfg2["filament_notes"] == f"Summary\n{inapp.MARK}\nmine"


def test_keep_edits_without_both_sides():
    cfg = {"name": "x", "filament_flow_ratio": ["0.98"]}
    assert inapp.keep_edits(cfg, None, LIVE, []) == set()
    assert inapp.keep_edits(cfg, INSTALLED, None, []) == set()
    assert cfg == {"name": "x", "filament_flow_ratio": ["0.98"]}


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
