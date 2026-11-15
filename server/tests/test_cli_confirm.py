"""S5.2: confirmations (06 7), AUT-9 for every destructive command that exists today. Each command, run three ways:
piped with no `--yes` (exit 2, standard output empty, `Error:` and `Fix:` on standard error, nothing done); answered
no, with an empty answer, or at the end of input (exit 5, `Nothing changed.`, nothing done); and with `--yes` (the
action runs and the question is never printed). A `y` or `yes` in any case goes on. The commands are run through
`cli.main` with the action itself replaced by a recorder, so what each test checks is that the action did or did not
run. Example names and addresses only."""
from __future__ import annotations

import builtins
import types

import pytest

from filament_kit import cli, modules, output, release, updates
from filament_kit.bridge import registry
from filament_kit.profiles import builds
from filament_kit.web import reader as web_reader

SERIAL = "01S00C111111111"


class Rec:
    """What the replaced actions were asked to do."""

    def __init__(self):
        self.acted: list[str] = []

    def __call__(self, what):
        def act(*a, **k):
            self.acted.append(what)
            return 0
        return act


@pytest.fixture
def rec(monkeypatch):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")        # no systemctl, and root is not asked for
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    return Rec()


@pytest.fixture
def terminal(monkeypatch):
    """`terminal(True, "n")`: whether standard input is a terminal, and what it answers to each question."""
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


# ---------- one arrangement per command: (argv, what it prints in its question) ----------

def _unpair(m, rec, tmp_path):
    m.setattr(cli.pairing, "devices", lambda: [{"id": "d1", "name": "Shop phone", "paired": 0, "last_seen": 0}])
    m.setattr(cli.pairing, "revoke", lambda i: rec("revoke")() == 0)
    return ["unpair", "d1"], "Unpair Shop phone? It can no longer reach the kit server until it is paired again."


def _unpin(m, rec, tmp_path):
    p = registry.Printer(SERIAL, "Workshop X1", "X1C", "192.0.2.40", "12345678", True, "ab" * 32)
    m.setattr(registry, "load", lambda: {SERIAL: p})
    m.setattr(cli.secret_input, "ask", lambda prompt: "24681357")
    m.setattr(registry, "check_fields", lambda serial, code: None)
    m.setattr(registry, "set_code", rec("set_code"))
    return ["printer", "unpin", SERIAL], "Forget the certificate of Workshop X1? The next connection trusts whatever"


def _map(m, rec, tmp_path):
    p = registry.Printer(SERIAL, "Workshop X1", "X1C", "192.0.2.40", "12345678", True)
    m.setattr(registry, "load", lambda: {SERIAL: p})
    m.setattr(cli, "_server_api", lambda: object())
    m.setattr(cli, "_map_via_server", rec("map"))
    return ["printer", "map", SERIAL], "Map the slots of Workshop X1? The printer changes its slot colours briefly"


def _library_rollback(m, rec, tmp_path):
    m.setattr(cli.library, "rollback", lambda: rec("rollback")() or 3)
    m.setattr(cli.library, "rolled_back_from", lambda: None)
    m.setattr(cli, "_request_rebuild", lambda reason: None)
    return ["library", "rollback"], "Go back to the previous Filament Catalog? The version before the last update comes"


def _apply_updates(m, rec, tmp_path):
    row = {"line_id": "pla", "target": "base", "name": "Example PLA", "keys": ["nozzle_temperature"], "file": None}

    def apply(*, line_id=None, all_=False, dry_run=False, **kw):
        if not dry_run:
            rec("accept")()
        return {"stamp": "s1", "chosen": [row], "dry_run": dry_run}
    m.setattr(builds, "apply_updates", apply)
    return ["profiles", "apply-updates", "--all"], "Accept this update? The PC sync writes it at its next run, after its backup."


