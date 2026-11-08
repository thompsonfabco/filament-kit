"""bridge.klipper.moonraker: the HTTP client and the websocket subscriber, against FakeMoonraker."""
import json
import threading
import time

import pytest

from filament_kit.bridge.klipper import moonraker as mr


def _client(fake, **kw):
    return mr.Moonraker(fake.host, fake.port, **kw)


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_info_objects_and_query(moonraker):
    c = _client(moonraker)
    assert c.info()["state"] == "ready"
    assert "print_stats" in c.objects()
    st = c.query({"print_stats": ["state"], "toolhead": None, "nope": None})
    assert st == {"print_stats": {"state": "standby"}, "toolhead": {"extruder": "extruder"}}


def test_gcode_ok_and_spool(moonraker):
    c = _client(moonraker)
    c.gcode("SET_ACTIVE_SPOOL ID=7")
    assert moonraker.gcode_log == ["SET_ACTIVE_SPOOL ID=7"]
    assert c.spool_id() == 7


def test_gcode_error_message(moonraker):
    moonraker.gcode_errors["FOO"] = "Unknown command:\"FOO\""
    with pytest.raises(mr.GcodeError) as e:
        _client(moonraker).gcode("FOO")
    assert "Unknown command" in str(e.value)


def test_unauthorized(moonraker):
    moonraker.api_key = "s3cret"
    with pytest.raises(mr.Unauthorized):
        _client(moonraker).info()


def test_api_key_header_sent(moonraker):
    moonraker.api_key = "s3cret"
    assert _client(moonraker, api_key="s3cret").info()["state"] == "ready"


def test_offline():
    with pytest.raises(mr.Offline):
        mr.Moonraker("127.0.0.1", 9, timeout=0.5).info()


def test_print_actions_history_db_webcams(moonraker):
    c = _client(moonraker)
    c.print_action("pause")
    assert moonraker.actions == ["pause"]
    with pytest.raises(ValueError):
        c.print_action("explode")
    moonraker.history = [{"job_id": "2"}, {"job_id": "1"}]
    assert c.history_last() == {"job_id": "2"}
    assert c.db_get("lane_data") is None
    c.db_post("lane_data", "lane0", {"lane": "0"})
    assert c.db_get("lane_data") == {"lane0": {"lane": "0"}}
    assert c.db_namespaces() == ["lane_data"]
    moonraker.webcams = [{"name": "cam", "enabled": True, "stream_url": "/webcam/?action=stream"}]
    assert c.webcams()[0]["name"] == "cam"
    assert c.server_config()["spoolman"]["server"].endswith(":7912")
    assert c.spoolman_status()["spoolman_connected"] is True


def test_subscriber_gets_status_events_and_reconnects(moonraker):
    got, events = [], []
    sub = mr.Subscriber(_client(moonraker), {"print_stats": None}, got.append,
                        lambda name, params: events.append(name), backoff=(0.1, 0.5))
    sub.start()
    try:
        assert wait_for(lambda: got and got[0] == {"print_stats": {"state": "standby", "filename": "", "info": {}}})
        assert wait_for(lambda: moonraker._subs)
        moonraker.push({"print_stats": {"state": "printing"}})
        assert wait_for(lambda: {"print_stats": {"state": "printing"}} in got)
        moonraker.set_spool(5)
        assert wait_for(lambda: "notify_active_spool_set" in events)
        n = len(got)
        moonraker.drop()
        assert wait_for(lambda: len(got) > n, 5)          # a fresh snapshot after the reconnect
        assert sub.connected
    finally:
        sub.stop()
    assert not sub.connected


def test_subscriber_resubscribes_on_klippy_ready(moonraker):
    got = []
    sub = mr.Subscriber(_client(moonraker), {"print_stats": None}, got.append, lambda *a: None, backoff=(0.1, 0.5))
    sub.start()
    try:
        assert wait_for(lambda: len(got) == 1)
        moonraker.event("notify_klippy_ready")
        assert wait_for(lambda: len(got) == 2)
    finally:
        sub.stop()


def test_capture_strips_secrets(moonraker, tmp_path):
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "capture_klipper", pathlib.Path(__file__).parents[2] / "tools" / "capture_klipper.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    moonraker.server_config = {"spoolman": {"server": "http://x"}, "authorization": {"api_key": "abc"},
                               "notifier": {"token": "t"}}
    moonraker.history = [{"job_id": "1", "filename": "a.gcode"}]
    assert cap.main(["--host", moonraker.host, "--port", str(moonraker.port), "--out", str(tmp_path)]) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    for want in ("objects.json", "info.json", "server_info.json", "status.json", "webcams.json", "history.json",
                 "spoolman_status.json", "db_namespaces.json", "server_config.json"):
        assert want in names
    blob = "".join(p.read_text() for p in tmp_path.iterdir())
    assert "abc" not in blob and '"t"' not in blob
    assert json.loads((tmp_path / "status.json").read_text())["print_stats"]["state"] == "standby"
