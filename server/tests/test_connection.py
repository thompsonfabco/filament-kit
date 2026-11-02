import json
import ssl
import threading
import time
from pathlib import Path

import pytest

from filament_kit.bridge import connection, registry
from filament_kit.bridge.connection import Manager, NoReply, PrinterOffline, UnknownPrinter
from filament_kit.bridge.registry import Printer
from fakes.fake_paho import LEAF, FakeClient, FakePrinter, Msg  # noqa: F401  (re-exported for other tests)

DATA = Path(__file__).parent / "data"
CODE = "13572468"


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
    assert (c.host, c.port, c.password) == ("10.0.0.5", 8883, None)    # the code waits for the pin check
    assert c.socket_open()
    assert (c.username, c.password) == ("bblp", CODE)
    assert c.tls.verify_mode == ssl.CERT_NONE and c.tls.check_hostname is False
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
    assert len(clients) == 2 and clients[1].socket_open() and clients[1].password == "24681357"


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
    assert manager.summary("S1") == {"gcode_state": "RUNNING", "percent": 43, "remaining_min": 73,
                                      "job": "bracket_v3"}


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


def test_summary_job_is_none_without_a_job(manager):
    assert manager.summary("NOPE") == {"gcode_state": "UNKNOWN", "percent": 0, "remaining_min": 0, "job": None}


# ---------- final review: a slow stop during a re-key must not block state reads ----------

def test_state_reads_do_not_block_while_a_stale_connection_stops():
    release = threading.Event()
    entered = threading.Event()
    made = []

    class SlowStop(FakeClient):
        def disconnect(self):
            if self.host == "10.0.0.5":
                entered.set()
                release.wait(5)
            super().disconnect()

    def factory(cid):
        c = SlowStop(cid)
        made.append(c)
        return c
    m = Manager(client_factory=factory)
    try:
        add("S1", "10.0.0.5")
        add("S2", "10.0.0.6", name="Other")
        m.sync()
        add("S1", "10.0.0.9")                       # re-key: S1's old connection is stopped
        t = threading.Thread(target=m.sync)
        t.start()
        assert entered.wait(5)
        t0 = time.monotonic()
        assert m.state("S2") == "offline"
        assert m.state("S1") in ("offline", "not_configured")
        assert time.monotonic() - t0 < 0.5
        release.set()
        t.join(5)
        assert [c.host for c in made] == ["10.0.0.5", "10.0.0.6", "10.0.0.9"]
    finally:
        release.set()
        m.stop()


# ---------------------------------------------------------------- publish / set_slot / wait_report (part 2)
SETTING = {"tray_info_idx": "Pa735293", "tray_color": "1a1a1aff", "tray_type": "PETG",
           "nozzle_temp_min": "235", "nozzle_temp_max": 250}


def connected_printer(manager, clients, report=None):
    add()
    manager.sync()
    c = clients[0]
    printer = FakePrinter(c, report or {"gcode_state": "IDLE",
                                        "ams": {"ams": [{"id": "0", "tray": [{"id": "0"}, {"id": "2"}]}]}})
    c.connected(0)
    assert manager.wait_report("S1", lambda r: "ams" in r, 2) is not None
    return c, printer


def test_set_slot_publishes_the_owners_ams_filament_setting_shape(manager, clients):
    c, printer = connected_printer(manager, clients)
    reply = manager.set_slot("S1", 0, 2, SETTING)
    topic, body = [(t, b) for t, b in c.published if "print" in b][-1]
    assert topic == "device/S1/request"
    pr = body["print"]
    assert pr == {"command": "ams_filament_setting", "ams_id": 0, "tray_id": 2, "tray_info_idx": "Pa735293",
                  "tray_color": "1A1A1AFF", "tray_type": "PETG", "tray_sub_brands": "",
                  "nozzle_temp_min": 235, "nozzle_temp_max": 250, "setting_id": "",
                  "sequence_id": pr["sequence_id"]}
    assert isinstance(pr["sequence_id"], str) and pr["sequence_id"].isdigit()
    assert reply["result"] == "success" and reply["sequence_id"] == pr["sequence_id"]


def test_wait_report_returns_merged_report_once_predicate_holds(manager, clients):
    c, printer = connected_printer(manager, clients)

    def shows(r):
        trays = r["ams"]["ams"][0]["tray"]
        return any(t.get("tray_info_idx") == "Pa735293" for t in trays)
    assert manager.wait_report("S1", shows, 0.05) is None                 # not yet: times out
    manager.set_slot("S1", 0, 2, SETTING)
    r = manager.wait_report("S1", shows, 2)
    assert r is not None and r["ams"]["ams"][0]["tray"][1]["tray_color"] == "1A1A1AFF"
    assert r["gcode_state"] == "IDLE"                                     # merged, not just the delta


def test_wait_report_returns_none_when_the_connection_drops(manager, clients):
    c, printer = connected_printer(manager, clients)
    threading.Timer(0.1, c.dropped).start()
    t0 = time.monotonic()
    assert manager.wait_report("S1", lambda r: False, 5) is None
    assert time.monotonic() - t0 < 2
    assert manager.wait_report("S9", lambda r: True, 0.1) is None         # unknown printer: nothing to wait on


def test_publish_without_reply_returns_none_and_fills_sequence_id(manager, clients, monkeypatch):
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 0.1)
    c, printer = connected_printer(manager, clients)
    printer.answer_jobs = False
    assert manager.publish("S1", {"print": {"command": "project_file", "param": "x"}}) is None
    body = c.published[-1][1]["print"]
    assert body["command"] == "project_file" and body["sequence_id"].isdigit()


def test_publish_refused_for_developer_mode_flags_state(manager, clients):
    c, printer = connected_printer(manager, clients)
    printer.refuse[(0, 2)] = {"result": "fail", "reason": "mqtt message verify failed"}
    reply = manager.set_slot("S1", 0, 2, SETTING)
    assert reply["result"] == "fail"
    assert manager.state("S1") == "needs_developer_mode"
    assert manager.set_slot("S1", 0, 0, SETTING)["result"] == "success"
    assert manager.state("S1") == "connected"


def test_publish_offline_or_unknown_raises(manager, clients):
    add()
    manager.sync()
    with pytest.raises(PrinterOffline):
        manager.set_slot("S1", 0, 0, SETTING)
    with pytest.raises(UnknownPrinter):
        manager.publish("S9", {"print": {"command": "x"}})


# ---------------------------------------------------------------- M2 / M5 (final review)

def test_status_join_uses_the_serial_for_an_unnamed_printer(clients):
    class FakeSpoolman:
        def get(self, path):
            return [{"id": 7, "location": "S1 – AMS A1", "remaining_weight": 100,
                     "filament": {"name": "Red", "material": "PLA", "vendor": {"name": "Acme"}}}]

    m = Manager(client_factory=lambda cid: clients.append(FakeClient(cid)) or clients[-1], spoolman=FakeSpoolman())
    try:
        add(name="")
        m.sync()
        clients[0].connected(0)
        clients[0].deliver(json.loads((DATA / "h2d_pushall.json").read_text()))
        assert m.status("S1")["ams"][0]["slots"][0]["spool"]["id"] == 7
    finally:
        m.stop()


def test_sequence_ids_start_at_a_random_value(monkeypatch):
    seen = []
    monkeypatch.setattr(connection.secrets, "randbelow", lambda n: seen.append(n) or 4242)
    conn = connection.PrinterConnection(Printer("S1", "x", "O1D", "10.0.0.5", CODE, True), FakeClient)
    assert next(conn._seq) == 4242 and seen and seen[0] >= 10 ** 6
