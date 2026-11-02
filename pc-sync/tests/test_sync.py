import io
import json
import zipfile

import pytest

import studio_fixture
from fksync import client, installer, store, sync, treehash

STAMP = "20261102-010203"
T0 = 1_800_000_000.0

PRESET = {"type": "filament", "name": "Acme PLA @BBL H2D", "inherits": "", "from": "User",
          "filament_id": "P1234567", "filament_type": ["PLA"], "nozzle_temperature": ["215"]}
INFO = {"sync_info": "", "user_id": "", "setting_id": "", "base_id": "", "updated_time": "0"}


def _build_zip(stamp=STAMP, live_hash=None, presets=None) -> bytes:
    presets = presets or {"Acme PLA @BBL H2D": dict(PRESET, nozzle_temperature=["220"])}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BUILD.json", json.dumps({"stamp": stamp, "live_hash": live_hash, "stale": []}))
        for name, data in presets.items():
            zf.writestr(f"base/{name}.json", json.dumps(data, indent=4))
            zf.writestr(f"base/{name}.info", "sync_info = \nsetting_id = \n")
    return buf.getvalue()


class FakeClient:
    def __init__(self, state, build_zip=None):
        self.st = state
        self.zip = build_zip
        self.calls = []
        self.fail = {}

    def _maybe_fail(self, name):
        exc = self.fail.get(name)
        if exc is not None:
            raise exc

    def state(self):
        self.calls.append(("state",))
        self._maybe_fail("state")
        return json.loads(json.dumps(self.st))

    def upload(self, kind, data, user_id=None):
        self.calls.append(("upload", kind, user_id))
        self._maybe_fail("upload")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        self.st[f"{kind}_hash"] = f"uploaded:{len(names)}"
        self.uploaded = getattr(self, "uploaded", {})
        self.uploaded[kind] = names
        return {f"{kind}_hash": self.st[f"{kind}_hash"]}

    def rebuild(self, live_hash):
        self.calls.append(("rebuild", live_hash))
        self._maybe_fail("rebuild")
        return {"requested": True}

    def build(self, stamp):
        self.calls.append(("build", stamp))
        self._maybe_fail("build")
        return self.zip

    def installed(self, stamp):
        self.calls.append(("installed", stamp))
        self._maybe_fail("installed")
        self.st["installed"] = {"stamp": stamp, "at": 1}
        return {"installed": {"stamp": stamp, "at": 1}}


@pytest.fixture
def env(tmp_path):
    folders = studio_fixture.make(tmp_path / "appdata", base={"Acme PLA @BBL H2D": (PRESET, INFO)})
    dirs = store.AppDirs(tmp_path / "local" / "filament-kit-sync")
    dirs.ensure()
    return folders, dirs


def _hashes(folders):
    return treehash.tree_hash(folders.user_filament), treehash.tree_hash(folders.system_filament)


def _synced_state(folders, build=None, installed=None):
    live, system = _hashes(folders)
    return {"owner": "dev1", "you": "dev1", "user_id": folders.user_id, "live_hash": live, "system_hash": system,
            "build": build, "last_attempt": None, "installed": installed, "rebuild_requested": None}


def _log(dirs):
    return dirs.log_file.read_text(encoding="utf-8") if dirs.log_file.exists() else ""


def _run(c, folders, dirs, now=T0, running=lambda: False, **kw):
    return sync.run_once(c, folders, dirs, running=running, now=now, **kw)


def test_studio_running_no_client_call(env):
    folders, dirs = env
    c = FakeClient(_synced_state(folders))
    assert _run(c, folders, dirs, running=lambda: True) == "studio_running"
    assert c.calls == []
    assert "studio_running" in _log(dirs)


