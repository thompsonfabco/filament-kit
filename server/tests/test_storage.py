"""Storage locations (R79): the storage.xml model, the migration from the old keys, the placement rule, how full,
and the rename job. Tests marked skip wait for the amended R79 (design review R457)."""
import copy
import stat
from collections import Counter

import pytest

from filament_kit import config, inventory, storage
from filament_kit.placement import place
from filament_kit.storage import ANY, BULK, CONTAINERS, MATERIALS, Location, Storage, StorageError

RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 3, "overflow": "Overflow",
         "sealed_location": "Sealed stock"}
HELD = "held: R79 is being amended after design review R457 (overflow rule, migration mapping, contract)"


def migrated(rules=None, locations=None) -> Storage:
    return storage.migrate({"locations": locations if locations is not None else
                            ["Sealed stock", "Rack 1", "Storage box", "Overflow"], "placement": rules or RULES})


def names(st):
    return [x.name for x in st.locations]


def where(out):
    return [(i["location"], i.get("count", 1)) for i in out]


@pytest.fixture
def etc(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    return tmp_path / "etc"


# ---- the pinned old cases: an upgraded Hub places every spool as before

OLD_CASES = [   # (items, taken, rules overrides, expected [(location, count)]) from test_placement.py, as it was
    ([{"material": "pla+", "sealed": False, "count": 2}], set(), {}, [("Rack 1", 2)]),
    ([{"material": "PETG", "sealed": False, "count": 3}], {"Storage box 01"}, {},
     [("Storage box 02", 1), ("Storage box 03", 1), ("Overflow", 1)]),
    ([{"material": "ABS", "sealed": False}], set(), {"box_count": 0}, [("Overflow", 1)]),
    ([{"material": "PETG", "sealed": True}, {"material": "PETG"}], set(), {},
     [("Sealed stock", 1), ("Sealed stock", 1)]),
    ([{"material": "PETG", "sealed": False, "location": "Shelf"}], set(), {}, [("Shelf", 1)]),
    ([{"material": "PETG", "sealed": True}, {"material": "PLA", "sealed": False},
      {"material": "ABS", "sealed": False, "count": 2}], set(), {"box_count": 1},
     [("Sealed stock", 1), ("Rack 1", 1), ("Storage box 01", 1), ("Overflow", 1)]),
]


@pytest.mark.parametrize("items,taken,over,expected", OLD_CASES)
def test_an_upgraded_hub_places_every_spool_as_before(items, taken, over, expected):
    st = migrated({**RULES, **over})
    assert where(place(items, taken, st)) == expected


def test_old_rules_dict_goes_through_the_same_single_rule():
    assert where(place([{"material": "PETG", "sealed": False, "count": 3}], {"Storage box 01"}, RULES)) == [
        ("Storage box 02", 1), ("Storage box 03", 1), ("Overflow", 1)]


# ---- migration (the mapping is provisional until R457 is ruled)

def test_migration_default_install_has_the_four_names_in_the_same_roles():
    st = storage.migrate(config.DEFAULTS)
    assert names(st) == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]
    sealed, rack, box, over = st.locations
    assert sealed.sealed and not sealed.overflow
    assert (rack.fill, rack.materials) == (MATERIALS, ["PLA"])
    assert box.type == BULK and box.fill == "none"           # box_count 0: no container set
    assert over.overflow and over.default_overflow
    assert [x.id for x in st.locations] == ["loc-1", "loc-2", "loc-3", "loc-4"] and not st.converted


def test_migration_step1_every_entry_in_order_bulk_no_limit_fill_none():
    st = storage.migrate({"locations": ["B", "a", "b", "C"], "placement": {"pla_location": "", "box_count": 0,
                                                                         "overflow": "C", "sealed_location": "B"}})
    assert names(st) == ["B", "a", "C"]                       # "b" is "B" again (case ignored)
    assert all(x.type == BULK and x.limit is None for x in st.locations)


