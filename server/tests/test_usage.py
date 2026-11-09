"""Usage tracking: a fake printer (fake paho + fake FTPS) runs prints; deductions land in the fake Spoolman."""
import io
import json
import os
import zipfile

import pytest

from fakes.fake_ftps import FakeFtps
from fakes.fake_paho import LEAF, FakeClient, FakePrinter
from filament_kit import config, pairing
from filament_kit.bridge import ams, connection, ftps, registry, usage
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from filament_kit.spoolman import Spoolman

SERIAL = "0948ZZ0A0000001"
NAME = "Office H2D"
CODE = "13572468"
DASH = "–"

# Metadata/slice_info.config as Bambu Studio 2.x writes it for an H2D (shape of the owner's test 3MF):
# one <plate> per plate, <filament id> = the project filament number (1-based, may skip numbers), whose
# slot is mapping[id - 1] in the printer's report.
SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.03.00.70"/>
  </header>
{plates}
</config>
"""
PLATE = """  <plate>
    <metadata key="index" value="{index}"/>
    <metadata key="printer_model_id" value="O1D"/>
    <metadata key="nozzle_diameters" value="0.4,0.4"/>
    <metadata key="timelapse_type" value="0"/>
    <metadata key="prediction" value="5409"/>
    <metadata key="weight" value="31.52"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="false"/>
    <metadata key="label_object_enabled" value="true"/>
    <metadata key="filament_maps" value="1 2"/>
    <object identify_id="412" name="bracket_v3.stl" skipped="false" />
{filaments}
    <warning msg="bed_temperature_too_high_than_filament" level="1" error_code ="1000C001"  />
  </plate>"""
FIL = ('    <filament id="{id}" tray_info_idx="{idx}" type="{type}" color="{color}" used_m="{m}" '
       'used_g="{g}" />')


def slice_info(plates: dict[int, list[tuple]]) -> str:
    blocks = []
    for index, fils in plates.items():
        lines = [FIL.format(id=i, idx=idx, type=t, color=c, m=round(g / 3, 2), g=g) for i, idx, t, c, g in fils]
        blocks.append(PLATE.format(index=index, filaments="\n".join(lines)))
    return SLICE_INFO.format(plates="\n".join(blocks))


def build_3mf(plates: dict[int, list[tuple]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("Metadata/plate_1.gcode", "; HEADER_BLOCK_START\nM400\n")
        z.writestr("Metadata/slice_info.config", slice_info(plates))
    return buf.getvalue()


TWO_COLOUR = {1: [(1, "PFUS3f5a0c1d", "PLA", "#FFFFFF", 21.92), (2, "PFUS3f5a0c2e", "PETG", "#1A1A1A", 9.6)]}
IDLE = {"gcode_state": "IDLE", "mc_percent": 0, "subtask_name": "", "ams": {"ams": []}}
JOB = {"gcode_state": "RUNNING", "mc_percent": 3, "subtask_name": "bracket_v3", "task_id": "771234",
       "gcode_file": "/data/Metadata/plate_1.gcode", "plate_idx": 1, "mapping": [1, 128]}
CALIBRATED = {"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0},
              "A2": {"ams_id": 0, "tray_id": 1, "global_id": 1},
              "HT-A": {"ams_id": 128, "tray_id": 0, "global_id": 128}}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)


@pytest.fixture
def sd(tmp_path, monkeypatch):
    f = FakeFtps(LEAF, tmp_path / "sd", CODE)       # the same leaf as MQTT: one leaf on every port
    monkeypatch.setattr(ftps, "PORT", f.port)
    yield f
    f.close()


@pytest.fixture
def sm(spoolman_url, spoolman_fake_store):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    fil = s.post("filament", {"name": "PLA Basic", "material": "PLA", "weight": 1000, "spool_weight": 250})
    for loc in (f"{NAME} {DASH} AMS A1", f"{NAME} {DASH} AMS A2", f"{NAME} {DASH} AMS HT-A", "Shelf"):
        s.post("spool", {"filament_id": fil["id"], "location": loc, "initial_weight": 1000})
    return s


A1, A2, HTA, SHELF = 1, 2, 3, 4      # spool ids by location


def used(store, sid):
    return round(store["spools"][sid]["used_weight"], 3)


def calibrate(slots=CALIBRATED, observe=False):
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(slots), calibrated=True, observe=observe))


class Rig:
    """A server process: Manager + Tracker, connected to a fake printer that reports `report`."""

    def __init__(self, sm, report):
        self.clients = []

        def factory(cid):
            c = FakeClient(cid)
            self.clients.append(c)
            return c
        self.manager = Manager(client_factory=factory)
        self.tracker = usage.Tracker(self.manager, sm)
        self.manager.sync()
        self.client = self.clients[0]
        self.printer = FakePrinter(self.client, report)
        self.client.connected(0)
        assert self.manager.wait_report(SERIAL, lambda r: "gcode_state" in r, 2) is not None

    def push(self, delta):
        self.printer.push(delta)

    def reconnect(self):
        self.client.dropped()
        self.client.connected(0)

    def print_job(self, final="FINISH", percent=100, job=JOB):
        self.push(job)
        self.push({"gcode_state": final, "mc_percent": percent})
        self.settled()

    def settled(self, timeout=60):
        """Wait for the settles queued so far. A settle fetches the 3mf over (fake) FTPS, whose own timeout is 20 s,
        and calls Spoolman: on a crowded machine that outlasted the 10 s this used to wait, and the test then read
        the usage log before anything was written (KeyError 'A2', flaky list 2026-11-09 11:30)."""
        self.tracker.flush(timeout)
        with self.tracker._lock:
            left = [f for f in self.tracker._futures if not f.done()]
        assert not left, f"{len(left)} settle(s) still running after {timeout} s"

    def close(self):
        self.tracker.stop()
        self.manager.stop()


@pytest.fixture
def rig(sm, sd):
    registry.upsert(Printer(SERIAL, NAME, "O1D", "127.0.0.1", CODE, True))
    rigs = []

    def make(report=IDLE):
        r = Rig(sm, report)
        rigs.append(r)
        return r
    yield make
    for r in rigs:
        r.close()


def put(sd, path, data):
    p = sd.root / path.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# ---------------------------------------------------------------- deductions

def test_finished_two_colour_print_deducts_from_the_right_spools(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    s = spoolman_fake_store
    assert used(s, A2) == 21.92 and used(s, HTA) == 9.6           # mapping [1, 128] -> A2, HT-A
    assert used(s, A1) == 0 and used(s, SHELF) == 0
    es = usage.entries(SERIAL, 7)
    assert sorted((e["slot"], e["spool_id"], e["grams"]) for e in es) == [("A2", A2, 21.92), ("HT-A", HTA, 9.6)]
    for e in es:
        assert set(e) == {"id", "at", "job", "grams", "spool_id", "slot", "observe", "undone"}
        assert e["job"] == "bracket_v3" and e["observe"] is False and e["undone"] is False


def test_cancelled_at_40_percent_deducts_40_percent(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/bracket_v3.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job(final="FAILED", percent=40)
    assert used(spoolman_fake_store, A2) == round(21.92 * 0.4, 2)
    assert used(spoolman_fake_store, HTA) == round(9.6 * 0.4, 2)


def test_finish_in_first_report_after_connect_is_not_settled(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(dict(JOB, gcode_state="FINISH", mc_percent=100))   # the server starts after a finished print
    r.push({"mc_percent": 100})                                  # more reports with the same state
    r.tracker.flush(5)
    assert spoolman_fake_store.get("uses", []) == [] and usage.entries(SERIAL, 7) == []


def test_finish_while_disconnected_is_not_settled_on_reconnect(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.push(JOB)
    r.client.dropped()
    with r.printer.lock:
        r.printer.report.update(gcode_state="FINISH", mc_percent=100)
    r.client.connected(0)                 # pushall: the first report after the reconnect already says FINISH
    assert r.manager.wait_report(SERIAL, lambda rep: rep.get("gcode_state") == "FINISH", 2)
    r.tracker.flush(5)
    assert spoolman_fake_store.get("uses", []) == [] and usage.entries(SERIAL, 7) == []


def test_restart_mid_print_then_finish_deducts_exactly_once(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    first = rig()
    first.push(JOB)
    first.close()                                         # the server restarts mid-print
    report = dict(first.printer.report)
    second = rig(report)                                  # first report after start: RUNNING
    second.push({"mc_percent": 60})
    second.push({"gcode_state": "FINISH", "mc_percent": 100})
    second.push({"gcode_state": "FINISH", "mc_percent": 100})
    second.reconnect()                                    # pushall repeats FINISH
    second.push({"gcode_state": "FINISH"})
    second.settled()
    assert used(spoolman_fake_store, A2) == 21.92 and used(spoolman_fake_store, HTA) == 9.6
    assert len(spoolman_fake_store["uses"]) == 2 and len(usage.entries(SERIAL, 7)) == 2


def test_two_prints_in_a_row_both_settle(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    r.push({"gcode_state": "IDLE"})
    r.print_job(job=dict(JOB, task_id="771235"))
    assert used(spoolman_fake_store, A2) == round(2 * 21.92, 2)


def test_3mf_not_found_logs_an_error_and_writes_nothing(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/someone_elses_newer_job.gcode.3mf", build_3mf(TWO_COLOUR))   # never "the newest file"
    r = rig()
    r.print_job()
    assert spoolman_fake_store.get("uses", []) == []
    (e,) = usage.entries(SERIAL, 7)
    assert e["error"] == "file_not_found" and e["job"] == "bracket_v3" and e["spool_id"] is None
    assert e["grams"] is None and e["slot"] is None


def test_3mf_found_by_name_ignoring_case(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/Bracket_V3_plate_1.gcode.3MF", build_3mf(TWO_COLOUR))
    put(sd, "/cache/zzz.gcode.3mf", build_3mf({1: [(1, "x", "PLA", "#000000", 500.0)]}))
    r = rig()
    r.print_job()
    assert used(spoolman_fake_store, A2) == 21.92


def test_a_similar_name_is_another_job(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/bracket_v3.gcode.3mf", build_3mf(TWO_COLOUR))         # job "bracket" must not take this one
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    put(sd, "/cache/my bracket.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job(job=dict(JOB, subtask_name="bracket"))
    assert spoolman_fake_store.get("uses", []) == []
    (e,) = usage.entries(SERIAL, 7)
    assert e["error"] == "file_not_found" and e["job"] == "bracket"


def test_nlst_match_is_exact_but_case_blind():
    names = ["/bracket_v3.gcode.3mf", "/cache/BRACKET_plate_2.gcode.3mf", "/Bracket.gcode.3mf",
             "/cache/bracket.gcode.3mf", "/bracket (2).gcode.3mf"]
    assert usage.nlst_match(names, "bracket", "2") == "/cache/BRACKET_plate_2.gcode.3mf"
    assert usage.nlst_match(names, "bracket", "1") == "/Bracket.gcode.3mf"         # / before /cache
    assert usage.nlst_match(names, "bracket", None) == "/Bracket.gcode.3mf"
    assert usage.nlst_match(names, "brack", None) is None
    assert usage.nlst_match(["/bracket_v3.gcode.3mf"], "bracket", None) is None


def test_prints_reporting_task_id_0_all_settle(rig, sd, spoolman_fake_store):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    for _ in range(2):                                   # LAN / SD-card / touchscreen prints report "0"
        r.print_job(job=dict(JOB, task_id="0"))
        r.push({"gcode_state": "IDLE"})
    r.print_job(job={k: v for k, v in JOB.items() if k != "task_id"})
    assert used(spoolman_fake_store, A2) == round(3 * 21.92, 2)
    assert len(usage.entries(SERIAL, 7)) == 6


@pytest.mark.parametrize("name", [f"fk-calib-{SERIAL}", f"fk-calib-{SERIAL}-1a2b3c"])   # old name, per-run name
def test_our_calibration_job_is_not_settled(rig, sd, spoolman_fake_store, name):
    calibrate()
    r = rig()
    r.print_job(job=dict(JOB, subtask_name=name, task_id="0", mapping=[0, 1, 128]))
    assert spoolman_fake_store.get("uses", []) == [] and usage.entries(SERIAL, 7) == []
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r.push({"gcode_state": "IDLE"})
    r.print_job(job=dict(JOB, task_id="0"))                # a real print afterwards still settles
    assert used(spoolman_fake_store, A2) == 21.92


def test_two_spools_claiming_one_slot_write_nothing_for_it(rig, sd, spoolman_fake_store, sm):
    calibrate()
    sm.patch(f"spool/{SHELF}", {"location": f"{NAME} {DASH} AMS HT-A"})
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    assert spoolman_fake_store["uses"] == [(A2, 21.92)]
    e = next(e for e in usage.entries(SERIAL, 7) if e["slot"] == "HT-A")
    assert e["error"] == "ambiguous_spool" and e["spool_id"] is None and e["grams"] == 9.6
    with pytest.raises(usage.NothingToUndo):
        usage.undo(e["id"], sm)


def test_an_archived_spool_at_the_slot_does_not_count(rig, sd, spoolman_fake_store, sm):
    calibrate()
    sm.patch(f"spool/{SHELF}", {"location": f"{NAME} {DASH} AMS HT-A", "archived": True})
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    assert used(spoolman_fake_store, HTA) == 9.6 and used(spoolman_fake_store, SHELF) == 0


def test_multi_plate_project_uses_the_printed_plate(rig, sd, spoolman_fake_store):
    calibrate()
    plates = {1: [(1, "a", "PLA", "#FFFFFF", 5.0)], 2: [(1, "a", "PLA", "#FFFFFF", 7.5),
                                                       (3, "b", "PLA", "#000000", 2.25)]}
    put(sd, "/cache/bracket_v3_plate_2.gcode.3mf", build_3mf(plates))
    r = rig()
    r.print_job(job=dict(JOB, plate_idx=2, gcode_file="/data/Metadata/plate_2.gcode", mapping=[0, 1, 128]))
    assert used(spoolman_fake_store, A1) == 7.5 and used(spoolman_fake_store, HTA) == 2.25   # id 3 -> mapping[2]
    assert used(spoolman_fake_store, A2) == 0


def test_observe_mode_logs_only(rig, sd, spoolman_fake_store):
    calibrate(observe=True)
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    assert spoolman_fake_store.get("uses", []) == []
    es = usage.entries(SERIAL, 7)
    assert len(es) == 2 and all(e["observe"] is True for e in es)
    assert sorted(e["grams"] for e in es) == [9.6, 21.92]


def test_uncalibrated_printer_is_observe_mode(rig, sd, spoolman_fake_store):
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    assert spoolman_fake_store.get("uses", []) == []
    es = usage.entries(SERIAL, 7)
    assert len(es) == 2 and all(e["observe"] is True for e in es)


def test_no_spool_at_a_slot_writes_nothing_for_it(rig, sd, spoolman_fake_store, sm):
    calibrate()
    sm.patch(f"spool/{HTA}", {"location": "Shelf"})
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    assert spoolman_fake_store["uses"] == [(A2, 21.92)]
    e = next(e for e in usage.entries(SERIAL, 7) if e["slot"] == "HT-A")
    assert e["spool_id"] is None and e["grams"] == 9.6 and e["observe"] is False


# ---------------------------------------------------------------- undo

def test_undo_restores_once(rig, sd, spoolman_fake_store, sm):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    e = next(e for e in usage.entries(SERIAL, 7) if e["slot"] == "A2")
    out = usage.undo(e["id"], sm)
    assert out["id"] == e["id"] and out["undone"] is True
    assert used(spoolman_fake_store, A2) == 0 and used(spoolman_fake_store, HTA) == 9.6
    assert spoolman_fake_store["uses"][-1] == (A2, -21.92)
    assert next(x for x in usage.entries(SERIAL, 7) if x["id"] == e["id"])["undone"] is True
    with pytest.raises(usage.AlreadyUndone) as ei:
        usage.undo(e["id"], sm)
    assert ei.value.code == "already_undone" and ei.value.status == 409
    assert used(spoolman_fake_store, A2) == 0


def _undoable(rig, sd, sm):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    rig().print_job()
    return next(e for e in usage.entries(SERIAL, 7) if e["slot"] == "A2")


class _Reused:
    """Spoolman with one spool's answer changed."""

    def __init__(self, real, spool_id, **change):
        self.real, self.spool_id, self.change, self.uses = real, spool_id, change, []

    def get(self, path):
        if self.change.get("gone") and path == f"spool/{self.spool_id}":
            raise usage.SpoolmanError("not found", status=404)
        if self.change.get("down"):
            raise usage.SpoolmanError("spoolman_unreachable", status=None)
        got = self.real.get(path)
        if path == f"spool/{self.spool_id}" and "registered" in self.change:
            got = {**got, "registered": self.change["registered"]}
        return got

    def use(self, spool_id, grams):
        self.uses.append((spool_id, grams))
        return self.real.use(spool_id, grams)


