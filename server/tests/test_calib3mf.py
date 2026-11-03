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
    reports its own ids), clobber (the job rewrites slot A1), stuck (never finishes), native (P3: the printer
    numbers slots by its own scheme `native`: from `ams_mapping2` when `use_mapping2`, else by decoding
    `ams_mapping` with that scheme, -1 for a number it cannot place). `final` / `print_error`: how the job ends."""

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
        self.native = "shift8"
        self.use_mapping2 = False
        self.refuse_unknown = False      # native: refuse a job with a number it cannot place
        self.final = "FINISH"
        self.print_error = None

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
        if self.behaviour == "native":
            mapping = self._native(pr)
            if self.refuse_unknown and -1 in mapping:
                return {"command": "project_file", "result": "fail", "reason": "invalid ams mapping"}
        name = pr["subtask_name"]
        self.queue.append({"gcode_state": "PREPARE", "subtask_name": name, "task_id": "222"})
        running = {"gcode_state": "RUNNING", "mapping": mapping}
        if self.behaviour == "clobber":
            rep = copy.deepcopy(self.report["ams"])
            rep["ams"][0]["tray"][0] = tray(0, "PLA", "123456FF", "")
            running["ams"] = rep
        self.queue.append(running)
        if self.behaviour != "stuck":
            end = {"gcode_state": self.final, "mc_percent": 100}
            if self.print_error is not None:
                end["print_error"] = self.print_error
            self.queue.append(end)
        return {"command": "project_file", "result": "success"}

    def _native(self, pr):
        from filament_kit.bridge import hardware
        sch = hardware.load().scheme(self.native)
        exts = {254, 255}
        if self.use_mapping2:
            return [x["ams_id"] if x["ams_id"] in exts else sch.encode(x["ams_id"], x["slot_id"])
                    for x in pr["ams_mapping2"]]
        loaded = {(int(u["id"]), int(t["id"])) for u in self.report["ams"]["ams"] for t in u["tray"]
                  if t.get("tray_type")}
        out = []
        for n in pr["ams_mapping"]:
            out.append(n if n in exts or sch.decode(n) in loaded else -1)
        return out

    def set_slot(self, serial, ams_id, tray_id, setting, kind=None):
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
    # the H2D's first candidate is shift8 (HT-A = 128 << 8); an external holder is sent as its own id
    assert r.decoding == {"A1": 0, "A2": 1, "A4": 3, "HT-A": 32768, "Ext": 254}
    assert r.scheme == "shift8" and r.tried == ["shift8"] and r.attempts == []
    assert r.skipped == ["A3"]
    pr = m.published[0]["print"]
    assert pr["ams_mapping"] == [0, 1, 3, 32768, 254]
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


def a1_changed(r):
    return any(p.startswith("A1: its setting changed on the printer during the calibration") for p in r.problems)


def test_slot_changed_during_the_job_is_left_as_is(fake_ftp, printer):
    """Round 2: the calibration writes no slot, so a slot that changed meanwhile was changed by someone else: it is
    reported and left as is, never written; `restored` means we left nothing changed."""
    m = FakeManager(fake_ftp.root, "clobber")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True, r.problems
    assert m.set_slots == []
    t = m.report["ams"]["ams"][0]["tray"][0]
    assert (t["tray_color"], t["tray_info_idx"]) == ("123456FF", "")
    assert a1_changed(r), r.problems
    assert r.restored is True


def test_slot_check_never_calls_set_slot(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")

    def boom(*a):
        raise AssertionError("the calibration must never write a slot")
    m.set_slot = boom
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert a1_changed(r) and r.restored is True
    assert not (fake_ftp.root / "cache" / FILE).exists()


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


def test_delete_crash_does_not_skip_the_slot_check(fake_ftp, printer, monkeypatch):
    def boom(self, path):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(ftps.Client, "delete", boom)
    m = FakeManager(fake_ftp.root, "clobber")
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert any("could not delete" in p for p in r.problems)
    assert a1_changed(r) and m.set_slots == []


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
    assert a1_changed(r) and m.set_slots == []                                 # checked, never written


def test_wait_report_raises_everywhere_after_snapshot(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "clobber")
    m.raise_on_wait = set(range(2, 20))
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))      # must not raise
    assert r.consistent is False
    assert not (fake_ftp.root / "cache" / FILE).exists()
    assert any("could not check the slots" in p for p in r.problems)
    assert m.set_slots == [] and r.restored is True                            # we changed nothing


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


PREVIOUS_RUNS = [f"fk-calib-{SERIAL}", f"fk-calib-{SERIAL}-0a0b0c"]     # the old fixed name, an earlier run


def earlier_calibration_report(name):
    rep = base_report()
    rep.update({"gcode_state": "FINISH", "subtask_name": name, "task_id": "222"})
    return rep


def test_each_run_sends_its_own_subtask_name(fake_ftp, printer):
    names = []
    for _ in range(2):
        m = FakeManager(fake_ftp.root)
        r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
        sent = m.published[0]["print"]["subtask_name"]
        assert re.fullmatch(rf"fk-calib-{SERIAL}-[0-9a-f]{{6}}", sent) and r.job == sent
        assert m.published[0]["print"]["url"] == f"ftp:///cache/{FILE}"     # the file keeps the fixed name
        names.append(sent)
    assert names[0] != names[1]


@pytest.mark.parametrize("previous", PREVIOUS_RUNS)
def test_never_started_after_an_earlier_calibration_sends_no_stop(fake_ftp, printer, previous):
    """Round 2: the printer still shows an earlier calibration run: not this run, so no stop."""
    m = FakeManager(fake_ftp.root, "silent", report=earlier_calibration_report(previous))
    calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file"]


@pytest.mark.parametrize("previous", PREVIOUS_RUNS)
def test_stale_report_naming_a_previous_run_plus_heating_print_sends_no_stop(fake_ftp, printer, previous):
    """Round 2: someone starts a print whose first PREPARE push still carries the previous calibration run's
    subtask_name, and it heats: that is not this run, so it is never stopped."""
    m = OtherJobManager(fake_ftp.root, {"gcode_state": "PREPARE", "nozzle_target_temper": 220})
    m.report = earlier_calibration_report(previous)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert commands(m) == ["project_file"], m.published
    assert any("heat" in p and "nothing was stopped" in p for p in r.problems), r.problems


def test_another_job_changing_a_slot_gets_no_write(fake_ftp, printer):
    """Round 2: another print starts and changes slot A1 (RFID / Studio): the calibration writes nothing to it."""
    rep = copy.deepcopy(base_report()["ams"])
    rep["ams"][0]["tray"][0] = tray(0, "PETG", "ABCDEFFF", "GFG02")
    m = OtherJobManager(fake_ftp.root, {**THEIRS, "ams": rep})
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert "stop" not in commands(m) and m.set_slots == []
    assert m.report["ams"]["ams"][0]["tray"][0]["tray_color"] == "ABCDEFFF"
    assert a1_changed(r) and r.restored is True and r.other_job is True


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


# ---------------------------------------------------------------- numbering schemes (P3)

def owner_h2d_report():
    """The owner's H2D facts: AMS 0 with trays 0 and 2 loaded (1, 3 empty), AMS HT 128 and 129 loaded."""
    rep = base_report()
    rep["ams"]["ams"] = [
        {"id": "0", "tray": [tray(0), {"id": "1"}, tray(2, "PETG", "00FF00FF", "GFG00"), {"id": "3"}]},
        {"id": "128", "tray": [tray(0, "PA-CF", "222222FF", "GFN03")]},
        {"id": "129", "tray": [tray(0, "PLA", "0000FFFF", "GFA01")]},
    ]
    del rep["vt_tray"]
    return rep


