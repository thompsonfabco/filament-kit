"""Linux: the Bambu Studio and Orca Slicer data folders (native, Beta, Flatpak, $XDG_CONFIG_HOME) and the Orca
install that holds OrcaFilamentLibrary.opc (native FHS, Flatpak system / user installs). All trees are fakes."""
import os
import time
from pathlib import Path

import pytest

import orca_fixture
import studio_fixture
from fksync import studio


def _age(path: Path, seconds_ago: float) -> None:
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def _layout(tmp_path, xdg=None) -> studio.LinuxLayout:
    home = tmp_path / "home"
    env = {"HOME": str(home)}
    if xdg is not None:
        env["XDG_CONFIG_HOME"] = str(xdg)
    return studio.LinuxLayout.from_env(env, system_flatpak=tmp_path / "var-lib-flatpak",
                                       share_dirs=(tmp_path / "usr-share", tmp_path / "usr-local-share"),
                                       opt_dirs=(tmp_path / "opt",))


FP_BAMBU = Path(".var/app/com.bambulab.BambuStudio/config")
FP_ORCA = Path(".var/app/com.orcaslicer.OrcaSlicer/config")
FP_ORCA_OLD = Path(".var/app/io.github.softfever.OrcaSlicer/config")


# --- the layout ----------------------------------------------------------------------------------

def test_layout_roots_default_and_xdg(tmp_path):
    lay = _layout(tmp_path)
    home = tmp_path / "home"
    assert lay.studio_roots() == [
        ("BambuStudio", home / ".config" / "BambuStudio"),
        ("BambuStudioBeta", home / ".config" / "BambuStudioBeta"),
        ("Flatpak BambuStudio", home / FP_BAMBU / "BambuStudio"),
        ("Flatpak BambuStudioBeta", home / FP_BAMBU / "BambuStudioBeta"),
    ]
    assert [(n, p) for n, p, _ in lay.orca_roots()] == [
        ("OrcaSlicer", home / ".config" / "OrcaSlicer"),
        ("Flatpak OrcaSlicer", home / FP_ORCA / "OrcaSlicer"),
        ("Flatpak OrcaSlicer (io.github.softfever)", home / FP_ORCA_OLD / "OrcaSlicer"),
    ]
    xdg = tmp_path / "xdg"
    lay = _layout(tmp_path, xdg=xdg)
    assert lay.studio_roots()[0] == ("BambuStudio", xdg / "BambuStudio")
    assert lay.studio_roots()[2] == ("Flatpak BambuStudio", home / FP_BAMBU / "BambuStudio")  # Flatpak sets its own
    assert lay.orca_roots()[0][1] == xdg / "OrcaSlicer"
    # an empty XDG_CONFIG_HOME is unset (as the slicers read it)
    lay = studio.LinuxLayout.from_env({"HOME": str(home), "XDG_CONFIG_HOME": ""})
    assert lay.studio_roots()[0][1] == home / ".config" / "BambuStudio"


# --- Bambu Studio --------------------------------------------------------------------------------

def test_bambu_native(tmp_path):
    lay = _layout(tmp_path)
    cfg = tmp_path / "home" / ".config"
    made = studio_fixture.make(cfg, variant="BambuStudio", user_id="111")
    got = studio.locate(None, layout=lay)
    assert (got.variant, got.user_id, got.root) == ("BambuStudio", "111", made.root)
    assert got.user_filament == cfg / "BambuStudio" / "user" / "111" / "filament"
    assert got.system_filament == cfg / "BambuStudio" / "system" / "BBL" / "filament"


def test_bambu_beta_and_xdg(tmp_path):
    xdg = tmp_path / "xdg"
    lay = _layout(tmp_path, xdg=xdg)
    studio_fixture.make(tmp_path / "home" / ".config", variant="BambuStudio", user_id="ignored")  # not XDG: unseen
    studio_fixture.make(xdg, variant="BambuStudioBeta", user_id="222")
    got = studio.locate(None, layout=lay)
    assert (got.variant, got.user_id, got.root) == ("BambuStudioBeta", "222", xdg / "BambuStudioBeta")


