"""`spoolwarden locations` (06 9.15), the Storage locations screen of `config` (8.3), the six old keys `config set`
refuses, and the installer's storage question (SL3). The changes go through `storage_api.save`, the Hub page's own path,
so these tests pin what the command line adds to it: the words, the exit codes, the Error and Fix lines, the asking and
the screens. Example names only."""
from __future__ import annotations

import builtins
import io
import json
import sys

import pytest
from starlette.testclient import TestClient

from filament_kit import apply, cli, config, inventory, output, pairing, storage, storage_api
from filament_kit.api import create_app
from filament_kit.spoolman import SpoolmanError
from filament_kit.storage import ANY, CONTAINERS, MATERIALS, Location, Storage


class FakeSm:
    def __init__(self, spools=()):
        self.spools = [{"id": i, "location": p} for i, p in enumerate(spools, 1)]
        self.fail_at = None

    def get(self, path):
        assert path == "spool"
        return [dict(s) for s in self.spools]

    def patch(self, path, body):
        sid = int(path.split("/")[1])
        if self.fail_at == sid:
            self.fail_at = None
            raise SpoolmanError("down", 500)
        next(s for s in self.spools if s["id"] == sid).update(body)


def listing() -> Storage:
    """Sealed stock, Rack 1 (20 spools, PLA), Storage box (12 containers, any material), Overflow (the default)."""
    return Storage([
        Location("Sealed stock", sealed=True),
        Location("Rack 1", limit=20, fill=MATERIALS, materials=["PLA"]),
        Location("Storage box", CONTAINERS, count=12, prefix="Storage box ", fill=ANY),
        Location("Overflow", overflow=True, default_overflow=True)])


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k, d in (("ETC", "etc"), ("STATE", "state"), ("OPT", "opt"), ("BACKUPS", "bk")):
        monkeypatch.setenv(f"FK_{k}", str(tmp_path / d))
        (tmp_path / d).mkdir()
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(cli, "_hub_audit", lambda what: None)
    storage.save(listing())
    return tmp_path


@pytest.fixture
def sm():
    return FakeSm(["Rack 1"] * 18 + ["Sealed stock"] * 4 + ["Storage box 02"] * 1 + ["Overflow"] * 7)


def run(capsys, sm, *argv, stdin=None, monkeypatch=None):
    """(exit code, standard output, standard error) of `spoolwarden <argv>` with `sm` as Spoolman."""
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    try:
        rc = cli.main(list(argv), sm_factory=lambda: sm)
    except SystemExit as e:
        rc = e.code
    got = capsys.readouterr()
    return rc, got.out, got.err


def names() -> list[str]:
    return [x.name for x in storage.current().locations]


def asking(monkeypatch, *answers):
    """Standard input is a terminal that answers each question with the next answer."""
    left = list(answers)
    monkeypatch.setattr(output, "terminal", lambda: True)

    def fake_input(prompt=""):
        print(prompt, end="")
        if not left:
            raise EOFError
        return left.pop(0)
    monkeypatch.setattr(builtins, "input", fake_input)


# ================================================================ the list

def test_locations_prints_the_list_as_a_table_in_fill_order(capsys, sm):
    rc, out, err = run(capsys, sm, "locations")
    lines = out.splitlines()
    assert rc == 0 and err == ""
    assert lines[0] == "4 locations - 2 with a limit"
    assert lines[1].split() == ["POS", "NAME", "TYPE", "HOW", "FULL", "TAKES", "MARKS"]
    assert lines[2].split()[0] == "1" and "Sealed stock" in lines[2] and "4 spools" in lines[2]
    assert "Sealed spools" in lines[2] and "Only when chosen" in lines[2]
    assert "Rack 1" in lines[3] and "18 of 20" in lines[3] and "Bulk storage" in lines[3] and lines[3].rstrip().endswith("PLA")
    assert "Storage box" in lines[4] and "Containers" in lines[4] and "1 of 12" in lines[4] and "Any material" in lines[4]
    assert "Overflow" in lines[5] and "7 spools" in lines[5] and lines[5].rstrip().endswith("Default overflow")
    assert out.rstrip().endswith("The places fill in this order. Change them: sudo spoolwarden locations -h")
    assert all(len(line) <= 79 for line in lines)
    assert run(capsys, sm, "locations", "list")[:2] == (0, out)


