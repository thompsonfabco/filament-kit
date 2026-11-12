"""Mapping job (slot test + calibration as one job per printer), `printer map` / `printer unpin` CLI."""
import json
import threading
import time

import pytest

from filament_kit import cli, config, secret_input
from filament_kit.bridge import ams, calib3mf, connection, mapping, registry, slottest
from filament_kit.bridge.calib3mf import CalibResult
from filament_kit.bridge.connection import Manager, PrinterOffline, UnknownPrinter
from filament_kit.bridge.slottest import PrinterBusy, SlotTestResult
from fakes.fake_paho import FakeClient

SERIAL = "01P00A111111111"
CODE = "13572468"
CONFIRMED = {"A1": {"ams_id": 0, "tray_id": 0}, "A2": {"ams_id": 0, "tray_id": 1},
             "HT-A": {"ams_id": 128, "tray_id": 0}}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    registry.upsert(registry.Printer(SERIAL, "Office H2D", "O1D", "10.0.0.5", CODE, True, cert_fp="ab" * 32))


class FakeManager:
    def __init__(self, state="connected", gcode_state="IDLE"):
        self.st = state
        self.gcode_state = gcode_state
        self.synced = self.stopped = 0

    def state(self, serial):
        return self.st if serial == SERIAL else "not_configured"

    def summary(self, serial):
        return {"gcode_state": self.gcode_state, "percent": 0, "remaining_min": 0, "job": None}

    def sync(self):
        self.synced += 1

    def wait_settled(self, serial, timeout):
        return self.state(serial)

    def wait_report(self, serial, predicate, timeout):
        return {"gcode_state": self.gcode_state}

    def stop(self):
        self.stopped += 1


@pytest.fixture
def calls():
    return {"slottest": 0, "calib": []}


@pytest.fixture(autouse=True)
def no_job_outlives_its_test():
    """A job a test started on a thread must have given the printer back before the next test begins: a hold left in
    the process-wide table (`mapping._WRITERS`) refuses the next test's job with AlreadyRunning. (That was the
    2026-11-10 flaky test_last_result_survives_a_restart: the test before it gave its slowed second job only 0.1 s.)
    Waits up to 5 s, then fails HERE, in the test that leaked the hold, and clears it so the next one is unaffected."""
    yield
    end = time.monotonic() + 5
    while time.monotonic() < end:
        with mapping._WRITERS_GUARD:
            held = sorted(k for k, w in mapping._WRITERS.items() if w["map"])
        if not held:
            return
        time.sleep(0.01)
    with mapping._WRITERS_GUARD:
        for k in held:
            mapping._WRITERS[k]["map"] = False
    pytest.fail(f"a mapping job still held {held} 5 s after the test ended")


@pytest.fixture
def stubs(monkeypatch, calls):
    """slottest.run confirms CONFIRMED (steps reported); calib3mf.run decodes default_global unless changed."""
    cfg = {"st": None, "calib": None, "gate": None}

    def st_run(manager, serial, on_step, should_stop=None):
        calls["slottest"] += 1
        on_step("Reading the AMS slots")
        if cfg["gate"] is not None:
            cfg["gate"].wait(5)
        on_step("Testing slot A1 (1/3)")
        on_step("Slot test finished")
        return cfg["st"] or SlotTestResult(confirmed=dict(CONFIRMED))

    def calib_run(manager, serial, slotmap, should_stop=None):
        calls["calib"].append(json.loads(json.dumps(slotmap.slots)))
        if cfg["calib"] is not None:
            return cfg["calib"]
        dec = {lab: ams.default_global(s["ams_id"], s["tray_id"]) for lab, s in slotmap.slots.items()}
        return CalibResult(decoding=dec, consistent=True, sent=dict(dec))
    monkeypatch.setattr(slottest, "run", st_run)
    monkeypatch.setattr(calib3mf, "run", calib_run)
    return cfg