LATER = "2099-01-01T00:00:00Z"


@pytest.mark.parametrize("change,word", [({"registered": LATER}, "added after this print"), ({"gone": True}, "gone from Spoolman"),
                                         ({"registered": None}, "can't tell"), ({"registered": "soon"}, "can't tell")])
def test_undo_refuses_a_spool_id_that_is_another_spool_now(rig, sd, spoolman_fake_store, sm, change, word):
    e = _undoable(rig, sd, sm)
    fake = _Reused(sm, A2, **change)
    with pytest.raises(usage.SpoolChanged) as ei:
        usage.undo(e["id"], fake)
    assert ei.value.code == "spool_changed" and ei.value.status == 409 and word in str(ei.value)
    assert "nothing was changed" in str(ei.value) and fake.uses == []
    assert next(x for x in usage.entries(SERIAL, 7) if x["id"] == e["id"])["undone"] is False


def test_undo_goes_ahead_for_a_spool_that_was_there(rig, sd, spoolman_fake_store, sm):
    e = _undoable(rig, sd, sm)
    fake = _Reused(sm, A2, registered="2020-01-01T00:00:00+00:00")
    assert usage.undo(e["id"], fake)["undone"] is True and fake.uses == [(A2, -21.92)]


def test_a_spool_added_in_the_same_second_counts_as_there(rig, sd, spoolman_fake_store, sm):
    e = _undoable(rig, sd, sm)
    assert usage.undo(e["id"], _Reused(sm, A2, registered=e["at"]))["undone"] is True


