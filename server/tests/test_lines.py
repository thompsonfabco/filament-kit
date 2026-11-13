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


def _ensure_saved(vendor, product, material, *, bambu_parent, library, store):
    with lines.transaction() as ls:
        return lines.ensure(ls, vendor, product, material, bambu_parent=bambu_parent, library=library, store=store,
                            used_fids=set())


def _group_saved(filaments, *, library, store):
    with lines.transaction() as ls:
        return lines.group(filaments, ls, library=library, store=store, used_fids=set()), ls


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
                 "parent_source": "brand", "orca_parent": "Generic PLA", "orca_parent_source": "material",
                 "exists": False}
    lines.ensure(ls, "SUNLU", "PLA+", "PLA", bambu_parent="Generic PLA", library=lib, store=store,
                 used_fids=set())
    p = lines.propose("sunlu", " pla+ ", "PLA", library=lib, store=store, lines=ls)
    assert p == {"line_id": "sunlu--pla-plus", "line": "PLA+", "bambu_parent": "Generic PLA",
                 "parent_source": "user", "orca_parent": "Generic PLA", "orca_parent_source": "material",
                 "exists": True}


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




# ---------- fix round 1: corrupt files, invalid rows, locking ----------

GOOD_ROW = {"line_id": "xzn--petg", "vendor": "XZN", "product": "PETG", "material": "PETG",
            "bambu_parent": "Generic PETG", "parent_source": "material", "filament_id": "P0123abc",
            "created": "2026-11-02T00:00:00Z"}


def _lines_file() -> Path:
    folder = config.paths().state / "profiles"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "lines.json"


@pytest.mark.parametrize("raw", [b"{not json", b"\xff\xfe", b'{"version": 1, "lines": 5}', b"[1, 2]"])
def test_corrupt_lines_file_moved_aside_and_raises(raw):
    p = _lines_file()
    p.write_bytes(raw)
    with pytest.raises(lines.LineStoreError) as ei:
        lines.load()
    from filament_kit.profiles import errors
    assert isinstance(ei.value, errors.ProfileError)
    assert (ei.value.status, ei.value.code) == (500, "lines_corrupt")
    assert not p.exists()
    aside = list(p.parent.glob("lines.json.corrupt-*"))
    assert len(aside) == 1 and aside[0].read_bytes() == raw
    assert ei.value.extra["moved"] == aside[0].name


def test_corrupt_file_aborts_transaction_without_writing():
    p = _lines_file()
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(lines.LineStoreError):
        with lines.transaction() as ls:
            ls["never"] = None
    assert not p.exists()                       # nothing wrote an empty set over the moved-aside file


def test_missing_file_is_empty_set():
    got = lines.load()
    assert got == {} and isinstance(got, lines.LineSet) and got.invalid == []


def test_invalid_rows_kept_reported_and_their_fids_reserved(lib, store, monkeypatch):
    p = _lines_file()
    rows = [GOOD_ROW, {"line_id": "bad", "filament_id": "P00000aa"},
            dict(GOOD_ROW, line_id="x--y", filament_id="GFL99"),
            dict(GOOD_ROW, line_id="a--b", parent_source="weird"), "junk", dict(GOOD_ROW, vendor="dup")]
    p.write_text(json.dumps({"version": 1, "lines": rows}), encoding="utf-8")
    ls = lines.load()
    assert list(ls) == ["xzn--petg"] and ls["xzn--petg"].vendor == "XZN"
    assert ls.invalid == rows[1:]
    probs = lines.problems(ls)
    assert sum("invalid row kept" in s for s in probs) == 5 and any("(bad)" in s for s in probs)
    draws = iter(["00000aa", "0123abc", "00000bb"])
    monkeypatch.setattr(lines.secrets, "token_hex", lambda n: next(draws) + "0")
    new = lines.ensure(ls, "SUNLU", "PLA+", "PLA", bambu_parent=None, library=lib, store=store, used_fids=set())
    assert new.filament_id == "P00000bb"       # neither the invalid row's id nor a valid line's
    lines.save(ls)
    saved = json.loads(p.read_text(encoding="utf-8"))["lines"]
    assert saved[2:] == rows[1:]               # invalid rows written back unchanged, after the valid lines
    assert [r["line_id"] for r in saved[:2]] == ["sunlu--pla-plus", "xzn--petg"]


def test_old_rows_without_members_load():
    _lines_file().write_text(json.dumps({"version": 1, "lines": [GOOD_ROW]}), encoding="utf-8")
    assert lines.load()["xzn--petg"].filaments == []


class _FakeFcntl:
    LOCK_EX, LOCK_UN = 2, 8

    def __init__(self):
        self.calls = []

    def flock(self, fd, op):
        self.calls.append(op)


