"""The X2D slot-mapping failure (Ext-L / Ext-R printer, one AMS loaded): the job file carries the printer's fields,
external holders stay out of the job, one loaded unit is enough for a confirmed map, empty slots are not written, and
an old failure or Developer Mode refusal does not stay in the way. No captured printer data: the expected values are
public Bambu Studio project fields, the serial a placeholder."""
from __future__ import annotations

import copy
import io
import json
import re
import zipfile

import pytest

from fakes.fake_paho import FakeClient, FakePrinter
from filament_kit import config
from filament_kit.bridge import ams, calib3mf, connection, hardware, mapping, registry, slottest
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from test_calib3mf import (CODE, FORBIDDEN, SERIAL, FakeManager, base_report, fake_ftp, jobs, leaf,  # noqa: F401
                           slotmap_for, tray)
from test_slottest import REPORT


def x2d_report(a=("PLA", "PLA", "PLA", "PLA")):
    """One AMS with the given slots (None: empty) and both external holders, which report a filament type even with
    no spool on them, as the X2D in the bug report did."""
    rep = base_report()
    rep["ams"]["tray_now"] = "255"
    rep["ams"]["ams"] = [{"id": "0", "info": "0", "tray": [tray(i, t) if t else {"id": str(i)}
                                                           for i, t in enumerate(a)]}]
    del rep["vt_tray"]
    rep["vir_slot"] = [dict(tray(0, "PLA", "FFFFFFFF"), id="254"), dict(tray(0, "PLA", "F5DEB3FF"), id="255")]
    return rep


def x2d_map(rep):
    return ams.SlotMap(slots={s.label: {"ams_id": u.ams_id, "tray_id": s.tray_id, "global_id": s.global_id}
                              for u in ams.units(rep, "N6") for s in u.slots})


@pytest.fixture
def x2d():
    p = Printer(serial=SERIAL, name="X2D", model="N6", ip="127.0.0.1", access_code=CODE, configured=True)
    registry.upsert(p)
    return p


# ---------------------------------------------------------------- point 2 + 3: what the bug report showed

def test_one_ams_and_two_empty_holders_is_a_confirmed_map(fake_ftp, x2d):
    """A1-A4 answer 0, 1, 2, 3 and the holders are not in the job: no "reported no slot", no "fit no scheme"."""
    rep = x2d_report()
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, x2d_map(rep))
    assert r.consistent is True, r.problems
    assert r.problems == []
    assert r.decoding == {"A1": 0, "A2": 1, "A3": 2, "A4": 3}
    assert r.external == ["Ext-L", "Ext-R"]
    (pr,) = jobs(m)
    assert pr["ams_mapping"] == [0, 1, 2, 3]
    assert [x["ams_id"] for x in pr["ams_mapping2"]] == [0, 0, 0, 0]


def test_one_unit_fits_both_schemes_takes_the_first_and_says_so(fake_ftp, x2d):
    rep = x2d_report()
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, x2d_map(rep))
    assert r.scheme == "shift8"
    assert len(r.notes) == 1 and "shift8, legacy" in r.notes[0] and "added" in r.notes[0]


def test_a_second_unit_settles_the_scheme_without_a_note(fake_ftp, x2d):
    rep = x2d_report()
    rep["ams"]["ams"].append({"id": "1", "tray": [tray(0), tray(1)]})
    m = FakeManager(fake_ftp.root, "native", report=rep)
    r = calib3mf.run(m, SERIAL, x2d_map(rep))
    assert r.scheme == "shift8" and r.notes == [] and r.decoding["B1"] == 1 << 8, r.problems


def test_empty_ams_slot_stays_out_of_the_job(fake_ftp, x2d):
    rep = x2d_report(("PLA", None, "PLA", None))
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, x2d_map(rep))
    assert r.consistent is True and r.problems == [], r.problems
    assert r.skipped == ["A2", "A4"] and jobs(m)[0]["ams_mapping"] == [0, 2]


def test_only_holders_loaded_says_what_to_do_and_sends_nothing(fake_ftp, x2d):
    rep = x2d_report((None, None, None, None))
    m = FakeManager(fake_ftp.root, report=rep)
    r = calib3mf.run(m, SERIAL, x2d_map(rep))
    assert r.consistent is False and r.problems == [calib3mf.NO_AMS_LOADED] and jobs(m) == []


def test_a_real_failure_is_still_a_failure_and_names_the_printers_code(fake_ftp, x2d):
    rep = x2d_report()
    m = FakeManager(fake_ftp.root, report=rep)
    m.final, m.print_error = "FAILED", 83935248
    r = calib3mf.run(m, SERIAL, x2d_map(rep))
    assert r.consistent is False
    assert any(p == "the calibration job ended as FAILED on the printer (print_error 0x0500C010)"
               for p in r.problems), r.problems
    assert len(jobs(m)) == 1           # never a second job after a real failure


