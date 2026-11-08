"""The printer pack installer (printer-pack/fkpack.py), against a temporary printer_data and a fake Moonraker.

Run with the server's test environment: `server/.venv/Scripts/python -m pytest printer-pack/tests` (it borrows the
server tests' FakeMoonraker).
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))
sys.path.insert(0, str(PACK.parent / "server" / "tests"))

import fkpack  # noqa: E402
from fakes.fake_moonraker import FakeMoonraker  # noqa: E402

PRINTER_CFG = "[printer]\nkinematics: corexy\n\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# x\n"
MOONRAKER_CONF = "[server]\nhost: 0.0.0.0\n\n[spoolman]\nserver: http://old.example.com:7912\n\n[authorization]\n"


@pytest.fixture
def moon():
    f = FakeMoonraker()
    host, port, stop = f.serve()
    f.url = f"http://{host}:{port}"
    yield f
    stop()


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "printer_data"
    (d / "config").mkdir(parents=True)
    (d / "config" / "printer.cfg").write_text(PRINTER_CFG, encoding="utf-8")
    (d / "config" / "moonraker.conf").write_text(MOONRAKER_CONF, encoding="utf-8")
    (d / "moonraker.asvc").write_text("klipper_mcu\nwebcamd\n", encoding="utf-8")
    return d


def pack(data, moon, answers=True, home=None, runs=None):
    said = []
    p = fkpack.Pack(str(data), moon.url, home=str(home or data.parent), ask=lambda q: answers,
                    out=said.append, run=(lambda cmd, **kw: runs.append(cmd)) if runs is not None else None,
                    klipper_dir=str(data.parent / "klipper"))
    p.said = said
    return p


def shell_command(data):
    d = data.parent / "klipper" / "klippy" / "extras"
    d.mkdir(parents=True)
    (d / "gcode_shell_command.py").write_text("# stub\n")


def test_install_writes_cfg_and_include(data, moon):
    moon.objects = ["print_stats", "toolhead"]
    p = pack(data, moon)
    assert p.install(["spool"]) == 0
    dest = data / "config" / "filament-kit"
    assert (dest / "fk_spool.cfg").exists() and (dest / "fk_active_spool.cfg").exists()
    cfg = (dest / "fk_spool.cfg").read_text()
    assert "@SCAN_OK@" not in cfg and "M118 Spool" in cfg
    text = (data / "config" / "printer.cfg").read_text()
    assert text.index(fkpack.INCLUDE) < text.index(fkpack.SAVE_CONFIG)          # before SAVE_CONFIG
    assert list((data / "config").glob("printer.cfg.bak-fk-*"))                  # backup kept
    assert moon.actions == ["restart"]                                           # standby + yes


def test_scan_hooks_from_options(data, moon):
    p = pack(data, moon)
    p.install(["spool"], scan_ok="_SPOOL_SCANNED ID={params.ID}", scan_unknown="_SPOOL_SCAN_UNKNOWN")
    cfg = (data / "config" / "filament-kit" / "fk_spool.cfg").read_text()
    assert "  _SPOOL_SCANNED ID={params.ID}" in cfg and "  _SPOOL_SCAN_UNKNOWN" in cfg


def test_skips_existing_set_active_spool(data, moon):
    moon.objects = ["print_stats", "gcode_macro SET_ACTIVE_SPOOL", "gcode_macro CLEAR_ACTIVE_SPOOL"]
    p = pack(data, moon)
    p.install(["spool"])
    assert not (data / "config" / "filament-kit" / "fk_active_spool.cfg").exists()
    assert any("already present" in s for s in p.said)


def test_no_answer_changes_nothing_of_the_owners(data, moon):
    p = pack(data, moon, answers=False)
    p.install(["spool", "moonraker"], spoolman="http://kit.example.com:7912")
    assert (data / "config" / "printer.cfg").read_text() == PRINTER_CFG
    assert (data / "config" / "moonraker.conf").read_text() == MOONRAKER_CONF
    assert moon.actions == []


def test_refuses_restart_when_printing(data, moon):
    moon.status["print_stats"]["state"] = "printing"
    p = pack(data, moon)
    p.install(["spool"])
    assert moon.actions == []
    assert any("restart it yourself" in s for s in p.said)


def test_refuses_to_overwrite_a_foreign_file(data, moon):
    dest = data / "config" / "filament-kit"
    dest.mkdir()
    (dest / "fk_spool.cfg").write_text("# mine")
    with pytest.raises(fkpack.PackError, match="not written by the pack"):
        pack(data, moon).install(["spool"])
    assert (dest / "fk_spool.cfg").read_text() == "# mine"


def test_reinstall_is_idempotent(data, moon):
    pack(data, moon).install(["spool"])
    moon.actions.clear()
    p = pack(data, moon)
    p.install(["spool"])
    assert (data / "config" / "printer.cfg").read_text().count(fkpack.INCLUDE) == 1
    assert moon.actions == []                         # nothing new: no restart offered


def test_scripts_need_shell_command(data, moon):
    p = pack(data, moon)
    p.install(["check", "loadtemp"])
    assert not (data / "config" / "filament-kit" / "fk_spool_check.cfg").exists()
    assert any("gcode_shell_command" in s for s in p.said)
    shell_command(data)
    p.install(["check", "loadtemp"])
    dest = data / "config" / "filament-kit"
    assert str(dest) in (dest / "fk_spool_check.cfg").read_text()
    assert (dest / "scripts" / "fk_load_temp.sh").exists()


def test_moonraker_edits(data, moon):
    p = pack(data, moon)
    p.install(["moonraker"], spoolman="http://kit.example.com:7912")
    conf = (data / "config" / "moonraker.conf").read_text()
    assert "server: http://kit.example.com:7912" in conf and "old.example.com" not in conf
    assert "[zeroconf]" in conf and "[authorization]" in conf


def test_set_section_adds_missing():
    out = fkpack.set_section("[server]\nhost: x\n", "spoolman", {"server": "http://a:1"})
    assert out.endswith("[spoolman]\nserver: http://a:1\n")


def test_uninstall_removes_only_manifest(data, moon):
    dest = data / "config" / "filament-kit"
    shell_command(data)
    pack(data, moon).install(["spool", "check"])
    (dest / "mine.cfg").write_text("# the owner's own file in the folder")
    p = pack(data, moon)
    assert p.uninstall() == 0
    assert sorted(os.listdir(dest)) == ["mine.cfg"]
    assert fkpack.INCLUDE not in (data / "config" / "printer.cfg").read_text()


def _git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


def test_adopt_existing_nfc2klipper_no_changes(data, moon, tmp_path, monkeypatch):
    home = tmp_path / "home"
    nfc = home / "nfc2klipper"
    nfc.mkdir(parents=True)
    _git(nfc, "init", "-q")
    _git(nfc, "config", "user.email", "t@example.com")
    _git(nfc, "config", "user.name", "t")
    (nfc / "a.txt").write_text("one\n")
    _git(nfc, "add", ".")
    _git(nfc, "commit", "-qm", "x")
    (nfc / "a.txt").write_text("two\n")                                  # a local change = the kit's patch
    patch = tmp_path / "0001-a.patch"
    patch.write_text(subprocess.run(["git", "-C", str(nfc), "diff"], capture_output=True, text=True).stdout)
    other = tmp_path / "0002-b.patch"
    other.write_text("diff --git a/b.txt b/b.txt\n--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-x\n+y\n")
    monkeypatch.setattr(fkpack.Pack, "patches", lambda self: [str(patch), str(other)])
    runs = []
    p = pack(data, moon, home=home, runs=runs)
    p.install(["nfc"])
    assert runs == []                                                    # adopted: nothing run
    said = "\n".join(p.said)
    assert "adopted" in said and "0001-a.patch: applied" in said and "0002-b.patch: differs" in said
    assert (nfc / "a.txt").read_text() == "two\n"


def test_fresh_nfc_install_commands(data, moon, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    runs = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        if cmd[:2] == ["git", "clone"]:
            d = Path(cmd[-1])
            d.mkdir()
            (d / "nfc2klipper.cfg").write_text(UPSTREAM)
            for s in ("nfc2klipper_backend", "nfc2klipper_api"):
                (d / f"{s}.service").write_text("[Service]\nUser=pi\nExecStart=/home/pi/nfc2klipper/x\n")
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=lambda q: True, out=lambda s: None, run=fake_run)
    p.install(["nfc"], nfc_device="tty:USB0:pn532", spoolman="http://kit.example.com:7912")
    assert ["git", "-C", str(home / "nfc2klipper"), "checkout", "-q", p.pin()] in runs
    assert sum(1 for c in runs if c[:3] == ["git", "-C", str(home / "nfc2klipper")] and c[3] == "apply") == 2
    assert any(c[:3] == ["sudo", "systemctl", "enable"] and c[-1] == "nfc2klipper_backend" for c in runs)
    assert not any(c[-1] == "nfc2klipper_api" for c in runs if c[:2] == ["sudo", "systemctl"])   # web off
    cfg = (home / ".config" / "nfc2klipper" / "nfc2klipper.cfg").read_text()
    assert 'nfc-device = "tty:USB0:pn532"' in cfg and 'spoolman-url = "http://kit.example.com:7912"' in cfg
    assert "_FK_SCAN_OK ID={spool}" in cfg and "disable_web_server = true" in cfg
    assert "nfc2klipper_backend" in (data / "moonraker.asvc").read_text().split()


UPSTREAM = '''[webserver]
disable_web_server = true
web_port = 5001

[nfc]
nfc-device = "tty:AMA0"

[spoolman]
spoolman-url = "http://mainsailos.local:7912"

[moonraker]
moonraker-url = "http://mainsailos.local"
clear-spool = false
always-send = false

[macros]
setting_gcode = """
SET_ACTIVE_SPOOL ID={spool}
SET_ACTIVE_FILAMENT ID={filament}
"""
clearing_gcode = """
CLEAR_ACTIVE_SPOOL
"""
'''


def test_nfc_config_from_upstream():
    out = fkpack.nfc_config(UPSTREAM, "tty:USB0:pn532", "http://kit.example.com:7912", "http://localhost:7125", True)
    assert 'disable_web_server = false' in out and 'moonraker-url = "http://localhost:7125"' in out
    assert "always-send = true" in out and "SET_ACTIVE_FILAMENT" not in out
    assert 'clearing_gcode = """\n"""' in out


def test_load_temp_rules():
    sys.path.insert(0, str(PACK / "scripts"))
    import fk_load_temp as lt
    assert lt.temp_for({"extra": {"nozzle_range": '"200-220"'}}) == 210
    assert lt.temp_for({"settings_extruder_temp": 245}) == 245
    assert lt.temp_for({"material": "PETG-CF"}) == 235
    assert lt.temp_for({"material": "PA12"}) == 0


@pytest.mark.parametrize("rel", ["fkpack.py", "scripts/fk_spool_check.py", "scripts/fk_load_temp.py",
                                 "lasttag/lasttag.py"])
def test_runs_on_py39(rel):
    """The printer may have Python 3.9 (Debian 11): no newer syntax anywhere in what runs there."""
    ast.parse((PACK / rel).read_text(encoding="utf-8"), feature_version=(3, 9))


def test_restart_offered_when_printer_cfg_was_replaced(data, moon):
    """The include line was lost (printer.cfg restored from a backup): adding it again needs a restart."""
    pack(data, moon).install(["spool"])
    (data / "config" / "printer.cfg").write_text(PRINTER_CFG, encoding="utf-8")
    moon.actions.clear()
    pack(data, moon).install(["spool"])
    assert fkpack.INCLUDE in (data / "config" / "printer.cfg").read_text()
    assert moon.actions == ["restart"]


# ---- final review I5: never overwrite what the pack did not write ------------------------------------------------

def test_existing_units_are_adopted_not_replaced(data, moon, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "nfc2klipper" / "venv" / "bin").mkdir(parents=True)        # an nfc2klipper without .git
    units = tmp_path / "units"
    units.mkdir()
    (units / "lasttag.service").write_text("[Service]\nExecStart=/the/owners/lasttag\n")
    runs = []
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=lambda q: True, out=lambda s: None,
                    run=lambda cmd, **kw: runs.append(cmd), units_dir=str(units))
    said = []
    p.out = said.append
    p.install(["lasttag"], allow=["192.0.2.10"])
    assert (units / "lasttag.service").read_text() == "[Service]\nExecStart=/the/owners/lasttag\n"
    assert not any("install" in c for c in runs if c[:1] == ["sudo"]), runs
    assert "lasttag" not in p.manifest()["services"]
    assert any("already installed" in s for s in said)
    p.uninstall()
    assert (units / "lasttag.service").exists()                       # uninstall leaves the owner's unit


def test_existing_nfc2klipper_config_is_never_overwritten(data, moon, tmp_path):
    home = tmp_path / "home"
    cfg = home / ".config" / "nfc2klipper"
    cfg.mkdir(parents=True)
    (cfg / "nfc2klipper.cfg").write_text("# the owner's config\n")
    runs = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        if cmd[:2] == ["git", "clone"]:
            d = Path(cmd[-1])
            d.mkdir()
            (d / "nfc2klipper.cfg").write_text(UPSTREAM)
            (d / "nfc2klipper_backend.service").write_text("[Service]\nUser=pi\n")
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=lambda q: True, out=lambda s: None, run=fake_run,
                    units_dir=str(tmp_path / "units"))
    p.install(["nfc"])
    assert (cfg / "nfc2klipper.cfg").read_text() == "# the owner's config\n"
    assert (cfg / "nfc2klipper.cfg.fk-new").exists()


def test_nfc_folder_without_git_is_refused(data, moon, tmp_path):
    home = tmp_path / "home"
    (home / "nfc2klipper").mkdir(parents=True)
    runs = []
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=lambda q: True, out=lambda s: None,
                    run=lambda cmd, **kw: runs.append(cmd), units_dir=str(tmp_path / "units"))
    p.install(["nfc"])
    assert runs == []                                                  # nothing cloned over the owner's folder
