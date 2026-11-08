"""The kit never replaces a Spoolman it did not install; Spoolman's listener answers only the home network, by a list its
owner can edit; after an update the new program installs the hardware data."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import apply, cli, config, modules, updates

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "install" / "spoolman.sh").read_text(encoding="utf-8")


def _check(tmp_path, *, opt=True, marker=False, unit=None):
    """Run only the script's check, as the installer would reach it."""
    block = SCRIPT[SCRIPT.index("# BEGIN foreign-spoolman check"):SCRIPT.index("# END foreign-spoolman check")]
    o = tmp_path / "opt-spoolman"
    if opt:
        o.mkdir()
    if marker:
        (o / ".fk-installed").write_text("old\n")
    u = tmp_path / "spoolman.service"
    if unit:
        u.write_text(unit)
    script = tmp_path / "check.sh"
    script.write_text(f"""set -euo pipefail
die() {{ printf 'error: %s\\n' "$*" >&2; exit 1; }}
SPOOLMAN_OPT={o.as_posix()}
SPOOLMAN_MARKER=$SPOOLMAN_OPT/.fk-installed
SPOOLMAN_UNIT={u.as_posix()}
{block}
echo went-on
""", newline="\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False)


needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="a POSIX shell")


@needs_bash
def test_a_fresh_machine_goes_on(tmp_path):
    assert "went-on" in _check(tmp_path, opt=False).stdout


@needs_bash
def test_a_spoolman_the_kit_did_not_install_is_refused_and_says_what_to_do(tmp_path):
    r = _check(tmp_path)
    assert r.returncode == 1 and "went-on" not in r.stdout
    assert "modules disable spoolman" in r.stderr and ".fk-installed" in r.stderr and "Nothing was changed" in r.stderr


@needs_bash
def test_its_own_unit_with_another_description_is_refused(tmp_path):
    assert _check(tmp_path, unit="[Unit]\nDescription=Spoolman\n").returncode == 1


@needs_bash
def test_an_upgrade_never_refuses(tmp_path):
    assert "went-on" in _check(tmp_path, marker=True).stdout


@needs_bash
def test_an_install_stopped_before_the_marker_is_still_the_kits(tmp_path):
    unit = (ROOT / "install" / "systemd" / "spoolman.service").read_text(encoding="utf-8")
    assert "went-on" in _check(tmp_path, unit=unit).stdout


def test_the_check_comes_before_anything_is_replaced():
    assert SCRIPT.index("# BEGIN foreign-spoolman check") < SCRIPT.index('mv "$SPOOLMAN_OPT"')
    assert SCRIPT.index("# BEGIN foreign-spoolman check") < SCRIPT.index("curl -fsSL")


def test_the_units_description_is_what_the_check_looks_for():
    assert "\nDescription=Spoolman filament inventory" in (ROOT / "install/systemd/spoolman.service").read_text(encoding="utf-8")


# ---------- the allow-list ----------

def test_the_default_comes_from_web_lan():
    assert apply.spoolman_dropin({}) == ("[Service]\nIPAddressDeny=any\n"
                                         "IPAddressAllow=localhost 192.168.0.0/16 10.0.0.0/8\n")


def test_a_custom_web_lan_carries_over_and_its_own_setting_wins():
    assert "198.51.100.0/24" in apply.spoolman_dropin({"web": {"lan": ["198.51.100.0/24"]}})
    d = apply.spoolman_dropin({"web": {"lan": ["198.51.100.0/24"]}, "spoolman": {"allow": ["100.64.0.0/10", "fd7a::/48"]}})
    assert "IPAddressAllow=localhost 100.64.0.0/10 fd7a::/48\n" in d and "198.51" not in d


def test_an_empty_list_means_this_machine_only():
    assert "IPAddressAllow=localhost\n" in apply.spoolman_dropin({"spoolman": {"allow": []}})


@pytest.mark.parametrize("bad,word", [(["nope"], "not a network"), (["0.0.0.0/0"], "every address"), (["::/0"], "every address"),
                                      ("10.0.0.0/8", "must be a list"), (["10.0.0.0/8\nExecStart=/bin/sh"], "not a network")])
def test_a_bad_list_is_refused_naming_the_setting(bad, word):
    with pytest.raises(modules.ModuleError) as e:
        apply.spoolman_dropin({"spoolman": {"allow": bad}})
    assert "spoolman.allow" in str(e.value) and word in str(e.value)


def test_the_plan_installs_it_only_with_the_module_on():
    on = {"modules": {n: n in {"spoolman"} for n in modules.MODULES}, "spoolman_url": "http://127.0.0.1:7912"}
    files = [a.arg for a in apply.plan(on) if a.kind == "install_file"]
    assert any(f[0] == apply.SPOOLMAN_DROPIN and f[2:] == ("0644", "root:root") for f in files)
    off = {"modules": {n: n in {"server"} for n in modules.MODULES}, "spoolman_url": "http://192.0.2.31:7912"}
    assert not any(a.kind == "install_file" and a.arg[0] == apply.SPOOLMAN_DROPIN for a in apply.plan(off))


def test_the_dropin_goes_in_before_the_unit_is_started():
    on = {"modules": {n: n in {"spoolman"} for n in modules.MODULES}, "spoolman_url": "http://127.0.0.1:7912"}
    kinds = [(a.kind, a.arg) for a in apply.plan(on)]
    at = next(i for i, (k, x) in enumerate(kinds) if k == "install_file" and x[0] == apply.SPOOLMAN_DROPIN)
    assert at < kinds.index(("daemon_reload", "")) < kinds.index(("enable", "spoolman.service"))


def test_uninstall_removes_it():
    assert "spoolman.service.d" in (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")


# ---------- the feed after an update ----------

class Fetcher:
    def release(self, repo, version=None):
        return {"version": "0.6.0", "assets": {}}


def _exe():
    exe = config.paths().opt / "venv" / "bin" / "filament-kit"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    return exe


@pytest.mark.parametrize("rc,want", [(0, 0), (1, 1), (7, 1)])
def test_after_an_install_the_new_program_runs_the_feed(monkeypatch, rc, want):
    exe = _exe()
    seen = []
    monkeypatch.setattr(updates, "_feed", lambda f, r: pytest.fail("ran in the old process"))
    assert updates._feed_after_install({}, Fetcher(), {}, lambda cmd: seen.append(cmd) or rc) == want
    assert seen == [[str(exe), "update", "--feed"]]


def test_a_new_program_that_will_not_start_is_said_not_raised(capsys):
    _exe()

    def boom(cmd):
        raise OSError("exec format error")
    assert updates._feed_after_install({}, Fetcher(), {}, boom) == 1
    assert "cannot run the new program" in capsys.readouterr().err


def test_with_no_installed_program_it_runs_here(monkeypatch):
    monkeypatch.setattr(updates, "_feed", lambda f, r: 5)
    assert updates._feed_after_install({}, Fetcher(), {}, lambda c: pytest.fail("ran")) == 5


def test_update_feed_runs_the_feed_alone(monkeypatch):
    called = []
    monkeypatch.setattr(updates, "feed_now", lambda cfg: called.append(1) or 3)
    monkeypatch.setattr(updates, "update", lambda *a, **k: pytest.fail("updated"))
    assert cli.main(["update", "--feed"]) == 3 and called == [1]


def test_feed_now_says_a_release_it_cannot_read(capsys):
    class Down:
        def release(self, repo, version=None):
            raise updates.ReleaseError("cannot reach api.github.com")
    assert updates.feed_now({}, fetcher=Down()) == 1
    assert "hardware data: cannot reach" in capsys.readouterr().err
