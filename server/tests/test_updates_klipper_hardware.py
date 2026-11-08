"""The updater's hardware feed for klipper_hardware.xml (spec §4.1: the feed is a list of assets)."""
from __future__ import annotations

import re

import pytest

from filament_kit import updates
from filament_kit.bridge import hardware
from filament_kit.bridge.klipper import hardware as khw
from test_updates import Runner, _cfg, _state, env, key, srv  # noqa: F401  (fixtures)
from test_updates_hardware import xml as bambu_xml

KHW = "klipper_hardware.xml"
KBUNDLED = khw.BUNDLED.read_bytes()


def kxml(version: str) -> bytes:
    text, n = re.subn(r'<klipper-hardware version="[^"]*">', f'<klipper-hardware version="{version}">',
                      KBUNDLED.decode("utf-8"), count=1)
    assert n == 1
    return text.encode("utf-8")


@pytest.fixture
def overrides(env):
    hardware._reset_cache()
    khw._reset_cache()
    yield env / "etc" / "bambu_hardware.xml", env / "etc" / KHW
    hardware._reset_cache()
    khw._reset_cache()


def _update(env, srv):
    return updates.update(_cfg(env), fetcher=srv.fetcher(), run=Runner(), now=50.0)


def test_feed_installs_klipper_asset(env, srv, key, overrides, capsys):
    b, k = overrides
    srv.add("1.0.0", extra={"bambu_hardware.xml": bambu_xml("1.5"), KHW: kxml("1.2")})
    assert _update(env, srv) == 0
    assert b.read_bytes() == bambu_xml("1.5") and k.read_bytes() == kxml("1.2")
    st = _state(env)
    assert st["hardware"]["version"] == "1.5"              # the Bambu key is unchanged (existing installs)
    assert st["hardware_klipper"]["version"] == "1.2"
    assert khw.load().errors == []
    assert "installed klipper_hardware.xml version 1.2" in capsys.readouterr().out


def test_klipper_only_release(env, srv, key, overrides):
    b, k = overrides
    srv.add("1.0.0", extra={KHW: kxml("1.2")})
    assert _update(env, srv) == 0
    assert k.exists() and not b.exists()


def test_hand_made_klipper_override_untouched(env, srv, key, overrides, capsys):
    b, k = overrides
    k.write_bytes(kxml("1.7"))
    srv.add("1.0.0", extra={KHW: kxml("1.9")})
    assert _update(env, srv) == 0
    assert k.read_bytes() == kxml("1.7")
    assert "hand-made override" in capsys.readouterr().out


def test_bad_klipper_file_is_refused_bambu_still_installed(env, srv, key, overrides):
    b, k = overrides
    bad = kxml("1.2").replace(b'system="single" verified="true"', b'system="nope" verified="true"', 1)
    srv.add("1.0.0", extra={"bambu_hardware.xml": bambu_xml("1.5"), KHW: bad})
    assert _update(env, srv) == 1
    assert b.read_bytes() == bambu_xml("1.5") and not k.exists()


def test_release_build_publishes_the_klipper_files():
    from test_updates import ROOT
    make = (ROOT / "tools/make_release.sh").read_text(encoding="utf-8")
    wf = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'cp server/filament_kit/bridge/klipper/klipper_hardware.xml "$dist/klipper_hardware.xml"' in make
    assert "fk-printer-pack.tar.gz" in make
    sums = re.search(r'assets="([^"]*)"', wf).group(1)
    assert "klipper_hardware.xml" in sums and "fk-printer-pack.tar.gz" in sums
    assert wf.count("dist/klipper_hardware.xml") >= 2 and wf.count("dist/fk-printer-pack.tar.gz") >= 2
