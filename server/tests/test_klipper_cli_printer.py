"""R83 10.5, the printer commands that call the Hub: `printer load|unload|clear`, `printer usage`, `printer show --watch`
(klipper_cli.py), each against a fake Hub built from the contract (hub_fakes.py): text, --json document, exit code, and
what was sent (always a dry run first). Plus the drift test of the catalogue texts the EV2 commands hold as constants
until part B moves them into strings/en.json. Example names only."""
from __future__ import annotations

import argparse
import builtins
import json
import re
from pathlib import Path

import pytest

from filament_kit import klipper_cli, output, spools_cli
from filament_kit.web.slots import SlotError
from hub_fakes import FakeApi, run_json, spool_view

P = {"serial": "S1", "name": "Workshop"}
SLOT = "/api/printers/S1/slots/A1"


@pytest.fixture(autouse=True)
def plain_output():
    output.reset()
    output.configure(plain=True)
    yield
    output.reset()


@pytest.fixture
def terminal(monkeypatch):
    def setup(*answers: str):
        left, asked = list(answers), []
        monkeypatch.setattr(output, "terminal", lambda: True)

        def fake_input(prompt=""):
            asked.append(prompt)
            print(prompt, end="")                    # what the real input() writes at a terminal
            if not left:
                raise EOFError
            return left.pop(0)
        monkeypatch.setattr(builtins, "input", fake_input)
        return asked
    return setup


def raw_spool(n=12, location="Shelf A") -> dict:
    """Spoolman's spool as load and unload answer with it."""
    return {"id": n, "location": location, "filament": {"id": 3, "name": "PLA Red", "vendor": {"name": "Acme"}}}


def load_answer(body: dict) -> dict:
    return {"slot": {"label": "A1", "location": "Workshop A1"}, "dry_run": bool(body["dry_run"]), "problems": [],
            "spool": raw_spool(body["spool_id"], "Workshop A1"), "confirmed": None if body["dry_run"] else True,
            "moved_back": [{"id": 7, "location": "Shelf C"}]}


# ---------- load ----------

def test_load_previews_asks_then_loads(capsys, terminal):
    api = FakeApi({f"POST {SLOT}/load": load_answer})
    asked = terminal("y")
    assert klipper_cli.cmd_printer_slot(api, P, "load", "A1", "12") == 0
    out = capsys.readouterr().out
    assert "Load spool 12, Acme PLA Red, into slot A1 of Workshop." in out and "Spool 7 goes back to Shelf C." in out
    assert asked == ["Load spool 12 into slot A1 of Workshop? [y/N] "]
    assert "Spool 12 is loaded in slot A1 of Workshop." in out
    assert [b for _, _, b in api.calls] == [{"spool_id": 12, "dry_run": True}, {"spool_id": 12, "dry_run": False}]


def test_load_that_waits_says_so(capsys):
    def answer(body):
        return {**load_answer(body), "pending": not body["dry_run"], "confirmed": None}
    assert klipper_cli.cmd_printer_slot(FakeApi({f"POST {SLOT}/load": answer}), P, "load", "A1", "12", yes=True) == 0
    out = capsys.readouterr().out
    assert "Waiting for the spool to load in A1." in out and "is loaded" not in out


def test_load_no_is_exit_5_and_sends_only_the_dry_run(capsys, terminal):
    api = FakeApi({f"POST {SLOT}/load": load_answer})
    terminal("n")
    assert klipper_cli.cmd_printer_slot(api, P, "load", "A1", "12") == output.CANCELLED
    assert [b["dry_run"] for _, _, b in api.calls] == [True]


def test_load_without_terminal_names_the_command_with_yes(capsys, monkeypatch):
    monkeypatch.setattr(output, "terminal", lambda: False)
    api = FakeApi({f"POST {SLOT}/load": load_answer})
    assert klipper_cli.cmd_printer_slot(api, P, "load", "A1", "12") == output.USAGE
    assert "spoolwarden printer load Workshop A1 12 --yes" in capsys.readouterr().err
    assert len(api.calls) == 1


def test_load_json_is_the_route_object():
    api = FakeApi({f"POST {SLOT}/load": load_answer})
    rc, doc = run_json(lambda: klipper_cli.cmd_printer_slot(api, P, "load", "A1", "12", yes=True))
    assert rc == 0 and doc["confirmed"] is True and doc["dry_run"] is False and doc["spool"]["id"] == 12


