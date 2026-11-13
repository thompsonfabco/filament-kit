"""Every printer's state, job progress and slots in one read (`G printers/states`, S2.3 / N14): it answers from what the
managers already hold, opens no printer connection, and leaves the per-printer replies as they were."""
from __future__ import annotations

import pytest

from filament_kit import api
from filament_kit.bridge import registry, status
from test_setup_page import (HOME, SERIAL, STATIC, client, env, helper, make)  # noqa: F401

NAME = "voron.example.com"
REPORT = {"gcode_state": "RUNNING", "subtask_name": "bracket", "mc_percent": 42, "mc_remaining_time": 30,
          "layer_num": 10, "total_layer_num": 50, "ams": {"tray_now": "0", "ams": [{"id": "0", "tray": [
              {"id": "0", "tray_type": "PLA", "tray_color": "FF0000FF", "tray_info_idx": "GFA00"}]}]}}


class CountingManager:
    """A Printers stand-in: reads are answered from held data; anything that would touch a printer is counted."""

    def __init__(self, held):
        self.held, self.touched, self.reads = held, [], 0

    def state(self, serial):
        return "connected" if self.held.get(serial) is not None else "offline"

    def summary(self, serial):
        return None

    def status(self, serial):
        self.reads += 1
        return self.held.get(serial)

    def __getattr__(self, name):    # sync, wait_settled, command, publish, request_pushall ...: a connection or a write
        self.touched.append(name)
        raise AttributeError(name)


def _klipper_status():
    return {"gcode_state": "STANDBY", "stage": "", "job": "", "percent": 0, "layer": None, "total_layers": None,
            "remaining_min": 0, "eta": None, "ams": [{"unit": 0, "label": "Toolhead", "kind": "tool", "slots": [
                {"slot": 0, "label": "T0", "type": "PETG", "color_hex": "00FF00", "present": True, "active": True,
                 "spool": None}]}]}


@pytest.fixture
def fleet():
    bambu = registry.Printer(SERIAL, "H2D", "H2D", "192.0.2.40", "12345678", True)
    registry.upsert(bambu)
    kl = registry.add_klipper("Workshop", NAME, 7125)
    off = registry.Printer("0948ZZ0A0000002", "P1S", "P1S", "192.0.2.41", "12345678", True)
    registry.upsert(off)
    held = {SERIAL: status.summarize(REPORT, [], printer_name="H2D", model="H2D"), kl.serial: _klipper_status()}
    return CountingManager(held), kl


def _states(env, helper, mgr):
    app = make(env, helper, mgr, add=frozenset({"klipper"}))
    return client(app).get("/setup/api/printers/states")


def test_one_read_returns_every_printer_with_state_job_and_slots(env, helper, fleet):
    mgr, kl = fleet
    r = _states(env, helper, mgr)
    assert r.status_code == 200, r.text
    rows = {p["serial"]: p for p in r.json()["printers"]}
    assert set(rows) == {SERIAL, kl.serial, "0948ZZ0A0000002"}
    b, k, o = rows[SERIAL], rows[kl.serial], rows["0948ZZ0A0000002"]
    assert (b["family"], b["state"]) == ("bambu", "connected")
    assert b["job"]["gcode_state"] == "RUNNING" and b["job"]["percent"] == 42 and b["job"]["name"] == "bracket"
    assert b["job"]["remaining_min"] == 30 and (b["job"]["layer"], b["job"]["total_layers"]) == (10, 50)
    assert b["slots"][0]["slots"][0]["type"] == "PLA" and b["slots"][0]["slots"][0]["color_hex"] == "FF0000"
    assert (k["family"], k["state"]) == ("klipper", "connected")
    assert k["job"]["gcode_state"] == "STANDBY" and k["job"]["percent"] == 0 and k["job"]["name"] is None
    assert k["slots"][0]["slots"][0]["label"] == "T0"
    assert (o["state"], o["job"], o["slots"]) == ("offline", None, None)


def test_the_read_opens_no_printer_connection_and_shows_no_address(env, helper, fleet):
    mgr, kl = fleet
    r = _states(env, helper, mgr)
    assert r.status_code == 200 and mgr.touched == [] and mgr.reads == 3
    for secret in ("192.0.2.40", "12345678", NAME, "api_key"):
        assert secret not in r.text


def test_the_read_is_for_the_lan_only(env, helper, fleet):
    from test_setup_page import AWAY
    mgr, _ = fleet
    app = make(env, helper, mgr, add=frozenset({"klipper"}))
    assert client(app, AWAY).get("/setup/api/printers/states").status_code == 403


def test_the_per_printer_replies_are_unchanged(env, helper, fleet):
    mgr, kl = fleet
    app = make(env, helper, mgr, add=frozenset({"klipper"}))
    c = client(app)
    before = c.get("/setup/api/state").json()["printers"]["list"]
    assert c.get("/setup/api/printers/states").status_code == 200
    assert c.get("/setup/api/state").json()["printers"]["list"] == before
    keys = {r["serial"]: set(r) for r in before}
    assert keys[SERIAL] == {"serial", "name", "model", "ip", "configured", "state", "pinned", "family", "mapping",
                            "report_why"}
    assert keys[kl.serial] == {"serial", "name", "model", "ip", "configured", "state", "pinned", "family", "host",
                               "port", "api_key", "lane_data"}
    p = registry.load()[SERIAL]
    assert set(api._printer_view(p, mgr)) == {"id", "name", "model", "serial", "ip", "configured", "state", "camera",
                                              "model_name", "summary", "family", "pinned"}
