"""The installer's secondary-folder mode (the other Bambu Studio folder) and the differing list. A
secondary never refuses for its own in-app changes (it cannot ask for a rebuild): a preset edited there since its
last install is never written over, not even an accepted update, and one deleted there is not brought back. All
trees are fakes."""
import json
from pathlib import Path

import pytest

import studio_fixture
from fksync import installer
from fksync.store import AppDirs

A, B, C = "Acme PLA @BBL H2D", "Acme PLA @BBL H2D 0.6 nozzle", "Acme PLA @BBL H2D 0.8 nozzle"
D, E = "Acme PETG @BBL H2D", "Acme PETG @BBL H2D 0.6 nozzle"
INFO = {"sync_info": "", "user_id": "1234567890", "setting_id": "", "base_id": ""}


def _p(name, **kw):
    d = {"type": "filament", "name": name, "inherits": "", "from": "User", "filament_id": "P1a2b3c4",
         "filament_type": ["PLA"], "nozzle_temperature": ["215"]}
    d.update(kw)
    return d


def _build(tmp: Path, presets: dict, n=1) -> Path:
    b = tmp / f"build{n}"
    (b / "base").mkdir(parents=True)
    (b / "BUILD.json").write_text(json.dumps({"stamp": f"20261102-01000{n}", "live_hash": "x"}))
    for name, data in presets.items():
        (b / "base" / f"{name}.json").write_text(json.dumps(data, indent=4), encoding="utf-8")
        (b / "base" / f"{name}.info").write_text("sync_info = \nsetting_id = \n", encoding="utf-8")
    return b


def _install(build, f, dirs, n=1, **kw):
    return installer.install(build, f, dirs, running=lambda: False, stamp_now=f"20261102-01000{n}", **kw)


@pytest.fixture
def beta(tmp_path):
    f = studio_fixture.make(tmp_path / "appdata", variant="BambuStudioBeta", user_id="1234567890",
                            base={A: (_p(A), INFO), B: (_p(B, nozzle_temperature=["230"]), INFO)})
    dirs = AppDirs(tmp_path / "local" / "folders" / "BambuStudioBeta-1234567890")
    return f, dirs


def test_differing_lists_the_kept_presets_that_differ(tmp_path, beta):
    f, dirs = beta
    res = _install(_build(tmp_path, {A: _p(A), B: _p(B), C: _p(C)}), f, dirs, secondary=True)
    assert res.installed == [C] and sorted(res.kept) == [A, B]
    assert res.differing == [B]                  # A is the same preset; B is another generation of it
    assert json.loads((f.user_filament / "base" / f"{B}.json").read_text())["nozzle_temperature"] == ["230"]


def test_the_primary_lists_differing_too(tmp_path, beta):
    f, dirs = beta
    res = _install(_build(tmp_path, {A: _p(A), B: _p(B)}), f, dirs)
    assert res.differing == [B]


def test_an_accepted_update_never_replaces_a_secondarys_own_preset(tmp_path, beta):
    """Beta's own B (never installed by the kit: no snapshot proves it is ours) stays as it is, accepted or not, and
    is listed as differing in that folder."""
    f, dirs = beta
    res = _install(_build(tmp_path, {A: _p(A), B: _p(B)}), f, dirs, secondary=True, accept={"base": [B]})
    assert res.installed == [] and res.differing == [B]
    assert json.loads((f.user_filament / "base" / f"{B}.json").read_text())["nozzle_temperature"] == ["230"]
    # still the owner's after an install kept it (its snapshot copy is the owner's file, not ours)
    res = _install(_build(tmp_path, {B: _p(B, nozzle_temperature=["205"])}, n=2), f, dirs, n=2, secondary=True,
                   accept={"base": [B]})
    assert res.installed == [] and res.differing == [B]
    assert json.loads((f.user_filament / "base" / f"{B}.json").read_text())["nozzle_temperature"] == ["230"]


def test_an_accepted_update_is_written_where_the_snapshot_proves_it_is_ours(tmp_path, beta):
    f, dirs = beta
    _install(_build(tmp_path, {C: _p(C)}), f, dirs, secondary=True)                 # the kit wrote C here
    _install(_build(tmp_path, {C: _p(C)}, n=2), f, dirs, n=2, secondary=True)       # kept, unchanged: still ours
    res = _install(_build(tmp_path, {C: _p(C, nozzle_temperature=["225"])}, n=3), f, dirs, n=3, secondary=True,
                   accept={"base": [C]})
    assert res.installed == [C]
    assert json.loads((f.user_filament / "base" / f"{C}.json").read_text())["nozzle_temperature"] == ["225"]