def test_locked_uses_flock_on_lines_lock_and_is_reentrant(monkeypatch, lib, store):
    fake = _FakeFcntl()
    monkeypatch.setattr(lines, "fcntl", fake)
    with lines.locked():
        assert (config.paths().state / "profiles" / "lines.lock").is_file()
        with lines.locked():                   # nested: no second flock (it would block on Linux)
            pass
        assert fake.calls == [fake.LOCK_EX]
    assert fake.calls == [fake.LOCK_EX, fake.LOCK_UN]
    fake.calls.clear()
    _ensure_saved("XZN", "PETG", "PETG", bambu_parent=None, library=lib, store=store)
    assert fake.calls == [fake.LOCK_EX, fake.LOCK_UN]


def test_saved_helpers_serialize_threads(lib, store):
    import threading
    errs = []

    def work(i):
        try:
            _ensure_saved("Vend", f"Line {i}", "PLA", bambu_parent=None, library=lib, store=store)
        except Exception as e:  # pragma: no cover - reported below
            errs.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    got = lines.load()
    assert sorted(got) == sorted(f"vend--line-{i}" for i in range(8))
    assert len({l.filament_id for l in got.values()}) == 8
    assert lines.set_parent_saved("vend--line-0", "Generic PLA").parent_source == "user"
    assert lines.load()["vend--line-0"].parent_source == "user"
    with pytest.raises(KeyError):
        lines.set_parent_saved("nope--nope", "Generic PLA")


# ---------- fix round 1: line stability (S12) ----------

def test_group_records_members_and_library_update_does_not_move(store):
    lib_a = make_lib(_local("Acme", "PLA", "PLA"))
    f1 = _fil(1, "PLA Matte Black", vendor="Acme")
    g, ls = _group_saved([f1], library=lib_a, store=store)
    assert list(g) == ["acme--pla"] and ls["acme--pla"].filaments == [1]
    lib_b = make_lib(_local("Acme", "PLA", "PLA"), _local("Acme", "PLA Matte", "PLA"))
    f2 = _fil(2, "PLA Matte Red", vendor="Acme")
    g, ls = _group_saved([f1, f2], library=lib_b, store=store)
    assert [f["id"] for f in g["acme--pla"]] == [1]          # the longer prefix does not move filament 1
    assert [f["id"] for f in g["acme--pla-matte"]] == [2]    # a new filament takes the longer one
    assert not any("moved" in s for s in lines.problems(ls))


def test_explicit_extra_line_moves_and_reports(store):
    lib_a = make_lib(_local("Acme", "PLA", "PLA"))
    f1 = _fil(1, "PLA Matte Black", vendor="Acme")
    _group_saved([f1], library=lib_a, store=store)
    fid = lines.load()["acme--pla"].filament_id
    f1 = _fil(1, "PLA Matte Black", vendor="Acme", line="PLA Matte")
    g, ls = _group_saved([f1], library=lib_a, store=store)
    assert list(g) == ["acme--pla-matte"]
    assert ls["acme--pla-matte"].filaments == [1]
    assert ls["acme--pla"].filaments == [] and ls["acme--pla"].filament_id == fid   # kept, never deleted
    assert any("filament 1 moved from line acme--pla to acme--pla-matte" in s for s in lines.problems(ls))
    saved = lines.load()
    assert saved["acme--pla"].filaments == [] and saved["acme--pla-matte"].filaments == [1]
    # the same extra.line as the recorded line is no move
    g, ls = _group_saved([f1], library=lib_a, store=store)
    assert list(g) == ["acme--pla-matte"] and not any("moved" in s for s in lines.problems(ls))


def test_archived_member_stays_recorded(lib, store):
    f1 = _fil(1, "PETG Black", vendor="XZN", material="PETG", line="PETG")
    _group_saved([f1], library=lib, store=store)
    f1["archived"] = True
    g, ls = _group_saved([f1], library=lib, store=store)
    assert g == {} and ls["xzn--petg"].filaments == [1]


# ---------- fix round 1: line_id collisions, empty slugs ----------

def test_two_names_sharing_a_line_id_are_reported(lib, store):
    ls = lines.LineSet()
    a = lines.ensure(ls, "Acme", "PLA & Silk", "PLA", bambu_parent=None, library=lib, store=store, used_fids=set())
    b = lines.ensure(ls, "Acme", "PLA and Silk", "PLA", bambu_parent=None, library=lib, store=store,
                     used_fids=set())
    assert a is b and a.line_id == "acme--pla-and-silk"
    assert any("two names share line acme--pla-and-silk" in s for s in lines.problems(ls))
    lines.ensure(ls, "ACME", "pla & silk", "PLA", bambu_parent=None, library=lib, store=store, used_fids=set())
    assert sum("two names share" in s for s in lines.problems(ls)) == 1


