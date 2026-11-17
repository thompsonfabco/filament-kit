"""The event watcher: what both printer families' listeners turn into events (R80 sections 2 and 10, assumption 3)."""
import json
import time
from pathlib import Path

import pytest

from filament_kit import event_sink, watch
from filament_kit.bridge import registry, status
from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper.manager import KlipperFamily
from filament_kit.event_sink import StoreSink
from filament_kit.events import EventStore

DATA = Path(__file__).parent / "data" / "klipper"


def wait_for(pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.03)
    return False


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    kh._reset_cache()
    monkeypatch.setattr(event_sink, "runs", event_sink.RunBook())
    yield tmp_path
    kh._reset_cache()


@pytest.fixture
def store(env):
    return EventStore(env / "state" / "events")


@pytest.fixture
def sink(store):
    s = StoreSink(store)
    event_sink.set_sink(s)           # the run book asks the sink in force for the next id
    yield s
    event_sink.set_sink(None)


def kinds(store):
    return [e["kind"] for e in store.read()["events"]]


class FakeBambu:
    """The Manager's listener hook, the merged report and the connection state."""

    def __init__(self):
        self.listeners, self.report, self.states = [], {}, {}

    def add_listener(self, fn):
        self.listeners.append(fn)

    def wait_report(self, serial, pred, timeout):
        return self.report

    def state(self, serial):
        return self.states.get(serial, "connected")

    def send(self, delta, serial="S1", first=False):
        self.report = status.merge(self.report, delta)
        for fn in self.listeners:
            fn(serial, self.report, first)


@pytest.fixture
def bambu(env):
    registry.upsert(registry.Printer("S1", "Workshop X1", configured=True))
    return FakeBambu()


@pytest.fixture
def w(bambu, sink):
    wt = watch.Watcher(sink, settle=0.2, grace=0).attach(bambu=bambu)
    yield wt
    wt.stop()


def start_print(bambu, job="bracket.3mf"):
    bambu.send({"gcode_state": "IDLE"}, first=True)
    bambu.send({"gcode_state": "RUNNING", "subtask_name": job, "mc_percent": 3})


# ---------------------------------------------------------------- Bambu

def test_first_sight_of_a_printer_writes_no_event(bambu, w, store):
    bambu.send({"gcode_state": "RUNNING", "subtask_name": "a", "mc_percent": 40}, first=True)
    bambu.send({"gcode_state": "RUNNING", "mc_percent": 41})
    assert kinds(store) == []


def test_a_print_started_event_has_job_printer_and_run(bambu, w, store):
    start_print(bambu)
    ev = store.read()["events"][0]
    assert ev["kind"] == "print.started" and ev["subject"] == {"type": "printer", "id": "S1", "name": "Workshop X1"}
    assert ev["actor"]["type"] == "hub" and ev["severity"] == "info"
    assert ev["data"]["job"] == "bracket.3mf" and ev["data"]["printer"] == "S1" and ev["data"]["run"].startswith("r-")
    assert ev["data"]["run"] == f"r-{ev['id']}"                      # the run is named for its first event


def test_runout_stage_gives_print_runout_with_a_condition_and_the_run(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 6, "mc_percent": 41})
    evs = store.read()["events"]
    assert [e["kind"] for e in evs] == ["print.started", "print.runout"]
    assert evs[1]["data"]["percent"] == "41" and evs[1]["data"]["job"] == "bracket.3mf"
    assert evs[1]["data"]["run"] == evs[0]["data"]["run"]
    assert evs[1]["condition"] == {"key": "print-paused:S1", "state": "raised"}
    assert store.is_raised("print-paused:S1")


def test_the_stage_arriving_after_the_state_still_gives_runout(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "mc_percent": 41})          # the stage is not here yet
    assert kinds(store) == ["print.started"]
    bambu.send({"stg_cur": 6})
    w.flush()
    assert kinds(store)[-1] == "print.runout"


def test_user_pause_gives_print_paused_reason_user(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 16})
    ev = store.read()["events"][-1]
    assert ev["kind"] == "print.paused" and ev["data"]["reason"] == "user" and ev["data"]["stage"] == "Paused by user"


def test_a_fault_stage_gives_reason_error(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 17})
    assert store.read()["events"][-1]["data"]["reason"] == "error"


