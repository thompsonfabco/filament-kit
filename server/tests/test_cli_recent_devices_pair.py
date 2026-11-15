"""S5.6: `recent`, `devices` and `pair` (06 9.3, 9.4), with their old spellings (`intake`, `unpair`, `pair --pc`).

Each command is run through `cli.main` against the Hub's own history and pairing code, with the fake Spoolman and a fake
Label Reader. AUT-9 for `recent` and `pair --text` as root: 79-column lines, no escape byte without colour, ASCII and no
carriage return with `--plain`, `--json` parses. Example names and addresses only."""
from __future__ import annotations

import builtins
import copy
import json
import re
import threading
import time

import pytest
from fakes.claude_fake import FakeClaude
from test_intake_history import ITEM, JPEG, JPEG2, READ, RULES  # noqa: F401  (the same example label as the history tests)

from filament_kit import cli, config, intake, intake_history, inventory, modules, output, pairing
from filament_kit.intake import read_labels
from filament_kit.spoolman import Spoolman

ESC = "\x1b"


@pytest.fixture(autouse=True)
def hub(tmp_path, monkeypatch, spoolman_url):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    (tmp_path / "etc" / "anthropic_key").write_text("sk-test\n")
    pairing.make_cert("fkhost", ["192.0.2.5"], tmp_path / "etc")
    monkeypatch.setattr(pairing, "short_hostname", lambda: "fkhost")        # a runner's own host name is long and wraps the link
    config.save({"placement": {"box_count": 2}})
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    monkeypatch.setattr(cli, "Spoolman", lambda url: sm)
    return sm


@pytest.fixture
def sm(hub):
    return hub


def reading_on(monkeypatch, on: bool = True):
    monkeypatch.setattr(intake, "reading_on", lambda cfg: on)


def run(capsys, *args):
    rc = cli.main(list(args))
    got = capsys.readouterr()
    return rc, got.out, got.err


def add(sm, *, it=None, source="phone", photos=True, count=1):
    item = {k: v for k, v in (it or ITEM).items() if k not in ("photos", "existing_filament_id", "estimates", "sealed_reason")}
    item["count"] = count
    r = inventory.add_and_link(sm, [item], RULES, False, None)
    read_id = read_labels(sm, [JPEG, JPEG2], "", None, client=FakeClaude(copy.deepcopy(READ)))["read_id"] if photos else None
    return r, intake_history.record_save(r.saved, source=source, device="test phone", read_id=read_id)


def rate(hid, levels, *, filled=(), rated=True, reader="local"):
    """Give the record's stored read the confidence levels the Label Reader would have kept."""
    rec = intake_history._load(hid)
    rec["read"]["items"][0].update(confidence_levels=levels, confidence_filled=list(filled))
    rec["read"].update(confidence_rated=rated, engine={"reader": reader, "model": "m1", "tier": None})
    intake_history._save(rec)


def doc(out):
    return json.loads(out)


# ---------------------------------------------------------------- recent

