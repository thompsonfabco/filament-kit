"""R83 10.5: `spools`, `spool show|weigh|move|empty`, `catalog local|local remove|add --ask`, `devices show|set`, each
against a fake Hub built from the contract (hub_fakes.py): the human text, the --json document, the exit code, and
what was sent (a dry run first, the real change only after a yes). Example names only."""
from __future__ import annotations

import argparse
import builtins

import pytest

from filament_kit import output, spools_cli
from filament_kit.web.slots import SlotError
from hub_fakes import FakeApi, FakePage, run_json, spool_view


@pytest.fixture(autouse=True)
def plain_output():
    output.reset()
    output.configure(plain=True)
    yield
    output.reset()


@pytest.fixture
def terminal(monkeypatch):
    """`terminal("y")`: standard input is a terminal and answers each question in turn."""
    def setup(*answers: str):
        left = list(answers)
        asked: list[str] = []
        monkeypatch.setattr(output, "terminal", lambda: True)

        def fake_input(prompt=""):
            asked.append(prompt)
            if not left:
                raise EOFError
            return left.pop(0)
        monkeypatch.setattr(builtins, "input", fake_input)
        return asked
    return setup


def listing(*views, **extra) -> dict:
    return {"spools": [{"id": v["id"], "view": v} for v in views], "total": len(views), "offset": 0, "has_more": False,
            **extra}


# ---------- spools ----------

def test_spools_table_count_and_spoolman_line(capsys):
    a = spool_view(12)
    b = spool_view(13, vendor="Other", name="PETG Blue", material="PETG", remaining_g=90.0, low=True, tag="04AABB",
                   loaded={"printer_id": "S1", "printer": "Workshop", "slot": "A1"}, state="sealed")
    api = FakeApi({"GET /api/spools": listing(a, b, spoolman_url="http://hub.local:7912")})
    assert spools_cli.cmd_spools(api) == 0
    out = capsys.readouterr().out
    assert "Acme PLA Red" in out and "640 g" in out and "Shelf A" in out
    assert "in Workshop, A1" in out and "sealed, low, tagged" in out
    assert "2 spools." in out and out.rstrip().endswith("Spoolman: http://hub.local:7912")


def test_spools_words_and_filter_go_in_the_query(capsys):
    api = FakeApi({"GET /api/spools?q=acme+red&filter=low": listing(spool_view(12))})
    assert spools_cli.cmd_spools(api, ["acme", "red"], "low") == 0
    assert api.calls[0][1] == "GET /api/spools?q=acme+red&filter=low".split(" ", 1)[1]
    assert "1 spool." in capsys.readouterr().out


def test_spools_empty_and_no_match(capsys):
    api = FakeApi({"GET /api/spools": listing(), "GET /api/spools?q=zzz": listing()})
    assert spools_cli.cmd_spools(api) == 0
    assert capsys.readouterr().out.strip() == "No spools yet. Add your first one from your phone."
    assert spools_cli.cmd_spools(api, ["zzz"]) == 0
    assert capsys.readouterr().out.strip() == "No spool matches."


def test_spools_json_is_the_route_object():
    answer = listing(spool_view(12), spoolman_url="http://hub.local:7912")
    rc, doc = run_json(lambda: spools_cli.cmd_spools(FakeApi({"GET /api/spools": answer})))
    assert rc == 0 and doc == answer


def test_no_hub_is_exit_4(capsys):
    assert spools_cli.cmd_spools(None) == output.HUB_DOWN
    err = capsys.readouterr().err
    assert "the Hub is not running" in err and "sudo systemctl start filament-kit" in err


def test_unreachable_hub_is_exit_4(capsys):
    api = FakeApi({"GET /api/spools": SlotError("the kit server is not reachable", code="unreachable")})
    assert spools_cli.cmd_spools(api) == output.HUB_DOWN


# ---------- spool show ----------

def test_spool_show(capsys):
    v = spool_view(12, tag="04AABB", lot="L7", low=True)
    api = FakeApi({"GET /api/spools/12": {"spool": {"id": 12}, "view": v}})
    assert spools_cli.cmd_spool_show(api, "12") == 0
    out = capsys.readouterr().out
    assert out.startswith("Spool 12: Acme PLA Red") and "640 g of 1000 g" in out and "running low" in out
    assert "04AABB" in out and "L7" in out