def wait_done(mapper, serial=SERIAL, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = mapper.view(serial)
        if v["state"] != "running":
            return v
        time.sleep(0.01)
    raise AssertionError("mapping did not finish")


# ---------------------------------------------------------------- the job

def test_success_saves_calibrated_map(stubs, calls):
    m = mapping.Mapper(FakeManager())
    steps = []
    v = m.run(SERIAL, on_step=steps.append)
    assert v["state"] == "done" and v["calibrated"] is True and v["observe"] is False and v["problems"] == []
    assert {s["label"]: (s["ams_id"], s["tray_id"], s["global"]) for s in v["slots"]} == {
        "A1": (0, 0, 0), "A2": (0, 1, 1), "HT-A": (128, 0, 128)}
    saved = ams.load_map(SERIAL)
    assert saved.calibrated and not saved.observe
    assert saved.slots["HT-A"] == {"ams_id": 128, "tray_id": 0, "global_id": 128}
    assert "Testing slot A1 (1/3)" in steps and any("calibration" in s.lower() for s in steps)
    # the calibration was given exactly the confirmed slots
    assert set(calls["calib"][0]) == set(CONFIRMED)


def test_global_ids_come_from_the_decoding(stubs):
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 1, "HT-A": 16}, consistent=True)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert {s["label"]: s["global"] for s in v["slots"]}["HT-A"] == 16
    assert ams.load_map(SERIAL).slots["HT-A"]["global_id"] == 16