def test_recent_gives_a_summary_line_then_the_table_newest_first(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    _, first = add(sm, photos=False)
    _, second = add(sm, it={**ITEM, "vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black"})
    rc, out, err = run(capsys, "recent")
    lines = out.splitlines()
    assert rc == 0 and err == ""
    assert re.fullmatch(r"Recently added: 2 records, keeping 20, 0\.0 MB of photos\.", lines[0]) and lines[1] == ""
    assert lines[2].split() == ["ID", "ADDED", "STATE", "SPOOLS", "FILAMENT"]
    assert lines[3].startswith(second) and lines[4].startswith(first)
    assert re.search(r"\d{4}-\d\d-\d\d \d\d:\d\d  as detected  \d+ +Polymaker PolyTerra PLA Charcoal Black$", lines[3])


def test_one_record_is_not_plural_and_several_spools_of_one_filament_say_so(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    r, hid = add(sm, count=2)
    out = run(capsys, "recent")[1]
    assert out.startswith("Recently added: 1 record, keeping")
    row = out.splitlines()[3]
    assert row.startswith(hid) and ", ".join(str(i) for i in r.spool_ids) in row and row.endswith("SUNLU PLA+ Grey x2")


def test_an_empty_history_says_so_and_a_reader_that_is_off_is_a_note(sm, capsys, monkeypatch):
    reading_on(monkeypatch, False)
    rc, out, err = run(capsys, "recent")
    assert rc == 0 and out.splitlines()[-1] == "No spool has been added since the history started."
    assert err.strip() == "Note: the Label Reader is off on this Hub, so corrections are by hand only."
    reading_on(monkeypatch, True)
    assert run(capsys, "recent")[2] == ""


def test_a_history_that_keeps_nothing_says_where_to_change_it(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    config.save({"placement": {"box_count": 2}, "intake": {"history_keep": 0}})
    out = run(capsys, "recent")[1]
    assert out.startswith("Recently added keeps no records.") and "spoolwarden config (Records kept)" in " ".join(out.split())
    assert "No spool has been added" not in out


def test_from_adds_the_column_and_history_is_the_same_command(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    add(sm, photos=False)
    add(sm, source="station")
    plain = run(capsys, "recent")[1]
    withfrom = run(capsys, "recent", "--from")[1]
    assert "FROM" not in plain and "FROM" in withfrom.splitlines()[2]
    assert "by hand" in withfrom and "Weigh Station" in withfrom
    assert run(capsys, "recent", "history")[1] == plain
    assert run(capsys, "recent", "history", "--from")[1] == withfrom


def test_a_record_with_low_confidence_gets_the_footer_with_the_command(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    _, hid = add(sm)
    rate(hid, {"vendor": "high", "name": "low", "color_hex": "medium"})
    lines = run(capsys, "recent")[1].splitlines()
    assert lines[-3] == "" and lines[-2] == f"! {hid} has fields read with low confidence:"
    assert lines[-1] == f"     spoolwarden recent show {hid}"          # the command does not fit: its own line, five in


def test_recent_json_is_the_hubs_history_reply(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    add(sm)
    rc, out, _ = run(capsys, "recent", "--json")
    assert rc == 0 and doc(out) == json.loads(json.dumps(intake_history.list_records(True)))
    assert set(doc(out)) == {"keep", "photo_bytes", "ai", "count", "records"}


# ---------------------------------------------------------------- recent show

def test_show_prints_the_fields_in_groups_and_marks_only_what_is_not_high(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    r, hid = add(sm)
    rate(hid, {"vendor": "high", "name": "high", "color_hex": "medium", "tare": "not_on_label", "nozzle": "low",
               "price_per_kg": "not_on_label", "density": "medium"}, filled=["density"], reader="cloud")
    rc, out, _ = run(capsys, "recent", "show", hid)
    lines = out.splitlines()
    assert rc == 0
    assert re.fullmatch(rf"Record {hid} - \d{{4}}-\d\d-\d\d \d\d:\d\d - from a phone photo - as detected", lines[0])
    assert lines[1] == f"Spool {r.spool_ids[0]} - filament {intake_history.get(hid)['saved'][0]['filament_id']} - 2 photos - read by Cloud (Claude)"
    assert [ln for ln in lines if ln in ("Identity", "Weights", "Temperatures", "Other")] == ["Identity", "Weights", "Temperatures", "Other"]
    by = {ln.strip().split("  ")[0]: ln for ln in lines if ln.startswith("  ") and not ln.startswith("   ")}
    assert by["Brand"].split() == ["Brand", "SUNLU"] and by["Name"].split() == ["Name", "PLA+", "Grey"]
    assert by["Colour"].split() == ["Colour", "#8A8C8E", "!", "medium"]
    assert by["Empty spool weight"].split() == ["Empty", "spool", "weight", "213", "g", "o", "not", "on", "label"]
    assert by["Nozzle"].split() == ["Nozzle", "220", "C", "x", "low:", "check", "this"]
    assert by["Density"].split()[-7:] == ["!", "medium:", "filled", "in", "by", "the", "Hub"]
    assert by["Net weight"].split() == ["Net", "weight", "1000", "g"]
    assert by["Bed range"].split() == ["Bed", "range", "50-60", "C"]
    assert by["Price per kg"].split()[:2] == ["Price", "per"] and "(empty)" in by["Price per kg"] and "not on label" in by["Price per kg"]
    assert "Read confidence is high unless marked." in lines
    assert "Revisions: none." in lines
    link = " ".join(lines[next(i for i, ln in enumerate(lines) if ln.startswith("Photos open on the Hub page:")):])   # the link is never cut: it may be on its own line
    assert link.startswith("Photos open on the Hub page: https://") and link.endswith(f"/setup#recent/{hid}")
    assert max(len(ln) for ln in lines if not ln.startswith("Photos open")) <= 79


def test_a_reader_that_gives_no_number_is_not_rated_and_says_so(sm, capsys, monkeypatch):
    _, hid = add(sm)
    rate(hid, {"vendor": "high", "name": "high"}, rated=False, reader="cloud")
    out = run(capsys, "recent", "show", hid)[1]
    assert "This reader does not say how sure it is. Check the values against the label." in out
    assert "Read confidence is high unless marked." not in out
    assert not [ln for ln in out.splitlines() if ln.startswith("  Brand") and ("medium" in ln or "low" in ln)]


def test_show_of_a_record_typed_by_hand_has_no_marks_and_says_no_photo(sm, capsys):
    _, hid = add(sm, photos=False)
    out = run(capsys, "recent", "show", hid)[1]
    assert "Read confidence" not in out and "!" not in out.replace("Record", "")
    assert out.splitlines()[0].endswith("added by hand - as detected") and out.splitlines()[-1] == "No photo: this spool was added by hand."
    _, st = add(sm, source="station", photos=False)
    assert run(capsys, "recent", "show", st)[1].splitlines()[-1] == "No photo was taken for this addition."


def test_show_lists_the_revisions_newest_last_with_what_undone_and_a_note_and_an_emptied_filament(sm, capsys):
    r, hid = add(sm)
    assert run(capsys, "recent", "edit", hid, "tare=150")[0] == 0
    intake_history.apply(sm, hid, item=0, values={"vendor": "Polymaker"}, device="x")
    intake_history.undo(sm, hid, None)
    rec = intake_history._load(hid)
    rec["revisions"][0]["note"] = "it is the matte one"
    intake_history._save(rec)
    out = run(capsys, "recent", "show", hid)[1]
    revs = out.split("Revisions:\n")[1].splitlines()
    revs = revs[:next(i for i, ln in enumerate(revs) if ln.startswith("Photos open on the Hub page:"))] + ["link"]   # the link: whole or on its own line
    assert revs[0].startswith("  1  ") and revs[1].startswith("     ")          # a long one goes on, indented
    first = " ".join(" ".join(revs[:2]).split())
    assert re.fullmatch(r"1 \d{4}-\d\d-\d\d \d\d:\d\d by hand Empty spool weight 213 g -> 150 g - note: it is the matte one", first), first
    at = next(i for i, ln in enumerate(revs) if ln.startswith("  2  "))
    rest = " ".join(" ".join(revs[at:-1]).split())
    assert re.match(r"2 .* by hand Brand SUNLU -> Polymaker", rest) and rest.endswith("(undone)")
    assert "has no spools left (not deleted)" in rest
    assert max(len(ln) for ln in revs[:-1]) <= 79
    assert out.index("  1  ") < out.index("  2  ")


def test_a_record_of_several_items_shows_each_item_and_says_a_change_applies_to_all_its_spools(sm, capsys):
    r, hid = add(sm, count=2)
    intake_history.apply(sm, hid, item=0, values={"color_hex": "FF0000"}, spool_ids=[r.spool_ids[1]], device="x")
    out = run(capsys, "recent", "show", hid)[1]
    assert f"Item 1: spool {r.spool_ids[0]} (filament" in out and f"Item 2: spool {r.spool_ids[1]} (filament" in out
    assert out.count("changes apply to all of them") == 2 and "#FF0000" in out and "#8A8C8E" in out
    assert out.splitlines()[1].startswith(f"Spools {r.spool_ids[0]}, {r.spool_ids[1]} - 2 photos")     # no one filament for the line


def test_show_photos_adds_the_files_one_per_line(sm, capsys):
    _, hid = add(sm)
    out = run(capsys, "recent", "show", hid, "--photos")[1].splitlines()
    assert out[-3] == "Photo files on the Hub:"
    files = out[out.index("Photo files on the Hub:") + 1:]
    assert files == ["  " + p for p in intake_history.photo_paths(hid)] and len(files) == 2
    assert "Photo files" not in run(capsys, "recent", "show", hid)[1]


def test_show_json_is_the_hubs_record(sm, capsys):
    _, hid = add(sm)
    rc, out, _ = run(capsys, "recent", "show", hid, "--json")
    assert rc == 0 and doc(out) == json.loads(json.dumps(intake_history.get(hid)))


def test_a_record_that_is_not_kept_is_exit_2_and_names_the_command_that_lists_them(sm, capsys):
    for argv in (["show", "nosuchrecord"], ["undo", "nosuchrecord"], ["edit", "nosuchrecord", "nozzle=1"]):
        rc, out, err = run(capsys, "recent", *argv)
        assert rc == 2 and out == "" and " ".join(err.split()).startswith(
            'Error: "nosuchrecord" is not a record in Recently added; only the newest 20 are kept.')
        assert "Fix: use an ID from spoolwarden recent." in err


# ---------------------------------------------------------------- recent edit and undo

@pytest.mark.parametrize("key, value, field, shown", [
    ("brand", "Polymaker", "vendor", "Polymaker"), ("vendor", "Polymaker", "vendor", "Polymaker"),
    ("colour", "#FF0000", "color_hex", "FF0000"), ("color", "00ff00", "color_hex", "00FF00"),
    ("color_hex", "0000FF", "color_hex", "0000FF"), ("net-weight", "750 g", "net", 750), ("net", "800", "net", 800),
    ("empty-spool-weight", "150", "tare", 150), ("spool-weight", "151 g", "tare", 151), ("tare", "152", "tare", 152),
    ("nozzle", "230", "nozzle", 230), ("bed", "60 C", "bed", 60), ("nozzle-range", "190-240", "nozzle_range", "190-240"),
    ("nozzle_range", "190-241", "nozzle_range", "190-241"), ("bed-range", "30-60", "bed_range", "30-60"),
    ("density", "1.31", "density", 1.31), ("price-per-kg", "24.5", "price_per_kg", 24.5),
    ("price_per_kg", "25", "price_per_kg", 25), ("line", "PLA Basic", "line", "PLA Basic"), ("name", "PLA+ Black", "name", "PLA+ Black")])
def test_every_key_of_the_table_and_its_other_spellings_changes_its_field(sm, capsys, key, value, field, shown):
    _, hid = add(sm)
    rc, out, err = run(capsys, "recent", "edit", hid, f"{key}={value}")
    assert rc == 0 and err == "" and out.startswith("Saved as revision 1: ")
    got = intake_history.get(hid)["saved"][0]["values"][field]
    assert (got.upper() if isinstance(shown, str) and field == "color_hex" else got) == shown


def test_an_edit_says_the_revision_and_what_changed_with_before_and_after(sm, capsys):
    _, hid = add(sm)
    rc, out, _ = run(capsys, "recent", "edit", hid, "tare=150", "nozzle=230")
    assert rc == 0
    assert out.splitlines()[0] == "Saved as revision 1: Empty spool weight 213 g -> 150 g; Nozzle 220 C -> 230 C."
    assert intake_history.get(hid)["state"] == "edited"


def test_an_edit_with_the_current_values_changes_nothing_and_succeeds(sm, capsys):
    _, hid = add(sm)
    rc, out, err = run(capsys, "recent", "edit", hid, "nozzle=220")
    assert (rc, out, err) == (0, "Nothing changed.\n", "") and intake_history.get(hid)["revisions"] == []


def test_a_filament_that_changes_gets_the_hubs_sentences(sm, capsys):
    _, hid = add(sm)
    out = run(capsys, "recent", "edit", hid, "brand=Polymaker")[1].splitlines()
    new = intake_history.get(hid)["revisions"][0]["filaments"]
    assert out[1] == f"The spools now use filament {new['to']} (new)."
    assert out[2] == f"Filament {new['from']} has no spools left; it was not deleted."
    _, other = add(sm, it={**ITEM, "vendor": "Polymaker"})
    assert run(capsys, "recent", "edit", other, "brand=SUNLU")[0] == 0


def test_an_unknown_key_is_exit_2_with_the_list_of_keys_and_nothing_is_written(sm, capsys):
    _, hid = add(sm)
    rc, out, err = run(capsys, "recent", "edit", hid, "nozzle=230", "weight=5")
    assert rc == 2 and out == ""
    assert err.splitlines()[0] == 'Error: "weight" is not a field of a record.'
    assert "brand, name, material, colour, net-weight, empty-spool-weight, density, nozzle, bed, nozzle-range, bed-range, price-per-kg, line" in " ".join(err.split())
    assert intake_history.get(hid)["revisions"] == []


@pytest.mark.parametrize("argv, message", [
    (["nozzle"], '"nozzle" is not field=value.'), (["nozzle=hot"], "Nozzle must be whole degrees, like 210."),
    (["nozzle=2.5"], "Nozzle must be whole degrees, like 210."), (["net-weight=lots"], "Net weight must be a number of grams"),
    (["density=x"], "Density must be a number in g/cm"), (["price-per-kg=cheap"], "Price per kg must be a number"),
    (["nozzle=230", "--spools", "x"], "--spools takes spool ids."), (["nozzle=230", "--item", "0"], "item numbers start at 1."),
    (["colour=red"], "color_hex must be 6 hex digits"), (["brand="], "vendor must be text")])
def test_a_bad_value_is_exit_2_and_changes_nothing(sm, capsys, argv, message):
    _, hid = add(sm)
    rc, out, err = run(capsys, "recent", "edit", hid, *argv)
    assert rc == 2 and out == "" and message in " ".join(err.split()), err
    assert intake_history.get(hid)["revisions"] == []


def test_edit_takes_the_item_as_the_hub_page_numbers_it_and_some_of_the_spools(sm, capsys):
    r, hid = add(sm, count=2)
    assert run(capsys, "recent", "edit", hid, "colour=FF0000", "--spools", str(r.spool_ids[1]))[0] == 0
    assert sm.get(f"spool/{r.spool_ids[0]}")["filament"]["color_hex"] == "8A8C8E"
    assert sm.get(f"spool/{r.spool_ids[1]}")["filament"]["color_hex"] == "FF0000"
    rec = intake_history.get(hid)
    assert [s["item"] for s in rec["saved"]] == [0, 1]
    assert run(capsys, "recent", "edit", hid, "nozzle=240", "--item", "2")[0] == 0           # the second item is `--item 2`
    assert sm.get(f"spool/{r.spool_ids[1]}")["filament"]["settings_extruder_temp"] == 240
    assert sm.get(f"spool/{r.spool_ids[0]}")["filament"]["settings_extruder_temp"] == 220
    rc, _, err = run(capsys, "recent", "edit", hid, "nozzle=250", "--item", "3")
    assert rc == 2 and "no such item in this record" in err


def test_undo_names_the_revision_and_the_state_the_record_is_in_again(sm, capsys):
    _, hid = add(sm)
    run(capsys, "recent", "edit", hid, "tare=150")
    run(capsys, "recent", "edit", hid, "nozzle=230")
    rc, out, _ = run(capsys, "recent", "undo", hid)
    assert (rc, out) == (0, f"Undone: revision 2. Record {hid} is edited by hand again.\n")
    assert run(capsys, "recent", "undo", hid)[1] == f"Undone: revision 1. Record {hid} is as detected again.\n"
    rc, out, err = run(capsys, "recent", "undo", hid)
    assert rc == 1 and out == "" and err.startswith("Error: nothing to undo")


def test_undoing_a_change_of_filament_says_which_filament_has_no_spools_left(sm, capsys):
    _, hid = add(sm)
    run(capsys, "recent", "edit", hid, "brand=Polymaker")
    fl = intake_history.get(hid)["revisions"][0]["filaments"]
    out = run(capsys, "recent", "undo", hid)[1].splitlines()
    assert out[0].startswith("Undone: revision 1.") and out[1] == f"Filament {fl['to']} has no spools left; it was not deleted."


def test_edit_and_undo_json_are_ok_true_and_the_record(sm, capsys):
    _, hid = add(sm)
    got = doc(run(capsys, "recent", "edit", hid, "tare=150", "--json")[1])
    assert got["ok"] is True and got["revisions"][0]["n"] == 1 and got["id"] == hid
    got = doc(run(capsys, "recent", "undo", hid, "--json")[1])
    assert got["ok"] is True and got["revisions"][0]["undone"] is True
    rc, out, err = run(capsys, "recent", "edit", hid, "weight=1", "--json")
    assert rc == 2 and doc(out)["ok"] is False and "Error:" in err


def test_quiet_drops_the_result_lines_of_edit_and_undo(sm, capsys):
    _, hid = add(sm)
    assert run(capsys, "recent", "edit", hid, "tare=150", "--quiet")[1:] == ("", "")
    assert run(capsys, "recent", "undo", hid, "--quiet")[1:] == ("", "")
    assert run(capsys, "recent", "undo", hid, "--quiet")[0] == 1


# ---------------------------------------------------------------- recent revise

@pytest.fixture
def asked(monkeypatch):
    """Answer the questions at a terminal; `asked.prompts` are the questions."""
    class Asked(list):
        answers: list[str] = []

        def answer(self, text: str) -> None:
            self.answers.append(text)

    prompts = Asked()
    prompts.answers = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        print(prompt, end="")
        if not prompts.answers:
            raise EOFError
        return prompts.answers.pop(0)
    monkeypatch.setattr(output, "terminal", lambda: True)
    monkeypatch.setattr(builtins, "input", fake_input)
    return prompts


def fixed(**changes):
    """What the Label Reader answers: the example item with `changes`."""
    return {"questions": [], "items": [{**ITEM, **changes}]}


def label_reader(monkeypatch, reply):
    fake = FakeClaude(copy.deepcopy(reply))
    real = intake_history.revise
    monkeypatch.setattr(intake_history, "revise", lambda sm, rid, note, item=None, **k: real(sm, rid, note, item, client=fake, **k))
    return fake


def test_revise_shows_the_suggestion_asks_and_saves_what_was_accepted(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm)
    fake = label_reader(monkeypatch, fixed(name="PLA+ Grey (Matte)", nozzle_range="200-220"))
    asked.answer("y")
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "it is the matte one")
    lines = out.splitlines()
    assert rc == 0 and len(fake.calls) == 1
    assert lines[0] == "The Label Reader suggests:"
    assert lines[1] == "  Name: PLA+ Grey -> PLA+ Grey (Matte)" and lines[2] == "  Nozzle range: 200-230 C -> 200-220 C"
    assert lines[3] == "  Line: (empty) -> PLA+"                       # the Hub works the product line out too
    assert lines[4].startswith("Accept these changes? [y/N]")
    assert "Saved as revision 1: Name, Nozzle range, Line." in out
    rec = intake_history.get(hid)
    assert rec["state"] == "revised_ai" and rec["revisions"][0]["note"] == "it is the matte one"
    assert asked == ["Accept these changes? [y/N] "]


def test_a_long_change_puts_the_after_value_on_the_next_line_starting_with_the_arrow(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm)
    label_reader(monkeypatch, fixed(name="PLA+ Grey Matte Limited Edition Anniversary Release Of The Year Special Pack"))
    asked.answer("n")
    out = run(capsys, "recent", "revise", hid, "--note", "x")[1].splitlines()
    assert out[1] == "  Name: PLA+ Grey" and out[2] == "     -> PLA+ Grey Matte Limited Edition Anniversary Release Of The Year Special Pack"


def test_answering_no_changes_nothing_and_exits_5(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm)
    label_reader(monkeypatch, fixed(name="PLA+ Black"))
    asked.answer("")
    rc, out, _ = run(capsys, "recent", "revise", hid, "--note", "x")
    assert rc == 5 and out.rstrip().endswith("Nothing changed.") and intake_history.get(hid)["revisions"] == []


def test_yes_saves_without_the_question_and_json_needs_it(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    _, hid = add(sm)
    fake = label_reader(monkeypatch, fixed(name="PLA+ Black"))
    monkeypatch.setattr(output, "terminal", lambda: False)
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "x", "--json")
    assert rc == 2 and doc(out)["ok"] is False and fake.calls == [] and intake_history.get(hid)["revisions"] == []     # nothing was read
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "x", "--yes")
    assert rc == 0 and "[y/N]" not in out and "Saved as revision 1: Name, Line." in out
    _, other = add(sm)
    got = doc(run(capsys, "recent", "revise", other, "--note", "x", "--yes", "--json")[1])
    assert got["ok"] is True and got["revisions"][0]["by"] == "ai" and len(fake.calls) == 2


def test_piped_without_yes_is_refused_before_the_reader_is_asked(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    _, hid = add(sm)
    fake = label_reader(monkeypatch, fixed(name="PLA+ Black"))
    monkeypatch.setattr(output, "terminal", lambda: False)
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "x")
    assert rc == 2 and out == "" and fake.calls == []
    assert err.splitlines()[0] == "Error: applying the revision needs a yes, and there is no terminal to ask."
    assert err.splitlines()[-1].strip() == f"sudo spoolwarden recent revise {hid} --note x --yes"


def test_a_reader_that_changes_nothing_says_so_and_asks_nothing(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm)
    run(capsys, "recent", "edit", hid, "line=PLA+")                       # what the Hub would fill in itself
    label_reader(monkeypatch, fixed())
    rc, out, _ = run(capsys, "recent", "revise", hid, "--note", "x")
    assert (rc, out) == (0, "The Label Reader changed nothing.\n") and asked == []


def test_a_record_with_no_photo_says_the_reader_worked_from_the_saved_values(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm, photos=False)
    label_reader(monkeypatch, fixed(name="PLA+ Black"))
    asked.answer("y")
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "x")
    assert rc == 0 and " ".join(err.split()) == ("Note: no photo was kept for this record; the Label Reader worked from "
                                                 "the saved values and your note.")


def test_revise_with_the_reader_off_says_edit_by_hand_with_the_command(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch, False)
    _, hid = add(sm)
    fake = label_reader(monkeypatch, fixed(name="PLA+ Black"))
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "x")
    lines = err.splitlines()
    assert rc == 1 and out == "" and fake.calls == [] and asked == []
    assert lines[0] == "Error: the Label Reader is off on this Hub, so only edits by hand work."
    assert lines[1] == 'Fix: sudo spoolwarden recent edit ' + hid + ' name="..."' and len(lines) == 2


def test_revise_takes_the_item_as_numbered_and_needs_a_note(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    r, hid = add(sm, count=2)
    run(capsys, "recent", "edit", hid, "colour=FF0000", "--spools", str(r.spool_ids[1]))
    fake = label_reader(monkeypatch, fixed(name="PLA+ Black"))
    asked.answer("n")
    assert run(capsys, "recent", "revise", hid, "--note", "x", "--item", "2")[0] == 5
    hints = [c["text"] for m in fake.calls[0]["messages"] for c in m["content"] if c.get("type") == "text"]
    assert any('"color_hex": "FF0000"' in t for t in hints) and not any('"color_hex": "8A8C8E"' in t and "saved from" in t for t in hints)
    with pytest.raises(SystemExit) as e:
        cli.main(["recent", "revise", hid])
    assert e.value.code == 2 and "--note" in capsys.readouterr().err


def test_quiet_revise_still_shows_what_it_asks_about_and_the_question(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm)
    label_reader(monkeypatch, fixed(name="PLA+ Black"))
    asked.answer("y")
    rc, out, _ = run(capsys, "recent", "revise", hid, "--note", "x", "--quiet")
    assert rc == 0 and "The Label Reader suggests:" in out and "Accept these changes?" in out and "Saved as" not in out


# ---------------------------------------------------------------- devices

def pair_device(name="Shop phone", claim=True):
    p = pairing.issue(device_hint=name)
    if claim:
        pairing.redeem_code(p.code)
    return next((d for d in pairing.devices() if d["name"] == name), None) if claim else p


def test_devices_lists_name_paired_last_seen_and_id_and_marks_the_built_in_ones(capsys):
    from filament_kit.web.slots import INTAKE_DEVICE
    shop, studio = pair_device("Shop phone"), pair_device("Studio PC")
    built = pair_device(INTAKE_DEVICE)
    rc, out, err = run(capsys, "devices")
    lines = out.splitlines()
    assert rc == 0 and err == "" and lines[0].split() == ["NAME", "PAIRED", "LAST", "SEEN", "ID"]
    assert re.fullmatch(rf"Shop phone +\d{{4}}-\d\d-\d\d \d\d:\d\d +\d{{4}}-\d\d-\d\d \d\d:\d\d +{shop['id']}", lines[1])
    assert lines[2].startswith("Studio PC") and lines[2].endswith(studio["id"])
    assert re.fullmatch(rf"{re.escape(INTAKE_DEVICE)} +built in: this Hub's own pairing +{built['id']}", lines[3])
    assert run(capsys, "devices", "list")[1] == out and run(capsys, "unpair")[1] == out


def test_nothing_paired_says_how_to_pair_a_phone(capsys):
    rc, out, _ = run(capsys, "devices")
    assert (rc, out) == (0, "Nothing paired yet.\nPair a phone: sudo spoolwarden pair\n")


def test_devices_json_is_the_hubs_list_with_iso_times(capsys):
    from filament_kit.web.slots import CLI_DEVICE
    shop, built = pair_device("Shop phone"), pair_device(CLI_DEVICE)
    got = doc(run(capsys, "devices", "--json")[1])
    assert [set(d) for d in got] == [{"id", "name", "paired", "last_seen", "built_in"}] * 2
    assert [d["built_in"] for d in got] == [False, True] and got[0]["id"] == shop["id"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", got[0]["paired"])


def test_a_pairing_nobody_has_claimed_is_not_listed(capsys):
    pair_device("Never used", claim=False)
    assert run(capsys, "devices")[1].startswith("Nothing paired yet.")
    assert doc(run(capsys, "devices", "--json")[1]) == []


def test_forget_asks_in_the_hub_pages_words_and_unpairs_after_a_yes(capsys, asked):
    shop = pair_device("Shop phone")
    asked.answer("y")
    rc, out, _ = run(capsys, "devices", "forget", "shop")
    assert rc == 0 and " ".join(out.split()).startswith("Unpair Shop phone? It can no longer reach the Hub until it is paired again. [y/N]")
    assert out.rstrip().endswith("Unpaired Shop phone.") and pairing.devices() == []
    assert len(asked) == 1 and asked[0].endswith("[y/N] ")


@pytest.mark.parametrize("answer", ["", "n", "no", "yess"])
def test_forget_answered_no_changes_nothing_and_exits_5(capsys, asked, answer):
    pair_device("Shop phone")
    asked.answer(answer)
    rc, out, _ = run(capsys, "devices", "forget", "Shop phone")
    assert rc == 5 and out.rstrip().endswith("Nothing changed.") and len(pairing.devices()) == 1


def test_forget_piped_without_yes_is_exit_2_and_names_the_command_with_yes(capsys, monkeypatch):
    shop = pair_device("Shop phone")
    monkeypatch.setattr(output, "terminal", lambda: False)
    rc, out, err = run(capsys, "devices", "forget", shop["id"])
    assert rc == 2 and out == "" and len(pairing.devices()) == 1
    assert err.splitlines()[0] == "Error: unpairing Shop phone needs a yes, and there is no terminal to ask."
    assert err.splitlines()[-1].strip() == f"sudo spoolwarden devices forget {shop['id']} --yes"
    assert run(capsys, "devices", "forget", shop["id"], "--yes")[1:] == ("Unpaired Shop phone.\n", "") and pairing.devices() == []


def test_a_device_is_named_by_id_by_exact_name_or_by_the_start_of_exactly_one_name(capsys):
    shop = pair_device("Shop phone")
    pair_device("Studio PC")
    assert run(capsys, "devices", "forget", "STUDIO", "-y")[1] == "Unpaired Studio PC.\n"          # the start, any case
    assert run(capsys, "devices", "forget", shop["id"].upper(), "-y")[1] == "Unpaired Shop phone.\n"    # the id, any case
    pair_device("Studio PC")
    assert run(capsys, "devices", "forget", "studio pc", "-y")[0] == 0 and pairing.devices() == []   # the whole name


def test_more_than_one_or_no_match_is_exit_2_with_the_close_matches(capsys):
    a, b = pair_device("Shop phone"), pair_device("Shop tablet")
    rc, out, err = run(capsys, "devices", "forget", "shop", "--yes")
    lines = err.splitlines()
    assert rc == 2 and out == "" and len(pairing.devices()) == 2
    assert lines[0] == 'Error: "shop" does not name one device.'
    assert lines[1] == "Fix: use a name or id from spoolwarden devices. Close matches:"
    assert [ln.split() for ln in lines[2:]] == [["Shop", "phone", a["id"]], ["Shop", "tablet", b["id"]]]
    rc, _, err = run(capsys, "devices", "forget", "nobody", "--yes")
    assert rc == 2 and err.splitlines() == ['Error: "nobody" does not name one device.', "Fix: use a name or id from spoolwarden devices."]
    rc, _, err = run(capsys, "devices", "forget", "tablet", "--yes")           # a name's middle is a close match, not a name
    assert rc == 2 and "Shop tablet" in err


def test_a_built_in_pairing_cannot_be_forgotten(capsys, asked):
    from filament_kit.web.slots import CLI_DEVICE
    built = pair_device(CLI_DEVICE)
    rc, out, err = run(capsys, "devices", "forget", built["id"], "--yes")
    assert rc == 2 and out == "" and err.splitlines() == [f"Error: {CLI_DEVICE} is built in: it is this Hub's own pairing."]
    assert len(pairing.devices()) == 1 and asked == []


def test_unpair_by_id_still_removes_a_pairing_nobody_claimed_and_by_id_only(capsys):
    pair_device("phone", claim=False)
    shop = pair_device("Shop phone")
    device_id = pairing._read("devices.json")[0]["id"]
    assert run(capsys, "devices", "forget", "phone", "-y")[0] == 2                     # a name never reaches an unclaimed one
    assert run(capsys, "unpair", device_id, "--yes")[1] == "Unpaired phone.\n"
    assert [d["id"] for d in pairing.devices()] == [shop["id"]]


def test_forget_json_is_ok_true_with_the_device_and_needs_yes(capsys):
    shop = pair_device("Shop phone")
    rc, out, _ = run(capsys, "devices", "forget", "shop", "--json")
    assert rc == 2 and doc(out)["ok"] is False
    got = doc(run(capsys, "devices", "forget", "shop", "--yes", "--json")[1])
    assert got == {"ok": True, "id": shop["id"], "name": "Shop phone"}


def test_quiet_drops_the_result_of_forget_but_not_the_list(capsys):
    pair_device("Shop phone")
    assert "Shop phone" in run(capsys, "devices", "--quiet")[1]
    assert run(capsys, "devices", "forget", "shop", "--yes", "--quiet")[1:] == ("", "")


# ---------------------------------------------------------------- pair

def fingerprint_groups():
    fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    return [fp[i:i + 4] for i in range(0, len(fp), 4)]


def pending_code():
    return pairing._read("pending.json")[-1]["code"]


@pytest.fixture
def waiting(monkeypatch):
    """`pair` waits by sleeping; `steps` are what happens at each look (a callable), the sleeps themselves take no time."""
    state = {"looks": 0, "steps": []}
    real_sleep, test_thread = time.sleep, threading.get_ident()

    def sleep(seconds):
        if threading.get_ident() != test_thread:    # time.sleep is the process's: another thread's sleep is not a look
            return real_sleep(seconds)
        state["looks"] += 1
        assert state["looks"] < 200, "pair keeps waiting for a device nobody pairs"
        if state["steps"]:
            state["steps"].pop(0)()
        else:                                   # nothing planned: the device pairs now
            pairing.redeem_code(pending_code())
    monkeypatch.setattr(cli.time, "sleep", sleep)
    return state


def test_pair_prints_the_qr_the_instruction_the_code_the_fingerprint_and_the_expiry_in_that_order(capsys, waiting):
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    rc, out, err = run(capsys, "pair")
    lines = out.splitlines()
    qr_rows = [i for i, ln in enumerate(lines) if ln.startswith(ESC + "[30;47m")]
    assert rc == 0 and qr_rows and qr_rows == list(range(qr_rows[0], qr_rows[-1] + 1))
    tail = [ln for ln in lines[qr_rows[-1] + 1:] if ln]
    assert tail[0] == "Open the Spoolwarden app and scan this code, or type the pairing code."
    assert re.fullmatch(r"Pairing code: \d{3} \d{3}", tail[1])
    assert tail[2] == "Certificate fingerprint (the phone asks for two groups of it):"
    g = fingerprint_groups()
    assert tail[3] == "  " + " ".join(g[:8]) and tail[4] == "  " + " ".join(g[8:]) and len(g) == 16
    assert re.fullmatch(r"Expires at \d\d:\d\d \(in (10|9) min\)\.", tail[5])
    assert tail[6] == "Paired: phone." and len(tail) == 7 and waiting["looks"] == 1
    assert max(len(ln) for ln in tail) <= 79


def test_the_code_on_screen_is_the_code_that_pairs(capsys, waiting):
    seen = []
    waiting["steps"] = [lambda: seen.append(pending_code())]            # what the Hub holds while `pair` waits
    rc, out, _ = run(capsys, "pair", "--text")
    code = re.search(r"Pairing code: (\d{3}) (\d{3})", out)
    assert code and seen == [code.group(1) + code.group(2)]


def test_pair_text_has_no_qr_and_the_link_alone_on_its_line(capsys, monkeypatch, waiting):
    monkeypatch.setattr(cli, "_qr_text", lambda payload: pytest.fail("no QR code with --text"))
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    rc, out, _ = run(capsys, "pair", "--text")
    lines = out.splitlines()
    assert rc == 0 and ESC not in out
    assert lines[0] == "Open the Spoolwarden app and type the pairing code, or give it this link:"
    assert lines[1].startswith("fkit://pair?") and " " not in lines[1]
    assert lines[2].startswith("Pairing code: ") and lines[-1] == "Paired: phone."


def test_slicer_sync_and_weigh_station_print_the_instruction_and_the_link_never_a_qr(capsys, monkeypatch, waiting):
    monkeypatch.setattr(cli, "_qr_text", lambda payload: pytest.fail("no QR code for a link that is pasted"))
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())] * 2
    rc, out, _ = run(capsys, "pair", "--slicer-sync")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "Paste this link into the Slicer Sync when it asks:"
    assert lines[1].startswith("fkit://pair?") and lines[2].startswith("Pairing code: ")
    assert lines[3] == "Certificate fingerprint (check it matches the one the Slicer Sync shows):"
    assert lines[-1] == "Paired: pc." and [d["name"] for d in pairing.devices()] == ["pc"]
    rc, out, _ = run(capsys, "pair", "--weigh-station")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "On the Weigh Station run: sudo spoolwarden station pair, then paste this link:"
    assert lines[1].startswith("fkit://pair?") and "check it matches the one the Weigh Station shows" in lines[3]
    assert pairing._read("devices.json")[-1]["scope"] == "station"


def test_the_old_spellings_pair_the_same_kinds(capsys, waiting):
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())] * 2
    assert run(capsys, "pair", "--pc")[1].splitlines()[0] == "Paste this link into the Slicer Sync when it asks:"
    assert "Weigh Station" in run(capsys, "pair", "--station")[1]
    assert [d["name"] for d in pairing.devices()] == ["pc", "station"]


def test_plain_is_text_without_a_qr(capsys, monkeypatch, waiting):
    monkeypatch.setattr(cli, "_qr_text", lambda payload: pytest.fail("no QR code with --plain"))
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    rc, out, _ = run(capsys, "--plain", "pair")
    assert rc == 0 and out.splitlines()[0].startswith("Open the Spoolwarden app and type the pairing code")
    assert ESC not in out and "\r" not in out and out.isascii()


def test_pair_says_what_it_waits_for_and_when_it_ends_the_wait_the_code_works_until(capsys, monkeypatch, waiting):
    seen = {}

    class Wait:
        def __init__(self, text, **k):
            seen["text"] = text

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False
    monkeypatch.setattr(output, "wait", Wait)
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    run(capsys, "pair", "--text")
    assert re.fullmatch(r"Waiting for the phone… \(the code works until \d\d:\d\d\)", seen["text"].replace("...", "…"))
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    run(capsys, "pair", "--slicer-sync")
    assert seen["text"].startswith("Waiting for Slicer Sync…")
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    run(capsys, "pair", "--weigh-station")
    assert seen["text"].startswith("Waiting for the Weigh Station…")


def test_pair_keeps_looking_until_the_device_pairs_and_names_it(capsys, waiting):
    waiting["steps"] = [lambda: None, lambda: None, lambda: pairing.redeem_code(pending_code())]
    rc, out, _ = run(capsys, "pair", "--text")
    assert rc == 0 and out.splitlines()[-1] == "Paired: phone." and waiting["looks"] == 3


def test_a_phone_that_scans_the_qr_pairs_too(capsys, waiting):
    def scan():
        token = re.search(r"[?&]t=([^&]+)", pairing_link["link"]).group(1)
        assert pairing.check(token)
    pairing_link = {}
    real = pairing.issue

    def issue(*a, **k):
        p = real(*a, **k)
        pairing_link["link"] = p.qr
        return p
    cli.pairing.issue = issue
    try:
        waiting["steps"] = [scan]
        rc, out, _ = run(capsys, "pair", "--text")
    finally:
        cli.pairing.issue = real
    assert rc == 0 and out.splitlines()[-1] == "Paired: phone."


def test_ctrl_c_stops_the_wait_says_until_when_the_code_works_and_leaves_it_valid(capsys, waiting):
    def stop():
        raise KeyboardInterrupt
    waiting["steps"] = [stop]
    rc, out, err = run(capsys, "pair", "--text")
    assert rc == 130 and err == ""
    assert re.fullmatch(r"Stopped waiting\. The code works until \d\d:\d\d\.", out.splitlines()[-1])
    assert re.fullmatch(r"\d{6}", pending_code()) and pairing.redeem_code(pending_code())      # the code still works


def test_a_code_that_runs_out_is_an_error_with_the_command_to_make_a_new_one(capsys, monkeypatch):
    monkeypatch.setattr(pairing, "TOKEN_TTL", 1)
    real_sleep = time.sleep
    monkeypatch.setattr(cli.time, "sleep", lambda s: real_sleep(1.1))
    rc, out, err = run(capsys, "pair", "--text")
    assert rc == 1 and "Paired" not in out
    assert err.splitlines()[0] == "Error: the pairing code expired before a device paired."
    assert err.splitlines()[1].startswith("Fix: make a new one with:") or "sudo spoolwarden pair" in err
    assert err.strip().splitlines()[-1].strip() == "sudo spoolwarden pair"


def test_json_does_not_wait_and_prints_the_link_code_fingerprint_and_expiry(capsys, monkeypatch):
    monkeypatch.setattr(cli.time, "sleep", lambda s: pytest.fail("pair --json must not wait"))
    rc, out, err = run(capsys, "pair", "--json")
    got = doc(out)
    assert rc == 0 and set(got) == {"ok", "code", "link", "fingerprint", "expires"} and got["ok"] is True
    assert got["code"] == pending_code() and got["link"].startswith("fkit://pair?") and got["fingerprint"] == "".join(fingerprint_groups())
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", got["expires"]) and err == ""
    assert pairing.devices() == []
    rc, out, _ = run(capsys, "pair", "--slicer-sync", "--json")
    assert rc == 0 and doc(out)["ok"] is True


def test_no_wait_prints_and_ends(capsys, monkeypatch):
    monkeypatch.setattr(cli.time, "sleep", lambda s: pytest.fail("--no-wait must not wait"))
    rc, out, _ = run(capsys, "pair", "--text", "--no-wait")
    assert rc == 0 and re.fullmatch(r"The code works until \d\d:\d\d\.", out.splitlines()[-1]), out
    assert out.splitlines()[-2].startswith("Expires at ") and "Waiting" not in out


def test_no_wait_is_listed_in_the_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["pair", "-h"])
    assert "--no-wait" in capsys.readouterr().out