def _setup_code_new(m, rec, tmp_path):
    from filament_kit import setup_code
    m.setattr(setup_code, "generate", lambda: rec("generate")() or "code")
    m.setattr(setup_code, "write", lambda code: None)
    m.setattr(setup_code, "page_url", lambda cfg: "https://hub.example/setup")
    m.setattr(setup_code, "shown", lambda code: code)
    m.setattr(setup_code, "ensure", lambda: "code")
    from filament_kit import trusted
    m.setattr(trusted, "listing", lambda: [])
    return ["setup-code", "--new"], "Make a new setup code? The old one stops working."


def _setup_code_revoke(m, rec, tmp_path):
    from filament_kit import setup_code, trusted
    m.setattr(setup_code, "ensure", lambda: "code")
    m.setattr(setup_code, "page_url", lambda cfg: "https://hub.example/setup")
    m.setattr(setup_code, "shown", lambda code: code)
    m.setattr(trusted, "revoke_all", lambda: rec("revoke_all")() or 2)
    return ["setup-code", "--revoke-trusted"], "Revoke every trusted computer? Each one needs the setup code again."


def _reader_revoke(m, rec, tmp_path):
    class Store:
        def list(self):
            return [{"id": "tr3", "name": "bench", "created": "2026-11-01"}]

        def revoke(self, ref):
            rec("revoke")()
            return True
    m.setattr(web_reader, "TokenStore", Store)
    return ["reader", "revoke", "tr3"], "Revoke the token tr3? A reader using it is refused from now on."


def _uninstall(m, rec, tmp_path):
    root = tmp_path / "kept"
    root.mkdir()
    (root / "uninstall.sh").write_text("# example\n")
    m.setattr(cli, "_kept_release", lambda: ("1.2.0", tmp_path / "1.2.0.tar.gz"))
    m.setattr(updates, "current_version", lambda: "1.2.0")
    m.setattr(release, "extract", lambda tarball, ver, work: root)
    m.setattr(cli.subprocess, "call", lambda cmd, **k: rec("uninstall")() or 0)
    return ["uninstall"], "Remove filament-kit from this machine? Its data stays unless you add --purge."


def _update(m, rec, tmp_path):
    m.setattr(updates, "check_info", lambda cfg, **k: {"newer": True, "latest": "0.5.3"})
    m.setattr(updates, "update", lambda cfg, **k: rec("update")() or 0)
    return ["update"], "Update to 0.5.3? filament-kit stops while it installs and starts again by itself."


def _rollback(m, rec, tmp_path):
    m.setattr(updates, "_read_state", lambda: {"previous": "0.5.1"})
    m.setattr(updates, "_kept", lambda version: True)
    m.setattr(updates, "rollback", lambda cfg, **k: rec("rollback")() or 0)
    return ["update", "--rollback"], "Roll back to 0.5.1? filament-kit stops while it installs and starts again by itself."


def _remote_issue(m, rec, tmp_path):
    from filament_kit import remote
    m.setattr(modules, "enabled", lambda cfg: {"remote"})
    m.setattr(remote, "issue", lambda cfg, **k: rec("issue")() or 0)
    return ["remote", "issue"], "Get the certificate now? Port 80 on your router must reach this kit server while it runs."


def _local_intake_remove(m, rec, tmp_path):
    from filament_kit import local_intake_install as lii
    m.setattr(lii, "installed", lambda: {"version": "0.2.0"})
    m.setattr(lii, "remove", lambda **k: rec("remove")())
    m.setattr(modules, "enabled", lambda cfg: {"server", "local_intake"})
    m.setattr(cli, "_save_and_apply", lambda cfg, notes=(): 0)
    return ["local-intake", "remove"], "Remove the local label reader 0.2.0 from this machine? Its settings are kept."


