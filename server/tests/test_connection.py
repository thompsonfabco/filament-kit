import json
import threading
import time
from pathlib import Path

import pytest

from filament_kit.bridge import connection, registry
from filament_kit.bridge.connection import Manager, NoReply, PrinterOffline, UnknownPrinter
from filament_kit.bridge.registry import Printer

DATA = Path(__file__).parent / "data"
CODE = "13572468"


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, json.dumps(payload).encode()


class FakeClient:
    """Stands in for paho.mqtt.client.Client; the test drives its callbacks."""

    def __init__(self, client_id):
        self.client_id = client_id
        self.published, self.subscribed, self.calls = [], [], []
        self.host = self.port = self.keepalive = None
        self.username = self.password = None
        self.reconnect_delay = None
        self.on_connect = self.on_disconnect = self.on_message = self.on_connect_fail = None
        self.responder = None          # fn(topic, payload_dict) -> reply payload dict | None

    def username_pw_set(self, username, password):
        self.username, self.password = username, password

    def tls_set_context(self, ctx):
        self.tls = ctx

    def reconnect_delay_set(self, min_delay, max_delay):
        self.reconnect_delay = (min_delay, max_delay)

    def connect_async(self, host, port, keepalive):
        self.host, self.port, self.keepalive = host, port, keepalive
        self.calls.append("connect_async")

    def loop_start(self):
        self.calls.append("loop_start")

    def loop_stop(self):
        self.calls.append("loop_stop")

    def disconnect(self):
        self.calls.append("disconnect")

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos=0):
        body = json.loads(payload)
        self.published.append((topic, body))
        if self.responder:
            reply = self.responder(topic, body)
            if reply is not None:
                threading.Timer(0.02, self.deliver, args=(reply,)).start()

    # test helpers
    def connected(self, rc=0):
        self.on_connect(self, None, {}, rc, None)

    def dropped(self, rc=7):
        self.on_disconnect(self, None, {}, rc, None)

    def deliver(self, payload, serial=None):
        self.on_message(self, None, Msg(f"device/{serial or 'x'}/report", payload))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)


@pytest.fixture
def clients():
    return []


@pytest.fixture
def manager(clients):
    def factory(client_id):
        c = FakeClient(client_id)
        clients.append(c)
        return c
    m = Manager(client_factory=factory)
    yield m
    m.stop()


def add(serial="S1", ip="10.0.0.5", name="Office H2D"):
    registry.upsert(Printer(serial, name, "O1D", ip, CODE, True))


def pushalls(c):
    return [b for t, b in c.published if b.get("pushing", {}).get("command") == "pushall"]


def test_connect_configures_client_subscribes_and_requests_pushall(manager, clients):
    add()
    registry.detected("S9", "10.0.0.9", "N2", "Shed")           # unconfigured: no connection
    manager.sync()
    assert len(clients) == 1
    c = clients[0]
    assert (c.host, c.port, c.username, c.password) == ("10.0.0.5", 8883, "bblp", CODE)
    assert c.tls.verify_mode == connection.ssl.CERT_NONE and c.tls.check_hostname is False
    assert c.reconnect_delay == (2, 60)
    assert manager.state("S1") == "offline"
    assert manager.state("S9") == "not_configured"
    c.connected(0)
    assert manager.state("S1") == "connected"
    assert c.subscribed == ["device/S1/report"]
    assert pushalls(c) and c.published[0][0] == "device/S1/request"
    assert manager.wait_settled("S1", 0.1) == "connected"


def test_rc5_is_wrong_code_and_stops_retrying(manager, clients):
    add()
    manager.sync()
    clients[0].connected(5)
    assert manager.state("S1") == "wrong_code"
    assert "disconnect" in clients[0].calls
    clients[0].dropped()
    assert manager.state("S1") == "wrong_code"                    # stays until the code changes
    assert manager.wait_settled("S1", 0.1) == "wrong_code"


def test_rc5_as_paho_reason_code():
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.reasoncodes import ReasonCode
    assert connection._auth_refused(ReasonCode(PacketTypes.CONNACK, "Not authorized"))
    assert connection._auth_refused(ReasonCode(PacketTypes.CONNACK, "Bad user name or password"))
    assert not connection._auth_refused(ReasonCode(PacketTypes.CONNACK, "Success"))
    assert not connection._auth_refused(ReasonCode(PacketTypes.CONNACK, "Server unavailable"))


