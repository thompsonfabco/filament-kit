"""Calibration 3MF and job: a gcode-only, no-motion job whose reported `mapping` decodes the printer's slot ids.

The printer is a fake Manager (the three Task 3 calls plus `state`) that replays reports, and the fake FTPS server;
nothing touches real hardware."""
import copy
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile

import pytest

from fakes.fake_certs import Leaf
from fakes.fake_ftps import FakeFtps
from filament_kit.bridge import ams, calib3mf, ftps, registry, status
from filament_kit.bridge.registry import Printer

CODE = "13572468"
SERIAL = "0948AB123456789"
FILE = f"fk-calib-{SERIAL}.gcode.3mf"
FORBIDDEN = re.compile(r"^\s*(G0|G1|G28|M104|M109|M140|M190|T\d*)\b", re.I)


def tray(i, t="PLA", color="FF0000FF", idx="GFA00"):
    return {"id": str(i), "tray_type": t, "tray_color": color, "tray_info_idx": idx,
            "nozzle_temp_min": "190", "nozzle_temp_max": "230"}


def base_report():
    return {
        "gcode_state": "IDLE", "subtask_name": "benchy", "task_id": "111", "mc_percent": 100,
        "ams": {"tray_now": "255", "ams": [
            {"id": "0", "tray": [tray(0), tray(1, "PETG", "00FF00FF", "GFG00"), {"id": "2"},
                                 tray(3, "PLA", "0000FFFF", "GFA01")]},
            {"id": "128", "tray": [tray(0, "PA-CF", "222222FF", "GFN03")]},
        ]},
        "vt_tray": {"id": "254", "tray_type": "TPU", "tray_color": "FFFFFFFF", "tray_info_idx": "GFU01",
                    "nozzle_temp_min": "200", "nozzle_temp_max": "240"},
    }


def slotmap_for(report):
    m = ams.SlotMap()
    for u in ams.units(report):
        for s in u.slots:
            m.slots[s.label] = {"ams_id": u.ams_id, "tray_id": s.tray_id, "global_id": s.global_id}
    return m


class FakeManager:
    """`behaviour`: echo (mapping = ams_mapping), refuse, silent (no reply, nothing happens), remap (the printer
    reports its own ids), clobber (the job rewrites slot A1), stuck (never finishes)."""

    def __init__(self, ftp_root, behaviour="echo", report=None):
        self.ftp_root = ftp_root
        self.behaviour = behaviour
        self.report = report or base_report()
        self.queue: list[dict] = []
        self.published: list[dict] = []
        self.set_slots: list[tuple] = []
        self.conn_state = "connected"
        self.file_at_start = None
        self.raise_on_wait: set[int] = set()     # 1-based wait_report calls that raise (connection lost)
        self.raise_on_publish = False
        self.waits = 0

    def state(self, serial):
        assert serial == SERIAL
        return self.conn_state

    def wait_report(self, serial, predicate, timeout):
        assert serial == SERIAL and 0 < timeout <= 120
        self.waits += 1
        if self.waits in self.raise_on_wait:
            while self.queue:                   # the reports so far arrived, then the connection dropped
                self.report = status.merge(self.report, self.queue.pop(0))
            raise ConnectionError("connection lost")
        if predicate(self.report):
            return self.report
        while self.queue:
            self.report = status.merge(self.report, self.queue.pop(0))
            if predicate(self.report):
                return self.report
        return None

    def publish(self, serial, payload):
        assert serial == SERIAL
        self.published.append(copy.deepcopy(payload))
        if self.raise_on_publish:
            raise ConnectionError("connection lost")
        pr = payload["print"]
        if pr["command"] == "stop":
            self.queue.append({"gcode_state": "FAILED"})
            return {"command": "stop", "result": "success"}
        assert pr["command"] == "project_file"
        f = self.ftp_root / "cache" / FILE
        self.file_at_start = f.read_bytes() if f.exists() else None
        if self.behaviour == "refuse":
            return {"command": "project_file", "result": "fail", "reason": "file not supported"}
        if self.behaviour == "silent":
            return None
        mapping = list(pr["ams_mapping"])
        if self.behaviour == "remap":
            mapping = [m if m < 128 else 0x8000 + m for m in mapping]
        name = pr["subtask_name"]
        self.queue.append({"gcode_state": "PREPARE", "subtask_name": name, "task_id": "222"})
        running = {"gcode_state": "RUNNING", "mapping": mapping}
        if self.behaviour == "clobber":
            rep = copy.deepcopy(self.report["ams"])
            rep["ams"][0]["tray"][0] = tray(0, "PLA", "123456FF", "")
            running["ams"] = rep
        self.queue.append(running)
        if self.behaviour != "stuck":
            self.queue.append({"gcode_state": "FINISH", "mc_percent": 100})
        return {"command": "project_file", "result": "success"}

    def set_slot(self, serial, ams_id, tray_id, setting):
        assert serial == SERIAL
        self.set_slots.append((ams_id, tray_id, dict(setting)))
        rep = copy.deepcopy(self.report["ams"])
        for u in rep["ams"]:
            if int(u["id"]) == ams_id:
                for t in u["tray"]:
                    if int(t["id"]) == tray_id:
                        t.update({k: (str(v) if k.startswith("nozzle") else v) for k, v in setting.items()})
        self.queue.append({"ams": rep})
        return {"command": "ams_filament_setting", "result": "success"}


