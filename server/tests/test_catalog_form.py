"""The catalog form (R83 s4): one function builds the owner's entry from Brand, Name and Material (and the optional
values), the catalog fills what is left out, and the owner's entries are listed and removed."""
import json
import threading

import pytest

import test_generate as tg
from filament_kit import config, library, profiles_api
from filament_kit.profiles import builds
from filament_kit.profiles.errors import ProfileError


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    (tmp_path / "etc").mkdir()


def form(**kw):
    return {"brand": "Acme", "name": "Pla Max", "material": "PLA", **kw}


def problems(f, lib=None):
    with pytest.raises(library.FormError) as ei:
        library.build_entry(f, lib)
    return {p["field"]: p["text"] for p in ei.value.problems}


# ---------- the entry (assumption 2) ----------

def test_three_values_alone_build_a_valid_entry_from_the_catalogs_values_for_the_material():
    lib = library.load()
    assert "PLA" in lib.materials()
    fill = lib.material_values("PLA")
    assert {"nozzle", "bed"} <= set(fill)
    e = library.build_entry(form())
    assert library.validate(e, local=True) == []                 # the check at library.py:83-88 passes
    assert (e["vendor"], e["product"], e["material"]) == ("Acme", "Pla Max", "PLA")
    f = e["fields"]
    lo, hi = fill["nozzle"]
    assert f["nozzle_temperature_range_low"] == [f"{lo:g}"] and f["nozzle_temperature_range_high"] == [f"{hi:g}"]
    assert 150 <= lo <= hi <= 450
    assert e["published_ranges"]["bed_all_plates"]


def test_a_material_is_matched_to_the_catalogs_spelling():
    assert library.build_entry(form(material="pla"))["material"] == "PLA"


def test_the_forms_own_values_win_over_the_catalogs():
    e = library.build_entry(form(nozzle_min="205", nozzle_max="225", bed_min=50, bed_max="60", density="1.3",
                                 max_volumetric_speed=14, bambu_parent="Generic PLA", notes="from the box"))
    assert e["fields"] == {"nozzle_temperature_range_low": ["205"], "nozzle_temperature_range_high": ["225"],
                           "filament_density": ["1.3"], "filament_max_volumetric_speed": ["14"]}
    assert e["published_ranges"] == {"bed_all_plates": "50-60", "_notes": "from the box"}
    assert e["bambu_parent"] == "Generic PLA"


def test_one_end_of_a_range_is_both_ends():
    e = library.build_entry(form(nozzle_min="210", bed_max="55"))
    assert e["fields"]["nozzle_temperature_range_low"] == e["fields"]["nozzle_temperature_range_high"] == ["210"]
    assert e["published_ranges"]["bed_all_plates"] == "55"


def test_other_asks_for_the_nozzle_and_bed_temperatures():
    p = problems(form(material="Moon Dust"))
    assert set(p) == {"nozzle_min", "bed_min"} and "Moon Dust" in p["nozzle_min"]
    assert "nozzle temperature" in p["nozzle_min"] and "bed temperature" in p["bed_min"]
    p = problems(form(material="Moon Dust", nozzle_min="200"))
    assert set(p) == {"bed_min"}
    e = library.build_entry(form(material="Moon Dust", nozzle_min="200", nozzle_max="230", bed_min="40", bed_max="50"))
    assert library.validate(e, local=True) == [] and e["material"] == "Moon Dust"


def test_without_a_downloaded_catalog_every_material_is_other(no_library):
    assert library.load().materials() == []
    assert set(problems(form())) == {"nozzle_min", "bed_min"}
    e = library.build_entry(form(nozzle_min="200", nozzle_max="220", bed_min="55", bed_max="65"))
    assert library.validate(e, local=True) == []


@pytest.mark.parametrize("bad,field", [
    ({"brand": ""}, "brand"), ({"name": "  "}, "name"), ({"material": None}, "material"), ({"brand": 5}, "brand"),
    ({"brand": "x" * 101}, "brand"), ({"nozzle_min": "hot"}, "nozzle_min"), ({"nozzle_min": 100}, "nozzle_min"),
    ({"nozzle_max": True}, "nozzle_max"), ({"bed_min": 200}, "bed_min"), ({"density": 9}, "density"),
    ({"max_volumetric_speed": 0}, "max_volumetric_speed"), ({"bambu_parent": "Generic PLA @BBL X1C"}, "bambu_parent"),
    ({"nozzle_min": 230, "nozzle_max": 200}, "nozzle_min"), ({"bed_min": 70, "bed_max": 60}, "bed_min"),
    ({"notes": "n" * 501}, "notes"), ({"brand": "!!!"}, "brand")])
def test_a_value_that_is_not_an_entry_names_its_field(bad, field):
    assert field in problems(form(**bad))


def test_every_problem_is_listed_at_once():
    assert set(problems({"nozzle_min": "x"})) == {"brand", "name", "material", "nozzle_min"}


def test_a_form_that_is_not_an_object():
    with pytest.raises(library.FormError):
        library.build_entry([1])


