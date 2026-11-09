import logging

import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing
from filament_kit.api import create_app
from filament_kit.bridge import registry
from filament_kit.bridge.connection import NoReply, PrinterOffline, UnknownPrinter
from filament_kit.bridge.models import camera_kind

CODE = "12345678"
SERIAL = "01P00A111111111"


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})


class FakeManager:
    def __init__(self):
        self.states = {}
        self.statuses = {}
        self.settle = "connected"
        self.sent = []
        self.error = None
        self.synced = 0

    def sync(self):
        self.synced += 1
        for p in registry.load().values():
            if p.configured:
                if self.states.get(p.serial) != "connected":
                    self.states[p.serial] = self.settle

    def state(self, serial):
        return self.states.get(serial, "not_configured")

    def wait_settled(self, serial, timeout):
        return self.state(serial)

    def summary(self, serial):
        return {"gcode_state": "RUNNING", "percent": 42, "remaining_min": 30, "job": "bracket"} if self.state(serial) == "connected" \
            else {"gcode_state": "UNKNOWN", "percent": 0, "remaining_min": 0, "job": None}

    def status(self, serial):
        return self.statuses.get(serial)

    def command(self, serial, action):
        if self.error:
            raise self.error
        if serial not in self.states:
            raise UnknownPrinter(serial)
        self.sent.append((serial, action))
        return {"command": action}


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def client(mgr):
    c = TestClient(create_app(object(), printers=mgr))
    c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
    return c


def add_configured(mgr, serial=SERIAL, model="C12", name="Shop P1S", state="connected"):
    registry.upsert(registry.Printer(serial=serial, name=name, model=model, ip="10.0.0.5",
                                     access_code=CODE, configured=True))
    mgr.states[serial] = state


def no_code(resp):
    assert CODE not in resp.text


def test_requires_token(mgr):
    c = TestClient(create_app(object(), printers=mgr))
    for r in (c.get("/api/printers"), c.post("/api/printers", json={}), c.get(f"/api/printers/{SERIAL}"),
              c.post(f"/api/printers/{SERIAL}/command", json={"action": "pause"})):
        assert r.status_code == 401 and r.json()["error"] == "unauthorized"


def test_list_merges_detected_and_configured(client, mgr):
    add_configured(mgr)
    registry.detected("00M00B222222222", "10.0.0.9", "BL-P001", "Garage X1C")
    r = client.get("/api/printers")
    no_code(r)
    assert r.status_code == 200
    by = {p["id"]: p for p in r.json()["printers"]}
    a = by[SERIAL]
    assert a == {"id": SERIAL, "name": "Shop P1S", "model": "C12", "serial": SERIAL, "ip": "10.0.0.5",
                 "configured": True, "state": "connected", "camera": {"kind": "mjpeg"}, "model_name": "P1S",
                 "summary": {"gcode_state": "RUNNING", "percent": 42, "remaining_min": 30, "job": "bracket"},
                 "family": "bambu"}
    b = by["00M00B222222222"]
    assert b["configured"] is False and b["state"] == "not_configured" and b["camera"] == {"kind": "hls"}
    assert b["model"] == "BL-P001" and b["model_name"] == "X1 Carbon"   # a detected printer: the name too
    assert b["summary"]["percent"] == 0


def test_model_name_keeps_the_code_and_falls_back_to_it(client, mgr):
    add_configured(mgr, model="O1D", name="Shop H2D")
    registry.detected("00M00B333333333", "10.0.0.10", "ZZ9", "Future printer")
    registry.detected("00M00B444444444", "10.0.0.11", "", "")
    by = {p["id"]: p for p in client.get("/api/printers").json()["printers"]}
    assert (by[SERIAL]["model"], by[SERIAL]["model_name"]) == ("O1D", "H2D")
    assert (by["00M00B333333333"]["model"], by["00M00B333333333"]["model_name"]) == ("ZZ9", "ZZ9")
    assert (by["00M00B444444444"]["model"], by["00M00B444444444"]["model_name"]) == ("", "")
    one = client.get(f"/api/printers/{SERIAL}").json()
    assert one["printer"]["model"] == "O1D" and one["printer"]["model_name"] == "H2D"   # the detail route too


def test_list_configured_unknown_to_manager_is_offline(client, mgr):
    registry.upsert(registry.Printer(serial=SERIAL, name="x", model="", ip="10.0.0.5", access_code=CODE,
                                     configured=True))
    p = client.get("/api/printers").json()["printers"][0]
    assert p["state"] == "offline" and p["camera"] == {"kind": None}