def test_spoolman_down_at_the_check_changes_nothing_and_says_so_as_before(rig, sd, spoolman_fake_store, sm):
    e = _undoable(rig, sd, sm)
    fake = _Reused(sm, A2, down=True)
    with pytest.raises(usage.SpoolmanError):
        usage.undo(e["id"], fake)
    assert fake.uses == []


@pytest.mark.parametrize("text,want", [("2026-11-08T12:00:00Z", 1793880000.0), ("2026-11-08T12:00:00", 1793880000.0),
                                       ("2026-11-08T07:00:00-05:00", 1793880000.0), ("2026-11-08T12:00:00.5Z", 1793880000.5)])
def test_spoolmans_time_forms_all_read_as_utc(text, want):
    import datetime as dt
    expected = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc).timestamp() + (want - 1793880000.0)
    assert usage._registered({"registered": text}) == expected


def test_undo_after_7_days_is_too_old(rig, sd, spoolman_fake_store, sm, monkeypatch):
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    e = usage.entries(SERIAL, 7)[0]
    real = usage._now()
    monkeypatch.setattr(usage, "_now", lambda: real + 7 * 86400 + 60)
    with pytest.raises(usage.TooOld) as ei:
        usage.undo(e["id"], sm)
    assert ei.value.code == "too_old" and ei.value.status == 409
    assert len(spoolman_fake_store["uses"]) == 2
    assert usage.entries(SERIAL, 7) == [] and len(usage.entries(SERIAL, 8)) == 2


