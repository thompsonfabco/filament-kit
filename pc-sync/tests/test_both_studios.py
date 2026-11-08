"""PCBOTH: the PC sync keeps every Bambu Studio folder of this PC current (the primary, the one the server builds
from, and each secondary: stable and Beta), never replaces an existing preset in any of them, handles a change of
primary as that folder's first sync, and makes a wait for a running Bambu Studio visible (state, status, log, a
heartbeat to the server). All folders are fakes under tmp_path."""
import json
import os
import time

import pytest

import studio_fixture
from fksync import client, installer, store, studio, sync, treehash
from test_sync import INFO, PRESET, STAMP, T0, FakeClient, _build_zip

UID = "1234567890"
A, B = "Acme PLA @BBL H2D", "Acme PLA @BBL H2D 0.6 nozzle"
NEW = "Acme PLA @BBL H2D 0.8 nozzle"
BETA_KEY = f"BambuStudioBeta-{UID}"
STAMP2 = "20261103-010203"


class Client2(FakeClient):
    def __init__(self, state, build_zip=None):
        super().__init__(state, build_zip)
        self.beats = []
        self.fresh_ok = True

    def upload(self, kind, data, user_id=None, partial=None, fresh=False):
        res = super().upload(kind, data, user_id, partial)
        if fresh:
            self.calls[-1] = self.calls[-1] + ("fresh",)
            self.st["installed"] = None             # as the server: that folder's first sync
            if self.fresh_ok:
                res["fresh"] = True
        return res

    def heartbeat(self, outcome, waiting_since=None, app=None):
        self.calls.append(("heartbeat", outcome))
        self._maybe_fail("heartbeat")
        self.beats.append({"outcome": outcome, "waiting_since": waiting_since, "app": app})
        return {"ok": True}


def _p(name, **kw):
    return dict(PRESET, name=name, **kw)


def _zip(stamp=STAMP, live_hash=None, presets=None):
    return _build_zip(stamp, live_hash, presets or {A: _p(A, nozzle_temperature=["220"]), NEW: _p(NEW)})


@pytest.fixture
def two(tmp_path):
    """stable (the primary: newest conf) and Beta (a secondary), both with an older A."""
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id=UID, base={A: (_p(A), INFO)})
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id=UID,
                               base={A: (_p(A, nozzle_temperature=["230"]), INFO)})
    _older(beta.root / "BambuStudio.conf")
    dirs = store.AppDirs(tmp_path / "local" / "filament-kit-sync")
    dirs.ensure()
    return stable, beta, dirs


def _older(path, seconds=3600):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _live(f):
    return treehash.tree_hash(f.user_filament)


def _state(f, build=None, installed=None):
    return {"owner": "dev1", "you": "dev1", "user_id": f.user_id, "live_hash": _live(f),
            "system_hash": treehash.tree_hash(f.system_filament), "build": build, "last_attempt": None,
            "installed": installed, "rebuild_requested": None}


def _run(c, f, dirs, others=(), now=T0, running=lambda: False, **kw):
    return sync.run_once(c, f, dirs, running=running, now=now, others=list(others), **kw)


def _log(dirs):
    return dirs.log_file.read_text(encoding="utf-8") if dirs.log_file.exists() else ""


def _sec(dirs, key=BETA_KEY):
    return store.AppDirs(dirs.base / "folders" / key)


def _bs(f, name):
    return json.loads((f.user_filament / "base" / f"{name}.json").read_text(encoding="utf-8"))


def _build(stamp, f):
    return {"stamp": stamp, "live_hash": _live(f), "created": 1, "presets": 2, "problems": 0}


# --- R1: primary + secondary install -------------------------------------------------------------

def test_install_goes_into_the_primary_and_each_secondary(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs, [beta]) == "installed"
    # the server only hears about the primary: one build download, one report, one live upload (stable's)
    assert [x[0] for x in c.calls] == ["state", "build", "installed", "upload"]
    assert c.calls[3] == ("upload", "live", UID)
    for f in (stable, beta):
        assert _bs(f, NEW) == _p(NEW)
    sd = _sec(dirs)
    assert json.loads((sd.installed / "BUILD.json").read_text())["stamp"] == STAMP
    assert len(list(sd.backups.iterdir())) == 1 and len(list(dirs.backups.iterdir())) == 1
    assert not sync.marker_path(sd).exists()
    rec = sync.load_state(sd)
    assert rec["installed"]["stamp"] == STAMP and rec["variant"] == "BambuStudioBeta" and rec["user_id"] == UID
    assert f"installed build {STAMP} into BambuStudioBeta user {UID}" in _log(dirs)


