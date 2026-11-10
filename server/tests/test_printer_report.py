"""The printer report holds no owner data, says what happened, and a maintainer can read it."""
from __future__ import annotations

import copy
import importlib.util
import json
import time
from pathlib import Path

import pytest
from defusedxml import ElementTree

from fakes.fake_paho import FakeClient, FakePrinter
from filament_kit import cli, config
from filament_kit.bridge import ams, calib3mf, connection, mapping, printer_report, registry
from filament_kit.bridge.connection import Manager, PrinterOffline
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


@pytest.mark.parametrize("value", [SERIAL, PLANTED["ip"], PLANTED["host"], "0123456789AB"])
def test_a_serial_address_or_host_in_a_copied_name_is_left_out(value):
    r = {"ams": {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": value}]}]},
         "fk_firmware": [{"name": value, "version": "01.02"}, {"name": "ota", "version": value}]}
    assert value not in printer_report.build(r, value).decode("utf-8")
    assert value not in printer_report.file_name(value)


def test_a_real_module_type_and_model_still_go_in():
    r = {"ams": {"ams": [{"id": "0", "info": "10003003", "tray": [{"id": "0", "tray_type": "PETG-HF"}]}]},
         "fk_firmware": [{"name": "ams_f1/0", "version": "00.00.06.49"}]}
    text = printer_report.build(r, "BL-P001").decode("utf-8")
    for want in ("PETG-HF", "ams_f1/0", "00.00.06.49", "BL-P001", "10003003"):
        assert want in text, want
    assert printer_report.file_name("BL-P001").startswith("printer-report-BL-P001-")


@pytest.mark.parametrize("name", ["3DPrinter-X1-Carbon", "3DPrinter-X1"])
def test_a_known_model_reported_by_a_long_name_keeps_its_code(name):
    from filament_kit.bridge import hardware
    code = hardware.load().model(name).code
    assert code and f'model-code="{code}"' in printer_report.build({}, name).decode("utf-8")
    assert printer_report.file_name(name).startswith(f"printer-report-{code}-")


def test_someones_name_for_the_printer_is_not_a_model_code():
    assert 'model-code' not in printer_report.build({}, "kitchen-printer").decode("utf-8")
    assert "kitchen" not in printer_report.file_name("kitchen-printer")


@pytest.mark.parametrize("key", ["0948zz0a0000001", "user_4242424242"])
def test_a_key_with_an_id_in_it_is_left_out(key):
    assert key not in printer_report.build({key: 1, "ams_rfid_status": 2}, "N6").decode("utf-8")
    assert "ams_rfid_status" in printer_report.build({key: 1, "ams_rfid_status": 2}, "N6").decode("utf-8")


def test_every_reason_has_its_sentence_and_none_claims_the_wrong_thing():
    for w in printer_report.WANTED:
        assert printer_report.why(w)
    assert printer_report.why(None) is None
    assert "doesn't know" not in printer_report.why("job_refused")


def test_the_issue_template_offers_only_what_exists():
    text = (ROOT / ".github/ISSUE_TEMPLATE/printer-report.md").read_text(encoding="utf-8")
    assert "the app" not in text and "web app" in text and "printer report <serial>" in text


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


# ---------------------------------------------------------------- the printer cannot be reached (a live case, 2026-11-10)

class Gone:
    """A Manager whose printer never answers."""

    def state(self, s):
        return "disconnected"

    def wait_report(self, serial, predicate, timeout):
        return None

    def wait_settled(self, serial, timeout):
        return "offline"

    def sync(self):
        pass

    def stop(self):
        pass


def _saved_map():
    registry.upsert(registry.Printer(SERIAL, "", "N6", "192.0.2.5", "12345678", True))
    smap = ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0},
                              "A2": {"ams_id": 0, "tray_id": 1, "global_id": 1}}, calibrated=True, scheme="shift8",
                       fingerprint=[[0, "ams", 4], [255, None, 1]])
    ams.save_map(SERIAL, smap)
    d = config.paths().state / "printers" / SERIAL
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "a", "state": "failed", "step": "", "problems": ["x"],
                                                     "reason": "offline", "finished": 1762800000, "trail": TRAIL[:1],
                                                     "report_wanted": "no_mapping"}), encoding="utf-8")