def test_inconsistent_calibration_is_observe_mode(stubs):
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 2, "HT-A": 128}, consistent=False,
                                 problems=["A2: sent slot 1, the printer reported 2"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "done" and v["calibrated"] is False and v["observe"] is True
    assert "A2: sent slot 1, the printer reported 2" in v["problems"]
    saved = ams.load_map(SERIAL)
    assert not saved.calibrated and saved.observe and set(saved.slots) == set(CONFIRMED)


@pytest.mark.parametrize("problem", ["cert_changed", "printer refused the calibration job", "printer_busy"])
def test_refused_calibration_is_observe_mode(stubs, problem):
    stubs["calib"] = CalibResult(consistent=False, problems=[problem], cert_changed=problem == "cert_changed")
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["calibrated"] is False and v["observe"] is True and problem in v["problems"]


def test_slot_test_restore_failure_fails_the_job(stubs, calls):
    """A failed job never leaves a trusted map: an earlier calibrated map is downgraded to observe mode."""
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                                     calibrated=True, observe=False))
    stubs["st"] = SlotTestResult(confirmed={"A1": {"ams_id": 0, "tray_id": 0}}, restored=False,
                                 problems=["A1: restore not confirmed (...)", "A2: not restored (printer_offline)"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "failed"
    assert "A1: restore not confirmed (...)" in v["problems"] and "A2: not restored (printer_offline)" in v["problems"]
    assert calls["calib"] == []                        # no calibration after a failed restore
    saved = ams.load_map(SERIAL)
    assert saved.calibrated is False and saved.observe is True
    assert saved.slots == {"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}   # its slots kept, untrusted
    assert v["calibrated"] is False and v["observe"] is True


def test_slot_test_restore_failure_without_earlier_map(stubs):
    stubs["st"] = SlotTestResult(restored=False, problems=["A1: not restored (printer_offline)"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "failed" and v["calibrated"] is False and v["observe"] is True
    assert ams.load_map(SERIAL).calibrated is False


def test_calibration_restore_failure_fails_the_job(stubs):
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 1, "HT-A": 128}, consistent=True, restored=False,
                                 problems=["A2: restore not confirmed by the printer"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "failed" and "A2: restore not confirmed by the printer" in v["problems"]
    assert v["calibrated"] is False and v["observe"] is True
    saved = ams.load_map(SERIAL)
    assert saved.calibrated is False and saved.observe is True and set(saved.slots) == set(CONFIRMED)


def test_restore_flag_not_problem_text_decides(stubs):
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 1, "HT-A": 128}, consistent=True, restored=True,
                                 problems=["could not delete /cache/x: restore of nothing"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "done" and v["calibrated"] is True


def test_no_confirmed_slot_fails(stubs, calls):
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                                     calibrated=True, observe=False))
    stubs["st"] = SlotTestResult(confirmed={}, needs_developer_mode=True,
                                 problems=["needs_developer_mode: turn on Developer Mode", "A1: not confirmed"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "failed" and v["problems"][0].startswith("needs_developer_mode")
    assert calls["calib"] == []
    assert v["calibrated"] is False and v["observe"] is True           # a failed job leaves no trusted map


def test_unconfirmed_slots_listed_but_calibration_runs(stubs, calls):
    stubs["st"] = SlotTestResult(confirmed={"A1": {"ams_id": 0, "tray_id": 0}},
                                 problems=["A2: not confirmed (no report showed its test colour within 10 s)"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "done" and v["calibrated"] is True
    assert v["problems"] == ["A2: not confirmed (no report showed its test colour within 10 s)"]
    assert set(calls["calib"][0]) == {"A1"}


def test_slot_test_crash_fails_with_reason(stubs, monkeypatch):
    def boom(manager, serial, on_step, should_stop=None):
        raise RuntimeError("kaput")
    monkeypatch.setattr(slottest, "run", boom)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    # the exception goes to the log; the owner reads a sentence and the reason
    assert v["state"] == "failed" and v["reason"] == "kit_error" and not any("kaput" in p for p in v["problems"])


def test_printer_starts_job_during_slot_test(stubs, monkeypatch):
    def busy(manager, serial, on_step, should_stop=None):
        raise PrinterBusy("RUNNING")
    monkeypatch.setattr(slottest, "run", busy)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["state"] == "failed" and v["reason"] == "busy" and v["problems"][0].startswith("The printer started a job")


# ---------------------------------------------------------------- refusals

def test_refused_while_busy_offline_cert_changed_or_unknown(stubs, calls):
    with pytest.raises(PrinterBusy):
        mapping.Mapper(FakeManager(gcode_state="RUNNING")).start(SERIAL)
    with pytest.raises(PrinterOffline):
        mapping.Mapper(FakeManager(state="offline")).start(SERIAL)
    with pytest.raises(mapping.CertChanged):
        mapping.Mapper(FakeManager(state="cert_changed")).start(SERIAL)
    with pytest.raises(UnknownPrinter):
        mapping.Mapper(FakeManager()).start("NOPE")
    assert calls["slottest"] == 0
    assert mapping.Mapper(FakeManager()).view(SERIAL)["state"] == "none"


def test_one_job_per_printer_and_progress_visible(stubs):
    gate = threading.Event()
    stubs["gate"] = gate
    m = mapping.Mapper(FakeManager())
    job_id = m.start(SERIAL)
    assert isinstance(job_id, str) and job_id
    v = m.view(SERIAL)
    assert v["state"] == "running" and v["step"]
    with pytest.raises(mapping.AlreadyRunning):
        m.start(SERIAL)
    with pytest.raises(mapping.AlreadyRunning):
        m.run(SERIAL)
    gate.set()
    v = wait_done(m)
    assert v["state"] == "done" and v["calibrated"] is True
    assert m.start(SERIAL)                     # a finished job does not block the next
    wait_done(m)                               # (the printer is held per process: do not leak the job)


def test_a_start_right_after_done_waits_for_the_printer_to_be_given_back(stubs, monkeypatch):
    # the job shows "done" a moment before its worker gives the printer back; a start in that moment is not refused
    real = mapping._give_back

    def slow(serial, plock):
        time.sleep(0.3)
        real(serial, plock)
    monkeypatch.setattr(mapping, "_give_back", slow)
    m = mapping.Mapper(FakeManager())
    m.start(SERIAL)
    assert wait_done(m)["state"] == "done"
    assert m.start(SERIAL)
    wait_done(m)
    assert m._jobs[SERIAL].released.wait(5)    # the second job gives the printer back (its sleep is 0.3 s)


def test_last_result_survives_a_restart(stubs):
    mapping.Mapper(FakeManager()).run(SERIAL)
    v = mapping.Mapper(FakeManager()).view(SERIAL)  # a new process
    assert v["state"] == "done" and v["calibrated"] is True and len(v["slots"]) == 3


def test_failed_result_survives_a_restart(stubs):
    stubs["st"] = SlotTestResult(restored=False, problems=["A1: not restored (printer_offline)"])
    mapping.Mapper(FakeManager()).run(SERIAL)
    v = mapping.Mapper(FakeManager()).view(SERIAL)
    assert v["state"] == "failed" and v["problems"] == ["A1: not restored (printer_offline)"]


def test_interrupted_job_is_not_running_forever(stubs):
    f = config.paths().state / "printers" / SERIAL / mapping.STATUS_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"job_id": "x", "state": "running", "step": "Testing slot A1 (1/3)", "problems": []}),
                 encoding="utf-8")
    v = mapping.Mapper(FakeManager()).view(SERIAL)
    assert v["state"] == "failed" and any("interrupted" in p for p in v["problems"])


@pytest.mark.skipif(mapping.fcntl is None, reason="cross-process lock needs fcntl (Linux)")
def test_job_in_another_process_blocks_and_shows_running(stubs):
    fcntl = mapping.fcntl
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "x", "state": "running", "step": "Testing slot A1",
                                                     "problems": []}), encoding="utf-8")
    with open(d / mapping.LOCK_FILE, "a") as other:          # another process's job (own open file description)
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        m = mapping.Mapper(FakeManager())
        with pytest.raises(mapping.AlreadyRunning):
            m.start(SERIAL)
        assert m.view(SERIAL)["state"] == "running"
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)
    assert mapping.Mapper(FakeManager()).view(SERIAL)["state"] == "failed"   # its holder is gone