def test_a_location_over_its_limit_shows_22_of_20_and_materials_are_listed(capsys, sm):
    sm.spools += [{"id": 100 + i, "location": "Rack 1"} for i in range(4)]
    st = storage.current()
    st.locations[1].materials = ["PLA", "PETG"]
    storage.save(st)
    out = run(capsys, sm, "locations")[1]
    assert "22 of 20" in out and "PLA, PETG" in out


def test_the_list_says_when_the_default_overflow_has_no_limit_and_two_places_overflow(capsys, sm):
    st = storage.current()
    st.locations.append(Location("Overflow 2", overflow=True))
    storage.save(st)
    rc, out, err = run(capsys, sm, "locations")
    assert rc == 0 and "Overflow, Default overflow" in out
    assert " ".join(err.split()) == "Note: " + storage.DEFAULT_OVERFLOW_NOTE


def test_locations_json_is_the_answer_of_get_api_storage(capsys, sm, tmp_path):
    rc, out, _ = run(capsys, sm, "locations", "--json")
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    c = TestClient(create_app(sm=sm))
    tok = pairing.redeem_code(pairing.issue().code)
    served = c.get("/api/storage", headers={"Authorization": f"Bearer {tok}"}).json()
    assert rc == 0 and json.loads(out) == served == storage_api.current_view(sm)
    assert list(json.loads(out)) == ["locations", "order_by_material", "everything_else", "notices"]
    assert "Note:" not in out


def test_the_list_without_spoolman_says_so(capsys):
    class Down(FakeSm):
        def get(self, path):
            raise SpoolmanError("connection refused", 0)
    rc, out, err = run(capsys, Down(), "locations")
    assert rc == 1 and out == "" and err.startswith("Error: Spoolman did not answer")


# ================================================================ add

def test_add_puts_the_new_location_last_and_says_so(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "add", "Rack 2", "--limit", "20", "--takes", "PLA, PETG")
    assert (rc, out, err) == (0, "Added Rack 2.\n", "")
    assert names() == ["Sealed stock", "Rack 1", "Storage box", "Overflow", "Rack 2"]
    rack = storage.current().by_name("rack 2")
    assert (rack.type, rack.limit, rack.fill, rack.materials) == ("bulk", 20, MATERIALS, ["PLA", "PETG"])


def test_add_without_options_is_bulk_with_no_limit_that_takes_nothing(capsys, sm):
    assert run(capsys, sm, "locations", "add", "Drawer")[0] == 0
    drawer = storage.current().by_name("Drawer")
    assert (drawer.type, drawer.limit, drawer.fill, drawer.overflow) == ("bulk", None, "none", False)


def test_add_containers_with_a_count_and_takes_any(capsys, sm):
    rc, out, _ = run(capsys, sm, "locations", "add", "Bags", "--type", "containers", "--count", "5", "--takes", "any")
    bags = storage.current().by_name("Bags")
    assert rc == 0 and (bags.type, bags.count, bags.fill) == (CONTAINERS, 5, ANY) and bags.container_name(2) == "Bags 02"


def test_add_an_overflow_place_prints_the_note_when_the_default_has_no_limit(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "add", "Garage", "--overflow", "--limit", "10")
    assert rc == 0 and out == "Added Garage.\n"
    assert "Note: The default overflow has no limit" in " ".join(err.split())