def test_a_later_up_to_date_run_catches_a_secondary_up(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs) == "installed"                         # Beta not there yet (or not usable)
    assert not (beta.user_filament / "base" / f"{NEW}.json").exists()
    c.st["live_hash"] = _live(stable)
    c.calls.clear()
    assert _run(c, stable, dirs, [beta], now=T0 + 600) == "up_to_date"
    assert [x[0] for x in c.calls] == ["state", "build"]                 # no upload, no rebuild, no report
    assert _bs(beta, NEW) == _p(NEW)
    c.calls.clear()
    assert _run(c, stable, dirs, [beta], now=T0 + 1200) == "up_to_date"
    assert [x[0] for x in c.calls] == ["state"]                          # Beta has it: nothing downloaded


# --- R2: never replace, accepted updates everywhere ----------------------------------------------

def test_secondary_never_replaces_and_lists_what_differs(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs, [beta]) == "installed"
    assert _bs(beta, A)["nozzle_temperature"] == ["230"] and _bs(stable, A)["nozzle_temperature"] == ["215"]
    lines = [ln for ln in _log(dirs).splitlines() if "differ from build" in ln]
    assert len(lines) == 2                                                # one per folder
    assert any(f"BambuStudioBeta user {UID}" in ln and f"1 presets" in ln and A in ln for ln in lines)
    assert sync.load_state(_sec(dirs))["differing"] == [A]
    assert sync.load_state(dirs)["differing"] == [A]


def test_accepted_updates_are_written_into_both(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [A]}
    assert _run(c, stable, dirs, [beta]) == "installed"
    assert _bs(stable, A)["nozzle_temperature"] == ["220"] and _bs(beta, A)["nozzle_temperature"] == ["220"]
    assert sync.load_state(_sec(dirs)).get("differing") == []


def test_updates_accepted_after_the_install_reach_the_secondary_too(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs, [beta]) == "installed"
    c.st["live_hash"] = _live(stable)
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [A]}            # sudo filament-kit profiles apply-updates
    assert _run(c, stable, dirs, [beta], now=T0 + 600) == "installed"
    assert _bs(stable, A)["nozzle_temperature"] == ["220"] and _bs(beta, A)["nozzle_temperature"] == ["220"]


def test_accepted_updates_are_owed_to_a_secondary_that_failed(two):
    stable, beta, dirs = two
    boom = {"n": 1}

    def flaky(build_dir, folders, d, **kw):
        if folders.variant == "BambuStudioBeta" and boom["n"]:
            boom["n"] -= 1
            raise OSError("disk full")
        return installer.install(build_dir, folders, d, **kw)

    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [A]}
    assert _run(c, stable, dirs, [beta], install=flaky) == "installed"
    assert _bs(beta, A)["nozzle_temperature"] == ["230"]
    assert c.st["accepted_updates"]["base"] == []                       # the server took the primary's report
    c.st["live_hash"] = _live(stable)
    assert _run(c, stable, dirs, [beta], now=T0 + 600, install=flaky) == "up_to_date"
    assert _bs(beta, A)["nozzle_temperature"] == ["220"]                 # still written: it was owed
    assert "owed_accept" not in sync.load_state(_sec(dirs))


# --- R1: a secondary never blocks the primary ----------------------------------------------------

def test_a_failed_secondary_does_not_block_the_primary(two):
    stable, beta, dirs = two

    def broken(build_dir, folders, d, **kw):
        if folders.variant == "BambuStudioBeta":
            raise installer.Refused("could not back up the Beta folder", "refused")
        return installer.install(build_dir, folders, d, **kw)

    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs, [beta], install=broken) == "installed"
    assert [x[0] for x in c.calls] == ["state", "build", "installed", "upload"]
    assert _bs(stable, NEW) == _p(NEW)
    rec = sync.load_state(_sec(dirs))
    assert "could not back up" in rec["error"] and "installed" not in rec
    assert "BambuStudioBeta" in _log(dirs) and "could not back up" in _log(dirs)
    # retried next run
    c.st["live_hash"] = _live(stable)
    assert _run(c, stable, dirs, [beta], now=T0 + 600) == "up_to_date"
    rec = sync.load_state(_sec(dirs))
    assert rec["installed"]["stamp"] == STAMP and "error" not in rec


