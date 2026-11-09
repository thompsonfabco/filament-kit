import copy

from filament_kit.placement import place

RULES = {
    "pla_location": "Rack 1",
    "box_prefix": "Storage box ",
    "box_count": 3,
    "overflow": "Overflow",
    "sealed_location": "Sealed stock",
}


def test_opened_pla_goes_to_rack():
    out = place([{"material": "pla+", "sealed": False, "count": 2}], set(), RULES)
    assert [i["location"] for i in out] == ["Rack 1"]
    assert out[0]["count"] == 2


def test_opened_petg_count_3_fills_free_boxes_then_overflow():
    items = [{"material": "PETG", "sealed": False, "count": 3}]
    out = place(items, {"Storage box 01"}, RULES)
    assert [i["location"] for i in out] == ["Storage box 02", "Storage box 03", "Overflow"]
    assert [i["count"] for i in out] == [1, 1, 1]


def test_box_count_zero_goes_to_overflow():
    out = place([{"material": "ABS", "sealed": False}], set(), {**RULES, "box_count": 0})
    assert [i["location"] for i in out] == ["Overflow"]


def test_sealed_gets_sealed_location():
    out = place([{"material": "PETG", "sealed": True}, {"material": "PETG"}], set(), RULES)
    assert [i["location"] for i in out] == ["Sealed stock", "Sealed stock"]


def test_given_location_kept():
    out = place([{"material": "PETG", "sealed": False, "location": "Shelf"}], set(), RULES)
    assert out[0]["location"] == "Shelf" and "placed_by" not in out[0]


def test_each_chosen_location_says_which_rule_chose_it():
    out = place([{"material": "PETG", "sealed": True}, {"material": "PLA", "sealed": False},
                 {"material": "ABS", "sealed": False, "count": 2}], set(), {**RULES, "box_count": 1})
    assert [(i["location"], i["placed_by"]) for i in out] == [
        ("Sealed stock", "sealed"), ("Rack 1", "pla"), ("Storage box 01", "box"), ("Overflow", "overflow")]


def test_inputs_not_mutated():
    items = [{"material": "PETG", "sealed": False, "count": 2}, {"material": "PLA", "sealed": False}]
    used = {"Storage box 01"}
    before = (copy.deepcopy(items), set(used))
    place(items, used, RULES)
    assert (items, used) == before