def _intake_revise(m, rec, tmp_path):
    from filament_kit import intake, intake_history
    m.setattr(intake, "reading_on", lambda cfg: True)
    proposal = {"reader": None, "before": {"vendor": "Example"}, "after": {"vendor": "Sample"},
                "changes": ["vendor"], "no_photo": False, "proposal": {}}
    m.setattr(intake_history, "revise", lambda *a, **k: proposal)
    m.setattr(intake_history, "apply", lambda *a, **k: rec("apply")() or {"revisions": [
        {"n": 2, "changes": [], "filaments": {"from": 1, "to": 1}, "spool_ids": [1]}]})
    return ["intake", "revise", "r1", "--note", "brand is Sample"], "Accept these changes?"


CASES = {
    "unpair": _unpair,
    "printer unpin": _unpin,
    "printer map": _map,
    "library rollback": _library_rollback,
    "profiles apply-updates": _apply_updates,
    "setup-code --new": _setup_code_new,
    "setup-code --revoke-trusted": _setup_code_revoke,
    "reader revoke": _reader_revoke,
    "uninstall": _uninstall,
    "update": _update,
    "update --rollback": _rollback,
    "remote issue": _remote_issue,
    "local-intake remove": _local_intake_remove,
    "intake revise": _intake_revise,
}


@pytest.fixture(params=list(CASES))
def command(request, monkeypatch, rec, tmp_path):
    argv, question = CASES[request.param](monkeypatch, rec, tmp_path)
    return types.SimpleNamespace(argv=argv, question=question, name=request.param)


