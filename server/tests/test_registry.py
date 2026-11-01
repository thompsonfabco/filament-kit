import json
import os
import stat

import pytest

from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    return tmp_path


def test_repr_hides_access_code():
    p = Printer(serial="S1", access_code="12345678", configured=True)
    assert "12345678" not in repr(p)


def test_upsert_load_remove_roundtrip():
    registry.upsert(Printer("S1", "Office", "C11", "10.0.0.5", "99887766", True))
    got = registry.load()["S1"]
    assert (got.name, got.model, got.ip, got.access_code, got.configured) == ("Office", "C11", "10.0.0.5", "99887766", True)
    assert registry.remove("S1") is True
    assert registry.remove("S1") is False
    assert registry.load() == {}


def test_detected_adds_unconfigured():
    p = registry.detected("S2", "10.0.0.6", "N2", "Shed")
    assert p.configured is False and p.access_code == ""
    assert registry.load()["S2"].ip == "10.0.0.6"


def test_detected_updates_unconfigured_ip_model_name():
    registry.detected("S2", "10.0.0.6", "N2", "Shed")
    registry.detected("S2", "10.0.0.9", "N2", "Shed 2")
    p = registry.load()["S2"]
    assert (p.ip, p.name, p.configured) == ("10.0.0.9", "Shed 2", False)


def test_detected_updates_ip_of_configured_without_touching_code_or_name():
    registry.upsert(Printer("S3", "Mine", "O1D", "10.0.0.7", "55555555", True))
    registry.detected("S3", "10.0.0.8", "O1D", "Announced name")
    p = registry.load()["S3"]
    assert p.ip == "10.0.0.8"
    assert p.access_code == "55555555" and p.configured is True and p.name == "Mine"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_file_mode_600(env):
    registry.upsert(Printer("S1", access_code="x", configured=True))
    f = env / "state" / "printers.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_file_is_json_keyed_by_serial(env):
    registry.upsert(Printer("S1", "A"))
    assert json.loads((env / "state" / "printers.json").read_text())["S1"]["name"] == "A"