def test_an_interrupted_secondary_install_is_resumed(two):
    stable, beta, dirs = two
    calls = []

    def crash(build_dir, folders, d, **kw):
        if folders.variant == "BambuStudioBeta" and not calls:
            calls.append(1)
            kw["before_write"](d.backups / "x")       # the marker is written, then the PC loses power
            raise OSError("power cut")
        return installer.install(build_dir, folders, d, **kw)

    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [A]}
    assert _run(c, stable, dirs, [beta], install=crash) == "installed"
    m = json.loads(sync.marker_path(_sec(dirs)).read_text())
    assert m["stamp"] == STAMP and m["accept"] == {"base": [A]}
    c.st["live_hash"] = _live(stable)
    assert _run(c, stable, dirs, [beta], now=T0 + 600, install=crash) == "up_to_date"
    assert not sync.marker_path(_sec(dirs)).exists()
    assert _bs(beta, A)["nozzle_temperature"] == ["220"] and _bs(beta, NEW) == _p(NEW)
    assert "interrupted install" in _log(dirs)


# --- R1: secondaries: false -----------------------------------------------------------------------

def test_without_secondaries_only_the_primary_is_written(two):
    stable, beta, dirs = two
    before = {p.name: p.read_bytes() for p in (beta.user_filament / "base").iterdir()}
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs, [beta], secondaries=False) == "installed"
    assert [x[0] for x in c.calls] == ["state", "build", "installed", "upload"]
    assert {p.name: p.read_bytes() for p in (beta.user_filament / "base").iterdir()} == before
    assert not (dirs.base / "folders").exists()
    c.st["live_hash"] = _live(stable)
    c.calls.clear()
    assert _run(c, stable, dirs, [beta], now=T0 + 600, secondaries=False) == "up_to_date"
    assert [x[0] for x in c.calls] == ["state"]


def test_main_passes_no_secondaries_when_switched_off(tmp_path):
    from fksync import __main__ as cli
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id=UID)
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id=UID)
    assert cli._secondaries(appdata, {}, stable) == ([beta], True)
    assert cli._secondaries(appdata, {"secondaries": True}, stable) == ([beta], True)
    assert cli._secondaries(appdata, {"secondaries": False}, stable) == ([beta], False)


# --- R2: a change of primary ----------------------------------------------------------------------

def _installed_into_beta(two):
    """Beta was the primary and has build STAMP (made from its live presets); stable now has the newest conf."""
    stable, beta, dirs = two
    c = Client2(_state(beta, build=_build(STAMP, beta)), _zip(live_hash=_live(beta)))
    assert _run(c, beta, dirs) == "installed"                         # the single-folder PC sync of before
    assert sync.load_state(dirs)["folder"]["key"] == BETA_KEY
    return c


def test_a_primary_change_is_that_folders_first_sync(two):
    stable, beta, dirs = two
    c = _installed_into_beta(two)
    c.st["live_hash"] = _live(beta)
    c.calls.clear()
    # stable becomes the primary (newest conf); the server still has the Beta install
    out = _run(c, stable, dirs, [beta], now=T0 + 600)
    assert out == "rebuild_requested"
    ups = [x for x in c.calls if x[0] == "upload" and x[1] == "live"]
    assert ups == [("upload", "live", UID, "fresh")]                     # that folder's first sync, said so
    i = [x[0] for x in c.calls]
    assert i.index("upload") < i.index("state", 1)                       # the state is read again after it
    st = sync.load_state(dirs)
    assert st["folder"]["key"] == f"BambuStudio-{UID}" and "fresh_owed" not in st
    assert "installed" not in st and not dirs.installed.exists()         # Beta's snapshot is not stable's
    # Beta's record moved into its own secondary record, with its snapshot and backup
    sd = _sec(dirs)
    assert json.loads((sd.installed / "BUILD.json").read_text())["stamp"] == STAMP
    assert sync.load_state(sd)["installed"]["stamp"] == STAMP and list(sd.backups.iterdir())
    assert "Bambu Studio folder changed from BambuStudioBeta" in _log(dirs)
    # stable is never written by a build made from Beta's live presets
    assert not (stable.user_filament / "base" / f"{NEW}.json").exists()


