"""The pure parts of e2e scenario h (tools/e2e/storage_e2e.py): the fixed spool list, the old release's placement rule
as an oracle (checked against the real v0.6.x placement.place text it copies), placement comparison, the settings
variants and the owner/mode/ACL parsing. No WSL, no network, no kit."""
from __future__ import annotations

import importlib.util
import os
import struct
import subprocess
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parents[2] / "tools" / "e2e"
_spec = importlib.util.spec_from_file_location("storage_e2e_under_test", E2E_DIR / "storage_e2e.py")
se = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se)

MAIN = next(v for v in se.VARIANTS if v["main"])


def test_the_fixed_list_is_fixed_and_hits_every_case():
    items = se.fixed_spools()
    assert items == se.fixed_spools()                                   # the same list every call
    assert len({i["name"] for i in items}) == len(items)
    assert {i["material"] for i in items} >= {"PLA", "PLA+", "PETG", "ABS", "TPU"}
    assert all(isinstance(i["sealed"], bool) for i in items)            # the old rule treats a missing flag as sealed
    assert any(i["sealed"] for i in items) and any(not i["sealed"] for i in items)
    opened_not_pla = sum(i["count"] for i in items if not i["sealed"] and not i["material"].upper().startswith("PLA"))
    assert opened_not_pla > max(v["box_count"] for v in se.VARIANTS)    # more spools than any variant's boxes: overflow


def test_exactly_one_variant_is_upgraded_for_real_and_it_is_set_last():
    assert [v["main"] for v in se.variants_main_last()] == [False, False, True]
    assert se.variants_main_last()[-1] is MAIN


def test_the_variants_cover_a_trailing_space_none_and_no_boxes():
    prefixes = {v["name"]: v["box_prefix"] for v in se.VARIANTS}
    assert any(p.endswith(" ") and p.strip() for p in prefixes.values())
    assert any(p and not p.endswith(" ") for p in prefixes.values())
    blank = [v for v in se.VARIANTS if not v["box_prefix"].strip()]
    assert blank and all(v["box_count"] == 0 for v in blank)
    assert MAIN["box_count"] > 0 and MAIN["overflow"] != "Overflow" and MAIN["pla_location"] != "Rack 1"
    assert MAIN["sealed_location"] != "Sealed stock"


def test_old_rule_main_variant():
    got = se.old_rule(se.fixed_spools(), MAIN)
    where = {(n, i): loc for n, i, loc in got}
    assert where[("E2E PLA Red", 1)] == where[("E2E PLA Red", 2)] == where[("E2E PLA+ Blue", 1)] == "PLA rack"
    assert where[("E2E Sealed PETG White", 1)] == where[("E2E Sealed PLA Gold", 1)] == "Sealed shelf"
    # five opened non-PLA spools into three boxes: PETG 01 02, ABS 03, then TPU hits the overflow twice
    assert [where[("E2E PETG Black", 1)], where[("E2E PETG Black", 2)], where[("E2E ABS Grey", 1)]] == \
        ["Dry box 01", "Dry box 02", "Dry box 03"]
    assert where[("E2E TPU Green", 1)] == where[("E2E TPU Green", 2)] == "Overflow bin"


def test_old_rule_no_space_prefix_and_no_boxes():
    no_space = next(v for v in se.VARIANTS if v["box_prefix"] == "Bin")
    names = [loc for _, _, loc in se.old_rule(se.fixed_spools(), no_space)]
    assert "Bin01" in names and "Bin04" in names and "Bin 01" not in names
    none = next(v for v in se.VARIANTS if v["box_count"] == 0)
    assert {loc for n, _, loc in se.old_rule(se.fixed_spools(), none) if "Sealed" not in n and "PLA" not in n} == {"Garage"}


def test_old_rule_counts_what_is_already_taken():
    one = [i for i in se.fixed_spools() if i["name"] == "E2E ABS Grey"]
    assert se.old_rule(one, MAIN, {"Dry box 01"})[0][2] == "Dry box 02"


