"""The System commands of the command line (06 9.8 to 9.15, 10, 3): config show and set, label-reader, catalog, backup,
web, remote, setup-code, certificate, spoolman, update, uninstall, logs, add, spool, help and the grouped top-level help."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import apply, backup, cli, config, intake, library, modules, output, remote, secret_input, setup_helper
from filament_kit import status as status_rows
from filament_kit.spoolman import SpoolmanError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k, d in (("ETC", "etc"), ("STATE", "state"), ("OPT", "opt"), ("BACKUPS", "bk")):
        monkeypatch.setenv(f"FK_{k}", str(tmp_path / d))
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(cli, "_hub_audit", lambda what: None)       # never the machine's journal
    return tmp_path


def run(capsys, argv):
    """(exit code, standard output, standard error) of `cli.main(argv)`; a SystemExit is its code."""
    try:
        rc = cli.main(argv)
    except SystemExit as e:
        rc = e.code
    got = capsys.readouterr()
    return rc, got.out, got.err


def words(text: str) -> str:
    return " ".join(text.split())


def modules_on(*names, **settings):
    cfg = config.load()
    cfg["modules"] = {n: True for n in names}
    cfg.update(settings)
    config.save(cfg)


# ---------- config show and config set (06 9.8) ----------

def test_config_show_prints_every_group_in_the_menus_order_and_secrets_as_set_or_not_set(capsys):
    modules_on("spoolman", "server", "ai_intake")
    rc, out, _ = run(capsys, ["config", "show"])
    assert rc == 0
    heads = ["Appearance", "General", "Storage locations", "Label Reader", "Backups and restore",
             "Network and addresses", "Web passphrase", "Filament Catalog"]
    at = [out.index(f"\n{h}\n") if h != heads[0] else out.index(h) for h in heads]
    assert at == sorted(at)
    assert re.search(r"^  Theme for new devices +Console$", out, re.M)
    assert re.search(r"^  Anthropic API key +not set$", out, re.M)
    (config.paths().etc / cli.KEY_FILE).write_text("sk-test\n")
    out = run(capsys, ["config", "show"])[1]
    assert re.search(r"^  Anthropic API key +set$", out, re.M) and "sk-test" not in out
    assert all(len(line) < 80 for line in out.splitlines())


def test_config_show_json_has_the_values_by_key_and_the_secrets_as_set(capsys):
    modules_on("spoolman", "server", "ai_intake")
    rc, out, _ = run(capsys, ["config", "show", "--json"])
    got = json.loads(out)
    assert rc == 0 and got["values"]["placement.pla_location"] == config.load()["placement"]["pla_location"]
    assert got["secrets"]["anthropic_key"] == {"set": False}
    assert [g["group"] for g in got["groups"]][:3] == ["Appearance", "General", "Storage locations"]


def test_config_set_saves_one_setting_checked_as_the_menu_checks_it(capsys):
    rc, out, err = run(capsys, ["config", "set", "placement.pla_location", "Shelf B"])
    assert (rc, out, err) == (0, "Saved: PLA rack is Shelf B.\n", "")
    assert config.load()["placement"]["pla_location"] == "Shelf B"
    rc, out, _ = run(capsys, ["config", "set", "placement.pla_location", "Shelf B"])
    assert rc == 0 and out.startswith("Unchanged: PLA rack is Shelf B.")


def test_config_theme_shows_the_theme_for_new_devices_and_needs_no_rights(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    monkeypatch.setattr(cli, "_no_systemd", lambda: False)
    rc, out, err = run(capsys, ["config", "theme"])
    assert (rc, out, err) == (0, "Theme for new devices: Console (dense and technical; the default).\n", "")
    cfg = config.load()
    cfg["appearance"] = {"theme": "palette"}
    config.save(cfg)
    assert run(capsys, ["config", "theme"])[:2] == (0, "Theme for new devices: Palette (colourful and roomy).\n")
    got = json.loads(run(capsys, ["config", "theme", "--json"])[1])
    assert got == {"theme": "palette"}       # the one setting, not every general setting


def test_config_theme_sets_a_theme_in_any_case_and_says_devices_keep_theirs(capsys):
    rc, out, err = run(capsys, ["config", "theme", "WorkBench"])
    assert (rc, out, err) == (0, "Theme for new devices: Workbench (calm cards).\nDevices that already chose a theme keep theirs.\n", "")
    assert config.load()["appearance"]["theme"] == "workbench" and config.look(config.load()) == "workbench"
    rc, out, _ = run(capsys, ["config", "theme", "workbench"])
    assert rc == 0 and out == "Unchanged: Theme for new devices: Workbench (calm cards).\n"
    assert run(capsys, ["config", "theme", "panes"])[0] == 0 and config.look(config.load()) == "panes"


def test_config_theme_an_unknown_name_exits_2_with_the_fix_at_80_columns_and_changes_nothing(capsys):
    before = config.load()
    rc, out, err = run(capsys, ["config", "theme", "dark"])
    assert rc == 2 and out == ""
    assert err == ('Error: there is no theme called "dark".\n'
                   "Fix: choose console, workbench, palette or panes. Light and dark are chosen on\n"
                   "     each device, in Settings > Appearance.\n")
    assert all(len(line) <= 79 for line in err.splitlines())
    assert config.load() == before


def test_config_theme_setting_without_rights_asks_for_sudo_and_changes_nothing(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    monkeypatch.setattr(cli, "_no_systemd", lambda: False)
    before = config.load()
    rc, out, err = run(capsys, ["config", "theme", "palette"])
    assert rc == output.NEEDS_SUDO and "config theme palette" in err and config.load() == before


def test_config_set_takes_the_key_of_the_design_for_the_backup_days(capsys):
    assert run(capsys, ["config", "set", "backups.keep_days", "20"])[:2] == (0, "Saved: Nightly backups are kept for 20 days.\n")
    assert config.load()["backup"]["keep_days"] == 20


def test_config_set_a_wrong_value_changes_nothing_and_exits_2(capsys):
    before = config.load()
    rc, out, err = run(capsys, ["config", "set", "placement.box_count", "two"])
    assert rc == 2 and out == "" and err.startswith("Error: the number of storage boxes is a whole number, 0 or more.")
    assert config.load() == before


def test_config_set_an_unknown_key_exits_2_and_lists_the_keys(capsys):
    rc, out, err = run(capsys, ["config", "set", "nosuch", "x"])
    assert rc == 2 and out == "" and '"nosuch"' in err
    assert "placement.pla_location" in words(err) and "backups.keep_days" in words(err)


def test_config_set_refuses_a_secret_and_names_where_to_set_it(capsys):
    rc, out, err = run(capsys, ["config", "set", "anthropic_key", "sk-x"])
    assert rc == 2 and "the Anthropic API key is a secret." in err and "config, Label Reader." in words(err)
    assert not (config.paths().etc / cli.KEY_FILE).exists()


def test_config_set_a_setting_that_restarts_the_hub_shows_the_restart(capsys, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_no_systemd", lambda: False)
    monkeypatch.setattr(cli, "_restart_service", lambda: seen.append("restart"))
    rc, out, _ = run(capsys, ["config", "set", "reads_per_day", "50"])
    assert rc == 0 and seen == ["restart"] and "Saved: Reads per day is 50." in out and "The Hub is back." in out


def test_config_set_a_choice_by_its_word_and_a_bool_by_on_or_off(capsys):
    assert run(capsys, ["config", "set", "appearance.theme", "Workbench"])[0] == 0
    assert config.load()["appearance"]["theme"] == "workbench"
    modules_on("spoolman", "server", "web")
    assert run(capsys, ["config", "set", "web.printer_changes", "on"])[:2] == (
        0, "Saved: Allow printer changes from the public address is on.\n")
    assert config.load()["web"]["printer_changes"] is True


def test_config_set_needs_root(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_no_systemd", lambda: False)
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert run(capsys, ["config", "set", "model", "x"])[0] == 3


def test_a_json_menu_points_at_config_show(capsys):
    rc, out, err = run(capsys, ["config", "--json"])
    assert rc == 2 and "config show --json" in err


# ---------- label-reader (06 9.9) ----------

def test_label_reader_status_with_no_engine_says_how_to_turn_one_on(capsys):
    modules_on("spoolman", "server")
    rc, out, err = run(capsys, ["label-reader", "status"])
    assert rc == 1 and "the Label Reader is off" in err and "features on label-reader" in words(err)


def test_label_reader_status_prints_the_engine_order_before_the_groups_rows(capsys, monkeypatch):
    modules_on("spoolman", "server", "local_intake")
    monkeypatch.setattr(status_rows, "local_reader_rows", lambda cfg=None: iter(
        [status_rows.Row(status_rows.OK, "local label reader answering at http://192.0.2.10:7915"),
         status_rows.Row(status_rows.INFO, "label reading: the local reader")]))
    rc, out, _ = run(capsys, ["label-reader", "status"])
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "Label Reader" and "on" in lines[1] and "Engine order: On this Hub" in lines[1]
    assert "answering at http://192.0.2.10:7915" in out and "label reading:" not in out


def test_the_old_local_intake_status_is_the_same_command(capsys, monkeypatch):
    modules_on("spoolman", "server", "local_intake")
    monkeypatch.setattr(status_rows, "local_reader_rows", lambda cfg=None: iter([]))
    assert run(capsys, ["label-reader", "status"]) == run(capsys, ["local-intake", "status"])


def test_label_reader_test_with_an_engine_that_is_off_says_so_with_its_fix(capsys, tmp_path):
    modules_on("spoolman", "server", "local_intake")
    rc, out, err = run(capsys, ["label-reader", "test", str(tmp_path / "a.jpg"), "--engine", "cloud"])
    assert rc == 1 and "Cloud (Claude) is not installed." in err and "features on label-reader" in words(err)


def test_label_reader_test_a_missing_photo_exits_2(capsys, tmp_path):
    modules_on("spoolman", "server", "local_intake")
    rc, out, err = run(capsys, ["label-reader", "test", str(tmp_path / "nope.jpg")])
    assert rc == 2 and "there is no readable file at" in words(err)


def _read(reader="local", **item):
    it = {"vendor": "Polymaker", "name": "PolyTerra PLA Charcoal Black", "material": "PLA", "color_hex": "2B2B2E",
          "color_name": "black", "net": 1000, "price_per_kg": None,
          "confidence_levels": {"vendor": "high", "name": "high", "material": "high", "color_hex": "medium",
                                "net": "high", "price_per_kg": "not_on_label"}, **item}
    return {"items": [it], "reader": reader, "tier": "cpu" if reader == "local" else None, "questions": []}


def test_label_reader_test_prints_the_fields_with_their_confidence_and_adds_nothing(capsys, monkeypatch, tmp_path):
    modules_on("spoolman", "server", "local_intake")
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"x")
    monkeypatch.setattr(intake, "check_photos", lambda photos: [b"x"])
    monkeypatch.setattr(intake, "_call", lambda sm, images, hint, tag, client, **k: _read())
    rc, out, err = run(capsys, ["label-reader", "test", str(photo)])
    assert rc == 0 and err == ""
    assert "Read by On this Hub (tier: cpu) in 0 s. Nothing was added." in out
    row = {m[0]: m[1] for m in re.findall(r"^  (\S[\w ]+?) {2,}(.*?)$", out, re.M)}
    assert row["Brand"].startswith("Polymaker") and row["Brand"].endswith("high")
    assert row["Colour"].startswith("#2B2B2E (black)") and row["Colour"].endswith("medium")
    assert row["Price per kg"].startswith("(empty)") and row["Price per kg"].endswith("not on label")
    assert all(len(line) < 80 for line in out.splitlines())


def test_a_cloud_read_says_how_many_of_the_days_reads_it_used(capsys, monkeypatch, tmp_path):
    modules_on("spoolman", "server", "ai_intake")
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"x")
    monkeypatch.setattr(intake, "check_photos", lambda photos: [b"x"])
    monkeypatch.setattr(cli, "_history_charge", lambda: (lambda: None))

    def call(sm, images, hint, tag, client, *, readers, charge):
        charge()
        return _read("cloud")
    monkeypatch.setattr(intake, "_call", call)
    rc, out, err = run(capsys, ["label-reader", "test", str(photo), "--engine", "cloud"])
    assert rc == 0 and "Read by Cloud (Claude) in" in out
    assert f"Note: this used 1 of today's {config.load()['reads_per_day']} reads." in err


# ---------- catalog (06 9.11) ----------

def test_catalog_status_says_when_it_is_not_downloaded_with_the_fix(capsys, monkeypatch):
    monkeypatch.setattr(library, "status", lambda: {"version": 0, "source": "none", "local": 0, "url": "https://x.example/l",
                                                    "last_check": None, "skipped": None})
    rc, out, _ = run(capsys, ["catalog", "status"])
    assert rc == 0 and out.splitlines()[:2] == ["The Filament Catalog is not downloaded yet.",
                                                "Fix: sudo spoolwarden catalog update"]
    assert "Last check: never." in out and "Source: https://x.example/l" in out


def test_the_old_library_spelling_is_the_same_command(capsys):
    assert run(capsys, ["library", "status"]) == run(capsys, ["catalog", "status"])


def test_catalog_status_names_a_failed_check(capsys, monkeypatch):
    monkeypatch.setattr(library, "status", lambda: {"version": 4, "source": "updated", "local": 3, "url": "https://x.example/l",
                                                    "last_check": {"at": "2026-11-12 03:10", "ok": False, "error": "no route"},
                                                    "skipped": None})
    out = run(capsys, ["catalog", "status"])[1]
    assert out.startswith("Filament Catalog version 4 (signed release), 3 local additions.\n")
    assert "Last check 2026-11-12 03:10: failed: no route." in out


def test_catalog_token_remove_asks_then_removes(capsys, monkeypatch):
    removed = []
    monkeypatch.setattr(library, "remove_token", lambda: removed.append(1) or True)
    monkeypatch.setattr(output, "terminal", lambda: False)
    rc, out, err = run(capsys, ["catalog", "token", "--remove"])
    assert rc == 2 and removed == [] and "needs a yes" in err
    rc, out, _ = run(capsys, ["catalog", "token", "--remove", "--yes"])
    assert rc == 0 and removed == [1] and out == "Removed the Catalog token.\n"


def test_catalog_token_is_typed_hidden_and_saved(capsys, monkeypatch):
    saved = []
    monkeypatch.setattr(secret_input, "ask", lambda prompt="": "ghp_abc123")
    monkeypatch.setattr(library, "write_token", lambda t: saved.append(t))
    rc, out, _ = run(capsys, ["catalog", "token"])
    assert rc == 0 and saved == ["ghp_abc123"] and out == "Saved the catalog token.\n"
    assert run(capsys, ["catalog", "token", "--json"])[0] == 2         # --json does not ask


def test_catalog_add_a_missing_file_exits_2_with_the_fix(capsys, tmp_path):
    rc, out, err = run(capsys, ["catalog", "add", str(tmp_path / "none.json")])
    assert rc == 2 and "there is no readable file at" in words(err)
    assert "give the path of one catalog entry as a JSON file." in words(err)


def test_catalog_adopt_says_what_it_took_over(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(library, "adopt", lambda folder: 3)
    rc, out, _ = run(capsys, ["catalog", "adopt", str(tmp_path)])
    assert rc == 0 and words(out).startswith("Took over the catalog in ") and words(out).endswith("0 local additions.")


# ---------- backup (06 9.10) ----------

def _entry(name, kind, at=1700000000.0, size=4812 * 1024):
    return backup.Entry(name, name, size, at, kind)


def test_backup_list_names_the_kinds_in_the_hub_pages_words_and_the_folder(capsys, monkeypatch):
    monkeypatch.setattr(backup, "listing", lambda folder=None: [_entry("a.zip", "daily"), _entry("b.zip", "made"),
                                                                _entry("c.zip", "pre-restore")])
    rc, out, _ = run(capsys, ["backup", "list"])
    assert rc == 0 and out.startswith("Nightly backups are kept 14 days.\n\n")
    assert re.search(r"nightly +4,812 KiB +a\.zip", out) and "made here" in out and "before a restore" in out
    assert words(out).endswith(f"Folder: {backup.backups_dir()}")
    assert [line.split()[0] for line in out.splitlines()[2:3]] == ["MADE"]


def test_backup_list_with_none_says_how_to_make_one(capsys, monkeypatch):
    monkeypatch.setattr(backup, "listing", lambda folder=None: [])
    rc, out, _ = run(capsys, ["backup", "list"])
    assert rc == 0 and words(out) == f"No backups in {backup.backups_dir()} yet. Back up now: sudo spoolwarden backup create"


def test_backup_keep_saves_the_days_as_the_hub_page_does(capsys):
    rc, out, _ = run(capsys, ["backup", "keep", "21"])
    assert (rc, out) == (0, "Backups are kept for 21 days.\n") and config.load()["backup"]["keep_days"] == 21
    rc, out, err = run(capsys, ["backup", "keep", "0"])
    assert rc == 2 and "days must be a whole number from 1 to 365" in err


def test_backup_create_says_where_and_that_the_zip_is_not_encrypted(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "create", lambda dest=None, **k: tmp_path / "bk" / "backup.zip")
    rc, out, err = run(capsys, ["backup", "create"])
    assert rc == 0 and words(out).startswith("Backup written: ") and out.rstrip().endswith("backup.zip")
    assert "Note: the zip is not encrypted and holds the setup secrets: store it somewhere safe." in words(err)


def test_restore_done_is_a_done_row(capsys):
    cli._restore_out("Restored. The Hub is back.")
    assert re.search(r"done +Restored\. The Hub is back\.", capsys.readouterr().out)


# ---------- web, remote, setup-code, certificate, spoolman (06 9.12) ----------

def test_remote_with_the_feature_off_says_so_for_both_commands(capsys):
    modules_on("spoolman", "server")
    for argv in (["remote", "get-certificate", "--yes"], ["remote", "issue", "--yes"], ["remote", "firewall"]):
        rc, out, err = run(capsys, argv)
        assert rc == 1 and err.startswith("Error: Remote access is off.") and "features on remote" in words(err)


def test_remote_get_certificate_failure_is_a_failed_row_with_its_fix(capsys, monkeypatch):
    cfg = {"modules": {"server": True, "web": True, "remote": True}}
    monkeypatch.setattr(remote, "_is_root", lambda: True)
    monkeypatch.setattr(remote, "settings", lambda c: {"hostname": "hub.example", "email": ""})

    def fail(cmd):
        raise subprocess.CalledProcessError(1, cmd)
    assert remote.issue(cfg, run=fail) == 1
    seen = capsys.readouterr()
    assert "failed" in seen.out and "The certificate was not issued:" in seen.out
    assert "hub.example points at this Hub and port 80 reaches it" in words(seen.out)
    assert "Note: certbot listens on port 80 of this Hub now." in words(seen.err)


def test_remote_firewall_starts_with_the_sentence_that_nothing_is_changed(capsys, monkeypatch):
    modules_on("spoolman", "server", "web", "remote")
    monkeypatch.setattr(remote, "settings", lambda cfg: {})
    monkeypatch.setattr(remote, "firewall_text", lambda s, r: "RULES")
    rc, out, _ = run(capsys, ["remote", "firewall"])
    assert rc == 0 and out.startswith("Spoolwarden never changes your firewall or router. These are the rules to add:\n")
    assert out.rstrip().endswith("RULES")


def test_setup_code_without_a_terminal_shows_the_address_and_says_where_the_code_is(capsys, monkeypatch):
    monkeypatch.setattr(apply, "_tty", lambda: False)
    rc, out, err = run(capsys, ["setup-code"])
    assert rc == 0 and out.startswith("Open https://") and "setup code" not in out
    assert "Note: the setup code is shown at a terminal only." in words(err)


def test_setup_code_revoke_trusted_says_how_many_and_what_each_needs(capsys, monkeypatch):
    from filament_kit import trusted
    monkeypatch.setattr(trusted, "revoke_all", lambda: 2)
    rc, out, _ = run(capsys, ["setup-code", "--revoke-trusted", "--yes"])
    assert "2 trusted computers revoked. Each needs the setup code again." in out


def test_certificate_makes_one_once_and_prints_the_fingerprint_in_groups(capsys):
    rc, out, _ = run(capsys, ["certificate"])
    lines = out.splitlines()
    assert rc == 0 and lines[:2] == ["Made a new certificate.", "Fingerprint:"] and len(lines) == 4
    assert all(len(g) == 4 for line in lines[2:] for g in line.split()) and len(lines[2].split()) == 8
    rc, again, _ = run(capsys, ["certificate"])
    assert again.splitlines()[0] == "Certificate present." and again.splitlines()[1:] == lines[1:]
    assert run(capsys, ["cert"]) == (0, again, "")                      # the old spelling


def test_certificate_json_has_the_fingerprint(capsys):
    got = json.loads(run(capsys, ["certificate", "--json"])[1])
    assert got["ok"] is True and got["made"] is True and re.fullmatch(r"[0-9a-f]{64}", got["fingerprint"], re.I)


class _Spoolman:
    answers = True

    def __init__(self, url, timeout=None):
        self.url = url

    def ping(self):
        if not self.answers:
            raise SpoolmanError("connection refused")
        return "0.22"

    def ensure_fields(self):
        return ["nfc_id", "tag_uid"]


def test_spoolman_fields_says_which_fields_it_added(capsys, monkeypatch):
    monkeypatch.setattr(cli, "Spoolman", _Spoolman)
    rc, out, _ = run(capsys, ["spoolman", "fields"])
    assert (rc, out) == (0, "Spoolman: added the kit's extra fields: nfc_id, tag_uid.\n")
    assert run(capsys, ["ensure-fields"])[:2] == (0, out)                # the old spelling


def test_spoolman_address_shows_the_one_in_use(capsys):
    cfg = config.load()
    rc, out, _ = run(capsys, ["spoolman", "address"])
    assert (rc, out) == (0, f"Spoolman in use: {cfg['spoolman_url']}.\n")


def test_spoolman_address_checks_the_address_first_and_changes_nothing_when_nothing_answers(capsys, monkeypatch):
    modules_on("server")
    monkeypatch.setattr(cli, "Spoolman", _Spoolman)
    monkeypatch.setattr(cli, "_run_apply", lambda **k: 0)
    before = config.load()
    _Spoolman.answers = False
    try:
        rc, out, err = run(capsys, ["spoolman", "address", "http://spoolman.example:7912"])
    finally:
        _Spoolman.answers = True
    assert rc == 1 and "nothing was changed: no Spoolman answered at that address" in words(err)
    assert config.load() == before
    rc, out, _ = run(capsys, ["spoolman", "address", "http://spoolman.example:7912"])
    assert rc == 0 and "Saved. The kit now uses the Spoolman at http://spoolman.example:7912." in out
    assert config.load()["spoolman_url"] == "http://spoolman.example:7912"


def test_web_passphrase_ends_with_one_short_line(capsys, monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.setattr(secret_input, "ask", lambda prompt="": "a long enough passphrase")
    monkeypatch.setattr(cli.shutil, "chown", lambda *a, **k: None)
    rc, out, _ = run(capsys, ["web", "passphrase"])
    assert (rc, out) == (0, "Passphrase saved.\n")


# ---------- update and uninstall (06 9.13) ----------

def test_the_removal_runs_with_its_lines_indented_and_reports_its_last_line(capsys):
    script = [sys.executable, "-c", "print('stopping'); print('removing files'); raise SystemExit(0)"]
    rc, last = cli._run_removal(script, None)
    seen = capsys.readouterr()
    assert (rc, last) == (0, "removing files")
    assert seen.out.splitlines() == ["    stopping", "    removing files"]
    rc, last = cli._run_removal([sys.executable, "-c", "print('stopped here'); raise SystemExit(4)"], None)
    assert (rc, last) == (4, "stopped here")


def test_uninstall_ends_with_one_sentence_or_a_failed_row_naming_the_last_line(capsys, monkeypatch, tmp_path):
    from filament_kit import release, updates
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "uninstall.sh").write_text("# x\n")
    monkeypatch.setattr(cli, "_kept_release", lambda: ("1.2.0", tmp_path / "1.2.0.tar.gz"))
    monkeypatch.setattr(updates, "current_version", lambda: "1.2.0")
    monkeypatch.setattr(release, "extract", lambda tarball, ver, work: kept)
    monkeypatch.setattr(cli, "_run_removal", lambda cmd, stdin_file: (0, "done"))
    assert run(capsys, ["uninstall", "--yes"])[:2] == (0, "filament-kit is removed from this machine.\n")
    monkeypatch.setattr(cli, "_run_removal", lambda cmd, stdin_file: (1, "cannot stop the service."))
    rc, out, _ = run(capsys, ["uninstall", "--yes"])
    assert rc == 1 and "The removal stopped: cannot stop the service." in out and "failed" in out


# ---------- logs (06 9.14) ----------

def _units(monkeypatch, text="", truncated=False):
    monkeypatch.setattr(setup_helper, "journal_units", lambda cfg: ["filament-kit-web.service", "filament-kit.service"])
    asked = []

    def journal(req):
        asked.append(req)
        return {"unit": req["unit"], "text": text, "truncated": truncated}
    monkeypatch.setattr(setup_helper, "_journal", journal)
    return asked


def test_logs_default_is_the_hubs_service_100_lines(capsys, monkeypatch):
    asked = _units(monkeypatch, "2026-11-12T03:00:00 hub filament-kit[1]: started\n")
    rc, out, _ = run(capsys, ["logs"])
    assert rc == 0 and asked == [{"unit": "filament-kit.service", "lines": 100}]
    assert out == "2026-11-12T03:00:00 hub filament-kit[1]: started\n"


def test_logs_takes_a_service_by_its_name_and_the_lines(capsys, monkeypatch):
    asked = _units(monkeypatch, "x\n")
    assert run(capsys, ["logs", "filament-kit-web", "--lines", "50"])[0] == 0
    assert asked == [{"unit": "filament-kit-web.service", "lines": 50}]
    assert run(capsys, ["logs", "--lines", "7"])[0] == 2                      # 50, 100 or 200 only


def test_logs_with_no_match_lists_the_services(capsys, monkeypatch):
    _units(monkeypatch)
    rc, out, err = run(capsys, ["logs", "nosuch"])
    assert rc == 2 and '"nosuch" is not one of the services the switched-on features run.' in words(err)
    assert "name one of: filament-kit-web, filament-kit." in words(err)


def test_logs_empty_and_cut(capsys, monkeypatch):
    _units(monkeypatch, "")
    assert run(capsys, ["logs"])[:2] == (0, "Nothing logged.\n")
    _units(monkeypatch, "a\nb\n", truncated=True)
    out = run(capsys, ["logs"])[1]
    assert "Only the last 100 lines are shown." in out and "Fix: for more, run journalctl -u filament-kit" in words(out)


def test_logs_need_root_and_the_json_has_the_hubs_shape(capsys, monkeypatch):
    _units(monkeypatch, "a\n")
    got = json.loads(run(capsys, ["logs", "--json"])[1])
    assert got == {"unit": "filament-kit.service", "text": "a\n", "truncated": False}
    monkeypatch.setattr(cli, "_no_systemd", lambda: False)
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert run(capsys, ["logs"])[0] == 3


# ---------- add and spool (06 10) ----------

def test_add_and_spool_say_where_with_the_address(capsys):
    rc, out, _ = run(capsys, ["add"])
    assert rc == 0 and out.startswith("Add spools in the web app, app or Weigh Station:") and "/intake" in out
    rc, out, _ = run(capsys, ["spool"])
    assert rc == 0 and out.startswith("Spools are opened and tagged in the web app or app:") and out.rstrip().endswith("/intake")


def test_the_address_goes_on_the_next_line_when_the_two_do_not_fit(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    out = run(capsys, ["add"])[1]
    lines = out.splitlines()
    assert len(lines) == 2 and lines[1].startswith("https://") and lines[1].endswith("/intake")


def test_add_and_spool_json_is_the_pointer_document(capsys):
    for argv in (["add", "--json"], ["spool", "--json"]):
        got = json.loads(run(capsys, argv)[1])
        assert got["available"] is False and got["where"] == "web app" and got["url"].endswith("/intake")


# ---------- help (06 3) ----------

def test_no_command_prints_the_grouped_help_that_help_and_dash_h_print(capsys):
    rc, bare, _ = run(capsys, [])
    assert rc == 0
    assert run(capsys, ["help"])[:2] == (0, bare) and run(capsys, ["-h"])[:2] == (0, bare)
    lines = bare.splitlines()
    assert lines[0].startswith("Spoolwarden on this Hub.") and "Usage: spoolwarden <command> [options]" in lines[1]
    heads = [i for i, line in enumerate(lines) if line in ("Everyday", "System")]
    assert [lines[i] for i in heads] == ["Everyday", "System"]
    assert "  catalog          Filament Catalog: status, update, roll back, add" in lines
    assert lines[-2].startswith("Every command: -h  --json  -q/--quiet  -y/--yes")
    for old in ("modules", "profiles", "library", "intake", "unpair", "ensure-fields", "local-intake", "reader "):
        assert not any(line.startswith(f"  {old}") for line in lines), old


def test_help_for_a_command_is_its_own_usage(capsys):
    rc, out, _ = run(capsys, ["help", "catalog"])
    assert rc == 0 and out.startswith("usage: spoolwarden catalog") and "token" in out
    rc, out, err = run(capsys, ["help", "nosuch"])
    assert rc == 2 and 'there is no command called "nosuch"' in err


def test_help_aliases_lists_every_old_spelling_with_the_new_one(capsys):
    rc, out, _ = run(capsys, ["help", "aliases"])
    assert rc == 0 and re.search(r"^ +unpair +(->|→) +devices list$", out, re.M) and re.search(r"^ +cert +(->|→) +certificate$", out, re.M)
    got = json.loads(run(capsys, ["help", "aliases", "--json"])[1])
    assert {"old": "library status, update, rollback, adopt, add", "new": "catalog status, update, rollback, adopt, add"} in got["aliases"]
    assert all(len(line) <= 79 for line in out.splitlines())


# Commands of 06 3.2 this program does not have: they come with their own steps or went away with the migrations.
NOT_HERE = ("label-reader corrections", "migrate-ops", "migrate-scanner")


def _design_commands() -> list[str]:
    text = (ROOT / "docs" / "design" / "06-command-line.md").read_text(encoding="utf-8")
    table = text[text.index("### 3.2 Every command"):text.index("## 4. Old and new spellings")]
    found = []
    for line in table.splitlines():
        m = re.match(r"\| `([^`]+)`", line)
        if m:
            found.append(re.split(r" [\[<(|-]", m.group(1))[0].strip())
    return found


# The three rows this program words otherwise until their steps: the product name (the rename steps) and pair --no-wait.
_RENAME_STEPS = {
    r"| `pair [--slicer-sync \| --weigh-station] [--text]` | Pairing code, QR and fingerprint | Pair a phone / Link for the Slicer Sync / Link for the Weigh Station |":
    r"| `pair [--slicer-sync \| --weigh-station] [--text] [--no-wait]` | Pairing code, QR and fingerprint | Pair a phone / Link for the Slicer Sync / Link for the Weigh Station |",
}


def _design_rows() -> list[str]:
    text = (ROOT / "docs" / "design" / "06-command-line.md").read_text(encoding="utf-8")
    table = text[text.index("### 3.2 Every command"):text.index("## 4. Old and new spellings")]
    # the design's own section references ("(9.2)", "(section 10)") are left out of the printed help (design 11:55)
    return [re.sub(r" \((?:section )?\d+(?:\.\d+)?\)", "", ln.strip()) for ln in table.splitlines()
            if re.match(r"\| `", ln) and not ln[3:].startswith(NOT_HERE)]


def _cells(row: str) -> list[str]:
    return re.split(r" \| ", row.strip()[2:-2])      # the escaped pipes of a command (" \| ") do not split


def _catalogue_place(cell: str) -> str:
    en = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))
    return re.sub(r"\{(\w+)\}", lambda m: en[m.group(1)], cell)


def test_help_place_names_come_from_the_string_catalogue(capsys):
    en = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))
    names = {v for v in en.values() if isinstance(v, str)}
    keyed = 0
    for command, _what, place in cli._COMMAND_TABLE:
        if "{" in place:
            keyed += 1
            assert all(k in en for k in re.findall(r"\{(\w+)\}", place)), command
        else:                                       # a description, never a hand-typed Hub name
            assert place not in names, f"{command}: {place!r} is a catalogue text, write it as {{key}}"
    assert keyed > 60
    rc, md, _ = run(capsys, ["help", "--markdown"])
    assert rc == 0
    for command, _what, place in cli._COMMAND_TABLE:
        assert _cells(next(r for r in md.splitlines() if r.startswith(f"| {command} |")))[2] == _catalogue_place(place)
    assert "| Bring back deleted presets |" in md and "| Show what would change |" in md
    assert "| Restore deleted presets |" not in md and "| Show what would be accepted |" not in md


def test_help_markdown_lists_every_command_of_the_design(capsys):
    rc, md, _ = run(capsys, ["help", "--markdown"])
    wanted = [c for c in _design_commands() if not c.startswith(NOT_HERE)]
    assert rc == 0 and len(wanted) > 70
    rows = md.splitlines()
    for command in wanted:
        assert f"| `{command}" in md, command
    helped = {_cells(r)[0]: _cells(r) for r in rows[2:]}
    raw = {c: p for c, _w, p in cli._COMMAND_TABLE}
    for row in _design_rows():                      # every row: the command and what it does whole; the place as below
        want = _cells(_RENAME_STEPS.get(row, row))
        got = helped[want[0]]
        assert got[:2] == want[:2], row
        # a place that names a Hub button or section is the catalogue text of the key the Hub page uses (design amends 06 3.2)
        assert got[2] == (_catalogue_place(raw[want[0]]) if "{" in raw[want[0]] else want[2]), row
    assert md.splitlines()[:2] == ["| Command | What it does | Hub page place |", "| --- | --- | --- |"]
    assert not any(f"| `{c}" in md for c in NOT_HERE)
    assert not re.search(r"\((?:section )?\d+(?:\.\d+)?\)", md), "a design section number in the help"


def test_every_command_the_help_lists_is_a_command_of_the_parser(capsys):
    for _group, items in cli._HELP_GROUPS:
        for name, _text in items:
            rc = run(capsys, [name, "-h"])[0]
            assert rc == 0, name


# ---------- AUT-9: width, escapes, plain ASCII and JSON ----------

AUT9 = [["help"], ["help", "aliases"], ["config", "show"], ["certificate"], ["add"], ["spool"], ["catalog", "status"],
        ["logs"], ["backup", "list"], ["spoolman", "address"], ["web", "status"]]


@pytest.mark.parametrize("argv", AUT9, ids=lambda a: " ".join(a))
def test_aut9_the_new_commands_hold_80_columns_no_escape_ascii_and_json(argv, capsys, monkeypatch):
    monkeypatch.setattr(backup, "listing", lambda folder=None: [])
    monkeypatch.setattr(setup_helper, "journal_units", lambda cfg: [])
    monkeypatch.setattr(cli, "_web_health", lambda port: (False, "no"))
    if argv[0] == "logs":
        monkeypatch.setattr(setup_helper, "journal_units", lambda cfg: ["filament-kit.service"])
        monkeypatch.setattr(setup_helper, "_journal", lambda req: {"unit": req["unit"], "text": "", "truncated": False})
    rc, out, err = run(capsys, argv)
    assert rc in (0, 1), err
    long = [x for x in (out + err).splitlines() if len(x) > 79]
    assert all(" " not in x.strip() for x in long), long              # only an address or a path stays whole (06 6.3)
    assert "\x1b" not in out + err                                        # piped: no colour
    rc, plain, _ = run(capsys, ["--plain", *argv])
    assert plain.isascii(), [c for c in plain if not c.isascii()]
    rc, js, _ = run(capsys, [*argv, "--json"])
    assert isinstance(json.loads(js), dict)


# ---------- the rework of S5.8 (brief 69) ----------

REAL_AUDIT = cli._hub_audit


class _Journal:
    """Stands in for the syslog handler on /dev/log: keeps the lines the command writes."""
    made: list = []

    def __init__(self, address=None, **kw):
        import logging
        self.level, self.lines, self.filters = logging.NOTSET, [], []
        _Journal.made.append(self)

    def setFormatter(self, fmt):
        self.fmt = fmt

    def handle(self, record):
        self.lines.append(self.fmt.format(record))

    def acquire(self):
        pass

    def release(self):
        pass


@pytest.fixture
def audit(monkeypatch):
    """The real `_hub_audit` (the autouse fixture stubs it) with the journal handler replaced; returns the lines written."""
    import logging
    import logging.handlers
    _Journal.made = []
    monkeypatch.setattr(cli, "_hub_audit", REAL_AUDIT)
    monkeypatch.setattr(cli, "_journal_address", lambda: "/dev/log")
    monkeypatch.setattr(logging.handlers, "SysLogHandler", _Journal)
    logging.getLogger("filament_kit").handlers[:] = []
    return lambda: [ln for h in _Journal.made for ln in h.lines]


def _heard(lines, what):
    return [ln for ln in lines if f"setup: {what} from " in ln]


def test_config_set_writes_the_hubs_audit_line_and_an_unchanged_value_none(capsys, audit):
    run(capsys, ["config", "set", "placement.pla_location", "Shelf B"])
    assert len(_heard(audit(), "setting placement.pla_location changed")) == 1
    run(capsys, ["config", "set", "placement.pla_location", "Shelf B"])
    assert len(audit()) == 1


def test_spoolman_address_writes_the_hubs_audit_line(capsys, monkeypatch, audit):
    modules_on("server")
    monkeypatch.setattr(cli, "Spoolman", _Spoolman)
    monkeypatch.setattr(cli, "_run_apply", lambda **k: 0)
    run(capsys, ["spoolman", "address", "http://spoolman.example:7912"])
    assert len(_heard(audit(), "Spoolman address changed")) == 1


def test_catalog_token_writes_the_hubs_audit_lines_set_replaced_and_removed(capsys, monkeypatch, audit):
    monkeypatch.setattr(secret_input, "ask", lambda prompt="": "ghp_abc123")
    assert run(capsys, ["catalog", "token"])[0] == 0
    assert run(capsys, ["catalog", "token"])[0] == 0
    assert run(capsys, ["catalog", "token", "--remove", "--yes"])[0] == 0
    assert run(capsys, ["catalog", "token", "--remove", "--yes"])[0] == 0           # none left: nothing to say
    lines = audit()
    assert len(lines) == 3
    for line, what in zip(lines, ("library token set", "library token replaced", "library token removed")):
        assert _heard([line], what), line


def test_catalog_token_remove_says_so_when_none_was_set(capsys):
    rc, out, _ = run(capsys, ["catalog", "token", "--remove", "--yes"])
    assert (rc, out) == (0, "There was no Catalog token to remove.\n")


def test_config_show_json_is_the_hubs_general_values(capsys):
    from filament_kit.setup_console import general_tab
    modules_on("spoolman", "server")                         # the menu hides the reader and voice rows; the Hub's values stay
    cfg = config.load()
    cfg["appearance"] = {"theme": "no-such-theme"}
    config.save(cfg)
    got = json.loads(run(capsys, ["config", "show", "--json"])[1])["values"]
    hub = general_tab._view()["values"]
    assert hub["appearance.theme"] == "console" and got == {**got, **hub}
    for key in ("model", "reads_per_day", "intake.reader", "local_intake.url", "local_intake.tier", "station.tts",
                "web.printer_changes"):
        assert key in got, key
    assert got["intake.history_keep"] is None and "backup.keep_days" in got


def test_config_show_still_prints_the_number_of_records_the_hub_keeps(capsys):
    modules_on("spoolman", "server", "ai_intake")
    assert re.search(r"^  Records kept +\d+$", run(capsys, ["config", "show"])[1], re.M)


def test_the_old_local_intake_test_reads_with_the_local_reader_only(capsys, monkeypatch, tmp_path):
    modules_on("spoolman", "server", "local_intake", "ai_intake")
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(intake, "check_photos", lambda photos: [b"x"])
    monkeypatch.setattr(intake, "_call", lambda sm, images, hint, tag, client, *, readers, charge: seen.append(readers) or _read())
    assert run(capsys, ["local-intake", "test", str(photo)])[0] == 0
    assert run(capsys, ["label-reader", "test", str(photo)])[0] == 0
    assert seen == [["local"], ["local", "cloud"]]


def test_the_old_local_intake_test_help_still_says_no_claude(capsys):
    assert "no Claude" in words(run(capsys, ["local-intake", "-h"])[1])


def test_quiet_spoolman_address_without_an_address_still_shows_the_one_in_use(capsys):
    rc, out, _ = run(capsys, ["--quiet", "spoolman", "address"])
    assert rc == 0 and out == f"Spoolman in use: {config.load()['spoolman_url']}.\n"


def test_help_under_json_is_ok_and_the_help_text(capsys):
    plain = run(capsys, ["help"])[1]
    for argv in (["help", "--json"], ["--json"], ["help", "catalog", "--json"]):
        rc, out, _ = run(capsys, argv)
        got = json.loads(out)
        assert rc == 0 and set(got) == {"ok", "help"} and got["ok"] is True, argv
    assert json.loads(run(capsys, ["help", "--json"])[1])["help"] == plain
    assert json.loads(run(capsys, ["help", "catalog", "--json"])[1])["help"].startswith("usage: spoolwarden catalog")


def test_config_set_the_weigh_station_address_with_the_feature_off_is_refused(capsys, monkeypatch):
    modules_on("spoolman", "server")
    monkeypatch.setattr(cli, "_run_apply", lambda **k: pytest.fail("no apply"))
    before = config.load()
    rc, out, err = run(capsys, ["config", "set", "station.url", "http://station.example:7913"])
    assert rc == 1 and 'the "Weigh Station" Feature is off.' in err and "features on weigh-station" in words(err)
    assert config.load() == before


def test_spoolman_address_a_save_error_is_an_error_line_not_a_traceback(capsys, monkeypatch):
    modules_on("server")
    monkeypatch.setattr(cli, "Spoolman", _Spoolman)
    monkeypatch.setattr(cli, "_run_apply", lambda **k: 0)

    def refuse(cfg):
        raise PermissionError("read-only")
    monkeypatch.setattr(config, "save", refuse)
    rc, out, err = run(capsys, ["spoolman", "address", "http://spoolman.example:7912"])
    assert rc == 1 and err.startswith("Error: nothing was changed: read-only.")


def test_logs_with_no_service_of_the_hub_running_says_it_in_one_sentence(capsys, monkeypatch):
    monkeypatch.setattr(setup_helper, "journal_units", lambda cfg: ["filament-kit-web.service"])
    rc, out, err = run(capsys, ["logs"])
    assert rc == 2 and err.startswith("Error: the Hub's service does not run here.\n")
    assert "run here the" not in err
