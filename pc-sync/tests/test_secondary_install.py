"""PCBOTH R1/R2: the installer's secondary-folder mode (the other Bambu Studio folder) and the differing list. A
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


def test_accepted_updates_are_written_in_a_secondary(tmp_path, beta):
    f, dirs = beta
    res = _install(_build(tmp_path, {A: _p(A), B: _p(B)}), f, dirs, secondary=True, accept={"base": [B]})
    assert res.installed == [B] and res.differing == []
    assert json.loads((f.user_filament / "base" / f"{B}.json").read_text())["nozzle_temperature"] == ["215"]


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