def test_the_entry_gives_a_usable_preset(tmp_path):
    """Assumption 2, end to end: a preset is built for a Spoolman filament of the entry's brand and name."""
    e = library.build_entry(form())
    fils = [tg.fil(5, "Pla Max Red", vendor="Acme")]
    manifest, ls = tg.build(tmp_path, fils, lib=tg.make_lib(e))
    mine = [p for p in manifest["presets"] if p["name"].startswith("Acme Pla Max")]
    assert mine and all(p["filament_type"] == "PLA" for p in mine)
    cfg = tg.read(tmp_path, mine[0]["name"])
    lo, hi = (float(x) for x in library.load().material_values("PLA")["nozzle"])
    assert float(cfg["nozzle_temperature_range_low"][0]) == lo and float(cfg["nozzle_temperature_range_high"][0]) == hi


# ---------- storing, listing, removing ----------

def test_add_list_and_remove_an_entry():
    assert library.local_list() == {"entries": []}
    row = library.add_local_form(form(name="Pla Max"))
    assert set(row) == {"id", "brand", "name", "material", "added"}
    assert row["id"] == "acme--pla-max" and row["added"] and (row["brand"], row["material"]) == ("Acme", "PLA")
    library.add_local_form(form(brand="Acme", name="Abs Max", material="ABS"))
    library.add_local_form(form(brand="Zed", name="First"))
    assert [(r["brand"], r["name"]) for r in library.local_list()["entries"]] == [
        ("Acme", "Abs Max"), ("Acme", "Pla Max"), ("Zed", "First")]
    assert library.load().lookup("Acme", "Pla Max").local is not None
    assert library.remove_local("acme--pla-max") is True
    assert library.remove_local("acme--pla-max") is False
    assert library.load().lookup("Acme", "Pla Max").local is None
    assert [r["id"] for r in library.local_list()["entries"]] == ["acme--abs-max", "zed--first"]
    assert library.remove_local("zed--first") is True
    assert not (config.paths().state / "library-local" / "zed").exists()         # an empty brand folder goes
    assert (config.paths().state / "library-local" / "acme" / "abs-max.json").is_file()


@pytest.mark.parametrize("bad", ["", "../x", "acme", "acme--", "--x", "ACME--PLA", "a/b--c", "acme--pla--max", None, 5])
def test_remove_takes_only_a_listed_id(bad):
    library.add_local_form(form())
    assert library.remove_local(bad) is False
    assert len(library.local_list()["entries"]) == 1


def test_remove_never_leaves_the_local_folder(tmp_path):
    (tmp_path / "state" / "secret.json").write_text("{}")
    library.add_local_form(form())
    assert library.remove_local("acme--pla-max")
    assert (tmp_path / "state" / "secret.json").is_file()


def test_the_same_brand_and_name_again_replaces_the_entry():
    library.add_local_form(form(nozzle_min="200", nozzle_max="210", bed_min="50"))
    library.add_local_form(form(nozzle_min="230", nozzle_max="240", bed_min="50"))
    (row,) = library.local_list()["entries"]
    e = library.load().lookup("Acme", "Pla Max").local
    assert e["fields"]["nozzle_temperature_range_low"] == ["230"] and row["id"] == "acme--pla-max"


def test_the_stored_entry_is_the_one_add_local_takes(tmp_path):
    library.add_local_form(form())
    stored = json.loads((tmp_path / "state" / "library-local" / "acme" / "pla-max.json").read_text(encoding="utf-8"))
    assert library.validate(stored, local=True) == [] and library.canonical(stored) == stored


# ---------- profiles_api: what the routes will call ----------

def test_profiles_api_functions(monkeypatch):
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda why: asked.append(why))
    out = profiles_api.add_local_form(form(), "dev1", "library local form")
    assert out["entry"]["id"] == "acme--pla-max" and asked == ["library local"]
    assert profiles_api.local_entries()["entries"][0]["id"] == "acme--pla-max"
    assert "PLA" in profiles_api.local_materials()
    assert profiles_api.remove_local("acme--pla-max", "dev1", "library local remove") == {"removed": True}
    assert asked[-1] == "library local removed"
    n = len(asked)
    with pytest.raises(ProfileError) as ei:
        profiles_api.remove_local("acme--pla-max", "dev1", "library local remove")
    assert ei.value.status == 404 and len(asked) == n                            # nothing to rebuild
    with pytest.raises(ProfileError) as ei:
        profiles_api.add_local_form({"brand": "x"}, "dev1", "library local form")
    assert (ei.value.status, ei.value.code) == (400, "invalid_entry")
    assert {p["field"] for p in ei.value.extra["problems"]} == {"name", "material"}
    assert all(set(p) == {"field", "text"} for p in ei.value.extra["problems"]) and len(asked) == n


def test_concurrent_adds_of_one_entry_leave_one_valid_file():
    library.load()                                  # the test library is put in place once, not by six threads
    ts = [threading.Thread(target=library.add_local_form, args=(form(),)) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(library.local_list()["entries"]) == 1