def test_load_refusals(capsys):
    refused = FakeApi({f"POST {SLOT}/load": SlotError("no preset of yours for Spoolman filament 3", code="no_preset",
                                                        http=409)})
    assert klipper_cli.cmd_printer_slot(refused, P, "load", "A1", "12", yes=True) == output.FAILED
    assert "the Hub did not change slot A1: no preset of yours for Spoolman filament 3." in " ".join(
        capsys.readouterr().err.split())
    assert klipper_cli.cmd_printer_slot(FakeApi(), P, "load", "A1", "x", yes=True) == output.USAGE
    assert klipper_cli.cmd_printer_slot(FakeApi(), P, "load", "A 1/..", "12", yes=True) == output.USAGE
    assert klipper_cli.cmd_printer_slot(None, P, "load", "A1", "12", yes=True) == output.HUB_DOWN
    unknown = FakeApi({f"POST {SLOT}/load": SlotError("no slot 'A1'", code="not_found", http=404)})
    assert klipper_cli.cmd_printer_slot(unknown, P, "load", "A1", "12", yes=True) == output.USAGE


# ---------- unload ----------

def unload_answer(body: dict) -> dict:
    return {"spool": raw_spool(12), "slot": {"label": "A1"}, "dry_run": bool(body["dry_run"]), "preset": None,
            "moved_back": [{"id": 12, "location": "Shelf A"}], "location": "Shelf A", "waiting_ended": not body["dry_run"]}


def test_unload(capsys, terminal):
    api = FakeApi({f"POST {SLOT}/unload": unload_answer})
    asked = terminal("y")
    assert klipper_cli.cmd_printer_slot(api, P, "unload", "A1") == 0
    out = capsys.readouterr().out
    assert "spool 12, Acme PLA Red, goes back to Shelf A." in out and asked == ["Unload slot A1 of Workshop? [y/N] "]
    assert "Slot A1 of Workshop is unloaded. Spool 12 is at Shelf A." in out
    assert "No spool waits for slot A1 any more." in out
    assert [b for _, _, b in api.calls] == [{"dry_run": True}, {"dry_run": False}]


def test_unload_json():
    api = FakeApi({f"POST {SLOT}/unload": unload_answer})
    rc, doc = run_json(lambda: klipper_cli.cmd_printer_slot(api, P, "unload", "A1", yes=True))
    assert rc == 0 and doc["waiting_ended"] is True and doc["location"] == "Shelf A"


# ---------- clear ----------

def clear_answer(body: dict) -> dict:
    return {"slot": "A1", "spool": spool_view(12), "moved_back": "Shelf A", "waiting_ended": True, "printer_cleared": True,
            "dry_run": bool(body["dry_run"])}


def test_clear_asks_with_the_ruled_text(capsys, terminal):
    api = FakeApi({f"POST {SLOT}/clear": clear_answer})
    asked = terminal("y")
    assert klipper_cli.cmd_printer_slot(api, P, "clear", "A1") == 0
    assert asked[0].endswith("[y/N] ")
    out = capsys.readouterr().out
    assert "Clear slot A1? The Hub forgets the spool recorded here. Acme PLA Red goes back to Shelf A. [y/N]" in " ".join(
        out.split())
    assert "Slot A1 of Workshop is cleared." in out and "Spool 12 goes back to Shelf A." in out
    assert "No spool waits for slot A1 any more." in out and "The slot's setting on the printer is cleared." in out
    assert [b for _, _, b in api.calls] == [{"dry_run": True}, {"dry_run": False}]


def test_clear_without_a_spool_has_the_short_question(capsys, terminal):
    api = FakeApi({f"POST {SLOT}/clear": lambda body: {"slot": "A1", "waiting_ended": False, "printer_cleared": False,
                                                        "dry_run": body["dry_run"]}})
    asked = terminal("y")
    assert klipper_cli.cmd_printer_slot(api, P, "clear", "A1") == 0
    assert asked == ["Clear slot A1? The Hub forgets the spool recorded here. [y/N] "]
    out = capsys.readouterr().out
    assert "No spool is recorded in slot A1." in out and "goes back" not in out and "printer is cleared" not in out


