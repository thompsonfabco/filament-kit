"""Orca parents on lines (Task 3): Line.orca_parent, lines.json v2, choose_orca_parent, set_parent target."""
import json
from pathlib import Path

import pytest

from filament_kit import config, library
from filament_kit.profiles import errors, lines, orca

LIB = Path(__file__).parent / "data" / "library"
ORCA = Path(__file__).parent / "data" / "orca" / "system"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path


def _local(vendor, product, material, orca_parent=None) -> dict:
    e = {"schema_version": 1, "vendor": vendor, "product": product, "material": material, "fields": {}}
    if orca_parent is not None:
        e["orca_parent"] = orca_parent
    return e


def make_lib(*local) -> library.Library:
    idx = json.loads((LIB / "index.json").read_text(encoding="utf-8"))
    return library.Library(LIB, idx, "bundled", list(local))


@pytest.fixture
def lib():
    return make_lib(_local("Acme", "PLA Matte", "PLA", "Overture PLA Pro"),
                    _local("Acme", "PETG Nope", "PETG", "Nope"))


@pytest.fixture
def ostore():
    return orca.OrcaStore.load(ORCA)


def _line(vendor, product, material) -> lines.Line:
    return lines.Line(lines.line_id_for(vendor, product), vendor, product, material, None, "none", "P0000001",
                      "2026-11-02T00:00:00Z")


# ---------- orca_type ----------

def test_orca_type_port_of_ops():
    assert lines.ORCA_TYPE == {"TPU-GF": "TPU", "PPS-GF": "PPS"}
    assert lines.orca_type("tpu-gf") == "TPU"
    assert lines.orca_type("PA12-CF") == "PA12-CF"      # Orca keeps what Bambu Studio maps
    assert lines.orca_type(" petg ") == "PETG"


# ---------- choose_orca_parent ----------

def test_orca_parent_library_hint(lib, ostore):
    assert lines.choose_orca_parent(_line("Acme", "PLA Matte", "PLA"), ostore, library=lib) == \
        ("Overture PLA Pro", "library")


def test_orca_hint_missing_from_store_falls_through(lib, ostore):
    assert lines.choose_orca_parent(_line("Acme", "PETG Nope", "PETG"), ostore, library=lib) == \
        ("Generic PETG", "material")


def test_orca_parent_same_name_system_preset(lib, ostore):
    assert lines.choose_orca_parent(_line("SUNLU", "PLA+ 2.0", "PLA"), ostore, library=lib) == \
        ("SUNLU PLA+ 2.0", "brand")
    # case differs: the store's spelling is kept
    assert lines.choose_orca_parent(_line("sunlu", "pla+ 2.0", "PLA"), ostore, library=lib) == \
        ("SUNLU PLA+ 2.0", "brand")


def test_orca_parent_generic_by_type(lib, ostore):
    assert lines.choose_orca_parent(_line("XZN", "TPU-GF", "TPU-GF"), ostore, library=lib) == \
        ("Generic TPU", "material")
    assert lines.choose_orca_parent(_line("XZN", "PPS-GF", "PPS-GF"), ostore, library=lib) == \
        ("Generic PPS", "material")
    assert lines.choose_orca_parent(_line("XZN", "PLA", "PLA"), ostore, library=lib) == ("Generic PLA", "material")


def test_orca_parent_generic_by_index_type_when_no_plain_name(lib, tmp_path):
    root = tmp_path / "sys"
    (root / "OrcaFilamentLibrary").mkdir(parents=True)
    (root / "OrcaFilamentLibrary" / "index.json").write_text(json.dumps({"version": 1, "presets": [
        {"name": "Generic PLA Silk @System", "filament_type": "PLA"},
        {"name": "Generic PLA-CF @System", "filament_type": "PLA"},
        {"name": "Acme PLA @System", "filament_type": "PLA"}]}), encoding="utf-8")
    s = orca.OrcaStore.load(root)
    assert lines.choose_orca_parent(_line("XZN", "PLA", "PLA"), s, library=lib) == ("Generic PLA Silk", "material")
    assert lines.choose_orca_parent(_line("XZN", "ASA", "ASA"), s, library=lib) == (None, "none")


def test_orca_parent_without_store(lib):
    assert lines.choose_orca_parent(_line("Acme", "PETG Nope", "PETG"), None, library=lib) == ("Nope", "library")
    assert lines.choose_orca_parent(_line("XZN", "TPU-GF", "TPU-GF"), None, library=lib) == \
        ("Generic TPU", "material")
    assert lines.choose_orca_parent(_line("XZN", "X", ""), None, library=lib) == (None, "none")


def test_store_without_library_index_is_like_no_store(lib, tmp_path):
    s = orca.OrcaStore.load(tmp_path / "missing")
    assert lines.choose_orca_parent(_line("Acme", "PETG Nope", "PETG"), s, library=lib) == ("Nope", "library")


def test_local_orca_hint_wins_over_library(ostore):
    lib2 = make_lib(_local("SUNLU", "PLA+ 2.0", "PLA", "Overture PLA Pro"))
    assert lines.choose_orca_parent(_line("SUNLU", "PLA+ 2.0", "PLA"), ostore, library=lib2) == \
        ("Overture PLA Pro", "library")