@pytest.mark.parametrize("argv, rc, error, fix", [
    (["add", "rack 1"], 1, "Error: There is already a location called rack 1.", None),
    (["add", "Rack 2", "--limit", "many"], 1, "Error: Enter a whole number, 1 or more.", None),
    (["add", "Rack 2", "--limit", "0"], 1, "Error: Enter a whole number, 1 or more.", None),
    (["add", "Bags", "--type", "containers", "--count", "x"], 1, "Error: Enter a whole number, 1 or more.", None),
    (["add", "Rack 2", "--takes", ","], 1, "Error: Enter at least one material, e.g. PLA.", None),
    (["add", "Rack 2", "--takes", "any", "--overflow"], 1,
     "Error: an overflow location cannot take any material automatically.", "Fix: use --takes none or name the materials."),
    (["add", "Rack 2", "--type", "containers", "--limit", "5"], 2, "Error: --limit is for Bulk storage.", None),
    (["add", "Rack 2", "--count", "5"], 2, "Error: --count is for Containers.", None),
    (["add", "Storage box 03"], 1, "Error: Storage box 03 is the name of a container in Storage box.", None),
])
def test_add_refusals_are_error_lines_with_the_right_exit_code_and_nothing_is_saved(capsys, sm, argv, rc, error, fix):
    got, out, err = run(capsys, sm, "locations", *argv)
    assert got == rc and out == "" and err.splitlines()[0].startswith(error)
    if fix:
        assert fix in err
    assert "Fix:" in err or rc == 2
    assert names() == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]


def test_a_change_needs_root_and_names_the_command(capsys, sm, monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    rc, out, err = run(capsys, sm, "locations", "add", "Rack 2")
    assert rc == 3 and "Error: this needs administrator rights." in err and "sudo spoolwarden locations add" in err
    assert names() == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]
    assert run(capsys, sm, "locations")[0] == 0              # reading needs none


# ================================================================ edit

def test_edit_changes_what_is_given_and_leaves_the_rest(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "edit", "RACK 1", "--limit", "25", "--takes", "PETG")
    rack = storage.current().by_name("Rack 1")
    assert (rc, out, err) == (0, "Changed Rack 1.\n", "") and (rack.limit, rack.materials) == (25, ["PETG"])
    assert run(capsys, sm, "locations", "edit", "Rack 1", "--limit", "none")[0] == 0
    assert storage.current().by_name("Rack 1").limit is None


def test_edit_with_nothing_new_is_unchanged(capsys, sm):
    assert run(capsys, sm, "locations", "edit", "Rack 1", "--limit", "20")[:2] == (0, "Unchanged.\n")


def test_edit_rename_renames_the_spools_stored_there(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "edit", "Rack 1", "--name", "PLA rack 1")
    assert (rc, err) == (0, "") and out == "Renamed Rack 1 to PLA rack 1. 18 spools updated.\n"
    assert sum(s["location"] == "PLA rack 1" for s in sm.spools) == 18 and "Rack 1" not in names()


def test_edit_rename_of_a_containers_location_renames_its_containers_and_prefix(capsys, sm):
    rc, out, _ = run(capsys, sm, "locations", "edit", "Storage box", "--name", "Dry box")
    assert rc == 0 and out == "Renamed Storage box to Dry box. 1 spool updated.\n"
    assert any(s["location"] == "Dry box 02" for s in sm.spools)
    assert storage.current().by_name("Dry box").container_prefix() == "Dry box "


def test_a_rename_of_more_than_20_spools_runs_as_a_job_and_resumes_after_a_failure(capsys):
    big = FakeSm(["Rack 1"] * 45)
    big.fail_at = 30
    rc, out, err = run(capsys, big, "locations", "edit", "Rack 1", "--name", "PLA rack 1")
    assert rc == 1 and out == "" and err.startswith("Error: ") and "down" in err and "Fix: " in err
    assert "Rack 1" in names() and any(s["location"] == "PLA rack 1" for s in big.spools)     # half done, list unchanged
    rc, out, err = run(capsys, big, "locations", "edit", "Rack 1", "--name", "PLA rack 1")
    assert (rc, err) == (0, "") and out == "Renamed Rack 1 to PLA rack 1. 45 spools updated.\n"
    assert all(s["location"] == "PLA rack 1" for s in big.spools) and "PLA rack 1" in names()


def test_a_different_rename_while_one_is_half_done_is_refused_with_error_and_fix(capsys):
    big = FakeSm(["Rack 1"] * 45)
    big.fail_at = 30
    run(capsys, big, "locations", "edit", "Rack 1", "--name", "PLA rack 1")
    rc, out, err = run(capsys, big, "locations", "edit", "Rack 1", "--name", "Other")
    assert rc == 1 and err.startswith("Error: ") and "Fix: " in err and "not finished" in err


