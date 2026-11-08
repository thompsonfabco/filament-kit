"""registry: printers.xml, the printers.json migration, Klipper fields."""
import json

import pytest

from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path


def _json(env, data):
    (env / "state" / "printers.json").write_text(json.dumps(data), encoding="utf-8")


def test_json_migrates_once(env):
    _json(env, {"S1": {"name": "H2D", "model": "H2D", "ip": "10.0.0.5", "access_code": "12345678",
                       "configured": True, "cert_fp": "ab"}})
    p = registry.load()["S1"]
    assert (p.family, p.access_code, p.configured, p.cert_fp) == ("bambu", "12345678", True, "ab")
    xml = (env / "state" / "printers.xml").read_text(encoding="utf-8")
    assert 'family="bambu"' in xml and "<access-code>12345678</access-code>" in xml
    assert (env / "state" / "printers.json.migrated").exists()
    assert not (env / "state" / "printers.json").exists()
    assert registry.load()["S1"] == p            # second load: same, from the XML


def test_xml_wins_over_a_json_left_behind(env):
    registry.upsert(Printer("S1", "from xml"))
    _json(env, {"S1": {"name": "from json"}})
    assert registry.load()["S1"].name == "from xml"


def test_migration_failure_keeps_json(env, monkeypatch):
    _json(env, {"S1": {"name": "A", "access_code": "x", "configured": True}})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(registry, "_write_atomic", boom)
    assert registry.load()["S1"].name == "A"
    assert (env / "state" / "printers.json").exists()
    assert not (env / "state" / "printers.xml").exists()


def test_secret_not_in_attributes(env):
    registry.upsert(Printer("S1", access_code="12345678", configured=True))
    p = registry.add_klipper("SV08 MAX", "sv08.home.arpa")
    registry.set_api_key(p.serial, "k3y")
    xml = (env / "state" / "printers.xml").read_text(encoding="utf-8")
    assert "access_code=" not in xml and "access-code=" not in xml and "api-key=" not in xml
    assert "<api-key>k3y</api-key>" in xml
    assert "k3y" not in repr(registry.load()[p.serial])


def test_add_klipper_slug_unique(env):
    a = registry.add_klipper("SV08 MAX", "a.home.arpa")
    b = registry.add_klipper("SV08 MAX", "b.home.arpa")
    assert (a.serial, b.serial) == ("sv08-max", "sv08-max-2")
    got = registry.load()["sv08-max"]
    assert (got.family, got.host, got.port, got.configured) == ("klipper", "a.home.arpa", 7125, True)


def test_slug_rules():
    assert registry.slug("", set()) == "printer"
    assert registry.slug("  Ünïcode!! Printer  ", set()) == "n-code-printer"
    assert len(registry.slug("x" * 80, set())) == 48


def test_old_json_without_family_defaults_bambu(env):
    _json(env, {"S9": {"name": "P1S"}})
    assert registry.load()["S9"].family == "bambu"


def test_unknown_xml_attribute_ignored(env):
    (env / "state" / "printers.xml").write_text(
        '<printers version="1"><printer id="S1" family="bambu" name="A" shiny="yes" configured="true">'
        '<gizmo/></printer></printers>', encoding="utf-8")
    assert registry.load()["S1"].name == "A"


def test_unknown_family_reads_as_bambu(env):
    (env / "state" / "printers.xml").write_text(
        '<printers version="1"><printer id="S1" family="prusa"/></printers>', encoding="utf-8")
    assert registry.load()["S1"].family == "bambu"


def test_klipper_names(env):
    registry.upsert(Printer("S1", "H2D"))
    registry.add_klipper("SV08 MAX", "h")
    assert registry.klipper_names() == {"SV08 MAX"}


def test_xml_with_entities_is_refused(env):
    (env / "state" / "printers.xml").write_text(
        '<!DOCTYPE p [<!ENTITY a "b">]><printers version="1"/>', encoding="utf-8")
    with pytest.raises(registry.RegistryError):
        registry.upsert(Printer("S1"))
