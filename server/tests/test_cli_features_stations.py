"""S5.7: `features` (06 9.6), `weigh-station` and `tag-reader` (06 9.7), with the old spellings (`modules`, `station`,
`reader`) as the same commands. AUT-9 for `features`: 79-column lines, no escape byte without colour, ASCII with
`--plain`, `--json` parses. Example names and addresses only."""
from __future__ import annotations

import json
import re
import types

import pytest
from test_cli_modules import _deep, _stdin, _terminal, applied, env  # noqa: F401  (fixtures and helpers)

from filament_kit import apply, cli, config, modules, output
from filament_kit.station import server_api

ESC = "\x1b"


def run(capsys, *args):
    rc = cli.main(list(args))
    got = capsys.readouterr()
    return rc, got.out, got.err


@pytest.fixture(autouse=True)
def glyphs(monkeypatch):
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")


def flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------- the keys

def test_every_feature_has_one_key_and_the_titles_are_the_hub_pages():
    assert list(cli._FEATURE_KEYS) == ["spoolman", "hub", "label-reader", "label-reader-local", "printers", "klipper",
                                       "presets", "catalog", "backups", "weigh-station", "web", "remote", "orders",
                                       "updates"]
    assert sorted(cli._FEATURE_KEYS.values()) == sorted(modules.MODULES)             # each module has exactly one key
    assert [modules.MODULES[old].title for old in cli._FEATURE_KEYS.values()] == [
        "Spoolman", "Hub service", "Label Reader: Cloud (Claude)", "Label Reader: On this Hub", "Bambu Lab printers",
        "Klipper printers", "Slicer presets", "Filament Catalog", "Nightly backup", "Weigh Station", "Web access",
        "Remote access", "Order history", "Automatic updates"]


def test_a_key_the_old_name_or_the_title_names_the_same_feature(applied, capsys):
    for word in ("label-reader-local", "local_intake", "Label Reader: On this Hub", "LABEL-READER-LOCAL"):
        assert cli._feature_named(word) == "local_intake", word
    assert cli._feature_named("nope") is None and 'Error: "nope" is not a Feature.' in capsys.readouterr().err


# ---------------------------------------------------------------- features (list)

def test_features_json_is_the_hubs_modules_state_plus_the_setup(capsys):
    rc, out, _ = run(capsys, "features", "--json")
    got = json.loads(out)
    assert rc == 0 and out.count("\n") == 1 and got["setup"] == "server"
    row = next(m for m in got["modules"] if m["name"] == "server")
    assert row == {"name": "server", "key": "hub", "title": "Hub service",
                   "description": modules.MODULES["server"].description, "needs": ["Spoolman (this machine or a remote one)"],
                   "optional_ai": False, "on": True}
    assert {m["name"] for m in got["modules"]} == set(modules.MODULES)


def test_features_in_a_custom_setup_says_custom(applied, capsys):
    cfg = config.load()
    cfg["modules"] = {n: n == "backup" for n in modules.MODULES}
    config.save(cfg)
    assert run(capsys, "features")[1].splitlines()[0] == "Setup: custom"


# ---------------------------------------------------------------- features on / off

def test_on_asks_one_question_for_each_feature_it_needs_then_the_plan_then_applies(applied, capsys, monkeypatch):
    config.save(modules.set_mode(config.load(), "station"))
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    asked = []
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: asked.append(q) or True)
    rc, out, _ = run(capsys, "features", "on", "printers")
    assert rc == 0 and asked == ["Also turn on Hub service? Bambu Lab printers needs it. [y/N] "]
    lines = flat(out)
    assert lines.index("Turns on: Hub service (Bambu Lab printers needs it), Bambu Lab printers.") < lines.index("Features applied: ")
    assert lines.endswith("Features applied: Hub service on, Bambu Lab printers on.")
    assert config.load()["modules"]["server"] is True and config.load()["modules"]["printers"] is True


def test_off_with_dependants_asks_each_and_a_no_stops_with_exit_5(applied, capsys, monkeypatch):
    asked, answers = [], iter([True, False])
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(cli, "_tty_confirm", lambda q: asked.append(q) or next(answers))
    before = config.load()
    rc, out, _ = run(capsys, "features", "off", "hub")
    assert rc == 5 and out.strip().endswith("Nothing changed.") and len(asked) == 2
    assert asked[0].startswith("Also turn off Label Reader: Cloud (Claude)? It needs Hub service.")
    assert config.load() == before and applied == []