def test_empty_slug_parts_get_hash_ids(lib):
    import hashlib
    ls = lines.LineSet()
    line = lines.ensure(ls, "Acme", "***", "PLA", bambu_parent=None, library=lib, store=None, used_fids=set())
    assert line.line_id == "acme--x" + hashlib.sha1("***".encode()).hexdigest()[:6]
    jp = "日本"
    assert lines.line_id_for(jp, "PLA") == "x" + hashlib.sha1(jp.encode()).hexdigest()[:6] + "--pla"
    assert lines.line_id_for("Acme", "***") != lines.line_id_for("Acme", "###")
    assert library.line_id("Acme", "***") == "acme--"                  # library.line_id unchanged
    assert lines.propose("Acme", "***", "PLA", library=lib, store=None, lines=ls)["exists"] is True


# ---------- fix round 1: Generic step from the store (S9), "+" (S10), rechoose (S13) ----------

def _store(tmp_path, presets: dict) -> bbl.Store:
    folder = tmp_path / "bbl-x"
    folder.mkdir()
    for name, data in presets.items():
        (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return bbl.Store.load(folder)


def _preset(vendor, ftype, printers=("Bambu Lab H2D 0.4 nozzle",)):
    return {"instantiation": "true", "filament_vendor": [vendor], "filament_type": [ftype],
            "compatible_printers": list(printers)}


def test_generic_tpu_prefers_for_ams(lib, tmp_path):
    s = _store(tmp_path, {"Generic TPU @BBL H2D": _preset("Generic", "TPU"),
                          "Generic TPU for AMS @BBL H2D": _preset("Generic", "TPU-AMS")})
    assert lines.choose_parent("XZN", "TPU", "TPU", library=lib, store=s) == ("Generic TPU for AMS", "material")
    assert lines.choose_parent("XZN", "TPU-GF", "TPU-GF", library=lib, store=s) == \
        ("Generic TPU for AMS", "material")


def test_generic_from_fixture_store_real_types(lib, store):
    # the fixture's "Generic TPU for AMS" has filament_type TPU-AMS; TPU-GF maps to TPU-AMS
    assert lines.choose_parent("XZN", "TPU-GF", "TPU-GF", library=lib, store=store) == \
        ("Generic TPU for AMS", "material")
    assert lines.choose_parent("XZN", "TPU", "TPU", library=lib, store=store) == ("Generic TPU for AMS", "material")
    assert lines.choose_parent("XZN", "PLA-CF", "PLA-CF", library=lib, store=store) == ("Generic PLA-CF", "material")


def test_generic_needs_generic_vendor(lib, tmp_path):
    s = _store(tmp_path, {"Generic PLA @BBL H2D": _preset("Bambu Lab", "PLA"),   # named Generic, wrong vendor
                          "Other PLA @BBL H2D": _preset("Other", "PLA")})
    assert lines.choose_parent("XZN", "Silk", "PLA", library=lib, store=s) == (None, "none")


def test_generic_plain_name_before_others(lib, tmp_path):
    s = _store(tmp_path, {"Generic PLA Silk @BBL H2D": _preset("Generic", "PLA"),
                          "Generic PLA @BBL H2D": _preset("Generic", "PLA"),
                          "Generic PLA High Speed @BBL H2D": _preset("Generic", "PLA")})
    assert lines.choose_parent("XZN", "Silk", "PLA", library=lib, store=s) == ("Generic PLA", "material")


def test_store_without_generic_gives_none(lib, tmp_path):
    s = _store(tmp_path, {"Bambu PETG HF @BBL H2D": _preset("Bambu Lab", "PETG")})
    assert lines.choose_parent("XZN", "PETG", "PETG", library=lib, store=s) == (None, "none")


def test_plus_is_not_dropped_in_brand_match(lib, tmp_path):
    s = _store(tmp_path, {"SUNLU PLA @BBL H2D": _preset("SUNLU", "PLA"),
                          "SUNLU PLA+ @BBL H2D": _preset("SUNLU", "PLA")})
    assert lines.choose_parent("SUNLU", "PLA", "PLA", library=lib, store=s) == ("SUNLU PLA", "brand")
    assert lines.choose_parent("SUNLU", "PLA+", "PLA", library=lib, store=s) == ("SUNLU PLA+", "brand")


def test_rechoose(lib, store, tmp_path):
    ls = lines.LineSet()
    static = lines.ensure(ls, "XZN", "TPU-GF", "TPU-GF", bambu_parent=None, library=lib, store=None,
                          used_fids=set())
    assert (static.bambu_parent, static.parent_source) == ("Generic TPU-AMS", "material")
    empty = _store(tmp_path, {})
    none = lines.ensure(ls, "XZN", "PLA", "PLA", bambu_parent=None, library=lib, store=empty, used_fids=set())
    assert none.parent_source == "none"
    user = lines.ensure(ls, "XZN", "PETG", "PETG", bambu_parent="Generic PLA", library=lib, store=None,
                        used_fids=set())
    fids = {k: l.filament_id for k, l in ls.items()}
    assert lines.rechoose(static, store, library=lib) is static
    assert (static.bambu_parent, static.parent_source) == ("Generic TPU for AMS", "material")
    lines.rechoose(none, store, library=lib)
    assert (none.bambu_parent, none.parent_source) == ("Generic PLA", "material")
    lines.rechoose(user, store, library=lib)
    assert (user.bambu_parent, user.parent_source) == ("Generic PLA", "user")
    assert {k: l.filament_id for k, l in ls.items()} == fids
    # without a library argument it loads the current one (bundled here)
    lines.rechoose(none, None)
    assert none.bambu_parent == "Generic PLA" and none.parent_source == "material"


@pytest.mark.parametrize("raw", ["null", "5", "1.5", "true", "[\"PLA\"]", "{}"])
def test_extra_line_non_string_json_is_ignored(lib, raw):
    f = _fil(1, "PLA+ 2.0 Grey")
    f["extra"]["line"] = raw
    assert lines.product_of(f, lib) == "PLA+ 2.0"


# ---------- fix round 2 ----------

@pytest.mark.parametrize("exc", [PermissionError(13, "denied"), OSError(5, "I/O error"), IsADirectoryError(21, "dir")])
def test_read_error_raises_and_leaves_file_in_place(monkeypatch, exc):
    p = _lines_file()
    raw = json.dumps({"version": 1, "lines": [GOOD_ROW]}).encode("utf-8")
    p.write_bytes(raw)
    real = Path.read_bytes

    def boom(self):
        if self == p:
            raise exc
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(lines.LineStoreError) as ei:
        lines.load()
    assert ei.value.code == "lines_corrupt" and ei.value.extra.get("moved") is None
    with pytest.raises(lines.LineStoreError):
        with lines.transaction():
            pass
    monkeypatch.setattr(Path, "read_bytes", real)
    assert p.read_bytes() == raw                       # never moved aside, never overwritten
    assert not list(p.parent.glob("lines.json.corrupt-*"))
    assert list(lines.load()) == ["xzn--petg"]


def test_filament_in_two_lines_is_reported_and_dropped_from_the_later_one(lib, store):
    p = _lines_file()
    rows = [dict(GOOD_ROW, filaments=[1, 2]),
            dict(GOOD_ROW, line_id="acme--pla", vendor="Acme", product="PLA", filament_id="P0000aaa", filaments=[2, 3])]
    p.write_text(json.dumps({"version": 1, "lines": rows}), encoding="utf-8")
    ls = lines.load()
    assert ls["acme--pla"].filaments == [3] and ls["xzn--petg"].filaments == [1, 2]
    assert any("filament 2 is listed in lines acme--pla and xzn--petg" in s for s in lines.problems(ls))
    lines.save(ls)
    saved = {r["line_id"]: r["filaments"] for r in json.loads(p.read_text(encoding="utf-8"))["lines"]}
    assert saved == {"acme--pla": [3], "xzn--petg": [1, 2]}
    assert not any("listed in lines" in s for s in lines.problems(lines.load()))


# ---------- Task 7c: one parent gate, one text limit ----------

def test_check_parent_gate(store):
    from filament_kit.profiles.errors import ProfileError
    usable = next(b for b in sorted(store.bases()) if lines.usable(store, b))
    lines.check_parent(usable, store)
    lines.check_parent("No Such Preset", None)          # no store uploaded yet: anything, re-checked at build
    lines.check_parent("", store)                       # blank: nothing to check
    lines.check_parent("   ", store)
    with pytest.raises(ProfileError) as e:
        lines.check_parent("No Such Preset", store)
    assert (e.value.status, e.value.code, e.value.extra) == (400, "unknown_parent", {"parent": "No Such Preset"})
    assert "not a usable Bambu Studio system preset" in e.value.message
    assert not isinstance(e.value, ValueError)


@pytest.mark.parametrize("value, problem", [
    ("PETG HF", None), ("  " + "x" * 100 + "  ", None), ("x" * 101, "is longer than 100 characters"),
    ("PETG @BBL H2D", "may not contain '@'"), (5, "must be text"),
])
def test_text_problem(value, problem):
    got = lines.text_problem(value)
    assert got == problem if problem is None else problem in got


def test_text_problem_at_allowed_when_asked():
    assert lines.text_problem("a@b", at_ok=True) is None
