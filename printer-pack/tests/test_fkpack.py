"""The printer pack installer (printer-pack/fkpack.py), against a temporary printer_data and a fake Moonraker.

Run with the server's test environment: `server/.venv/Scripts/python -m pytest printer-pack/tests` (it borrows the
server tests' FakeMoonraker).
"""
import ast
import http.client
import os
import subprocess
import sys
import urllib.error
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


def test_installed_scripts_use_the_packs_moonraker(data, moon):
    """Not always :7125: a second Moonraker on the printer, or --moonraker, must reach the scripts."""
    shell_command(data)
    pack(data, moon).install(["check", "loadtemp"])
    scripts = data / "config" / "filament-kit" / "scripts"
    for name in ("fk_spool_check.py", "fk_load_temp.py"):
        text = (scripts / name).read_text(encoding="utf-8")
        assert f'MOONRAKER = "{moon.url}"' in text and "7125" not in text


def test_moonraker_edits(data, moon):
    p = pack(data, moon)
    p.install(["moonraker"], spoolman="http://kit.example.com:7912")
    conf = (data / "config" / "moonraker.conf").read_text()
    assert "server: http://kit.example.com:7912" in conf and "old.example.com" not in conf
    assert "[zeroconf]" in conf and "[authorization]" in conf


KIT = "http://kit.example.com:7912"


def test_moonraker_edit_offers_its_own_restart(data, moon):
    p = pack(data, moon)
    p.install(["moonraker"], spoolman=KIT)
    assert moon.actions == ["server_restart"]       # no Klipper restart: no Klipper config changed
    assert any("Moonraker is restarting" in s for s in p.said)


def test_klipper_restarts_first_and_both_use_one_idle_check(data, moon):
    """Klipper restarting makes the printer's state unreadable, so the second question must not read it again."""
    p = pack(data, moon)
    states = []
    real = p.print_state
    p.print_state = lambda: states.append(1) or real()
    p.install(["spool", "moonraker"], spoolman=KIT)
    assert moon.actions == ["restart", "server_restart"] and len(states) == 1


def test_moonraker_restart_is_its_own_question(data, moon):
    asked = []
    p = fkpack.Pack(str(data), moon.url, home=str(data.parent), out=lambda s: None,
                    ask=lambda q: asked.append(q) or "Restart Moonraker" not in q)
    p.install(["spool", "moonraker"], spoolman=KIT)
    assert moon.actions == ["restart"]
    assert [q for q in asked if q.startswith("Restart")] == ["Restart Klipper now to load the macros?",
                                                             "Restart Moonraker now to use its new settings?"]


def test_no_moonraker_restart_when_nothing_changed(data, moon):
    pack(data, moon).install(["moonraker"], spoolman=KIT)
    moon.actions.clear()
    pack(data, moon).install(["moonraker"], spoolman=KIT)
    assert moon.actions == []


def test_no_moonraker_restart_when_the_edit_is_declined(data, moon):
    asked = []
    p = fkpack.Pack(str(data), moon.url, home=str(data.parent), out=lambda s: None,
                    ask=lambda q: asked.append(q) or False)
    p.install(["moonraker"], spoolman=KIT)
    assert moon.actions == [] and not any("Restart" in q for q in asked)
    assert (data / "config" / "moonraker.conf").read_text() == MOONRAKER_CONF


def test_no_moonraker_restart_while_printing(data, moon):
    moon.status["print_stats"]["state"] = "printing"
    p = pack(data, moon)
    p.install(["moonraker"], spoolman=KIT)
    assert moon.actions == []
    assert any("Moonraker must restart" in s and "printing" in s for s in p.said)


def _restart_raises(monkeypatch, error, path="/server/restart"):
    real = fkpack.urllib.request.urlopen

    def fail_restart(req, *a, **kw):
        if getattr(req, "full_url", "").endswith(path):
            raise error
        return real(req, *a, **kw)
    monkeypatch.setattr(fkpack.urllib.request, "urlopen", fail_restart)


