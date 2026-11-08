"""One sync run with Orca Slicer present (or not): uploads, install of the orca/ tree, rebuild triggers."""
import io
import json
import zipfile

import pytest

import orca_fixture
import studio_fixture
from fksync import client, installer, store, sync, treehash
from test_sync import INFO, PRESET, STAMP, T0, FakeClient

N = "Acme PLA @SV08 MAX 0.4"
OPRESET = {"name": N, "inherits": "Generic PLA @System", "from": "User", "filament_id": "Pabcdef1",
           "filament_flow_ratio": ["0.98"], "nozzle_temperature": ["215"]}
OINFO = {"sync_info": "", "user_id": orca_fixture.USER_ID, "setting_id": "", "base_id": "RcBNzytWgwRrwXXz"}


class OrcaClient(FakeClient):
    def __init__(self, state, build_zip=None):
        super().__init__(state, build_zip)
        self.fail_kind = {}

    def upload(self, kind, data, user_id=None, partial=None):
        exc = self.fail_kind.get(kind)
        if exc is not None:
            self.calls.append(("upload", kind, user_id))
            raise exc
        return super().upload(kind, data, user_id, partial)

    def rebuild(self, live_hash, orca_live_hash=None):
        self.rebuild_orca = getattr(self, "rebuild_orca", []) + [orca_live_hash]
        return super().rebuild(live_hash)


@pytest.fixture
def env(tmp_path):
    folders = studio_fixture.make(tmp_path / "appdata", base={"Acme PLA @BBL H2D": (PRESET, INFO)})
    orca = orca_fixture.make(tmp_path / "appdata", presets={N: (OPRESET, OINFO)},
                             install=tmp_path / "pf" / "OrcaSlicer 2.5.0",
                             opc=orca_fixture.opc_blob(orca_fixture.LIBRARY))
    dirs = store.AppDirs(tmp_path / "local" / "filament-kit-sync")
    dirs.ensure()
    return folders, orca, dirs


def _hashes(folders, orca):
    return (treehash.tree_hash(folders.user_filament), treehash.tree_hash(folders.system_filament),
            treehash.tree_hash(orca.user_filament), sync.zips.orca_system(orca)[1])


def _state(folders, orca, build=None, installed=None, orca_keys=True, orca_target=True):
    live, system, olive, osys = _hashes(folders, orca)
    st = {"owner": "dev1", "you": "dev1", "user_id": folders.user_id, "live_hash": live, "system_hash": system,
          "build": build, "last_attempt": None, "installed": installed, "rebuild_requested": None}
    if orca_keys:
        st.update(orca_live_hash=olive, orca_system_hash=osys, orca_target=orca_target)
    return st


def _zip(stamp=STAMP, live_hash=None, orca_live_hash=None, orca=None, base=None):
    base = base if base is not None else {"Acme PLA @BBL H2D": dict(PRESET, nozzle_temperature=["220"])}
    orca = orca if orca is not None else {N: dict(OPRESET, nozzle_temperature=["225"])}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        meta = {"stamp": stamp, "live_hash": live_hash, "stale": []}
        if orca_live_hash:
            meta["orca_live_hash"] = orca_live_hash
        zf.writestr("BUILD.json", json.dumps(meta))
        for name, data in base.items():
            zf.writestr(f"base/{name}.json", json.dumps(data, indent=4))
            zf.writestr(f"base/{name}.info", "sync_info = \nsetting_id = \n")
        for name, data in orca.items():
            zf.writestr(f"orca/{name}.json", json.dumps(data, indent=4))
            zf.writestr(f"orca/{name}.info", "sync_info = \nsetting_id = \n")
    return buf.getvalue()


def _all(stamp):
    """The owner accepted every update of build `stamp` (the only way an existing preset is written over)."""
    return {"stamp": stamp, "base": ["Acme PLA @BBL H2D"], "orca": [N]}


def _log(dirs):
    return dirs.log_file.read_text(encoding="utf-8") if dirs.log_file.exists() else ""