def test_migration_step2_pla_location_added_at_the_end_if_missing():
    st = storage.migrate({"locations": ["Shelf"], "placement": {"pla_location": "PLA rack", "box_count": 0,
                                                              "overflow": "Shelf", "sealed_location": "Shelf"}})
    assert names(st) == ["Shelf", "PLA rack"]
    assert st.by_name("PLA rack").materials == ["PLA"]


def test_migration_step3_box_entry_becomes_the_container_set_in_its_place():
    st = migrated()
    box = st.by_name("Storage box")
    assert names(st) == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]
    assert (box.type, box.count, box.prefix, box.fill) == (CONTAINERS, 3, "Storage box ", ANY)


def test_migration_step3_prefix_verbatim_and_put_before_overflow_when_no_entry():
    st = migrated({**RULES, "box_prefix": "Dry box  ", "box_count": 12}, ["Rack 1", "Overflow", "Sealed stock"])
    assert names(st) == ["Rack 1", "Dry box", "Overflow", "Sealed stock"]
    assert st.by_name("Dry box").prefix == "Dry box  " and st.by_name("Dry box").container_name(7) == "Dry box  07"


def test_migration_step3_box_count_zero_makes_no_container_set():
    assert all(x.type == BULK for x in migrated({**RULES, "box_count": 0}).locations)


def test_migration_step4_overflow_added_last_when_missing():
    st = migrated({**RULES, "overflow": "Floor"})
    assert names(st)[-1] == "Floor" and st.default_overflow().name == "Floor"


def test_migration_step5_sealed_added_first_when_missing():
    st = migrated({**RULES, "sealed_location": "Safe"})
    assert names(st)[0] == "Safe" and st.sealed_location().name == "Safe"


@pytest.mark.skip(reason=HELD)
def test_migration_clash_overflow_equals_the_box_prefix_keeps_roles_apart_and_says_so():
    st = migrated({**RULES, "overflow": "Storage box"}, ["Sealed stock", "Rack 1", "Storage box"])
    assert st.converted and storage.NOTICE == "Storage locations were converted. Check them."


@pytest.mark.skip(reason=HELD)
def test_migration_clash_pla_location_equals_the_box_prefix():
    assert migrated({**RULES, "pla_location": "Storage box"}).converted


def test_migration_leaves_the_old_keys_in_config_untouched(etc):
    config.save({"locations": ["A", "Overflow", "Sealed stock"], "placement": {"box_count": 2}})
    before = (etc / "config.json").read_bytes()
    st = storage.current()
    assert st.by_name("Storage box").count == 2 and (etc / "storage.xml").exists()
    assert (etc / "config.json").read_bytes() == before


def test_migration_runs_once_after_that_old_keys_are_not_read(etc):
    config.save({"placement": {"box_count": 2}})
    storage.current()
    config.save({"placement": {"box_count": 9}, "locations": ["Other"]})
    assert [x.count for x in storage.current().locations if x.type == CONTAINERS] == [2]


def test_fresh_install_writes_storage_xml_with_the_four_default_names(etc):
    st = storage.current()
    assert names(st) == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]
    assert names(storage.load()) == names(st)


# ---- XML

def full_list() -> Storage:
    return Storage([
        Location("Sealed stock", sealed=True),
        Location("Rack 1", limit=20, fill=MATERIALS, materials=["PLA", "PETG"]),
        Location("Storage box", CONTAINERS, count=12, prefix="Storage box ", fill=ANY),
        Location("Overflow", overflow=True, default_overflow=True)])


def test_xml_round_trip(etc):
    st = full_list()
    storage.save(st)
    back = storage.load()
    assert back.locations == st.locations and [x.id for x in back.locations] == ["loc-1", "loc-2", "loc-3", "loc-4"]
    text = (etc / "storage.xml").read_text(encoding="utf-8")
    assert '<storage version="1"' in text and "<material>PLA</material>" in text and 'prefix="Storage box "' in text