def test_undo_unknown_and_unwritten_entries(rig, sd, sm):
    with pytest.raises(usage.UsageNotFound) as ei:
        usage.undo("0123456789abcdef0123456789abcdef", sm)
    assert ei.value.status == 404
    with pytest.raises(usage.UsageNotFound):
        usage.undo("../../etc/passwd", sm)
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()                                          # uncalibrated: observe entries, nothing written
    e = usage.entries(SERIAL, 7)[0]
    with pytest.raises(usage.NothingToUndo) as ei:
        usage.undo(e["id"], sm)
    assert ei.value.code == "nothing_to_undo" and ei.value.status == 409


def test_entries_of_unknown_or_bad_serial(env):
    assert usage.entries("NOPE", 7) == []
    with pytest.raises(usage.UsageNotFound):
        usage.entries("../x", 7)


def test_parse_slice_info_plates():
    plates = usage.parse_filaments(build_3mf({1: [(1, "a", "PLA", "#FFF", 1.5)], 2: [(4, "b", "PETG", "#000", 2)]}))
    assert plates == {"1": [{"id": 1, "used_g": 1.5, "type": "PLA", "color": "#FFF", "idx": "a"}],
                      "2": [{"id": 4, "used_g": 2.0, "type": "PETG", "color": "#000", "idx": "b"}]}
    assert usage.parse_filaments(b"not a zip") == {}