def test_a_pause_nobody_can_explain_is_unknown_after_the_wait(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE"})
    assert kinds(store) == ["print.started"]
    assert wait_for(lambda: kinds(store)[-1:] == ["print.paused"])
    assert store.read()["events"][-1]["data"]["reason"] == "unknown"


def test_resumed_clears_the_condition_and_a_quick_resume_is_no_news(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 16})
    bambu.send({"gcode_state": "RUNNING"})
    assert kinds(store) == ["print.started", "print.paused", "print.resumed"]
    assert not store.is_raised("print-paused:S1")
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 255})                 # no reason yet ...
    bambu.send({"gcode_state": "RUNNING"})                               # ... and running again
    time.sleep(0.4)
    assert kinds(store) == ["print.started", "print.paused", "print.resumed"]


def test_finished_clears_and_has_minutes(bambu, w, store, monkeypatch):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 6})
    now = time.time()
    monkeypatch.setattr(watch.time, "time", lambda: now + 600)
    bambu.send({"gcode_state": "FINISH", "mc_percent": 100})
    ev = store.read()["events"][-1]
    assert ev["kind"] == "print.finished" and ev["data"]["minutes"] == "10" and ev["severity"] == "ok"
    assert not store.is_raised("print-paused:S1")


def test_failed_with_a_print_error_is_error_and_without_one_unknown(bambu, w, store):
    """Prove-first 4: no recorded Bambu report in the repository shows a cancel, so Bambu never says cancelled."""
    start_print(bambu)
    bambu.send({"gcode_state": "FAILED", "mc_percent": 52, "print_error": 0x0300400C})
    ev = [e for e in store.read()["events"] if e["kind"] == "print.failed"][-1]
    assert ev["kind"] == "print.failed" and ev["data"]["reason"] == "error" and ev["data"]["percent"] == "52"
    assert ev["data"]["error"] == "0300_400C"
    start_print(bambu, "b.3mf")
    bambu.send({"print_error": 0})
    bambu.send({"gcode_state": "FAILED", "mc_percent": 10})
    ev = store.read()["events"][-1]
    assert ev["kind"] == "print.failed" and ev["data"]["reason"] == "unknown" and "error" not in ev["data"]
    assert all(e["data"].get("reason") != "cancelled" for e in store.read()["events"])


def test_every_print_event_of_one_run_shares_the_run_value_and_the_next_run_has_another(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "FINISH"})
    start_print(bambu, "two.3mf")
    bambu.send({"gcode_state": "FINISH"})
    runs = [e["data"]["run"] for e in store.read()["events"]]
    assert runs[0] == runs[1] and runs[2] == runs[3] and runs[0] != runs[2]
    assert event_sink.runs.last("S1", "two.3mf") == runs[2]


def test_a_new_hms_code_and_a_new_print_error_give_printer_error_once(bambu, w, store):
    start_print(bambu)
    hms = [{"attr": 0x03000100, "code": 0x00010001}]
    bambu.send({"hms": hms})
    bambu.send({"hms": hms})
    bambu.send({"print_error": 0x05010001})
    errs = [e for e in store.read()["events"] if e["kind"] == "printer.error"]
    assert [e["data"]["code"] for e in errs] == ["0300_0100_0001_0001", "0501_0001"]
    assert errs[0]["data"]["text"] and errs[0]["severity"] == "bad" and errs[0]["condition"] is None


def test_the_hms_codes_at_first_sight_are_not_news(bambu, w, store):
    bambu.send({"gcode_state": "IDLE", "hms": [{"attr": 1, "code": 2}]}, first=True)
    bambu.send({"hms": [{"attr": 1, "code": 2}]})
    assert kinds(store) == []


def test_slot_mapping_jobs_write_no_event(bambu, sink, store):
    busy = {"S1": False}
    watch.Watcher(sink, settle=0.1, mapping_busy=lambda pid: busy[pid]).attach(bambu=bambu)
    bambu.send({"gcode_state": "IDLE"}, first=True)
    busy["S1"] = True                                                # the kit's own mapping job
    bambu.send({"gcode_state": "RUNNING", "subtask_name": "x"})
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 6})
    bambu.send({"gcode_state": "FINISH"})
    busy["S1"] = False
    bambu.send({"gcode_state": "IDLE"})
    bambu.send({"gcode_state": "RUNNING", "subtask_name": "sw-calib-0"})   # its calibration file name
    bambu.send({"gcode_state": "FAILED"})
    assert kinds(store) == []


def test_a_condition_left_raised_by_an_earlier_run_is_cleared_at_first_sight(bambu, w, store):
    store.write("print.runout", {"type": "printer", "id": "S1", "name": "Workshop X1"}, {"type": "hub"}, {"job": "a"})
    assert store.is_raised("print-paused:S1")
    bambu.send({"gcode_state": "IDLE"}, first=True)
    ev = store.read()["events"][-1]
    assert ev["kind"] == "condition.cleared" and ev["data"] == {"key": "print-paused:S1", "reason": "reconciled"}
    assert not store.is_raised("print-paused:S1")