def test_a_machine_without_the_hub_cannot_pair_devices(capsys, monkeypatch):
    config.save({"modules": modules.module_map({"station"}, config.load()), "station": {"allow": ["kit.example.lan"], "url": None}})
    for argv in (["pair"], ["pair", "--slicer-sync"]):
        rc, out, err = run(capsys, *argv)
        assert rc == 1 and out == "" and err.splitlines()[0] == "Error: this machine has no Hub, so it cannot pair devices."
        assert "Fix: run it on the Hub (kit.example.lan, from station.allow)." in " ".join(err.split())
    rc, out, err = run(capsys, "pair", "--json")
    assert rc == 1 and doc(out)["ok"] is False and "no Hub" in doc(out)["error"]
    assert pairing._read("devices.json") == []


# ---------------------------------------------------------------- AUT-9: width, escape bytes, plain, json

def seeded(sm, monkeypatch):
    reading_on(monkeypatch)
    r, hid = add(sm, it={**ITEM, "vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black Matte Limited"})
    rate(hid, {"vendor": "high", "name": "low", "color_hex": "medium"}, filled=["color_hex"])
    run_edit = cli.main(["recent", "edit", hid, "tare=150", "--quiet"])
    assert run_edit == 0
    return hid


AUT = [["recent"], ["recent", "--from"], ["devices"], ["pair", "--text"], ["pair", "--slicer-sync"], ["pair", "--weigh-station"]]


