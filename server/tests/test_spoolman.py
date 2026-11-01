import pytest

from filament_kit.spoolman import Spoolman, SpoolmanError
from conftest import free_port

NAMES = ["nfc_id", "prev_location", "nozzle_range", "bed_range", "line"]


def test_ping_returns_version(spoolman_url):
    assert Spoolman(spoolman_url).ping() == "0.27.0"


def test_ensure_fields_idempotent(spoolman_url, spoolman_fake_store):
    sm = Spoolman(spoolman_url)
    assert sorted(sm.ensure_fields()) == sorted(NAMES)
    assert sm.ensure_fields() == []
    assert {f["key"] for f in spoolman_fake_store["fields"]["spool"]} == {"nfc_id", "prev_location"}
    assert {f["key"] for f in spoolman_fake_store["fields"]["filament"]} == {"nozzle_range", "bed_range", "line"}


def test_unreachable_raises():
    with pytest.raises(SpoolmanError) as ei:
        Spoolman(f"http://127.0.0.1:{free_port()}", timeout=2).ping()
    assert ei.value.status is None
    assert "spoolman_unreachable" in str(ei.value)


def test_http_error_carries_status(spoolman_url):
    with pytest.raises(SpoolmanError) as ei:
        Spoolman(spoolman_url).get("spool/99")
    assert ei.value.status == 404


def test_fake_write_shapes(spoolman_url):
    sm = Spoolman(spoolman_url)
    v = sm.post("vendor", {"name": "SUNLU"})
    f = sm.post("filament", {"name": "PLA", "vendor_id": v["id"], "weight": 1000, "material": "PLA"})
    assert f["vendor"]["name"] == "SUNLU"
    s = sm.post("spool", {"filament_id": f["id"], "remaining_weight": 800})
    assert s["filament"]["id"] == f["id"] and s["used_weight"] == 200
    p = sm.patch(f"spool/{s['id']}", {"extra": {"nfc_id": '"4:a"'}, "location": "Rack 1", "remaining_weight": 700})
    assert p["extra"] == {"nfc_id": '"4:a"'} and p["location"] == "Rack 1" and p["remaining_weight"] == 700
    sm.patch(f"spool/{s['id']}", {"archived": True})
    assert sm.get("spool") == []
    assert len(sm.get("spool?allow_archived=true")) == 1
