"""S5.3: `--json` and `--quiet` (06 6.8). Every command that prints data or a result is run with `--json`: standard output
is then one JSON document with no escape byte, whatever the command did; an error is `{"ok": false, "error", "fix"}`
beside the usual text on standard error and the usual exit code; a command that would ask stops with exit code 2 unless
it has `--yes`; the menus refuse. `--quiet` drops result lines, notes and progress, and keeps errors, what was asked for
and the questions. Example names only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from filament_kit import apply, cli, config, modules, output, pairing, status, updates
from filament_kit.setup_console import overview
from filament_kit.web import reader as web_reader


@pytest.fixture(autouse=True)
def kit(tmp_path, monkeypatch, spoolman_url):
    """A kit with a fake Spoolman, a certificate and nothing else, run as root and without systemd."""
    for name, folder in (("FK_ETC", "etc"), ("FK_STATE", "state"), ("FK_BACKUPS", "bk"), ("FK_OPT", "opt")):
        monkeypatch.setenv(name, str(tmp_path / folder))
        (tmp_path / folder).mkdir(exist_ok=True)
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    pairing.make_cert("fk-test", ["127.0.0.1"], config.paths().etc)
    cli.Spoolman(spoolman_url).ensure_fields()


def run(capsys, argv):
    """(exit code, standard output, standard error) of `cli.main(argv)`; a SystemExit is its code."""
    try:
        rc = cli.main(argv)
    except SystemExit as e:
        rc = e.code
    got = capsys.readouterr()
    return rc, got.out, got.err


class _Fetcher:
    """The release fetcher of `update --check` with one release and no network."""

    def release(self, repo, version=None):
        return {"version": "99.0.0", "notes": "New things."}


def doc(out: str):
    """The one JSON document in `out`: one line, no escape byte."""
    assert "\x1b" not in out
    assert out.endswith("\n") and out.count("\n") == 1, out
    return json.loads(out)


# ---------- every command that prints data or a result gives one document ----------

def _pair_device(m, tmp_path):
    m.setattr(cli.pairing, "devices", lambda: [{"id": "d1", "name": "Shop phone", "paired": 1762000000.0, "last_seen": 0}])


COMMANDS = [
    ["status"], ["web", "status"], ["local-intake", "status"], ["unpair"], ["backup", "list"], ["library", "status"],
    ["profiles", "status"], ["profiles", "lines"], ["profiles", "apply-updates", "--all", "--dry-run"],
    ["modules", "list"], ["modules", "units"], ["reader", "tokens"], ["reader", "token", "--name", "shop"],
    ["intake", "history"], ["station", "pairing-state"], ["pair", "--text"], ["pair", "--pc"], ["setup-code"],
    ["cert"], ["ensure-fields"], ["remote", "firewall"], ["printer", "report", "01S00C111111111"],
    ["klipper", "set", "nosuch", "--lane-data", "auto"], ["update", "--check"], ["unpair", "nosuch"],
    ["backup", "create"], ["library", "adopt", "nosuch-folder"], ["profiles", "restore-deleted"],
    ["reader", "revoke", "nosuch"], ["uninstall"], ["restore", "nosuch.zip"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=" ".join)
def test_every_json_command_gives_one_document_with_no_escape_byte(capsys, monkeypatch, argv):
    monkeypatch.setattr(updates, "default_fetcher", lambda cfg: _Fetcher())
    rc, out, err = run(capsys, ["--color", "always", *argv, "--json"])
    got = doc(out)
    assert isinstance(got, (dict, list))
    if rc != 0 and isinstance(got, dict) and "ok" in got:
        assert got["ok"] is False and got["error"] and "fix" in got
    if rc == 0 and isinstance(got, dict) and "ok" in got:
        assert got["ok"] is True
    assert "\x1b" not in err                    # --json is plain on standard error too


# ---------- shapes ----------

def test_status_json_is_the_overviews_rows_and_a_summary(capsys):
    cfg = config.load()
    cfg["modules"] = modules.module_map(modules.enabled(cfg) - {"ai_intake"}, cfg)     # the one row the Hub words apart
    config.save(cfg)
    rc, out, _ = run(capsys, ["status", "--json"])
    got = doc(out)
    page = types.SimpleNamespace(client_factory=None, overview_cache=types.SimpleNamespace(get=lambda key, fn: fn()))
    hub = overview._rows(page, None)             # the Hub page's own rows (GET /setup/api/overview)
    assert got["rows"] == hub
    assert set(got["rows"][0]) == {"state", "text", "fix", "action", "group"}
    assert got["summary"] == status.summary_counts(status.Row(r["state"], r["text"]) for r in hub)
    assert rc == (1 if got["summary"]["needs_a_look"] else 0)


def test_a_status_that_needs_a_look_keeps_its_exit_code_with_json(capsys):
    cfg = config.load()
    cfg["spoolman_url"] = "http://127.0.0.1:1"
    config.save(cfg)
    rc, out, _ = run(capsys, ["--json", "status"])
    got = doc(out)
    assert rc == 1 and got["summary"]["needs_a_look"] >= 1
    assert any(r["state"] == "fail" and r["group"] == "Spoolman" and r["fix"] for r in got["rows"])


def test_reader_tokens_json_is_the_hubs_list(capsys):
    store = web_reader.TokenStore()
    store.issue("shop")
    rc, out, _ = run(capsys, ["reader", "tokens", "--json"])
    assert rc == 0 and doc(out) == store.list() and doc(out)[0]["name"] == "shop"
    assert "token" not in doc(out)[0]                    # never a token


def test_the_devices_list_is_the_hubs_shape_with_iso_times(capsys, monkeypatch, tmp_path):
    _pair_device(monkeypatch, tmp_path)
    got = doc(run(capsys, ["unpair", "--json"])[1])
    assert set(got[0]) == {"id", "name", "paired", "last_seen", "built_in"}
    assert got[0]["id"] == "d1" and got[0]["built_in"] is False and got[0]["last_seen"] is None
    assert got[0]["paired"][:4] == "2025" and got[0]["paired"][-6] in "+-" or got[0]["paired"].endswith("Z")


def test_an_action_prints_ok_true_and_its_result(capsys, monkeypatch, tmp_path):
    _pair_device(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.pairing, "revoke", lambda i: True)
    rc, out, _ = run(capsys, ["unpair", "d1", "--yes", "--json"])
    assert rc == 0 and doc(out) == {"ok": True, "message": "Unpaired d1."}


def test_backup_list_has_the_hubs_fields(capsys):
    got = doc(run(capsys, ["backup", "list", "--json"])[1])
    assert set(got) == {"backups", "keep_days", "folder"} and got["backups"] == []


def test_the_json_is_indented_at_a_terminal_and_one_line_otherwise(capsys, monkeypatch):
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)
    out = run(capsys, ["modules", "list", "--json"])[1]
    assert out.startswith('{\n  "modules": [\n    {\n      "name"') and json.loads(out)["setup"]


def test_a_stored_secret_is_set_true(capsys):
    got = doc(run(capsys, ["setup-code", "--json"])[1])
    assert got == {"address": got["address"], "code": {"set": True}} and got["address"]


def test_a_code_the_command_was_asked_to_make_is_printed(capsys):
    from filament_kit import setup_code
    got = doc(run(capsys, ["setup-code", "--new", "--yes", "--json"])[1])
    assert got == {"ok": True, "address": got["address"], "code": setup_code.shown(setup_code.ensure())}
    assert doc(run(capsys, ["setup-code", "--json"])[1])["code"] == {"set": True}      # later it is stored: not shown


def test_a_new_reader_token_and_a_pairing_link_are_printed(capsys):
    got = doc(run(capsys, ["reader", "token", "--name", "shop", "--json"])[1])
    assert got["token"] and "token" not in doc(run(capsys, ["reader", "tokens", "--json"])[1])[0]
    got = doc(run(capsys, ["pair", "--pc", "--json"])[1])
    assert set(got) == {"ok", "code", "link", "fingerprint", "expires"} and got["link"] and got["code"]


def test_update_check_json_is_the_hubs_updates_view(capsys, monkeypatch):
    monkeypatch.setattr(updates, "default_fetcher", lambda cfg: _Fetcher())
    rc, out, _ = run(capsys, ["update", "--check", "--json"])
    got = doc(out)
    assert rc == 0 and got == updates.view(config.load())          # GET /setup/api/updates, from what the check saved
    assert got["latest"] == "99.0.0" and got["notes"] == "New things." and "update_refused" in got


def test_web_status_json_has_the_rows_the_overview_has(capsys):
    cfg = config.load()
    cfg["modules"] = modules.module_map(modules.enabled(cfg) | {"web"}, cfg)
    config.save(cfg)
    assert "web" in modules.enabled(config.load())
    rows = doc(run(capsys, ["web", "status", "--json"])[1])["rows"]
    assert rows and rows == status.row_dicts(status.collect(cfg))[-len(rows):]     # the Overview's own rows for the web module
    assert all(r["group"] == "Hub" for r in rows) and "Web access is on" not in [r["text"] for r in rows]


def test_revoking_trusted_computers_gives_ok_with_json(capsys):
    got = doc(run(capsys, ["setup-code", "--revoke-trusted", "--yes", "--json"])[1])
    assert got["ok"] is True and got["trusted_revoked"] == 0 and got["code"] == {"set": True}


# ---------- errors ----------

def test_an_error_is_the_document_the_text_and_the_exit_code(capsys):
    rc, out, err = run(capsys, ["unpair", "nosuch", "--json"])
    assert rc == output.USAGE and doc(out) == {"ok": False, "error": "no paired device nosuch", "fix": None}
    assert err.startswith("Error: no paired device nosuch")


def test_an_error_with_a_fix_gives_both(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    monkeypatch.delenv("FK_NO_SYSTEMD")
    rc, out, err = run(capsys, ["backup", "list", "--json"])
    got = doc(out)
    assert rc == output.NEEDS_SUDO and got["ok"] is False and got["error"] == "this needs administrator rights."
    assert got["fix"].startswith("run it with sudo:") and "backup list" in got["fix"]
    assert "Fix: run it with sudo:" in err


def test_a_wrong_option_is_a_document_and_exit_code_2(capsys):
    rc, out, err = run(capsys, ["--json", "status", "--nosuch"])
    assert rc == 2 and doc(out)["ok"] is False and "Error:" in err


def test_help_is_a_document_under_json(capsys):
    rc, out, _ = run(capsys, ["--json", "status", "-h"])
    got = doc(out)
    assert rc == 0 and got["ok"] is True and got["help"].startswith("usage:")


def test_a_wrong_color_is_a_document_under_json(capsys):
    rc, out, err = run(capsys, ["--json", "--color", "bogus", "status"])
    got = doc(out)
    assert rc == 2 and got["ok"] is False and "--color takes" in got["error"] and "Error:" in err


# ---------- --json never asks ----------

def test_json_without_yes_stops_with_2_even_at_a_terminal(capsys, monkeypatch):
    _pair_device(monkeypatch, None)
    acted = []
    monkeypatch.setattr(cli.pairing, "revoke", lambda i: acted.append(i) or True)
    monkeypatch.setattr(output, "_is_tty", lambda stream: True)         # a terminal is there; --json still does not ask
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked"))
    rc, out, err = run(capsys, ["unpair", "d1", "--json"])
    assert rc == 2 and acted == []
    got = json.loads(out)                                  # indented: a terminal is there
    assert got["ok"] is False and "needs a yes" in got["error"] and "--yes" in got["fix"]
    assert "Error:" in err and "Fix:" in err


def test_a_question_with_its_own_answers_is_not_asked_under_json(capsys):
    output.configure(json=True)
    assert output.confirm("Go on?", doing="going on", ask=lambda prompt: pytest.fail("asked")) == output.USAGE
    assert output.confirm("Go on?", doing="going on", yes=True, ask=lambda prompt: pytest.fail("asked")) is None
    got = capsys.readouterr()
    assert got.out == "" and "Error: going on needs a yes" in got.err


class _Terminal:
    """Standard input that is a terminal and answers nothing: asking on it is a failure."""

    def isatty(self):
        return True

    def readline(self, *a):
        pytest.fail("asked")

    read = readline


def test_json_does_not_ask_when_standard_input_is_a_terminal(capsys, monkeypatch):
    argv = ["restore", "nosuch.zip"]
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked"))
    rc, out, err = run(capsys, [*argv, "--json"])
    got = json.loads(out)
    assert rc == 2 and got["ok"] is False and "needs a yes" in got["error"] and "[y/N]" not in out + err


def test_a_modules_question_is_not_asked_under_json_at_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked"))
    before = config.load()
    rc, out, err = run(capsys, ["modules", "disable", "server", "--json"])
    got = doc(out)
    assert rc == 1 and got["ok"] is False and "depend on server" in got["error"] and "[y/N]" not in out + err
    assert config.load() == before


def test_a_modules_question_is_not_asked_under_json_at_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked"))
    before = config.load()
    rc, out, err = run(capsys, ["modules", "disable", "server", "--json"])
    got = doc(out)
    assert rc == 1 and got["ok"] is False and "depend on server" in got["error"] and "[y/N]" not in out + err
    assert config.load() == before


def test_a_restore_has_no_word_to_type_under_json(capsys, tmp_path):
    zip_ = tmp_path / "b.zip"
    zip_.write_bytes(b"x")
    rc, out, _ = run(capsys, ["restore", str(zip_), "--json"])
    assert rc == 2 and "needs a yes" in doc(out)["error"]


@pytest.mark.parametrize("argv,fix", [(["config"], "filament-kit config show --json"),
                                      (["modules", "menu"], "filament-kit modules list --json")])
def test_menus_refuse_json(capsys, argv, fix):
    rc, out, err = run(capsys, [*argv, "--json"])
    assert rc == 2 and doc(out)["error"].endswith("is a menu.") and doc(out)["fix"] == "use " + fix
    assert err.startswith("Error:") and "Fix: use " + fix in err


@pytest.mark.parametrize("argv", [["web", "passphrase"], ["printer", "unpin", "01S00C111111111"], ["station", "pair"],
                                  ["printer", "map", "--manual", "01S00C111111111"], ["reader", "setup"]])
def test_commands_that_need_typed_answers_refuse_json(capsys, argv):
    rc, out, _ = run(capsys, [*argv, "--json"])
    assert rc == 2 and "asks for typed answers" in doc(out)["error"] and doc(out)["fix"] == "run it without --json."


# ---------- the switches ----------

def test_the_switches_are_taken_out_wherever_they_stand():
    assert output.extract_switches(["--json", "status", "-q"]) == (["status"], {"json": True, "quiet": True})
    assert output.extract_switches(["backup", "--quiet", "list"]) == (["backup", "list"], {"quiet": True})
    assert output.extract_switches(["intake", "edit", "x", "--", "-q", "--json"]) == (
        ["intake", "edit", "x", "--", "-q", "--json"], {})


# ---------- --quiet ----------

def test_status_quiet_prints_only_the_rows_that_need_a_look(capsys):
    cfg = config.load()
    cfg["spoolman_url"] = "http://127.0.0.1:1"
    config.save(cfg)
    rc, out, _ = run(capsys, ["status", "--quiet"])
    assert rc == 1                                             # the exit code still says there was one
    assert "Spoolman" in out and "needs a look" in out and "Fix:" in out
    assert "filament-kit " not in out.splitlines()[0]          # no header
    assert "OK" not in out and "note" not in out and "need a look" not in out and "need" not in out.splitlines()[-1][:5]
    assert not any(ln.strip().startswith(("+", "o ")) for ln in out.splitlines())      # no row that is fine


def test_status_quiet_with_nothing_to_look_at_prints_nothing(capsys, monkeypatch):
    monkeypatch.setattr(status, "rows", lambda **k: iter([status.Row(status.OK, "fine", group="Hub"),
                                                          status.Row(status.INFO, "a note", group="Hub")]))
    rc, out, err = run(capsys, ["status", "-q"])
    assert (rc, out, err) == (0, "", "")


def test_a_result_line_is_dropped_and_an_error_is_kept(capsys, monkeypatch):
    _pair_device(monkeypatch, None)
    monkeypatch.setattr(cli.pairing, "revoke", lambda i: True)
    assert run(capsys, ["unpair", "d1", "--yes"])[1] == "Unpaired d1.\n"
    rc, out, err = run(capsys, ["unpair", "d1", "--yes", "--quiet"])
    assert (rc, out, err) == (0, "", "")
    rc, out, err = run(capsys, ["unpair", "nosuch", "-q", "--yes"])
    assert rc == 2 and out == "" and err.startswith("Error: no paired device nosuch")


def test_a_list_that_was_asked_for_is_kept(capsys, monkeypatch):
    _pair_device(monkeypatch, None)
    out = run(capsys, ["unpair", "--quiet"])[1]
    assert "Shop phone" in out and out == run(capsys, ["unpair"])[1]


def test_quiet_drops_a_commands_other_result_lines(capsys, monkeypatch, tmp_path):
    rc, out, err = run(capsys, ["ensure-fields"])
    assert out.startswith("Spoolman:") and "backup written" in run(capsys, ["backup", "create"])[1]
    assert run(capsys, ["backup", "create", "--quiet"])[1:] == ("", "")
    assert run(capsys, ["profiles", "restore-deleted", "-q"])[1:] == ("", "")


def test_a_question_is_still_asked_and_shown_with_quiet(capsys, monkeypatch, tmp_path):
    _pair_device(monkeypatch, None)
    monkeypatch.setattr(cli.pairing, "revoke", lambda i: pytest.fail("revoked"))
    monkeypatch.setattr(output, "terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": (print(prompt, end=""), "n")[1])
    rc, out, _ = run(capsys, ["unpair", "d1", "--quiet"])
    assert rc == 5 and "Unpair Shop phone?" in out and out.rstrip().endswith("[y/N]")      # asked; "Nothing changed." dropped
    assert "Nothing changed." not in out


def test_quiet_drops_the_saved_revision_lines(capsys):
    r = {"revisions": [{"n": 2, "changes": [{"field": "net", "old": 1000, "new": 750}], "spool_ids": [4],
                        "filaments": {"from": 1, "to": 2, "created": True, "orphaned": 1}}]}
    output.configure(quiet=True)
    assert cli._say_revision(r) == 0
    assert capsys.readouterr() == ("", "")
    output.configure(quiet=False)
    assert "Saved as revision 2: net 1000 -> 750" in (cli._say_revision(r), capsys.readouterr().out)[1]


def test_quiet_setup_code_new_prints_the_code_and_no_other_line(capsys, monkeypatch):
    monkeypatch.setattr(cli.apply, "_tty", lambda: True)
    full = run(capsys, ["setup-code", "--new", "--yes"])[1]
    assert "setup code:" in full and "The old setup code no longer works." in full
    assert run(capsys, ["setup-code", "--new", "--yes", "--quiet"])[1].count("\n") == 1


def test_a_new_setup_code_is_printed_without_a_terminal_too(capsys, monkeypatch):
    from filament_kit import setup_code
    monkeypatch.setattr(cli.apply, "_tty", lambda: False)
    out = run(capsys, ["setup-code", "--new", "--yes"])[1]
    assert f"setup code: {setup_code.shown(setup_code.ensure())}" in out
    assert "setup code:" not in run(capsys, ["setup-code"])[1]              # a stored one needs a terminal


def test_quiet_drops_the_station_pair_result(capsys, monkeypatch):
    from filament_kit.station import server_api
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(server_api, "parse_link", lambda text: text)
    monkeypatch.setattr(server_api, "pair_with_link",
                        lambda link, confirm: types.SimpleNamespace(status="paired", message="Paired with the kit."))
    assert cli.cmd_station_pair(ask=lambda p: "link") == 0
    assert "Paired with the kit." in capsys.readouterr().out
    output.configure(quiet=True)
    assert cli.cmd_station_pair(ask=lambda p: "link") == 0
    assert capsys.readouterr() == ("", "")


def test_a_failed_or_stopped_flash_prints_no_result_line_with_quiet(capsys, monkeypatch, tmp_path):
    from filament_kit import reader_setup as rs
    monkeypatch.setattr(rs, "find_pio", lambda who=None: "/usr/bin/pio")
    monkeypatch.setattr(rs, "owner", lambda: None)
    monkeypatch.setattr(rs, "is_source", lambda p: True)
    monkeypatch.setattr(rs, "find_readers", lambda: [rs.Reader("/dev/ttyACM0", None, "JTAG")])
    monkeypatch.setattr(cli, "_answers_as_panel", lambda port: False)
    monkeypatch.setattr(rs, "flash", lambda *a, **k: 0)
    secrets = tmp_path / "s.h"
    secrets.write_text("x", encoding="utf-8")
    args = types.SimpleNamespace(name="b", ssid="Home", source=str(tmp_path), port=None, out=None, ota_pubkey=None,
                                 token_file=None, base=None, secrets=str(secrets), buzzer="high", yes=True)

    def stopped(p):
        raise KeyboardInterrupt
    for quiet in (False, True):
        output.configure(quiet=quiet)
        assert cli.cmd_reader_setup(args, ask=lambda p: "y") == 0
        flashed = capsys.readouterr().out
        assert ("Flashed." in flashed) is not quiet
        args.yes = False
        assert cli.cmd_reader_setup(args, ask=stopped) == 1
        assert ("Nothing was flashed." in capsys.readouterr().out) is not quiet
        args.yes = True


def test_an_unhandled_error_under_json_still_gives_the_error_document(capfd, monkeypatch):
    def boom():
        print("half an answer")
        raise RuntimeError("boom")
    monkeypatch.setattr(cli, "cmd_modules_list", boom)
    with pytest.raises(RuntimeError):
        cli.main(["modules", "list", "--json"])
    got = capfd.readouterr()
    assert json.loads(got.out) == {"ok": False, "error": "RuntimeError: boom", "fix": None}


def test_the_redirect_is_not_made_when_standard_error_is_not_open(monkeypatch):
    real_fstat, dup2s = os.fstat, []

    def fstat(fd):
        if fd == 2:
            raise OSError(9, "Bad file descriptor")       # standard error was closed
        return real_fstat(fd)
    output.configure(json=True)
    with monkeypatch.context() as m:                    # only around the call: pytest's own capture uses dup2 too
        m.setattr(os, "fstat", fstat)
        m.setattr(os, "dup2", lambda a, b: dup2s.append((a, b)))
        with output.children_to_stderr():
            pass
    assert dup2s == []


def test_a_note_is_dropped_but_the_old_name_line_is_kept(capsys):
    output.configure(quiet=True)
    output.note("a note")
    output.note("spoolwarden status is called status now", old_name=True)
    err = capsys.readouterr().err
    assert "a note" not in err and err.startswith("Note: spoolwarden status")


def test_a_progress_line_is_not_drawn_with_quiet(capsys, monkeypatch):
    import time
    monkeypatch.setattr(output, "PROGRESS_AFTER", 0.0)
    for quiet in (False, True):
        output.configure(quiet=quiet)
        with output.wait("Checking…"):
            time.sleep(0.4)
        err = capsys.readouterr().err
        assert ("Checking" in err) is (not quiet)


# ---------- what a child program prints goes to standard error ----------

_CHILD = """
import subprocess, sys
sys.path.insert(0, sys.argv[1])
from filament_kit import cli, output