def test_in_progress_sees_this_process_job(stubs):
    gate = threading.Event()
    stubs["gate"] = gate
    m = mapping.Mapper(FakeManager())
    assert m.in_progress(SERIAL) is False
    m.start(SERIAL)
    assert m.in_progress(SERIAL) is True
    gate.set()
    wait_done(m)
    # the job says it's done a moment before it gives the lock back: wait for that moment itself, not a clock (FLAKY
    # once in a crowd of three suites, where a status write before the give-back took longer than a fixed 5 s)
    assert m._jobs[SERIAL].released.wait(30)
    assert m.in_progress(SERIAL) is False


@pytest.mark.skipif(mapping.fcntl is None, reason="cross-process lock needs fcntl (Linux)")
def test_in_progress_sees_another_process_job(stubs):
    fcntl = mapping.fcntl
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    m = mapping.Mapper(FakeManager())
    with open(d / mapping.LOCK_FILE, "a") as other:          # `filament-kit printer map` in another process
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert m.in_progress(SERIAL) is True
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)
    assert m.in_progress(SERIAL) is False


def test_corrupt_status_file_reads_as_none(stubs):
    f = config.paths().state / "printers" / SERIAL / mapping.STATUS_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{nope", encoding="utf-8")
    assert mapping.Mapper(FakeManager()).view(SERIAL)["state"] == "none"


# ---------------------------------------------------------------- Manager(only=...) for the CLI

def test_manager_only_connects_the_given_printer(monkeypatch):
    registry.upsert(registry.Printer("OTHER1", "Other", "C12", "10.0.0.6", CODE, True))
    made = []

    def factory(cid):
        c = FakeClient(cid)
        made.append(cid)
        return c
    m = Manager(client_factory=factory, only={SERIAL})
    m.sync()
    try:
        assert len(made) == 1 and SERIAL in made[0]
        assert m.state("OTHER1") not in ("connected", "needs_developer_mode")
    finally:
        m.stop()


# ---------------------------------------------------------------- CLI

def test_cli_map_prints_each_step(stubs, capsys):
    fm = FakeManager()
    assert cli.main(["printer", "map", SERIAL], manager_factory=lambda serial: fm) == 0
    out = capsys.readouterr().out
    assert "Reading the AMS slots" in out and "Testing slot A1 (1/3)" in out and "Slot test finished" in out
    assert "calibrat" in out.lower() and "A1" in out
    assert fm.synced == 1 and fm.stopped == 1
    assert ams.load_map(SERIAL).calibrated
    assert CODE not in out


def test_cli_map_reports_observe_mode(stubs, capsys):
    stubs["calib"] = CalibResult(consistent=False, problems=["printer refused the calibration job"])
    assert cli.main(["printer", "map", SERIAL], manager_factory=lambda s: FakeManager()) == 1
    out = capsys.readouterr().out
    assert "printer refused the calibration job" in out and "only logged" in out


@pytest.mark.parametrize("fm,text", [(FakeManager(gcode_state="RUNNING"), "busy"),
                                     (FakeManager(state="offline"), "offline"),
                                     (FakeManager(state="cert_changed"), "certificate")])
def test_cli_map_refusals(stubs, capsys, fm, text):
    assert cli.main(["printer", "map", SERIAL], manager_factory=lambda s: fm) == 1
    assert text in capsys.readouterr().err.lower()
    assert fm.stopped == 1


def test_cli_map_unknown_printer(stubs, capsys):
    made = []
    assert cli.main(["printer", "map", "NOPE"], manager_factory=lambda s: made.append(s)) == 1
    assert "no printer" in capsys.readouterr().err.lower() and made == []


def test_cli_unpin_with_the_access_code_clears_the_pin(monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(secret_input, "ask", lambda prompt: asked.append(prompt) or "24681357")
    assert registry.load()[SERIAL].cert_fp
    assert cli.main(["printer", "unpin", SERIAL]) == 0
    assert asked == ["Access Code: "]
    assert registry.load()[SERIAL].cert_fp == ""
    assert registry.load()[SERIAL].access_code == "24681357"
    out = capsys.readouterr().out
    assert "Office H2D" in out and "24681357" not in out


@pytest.mark.parametrize("typed", ["", "  ", "bad code!"])
def test_cli_unpin_without_a_usable_access_code_changes_nothing(monkeypatch, capsys, typed):
    monkeypatch.setattr(secret_input, "ask", lambda prompt: typed)
    assert cli.main(["printer", "unpin", SERIAL]) == 1
    assert registry.load()[SERIAL].cert_fp == "ab" * 32 and registry.load()[SERIAL].access_code == CODE
    assert capsys.readouterr().err


def test_cli_unpin_unknown_printer(monkeypatch, capsys):
    monkeypatch.setattr(secret_input, "ask", lambda prompt: pytest.fail("asked for a code for no printer"))
    assert cli.main(["printer", "unpin", "NOPE"]) == 1
    assert "no printer" in capsys.readouterr().err.lower()


def test_cert_changed_hint_points_to_adding_the_printer_again_not_unpin():
    assert "unpin" not in cli.NOT_CONNECTED["cert_changed"]
    assert "Access Code" in cli.NOT_CONNECTED["cert_changed"]


# ---------------------------------------------------------------- numbering scheme (P3)

def test_scheme_saved_and_skipped_slots_numbered_by_it(stubs):
    """The calibration proved shift8: it is saved with the map, and a confirmed slot the job skipped (empty) gets
    its shift8 number, not a legacy guess."""
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 1}, consistent=True, scheme="shift8")
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    saved = ams.load_map(SERIAL)
    assert saved.calibrated and saved.scheme == "shift8"
    assert saved.slots["HT-A"]["global_id"] == 32768 and saved.slots["A2"]["global_id"] == 1
    assert v["scheme"] == "shift8" and v["suspect"] is False