def test_the_file_has_the_mode_of_the_config_file_and_no_temp_left(etc):
    config.save({})
    storage.save(full_list())
    assert stat.S_IMODE((etc / "storage.xml").stat().st_mode) == stat.S_IMODE((etc / "config.json").stat().st_mode)
    assert sorted(p.name for p in etc.iterdir()) == ["config.json", "storage.xml"]


def test_ids_are_never_reused(etc):
    storage.save(full_list())
    st = storage.load()
    st.locations = [x for x in st.locations if x.id != "loc-4"] + [Location("New overflow", overflow=True,
                                                                          default_overflow=True)]
    storage.save(st)
    st = storage.load()
    assert st.locations[-1].id == "loc-5"
    st.locations = [x for x in st.locations if x.id != "loc-5"] + [Location("Again", overflow=True,
                                                                          default_overflow=True)]
    storage.save(st)
    assert storage.load().locations[-1].id == "loc-6"


@pytest.mark.parametrize("text", ["", "<storage", "<other/>", '<storage version="2"/>',
                                  '<storage version="1"><location id="loc-1" name="A" type="bulk" limit="x"/></storage>'])
def test_a_file_that_cannot_be_read_is_an_error_with_a_fix_not_defaults(etc, text):
    etc.mkdir(parents=True)
    (etc / "storage.xml").write_text(text, encoding="utf-8")
    with pytest.raises(StorageError) as e:
        storage.current()
    assert str(e.value).startswith("Error: ") and "\nFix: " in str(e.value)
    assert (etc / "storage.xml").read_text(encoding="utf-8") == text            # nothing was overwritten


def test_a_file_that_is_not_text_is_an_error(etc):
    etc.mkdir(parents=True)
    (etc / "storage.xml").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(StorageError):
        storage.load()


def bad_fields(locations):
    return {(p.row, p.field) for p in storage.validate(locations)}


def test_validation_names_limits_counts_materials_and_the_two_marks():
    ok = full_list().locations
    assert storage.validate(ok) == []
    mod = copy.deepcopy(ok)
    mod[0].name = ""
    mod[3].name = "rack 1"
    mod[1].limit = 0
    mod[2].count = 1000
    assert {(0, "name"), (3, "name"), (1, "limit"), (2, "count")} <= bad_fields(mod)
    mod = copy.deepcopy(ok)
    mod[1].materials = []
    mod[1].name = "x" * 101
    assert {(1, "materials"), (1, "name")} <= bad_fields(mod)
    mod = copy.deepcopy(ok)
    mod[3].default_overflow = False
    assert (None, "default_overflow") in bad_fields(mod)
    mod = copy.deepcopy(ok)
    mod[0].sealed = False
    assert (None, "sealed") in bad_fields(mod)
    mod = copy.deepcopy(ok)
    mod[2].sealed = True
    assert (2, "sealed") in bad_fields(mod)
    mod = copy.deepcopy(ok)
    mod[1].name = "line\nbreak"
    assert (1, "name") in bad_fields(mod)


def test_validation_texts_are_the_catalogue_sentences():
    mod = full_list().locations
    mod[3].name = "rack 1"
    mod[0].name = ""
    texts = {p.error for p in storage.validate(mod)}
    assert {"Enter a name for the location.", "There is already a location called rack 1."} <= texts


def test_save_refuses_an_invalid_list_and_writes_nothing(etc):
    st = full_list()
    st.locations[1].name = "sealed STOCK"
    with pytest.raises(StorageError):
        storage.save(st)
    assert not (etc / "storage.xml").exists()


# ---- the placement rule, steps 1 to 4

def base(*middle) -> Storage:
    st = Storage([Location("Sealed stock", sealed=True), *middle,
                  Location("Overflow", overflow=True, default_overflow=True)])
    for x in st.locations:
        x.id = st.new_id()
    return st


