import json
import re
from pathlib import Path

import pytest

from filament_kit import config, library
from filament_kit.profiles import bbl, lines

LIB = Path(__file__).parent / "data" / "library"
BBL = Path(__file__).parent / "data" / "bbl"
FID = re.compile(r"^P[0-9a-f]{7}$")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path


def _local(vendor, product, material, parent=None) -> dict:
    e = {"schema_version": 1, "vendor": vendor, "product": product, "material": material, "fields": {}}
    if parent is not None:
        e["bambu_parent"] = parent
    return e


def make_lib(*local) -> library.Library:
    """The Task 1 fixture library plus `local` entries (the owner's additions)."""
    idx = json.loads((LIB / "index.json").read_text(encoding="utf-8"))
    return library.Library(LIB, idx, "bundled", list(local))


@pytest.fixture
def lib():
    return make_lib(_local("Acme", "PLA Matte", "PLA", "Bambu PLA Basic"),
                    _local("Acme", "PETG Nope", "PETG", "Nope"))


@pytest.fixture
def store():
    return bbl.Store.load(BBL)


def _fil(fid, name, vendor="SUNLU", material="PLA", archived=False, line=None):
    f = {"id": fid, "name": name, "material": material, "archived": archived, "extra": {}}
    if vendor is not None:
        f["vendor"] = {"id": 1, "name": vendor}
    if line is not None:
        f["extra"]["line"] = json.dumps(line)
    return f


# ---------- bs_type ----------

def test_bs_type_maps_and_uppercases():
    assert lines.bs_type("PA12-CF") == "PA-CF"
    assert lines.bs_type("pa12-cf") == "PA-CF"
    assert lines.bs_type("petg") == "PETG"
    assert lines.bs_type("Wood") == "WOOD"          # returned even though not in BS_VALID
    assert "WOOD" not in lines.BS_VALID and "PLA" in lines.BS_VALID


# ---------- choose_parent ----------

def test_parent_from_library_hint(lib, store):
    assert lines.choose_parent("Acme", "PLA Matte", "PLA", library=lib, store=store) == \
        ("Bambu PLA Basic", "library")


def test_library_hint_missing_from_store_falls_through(lib, store):
    got = lines.choose_parent("Acme", "PETG Nope", "PETG", library=lib, store=store)
    assert got[0] != "Nope"
    assert got == ("Generic PETG", "material")


def test_parent_brand_step(lib, store):
    assert lines.choose_parent("SUNLU", "PLA+", "PLA", library=lib, store=store) == ("SUNLU PLA+", "brand")


def test_parent_brand_step_only_preset_of_vendor_and_type(lib, store):
    # "Silk PLA" is not "PLA+", but SUNLU has exactly one PLA brand preset
    assert lines.choose_parent("sunlu", "Silk PLA", "PLA", library=lib, store=store) == ("SUNLU PLA+", "brand")


def test_parent_brand_name_match_wins_over_ambiguity(lib, tmp_path):
    folder = tmp_path / "bbl"
    folder.mkdir()
    common = {"instantiation": "true", "filament_vendor": ["Vend"], "filament_type": ["PLA"],
              "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"]}
    for name in ("Vend PLA Matte @BBL H2D", "Vend PLA Silk @BBL H2D"):
        (folder / f"{name}.json").write_text(json.dumps(common), encoding="utf-8")
    s = bbl.Store.load(folder)
    assert lines.choose_parent("VEND", "pla-silk", "PLA", library=lib, store=s) == ("Vend PLA Silk", "brand")
    # two candidates, no name match -> no brand; no Generic PLA in this store -> none
    assert lines.choose_parent("Vend", "PLA Glow", "PLA", library=lib, store=s) == (None, "none")


def test_parent_material_step(lib, store):
    assert lines.choose_parent("XZN", "PETG", "PETG", library=lib, store=store) == ("Generic PETG", "material")


def test_parent_none_when_store_has_no_generic(lib, store):
    assert lines.choose_parent("XZN", "ASA", "ASA", library=lib, store=store) == (None, "none")


def test_parent_without_store_is_static_generic(lib):
    assert lines.choose_parent("XZN", "PA12-CF", "PA12-CF", library=lib, store=None) == \
        ("Generic PA-CF", "material")


def test_parent_without_store_accepts_library_hint(lib):
    assert lines.choose_parent("Acme", "PETG Nope", "PETG", library=lib, store=None) == ("Nope", "library")


def test_parent_without_material_is_none(lib):
    assert lines.choose_parent("XZN", "Mystery", "", library=lib, store=None) == (None, "none")