def test_an_unreachable_printer_gets_a_report_from_what_the_kit_saved():
    _saved_map()
    r = mapping.Mapper(Gone()).report(SERIAL)
    assert r["live"] is False and r["saved_until"] and SERIAL not in r["xml"] and "192.0.2.5" not in r["xml"]
    root = ElementTree.fromstring(r["xml"].encode())
    assert root.get("live") == "false" and root.get("saved-until") and root.get("wanted") == "no_mapping"
    assert root.get("hardware-file")
    saved = root.find("saved")
    assert [u.get("id") for u in saved.findall("unit")] == ["0", "255"]
    m = saved.find("map")
    assert m.get("calibrated") == "true" and m.get("scheme") == "shift8"
    assert [(s.get("label"), s.get("tray-id")) for s in m.findall("slot")] == [("A1", "0"), ("A2", "1")]
    assert saved.find("last-mapping").get("reason") == "offline" and root.find("attempt") is not None
    assert root.find("layout") is None and root.find("firmware") is None     # nothing live is made up
    assert "x" not in [e.text for e in root.iter()]                           # no free text from a failure


def test_a_printer_the_kit_never_saw_is_refused():
    with pytest.raises(PrinterOffline):
        mapping.Mapper(Gone()).report("0948ZZ0A0000009")


def test_the_cli_says_the_report_is_from_saved_records(capsys, monkeypatch):
    monkeypatch.setattr(cli, "CONNECT_WAIT", 0.3)        # an unreachable printer is waited for that long first
    _saved_map()
    assert cli.main(["printer", "report", SERIAL], manager_factory=lambda s: Gone()) == 0
    out = capsys.readouterr().out
    assert "could not be reached" in out and "built from what the kit saved" in out and "Printer report saved:" in out
    assert "Not reached: the printer did not answer" in out


# ---------------------------------------------------------------- the running server holds the printer (live bug, 2026-11-10)

class ServerApi:
    """The running kit server's API as cli._server_api gives it: it holds the printer's connection."""

    def __init__(self, map_states=None):
        self.posts, self.gets = [], []
        self.map_states = list(map_states or [])

    def post(self, path, body):
        self.posts.append(path)
        if path.endswith("/report"):
            return {"name": "printer-report-N6-20261110-120000.xml", "xml": "<printer-report/>", "live": True,
                    "saved_until": None}
        return {"job_id": "j1"}

    def get(self, path):
        self.gets.append(path)
        return self.map_states.pop(0)


def test_the_cli_report_asks_the_running_server(monkeypatch, capsys):
    registry.upsert(registry.Printer(SERIAL, "", "N6", "192.0.2.5", "12345678", True))
    api = ServerApi()
    monkeypatch.setattr(cli, "_server_api", lambda: api)
    assert cli.main(["printer", "report", SERIAL], manager_factory=lambda s: pytest.fail("a second connection")) == 0
    assert api.posts == [f"/api/printers/{SERIAL}/report"]
    out = capsys.readouterr().out
    assert "printer-report-N6-20261110-120000.xml" in out and "could not be reached" not in out


def test_the_cli_map_follows_the_servers_job(monkeypatch, capsys):
    registry.upsert(registry.Printer(SERIAL, "", "N6", "192.0.2.5", "12345678", True))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    done = {"state": "done", "step": "", "slots": [{"label": "A1", "ams_id": 0, "tray_id": 0, "global": 0}],
            "problems": [], "notes": [], "outcome": "confirmed", "outcome_text": "Mapped and confirmed.", "next_step": ""}
    api = ServerApi([{"state": "running", "step": "Reading the AMS slots"}, {"state": "running", "step": "Reading the AMS slots"},
                     {"state": "running", "step": "Running the calibration job"}, done])
    monkeypatch.setattr(cli, "_server_api", lambda: api)
    assert cli.main(["printer", "map", SERIAL], manager_factory=lambda s: pytest.fail("a second connection")) == 0
    out = capsys.readouterr().out
    assert api.posts == [f"/api/printers/{SERIAL}/map"]
    assert out.count("Reading the AMS slots") == 1 and "Running the calibration job" in out
    assert "A1: AMS 0 tray 0 -> printer slot 0" in out and "Mapped and confirmed." in out


def test_the_cli_says_what_the_server_refused(monkeypatch, capsys):
    from filament_kit.web.slots import SlotError
    registry.upsert(registry.Printer(SERIAL, "", "N6", "192.0.2.5", "12345678", True))

    class Busy(ServerApi):
        def post(self, path, body):
            raise SlotError("slot mapping is already running for this printer", code="already_running", http=409)
    monkeypatch.setattr(cli, "_server_api", lambda: Busy())
    assert cli.main(["printer", "map", SERIAL], manager_factory=lambda s: pytest.fail("a second connection")) == 1
    assert "already running" in capsys.readouterr().err