def test_a_paused_printer_at_first_sight_keeps_its_condition(bambu, w, store):
    store.write("print.runout", {"type": "printer", "id": "S1", "name": "x"}, {"type": "hub"}, {"job": "a"})
    bambu.send({"gcode_state": "PAUSE"}, first=True)
    assert store.is_raised("print-paused:S1")


def test_paused_then_idle_without_an_end_state_clears_the_condition(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 6})
    bambu.send({"gcode_state": "IDLE"})
    assert store.read()["events"][-1]["kind"] == "condition.cleared" and not store.is_raised("print-paused:S1")


def test_the_loop_reconciles_a_paused_condition_that_is_no_longer_true(bambu, w, store):
    start_print(bambu)
    bambu.send({"gcode_state": "PAUSE", "stg_cur": 6})
    w._p["S1"].state = "IDLE"                                         # something the listener never saw
    w.reconcile()
    assert not store.is_raised("print-paused:S1")


# ---- offline / online

def test_offline_and_online_with_the_condition(bambu, w, store):
    bambu.send({"gcode_state": "IDLE"}, first=True)
    w.poll()                                                          # first poll: answering
    bambu.states["S1"] = "offline"
    w.poll()
    assert kinds(store) == ["printer.offline"] and store.is_raised("printer-offline:S1")
    w.poll()
    assert kinds(store) == ["printer.offline"]                        # once
    bambu.states["S1"] = "connected"
    w.poll()
    assert kinds(store) == ["printer.offline", "printer.online"] and not store.is_raised("printer-offline:S1")


def test_offline_at_first_sight_writes_nothing_and_a_short_drop_is_no_news(bambu, sink, store):
    bambu.states["S1"] = "offline"
    wt = watch.Watcher(sink, grace=30).attach(bambu=bambu)
    wt.poll()
    bambu.states["S1"] = "connected"
    wt.poll()
    assert kinds(store) == []
    bambu.states["S1"] = "offline"
    wt.poll()                                                         # inside the grace time
    bambu.states["S1"] = "connected"
    wt.poll()
    assert kinds(store) == []


def test_a_printer_that_answers_while_its_offline_condition_is_raised_is_reconciled(bambu, w, store):
    store.write("printer.offline", {"type": "printer", "id": "S1", "name": "x"}, {"type": "hub"})
    w.poll()
    assert store.read()["events"][-1]["data"]["reason"] == "reconciled" and not store.is_raised("printer-offline:S1")


def test_removing_a_printer_clears_its_conditions_at_once(bambu, w, store):
    sub = {"type": "printer", "id": "S9", "name": "Gone"}
    store.write("print.runout", sub, {"type": "hub"}, {"job": "a"})
    store.write("printer.offline", sub, {"type": "hub"})
    w.poll()
    cleared = [e for e in store.read()["events"] if e["kind"] == "condition.cleared"]
    assert {e["data"]["key"] for e in cleared} == {"print-paused:S9", "printer-offline:S9"}
    assert all(e["data"]["reason"] == "subject_removed" for e in cleared) and store.conditions() == []


# ---------------------------------------------------------------- Klipper (the real manager against the fake Moonraker)

SENSOR = "filament_switch_sensor runout"


def sv08(fake, sensor=True):
    fake.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    fake.status = json.loads((DATA / "SV08-MAX" / "status.json").read_text())
    fake.hostname = "SV08MAX"
    if sensor:
        fake.objects = fake.objects + [SENSOR]
        fake.status[SENSOR] = {"filament_detected": True, "enabled": True}


class NoSpoolman:
    def get(self, path):
        return []


@pytest.fixture
def klipper(moonraker, sink, store):
    sv08(moonraker)
    fam = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4))
    pid = registry.add_klipper("SV08 MAX", moonraker.host, moonraker.port).serial
    wt = watch.Watcher(sink, settle=0.5, grace=0).attach(klipper=fam)
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    wait_for(lambda: fam.live(pid) is not None and fam.live(pid)["print"] == "standby")
    time.sleep(0.2)
    yield moonraker, fam, wt, pid
    wt.stop()
    fam.stop()


def printing(fake, name="part.gcode", pct=0.4):
    fake.push({"print_stats": {"state": "printing", "filename": name, "print_duration": 60.0},
               "virtual_sdcard": {"progress": pct}})


def test_assumption_3_the_manager_subscribes_to_the_runout_sensors(klipper):
    fake, fam, wt, pid = klipper
    assert fam.live(pid)["sensors"] == {SENSOR: True}                 # the snapshot carried the sensor's state
    fake.push({SENSOR: {"filament_detected": False}})
    assert wait_for(lambda: fam.live(pid)["sensors"] == {SENSOR: False})     # and its changes arrive by push