def test_condition_only_presets_are_not_parents(lib, tmp_path):
    """A preset gated only by compatible_printers_condition never yields a build parent (Task 2 review), so it
    is not chosen; the line falls through, and with nothing left it is a visible 'none' line with a problem."""
    folder = tmp_path / "bbl"
    folder.mkdir()
    cond = {"instantiation": "true", "filament_type": ["PLA"], "compatible_printers": [],
            "compatible_printers_condition": "printer_model==\"H2D\""}
    (folder / "Bambu PLA Basic @BBL H2D.json").write_text(
        json.dumps(dict(cond, filament_vendor=["Bambu Lab"])), encoding="utf-8")
    (folder / "Generic PLA @BBL H2D.json").write_text(json.dumps(cond), encoding="utf-8")
    s = bbl.Store.load(folder)
    assert lines.choose_parent("Acme", "PLA Matte", "PLA", library=lib, store=s) == (None, "none")
    assert lines.choose_parent("Bambu Lab", "PLA Basic", "PLA", library=lib, store=s) == (None, "none")
    ls: dict = {}
    line = lines.ensure(ls, "Acme", "PLA Matte", "PLA", bambu_parent=None, library=lib, store=s, used_fids=set())
    assert (line.bambu_parent, line.parent_source) == (None, "none")
    probs = lines.problems(ls)
    assert len(probs) == 1 and "acme--pla-matte" in probs[0] and "no Bambu parent" in probs[0]


# ---------- ids, ensure, set_parent ----------

def test_new_filament_id_avoids_used(monkeypatch):
    used = {"P0000001"}
    draws = iter(["0000001", "00000ab"])
    monkeypatch.setattr(lines.secrets, "token_hex", lambda n: next(draws) + "0" * (2 * n - 7))
    assert lines.new_filament_id(used) == "P00000ab"
    monkeypatch.undo()
    seen: set[str] = set(used)
    for _ in range(100):
        fid = lines.new_filament_id(seen)
        assert FID.fullmatch(fid) and fid not in seen
        seen.add(fid)
    assert len(seen) == 101


def test_ensure_user_parent_and_stable_fid(lib, store):
    ls: dict = {}
    used: set[str] = set()
    a = lines.ensure(ls, "SUNLU", "PLA+", "PLA", bambu_parent="Generic PLA", library=lib, store=store,
                     used_fids=used)
    assert (a.bambu_parent, a.parent_source) == ("Generic PLA", "user")
    assert FID.fullmatch(a.filament_id) and a.filament_id in used
    assert a.line_id == "sunlu--pla-plus" and ls[a.line_id] is a and a.created
    b = lines.ensure(ls, "sunlu", "pla+", "PLA", bambu_parent=None, library=lib, store=store, used_fids=used)
    assert b.filament_id == a.filament_id and b.parent_source == "user" and len(ls) == 1


def test_ensure_same_parent_as_chosen_keeps_source(lib, store):
    ls: dict = {}
    a = lines.ensure(ls, "SUNLU", "PLA+", "PLA", bambu_parent="SUNLU PLA+", library=lib, store=store,
                     used_fids=set())
    assert (a.bambu_parent, a.parent_source) == ("SUNLU PLA+", "brand")


def test_ensure_existing_line_takes_new_user_parent(lib, store):
    ls: dict = {}
    a = lines.ensure(ls, "XZN", "PETG", "PETG", bambu_parent=None, library=lib, store=store, used_fids=set())
    assert a.parent_source == "material"
    b = lines.ensure(ls, "XZN", "PETG", "PETG", bambu_parent="Generic PLA", library=lib, store=store,
                     used_fids=set())
    assert (b.bambu_parent, b.parent_source, b.filament_id) == ("Generic PLA", "user", a.filament_id)


def test_set_parent(lib, store):
    ls: dict = {}
    a = lines.ensure(ls, "XZN", "PETG", "PETG", bambu_parent=None, library=lib, store=store, used_fids=set())
    got = lines.set_parent(ls, a.line_id, "Generic PLA")
    assert (got.bambu_parent, got.parent_source) == ("Generic PLA", "user")
    with pytest.raises(KeyError):
        lines.set_parent(ls, "nope--nope", "Generic PLA")


def test_propose(lib, store):
    ls: dict = {}
    p = lines.propose("SUNLU", "PLA+", "PLA", library=lib, store=store, lines=ls)
    assert p == {"line_id": "sunlu--pla-plus", "line": "PLA+", "bambu_parent": "SUNLU PLA+",
                 "parent_source": "brand", "exists": False}
    lines.ensure(ls, "SUNLU", "PLA+", "PLA", bambu_parent="Generic PLA", library=lib, store=store,
                 used_fids=set())
    p = lines.propose("sunlu", " pla+ ", "PLA", library=lib, store=store, lines=ls)
    assert p == {"line_id": "sunlu--pla-plus", "line": "PLA+", "bambu_parent": "Generic PLA",
                 "parent_source": "user", "exists": True}