@pytest.mark.parametrize("argv, error", [
    (["edit", "Overflow", "--no-overflow"], "Error: Make another location the default overflow first."),
    (["edit", "Storage box", "--type", "bulk"], "Error: Move the spools out to change the type."),
    (["edit", "Storage box", "--count", "1"], "Error: Storage box 02 holds spools. Move it first, or keep at least 2."),
    (["edit", "Rack 1", "--name", "Sealed stock"], "Error: There is already a location called Sealed stock."),
    (["edit", "Rack 1", "--takes", "any", "--overflow"], "Error: an overflow location cannot take any material"),
])
def test_edit_refusals_have_error_and_fix_and_exit_code_1(capsys, sm, argv, error):
    before = storage.current().describe(inventory._used_locations(sm))
    rc, out, err = run(capsys, sm, "locations", *argv)
    assert rc == 1 and out == "" and err.startswith(error) and "Fix:" in err
    assert storage.current().describe(inventory._used_locations(sm)) == before


def test_a_name_that_matches_no_location_is_exit_code_2_and_lists_the_names(capsys, sm):
    for argv in (["edit", "Nowhere", "--limit", "5"], ["move", "Nowhere", "--first"], ["remove", "Nowhere", "--yes"],
                 ["default-overflow", "Nowhere"], ["sealed", "Nowhere"], ["move", "Rack 1", "--before", "Nowhere"]):
        rc, out, err = run(capsys, sm, "locations", *argv)
        assert rc == 2 and out == "" and err.startswith('Error: there is no location called "Nowhere".'), argv
        assert "Rack 1" in err and "Fix:" in err


# ================================================================ move, remove, default overflow, sealed

def test_move_first_last_and_before(capsys, sm):
    assert run(capsys, sm, "locations", "move", "Overflow", "--first")[:2] == (0, "Moved Overflow first.\n")
    assert names() == ["Overflow", "Sealed stock", "Rack 1", "Storage box"]
    assert run(capsys, sm, "locations", "move", "Overflow", "--last")[:2] == (0, "Moved Overflow last.\n")
    assert run(capsys, sm, "locations", "move", "storage box", "--before", "rack 1")[:2] == (
        0, "Moved Storage box before Rack 1.\n")
    assert names() == ["Sealed stock", "Storage box", "Rack 1", "Overflow"]
    assert run(capsys, sm, "locations", "move", "Rack 1", "--before", "Overflow")[:2] == (0, "Unchanged.\n")


def test_move_needs_one_of_first_last_before_and_not_itself(capsys, sm):
    assert run(capsys, sm, "locations", "move", "Rack 1")[0] == 2
    assert run(capsys, sm, "locations", "move", "Rack 1", "--first", "--last")[0] == 2
    rc, out, err = run(capsys, sm, "locations", "move", "Rack 1", "--before", "Rack 1")
    assert rc == 2 and err.startswith("Error: Rack 1 cannot go before itself.")


def test_remove_asks_the_hub_pages_question_and_removes_on_yes(capsys, sm, monkeypatch):
    asking(monkeypatch, "y")
    rc, out, err = run(capsys, sm, "locations", "remove", "Rack 1")
    assert rc == 0 and err == ""
    assert " ".join(out.split()).startswith("Remove Rack 1? 18 spools are recorded there. They keep that location until "
                                            "you move them; it is no longer offered for new spools. [y/N]")
    assert out.rstrip().endswith("Removed Rack 1.") and "Rack 1" not in names()
    assert sum(s["location"] == "Rack 1" for s in sm.spools) == 18                 # the spools keep their text


def test_remove_says_no_spools_are_recorded_when_there_are_none(capsys, sm, monkeypatch):
    st = storage.current()
    st.locations.append(Location("Drawer"))
    storage.save(st)
    asking(monkeypatch, "y")
    out = " ".join(run(capsys, sm, "locations", "remove", "Drawer")[1].split())
    assert "Remove Drawer? No spools are recorded there." in out and out.endswith("Removed Drawer.")