def test_hash_mismatch_uploads_then_no_build(env):
    folders, dirs = env
    st = _synced_state(folders)
    st.update(live_hash=None, system_hash="old")
    c = FakeClient(st)
    assert _run(c, folders, dirs) == "uploaded"
    assert ("upload", "live", folders.user_id) in c.calls
    assert ("upload", "system", None) in c.calls
    assert "base/Acme PLA @BBL H2D.json" in c.uploaded["live"]
    assert "Generic PLA @BBL H2D.json" in c.uploaded["system"]
    # the server now has both trees; still no build
    c.st.update(live_hash=_hashes(folders)[0], system_hash=_hashes(folders)[1])
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 60) == "no_build"
    assert not [x for x in c.calls if x[0] == "upload"]
    assert "no_build" in _log(dirs)


def test_no_build_asks_for_one_at_most_every_15_min(env):
    folders, dirs = env
    c = FakeClient(_synced_state(folders))
    live = _hashes(folders)[0]
    assert _run(c, folders, dirs) == "no_build"
    assert c.calls.count(("rebuild", live)) == 1
    assert _run(c, folders, dirs, now=T0 + 600) == "no_build"
    assert c.calls.count(("rebuild", live)) == 1
    assert _run(c, folders, dirs, now=T0 + 901) == "no_build"
    assert c.calls.count(("rebuild", live)) == 2


def test_build_for_other_live_hash_rebuild_then_waiting(env):
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": "older", "created": 1,
                                                 "presets": 1, "problems": 0}))
    assert _run(c, folders, dirs) == "rebuild_requested"
    assert c.calls.count(("rebuild", live)) == 1
    assert json.loads(dirs.state.read_text())["requested"] == {"live_hash": live, "at": T0}
    assert _run(c, folders, dirs, now=T0 + 14 * 60) == "waiting"
    assert c.calls.count(("rebuild", live)) == 1
    assert _run(c, folders, dirs, now=T0 + 15 * 60 + 1) == "rebuild_requested"
    assert c.calls.count(("rebuild", live)) == 2
    assert not [x for x in c.calls if x[0] in ("build", "installed")]
    log = _log(dirs)
    assert "rebuild_requested" in log and "waiting" in log


def test_matching_build_installs_reuploads_and_reports(env):
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live, "created": 1,
                                                 "presets": 1, "problems": 0}), _build_zip(live_hash=live))
    assert _run(c, folders, dirs) == "installed"
    names = [x[0] for x in c.calls]
    assert names == ["state", "build", "upload", "installed"]
    assert c.calls[2] == ("upload", "live", folders.user_id)
    assert c.calls[3] == ("installed", STAMP)
    got = json.loads((folders.user_filament / "base" / "Acme PLA @BBL H2D.json").read_text(encoding="utf-8"))
    assert got["nozzle_temperature"] == ["220"]
    assert json.loads((dirs.installed / "BUILD.json").read_text())["stamp"] == STAMP
    assert len(list(dirs.backups.iterdir())) == 1
    assert not sync.marker_path(dirs).exists()
    state = json.loads(dirs.state.read_text())
    assert state["last"]["outcome"] == "installed"
    assert f"installed build {STAMP}" in _log(dirs)
    # next run: the server has the re-uploaded live tree and the install recorded
    c.st["live_hash"] = _hashes(folders)[0]
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 600) == "up_to_date"
    assert [x[0] for x in c.calls] == ["state"]


def test_backup_stamp_sorts_by_time(env, monkeypatch):
    folders, dirs = env
    seen = []

    def fake_install(build_dir, folders, dirs, *, running, stamp_now):
        seen.append(stamp_now)
        raise installer.Refused("nope")

    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    _run(c, folders, dirs, install=fake_install)
    import time
    assert seen == [time.strftime("%Y%m%d-%H%M%S", time.localtime(T0))]


def test_stale_presets_logged_one_line(env):
    folders, dirs = env
    live = _hashes(folders)[0]

    def fake_install(build_dir, folders, dirs, *, running, stamp_now):
        return installer.InstallResult(installed=["X"], stale=["Old A", "Old B"], backup=dirs.backups / "b")

    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    assert _run(c, folders, dirs, install=fake_install) == "installed"
    lines = [ln for ln in _log(dirs).splitlines() if "Old A" in ln]
    assert len(lines) == 1 and "Old B" in lines[0] and "delete" in lines[0].lower()
    assert json.loads(dirs.state.read_text())["stale"] == ["Old A", "Old B"]