@pytest.mark.parametrize("error", [urllib.error.URLError("connection refused"),
                                   urllib.error.HTTPError("u", 500, "broken", None, None), TimeoutError("slow")])
def test_a_failed_moonraker_restart_only_says_so(data, moon, monkeypatch, error):
    """The request never arrived, or was refused: the person has to do it."""
    _restart_raises(monkeypatch, error)
    p = pack(data, moon)
    assert p.install(["moonraker"], spoolman=KIT) == 0
    assert any("restart it yourself" in s for s in p.said)
    assert not any("Moonraker is restarting" in s for s in p.said)


@pytest.mark.parametrize("error", [ConnectionResetError("reset"), ConnectionAbortedError("aborted"),
                                   http.client.RemoteDisconnected("closed")])
@pytest.mark.parametrize("path, what, parts", [("/server/restart", "Moonraker", ["moonraker"]),
                                                ("/printer/restart", "Klipper", ["spool"])])
def test_a_connection_dropped_while_answering_means_it_is_restarting(data, moon, monkeypatch, error, path, what, parts):
    """Sent, and then the server went away, as one about to restart may. Not a failure to tell the person about."""
    _restart_raises(monkeypatch, error, path)
    p = pack(data, moon)
    assert p.install(parts, spoolman=KIT) == 0
    assert any(f"{what} is restarting" in s for s in p.said)
    assert not any("restart it yourself" in s for s in p.said)


def test_a_refused_klipper_restart_says_so_instead_of_a_traceback(data, moon, monkeypatch):
    _restart_raises(monkeypatch, urllib.error.URLError("connection refused"), "/printer/restart")
    p = pack(data, moon)
    assert p.install(["spool"]) == 0
    assert any("could not ask Klipper to restart" in s for s in p.said)


def _asking(data, moon, answers):
    """A pack whose URL question gets `answers` in turn; y/N is always yes."""
    said, asked = [], []
    left = list(answers)

    def prompt(q):
        asked.append(q)
        return left.pop(0) if left else ""
    p = fkpack.Pack(str(data), moon.url, home=str(data.parent), ask=lambda q: True, out=said.append, prompt=prompt)
    p.said, p.asked = said, asked
    return p


def test_interactive_asks_for_the_spoolman_url(data, moon):
    p = _asking(data, moon, [KIT])
    p.install(["moonraker"])
    assert len(p.asked) == 1 and "Spoolman" in p.asked[0]
    assert f"server: {KIT}" in (data / "config" / "moonraker.conf").read_text()


def test_a_given_url_is_not_asked_for(data, moon):
    p = _asking(data, moon, [])
    p.install(["moonraker"], spoolman=KIT)
    assert p.asked == []


def test_only_the_parts_that_use_it_ask(data, moon):
    p = _asking(data, moon, [KIT])
    p.install(["spool"])
    assert p.asked == []


def test_an_empty_answer_leaves_it_and_says_so(data, moon):
    p = _asking(data, moon, [""])
    p.install(["moonraker"])
    conf = (data / "config" / "moonraker.conf").read_text()
    assert "server: http://old.example.com:7912" in conf
    assert any("[spoolman] is left as it is" in s for s in p.said)


def test_no_url_with_yes_says_so_instead_of_skipping_silently(data, moon):
    """--yes answers no question: the pack must not leave a printer with no usage and no word about it."""
    p = pack(data, moon)
    p.prompt = lambda q: ""
    p.install(["moonraker"])
    assert any("[spoolman] is left as it is" in s for s in p.said)


@pytest.mark.parametrize("bad", ["not a url", "ftp://kit.example.com", "http://kit example.com:7912",
                                 "http://kit.example.com:7912\n[evil]", "kit.example.com:7912"])