def test_without_a_terminal_a_cascade_stops_with_exit_2_and_yes_answers_it(applied, capsys, monkeypatch):
    _stdin(monkeypatch, "")
    rc, out, err = run(capsys, "features", "off", "hub")
    assert rc == 2 and out == ""
    assert "Fix: add --yes to accept the cascade, or switch the others first." in err and applied == []
    assert "modules" not in config.load()
    cfg = config.load()
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    rc, out, _ = run(capsys, "features", "off", "hub", "--yes")
    assert rc == 0 and "Hub service off" in flat(out) and config.load()["modules"]["server"] is False


def test_on_for_a_feature_already_on_says_unchanged(applied, capsys):
    rc, out, _ = run(capsys, "features", "on", "spoolman")
    assert rc == 0 and out.strip().endswith("Unchanged.") and "Turns" not in out and "Features applied" not in out


def test_json_never_asks_and_on_gives_the_changes(applied, capsys):
    rc, out, _ = run(capsys, "features", "off", "hub", "--json")
    assert rc == 2 and json.loads(out)["ok"] is False and "add --yes" in json.loads(out)["fix"]
    rc, out, _ = run(capsys, "features", "on", "backups", "--json")
    assert rc == 0 and json.loads(out) == {"ok": True, "changed": False, "on": [], "off": []}
    rc, out, _ = run(capsys, "features", "off", "backups", "--json")
    assert rc == 0 and json.loads(out) == {"ok": True, "changed": True, "on": [], "off": ["backups"]}


def test_the_hub_address_prompt_is_the_checklists_and_hub_answers_it(applied, capsys, monkeypatch):
    cfg = config.load()
    cfg["modules"] = {n: n == "backup" for n in modules.MODULES}
    config.save(cfg)
    asked = _terminal(monkeypatch, "192.168.1.0/24", "192.0.2.10")
    rc, out, err = run(capsys, "features", "on", "weigh-station")
    assert rc == 0 and "Weigh Station only needs the Hub's address." in out
    assert asked == ["The Hub's address (IP address or name): "] * 2
    assert "Error: enter one address or name, not a range or wildcard." in err
    assert config.load()["station"]["allow"] == ["192.0.2.10"]
    rc, out, _ = run(capsys, "features", "off", "weigh-station")
    assert rc == 0
    assert run(capsys, "features", "on", "weigh-station", "--hub", "192.0.2.11")[0] == 0
    assert config.load()["station"]["allow"] == ["192.0.2.11"]


def test_off_takes_hub_too_and_the_old_server_switch(applied, capsys):
    assert run(capsys, "features", "off", "backups", "--hub", "192.0.2.11")[0] == 0
    assert run(capsys, "modules", "enable", "backup", "--server", "192.0.2.11")[0] == 0


# ---------------------------------------------------------------- features setup

@pytest.mark.parametrize("new,old", [("hub", "server"), ("weigh-station", "station"),
                                     ("hub-with-weigh-station", "all-in-one")])
def test_the_new_setup_names_select_the_same_setup_as_the_old_words(new, old, applied, capsys):
    rc, out, _ = run(capsys, "features", "setup", new, "--hub", "192.0.2.10")
    first = config.load()
    assert rc == 0 and modules.mode_of(modules.enabled(first)) == old
    config.save({})
    rc, out_old, _ = run(capsys, "modules", "set", old, "--server", "192.0.2.10")
    assert rc == 0 and config.load() == first and out_old.splitlines()[0] == out.splitlines()[0]


def test_setup_says_the_setup_then_the_plan_then_the_apply(applied, capsys):
    rc, out, _ = run(capsys, "features", "setup", "weigh-station", "--hub", "192.0.2.10")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "Setup: Weigh Station only."
    assert flat(out).index("Turns on:") > flat(out).index("Setup: Weigh Station only.")
    assert flat(out).endswith("Features applied: " + flat(out).split("Features applied: ")[1])
    assert config.load()["station"]["allow"] == ["192.0.2.10"]


def test_the_weigh_station_setup_asks_for_the_hubs_address_when_none_is_given(applied, capsys, monkeypatch):
    asked = _terminal(monkeypatch, "192.0.2.10")
    rc, out, _ = run(capsys, "features", "setup", "weigh-station")
    assert rc == 0 and asked == ["The Hub's address (IP address or name): "]
    assert "Weigh Station only needs the Hub's address." in out and config.load()["station"]["allow"] == ["192.0.2.10"]
    asked = _terminal(monkeypatch)                                         # an empty answer: nothing changes
    config.save({})
    assert run(capsys, "features", "setup", "weigh-station")[0] == 1 and "modules" not in config.load()