def test_clear_json_is_the_route_object():
    api = FakeApi({f"POST {SLOT}/clear": clear_answer})
    rc, doc = run_json(lambda: klipper_cli.cmd_printer_slot(api, P, "clear", "A1", yes=True))
    assert rc == 0 and doc["dry_run"] is False and doc["printer_cleared"] is True and doc["moved_back"] == "Shelf A"


def test_clear_json_without_yes_never_asks():
    api = FakeApi({f"POST {SLOT}/clear": clear_answer})
    rc, doc = run_json(lambda: klipper_cli.cmd_printer_slot(api, P, "clear", "A1"))
    assert rc == output.USAGE and doc["ok"] is False and len(api.calls) == 1


def test_a_slot_label_with_a_slash_cannot_reach_another_route():
    api = FakeApi()
    assert klipper_cli.cmd_printer_slot(api, P, "clear", "A1/unload", yes=True) == output.USAGE
    assert api.calls == []


# ---------- usage ----------

ENTRIES = {"entries": [
    {"id": "u1", "at": "2026-11-17T14:05:09+01:00", "job": "Benchy", "grams": 12.4, "spool_id": 12, "slot": "A1",
     "observe": False, "undone": False,
     "spool": {"id": 12, "vendor": "Acme", "name": "PLA Red", "material": "PLA", "color_hex": "cc0000", "state": "opened"}},
    {"id": "u2", "at": "2026-11-16T09:00:00+01:00", "job": "Clip", "grams": 3, "spool_id": None, "slot": "A2",
     "observe": True, "undone": True, "spool": None}]}


def test_usage_table(capsys):
    api = FakeApi({"GET /api/printers/S1/usage": ENTRIES})
    assert klipper_cli.cmd_printer_usage(api, P) == 0
    out = capsys.readouterr().out
    assert "2026-11-17 14:05" in out and "Benchy" in out and "12.4 g" in out and "12 Acme PLA Red" in out
    assert "no spool" in out and "undone, seen only" in out


def test_usage_days_and_json(capsys):
    api = FakeApi({"GET /api/printers/S1/usage?days=2": ENTRIES, "GET /api/printers/S1/usage?days=0.5": {"entries": []}})
    rc, doc = run_json(lambda: klipper_cli.cmd_printer_usage(api, P, 2.0))
    assert (rc, doc) == (0, ENTRIES)
    output.reset()
    output.configure(plain=True)
    assert klipper_cli.cmd_printer_usage(api, P, 0.5) == 0
    assert capsys.readouterr().out.strip() == "No filament used in the last 0.5 days."


def test_usage_empty_default_bad_days_and_no_hub(capsys):
    assert klipper_cli.cmd_printer_usage(FakeApi({"GET /api/printers/S1/usage": {"entries": []}}), P) == 0
    assert capsys.readouterr().out.strip() == "No filament used lately."
    assert klipper_cli.cmd_printer_usage(FakeApi(), P, -1) == output.USAGE
    assert klipper_cli.cmd_printer_usage(None, P) == output.HUB_DOWN
    unknown = FakeApi({"GET /api/printers/S1/usage": SlotError("no printer", code="not_found", http=404)})
    assert klipper_cli.cmd_printer_usage(unknown, P) == output.USAGE


# ---------- show --watch ----------

LIVE = {"printer": {"id": "S1", "name": "Workshop", "state": "connected"},
        "status": {"gcode_state": "RUNNING", "stage": "Printing", "job": "Benchy", "percent": 42, "layer": 10,
                   "total_layers": 100, "remaining_min": 75,
                   "temps": {"nozzle": [{"current": 215.0, "target": 220.0}], "bed": {"current": 60, "target": 60},
                             "chamber": None},
                   "ams": [{"slots": [{"label": "A1", "name": "PLA", "present": True,
                                       "spool": {"id": 12, "name": "Acme PLA Red", "remaining_weight": 640.0}},
                                      {"label": "A2", "present": True, "type": "PETG",
                                       "pending": {"spool_id": 13, "text": "waiting"}}]}]}}


