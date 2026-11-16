"""S5.4: the `config` menu (06 8.3), the Printers screen (8.4), the Features checklist (8.5) and the prompts (8.7), driven
with typed lines in the numbered variant (`--numbered`, `--plain`) and exits (06 6.7). The full-screen variant is
tested in test_menu_ui.py."""
from __future__ import annotations

import io
import sys

import pytest

from filament_kit import cli, config, menu_ui, modules, output, secret_input
from filament_kit.bridge import registry

BOTH = {n: True for n in ("spoolman", "server", "ai_intake", "local_intake", "backup", "web", "library", "station")}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt", "bk"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "bk"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(config.socket, "gethostname", lambda: "workshop")  # the Hub's own name is a placeholder here
    return tmp_path


def run(monkeypatch, script: str, *args: str, command=("config",)) -> int:
    """`config --numbered ...` with `script` as the typed lines."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(script))
    return cli.main([*command, "--numbered", *args])


def say(text: str) -> str:
    return " ".join(text.split())


def stored() -> dict:
    return config.load()


def all_features(**extra):
    cfg = config.load()
    cfg["modules"] = {n: True for n in modules.MODULES if n not in modules.NEWER} | extra
    config.save(cfg)


# ---------- the main list and the groups ----------

def test_the_main_list_has_the_hub_pages_groups_in_order_then_printers_and_features(capsys, monkeypatch):
    assert run(monkeypatch, "q\n") == 0
    out = capsys.readouterr().out
    names = ["Appearance", "General", "Storage locations", "Label Reader", "Backups and restore",
             "Network and addresses", "Web passphrase", "Filament Catalog", "Weigh Station voice", "Printers", "Features"]
    rows = [ln for ln in out.splitlines() if ln[:4].strip().isdigit()]
    assert [r.split("  ")[2].strip() for r in rows] == names and [int(r[:4]) for r in rows] == list(range(1, 12))
    assert "These open their own screens; changes there apply at once:" in out
    assert out.splitlines()[0].startswith("Settings") and out.rstrip().endswith("Number:")
    assert "  s save   q leave   ? help" in out


def test_a_group_screen_is_headed_by_its_place_and_ends_with_the_actions_that_are_commands_elsewhere(capsys, monkeypatch):
    assert run(monkeypatch, "5\nq\n6\nq\n8\nq\nq\n") == 0
    out = say(capsys.readouterr().out)
    assert "Settings > Backups and restore" in out and "Back up now: sudo spoolwarden backup create" in out
    assert "Restore: sudo spoolwarden restore <zip>" in out
    assert "Settings > Network and addresses" in out and "Firewall rules: spoolwarden remote firewall" in out
    assert "Settings > Filament Catalog" in out and "Update now: sudo spoolwarden catalog update" in out


def test_a_staged_change_is_saved_with_s_and_the_group_shows_what_is_stored(capsys, monkeypatch):
    # 3 Storage locations, 2 PLA rack, 5 Overflow location; q back; s saves both; q leaves
    assert run(monkeypatch, "3\n2\nShelf Z\n5\nSpill\nq\ns\nq\n") == 0
    cfg = stored()
    assert cfg["placement"]["pla_location"] == "Shelf Z" and cfg["placement"]["overflow"] == "Spill"
    out = capsys.readouterr().out
    assert "PLA rack [Rack 1]: Changed, not saved yet." in out
    assert "Settings - workshop - 2 changes not saved" in out
    assert "Saved 2 changes: PLA rack, overflow location." in out


def test_s_saves_from_a_group_level_too_and_with_nothing_staged_says_so(capsys, monkeypatch):
    assert run(monkeypatch, "3\ns\n2\nShelf Z\ns\nq\nq\n") == 0
    out = capsys.readouterr().out
    assert "Nothing to save." in out and "Saved 1 change: PLA rack." in out
    assert stored()["placement"]["pla_location"] == "Shelf Z"


def test_nothing_is_saved_by_leaving_q_with_changes_asks_and_a_no_stays(capsys, monkeypatch):
    before = stored()["placement"]["pla_location"]
    assert run(monkeypatch, "3\n2\nShelf Z\nq\nq\nn\nq\ny\n") == 5
    out = capsys.readouterr().out
    assert out.count("Leave without saving 1 change (PLA rack)? [y/N] ") == 2
    assert out.rstrip().endswith("Nothing saved.") and stored()["placement"]["pla_location"] == before


def test_q_with_nothing_staged_just_leaves_and_an_empty_answer_to_the_question_is_a_no(capsys, monkeypatch):
    assert run(monkeypatch, "q\n") == 0
    assert "Leave without" not in capsys.readouterr().out
    assert run(monkeypatch, "3\n2\nX\nq\nq\n\nq\nyes\n") == 5          # an empty answer: no; "yes" in any case: yes


def test_the_end_of_input_ends_with_5_and_says_how_many_changes_were_lost(capsys, monkeypatch):
    assert run(monkeypatch, "3\n2\nShelf Z\n") == 5
    assert capsys.readouterr().out.rstrip().endswith("Input ended: 1 change not saved.")
    assert run(monkeypatch, "3\n2\nA\n5\nB\n") == 5
    assert "Input ended: 2 changes not saved." in capsys.readouterr().out
    assert run(monkeypatch, "") == 0 and "Input ended" not in capsys.readouterr().out      # nothing staged


def test_ctrl_c_leaves_at_once_without_asking_with_130(capsys, monkeypatch):
    answers = iter(["3", "2", "Shelf Z", "q"])

    def ask(prompt):
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt from None
    monkeypatch.setattr(cli, "_ask", ask)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["config", "--numbered"]) == 130
    assert capsys.readouterr().out.rstrip().endswith("Left without saving 1 change.")
    assert stored()["placement"]["pla_location"] != "Shelf Z"
    answers = iter([])
    assert cli.main(["config", "--numbered"]) == 130
    assert "Left without" not in capsys.readouterr().out


def test_unknown_input_and_a_wrong_number_are_errors_on_standard_error(capsys, monkeypatch):
    assert run(monkeypatch, "x\n0\n12\n3\nz\nq\nq\n") == 0
    err = capsys.readouterr().err
    for token in ("x", "0", "12", "z"):
        assert f'Error: "{token}" is not a number or letter on this screen.' in err


def test_question_mark_lists_every_key_and_a_checklist_adds_its_setup_letters(capsys, monkeypatch):
    assert run(monkeypatch, "?\nq\n") == 0
    out = capsys.readouterr().out
    assert "Keys on this screen:" in out and "Ctrl-C" in out and "leave at once, saving nothing" in out
    assert run(monkeypatch, "11\n?\nq\nq\n") == 0
    out = capsys.readouterr().out
    assert "Hub setup" in out and "Weigh Station only" in out and "Enter never applies" in out


def test_a_wrong_value_prints_the_error_and_asks_again_and_earlier_changes_stay(capsys, monkeypatch):
    assert run(monkeypatch, "3\n2\nShelf Z\n4\ntwo\n-1\n\nq\nq\nn\ns\nq\n") == 0
    cap = capsys.readouterr()
    assert cap.err.count("Error: the number of storage boxes is a whole number, 0 or more.") == 2
    assert "Number of storage boxes [0]: Number of storage boxes [0]: Number of storage boxes [0]: Unchanged." in cap.out
    assert "Leave without saving 1 change (PLA rack)?" in cap.out and stored()["placement"]["pla_location"] == "Shelf Z"


def test_the_same_value_is_unchanged_and_staging_the_stored_value_again_drops_the_change(capsys, monkeypatch):
    assert run(monkeypatch, "3\n2\nRack 1\nq\nq\n") == 0                      # equal to the current one
    assert capsys.readouterr().out.count("Unchanged.") == 1
    assert run(monkeypatch, "3\n2\nShelf Z\n2\nRack 1\nq\nq\n") == 0         # back to the stored value: nothing to lose
    assert "Leave without" not in capsys.readouterr().out


def test_a_box_prefix_with_a_trailing_space_is_shown_in_quotes_and_kept(capsys, monkeypatch):
    assert run(monkeypatch, "3\n3\nDry box \nq\ns\nq\n") == 0
    out = capsys.readouterr().out
    assert 'Box location prefix "Storage box "' in say(out) and stored()["placement"]["box_prefix"] == "Dry box "


def test_choices_are_numbered_with_the_current_one_marked_and_an_empty_answer_keeps_it(capsys, monkeypatch):
    assert run(monkeypatch, "1\n1\n\nq\nq\n") == 0                           # 1 Appearance, Theme, Enter
    out = capsys.readouterr().out
    assert "Console (dense and technical)  (now)" in out and "Workbench (calm cards)" in out
    assert "Number (Enter keeps it): " in out and "Unchanged." in out
    assert run(monkeypatch, "1\n1\n3\nq\ns\nq\n") == 0
    assert stored()["appearance"]["theme"] == "palette"


def test_the_label_reader_screen_numbers_straight_through_under_its_sub_headings(capsys, monkeypatch):
    all_features(local_intake=True)
    assert run(monkeypatch, "4\nq\nq\n") == 0
    screen = capsys.readouterr().out.split("Settings > Label Reader")[1].split("  c check the key")[0]
    for heading in ("Cloud (Claude)", "On this Hub", "Recently added"):
        assert f"\n  {heading}\n" in screen
    rows = [ln.split() for ln in screen.splitlines() if ln[:4].strip().isdigit()]
    assert [(r[0], " ".join(r[1:3])) for r in rows] == [
        ("1", "Engine order"), ("2", "Anthropic API"), ("3", "Claude model"), ("4", "Reads per"), ("5", "Address http://127.0.0.1:7915"),
        ("6", "Tier Automatic"), ("7", "Records kept")]


def test_with_one_engine_on_the_engine_row_says_so_and_cannot_be_opened(capsys, monkeypatch):
    assert run(monkeypatch, "4\n1\nq\nq\n") == 0
    out = say(capsys.readouterr().out)
    assert out.count("Engine: Cloud (Claude). Switch on the other one in Features (11) to use both.") == 2
    assert "Address" not in out.split("Settings > Label Reader")[1]


def test_switched_off_features_say_so_and_stay_on_the_main_list(capsys, monkeypatch):
    assert run(monkeypatch, "9\nq\n") == 0                                    # a Hub without the Weigh Station
    out = say(capsys.readouterr().out)
    assert "off: switch it on in Features (11)" in out
    assert "Weigh Station is off on this Hub. Switch it on in Features (11) first." in out
    assert "Settings > Weigh Station voice" not in out
    cfg = config.load()
    cfg["modules"] = {n: n in ("spoolman", "server") for n in modules.MODULES}
    config.save(cfg)
    assert run(monkeypatch, "8\nq\nq\n") == 0
    out = say(capsys.readouterr().out)
    assert "off: only Catalog token" in out
    assert "The Filament Catalog is switched off. Switch it on in Features (11)." in out
    assert "Catalog token not set" in out.split("Settings > Filament Catalog")[1]


# ---------- saving ----------

def test_a_save_that_fails_keeps_every_staged_change_and_says_what_to_change(capsys, monkeypatch):
    all_features(orders=False)
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: "the web public address must start with https://")
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: pytest.fail("nothing was saved"))
    # 6 Network: 1 Public address; 9 Weigh Station voice: 1 Voice, 2; s; the error; the changes are still there
    assert run(monkeypatch, "6\n1\nhttps://hub.example/filament\nq\n9\n1\n2\nq\ns\nq\nn\nq\ny\n") == 5
    cap = capsys.readouterr()
    assert ("Error: nothing was saved: the web public address must start with https://. Your changes are still here."
            in say(cap.err))
    assert "Leave without saving 2 changes (Public address, Voice)?" in cap.out
    assert stored().get("web", {}).get("public_url") is None


def test_a_value_changed_elsewhere_while_the_menu_was_open_asks_per_value(capsys, monkeypatch):
    answers = iter(["2", "1", "Mine", "q", "s", "n", "q"])

    def ask(prompt):
        a = next(answers)
        print(prompt, end="")
        if a == "s":                                    # another terminal saves the display name first
            cfg = config.load()
            cfg["server_name"] = "Workshop"
            config.save(cfg)
        return a
    monkeypatch.setattr(cli, "_ask", ask)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["config", "--numbered"]) == 0
    out = say(capsys.readouterr().out)
    assert 'Display name was changed elsewhere to "Workshop" while this menu was open. Keep yours? [y/N]' in out
    assert stored()["server_name"] == "Workshop" and "Nothing to save." in out


def test_keeping_yours_saves_over_the_other_change(monkeypatch, capsys):
    answers = iter(["2", "1", "Mine", "q", "s", "y", "q"])

    def ask(prompt):
        a = next(answers)
        if a == "s":
            cfg = config.load()
            cfg["server_name"] = "Workshop"
            config.save(cfg)
        return a
    monkeypatch.setattr(cli, "_ask", ask)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["config", "--numbered"]) == 0
    assert stored()["server_name"] == "Mine"


def test_a_change_that_needs_the_hub_to_restart_says_so_while_staged_and_restarts_on_save(capsys, monkeypatch):
    restarted = []
    monkeypatch.setattr(cli, "_no_systemd", lambda: False)
    monkeypatch.setattr(cli, "_require_root", lambda: True)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(cli, "_restart_service", lambda: restarted.append(1))
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: pytest.fail("a model change applies nothing"))
    assert run(monkeypatch, "4\n3\nclaude-x\nq\n4\nq\ns\nq\n") == 0           # 3 = Claude model, then look again
    out = capsys.readouterr().out
    assert "Claude model claude-x (not saved; restarts the Hub)" in say(out)
    assert "The Hub is restarting" in out and "The Hub is back." in out and restarted == [1]
    assert stored()["model"] == "claude-x"


def test_a_key_value_that_is_not_a_restart_does_not_restart(monkeypatch):
    restarted = []
    monkeypatch.setattr(cli, "_restart_service", lambda: restarted.append(1))
    assert run(monkeypatch, "2\n1\nMine\nq\ns\nq\n") == 0
    assert restarted == []


def test_the_voice_applies_once_after_the_save(monkeypatch, capsys):
    all_features()
    applied = []
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: applied.append(pairing) or 0)
    assert run(monkeypatch, "9\n1\n2\nq\ns\nq\n") == 0
    assert applied == [False] and stored()["station"]["tts"] == "espeak"


def test_an_apply_that_fails_ends_with_its_code_after_the_save(monkeypatch):
    all_features()
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: 1)
    assert run(monkeypatch, "9\n1\n2\nq\ns\nq\n") == 1


def test_the_public_address_and_the_station_address_are_checked_and_cleared_with_a_dash(capsys, monkeypatch):
    all_features(orders=False)
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: 0)
    assert run(monkeypatch, "6\n1\nhttp://plain\nhttps://hub.example/filament\n2\nhttp://station.example:5003\nq\nq\ny\n") == 5
    err = say(capsys.readouterr().err)
    assert "Error: the public address must start with https://, e.g. https://hub.example/filament." in err
    assert run(monkeypatch, "6\n1\nhttps://hub.example/filament\n2\nhttp://station.example:5003\n3\nhub.example "
                            "alt.example\nq\ns\nq\n") == 0
    cfg = stored()
    assert cfg["web"]["public_url"] == "https://hub.example/filament" and cfg["station"]["url"] == "http://station.example:5003"
    assert cfg["setup"]["hosts"] == ["hub.example", "alt.example"]
    assert run(monkeypatch, "6\n2\n-\nq\ns\nq\n") == 0                        # `-` clears it
    assert stored()["station"]["url"] is None


def test_allow_printer_changes_is_switched_by_its_number_and_only_shown_with_web_access(capsys, monkeypatch):
    assert "Allow printer changes" not in say(_after(monkeypatch, capsys, "6\nq\nq\n"))
    all_features()
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    assert run(monkeypatch, "6\n4\nq\ns\nq\n") == 0
    assert stored()["web"]["printer_changes"] is True


def _after(monkeypatch, capsys, script):
    run(monkeypatch, script)
    return capsys.readouterr().out


def test_backups_keep_days_is_checked_from_1_to_365(capsys, monkeypatch):
    assert run(monkeypatch, "5\n1\n0\n400\n30\nq\ns\nq\n") == 0
    assert capsys.readouterr().err.count("Error: the keep nightly backups for is a whole number, 1 to 365.") == 2
    assert stored()["backup"]["keep_days"] == 30


def test_an_external_spoolman_address_is_only_shown_without_a_local_one_and_must_answer(capsys, monkeypatch):
    assert "Spoolman address" not in say(_after(monkeypatch, capsys, "2\nq\nq\n"))
    cfg = config.load()
    cfg["modules"] = {n: n == "server" for n in modules.MODULES}
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    answers = []

    class Down:
        def __init__(self, url, timeout=5):
            answers.append(url)

        def ping(self):
            raise cli.SpoolmanError("connection refused")
    monkeypatch.setattr(cli, "Spoolman", Down)
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    assert run(monkeypatch, "2\n2\nhttp://other.example:7912\nq\ns\nq\nn\nq\ny\n") == 5
    cap = capsys.readouterr()
    assert say(cap.err).startswith("Error: nothing was saved: no Spoolman answered at that address (connection refused). "
                                   "Your changes are still here.")
    assert answers == ["http://other.example:7912"] and stored()["spoolman_url"] == "http://spoolman.example:7912"


# ---------- secrets (CLI-8) ----------

@pytest.fixture
def secrets(monkeypatch, secret_terminal):
    """The secret prompts: what was asked, answering from a list."""
    asked, given = [], []

    def getpass(prompt=""):
        asked.append(prompt)
        return given.pop(0)
    monkeypatch.setattr("getpass.getpass", getpass)
    return asked, given


def test_a_secret_is_asked_hidden_never_shown_back_and_its_row_says_set_or_not_set(secrets, monkeypatch, capsys):
    asked, given = secrets
    given += ["sk-ant-TOPSECRET"]
    assert run(monkeypatch, "4\n2\nq\n4\nq\ns\nq\n") == 0               # set it, look at the group again, save
    cap = capsys.readouterr()
    assert asked == ["Anthropic API key (Enter keeps it): "]
    assert "sk-ant-TOPSECRET" not in cap.out + cap.err
    assert "Anthropic API key set (not saved)" in say(cap.out)
    assert (config.paths().etc / "anthropic_key").read_text().strip() == "sk-ant-TOPSECRET"


def test_with_plain_nothing_is_echoed_and_the_prompt_says_so(secrets, monkeypatch, capsys):
    asked, given = secrets
    given += ["sk-ant-TOPSECRET"]
    assert run(monkeypatch, "4\n2\nq\ns\nq\n", "--plain") == 0
    assert asked == ["Anthropic API key (Enter keeps it) (typing is not shown): "]
    cap = capsys.readouterr()
    assert "sk-ant-TOPSECRET" not in cap.out + cap.err


def test_secret_input_in_plain_mode_never_draws_stars_and_ends_the_prompt_with_the_note(monkeypatch, secret_terminal):
    asked = []
    monkeypatch.setattr("getpass.getpass", lambda prompt="": asked.append(prompt) or "pw")
    monkeypatch.setattr(secret_input, "_posix", lambda *a: pytest.fail("a terminal read draws stars"), raising=False)
    monkeypatch.setattr(secret_input, "_windows", lambda *a: pytest.fail("a terminal read draws stars"))
    output.configure(plain=True)
    assert secret_input.ask("Access Code: ") == "pw"
    assert asked == ["Access Code (typing is not shown): "] and secret_input.plain_prompt("Key") == "Key (typing is not shown) "
    output.reset()


def test_a_secret_typed_at_a_terminal_echoes_one_star_per_character_and_backspace_works():
    line = secret_input.Line()
    assert "".join(line.key(c) for c in "abc") == "***" and line.key("\x7f") == "\b \b" and line.key("d") == "*"
    assert line.text == "abd"


def test_the_passphrase_is_asked_twice_a_mismatch_asks_both_again_and_a_short_one_is_refused(secrets, monkeypatch, capsys):
    pytest.importorskip("mcp")
    asked, given = secrets
    monkeypatch.setattr(cli, "write_passphrase", lambda text: asked.append(f"saved {len(text)}"))
    given += ["short", "a long example passphrase", "another long passphrase", "a long example passphrase",
              "a long example passphrase"]
    all_features()
    assert run(monkeypatch, "7\n1\nq\ns\nq\n") == 0
    err = say(capsys.readouterr().err)
    assert "Error: use at least 12 characters. This one has 5." in err
    assert "Error: the two passphrases do not match. Type them again." in err
    assert asked[0] == "New passphrase (Enter keeps it): " and "New passphrase again: " in asked
    assert asked[-1] == "saved 25"


def test_the_anthropic_key_and_the_catalog_token_are_removed_after_a_question_and_only_on_save(secrets, monkeypatch, capsys):
    all_features()
    (config.paths().etc / "anthropic_key").write_text("sk-ant-x\n")
    (config.paths().etc / "github_token").write_text("ghp_x\n")
    assert run(monkeypatch, "4\nx\nn\nq\nq\n") == 0                           # a no: nothing staged
    assert (config.paths().etc / "anthropic_key").exists()
    assert run(monkeypatch, "4\nx\ny\nq\n4\nq\nq\nn\ns\nq\n") == 0
    out = say(capsys.readouterr().out)
    assert ("Remove the Anthropic API key? Label Reader: Cloud (Claude) stops reading labels until a new key is set. "
            "[y/N]") in out and "(will be removed)" in out
    assert not (config.paths().etc / "anthropic_key").exists()
    assert run(monkeypatch, "8\nx\ny\nq\ns\nq\n") == 0
    assert "Remove the Catalog token? The Filament Catalog can then download only from public sources." in say(
        capsys.readouterr().out)
    assert not (config.paths().etc / "github_token").exists()


# ---------- the variants and exits ----------

def test_piped_input_without_numbered_is_refused_with_exit_2_and_a_fix(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert cli.main(["config"]) == 2
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err.startswith("Error: config is a menu, and there is no terminal to ask on.")
    assert "--numbered" in cap.err
    assert cli.main(["modules", "menu"]) == 2 and capsys.readouterr().out == ""


def test_plain_implies_numbered_and_its_output_has_no_escape_or_carriage_return(capsys, monkeypatch):
    all_features()
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(sys, "stdin", io.StringIO("3\n2\nShelf Z\nq\n10\nq\n11\n?\nq\nq\nq\ny\n"))
    assert cli.main(["config", "--plain"]) == 5
    cap = capsys.readouterr()
    assert "\x1b" not in cap.out + cap.err and "\r" not in cap.out + cap.err
    assert "Number: " in cap.out and "[x]" in cap.out


def test_the_menu_env_variable_asks_for_numbers_too(capsys, monkeypatch):
    monkeypatch.setenv("SPOOLWARDEN_MENU", "numbered")
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert cli.main(["config"]) == 0 and "Number: " in capsys.readouterr().out


def test_json_is_refused_for_the_menus(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert cli.main(["config", "--json"]) == 2
    assert "config is a menu." in capsys.readouterr().err


def test_config_without_root_says_to_use_sudo_before_anything_is_asked(monkeypatch, capsys):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert cli.main(["config", "--numbered"]) == 3
    cap = capsys.readouterr()
    assert "administrator rights" in cap.err and "Number" not in cap.out


# ---------- every old setting is still reachable ----------

def test_every_setting_the_old_menu_had_is_reachable_and_saved(capsys, monkeypatch, secrets):
    """Old -> new: 1 display name -> 2 General; 2 storage (5 values) -> 3 Storage locations; 3 model and reads per day
    and 4 the Anthropic key -> 4 Label Reader; 5 Printers -> 10 Printers; 6 Modules -> 11 Features; 7 Station voice ->
    9 Weigh Station voice; 8 intake records kept and 9 label reader (order, address, tier) -> 4 Label Reader."""
    all_features(local_intake=True)
    asked, given = secrets
    given += ["sk-ant-TOPSECRET"]
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: 0)
    script = "\n".join([
        "2", "1", "my-kit", "q",                                                   # display name
        "3", "1", "A, B ,C", "2", "Shelf", "3", "Box ", "4", "7", "5", "Spill", "q",   # the five storage values
        "4", "1", "2", "2", "3", "claude-x", "4", "30", "5", "http://gpu-box.example:7915", "6", "3", "7", "99", "q",
        "9", "1", "2", "q",                                                        # station voice: espeak-ng
        "10", "q", "11", "q",                                                      # Printers and Features open
        "s", "q", ""])
    assert run(monkeypatch, script) == 0
    cfg = stored()
    assert cfg["server_name"] == "my-kit" and cfg["locations"] == ["A", "B", "C"]
    assert cfg["placement"] == {**cfg["placement"], "pla_location": "Shelf", "box_prefix": "Box ", "box_count": 7,
                                "overflow": "Spill"}
    assert cfg["model"] == "claude-x" and cfg["reads_per_day"] == 30 and cfg["intake"]["history_keep"] == 99
    assert cfg["intake"]["reader"] == "local-then-cloud"
    assert cfg["local_intake"] == {"url": "http://gpu-box.example:7915", "tier": "gpu"}
    assert cfg["station"]["tts"] == "espeak"
    assert (config.paths().etc / "anthropic_key").read_text().strip() == "sk-ant-TOPSECRET"
    out = capsys.readouterr().out
    assert "Printers - 0 set up - 0 found" in out and "Features - Custom" in out
    assert "Saved 14 changes: display name, locations, PLA rack, box location prefix, number of storage boxes, " in say(out)


def test_the_installers_storage_question_edits_the_config_in_place_with_q(monkeypatch):
    cfg = config.load()
    monkeypatch.setattr(sys, "stdin", io.StringIO("2\nShelf Z\n4\n3\nq\n"))
    output.configure(numbered=True)
    cli._storage_menu(cfg)
    assert cfg["placement"]["pla_location"] == "Shelf Z" and cfg["placement"]["box_count"] == 3
    assert config.load()["placement"]["pla_location"] != "Shelf Z"        # the caller saves


# ---------- the Printers screen (8.4) ----------

SER = "03000A000000002"


def _printers():
    registry.upsert(registry.Printer("01S00C111111111", "Workshop X1", "X1C", "192.0.2.40", "12345678", True))
    registry.upsert(registry.Printer(SER, "Study A1 mini", "N2S", "192.0.2.41", "87654321", True, cert_fp="ab" * 32))
    registry.add_klipper("Garage Voron", "voron.example", 7125)
    registry.detected("0948ZZ0A0000009", "192.0.2.57", "H2D", "mainsailos")


def test_the_printers_screen_lists_them_with_a_kind_an_address_and_a_state_word(capsys, monkeypatch):
    _printers()
    monkeypatch.setattr(cli, "_printer_states", lambda: {"01S00C111111111": "connected", SER: "offline"})
    assert run(monkeypatch, "10\nq\nq\n") == 0
    out = capsys.readouterr().out
    assert "Printers - 3 set up - 1 found" in out
    assert any(ln.endswith("Bambu    192.0.2.40  + connected") and "Workshop X1" in ln for ln in out.splitlines())
    assert any("Study A1 mini" in ln and ln.endswith("o offline") for ln in out.splitlines())
    assert any("Garage Voron" in ln and "Klipper  voron.example:7125" in ln for ln in out.splitlines())
    assert any("mainsailos" in ln and ln.endswith("o found, not added") for ln in out.splitlines())
    assert "a add a printer   l look again   q back   ? help" in out


def _idx(name: str) -> int:
    """The number a printer has on the Printers screen."""
    return [registry.display_name(p) for p in registry.load().values()].index(name) + 1


def _screen(monkeypatch, capsys, name, states=None):
    monkeypatch.setattr(cli, "_printer_states", lambda: states or {})
    assert run(monkeypatch, f"10\n{_idx(name)}\nq\nq\nq\n") == 0
    return capsys.readouterr().out


def test_a_printer_screen_gives_its_facts_and_the_actions_in_the_order_of_the_table(capsys, monkeypatch):
    _printers()
    out = say(_screen(monkeypatch, capsys, "Workshop X1", {"01S00C111111111": "connected"}))
    assert "Printers > Workshop X1" in out and "serial 01S00C111111111" in out
    assert ("t test connection c collect a report m map slots b map by loading filament v saved reports r rename "
            "e change address k replace Access Code u forget certificate f forget printer q back ? help") in out
    out = say(_screen(monkeypatch, capsys, "Study A1 mini", {SER: "offline"}))     # a problem: the report comes first
    assert "certificate pinned" in out and "c collect a report t test connection m map slots" in out
    out = say(_screen(monkeypatch, capsys, "Garage Voron"))
    assert ("t test connection d detect model and slots b map by loading filament r rename e change address "
            "k set or replace Moonraker API key n lane data x clear API key f forget printer q back") in out
    out = say(_screen(monkeypatch, capsys, "mainsailos"))
    assert "u use this printer t test connection f dismiss q back ? help" in out


def test_a_printer_actions_run_the_commands_that_exist_today(capsys, monkeypatch):
    _printers()
    seen = []
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    monkeypatch.setattr(cli, "cmd_printer_report", lambda serial, mf: seen.append(("report", serial)) or 0)
    monkeypatch.setattr(cli, "cmd_printer_map", lambda serial, mf, manual=False, yes=False: seen.append(
        ("by loading" if manual else "map", serial)) or 0)
    monkeypatch.setattr(cli, "cmd_printer_unpin", lambda serial, yes=False: seen.append(("unpin", serial)) or 0)
    assert run(monkeypatch, f"10\n{_idx('Workshop X1')}\nc\nm\nb\nu\nq\nq\nq\n") == 0
    assert seen == [("report", "01S00C111111111"), ("map", "01S00C111111111"), ("by loading", "01S00C111111111"),
                    ("unpin", "01S00C111111111")]


def test_a_found_printer_is_dismissed_after_a_question_and_a_klipper_one_clears_its_key(capsys, monkeypatch):
    _printers()
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    found = _idx("mainsailos")
    assert run(monkeypatch, f"10\n{found}\nf\nn\nq\nq\nq\n") == 0
    out = say(capsys.readouterr().out)
    assert "Dismiss mainsailos? It leaves this list. A new scan may find it again. [y/N]" in out and "Nothing changed." in out
    assert run(monkeypatch, f"10\n{found}\nf\ny\nq\nq\n") == 0
    assert "Dismissed mainsailos." in capsys.readouterr().out
    assert "0948ZZ0A0000009" not in registry.load()
    voron = next(p for p in registry.load().values() if p.family == "klipper")
    registry.set_api_key(voron.serial, "secretkey")
    assert run(monkeypatch, f"10\n{_idx('Garage Voron')}\nx\ny\nq\nq\nq\n") == 0
    assert registry.load()[voron.serial].api_key == "" and "Cleared the API key of Garage Voron." in capsys.readouterr().out


def test_a_new_address_keeps_the_pin_and_a_new_access_code_clears_it_both_asked_hidden(secrets, capsys, monkeypatch):
    _printers()
    asked, given = secrets
    given += ["33334444", "11112222"]
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    study = _idx("Study A1 mini")
    assert run(monkeypatch, f"10\n{study}\ne\n192.0.2.99\nq\nq\nq\n") == 0
    p = registry.load()[SER]
    assert p.access_code == "33334444" and p.ip == "192.0.2.99" and p.cert_fp == "ab" * 32       # the pin is the printer's
    assert run(monkeypatch, f"10\n{study}\nk\nq\nq\nq\n") == 0
    p = registry.load()[SER]
    assert p.access_code == "11112222" and p.cert_fp == ""                  # as adding it again: the next one is pinned
    assert asked == ["Access Code of Study A1 mini (on the printer: Settings > Network/LAN): ",
                     "New Access Code for Study A1 mini (on the printer: Settings > Network/LAN): "]
    cap = capsys.readouterr()
    assert "1111" not in cap.out + cap.err and "3333" not in cap.out + cap.err


def test_an_empty_access_code_changes_nothing_and_says_so(secrets, capsys, monkeypatch):
    _printers()
    asked, given = secrets
    given += ["", ""]
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, f"10\n{_idx('Study A1 mini')}\nk\ne\n192.0.2.99\nq\nq\nq\n") == 0
    out = capsys.readouterr().out
    assert "Unchanged." in out and "No Access Code entered; nothing changed." in out
    assert registry.load()[SER].access_code == "87654321" and registry.load()[SER].ip == "192.0.2.41"


def test_look_again_reads_the_list_again(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\nl\nq\nq\n") == 0
    assert capsys.readouterr().out.count("Printers - 0 set up - 0 found") == 2


def test_adding_a_klipper_printer_asks_address_port_name_and_an_optional_key(secrets, capsys, monkeypatch):
    asked, given = secrets
    given += ["moonkey"]
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\nk\nvoron.example\n\nGarage Voron\nq\nq\n") == 0
    p = next(iter(registry.load().values()))
    assert (p.family, p.host, p.port, p.api_key, p.name) == ("klipper", "voron.example", 7125, "moonkey", "Garage Voron")
    assert asked == ["Moonraker API key (optional): "]
    assert "Added Garage Voron." in capsys.readouterr().out


# ---------- the Features checklist (8.5) ----------

def test_the_checklist_lists_every_feature_with_its_needs_before_anything_is_switched(capsys, monkeypatch):
    assert run(monkeypatch, "11\nq\nq\n") == 0
    out = say(capsys.readouterr().out)
    assert "Features - Hub" in out and "1 [x] Spoolman" in out and "3 [x] Label Reader: Cloud (Claude)" in out
    assert "14 [ ] Label Reader: On this Hub" in out and "needs: Hub service, the local reader service" in out
    assert "Changes: none" in out and "Type numbers to switch (several: 2 5 7); h, w, b choose a setup; s applies; q leaves" in out


def test_the_footer_names_what_a_row_needs_and_what_switching_it_off_also_turns_off():
    on = frozenset(modules.MODES["server"] | {"ai_intake"})
    assert cli._feature_note("ai_intake", on).startswith("Needs Hub service and an Anthropic API key.")
    assert cli._feature_note("server", on).startswith("Needs Spoolman (this machine or a remote one).")
    assert "Off also turns off: Label Reader: Cloud (Claude)" in cli._feature_note("server", on)
    assert cli._feature_note("spoolman", on).endswith("Off also turns off: nothing else.")


def test_the_plan_line_says_what_turns_on_and_off_and_what_a_switch_pulls_in():
    on = modules.MODES["server"]
    plan, short = cli._feature_plan(on, on, set())
    assert (plan, short) == ("Changes: none", "")
    chosen, _ = modules.toggle(on, "remote")
    assert cli._feature_plan(on, chosen, {"remote"})[0] == "Turns on: Web access (Remote access needs it), Remote access."
    chosen, _ = modules.toggle(on, "server")
    plan, short = cli._feature_plan(on, chosen, {"server"})
    assert plan.startswith("Turns off: Hub service") and short.endswith("off") and "Hub service off" in short
    mixed = (on | {"ai_intake"}) - {"station"}
    assert cli._feature_plan(on, mixed, {"ai_intake"})[0] == "Turns on: Label Reader: Cloud (Claude)."


def test_leaving_the_checklist_with_switched_rows_asks_and_a_yes_prints_nothing_applied(capsys, monkeypatch):
    applied = []
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: applied.append(1) or 0)
    # 3 Cloud off, 14 On this Hub on; Enter on nothing; q asks; n stays; q asks; y leaves
    assert run(monkeypatch, "3 14\nq\nn\nq\ny\n", command=("modules", "menu")) == 5
    out = say(capsys.readouterr().out)
    assert out.count("Leave without applying 2 changes (Label Reader: On this Hub on, Label Reader: Cloud (Claude) off)? "
                     "[y/N]") == 2
    assert out.rstrip().endswith("Nothing applied.") and applied == []


def test_leaving_the_checklist_inside_config_goes_back_to_config(capsys, monkeypatch):
    # the features screen says Nothing applied.; config goes on and q leaves it (nothing staged there)
    assert run(monkeypatch, "11\n7\nq\ny\nq\n") == 0
    out = capsys.readouterr().out
    assert "Nothing applied." in out and out.count("Settings - workshop") == 2


def test_a_checklist_with_no_changes_leaves_with_q_without_a_question(capsys, monkeypatch):
    assert run(monkeypatch, "q\n", command=("modules", "menu")) == 0
    assert "Leave without" not in capsys.readouterr().out


def test_enter_alone_never_applies_it_prints_the_line_again(capsys, monkeypatch):
    applied = []
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: applied.append(1) or 0)
    assert run(monkeypatch, "4\n\n\nq\ny\n", command=("modules", "menu")) == 5
    out = capsys.readouterr().out
    assert applied == [] and out.count("Type numbers to switch (several: 2 5 7)") == 4     # listed, after 4, and twice more


def test_applying_asks_for_a_setting_a_feature_needs_after_one_line_naming_the_feature(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: 0)
    web = list(modules.MODULES).index("web") + 1
    assert run(monkeypatch, f"{web}\ns\nhttp://plain\nhttps://hub.example/filament\nq\n", command=("modules", "menu")) == 0
    cap = capsys.readouterr()
    assert "Web access needs the address people use." in cap.out
    assert "Public https address of the web app (e.g. https://hub.example/filament): " in cap.out
    assert "Error: give the https address people use, e.g. https://hub.example/filament." in cap.err
    assert "Features applied: Web access on." in cap.out
    assert stored()["web"]["public_url"] == "https://hub.example/filament"


def test_an_empty_answer_returns_to_the_checklist_with_the_rows_kept(capsys, monkeypatch):
    orders = list(modules.MODULES).index("orders") + 1
    config.save({**config.load(), "modules": {n: n in modules.MODES["server"] | {"ai_intake"} for n in modules.MODULES}})
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: pytest.fail("not applied"))
    assert run(monkeypatch, f"{orders}\ns\n\nq\ny\n", command=("modules", "menu")) == 5
    out = capsys.readouterr().out
    assert "Order history needs its file." in out and "Not applied: Order history needs that setting." in out
    assert f"{orders:>4}  [x] Order history" in out and "Nothing applied." in out


def test_a_cascade_is_in_the_plan_before_s_is_pressed(capsys, monkeypatch):
    server = list(modules.MODULES).index("server") + 1
    assert run(monkeypatch, f"{server}\nq\ny\n", command=("modules", "menu")) == 5
    out = say(capsys.readouterr().out)
    assert "Turns off: Hub service, Label Reader: Cloud (Claude)," in out


def test_the_setup_letters_choose_a_setup_and_say_what_it_changed(capsys, monkeypatch):
    assert run(monkeypatch, "w\nq\ny\n", command=("modules", "menu")) == 5
    out = say(capsys.readouterr().out)
    assert "Turns on: Weigh Station." in out and "Turns off:" in out


def test_features_without_root_is_not_applied(monkeypatch, capsys):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("1\ns\nq\ny\n"))
    assert cli.main(["modules", "menu", "--numbered"]) == 3
    assert "administrator rights" in capsys.readouterr().err


# ---------- brief 49: apply Spoolman, piped secrets, honest save, Features fresh, add questions ----------

def test_a_saved_spoolman_address_is_applied_like_the_hubs(monkeypatch):
    cfg = config.load()
    cfg["modules"] = {n: n == "server" for n in modules.MODULES}
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)

    class Up:
        def __init__(self, url, timeout=5):
            pass

        def ping(self):
            return {}
    applied = []
    monkeypatch.setattr(cli, "Spoolman", Up)
    monkeypatch.setattr(cli, "_plan_error", lambda cfg: None)
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: applied.append(pairing) or 0)
    assert run(monkeypatch, "2\n2\nhttp://other.example:7912\nq\ns\nq\n") == 0
    assert stored()["spoolman_url"] == "http://other.example:7912" and applied == [False]


def test_a_secret_prompt_reads_the_next_piped_line_and_never_calls_getpass(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("getpass reads the terminal, not the pipe"))
    assert run(monkeypatch, "4\n2\nsk-ant-PIPED\nq\n4\n3\nclaude-x\nq\ns\nq\n") == 0     # the lines after it stay in step
    cap = capsys.readouterr()
    assert (config.paths().etc / "anthropic_key").read_text().strip() == "sk-ant-PIPED"
    assert stored()["model"] == "claude-x" and "sk-ant-PIPED" not in cap.out + cap.err


def test_a_save_that_fails_leaves_every_secret_unchanged(monkeypatch, capsys):
    all_features()
    (config.paths().etc / "github_token").write_text("ghp_old\n")

    def boom(cfg):
        raise ValueError("the disk is full")
    monkeypatch.setattr(config, "save", boom)
    assert run(monkeypatch, "4\n2\nsk-ant-NEW\nq\n8\n1\nghp_new\nq\ns\nq\ny\n") == 5
    err = say(capsys.readouterr().err)
    assert "Error: nothing was saved: the disk is full. Your changes are still here." in err
    assert not (config.paths().etc / "anthropic_key").exists()
    assert (config.paths().etc / "github_token").read_text().strip() == "ghp_old"


def test_a_secret_that_cannot_be_written_puts_the_settings_back(monkeypatch, capsys):
    all_features()

    def boom(text):
        raise ValueError("no group")
    monkeypatch.setattr(cli, "write_key", boom)
    before = stored()["server_name"]
    assert run(monkeypatch, "2\n1\nMine\nq\n4\n2\nsk-ant-NEW\nq\ns\nq\ny\n") == 5
    assert stored()["server_name"] == before
    assert "not everything was saved: no group. The settings are as before. Your changes are still here." in say(
        capsys.readouterr().err)


def test_a_bad_catalog_token_asks_again(monkeypatch, capsys):
    all_features()
    assert run(monkeypatch, "8\n1\nnot a token\nghp_good\nq\ns\nq\n") == 0
    assert "Error: a GitHub token is one word of printable characters." in capsys.readouterr().err
    assert (config.paths().etc / "github_token").read_text().strip() == "ghp_good"


def test_features_opened_inside_config_apply_on_settings_read_when_s_is_pressed(monkeypatch):
    seen, first = [], []
    real = cli._features_checklist

    def checklist(*a, **k):
        if not first:                         # something else changes the settings after the menu opened
            first.append(1)
            cfg = config.load()
            cfg["server_name"] = "Changed elsewhere"
            config.save(cfg)
        return real(*a, **k)
    monkeypatch.setattr(cli, "_features_checklist", checklist)
    monkeypatch.setattr(cli, "_apply_features", lambda ui, cfg, *a: seen.append(cfg["server_name"]) or (False, 0))
    assert run(monkeypatch, "11\ns\nq\nq\n") == 0
    assert seen == ["Changed elsewhere"]


@pytest.fixture
def cert(monkeypatch):
    """The serial the printer names in its certificate (setup_page.setup_serial): `box[0]` is it, or an OSError."""
    box = [OSError("no answer")]
    asked = []

    def setup_serial(ip, timeout=5):
        asked.append(ip)
        if isinstance(box[0], Exception):
            raise box[0]
        return box[0]
    monkeypatch.setattr("filament_kit.setup_page.setup_serial", setup_serial)
    return box, asked


@pytest.fixture(autouse=True)
def no_printer_answers(monkeypatch):
    monkeypatch.setattr("filament_kit.setup_page.setup_serial", lambda ip, timeout=5: (_ for _ in ()).throw(OSError("off")))


def test_an_empty_serial_is_read_from_the_printers_certificate(secrets, cert, monkeypatch, capsys):
    asked, given = secrets
    given += ["12345678"]
    box, seen = cert
    box[0] = "0948ZZ0A0000009"
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\n\n192.0.2.57\nMine\n\n\nq\nq\n") == 0
    assert seen == ["192.0.2.57"] and registry.load()["0948ZZ0A0000009"].name == "Mine"
    assert "Added Mine." in capsys.readouterr().out


def test_an_empty_serial_is_never_taken_from_a_saved_printer_at_that_address(secrets, monkeypatch, capsys):
    asked, given = secrets
    given += ["NEWCODE2"]
    registry.add_bambu("0948ZZ0A0000001", "Workshop", "H2D", "192.0.2.57", "OLDCODE1")
    registry.upsert(registry.Printer("0948ZZ0A0000001", "Workshop", "H2D", "192.0.2.57", "OLDCODE1", True, cert_fp="ab" * 32))
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\n\n192.0.2.57\nNew printer\n\n\nq\nq\n") == 0
    cap = capsys.readouterr()
    assert "Error: the printer at 192.0.2.57 did not answer (OSError), so it cannot be read. Fix: give the serial" in say(cap.err)
    p = registry.load()
    assert list(p) == ["0948ZZ0A0000001"] and p["0948ZZ0A0000001"].name == "Workshop"
    assert p["0948ZZ0A0000001"].access_code == "OLDCODE1" and p["0948ZZ0A0000001"].cert_fp == "ab" * 32


def test_a_typed_serial_that_the_certificate_contradicts_is_refused(secrets, cert, monkeypatch, capsys):
    asked, given = secrets
    given += ["12345678"]
    box, _ = cert
    box[0] = "0948ZZ0A0000009"
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\n\n192.0.2.57\nMine\n0948ZZ0A0000001\n\nq\nq\n") == 0
    err = say(capsys.readouterr().err)
    assert "names itself 0948ZZ0A0000009, not 0948ZZ0A0000001" in err and registry.load() == {}


def test_a_typed_serial_is_used_when_the_printer_does_not_answer(secrets, monkeypatch, capsys):
    asked, given = secrets
    given += ["12345678"]
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\n\n192.0.2.57\nMine\n0948ZZ0A0000001\n\nq\nq\n") == 0
    assert registry.load()["0948ZZ0A0000001"].name == "Mine"


def test_an_empty_serial_with_a_certificate_without_one_is_an_error_with_a_fix(secrets, cert, monkeypatch, capsys):
    asked, given = secrets
    given += ["12345678"]
    cert[0][0] = None
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\n\n192.0.2.57\nMine\n\n\nq\nq\n") == 0
    assert "did not name its serial" in say(capsys.readouterr().err) and registry.load() == {}


def test_the_end_of_input_at_a_secret_prompt_of_the_add_ends_the_session_with_5(secrets, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    monkeypatch.setattr(secret_input, "ask", lambda prompt: (_ for _ in ()).throw(EOFError()))
    assert run(monkeypatch, "3\n2\nShelf Z\n10\na\n\n192.0.2.57\n") == 5
    out = capsys.readouterr().out
    assert out.rstrip().endswith("Input ended: 1 change not saved.") and registry.load() == {}


def test_a_settings_file_that_cannot_be_written_is_an_error_and_the_changes_stay(capsys, monkeypatch):
    def refuse(cfg):
        raise PermissionError("config.json: access denied")
    monkeypatch.setattr(config, "save", refuse)
    assert run(monkeypatch, "3\n2\nShelf Z\ns\nq\nq\nyes\n") == 5
    assert "nothing was saved: config.json: access denied. Your changes are still here." in say(capsys.readouterr().err)


def test_a_klipper_port_that_is_not_a_number_is_a_plain_error(secrets, monkeypatch, capsys):
    asked, given = secrets
    given += [""]
    monkeypatch.setattr(cli, "_printer_states", lambda: {})
    assert run(monkeypatch, "10\na\nk\nvoron.example\nabc\n\nq\nq\n") == 0
    err = say(capsys.readouterr().err)
    assert "Error: the port is a number. Fix: give the port as digits, for example 7125." in err and "invalid literal" not in err
    assert registry.load() == {}
