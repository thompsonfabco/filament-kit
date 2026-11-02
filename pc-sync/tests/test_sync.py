import hashlib
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
        self.hash_override = {}

    def _maybe_fail(self, name):
        exc = self.fail.get(name)
        if exc is not None:
            raise exc

    def state(self):
        self.calls.append(("state",))
        self._maybe_fail("state")
        return json.loads(json.dumps(self.st))

    def upload(self, kind, data, user_id=None, partial=None):
        self.calls.append(("upload", kind, user_id) + ((partial,) if partial else ()))
        self._maybe_fail("upload")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            h = hashlib.sha256()
            for n in sorted(names):
                h.update(n.encode() + b"\0" + hashlib.sha256(zf.read(n)).digest())
        self.st[f"{kind}_hash"] = self.hash_override.get(kind) or h.hexdigest()
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
    assert names == ["state", "build", "installed", "upload"]       # the report first (fix round 1)
    assert c.calls[2] == ("installed", STAMP)
    assert c.calls[3] == ("upload", "live", folders.user_id)
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

    def fake_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None):
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

    def fake_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None):
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

    def fake_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None):
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

    def crashing_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None):
        calls.append(build_dir)
        before_write(installer._backup(folders.user_filament, dirs.backups, stamp_now))
        # one preset written, then the disk fails before the snapshot swap
        (folders.user_filament / "base" / "Acme PLA @BBL H2D.json").write_bytes(
            (build_dir / "base" / "Acme PLA @BBL H2D.json").read_bytes())
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
    assert c.calls[-2:] == [("installed", STAMP), ("upload", "live", folders.user_id)]
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
    # round 3: the live upload the install owed follows the report, even with equal hashes
    assert out == "uploaded"
    names = [x[0] for x in c.calls]
    assert names.index("installed") < names.index("upload")


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


def test_resume_refused_when_a_new_preset_was_edited_after_the_crash(env):
    folders, dirs = env
    live = _hashes(folders)[0]
    new_name = "Acme PETG @BBL H2D"
    presets = {"Acme PLA @BBL H2D": dict(PRESET, nozzle_temperature=["220"]),
               new_name: dict(PRESET, name=new_name, filament_type=["PETG"], filament_id="P7654321")}

    def crashing_install(build_dir, folders, dirs, *, running, stamp_now, before_write=None):
        before_write(installer._backup(folders.user_filament, dirs.backups, stamp_now))
        # the preset that is new in this build is written, then the disk fails
        (folders.user_filament / "base" / f"{new_name}.json").write_bytes(
            (build_dir / "base" / f"{new_name}.json").read_bytes())
        raise OSError("disk full")

    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}),
                   _build_zip(live_hash=live, presets=presets))
    with pytest.raises(OSError):
        _run(c, folders, dirs, install=crashing_install)
    marker = json.loads(sync.marker_path(dirs).read_text())
    assert marker["stamp"] == STAMP and (dirs.backups / marker["backup"]).is_dir()
    # edited in Bambu Studio before the next run
    target = folders.user_filament / "base" / f"{new_name}.json"
    edited = dict(presets[new_name], nozzle_temperature=["245"])
    target.write_text(json.dumps(edited), encoding="utf-8")
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 600) == "rebuild_requested"
    assert json.loads(target.read_text(encoding="utf-8")) == edited
    assert not sync.marker_path(dirs).exists()
    here = _hashes(folders)[0]
    assert ("upload", "live", folders.user_id, STAMP) in c.calls and ("rebuild", here) in c.calls
    assert not [x for x in c.calls if x[0] == "installed"]
    assert "edited" in _log(dirs)
    # ruling S28: the half-installed build is kept as dirs.partial and named in every live upload until an install
    assert json.loads(dirs.state.read_text())["partial"]["stamp"] == STAMP
    assert json.loads((dirs.partial / "BUILD.json").read_text())["stamp"] == STAMP
    assert (dirs.partial / "base" / f"{new_name}.json").is_file()
    target.write_text(json.dumps(dict(edited, nozzle_temperature=["246"])), encoding="utf-8")
    c.calls.clear()
    _run(c, folders, dirs, now=T0 + 2000)
    assert ("upload", "live", folders.user_id, STAMP) in c.calls
    # the rebuilt build carrying the edit installs; the partial build is then forgotten
    here = _hashes(folders)[0]
    rebuilt = {**presets, new_name: json.loads(target.read_text(encoding="utf-8"))}
    stamp2 = "20261102-020000"
    c.st["build"] = {"stamp": stamp2, "live_hash": here}
    c.zip = _build_zip(stamp=stamp2, live_hash=here, presets=rebuilt)
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 3000) == "installed"
    assert "partial" not in json.loads(dirs.state.read_text()) and not dirs.partial.exists()
    uploads = [x for x in c.calls if x[0] == "upload"]
    assert uploads == [("upload", "live", folders.user_id)]