def test_the_weigh_station_setup_under_json_needs_the_hub_option(applied, capsys):
    rc, out, err = run(capsys, "features", "setup", "weigh-station", "--json")
    assert rc == 2 and "--hub" in json.loads(out)["fix"] and "modules" not in config.load()


def test_the_weigh_station_setup_without_a_terminal_or_hub_stops_first_with_exit_2(applied, capsys, monkeypatch):
    _stdin(monkeypatch, "")
    before = config.load()
    rc, out, err = run(capsys, "features", "setup", "weigh-station")
    assert rc == 2 and out == "" and config.load() == before and applied == []        # no output, no change, no apply
    assert flat(err).startswith("Error: the Weigh Station only setup needs the Hub's address, and there is no terminal to ask.")
    assert "--hub <address>" in err and "pass --server" not in err and "modules set" not in err


# ---------------------------------------------------------------- features apply, units, menu

def test_apply_keeps_the_pairing_unless_no_pair(applied, capsys):
    assert run(capsys, "features", "apply")[0] == 0
    assert ("finish", True) in applied
    applied.clear()
    assert run(capsys, "features", "apply", "--no-pair")[0] == 0
    assert ("finish", False) in applied


def test_run_apply_names_the_setup_and_its_features(monkeypatch, capsys):
    cfg = config.load()
    monkeypatch.setattr(cli, "_require_root", lambda: True)
    monkeypatch.setattr(apply, "plan", lambda cfg, **kw: [])
    monkeypatch.setattr(apply, "execute", lambda actions, **kw: None)
    monkeypatch.setattr(apply, "finish", lambda cfg, **kw: None)
    assert cli._run_apply(pairing=False) == 0
    out = flat(capsys.readouterr().out)
    assert out.startswith("Setup: Hub (Spoolman, Hub service, ") and "Slicer presets" in out
    drop = types.SimpleNamespace(kind="install_file", arg=(apply.DROPIN, "[Service]\nIPAddressAllow=127.0.0.1 192.0.2.10\n"))
    monkeypatch.setattr(apply, "plan", lambda cfg, **kw: [drop])
    assert cli._run_apply(pairing=False) == 0
    assert "Weigh Station answers at: 127.0.0.1 192.0.2.10" in capsys.readouterr().out


def test_units_prints_one_service_file_per_line_under_both_names(capsys):
    rc, out, _ = run(capsys, "features", "units")
    assert rc == 0 and out.splitlines() and all(" " not in ln for ln in out.splitlines())
    assert "filament-kit.service" in out.splitlines() and run(capsys, "modules", "units")[1] == out


def test_menu_is_the_checklist_and_takes_no_json(capsys, monkeypatch):
    _stdin(monkeypatch, "q\n")
    assert cli.main(["features", "menu", "--numbered"]) == 0
    assert "Spoolman" in capsys.readouterr().out
    rc, out, err = run(capsys, "features", "menu", "--json")
    assert rc == 2 and json.loads(out)["fix"] == "use spoolwarden features --json"


# ---------------------------------------------------------------- AUT-9

AUT = [["features"], ["features", "--json"]]


def test_aut9_every_line_fits_79_columns_with_no_escape_byte_without_colour(env, capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)           # a terminal: the table is cut or turned into blocks
    rc, out, err = run(capsys, "features")
    assert rc == 0
    for line in (out + err).splitlines():
        assert len(re.sub(ESC + r"\[[0-9;]*m", "", line)) <= 79, line
    monkeypatch.setenv("NO_COLOR", "1")
    rc, out, err = run(capsys, "features")
    assert rc == 0 and ESC not in out + err
    monkeypatch.setenv("COLUMNS", "40")                                   # a narrow terminal: blocks, still inside it
    assert all(len(ln) <= 39 for ln in run(capsys, "features")[1].splitlines())


def test_aut9_a_pipe_gets_whole_rows_and_no_escape_byte(env, capsys):
    rc, out, err = run(capsys, "features")
    assert rc == 0 and ESC not in out + err and "…" not in out
    assert "Label Reader: Cloud (Claude)  label-reader" in out


