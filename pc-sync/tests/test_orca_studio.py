"""Orca Slicer discovery: user folder, install dir, the packed library, the running check."""
import os
import time
from pathlib import Path

import pytest

import orca_fixture
from fksync import studio

OTHER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _age(path: Path, seconds_ago: float) -> None:
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def _locate(appdata, pin=None, *, program_files=(), registry=lambda: []):
    return studio.locate_orca(appdata, pin, program_files=program_files, registry=registry)


def test_no_orca_is_none(tmp_path):
    assert _locate(tmp_path / "appdata") is None
    (tmp_path / "appdata" / "OrcaSlicer" / "user").mkdir(parents=True)  # no user/<id>/filament yet
    assert _locate(tmp_path / "appdata") is None


def test_user_from_conf_preset_folder(tmp_path):
    appdata = tmp_path / "appdata"
    orca_fixture.make(appdata, user_id=OTHER)
    want = orca_fixture.make(appdata)                      # conf now names USER_ID
    _age(want.user_filament, 3600)                         # older, but the conf decides
    got = _locate(appdata)
    assert got.user_id == orca_fixture.USER_ID
    assert got.root == appdata / "OrcaSlicer"
    assert got.user_filament == want.user_filament
    assert got.system_bbl == appdata / "OrcaSlicer" / "system" / "BBL" / "filament"


def test_user_newest_without_usable_conf_and_pin(tmp_path):
    appdata = tmp_path / "appdata"
    a = orca_fixture.make(appdata, user_id=OTHER)
    b = orca_fixture.make(appdata, conf_folder="gone-user")  # the conf names a folder that is not there
    _age(a.user_filament, 10)
    _age(b.user_filament, 3600)
    assert _locate(appdata).user_id == OTHER
    (appdata / "OrcaSlicer" / "OrcaSlicer.conf").write_text("{not json", encoding="utf-8")
    assert _locate(appdata).user_id == OTHER
    assert _locate(appdata, {"orca_user_id": orca_fixture.USER_ID}).user_id == orca_fixture.USER_ID
    with pytest.raises(studio.NotFound):
        _locate(appdata, {"orca_user_id": "missing"})
    with pytest.raises(studio.NotFound):
        _locate(appdata, {"orca_user_id": "../x"})


def test_install_dir_pin_registry_program_files(tmp_path):
    appdata = tmp_path / "appdata"
    pf = tmp_path / "pf"
    old = orca_fixture.make(appdata, install=pf / "OrcaSlicer 2.3.0").install
    new = pf / "OrcaSlicer 2.5.0"
    orca_fixture.make(appdata, install=new, opc=orca_fixture.opc_blob(orca_fixture.LIBRARY))
    _age(old / "orca-slicer.exe", 7200)
    reg_dir = tmp_path / "elsewhere" / "Orca"
    orca_fixture.make(appdata, install=reg_dir)

    # Program Files: the newest OrcaSlicer* folder that has orca-slicer.exe
    got = _locate(appdata, program_files=[pf, tmp_path / "missing"])
    assert got.install == new
    assert got.library_opc == new / "resources" / "profiles" / "OrcaFilamentLibrary.opc"
    # the uninstall registry entry wins over Program Files (InstallLocation is often empty; DisplayIcon is not)
    entries = [{"DisplayName": "Something else", "DisplayIcon": str(new / "orca-slicer.exe")},
               {"DisplayName": "OrcaSlicer", "InstallLocation": "", "UninstallString": f'"{reg_dir}\\Uninstall.exe"',
                "DisplayIcon": str(reg_dir / "orca-slicer.exe")}]
    got = _locate(appdata, program_files=[pf], registry=lambda: entries)
    assert got.install == reg_dir
    assert got.library_opc is None                      # that install has no packed library ...
    (appdata / "OrcaSlicer" / "system").mkdir(exist_ok=True)
    (appdata / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc").write_bytes(b"ZCRO")
    got = _locate(appdata, program_files=[pf], registry=lambda: entries)
    assert got.library_opc == appdata / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc"  # ... the user copy
    # the config pin wins over both
    assert _locate(appdata, {"orca_install": str(old)}, program_files=[pf], registry=lambda: entries).install == old
    with pytest.raises(studio.NotFound):
        _locate(appdata, {"orca_install": str(tmp_path / "nope")})
    # no install anywhere: still usable (live presets), no packed library from the install
    (appdata / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc").unlink()
    got = _locate(appdata, program_files=[tmp_path / "missing"])
    assert got.install is None and got.library_opc is None


def test_registry_errors_are_ignored(tmp_path):
    orca_fixture.make(tmp_path / "appdata")

    def broken():
        raise OSError("no registry")
    assert _locate(tmp_path / "appdata", registry=broken).install is None


def test_orca_running():
    assert studio.orca_running(lambda: '"orca-slicer.exe","1234","Console","1","200,000 K"\n') is True
    assert studio.orca_running(lambda: "INFO: No tasks are running which match the specified criteria.\n") is False
    assert studio.orca_running(lambda: '"bambu-studio.exe","1"\n') is False