def _old_placement_module(tmp_path):
    """v0.6.2's placement.py from the repository's own history, when the tag is here."""
    root = E2E_DIR.parents[1]
    # FK_E2E_GIT_DIR: the repository's .git, for a worktree whose .git file names another OS's path (as run.sh)
    where = ["--git-dir", os.environ["FK_E2E_GIT_DIR"]] if os.environ.get("FK_E2E_GIT_DIR") else ["-C", str(root)]
    try:
        text = subprocess.run(["git", "-c", "safe.directory=*", *where, "show", "v0.6.2:server/filament_kit/placement.py"],
                              capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    if "def place" not in text:
        pytest.skip("the tag v0.6.2 is not in this clone")
    f = tmp_path / "old_placement.py"
    f.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("old_placement", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("variant", se.VARIANTS, ids=lambda v: v["name"])
def test_the_oracle_equals_the_real_old_placement_code(tmp_path, variant):
    old = _old_placement_module(tmp_path)
    s = se.old_settings(variant)
    rules = {"pla_location": s["pla_location"], "box_prefix": s["box_prefix"], "box_count": s["box_count"],
             "overflow": s["overflow"], "sealed_location": s["sealed_location"]}
    # place() keeps one item (with its count) for a sealed or PLA item and one item per spool for the boxes
    expanded, counts = [], {}
    for it in old.place(se.fixed_spools(), set(), rules):
        n = counts.get(it["name"], 0)
        for _ in range(int(it["count"]) if it["placed_by"] in ("sealed", "pla") else 1):
            n += 1
            expanded.append((it["name"], n, it["location"]))
        counts[it["name"]] = n
    assert len(expanded) == 10
    assert se.compare_placements(expanded, se.old_rule(se.fixed_spools(), variant)) == []


def test_compare_placements_names_each_difference():
    a = [("x", 1, "Box 01"), ("x", 2, "Box 02"), ("y", 1, "Rack")]
    assert se.compare_placements(a, list(a)) == []
    diff = se.compare_placements(a, [("x", 1, "Box 01"), ("x", 2, "Overflow"), ("z", 1, "Rack")])
    assert diff == ["x #2: 'Box 02' -> 'Overflow'", "y #1: 'Rack' -> None", "z #1: None -> 'Rack'"]


def test_cli_args_are_the_five_settings_with_the_prefix_kept_as_given():
    args = dict(se.cli_args(MAIN))
    assert args == {"locations": "Sealed shelf,PLA rack,Dry box,Overflow bin,Spare", "placement.pla_location": "PLA rack",
                    "placement.box_prefix": "Dry box ", "placement.box_count": "3", "placement.overflow": "Overflow bin"}
    assert dict(se.cli_args(next(v for v in se.VARIANTS if v["box_prefix"] == " ")))["placement.box_prefix"] == " "


def test_cfg_with_sets_the_six_keys_and_keeps_the_rest():
    cfg = {"port": 8710, "placement": {"pla_location": "x", "other": 1}, "locations": ["a"]}
    out = se.cfg_with(cfg, MAIN)
    assert out["port"] == 8710 and out["placement"]["other"] == 1 and cfg["locations"] == ["a"]
    assert se.old_keys_of(out) == {"locations": MAIN["locations"], "pla_location": "PLA rack",
                                   "box_prefix": "Dry box ", "box_count": 3, "overflow": "Overflow bin",
                                   "sealed_location": "Sealed shelf"}
    assert se.old_keys_of({}) == {"locations": None, "pla_location": None, "box_prefix": None, "box_count": None,
                                  "overflow": None, "sealed_location": None}


ROWS = [
    {"name": "Sealed shelf", "type": "bulk", "sealed": True, "overflow": False, "default_overflow": False,
     "fill": "none", "materials": [], "count": None, "prefix": None, "containers": None},
    {"name": "PLA rack", "type": "bulk", "sealed": False, "overflow": False, "default_overflow": False,
     "fill": "materials", "materials": ["PLA"], "count": None, "prefix": None, "containers": None},
    {"name": "Dry box", "type": "containers", "sealed": False, "overflow": False, "default_overflow": False,
     "fill": "any", "materials": [], "count": 3, "prefix": "Dry box ",
     "containers": [{"name": f"Dry box {n:02d}", "number": n, "taken": False} for n in (1, 2, 3)]},
    {"name": "Overflow bin", "type": "bulk", "sealed": False, "overflow": True, "default_overflow": True,
     "fill": "any", "materials": [], "count": None, "prefix": None, "containers": None},
    {"name": "Spare", "type": "bulk", "sealed": False, "overflow": False, "default_overflow": False,
     "fill": "none", "materials": [], "count": None, "prefix": None, "containers": None},
]


def test_structure_problems_accept_the_right_list_and_name_each_wrong_thing():
    assert se.structure_problems(ROWS, MAIN) == []
    wrong = [dict(r) for r in ROWS]
    wrong[2]["count"], wrong[2]["prefix"] = 4, "Dry box"
    wrong[1]["materials"] = ["PETG"]
    wrong[3]["default_overflow"] = False
    problems = se.structure_problems(wrong, MAIN)
    assert len(problems) == 3 and any("containers set of 3" in p for p in problems)
    assert any("takes PLA" in p for p in problems) and any("default overflow" in p for p in problems)


def test_expected_used_counts_spools_in_bulk_and_taken_containers_in_sets():
    places = [("a", 1, "PLA rack"), ("a", 2, "PLA rack"), ("b", 1, "Dry box 01"), ("c", 1, "Dry box 03"),
              ("d", 1, "Overflow bin")]
    assert se.expected_used(ROWS, places) == {"Sealed shelf": 0, "PLA rack": 2, "Dry box": 2, "Overflow bin": 1,
                                              "Spare": 0}
    assert {"Dry box 02", "PLA rack", "Spare"} <= se.location_texts(ROWS)


def test_parse_stat():
    assert se.parse_stat("root filament-kit 640\n") == ("root", "filament-kit", 0o640)
    assert se.parse_stat("root root 0600") == ("root", "root", 0o600)
    with pytest.raises(ValueError):
        se.parse_stat("stat: cannot statx")


def _acl(entries):
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *e) for e in entries)


def test_decode_acl_names_the_users_and_their_bits():
    data = _acl([(0x01, 6, 0xFFFFFFFF), (0x02, 4, 998), (0x02, 7, 5), (0x04, 4, 0xFFFFFFFF), (0x10, 4, 0xFFFFFFFF),
                 (0x20, 0, 0xFFFFFFFF)])
    assert se.decode_acl(data, {998: "filament-kit-web"}.get) == {"filament-kit-web": "r--", "5": "rwx"}
    with pytest.raises(ValueError):
        se.decode_acl(b"nope", lambda uid: None)


def test_owner_mode_problems():
    cfg = ("root", "filament-kit", 0o640)
    acl = {"filament-kit-web": "r--"}
    assert se.owner_mode_problems(cfg, cfg, acl, dict(acl), "filament-kit-web") == []
    bad = se.owner_mode_problems(cfg, ("filament-kit", "filament-kit", 0o600), acl, {}, "filament-kit-web")
    assert len(bad) == 4 and "owner:group" in bad[0] and "config.json has 640" in bad[1] and "not 640" in bad[2]
    assert "filament-kit-web" in bad[3]
    # config.json has no grant either (a file system without ACLs): equal, so nothing to report here
    assert se.owner_mode_problems(cfg, cfg, {}, {}, "filament-kit-web") == []
