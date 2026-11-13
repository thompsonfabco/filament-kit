"""filament_kit.station: scale report parsing, the read-only HTTP view, and finding the button panel by its HELLO.

Hardware loops (hidraw select, nfcpy, aplay) are Linux-only and not run here; these tests cover the pure pieces
they are built from, with fake reports and a fake serial port.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from filament_kit.station import http as station_http
from filament_kit.station import nfc as station_nfc
from filament_kit.station import panel as station_panel
from filament_kit.station import scale, state


# --- scale reports -------------------------------------------------------------------------------------------------

def test_parse_report_stable_grams():
    assert scale.parse_report(bytes([3, 4, 2, 0, 0xE8, 0x03])) == {
        "grams": 1000.0, "status": "stable", "stable": True, "unit": 2}


def test_parse_report_ounces_negative_exponent():
    r = scale.parse_report(bytes([3, 4, 11, 0xFF, 0x64, 0x00]))  # 100 x 10^-1 oz = 10.0 oz
    assert r["grams"] == pytest.approx(283.495, abs=0.05)
    assert r["stable"] is True


def test_parse_report_pounds():
    r = scale.parse_report(bytes([3, 4, 12, 0xFE, 0x64, 0x00]))  # 100 x 10^-2 lb = 1 lb
    assert r["grams"] == pytest.approx(453.6, abs=0.05)


def test_parse_report_moving_not_stable():
    r = scale.parse_report(bytes([3, 3, 2, 0, 0x10, 0x00]))
    assert r["stable"] is False
    assert r["status"] == "moving"


def test_parse_report_negative_status_flips_sign():
    r = scale.parse_report(bytes([3, 5, 2, 0, 0x0A, 0x00]))
    assert r["grams"] == -10.0
    assert r["status"] == "negative"


def test_parse_report_other_id_ignored():
    assert scale.parse_report(bytes([2, 4, 2, 0, 0xE8, 0x03])) is None
    assert scale.parse_report(bytes([3, 4, 2])) is None  # short read


# --- HTTP ----------------------------------------------------------------------------------------------------------

def _serve(view, allow):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), station_http.make_handler(view, allow))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _stop(srv):
    srv.shutdown()
    srv.server_close()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


IDLE = {"step": "idle", "message": "", "spool": None, "filament": None}


def _raw(now, **kw):
    s = {"tag": "a:b:c:d:e:f:1", "tag_at": now - 10, "scale": {"grams": 1000.0, "status": "stable", "unit": 2},
         "scale_at": now - 1, "last": 1000.0, "last_at": now - 2, "held": None, "held_at": None,
         "blink_until": 0, "panel": "/dev/ttyUSB1", "panel_version": "2",
         "panel_nfc": True, "air": None, "air_at": None, "photo": None, "photo_at": None, "flow": IDLE}
    s.update(kw)
    return s


def _ages_near(doc, expect):
    """The handler reads the clock itself, a moment after the test took `now`: ages are compared to within 2 s and
    taken out of the document, so the rest can be compared exactly."""
    out = {}
    for key, want in expect.items():
        node = doc[key]
        assert abs(node.pop("age_seconds") - want) <= 2, (key, node)
        out[key] = node
    return out


def test_state_and_last_tag_shapes():
    """Same output as filament-ops station/intake_station.py for the same state (shapes are a contract with the
    owner's filament-mcp)."""
    now = time.time()
    raw = _raw(now)
    srv, base = _serve(lambda: dict(raw), {"127.0.0.1"})
    try:
        code, st = _get(base + "/state")
        assert code == 200
        assert set(st) == {"tag", "scale", "last_weight", "panel", "panel_version", "panel_nfc", "air", "photo",
                       "flow"}
        iso = station_http.iso(now - 10)
        tag = {"status": "ok", "nfc_id": "a:b:c:d:e:f:1", "read_at": iso, "read_at_unix": now - 10, "held": False}
        _ages_near(st, {"tag": 10, "scale": 1, "last_weight": 2})
        assert st == {
            "tag": tag,
            "scale": {"grams": 1000.0, "status": "stable", "unit": 2, "stable": True},
            "last_weight": {"grams": 1000.0, "held": False},
            "panel": "/dev/ttyUSB1", "panel_version": "2", "panel_nfc": True, "air": None, "photo": None,
            "flow": IDLE}
        code, lt = _get(base + "/last-tag")
        assert code == 200
        assert abs(lt.pop("age_seconds") - 10) <= 2
        assert lt == tag
        code, body = _get(base + "/other")
        assert code == 404
        assert body == {"status": "error", "message": "not found"}
    finally:
        _stop(srv)


def test_state_held_and_empty():
    now = time.time()
    held = _raw(now, held=812.5, held_at=now - 30, tag_at=now - 900)
    empty = _raw(now, tag=None, tag_at=None, scale=None, scale_at=None, last=None, last_at=None, panel=None, panel_version=None, panel_nfc=None)
    views = iter([held, empty])
    srv, base = _serve(lambda: dict(next(views)), {"127.0.0.1"})
    try:
        _, st = _get(base + "/state")
        assert abs(st["last_weight"].pop("age_seconds") - 30) <= 2
        assert st["last_weight"] == {"grams": 812.5, "held": True}
        assert st["tag"]["held"] is True
        _, st = _get(base + "/state")
        assert st == {"tag": {"status": "ok", "nfc_id": None, "read_at": None, "read_at_unix": None,
                              "age_seconds": None, "held": False},
                      "scale": None, "last_weight": None, "panel": None, "panel_version": None, "panel_nfc": None, "air": None,
                      "photo": None, "flow": IDLE}
    finally:
        _stop(srv)


def test_state_air_goes_stale_after_a_minute_and_a_zero_last_weight_is_none():
    now = time.time()
    air = {"temp_c": 21.5, "humidity": 40}
    views = iter([_raw(now, air=air, air_at=now - 5), _raw(now, air=air, air_at=now - 61, last=0.0, last_at=now)])
    srv, base = _serve(lambda: dict(next(views)), {"127.0.0.1"})
    try:
        _, st = _get(base + "/state")
        assert st["air"]["temp_c"] == 21.5 and 3 <= st["air"]["age_seconds"] <= 8
        _, st = _get(base + "/state")
        assert st["air"] is None                                       # the panel is gone: no stale reading
        assert st["last_weight"] is None                               # 0.0 g is "no weight", not a reading
    finally:
        _stop(srv)


def test_photo_is_served_as_a_jpeg_and_is_a_404_without_one():
    now = time.time()
    jpeg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"fake"
    views = iter([_raw(now, photo=jpeg, photo_at=now - 3), _raw(now, photo=jpeg, photo_at=now - 3), _raw(now)])
    srv, base = _serve(lambda: dict(next(views)), {"127.0.0.1"})
    try:
        _, st = _get(base + "/state")
        assert st["photo"]["url"] == "/photo" and 1 <= st["photo"]["age_seconds"] <= 6
        with urllib.request.urlopen(base + "/photo", timeout=5) as r:
            assert r.status == 200 and r.headers["Content-Type"] == "image/jpeg" and r.read() == jpeg
        assert _get(base + "/photo")[0] == 404
    finally:
        _stop(srv)


def test_refuses_client_not_in_allow():
    srv, base = _serve(lambda: _raw(time.time()), {"10.9.9.9"})
    try:
        assert _get(base + "/state") == (403, {"status": "error", "message": "forbidden"})
        assert _get(base + "/last-tag")[0] == 403
    finally:
        _stop(srv)


def _no_station_env(monkeypatch):
    import os
    for k in [k for k in os.environ if k.startswith("STATION_")] + ["NFC_DEVICE"]:
        monkeypatch.delenv(k, raising=False)


def test_allow_default_and_split(monkeypatch):
    _no_station_env(monkeypatch)
    assert state.settings_from_env()["allow"] == {"127.0.0.1"}
    monkeypatch.setenv("STATION_ALLOW", "127.0.0.1 192.0.2.10  198.51.100.7")
    s = state.settings_from_env()
    assert s["allow"] == {"127.0.0.1", "192.0.2.10", "198.51.100.7"}
    assert (s["port"], s["nfc_device"], s["beep"], s["beep_device"]) == (5003, "auto", True, "")
    assert "active" not in s  # the old Hold/Discard expiry (STATION_ACTIVE): the flow has its own timeout


def test_flow_settings_from_env(monkeypatch):
    _no_station_env(monkeypatch)
    s = state.settings_from_env()
    assert (s["flow_timeout"], s["recognise_timeout"]) == (600, 90)
    monkeypatch.setenv("STATION_FLOW_TIMEOUT", "120")
    monkeypatch.setenv("STATION_RECOGNISE_TIMEOUT", "30")
    s = state.settings_from_env()
    assert (s["flow_timeout"], s["recognise_timeout"]) == (120, 30)
    assert not {"server", "token_file"} & set(s)  # the pairing files (server_api) say where the server is


# --- panel + reader port -------------------------------------------------------------------------------------------

class FakeSerial:
    """pyserial stand-in: the port in PANEL_PORT says HELLO after `?`, every other port stays silent."""
    PANEL_PORT = "/dev/ttyUSB1"
    opened: list[str] = []

    def __init__(self):
        self.port = None
        self._lines: list[bytes] = []

    def open(self):
        FakeSerial.opened.append(self.port)

    def readline(self):
        time.sleep(0.01)
        return self._lines.pop(0) if self._lines else b""

    def write(self, data):
        if data == b"?\n" and self.port == self.PANEL_PORT:
            self._lines.append(b"HELLO intake-panel 1\r\n")

    def close(self):
        pass


@pytest.fixture
def fake_ports(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=FakeSerial))
    monkeypatch.setattr(state, "usb_ttys", lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"])
    monkeypatch.setitem(state.ports, "panel", None)
    monkeypatch.setitem(state.ports, "panel_chip", None)
    monkeypatch.setitem(state.ports, "nfc", None)
    monkeypatch.setitem(state.settings, "nfc_device", "auto")
    state.probed.clear()
    FakeSerial.opened = []
    yield
    state.probed.clear()


def test_panel_found_by_hello(fake_ports):
    ser = station_panel.find_panel()
    assert ser is not None and ser.port == "/dev/ttyUSB1"
    assert state.ports["panel"] == "/dev/ttyUSB1"
    assert state.probed.is_set()
    assert station_nfc.nfc_path() == "tty:USB0:pn532"
    assert state.ports["nfc"] == "/dev/ttyUSB0"


def test_panel_search_skips_reader_port(fake_ports):
    state.ports["nfc"] = "/dev/ttyUSB0"  # nfcpy already holds it
    station_panel.find_panel()
    assert FakeSerial.opened == ["/dev/ttyUSB1"]


def test_nfc_path_explicit_device(fake_ports):
    state.settings["nfc_device"] = "usb:054c:06c3"
    assert station_nfc.nfc_path() == "usb:054c:06c3"


def test_no_panel_reader_gets_first_port(fake_ports, monkeypatch):
    monkeypatch.setattr(FakeSerial, "PANEL_PORT", "/dev/none")
    assert station_panel.find_panel() is None
    assert state.ports["panel"] is None
    assert station_nfc.nfc_path() == "tty:USB0:pn532"


def test_tag_ids_use_format_uid(monkeypatch):
    seen = []
    monkeypatch.setattr(station_nfc, "on_tag", seen.append)
    station_nfc.on_identifier(bytes([0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x01]))
    assert seen == ["a:b:c:d:e:f:1"]
