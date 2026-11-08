"""bridge.klipper.detect: model and filament-system detection from Moonraker answers."""
import json
from pathlib import Path

import pytest

from filament_kit.bridge.klipper import detect
from filament_kit.bridge.klipper import hardware as kh

DATA = Path(__file__).parent / "data" / "klipper"


def objs(name):
    return json.loads((DATA / name / "objects.json").read_text())["objects"]


@pytest.fixture(autouse=True)
def etc(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path))
    kh._reset_cache()
    yield tmp_path
    kh._reset_cache()


def test_SV08_fixture_detects_SV08():
    info = json.loads((DATA / "SV08-MAX" / "info.json").read_text())
    d = detect.detect(objs("SV08-MAX"), [], info["hostname"], kh.load())
    assert (d.model_key, d.system_key, d.verified) == ("SOVOL-SV08-MAX", "single", True)
    assert any("DEMON_START" in r for r in d.reasons)


def test_SV08_needs_every_rule():
    d = detect.detect(objs("SV08-MAX"), [], "otherhost", kh.load())   # hostname rule fails
    assert d.model_key == "generic"


def test_afc_detects_generic_afc():
    d = detect.detect(objs("afc"), [], "voron", kh.load())
    assert (d.model_key, d.system_key) == ("generic", "afc")


def test_hh_detects_generic_happyhare():
    d = detect.detect(objs("happyhare"), [], "voron", kh.load())
    assert (d.model_key, d.system_key) == ("generic", "happy-hare")


def test_lane_data_namespace_detected():
    d = detect.detect(["print_stats"], ["lane_data", "mainsail"], "x", kh.load())
    assert d.system_key == "lane-data"


def test_empty_is_generic_single():
    d = detect.detect([], [], "", kh.load())
    assert (d.model_key, d.system_key, d.verified) == ("generic", "single", True)


def test_m1d_never_matches_unfilled():
    d = detect.detect(objs("SV08-MAX") + ["gcode_macro T6"], [], "M1D", kh.load())
    assert d.model_key != "sovol-m1d"


def test_override_model_wins_order(etc):
    (etc / "klipper_hardware.xml").write_text(
        '<klipper-hardware version="1.1"><models><model key="mine" name="Mine" system="single">'
        '<detect><object>gcode_macro DEMON_START</object></detect></model></models></klipper-hardware>',
        encoding="utf-8")
    # an override model is appended after the bundled ones; the bundled SV08 still matches first on the SV08
    d = detect.detect(objs("SV08-MAX"), [], "SV08MAX", kh.load())
    assert d.model_key == "SOVOL-SV08-MAX"
    d = detect.detect(objs("SV08-MAX"), [], "elsewhere", kh.load())
    assert d.model_key == "mine"


def test_model_with_system_auto_and_afc():
    hw = kh.load()
    d = detect.detect(objs("afc") + ["gcode_macro DEMON_START"], [], "SV08MAX", hw)
    # the SV08 entry names system single explicitly: its system wins over auto-detection
    assert (d.model_key, d.system_key) == ("SOVOL-SV08-MAX", "single")


def test_unverified_flag_from_model(etc):
    (etc / "klipper_hardware.xml").write_text(
        '<klipper-hardware version="1.1"><models><model key="new" name="New" system="single" verified="false">'
        '<detect><object>gcode_macro NEW_ONE</object></detect></model></models></klipper-hardware>',
        encoding="utf-8")
    d = detect.detect(["gcode_macro NEW_ONE"], [], "h", kh.load())
    assert (d.model_key, d.verified) == ("new", False)


def test_probe_uses_client(moonraker):
    from filament_kit.bridge.klipper.moonraker import Moonraker
    moonraker.objects = objs("afc")
    moonraker.db = {"mainsail": {}}
    d = detect.probe(Moonraker(moonraker.host, moonraker.port), kh.load())
    assert (d.model_key, d.system_key, d.hostname) == ("generic", "afc", "fakeprinter")


def test_detected_xml_roundtrip(tmp_path):
    d = detect.Detected("SOVOL-SV08-MAX", "single", True, "SV08MAX", ["object gcode_macro DEMON_START"])
    p = tmp_path / "detected.xml"
    detect.save(d, p)
    assert detect.read(p) == d
    assert detect.read(tmp_path / "missing.xml") is None