def test_a_bad_answer_is_asked_again_then_left(data, moon, bad):
    p = _asking(data, moon, [bad, KIT])
    p.install(["moonraker"])
    assert len(p.asked) == 2 and f"server: {KIT}" in (data / "config" / "moonraker.conf").read_text()
    p = _asking(data, moon, [bad, bad, bad, bad])
    (data / "config" / "moonraker.conf").write_text(MOONRAKER_CONF, encoding="utf-8")
    p.install(["moonraker"])
    assert len(p.asked) == 3 and (data / "config" / "moonraker.conf").read_text().count("old.example.com") == 1


@pytest.mark.parametrize("bad", ["not a url", "http://a b", "http://kit.example.com\n[evil]"])
def test_a_bad_spoolman_option_is_refused(data, moon, bad):
    (data / "config" / "moonraker.conf").write_text(MOONRAKER_CONF, encoding="utf-8")
    with pytest.raises(fkpack.PackError, match="Spoolman URL"):
        pack(data, moon).install(["moonraker"], spoolman=bad)
    assert (data / "config" / "moonraker.conf").read_text() == MOONRAKER_CONF


def test_set_section_finds_a_header_with_a_comment():
    """It used to add a second [spoolman] section beside `[spoolman] # mine`."""
    text = "[spoolman] # mine\nserver: http://old:1\n\n[history]\n"
    out = fkpack.set_section(text, "spoolman", {"server": "http://new:2"})
    assert out.count("[spoolman]") == 1 and "server: http://new:2" in out and "http://old:1" not in out
    assert fkpack.set_section("[spoolman]; x\nserver: a\n", "spoolman", {"server": "b"}).count("[spoolman]") == 1


def test_a_commented_out_zeroconf_is_not_a_zeroconf(data, moon):
    conf = data / "config" / "moonraker.conf"
    conf.write_text("[server]\nhost: 0.0.0.0\n# [zeroconf]\n", encoding="utf-8")
    pack(data, moon).install(["moonraker"], spoolman=KIT)
    assert "\n[zeroconf]\n" in conf.read_text()
    before = conf.read_text()
    moon.actions.clear()
    pack(data, moon).install(["moonraker"], spoolman=KIT)
    assert conf.read_text() == before and moon.actions == []


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


def _fake_nfc_run(home):
    def run(cmd, **kw):
        if cmd[:2] == ["git", "clone"]:
            d = Path(cmd[-1])
            d.mkdir(parents=True)
            (d / ".git").mkdir()
            (d / "nfc2klipper.cfg").write_text(UPSTREAM, encoding="utf-8")
            (d / "requirements.txt").write_text("", encoding="utf-8")
    return run


def test_a_reader_the_pack_installs_brings_the_spool_macros_its_gcode_calls(data, moon, tmp_path, monkeypatch):
    """nfc2klipper's setting_gcode calls _FK_SCAN_OK, and only fk_spool.cfg defines it."""
    home = tmp_path / "home"
    home.mkdir()
    said = []
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=lambda q: True, out=said.append, run=_fake_nfc_run(home),
                    units_dir=str(tmp_path / "units"), prompt=lambda q: KIT)
    monkeypatch.setattr(p, "install_services", lambda *a: None)
    monkeypatch.setattr(p, "patches", lambda: [])
    monkeypatch.setattr(p, "nfc_status", lambda: (False, []))
    p.install(["nfc"])
    assert (data / "config" / "filament-kit" / "fk_spool.cfg").exists()
    assert any("uses the spool part's macros" in s for s in said)
    assert '"' + KIT + '"' in (home / ".config" / "nfc2klipper" / "nfc2klipper.cfg").read_text()


def test_an_adopted_reader_brings_nothing(data, moon, tmp_path, monkeypatch):
    p = fkpack.Pack(str(data), moon.url, home=str(tmp_path), ask=lambda q: True, out=lambda s: None,
                    prompt=lambda q: pytest.fail("asked for a URL it can't use"))
    monkeypatch.setattr(p, "nfc_status", lambda: (True, ["adopted"]))
    p.install(["nfc"])
    assert not (data / "config" / "filament-kit" / "fk_spool.cfg").exists()


