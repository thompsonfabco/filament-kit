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
        self.tracker.flush(10)

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
    second.tracker.flush(10)
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
    monkeypatch.setattr(os, "chown", lambda p, u, g: calls.append((os.fspath(p), u, g)), raising=False)
    return calls


def test_new_state_dirs_and_usage_log_go_to_the_state_owner(env, monkeypatch):
    state = config.paths().state
    state.mkdir(parents=True)
    st = os.stat(state)
    calls = _as_root(monkeypatch)
    usage.append(SERIAL, {"job": "x"})
    paths = {os.path.relpath(c[0], state) for c in calls if c[1:] == (st.st_uid, st.st_gid)}
    assert {"printers", os.path.join("printers", SERIAL), os.path.join("printers", SERIAL, "usage.jsonl")} <= paths
    calls.clear()
    usage.append(SERIAL, {"job": "y"})                     # existing dir and file: nothing to hand over
    assert calls == []


def test_save_map_gives_new_dirs_to_the_state_owner(env, monkeypatch):
    state = config.paths().state
    state.mkdir(parents=True)
    calls = _as_root(monkeypatch)
    ams.save_map(SERIAL, ams.SlotMap())
    paths = {os.path.relpath(c[0], state) for c in calls}
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
