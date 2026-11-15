"""S5.7: `presets` (06 9.5) and its old spelling `profiles`. Each command runs through `cli.main` against the Hub's own
build, line and update code (the fakes of test_builds and test_presets_updates). AUT-9 for `presets status`: 79-column
lines, no escape byte without colour, ASCII with `--plain`, `--json` parses. Example names only."""
from __future__ import annotations

import builtins
import json
import logging
import re

import pytest
import test_builds as TB
import test_generate as TG
from test_presets_updates import LID, N04, _first_install, _rebuild, env  # noqa: F401  (env is the fixture)

from filament_kit import cli, config, output
from filament_kit.profiles import builds
from filament_kit.setup_console import presets_tab

ESC = "\x1b"


def run(capsys, *args):
    rc = cli.main(list(args), sm_factory=lambda: _SM[0])
    got = capsys.readouterr()
    return rc, got.out, got.err


_SM: list = [None]


@pytest.fixture(autouse=True)
def sm(env, monkeypatch):                       # noqa: F811
    _SM[0] = env
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")
    return env


@pytest.fixture
def terminal(monkeypatch):
    """`terminal(True, "y")`: whether standard input is a terminal, and what it answers to each question."""
    asked: list[str] = []

    def setup(at_terminal: bool, *answers: str):
        left = list(answers)
        monkeypatch.setattr(output, "terminal", lambda: at_terminal)

        def fake_input(prompt=""):
            asked.append(prompt)
            print(prompt, end="")                    # what the real input() writes at a terminal
            if not left:
                raise EOFError
            return left.pop(0)
        monkeypatch.setattr(builtins, "input", fake_input)
        return asked
    return setup


def updated(env):
    """A first install, then a rebuild with new densities: every installed preset has an update waiting."""
    _first_install(env)
    return _rebuild(env, 1.31, TG.NOW + 1)


# ---------------------------------------------------------------- presets status

def test_status_before_any_build_says_what_is_missing_and_how_to_fix_it(capsys):
    rc, out, _ = run(capsys, "presets", "status")
    lines = out.splitlines()
    assert rc == 0 and lines[:3] == ["Lines: 0.", "No build yet.", "Installed on the PC: nothing yet."]
    assert lines[3] == "  ▲ needs a look  Slicer Sync: not set up."
    assert lines[4].strip() == "Fix: sudo filament-kit pair --slicer-sync"
    assert " ".join(" ".join(lines[5:]).split()) == ("Updates: none. Presets already in your slicers are never replaced "
                                                    "unless you accept them.")


def test_status_after_a_build_follows_the_hub_pages_order_and_counts_updates(env, capsys):
    updated(env)
    rc, out, _ = run(capsys, "presets", "status")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "Lines: 1."
    assert lines[1].startswith("Last build ") and ". Presets: " in lines[1] and lines[1].endswith("Problems: none.")
    assert lines[2].startswith("Installed on the PC: the build of ") and ", written " in lines[2]
    assert lines[3].startswith("Slicer Sync: last reported ") or lines[3].startswith("Slicer Sync: set up")
    text = " ".join(out.split())
    n = builds.status()["updates"]["count"]
    assert n and f"Updates: {n} on 1 line. Presets already in your slicers are never replaced unless you accept them." in text
    assert "See them: sudo filament-kit presets updates" in text and "presets status" not in text.split("See them")[1]


def test_status_json_is_what_the_hub_page_reads(env, capsys):
    updated(env)
    rc, out, _ = run(capsys, "presets", "status", "--json")
    assert rc == 0 and out.count("\n") == 1
    assert json.loads(out) == json.loads(json.dumps(presets_tab._view()))


def test_status_names_the_presets_to_delete_by_hand_and_the_last_failure(env, capsys, monkeypatch):
    TB.synced(env)
    view = presets_tab._view()
    monkeypatch.setattr(presets_tab, "_view", lambda: {**view, "stale": ["Old PLA"], "orca_stale": ["Old Orca PLA"],
                                                       "problems": ["Sample PLA: no parent; skipped"],
                                                       "last_attempt": {"at": view["last_attempt"] and None or "2026-11-12T03:05:00+00:00",
                                                                        "ok": False, "error": "ValueError: boom"}})
    out = run(capsys, "presets", "status")[1]
    assert "Delete in Bambu Studio: Old PLA\nDelete in Orca Slicer: Old Orca PLA\n" in out
    assert "▲ needs a look Sample PLA: no parent; skipped" in " ".join(out.split())
    assert "The last build attempt failed (" in out and "): ValueError: boom." in out


