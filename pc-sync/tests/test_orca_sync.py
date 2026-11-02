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


def _state(folders, orca, build=None, installed=None, orca_keys=True):
    live, system, olive, osys = _hashes(folders, orca)
    st = {"owner": "dev1", "you": "dev1", "user_id": folders.user_id, "live_hash": live, "system_hash": system,
          "build": build, "last_attempt": None, "installed": installed, "rebuild_requested": None}
    if orca_keys:
        st.update(orca_live_hash=olive, orca_system_hash=osys)
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
    assert c.calls == []
    assert "Orca Slicer is open" in _log(dirs)


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
    assert _run(c, folders, orca, dirs) == "installed"
    assert json.loads((orca.user_filament / f"{N}.json").read_text())["nozzle_temperature"] == ["225"]
    names = [x[:2] for x in c.calls]
    assert names[-3:] == [("installed", STAMP), ("upload", "live"), ("upload", "orca_live")]
    assert (dirs.installed / "orca" / f"{N}.json").is_file()
    assert "Orca Slicer" in _log(dirs)


def test_orca_live_newer_than_build_asks_for_rebuild(env):
    folders, orca, dirs = env
    live = _hashes(folders, orca)[0]
    c = OrcaClient(_state(folders, orca, build={"stamp": STAMP, "live_hash": live, "orca_live_hash": "older"}),
                   _zip(live_hash=live))
    assert _run(c, folders, orca, dirs) == "rebuild_requested"
    assert ("rebuild", live) in c.calls and not [x for x in c.calls if x[0] == "build"]


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