# ---------- product_of and group ----------

def test_product_of_extra_line_json_encoded(lib):
    assert lines.product_of(_fil(1, "Whatever", line="PLA+ 2.0"), lib) == "PLA+ 2.0"
    f = _fil(1, "Whatever")
    f["extra"]["line"] = "not json"
    assert lines.product_of(f, lib) == "not json"
    f["extra"]["line"] = json.dumps("   ")       # blank -> fall back to the name rules
    assert lines.product_of(f, lib) == "Whatever"


def test_product_of_library_prefix(lib):
    assert lines.product_of(_fil(1, "PLA+ 2.0 Grey"), lib) == "PLA+ 2.0"
    assert lines.product_of(_fil(1, "pla+ 2.0"), lib) == "PLA+ 2.0"
    assert lines.product_of(_fil(1, "PLA+ 2.05 Grey"), lib) == "PLA+ 2.05 Grey"    # not at a word boundary
    assert lines.product_of(_fil(1, "PLA+ 2.0 Grey", vendor="XZN"), lib) == "PLA+ 2.0 Grey"


def test_product_of_prefers_longest_library_product():
    lib2 = make_lib(_local("SUNLU", "PLA+", "PLA"))
    assert lines.product_of(_fil(1, "PLA+ 2.0 Grey"), lib2) == "PLA+ 2.0"
    assert lines.product_of(_fil(1, "PLA+ Grey"), lib2) == "PLA+"


def test_group_creates_lines_and_skips_archived(lib, store):
    fils = [_fil(1, "PLA+ 2.0 Grey"), _fil(2, "PLA+ 2.0 Red"), _fil(3, "PETG Black", vendor="XZN", material="PETG", line="PETG"),
            _fil(4, "PLA+ 2.0 Blue", archived=True), _fil(5, "No vendor", vendor=None)]
    ls: dict = {}
    used: set[str] = set()
    g = lines.group(fils, ls, library=lib, store=store, used_fids=used)
    assert sorted(g) == ["sunlu--pla-plus-2-0", "xzn--petg"]
    assert [f["id"] for f in g["sunlu--pla-plus-2-0"]] == [1, 2]
    assert [f["id"] for f in g["xzn--petg"]] == [3]
    assert sorted(ls) == sorted(g)
    assert ls["xzn--petg"].bambu_parent == "Generic PETG"
    # the library hint "Bambu PLA Tough+" is not in the store; SUNLU has one PLA brand preset
    assert (ls["sunlu--pla-plus-2-0"].bambu_parent, ls["sunlu--pla-plus-2-0"].parent_source) == \
        ("SUNLU PLA+", "brand")
    assert len(used) == 2 and len({l.filament_id for l in ls.values()}) == 2
    fids = {k: v.filament_id for k, v in ls.items()}
    lines.group(fils, ls, library=lib, store=store, used_fids=used)
    assert {k: v.filament_id for k, v in ls.items()} == fids


def test_group_vendor_name_only_in_string_vendor_is_skipped(lib, store):
    f = _fil(1, "X")
    f["vendor"] = {"id": 1, "name": "  "}
    assert lines.group([f], {}, library=lib, store=store, used_fids=set()) == {}


# ---------- persistence ----------

def test_lines_roundtrip_atomic(lib, store):
    assert lines.load() == {}
    ls: dict = {}
    lines.ensure(ls, "SUNLU", "PLA+", "PLA", bambu_parent=None, library=lib, store=store, used_fids=set())
    lines.ensure(ls, "XZN", "PA12-CF", "PA12-CF", bambu_parent=None, library=lib, store=None, used_fids=set())
    lines.save(ls)
    assert lines.load() == ls
    folder = config.paths().state / "profiles"
    assert (folder / "lines.json").is_file()
    assert not list(folder.glob("*.tmp"))


def test_load_skips_broken_rows():
    folder = config.paths().state / "profiles"
    folder.mkdir(parents=True)
    good = {"line_id": "xzn--petg", "vendor": "XZN", "product": "PETG", "material": "PETG",
            "bambu_parent": "Generic PETG", "parent_source": "material", "filament_id": "P0123abc",
            "created": "2026-11-02T00:00:00Z"}
    rows = [good, {"line_id": "bad"}, dict(good, line_id="x--y", filament_id="GFL99"),
            dict(good, line_id="a--b", parent_source="weird"), "junk"]
    (folder / "lines.json").write_text(json.dumps({"version": 1, "lines": rows}), encoding="utf-8")
    assert list(lines.load()) == ["xzn--petg"]
    (folder / "lines.json").write_text("{not json", encoding="utf-8")
    assert lines.load() == {}