def test_status_while_the_feature_is_off_says_so_and_json_gives_on_false(capsys):
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True, "presets": False}
    config.save(cfg)
    rc, out, err = run(capsys, "presets", "status")
    assert rc == 1 and out == "" and err.startswith('Error: the "Slicer presets" Feature is off.')
    assert "sudo filament-kit features on presets" in err
    rc, out, _ = run(capsys, "presets", "status", "--json")                 # the same exit code and an error document
    got = json.loads(out)
    assert rc == 1 and got["ok"] is False and "Slicer presets" in got["error"]
    assert run(capsys, "presets", "restore-deleted")[0] == 1 and run(capsys, "presets", "updates")[0] == 1


# ---------------------------------------------------------------- presets build

def test_build_says_done_with_the_count_and_no_problems(env, capsys):
    TB.synced(env)
    rc, out, _ = run(capsys, "presets", "build")
    assert rc == 0
    n = builds.current()["presets"]
    assert out == f"  ● done          Presets built: {n}. Problems: none.\n"


def test_build_lists_each_problem_as_a_line_that_needs_a_look(capsys, monkeypatch):
    monkeypatch.setattr(builds, "run_build", lambda sm: {"ok": True, "stamp": "s1", "problems": ["A: no parent", "B: bad"]})
    monkeypatch.setattr(builds, "current", lambda: {"presets": 48})
    rc, out, _ = run(capsys, "presets", "build")
    assert rc == 0 and out.splitlines()[0] == "  ● done          Presets built: 48. Problems: 2:"
    assert out.splitlines()[1:] == ["  ▲ needs a look  A: no parent", "  ▲ needs a look  B: bad"]


def test_a_failed_build_keeps_the_last_good_one_and_says_where_to_read_why(capsys, monkeypatch):
    monkeypatch.setattr(builds, "run_build", lambda sm: {"ok": False, "error": "boom"})
    rc, out, err = run(capsys, "presets", "build")
    assert rc == 1 and out == ""
    assert "Error: The build failed: boom. The last good build stays in use." in err
    assert "sudo journalctl -u filament-kit-build -n 50" in err


def test_a_build_still_waiting_for_the_first_sync_is_a_note_not_a_failure(capsys, monkeypatch):
    monkeypatch.setattr(builds, "run_build", lambda sm: {"waiting": True, "error": builds.NO_SYSTEM})
    rc, out, err = run(capsys, "presets", "build")
    assert rc == 0 and out.startswith("  ◆ note          ") and builds.NO_SYSTEM in " ".join(out.split())
    assert "Fix: sudo filament-kit pair --slicer-sync" in out


def test_build_json_and_the_old_spelling_the_build_unit_runs(env, capsys):
    TB.synced(env)
    rc, out, _ = run(capsys, "profiles", "build", "--json")
    got = json.loads(out)
    assert rc == 0 and got["ok"] is True and got["problems"] == [] and got["presets"] > 0


# ---------------------------------------------------------------- presets lines

def test_lines_is_a_table_with_the_parents_and_filaments_under_each_row(env, capsys):
    TB.synced(env)
    builds.run_build(env, now=TG.NOW)
    rc, out, _ = run(capsys, "presets", "lines")
    lines = out.splitlines()
    assert rc == 0 and lines[0].split() == ["ID", "LINE", "MATERIAL", "PRESETS"]
    assert lines[1].startswith(LID) and lines[2].startswith("  parents: Bambu Studio ")
    assert " Orca Slicer " in " ".join(lines[2:4]) and "  filaments: " in out


def test_lines_with_none_yet_says_where_they_come_from(capsys):
    rc, out, _ = run(capsys, "presets", "lines")
    assert rc == 0 and " ".join(out.split()) == ("No lines yet. They are made from the Spoolman filaments at the next "
                                                 "build or addition.")


def test_lines_json_is_the_hubs_line_view(env, capsys):
    TB.synced(env)
    builds.run_build(env, now=TG.NOW)
    got = json.loads(run(capsys, "presets", "lines", "--json")[1])
    assert [r["line_id"] for r in got["lines"]] == [LID] and set(got["lines"][0]) >= {"bambu_parent", "orca_parent",
                                                                                      "spoolman_ids", "presets"}


# ---------------------------------------------------------------- restore-deleted, set-parent: audit lines come with them

def _audit(caplog) -> list[str]:
    return [r.getMessage().split(" from ")[0] for r in caplog.records if r.name == "filament_kit.setup_page"]


def test_a_lines_error_gives_the_same_exit_code_and_an_error_document_under_json(env, capsys, monkeypatch):
    v = presets_tab._view()
    monkeypatch.setattr(presets_tab, "_view", lambda: {**v, "lines_error": "lines.json is unreadable."})
    assert run(capsys, "presets", "status")[0] == 1
    rc, out, _ = run(capsys, "presets", "status", "--json")
    assert rc == 1 and json.loads(out)["ok"] is False and "lines.json" in json.loads(out)["error"]