def jobs(m):
    return [p["print"] for p in m.published if p["print"]["command"] == "project_file"]


def test_owner_h2d_shift8_proved_by_one_job(fake_ftp, printer):
    """Observed on the owner's H2D: AMS 0 trays 0 / 2 -> 0 / 2, HT 128 / 129 -> 32768 / 33024 (shift8)."""
    m = FakeManager(fake_ftp.root, "native", report=owner_h2d_report())
    m.use_mapping2 = True
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True and r.problems == [], r.problems
    assert r.scheme == "shift8" and r.tried == ["shift8"]
    assert r.decoding == {"A1": 0, "A3": 2, "HT-A": 32768, "HT-B": 33024}
    (pr,) = jobs(m)
    assert pr["ams_mapping"] == [0, 2, 32768, 33024]
    assert pr["ams_mapping2"] == [{"ams_id": 0, "slot_id": 0}, {"ams_id": 0, "slot_id": 2},
                                  {"ams_id": 128, "slot_id": 0}, {"ams_id": 129, "slot_id": 0}]


def test_legacy_printer_answering_from_ams_mapping2_is_proved_by_the_first_job(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "native", report=owner_h2d_report())
    m.native, m.use_mapping2 = "legacy", True
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True and r.scheme == "legacy" and len(jobs(m)) == 1
    assert r.decoding == {"A1": 0, "A3": 2, "HT-A": 128, "HT-B": 129}