def test_add_returns_first_state(client, mgr):
    registry.detected(SERIAL, "10.0.0.5", "C12", "Shop P1S")
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": CODE})
    no_code(r)
    assert r.status_code == 200
    p = r.json()["printer"]
    assert p["id"] == SERIAL and p["configured"] is True and p["state"] == "connected" and p["name"] == "Shop P1S"
    assert registry.load()[SERIAL].access_code == CODE and mgr.synced == 1


def test_add_with_name_and_wrong_code(client, mgr):
    mgr.settle = "wrong_code"
    registry.detected(SERIAL, "10.0.0.5", "C12", "Shop P1S")
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": CODE, "name": "Bench"})
    no_code(r)
    assert r.status_code == 200 and r.json()["printer"]["state"] == "wrong_code"
    assert r.json()["printer"]["name"] == "Bench"


def test_add_duplicate_is_409(client, mgr):
    add_configured(mgr)
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": "99999999"})
    no_code(r)
    assert r.status_code == 409 and r.json()["error"] == "exists"
    assert registry.load()[SERIAL].access_code == CODE


@pytest.mark.parametrize("state", ["wrong_code", "offline", "not_configured"])
def test_add_existing_replaces_code_unless_connected(client, mgr, state):
    add_configured(mgr, state=state)
    mgr.settle = "connected"
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": "87654321"})
    assert "87654321" not in r.text
    assert r.status_code == 200 and r.json()["printer"]["state"] == "connected"
    p = registry.load()[SERIAL]
    assert p.access_code == "87654321" and p.name == "Shop P1S"   # name kept when none is given


def test_add_existing_replaces_name_only_when_given(client, mgr):
    add_configured(mgr, state="wrong_code")
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": "87654321", "name": "Bench"})
    assert r.status_code == 200 and r.json()["printer"]["name"] == "Bench"
    assert registry.load()[SERIAL].name == "Bench"


def test_add_connected_keeps_code(client, mgr):
    add_configured(mgr, state="connected")
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": "87654321", "name": "Bench"})
    assert r.status_code == 409 and r.json()["error"] == "exists"
    p = registry.load()[SERIAL]
    assert p.access_code == CODE and p.name == "Shop P1S"


def test_wrong_code_printer_rekeyed_with_real_manager(monkeypatch):
    import threading
    from filament_kit.api import FIRST_STATE_WAIT  # noqa: F401
    from filament_kit.bridge.connection import Manager
    from test_connection import FakeClient
    monkeypatch.setattr("filament_kit.api.FIRST_STATE_WAIT", 3.0)

    class Client(FakeClient):
        def connect_async(self, host, port, keepalive):
            super().connect_async(host, port, keepalive)

            def attempt():
                if self.socket_open():   # the code is only set once the leaf passed
                    self.on_connect(self, None, {}, 0 if self.password == "24681357" else 5, None)
            threading.Timer(0.05, attempt).start()

    m = Manager(client_factory=Client)
    try:
        c = TestClient(create_app(object(), printers=m))
        c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
        registry.detected(SERIAL, "10.0.0.5", "C12", "P1S")
        r = c.post("/api/printers", json={"serial": SERIAL, "access_code": "13572468"})
        assert r.status_code == 200 and r.json()["printer"]["state"] == "wrong_code"
        r = c.post("/api/printers", json={"serial": SERIAL, "access_code": "24681357"})
        assert r.status_code == 200 and r.json()["printer"]["state"] == "connected"
        assert "24681357" not in r.text
    finally:
        m.stop()


@pytest.mark.parametrize("body", [{}, {"serial": SERIAL}, {"serial": "", "access_code": CODE},
                                  {"serial": SERIAL, "access_code": 5},
                                  {"serial": SERIAL, "access_code": CODE, "name": 3}])
def test_add_bad_request(client, body):
    r = client.post("/api/printers", json=body)
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_status_shape(client, mgr):
    add_configured(mgr)
    mgr.statuses[SERIAL] = {"gcode_state": "RUNNING", "percent": 42, "ams": []}
    r = client.get(f"/api/printers/{SERIAL}")
    no_code(r)
    j = r.json()
    assert j["printer"]["id"] == SERIAL and j["status"] == {"gcode_state": "RUNNING", "percent": 42, "ams": []}