def test_spool_show_json_and_unknown_spool(capsys):
    answer = {"spool": {"id": 12}, "view": spool_view(12)}
    rc, doc = run_json(lambda: spools_cli.cmd_spool_show(FakeApi({"GET /api/spools/12": answer}), "12"))
    assert (rc, doc) == (0, answer)
    api = FakeApi({"GET /api/spools/99": SlotError("not found", code="not_found", http=404)})
    assert spools_cli.cmd_spool_show(api, "99") == output.USAGE
    assert "there is no spool 99." in capsys.readouterr().err
    assert spools_cli.cmd_spool_show(api, "abc") == output.USAGE


# ---------- spool weigh / move / empty ----------

def edit(before: dict, after: dict):
    """The route's answer: a dry run shows `after` and dry true, the real call the same with dry false."""
    return lambda body: {"spool": {"id": before["id"]}, "view": after, "before": before, "dry": bool(body["dry_run"])}


def test_weigh_previews_asks_then_changes(capsys, terminal):
    before, after = spool_view(12), spool_view(12, remaining_g=512.0)
    api = FakeApi({"PATCH /api/spools/12": edit(before, after)})
    asked = terminal("y")
    assert spools_cli.cmd_spool_weigh(api, "12", "692") == 0
    out = capsys.readouterr().out
    assert "640 g left, would be 512 g left" in out and asked == ["Set spool 12 to 512 g left? [y/N] "]
    assert "Spool 12 has 512 g left." in out
    assert [b for _, _, b in api.calls] == [{"gross": 692.0, "dry_run": True}, {"gross": 692.0, "dry_run": False}]


def test_weigh_answered_no_changes_nothing(capsys, terminal):
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, remaining_g=512.0))})
    terminal("n")
    assert spools_cli.cmd_spool_weigh(api, "12", "692") == output.CANCELLED
    assert "Nothing changed." in capsys.readouterr().out
    assert [b["dry_run"] for _, _, b in api.calls] == [True]


def test_weigh_yes_does_not_ask(capsys):
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, remaining_g=512.0))})
    assert spools_cli.cmd_spool_weigh(api, "12", "692", yes=True) == 0
    assert "[y/N]" not in capsys.readouterr().out
    assert [b["dry_run"] for _, _, b in api.calls] == [True, False]


def test_change_without_terminal_and_without_yes_is_exit_2_and_changes_nothing(capsys, monkeypatch):
    monkeypatch.setattr(output, "terminal", lambda: False)
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, remaining_g=512.0))})
    assert spools_cli.cmd_spool_weigh(api, "12", "692") == output.USAGE
    err = capsys.readouterr().err
    assert "needs a yes" in err and "spoolwarden spool weigh 12 692 --yes" in err
    assert [b["dry_run"] for _, _, b in api.calls] == [True]


def test_weigh_json_never_asks_and_gives_the_changed_object():
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, remaining_g=512.0))})
    rc, doc = run_json(lambda: spools_cli.cmd_spool_weigh(api, "12", "692"))
    assert rc == output.USAGE and doc["ok"] is False          # --json never asks: it needs -y
    rc, doc = run_json(lambda: spools_cli.cmd_spool_weigh(api, "12", "692", yes=True))
    assert rc == 0 and doc["dry"] is False and doc["view"]["remaining_g"] == 512.0 and doc["before"]["remaining_g"] == 640.0


def test_weigh_bad_grams_and_refusal(capsys):
    assert spools_cli.cmd_spool_weigh(FakeApi(), "12", "heavy") == output.USAGE
    assert "heavy is not a number of grams." in capsys.readouterr().err
    api = FakeApi({"PATCH /api/spools/12": SlotError("gross 100 g is below the spool tare 180 g - check the weight",
                                                       code="bad_request", http=400)})
    assert spools_cli.cmd_spool_weigh(api, "12", "100") == output.USAGE
    assert "below the spool tare" in capsys.readouterr().err


def test_move(capsys, terminal):
    before, after = spool_view(12), spool_view(12, location="Shelf B")
    api = FakeApi({"PATCH /api/spools/12": edit(before, after)})
    terminal("yes")
    assert spools_cli.cmd_spool_move(api, "12", "Shelf B") == 0
    out = capsys.readouterr().out
    assert "now Shelf A, would go to Shelf B" in out and "Spool 12 is now at Shelf B." in out
    assert api.calls[0][2] == {"location": "Shelf B", "dry_run": True}


def test_move_auto_sends_the_automatic_choice_not_a_place_called_auto():
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, location="Dry box 2"))})
    assert spools_cli.cmd_spool_move(api, "12", "auto", yes=True) == 0
    assert api.calls[0][2] == {"auto_location": True, "dry_run": True}