def test_bambu_flatpak(tmp_path):
    lay = _layout(tmp_path)
    fp = tmp_path / "home" / FP_BAMBU
    studio_fixture.make(fp, variant="BambuStudio", user_id="333")
    got = studio.locate(None, layout=lay)
    assert (got.variant, got.user_id, got.root) == ("Flatpak BambuStudio", "333", fp / "BambuStudio")
    studio_fixture.make(fp, variant="BambuStudioBeta", user_id="334")
    _age(fp / "BambuStudio" / "BambuStudio.conf", 600)
    assert studio.locate(None, layout=lay).variant == "Flatpak BambuStudioBeta"


def test_bambu_both_present_newest_conf_wins_and_pin(tmp_path):
    lay = _layout(tmp_path)
    native = studio_fixture.make(tmp_path / "home" / ".config", variant="BambuStudio", user_id="111")
    flat = studio_fixture.make(tmp_path / "home" / FP_BAMBU, variant="BambuStudio", user_id="222")
    _age(native.root / "BambuStudio.conf", 3600)
    _age(flat.root / "BambuStudio.conf", 10)
    assert studio.locate(None, layout=lay).variant == "Flatpak BambuStudio"
    _age(flat.root / "BambuStudio.conf", 7200)
    assert studio.locate(None, layout=lay).variant == "BambuStudio"
    # no confs: the newest user filament dir decides
    (native.root / "BambuStudio.conf").unlink()
    (flat.root / "BambuStudio.conf").unlink()
    _age(native.user_filament, 900)
    _age(flat.user_filament, 30)
    assert studio.locate(None, layout=lay).variant == "Flatpak BambuStudio"
    # the config pin wins; a pin that is not one of this PC's names is refused
    got = studio.locate(None, {"variant": "BambuStudio"}, layout=lay)
    assert (got.variant, got.user_id) == ("BambuStudio", "111")
    with pytest.raises(studio.NotFound) as e:
        studio.locate(None, {"variant": "BambuStudioBeta"}, layout=lay)      # a valid name, but not here
    assert "does not exist" in e.value.message
    with pytest.raises(studio.NotFound) as e:
        studio.locate(None, {"variant": "../etc"}, layout=lay)
    assert "Flatpak BambuStudio" in e.value.message


def test_bambu_not_found_names_the_linux_folders(tmp_path):
    with pytest.raises(studio.NotFound) as e:
        studio.locate(None, layout=_layout(tmp_path))
    msg = e.value.message
    assert "Bambu Studio not found" in msg
    assert str(tmp_path / "home" / ".config" / "BambuStudio") in msg
    assert str(tmp_path / "home" / FP_BAMBU / "BambuStudio") in msg


def test_windows_locate_unchanged_message(tmp_path):
    with pytest.raises(studio.NotFound) as e:
        studio.locate(tmp_path / "appdata")
    assert e.value.message.startswith(f"Bambu Studio not found: neither {tmp_path / 'appdata' / 'BambuStudio'} nor ")


# --- Orca Slicer ---------------------------------------------------------------------------------

def _orca(lay, pin=None):
    return studio.locate_orca(None, pin, layout=lay)


def _fake_resources(res: Path, opc: bytes | None = b"ZCRO") -> Path:
    """A resources dir as Orca installs it: <res>/profiles[/OrcaFilamentLibrary.opc]."""
    (res / "profiles").mkdir(parents=True, exist_ok=True)
    if opc is not None:
        (res / "profiles" / "OrcaFilamentLibrary.opc").write_bytes(opc)
    return res


def test_orca_none_on_linux(tmp_path):
    assert _orca(_layout(tmp_path)) is None