# ---------------------------------------------------------------- state ownership (root-run CLI first)

def _as_root(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "chown", lambda p, u, g, **kw: calls.append((os.fspath(p), u, g)), raising=False)
    monkeypatch.setattr(os, "fchown", lambda fd, u, g: calls.append(("<open temp file>", u, g)), raising=False)
    return calls


def test_new_state_dirs_and_usage_log_go_to_the_state_owner(env, monkeypatch):
    state = config.paths().state
    state.mkdir(parents=True)
    st = os.stat(state)
    calls = _as_root(monkeypatch)
    usage.append(SERIAL, {"job": "x"})
    paths = {os.path.relpath(c[0], state) for c in calls if c[1:] == (st.st_uid, st.st_gid) and c[0][0] != "<"}
    assert {"printers", os.path.join("printers", SERIAL), os.path.join("printers", SERIAL, "usage.jsonl")} <= paths
    calls.clear()
    usage.append(SERIAL, {"job": "y"})                     # existing dir and file: nothing to hand over
    assert calls == []


def test_save_map_gives_new_dirs_to_the_state_owner(env, monkeypatch):
    state = config.paths().state
    state.mkdir(parents=True)
    calls = _as_root(monkeypatch)
    ams.save_map(SERIAL, ams.SlotMap())
    paths = {os.path.relpath(c[0], state) for c in calls if c[0][0] != "<"}
    assert {"printers", os.path.join("printers", SERIAL)} <= paths