def test_move_to_where_it_is_changes_nothing(capsys):
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12))})
    assert spools_cli.cmd_spool_move(api, "12", "Shelf A") == 0
    assert "Spool 12 is already at Shelf A." in capsys.readouterr().out
    assert len(api.calls) == 1


def test_empty(capsys, terminal):
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, remaining_g=0, state="empty"))})
    asked = terminal("y")
    assert spools_cli.cmd_spool_empty(api, "12") == 0
    assert asked == ["Mark spool 12 empty? [y/N] "]
    out = capsys.readouterr().out
    assert "would be marked empty" in out and "Spool 12 is marked empty." in out
    assert api.calls[1][2] == {"empty": True, "dry_run": False}


def test_edit_of_unknown_spool(capsys):
    api = FakeApi({"PATCH /api/spools/99": SlotError("not found", code="not_found", http=404)})
    assert spools_cli.cmd_spool_empty(api, "99", yes=True) == output.USAGE
    assert "there is no spool 99." in capsys.readouterr().err


# ---------- catalog ----------

ENTRY = {"id": "e1", "brand": "Acme", "name": "PLA Red", "material": "PLA", "added": "2026-11-01"}


def test_catalog_local_lists_and_json(capsys):
    api = FakeApi({"GET /api/library/local": {"entries": [ENTRY]}})
    assert spools_cli.cmd_catalog_local(api) == 0
    out = capsys.readouterr().out
    assert "e1" in out and "Acme" in out and "2026-11-01" in out
    rc, doc = run_json(lambda: spools_cli.cmd_catalog_local(api))
    assert (rc, doc) == (0, {"entries": [ENTRY]})


def test_catalog_local_empty(capsys):
    api = FakeApi({"GET /api/library/local": {"entries": []}})
    assert spools_cli.cmd_catalog_local(api) == 0
    out = capsys.readouterr().out
    assert "No entries of your own yet." in out and "Add one: spoolwarden catalog add --ask" in out


def test_catalog_remove_asks_with_the_hub_text(capsys, terminal):
    api = FakeApi({"GET /api/library/local": {"entries": [ENTRY]}, "DELETE /api/library/local/e1": {"removed": True}})
    asked = terminal("y")
    assert spools_cli.cmd_catalog_local_remove(api, "e1") == 0
    assert asked == ["Remove Acme PLA Red from your own entries? Slicer presets are rebuilt. [y/N] "]
    assert "Removed Acme PLA Red." in capsys.readouterr().out
    assert ("DELETE", "/api/library/local/e1", None) in api.calls


def test_catalog_remove_no_and_unknown(capsys, terminal):
    api = FakeApi({"GET /api/library/local": {"entries": [ENTRY]}})
    terminal("n")
    assert spools_cli.cmd_catalog_local_remove(api, "e1") == output.CANCELLED
    assert not any(m == "DELETE" for m, _, _ in api.calls)
    assert spools_cli.cmd_catalog_local_remove(api, "zz", yes=True) == output.USAGE
    assert "there is no entry zz of your own." in capsys.readouterr().err


def test_catalog_remove_json():
    api = FakeApi({"GET /api/library/local": {"entries": [ENTRY]}, "DELETE /api/library/local/e1": {"removed": True}})
    rc, doc = run_json(lambda: spools_cli.cmd_catalog_local_remove(api, "e1", yes=True))
    assert (rc, doc) == (0, {"removed": True})


def asking(*answers):
    left = list(answers)
    asked: list[str] = []

    def ask(prompt):
        asked.append(prompt)
        return left.pop(0)
    ask.asked = asked
    return ask


def test_catalog_add_ask_three_fields(capsys):
    created = {"entry": ENTRY}
    api = FakeApi({"POST /api/library/local/form": created})
    ask = asking("Acme", "PLA Red", "PLA", "n")
    assert spools_cli.cmd_catalog_add_ask(api, ask=ask, yes=True) == 0
    assert [p.split(" (")[0].split(":")[0] for p in ask.asked[:3]] == ["Brand", "Name", "Material"]
    assert api.calls[0][2] == {"brand": "Acme", "name": "PLA Red", "material": "PLA"}
    assert "Added. Slicer presets are rebuilt in a minute." in capsys.readouterr().out


