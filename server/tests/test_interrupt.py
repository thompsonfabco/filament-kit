"""C1: an interrupted slot test / calibration / mapping never leaves a test colour silently.

Restore in a finally (KeyboardInterrupt too), cooperative abort (CLI signals, service shutdown), and the slot
snapshot on disk for a process that is killed outright."""
import copy
import json
import signal
import threading
import time

import pytest

from filament_kit import cli
from filament_kit.bridge import ams, calib3mf, connection, mapping, registry, slottest, snapshot
from filament_kit.bridge.calib3mf import CalibResult
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from fakes.fake_paho import FakeClient, FakePrinter
from test_slottest import ADDR, LABELS, REPORT, assert_back_to_original, no_test_colour_left

SERIAL = "S1"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir(exist_ok=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 2.0)
    monkeypatch.setattr(snapshot, "CONFIRM_TIMEOUT", 1.0)


@pytest.fixture
def rig():
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c
    m = Manager(client_factory=factory)
    registry.upsert(Printer(SERIAL, "Office H2D", "O1D", "10.0.0.5", "13572468", True))
    m.sync()
    printer = FakePrinter(clients[0], REPORT)
    clients[0].connected(0)
    assert m.wait_report(SERIAL, lambda r: "vt_tray" in r, 2) is not None
    yield m, printer, clients[0]
    m.stop()


def colours_written(printer):
    return [w["tray_color"] for w in printer.writes]


# ---------------------------------------------------------------- slot test

def test_keyboard_interrupt_mid_test_still_restores_then_reraises(rig):
    m, printer, _ = rig

    def step(text):
        if text.startswith("Testing slot A3"):
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        slottest.run(m, SERIAL, step)
    assert no_test_colour_left(printer)
    assert_back_to_original(printer)
    assert not snapshot.pending(SERIAL)


def test_should_stop_aborts_restores_and_says_interrupted(rig):
    m, printer, _ = rig
    stop = threading.Event()

    def step(text):
        if text.startswith("Testing slot A2"):
            stop.set()
    res = slottest.run(m, SERIAL, step, should_stop=stop.is_set)
    assert res.problems[0].startswith("interrupted")
    assert set(res.confirmed) == {"A1"}                  # stopped before A2's write
    assert res.restored is True
    assert no_test_colour_left(printer)
    assert not snapshot.pending(SERIAL)


def test_snapshot_saved_before_the_first_write_and_deleted_after_restore(rig, monkeypatch):
    m, printer, _ = rig
    seen = []
    real = m.set_slot

    def spy(serial, ams_id, tray_id, setting, timeout=None):
        if not seen:
            seen.append(snapshot.load(SERIAL))
        return real(serial, ams_id, tray_id, setting, timeout)
    monkeypatch.setattr(m, "set_slot", spy)
    res = slottest.run(m, SERIAL, lambda t: None)
    assert res.restored is True
    snap = seen[0]
    assert snap is not None and snap["kind"] == "slottest"
    assert {s["label"] for s in snap["slots"]} == set(LABELS)
    a1 = next(s for s in snap["slots"] if s["label"] == "A1")
    assert (a1["ams_id"], a1["tray_id"], a1["setting"]["tray_color"]) == (0, 0, "FF0000FF")
    assert snap["test_colours"] == [f"FA{n:02X}00FF" for n in range(1, 7)]
    assert not snapshot.pending(SERIAL)


def test_unconfirmed_restore_keeps_the_snapshot(rig, monkeypatch):
    m, printer, _ = rig
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 0.3)

    def step(text):
        if text.startswith("Restoring"):
            printer.frozen = True
    res = slottest.run(m, SERIAL, step)
    assert res.restored is False
    assert snapshot.pending(SERIAL)


def test_snapshot_cannot_be_saved_nothing_is_written(rig, monkeypatch):
    m, printer, _ = rig

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(snapshot, "save", boom)
    res = slottest.run(m, SERIAL, lambda t: None)
    assert printer.writes == [] and res.confirmed == {}
    assert any("snapshot" in p for p in res.problems)


def test_real_near_red_spool_is_mapped_not_refused(rig):
    """R3: a slot whose real colour has the test-colour shape no longer locks mapping out; the test picks a test
    colour that no slot holds and puts the near-red colour back afterwards."""
    m, printer, _ = rig
    printer.push({"vt_tray": dict(REPORT["vt_tray"], tray_color="FA0600FF")})
    assert m.wait_report(SERIAL, lambda r: r["vt_tray"]["tray_color"] == "FA0600FF", 2)
    res = slottest.run(m, SERIAL, lambda t: None)
    assert res.restored is True and len(res.confirmed) == 6, res.problems
    assert "FA0600FF" not in colours_written(printer)[:6]
    assert printer.tray(254, 0)["tray_color"] == "FA0600FF"
    assert not snapshot.pending(SERIAL)


