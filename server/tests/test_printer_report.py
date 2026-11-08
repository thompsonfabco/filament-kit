"""The printer report holds no owner data, says what happened, and a maintainer can read it."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from defusedxml import ElementTree

from fakes.fake_paho import FakeClient, FakePrinter
from filament_kit import cli, config
from filament_kit.bridge import calib3mf, connection, mapping, printer_report, registry
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from test_slottest import REPORT

SERIAL = "0948ZZ0A0000001"
CODE = "13572468"
ROOT = Path(__file__).resolve().parents[2]
PLANTED = {"serial": SERIAL, "access": CODE, "account": "1234567890", "ip": "192.0.2.77", "host": "printer.example.com",
           "name": "Example Bench", "ssid": "HomeWifiName", "tag": "AABBCCDD11223344", "uuid": "F00DF00DF00DF00D",
           "preset": "Pabc1234", "colour": "123456FF", "job": "my-secret-model", "module_sn": "01S00ABC123"}


def poisoned():
    r = copy.deepcopy(REPORT)
    r.update(sn=SERIAL, dev_id=SERIAL, access_code=CODE, user_id=PLANTED["account"], uid=PLANTED["account"],
             net={"info": [{"ip": PLANTED["ip"], "mask": 1}]}, wifi_signal="-60dBm", ssid=PLANTED["ssid"],
             subtask_name=PLANTED["job"], gcode_file=PLANTED["job"], ipcam={"rtsp_url": f"rtsps://{PLANTED['ip']}:322"},
             hms=[{"attr": 1, "code": 2, "text": PLANTED["name"]}], print_error=7, nickname=PLANTED["name"],
             brand_new_field={"who": PLANTED["host"]})
    r["ams"]["tray_exist_bits"] = "7"
    r["ams"]["brand_new_ams_field"] = PLANTED["host"]
    for u in r["ams"]["ams"]:
        for t in u["tray"]:
            t.update(tag_uid=PLANTED["tag"], tray_uuid=PLANTED["uuid"], tray_info_idx=PLANTED["preset"],
                     tray_color=PLANTED["colour"], tray_id_name=PLANTED["name"])
    r["vt_tray"].update(tag_uid=PLANTED["tag"], tray_info_idx=PLANTED["preset"], tray_color=PLANTED["colour"])
    r["device"] = {"nozzle": {"info": [{"id": 0, "diameter": 0.4, "sn": PLANTED["module_sn"]}]}}
    r["fk_firmware"] = [{"name": "ota", "version": "01.02.03.04"}, {"name": PLANTED["name"], "version": "1"},
                        {"name": "ams/0", "version": PLANTED["host"] + " " + PLANTED["ip"]}]
    return r


TRAIL = [{"scheme": "legacy", "job_file": "minimal", "final": "FAILED", "print_error": "0x0500C010", "sent": [0, 1, 2],
          "reported": [0, 1, 2], "fits": ["shift8", "legacy"]},
         {"scheme": PLANTED["name"], "job_file": PLANTED["job"], "final": PLANTED["job"], "print_error": PLANTED["ip"],
          "sent": [PLANTED["ip"], 3], "reported": ["x"], "fits": [PLANTED["host"]]}]


def test_no_owner_value_gets_into_the_report():
    text = printer_report.build(poisoned(), "N6", trail=TRAIL, wanted="job_failed").decode("utf-8")
    for what, value in PLANTED.items():
        assert value not in text, what


def test_a_new_field_shows_by_name_only():
    text = printer_report.build(poisoned(), "N6").decode("utf-8")
    assert "brand_new_field" in text and "brand_new_ams_field" in text


def test_a_key_of_a_strange_shape_is_left_out_too():
    r = {"192.0.2.77": 1, "Example Bench": 2, "plain_key": 3}
    text = printer_report.build(r, "N6").decode("utf-8")
    assert "192.0.2.77" not in text and "Example" not in text and "plain_key" in text


def test_it_says_what_a_maintainer_needs():
    root = ElementTree.fromstring(printer_report.build(poisoned(), "N6", trail=TRAIL, wanted="job_failed"))
    assert root.get("wanted") == "job_failed" and root.get("version") == "1"
    assert root.find("printer").get("model-code") == "N6" and root.find("printer").get("known") == "true"
    assert root.find("presence").get("tray-exist-bits") == "7"
    unit = root.find("layout/unit")
    assert unit.get("id") == "0" and unit.get("slots") == "4" and unit.find("slot").get("type")
    assert root.find("firmware").get("module") == "ota" and root.find("firmware").get("version") == "01.02.03.04"
    a = root.find("attempt")
    assert (a.get("scheme"), a.get("job-file"), a.get("final"), a.get("print-error")) == ("legacy", "minimal", "FAILED", "0x0500C010")
    assert a.findtext("sent") == "0 1 2" and a.findtext("reported") == "0 1 2" and a.findtext("fits") == "shift8 legacy"
    assert root.find("nozzle").get("diameter") == "0.4"


@pytest.mark.parametrize("report", [None, {}, {"ams": "x"}, {"ams": {"ams": ["x", {"id": "y", "tray": "z"}]}}, {"device": 3},
                                    {"fk_firmware": "no"}, {"vt_tray": 1, "vir_slot": "2"}])
def test_a_strange_report_never_stops_it(report):
    root = ElementTree.fromstring(printer_report.build(report, "N6", trail="nope"))
    assert root.tag == "printer-report"


def test_hostile_text_cannot_break_the_xml():
    r = {"ams": {"ams": [{"id": "0", "info": "<x>", "tray": [{"id": "0", "tray_type": "<&\"'>"}]}]}}
    assert ElementTree.fromstring(printer_report.build(r, '<evil model="1">'))


def test_the_file_name_holds_no_serial_and_only_the_last_few_stay(monkeypatch):
    assert SERIAL not in printer_report.file_name("N6") and "N6" in printer_report.file_name("N6")
    assert "evil" not in printer_report.file_name("../evil model")
    t = [100.0]
    monkeypatch.setattr(printer_report.time, "time", lambda: t[0])
    for i in range(printer_report.KEEP + 3):
        t[0] = 1000.0 + i
        printer_report.save(SERIAL, b"x", "N6")
    assert len(list((config.paths().state / "printers" / SERIAL).glob("printer-report-*.xml"))) == printer_report.KEEP


def test_firmware_from_version_takes_no_serial():
    info = {"command": "get_version", "module": [{"name": "ota", "sw_ver": "01.02", "sn": SERIAL, "hw_ver": "OTA"},
                                                 {"name": "x"}, "junk"]}
    assert connection.firmware_from_version(info) == [{"name": "ota", "version": "01.02"}]
    assert connection.firmware_from_version({"command": "other"}) == []


# ---------- report_wanted through a mapping ----------

@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state2"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    clients, made = [], []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c

    def start(report, model="N6"):
        m = Manager(client_factory=factory)
        registry.upsert(Printer(SERIAL, "Bench", model, "192.0.2.5", CODE, True))
        m.sync()
        printer = FakePrinter(clients[0], report)
        clients[0].connected(0)
        assert m.wait_report(SERIAL, lambda r: "gcode_state" in r, 2) is not None
        made.append(m)
        return m, printer
    yield start
    for m in made:
        m.stop()


def _result(**k):
    return lambda *a, **kw: calib3mf.CalibResult(**{"consistent": True, "scheme": "shift8", **k})


def _reports():
    return list((config.paths().state / "printers" / SERIAL).glob("printer-report-*.xml"))


def test_a_clean_map_of_a_known_printer_wants_nothing(rig, monkeypatch):
    monkeypatch.setattr(calib3mf, "run", _result())
    m, _ = rig(copy.deepcopy(REPORT))
    v = mapping.Mapper(m).run(SERIAL)
    assert v["report_wanted"] is None and _reports() == []


@pytest.mark.parametrize("wanted", printer_report.LOUD)
def test_an_unclean_mapping_says_why_and_keeps_a_report(rig, monkeypatch, wanted):
    monkeypatch.setattr(calib3mf, "run", _result(consistent=False, scheme=None, report_wanted=wanted,
                                                 problems=["x"], trail=TRAIL[:1]))
    m, _ = rig(copy.deepcopy(REPORT))
    v = mapping.Mapper(m).run(SERIAL)
    assert v["report_wanted"] == wanted and "trail" not in v
    (saved,) = _reports()
    root = ElementTree.fromstring(saved.read_bytes())
    assert root.get("wanted") == wanted and root.find("attempt").get("print-error") == "0x0500C010"


def test_a_model_the_kit_doesnt_know_is_said_quietly_and_keeps_no_report(rig, monkeypatch):
    monkeypatch.setattr(calib3mf, "run", _result())
    m, _ = rig(copy.deepcopy(REPORT), model="ZZ9")
    v = mapping.Mapper(m).run(SERIAL)
    assert v["calibrated"] is True and v["report_wanted"] == "unknown_model" and _reports() == []


def test_an_ams_module_the_file_has_no_type_for_is_said(rig, monkeypatch):
    monkeypatch.setattr(calib3mf, "run", _result())
    rep = copy.deepcopy(REPORT)
    rep["fk_modules"] = {"0": "Z9Q01"}
    m, _ = rig(rep)
    v = mapping.Mapper(m).run(SERIAL)
    assert v["calibrated"] is True and v["report_wanted"] == "unknown_ams" and _reports() == []


def test_report_wanted_survives_the_status_file(tmp_path, monkeypatch):
    class Nothing:
        def state(self, s):
            return "connected"
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True)
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "a", "state": "done", "step": "", "problems": [],
                                                     "report_wanted": "no_mapping"}), encoding="utf-8")
    assert mapping.Mapper(Nothing()).view(SERIAL)["report_wanted"] == "no_mapping"
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "a", "state": "done", "step": "", "problems": [],
                                                     "report_wanted": "<b>made up</b>"}), encoding="utf-8")
    assert mapping.Mapper(Nothing()).view(SERIAL)["report_wanted"] is None


def test_on_request_it_uses_the_live_report_and_the_last_attempts(rig, monkeypatch):
    monkeypatch.setattr(calib3mf, "run", _result(consistent=False, scheme=None, report_wanted="no_mapping", trail=TRAIL[:1],
                                                 problems=["x"]))
    m, _ = rig(copy.deepcopy(REPORT))
    mp = mapping.Mapper(m)
    mp.run(SERIAL)
    r = mp.report(SERIAL)
    assert r["name"].startswith("printer-report-N6-") and SERIAL not in r["name"] and SERIAL not in r["xml"]
    assert ElementTree.fromstring(r["xml"].encode()).find("attempt").get("final") == "FAILED"


def test_cli_makes_the_report(rig, capsys):
    m, _ = rig(copy.deepcopy(REPORT))
    assert cli.main(["printer", "report", SERIAL], manager_factory=lambda s: m) == 0
    out = capsys.readouterr().out
    assert "Printer report saved:" in out and "GitHub" in out


def test_cli_refuses_a_printer_it_doesnt_have(capsys):
    assert cli.main(["printer", "report", "NOPE"], manager_factory=lambda s: pytest.fail("connected")) == 1


def test_the_report_says_when_the_numbers_repeat_the_last_print():
    trail = [{**TRAIL[0], "repeats_last_print": True}]
    root = ElementTree.fromstring(printer_report.build({}, "N6", trail=trail))
    assert root.find("attempt").get("repeats-last-print") == "true"
    assert ElementTree.fromstring(printer_report.build({}, "N6", trail=TRAIL[:1])).find("attempt").get("repeats-last-print") is None


def test_calibration_records_what_each_job_did():
    from test_calib3mf import FakeManager  # noqa: F401 - the job paths are covered in test_calib3mf; the entry's shape here
    r = calib3mf.CalibResult(sent={"A1": 0}, mapping=[0], sent_scheme="legacy", job_file="minimal", final="FINISH", fits=["legacy"])
    assert calib3mf._trail_entry(r) == {"scheme": "legacy", "job_file": "minimal", "final": "FINISH", "print_error": None,
                                        "sent": [0], "reported": [0], "fits": ["legacy"],
                                        "repeats_last_print": False}


# ---------- the maintainer's side ----------

def _tool():
    spec = importlib.util.spec_from_file_location("hardware_from_report", ROOT / "tools" / "hardware_from_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_maintainer_gets_a_proposal_and_what_it_doesnt_prove():
    xml = printer_report.build(copy.deepcopy(REPORT), "ZZ9", trail=TRAIL[:1], wanted="unknown_model")
    out = _tool().propose(xml)
    assert 'code="ZZ9"' in out and '<numbering ref="shift8"/>' in out and "0x0500C010" in out
    assert "more than one scheme fits" in out


def test_the_tool_refuses_another_file():
    with pytest.raises(ValueError):
        _tool().propose(b"<other/>")


def test_the_issue_template_says_to_read_it_first():
    t = (ROOT / ".github/ISSUE_TEMPLATE/printer-report.md").read_text(encoding="utf-8")
    assert "open it and read it" in t and "printer report" in t