def test_catalog_add_ask_more_in_the_forms_order():
    api = FakeApi({"POST /api/library/local/form": {"entry": ENTRY}})
    ask = asking("Acme", "PLA Red", "PLA", "y", "200", "220", "50", "60", "1.24", "15", "", "my notes")
    assert spools_cli.cmd_catalog_add_ask(api, ask=ask, yes=True) == 0
    assert api.calls[0][2] == {"brand": "Acme", "name": "PLA Red", "material": "PLA", "nozzle_min": 200.0,
                               "nozzle_max": 220.0, "bed_min": 50.0, "bed_max": 60.0, "density": 1.24,
                               "max_volumetric_speed": 15.0, "notes": "my notes"}
    assert len(ask.asked) == 12


def test_catalog_add_ask_confirms_unless_yes(capsys, terminal):
    api = FakeApi({"POST /api/library/local/form": {"entry": ENTRY}})
    asked = terminal("n")
    assert spools_cli.cmd_catalog_add_ask(api, ask=asking("Acme", "PLA Red", "PLA", "n")) == output.CANCELLED
    assert asked == ["Add Acme PLA Red (PLA)? [y/N] "] and api.calls == []


def test_catalog_add_ask_needs_the_three_and_a_terminal(capsys, monkeypatch):
    assert spools_cli.cmd_catalog_add_ask(FakeApi(), ask=asking("Acme", "", "PLA")) == output.USAGE
    assert "Name is needed." in capsys.readouterr().err
    monkeypatch.setattr(output, "terminal", lambda: False)
    assert spools_cli.cmd_catalog_add_ask(FakeApi()) == output.USAGE
    assert "catalog add <file>" in capsys.readouterr().err


def test_catalog_add_ask_problems_are_printed(capsys):
    err = SlotError("invalid entry", code="invalid_entry", http=400)
    err.problems = [{"field": "material", "text": "Material is not one the catalog knows."}]
    api = FakeApi({"POST /api/library/local/form": err})
    assert spools_cli.cmd_catalog_add_ask(api, ask=asking("Acme", "X", "Zork", "n"), yes=True) == output.USAGE
    assert "material: Material is not one the catalog knows." in capsys.readouterr().err


def test_catalog_add_ask_json_gives_the_created_object():
    created = {"entry": ENTRY}
    api = FakeApi({"POST /api/library/local/form": created})
    rc, doc = run_json(lambda: spools_cli.cmd_catalog_add_ask(api, ask=asking("Acme", "PLA Red", "PLA", "n"), yes=True))
    assert (rc, doc) == (0, created)


# ---------- devices ----------

STATION = {"id": "d1", "name": "Weigh Station", "kind": "station", "version": "0.5.0", "newest": "0.7.0",
           "out_of_date": True, "advice": "Out of date (0.5.0; the Hub is 0.7.0). On that machine: sudo spoolwarden update",
           "paired": "2026-10-01", "last_seen": "2026-11-17 12:00", "reachable": True, "built_in": False, "page": True}
PHONE = {"id": "d2", "name": "Phone", "kind": "phone", "out_of_date": False, "built_in": False, "page": False}
SETTINGS = [{"id": "beep", "label": "Beep", "kind": "switch", "value": True},
            {"id": "voice", "label": "Voice", "kind": "choice", "value": "plain", "choices": ["plain", "kind"]},
            {"id": "volume", "label": "Volume", "kind": "number", "value": 5, "min": 0, "max": 10},
            {"id": "lamp.weigh", "label": "Lamp for weighing", "kind": "choice", "value": "off",
             "choices": ["off", "green", "yellow"]}]


def devpage() -> FakePage:
    return FakePage({"GET devices": {"devices": [STATION, PHONE]},
                     "GET device/d1": {"device": STATION, "status": {"scale": "ok", "last_weight": 812.5},
                                       "settings": SETTINGS},
                     "POST device/d1/settings": lambda body: {"settings": [{**s, "value": body.get(s["id"], s["value"])}
                                                                           for s in SETTINGS]}})


def test_devices_show_station(capsys):
    assert spools_cli.cmd_devices_show(devpage(), "d1") == 0
    out = capsys.readouterr().out
    assert "Weigh Station" in out and "0.5.0" in out and "answering" in out
    assert "Out of date (0.5.0; the Hub is 0.7.0). On that machine:" in out
    assert "sudo spoolwarden update" in out
    assert "last_weight" in out and "812.5" in out and "lamp.weigh" in out and "beep" in out and "on" in out


def test_devices_show_by_name_and_without_a_page(capsys):
    page = devpage()
    assert spools_cli.cmd_devices_show(page, "phone") == 0
    out = capsys.readouterr().out
    assert "Phone" in out and "Version not known" in out and "never" in out
    assert not any(r.startswith("device/") for _, r, _ in page.calls)