def dispatch(args, **k):
    subprocess.run([sys.executable, "-c", "print('from the child')"], check=True)
    if output.json_mode():
        output.emit({"answer": 1})
    else:
        with output.shown():
            print("what was asked for")
    return 0

cli._dispatch = dispatch
raise SystemExit(cli.main(sys.argv[2:]))
"""


def _child_run(*argv):
    root = str(Path(cli.__file__).resolve().parents[1])
    return subprocess.run([sys.executable, "-c", _CHILD, root, *argv], capture_output=True, text=True, timeout=120)


def test_a_child_cannot_put_a_line_before_the_json_document():
    got = _child_run("ensure-fields", "--json")
    assert got.returncode == 0 and json.loads(got.stdout) == {"answer": 1} and got.stdout.count("\n") == 1
    assert "from the child" in got.stderr


def test_a_child_cannot_print_on_standard_output_under_quiet():
    got = _child_run("ensure-fields", "--quiet")
    assert got.returncode == 0 and got.stdout.strip() == "what was asked for"
    assert "from the child" in got.stderr


def test_a_child_is_not_redirected_without_the_switches():
    got = _child_run("ensure-fields")
    assert got.stdout.split() == ["from", "the", "child", "what", "was", "asked", "for"] and "child" not in got.stderr


@pytest.mark.parametrize("fails", [None, RuntimeError, KeyboardInterrupt])
def test_standard_output_is_put_back_on_every_way_out(capfd, fails):
    output.configure(json=True)
    try:
        with output.children_to_stderr():
            os.write(1, b"inside\n")
            if fails:
                raise fails
    except BaseException as e:
        assert fails and isinstance(e, fails)
    os.write(1, b"after\n")
    got = capfd.readouterr()
    assert got.out == "after\n" and "inside" in got.err
