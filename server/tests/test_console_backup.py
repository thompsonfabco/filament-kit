"""The setup console's Backups card: every route takes the code or a trusted computer, nothing is sent without one."""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest
from test_setup_page import BASE, CODE, H, HOME, Helper, client, env, make, post  # noqa: F401

from filament_kit import backup, cli, config

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FK_BACKUPS", str(tmp_path / "backups"))
    monkeypatch.setenv("FK_SPOOLMAN_DB", str(tmp_path / "spoolman.db"))
    db = sqlite3.connect(tmp_path / "spoolman.db")
    db.execute("create table t (x)")
    db.commit()
    db.close()
    return make(env, Helper(), Mgr())


def test_listing_needs_the_code(app):
    backup.create()
    assert post(client(app), "backups/list", {}, code=None).status_code in (401, 403)
    assert post(client(app), "backups/list", {}, code="0000-0000").status_code == 403
    r = post(client(app), "backups/list", {}).json()
    assert len(r["backups"]) == 1 and r["keep_days"] == 14


def test_download_gives_the_zip_under_its_own_name(app):
    z = backup.create()
    r = post(client(app), "backups/download", {"name": z.name})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert f'filename="{z.name}"' in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    assert r.content == z.read_bytes()


def test_a_nightly_tar_downloads_as_a_zip(app, tmp_path):
    import tarfile
    (tmp_path / "backups").mkdir()
    tgz = tmp_path / "backups" / "2026-11-08.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(config.paths().etc, arcname="etc/filament-kit")
    r = post(client(app), "backups/download", {"name": tgz.name})
    assert r.status_code == 200 and 'filename="filament-kit-backup-' in r.headers["content-disposition"]
    (tmp_path / "got.zip").write_bytes(r.content)
    assert backup.verify(tmp_path / "got.zip").source == "daily 2026-11-08.tar.gz"


@pytest.mark.parametrize("name", ["../etc/passwd", "nope.zip", "", None, 5, ".restore-1.zip"])
def test_download_takes_only_a_listed_name(app, tmp_path, name):
    backup.create()
    (tmp_path / "backups" / ".restore-1.zip").write_bytes(b"PK")
    assert post(client(app), "backups/download", {"name": name}).status_code == 404


def test_download_needs_the_code(app):
    z = backup.create()
    assert post(client(app), "backups/download", {"name": z.name}, code="0000-0000").status_code == 403


def _upload(app, data: bytes, code=CODE):
    headers = {**H, "Content-Type": "application/zip"}
    if code is not None:
        headers["X-Setup-Code"] = code
    return client(app).post("/setup/api/restore/upload", content=data, headers=headers)


def test_upload_checks_the_zip_and_says_what_it_holds(app):
    z = backup.create()
    r = _upload(app, z.read_bytes())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kit"] and body["files"] >= 1 and body["spoolman"] is True and body["replaces_data"] is True
    assert backup.uploaded().read_bytes() == z.read_bytes()


def test_upload_needs_the_code_and_keeps_nothing_without_it(app):
    z = backup.create()
    assert _upload(app, z.read_bytes(), code=None).status_code in (401, 403)
    assert _upload(app, z.read_bytes(), code="0000-0000").status_code == 403
    assert not backup.uploaded().exists()


def test_a_bad_upload_is_refused_and_removed(app, tmp_path):
    z = backup.create()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(z) as zin, zipfile.ZipFile(bad, "w") as zout:
        for i in zin.infolist():
            zout.writestr(i.filename, zin.read(i) + (b"x" if i.filename.endswith("config.json") else b""))
    r = _upload(app, bad.read_bytes())
    assert r.status_code == 400 and "damaged" in r.json()["error"]
    assert not backup.uploaded().parent.exists()
    assert _upload(app, b"not a zip").status_code == 400


def test_a_newer_kits_upload_is_refused(app, monkeypatch):
    z = backup.create()
    monkeypatch.setattr(backup, "__version__", "0.0.1")
    r = _upload(app, z.read_bytes())
    assert r.status_code == 409 and "install" in r.json()["error"]


def test_the_restore_job_takes_the_typed_word(app, monkeypatch):
    started = []
    from filament_kit import setup_helper
    monkeypatch.setattr(setup_helper, "_start_job", lambda name, why="": started.append(name))
    _upload(app, backup.create().read_bytes())
    assert post(client(app), "job", {"name": "restore", "confirm": "yes"}).status_code == 400
    assert post(client(app), "job", {"name": "restore"}).status_code == 400
    assert post(client(app), "job", {"name": "restore", "confirm": "restore"}).status_code == 200
    assert started == ["restore"]


def test_forget_drops_the_upload(app):
    _upload(app, backup.create().read_bytes())
    assert post(client(app), "restore/forget", {}).status_code == 200 and not backup.uploaded().exists()


def test_keep_days_goes_through_the_helper(app):
    assert post(client(app), "backups/keep", {"days": 30}).json() == {"ok": True, "days": 30}
    assert backup.keep_days(config.load()) == 30
    assert post(client(app), "backups/keep", {"days": 0}).status_code == 400


def test_the_settings_tab_has_the_card_and_the_page_its_script(app):
    assert "backupCard()" in (STATIC / "setup.js").read_text(encoding="utf-8")
    src = (STATIC / "setup_backup.js").read_text(encoding="utf-8")
    assert "innerHTML" not in src and 'confirm: word.value.trim()' in src
    assert "The zip is not encrypted and holds the setup secrets" in src
    assert "/setup/setup_backup.js" in client(app).get("/setup").text
    assert BASE and HOME