def test_devices_show_json_and_unknown(capsys):
    rc, doc = run_json(lambda: spools_cli.cmd_devices_show(devpage(), "weigh"))
    assert rc == 0 and doc["device"]["id"] == "d1" and doc["settings"]
    assert spools_cli.cmd_devices_show(devpage(), "nothing") == output.USAGE
    assert "there is no device nothing." in capsys.readouterr().err


def test_devices_set_asks_then_sends_the_typed_value(capsys, terminal):
    page = devpage()
    asked = terminal("y")
    assert spools_cli.cmd_devices_set(page, "d1", "voice", "kind") == 0
    assert asked == ["Set Voice to kind on Weigh Station? [y/N] "]
    assert page.calls[-1] == ("POST", "device/d1/settings", {"voice": "kind"})
    assert "Voice is now kind on Weigh Station." in capsys.readouterr().out


def test_devices_set_value_kinds():
    page = devpage()
    assert spools_cli.cmd_devices_set(page, "d1", "beep", "off", yes=True) == 0
    assert page.calls[-1][2] == {"beep": False}
    assert spools_cli.cmd_devices_set(page, "d1", "volume", "7", yes=True) == 0
    assert page.calls[-1][2] == {"volume": 7}
    assert spools_cli.cmd_devices_set(page, "d1", "lamp.weigh", "Green", yes=True) == 0
    assert page.calls[-1][2] == {"lamp.weigh": "green"}


def test_devices_set_refuses_a_bad_value_or_setting_before_sending(capsys):
    page = devpage()
    for setting, value, text in (("volume", "11", "give a number from 0 to 10"), ("voice", "loud", "choose one of plain, kind"),
                                 ("beep", "maybe", "use on or off")):
        assert spools_cli.cmd_devices_set(page, "d1", setting, value, yes=True) == output.USAGE
        assert text in capsys.readouterr().err
    assert spools_cli.cmd_devices_set(page, "d1", "colour", "red", yes=True) == output.USAGE
    assert "its settings are: beep, voice, volume, lamp.weigh" in capsys.readouterr().err
    assert spools_cli.cmd_devices_set(page, "d2", "beep", "on", yes=True) == output.USAGE
    assert not any(m == "POST" for m, _, _ in page.calls)


def test_devices_set_same_value_changes_nothing(capsys):
    page = devpage()
    assert spools_cli.cmd_devices_set(page, "d1", "beep", "on") == 0
    assert "Beep is already on on Weigh Station." in capsys.readouterr().out
    assert not any(m == "POST" for m, _, _ in page.calls)


def test_devices_set_json_gives_the_new_list():
    rc, doc = run_json(lambda: spools_cli.cmd_devices_set(devpage(), "d1", "volume", "3", yes=True))
    assert rc == 0 and next(s for s in doc["settings"] if s["id"] == "volume")["value"] == 3


def test_kind_and_version_words_for_the_devices_table():
    assert [spools_cli.kind_word(k) for k in ("phone", "pc", "station", "web", "reader", "builtin", None)] == [
        "Phone", "Slicer Sync PC", "Weigh Station", "Web app", "Tag Reader", "built in", ""]
    assert spools_cli.version_cell({"version": "0.7.0"}) == "0.7.0"
    assert spools_cli.version_cell({}) == "Version not known"


# ---------- the parsers ----------

def parse(*argv):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    spools_cli.add_parser(sub)
    return ap.parse_args(argv)


def test_parsers_and_run(capsys):
    a = parse("spools", "acme", "red", "--low")
    assert (a.words, a.filter) == (["acme", "red"], "low")
    assert parse("spools").filter is None
    with pytest.raises(SystemExit):
        parse("spools", "--low", "--sealed")
    api = FakeApi({"GET /api/spools?q=acme&filter=sealed": listing(spool_view(12))})
    assert spools_cli.run(parse("spools", "acme", "--sealed"), api) == 0
    b = parse("spool", "weigh", "12", "692", "-y")
    assert (b.spool_cmd, b.number, b.grams, b.yes) == ("weigh", "12", "692", True)
    assert parse("spool", "move", "12", "auto").location == "auto"
    api = FakeApi({"PATCH /api/spools/12": edit(spool_view(12), spool_view(12, remaining_g=0, state="empty"))})
    assert spools_cli.run(parse("spool", "empty", "12", "-y"), api) == 0
    assert "Spool 12 is marked empty." in capsys.readouterr().out
    assert spools_cli.run(parse("spool", "show", "12"), FakeApi({"GET /api/spools/12": {"spool": {}, "view": spool_view(12)}})) == 0
