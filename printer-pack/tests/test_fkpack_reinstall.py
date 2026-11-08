"""The printer pack run again and again (review 2026-11-08 A5, B1): reinstall, uninstall, kept services, a failed
nfc2klipper install, the lasttag allow list, manifest entries. systemd is simulated: `sudo install` copies the unit,
`systemctl disable` fails for a unit that is not there (as the real one does), `rm -f` never fails."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_fkpack import UPSTREAM, data, moon  # noqa: F401  (fixtures; it also puts the pack on sys.path)

import fkpack  # noqa: E402


class Systemd:
    def __init__(self, units, fail_pip=0):
        self.units, self.runs, self.fail_pip = units, [], fail_pip

    def __call__(self, cmd, **kw):
        self.runs.append(cmd)
        if cmd[:2] == ["sudo", "install"]:
            shutil.copy(cmd[-2], cmd[-1])
        elif cmd[:3] == ["sudo", "rm", "-f"]:
            Path(cmd[-1]).unlink(missing_ok=True)
        elif cmd[:4] == ["sudo", "systemctl", "disable", "--now"]:
            if not (self.units / (cmd[-1] + ".service")).exists():
                raise subprocess.CalledProcessError(1, cmd, "Unit file does not exist")
        elif cmd[:2] == ["git", "clone"]:
            d = Path(cmd[-1])
            (d / ".git").mkdir(parents=True)
            (d / "nfc2klipper.cfg").write_text(UPSTREAM)
            (d / "nfc2klipper_backend.service").write_text("[Service]\nUser=pi\nExecStart=/home/pi/x\n")
        elif "pip" in cmd[0] and self.fail_pip:
            self.fail_pip -= 1
            raise subprocess.CalledProcessError(1, cmd, "pip: network down")


@pytest.fixture
def env(data, tmp_path):
    home = tmp_path / "home"
    (home / "nfc2klipper" / "venv" / "bin").mkdir(parents=True)
    (home / "nfc2klipper" / ".git").mkdir()
    units = tmp_path / "units"
    units.mkdir()
    return data, home, units


def mk(data, moon, home, units, sd, answers=None):
    said = []
    ask = answers if answers is not None else (lambda q: True)
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=ask, out=said.append, run=sd, units_dir=str(units),
                    klipper_dir=str(data.parent / "klipper"))
    p.said = said
    return p


def test_reinstall_twice_then_uninstall_works(env, moon):
    data, home, units = env
    sd = Systemd(units)
    for _ in range(3):
        mk(data, moon, home, units, sd).install(["spool", "lasttag"], allow=["192.0.2.10"])
    m = mk(data, moon, home, units, sd).manifest()
    assert m["services"] == ["lasttag"] and m["asvc"] == ["lasttag"]
    assert len(m["files"]) == len(set(m["files"]))
    assert mk(data, moon, home, units, sd).uninstall() == 0
    assert not (units / "lasttag.service").exists()
    assert not (data / "config" / "filament-kit").exists()
    assert "lasttag" not in (data / "moonraker.asvc").read_text().split()
    assert mk(data, moon, home, units, sd).uninstall() == 0            # again: nothing left, no error


def test_an_old_manifest_with_duplicates_and_a_gone_unit_still_uninstalls(env, moon):
    data, home, units = env
    dest = data / "config" / "filament-kit"
    dest.mkdir(parents=True)
    (dest / ".manifest").write_text(json.dumps({"files": [], "include": False, "services": ["lasttag", "lasttag"],
                                                "asvc": ["lasttag", "lasttag"], "moonraker": []}))
    sd = Systemd(units)                                                  # the unit is already gone
    p = mk(data, moon, home, units, sd)
    assert p.uninstall() == 0
    assert sum(c[:4] == ["sudo", "systemctl", "disable", "--now"] for c in sd.runs) == 1
    assert any("failed" in s and "going on" in s for s in p.said)
    assert not (dest / ".manifest").exists()


def test_a_kept_service_keeps_its_files_and_its_manifest_entry(env, moon):
    data, home, units = env
    sd = Systemd(units)
    mk(data, moon, home, units, sd).install(["spool", "lasttag"], allow=["192.0.2.10"])
    lt = data / "config" / "filament-kit" / "lasttag"
    p = mk(data, moon, home, units, sd, answers=lambda q: "lasttag" not in q)   # "no" to removing lasttag
    assert p.uninstall() == 0
    assert (units / "lasttag.service").exists()
    assert (lt / "lasttag.py").exists() and "192.0.2.10" in (lt / "allow").read_text()
    assert "lasttag" in (data / "moonraker.asvc").read_text().split()
    assert not (data / "config" / "filament-kit" / "fk_spool.cfg").exists()
    m = mk(data, moon, home, units, sd).manifest()
    assert m["services"] == ["lasttag"] and set(m["files"]) == {"lasttag/lasttag.py", "lasttag/allow"}
    assert mk(data, moon, home, units, sd).uninstall() == 0            # later: yes, now it goes
    assert not (units / "lasttag.service").exists() and not (data / "config" / "filament-kit").exists()


def test_reinstall_without_allow_keeps_the_list_and_a_change_restarts_lasttag(env, moon):
    data, home, units = env
    sd = Systemd(units)
    mk(data, moon, home, units, sd).install(["lasttag"], allow=["192.0.2.10"])
    allow = data / "config" / "filament-kit" / "lasttag" / "allow"
    p = mk(data, moon, home, units, sd)
    p.install(["lasttag"])
    assert "192.0.2.10" in allow.read_text() and any("keeping its allow list" in s for s in p.said)
    assert ["sudo", "systemctl", "restart", "lasttag"] not in sd.runs
    mk(data, moon, home, units, sd).install(["lasttag"], allow=["192.0.2.11"])
    assert "192.0.2.11" in allow.read_text()
    assert ["sudo", "systemctl", "restart", "lasttag"] in sd.runs


def test_a_failed_nfc2klipper_install_is_finished_by_the_next(env, moon):
    data, home, units = env
    shutil.rmtree(home / "nfc2klipper")
    sd = Systemd(units, fail_pip=1)
    with pytest.raises(subprocess.CalledProcessError):
        mk(data, moon, home, units, sd).install(["nfc"])
    m = mk(data, moon, home, units, sd).manifest()
    assert m["nfc"] == {"dir": str(home / "nfc2klipper"), "state": "started"}
    sd.runs.clear()
    p = mk(data, moon, home, units, sd)
    p.install(["nfc"])
    assert any("finishing the nfc2klipper install" in s for s in p.said)
    assert not any(c[:2] == ["git", "clone"] for c in sd.runs)        # finished in place, not cloned again
    assert any("pip" in c[0] for c in sd.runs) and (units / "nfc2klipper_backend.service").exists()
    assert mk(data, moon, home, units, sd).manifest()["nfc"]["state"] == "done"


def test_after_uninstall_a_reinstall_puts_the_reader_services_back(env, moon):
    data, home, units = env
    shutil.rmtree(home / "nfc2klipper")
    sd = Systemd(units)
    mk(data, moon, home, units, sd).install(["nfc"])
    mk(data, moon, home, units, sd).uninstall()
    assert not (units / "nfc2klipper_backend.service").exists()
    mk(data, moon, home, units, sd).install(["nfc"])                    # the checkout is still there: adopted
    assert (units / "nfc2klipper_backend.service").exists()


def test_units_are_staged_outside_printer_data(env, moon):
    data, home, units = env
    sd = Systemd(units)
    mk(data, moon, home, units, sd).install(["lasttag"], allow=[])
    src = next(c[-2] for c in sd.runs if c[:2] == ["sudo", "install"])
    assert not Path(src).resolve().is_relative_to(data.resolve())
    assert not Path(src).exists()                                         # and cleaned up


@pytest.mark.parametrize("bad", [{"services": ["../../../x"]}, {"asvc": ["a b"]}, {"files": ["../../printer.cfg"]},
                                 {"files": ["/etc/passwd"]}])
def test_bad_manifest_entries_are_ignored(env, moon, bad):
    data, home, units = env
    dest = data / "config" / "filament-kit"
    dest.mkdir(parents=True)
    (dest / ".manifest").write_text(json.dumps({"files": [], "services": [], "asvc": [], "moonraker": [], **bad}))
    sd = Systemd(units)
    p = mk(data, moon, home, units, sd)
    m = p.manifest()
    assert m["services"] == [] and m["asvc"] == [] and m["files"] == []
    assert any("ignoring" in s for s in p.said)
    p.uninstall()
    assert (data / "config" / "printer.cfg").exists()
    assert not any(c[:2] == ["sudo", "rm"] for c in sd.runs)
