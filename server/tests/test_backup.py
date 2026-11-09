"""The whole-kit backup zip and its restore (filament_kit/backup.py), the CLI around them and the scripts' parts."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from filament_kit import __version__, backup, cli, config, release, setup_helper

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def kit(tmp_path, monkeypatch):
    """A kit's folders with a little of everything, the Spoolman database, and the backups folder."""
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "backups"))
    monkeypatch.setenv("FK_SPOOLMAN_DB", str(tmp_path / "spoolman" / "spoolman.db"))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(backup, "host", lambda: "kitbox")
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True, "printers": True}
    config.save(cfg)
    etc, state = tmp_path / "etc", tmp_path / "state"
    (etc / "cert.pem").write_text("CERT\n")
    (etc / "key.pem").write_text("KEY\n")
    (state / "devices.json").write_text('[{"id": "d1"}]\n')
    (state / "profiles" / "live" / "system").mkdir(parents=True)
    (state / "profiles" / "live" / "system" / "huge.json").write_text("left out\n")
    (state / "profiles" / "builds").mkdir(parents=True)
    (state / "profiles" / "builds" / "b1.tmp").write_text("half\n")
    (state / "profiles" / "builds" / "b2.json").write_text("kept\n")
    (state / "library" / "versions").mkdir(parents=True)
    (state / "library" / "versions" / "v3.tar.gz").write_text("old\n")
    web = tmp_path / "state-web"
    web.mkdir()
    (web / "oauth.json").write_text("{}\n")
    station = tmp_path / "etc-station"
    station.mkdir()
    (station / "server.json").write_text('{"ips": ["192.0.2.5"]}\n')
    (tmp_path / "spoolman").mkdir()
    db = sqlite3.connect(tmp_path / "spoolman" / "spoolman.db")
    db.execute("create table spool (id integer, name text)")
    db.execute("insert into spool values (1, 'E2E PLA')")
    db.commit()
    db.close()
    return tmp_path


class Runner:
    def __init__(self, rc=0):
        self.cmds, self.rc = [], rc

    def __call__(self, cmd):
        self.cmds.append(cmd)
        return self.rc if cmd[:3] == [backup.WRAPPER, "modules", "apply"] else 0


def _spools(kit) -> list:
    db = sqlite3.connect(kit / "spoolman" / "spoolman.db")
    try:
        return db.execute("select id, name from spool").fetchall()
    finally:
        db.close()


