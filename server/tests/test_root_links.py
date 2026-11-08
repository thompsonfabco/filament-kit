"""Root's web_state step (web_access.migrate / shared_files / pair / grant) never acts through a link that the kit
server's user (owner of the state folder) or the web unit's user (owner of its own folder) planted. These use the
real os functions on a temp folder; the root test also checks owners (run it as root: sudo .../pytest -k root)."""
from __future__ import annotations

import logging
import os
import stat
import sys

import pytest

from filament_kit import acl, config, pairing, web_access

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
    assert os.lstat(w / "push" / "innocent").st_uid == 0           # the link itself was not chowned either
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