def test_an_audit_line_lands_where_the_hubs_go_without_any_test_handler(capsys, real_journal_logging):
    """No caplog: the Hub's own logger setup (__main__._log_to_journal) is what puts the line on standard error."""
    log = logging.getLogger("filament_kit")
    log.handlers[:], log.propagate = [], True              # a real run: no handler yet (conftest restores it)
    cli._hub_audit("probe change")
    cli._history_audit("rid1", "revised")
    err = capsys.readouterr().err
    assert "INFO filament_kit.setup_page: setup: probe change from " in err
    assert "setup: recently added record rid1 revised from " in err


def test_restore_deleted_asks_for_a_build_and_is_audited_as_the_hub_page_does(env, capsys, caplog, monkeypatch):
    caplog.set_level("INFO")
    asked = []
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: asked.append(reason))
    rc, out, _ = run(capsys, "presets", "restore-deleted")
    assert rc == 0 and " ".join(out.split()) == ("The next build brings back the presets deleted in Bambu Studio. "
                                                 "A build was asked for.") and asked
    assert (config.paths().state / "profiles" / "restore-deleted").exists()
    assert _audit(caplog) == ["setup: Slicer presets deleted in Bambu Studio: restore requested"]
    assert run(capsys, "profiles", "restore-deleted", "--quiet")[1] == ""


def test_set_parent_is_audited_and_json_names_what_was_set(env, capsys, caplog, monkeypatch):
    caplog.set_level("INFO")
    TB.synced(env)
    builds.run_build(env, now=TG.NOW)
    monkeypatch.setattr(builds, "request_rebuild", lambda reason, live_hash=None, *, orca_live_hash=None: None)
    rc, out, _ = run(capsys, "presets", "set-parent", LID, "Generic PLA", "--json")
    got = json.loads(out)
    assert rc == 0 and got["ok"] is True and got["line"] == LID and got["parent"] == "Generic PLA"
    assert _audit(caplog) == [f"setup: Slicer preset line {LID}: bambu parent set"]


# ---------------------------------------------------------------- presets updates, accept-updates

def test_updates_lists_one_line_per_update_and_changes_nothing(env, capsys, caplog):
    caplog.set_level("INFO")
    updated(env)
    rc, out, _ = run(capsys, "presets", "updates")
    n = builds.status()["updates"]["count"]
    lines = out.splitlines()
    assert rc == 0 and lines[-1] == f"{n} updates would be accepted; nothing was changed."
    assert lines[0].startswith("SUNLU PLA+ 2.0  Bambu Studio: ") and out.count("filament_density") == n
    assert all(len(ln) <= 79 for ln in lines)
    assert builds.status()["updates"]["accepted"] == 0 and _audit(caplog) == []


def test_updates_with_none_says_so(env, capsys):
    _first_install(env)
    assert run(capsys, "presets", "updates")[1] == "No updates to accept.\n"
    assert run(capsys, "presets", "accept-updates", "--yes")[1] == "No updates to accept.\n"


def test_accept_updates_lists_asks_and_then_says_when_the_sync_writes_them(env, capsys, caplog, terminal):
    caplog.set_level("INFO")
    updated(env)
    n = builds.status()["updates"]["count"]
    asked = terminal(True, "y")
    rc, out, _ = run(capsys, "presets", "accept-updates")
    text = " ".join(out.split())
    assert rc == 0 and f"Accept these {n} updates? The Slicer Sync writes them at its next run, after its backup. [y/N]" in text
    assert text.endswith(f"{n} updates accepted; the Slicer Sync writes them at its next run, after its backup.")
    assert out.index("filament_density") < out.index("Accept these")      # the list comes before the question
    assert out.count("filament_density") == n and asked
    assert builds.status()["updates"]["accepted"] == n
    assert _audit(caplog) == [f"setup: {n} Slicer preset updates accepted"]


def test_accept_updates_a_no_changes_nothing_and_a_pipe_without_yes_stops(env, capsys, terminal):
    updated(env)
    terminal(True, "n")
    rc, out, _ = run(capsys, "presets", "accept-updates")
    assert rc == 5 and out.rstrip().endswith("Nothing changed.") and builds.status()["updates"]["accepted"] == 0
    terminal(False)
    rc, out, err = run(capsys, "presets", "accept-updates")
    assert rc == 2 and out == "" and "needs a yes, and there is no terminal to ask." in " ".join(err.split())
    assert err.rstrip().endswith("presets accept-updates --yes") and builds.status()["updates"]["accepted"] == 0