def put(st, material, taken=None, count=1):
    return [(i["location"], i["placed_by"]) for i in place(
        [{"material": material, "sealed": False, "count": count}], taken or {}, st)]


def test_rule1_a_given_location_is_kept_whatever_limits_say():
    st = base(Location("Rack", limit=1, fill=ANY))
    out = place([{"material": "PLA", "location": "Rack"}], {"Rack": 5}, st)
    assert out[0]["location"] == "Rack" and "placed_by" not in out[0]


def test_rule2_sealed_goes_to_the_sealed_location_and_its_limit_is_not_applied():
    st = Storage([Location("Safe", limit=1, sealed=True), Location("Overflow", overflow=True, default_overflow=True)])
    out = place([{"material": "PLA", "count": 3}], {"Safe": 9}, st)
    assert (out[0]["location"], out[0]["count"], out[0]["placed_by"]) == ("Safe", 3, "sealed")


def test_rule3_only_the_longest_matching_material_name_counts():
    st = base(Location("PLA rack", fill=MATERIALS, materials=["PLA"]),
              Location("PLA+ rack", fill=MATERIALS, materials=["pla+"]),
              Location("Anything", fill=ANY))
    assert put(st, "PLA+") == [("PLA+ rack", "material")]
    assert put(st, "PLA-CF") == [("PLA rack", "material")]                 # "pla+" does not match PLA-CF
    assert put(st, "pla") == [("PLA rack", "material")]                     # case ignored


def test_rule3_when_the_own_places_are_full_it_goes_to_overflow_not_to_any_material():
    st = base(Location("PLA rack", limit=2, fill=MATERIALS, materials=["PLA"]), Location("Anything", fill=ANY))
    assert put(st, "PLA", {"PLA rack": 2}) == [("Overflow", "overflow")]
    assert put(st, "PETG", {"PLA rack": 2}) == [("Anything", "any")]        # rule 4: no place names PETG


def test_rule3_own_places_are_tried_in_list_order_and_a_count_is_split():
    st = base(Location("R1", limit=2, fill=MATERIALS, materials=["PLA"]),
              Location("R2", limit=1, fill=MATERIALS, materials=["PLA"]))
    out = place([{"material": "PLA", "sealed": False, "count": 5}], {"R1": 1}, st)
    assert [(i["location"], i["count"]) for i in out] == [("R1", 1), ("R2", 1), ("Overflow", 3)]


def test_rule4_any_material_places_in_list_order_with_room():
    st = base(Location("A", limit=1, fill=ANY), Location("B", fill=ANY))
    assert put(st, "ABS", {"A": 1}) == [("B", "any")]
    assert put(st, "ABS") == [("A", "any")]


def test_a_location_that_takes_nothing_is_never_chosen():
    assert put(base(Location("Manual only")), "ABS") == [("Overflow", "overflow")]


@pytest.mark.skip(reason=HELD)
def test_rule5_overflow_order_default_first_then_list_order():
    st = Storage([Location("Sealed stock", sealed=True), Location("O1", limit=1, overflow=True),
                  Location("O2", overflow=True, default_overflow=True, limit=1), Location("O3", overflow=True)])
    out = place([{"material": "ABS", "sealed": False, "count": 4}], {}, st)
    assert [i["location"] for i in out] == ["O2", "O1", "O3"] and out[-1]["count"] == 2


@pytest.mark.skip(reason=HELD)
def test_rule5_the_default_overflow_never_refuses_when_all_are_at_their_limit():
    st = Storage([Location("Sealed stock", sealed=True), Location("O1", limit=1, overflow=True),
                  Location("O2", overflow=True, default_overflow=True, limit=1)])
    out = place([{"material": "ABS", "sealed": False, "count": 3}], {"O1": 1, "O2": 1}, st)
    assert [(i["location"], i["count"]) for i in out] == [("O2", 3)]