def test_watch_asks_again_and_ends_after_the_ticks(capsys):
    api = FakeApi({"GET /api/printers/S1": LIVE})
    slept = []
    assert klipper_cli.cmd_printer_watch(api, P, ticks=3, sleep=slept.append) == 0
    out = capsys.readouterr().out
    assert len(api.calls) == 3 and slept == [10.0, 10.0]        # plain: a whole look every 10 seconds
    assert out.count("Workshop: RUNNING, Printing") == 3
    assert "Benchy, 42%, layer 10 of 100, 1 h 15 min left" in out
    assert "nozzle 215/220 °C, bed 60/60 °C" in out
    assert "Acme PLA Red" in out and "640 g" in out and "PETG (waiting: spool 13)" in out


def test_watch_at_a_terminal_every_two_seconds_and_ctrl_c_ends_it(capsys, monkeypatch):
    output.reset()
    monkeypatch.setattr(output, "terminal", lambda: True)
    api = FakeApi({"GET /api/printers/S1": LIVE})
    slept = []

    def sleep(s):
        slept.append(s)
        raise KeyboardInterrupt
    assert klipper_cli.cmd_printer_watch(api, P, sleep=sleep) == 0
    assert slept == [2.0] and "(Ctrl-C stops)" in capsys.readouterr().out


def test_watch_json_is_one_look():
    api = FakeApi({"GET /api/printers/S1": LIVE})
    rc, doc = run_json(lambda: klipper_cli.cmd_printer_watch(api, P, sleep=lambda s: pytest.fail("looped")))
    assert (rc, doc) == (0, LIVE) and len(api.calls) == 1


def test_watch_stops_when_the_hub_stops_answering(capsys):
    api = FakeApi({"GET /api/printers/S1": SlotError("not reachable", code="unreachable")})
    assert klipper_cli.cmd_printer_watch(api, P, sleep=lambda s: None) == output.HUB_DOWN
    assert klipper_cli.cmd_printer_watch(None, P) == output.HUB_DOWN


# ---------- parsers ----------

def test_printer_parsers_and_run(capsys):
    ap = argparse.ArgumentParser()
    psub = ap.add_subparsers(dest="printer_cmd", required=True)
    klipper_cli.add_printer_parsers(psub)
    a = ap.parse_args(["load", "Workshop", "A1", "12", "-y"])
    assert (a.printer, a.slot, a.spool, a.yes) == ("Workshop", "A1", "12", True)
    assert ap.parse_args(["usage", "Workshop", "--days", "3"]).days == 3.0
    with pytest.raises(SystemExit):
        ap.parse_args(["load", "Workshop", "A1"])                 # a spool number is needed
    api = FakeApi({f"POST {SLOT}/clear": clear_answer})
    assert klipper_cli.run_printer(ap.parse_args(["clear", "Workshop", "A1", "-y"]), api, P) == 0
    api = FakeApi({"GET /api/printers/S1/usage?days=3": {"entries": []}})
    assert klipper_cli.run_printer(ap.parse_args(["usage", "Workshop", "--days", "3"]), api, P) == 0


# ---------- the catalogue texts held as constants until part B ----------

EN = Path(__file__).resolve().parents[2] / "strings" / "en.json"


def test_catalogue_texts_are_named_like_keys_and_use_known_fields():
    texts = spools_cli.catalogue_texts()
    assert len(texts) > 60 and all(re.fullmatch(r"cli_[a-z0-9_]+", k) for k in texts)
    for key, text in texts.items():
        assert text.strip(), key
        assert set(re.findall(r"\{(\w+)\}", text)) <= {"n", "name", "slot", "printer", "place", "why", "value", "days", "url",
                                                          "brand", "material", "field", "text", "id", "names", "setting",
                                                          "ids", "choices", "low", "high", "label", "device", "after",
                                                          "before"}, key


def test_texts_already_in_the_catalogue_have_not_drifted():
    """Part B moves the keys into strings/en.json; from then on the file and the constants must say the same."""
    catalogue = json.loads(EN.read_text(encoding="utf-8"))
    drift = {k: (v, catalogue[k]) for k, v in spools_cli.catalogue_texts().items() if k in catalogue and catalogue[k] != v}
    assert drift == {}


@pytest.mark.xfail(reason="part B (after AF5 is merged into next) adds these keys to strings/en.json", strict=False)
def test_every_cli_text_is_in_the_catalogue():
    catalogue = json.loads(EN.read_text(encoding="utf-8"))
    assert [k for k in spools_cli.catalogue_texts() if k not in catalogue] == []