def test_rechoose_orca_keeps_user_choice(lib, ostore):
    ls = lines.LineSet()
    a = lines.ensure(ls, "XZN", "PLA", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set())
    assert (a.orca_parent, a.orca_parent_source) == ("Generic PLA", "material")
    lines.set_parent(ls, a.line_id, "Overture PLA Pro", target="orca")
    assert lines.rechoose_orca(a, ostore, library=lib) is a
    assert (a.orca_parent, a.orca_parent_source) == ("Overture PLA Pro", "user")
    b = lines.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set())
    lines.rechoose_orca(b, ostore, library=lib)
    assert (b.orca_parent, b.orca_parent_source) == ("SUNLU PLA+ 2.0", "brand")
    assert (b.bambu_parent, b.parent_source) != (None, "none")      # the Bambu parent is untouched


# ---------- ensure / set_parent / propose ----------

def test_ensure_new_line_gets_orca_parent_and_user_override(lib, ostore):
    ls: dict = {}
    a = lines.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set(),
                     orca_store=ostore)
    assert (a.orca_parent, a.orca_parent_source) == ("SUNLU PLA+ 2.0", "brand")
    b = lines.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set(),
                     orca_parent="Generic PLA")
    assert b is a and (a.orca_parent, a.orca_parent_source) == ("Generic PLA", "user")


def test_set_parent_targets(lib):
    ls: dict = {}
    a = lines.ensure(ls, "XZN", "PETG", "PETG", bambu_parent=None, library=lib, store=None, used_fids=set())
    bambu = (a.bambu_parent, a.parent_source)
    lines.set_parent(ls, a.line_id, "Generic PLA", target="orca")
    assert (a.orca_parent, a.orca_parent_source) == ("Generic PLA", "user")
    assert (a.bambu_parent, a.parent_source) == bambu
    lines.set_parent(ls, a.line_id, "Generic PLA")
    assert (a.bambu_parent, a.parent_source) == ("Generic PLA", "user")
    with pytest.raises(ValueError):
        lines.set_parent(ls, a.line_id, "X", target="cura")


def test_set_parent_saved_orca():
    with lines.transaction() as ls:
        ls["xzn--petg"] = _line("XZN", "PETG", "PETG")
    got = lines.set_parent_saved("xzn--petg", "Generic PETG", target="orca")
    assert got.orca_parent == "Generic PETG"
    assert lines.load()["xzn--petg"].orca_parent_source == "user"


def test_propose_includes_orca_parent(lib, ostore):
    ls: dict = {}
    p = lines.propose("SUNLU", "PLA+ 2.0", "PLA", library=lib, store=None, lines=ls, orca_store=ostore)
    assert (p["orca_parent"], p["orca_parent_source"], p["exists"]) == ("SUNLU PLA+ 2.0", "brand", False)
    lines.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set(),
                 orca_parent="Overture PLA Pro")
    p = lines.propose("SUNLU", "PLA+ 2.0", "PLA", library=lib, store=None, lines=ls, orca_store=ostore)
    assert (p["orca_parent"], p["orca_parent_source"], p["exists"]) == ("Overture PLA Pro", "user", True)


def test_check_orca_parent(ostore):
    assert lines.check_orca_parent("Overture PLA Pro", ostore) == "Overture PLA Pro"
    assert lines.check_orca_parent("  generic pla ", ostore) == "Generic PLA"      # the store's spelling (I1)
    assert lines.check_orca_parent(" Anything ", None) == "Anything"                # no store: as given, stripped
    assert lines.check_orca_parent("", ostore) == ""
    with pytest.raises(errors.ProfileError) as e:
        lines.check_orca_parent("Nope", ostore)
    assert (e.value.status, e.value.code, e.value.extra) == (400, "unknown_parent", {"parent": "Nope"})
    with pytest.raises(errors.ProfileError):
        lines.check_orca_parent("Bambu PLA Basic @BBL H2D", ostore)    # a BBL preset is not an @System parent


# ---------- persistence: v2, v1 read with None ----------

V1_ROW = {"line_id": "xzn--petg", "vendor": "XZN", "product": "PETG", "material": "PETG",
          "bambu_parent": "Generic PETG", "parent_source": "material", "filament_id": "P0123abc",
          "created": "2026-11-02T00:00:00Z", "filaments": [3]}


def _file() -> Path:
    folder = config.paths().state / "profiles"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "lines.json"


def test_v1_file_reads_with_no_orca_parent_and_saves_v2():
    _file().write_text(json.dumps({"version": 1, "lines": [V1_ROW]}), encoding="utf-8")
    ls = lines.load()
    line = ls["xzn--petg"]
    assert (line.orca_parent, line.orca_parent_source) == (None, "none")
    assert line.filaments == [3]
    lines.save(ls)
    data = json.loads(_file().read_text(encoding="utf-8"))
    assert data["version"] == 2 == lines.FILE_VERSION
    assert data["lines"][0] == {**V1_ROW, "orca_parent": None, "orca_parent_source": "none"}


def test_v2_roundtrip():
    row = {**V1_ROW, "orca_parent": "Generic PETG", "orca_parent_source": "user"}
    _file().write_text(json.dumps({"version": 2, "lines": [row]}), encoding="utf-8")
    ls = lines.load()
    assert (ls["xzn--petg"].orca_parent, ls["xzn--petg"].orca_parent_source) == ("Generic PETG", "user")
    lines.save(ls)
    assert json.loads(_file().read_text(encoding="utf-8"))["lines"] == [row]


@pytest.mark.parametrize("bad", [{"orca_parent": 5}, {"orca_parent_source": "weird"},
                                 {"orca_parent": "X", "orca_parent_source": None}])
def test_invalid_orca_fields_make_the_row_invalid(bad):
    row = {**V1_ROW, **bad}
    _file().write_text(json.dumps({"version": 2, "lines": [row]}), encoding="utf-8")
    ls = lines.load()
    assert ls == {} and ls.invalid == [row]