def test_failed_report_skips_the_live_upload_and_is_sent_first_next_run(env):
    """Fix round 1: the post-install live upload only follows a recorded install, so the server never holds the
    new live folder next to the old installed snapshot."""
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    c.fail["installed"] = client.Offline("server unreachable")
    with pytest.raises(client.Offline):
        _run(c, folders, dirs)
    assert not [x for x in c.calls if x[0] == "upload"]
    c.fail.clear()
    c.calls.clear()
    _run(c, folders, dirs, now=T0 + 600)
    names = [x[0] for x in c.calls]
    assert ("installed", STAMP) in c.calls and "upload" in names
    assert names.index("installed") < names.index("upload")


def test_live_upload_owed_after_an_install_is_sent_even_when_the_hashes_match(env):
    """Round 3: the report went through, the re-upload failed; the next run must send live although the server's
    hash equals this PC's (the install left the folder byte-identical), or the server waits forever (S32)."""
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    c.fail["upload"] = client.Offline("server unreachable")
    with pytest.raises(client.Offline):
        _run(c, folders, dirs)
    assert ("installed", STAMP) in c.calls
    assert json.loads(dirs.state.read_text())["live_owed"] is True
    c.fail.clear()
    c.st["live_hash"] = _hashes(folders)[0]                  # equal hashes: no upload would be "needed"
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 600) == "uploaded"
    assert ("upload", "live", folders.user_id) in c.calls
    assert "live_owed" not in json.loads(dirs.state.read_text())
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 1200) == "up_to_date"
    assert not [x for x in c.calls if x[0] == "upload"]


def test_studio_info_rewrites_and_own_presets_do_not_ask_for_a_rebuild(env):
    """Ruling S31: only a generated preset that differs from dirs.installed (inapp.diff) or is gone asks for one."""
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    assert _run(c, folders, dirs) == "installed"
    base = folders.user_filament / "base"
    (base / "Acme PLA @BBL H2D.info").write_text("sync_info = update\nsetting_id = PFUS9\nupdated_time = 9\n",
                                                  encoding="utf-8")
    (base / "My own PETG.json").write_text(json.dumps(dict(PRESET, name="My own PETG")), encoding="utf-8")
    cfg = json.loads((base / "Acme PLA @BBL H2D.json").read_text(encoding="utf-8"))
    cfg["updated_time"] = "12345"                                       # bookkeeping only (inapp.IGNORE)
    (base / "Acme PLA @BBL H2D.json").write_text(json.dumps(cfg), encoding="utf-8")
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 60) == "uploaded"            # the server gets the folder, no rebuild
    assert not [x for x in c.calls if x[0] == "rebuild"]
    (base / "Acme PLA @BBL H2D.json").unlink()                          # deleted in the app: a rebuild
    assert _run(c, folders, dirs, now=T0 + 120) == "rebuild_requested"