def _run(c, folders, orca, dirs, now=T0, running=lambda: False, orca_running=lambda: False, **kw):
    return sync.run_once(c, folders, dirs, running=running, now=now, orca=orca, orca_running=orca_running, **kw)


def _uploads(c):
    return [x[1] for x in c.calls if x[0] == "upload"]


def test_orca_trees_uploaded_with_target(env):
    folders, orca, dirs = env
    st = _state(folders, orca)
    st.update(orca_live_hash=None, orca_system_hash=None)
    c = OrcaClient(st)
    assert _run(c, folders, orca, dirs) == "uploaded"
    assert _uploads(c) == ["orca_live", "orca_system"]
    assert ("upload", "orca_live", None) in c.calls                  # no Bambu user id on an Orca upload
    assert f"{N}.json" in c.uploaded["orca_live"]
    assert "OrcaFilamentLibrary/index.json" in c.uploaded["orca_system"]
    assert "BBL/filament/Bambu PLA Basic @BBL H2D.json" in c.uploaded["orca_system"]
    assert "Orca Slicer live presets" in _log(dirs)
    # the server has them now: nothing sent again
    c.calls.clear()
    assert _run(c, folders, orca, dirs, now=T0 + 60) == "no_build"
    assert _uploads(c) == []


def test_old_server_without_orca_keys_gets_no_orca_upload(env):
    folders, orca, dirs = env
    st = _state(folders, orca, orca_keys=False)
    st["live_hash"] = None
    c = OrcaClient(st)
    assert _run(c, folders, orca, dirs) == "uploaded"
    assert _uploads(c) == ["live"]                 # an old server would store target=orca as the Bambu live folder
    assert "does not take Orca Slicer presets" in _log(dirs)
    assert sync.load_state(dirs)["orca"]["note"].startswith("the server does not take Orca Slicer presets")
    _run(c, folders, orca, dirs, now=T0 + 60)
    assert _log(dirs).count("does not take Orca Slicer presets") == 1   # noted once, not every run


@pytest.mark.parametrize("status", [400, 404])
def test_orca_upload_refused_skips_orca_quietly(env, status):
    folders, orca, dirs = env
    st = _state(folders, orca)
    st.update(orca_live_hash=None, live_hash=None)
    c = OrcaClient(st)
    c.fail_kind["orca_live"] = client.ApiError(status, "not_found" if status == 404 else "bad_request", "no")
    assert _run(c, folders, orca, dirs) == "uploaded"           # the Bambu Studio part went on
    assert "orca_live" in _uploads(c) and "live" in _uploads(c)
    c.calls.clear()
    _run(c, folders, orca, dirs, now=T0 + 60)
    assert "orca_live" not in _uploads(c)                     # not retried for a while
    if status == 404:
        assert "Orca" in sync.load_state(dirs)["orca"]["note"]


def test_orca_running_does_nothing(env):
    folders, orca, dirs = env
    c = OrcaClient(_state(folders, orca))
    assert _run(c, folders, orca, dirs, orca_running=lambda: True) == "studio_running"
    assert c.calls == [("state",), ("heartbeat", "studio_running")]   # B-I2: the state call (is Orca synced?), then R3
    assert "Orca Slicer is open" in _log(dirs)


# ---------- B-I2: Orca is synced only when the server makes Orca presets (orca_target) ----------

@pytest.mark.parametrize("target", [False, None])
def test_server_without_orca_target_skips_orca_entirely(env, monkeypatch, target):
    """No Orca printers on the server (orca_target false, or a server without the key): no Orca running check,
    no Orca zip packed, no Orca upload; Bambu Studio syncs with Orca Slicer open."""
    folders, orca, dirs = env
    st = _state(folders, orca, orca_target=bool(target))
    st.update(live_hash=None, orca_live_hash=None, orca_system_hash=None)
    if target is None:
        del st["orca_target"]
    c = OrcaClient(st)
    packed = []
    real_pack, real_sys = sync.zips.pack, sync.zips.orca_system
    monkeypatch.setattr(sync.zips, "pack", lambda root, m=None: packed.append(root) or real_pack(root, m))
    monkeypatch.setattr(sync.zips, "orca_system", lambda *a, **k: packed.append("orca_system") or real_sys(*a, **k))
    assert _run(c, folders, orca, dirs, orca_running=lambda: True) == "uploaded"
    assert _uploads(c) == ["live"]
    assert packed == [folders.user_filament]
    assert "makes no Orca Slicer presets" in sync.load_state(dirs)["orca"]["note"]
    _run(c, folders, orca, dirs, now=T0 + 60, orca_running=lambda: True)
    assert _log(dirs).count("makes no Orca Slicer presets") == 1


