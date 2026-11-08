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


def test_running_false_when_not_windows_or_linux(monkeypatch):
    monkeypatch.setattr(studio.sys, "platform", "darwin")      # Linux reads /proc: test_linux_running
    assert studio.running() is False


def test_never_touches_real_appdata(tmp_path):
    for key in ("APPDATA", "LOCALAPPDATA"):
        value = Path(os.environ[key]).resolve()
        assert value.is_relative_to(tmp_path.resolve()), key
        if REAL_ENV[key]:
            assert value != Path(REAL_ENV[key]).resolve()


def test_locate_ignores_newer_conf_of_a_root_without_user_folder(tmp_path):
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id="111")
    beta_root = appdata / "BambuStudioBeta"
    beta_root.mkdir()
    (beta_root / "BambuStudio.conf").write_text("{}", encoding="utf-8")
    _age(stable.root / "BambuStudio.conf", 3600)
    got = studio.locate(appdata)
    assert got.variant == "BambuStudio" and got.user_id == "111"


# --- the other Bambu Studio folders (secondaries) --------------------------------------

def test_secondaries_are_the_other_usable_roots(tmp_path):
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id="1234567890")
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="1234567890")
    _age(beta.root / "BambuStudio.conf", 3600)
    primary = studio.locate(appdata)
    assert primary.variant == "BambuStudio"
    got = studio.secondaries(appdata, primary)
    assert got == [beta]
    assert studio.folder_key(got[0]) == "BambuStudioBeta-1234567890"
    assert studio.folder_key(primary) == "BambuStudio-1234567890"
    # the pin still picks the primary; the other one is the secondary
    pinned = studio.locate(appdata, {"variant": "BambuStudioBeta"})
    assert studio.secondaries(appdata, pinned) == [stable]


def test_secondary_user_is_the_primarys_id_else_its_own_newest(tmp_path):
    appdata = tmp_path / "appdata"
    primary = studio_fixture.make(appdata, variant="BambuStudio", user_id="1234567890")
    studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="1234567890")
    newer = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="default")
    _age(newer.user_filament, 0)
    _age(appdata / "BambuStudioBeta" / "user" / "1234567890" / "filament", 3600)
    assert [s.user_id for s in studio.secondaries(appdata, primary)] == ["1234567890"]   # the same id wins
    other = studio_fixture.make(tmp_path / "b", variant="BambuStudio", user_id="555")
    studio_fixture.make(tmp_path / "b", variant="BambuStudioBeta", user_id="default")
    assert [s.user_id for s in studio.secondaries(tmp_path / "b", other)] == ["default"]


def test_a_root_without_a_user_filament_dir_is_no_secondary(tmp_path):
    appdata = tmp_path / "appdata"
    primary = studio_fixture.make(appdata, variant="BambuStudio", user_id="1234567890")
    (appdata / "BambuStudioBeta" / "user").mkdir(parents=True)           # never opened / signed in
    assert studio.secondaries(appdata, primary) == []


# --- the primary is sticky once recorded --------------------------------------------------------

def _rec(f):
    return {"key": studio.folder_key(f), "variant": f.variant, "user_id": f.user_id, "root": str(f.root)}


def test_primary_without_a_record_is_the_newest_conf(tmp_path):
    appdata = tmp_path / "appdata"
    studio_fixture.make(appdata, variant="BambuStudio", user_id="1234567890")
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="1234567890")
    _age(beta.root / "BambuStudio.conf", 3600)
    f, why = studio.primary(appdata, {}, None)
    assert f.variant == "BambuStudio" and why is None


def test_a_recorded_primary_stays_whatever_conf_is_newer(tmp_path):
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id="1234567890")
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="1234567890")
    for newer in (stable, beta, stable):
        _age(newer.root / "BambuStudio.conf", 0)
        _age((beta if newer is stable else stable).root / "BambuStudio.conf", 3600)
        f, why = studio.primary(appdata, {}, _rec(beta))
        assert f == beta and why is None


def test_a_pin_or_a_gone_folder_changes_the_primary_with_a_reason(tmp_path):
    import shutil
    appdata = tmp_path / "appdata"
    stable = studio_fixture.make(appdata, variant="BambuStudio", user_id="1234567890")
    beta = studio_fixture.make(appdata, variant="BambuStudioBeta", user_id="1234567890")
    f, why = studio.primary(appdata, {"variant": "BambuStudio"}, _rec(beta))
    assert f == stable and "pin" in why and "variant" in why
    f, why = studio.primary(appdata, {"variant": "BambuStudioBeta"}, _rec(beta))
    assert f == beta and why is None                             # the pin names the recorded folder
    shutil.rmtree(beta.user_filament)
    f, why = studio.primary(appdata, {}, _rec(beta))
    assert f == stable and "no longer" in why and "BambuStudioBeta" in why