def test_status_null_when_not_connected_and_404(client, mgr):
    registry.detected(SERIAL, "10.0.0.5", "C12", "x")
    r = client.get(f"/api/printers/{SERIAL}")
    assert r.status_code == 200 and r.json()["status"] is None
    r = client.get("/api/printers/NOPE")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_command_ok_and_logged(client, mgr, caplog):
    add_configured(mgr)
    caplog.set_level(logging.INFO, logger="filament_kit.api")
    r = client.post(f"/api/printers/{SERIAL}/command", json={"action": "pause"})
    no_code(r)
    assert r.status_code == 200 and r.json() == {"ok": True, "reply": {"command": "pause"}}
    assert mgr.sent == [(SERIAL, "pause")]
    text = "\n".join(caplog.messages)
    device = pairing.devices()[0]["id"]
    assert f"device_id={device} serial={SERIAL} action=pause result=ok" in text and CODE not in text


def test_command_offline_409_no_reply_504(client, mgr):
    add_configured(mgr)
    mgr.error = PrinterOffline(SERIAL)
    r = client.post(f"/api/printers/{SERIAL}/command", json={"action": "stop"})
    no_code(r)
    assert r.status_code == 409 and r.json()["error"] == "printer_offline"
    mgr.error = NoReply("no reply")
    r = client.post(f"/api/printers/{SERIAL}/command", json={"action": "light_on"})
    assert r.status_code == 504 and r.json()["error"] == "no_reply"


def test_command_unknown_printer_and_bad_action(client, mgr):
    add_configured(mgr)
    r = client.post("/api/printers/NOPE/command", json={"action": "pause"})
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = client.post(f"/api/printers/{SERIAL}/command", json={"action": "explode"})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    r = client.post(f"/api/printers/{SERIAL}/command", json={})
    assert r.status_code == 400


@pytest.mark.parametrize("model,kind", [("BL-P001", "hls"), ("3DPrinter-X1-Carbon", "hls"), ("O1D", "hls"),
                                        ("H2D", "hls"), ("X2D", "hls"), ("C11", "mjpeg"), ("C12", "mjpeg"),
                                        ("N1", "mjpeg"), ("A1 mini", "mjpeg"), ("P1S", "mjpeg"),
                                        ("", None), ("Unknown9", None), ("ZZ9", None), (None, None)])
def test_camera_kind(model, kind):
    assert camera_kind(model) == kind


# ---------- final review ----------

@pytest.mark.parametrize("serial", ["../etc", "has space", "x" * 65, "semi;colon"])
def test_add_rejects_bad_serial(client, serial):
    r = client.post("/api/printers", json={"serial": serial, "access_code": CODE})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    assert registry.load() == {}


@pytest.mark.parametrize("code", ["1234 5678", "abc-123", "x" * 33, "côde123"])
def test_add_rejects_bad_access_code_with_plain_message(client, code):
    registry.detected(SERIAL, "10.0.0.5", "C12", "Shop P1S")
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": code})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    assert "Access Code" in r.json()["message"] and code not in r.text
    assert registry.load()[SERIAL].configured is False


def test_add_unseen_printer_is_404(client, mgr):
    r = client.post("/api/printers", json={"serial": SERIAL, "access_code": CODE})
    assert r.status_code == 404 and r.json() == {"error": "not_found",
                                                 "message": "That printer hasn't been seen on the network yet"}
    assert registry.load() == {} and mgr.synced == 0


def test_list_survives_one_bad_summary(client, mgr):
    add_configured(mgr)
    add_configured(mgr, serial="0948ZZ0A0000002", name="Other")
    real = mgr.summary

    def summary(serial):
        if serial == SERIAL:
            raise TypeError("odd report")
        return real(serial)
    mgr.summary = summary
    r = client.get("/api/printers")
    assert r.status_code == 200
    by = {p["id"]: p for p in r.json()["printers"]}
    assert by[SERIAL]["summary"] is None and by[SERIAL]["state"] == "connected"
    assert by["0948ZZ0A0000002"]["summary"]["percent"] == 42


def test_printer_get_reports_hardware_errors_and_warnings(client, mgr, tmp_path):
    from filament_kit.bridge import hardware
    add_configured(mgr)
    hardware._reset_cache()
    try:
        j = client.get(f"/api/printers/{SERIAL}").json()
        assert j["hardware"] == {"errors": [], "warnings": []}
        (tmp_path / "etc" / "bambu_hardware.xml").write_text("<bambu-hardware version='1'><models><nope", "utf-8")
        j = client.get(f"/api/printers/{SERIAL}").json()
        assert j["hardware"]["errors"] and j["printer"]["id"] == SERIAL        # last good data still serves
        (tmp_path / "etc" / "bambu_hardware.xml").write_text(
            "<bambu-hardware version='1.4'><future-thing/></bambu-hardware>", "utf-8")
        j = client.get(f"/api/printers/{SERIAL}").json()
        assert not j["hardware"]["errors"] and j["hardware"]["warnings"]
    finally:
        hardware._reset_cache()