def test_primary_change_back_and_forth_never_pairs_folders(two):
    stable, beta, dirs = two
    c = _installed_into_beta(two)
    c.st["live_hash"] = _live(beta)
    _run(c, stable, dirs, [beta], now=T0 + 600)
    # back to Beta: its own record comes back as its first sync again, stable's (none) goes to a record
    c.calls.clear()
    assert not (dirs.base / "folders" / f"BambuStudio-{UID}").exists()
    _run(c, beta, dirs, [stable], now=T0 + 1200)
    ups = [x for x in c.calls if x[0] == "upload" and x[1] == "live"]
    assert ups[0] == ("upload", "live", UID, "fresh") and all("fresh" not in x for x in ups[1:])
    assert sync.load_state(dirs)["folder"]["key"] == BETA_KEY
    assert (dirs.base / "folders" / f"BambuStudio-{UID}").is_dir()     # stable's (empty) record, kept apart
    # Beta's install is made again from its own live presets (the server forgot the pairing): its snapshot is Beta's
    snap = dirs.installed / "base" / f"{A}.json"
    assert not snap.exists() or json.loads(snap.read_text())["nozzle_temperature"] == ["230"]


def test_an_older_server_that_ignores_fresh_is_logged(two):
    stable, beta, dirs = two
    c = _installed_into_beta(two)
    c.fresh_ok = False
    c.st["live_hash"] = _live(beta)
    _run(c, stable, dirs, [beta], now=T0 + 600)
    assert "did not confirm" in _log(dirs)


def test_upgrade_from_a_single_folder_pc_sync_finds_where_it_installed(two):
    """An older state.json has no `folder`: the install snapshot tells which folder it belongs to."""
    stable, beta, dirs = two
    c = _installed_into_beta(two)
    st = sync.load_state(dirs)
    st.pop("folder")
    sync._save_state(dirs, st)
    c.st["live_hash"] = _live(beta)
    c.calls.clear()
    _run(c, stable, dirs, [beta], now=T0 + 600)
    assert [x for x in c.calls if x[0] == "upload" and x[1] == "live"] == [("upload", "live", UID, "fresh")]
    assert sync.load_state(_sec(dirs))["installed"]["stamp"] == STAMP


def test_upgrade_where_the_snapshot_is_the_primarys_is_adopted(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs) == "installed"
    st = sync.load_state(dirs)
    st.pop("folder")
    sync._save_state(dirs, st)
    c.st["live_hash"] = _live(stable)
    c.calls.clear()
    assert _run(c, stable, dirs, [beta], now=T0 + 600) == "up_to_date"
    assert not [x for x in c.calls if x[0] == "upload"]
    assert sync.load_state(dirs)["folder"]["key"] == f"BambuStudio-{UID}"


# --- R3: a visible wait for a running Bambu Studio ------------------------------------------------

def test_waiting_is_recorded_and_one_heartbeat_an_hour(two):
    stable, beta, dirs = two
    c = Client2(_state(stable))
    for i, now in enumerate((T0, T0 + 600, T0 + 1200)):
        assert _run(c, stable, dirs, now=now, running=lambda: True) == "studio_running"
    assert c.calls == [("heartbeat", "studio_running")]                  # nothing else, and only once
    assert c.beats == [{"outcome": "studio_running", "waiting_since": T0, "app": "Bambu Studio"}]
    w = sync.load_state(dirs)["waiting"]
    assert w == {"since": T0, "skipped_runs": 3, "app": "Bambu Studio"}
    assert _run(c, stable, dirs, now=T0 + 3600, running=lambda: True) == "studio_running"
    assert c.calls.count(("heartbeat", "studio_running")) == 2
    assert len([ln for ln in _log(dirs).splitlines() if "studio_running" in ln]) == 4    # one line per run