def _rewrite(src: Path, dst: Path, change) -> None:
    """A copy of the zip with `change(name, data) -> data or None (drop)` applied to each entry."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for i in zin.infolist():
            data = change(i.filename, zin.read(i))
            if data is not None:
                zout.writestr(i.filename, data)


# ---------------------------------------------------------------- the zip

def test_the_zip_is_named_and_holds_what_a_restore_needs(kit):
    z = backup.create(now=1762700000.0)
    assert backup.NAME.fullmatch(z.name) and z.name.startswith("filament-kit-backup-kitbox-") and z.name.endswith(
        f"-v{__version__}.zip")
    assert z.parent == kit / "backups" and not list(z.parent.glob("*.part"))
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
        assert zf.testzip() is None
    assert {"manifest.xml", "spoolman/spoolman.db", "files/etc/filament-kit/config.json",
            "files/etc/filament-kit/key.pem", "files/var/lib/filament-kit/devices.json",
            "files/var/lib/filament-kit/profiles/builds/b2.json", "files/var/lib/filament-kit-web/oauth.json",
            "files/etc/filament-kit-station/server.json"} <= names
    for left_out in ("profiles/live/system/huge.json", "profiles/builds/b1.tmp", "library/versions/v3.tar.gz"):
        assert f"files/var/lib/filament-kit/{left_out}" not in names
    m = backup.verify(z)
    assert m.kit == __version__ and m.host == "kitbox" and m.modules == ["printers", "server", "spoolman"]
    assert m.spoolman is not None and m.summary()["files"] == len(m.files)


def test_a_second_backup_in_the_same_minute_gets_its_own_name(kit):
    assert backup.create(now=1762700000.0) != backup.create(now=1762700000.0)


def test_the_page_upload_is_left_out(kit):
    backup.uploaded().parent.mkdir(parents=True)
    backup.uploaded().write_bytes(b"PK")
    with zipfile.ZipFile(backup.create()) as zf:
        assert not [n for n in zf.namelist() if backup.UPLOAD in n]


@pytest.mark.parametrize("change,why", [
    (lambda n, d: d + b"x" if n.endswith("devices.json") else d, "damaged or changed"),
    (lambda n, d: None if n.endswith("devices.json") else d, "missing"),
    (lambda n, d: d.replace(b'path="devices.json"', b'path="../devices.json"') if n == "manifest.xml" else d,
     "outside its folder"),
    (lambda n, d: d.replace(b'root="var/lib/filament-kit"', b'root="etc/shadow"', 1) if n == "manifest.xml" else d,
     "outside the kit's folders"),
    (lambda n, d: None if n == "manifest.xml" else d, "no manifest.xml"),
    (lambda n, d: d.replace(b'format="1"', b'format="9"') if n == "manifest.xml" else d, "format"),
])
def test_a_changed_zip_is_refused(kit, tmp_path, change, why):
    bad = tmp_path / "bad.zip"
    _rewrite(backup.create(), bad, change)
    with pytest.raises(backup.BackupError, match=why):
        backup.verify(bad)


def test_an_entry_the_manifest_does_not_list_is_refused(kit, tmp_path):
    bad = tmp_path / "bad.zip"
    _rewrite(backup.create(), bad, lambda n, d: d)
    with zipfile.ZipFile(bad, "a") as zf:
        zf.writestr("files/etc/filament-kit/extra", b"x")
    with pytest.raises(backup.BackupError, match="not listed"):
        backup.verify(bad)


def test_not_a_zip(kit, tmp_path):
    (tmp_path / "x.zip").write_bytes(b"nope")
    with pytest.raises(backup.BackupError, match="not a zip"):
        backup.verify(tmp_path / "x.zip")


def test_a_setuid_bit_never_comes_back(kit, tmp_path):
    bad = tmp_path / "bad.zip"
    _rewrite(backup.create(), bad, lambda n, d: d.replace(b'path="devices.json" sha256', b'path="devices.json" x="1" sha256')
             if n == "manifest.xml" else d)
    m = backup.verify(bad)
    assert all(i.mode & 0o4000 == 0 for i in m.items)
    assert backup._mode("4755", "file") == 0o755 and backup._mode("2750", "dir") == 0o2750


# ---------------------------------------------------------------- restore

def _wipe_and_change(kit) -> None:
    """What a different, newer state looks like: a fresh install's few files."""
    import shutil
    shutil.rmtree(kit / "state")
    (kit / "state").mkdir()
    (kit / "state" / "devices.json").write_text("[]\n")
    shutil.rmtree(kit / "state-web")
    (kit / "etc" / "config.json").write_text('{"modules": {"server": true, "spoolman": true}}\n')
    db = sqlite3.connect(kit / "spoolman" / "spoolman.db")
    db.execute("delete from spool")
    db.commit()
    db.close()


def test_restore_brings_every_file_and_the_database_back(kit, capsys):
    z = backup.create()
    _wipe_and_change(kit)
    run = Runner()
    assert backup.restore(z, yes=True, run=run) == 0
    assert (kit / "state" / "devices.json").read_text() == '[{"id": "d1"}]\n'
    assert (kit / "state" / "profiles" / "builds" / "b2.json").read_text() == "kept\n"
    assert (kit / "state-web" / "oauth.json").exists() and (kit / "etc-station" / "server.json").exists()
    assert json.loads((kit / "etc" / "config.json").read_text())["modules"]["printers"] is True
    assert _spools(kit) == [(1, "E2E PLA")]
    assert run.cmds == [[backup.WRAPPER, "modules", "apply", "--no-pair"], [backup.WRAPPER, "status"]]
    assert not list(kit.glob("*" + backup.OLD)) and not list(kit.glob("*" + backup.NEW))
    out = capsys.readouterr().out
    assert "Restored." in out and "certificate" not in out
    # what was here first is kept, as a zip a restore takes too
    kept = [p for p in (kit / "backups").iterdir() if p.name.startswith(backup.PRE_RESTORE)]
    assert len(kept) == 1 and backup.verify(kept[0])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_restore_puts_the_modes_back(kit):
    os.chmod(kit / "etc" / "key.pem", 0o640)
    os.chmod(kit / "state", 0o2750)
    z = backup.create()
    os.chmod(kit / "etc" / "key.pem", 0o666)
    assert backup.restore(z, yes=True, run=Runner()) == 0
    assert (os.stat(kit / "etc" / "key.pem").st_mode & 0o7777) == 0o640
    assert (os.stat(kit / "state").st_mode & 0o7777) == 0o2750


