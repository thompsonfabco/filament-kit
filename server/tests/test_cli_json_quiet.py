"""S5.3: `--json` and `--quiet` (06 6.8). Every command that prints data or a result is run with `--json`: standard output
is then one JSON document with no escape byte, whatever the command did; an error is `{"ok": false, "error", "fix"}`
beside the usual text on standard error and the usual exit code; a command that would ask stops with exit code 2 unless
it has `--yes`; the menus refuse. `--quiet` drops result lines, notes and progress, and keeps errors, what was asked for
and the questions. Example names only."""
from __future__ import annotations

import json
import types

import pytest

from filament_kit import cli, config, modules, output, pairing, status, updates
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
    monkeypatch.setattr(updates, "check_info", lambda cfg: {"installed": "0.5.2", "latest": "0.5.3", "newer": True,
                                                            "held": None, "notes": "", "going_back": ""})
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


def test_secrets_are_set_true_or_false(capsys):
    got = doc(run(capsys, ["setup-code", "--json"])[1])
    assert got["code"] == {"set": True} and got["url"]


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


def test_help_is_not_wrapped_in_json(capsys):
    rc, out, _ = run(capsys, ["--json", "status", "-h"])
    assert rc == 0 and out.startswith("usage:")


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