def test_server_without_orca_target_installs_bambu_only_with_orca_open(env):
    folders, orca, dirs = env
    live = _hashes(folders, orca)[0]
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live}, orca_target=False),
                   _zip(live_hash=live, orca={}))
    assert _run(c, folders, orca, dirs, orca_running=lambda: True) == "installed"
    assert c.trees == [["base"]]
    assert _uploads(c) == ["live"]


def test_orca_absent_is_bambu_only(env):
    folders, orca, dirs = env
    st = _state(folders, orca)
    st.update(live_hash=None, orca_live_hash=None)
    c = OrcaClient(st)
    assert _run(c, folders, None, dirs, orca_running=lambda: True) == "uploaded"
    assert _uploads(c) == ["live"]


def test_install_both_trees_then_report_and_upload_both(env):
    folders, orca, dirs = env
    live, _, olive, _ = _hashes(folders, orca)
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive}),
                   _zip(live_hash=live, orca_live_hash=olive))
    c.st["accepted_updates"] = _all(STAMP)          # written over the existing presets
    assert _run(c, folders, orca, dirs) == "installed"
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["225"]
    names = [x[:2] for x in c.calls]
    assert names[-3:] == [("installed", STAMP), ("upload", "live"), ("upload", "orca_live")]
    assert (dirs.installed / "orca" / f"{N}.json").is_file()
    assert "Orca Slicer" in _log(dirs)


def test_orca_live_newer_than_build_asks_for_rebuild_but_installs_bambu_studio(env):
    """Ruling Z: the Orca hash never gates the Bambu Studio install; the orca/ tree waits for a matching build."""
    folders, orca, dirs = env
    live = _hashes(folders, orca)[0]
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": "older"}),
                   _zip(live_hash=live, orca_live_hash="older"))
    c.st["accepted_updates"] = _all(STAMP)          # written over the existing presets
    assert _run(c, folders, orca, dirs) == "installed"
    assert ("rebuild", live) in c.calls
    assert c.rebuild_orca == [_hashes(folders, orca)[2]]           # Ruling O: both live hashes
    assert json.loads((folders.user_filament / "base" / "Acme PLA @BBL H2D.json").read_text())[
        "nozzle_temperature"] == ["220"]
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["215"]
    assert "Orca presets not installed this run" in _log(dirs)
    assert not (dirs.installed / "orca").exists()


def test_orca_edit_after_install_asks_for_rebuild(env):
    folders, orca, dirs = env
    live, _, olive, _ = _hashes(folders, orca)
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive}),
                   _zip(live_hash=live, orca_live_hash=olive))
    assert _run(c, folders, orca, dirs) == "installed"
    c.st.update(_state(folders, orca, build=c.st["build"], installed={"stamp": STAMP}))
    c.calls.clear()
    assert _run(c, folders, orca, dirs, now=T0 + 60) == "up_to_date"
    data = json.loads((orca.user_filament / f"{N}.json").read_text())
    data["filament_flow_ratio"] = ["0.9"]
    (orca.user_filament / f"{N}.json").write_text(json.dumps(data))
    assert _run(c, folders, orca, dirs, now=T0 + 120) == "rebuild_requested"
    assert "orca_live" in _uploads(c)