def test_slot_test_refuses_while_a_snapshot_is_pending(rig):
    m, printer, _ = rig
    snapshot.save(SERIAL, "slottest", [{"label": "A1", "ams_id": 0, "tray_id": 0,
                                         "setting": {"tray_color": "FF0000FF"}}])
    res = slottest.run(m, SERIAL, lambda t: None)
    assert printer.writes == [] and res.confirmed == {}
    assert snapshot.pending(SERIAL)


def test_corrupt_snapshot_says_what_test_colours_look_like_and_where_the_file_is(rig):
    """R3: an unreadable snapshot names the shape of the test colours and the file to delete."""
    m, printer, _ = rig
    f = snapshot.path(SERIAL)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{not json", encoding="utf-8")
    probs = snapshot.restore(m, SERIAL)
    assert len(probs) == 1, probs
    p = probs[0]
    assert "FAnn00FF" in p and "F7" in p and "FE" in p and "red" in p
    assert "Studio" in p and str(f) in p and "delete" in p
    assert printer.writes == [] and snapshot.pending(SERIAL)


# ---------------------------------------------------------------- the snapshot file + mapping

def leave_test_colours(printer):
    """What a killed slot test leaves: the snapshot of the originals, and test colours on two slots."""
    slots = []
    for label in LABELS:
        a, t = ADDR[label]
        tray = printer.tray(a, t)
        slots.append({"label": label, "ams_id": a, "tray_id": t,
                      "setting": {k: tray.get(k, "") for k in ("tray_info_idx", "tray_color", "tray_type",
                                                                "tray_sub_brands", "nozzle_temp_min",
                                                                "nozzle_temp_max")}})
    snapshot.save(SERIAL, "slottest", slots, ["FA0100FF", "FA0200FF"])
    rep = copy.deepcopy(printer.report["ams"])
    rep["ams"][0]["tray"][0]["tray_color"] = "FA0100FF"
    rep["ams"][0]["tray"][1]["tray_color"] = "FA0200FF"
    printer.push({"ams": rep})


@pytest.fixture
def stub_jobs(monkeypatch):
    calls = {"st": 0, "calib": 0}

    def st_run(manager, serial, on_step, should_stop=None):
        calls["st"] += 1
        return slottest.SlotTestResult(confirmed={"A1": {"ams_id": 0, "tray_id": 0}})

    def calib_run(manager, serial, slotmap, should_stop=None):
        calls["calib"] += 1
        return CalibResult(decoding={"A1": 0}, consistent=True)
    monkeypatch.setattr(slottest, "run", st_run)
    monkeypatch.setattr(calib3mf, "run", calib_run)
    return calls


def test_next_job_restores_from_the_snapshot_first(rig, stub_jobs):
    m, printer, _ = rig
    leave_test_colours(printer)
    assert m.wait_report(SERIAL, lambda r: r["ams"]["ams"][0]["tray"][1]["tray_color"] == "FA0200FF", 2)
    v = mapping.Mapper(m).run(SERIAL)
    assert no_test_colour_left(printer)
    assert_back_to_original(printer)
    assert not snapshot.pending(SERIAL)
    assert v["state"] == "done" and stub_jobs["st"] == 1


def test_next_job_refused_when_the_snapshot_restore_is_not_confirmed(rig, stub_jobs):
    m, printer, _ = rig
    leave_test_colours(printer)
    assert m.wait_report(SERIAL, lambda r: r["ams"]["ams"][0]["tray"][1]["tray_color"] == "FA0200FF", 2)
    printer.frozen = True
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                                     calibrated=True, observe=False))
    v = mapping.Mapper(m).run(SERIAL)
    assert v["state"] == "failed" and stub_jobs["st"] == 0
    assert any("interrupted mapping" in p for p in v["problems"])
    assert snapshot.pending(SERIAL)
    assert v["calibrated"] is False and v["observe"] is True


def set_colour(m, printer, unit, tray, colour):
    """The owner (RFID, Studio, touchscreen) changes a slot's colour on the printer."""
    rep = copy.deepcopy(printer.report["ams"])
    rep["ams"][unit]["tray"][tray]["tray_color"] = colour
    printer.push({"ams": rep})
    assert m.wait_report(SERIAL, lambda r: r["ams"]["ams"][unit]["tray"][tray]["tray_color"] == colour, 2)