def test_accept_updates_with_yes_and_one_line_only(env, capsys, terminal):
    updated(env)
    terminal(False)
    rc, out, err = run(capsys, "presets", "accept-updates", "--line", "nope", "--yes")
    assert rc == 1 and "there are no updates for line nope." in " ".join(err.split())
    rc, out, _ = run(capsys, "presets", "accept-updates", "--line", LID, "--yes", "--json")
    got = json.loads(out)
    assert rc == 0 and got["ok"] is True and got["dry_run"] is False and got["count"] == len(got["chosen"]) > 0
    assert set(got["chosen"][0]) == {"line_id", "target", "name", "file", "keys"}      # the Hub's own reply shape


def test_all_is_every_update_and_excludes_line(env, capsys, terminal):
    updated(env)
    terminal(False)
    n = builds.status()["updates"]["count"]
    assert run(capsys, "presets", "updates", "--all")[1] == run(capsys, "presets", "updates")[1]
    for argv in (["updates", "--all", "--line", LID], ["accept-updates", "--all", "--line", LID, "--yes"]):
        with pytest.raises(SystemExit) as e:
            run(capsys, "presets", *argv)
        assert e.value.code == 2
    rc, out, _ = run(capsys, "presets", "accept-updates", "--all", "--yes")
    assert rc == 0 and f"{n} updates accepted" in out and builds.status()["updates"]["accepted"] == n


def test_an_empty_line_is_a_usage_error_naming_the_lines_command(env, capsys):
    updated(env)
    for which in ("updates", "accept-updates"):
        rc, out, err = run(capsys, "presets", which, "--line", "")
        assert rc == 2 and "--all" not in err and "presets lines" in err and builds.status()["updates"]["accepted"] == 0


def test_the_updates_changing_while_asked_is_the_hubs_refusal_in_the_specs_words(env, capsys, terminal, monkeypatch):
    updated(env)
    real = builds.apply_updates

    def apply(**kw):
        if kw.get("dry_run") is False:
            raise builds.UpdatesChanged()
        return real(**kw)
    monkeypatch.setattr(builds, "apply_updates", apply)
    terminal(True, "y")
    rc, _, err = run(capsys, "presets", "accept-updates")
    assert rc == 1 and err.startswith("Error: the updates changed since this list.")
    assert "Fix: run it again to see them." in err


# ---------------------------------------------------------------- the old spellings are the same commands

def test_profiles_is_presets_under_its_old_name(env, capsys):
    updated(env)
    for old, new in ((["profiles", "status"], ["presets", "status"]), (["profiles", "lines"], ["presets", "lines"]),
                     (["profiles", "apply-updates", "--all", "--dry-run"], ["presets", "updates"]),
                     (["profiles", "apply-updates", "--line", LID, "--dry-run"], ["presets", "updates", "--line", LID])):
        a, b = run(capsys, *old), run(capsys, *new)
        assert a == b and a[0] == 0, old


def test_profiles_apply_updates_still_needs_a_line_or_all(env, capsys):
    updated(env)
    with pytest.raises(SystemExit) as e:
        cli.main(["profiles", "apply-updates"])
    assert e.value.code == 2 and "required" in capsys.readouterr().err
    assert run(capsys, "profiles", "apply-updates", "--all", "--yes")[0] == 0
    assert builds.status()["updates"]["accepted"] > 0


# ---------------------------------------------------------------- AUT-9: width, escape bytes, plain, json

AUT = [["presets", "status"], ["presets", "lines"], ["presets", "updates"]]


@pytest.mark.parametrize("argv", AUT, ids=" ".join)
def test_aut9_every_line_fits_79_columns_with_no_escape_byte_without_colour(argv, env, capsys, monkeypatch):
    updated(env)
    capsys.readouterr()
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)           # a terminal: tables are cut or turned into blocks
    rc, out, err = run(capsys, *argv)
    assert rc == 0
    for line in (out + err).splitlines():
        assert len(re.sub(ESC + r"\[[0-9;]*m", "", line)) <= 79, line
    monkeypatch.setenv("NO_COLOR", "1")
    rc, out, err = run(capsys, *argv)
    assert rc == 0 and ESC not in out + err


@pytest.mark.parametrize("argv", AUT, ids=" ".join)
def test_aut9_plain_is_ascii_with_no_carriage_return_and_no_escape(argv, env, capsys, monkeypatch):
    updated(env)
    capsys.readouterr()
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")      # --plain wins over the locale
    rc, out, err = run(capsys, "--plain", *argv)
    assert rc == 0 and (out + err).isascii() and "\r" not in out + err and ESC not in out + err


@pytest.mark.parametrize("argv", AUT, ids=" ".join)
def test_aut9_json_is_one_document(argv, env, capsys):
    updated(env)
    capsys.readouterr()
    rc, out, err = run(capsys, "--color", "always", *argv, "--json")
    assert rc == 0 and out.endswith("}\n") and out.count("\n") == 1 and ESC not in out and json.loads(out) is not None