def test_remap_clears_suspect_learned_and_streak(stubs):
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}, calibrated=True,
                                     observe=True, scheme="legacy", learned={"77": "A1"}, mismatch_streak=2,
                                     suspect=True))
    stubs["calib"] = CalibResult(decoding={"A1": 0, "A2": 1, "HT-A": 32768}, consistent=True, scheme="shift8")
    mapping.Mapper(FakeManager()).run(SERIAL)
    m = ams.load_map(SERIAL)
    assert (m.scheme, m.learned, m.mismatch_streak, m.suspect, m.observe) == ("shift8", {}, 0, False, False)


def test_inconsistent_calibration_saves_no_scheme(stubs):
    stubs["calib"] = CalibResult(decoding={"A1": 0}, consistent=False, problems=["x"])
    mapping.Mapper(FakeManager()).run(SERIAL)
    assert ams.load_map(SERIAL).scheme is None


def test_suspect_remap_step_says_why(stubs, monkeypatch):
    """An automatic job on a suspect (not stale) map starts with the suspect step; on a stale map the layout step."""
    first = []
    real = mapping._save_status

    def save_status(serial, job):
        if not first or first[-1][0] != job.id:
            first.append((job.id, job.step))
        real(serial, job)
    monkeypatch.setattr(mapping, "_save_status", save_status)
    m = ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}, calibrated=True, suspect=True)
    ams.save_map(SERIAL, m)
    mp = mapping.Mapper(FakeManager())
    mp.start(SERIAL, auto=True)
    wait_done(mp)
    m.stale = True
    ams.save_map(SERIAL, m)
    mp.start(SERIAL, auto=True)
    wait_done(mp)
    assert [step for _, step in first] == [mapping.REMAP_SUSPECT_STEP, mapping.REMAP_STEP]


# ---------------------------------------------------------------- outcome and reason (G4)

def test_a_confirmed_map_reads_confirmed_with_no_next_step(stubs):
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["outcome"] == "confirmed" and v["reason"] == "none" and v["next_step"] == ""
    assert v["outcome_text"] == mapping.OUTCOME_TEXT["confirmed"]


def test_nothing_mapped_yet():
    v = mapping.Mapper(FakeManager()).view(SERIAL)
    assert v["outcome"] == "none" and v["next_step"] == "Map the slots."