def test_a_backup_from_another_host_makes_a_new_certificate(kit, monkeypatch, capsys):
    z = backup.create()
    monkeypatch.setattr(backup, "host", lambda: "newbox")
    assert backup.restore(z, yes=True, run=Runner()) == 0
    assert not (kit / "etc" / "cert.pem").exists() and not (kit / "etc" / "key.pem").exists()
    assert "Pair the phones and the PC sync again" in capsys.readouterr().out


def test_a_newer_kits_backup_is_refused_with_what_to_install(kit, monkeypatch, capsys):
    z = backup.create()
    monkeypatch.setattr(backup, "__version__", "0.0.1")
    run = Runner()
    assert backup.restore(z, yes=True, run=run) == 1
    out = capsys.readouterr().out
    assert f"install {__version__} first" in out and f"--version {__version__}" in out and "Nothing was changed" in out
    assert run.cmds == []


def test_an_older_kits_backup_is_restored(kit, tmp_path):
    older = tmp_path / "older.zip"
    _rewrite(backup.create(), older, lambda n, d: d.replace(f'kit="{__version__}"'.encode(), b'kit="0.1.0"')
             if n == "manifest.xml" else d)
    assert backup.verify(older).kit == "0.1.0"
    assert backup.restore(older, yes=True, run=Runner()) == 0


def test_at_a_terminal_it_takes_the_typed_word(kit, capsys):
    z = backup.create()
    _wipe_and_change(kit)
    run = Runner()
    assert backup.restore(z, ask=lambda q: "yes", run=run) == 1
    assert run.cmds == [] and (kit / "state" / "devices.json").read_text() == "[]\n"
    assert backup.restore(z, ask=lambda q: "restore", run=run) == 0


def test_no_terminal_and_no_yes_changes_nothing(kit):
    z = backup.create()

    def eof(q):
        raise EOFError
    run = Runner()
    assert backup.restore(z, ask=eof, run=run) == 1 and run.cmds == []


def test_a_damaged_zip_changes_nothing(kit, tmp_path, capsys):
    bad = tmp_path / "bad.zip"
    _rewrite(backup.create(), bad, lambda n, d: d + b"x" if n.endswith("config.json") else d)
    _wipe_and_change(kit)
    run = Runner()
    assert backup.restore(bad, yes=True, run=run) == 1
    assert run.cmds == [] and (kit / "state" / "devices.json").read_text() == "[]\n"
    assert not (kit / "backups").exists() or not [p for p in (kit / "backups").iterdir() if p.name.startswith("pre")]


def test_a_failure_halfway_puts_everything_back(kit, monkeypatch, capsys):
    z = backup.create()
    _wipe_and_change(kit)
    real = backup._extract

    def extract(zf, items, target):
        if items and items[0].root == "var/lib/filament-kit-web":
            raise OSError(28, "No space left on device")
        return real(zf, items, target)
    monkeypatch.setattr(backup, "_extract", extract)
    assert backup.restore(z, yes=True, run=Runner()) == 1
    assert (kit / "state" / "devices.json").read_text() == "[]\n"                  # swapped back
    assert json.loads((kit / "etc" / "config.json").read_text())["modules"] == {"server": True, "spoolman": True}
    assert _spools(kit) == []
    assert not list(kit.glob("*" + backup.OLD))
    assert "what was here is back in place" in capsys.readouterr().out


def test_a_failed_apply_keeps_the_data_and_says_how_to_finish(kit, capsys):
    z = backup.create()
    _wipe_and_change(kit)
    assert backup.restore(z, yes=True, run=Runner(rc=1)) == 1
    assert (kit / "state" / "devices.json").read_text() == '[{"id": "d1"}]\n'
    out = capsys.readouterr().out
    assert "sudo filament-kit modules apply" in out and "the earlier" in out


# ---------------------------------------------------------------- the nightly tar.gz as the same zip

def test_a_nightly_backup_becomes_the_same_zip(kit, tmp_path):
    tgz = tmp_path / "2026-11-09.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(kit / "spoolman" / "spoolman.db", arcname="./spoolman.db")
        tf.add(kit / "etc", arcname="etc/filament-kit")
        tf.add(kit / "state", arcname="var/lib/filament-kit")
    out = tmp_path / "out.zip"
    with open(out, "wb") as fh:
        backup.from_daily(tgz, fh)
    m = backup.verify(out)
    assert m.spoolman is not None and m.modules == ["printers", "server", "spoolman"] and "daily" in m.source
    with zipfile.ZipFile(out) as zf:
        assert "files/var/lib/filament-kit/profiles/live/system/huge.json" not in zf.namelist()
    assert backup.restore(out, yes=True, run=Runner()) == 0