@pytest.mark.parametrize("argv", AUT, ids=" ".join)
def test_aut9_every_line_fits_79_columns_with_no_escape_byte_when_piped_or_without_colour(argv, sm, capsys, monkeypatch, waiting):
    seeded(sm, monkeypatch)
    pair_device("Shop phone with a very long name that goes on and on")
    capsys.readouterr()
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)           # a terminal: tables are cut or turned into blocks
    rc, out, err = run(capsys, *argv)
    assert rc == 0
    for line in (out + err).splitlines():                                  # but the link, which is never wrapped
        assert len(line) <= 79 or (" " not in line.strip() and "://" in line), line
    monkeypatch.setenv("NO_COLOR", "1")
    rc, out, err = run(capsys, *argv)
    assert rc == 0 and ESC not in out + err                                # NO_COLOR, though a terminal


def test_aut9_a_pipe_gets_whole_rows_and_no_escape_byte(sm, capsys, monkeypatch, waiting):
    seeded(sm, monkeypatch)
    pair_device("Shop phone with a very long name that goes on and on")
    capsys.readouterr()
    for argv in (["recent"], ["devices"], ["pair", "--text"]):
        rc, out, err = run(capsys, *argv)
        assert rc == 0 and ESC not in out + err and "..." not in out and "…" not in out
    assert "Polymaker PolyTerra PLA Charcoal Black Matte Limited" in run(capsys, "recent")[1]