def test_after_a_day_the_line_is_louder(two):
    stable, beta, dirs = two
    c = Client2(_state(stable))
    _run(c, stable, dirs, now=T0, running=lambda: True)
    _run(c, stable, dirs, now=T0 + 4 * 86400 + 60, running=lambda: True)
    last = _log(dirs).splitlines()[-1]
    assert "waiting 4 days for Bambu Studio to close; presets not installed since never" in last
    assert "WARNING" in last


def test_the_wait_ends_with_one_clearing_heartbeat(two):
    stable, beta, dirs = two
    c = Client2(_state(stable))
    _run(c, stable, dirs, now=T0, running=lambda: True)
    assert _run(c, stable, dirs, now=T0 + 600) == "no_build"
    assert c.beats[-1] == {"outcome": "no_build", "waiting_since": None, "app": None}
    assert "waiting" not in sync.load_state(dirs)
    n = len(c.beats)
    _run(c, stable, dirs, now=T0 + 1200)
    assert len(c.beats) == n                                             # only once


def test_a_failed_heartbeat_never_changes_the_outcome(two):
    stable, beta, dirs = two
    c = Client2(_state(stable))
    c.fail["heartbeat"] = client.ApiError(404, "not_found", "no")
    assert _run(c, stable, dirs, now=T0, running=lambda: True) == "studio_running"
    assert "heartbeat" in _log(dirs)
    c.fail["heartbeat"] = client.Offline("away")
    assert _run(c, stable, dirs, now=T0 + 7200, running=lambda: True) == "studio_running"


def test_orca_open_is_named_in_the_wait(two):
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))

    def refuse(build_dir, folders, d, **kw):
        raise installer.Refused(installer.ORCA_RUNNING, "studio_running")
    assert _run(c, stable, dirs, install=refuse) == "studio_running"
    assert sync.load_state(dirs)["waiting"]["app"] == "Orca Slicer"
    assert c.beats[-1]["app"] == "Orca Slicer"


# --- status ----------------------------------------------------------------------------------------

def test_status_shows_the_wait_and_every_folder(two, capsys):
    from fksync import __main__ as cli
    stable, beta, dirs = two
    c = Client2(_state(stable, build=_build(STAMP, stable)), _zip(live_hash=_live(stable)))
    assert _run(c, stable, dirs, [beta]) == "installed"
    since = time.mktime((2026, 11, 3, 10, 0, 0, 0, 0, -1))
    st = sync.load_state(dirs)
    st["waiting"] = {"since": since, "skipped_runs": 612, "app": "Bambu Studio"}
    sync._save_state(dirs, st)
    cli.cmd_status(dirs, stable.root.parent)
    out = capsys.readouterr().out
    assert "Waiting:         for Bambu Studio to close since 2026-11-03 10:00 (612 runs skipped)" in out
    assert f"Bambu Studio:    BambuStudio, user {UID}" in out
    assert f"Also installs:   BambuStudioBeta, user {UID}: build {STAMP}" in out
    assert f"Kept, differ:    BambuStudioBeta: 1 ({A})" in out
    assert f"Kept, differ:    BambuStudio: 1 ({A})" in out


def test_status_with_secondaries_off(two, capsys):
    from fksync import __main__ as cli
    stable, beta, dirs = two
    store.save_config(dirs, {"secondaries": False})
    cli.cmd_status(dirs, stable.root.parent)
    out = capsys.readouterr().out
    assert f"Also installs:   none (secondaries is off in the config; BambuStudioBeta, user {UID} is not synced)" in out


def test_linux_status_lists_the_other_roots(tmp_path, capsys):
    from fksync import __main__ as cli
    home = tmp_path / "home"
    lay = studio.LinuxLayout.from_env({"HOME": str(home)})
    studio_fixture.make(home / ".config", variant="BambuStudio", user_id=UID)
    fp = studio_fixture.make(home / ".var/app/com.bambulab.BambuStudio/config", variant="BambuStudioBeta",
                             user_id=UID)
    _older(fp.root / "BambuStudio.conf")
    dirs = store.AppDirs(tmp_path / "data")
    cli.cmd_status(dirs, None, lay)
    out = capsys.readouterr().out
    assert f"Also installs:   Flatpak BambuStudioBeta, user {UID}: nothing installed yet" in out