def test_remove_answered_no_changes_nothing_and_yes_flag_skips_the_question(capsys, sm, monkeypatch):
    asking(monkeypatch, "n")
    rc, out, _ = run(capsys, sm, "locations", "remove", "Rack 1")
    assert rc == 5 and "Nothing changed." in out and "Rack 1" in names()
    rc, out, _ = run(capsys, sm, "locations", "remove", "Rack 1", "--yes")
    assert (rc, out) == (0, "Removed Rack 1.\n") and "Rack 1" not in names()


def test_remove_with_no_terminal_and_no_yes_is_exit_code_2(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "remove", "Rack 1")
    assert rc == 2 and out == "" and "needs a yes" in err and "Rack 1" in names()


def test_remove_refuses_the_default_overflow_and_the_sealed_location_without_asking(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "remove", "Overflow")
    assert rc == 1 and out == "" and err.splitlines() == [
        "Error: Make another location the default overflow first.",
        "Fix: sudo spoolwarden locations default-overflow <name>"]
    rc, out, err = run(capsys, sm, "locations", "remove", "Sealed stock")
    assert rc == 1 and err.splitlines()[0] == "Error: Choose another location for sealed spools first."
    assert err.splitlines()[1] == "Fix: sudo spoolwarden locations sealed <name>"


def test_default_overflow_on_a_bulk_location_that_is_not_overflow_makes_it_overflow_too(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "default-overflow", "Rack 1")
    now = storage.current()
    assert (rc, out) == (0, "Made Rack 1 the default overflow.\n")
    assert now.by_name("Rack 1").default_overflow and now.by_name("Rack 1").overflow
    assert not now.by_name("Overflow").default_overflow and now.by_name("Overflow").overflow
    assert run(capsys, sm, "locations", "default-overflow", "Rack 1")[:2] == (0, "Unchanged.\n")


def test_default_overflow_on_a_containers_location_is_an_error_with_a_fix(capsys, sm):
    rc, out, err = run(capsys, sm, "locations", "default-overflow", "Storage box")
    assert rc == 1 and out == "" and err.splitlines() == [
        "Error: Storage box cannot be the default overflow.", "Fix: choose a Bulk storage location."]


def test_default_overflow_on_a_place_that_takes_any_material_says_how_to_fix_it(capsys, sm):
    assert run(capsys, sm, "locations", "add", "Shelf", "--takes", "any")[0] == 0
    rc, out, err = run(capsys, sm, "locations", "default-overflow", "Shelf")
    assert rc == 1 and err.startswith("Error: An overflow location cannot take any material automatically.")
    assert "locations edit Shelf --takes none" in err


def test_sealed_moves_the_role_and_refuses_containers(capsys, sm):
    rc, out, _ = run(capsys, sm, "locations", "sealed", "Rack 1")
    assert (rc, out) == (0, "Sealed spools now go to Rack 1.\n")
    now = storage.current()
    assert now.by_name("Rack 1").sealed and not now.by_name("Sealed stock").sealed
    rc, out, err = run(capsys, sm, "locations", "sealed", "Storage box")
    assert rc == 1 and err.splitlines()[1] == "Fix: choose a Bulk storage location."