@pytest.mark.parametrize("argv", [["recent"], ["recent", "show", "{hid}"], ["devices"], ["pair", "--text"]], ids=" ".join)
def test_aut9_plain_is_ascii_with_no_carriage_return_and_no_escape(argv, sm, capsys, monkeypatch, waiting):
    hid = seeded(sm, monkeypatch)
    pair_device("Shop phone")
    capsys.readouterr()
    waiting["steps"] = [lambda: pairing.redeem_code(pending_code())]
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")      # --plain wins over the locale
    rc, out, err = run(capsys, "--plain", *[a.format(hid=hid) for a in argv])
    assert rc == 0 and (out + err).isascii() and "\r" not in out + err and ESC not in out + err


@pytest.mark.parametrize("argv", [["recent"], ["recent", "show", "{hid}"], ["devices"], ["pair"]], ids=" ".join)
def test_aut9_json_is_one_document(argv, sm, capsys, monkeypatch):
    hid = seeded(sm, monkeypatch)
    pair_device("Shop phone")
    capsys.readouterr()
    rc, out, err = run(capsys, "--color", "always", *[a.format(hid=hid) for a in argv], "--json")
    assert rc == 0 and out.endswith("}\n") or out.endswith("]\n")
    assert out.count("\n") == 1 and ESC not in out and json.loads(out) is not None