# ---------------------------------------------------------------- point 1: the job file per model

BASELINE = {   # public fields of unsliced Bambu Studio 02.09.01.70 projects
    "N6": ("N6", "Bambu Lab X2D", ["Direct Drive", "Bowden"], ["1", "0"], "1", "0 1",
           ["0x0", "256x0", "256x256", "0x256"], "261"),
    "N7": ("N7", "Bambu Lab P2S", ["Direct Drive"], ["0"], "1", "0", ["0x0", "256x0", "256x256", "0x256"], "256"),
    "O1D": ("O1D", "Bambu Lab H2D", ["Direct Drive", "Direct Drive"], ["1", "0"], "2", "0 0",
            ["0x0", "350x0", "350x320", "0x320"], "325"),
    "N1": ("N1", "Bambu Lab A1 mini", ["Direct Drive"], ["0"], "1", "0", ["0x0", "180x0", "180x180", "0x180"], "180"),
    "O1C": ("O1C2", "Bambu Lab H2C", ["Direct Drive", "Direct Drive"], ["1", "0"], "2", "0 0",
            ["0x0", "330x0", "330x320", "0x320"], "325"),
}


def _project_files(code, report=None, addrs=((0, 0), (0, 1))):
    mi = hardware.load().model(code)
    pr = calib3mf.project_for(mi, report or {}, list(addrs))
    z = zipfile.ZipFile(io.BytesIO(calib3mf.build([f"A{i}" for i in range(1, len(addrs) + 1)], pr)))
    return z, json.loads(z.read("Metadata/project_settings.config")), z.read("Metadata/slice_info.config").decode()


@pytest.mark.parametrize("code", sorted(BASELINE))
def test_the_job_file_carries_the_models_project_fields(code):
    mid, model, types, phys, master, ext_codes, area, height = BASELINE[code]
    z, ps, si = _project_files(code)
    assert f'key="printer_model_id" value="{mid}"' in si
    assert 'key="X-BBL-Client-Version" value="02.09.01.70"' in si
    assert f'key="extruder_type" value="{ext_codes}"' in si
    assert ps["printer_model"] == model and ps["extruder_type"] == types
    assert ps["physical_extruder_map"] == phys and ps["master_extruder_id"] == master
    assert ps["printable_area"] == area and ps["printable_height"] == height
    assert ps["printer_settings_id"] == f"{model} 0.4 nozzle" and ps["nozzle_diameter"] == ["0.4"] * len(types)
    assert "Metadata/_rels/model_settings.config.rels" in z.namelist()
    assert 'key="gcode_file" value="Metadata/plate_1.gcode"' in z.read("Metadata/model_settings.config").decode()


@pytest.mark.parametrize("code", sorted(BASELINE))
def test_the_job_file_is_still_comments_and_m400_only(code):
    z, _, _ = _project_files(code)
    code_lines = [ln for ln in z.read("Metadata/plate_1.gcode").decode().splitlines()
                  if ln.strip() and not ln.startswith(";")]
    assert code_lines == ["M400"]
    assert not any(FORBIDDEN.match(ln) for ln in code_lines)
    md5 = z.read("Metadata/plate_1.gcode.md5").decode()
    import hashlib
    assert md5 == hashlib.md5(z.read("Metadata/plate_1.gcode")).hexdigest().upper()


def test_nozzles_and_extruders_come_from_the_report():
    rep = {"ams": {"ams": [{"id": "0", "info": "1003"}, {"id": "1", "info": "1103"}]},
           "device": {"nozzle": {"info": [{"id": 0, "diameter": 0.6}, {"id": 1, "diameter": 0.2}]}}}
    # physical extruder 1 is the X2D's first (Bambu Studio's 1), physical 0 its second
    z, ps, si = _project_files("N6", rep, [(0, 0), (1, 0)])
    assert ps["nozzle_diameter"] == ["0.2", "0.6"]
    assert ps["filament_map"] == ["2", "1"]
    assert 'key="filament_maps" value="2 1"' in si
    assert 'group_id="1" nozzle_diameter="0.60"' in si and 'group_id="0" nozzle_diameter="0.20"' in si
    assert 'key="filament_maps" value="2 1"' in z.read("Metadata/model_settings.config").decode()


def test_a_single_top_level_nozzle_applies_and_a_silent_report_means_the_default():
    assert _project_files("N7", {"nozzle_diameter": "0.6"})[1]["nozzle_diameter"] == ["0.6"]
    assert _project_files("N7", {"nozzle_diameter": "junk"})[1]["nozzle_diameter"] == ["0.4"]
    assert _project_files("N7")[1]["filament_map"] == ["1", "1"]