def test_orca_native_with_fhs_install(tmp_path):
    lay = _layout(tmp_path)
    cfg = tmp_path / "home" / ".config"
    made = orca_fixture.make(cfg)
    got = _orca(lay)
    assert (got.root, got.user_id, got.user_filament) == (cfg / "OrcaSlicer", orca_fixture.USER_ID, made.user_filament)
    assert got.system_bbl == cfg / "OrcaSlicer" / "system" / "BBL" / "filament"
    assert got.install is None and got.library_opc is None          # an AppImage: nothing installed
    (cfg / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc").write_bytes(b"ZCRO")
    assert _orca(lay).library_opc == cfg / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc"   # Ruling L
    local = _fake_resources(tmp_path / "usr-local-share" / "OrcaSlicer")
    assert _orca(lay).install == local
    usr = _fake_resources(tmp_path / "usr-share" / "OrcaSlicer")
    got = _orca(lay)
    assert got.install == usr and got.library_opc == usr / "profiles" / "OrcaFilamentLibrary.opc"


def test_orca_native_with_opt_tarball_install(tmp_path):
    lay = _layout(tmp_path)
    orca_fixture.make(tmp_path / "home" / ".config")
    res = _fake_resources(tmp_path / "opt" / "OrcaSlicer" / "resources")
    got = _orca(lay)
    assert got.install == res and got.library_opc == res / "profiles" / "OrcaFilamentLibrary.opc"


def test_orca_install_without_packed_library_falls_back(tmp_path):
    lay = _layout(tmp_path)
    cfg = tmp_path / "home" / ".config"
    orca_fixture.make(cfg)
    res = _fake_resources(tmp_path / "usr-share" / "OrcaSlicer", opc=None)
    (cfg / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc").write_bytes(b"ZCRO")
    got = _orca(lay)
    assert got.install == res
    assert got.library_opc == cfg / "OrcaSlicer" / "system" / "OrcaFilamentLibrary.opc"


@pytest.mark.parametrize("user_install", [False, True])
def test_orca_flatpak_with_its_install(tmp_path, user_install):
    lay = _layout(tmp_path)
    fp = tmp_path / "home" / FP_ORCA
    orca_fixture.make(fp)
    _fake_resources(tmp_path / "usr-share" / "OrcaSlicer")             # a native install too: not this Orca's
    base = (tmp_path / "home" / ".local" / "share" / "flatpak") if user_install else tmp_path / "var-lib-flatpak"
    res = _fake_resources(base / "app" / "com.orcaslicer.OrcaSlicer" / "current" / "active" / "files" / "share"
                          / "OrcaSlicer")
    got = _orca(lay)
    assert got.root == fp / "OrcaSlicer"
    assert got.install == res and got.library_opc == res / "profiles" / "OrcaFilamentLibrary.opc"


def test_orca_legacy_flatpak_id_and_newest_root(tmp_path):
    lay = _layout(tmp_path)
    old = orca_fixture.make(tmp_path / "home" / FP_ORCA_OLD)
    assert _orca(lay).root == tmp_path / "home" / FP_ORCA_OLD / "OrcaSlicer"
    new = orca_fixture.make(tmp_path / "home" / FP_ORCA)                 # Orca copied the old folder on update
    _age(old.root / "OrcaSlicer.conf", 3600)
    assert _orca(lay).root == new.root
    native = orca_fixture.make(tmp_path / "home" / ".config")
    _age(new.root / "OrcaSlicer.conf", 7200)
    assert _orca(lay).root == native.root


def test_orca_pins_on_linux(tmp_path):
    lay = _layout(tmp_path)
    orca_fixture.make(tmp_path / "home" / ".config")
    other = orca_fixture.make(tmp_path / "home" / ".config", user_id="other-user", conf_folder=orca_fixture.USER_ID)
    assert _orca(lay, {"orca_user_id": "other-user"}).user_filament == other.user_filament
    with pytest.raises(studio.NotFound):
        _orca(lay, {"orca_user_id": "missing"})
    res = _fake_resources(tmp_path / "elsewhere" / "squashfs-root" / "resources")
    assert _orca(lay, {"orca_install": str(res)}).install == res
    assert _orca(lay, {"orca_install": str(res.parent)}).install == res    # the folder holding resources/ works too
    with pytest.raises(studio.NotFound):
        _orca(lay, {"orca_install": str(tmp_path / "nope")})


def test_layout_never_reaches_the_real_system_dirs(tmp_path):
    """M7 (conftest guard): a layout made from the environment, as the CLI makes it, looks only under tmp_path."""
    lay = studio.LinuxLayout.from_env({"HOME": str(tmp_path / "home")})
    for p in (lay.system_flatpak, *lay.share_dirs, *lay.opt_dirs):
        assert Path(p).resolve().is_relative_to(tmp_path.resolve()), p