def _reader_pack(data, moon, tmp_path, monkeypatch, answer=KIT):
    home = tmp_path / "home"
    home.mkdir()
    said, asked = [], []

    def prompt(q):
        asked.append(q)
        return answer
    p = fkpack.Pack(str(data), moon.url, home=str(home), ask=lambda q: True, out=said.append, run=_fake_nfc_run(home),
                    units_dir=str(tmp_path / "units"), prompt=prompt)
    monkeypatch.setattr(p, "install_services", lambda *a: None)
    monkeypatch.setattr(p, "patches", lambda: [])
    p.said, p.asked, p.reader_cfg = said, asked, home / ".config" / "nfc2klipper" / "nfc2klipper.cfg"
    return p


def _left_at(p, state):
    """A checkout the pack's last run left in `state`."""
    d = Path(p.nfc_dir())
    d.mkdir(parents=True)
    (d / "nfc2klipper.cfg").write_text(UPSTREAM, encoding="utf-8")
    (d / "requirements.txt").write_text("", encoding="utf-8")
    m = p.manifest()
    m["nfc"] = {"dir": str(d), "state": state}
    p.save_manifest(m)


def test_a_reader_with_no_url_says_its_config_keeps_the_example(data, moon, tmp_path, monkeypatch):
    p = _reader_pack(data, moon, tmp_path, monkeypatch, answer="")
    monkeypatch.setattr(p, "nfc_status", lambda: (False, []))
    p.install(["nfc"])
    line = [s for s in p.said if "no Spoolman URL" in s]
    assert len(line) == 1 and str(p.reader_cfg) in line[0] and "spoolman-url" in line[0]


def test_a_reader_with_a_url_says_nothing_about_it(data, moon, tmp_path, monkeypatch):
    p = _reader_pack(data, moon, tmp_path, monkeypatch)
    monkeypatch.setattr(p, "nfc_status", lambda: (False, []))
    p.install(["nfc"])
    assert not any("no Spoolman URL" in s for s in p.said)


def test_finishing_a_started_install_asks_for_the_url(data, moon, tmp_path, monkeypatch):
    """It writes the reader's config, so it needs the answer as much as a first install does."""
    p = _reader_pack(data, moon, tmp_path, monkeypatch)
    _left_at(p, "started")
    monkeypatch.setattr(p, "nfc_status", lambda: (True, []))
    p.install(["nfc"])
    assert len(p.asked) == 1 and '"' + KIT + '"' in p.reader_cfg.read_text()


def test_a_reader_the_pack_finished_is_not_asked_about(data, moon, tmp_path, monkeypatch):
    p = _reader_pack(data, moon, tmp_path, monkeypatch)
    _left_at(p, "done")
    monkeypatch.setattr(p, "nfc_status", lambda: (True, []))
    p.install(["nfc"])
    assert p.asked == []


def test_a_folder_the_pack_will_not_touch_is_not_asked_about(data, moon, tmp_path, monkeypatch):
    p = _reader_pack(data, moon, tmp_path, monkeypatch)
    Path(p.nfc_dir()).mkdir(parents=True)
    p.install(["nfc"])
    assert p.asked == []


def test_a_reader_from_an_earlier_pack_gets_the_macros_its_gcode_calls(data, moon, tmp_path, monkeypatch):
    p = _reader_pack(data, moon, tmp_path, monkeypatch)
    _left_at(p, "done")
    monkeypatch.setattr(p, "nfc_status", lambda: (True, []))
    p.install(["nfc"])
    assert (data / "config" / "filament-kit" / "fk_spool.cfg").exists()