def test_an_overflow_location_is_not_an_own_place():
    st = Storage([Location("Sealed stock", sealed=True),
                  Location("Spill", overflow=True, default_overflow=True, fill=MATERIALS, materials=["PLA"]),
                  Location("Rack", fill=MATERIALS, materials=["PLA"], limit=1)])
    assert put(st, "PLA", {"Rack": 1}) == [("Spill", "overflow")]


def test_containers_take_the_lowest_free_number_two_digits_then_100():
    st = base(Location("Storage box", CONTAINERS, count=100, fill=ANY))
    taken = {f"Storage box {n:02d}" for n in range(1, 100)} - {"Storage box 05"}
    assert put(st, "ABS", taken) == [("Storage box 05", "any")]
    assert put(st, "ABS", taken | {"Storage box 05"}) == [("Storage box 100", "any")]
    assert put(st, "ABS", taken | {"Storage box 05", "Storage box 100"}) == [("Overflow", "overflow")]
    out = place([{"material": "ABS", "sealed": False, "count": 3}], {"Storage box 01"}, st)
    assert [i["location"] for i in out] == ["Storage box 02", "Storage box 03", "Storage box 04"]


def test_containers_default_prefix_is_the_name_plus_one_space_and_frees_gaps():
    st = base(Location("Dry box", CONTAINERS, count=3, fill=ANY))
    assert st.locations[1].container_name(1) == "Dry box 01"
    assert put(st, "ABS", {"Dry box 01", "Dry box 03"}) == [("Dry box 02", "any")]


def test_containers_by_material_name():
    st = base(Location("PETG boxes", CONTAINERS, count=2, fill=MATERIALS, materials=["PETG"]))
    assert put(st, "PETG", count=3) == [("PETG boxes 01", "material"), ("PETG boxes 02", "material"),
                                        ("Overflow", "overflow")]


def test_spools_given_a_location_in_the_same_add_take_room():
    st = base(Location("Box", CONTAINERS, count=2, fill=ANY))
    out = place([{"material": "ABS", "location": "Box 01"}, {"material": "ABS", "sealed": False}], {}, st)
    assert out[1]["location"] == "Box 02"


def test_inputs_not_mutated_with_counters():
    st = base(Location("A", limit=1, fill=ANY))
    used = Counter({"A": 0})
    items = [{"material": "ABS", "sealed": False, "count": 2}]
    before = (copy.deepcopy(items), copy.deepcopy(used))
    place(items, used, st)
    assert (items, used) == before


# ---- how full

def test_how_full_counts_spools_per_name_and_containers_used():
    st = full_list()
    taken = {"Rack 1": 22, "Storage box 01": 1, "Storage box 03": 2, "Storage box 13": 1, "Overflow": 7, "Elsewhere": 4}
    rows = {r["name"]: r for r in st.describe(taken)}
    assert (rows["Rack 1"]["used"], rows["Rack 1"]["free"], rows["Rack 1"]["limit"]) == (22, 0, 20)
    assert (rows["Storage box"]["used"], rows["Storage box"]["free"], rows["Storage box"]["count"]) == (2, 10, 12)
    assert (rows["Overflow"]["used"], rows["Overflow"]["free"]) == (7, None)
    assert [r["position"] for r in st.describe({})] == [1, 2, 3, 4]


def test_how_full_from_a_set_is_the_old_taken_set():
    st = full_list()
    assert st.used(st.by_name("Storage box"), {"Storage box 01", "Storage box 02"}) == 2
    assert st.lowest_free(st.by_name("Storage box"), {"Storage box 01"}) == "Storage box 02"


@pytest.mark.skip(reason=HELD)
def test_the_storage_row_has_the_field_for_automatic_where_and_why():
    assert "reason" in full_list().describe({})[0]


# ---- rename job

class FakeSm:
    def __init__(self, spools):
        self.spools = spools

    def get(self, path):
        assert path == "spool"
        return [dict(s) for s in self.spools]

    def patch(self, path, body):
        sid = int(path.split("/")[1])
        next(s for s in self.spools if s["id"] == sid).update(body)


