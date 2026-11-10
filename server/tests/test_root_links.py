"""Root's web_state step (web_access.migrate / shared_files / pair / grant) never acts through a link that the kit
server's user (owner of the state folder) or the web unit's user (owner of its own folder) planted. These use the
real os functions on a temp folder; the root test also checks owners (run it as root: sudo .../pytest -k root)."""
from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import acl, config, pairing, web_access
from filament_kit.bridge import printer_report

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only: root runs this on Linux")
ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
WEB_UID = KIT_UID = None


@pytest.fixture
def kit(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.delenv("FK_WEB_STATE", raising=False)
    victim = tmp_path / "victim"
    victim.mkdir()
    for n in ("a", "b"):
        (victim / n).write_text("root's\n", encoding="utf-8")
        os.chmod(victim / n, 0o600)
    return tmp_path


def _ids():
    """(web uid, kit uid): other users as root, this user otherwise (chown to oneself works without root)."""
    if ROOT:
        return 54321, 54322
    return os.getuid(), os.getuid()


def _plant(kit):
    st, v = kit / "state", kit / "victim"
    (st / "web" / "push").mkdir(parents=True)
    (st / "web" / "push" / "subs.json").write_text("{}", encoding="utf-8")
    os.symlink(v / "a", st / "web" / "push" / "innocent")          # a link inside a folder that moves
    os.symlink(v / "b", st / "web" / "reader_tokens")               # the tokens file chmod-ed 644
    os.symlink(v / "c", st / "inventory.lock")                      # dangling: root would create it


def _same(path, mode, uid=0):
    s = os.stat(path)
    assert stat.S_IMODE(s.st_mode) == mode, path
    if ROOT:
        assert (s.st_uid, s.st_gid) == (uid, uid), path


def test_web_state_follows_none_of_the_three_planted_links(kit, caplog):
    _plant(kit)
    web, kit_uid = _ids()
    caplog.set_level(logging.WARNING)
    moved = web_access.migrate(web, web)
    web_access.shared_files(kit_uid, kit_uid)
    v = kit / "victim"
    _same(v / "a", 0o600)
    _same(v / "b", 0o600)
    assert not os.path.lexists(v / "c")
    assert moved == ["push"]                                        # the real files still move
    w = config.paths().web
    assert (w / "push" / "subs.json").read_text(encoding="utf-8") == "{}"
    assert "skipped" in caplog.text and "symbolic link" in caplog.text
    assert os.path.islink(kit / "state" / "inventory.lock")         # left alone (logged), never replaced
    for name in web_access.LOCK_FILES[1:]:
        assert (kit / "state" / name).is_file() and not (kit / "state" / name).is_symlink()


def test_a_linked_state_web_folder_is_not_emptied(kit):
    os.symlink(kit / "victim", kit / "state" / "web")
    web_access.migrate(*_ids()[:1] * 2)
    assert sorted(os.listdir(kit / "victim")) == ["a", "b"]
    _same(kit / "victim" / "a", 0o600)


def test_a_linked_profiles_folder_gets_no_locks(kit):
    os.symlink(kit / "victim", kit / "state" / "profiles")
    web_access.shared_files(*_ids()[1:] * 2)
    assert sorted(os.listdir(kit / "victim")) == ["a", "b"]
    assert (kit / "state" / "inventory.lock").is_file()


def test_links_already_in_the_web_folder_are_not_followed(kit):
    w = config.paths().web
    w.mkdir()
    os.symlink(kit / "victim" / "a", w / "oauth.json")
    (w / "sub").mkdir()
    os.symlink(kit / "victim", w / "sub" / "dir")
    web_access.migrate(*_ids()[:1] * 2)
    _same(kit / "victim" / "a", 0o600)
    _same(kit / "victim", stat.S_IMODE(os.stat(kit / "victim").st_mode))


def test_pair_replaces_a_dangling_kit_token_link_and_never_writes_its_target(kit):
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    w = config.paths().web
    w.mkdir()
    os.symlink(kit / "victim" / "d", w / "kit_token")
    web, _ = _ids()
    assert web_access.pair(web, web) is True
    assert not os.path.lexists(kit / "victim" / "d")
    assert (w / "kit_token").is_file() and not (w / "kit_token").is_symlink()


def test_pair_does_not_take_a_link_to_a_file_for_a_token(kit):
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    w = config.paths().web
    w.mkdir()
    os.symlink(kit / "victim" / "a", w / "kit_token")
    web, _ = _ids()
    assert web_access.pair(web, web) is True
    _same(kit / "victim" / "a", 0o600)
    assert (kit / "victim" / "a").read_text(encoding="utf-8") == "root's\n"
    assert not (w / "kit_token").is_symlink()


def _acls_or_skip(path):
    if not acl.supported():
        pytest.skip("no xattrs here")
    try:
        acl.grant(path, {54329: acl.R})
    except OSError:
        pytest.skip("no ACLs on this file system")


def test_grants_never_go_through_a_link_in_a_tree_or_a_lock_folder(kit):
    _acls_or_skip(kit / "victim" / "b")
    st = kit / "state"
    (st / "library").mkdir()
    os.symlink(kit / "victim", st / "library" / "sub")
    os.symlink(kit / "victim" / "a", st / "library" / "f")
    web_access.shared_files(*_ids()[1:] * 2)
    os.rename(st / "profiles", st / "profiles.real")
    os.symlink(kit / "victim", st / "profiles")                    # lines.lock etc. now lead into the victim
    (kit / "victim" / "lines.lock").write_text("", encoding="utf-8")
    web_access.grant(54321, os.getuid(), {})
    assert 54321 not in acl.users_of(kit / "victim")
    assert 54321 not in acl.users_of(kit / "victim" / "a")
    assert 54321 not in acl.users_of(kit / "victim" / "lines.lock")
    assert acl.users_of(st / "library")[54321] == acl.R | acl.X


@pytest.mark.skipif(not ROOT, reason="owners: run as root (sudo)")
def test_as_root_the_owners_are_right_and_the_victims_keep_theirs(kit):
    _plant(kit)
    v = kit / "victim"
    web_access.migrate(54321, 54321)
    web_access.shared_files(54322, 54322)
    for n in ("a", "b"):
        s = os.stat(v / n)
        assert (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) == (0, 0, 0o600)
    assert not os.path.lexists(v / "c")
    w = config.paths().web
    assert os.stat(w).st_uid == 54321 and os.stat(w / "push" / "subs.json").st_uid == 54321
    assert not os.path.lexists(w / "push" / "innocent")             # a link is never copied
    assert os.lstat(kit / "state" / "web" / "push" / "innocent").st_uid == 0   # nor chowned where it is
    lock = kit / "state" / "profiles" / "lines.lock"
    assert os.stat(lock).st_uid == 54322 and stat.S_IMODE(os.stat(lock).st_mode) == 0o644


def test_root_never_reads_a_linked_devices_file_into_the_kits_state(kit):
    """pair() runs pairing.issue as root: a devices.json link to a root-only JSON file must not be read (and then
    written back, readable by the kit's user)."""
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    (kit / "victim" / "secret.json").write_text('[{"id": "x", "name": "SECRET-EXAMPLE", "hash": "h"}]',
                                                encoding="utf-8")
    os.symlink(kit / "victim" / "secret.json", kit / "state" / "devices.json")
    with pytest.raises(OSError):
        web_access.pair(*_ids()[:1] * 2)
    assert os.path.islink(kit / "state" / "devices.json")
    for f in (kit / "state").iterdir():
        if f.is_file() and not f.is_symlink():
            assert "SECRET-EXAMPLE" not in f.read_text(encoding="utf-8", errors="replace"), f


# --- the web unit's files are copied, not moved, so `update --rollback` to 0.3.0 (which reads only state/web/)
# keeps the connector sign-ins, push subscriptions and the web unit's pairing; a marker makes it one-time

def _old_files(kit):
    old = kit / "state" / "web"
    (old / "push").mkdir(parents=True)
    for rel, text in (("oauth.json", '{"clients": {"c1": {}}}'), ("kit_token", "tok-EXAMPLE\n"),
                      ("push/subs.json", '{"ep": {}}'), ("push/vapid.pem", "pem")):
        (old / rel).write_text(text, encoding="utf-8")
        os.chmod(old / rel, 0o600)
    os.chmod(old / "push", 0o750)
    return old


def _tree(root):
    """{relative path: (mode, bytes or None for a folder)} of everything below `root` (links as links)."""
    out = {}
    for dirpath, dirs, files in os.walk(root):
        for n in [*dirs, *files]:
            p = os.path.join(dirpath, n)
            s = os.lstat(p)
            rel = os.path.relpath(p, root)
            out[rel] = (stat.S_IMODE(s.st_mode), None if not stat.S_ISREG(s.st_mode) else open(p, "rb").read())
    return out


def test_migrate_copies_and_leaves_the_originals(kit):
    old = _old_files(kit)
    before = _tree(old)
    web, _ = _ids()
    copied = web_access.migrate(web, web)
    assert copied == ["kit_token", "oauth.json", "push"]
    assert _tree(old) == before                                     # 0.3.0 still finds every file, unchanged
    w = config.paths().web
    for rel, (mode, data) in before.items():
        assert _tree(w)[rel] == (mode, data), rel                   # same bytes, same modes as the move gave


def test_marker_is_written_once_owned_by_the_web_user_0600(kit):
    _old_files(kit)
    web, _ = _ids()
    web_access.migrate(web, web)
    m = config.paths().web / web_access.MARKER
    s = os.lstat(m)
    assert stat.S_ISREG(s.st_mode) and stat.S_IMODE(s.st_mode) == 0o600
    text = m.read_text(encoding="utf-8")
    for name in ("kit_token", "oauth.json", "push"):
        assert name in text.split()
    if ROOT:
        assert (s.st_uid, s.st_gid) == (web, web)


def test_a_file_the_web_unit_removed_later_is_never_brought_back(kit):
    _old_files(kit)
    web, _ = _ids()
    web_access.migrate(web, web)
    w = config.paths().web
    os.unlink(w / "push" / "subs.json")                            # a revoked push subscription
    os.unlink(w / "oauth.json")
    assert web_access.migrate(web, web) == []
    assert not (w / "push" / "subs.json").exists() and not (w / "oauth.json").exists()


def test_with_the_marker_present_nothing_is_copied(kit):
    _old_files(kit)
    w = config.paths().web
    w.mkdir()
    (w / web_access.MARKER).write_text("copied earlier\n", encoding="utf-8")
    assert web_access.migrate(*_ids()[:1] * 2) == []
    assert sorted(os.listdir(w)) == [web_access.MARKER]


def test_an_earlier_move_without_a_marker_gets_only_what_is_missing(kit):
    old = _old_files(kit)
    w = config.paths().web
    (w / "push").mkdir(parents=True)                                # round-2 layout: these were moved already
    (w / "oauth.json").write_text("moved-newer", encoding="utf-8")
    (w / "push" / "subs.json").write_text("moved-newer", encoding="utf-8")
    copied = web_access.migrate(*_ids()[:1] * 2)
    assert (w / "oauth.json").read_text(encoding="utf-8") == "moved-newer"            # never written over
    assert (w / "push" / "subs.json").read_text(encoding="utf-8") == "moved-newer"
    assert (w / "kit_token").read_text(encoding="utf-8") == "tok-EXAMPLE\n"
    assert (w / "push" / "vapid.pem").read_text(encoding="utf-8") == "pem"             # missing inside a folder
    assert copied == ["kit_token", "push"]
    assert (w / web_access.MARKER).is_file()
    assert (old / "oauth.json").read_text(encoding="utf-8") == '{"clients": {"c1": {}}}'


def test_links_and_fifos_in_the_old_folder_are_not_copied(kit, caplog):
    old = _old_files(kit)
    v = kit / "victim"
    os.symlink(v / "a", old / "linked.json")
    os.symlink(v, old / "linked_dir")
    os.mkfifo(old / "pipe")
    os.symlink(v / "b", old / "push" / "innocent")
    os.mkfifo(old / "push" / "pipe")
    caplog.set_level(logging.WARNING)
    copied = web_access.migrate(*_ids()[:1] * 2)
    w = config.paths().web
    assert copied == ["kit_token", "oauth.json", "push"]
    for rel in ("linked.json", "linked_dir", "pipe", "push/innocent", "push/pipe"):
        assert not os.path.lexists(w / rel), rel
        assert os.path.lexists(old / rel), rel                     # left where they were
    _same(v / "a", 0o600)
    _same(v / "b", 0o600)
    assert "symbolic link" in caplog.text and "not a regular file" in caplog.text


def test_a_name_planted_in_the_web_folder_is_never_written_through(kit):
    old = _old_files(kit)
    w = config.paths().web
    w.mkdir()
    os.symlink(kit / "victim" / "c", w / "kit_token")              # dangling: O_EXCL never makes its target
    os.symlink(kit / "victim", w / "push")                         # a folder name planted as a link
    web_access.migrate(*_ids()[:1] * 2)
    assert not os.path.lexists(kit / "victim" / "c")
    assert sorted(os.listdir(kit / "victim")) == ["a", "b"]
    assert (old / "kit_token").read_text(encoding="utf-8") == "tok-EXAMPLE\n"


def test_a_printer_report_never_writes_through_a_planted_name(kit, monkeypatch):
    monkeypatch.setattr(printer_report.time, "time", lambda: 1_700_000_000.0)
    d = config.paths().state / "printers" / "S1"
    d.mkdir(parents=True)
    os.symlink(kit / "victim" / "a", d / printer_report.file_name("N6"))
    path = printer_report.save("S1", b"<report/>", "N6")
    assert (kit / "victim" / "a").read_text(encoding="utf-8") == "root's\n"
    assert not path.is_symlink() and path.read_bytes() == b"<report/>"


@pytest.mark.skipif(not ROOT, reason="owners: run as root (sudo)")
def test_as_root_a_printer_report_leaves_the_folder_and_file_the_services(kit):
    state = config.paths().state
    os.chown(state, _ids()[1], _ids()[1])
    path = printer_report.save("S2", b"<report/>", "N6")
    assert path.parent.stat().st_uid == _ids()[1] and path.stat().st_uid == _ids()[1]


@pytest.mark.skipif(not ROOT, reason="owners: run as root (sudo)")
def test_as_root_copies_are_the_web_users_and_the_originals_stay_the_kits(kit):
    old = _old_files(kit)
    for dirpath, dirs, files in os.walk(old):
        for n in [dirpath, *[os.path.join(dirpath, f) for f in files]]:
            os.chown(n, 54322, 54322)
    web_access.migrate(54321, 54321)
    w = config.paths().web
    for rel in ("oauth.json", "kit_token", "push", "push/subs.json", "push/vapid.pem"):
        o, c = os.lstat(old / rel), os.lstat(w / rel)
        assert (o.st_uid, o.st_gid) == (54322, 54322), rel                       # originals untouched
        assert (c.st_uid, c.st_gid) == (54321, 54321), rel
        assert stat.S_IMODE(c.st_mode) == stat.S_IMODE(o.st_mode), rel
    assert stat.S_IMODE(os.lstat(old / "oauth.json").st_mode) == 0o600           # not widened


# ---------------------------------------------------------------- the setup helper's sandbox (R79 review)

UNIT = Path(__file__).resolve().parents[2] / "install" / "systemd" / "filament-kit-setup@.service"
SANDBOX_KEYS = ("ProtectSystem", "ReadWritePaths", "PrivateTmp", "PrivateDevices", "PrivateNetwork", "NoNewPrivileges",
                "UMask", "SystemCallFilter", "RestrictAddressFamilies", "CapabilityBoundingSet", "RestrictNamespaces",
                "MemoryDenyWriteExecute", "LockPersonality")


def _unit_settings() -> dict[str, str]:
    out = {}
    for line in UNIT.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_the_helper_unit_may_write_where_a_restore_pins_the_upload():
    paths = _unit_settings()["ReadWritePaths"].split()
    assert paths == ["/etc/filament-kit", "-/var/backups/filament-kit"]      # never a folder the server owns
    install = (Path(__file__).resolve().parents[2] / "install" / "install.sh").read_text(encoding="utf-8")
    assert "install -d -m 700 -o root -g root /var/backups/filament-kit" in install     # so the "-" path exists


@pytest.mark.skipif(not ROOT or not shutil.which("systemd-run") or not os.path.isdir("/run/systemd/system"),
                    reason="root and a running systemd")
def test_pin_upload_works_in_the_helper_units_own_sandbox(tmp_path, monkeypatch):
    """R79 review, finding 1: pin_upload under the unit's sandbox (its ReadWritePaths mapped onto scratch folders of the
    same kind; ProtectHome relaxed to read-only only so this checkout and its Python can load)."""
    import secrets as _secrets
    from filament_kit import backup
    tag = _secrets.token_hex(4)
    E, S, K = Path(f"/etc/fk-root-{tag}"), Path(f"/var/lib/fk-root-{tag}"), Path(f"/var/backups/fk-root-{tag}")
    try:
        for d in (E, S / "restore-upload", K):
            d.mkdir(parents=True)
        os.chmod(K, 0o700)
        scratch = tmp_path / "make"
        for name in ("etc", "state", "opt", "bk"):
            (scratch / name).mkdir(parents=True)
        for k, v in (("FK_ETC", "etc"), ("FK_STATE", "state"), ("FK_OPT", "opt"), ("FK_BACKUPS", "bk")):
            monkeypatch.setenv(k, str(scratch / v))
        monkeypatch.setenv("FK_SPOOLMAN_DB", str(scratch / "none.db"))
        monkeypatch.setenv("FK_NO_SYSTEMD", "1")
        config.save({})
        z = backup.create()
        shutil.copyfile(z, S / "restore-upload" / "backup.zip")
        unit = _unit_settings()
        mapped = {"/etc/filament-kit": str(E), "-/var/backups/filament-kit": f"-{K}"}
        props = []
        for key in SANDBOX_KEYS:
            if key in unit:
                value = " ".join(mapped.get(p, p) for p in unit[key].split()) if key == "ReadWritePaths" else unit[key]
                props += ["-p", f"{key}={value}"]
        code = ("import sys\nfrom filament_kit import backup\nm, sha = backup.pin_upload()\n"
                "print('PINNED', sha, len(m.files))")
        env = [f"-E{k}={v}" for k, v in (("FK_ETC", E), ("FK_STATE", S), ("FK_BACKUPS", K), ("FK_NO_SYSTEMD", "1"),
                                         ("PYTHONPATH", Path(__file__).resolve().parents[1]))]
        r = subprocess.run(["systemd-run", "--quiet", "--wait", "--pipe", "--collect", "-p", "ProtectHome=read-only",
                            *props, *env, sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        assert "PINNED" in r.stdout, r.stdout + r.stderr
        assert (K / backup.PENDING).is_file() and (S / "restore-upload" / "backup.zip").exists()   # the server's to remove
        assert stat.S_IMODE((K / backup.PENDING).stat().st_mode) == 0o600
    finally:
        for d in (E, S, K):
            shutil.rmtree(d, ignore_errors=True)