def test_every_change_prints_one_json_document_with_json(capsys, sm):
    rc, out, _ = run(capsys, sm, "locations", "add", "Rack 2", "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["ok"] is True and [r["name"] for r in doc["locations"]][-1] == "Rack 2"


# ================================================================ the six old keys

@pytest.mark.parametrize("key", ["locations", "placement.pla_location", "placement.box_prefix", "placement.box_count",
                                 "placement.overflow", "placement.sealed_location"])
def test_config_set_refuses_the_old_storage_keys(capsys, key):
    before = config.load()
    try:
        rc = cli.main(["config", "set", key, "Shelf B"])
    except SystemExit as e:
        rc = e.code
    got = capsys.readouterr()
    assert rc == 2 and got.out == ""
    assert got.err.splitlines() == ["Error: storage locations are a list now.", "Fix: spoolwarden locations"]
    assert config.load() == before


def test_config_show_prints_the_locations_as_a_numbered_list(capsys, sm):
    rc, out, _ = run(capsys, sm, "config", "show")
    block = out[out.index("Storage locations"):]
    lines = block.splitlines()[1:5]
    assert rc == 0 and [ln.split()[0] for ln in lines] == ["1", "2", "3", "4"]
    assert "Rack 1" in lines[1] and "18 of 20 spools" in lines[1] and "PLA" in lines[1]
    assert "9 of 12" not in out and "1 of 12 containers used" in lines[2] and "Default overflow" in lines[3]
    doc = json.loads(run(capsys, sm, "config", "show", "--json")[1])
    group = next(g for g in doc["groups"] if g["group"] == "Storage locations")
    assert group["items"][0]["label"] == "Locations" and [r["name"] for r in group["items"][0]["value"]][1] == "Rack 1"
    assert not any(k in doc["values"] for k in ("locations", "placement.pla_location", "placement.overflow"))


# ================================================================ the screens of `config`

def menu(capsys, sm, monkeypatch, script):
    monkeypatch.setattr(sys, "stdin", io.StringIO(script))
    rc = cli.main(["config", "--numbered"], sm_factory=lambda: sm)
    got = capsys.readouterr()
    return rc, got.out, got.err


def test_the_main_list_summarises_the_locations(capsys, sm, monkeypatch):
    rc, out, _ = menu(capsys, sm, monkeypatch, "q\n")
    row = next(ln for ln in out.splitlines() if "Storage locations" in ln and ln.strip().startswith("3"))
    assert rc == 0 and row.split("Storage locations")[1].strip() == "4 locations - 2 with a limit"


def test_the_storage_screen_lists_the_rows_and_a_number_opens_one(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n2\nq\nq\nq\n")
    assert (rc, err) == (0, "")
    assert "Settings > Storage locations" in out
    assert "a add   m move   r remove   s save   q back   ? help" in out
    rows = [ln for ln in out.splitlines() if ln.strip()[:1].isdigit() and ("of 12" in ln or "spools -" in ln)]
    assert "Sealed stock" in rows[0] and "4 spools - Only when chosen - Sealed spools" in rows[0]
    assert "Rack 1" in rows[1] and "18 of 20 spools - PLA" in rows[1]
    assert "1 of 12 containers used - Any material" in rows[2] and "7 spools - Only when chosen - Default overflow" in rows[3]
    after = out[out.index("Rack 1\n\n   1  Name"):]
    fields = [" ".join(ln.split()) for ln in after.splitlines()[2:9]]
    assert "1 Name Rack 1" in fields and "2 Type Bulk storage (fixed: 18 spools are here)" in fields
    assert "3 Spool limit 20" in fields and "4 Filled automatically with These materials" in fields
    assert "5 Materials PLA" in fields and "6 Use as overflow no" in fields and "7 Sealed spools go here no" in fields


def test_a_wrong_limit_is_an_error_and_asks_again_then_a_change_is_staged_and_saved_with_s(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n2\n3\nlots\n\n3\n25\nq\nq\ns\nq\n")
    assert rc == 0
    assert err.count("Error: Enter a whole number, 1 or more.") == 1
    assert "Spool limit [20]: Spool limit [20]: Unchanged." in out.replace("\n", " ")
    assert "Changed, not saved yet." in out and "Settings - workshop-hub - 1 change not saved" in out
    assert "Saved 1 change: storage locations." in out
    assert storage.current().by_name("Rack 1").limit == 25


def test_leaving_with_a_staged_change_asks_and_saves_nothing(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n2\n3\n25\nq\nq\nq\ny\n")
    assert rc == 5 and "Leave without saving 1 change (Storage locations)? [y/N]" in out and "Nothing saved." in out
    assert storage.current().by_name("Rack 1").limit == 20


def test_a_rename_in_the_menu_renames_the_spools_on_save(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n2\n1\nPLA rack 1\nq\nq\ns\nq\n")
    assert rc == 0 and "Saved 1 change: storage locations." in out and "Renamed Rack 1 to PLA rack 1. 18 spools updated." in out
    assert sum(s["location"] == "PLA rack 1" for s in sm.spools) == 18 and "PLA rack 1" in names()


def test_add_move_and_remove_in_the_menu(capsys, sm, monkeypatch):
    script = ("3\n"
              "a\nDrawer\n1\n\nn\n1\n"          # name, type 1 = Bulk storage, no limit, not overflow, fill 1 = nothing
              "m\n5\n1\n"                         # move the 5th (Drawer) to position 1
              "r\n1\ny\n"                         # remove the 1st (Drawer again)
              "q\nq\n")
    rc, out, err = menu(capsys, sm, monkeypatch, script)
    text = " ".join(out.split())
    assert err == "" and "Name: " in out and "Move which location? Number: " in out
    assert "Put it at position [5]: " in out and "Remove which location? Number: " in out
    assert "Remove Drawer? No spools are recorded there. [y/N]" in text
    assert names() == ["Sealed stock", "Rack 1", "Storage box", "Overflow"]        # nothing saved: ended with `y` to leave


def test_a_staged_add_is_saved_as_the_last_location(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\na\nDrawer\n1\n12\nn\n3\nPLA, PETG\nq\ns\nq\n")
    drawer = storage.current().by_name("Drawer")
    assert rc == 0 and err == "" and names()[-1] == "Drawer"
    assert (drawer.limit, drawer.fill, drawer.materials) == (12, MATERIALS, ["PLA", "PETG"])


def test_the_default_overflow_and_the_sealed_location_cannot_be_removed_or_switched_off_in_the_menu(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\nr\n4\nr\n1\n3\n4\nq\nq\nq\n")
    assert "Error: Make another location the default overflow first." in err
    assert "Error: Choose another location for sealed spools first." in err
    assert "Leave without" not in out and rc == 0


def test_a_type_with_spools_in_it_is_fixed_and_a_new_name_clash_is_an_error(capsys, sm, monkeypatch):
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n3\n2\n1\nq\nq\nq\n")           # Storage box, Type, Bulk storage
    assert "Error: Move the spools out to change the type." in err
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n2\n1\nOverflow\n\nq\nq\nq\n")
    assert "Error: There is already a location called Overflow." in err and rc == 0


def test_a_save_of_the_menu_refused_by_the_save_path_keeps_the_changes(capsys, sm, monkeypatch):
    sm.spools.append({"id": 99, "location": "Storage box 12"})
    rc, out, err = menu(capsys, sm, monkeypatch, "3\n3\n3\n5\nq\nq\nq\n")           # Number of containers -> 5
    assert "Storage box 12 holds spools" in err


# ================================================================ the installer's question

def test_the_installers_storage_question_opens_the_new_list_and_writes_the_list_on_q(capsys, monkeypatch):
    (config.paths().etc / "storage.xml").unlink()
    cfg = config.load()
    monkeypatch.setattr(sys, "stdin", io.StringIO("2\n3\n30\nq\n"))
    cli._storage_menu(cfg)
    out = capsys.readouterr().out
    assert "Settings > Storage locations" in out and "s save" not in out
    assert storage.current().locations[1].limit == 30


@pytest.mark.parametrize("answer, opened", [("n", True), ("N", True), ("y", False), ("", False)])
def test_the_installer_still_asks_use_the_default_storage_locations_and_n_opens_the_list(
        tmp_path, monkeypatch, capsys, answer, opened):
    from test_apply_exec import Recorder, _res
    monkeypatch.setattr(cli, "cmd_cert", lambda: 0)
    monkeypatch.setattr(apply, "_tty", lambda: True)
    answers = iter(["Workshop\n", answer + "\n"])
    monkeypatch.setattr(apply.sys, "stdin", type("S", (), {"readline": lambda self: next(answers)})())
    menus = []
    monkeypatch.setattr(cli, "_storage_menu", lambda cfg: menus.append(cfg))
    apply.execute([apply.Action("server_setup", "")], run=Recorder(), resources=_res(tmp_path), root=tmp_path / "r")
    assert "Use the default storage locations? [Y/n]: " in capsys.readouterr().out
    assert len(menus) == (1 if opened else 0)