def test_the_filament_preset_follows_the_nozzle_where_the_model_names_it():
    rep = {"nozzle_diameter": "0.6"}
    assert _project_files("N6", rep)[1]["filament_settings_id"][0] == "Bambu PLA Basic @BBL X2D 0.6 nozzle"
    assert _project_files("N7", rep)[1]["filament_settings_id"][0] == "Bambu PLA Basic @BBL P2S"


def test_a_model_without_project_fields_gets_the_minimal_file():
    mi = hardware.load().model("O1E")
    assert mi.slicer is None and calib3mf.project_for(mi, {}, [(0, 0)]) is None
    z = zipfile.ZipFile(io.BytesIO(calib3mf.build(["A1"], None)))
    assert "printer_model" not in json.loads(z.read("Metadata/project_settings.config"))
    assert "printer_model_id" not in z.read("Metadata/slice_info.config").decode()


def test_the_uploaded_job_file_is_the_models(fake_ftp, x2d):
    rep = x2d_report()
    m = FakeManager(fake_ftp.root, report=rep)
    calib3mf.run(m, SERIAL, x2d_map(rep))
    z = zipfile.ZipFile(io.BytesIO(m.file_at_start))
    assert 'key="printer_model_id" value="N6"' in z.read("Metadata/slice_info.config").decode()


def test_no_account_id_or_owner_field_in_the_job_file():
    z, _, _ = _project_files("N6")
    for n in z.namelist():
        assert "DesignerUserId" not in z.read(n).decode()
    assert "user_id" not in z.read("Metadata/project_settings.config").decode()


# ---------------------------------------------------------------- point 4 + the hardware file

def test_x2d_addresses_its_holders_like_the_h2d():
    mi = hardware.load().model("N6")
    assert mi.external_addressing == "tray-is-ams" and mi.ams_mapping2 is True
    assert [x.id for x in mi.externals] == [254, 255]


def test_every_project_fits_its_model():
    hw = hardware.load()
    assert hw.errors == [] and hw.warnings == []
    with_fields = [m for m in hw.models if m.slicer is not None]
    assert len(with_fields) >= 13
    for m in with_fields:
        assert len(m.slicer.extruders) == m.nozzles, m.name
        assert re.fullmatch(r"\d\d\.\d\d\.\d\d\.\d\d", m.slicer.client_version), m.name
        assert m.slicer.printer_model == m.preset_name, m.name


@pytest.mark.parametrize("bad,word", [
    ('master-extruder="3"', "master-extruder"),
    ('nozzle="9"', "nozzle"),
    ('client-version="2.9"', "client-version"),
])
def test_a_bad_project_in_a_file_is_refused(bad, word):
    key = bad.split("=")[0]
    good = {"master-extruder": '"1"', "nozzle": '"0.4"', "client-version": '"02.09.01.70"'}
    attrs = {**good, key: bad.split("=")[1]}
    xml = ('<bambu-hardware version="1"><models><model code="Z1" name="Z">'
           f'<slicer-project model-id="Z1" printer-model="Z" nozzle={attrs["nozzle"]} printable-width="1" '
           f'printable-depth="1" printable-height="1" master-extruder={attrs["master-extruder"]} '
           f'filament-preset="P" client-version={attrs["client-version"]}><extruder type="Direct Drive" physical="0"/>'
           '</slicer-project></model></models></bambu-hardware>')
    errs = hardware.validate(xml.encode())
    assert any(word in e for e in errs), errs


# ---------------------------------------------------------------- the slot test: empty slots are not written

SLOT_SERIAL = "S1"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state2"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c
    made = []

    def start(report):
        m = Manager(client_factory=factory)
        registry.upsert(Printer(SLOT_SERIAL, "X2D", "N6", "192.0.2.5", CODE, True))
        m.sync()
        printer = FakePrinter(clients[0], report)
        clients[0].connected(0)
        assert m.wait_report(SLOT_SERIAL, lambda r: "gcode_state" in r, 2) is not None
        made.append(m)
        return m, printer
    yield start
    for m in made:
        m.stop()


def _with_presence(bits: str):
    rep = copy.deepcopy(REPORT)
    rep["ams"]["ams"] = rep["ams"]["ams"][:1]          # one AMS, id 0
    rep["ams"]["ams"][0]["tray"][3] = {"id": "3"}
    rep["ams"]["tray_exist_bits"] = bits
    return rep