def test_assumption_3_a_pause_with_no_filament_gives_print_runout(klipper, store):
    fake, fam, wt, pid = klipper
    printing(fake)
    assert wait_for(lambda: kinds(store) == ["print.started"])
    fake.push({SENSOR: {"filament_detected": False}, "print_stats": {"state": "paused"}})   # one delta
    assert wait_for(lambda: kinds(store)[-1:] == ["print.runout"])
    ev = store.read()["events"][-1]
    assert ev["data"]["job"] == "part.gcode" and ev["data"]["percent"] == "40" and ev["subject"]["id"] == pid
    assert store.is_raised(f"print-paused:{pid}")


def test_assumption_3_the_sensor_may_arrive_before_or_after_the_state(klipper, store):
    fake, fam, wt, pid = klipper
    printing(fake)
    assert wait_for(lambda: kinds(store) == ["print.started"])
    fake.push({SENSOR: {"filament_detected": False}})                 # sensor first
    time.sleep(0.15)
    fake.push({"print_stats": {"state": "paused"}})
    assert wait_for(lambda: kinds(store)[-1:] == ["print.runout"])
    fake.push({"print_stats": {"state": "printing"}, SENSOR: {"filament_detected": True}})
    assert wait_for(lambda: kinds(store)[-1:] == ["print.resumed"])
    fake.push({"print_stats": {"state": "paused"}})                   # state first, sensor 0.2 s later (inside the wait)
    time.sleep(0.2)
    fake.push({SENSOR: {"filament_detected": False}})
    assert wait_for(lambda: kinds(store)[-1:] == ["print.runout"] and kinds(store).count("print.runout") == 2)
    assert kinds(store).count("print.paused") == 0


def test_a_user_pause_with_the_sensor_seeing_filament_gives_paused_user(klipper, store):
    fake, fam, wt, pid = klipper
    printing(fake)
    assert wait_for(lambda: kinds(store) == ["print.started"])
    fake.push({"print_stats": {"state": "paused"}})
    assert wait_for(lambda: kinds(store)[-1:] == ["print.paused"], 8)
    ev = store.read()["events"][-1]
    assert ev["data"]["reason"] == "user" and store.is_raised(f"print-paused:{pid}")


def test_a_printer_with_no_filament_sensor_falls_back_to_paused_unknown(moonraker, sink, store):
    sv08(moonraker, sensor=False)
    fam = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4))
    pid = registry.add_klipper("SV08 MAX", moonraker.host, moonraker.port).serial
    wt = watch.Watcher(sink, settle=0.3).attach(klipper=fam)
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        time.sleep(0.3)
        assert fam.live(pid)["sensors"] == {}
        printing(moonraker)
        assert wait_for(lambda: kinds(store) == ["print.started"])
        moonraker.push({"print_stats": {"state": "paused"}})
        assert wait_for(lambda: kinds(store)[-1:] == ["print.paused"])
        assert store.read()["events"][-1]["data"]["reason"] == "unknown"
    finally:
        wt.stop()
        fam.stop()


def test_klipper_finished_cancelled_and_error_end_states(klipper, store):
    fake, fam, wt, pid = klipper
    for end, kind, reason in (("complete", "print.finished", None), ("cancelled", "print.failed", "cancelled"),
                              ("error", "print.failed", "error")):
        n = len(kinds(store))
        printing(fake)
        assert wait_for(lambda: len(kinds(store)) == n + 1)
        fake.push({"print_stats": {"state": end, "message": "Heater failed" if end == "error" else ""}})
        assert wait_for(lambda: len(kinds(store)) == n + 2)
        ev = store.read()["events"][-1]
        assert ev["kind"] == kind
        if reason:
            assert ev["data"]["reason"] == reason
        if end == "error":
            assert ev["data"]["error"] == "Heater failed"
        fake.push({"print_stats": {"state": "standby", "message": ""}})
        time.sleep(0.15)


def test_klipper_offline_event_after_the_connection_drops(moonraker, sink, store):
    sv08(moonraker)
    fam = KlipperFamily(NoSpoolman(), backoff=(0.1, 0.4), offline_after=0.3)
    pid = registry.add_klipper("SV08 MAX", moonraker.host, moonraker.port).serial
    wt = watch.Watcher(sink, grace=0).attach(klipper=fam)
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        wt.poll()
        moonraker.refuse_ws = True
        moonraker.drop()
        assert wait_for(lambda: fam.state(pid) == "offline")
        wt.poll()
        assert kinds(store) == ["printer.offline"]
    finally:
        wt.stop()
        fam.stop()