def test_aut9_plain_is_ascii_with_no_carriage_return_and_no_escape(env, capsys):
    rc, out, err = run(capsys, "--plain", "features")
    assert rc == 0 and (out + err).isascii() and "\r" not in out + err and ESC not in out + err
    assert "State: on" in out and "Key: hub" in out


def test_aut9_json_is_one_document(env, capsys):
    rc, out, err = run(capsys, "--color", "always", "features", "--json")
    assert rc == 0 and out.endswith("}\n") and out.count("\n") == 1 and ESC not in out and json.loads(out)


# ---------------------------------------------------------------- weigh-station

def _paired_state(monkeypatch, state):
    monkeypatch.setattr(server_api, "pairing_state", lambda: state)


@pytest.mark.parametrize("state,text,word,address", [
    ("paired 192.0.2.10:8710", "paired with 192.0.2.10:8710", "paired", "192.0.2.10:8710"),
    ("unpaired", "not paired", "unpaired", None), ("unchecked", "not checked yet", "unchecked", None)])
def test_pairing_state_says_it_in_words_and_json_keeps_the_values_for_scripts(state, text, word, address, monkeypatch, capsys):
    _paired_state(monkeypatch, state)
    assert run(capsys, "weigh-station", "pairing-state") == (0, text + "\n", "")
    rc, out, _ = run(capsys, "weigh-station", "pairing-state", "--json")
    assert rc == 0 and json.loads(out) == {"state": word, "address": address}


def test_the_old_pairing_state_keeps_the_line_the_root_wrapper_passes_to_status(monkeypatch, capsys):
    for state in ("paired 192.0.2.10:8710", "unpaired", "unchecked"):
        _paired_state(monkeypatch, state)
        assert run(capsys, "station", "pairing-state") == (0, state + "\n", "")


def test_the_old_station_spellings_run_the_same_functions(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cli, "cmd_station_flash_panel", lambda **kw: seen.append(("flash", kw)) or 0)
    monkeypatch.setattr(cli, "cmd_station_pair_local", lambda: seen.append("local") or 0)
    monkeypatch.setattr(cli, "cmd_station_pair", lambda: seen.append("pair") or 0)
    for argv in (["flash-display", "--port", "/dev/ttyACM0", "--yes"], ["flash-panel", "--port", "/dev/ttyACM0", "--yes"],
                 ["pair", "--local"], ["pair"]):
        assert run(capsys, "weigh-station" if argv[0] != "flash-panel" else "station", *argv)[0] == 0
    assert run(capsys, "station", "pair", "--local")[0] == 0 and run(capsys, "station", "pair")[0] == 0
    assert seen == [("flash", {"yes": True, "only_port": "/dev/ttyACM0"})] * 2 + ["local", "pair", "local", "pair"]


def test_pair_takes_no_yes_a_person_compares_the_fingerprint(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["weigh-station", "pair", "--yes"])
    assert e.value.code == 2 and "unrecognized arguments: --yes" in capsys.readouterr().err


def test_pair_without_a_terminal_stops_before_asking_with_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(output, "terminal", lambda: False)
    rc, out, err = run(capsys, "weigh-station", "pair")
    assert rc == 2 and out == "" and "there is no terminal to ask." in flat(err)
    assert run(capsys, "weigh-station", "pair", "--json")[0] == 2


