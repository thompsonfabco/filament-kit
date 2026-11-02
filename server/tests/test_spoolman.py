import http.server
import threading

import pytest

from filament_kit.spoolman import Spoolman, SpoolmanError
from conftest import free_port

NAMES = ["nfc_id", "prev_location", "box_humidity", "humidity_checked", "nozzle_range", "bed_range", "line"]


def test_ping_returns_version(spoolman_url):
    assert Spoolman(spoolman_url).ping() == "0.27.0"


def test_ensure_fields_idempotent(spoolman_url, spoolman_fake_store):
    sm = Spoolman(spoolman_url)
    assert sorted(sm.ensure_fields()) == sorted(NAMES)
    assert sm.ensure_fields() == []
    assert {f["key"] for f in spoolman_fake_store["fields"]["spool"]} == {"nfc_id", "prev_location", "box_humidity",
                                                                          "humidity_checked"}
    assert {f["key"] for f in spoolman_fake_store["fields"]["filament"]} == {"nozzle_range", "bed_range", "line"}
    types = {f["key"]: f["field_type"] for f in spoolman_fake_store["fields"]["spool"]}
    assert (types["box_humidity"], types["humidity_checked"]) == ("float", "datetime")


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
    sm.ensure_fields()
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


def test_fake_rejects_unregistered_or_non_json_extra(spoolman_url):
    sm = Spoolman(spoolman_url)
    v = sm.post("vendor", {"name": "V"})
    f = sm.post("filament", {"name": "F", "vendor_id": v["id"], "weight": 1000})
    s = sm.post("spool", {"filament_id": f["id"]})
    for call in (
        lambda: sm.post("filament", {"name": "G", "extra": {"line": '"x"'}}),
        lambda: sm.post("vendor", {"name": "W", "extra": {"nope": '"x"'}}),
        lambda: sm.patch(f"spool/{s['id']}", {"extra": {"nfc_id": '"a"'}}),
    ):
        with pytest.raises(SpoolmanError) as ei:
            call()
        assert ei.value.status == 422
    sm.ensure_fields()
    for bad in ("not json", 5):
        with pytest.raises(SpoolmanError) as ei:
            sm.patch(f"spool/{s['id']}", {"extra": {"nfc_id": bad}})
        assert ei.value.status == 422
    assert sm.patch(f"spool/{s['id']}", {"extra": {"nfc_id": '"a"'}})["extra"] == {"nfc_id": '"a"'}


def _stub(handler_fn):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            handler_fn(self)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_bad_json_body_raises_spoolman_error():
    def h(r):
        r.send_response(200)
        r.send_header("Content-Length", "6")
        r.end_headers()
        r.wfile.write(b"<html>")
    srv = _stub(h)
    try:
        with pytest.raises(SpoolmanError) as ei:
            Spoolman(f"http://127.0.0.1:{srv.server_port}").get("info")
        assert ei.value.status == 200 and "bad response" in str(ei.value)
    finally:
        srv.shutdown()


def test_dropped_connection_is_unreachable():
    def h(r):
        r.wfile.write(b"garbage\r\n\r\n")
        r.close_connection = True
    srv = _stub(h)
    try:
        with pytest.raises(SpoolmanError) as ei:
            Spoolman(f"http://127.0.0.1:{srv.server_port}", timeout=2).get("info")
        assert ei.value.status is None
    finally:
        srv.shutdown()