@pytest.fixture
def leaf():
    return Leaf(SERIAL)


@pytest.fixture
def printer():
    p = Printer(serial=SERIAL, name="H2D", model="H2D", ip="127.0.0.1", access_code=CODE, configured=True)
    registry.upsert(p)
    return p


@pytest.fixture
def fake_ftp(leaf, tmp_path, monkeypatch):
    f = FakeFtps(leaf, tmp_path / "sd", CODE)
    monkeypatch.setattr(ftps, "PORT", f.port)
    yield f
    f.close()


# ---------------------------------------------------------------- the 3MF

def test_build_is_a_gcode_only_bambu_3mf():
    labels = ["A1", "A2", "A4", "HT-A", "Ext"]
    z = zipfile.ZipFile(io.BytesIO(calib3mf.build(labels)))
    names = set(z.namelist())
    for n in ("[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model", "Metadata/plate_1.gcode",
              "Metadata/plate_1.gcode.md5", "Metadata/slice_info.config", "Metadata/model_settings.config",
              "Metadata/project_settings.config"):
        assert n in names, n
    for n in ("[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model", "Metadata/slice_info.config",
              "Metadata/model_settings.config"):
        ET.fromstring(z.read(n))                                            # well-formed XML
    json.loads(z.read("Metadata/project_settings.config"))

    gcode = z.read("Metadata/plate_1.gcode").decode()
    lines = [l.strip() for l in gcode.splitlines() if l.strip()]
    assert not [l for l in lines if FORBIDDEN.match(l)]
    assert all(l.startswith(";") or l == "M400" for l in lines)
    assert "M400" in lines
    assert z.read("Metadata/plate_1.gcode.md5").decode().strip().lower() == \
        hashlib.md5(gcode.encode()).hexdigest()

    fils = ET.fromstring(z.read("Metadata/slice_info.config")).findall(".//filament")
    assert [f.get("id") for f in fils] == ["1", "2", "3", "4", "5"]
    for f in fils:
        assert (f.get("tray_info_idx"), f.get("type"), f.get("used_g"), f.get("used_m")) == ("", "PLA", "0", "0")
        assert re.fullmatch(r"#[0-9A-F]{6}", f.get("color"))
    assert len({f.get("color") for f in fils}) == 5


def test_build_needs_slots():
    with pytest.raises(ValueError):
        calib3mf.build([])


def test_payload_flags():
    p = calib3mf.payload(SERIAL, [0, 1, 128])["print"]
    assert p["command"] == "project_file" and p["param"] == "Metadata/plate_1.gcode"
    assert p["url"] == f"ftp:///cache/{FILE}"
    assert p["use_ams"] is True and p["ams_mapping"] == [0, 1, 128]
    for k in ("bed_levelling", "flow_cali", "vibration_cali", "layer_inspect", "timelapse"):
        assert p[k] is False, k
    assert p["subtask_name"] == f"fk-calib-{SERIAL}"


# ---------------------------------------------------------------- the job

def test_echoing_printer_is_consistent(fake_ftp, printer, tmp_path):
    m = FakeManager(fake_ftp.root)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True, r.problems
    assert r.problems == []
    # A3 is empty: not part of the job
    assert r.decoding == {"A1": 0, "A2": 1, "A4": 3, "HT-A": 128, "Ext": 254}
    assert r.skipped == ["A3"]
    pr = m.published[0]["print"]
    assert pr["ams_mapping"] == [0, 1, 3, 128, 254]
    assert zipfile.ZipFile(io.BytesIO(m.file_at_start)).namelist()             # uploaded before the job
    assert not (fake_ftp.root / "cache" / FILE).exists()                       # deleted afterwards
    assert r.tray_now == ["255"]
    assert m.set_slots == []                                                    # nothing changed, nothing to restore