def test_listing_names_each_kind(kit, tmp_path):
    z = backup.create()
    (kit / "backups" / "2026-11-08.tar.gz").write_bytes(b"x")
    (kit / "backups" / "notes.txt").write_text("x")
    (kit / "backups" / ".restore-1.zip").write_bytes(b"x")
    rows = {e.name: e for e in backup.listing()}
    assert set(rows) == {z.name, "2026-11-08.tar.gz"}
    assert rows["2026-11-08.tar.gz"].kind == "daily" and rows["2026-11-08.tar.gz"].download.endswith(".zip")
    assert rows[z.name].kind == "made"


# ---------------------------------------------------------------- the commands and the scripts

def test_the_commands_need_root(kit, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["backup", "create"]) == 1 and cli.main(["restore", "x.zip"]) == 1
    assert "sudo filament-kit" in capsys.readouterr().err


def test_backup_create_and_restore_through_the_cli(kit, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(backup, "default_run", Runner())
    assert cli.main(["backup", "create", "--out", str(kit / "elsewhere")]) == 0
    z = next((kit / "elsewhere").glob("*.zip"))
    assert cli.main(["backup", "list"]) == 0
    assert cli.main(["restore", "--yes", str(z)]) == 0
    assert cli.main(["restore", str(kit / "missing.zip")]) == 1


def test_the_page_upload_is_taken_out_of_the_state_folder(kit, monkeypatch):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.setattr(backup, "default_run", Runner())
    z = backup.create(kit / "elsewhere")
    backup.uploaded().parent.mkdir(parents=True)
    backup.uploaded().write_bytes(z.read_bytes())
    assert cli.main(["restore", "--uploaded", "--yes"]) == 0
    assert not backup.uploaded().exists() and not list((kit / "backups").glob(".restore-*"))


def test_keep_days(kit):
    assert backup.keep_days({}) == 14 and backup.keep_days({"backup": {"keep_days": 30}}) == 30
    for bad in (0, 366, "7", True, None):
        assert backup.keep_days({"backup": {"keep_days": bad}}) == 14


def test_the_helper_knows_the_jobs_and_the_restore_needs_the_word(kit):
    assert setup_helper.JOBS["backup"] == ("backup", "create")
    assert setup_helper.JOBS["restore"] == ("restore", "--uploaded", "--yes")
    with pytest.raises(setup_helper.Refused, match="type restore"):
        setup_helper._job({"name": "restore", "confirm": "yes"})
    with pytest.raises(setup_helper.Refused, match="upload the backup"):
        setup_helper._job({"name": "restore", "confirm": "restore"})


@pytest.mark.parametrize("days,ok", [(1, True), (365, True), (0, False), (366, False), ("7", False), (True, False)])
def test_backup_keep_op(kit, days, ok):
    if ok:
        assert setup_helper._backup_keep({"days": days}) == {"days": days}
        assert config.load()["backup"]["keep_days"] == days
    else:
        with pytest.raises(setup_helper.Refused):
            setup_helper._backup_keep({"days": days})


def test_scripts():
    text = (ROOT / "install" / "backup.sh").read_text(encoding="utf-8")
    assert 'chmod 750 "$DEST"' in text and "filament_kit.backup keep-days" in text and "-mtime +$((KEEP - 1))" in text
    inst = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    assert '--restore) [ $# -ge 2 ] || usage; RESTORE="$2"' in inst
    assert 'exec /usr/local/bin/filament-kit restore --yes "$RESTORE"' in inst
    assert inst.index("restore --yes") < inst.index("# ---------- 4. install mode")
    wrap = (ROOT / "install" / "filament-kit-cli.sh").read_text(encoding="utf-8")
    assert '    backup | restore) exec "$BIN" "$@" ;;' in wrap


def test_the_manifest_version_parses_as_a_release_version(kit):
    assert release.parse_version(backup.verify(backup.create()).kit)


def test_zip_bytes_are_a_standard_zip(kit):
    data = backup.create().read_bytes()
    assert data[:4] == b"PK\x03\x04" and zipfile.is_zipfile(io.BytesIO(data))