def test_stale_restore_leaves_a_slot_the_owner_changed_since(rig):
    """R2: after a kill -9, a slot whose colour is no test colour was changed by the owner since: left as is."""
    m, printer, _ = rig
    leave_test_colours(printer)
    set_colour(m, printer, 0, 2, "123456FF")              # A3: the owner swapped the spool meanwhile
    assert snapshot.restore(m, SERIAL) == []
    assert sorted({(w["ams_id"], w["tray_id"]) for w in printer.writes}) == [(0, 0), (0, 1)]
    assert printer.tray(0, 2)["tray_color"] == "123456FF"
    assert_back_to_original(printer, ["A1", "A2", "A4", "HT-A", "Ext"])
    assert not snapshot.pending(SERIAL)


def test_stale_calibration_snapshot_writes_nothing(rig):
    """R2: the calibration writes no slot setting, so a stale calibration snapshot puts nothing back."""
    m, printer, _ = rig
    slots = [{"label": "A1", "ams_id": 0, "tray_id": 0, "setting": dict(printer.tray(0, 0))}]
    snapshot.save(SERIAL, "calibration", slots)
    set_colour(m, printer, 0, 0, "123456FF")              # the owner loaded another spool into A1
    assert snapshot.restore(m, SERIAL) == []
    assert printer.writes == [] and printer.tray(0, 0)["tray_color"] == "123456FF"
    assert not snapshot.pending(SERIAL)


def test_old_slottest_snapshot_still_restores_its_test_colours(rig):
    """R2: an old snapshot (more than 10 minutes) restores only slots still showing one of its test colours."""
    m, printer, _ = rig
    leave_test_colours(printer)
    f = snapshot.path(SERIAL)
    d = json.loads(f.read_text(encoding="utf-8"))
    f.write_text(json.dumps(dict(d, at=time.time() - 3600)), encoding="utf-8")
    set_colour(m, printer, 0, 3, "ABCDEFFF")              # A4 changed since
    assert snapshot.restore(m, SERIAL) == []
    assert sorted({(w["ams_id"], w["tray_id"]) for w in printer.writes}) == [(0, 0), (0, 1)]
    assert printer.tray(0, 3)["tray_color"] == "ABCDEFFF"


def test_a_new_spool_in_a_test_colour_outside_the_snapshot_does_not_block(rig):
    """R2: the final 'no test colour left' check looks only at the snapshot's own (non-forgotten) slots."""
    m, printer, _ = rig
    leave_test_colours(printer)
    snapshot.forget(SERIAL, 0, 3)                         # A4 was loaded since (Load into printer) ...
    set_colour(m, printer, 0, 3, "FA0100FF")              # ... with a real near-red spool
    assert snapshot.restore(m, SERIAL) == []
    assert printer.tray(0, 3)["tray_color"] == "FA0100FF"
    assert_back_to_original(printer, ["A1", "A2"])
    assert not snapshot.pending(SERIAL)


def test_loading_a_slot_drops_it_from_the_snapshot():
    snapshot.save(SERIAL, "slottest", [{"label": "A1", "ams_id": 0, "tray_id": 0, "setting": {}},
                                        {"label": "A2", "ams_id": 0, "tray_id": 1, "setting": {}}])
    snapshot.forget(SERIAL, 0, 0)
    assert [s["label"] for s in snapshot.load(SERIAL)["slots"]] == ["A2"]
    snapshot.forget(SERIAL, 0, 1)
    assert not snapshot.pending(SERIAL)


def test_service_start_restores_a_pending_snapshot(rig):
    m, printer, _ = rig
    leave_test_colours(printer)
    assert m.wait_report(SERIAL, lambda r: r["ams"]["ams"][0]["tray"][1]["tray_color"] == "FA0200FF", 2)
    mp = mapping.Mapper(m)
    mp.recover_pending(wait=5)
    mp.shutdown(10)
    assert no_test_colour_left(printer)
    assert not snapshot.pending(SERIAL)


def test_service_start_leaves_the_snapshot_when_busy(rig):
    m, printer, _ = rig
    leave_test_colours(printer)
    printer.push({"gcode_state": "RUNNING"})
    assert m.wait_report(SERIAL, lambda r: r.get("gcode_state") == "RUNNING", 2)
    mp = mapping.Mapper(m)
    mp.recover_pending(wait=1)
    mp.shutdown(10)
    assert snapshot.pending(SERIAL)
    assert not [w for w in printer.writes]


# ---------------------------------------------------------------- mapping job: BaseException, abort, shutdown