@pytest.mark.parametrize("code,outcome", [("untrusted_gcode", "refused"), ("stale_build", "refused"),
                                          ("refused", "refused"), ("studio_running", "studio_running")])
def test_refused(env, code, outcome):
    folders, dirs = env
    live = _hashes(folders)[0]

    def fake_install(build_dir, folders, dirs, *, running, stamp_now):
        raise installer.Refused(f"because reason-{code}", code)

    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    assert _run(c, folders, dirs, install=fake_install) == outcome
    assert not [x for x in c.calls if x[0] == "installed"]
    if outcome == "refused":
        assert f"because reason-{code}" in _log(dirs)
    assert not sync.marker_path(dirs).exists()


def test_build_json_for_other_hash_is_refused(env):
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash="other"))
    assert _run(c, folders, dirs) == "refused"
    assert not [x for x in c.calls if x[0] == "installed"]


@pytest.mark.parametrize("where", ["state", "upload", "rebuild", "installed"])
def test_other_pc(env, where):
    folders, dirs = env
    live = _hashes(folders)[0]
    st = _synced_state(folders, build={"stamp": STAMP, "live_hash": "x" if where == "rebuild" else live})
    if where == "upload":
        st["live_hash"] = None
    c = FakeClient(st, _build_zip(live_hash=live))
    c.fail[where] = client.ApiError(409, "other_pc", "another PC is the sync PC")
    assert _run(c, folders, dirs) == "other_pc"
    assert "other_pc" in _log(dirs)


def test_unexpected_install_oserror_propagates_then_next_run_finishes(env):
    folders, dirs = env
    live = _hashes(folders)[0]
    calls = []

    def crashing_install(build_dir, folders, dirs, *, running, stamp_now):
        calls.append(build_dir)
        # one preset written, then the disk fails before the snapshot swap
        (folders.user_filament / "base" / "Acme PLA @BBL H2D.json").write_text(
            (build_dir / "base" / "Acme PLA @BBL H2D.json").read_text(encoding="utf-8"), encoding="utf-8")
        raise OSError("disk full")

    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    with pytest.raises(OSError):
        _run(c, folders, dirs, install=crashing_install)
    assert sync.marker_path(dirs).exists()
    assert not [x for x in c.calls if x[0] == "installed"]
    # the live folder is now ahead of the build's live hash; the marker makes the next run finish the install
    assert _hashes(folders)[0] != live
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 600) == "installed"
    assert ("rebuild", _hashes(folders)[0]) not in c.calls
    assert c.calls[-1] == ("installed", STAMP)
    assert not sync.marker_path(dirs).exists()
    assert "interrupted" in _log(dirs)


def test_report_retried_when_installed_call_failed(env):
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    c.fail["installed"] = client.Offline("server unreachable")
    with pytest.raises(client.Offline):
        _run(c, folders, dirs)
    assert not sync.marker_path(dirs).exists()  # the presets are in; only the report is pending
    c.fail.clear()
    c.st["live_hash"] = _hashes(folders)[0]
    c.calls.clear()
    out = _run(c, folders, dirs, now=T0 + 600)
    assert ("installed", STAMP) in c.calls
    assert not [x for x in c.calls if x[0] == "build"]  # not installed a second time
    assert out == "up_to_date"


def test_too_large_upload_is_refused_before_sending(env, monkeypatch):
    folders, dirs = env
    st = _synced_state(folders)
    st["live_hash"] = None
    c = FakeClient(st)
    monkeypatch.setattr(sync, "LIVE_MAX", 10)
    with pytest.raises(sync.zips.TooLarge) as ei:
        _run(c, folders, dirs)
    assert "too large" in str(ei.value)
    assert not [x for x in c.calls if x[0] == "upload"]
