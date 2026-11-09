"""bridge.klipper.manager.KlipperFamily: connections, states, status shape and commands (against FakeMoonraker)."""
import json
import time
from pathlib import Path

import pytest

from filament_kit.bridge import registry, status as bambu_status
from filament_kit.bridge.connection import PrinterOffline, UnknownPrinter
from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper.manager import KlipperFamily

DATA = Path(__file__).parent / "data" / "klipper"


def wait_for(pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.03)
    return False


class NoSpoolman:
    def get(self, path):
        return []


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    kh._reset_cache()
    yield tmp_path
    kh._reset_cache()


def as_sv08(fake):
    fake.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    fake.status = json.loads((DATA / "SV08-MAX" / "status.json").read_text())
    fake.hostname = "SV08MAX"


@pytest.fixture
def fam():
    f = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4))
    yield f
    f.stop()


def add(fake, name="SV08 MAX"):
    return registry.add_klipper(name, fake.host, fake.port).serial


def test_state_connected_and_status_shape(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    st = fam.status(pid)
    bambu_keys = set(bambu_status.summarize({}, []).keys())
    assert bambu_keys <= set(st)
    assert st["gcode_state"] == "IDLE"
    assert st["ams"][0]["label"] == "T0" and st["ams"][0]["kind"] == "toolhead"
    assert st["ams"][0]["slots"][0]["label"] == "T0"
    assert st["temps"]["nozzle"] and st["temps"]["bed"]["current"] is not None
    assert fam.verified(pid) is True
    assert fam.summary(pid) == {"gcode_state": "IDLE", "percent": 0, "remaining_min": 0, "job": None}
    assert (Path(registry.config.paths().state) / "printers" / pid / "detected.xml").exists()


def test_status_follows_push(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "connected")
    moonraker.push({"print_stats": {"state": "printing", "filename": "part.gcode", "print_duration": 60.0},
                    "virtual_sdcard": {"progress": 0.25}})
    assert wait_for(lambda: fam.status(pid)["gcode_state"] == "RUNNING")
    st = fam.status(pid)
    assert (st["job"], st["percent"], st["remaining_min"]) == ("part.gcode", 25, 3)


def test_klippy_shutdown_state(moonraker, fam):
    as_sv08(moonraker)
    moonraker.klippy_state, moonraker.state_message = "shutdown", "MCU 'mcu' shutdown: Timer too close"
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "klippy_not_ready")
    assert "Timer too close" in fam.status(pid)["notes"][0]
    moonraker.klippy_state = "ready"
    # "connected" comes before the subscription: an event sent in between is lost, as with the real thing
    assert wait_for(lambda: moonraker.event("notify_klippy_ready") or fam.state(pid) == "connected")


def test_shutdown_event_while_connected(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "connected")
    moonraker.klippy_state = "shutdown"
    # "connected" comes before the subscription: an event sent in between is lost, as with the real thing
    assert wait_for(lambda: moonraker.event("notify_klippy_shutdown") or fam.state(pid) == "klippy_not_ready")


def test_unauthorized_state(moonraker, fam):
    moonraker.api_key = "k"
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "unauthorized")
    registry.set_api_key(pid, "k")
    fam.sync()
    assert wait_for(lambda: fam.state(pid) in ("connected", "unknown_model"))


def test_unknown_model_state(moonraker, fam):
    pid = add(moonraker, "Voron")
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "unknown_model")
    assert fam.status(pid)["ams"][0]["slots"][0]["label"] == "T0"   # generic single still works


def test_command_pause_calls_print_pause(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "connected")
    r = fam.command(pid, "pause")
    assert r["ok"] is True and moonraker.actions == ["pause"]
    fam.command(pid, "stop")
    assert moonraker.actions == ["pause", "cancel"]
    fam.command(pid, "light_on")
    assert moonraker.gcode_log[-1] == "SET_LED LED=chamber_light WHITE=1 SYNC=0"


def test_light_not_supported_on_generic(moonraker, fam):
    pid = add(moonraker, "Voron")
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "unknown_model")
    r = fam.command(pid, "light_on")
    assert r["ok"] is False and r["reply"]["reason"] == "not_supported"


def test_command_unknown_printer(fam):
    with pytest.raises(UnknownPrinter):
        fam.command("nope", "pause")


def test_offline_backoff_no_exception(fam):
    pid = registry.add_klipper("Gone", "127.0.0.1", 9).serial
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "offline")
    assert fam.status(pid)["gcode_state"] == "UNKNOWN"
    with pytest.raises(PrinterOffline):
        fam.command(pid, "pause")


def test_offline_keeps_last_values(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "connected")
    moonraker.drop()
    st = fam.status(pid)
    assert st["ams"][0]["label"] == "T0"


def test_sync_removes_deleted_printer(moonraker, fam):
    pid = add(moonraker, "Voron")
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "unknown_model")
    registry.remove(pid)
    fam.sync()
    assert fam.state(pid) == "not_configured"


def test_camera_url(moonraker, fam):
    as_sv08(moonraker)
    moonraker.webcams = [{"name": "off", "enabled": False, "stream_url": "/x"},
                         {"name": "Front", "enabled": True, "service": "mjpegstreamer",
                          "stream_url": "/webcam/?action=stream"}]
    pid = add(moonraker)
    fam.start()
    assert wait_for(lambda: fam.state(pid) == "connected")
    assert fam.camera_url(pid) == f"http://{moonraker.host}/webcam/?action=stream"
    assert fam.camera_kind(pid) == "mjpeg"


