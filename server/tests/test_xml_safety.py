"""C1: XML 1.0 cannot hold most control characters; a name from the LAN must never make a data file unreadable."""
from filament_kit.bridge import registry, xmlfile
from filament_kit.bridge.klipper import detect
from filament_kit.bridge.klipper import usage as kusage


def test_clean_drops_invalid_xml_characters():
    assert xmlfile.clean("evil\x01na\x00me￾ ok\t") == "evilname ok\t"
    assert xmlfile.clean(None) == ""


def test_registry_survives_a_control_character_in_a_name(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    registry.set_code("SER1", "12345678", "H2D")
    registry.detected("SER2", "192.0.2.5", name="evil\x01name")
    got = registry.load()
    assert set(got) == {"SER1", "SER2"} and got["SER2"].name == "evilname"
    registry.add_klipper("bad\x02name", "printer.home.arpa")
    assert len(registry.load()) == 3


def test_usage_log_survives_a_control_character_in_a_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    kusage.record("p", {"job_id": "1", "filename": "a\x01b.gcode", "status": "completed", "end_time": 1e9}, 3)
    kusage.record("p", {"job_id": "2", "filename": "c.gcode", "status": "completed", "end_time": 1e9}, 3)
    assert [e["job"] for e in kusage.entries("p", 1e6)] == ["2", "1"]


def test_detected_xml_survives_control_characters(tmp_path):
    d = detect.Detected("generic", "single", True, "host\x01", ["object x\x02"])
    detect.save(d, tmp_path / "d.xml")
    assert detect.read(tmp_path / "d.xml").hostname == "host"