def test_the_unicode_glyph_set_uses_the_arrow_the_separator_and_the_degree_sign(sm, capsys, monkeypatch):
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")
    _, hid = add(sm)
    run(capsys, "recent", "edit", hid, "nozzle=230")
    out = run(capsys, "recent", "show", hid)[1]
    assert " · from a phone photo · edited by hand" in out and "Nozzle 220 °C → 230 °C" in out and "1.24 g/cm³" in out


# ---------------------------------------------------------------- the old spellings are the same commands

def test_intake_is_recent_under_its_old_name_and_still_needs_a_subcommand(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    r, hid = add(sm)
    assert run(capsys, "intake", "history")[1] == run(capsys, "recent")[1]
    assert run(capsys, "intake", "show", hid)[1] == run(capsys, "recent", "show", hid)[1]
    assert run(capsys, "intake", "edit", hid, "nozzle=230")[1].startswith("Saved as revision 1: Nozzle 220 C -> 230 C.")
    assert run(capsys, "intake", "undo", hid)[1].startswith("Undone: revision 1.")
    with pytest.raises(SystemExit) as e:
        cli.main(["intake"])
    assert e.value.code == 2 and "required" in capsys.readouterr().err


def test_intake_revise_is_recent_revise_under_its_old_name(sm, capsys, monkeypatch, asked):
    reading_on(monkeypatch)
    _, hid = add(sm)
    label_reader(monkeypatch, fixed(name="PLA+ Black"))
    asked.answer("y")
    rc, out, _ = run(capsys, "intake", "revise", hid, "--note", "x")
    assert rc == 0 and "Saved as revision 1: Name, Line." in out


def test_unpair_is_devices_and_devices_forget_under_its_old_name(capsys, asked):
    shop = pair_device("Shop phone")
    assert run(capsys, "unpair")[1] == run(capsys, "devices")[1]
    asked.answer("y")
    rc, out, _ = run(capsys, "unpair", shop["id"])
    assert rc == 0 and out.rstrip().endswith("Unpaired Shop phone.") and run(capsys, "unpair", "nobody")[0] == 2


# ---------------------------------------------------------------- the Cloud read limit, the audit lines, undo's revision

def _reads(tmp_path) -> list:
    path = tmp_path / "state" / "reads.json"
    return json.loads(path.read_text()) if path.exists() else []


def _audit_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "filament_kit.setup_page"]