# ---- final review I1 / I2 / M3 -----------------------------------------------------------------------------------

def test_offline_when_the_websocket_stays_down(moonraker):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4), offline_after=0.5)
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        moonraker.refuse_ws = True
        moonraker.drop()
        assert wait_for(lambda: fam.state(pid) == "offline", 5)
        assert fam.summary(pid)["gcode_state"] == "UNKNOWN"       # never a stale RUNNING
        moonraker.refuse_ws = False
        assert wait_for(lambda: fam.state(pid) == "connected", 8)
    finally:
        fam.stop()


def test_spool_reread_after_a_reconnect(moonraker):
    """A tap while the websocket was down (no notify reached the kit): the reconnect snapshot re-reads the spool."""
    as_sv08(moonraker)
    pid = add(moonraker)
    fam = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4))
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        moonraker.refuse_ws = True
        moonraker.drop()
        time.sleep(0.3)
        moonraker.spool_id = 42                  # changed with nobody listening
        moonraker.refuse_ws = False
        assert wait_for(lambda: fam.slots(pid)[0].slots[0].spool_id == 42, 8)
    finally:
        fam.stop()


def test_webhooks_shutdown_state_with_klippers_message(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    moonraker.push({"webhooks": {"state": "shutdown", "state_message": "MCU 'mcu' shutdown: Timer too close"}})
    assert wait_for(lambda: fam.state(pid) == "klippy_not_ready")
    assert "Timer too close" in fam.status(pid)["notes"][0]


def test_shutdown_event_shows_klippers_message(moonraker, fam):
    as_sv08(moonraker)
    pid = add(moonraker)
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    moonraker.klippy_state, moonraker.state_message = "shutdown", "Lost communication with MCU 'mcu'"
    moonraker.event("notify_klippy_shutdown")
    assert wait_for(lambda: "Lost communication" in (fam.status(pid)["notes"] or [""])[0])


def test_periodic_sync_picks_up_a_cli_add(moonraker):
    fam = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4), sync_every=0.3)
    fam.start()
    try:
        pid = add(moonraker, "Voron")                # e.g. `filament-kit klipper add` in another process
        assert wait_for(lambda: fam.state(pid) == "unknown_model", 8)
    finally:
        fam.stop()


def test_own_lane_data_does_not_change_detection(moonraker, fam):
    """Final review I6: lane_data the kit itself published is not a lane_data printer."""
    moonraker.db = {"lane_data": {"lane0": {"lane": "0", "spool_id": 3, "source": "filament-kit"}}}
    pid = add(moonraker, "Voron")
    fam.start()
    assert fam.wait_settled(pid, 8) == "unknown_model"
    assert fam.model(pid)[1].key == "single"


def test_foreign_lane_data_is_detected(moonraker, fam):
    moonraker.db = {"lane_data": {"lane0": {"lane": "0", "spool_id": 3}}}       # written by AFC or another tool
    pid = add(moonraker, "Voron")
    fam.start()
    assert fam.wait_settled(pid, 8) == "unknown_model"
    assert fam.model(pid)[1].key == "lane-data"


# ---- final review M2 / M4 ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    ("/webcam/?action=stream", True),
    ("http://{host}:8080/stream", True),
    ("file:///etc/passwd", False),
    ("http://evil.example.com/stream", False),
    ("ftp://{host}/x", False),
])
def test_camera_url_only_http_on_the_printer(moonraker, fam, url, ok):
    as_sv08(moonraker)
    moonraker.webcams = [{"name": "c", "enabled": True, "stream_url": url.replace("{host}", moonraker.host)}]
    pid = add(moonraker)
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    assert (fam.camera_url(pid) is not None) is ok


def test_job_record_never_blocks_follow_moves(moonraker, spoolman_url, monkeypatch):
    """Final review M4: waiting for Moonraker's history runs beside follow mode, and an entry still in progress
    after the wait is not recorded."""
    from filament_kit.bridge.klipper import manager as mgr_mod
    from filament_kit.spoolman import Spoolman
    monkeypatch.setattr(mgr_mod, "HISTORY_WAIT", 2.0)
    as_sv08(moonraker)
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    v = sm.post("vendor", {"name": "V"})
    f = sm.post("filament", {"name": "F", "vendor_id": v["id"], "material": "PLA"})
    s = sm.post("spool", {"filament_id": f["id"], "location": "Shelf"})
    pid = add(moonraker)
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        moonraker.history = [{"job_id": "9", "status": "in_progress", "filename": "x.gcode"}]
        moonraker.push({"print_stats": {"state": "printing"}})
        moonraker.push({"print_stats": {"state": "complete"}})
        time.sleep(0.2)
        t0 = time.monotonic()
        moonraker.set_spool(s["id"])
        assert wait_for(lambda: sm.get(f"spool/{s['id']}")["location"] == "SV08 MAX – T0", 5)
        assert time.monotonic() - t0 < 1.5                  # not queued behind the 2 s history wait
        time.sleep(2.5)
        assert fam.usage(pid, 36500) == []                  # still in progress after the wait: not recorded
    finally:
        fam.stop()