def test_refused_job(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "refuse")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False
    assert "printer refused the calibration job" in r.problems
    assert r.decoding == {}
    assert m.file_at_start is not None
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_job_never_starts(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "silent")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False and r.decoding == {}
    assert any("did not start" in p for p in r.problems)
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_job_never_ends_is_stopped(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "stuck")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False
    assert any("did not finish" in p for p in r.problems)
    assert m.published[-1]["print"]["command"] == "stop"
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_printer_reports_other_ids(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "remap")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False
    assert r.decoding == {"A1": 0, "A2": 1, "A4": 3, "HT-A": 0x8000 + 128, "Ext": 0x8000 + 254}
    assert any("HT-A" in p for p in r.problems)


def test_changed_slot_is_restored_and_verified(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True, r.problems
    assert m.set_slots == [(0, 0, {"tray_info_idx": "GFA00", "tray_color": "FF0000FF", "tray_type": "PLA",
                                   "nozzle_temp_min": 190, "nozzle_temp_max": 230})]
    t = m.report["ams"]["ams"][0]["tray"][0]
    assert (t["tray_color"], t["tray_info_idx"]) == ("FF0000FF", "GFA00")
    assert r.problems == []
    assert r.restored is True


def test_restore_not_confirmed(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    m.set_slot = lambda *a: (m.set_slots.append(a), {"result": "success"})[1]     # accepted, never applied
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert m.set_slots
    assert any("A1" in p and "restore" in p for p in r.problems)
    assert r.restored is False


def test_busy_printer_untouched(fake_ftp, printer):
    rep = base_report()
    rep["gcode_state"] = "RUNNING"
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False and r.problems == ["printer_busy"]
    assert m.published == [] and fake_ftp.commands == []


def test_offline_printer_untouched(fake_ftp, printer):
    m = FakeManager(fake_ftp.root)
    m.conn_state = "offline"
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.problems == ["printer_offline"] and m.published == [] and fake_ftp.commands == []


def test_ftps_leaf_mismatch_is_cert_changed(fake_ftp, printer):
    registry.pin(SERIAL, "cd" * 32)
    m = FakeManager(fake_ftp.root)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.cert_changed is True and r.consistent is False
    assert r.problems == ["cert_changed"]
    assert m.published == []
    assert "PASS" not in fake_ftp.commands


# ---------------------------------------------------------------- cleanup always happens (fix round 1)

def test_upload_dropped_midway_file_still_deleted(fake_ftp, printer):
    fake_ftp.drop_stor = True
    m = FakeManager(fake_ftp.root)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False
    assert any("cannot upload" in p for p in r.problems)
    assert m.published == []
    assert "DELE" in fake_ftp.commands                                         # a delete was attempted
    assert not (fake_ftp.root / "cache" / FILE).exists()                       # the partial file is gone


def test_delete_crash_does_not_skip_restore(fake_ftp, printer, monkeypatch):
    def boom(self, path):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(ftps.Client, "delete", boom)
    m = FakeManager(fake_ftp.root, "clobber")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert any("could not delete" in p for p in r.problems)
    assert [s[:2] for s in m.set_slots] == [(0, 0)]                            # restored anyway
    assert not any("restore" in p for p in r.problems)


def test_restore_crash_is_a_problem(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    def boom(*a):
        raise RuntimeError("unexpected")
    m.set_slot = boom
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert any("A1" in p and "restore" in p for p in r.problems)
    assert r.restored is False
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_publish_raises(fake_ftp, printer):
    m = FakeManager(fake_ftp.root)
    m.raise_on_publish = True
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False
    assert any("cannot send the calibration job" in p for p in r.problems)
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_wait_report_raises_during_job(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    m.raise_on_wait = {2}                                   # 1 = snapshot, 2 = watching the job
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))      # must not raise
    assert r.consistent is False
    assert any("lost" in p for p in r.problems)
    assert not (fake_ftp.root / "cache" / FILE).exists()
    assert [s[:2] for s in m.set_slots] == [(0, 0)]                            # still restored


def test_wait_report_raises_everywhere_after_snapshot(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    m.raise_on_wait = set(range(2, 20))
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))      # must not raise
    assert r.consistent is False
    assert not (fake_ftp.root / "cache" / FILE).exists()
    assert any("restore not confirmed" in p for p in r.problems)
    assert r.restored is False


def test_restore_refused_is_not_restored(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    m.set_slot = lambda *a: (m.set_slots.append(a), {"result": "fail", "reason": "nope"})[1]
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.restored is False and any("refused to restore" in p for p in r.problems)


def test_nothing_changed_counts_as_restored(fake_ftp, printer):
    m = FakeManager(fake_ftp.root)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.restored is True and m.set_slots == []


# ---------------------------------------------------------------- I3: heating / filament-load watchdog

class WatchManager(FakeManager):
    """The job's RUNNING report carries `extra` (a heater target, a filament load ...); it never ends by itself
    unless `ends` is true."""

    def __init__(self, ftp_root, extra, ends=False, after=None):
        super().__init__(ftp_root, "stuck")
        self.extra, self.ends, self.after = extra, ends, after

    def publish(self, serial, payload):
        reply = super().publish(serial, payload)
        if payload["print"]["command"] == "project_file":
            self.queue[-1].update(copy.deepcopy(self.extra))
            if self.ends:
                self.queue.append({"gcode_state": "FINISH", "mc_percent": 100, **(self.after or {})})
        return reply


def stopped_before_the_end(m):
    cmds = [p["print"]["command"] for p in m.published]
    return cmds == ["project_file", "stop"]


@pytest.mark.parametrize("extra", [
    {"nozzle_target_temper": 220},
    {"bed_target_temper": 55},
    {"device": {"extruder": {"info": [{"id": 0, "temp": (220 << 16) | 25}]}}},
    {"device": {"bed": {"info": {"temp": (60 << 16) | 24}}}},
])
def test_heating_stops_the_job_at_once(fake_ftp, printer, extra):
    m = WatchManager(fake_ftp.root, extra)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert stopped_before_the_end(m), m.published
    assert r.consistent is False
    assert any("heat" in p for p in r.problems), r.problems
    assert not any("did not finish" in p for p in r.problems)


def test_unchanged_targets_do_not_trip(fake_ftp, printer):
    rep = base_report()
    rep.update({"nozzle_target_temper": 0, "bed_target_temper": 0,
                "device": {"extruder": {"info": [{"id": 0, "temp": 30}]}}})
    m = WatchManager(fake_ftp.root, {"nozzle_target_temper": 0, "device": {"extruder": {"info": [{"id": 0, "temp": 31}]}}},
                     ends=True)
    m.report = rep
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True, r.problems


def test_filament_load_stops_the_job_and_is_not_restored(fake_ftp, printer):
    m = WatchManager(fake_ftp.root, {"ams": {"tray_now": "0"}})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert stopped_before_the_end(m), m.published
    assert any("filament" in p and "load" in p for p in r.problems), r.problems
    assert "printer left a filament loaded in the toolhead" in r.problems
    assert r.restored is False


def test_filament_left_loaded_after_the_job_is_not_restored(fake_ftp, printer):
    m = WatchManager(fake_ftp.root, {}, ends=True, after={"ams": {"tray_now": "1"}})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert "printer left a filament loaded in the toolhead" in r.problems
    assert r.restored is False


def commands(m):
    return [p["print"]["command"] for p in m.published]


def test_job_that_never_started_gets_a_stop_only_when_the_printer_shows_our_job(fake_ftp, printer):
    """R1: the never-started `stop` goes out only while the latest report names our job."""
    rep = base_report()
    rep.update({"gcode_state": "FINISH", "subtask_name": calib3mf.job_name(SERIAL), "task_id": "222"})
    m = FakeManager(fake_ftp.root, "silent", report=rep)       # an earlier calibration's FINISH, ours by name
    calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file", "stop"]


def test_job_that_never_started_on_an_idle_printer_sends_no_stop(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "silent")                   # still shows the owner's last print, "benchy"
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file"]
    assert any("did not start" in p for p in r.problems)


class OtherJobManager(FakeManager):
    """The printer accepts our job, but someone starts their own print (touchscreen / Studio) instead: `other` is
    the report delta that print sends."""

    def __init__(self, ftp_root, other):
        super().__init__(ftp_root, "silent")
        self.other = other

    def publish(self, serial, payload):
        reply = super().publish(serial, payload)
        if payload["print"]["command"] == "project_file":
            self.queue.append(copy.deepcopy(self.other))
            return {"command": "project_file", "result": "success"}
        return reply


THEIRS = {"gcode_state": "PREPARE", "subtask_name": "grandmas-vase", "task_id": "999"}


@pytest.mark.parametrize("extra", [
    {"nozzle_target_temper": 220},
    {"device": {"extruder": {"info": [{"id": 0, "temp": (220 << 16) | 25}]}}},
    {"ams": {"tray_now": "0"}},
    {},
])
def test_another_job_starting_in_the_window_is_never_stopped(fake_ftp, printer, extra):
    """R1: another print that starts (and heats / loads) while we wait for ours is not stopped; the calibration
    is abandoned, our file deleted, the slots restored (R9), and its filament load is not held against us."""
    m = OtherJobManager(fake_ftp.root, {**THEIRS, **extra})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert "stop" not in commands(m), m.published
    assert any(p.startswith("the printer started another job; calibration abandoned") for p in r.problems), \
        r.problems
    assert r.consistent is False
    assert r.restored is True and calib3mf.LEFT_LOADED not in r.problems
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_never_started_while_another_job_runs_sends_no_stop(fake_ftp, printer):
    m = OtherJobManager(fake_ftp.root, {"gcode_state": "RUNNING", "subtask_name": "grandmas-vase",
                                        "task_id": "999"})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file"]
    assert any("another job" in p for p in r.problems)


def test_heating_with_no_job_of_ours_running_is_not_stopped(fake_ftp, printer):
    """R1: the owner preheats from the touchscreen while the printer still shows their last print: the watchdog
    trips, but a `stop` is only ever sent for our own job."""
    m = OtherJobManager(fake_ftp.root, {"nozzle_target_temper": 220})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file"]
    assert any("heat" in p and "nothing was stopped" in p for p in r.problems), r.problems


def test_our_job_heating_is_stopped(fake_ftp, printer):
    m = WatchManager(fake_ftp.root, {"nozzle_target_temper": 220})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file", "stop"]
    assert any("heat" in p and "was stopped" in p for p in r.problems), r.problems


def test_packed_target_dropping_does_not_trip(fake_ftp, printer):
    """Minor: the owner preheated (packed target 200), the firmware zeroes it when our job starts: no trip."""
    rep = base_report()
    rep["device"] = {"extruder": {"info": [{"id": 0, "temp": (200 << 16) | 180}]},
                     "bed": {"info": {"temp": (60 << 16) | 58}}}
    m = WatchManager(fake_ftp.root, {"device": {"extruder": {"info": [{"id": 0, "temp": 175}]},
                                                "bed": {"info": {"temp": 57}}}}, ends=True)
    m.report = rep
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True, r.problems
    assert commands(m) == ["project_file"]


class InterruptManager(WatchManager):
    """Ctrl-C (KeyboardInterrupt, no handlers installed) lands while the job is watched."""

    def wait_report(self, serial, predicate, timeout):
        if self.waits == 1:                        # the watch: the job's reports arrive, then Ctrl-C
            self.waits += 1
            while self.queue:
                self.report = status.merge(self.report, self.queue.pop(0))
            raise KeyboardInterrupt
        return super().wait_report(serial, predicate, timeout)


def test_keyboard_interrupt_in_the_job_stops_our_job_then_restores(fake_ftp, printer):
    m = InterruptManager(fake_ftp.root, {})
    with pytest.raises(KeyboardInterrupt):
        calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file", "stop"]
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_keyboard_interrupt_with_another_job_running_sends_no_stop(fake_ftp, printer):
    m = InterruptManager(fake_ftp.root, {"subtask_name": "grandmas-vase", "task_id": "999"})   # theirs replaced ours
    with pytest.raises(KeyboardInterrupt):
        calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file"]
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_delete_leftover_removes_a_killed_jobs_file(fake_ftp, printer):
    """Minor: kill -9 mid-calibration left our file on the printer; it is deleted best effort."""
    f = fake_ftp.root / "cache" / FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"left over")
    assert calib3mf.delete_leftover(SERIAL) == []
    assert not f.exists()
    assert calib3mf.delete_leftover(SERIAL) == []   # nothing there: no problem, no exception


def test_should_stop_stops_the_job(fake_ftp, printer):
    m = WatchManager(fake_ftp.root, {})
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 3          # once the printer reports our job (PREPARE, fk-calib-<serial>)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report), should_stop=stop)
    assert stopped_before_the_end(m), m.published
    assert any("interrupted" in p and "was stopped" in p for p in r.problems), r.problems


def test_should_stop_before_our_job_shows_sends_no_stop(fake_ftp, printer):
    """R1: stopped while the printer still shows the owner's last print: nothing of ours to stop."""
    m = WatchManager(fake_ftp.root, {})
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2          # the job was sent, its first report not seen yet
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report), should_stop=stop)
    assert commands(m) == ["project_file"]
    assert any("interrupted" in p and "nothing was stopped" in p for p in r.problems), r.problems