def test_make_state_dir_non_root_does_not_chown(env, monkeypatch):
    calls = _as_root(monkeypatch)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    d = config.paths().state / "printers" / SERIAL
    pairing.make_state_dir(d)
    assert d.is_dir() and calls == []


# ---------------------------------------------------------------- listener hook

def test_manager_listener_sees_first_report_flag(sm):
    registry.upsert(Printer(SERIAL, NAME, "O1D", "127.0.0.1", CODE, True))
    clients = []
    m = Manager(client_factory=lambda cid: clients.append(FakeClient(cid)) or clients[-1])
    seen = []
    m.add_listener(lambda serial, report, first: seen.append((serial, report.get("gcode_state"), first)))
    m.add_listener(lambda *a: 1 / 0)                   # a failing listener does not break the others
    m.sync()
    c = clients[0]
    c.connected(0)
    c.deliver({"print": {"gcode_state": "IDLE"}})
    c.deliver({"print": {"gcode_state": "RUNNING"}})
    c.dropped()
    c.connected(0)
    c.deliver({"print": {"mc_percent": 5}})            # a delta before the full report: still "first"
    c.deliver({"print": {"gcode_state": "FINISH"}})    # the first state after the reconnect
    c.deliver({"print": {"mc_percent": 6}})
    m.stop()
    assert seen == [(SERIAL, "IDLE", True), (SERIAL, "RUNNING", False),
                    (SERIAL, "RUNNING", True), (SERIAL, "FINISH", True), (SERIAL, "FINISH", False)]


def test_spoolman_use(sm, spoolman_fake_store):
    out = sm.use(A1, 12.5)
    assert out["used_weight"] == 12.5
    sm.use(A1, -2.5)
    assert used(spoolman_fake_store, A1) == 10


# ---------------------------------------------------------------- I2 / M3: no stale mapping, unmapped slots

def test_print_without_mapping_after_calibration_writes_nothing(rig, sd, spoolman_fake_store):
    """The calibration job's `mapping` must not be used for the next print whose reports carry none."""
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job(job=dict(JOB, subtask_name=f"fk-calib-{SERIAL}", task_id="0", mapping=[0, 1, 128]))
    r.push({"gcode_state": "IDLE"})
    job = {k: v for k, v in JOB.items() if k not in ("mapping", "plate_idx")}
    r.print_job(job=job)
    assert spoolman_fake_store.get("uses", []) == [] and used(spoolman_fake_store, A1) == 0
    es = usage.entries(SERIAL, 7)
    assert [(e["job"], e.get("error"), e["grams"], e["spool_id"]) for e in es] == \
        [("bracket_v3", "no_mapping", None, None)]


def test_settle_without_mapping_is_no_mapping(sm, sd):
    registry.upsert(Printer(SERIAL, NAME, "O1D", "127.0.0.1", CODE, True))
    calibrate()
    out = usage.settle(SERIAL, {"subtask": "bracket_v3", "plate": "1", "mapping": None}, 100.0, sm)
    assert [e["error"] for e in out] == ["no_mapping"]
    assert sd.connections == 0                                   # nothing fetched


def test_calibrated_print_on_a_slot_missing_from_the_map_is_unmapped_slot(rig, sd, spoolman_fake_store):
    calibrate({"A2": CALIBRATED["A2"]})                          # HT-A (global 128) not in the map
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job()
    es = {e["slot"] or "none": e for e in usage.entries(SERIAL, 7)}
    assert es["A2"].get("error") is None and used(spoolman_fake_store, A2) == 21.92
    assert es["none"]["error"] == "unmapped_slot" and es["none"]["spool_id"] is None
    assert used(spoolman_fake_store, HTA) == 0


def test_unnamed_printer_finds_its_spools_by_serial(sd):
    """M2: the printer's display name (registry name, else serial) is the same everywhere: loading put the spool
    at "<serial> – AMS A2", so usage looks there too."""
    registry.upsert(Printer(SERIAL, "", "O1D", "127.0.0.1", CODE, True))
    calibrate()
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))

    class SM:
        uses = []

        def get(self, path):
            return [{"id": 9, "location": f"{SERIAL} {DASH} AMS A2"}]

        def use(self, sid, g):
            SM.uses.append((sid, g))
    out = usage.settle(SERIAL, {"subtask": "bracket_v3", "plate": "1", "mapping": [1, 128]}, 100.0, SM())
    assert SM.uses == [(9, 21.92)]
    assert [e["spool_id"] for e in out if e["slot"] == "A2"] == [9]


# ---------------------------------------------------------------- numbering schemes, learning, suspect (P3)