def test_a_busy_printer_is_a_sentence_and_a_reason(stubs, monkeypatch):
    def busy(*a, **k):
        raise PrinterBusy("RUNNING")
    monkeypatch.setattr(slottest, "run", busy)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["outcome"] == "failed" and v["reason"] == "busy" and v["next_step"] == mapping.NEXT_STEP["busy"]
    assert not any(p.startswith("printer_busy") for p in v["problems"])


def test_developer_mode_is_carried_from_the_slot_test(stubs):
    stubs["st"] = SlotTestResult(confirmed={}, needs_developer_mode=True,
                                 problems=["needs_developer_mode: the printer refused the write to A1"])
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["outcome"] == "failed" and v["reason"] == "developer_mode" and "Developer Mode" in v["next_step"]


@pytest.mark.parametrize("calib,reason", [
    (CalibResult(consistent=False, problems=["printer refused the calibration job"], report_wanted="job_refused"), "job_refused"),
    (CalibResult(consistent=False, problems=["the printer reported no slot mapping"], report_wanted="no_mapping"), "no_mapping"),
    (CalibResult(consistent=False, problems=["fit no numbering"], report_wanted="no_scheme"), "numbers_unfit"),
    (CalibResult(consistent=False, problems=[calib3mf.SAY["printer_busy"]], reason="busy"), "busy"),
    (CalibResult(consistent=True, restored=False, problems=[calib3mf.LEFT_LOADED]), "restore_failed"),
])
def test_an_unconfirmed_calibration_says_why(stubs, calib, reason):
    stubs["calib"] = calib
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["reason"] == reason and v["next_step"] == mapping.NEXT_STEP[reason]
    assert v["outcome"] in ("not_confirmed", "failed")


def test_an_unsettled_scheme_is_partial(stubs):
    dec = {"A1": 0, "A2": 1, "HT-A": 128}
    stubs["calib"] = CalibResult(decoding=dec, consistent=True, sent=dict(dec), scheme_unsettled=True)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["outcome"] == "partial" and v["reason"] == "none" and "second AMS unit" in v["next_step"]


def test_stale_and_suspect_come_before_how_good_the_map_is(stubs):
    m = mapping.Mapper(FakeManager())
    m.run(SERIAL)
    saved = ams.load_map(SERIAL)
    saved.stale = True
    ams.save_map(SERIAL, saved)
    assert m.view(SERIAL)["outcome"] == "stale"
    saved.suspect = True
    ams.save_map(SERIAL, saved)
    assert m.view(SERIAL)["outcome"] == "suspect"


def test_a_kit_error_names_no_exception(stubs, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(calib3mf, "run", boom)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["reason"] == "kit_error" and not any("secret detail" in p or "RuntimeError" in p for p in v["problems"])


def test_the_reason_survives_a_restart_and_older_files_read_none(stubs):
    stubs["calib"] = CalibResult(consistent=False, problems=["x"], report_wanted="job_refused")
    mapping.Mapper(FakeManager()).run(SERIAL)
    assert mapping.Mapper(FakeManager()).view(SERIAL)["reason"] == "job_refused"     # from the status file
    f = mapping._dir(SERIAL) / mapping.STATUS_FILE
    d = json.loads(f.read_text())
    d.pop("reason")
    f.write_text(json.dumps(d))
    assert mapping.Mapper(FakeManager()).view(SERIAL)["reason"] == "none"


def test_every_reason_has_its_next_step_and_every_outcome_its_text():
    assert set(mapping.NEXT_STEP) == set(mapping.REASONS) - {"none"}
    assert set(mapping.OUTCOME_TEXT) == set(mapping.OUTCOMES)


@pytest.mark.parametrize("abort,reason", [(slottest.OFFLINE, "offline"),
                                          ("The printer started a job (RUNNING); the slot test stopped.", "busy")])
def test_a_slot_test_stopped_midway_carries_its_reason(stubs, abort, reason):
    """R60: offline or busy during the test, not only before it."""
    stubs["st"] = SlotTestResult(problems=[abort, "A1: not confirmed (x)"], reason=reason)
    v = mapping.Mapper(FakeManager()).run(SERIAL)
    assert v["outcome"] == "failed" and v["reason"] == reason and v["next_step"] == mapping.NEXT_STEP[reason]
    assert not any(p.startswith(("printer_offline", "printer_busy")) for p in v["problems"])


def test_a_stale_map_says_map_again_whatever_stopped_an_earlier_job(stubs):
    stubs["calib"] = CalibResult(consistent=False, problems=["x"], report_wanted="no_mapping")
    m = mapping.Mapper(FakeManager())
    m.run(SERIAL)
    saved = ams.load_map(SERIAL)
    saved.stale = True
    ams.save_map(SERIAL, saved)
    v = m.view(SERIAL)
    assert v["outcome"] == "stale" and v["reason"] == "none" and v["next_step"] == "Map the slots."


def _failed_job(finished):
    f = config.paths().state / "printers" / SERIAL / mapping.STATUS_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"job_id": "x", "state": "failed", "step": "", "reason": "offline", "finished": finished,
                             "problems": ["printer_offline: the printer went offline; nothing was changed"]}),
                 encoding="utf-8")


