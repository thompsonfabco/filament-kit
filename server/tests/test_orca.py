"""Orca system store (Ruling L): BBL JSON from Orca's unpacked system folder + the OrcaFilamentLibrary index."""
import json
import shutil
from pathlib import Path

import pytest

from filament_kit.profiles import orca

ORCA = Path(__file__).parent / "data" / "orca" / "system"


@pytest.fixture
def store():
    return orca.OrcaStore.load(ORCA)


def _copy(tmp_path) -> Path:
    dest = tmp_path / "system"
    shutil.copytree(ORCA, dest)
    return dest


def test_names_hold_bbl_and_library(store):
    names = store.names()
    assert "Bambu PLA Basic @BBL H2D" in names
    assert "Bambu PLA Basic @BBL P1P" in names          # from a vendor subfolder
    assert "Generic PLA @System" in names
    assert "SUNLU PLA+ 2.0 @System" in names
    assert store.library_names() == {n for n in names if n.endswith(" @System")}
    assert store.problems == []


def test_parent_library_entry(store):
    p = store.parent("SUNLU PLA+ 2.0 @System")
    assert p == {"name": "SUNLU PLA+ 2.0 @System", "setting_id": "8EZyKHm5JquwOtfP", "filament_id": "OGFSNL04",
                 "filament_type": "PLA", "inherits": None}
    p["setting_id"] = "x"                                  # a copy
    assert store.parent("SUNLU PLA+ 2.0 @System")["setting_id"] == "8EZyKHm5JquwOtfP"


def test_parent_bbl_is_resolved(store):
    p = store.parent("Bambu PLA Basic @BBL H2D 0.6 nozzle")
    assert p["setting_id"] == "GFSA00_27"
    assert p["filament_id"] == "GFA00"                     # from @base
    assert p["filament_type"] == ["PLA"]                    # from fdm_filament_common
    assert p["compatible_printers"] == ["Bambu Lab H2D 0.6 nozzle"]
    assert p["filament_extruder_variant"] == ["Direct Drive Standard", "Direct Drive High Flow"]


def test_parent_unknown_is_none(store):
    assert store.parent("Nope @System") is None
    assert store.parent("Nope @BBL H2D") is None


def test_system_parent_for(store):
    assert store.system_parent_for("Bambu Lab H2D", "0.4", "Bambu PLA Basic") == "Bambu PLA Basic @BBL H2D"
    assert store.system_parent_for("Bambu Lab H2D", "0.6", "Bambu PLA Basic") == \
        "Bambu PLA Basic @BBL H2D 0.6 nozzle"
    assert store.system_parent_for("Bambu Lab H2D", "0.2", "Bambu PLA Basic") is None
    assert store.system_parent_for("Sovol SV08 MAX", "0.4", "Bambu PLA Basic") is None
    assert store.system_parent_for("Bambu Lab H2D", "0.4", "Nope") is None


def test_printer_variants(store):
    assert store.printer_variants("Bambu Lab H2D") == ["Direct Drive Standard", "Direct Drive High Flow"]
    assert store.printer_variants("Bambu Lab P1P") == ["Direct Drive Standard", "Direct Drive High Flow"]
    # only Generic PLA lists the X1 Carbon; it takes fdm_filament_common's single variant
    assert store.printer_variants("Bambu Lab X1 Carbon") == ["Direct Drive Standard"]
    # "Bambu Lab" is a prefix of every printer, not a printer: no preset lists "Bambu Lab <n> nozzle"
    store.bbl._raw["Bambu PLA Basic @BBL H2D"]["filament_extruder_variant"] = ["A", "B", "C"]
    assert store.printer_variants("Bambu Lab") == ["Direct Drive Standard"]
    assert store.printer_variants("Sovol SV08 MAX") == ["Direct Drive Standard"]   # not a BBL printer


def test_missing_folder_is_empty_store(tmp_path):
    s = orca.OrcaStore.load(tmp_path / "nope")
    assert s.names() == set() and s.problems == []
    assert not s


def test_index_problems_are_reported_not_fatal(tmp_path):
    root = _copy(tmp_path)
    idx = root / "OrcaFilamentLibrary" / "index.json"
    data = json.loads(idx.read_text(encoding="utf-8"))
    data["presets"] += [{"name": ""}, "junk", {"name": "Generic PLA @System"}, {"name": "X @System", "setting_id": 3}]
    idx.write_text(json.dumps(data), encoding="utf-8")
    s = orca.OrcaStore.load(root)
    assert "Generic PLA @System" in s.names()
    assert "X @System" not in s.names()
    assert len(s.problems) == 4


@pytest.mark.parametrize("raw", [b"{bad", b"[]", json.dumps({"version": 2, "presets": []}).encode(),
                                 json.dumps({"version": 1}).encode()])
def test_bad_index_is_a_problem_and_no_library(tmp_path, raw):
    root = _copy(tmp_path)
    (root / "OrcaFilamentLibrary" / "index.json").write_bytes(raw)
    s = orca.OrcaStore.load(root)
    assert s.library_names() == set()
    assert "Bambu PLA Basic @BBL H2D" in s.names()
    assert any("index.json" in p for p in s.problems)


def test_no_index_means_bbl_only(tmp_path):
    root = _copy(tmp_path)
    shutil.rmtree(root / "OrcaFilamentLibrary")
    s = orca.OrcaStore.load(root)
    assert s.library_names() == set() and s.problems == []
    assert s


def test_bbl_problems_are_reported(tmp_path):
    root = _copy(tmp_path)
    (root / "BBL" / "filament" / "broken.json").write_bytes(b"{")
    s = orca.OrcaStore.load(root)
    assert any("broken.json" in p for p in s.problems)


def test_read_then_parse_matches_load():
    s = orca.OrcaStore.parse(orca.OrcaStore.read(ORCA))
    assert s.names() == orca.OrcaStore.load(ORCA).names()


REAL = Path(__import__("os").environ.get("APPDATA", "/nonexistent")) / "OrcaSlicer" / "system"


@pytest.mark.skipif(not (REAL / "BBL" / "filament").is_dir(), reason="no Orca Slicer on this machine")
def test_real_orca_bbl_folder():
    s = orca.OrcaStore.load(REAL)                 # no index there: BBL only
    assert s.system_parent_for("Bambu Lab H2D", "0.4", "Bambu PLA Basic") == "Bambu PLA Basic @BBL H2D"
    assert s.printer_variants("Bambu Lab H2D") == ["Direct Drive Standard", "Direct Drive High Flow"]