def test_interrupted_install_not_resumed_after_orca_edit(env):
    folders, orca, dirs = env
    live, _, olive, _ = _hashes(folders, orca)

    def crashing_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None, orca=None,
                         orca_running=None):
        backup = installer._backup(folders.user_filament, dirs.backups, stamp_now)
        installer._backup(orca.user_filament, dirs.orca_backups, backup.name)
        before_write(backup)
        raise OSError("disk full")

    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive}),
                   _zip(live_hash=live, orca_live_hash=olive))
    with pytest.raises(OSError):
        _run(c, folders, orca, dirs, install=crashing_install)
    assert sync.marker_path(dirs).exists()
    data = json.loads((orca.user_filament / f"{N}.json").read_text())
    data["filament_flow_ratio"] = ["0.9"]                       # edited in Orca after the crash
    (orca.user_filament / f"{N}.json").write_text(json.dumps(data))
    c.calls.clear()
    _run(c, folders, orca, dirs, now=T0 + 60)
    assert not sync.marker_path(dirs).exists()
    assert "edited in Orca Slicer since" in _log(dirs)


def test_orca_too_large_does_not_stop_the_bambu_sync(env, monkeypatch):
    folders, orca, dirs = env
    st = _state(folders, orca)
    st.update(live_hash=None, orca_live_hash=None)
    c = OrcaClient(st)
    real = sync.zips.pack

    def pack(root, max_bytes=None):
        if root == orca.user_filament:
            raise sync.zips.TooLarge(f"{root} is too large to upload")
        return real(root, max_bytes)

    monkeypatch.setattr(sync.zips, "pack", pack)
    assert _run(c, folders, orca, dirs) == "uploaded"
    assert _uploads(c) == ["live"]
    assert "Orca Slicer not synced this run" in _log(dirs)


def test_orca_live_upload_names_the_partial_build(env):
    folders, orca, dirs = env
    st = _state(folders, orca)
    st.update(live_hash=None, orca_live_hash=None)
    c = OrcaClient(st)
    sync._save_state(dirs, {"partial": {"stamp": STAMP, "at": T0}})
    _run(c, folders, orca, dirs)
    assert ("upload", "orca_live", None, STAMP) in c.calls
    assert ("upload", "live", folders.user_id, STAMP) in c.calls


def test_orca_unreadable_opc_does_not_stop_the_bambu_sync(env, monkeypatch):
    folders, orca, dirs = env
    st = _state(folders, orca)
    st.update(live_hash=None, orca_system_hash=None)
    c = OrcaClient(st)

    def broken(opc):
        raise PermissionError(13, "Permission denied", str(opc))

    monkeypatch.setattr(sync.zips, "library_index", broken)
    assert _run(c, folders, orca, dirs) == "uploaded"
    assert _uploads(c) == ["live"]
    assert "Orca Slicer not synced this run" in _log(dirs) and "Permission denied" in _log(dirs)


def _matching(folders, orca):
    live, _, olive, _ = _hashes(folders, orca)
    return live, olive


def test_orca_pack_failure_skips_the_orca_install_and_backs_off(env, monkeypatch):
    """Ruling Z: the Orca live folder cannot be packed (too large): Bambu Studio installs, orca/ does not, and
    the Orca pack is not tried again for 6 h (orca_live_owed included)."""
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    st = _state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive})
    st["orca_live_hash"] = "server-has-another"
    c = OrcaClient(st, _zip(live_hash=live, orca_live_hash=olive))
    real, tries = sync.zips.pack, []

    def pack(root, max_bytes=None):
        if root == orca.user_filament:
            tries.append(root)
            raise sync.zips.TooLarge(f"{root} is too large to upload")
        return real(root, max_bytes)

    monkeypatch.setattr(sync.zips, "pack", pack)
    assert _run(c, folders, orca, dirs) == "installed"
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["215"]
    assert "Orca presets not installed this run" in _log(dirs)
    assert "orca_live" not in _uploads(c) and tries
    st2 = sync.load_state(dirs)
    st2["orca_live_owed"] = True
    sync._save_state(dirs, st2)
    tries.clear()
    c.calls.clear()
    _run(c, folders, orca, dirs, now=T0 + 60)
    assert not tries and "orca_live" not in _uploads(c)          # backed off, owed or not
    tries.clear()
    _run(c, folders, orca, dirs, now=T0 + sync.UPLOAD_BACKOFF + 61)
    assert tries                                                   # tried again after 6 h