WHITE_PLA = {"tray_type": "PLA", "tray_info_idx": "PFUS3f5a0c1d", "tray_color": "FFFFFFFF"}
BLACK_PETG = {"tray_type": "PETG", "tray_info_idx": "PFUS3f5a0c2e", "tray_color": "1A1A1AFF"}


def loaded_report(a2=WHITE_PLA, hta=BLACK_PETG, extra=None):
    """IDLE with AMS 0 (A2 holds `a2`, A1 / A3 / A4 empty) and AMS HT 128 (holds `hta`): the slots a print's
    start report shows."""
    trays = [{"id": "0"}, dict(a2, id="1"), {"id": "2"}, {"id": "3"}]
    units = [{"id": "0", "tray": trays}, {"id": "128", "tray": [dict(hta, id="0")]}] + list(extra or [])
    return {"gcode_state": "IDLE", "mc_percent": 0, "subtask_name": "", "ams": {"ams": units}}


def spool_at(sm, label):
    fil = sm.post("filament", {"name": "PLA Basic", "material": "PLA", "weight": 1000, "spool_weight": 250})
    return sm.post("spool", {"filament_id": fil["id"], "location": f"{NAME} {DASH} AMS {label}",
                             "initial_weight": 1000})["id"]


def test_owner_h2d_calibration_values_decode_a_print(rig, sd, spoolman_fake_store, sm):
    """The map the owner's H2D calibration gives (A1 / A3 = 0 / 2, HT-A / HT-B = 32768 / 33024, shift8): a print
    reporting [2, 33024] deducts from A3 and HT-B."""
    a3, htb = spool_at(sm, "A3"), spool_at(sm, "HT-B")
    ams.save_map(SERIAL, ams.SlotMap(slots={
        "A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}, "A3": {"ams_id": 0, "tray_id": 2, "global_id": 2},
        "HT-A": {"ams_id": 128, "tray_id": 0, "global_id": 32768},
        "HT-B": {"ams_id": 129, "tray_id": 0, "global_id": 33024}}, calibrated=True, observe=False, scheme="shift8"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job(job=dict(JOB, mapping=[2, 33024]))
    assert used(spoolman_fake_store, a3) == 21.92 and used(spoolman_fake_store, htb) == 9.6
    assert used(spoolman_fake_store, HTA) == 0


def test_saved_scheme_decodes_a_number_the_map_does_not_list(rig, sd, spoolman_fake_store):
    """A2 and HT-A are not in the calibrated map (they were empty at calibration): the saved scheme (shift8)
    decodes 1 -> A2 and 32768 -> HT-A, both slots of the printer at the print's start."""
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}, calibrated=True,
                                     observe=False, scheme="shift8"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(loaded_report())
    r.print_job(job=dict(JOB, mapping=[1, 32768]))
    assert used(spoolman_fake_store, A2) == 21.92 and used(spoolman_fake_store, HTA) == 9.6
    assert all(e.get("error") is None for e in usage.entries(SERIAL, 7))


def test_saved_scheme_never_decodes_to_a_slot_the_printer_does_not_have(rig, sd, spoolman_fake_store):
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0}}, calibrated=True,
                                     observe=False, scheme="shift8"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(loaded_report(hta=WHITE_PLA))                     # no slot holds the PETG: nothing to learn either
    r.print_job(job=dict(JOB, mapping=[1, 0x0300]))           # shift8: unit 3 tray 0, not on this printer
    es = {e["grams"]: e for e in usage.entries(SERIAL, 7)}
    assert es[9.6]["error"] == "unmapped_slot" and es[9.6]["slot"] is None


def test_uncalibrated_decodes_with_the_models_first_candidate(rig, sd, spoolman_fake_store):
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig()
    r.print_job(job=dict(JOB, mapping=[1, 32768]))           # H2D: shift8 first
    es = usage.entries(SERIAL, 7)
    assert sorted((e["slot"], e["observe"]) for e in es) == [("A2", True), ("HT-A", True)]
    assert spoolman_fake_store.get("uses", []) == []


def test_unseen_number_learned_when_exactly_one_loaded_slot_matches(rig, sd, spoolman_fake_store):
    """4000 is no number the map or its scheme knows; exactly one loaded slot (HT-A) holds the sliced filament
    (tray_info_idx): learned, deducted, and the next print decodes it from the map."""
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(CALIBRATED), calibrated=True, observe=False, scheme="legacy"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(loaded_report())
    r.print_job(job=dict(JOB, mapping=[1, 4000]))
    assert used(spoolman_fake_store, HTA) == 9.6
    assert ams.load_map(SERIAL).learned == {"4000": "HT-A"}
    r.push({"gcode_state": "IDLE"})
    r.print_job(job=dict(JOB, mapping=[1, 4000]))
    assert used(spoolman_fake_store, HTA) == 19.2