def test_mapping_job_base_exception_fails_and_reraises(rig, monkeypatch):
    m, printer, _ = rig
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                                     calibrated=True, observe=False))

    def st_run(manager, serial, on_step, should_stop=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(slottest, "run", st_run)
    mp = mapping.Mapper(m)
    with pytest.raises(KeyboardInterrupt):
        mp.run(SERIAL)
    v = mp.view(SERIAL)
    assert v["state"] == "failed" and v["calibrated"] is False and v["observe"] is True
    assert not mp.in_progress(SERIAL)


def test_shutdown_aborts_a_running_job_and_waits_for_its_restore(rig, monkeypatch):
    m, printer, _ = rig
    events = []

    def st_run(manager, serial, on_step, should_stop=None):
        events.append("started")
        while not should_stop():
            time.sleep(0.01)
        time.sleep(0.2)                      # the restore takes a moment
        events.append("restored")
        return slottest.SlotTestResult(problems=["interrupted: mapping was stopped; slot test stopped"])
    monkeypatch.setattr(slottest, "run", st_run)
    mp = mapping.Mapper(m)
    mp.start(SERIAL)
    for _ in range(200):
        if events:
            break
        time.sleep(0.01)
    mp.shutdown(10)
    assert events == ["started", "restored"]
    v = mp.view(SERIAL)
    assert v["state"] == "failed"


def test_aborted_slot_test_does_not_run_the_calibration(rig, monkeypatch, stub_jobs):
    m, printer, _ = rig
    mp = mapping.Mapper(m)

    def st_run(manager, serial, on_step, should_stop=None):
        mp.abort(SERIAL)
        return slottest.SlotTestResult(confirmed={"A1": {"ams_id": 0, "tray_id": 0}},
                                       problems=["interrupted: mapping was stopped; slot test stopped"])
    monkeypatch.setattr(slottest, "run", st_run)
    v = mp.run(SERIAL)
    assert v["state"] == "failed" and stub_jobs["calib"] == 0


def test_thread_start_failure_releases_the_lock(rig, monkeypatch, stub_jobs):
    m, printer, _ = rig
    mp = mapping.Mapper(m)

    def boom(self):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(threading.Thread, "start", boom)
    with pytest.raises(RuntimeError):
        mp.start(SERIAL)
    monkeypatch.undo()
    assert not mp.in_progress(SERIAL)
    assert mp.view(SERIAL)["state"] == "failed"


def test_interrupted_text_says_test_colours_may_remain():
    assert "test colour" in mapping.INTERRUPTED and "next run" in mapping.INTERRUPTED


# ---------------------------------------------------------------- CLI signals

def test_cli_signal_aborts_restores_then_exits_non_zero(rig, monkeypatch, capsys):
    m, printer, _ = rig
    seen = {}

    def st_run(manager, serial, on_step, should_stop=None):
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler) and handler is not signal.default_int_handler
        handler(signal.SIGINT, None)                       # Ctrl-C mid-test
        seen["stop"] = should_stop()
        return slottest.SlotTestResult(confirmed={"A1": {"ams_id": 0, "tray_id": 0}},
                                       problems=["interrupted: mapping was stopped; slot test stopped"])
    monkeypatch.setattr(slottest, "run", st_run)
    monkeypatch.setattr(m, "stop", lambda: None)
    before = signal.getsignal(signal.SIGINT)
    rc = cli.main(["printer", "map", SERIAL], manager_factory=lambda s: m)
    assert rc != 0 and seen["stop"] is True
    assert signal.getsignal(signal.SIGINT) is before       # handlers put back
    out = capsys.readouterr().out
    assert "stopped" in out.lower()


# ---------------------------------------------------------------- calibration snapshot

def test_calibration_saves_and_clears_its_snapshot(monkeypatch, tmp_path):
    from test_calib3mf import FakeManager as CalibManager, SERIAL as CS, CODE, slotmap_for
    from fakes.fake_certs import Leaf
    from fakes.fake_ftps import FakeFtps
    from filament_kit.bridge import ftps
    f = FakeFtps(Leaf(CS), tmp_path / "sd", CODE)
    monkeypatch.setattr(ftps, "PORT", f.port)
    try:
        registry.upsert(Printer(serial=CS, name="H2D", model="H2D", ip="127.0.0.1", access_code=CODE,
                                configured=True))
        cm = CalibManager(f.root, "clobber")
        seen = []
        real = cm.publish

        def spy(serial, payload):
            if payload["print"]["command"] == "project_file":
                seen.append(snapshot.load(CS))
            return real(serial, payload)
        cm.publish = spy
        r = calib3mf.run(cm, CS, slotmap_for(cm.report))
        assert r.restored is True
        assert seen[0] is not None and seen[0]["kind"] == "calibration"
        assert {s["label"] for s in seen[0]["slots"]} == {"A1", "A2", "A4", "HT-A", "Ext"}
        assert not snapshot.pending(CS)
    finally:
        f.close()