def test_orca_upload_refused_backs_off_and_bambu_studio_still_installs(env):
    """Ruling Z: a 400 on the Orca live upload: no orca/ install, no rebuild asked for Orca, Bambu Studio
    installed; orca_live_owed never bypasses the 6 h backoff."""
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    st = _state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": "older"})
    st["orca_live_hash"] = "older"
    c = OrcaClient(st, _zip(live_hash=live, orca_live_hash="older"))
    c.st["accepted_updates"] = _all(STAMP)          # written over the existing presets
    c.fail_kind["orca_live"] = client.ApiError(400, "bad_zip", "no")
    assert _run(c, folders, orca, dirs) == "installed"
    assert not [x for x in c.calls if x[0] == "rebuild"]
    assert json.loads((folders.user_filament / "base" / "Acme PLA @BBL H2D.json").read_text())[
        "nozzle_temperature"] == ["220"]
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["215"]
    assert "Orca presets not installed this run" in _log(dirs)
    st2 = sync.load_state(dirs)
    st2["orca_live_owed"] = True
    sync._save_state(dirs, st2)
    c.st.update(installed={"stamp": STAMP})
    c.calls.clear()
    assert _run(c, folders, orca, dirs, now=T0 + 60) in ("up_to_date", "uploaded")
    assert "orca_live" not in _uploads(c)


# ---------- Ruling AB: the install report says which trees went in ----------

def test_install_report_names_both_trees(env):
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive}),
                   _zip(live_hash=live, orca_live_hash=olive))
    assert _run(c, folders, orca, dirs) == "installed"
    assert c.trees == [["base", "orca"]]


def test_install_report_names_base_only_when_orca_did_not_go_in(env):
    folders, orca, dirs = env
    live = _hashes(folders, orca)[0]
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": "older"}),
                   _zip(live_hash=live, orca_live_hash="older"))
    assert _run(c, folders, orca, dirs) == "installed"
    assert c.trees == [["base"]]


def test_resumed_install_reports_the_trees_it_was_started_with(env):
    folders, orca, dirs = env
    live = _hashes(folders, orca)[0]

    def crashing_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None, orca=None,
                         orca_running=None):
        assert orca is None                                    # started base/ only
        backup = installer._backup(folders.user_filament, dirs.backups, stamp_now)
        before_write(backup)
        raise OSError("disk full")

    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": "older"}),
                   _zip(live_hash=live, orca_live_hash="older"))
    with pytest.raises(OSError):
        _run(c, folders, orca, dirs, install=crashing_install)
    assert json.loads(sync.marker_path(dirs).read_text())["orca"] is False
    assert _run(c, folders, orca, dirs, now=T0 + 60) == "installed"
    assert c.trees == [["base"]]
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["215"]


def test_owed_report_keeps_its_trees(env):
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive}),
                   _zip(live_hash=live, orca_live_hash=olive))
    c.fail_kind = {}
    real = c.installed

    def failing(stamp, trees=None, written=None):
        raise client.ApiError(503, "unavailable", "down")

    c.installed = failing
    with pytest.raises(client.ApiError):
        _run(c, folders, orca, dirs)
    assert sync.load_state(dirs)["report_trees"] == ["base", "orca"]
    c.installed = real
    _run(c, folders, orca, dirs, now=T0 + 60)
    assert c.trees[0] == ["base", "orca"] and "report_trees" not in sync.load_state(dirs)


# ---------- B-I1: an Orca upload that was refused recovers: the installed build's Orca presets catch up ----------