def test_unseen_number_by_type_and_colour_when_the_slice_has_no_preset(rig, sd, spoolman_fake_store):
    plain = {1: [(1, "", "PLA", "#FFFFFF", 21.92), (2, "", "PETG", "#1A1A1A", 9.6)]}
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(CALIBRATED), calibrated=True, observe=False, scheme="legacy"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(plain))
    r = rig(loaded_report())
    r.print_job(job=dict(JOB, mapping=[1, 4000]))
    assert ams.load_map(SERIAL).learned == {"4000": "HT-A"} and used(spoolman_fake_store, HTA) == 9.6


def test_unseen_number_not_learned_when_two_slots_match(rig, sd, spoolman_fake_store):
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(CALIBRATED), calibrated=True, observe=False, scheme="legacy"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(loaded_report(extra=[{"id": "129", "tray": [dict(BLACK_PETG, id="0")]}]))
    r.print_job(job=dict(JOB, mapping=[1, 4000]))
    es = {e["grams"]: e for e in usage.entries(SERIAL, 7)}
    assert es[9.6]["error"] == "unmapped_slot" and ams.load_map(SERIAL).learned == {}
    assert used(spoolman_fake_store, HTA) == 0


def test_two_mismatched_prints_make_the_map_suspect_and_ask_for_a_remap(rig, sd, spoolman_fake_store):
    """A2 holds PETG but the slice puts white PLA there: not deducted (slot_mismatch). Two such prints in a row:
    suspect, logging only, and LayoutWatch is asked to re-map when idle."""
    from filament_kit.bridge import mapping
    mapping._REMAP_REQUESTS.discard(SERIAL)
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(CALIBRATED), calibrated=True, observe=False, scheme="legacy"))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(loaded_report(a2=BLACK_PETG, hta=BLACK_PETG))
    r.print_job()
    es = {e["slot"]: e for e in usage.entries(SERIAL, 7)}
    assert es["A2"]["error"] == "slot_mismatch" and used(spoolman_fake_store, A2) == 0
    assert used(spoolman_fake_store, HTA) == 9.6                 # HT-A agrees: deducted
    m = ams.load_map(SERIAL)
    assert m.mismatch_streak == 1 and m.suspect is False and SERIAL not in mapping._REMAP_REQUESTS
    r.push({"gcode_state": "IDLE"})
    r.print_job()
    m = ams.load_map(SERIAL)
    assert m.mismatch_streak == 2 and m.suspect is True and m.observe is True and m.calibrated is True
    assert SERIAL in mapping._REMAP_REQUESTS
    assert used(spoolman_fake_store, HTA) == 9.6                 # suspect from this print on: logging only
    mapping._REMAP_REQUESTS.discard(SERIAL)


def test_a_matching_print_resets_the_mismatch_streak(rig, sd, spoolman_fake_store):
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(CALIBRATED), calibrated=True, observe=False, scheme="legacy",
                                     mismatch_streak=1))
    put(sd, "/cache/bracket_v3_plate_1.gcode.3mf", build_3mf(TWO_COLOUR))
    r = rig(loaded_report())
    r.print_job()
    m = ams.load_map(SERIAL)
    assert m.mismatch_streak == 0 and m.suspect is False
    assert used(spoolman_fake_store, A2) == 21.92


def test_usage_map_save_is_dropped_when_the_map_changed_meanwhile(env):
    """M1: usage saves what a print taught under the shared save lock, compare-and-save: a map a mapping job saved
    after usage read it wins, and usage's version is dropped."""
    registry.upsert(Printer(SERIAL, NAME, "O1D", "127.0.0.1", CODE, True))
    ams.save_map(SERIAL, ams.SlotMap(slots=dict(CALIBRATED), calibrated=True, observe=False))
    mine = ams.load_map(SERIAL)
    stamp = mine.updated
    newer = ams.SlotMap(slots={"A1": CALIBRATED["A1"]}, calibrated=True, observe=False, scheme="shift8")
    ams.save_map(SERIAL, newer)                                  # a mapping job finished meanwhile
    mine.learned["4000"] = "HT-A"
    usage._save_map(SERIAL, mine, stamp)
    m = ams.load_map(SERIAL)
    assert m.scheme == "shift8" and m.learned == {} and set(m.slots) == {"A1"}
    assert ams.save_map_if(SERIAL, mine, m.updated) is True     # the current stamp: saved
    assert ams.load_map(SERIAL).learned == {"4000": "HT-A"}