def test_second_job_only_when_no_candidate_fits(fake_ftp, printer):
    """A legacy printer that cannot place the shift8 numbers (-1): the next candidate's job proves legacy."""
    m = FakeManager(fake_ftp.root, "native", report=owner_h2d_report())
    m.native = "legacy"
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True and r.scheme == "legacy", r.problems
    assert r.tried == ["shift8", "legacy"] and len(r.attempts) == 1 and "fit no numbering" in r.attempts[0]
    assert [p["ams_mapping"] for p in jobs(m)] == [[0, 2, 32768, 33024], [0, 2, 128, 129]]
    assert r.decoding == {"A1": 0, "A3": 2, "HT-A": 128, "HT-B": 129}
    assert r.problems == []
    assert not (fake_ftp.root / "cache" / FILE).exists()


def test_refused_numbers_try_the_next_candidate(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "native", report=owner_h2d_report())
    m.native, m.refuse_unknown = "legacy", True
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is True and r.scheme == "legacy" and r.tried == ["shift8", "legacy"]
    assert "printer refused" in r.attempts[0]


def test_candidates_numbering_the_loaded_slots_alike_send_one_job(fake_ftp, printer):
    """Only AMS 0 loaded: shift8 and legacy give the same numbers, so both fit and the model's first is kept;
    a printer that fits neither gets no second job with the same numbers."""
    rep = owner_h2d_report()
    rep["ams"]["ams"] = rep["ams"]["ams"][:1]
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.scheme == "shift8" and len(jobs(m)) == 1

    class Wrong(FakeManager):
        def _native(self, pr):
            return [5 for _ in pr["ams_mapping"]]
    m = Wrong(fake_ftp.root, "native", report=rep)
    r = calib3mf.run(m, SERIAL, slotmap_for(rep))
    assert r.consistent is False and len(jobs(m)) == 1 and r.tried == ["shift8"]


def test_no_candidate_fits_any_job(fake_ftp, printer):
    m = FakeManager(fake_ftp.root, "remap", report=owner_h2d_report())
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is False and r.scheme is None and len(jobs(m)) == 2
    assert any("fit no numbering scheme" in p and "shift8, legacy" in p for p in r.problems)


def test_single_scheme_model_sends_no_ams_mapping2(fake_ftp, printer):
    registry.upsert(Printer(serial=SERIAL, name="P1S", model="C12", ip="127.0.0.1", access_code=CODE,
                            configured=True))
    rep = owner_h2d_report()
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, slotmap_for(rep))
    (pr,) = jobs(m)
    assert "ams_mapping2" not in pr and pr["ams_mapping"] == [0, 2, 128, 129]
    assert r.scheme == "legacy" and r.consistent is True


@pytest.mark.parametrize("model,error,finished", [
    ("H2D", None, True),            # FAILED, no print_error: finished on a model with the rule
    ("H2D", 0, True),
    ("H2D", "0", True),
    ("H2D", 50348044, False),       # a real error: not finished
    ("C12", None, False),           # a model without the rule: FAILED is FAILED
])
def test_failed_as_finish_only_by_the_model_rule(fake_ftp, printer, model, error, finished):
    registry.upsert(Printer(serial=SERIAL, name="X", model=model, ip="127.0.0.1", access_code=CODE, configured=True))
    m = FakeManager(fake_ftp.root)
    m.final, m.print_error = "FAILED", error
    r = calib3mf.run(m, SERIAL, slotmap_for(m.report))
    assert r.consistent is finished, r.problems
    assert r.failed_as_finish is finished
    assert any("ended as FAILED" in p for p in r.problems) is (not finished)