def test_an_older_snapshot_without_a_kept_list_proves_by_equality(tmp_path, beta):
    """A snapshot from before this rule (no KEPT.json, e.g. the 11-03 install): a preset equal to its copy there
    counts as ours."""
    f, dirs = beta
    _install(_build(tmp_path, {C: _p(C)}), f, dirs, secondary=True)
    (dirs.installed / installer.KEPT).unlink()
    res = _install(_build(tmp_path, {C: _p(C, nozzle_temperature=["225"])}, n=2), f, dirs, n=2, secondary=True,
                   accept={"base": [C]})
    assert res.installed == [C]


def test_secondary_edits_since_its_install_are_kept_not_refused(tmp_path, beta):
    f, dirs = beta
    _install(_build(tmp_path, {A: _p(A), C: _p(C), D: _p(D), E: _p(E)}), f, dirs, secondary=True)
    # in that Bambu Studio since: C edited, A deleted (one of four: not an app reset)
    (f.user_filament / "base" / f"{C}.json").write_text(json.dumps(_p(C, nozzle_temperature=["240"])),
                                                        encoding="utf-8")
    (f.user_filament / "base" / f"{A}.json").unlink()
    newer = _build(tmp_path, {A: _p(A, nozzle_temperature=["225"]), B: _p(B), C: _p(C, nozzle_temperature=["225"])},
                   n=2)
    with pytest.raises(installer.Refused) as e:                   # the primary's rule: a rebuild is asked for
        _install(newer, f, dirs, n=2)
    assert e.value.code == "stale_build"
    res = _install(newer, f, dirs, n=2, secondary=True, accept={"base": [C]})
    assert json.loads((f.user_filament / "base" / f"{C}.json").read_text())["nozzle_temperature"] == ["240"]
    assert not (f.user_filament / "base" / f"{A}.json").exists()   # deleted there: not brought back
    assert res.skipped == [A] and C in res.differing and res.installed == []
    assert B in res.kept                                           # B is the owner's own older preset there


def test_secondary_trusts_the_primarys_system_gcode(tmp_path, beta):
    f, dirs = beta
    primary_system = tmp_path / "stable-system"
    primary_system.mkdir()
    (primary_system / "Generic PLA @BBL H2D.json").write_text(json.dumps({"filament_start_gcode": ["; new"]}))
    b = _build(tmp_path, {C: _p(C, filament_start_gcode=["; new"])})
    with pytest.raises(installer.Refused) as e:
        _install(b, f, dirs, secondary=True)
    assert e.value.code == "untrusted_gcode"
    res = _install(b, f, dirs, secondary=True, trusted_extra=(primary_system,))
    assert res.installed == [C]


def _info(path):
    return installer.read_info(path)


@pytest.mark.parametrize("primary_user", ["555", "1234567890"])
def test_a_secondary_gets_its_own_local_preset_info(tmp_path, beta, primary_user):
    """The build's .info is the primary's (its user, maybe its cloud setting_id): a secondary's new preset is a fresh
    local preset of that folder (its own user id, no setting_id / base_id / sync_info), as Bambu Studio saves one;
    a preset the kit writes over keeps that folder's own cloud id."""
    f, dirs = beta
    b = _build(tmp_path, {C: _p(C), D: _p(D)})
    for name in (C, D):
        (b / "base" / f"{name}.info").write_text(
            f"sync_info = update\nuser_id = {primary_user}\nsetting_id = PFUSprimary\nbase_id = GFSA04\n"
            "updated_time = 1800000000\n", encoding="utf-8")
    _install(b, f, dirs, secondary=True)
    info = _info(f.user_filament / "base" / f"{C}.info")
    assert info["user_id"] == "1234567890" and info["setting_id"] == "" and info["base_id"] == ""
    assert info["sync_info"] == "" and info["updated_time"] == "1800000000"
    # Beta synced D to its own cloud since; an accepted update of D keeps Beta's id
    (f.user_filament / "base" / f"{D}.info").write_text(
        "sync_info = \nuser_id = 1234567890\nsetting_id = PFUSbeta\nbase_id = GFSA04\nupdated_time = 1\n",
        encoding="utf-8")
    b2 = _build(tmp_path, {D: _p(D, nozzle_temperature=["225"])}, n=2)
    (b2 / "base" / f"{D}.info").write_text("sync_info = update\nuser_id = 555\nsetting_id = PFUSprimary\n",
                                           encoding="utf-8")
    assert _install(b2, f, dirs, n=2, secondary=True, accept={"base": [D]}).installed == [D]
    info = _info(f.user_filament / "base" / f"{D}.info")
    assert info["user_id"] == "1234567890" and info["setting_id"] == "PFUSbeta" and info["sync_info"] == "update"


def test_the_primary_info_is_written_as_before(tmp_path, beta):
    f, dirs = beta
    b = _build(tmp_path, {C: _p(C)})
    (b / "base" / f"{C}.info").write_text("sync_info = update\nuser_id = 1234567890\nsetting_id = PFUSx\n",
                                          encoding="utf-8")
    _install(b, f, dirs)
    info = _info(f.user_filament / "base" / f"{C}.info")
    assert info["setting_id"] == "PFUSx" and info["sync_info"] == "update"