def test_rebuild_requested_after_an_inapp_edit_of_the_installed_build(env):
    """Ruling S29b: the installed build is current, but the live folder changed since the install."""
    folders, dirs = env
    live = _hashes(folders)[0]
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _build_zip(live_hash=live))
    assert _run(c, folders, dirs) == "installed"
    c.st["live_hash"] = _hashes(folders)[0]
    assert _run(c, folders, dirs, now=T0 + 60) == "up_to_date"           # the install's own writes: no rebuild
    target = folders.user_filament / "base" / "Acme PLA @BBL H2D.json"
    target.write_text(json.dumps(dict(PRESET, nozzle_temperature=["230"])), encoding="utf-8")
    here = _hashes(folders)[0]
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 120) == "rebuild_requested"
    assert ("upload", "live", folders.user_id) in c.calls and ("rebuild", here) in c.calls
    c.calls.clear()
    assert _run(c, folders, dirs, now=T0 + 600) == "waiting"             # rate-limited as today
    assert not [x for x in c.calls if x[0] == "rebuild"]
    assert _run(c, folders, dirs, now=T0 + 120 + 15 * 60 + 1) == "rebuild_requested"


def test_rejected_upload_backs_off_6h_for_the_same_hash(env):
    folders, dirs = env
    st = _synced_state(folders)
    st["live_hash"] = None
    c = FakeClient(st)
    c.fail["upload"] = client.ApiError(413, "too_large", "live zip over 32 MiB")
    assert _run(c, folders, dirs) == "no_build"
    rec = json.loads(dirs.state.read_text())["rejected"]["live"]
    assert rec == {"kind": "live", "hash": _hashes(folders)[0], "at": T0,
                   "error": "413 too_large: live zip over 32 MiB"}
    assert "413" in _log(dirs)

    def n():
        return len([x for x in c.calls if x[0] == "upload"])

    assert n() == 1
    _run(c, folders, dirs, now=T0 + 3600)
    assert n() == 1                                   # same hash, within 6 h: not sent again
    _run(c, folders, dirs, now=T0 + sync.UPLOAD_BACKOFF + 1)
    assert n() == 2                                   # after 6 h: tried again
    # a changed folder is tried at once
    (folders.user_filament / "base" / "Extra.json").write_text("{}", encoding="utf-8")
    _run(c, folders, dirs, now=T0 + sync.UPLOAD_BACKOFF + 60)
    assert n() == 3
    c.fail.clear()
    (folders.user_filament / "base" / "Extra2.json").write_text("{}", encoding="utf-8")
    _run(c, folders, dirs, now=T0 + sync.UPLOAD_BACKOFF + 120)
    assert n() == 4
    assert "live" not in json.loads(dirs.state.read_text()).get("rejected", {})


def test_upload_backoff_is_6_hours():
    assert sync.UPLOAD_BACKOFF == 6 * 3600


def test_server_hash_differs_logged_once_not_reuploaded_and_accepted(env):
    folders, dirs = env
    st = _synced_state(folders)
    st["live_hash"] = None
    c = FakeClient(st)
    c.hash_override["live"] = "f" * 64
    _run(c, folders, dirs)
    _run(c, folders, dirs, now=T0 + 60)
    assert len([x for x in c.calls if x == ("upload", "live", folders.user_id)]) == 1
    assert len([ln for ln in _log(dirs).splitlines() if "differs" in ln]) == 1
    # a build the server made from that upload is installable
    c.st["build"] = {"stamp": STAMP, "live_hash": "f" * 64}
    c.zip = _build_zip(live_hash="f" * 64)
    assert _run(c, folders, dirs, now=T0 + 120) == "installed"


def test_other_owner_short_circuits_before_sending(env):
    folders, dirs = env
    st = _synced_state(folders)
    st.update(owner="other-pc", you="dev1", live_hash=None)
    c = FakeClient(st)
    assert _run(c, folders, dirs) == "other_pc"
    assert c.calls == [("state",)]