def test_disconnect_goes_offline_then_reconnects(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.dropped()
    assert manager.state("S1") == "offline"
    assert c.reconnect_delay == (2, 60)            # paho's loop reconnects with backoff 2 -> 60 s
    c.connected(0)                                 # ... and the reconnect lands
    assert manager.state("S1") == "connected"
    assert len(pushalls(c)) == 2                   # fresh pushall after the reconnect


def test_registry_ip_change_reconnects_to_new_ip(manager, clients):
    add()
    manager.sync()
    clients[0].connected(0)
    manager.sync()
    assert len(clients) == 1                       # nothing changed: same connection
    registry.detected("S1", "10.0.0.77")
    manager.sync()
    assert len(clients) == 2
    assert "disconnect" in clients[0].calls and "loop_stop" in clients[0].calls
    assert clients[1].host == "10.0.0.77"
    assert manager.state("S1") == "offline"
    clients[1].connected(0)
    assert manager.state("S1") == "connected"


def test_new_code_after_wrong_code_reconnects(manager, clients):
    add()
    manager.sync()
    clients[0].connected(5)
    registry.upsert(Printer("S1", "Office H2D", "O1D", "10.0.0.5", "24681357", True))
    manager.sync()
    assert len(clients) == 2 and clients[1].password == "24681357"


def test_removed_printer_is_disconnected(manager, clients):
    add()
    manager.sync()
    registry.remove("S1")
    manager.sync()
    assert "disconnect" in clients[0].calls
    with pytest.raises(UnknownPrinter):
        manager.command("S1", "pause")


def test_reports_merge_into_status(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.deliver(json.loads((DATA / "h2d_pushall.json").read_text()))
    c.deliver(json.loads((DATA / "h2d_delta.json").read_text()))
    s = manager.status("S1")
    assert s["percent"] == 43 and s["stage"] == "Heatbed preheating"
    assert s["ams"][0]["slots"][0]["type"] == "PLA"
    assert s["updated"] is not None
    assert manager.summary("S1") == {"gcode_state": "RUNNING", "percent": 43, "remaining_min": 73}


def test_status_joins_spools_from_spoolman(clients):
    class FakeSpoolman:
        calls = 0

        def get(self, path):
            FakeSpoolman.calls += 1
            assert path == "spool"
            return [{"id": 5, "location": "Office H2D – AMS A1", "remaining_weight": 100,
                     "filament": {"name": "Red", "material": "PLA", "vendor": {"name": "Acme"}}}]

    m = Manager(client_factory=lambda cid: clients.append(FakeClient(cid)) or clients[-1],
                spoolman=FakeSpoolman())
    try:
        add()
        m.sync()
        clients[0].connected(0)
        clients[0].deliver(json.loads((DATA / "h2d_pushall.json").read_text()))
        assert m.status("S1")["ams"][0]["slots"][0]["spool"]["id"] == 5
        m.status("S1")
        assert FakeSpoolman.calls == 1                 # cached between polls
    finally:
        m.stop()


def test_command_pause_publishes_and_returns_reply(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)

    def responder(topic, body):
        pr = body.get("print")
        if pr and pr.get("command") == "pause":
            return {"print": {"command": "pause", "sequence_id": pr["sequence_id"], "result": "success",
                              "reason": ""}}
    c.responder = responder
    before = len(pushalls(c))
    got = manager.command("S1", "pause")
    topic, body = next((t, b) for t, b in c.published if "print" in b)
    assert topic == "device/S1/request"
    assert body == {"print": {"command": "pause", "param": "", "sequence_id": body["print"]["sequence_id"]}}
    assert got == {"ok": True, "reply": {"command": "pause", "sequence_id": body["print"]["sequence_id"],
                                         "result": "success", "reason": ""}}
    time.sleep(0.3)
    assert len(pushalls(c)) == before + 1          # pushall shortly after the command


def test_light_on_uses_system_ledctrl_chamber_light(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.responder = lambda t, b: ({"system": {**b["system"], "result": "success"}} if "system" in b else None)
    got = manager.command("S1", "light_on")
    sent = [b["system"] for t, b in c.published if "system" in b]
    assert sent[0] == {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "on", "led_on_time": 500,
                       "led_off_time": 500, "loop_times": 0, "interval_time": 0,
                       "sequence_id": sent[0]["sequence_id"]}
    assert len(sent) == 1                          # this printer reports no second chamber light
    assert got["ok"] is True


def test_light_also_drives_second_chamber_light_when_reported(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.deliver({"print": {"lights_report": [{"node": "chamber_light", "mode": "off"},
                                           {"node": "chamber_light2", "mode": "off"}]}})
    c.responder = lambda t, b: ({"system": {**b["system"], "result": "success"}} if "system" in b else None)
    assert manager.command("S1", "light_off")["ok"] is True
    nodes = [b["system"]["led_node"] for t, b in c.published if "system" in b]
    assert nodes == ["chamber_light", "chamber_light2"]


def _two_lights(c):
    c.deliver({"print": {"lights_report": [{"node": "chamber_light", "mode": "off"},
                                           {"node": "chamber_light2", "mode": "off"}]}})


def test_light_fails_if_second_node_fails(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    _two_lights(c)

    def responder(t, b):
        s = b.get("system")
        if s:
            ok = s["led_node"] == "chamber_light"
            return {"system": {**s, "result": "success" if ok else "fail", "reason": "" if ok else "busy"}}
    c.responder = responder
    got = manager.command("S1", "light_on")
    assert got["ok"] is False and got["reply"]["led_node"] == "chamber_light2"
    assert manager.state("S1") == "connected"


def test_light_second_node_refused_needs_developer_mode(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    _two_lights(c)

    def responder(t, b):
        s = b.get("system")
        if s:
            if s["led_node"] == "chamber_light":
                return {"system": {**s, "result": "success"}}
            return {"system": {**s, "result": "failed", "reason": "", "err_code": 84033543}}
    c.responder = responder
    assert manager.command("S1", "light_on")["ok"] is False
    assert manager.state("S1") == "needs_developer_mode"


def test_developer_mode_detected_by_err_code_alone(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.responder = lambda t, b: ({"print": {"sequence_id": b["print"]["sequence_id"], "result": "fail",
                                           "reason": "", "err_code": 84033543}} if "print" in b else None)
    assert manager.command("S1", "pause")["ok"] is False
    assert manager.state("S1") == "needs_developer_mode"


def test_keepalive_is_ten_seconds(manager, clients):
    add()
    manager.sync()
    assert clients[0].keepalive == 10


def test_failed_reply_with_authorization_reason_needs_developer_mode(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.responder = lambda t, b: ({"print": {"command": "stop", "sequence_id": b["print"]["sequence_id"],
                                           "result": "fail", "reason": "mqtt message verify failed",
                                           "err_code": 84033543}} if "print" in b else None)
    got = manager.command("S1", "stop")
    assert got["ok"] is False and got["reply"]["result"] == "fail"
    assert manager.state("S1") == "needs_developer_mode"
    c.responder = lambda t, b: ({"print": {"sequence_id": b["print"]["sequence_id"], "result": "success"}}
                                if "print" in b else None)
    manager.command("S1", "resume")
    assert manager.state("S1") == "connected"       # a command that works clears it


def test_failed_reply_without_authorization_reason_stays_connected(manager, clients):
    add()
    manager.sync()
    c = clients[0]
    c.connected(0)
    c.responder = lambda t, b: ({"print": {"sequence_id": b["print"]["sequence_id"], "result": "fail",
                                           "reason": "not printing"}} if "print" in b else None)
    assert manager.command("S1", "resume")["ok"] is False
    assert manager.state("S1") == "connected"


def test_command_while_offline_raises_printer_offline(manager, clients):
    add()
    manager.sync()
    with pytest.raises(PrinterOffline):
        manager.command("S1", "pause")
    assert not [b for t, b in clients[0].published if "print" in b]


def test_silent_printer_raises_no_reply(manager, clients, monkeypatch):
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 0.2)
    add()
    manager.sync()
    clients[0].connected(0)
    t0 = time.monotonic()
    with pytest.raises(NoReply):
        manager.command("S1", "pause")
    assert time.monotonic() - t0 < 2


def test_unknown_action_rejected(manager, clients):
    add()
    manager.sync()
    clients[0].connected(0)
    with pytest.raises(ValueError):
        manager.command("S1", "home")


def test_access_code_never_logged(manager, clients, caplog):
    caplog.set_level("DEBUG")
    add()
    manager.sync()
    clients[0].connected(5)
    registry.detected("S1", "10.0.0.8")
    manager.sync()
    assert CODE not in caplog.text
    assert CODE not in repr(manager._conns["S1"])


def test_real_paho_client_unreachable_printer_is_offline():
    """The default factory builds a real paho client; nothing listens on the port, so it settles offline."""
    m = Manager()
    try:
        registry.upsert(Printer("S1", "X", "C11", "127.0.0.1", CODE, True))
        m.port = _free_port()
        m.sync()
        assert m.wait_settled("S1", 5) == "offline"
    finally:
        m.stop()


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