def test_every_interface_offers_the_report():
    """Interface parity (2026-11-10): the setup page and the phone web app offer it for every Bambu printer, not only
    when a report would help; the command line has `printer report`; the API route is what they all call."""
    root = Path(__file__).resolve().parents[1] / "filament_kit"
    phone = (root / "web" / "static" / "printers.js").read_text(encoding="utf-8")
    assert 'h("button", { class: m.report_wanted ? "" : "secondary", textContent: "Collect a report"' in phone
    page = (root / "setup_static" / "setup_printers.js").read_text(encoding="utf-8")
    assert 'textContent: "Collect a report", on: { click: () => collectReport(p, reportBox) }' in page
# ---------------------------------------------------------------- a real printer takes a moment to connect (live bug)

@pytest.fixture
def slow(tmp_path, monkeypatch):
    """A Manager whose printer answers 0.4 s after the connection starts, as a real one does (TLS, then MQTT)."""
    import threading
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state3"))
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c

    def make(report, rc=0, refused_first=False):
        registry.upsert(Printer(SERIAL, "Bench", "N6", "192.0.2.5", CODE, True))
        m = Manager(client_factory=factory)
        real_sync = m.sync

        def sync():
            real_sync()
            c = clients[0]
            FakePrinter(c, report)
            if refused_first:        # the first attempt fails (printer still booting); paho's retry gets through
                threading.Timer(0.1, lambda: c.on_connect_fail(c, None)).start()
                threading.Timer(1.0, c.connected, args=(rc,)).start()
            else:
                threading.Timer(0.4, c.connected, args=(rc,)).start()
        m.sync = sync
        return m
    return make


@pytest.mark.parametrize("command", ["report", "map"])
def test_the_cli_waits_for_a_printer_that_takes_a_moment_to_connect(slow, monkeypatch, capsys, command):
    monkeypatch.setattr(calib3mf, "run", _result())
    m = slow(copy.deepcopy(REPORT))
    rc = cli.main(["printer", command, SERIAL], manager_factory=lambda s: m)
    out, err = capsys.readouterr()
    assert "offline" not in err and "did not answer" not in err, err
    assert rc == 0 and ("Printer report saved:" in out if command == "report" else "A1:" in out), out + err


def test_a_wrong_access_code_is_said_as_such(slow, capsys):
    m = slow(copy.deepcopy(REPORT), rc=5)        # MQTT: not authorized
    assert cli.main(["printer", "report", SERIAL], manager_factory=lambda s: m) == 1
    assert "Access Code" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["report", "map"])
def test_a_refused_first_attempt_does_not_end_the_wait(slow, monkeypatch, capsys, command):
    """R102: a printer still booting refuses the first attempt (settled as offline); the CLI keeps waiting for
    paho's retry until CONNECT_WAIT instead of saying "did not answer" at once."""
    monkeypatch.setattr(calib3mf, "run", _result())
    m = slow(copy.deepcopy(REPORT), refused_first=True)
    rc = cli.main(["printer", command, SERIAL], manager_factory=lambda s: m)
    out, err = capsys.readouterr()
    assert "did not answer" not in err, err
    assert rc == 0 and ("Printer report saved:" in out if command == "report" else "A1:" in out), out + err


def test_a_printer_that_never_comes_up_is_said_after_the_wait(slow, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONNECT_WAIT", 0.6)
    m = slow(copy.deepcopy(REPORT))
    m.sync = Manager.sync.__get__(m)          # the connection starts; the printer never answers
    t = time.monotonic()
    assert cli.main(["printer", "report", SERIAL], manager_factory=lambda s: m) == 1
    assert time.monotonic() - t >= 0.5
    assert "did not answer" in capsys.readouterr().err


def test_a_wrong_access_code_stops_the_wait_at_once(slow, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONNECT_WAIT", 10.0)
    m = slow(copy.deepcopy(REPORT), rc=5)
    t = time.monotonic()
    assert cli.main(["printer", "report", SERIAL], manager_factory=lambda s: m) == 1
    assert time.monotonic() - t < 3.0
    assert "Access Code" in capsys.readouterr().err