def test_pair_asks_for_the_link_then_the_fingerprint_and_names_the_hub(monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    link = server_api.Link("hub.example", 8710, "t" * 43, "ab" * 32, ["192.0.2.10"])
    monkeypatch.setattr(server_api, "parse_link", lambda text: link)
    seen = {}

    def pair_with_link(l, confirm):
        seen["answer"] = confirm("ab" * 32)
        return types.SimpleNamespace(status="paired" if seen["answer"] else "declined",
                                     message="Paired. The station was restarted and uses the server now.")
    monkeypatch.setattr(server_api, "pair_with_link", pair_with_link)
    prompts, answers = [], iter(["link", "y"])
    assert cli.cmd_station_pair(ask=lambda p: prompts.append(p) or next(answers)) == 0
    assert prompts == ["Paste the link from the Hub (sudo spoolwarden pair --weigh-station): ",
                       "Does it match the fingerprint the Hub shows? [y/N] "]
    out = capsys.readouterr().out
    assert out.splitlines()[:2] == ["  " + " ".join(["abab"] * 8)] * 2
    assert out.splitlines()[2:] == ["Paired with the Hub at hub.example.",
                                    "The station was restarted and uses the server now."]
    answers = iter(["link", "n"])
    assert cli.cmd_station_pair(ask=lambda p: next(answers)) == 5
    assert capsys.readouterr().out.splitlines()[-1] == "Not paired. Nothing changed."


# ---------------------------------------------------------------- tag-reader

def test_the_old_reader_spellings_run_the_same_functions(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cli, "cmd_reader", lambda action, name=None, ref=None, yes=False: seen.append((action, name, ref, yes)) or 0)
    monkeypatch.setattr(cli, "cmd_reader_setup", lambda a: seen.append(("setup", a.name, a.port, a.password)) or 0)
    for new, old in ((["tag-reader", "list"], ["reader", "tokens"]), (["tag-reader", "new-token", "--name", "bench"], ["reader", "token", "--name", "bench"]),
                     (["tag-reader", "revoke", "r1", "-y"], ["reader", "revoke", "r1", "-y"]),
                     (["tag-reader", "flash", "--name", "bench", "--port", "/dev/ttyACM0", "--password", "-"],
                      ["reader", "setup", "--name", "bench", "--port", "/dev/ttyACM0", "--password", "-"])):
        assert run(capsys, *new)[0] == 0 and run(capsys, *old)[0] == 0
    assert seen[0::2] == seen[1::2] and [s[0] for s in seen[0::2]] == ["tokens", "token", "revoke", "setup"]


def test_a_wifi_password_is_never_an_argument_only_standard_input(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["tag-reader", "flash", "--password", "hunter2"])
    assert e.value.code == 2 and "a secret is never given on the command line" in capsys.readouterr().err


def test_password_dash_reads_one_line_of_standard_input_and_asks_nothing_else(monkeypatch):
    _stdin(monkeypatch, "my wifi pass\nnext line\n")
    a = types.SimpleNamespace(password="-")
    assert cli._wifi_password(a, lambda prompt: pytest.fail("asked " + prompt)) == "my wifi pass"
    _stdin(monkeypatch, "  spaced pass \r\nnext\n")                  # spaces are part of a Wi-Fi password; the line ending is not
    assert cli._wifi_password(a, lambda prompt: pytest.fail("asked " + prompt)) == "  spaced pass "
    asked = []
    a = types.SimpleNamespace(password=None)
    assert cli._wifi_password(a, lambda prompt: asked.append(prompt) or "pw") == "pw"
    assert asked == ["Its Wi-Fi password: ", "The password again: "]


def test_tag_reader_new_token_is_audited_and_json_gives_the_token_once(env, capsys, monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    rc, out, _ = run(capsys, "tag-reader", "new-token", "--name", "bench", "--json")
    got = json.loads(out)
    assert rc == 0 and set(got) == {"ok", "id", "name", "token"} and got["name"] == "bench"
    rc, out, _ = run(capsys, "tag-reader", "list", "--json")
    assert rc == 0 and got["token"] not in out and json.loads(out)[0]["id"] == got["id"]
    assert run(capsys, "tag-reader", "revoke", "bench", "--yes")[1] == f"Revoked the token {got['id']}.\n"
    audit = [r.getMessage().split(" from ")[0] for r in caplog.records if r.name == "filament_kit.setup_page"]
    assert audit == [f"setup: reader token {got['id']} made", f"setup: reader token {got['id']} revoked"]


def test_tag_reader_revoke_asks_and_without_a_terminal_stops(env, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    run(capsys, "tag-reader", "new-token", "--name", "bench")
    monkeypatch.setattr(output, "terminal", lambda: False)
    rc, out, err = run(capsys, "tag-reader", "revoke", "bench")
    assert rc == 2 and out == "" and "needs a yes, and there is no terminal to ask." in flat(err)
    assert run(capsys, "tag-reader", "list")[1].count("bench") == 1


@pytest.mark.parametrize("argv", [["tag-reader", "list"], ["tag-reader", "list", "--json"]])
def test_aut9_tag_reader_list_fits_79_columns_with_no_escape_byte(env, argv, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    run(capsys, "tag-reader", "new-token", "--name", "a bench Tag Reader with a very long name that goes on and on")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)
    rc, out, err = run(capsys, *argv)
    assert rc == 0 and all(len(re.sub(ESC + r"\[[0-9;]*m", "", ln)) <= 79 for ln in out.splitlines())
    monkeypatch.setenv("NO_COLOR", "1")
    assert ESC not in run(capsys, *argv)[1]