def run(capsys, argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    got = capsys.readouterr()
    return rc, got.out, got.err


# ---------- AUT-9 ----------

def test_piped_without_yes_does_nothing_and_exits_2(command, rec, terminal, capsys):
    terminal(False)
    rc, out, err = run(capsys, command.argv)
    assert rc == 2 and rec.acted == []
    assert out == ""                                    # nothing on standard output
    assert err.startswith("Error: ") and "needs a yes, and there is no terminal to ask." in " ".join(err.split())
    assert "\nFix: run it again with --yes" in err and err.rstrip().endswith("--yes")


@pytest.mark.parametrize("answer", ["n", "no", "", "maybe", "yess"])
def test_anything_but_yes_is_no_exit_5(command, rec, terminal, capsys, answer):
    asked = terminal(True, answer)
    rc, out, err = run(capsys, command.argv)
    assert rc == 5 and rec.acted == []
    assert out.rstrip().endswith("Nothing changed.") and asked and "[y/N]" in asked[-1]


def test_the_end_of_input_is_no(command, rec, terminal, capsys):
    terminal(True)                                      # no answer: EOFError
    rc, out, _ = run(capsys, command.argv)
    assert rc == 5 and rec.acted == [] and out.rstrip().endswith("Nothing changed.")


@pytest.mark.parametrize("answer", ["y", "Y", "yes", " YES "])
def test_yes_goes_on(command, rec, terminal, capsys, answer):
    terminal(True, answer, *["y"] * 2)                  # setup-code --new may ask once more; none asks a third time
    rc, out, err = run(capsys, command.argv)
    assert rc == 0 and rec.acted, err


@pytest.mark.parametrize("flag", ["--yes", "-y"])
def test_yes_runs_without_asking(command, rec, terminal, capsys, flag):
    asked = terminal(False)                             # not a terminal, and any question would fail
    rc, out, err = run(capsys, [*command.argv, flag])
    assert rc == 0 and rec.acted, err
    assert asked == [] and "[y/N]" not in out and command.question not in out


def test_the_question_is_the_hub_pages_dialog(command, terminal, capsys):
    asked = terminal(True, "n")
    out = run(capsys, command.argv)[1]
    assert " ".join(command.question.split()) in " ".join(out.split())


# ---------- what is specific to a command ----------

def test_apply_updates_dry_run_asks_nothing(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _apply_updates(monkeypatch, rec, tmp_path)
    terminal(False)
    rc, out, err = run(capsys, [*argv, "--dry-run"])
    assert rc == 0 and rec.acted == [] and "dry run" in out


def test_apply_updates_lists_nothing_when_nobody_can_answer(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _apply_updates(monkeypatch, rec, tmp_path)
    terminal(False)
    assert run(capsys, argv)[1] == ""


def test_setup_code_new_with_revoke_asks_both_and_a_no_to_the_second_stops_before_either(rec, monkeypatch, terminal,
                                                                                         capsys, tmp_path):
    argv, _ = _setup_code_new(monkeypatch, rec, tmp_path)
    from filament_kit import trusted
    monkeypatch.setattr(trusted, "revoke_all", lambda: rec("revoke_all")() or 2)
    asked = terminal(True, "y", "n")
    rc, out, _ = run(capsys, [*argv, "--revoke-trusted"])
    assert rc == 5 and rec.acted == [] and len(asked) == 2


def _updates_landing(monkeypatch, rec, current):
    """builds.apply_updates over a list that a build changes once it was shown: `current["stamp"]` is the build now."""
    row = {"line_id": "pla", "target": "base", "name": "Example PLA", "keys": ["nozzle_temperature"], "file": None}
    got = {}

    def apply(*, line_id=None, all_=False, dry_run=False, only=None, expect_stamp=None):
        if dry_run:
            shown = current["stamp"]
            current["stamp"] = "s2"             # the build lands while the question is open
            return {"stamp": shown, "chosen": [row], "dry_run": True}
        got.update(only=only, expect_stamp=expect_stamp)
        if expect_stamp is not None and expect_stamp != current["stamp"]:
            raise builds.UpdatesChanged()
        rec("accept")()
        return {"stamp": current["stamp"], "chosen": [row], "dry_run": False}
    monkeypatch.setattr(builds, "apply_updates", apply)
    return got


def test_updates_that_changed_while_asked_are_not_accepted(rec, monkeypatch, terminal, capsys):
    got = _updates_landing(monkeypatch, rec, {"stamp": "s1"})
    terminal(True, "y")
    rc, out, err = run(capsys, ["profiles", "apply-updates", "--all"])
    assert rc == 1 and rec.acted == [] and "nothing was accepted" in err and "accepted 1 update" not in out
    assert got == {"only": {"Example PLA"}, "expect_stamp": "s1"}     # exactly what was shown, as the Hub does


def test_update_that_is_up_to_date_does_not_ask(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _update(monkeypatch, rec, tmp_path)
    monkeypatch.setattr(updates, "check_info", lambda cfg, **k: {"newer": False, "latest": "0.5.1"})
    asked = terminal(True)
    rc, _, _ = run(capsys, argv)
    assert rc == 0 and asked == [] and rec.acted == ["update"]


def test_scheduled_update_and_check_never_ask(rec, monkeypatch, terminal, capsys, tmp_path):
    _update(monkeypatch, rec, tmp_path)
    monkeypatch.setattr(updates, "check", lambda cfg, **k: rec("check")() or 0)
    terminal(False)
    assert run(capsys, ["update", "--scheduled"])[0] == 0 and run(capsys, ["update", "--check"])[0] == 0
    assert rec.acted == ["update", "check"]


def test_the_manual_map_does_not_ask(rec, monkeypatch, terminal, capsys, tmp_path):
    _map(monkeypatch, rec, tmp_path)
    monkeypatch.setattr(cli, "_manual_map_via_server", rec("manual"))
    terminal(False)
    assert run(capsys, ["printer", "map", "--manual", SERIAL])[0] == 0 and rec.acted == ["manual"]


def test_the_fix_line_names_the_command_again_with_yes(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _unpair(monkeypatch, rec, tmp_path)
    terminal(False)
    err = run(capsys, argv)[2]
    assert err.splitlines()[-1].strip() == "sudo filament-kit unpair d1 --yes"


def test_purge_asks_only_for_the_typed_word(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _uninstall(monkeypatch, rec, tmp_path)
    asked = terminal(True, " PURGE ")
    rc, out, _ = run(capsys, [*argv, "--purge"])
    assert rc == 0 and rec.acted == ["uninstall"]
    assert len(asked) == 1 and asked[0].endswith("go on: ") and "[y/N]" not in out
    assert "Type purge to go on:" in " ".join(out.split())


@pytest.mark.parametrize("typed", ["", "y", "yes", "purg"])
def test_purge_takes_only_its_word(rec, monkeypatch, terminal, capsys, tmp_path, typed):
    argv, _ = _uninstall(monkeypatch, rec, tmp_path)
    terminal(True, typed)
    rc, out, _ = run(capsys, [*argv, "--purge"])
    assert rc == 5 and rec.acted == [] and out.rstrip().endswith("Nothing changed.")


def test_purge_piped_without_yes_is_refused_and_with_yes_runs_both(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _uninstall(monkeypatch, rec, tmp_path)
    terminal(False)
    assert run(capsys, [*argv, "--purge"])[0] == 2 and rec.acted == []
    assert run(capsys, [*argv, "--purge", "--yes"])[0] == 0 and rec.acted == ["uninstall"]


def test_the_config_menu_asks_in_the_hub_pages_words_and_a_no_removes_nothing(monkeypatch, capsys):
    p = registry.Printer(SERIAL, "Workshop X1", "X1C", "192.0.2.40", "12345678", True)
    removed = []
    monkeypatch.setattr(registry, "remove", lambda serial: removed.append(serial))
    answers = iter(["n"])
    monkeypatch.setattr(cli, "_ask", lambda prompt: print(prompt, end="") or next(answers))
    monkeypatch.setattr(cli, "_pick_printer", lambda printers: p)
    cli._printers_action("4", [p])
    out = " ".join(capsys.readouterr().out.split())
    assert removed == [] and "Forget Workshop X1? filament-kit stops connecting to it and deletes its Access Code." in out
    assert "To use it again, add it again." in out and "Nothing changed." in out
    answers = iter(["yes"])
    cli._printers_action("4", [p])
    assert removed == [SERIAL]


def test_nothing_in_the_setup_helper_jobs_waits_for_an_answer():
    from filament_kit import setup_helper
    for name in ("update", "rollback", "library_rollback", "remote_issue", "restore"):
        assert "--yes" in setup_helper.JOBS[name], name


def test_a_pairing_nobody_claimed_is_removed_the_same_way(rec, monkeypatch, terminal, capsys):
    from filament_kit import pairing
    monkeypatch.setattr(pairing, "devices", lambda: [])                  # the list shows claimed pairings only
    monkeypatch.setattr(pairing, "_read", lambda name: [{"id": "u1", "name": "Shop phone", "claimed": None}])
    monkeypatch.setattr(pairing, "revoke", lambda i: rec("revoke")() == 0)
    terminal(True, "n")
    rc, out, _ = run(capsys, ["unpair", "u1"])
    assert rc == 5 and rec.acted == [] and "Unpair Shop phone?" in out
    terminal(True, "y")
    assert run(capsys, ["unpair", "u1"])[0] == 0 and rec.acted == ["revoke"]
    assert run(capsys, ["unpair", "zzz"])[0] == 2                        # still no such id: nothing asked


def test_update_without_root_is_left_to_the_command_even_when_piped(rec, monkeypatch, terminal, capsys, tmp_path):
    """Not root and piped: nothing is asked, so `updates.update` says it needs sudo (exit 3), not exit 2."""
    _update(monkeypatch, rec, tmp_path)
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    terminal(False)
    assert cli._confirm_update({}, rollback=False, yes=False) is None
    assert cli._confirm_update({}, rollback=True, yes=False) is None
    assert capsys.readouterr().err == ""


def test_update_that_is_up_to_date_does_not_ask_when_piped(rec, monkeypatch, terminal, capsys, tmp_path):
    argv, _ = _update(monkeypatch, rec, tmp_path)
    monkeypatch.setattr(updates, "check_info", lambda cfg, **k: {"newer": False, "latest": "0.5.1"})
    terminal(False)
    rc, out, err = run(capsys, argv)
    assert rc == 0 and rec.acted == ["update"] and "needs a yes" not in err