def _owner_map(at):
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}},
                                     by_user={"A1": {"by": "user", "at": at}}))


def test_a_manual_map_after_a_failed_job_is_the_current_map():
    """S1 (app walk 2026-11-09 16:45): the owner mapped by loading filament after a failed job; the view no longer
    says the last mapping failed, and the old failure stays readable as old problems."""
    _failed_job(time.mktime((2026, 11, 9, 13, 0, 0, 0, 0, -1)))
    _owner_map(time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.mktime((2026, 11, 9, 13, 5, 0, 0, 0, -1)))))
    v = mapping.Mapper(FakeManager()).view(SERIAL)
    assert v["outcome"] == "not_confirmed" and v["reason"] == "none"
    assert v["next_step"] == "Map by loading filament for any position not confirmed yet, or map the slots again."
    assert v["state"] == "failed" and v["problems_old"] is True and v["problems"]       # the job's own record is kept
    assert [s["label"] for s in v["slots"]] == ["A1"]


def test_a_failed_job_after_the_manual_map_still_reads_failed():
    _owner_map(time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.mktime((2026, 11, 9, 13, 0, 0, 0, 0, -1)))))
    _failed_job(time.mktime((2026, 11, 9, 13, 5, 0, 0, 0, -1)))
    v = mapping.Mapper(FakeManager()).view(SERIAL)
    assert v["outcome"] == "failed" and v["reason"] == "offline"
    assert v["next_step"] == "Map again when the printer is on and online."


def test_owner_since_is_the_newest_owner_entry_and_ignores_bad_times():
    m = ams.SlotMap(by_user={"A1": {"at": "2026-11-09T13:00:00-0500"}, "A2": {"at": "2026-11-09T14:00:00-0500"},
                             "A3": {"at": "garbage"}, "A4": {}})
    assert mapping.owner_since(m) == 1794250800.0                     # 19:00 UTC
    assert mapping.owner_since(ams.SlotMap()) is None
    assert mapping.superseded({"state": "failed", "finished": None}, m) is True
    assert mapping.superseded({"state": "done", "finished": 0}, m) is False


class AmsManager(FakeManager):
    """The printer reports one AMS with four trays (A1..A4)."""

    def wait_report(self, serial, predicate, timeout):
        return {"gcode_state": "IDLE", "ams": {"ams": [{"id": "0", "tray": [
            {"id": str(i), "tray_type": "PLA", "tray_color": "FF0000FF"} for i in range(4)]}]}}


def test_after_a_manual_map_the_next_step_names_what_is_left():
    """The orchestrator's 16:53 item: not "Map the slots." but the positions the owner has not confirmed."""
    _owner_map(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    v = mapping.Mapper(AmsManager()).view(SERIAL)
    assert v["outcome"] == "not_confirmed"
    assert v["next_step"].startswith("3 positions not yet confirmed (A2, A3, A4): map by loading filament, or map "
                                     "the slots again.")


def test_owner_step_wording():
    m = ams.SlotMap(by_user={"A1": {}, "A2": {}})
    assert mapping.owner_step(m, ["A1", "A2", "A3"]) == ("1 position not yet confirmed (A3): map by loading filament, "
                                                         "or map the slots again.")
    assert mapping.owner_step(m, ["A1", "A2"]).startswith("Every position is confirmed by you")
    assert mapping.owner_step(m, None).startswith("Map by loading filament for any position")


def test_a_map_without_owner_entries_keeps_map_the_slots():
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}))
    v = mapping.Mapper(AmsManager()).view(SERIAL)
    assert v["outcome"] == "not_confirmed" and v["next_step"] == "Map the slots."