def test_a_revision_takes_one_read_off_the_daily_cap_and_is_audited(sm, capsys, monkeypatch, asked, tmp_path, caplog):
    caplog.set_level("INFO")
    reading_on(monkeypatch)
    _, hid = add(sm)
    before = len(_reads(tmp_path))
    label_reader(monkeypatch, fixed(name="PLA+ Black"))
    asked.answer("y")
    assert run(capsys, "recent", "revise", hid, "--note", "x")[0] == 0
    assert len(_reads(tmp_path)) == before + 1
    assert _audit_lines(caplog) == [f"setup: recently added record {hid} revision asked of the AI from ",
                                    f"setup: recently added record {hid} revised from "]


def test_a_revision_at_the_daily_limit_is_refused_with_the_hubs_words(sm, capsys, monkeypatch, asked, tmp_path, caplog):
    caplog.set_level("INFO")
    reading_on(monkeypatch)
    _, hid = add(sm)
    cfg = config.load()
    cfg["reads_per_day"] = 1
    config.save(cfg)
    (tmp_path / "state" / "reads.json").write_text(json.dumps([time.time() - 10]))
    fake = label_reader(monkeypatch, fixed(name="PLA+ Black"))
    rc, out, err = run(capsys, "recent", "revise", hid, "--note", "x")
    assert rc == 1 and out == "" and fake.calls == [] and len(_reads(tmp_path)) == 1
    lines = err.splitlines()
    assert lines[0] == "Error: daily limit of 1 label reads reached (reads_per_day)" and lines[1].startswith("Fix: ")
    assert intake_history.get(hid)["revisions"] == [] and _audit_lines(caplog) == []