def test_a_foreign_macro_file_still_records_the_reader(data, moon, tmp_path, monkeypatch):
    """The reader is in by then: the next run mustn't think otherwise because the spool part refused."""
    p = _reader_pack(data, moon, tmp_path, monkeypatch)
    monkeypatch.setattr(p, "nfc_status", lambda: (False, []))
    (data / "config" / "filament-kit").mkdir(parents=True, exist_ok=True)
    (data / "config" / "filament-kit" / "fk_spool.cfg").write_text("# the owner's own\n")
    with pytest.raises(fkpack.PackError):
        p.install(["nfc"])
    assert p.manifest()["nfc"]["state"] == "done"


def test_the_checks_come_before_the_question(data, moon):
    (data / "config" / "printer.cfg").unlink()
    p = _asking(data, moon, [KIT])
    with pytest.raises(fkpack.PackError):
        p.install(["moonraker"])
    assert p.asked == []


@pytest.mark.parametrize("name", ["kit.local", "kit.example.com"])
def test_lasttag_allow_refuses_a_name(data, moon, name):
    """lasttag compares the caller's address with the list as text: a name would lock the kit out, with no word."""
    p = pack(data, moon)
    with pytest.raises(fkpack.PackError, match="IP address"):
        p.install(["lasttag"], allow=[name])
    assert not (data / "config" / "filament-kit" / "lasttag" / "allow").exists()


def test_the_readers_gcode_records_the_spool_against_the_active_tool():
    """Only SET_ACTIVE_SPOOL would be undone by the next _FK_TOOL_CHANGED, which reads the tool table."""
    out = fkpack.nfc_config(UPSTREAM, "tty:USB0:pn532", "", "http://localhost:7125", False)
    assert "_FK_TAG_SPOOL ID={spool}" in out and "_FK_SCAN_OK ID={spool}" in out
    assert "\nSET_ACTIVE_SPOOL" not in out


def test_the_tag_macro_is_in_the_spool_part(data, moon):
    pack(data, moon).install(["spool"])
    cfg = (data / "config" / "filament-kit" / "fk_spool.cfg").read_text()
    assert "[gcode_macro _FK_TAG_SPOOL]" in cfg


LOOKUP_LINE = "_FK_ON_SPOOL_SET"


def _own_macro(moon, gcode):
    moon.objects = [*moon.objects, "gcode_macro SET_ACTIVE_SPOOL", "configfile"]
    moon.status["configfile"] = {"settings": {"gcode_macro set_active_spool": {"gcode": gcode}}}


def test_load_temp_says_when_the_printers_own_macro_will_not_trigger_it(data, moon):
    shell_command(data)
    _own_macro(moon, "SAVE_VARIABLE VARIABLE=spool VALUE={params.ID}")
    p = pack(data, moon)
    p.install(["spool", "loadtemp"])
    line = [s for s in p.said if LOOKUP_LINE in s]
    assert len(line) == 1 and "SET_ACTIVE_SPOOL" in line[0]
    assert "gcode_macro" not in (data / "config" / "printer.cfg").read_text()      # its macro is the owner's


def test_load_temp_says_nothing_when_the_owner_added_the_hook(data, moon):
    shell_command(data)
    _own_macro(moon, "_FK_ON_SPOOL_SET ID={params.ID}")
    p = pack(data, moon)
    p.install(["spool", "loadtemp"])
    assert not any(LOOKUP_LINE in s for s in p.said)


def test_load_temp_says_nothing_with_the_packs_own_macro(data, moon):
    shell_command(data)
    moon.objects = ["print_stats", "toolhead"]
    p = pack(data, moon)
    p.install(["spool", "loadtemp"])
    assert not any(LOOKUP_LINE in s for s in p.said)


def test_load_temp_alone_says_it_needs_the_spool_part(data, moon):
    shell_command(data)
    p = pack(data, moon)
    p.install(["loadtemp"])
    assert any("spool part" in s for s in p.said)
