import os
import time
from pathlib import Path

import pytest

import studio_fixture
from conftest import REAL_ENV
from fksync import studio


def _age(path: Path, seconds_ago: float) -> None:
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def test_locate_prefers_newest_conf(tmp_path):
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id="111")
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="222")
    _age(stable.root / "BambuStudio.conf", 3600)
    _age(beta.root / "BambuStudio.conf", 10)
    # stable's filament dir is newer: the conf decides, not the filament dir
    _age(beta.user_filament, 7200)
    _age(stable.user_filament, 5)
    got = studio.locate(appdata)
    assert got.variant == "BambuStudioBeta"
    assert got.user_id == "222"
    assert got.root == appdata / "BambuStudioBeta"
    assert got.user_filament == appdata / "BambuStudioBeta" / "user" / "222" / "filament"
    assert got.system_filament == appdata / "BambuStudioBeta" / "system" / "BBL" / "filament"
    # the other way round
    _age(beta.root / "BambuStudio.conf", 3600 * 5)
    assert studio.locate(appdata).variant == "BambuStudio"
    # pinned variant wins over the newest conf
    assert studio.locate(appdata, {"variant": "BambuStudioBeta"}).variant == "BambuStudioBeta"


def test_locate_falls_back_to_newest_filament_dir_without_conf(tmp_path):
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id="111")
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="222")
    (stable.root / "BambuStudio.conf").unlink()
    (beta.root / "BambuStudio.conf").unlink()
    _age(beta.user_filament, 100)
    _age(stable.user_filament, 10)
    assert studio.locate(appdata).variant == "BambuStudio"


def test_locate_newest_user_and_pin(tmp_path):
    appdata = tmp_path / "appdata"
    default = studio_fixture.make(appdata, user_id="default")
    logged_in = studio_fixture.make(appdata, user_id="123")
    _age(default.user_filament, 86400)
    _age(logged_in.user_filament, 60)
    assert studio.locate(appdata).user_id == "123"
    pinned = studio.locate(appdata, {"user_id": "default"})
    assert pinned.user_id == "default"
    assert pinned.user_filament == default.user_filament
    assert studio.locate(appdata, {"variant": "BambuStudioBeta", "user_id": "default"}).user_id == "default"
    with pytest.raises(studio.NotFound) as e:
        studio.locate(appdata, {"user_id": "999"})
    assert "999" in str(e.value)
    with pytest.raises(studio.NotFound):
        studio.locate(appdata, {"variant": "BambuStudio"})


def test_locate_not_found_message(tmp_path):
    appdata = tmp_path / "appdata"
    with pytest.raises(studio.NotFound) as e:
        studio.locate(appdata)
    assert "Bambu Studio" in str(e.value)
    assert "Bambu Studio" in e.value.message
    # a root with no user filament folder is not enough
    (appdata / "BambuStudio").mkdir()
    (appdata / "BambuStudio" / "BambuStudio.conf").write_text("{}", encoding="utf-8")
    with pytest.raises(studio.NotFound) as e:
        studio.locate(appdata)
    assert "Bambu Studio" in str(e.value)


def test_locate_refuses_bad_pin_values(tmp_path):
    appdata = tmp_path / "appdata"
    studio_fixture.make(appdata, user_id="123")
    for bad in ({"variant": "..\\Windows"}, {"variant": "OrcaSlicer"}, {"user_id": "../x"}):
        with pytest.raises(studio.NotFound):
            studio.locate(appdata, bad)
    assert studio.locate(appdata, {"variant": None, "user_id": None}).user_id == "123"
    assert studio.locate(appdata, {"variant": "", "user_id": ""}).user_id == "123"  # empty = not pinned


def test_running_parses_tasklist():
    seen = '"bambu-studio.exe","12345","Console","1","512,000 K"\r\n'
    assert studio.running(lambda: seen) is True
    assert studio.running(lambda: '"Bambu-Studio.EXE","1","Console","1","1 K"') is True
    assert studio.running(lambda: "INFO: No tasks are running which match the specified criteria.\r\n") is False
    assert studio.running(lambda: "") is False


def test_running_false_when_not_windows(monkeypatch):
    monkeypatch.setattr(studio.sys, "platform", "linux")
    assert studio.running() is False


def test_never_touches_real_appdata(tmp_path):
    for key in ("APPDATA", "LOCALAPPDATA"):
        value = Path(os.environ[key]).resolve()
        assert value.is_relative_to(tmp_path.resolve()), key
        if REAL_ENV[key]:
            assert value != Path(REAL_ENV[key]).resolve()
