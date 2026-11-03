"""The updater's hardware data feed (spec R 2.5, Ruling BG): a signed bambu_hardware.xml release asset, verified
and validated before it replaces /etc/filament-kit/bambu_hardware.xml."""
from __future__ import annotations

import re

import pytest

from filament_kit import updates
from filament_kit.bridge import hardware
from test_updates import Runner, _cfg, _state, env, key, srv  # noqa: F401  (fixtures)

HW = "bambu_hardware.xml"
BUNDLED = hardware.BUNDLED.read_bytes()


def xml(version: str, *, broken: bool = False) -> bytes:
    text = BUNDLED.decode("utf-8")
    text, n = re.subn(r'<bambu-hardware version="[^"]*">', f'<bambu-hardware version="{version}">', text, count=1)
    assert n == 1
    if broken:
        text = text.replace('nozzles="2"', 'nozzles="0"', 1)
    return text.encode("utf-8")


@pytest.fixture
def override(env):
    hardware._reset_cache()
    yield env / "etc" / HW
    hardware._reset_cache()


def _update(env, srv, **kw):
    return updates.update(_cfg(env), fetcher=srv.fetcher(), run=Runner(), now=50.0, **kw)


def test_a_newer_verified_file_is_installed(env, srv, key, override, capsys):
    data = xml("1.5")
    srv.add("1.0.0", extra={HW: data})
    assert _update(env, srv) == 0
    assert override.read_bytes() == data
    assert _state(env)["hardware"]["version"] == "1.5"
    assert "installed bambu_hardware.xml version 1.5" in capsys.readouterr().out
    assert hardware.load().errors == []
    # a second run finds it in place
    assert _update(env, srv) == 0 and override.read_bytes() == data


def test_the_previous_override_is_kept(env, srv, key, override):
    old = xml("1.2")
    override.write_bytes(old)
    srv.add("1.0.0", extra={HW: xml("1.5")})
    assert _update(env, srv) == 0
    assert override.with_name(HW + ".previous").read_bytes() == old
    assert override.read_bytes() == xml("1.5")


def test_an_older_or_equal_override_feed_does_not_replace_a_newer_one(env, srv, key, override, capsys):
    mine = xml("1.7")
    override.write_bytes(mine)
    srv.add("1.0.0", extra={HW: xml("1.5")})
    assert _update(env, srv) == 0
    assert override.read_bytes() == mine
    assert "as new" in capsys.readouterr().out


@pytest.mark.parametrize("version", ["1", "1.0"])
def test_the_bundled_file_is_not_overwritten_by_an_older_feed(env, srv, key, override, version, capsys):
    srv.add("1.0.0", extra={HW: xml(version)})                # the bundled file is version 1
    assert _update(env, srv) == 0
    assert not override.exists()
    assert "as new" in capsys.readouterr().out


def test_a_feed_file_older_than_a_newer_kits_bundled_file_is_retired(env, srv, key, override, tmp_path,
                                                                     monkeypatch, capsys):
    srv.add("1.0.0", extra={HW: xml("1.5")})
    assert _update(env, srv) == 0 and override.exists()
    newer = tmp_path / "bundled.xml"                          # the kit is upgraded: its own file is now 1.6
    newer.write_bytes(xml("1.6"))
    monkeypatch.setattr(hardware, "BUNDLED", newer)
    assert _update(env, srv) == 0
    assert not override.exists()                              # the old feed file would win per element
    assert override.with_name(HW + ".previous").read_bytes() == xml("1.5")
    assert "kit's own" in capsys.readouterr().out


def test_a_hand_made_override_is_never_retired(env, srv, key, override, tmp_path, monkeypatch):
    mine = xml("1.2")
    override.write_bytes(mine)
    srv.add("1.0.0")
    newer = tmp_path / "bundled.xml"
    newer.write_bytes(xml("1.6"))
    monkeypatch.setattr(hardware, "BUNDLED", newer)
    assert _update(env, srv) == 0
    assert override.read_bytes() == mine


def test_a_file_that_fails_validation_is_never_installed(env, srv, key, override, capsys):
    srv.add("1.0.0", extra={HW: xml("1.5", broken=True)})
    assert _update(env, srv) == 1
    assert not override.exists()
    err = capsys.readouterr().err
    assert "hardware data" in err and "not installed" in err


def test_another_major_version_is_refused(env, srv, key, override, capsys):
    srv.add("1.0.0", extra={HW: xml("2.0")})
    assert _update(env, srv) == 1
    assert not override.exists()


@pytest.mark.parametrize("kw", [{"tamper_extra": True}, {"unlisted": {HW: xml("1.5")}}, {"tamper_sig": True}])
def test_an_unverified_file_is_never_installed(env, srv, key, override, kw, capsys):
    srv.add("1.0.0", **({"extra": {HW: xml("1.5")}} if "unlisted" not in kw else {}), **kw)
    assert _update(env, srv) == 1
    assert not override.exists()
    assert "not installed" in capsys.readouterr().err


def test_a_release_without_hardware_data_changes_nothing(env, srv, key, override):
    srv.add("1.0.0")
    assert _update(env, srv) == 0
    assert not override.exists()


def test_the_feed_also_runs_after_a_program_update(env, srv, key, override):
    srv.add("1.0.0")
    srv.add("1.1.0", extra={HW: xml("1.5")})
    assert _update(env, srv) == 0
    assert override.read_bytes() == xml("1.5")


def test_release_build_signs_and_publishes_the_hardware_file():
    from test_updates import ROOT
    make = (ROOT / "tools/make_release.sh").read_text(encoding="utf-8")
    wf = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'cp server/filament_kit/bridge/bambu_hardware.xml "$dist/bambu_hardware.xml"' in make
    sums = re.search(r"sha256sum (.*?)> SHA256SUMS", wf, re.S).group(1)
    assert "bambu_hardware.xml" in sums
    assert wf.count("dist/bambu_hardware.xml") >= 2           # uploaded by the build job and published