def test_used_locations_counts_spools_per_location():
    sm = FakeSm([{"id": 1, "location": "Rack 1"}, {"id": 2, "location": "Rack 1"},
                 {"id": 3, "location": "Storage box 01"}, {"id": 4, "location": None}])
    assert inventory._used_locations(sm) == {"Rack 1": 2, "Storage box 01": 1}


def test_rename_updates_the_spools_stored_there_and_says_how_many():
    sm = FakeSm([{"id": 1, "location": "Rack 1"}, {"id": 2, "location": "Rack 1"},
                 {"id": 3, "location": "Storage box 01"}, {"id": 4, "location": None}])
    r = inventory.rename_locations(sm, [storage.Rename("Rack 1", "PLA rack 1")])
    assert r == {"updated": 2, "text": "Renamed Rack 1 to PLA rack 1. 2 spools updated."}
    assert [s["location"] for s in sm.spools] == ["PLA rack 1", "PLA rack 1", "Storage box 01", None]


def test_rename_of_containers_keeps_the_numbers():
    sm = FakeSm([{"id": 3, "location": "Storage box 01"}, {"id": 4, "location": None},
                 {"id": 5, "location": "Storage box 100"}, {"id": 6, "location": "Storage box 1x"}])
    r = inventory.rename_locations(sm, [storage.Rename("Storage box ", "Dry box ", True)])
    assert r["updated"] == 2 and r["text"] == "Renamed Storage box to Dry box. 2 spools updated."
    assert [s["location"] for s in sm.spools] == ["Dry box 01", None, "Dry box 100", "Storage box 1x"]


def test_rename_is_a_job_with_steps_only_above_20_spools():
    sm = FakeSm([{"id": i, "location": "A"} for i in range(1, 21)])
    items = [storage.Rename("A", "B")]
    seen = []
    assert inventory.rename_steps(sm, items) == 0
    inventory.rename_locations(sm, items, step=seen.append)
    assert seen == []
    sm = FakeSm([{"id": i, "location": "A"} for i in range(1, 46)])
    assert inventory.rename_steps(sm, items) == 3
    r = inventory.rename_locations(sm, items, step=seen.append)
    assert seen == ["Updating spools 1 to 20 of 45", "Updating spools 21 to 40 of 45", "Updating spools 41 to 45 of 45"]
    assert r["updated"] == 45 and r["text"] == "Renamed A to B. 45 spools updated."
    assert all(s["location"] == "B" for s in sm.spools)


def test_one_spool_reads_in_the_singular():
    sm = FakeSm([{"id": 1, "location": "A"}])
    assert inventory.rename_locations(sm, [storage.Rename("A", "B")])["text"] == "Renamed A to B. 1 spool updated."


def test_renames_between_two_lists_are_matched_by_id_and_container_prefixes_follow_the_name():
    before = full_list()
    for x in before.locations:
        x.id = before.new_id()
    after = storage.copy_of(before)
    after.locations[1].name = "PLA rack 1"
    after.locations[2].name = "Dry box"
    storage.follow_names(before, after)
    assert storage.renames(before, after) == [storage.Rename("Rack 1", "PLA rack 1"),
                                              storage.Rename("Storage box ", "Dry box ", True)]
    assert storage.renames(before, before) == []


def test_a_prefix_that_differs_from_the_name_does_not_follow_a_rename():
    before = Storage([Location("Sealed stock", sealed=True),
                      Location("Crates", CONTAINERS, count=2, prefix="Storage box ", fill=ANY),
                      Location("Overflow", overflow=True, default_overflow=True)])
    for x in before.locations:
        x.id = before.new_id()
    after = storage.copy_of(before)
    after.locations[1].name = "Boxes"
    storage.follow_names(before, after)
    assert after.locations[1].prefix == "Storage box " and storage.renames(before, after) == []