def test_an_edit_and_an_undo_are_audited_as_the_hub_audits_them(sm, capsys, caplog):
    caplog.set_level("INFO")
    _, hid = add(sm)
    run(capsys, "recent", "edit", hid, "tare=150")
    run(capsys, "recent", "undo", hid)
    assert _audit_lines(caplog) == [f"setup: recently added record {hid} revised from ",
                                    f"setup: recently added record {hid} revision undone from "]


def test_undo_is_refused_when_a_newer_revision_appeared_after_it_looked(sm, capsys, monkeypatch):
    _, hid = add(sm)
    run(capsys, "recent", "edit", hid, "tare=150")
    real = intake_history.get

    def get_then_a_newer_revision(h):
        got = real(h)
        monkeypatch.setattr(intake_history, "get", real)
        intake_history.apply(sm, h, item=0, values={"nozzle": 230}, device="setup page")     # the Hub page, meanwhile
        return got
    monkeypatch.setattr(intake_history, "get", get_then_a_newer_revision)
    rc, out, err = run(capsys, "recent", "undo", hid)
    assert rc == 1 and out == "" and "only the newest revision (2) can be undone" in err
    assert not any(r.get("undone") for r in intake_history.get(hid)["revisions"])


def test_every_revised_by_ai_row_is_coloured(sm, capsys, monkeypatch):
    reading_on(monkeypatch)
    for _ in range(2):
        _, hid = add(sm)
        run(capsys, "recent", "edit", hid, "tare=150")
        rec = intake_history._load(hid)
        rec["state"] = "revised_ai"
        intake_history._save(rec)
    out = run(capsys, "--color", "always", "recent")[1]
    rows = [ln for ln in out.splitlines() if "revised by AI" in ln]
    assert len(rows) == 2 and all(ESC in ln for ln in rows)


@pytest.mark.parametrize("flag", ["--slicer-sync", "--weigh-station"])
def test_pair_text_goes_with_slicer_sync_and_weigh_station(capsys, flag):
    rc, out, err = run(capsys, "pair", flag, "--text", "--no-wait")
    assert rc == 0 and err == "" and "fkit://pair" in out