def test_a_slot_the_sensor_says_is_empty_gets_no_write(rig):
    m, printer = rig(_with_presence("7"))              # bits 0-2: A1-A3 present, A4 empty
    res = slottest.run(m, SLOT_SERIAL, lambda s: None)
    assert res.empty == {"A4": {"ams_id": 0, "tray_id": 3}}
    assert "A4" not in res.confirmed and not any("A4" in p for p in res.problems), res.problems
    assert (0, 3) not in {(w["ams_id"], w["tray_id"]) for w in printer.writes}
    assert res.restored is True


def test_a_refused_write_to_a_slot_with_no_filament_is_not_a_problem(rig):
    rep = copy.deepcopy(REPORT)                        # no presence bits: only the write can tell
    m, printer = rig(rep)
    printer.refuse[(0, 3)] = {"result": "fail", "reason": "write failed"}
    res = slottest.run(m, SLOT_SERIAL, lambda s: None)
    assert res.empty == {"A4": {"ams_id": 0, "tray_id": 3}}
    assert not any("A4" in p for p in res.problems), res.problems
    assert res.restored is True and "A1" in res.confirmed


def test_a_refused_write_to_a_loaded_slot_is_still_a_problem(rig):
    m, printer = rig(copy.deepcopy(REPORT))
    printer.refuse[(0, 1)] = {"result": "fail", "reason": "write failed"}
    res = slottest.run(m, SLOT_SERIAL, lambda s: None)
    assert "A2" not in res.empty and any(p.startswith("A2: not confirmed") for p in res.problems)


# ---------------------------------------------------------------- Developer Mode does not stick

@pytest.fixture
def refused(rig):
    m, _printer = rig(copy.deepcopy(REPORT))
    c = m._conns[SLOT_SERIAL].client
    c.responder = lambda t, b: ({"print": {"sequence_id": b["print"]["sequence_id"], "result": "fail",
                                           "reason": "mqtt message verify failed"}} if "print" in b else None)
    assert m.command(SLOT_SERIAL, "pause")["ok"] is False
    assert m.state(SLOT_SERIAL) == "needs_developer_mode"
    return m, c


def test_developer_mode_refusal_ages_out(refused, monkeypatch):
    m, _c = refused
    monkeypatch.setattr(connection, "DEVELOPER_MODE_HOLD", 0.0)
    assert m.state(SLOT_SERIAL) == "connected"


def test_a_new_refusal_flags_it_again_after_it_aged_out(refused, monkeypatch):
    m, _c = refused
    monkeypatch.setattr(connection, "DEVELOPER_MODE_HOLD", 0.0)
    assert m.state(SLOT_SERIAL) == "connected"
    monkeypatch.setattr(connection, "DEVELOPER_MODE_HOLD", 600.0)
    assert m.command(SLOT_SERIAL, "pause")["ok"] is False
    assert m.state(SLOT_SERIAL) == "needs_developer_mode"


def test_a_new_connection_clears_it(refused):
    m, c = refused
    conn = m._conns[SLOT_SERIAL]
    conn._set_state("offline")
    conn._set_state("connected")
    assert m.state(SLOT_SERIAL) == "connected"


# ---------------------------------------------------------------- an old result is marked, a new one is not

def _status(serial, **extra):
    d = config.paths().state / "printers" / serial
    d.mkdir(parents=True, exist_ok=True)
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "old", "state": "done", "step": "Mapping finished",
                                                     "problems": ["Ext-L: the printer reported no slot"],
                                                     "started": 1.0, "finished": 2.0, **extra}), encoding="utf-8")


class _NoManager:
    def state(self, serial):
        return "connected"


def test_a_result_from_an_earlier_server_run_is_marked_old(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state3"))
    _status(SERIAL)
    v = mapping.Mapper(_NoManager()).view(SERIAL)
    assert v["problems"] == ["Ext-L: the printer reported no slot"]
    assert v["problems_old"] is True and v["finished"] == 2.0 and v["notes"] == []


def test_an_old_result_without_problems_is_not_marked(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state3"))
    _status(SERIAL, problems=[])
    assert mapping.Mapper(_NoManager()).view(SERIAL)["problems_old"] is False


def test_notes_survive_the_status_file(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state3"))
    _status(SERIAL, problems=[], notes=["numbered alike"])
    assert mapping.Mapper(_NoManager()).view(SERIAL)["notes"] == ["numbered alike"]


def test_a_status_file_from_before_this_change_still_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state3"))
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "o", "state": "failed", "step": "",
                                                     "problems": ["x"]}), encoding="utf-8")
    v = mapping.Mapper(_NoManager()).view(SERIAL)
    assert v["state"] == "failed" and v["problems_old"] is True and v["finished"] is None and v["notes"] == []
