import json
from pathlib import Path

import pytest

from filament_kit.profiles import bbl
from filament_kit.profiles.errors import ProfileError

DATA = Path(__file__).parent / "data" / "bbl"


@pytest.fixture
def store():
    return bbl.Store.load(DATA)


def test_resolve_chain_and_include(store):
    cfg = store.resolve("Generic PLA @BBL H2D")
    assert cfg["filament_retraction_length"] == ["0.8"]        # from the include template
    assert cfg["nozzle_temperature_range_low"] == ["190"]      # from fdm_filament_common via the chain
    assert cfg["nozzle_temperature"] == ["220", "230"]         # own keys win
    assert cfg["filament_id"] == "GFL99"                       # from @base
    assert "include" not in cfg


def test_resolve_child_overrides_same_length_lists(store):
    cfg = store.resolve("Generic PLA @BBL H2D 0.2 nozzle")
    assert cfg["filament_max_volumetric_speed"] == ["2", "2"]
    assert cfg["compatible_printers"] == ["Bambu Lab H2D 0.2 nozzle"]
    assert cfg["filament_retraction_length"] == ["0.8"]


def test_resolve_is_cached_but_returns_copies(store):
    a = store.resolve("Generic PLA @BBL H2D")
    a["nozzle_temperature"].append("999")
    assert store.resolve("Generic PLA @BBL H2D")["nozzle_temperature"] == ["220", "230"]


def test_broken_file_is_a_problem_not_a_crash(store):
    assert any("broken.json" in p for p in store.problems)
    assert "broken" not in store.names()
    assert "Generic PLA @BBL H2D" in store.names()


def test_parent_for_prefers_nozzle_specific(store):
    assert store.parent_for("Generic PLA", "Bambu Lab H2D", "0.2") == "Generic PLA @BBL H2D 0.2 nozzle"
    assert store.parent_for("Generic PLA", "Bambu Lab H2D", "0.4") == "Generic PLA @BBL H2D"
    assert store.parent_for("Generic PLA", "Bambu Lab P1S", "0.6") is None
    assert store.parent_for("Generic PLA", "Bambu Lab P1S", "0.4") == "Generic PLA @BBL X1C"


def test_nozzles_for(store):
    assert store.nozzles_for("Generic PLA", "Bambu Lab H2D") == ["0.2", "0.4", "0.6", "0.8"]
    assert store.nozzles_for("Generic PLA", "Bambu Lab X1 Carbon") == ["0.4", "0.6"]
    assert store.nozzles_for("Generic PLA", "Bambu Lab A1") == []


def test_bases_filters_instantiable(store):
    assert "Generic PLA" in store.bases("PLA")
    assert "Generic PLA-CF" not in store.bases("PLA")
    assert "Generic PETG" not in store.bases("PLA")
    assert "Generic PLA-CF" in store.bases("PLA-CF")
    assert "fdm_filament_pla" not in store.bases()
    assert store.bases() == sorted(store.bases())
    assert set(store.bases()) == {"Bambu PLA Basic", "Generic PETG", "Generic PLA", "Generic PLA-CF",
                                  "Generic TPU for AMS", "SUNLU PLA+"}


def test_vendor_bases(store):
    assert store.vendor_bases("sunlu", "PLA") == ["SUNLU PLA+"]
    assert store.vendor_bases("Bambu Lab", "PLA") == ["Bambu PLA Basic"]
    assert store.vendor_bases("SUNLU", "PETG") == []


def test_base_name(store):
    assert store.base_name("Generic PLA @BBL H2D 0.2 nozzle") == "Generic PLA"
    assert store.base_name("fdm_filament_pla") == "fdm_filament_pla"


def test_variants(store):
    assert store.variants("Generic PLA @BBL H2D") == [bbl.STD, bbl.HF]
    assert store.variants("Generic PLA @BBL X1C") == [bbl.STD]
    assert bbl.STD == "Direct Drive Standard" and bbl.HF == "Direct Drive High Flow"


def test_gcode_values(store):
    assert json.dumps(["; filament start gcode\n"], sort_keys=True) in store.gcode_values()


def test_merge_nil_keeps_parent_value():
    assert bbl.merge({"a": ["nil", "5"], "b": "x"}, {"a": ["1", "2"], "c": 3}) == {"a": ["1", "5"], "b": "x", "c": 3}
    assert bbl.merge({"a": ["nil"]}, {"a": ["1", "2"]}) == {"a": ["nil"]}  # different length: child wins as is


def _write(folder: Path, name: str, data: dict) -> None:
    (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8", newline="\n")


def test_cycle_raises(tmp_path):
    _write(tmp_path, "A", {"name": "A", "inherits": "B", "instantiation": "true"})
    _write(tmp_path, "B", {"name": "B", "inherits": "A", "instantiation": "false"})
    store = bbl.Store.load(tmp_path)
    with pytest.raises(bbl.BblError):
        store.resolve("A")


def test_missing_parent_and_unknown_name_raise(tmp_path):
    _write(tmp_path, "A @BBL H2D", {"name": "A @BBL H2D", "inherits": "nope", "instantiation": "true",
                                    "filament_type": ["PLA"], "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"]})
    store = bbl.Store.load(tmp_path)
    with pytest.raises(bbl.BblError):
        store.resolve("A @BBL H2D")
    with pytest.raises(bbl.BblError):
        store.resolve("does not exist")
    assert store.bases() == []          # an unresolvable preset is skipped, not a crash
    assert store.parent_for("A", "Bambu Lab H2D", "0.4") is None


def test_load_recurses_and_missing_folder_is_empty(tmp_path):
    sub = tmp_path / "BBL" / "filament"
    sub.mkdir(parents=True)
    _write(sub, "X", {"name": "X"})
    assert bbl.Store.load(tmp_path).names() == {"X"}
    empty = bbl.Store.load(tmp_path / "missing")
    assert empty.names() == set()


def test_profile_error_fields():
    e = ProfileError(409, "other_pc", "another PC syncs", owner="abc")
    assert (e.status, e.code, e.message, e.extra) == (409, "other_pc", "another PC syncs", {"owner": "abc"})
    assert isinstance(e, Exception)


def test_profiles_package_keeps_interface():
    from filament_kit import profiles
    assert profiles.preset_for({}, "H2D", 0.4) is None
    assert profiles.PresetRef