def test_refused_orca_upload_recovers_and_asks_for_a_rebuild(env):
    """Orca live upload refused (400) -> the build (made from older Orca presets) is installed base/ only. After
    the backoff the upload goes through; the build is still the installed one, but its orca/ never went in and
    was not made from these Orca presets: a rebuild is asked for (not `up_to_date`), then that build installs
    both trees."""
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    st = _state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": "older"})
    st["orca_live_hash"] = "older"
    c = OrcaClient(st, _zip(live_hash=live, orca_live_hash="older"))
    c.st["accepted_updates"] = _all(STAMP)          # written over the existing presets
    c.fail_kind["orca_live"] = client.ApiError(400, "bad_zip", "no")
    assert _run(c, folders, orca, dirs) == "installed"
    assert c.trees == [["base"]]
    # recovered: the server takes the Orca upload now
    c.fail_kind = {}
    c.calls.clear()
    t = T0 + sync.UPLOAD_BACKOFF + 60
    assert _run(c, folders, orca, dirs, now=t) == "rebuild_requested"
    assert "orca_live" in _uploads(c)
    assert c.rebuild_orca[-1] == olive
    # the server builds from both live folders: both trees install
    live2 = treehash.tree_hash(folders.user_filament)
    c.st["build"] = {"stamp": "20261102-020000", "live_hash": live2, "orca_live_hash": olive}
    c.zip = _zip(stamp="20261102-020000", live_hash=live2, orca_live_hash=olive)
    c.st["accepted_updates"] = _all("20261102-020000")
    assert _run(c, folders, orca, dirs, now=t + 60) == "installed"
    assert c.trees[-1] == ["base", "orca"]
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["225"]


def test_installed_build_whose_orca_tree_did_not_go_in_installs_it_once_orca_syncs(env, monkeypatch):
    """The build was made from this PC's Orca presets, but Orca could not be synced on the run that installed it
    (pack failure): once Orca syncs again, the same build's orca/ tree is installed and reported."""
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    st = _state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive})
    st["orca_live_hash"] = "server-has-another"
    c = OrcaClient(st, _zip(live_hash=live, orca_live_hash=olive))
    c.st["accepted_updates"] = _all(STAMP)          # written over the existing presets
    real = sync.zips.pack

    def pack(root, max_bytes=None):
        if root == orca.user_filament:
            raise sync.zips.TooLarge(f"{root} is too large to upload")
        return real(root, max_bytes)

    monkeypatch.setattr(sync.zips, "pack", pack)
    assert _run(c, folders, orca, dirs) == "installed"
    assert c.trees == [["base"]]
    monkeypatch.setattr(sync.zips, "pack", real)
    c.calls.clear()
    assert _run(c, folders, orca, dirs, now=T0 + sync.UPLOAD_BACKOFF + 60) == "installed"
    assert c.trees[-1] == ["base", "orca"]
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["225"]
    # and then it is settled: no rebuild, no further install
    c.st["orca_live_hash"] = treehash.tree_hash(orca.user_filament)
    c.calls.clear()
    assert _run(c, folders, orca, dirs, now=T0 + sync.UPLOAD_BACKOFF + 120) in ("up_to_date", "uploaded")
    assert not [x for x in c.calls if x[0] in ("rebuild", "installed")]


def test_catch_up_of_a_build_without_an_orca_tree_happens_once(env, monkeypatch):
    """A build made from these Orca presets that has no orca/ tree (no Orca printers yet): the catch-up installs it
    once with Orca considered, then the build counts as settled (no install on every run)."""
    folders, orca, dirs = env
    live, olive = _matching(folders, orca)
    st = _state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": olive})
    st["orca_live_hash"] = "server-has-another"
    c = OrcaClient(st, _zip(live_hash=live, orca_live_hash=olive, orca={}))
    real = sync.zips.pack

    def pack(root, max_bytes=None):
        if root == orca.user_filament:
            raise sync.zips.TooLarge(f"{root} is too large to upload")
        return real(root, max_bytes)

    monkeypatch.setattr(sync.zips, "pack", pack)
    assert _run(c, folders, orca, dirs) == "installed"
    monkeypatch.setattr(sync.zips, "pack", real)
    t = T0 + sync.UPLOAD_BACKOFF + 60
    assert _run(c, folders, orca, dirs, now=t) == "installed"          # the catch-up, Orca considered
    c.st["orca_live_hash"] = treehash.tree_hash(orca.user_filament)
    c.calls.clear()
    assert _run(c, folders, orca, dirs, now=t + 60) in ("up_to_date", "uploaded")
    assert not [x for x in c.calls if x[0] in ("installed", "build")]
