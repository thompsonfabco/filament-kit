import copy
import re

import pytest

from filament_kit import config
from filament_kit.bridge import connection, registry, slottest
from filament_kit.bridge.connection import Manager, PrinterOffline
from filament_kit.bridge.registry import Printer
from fakes.fake_paho import FakeClient, FakePrinter

SERIAL = "S1"
FIELDS = ("tray_info_idx", "tray_color", "tray_type", "nozzle_temp_min", "nozzle_temp_max")
REPORT = {
    "gcode_state": "IDLE",
    "ams": {"ams": [
        {"id": "0", "tray": [
            {"id": "0", "tray_type": "PLA", "tray_color": "FF0000FF", "tray_info_idx": "Pa111111",
             "nozzle_temp_min": "190", "nozzle_temp_max": "230", "tray_sub_brands": ""},
            {"id": "1", "tray_type": "PETG", "tray_color": "1A1A1AFF", "tray_info_idx": "Pa735293",
             "nozzle_temp_min": "235", "nozzle_temp_max": "250", "tray_sub_brands": ""},
            {"id": "2", "tray_type": "ABS", "tray_color": "00FF00FF", "tray_info_idx": "Pa222222",
             "nozzle_temp_min": "240", "nozzle_temp_max": "270", "tray_sub_brands": ""},
            {"id": "3"},                                                   # empty slot
        ]},
        {"id": "128", "tray": [
            {"id": "0", "tray_type": "PA", "tray_color": "000000FF", "tray_info_idx": "Pa333333",
             "nozzle_temp_min": "260", "nozzle_temp_max": "290", "tray_sub_brands": ""}]},
    ]},
    "vt_tray": {"id": "254", "tray_type": "TPU", "tray_color": "FFFFFFFF", "tray_info_idx": "Pa444444",
                "nozzle_temp_min": "220", "nozzle_temp_max": "240", "tray_sub_brands": ""},
}
LABELS = ["A1", "A2", "A3", "A4", "HT-A", "Ext"]
ADDR = {"A1": (0, 0), "A2": (0, 1), "A3": (0, 2), "A4": (0, 3), "HT-A": (128, 0), "Ext": (254, 0)}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)


@pytest.fixture
def report():
    return REPORT


@pytest.fixture
def rig(report):
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c
    m = Manager(client_factory=factory)
    registry.upsert(Printer(SERIAL, "Office H2D", "O1D", "10.0.0.5", "13572468", True))
    m.sync()
    printer = FakePrinter(clients[0], report)
    clients[0].connected(0)
    assert m.wait_report(SERIAL, lambda r: "vt_tray" in r, 2) is not None
    yield m, printer, clients[0]
    m.stop()


def snapshot_colours(report=REPORT):
    trays = [t for u in report["ams"]["ams"] for t in u["tray"]] + [report["vt_tray"]]
    return {t["tray_color"].upper() for t in trays if t.get("tray_color")}


def expected_colours(report=REPORT):
    """The test colours slottest picks for slots 1..6 (from its own function, so nothing passes vacuously)."""
    taken, out = set(snapshot_colours(report)), []
    for n in range(1, len(LABELS) + 1):
        c = slottest.pick_test_colour(n, taken)
        taken.add(c)
        out.append(c)
    return out


TEST_COLOURS = set(expected_colours())


def is_test(colour):
    return str(colour).upper() in TEST_COLOURS


def original(label):
    ams_id, tray_id = ADDR[label]
    if label == "Ext":
        return REPORT["vt_tray"]
    unit = next(u for u in REPORT["ams"]["ams"] if u["id"] == str(ams_id))
    return next(t for t in unit["tray"] if t["id"] == str(tray_id))


def assert_back_to_original(printer, labels=LABELS):
    for label in labels:
        now = printer.tray(*ADDR[label])
        before = original(label)
        if len(before) == 1:                     # the empty slot: written and restored as empty
            assert now.get("tray_type", "") == "" and now.get("tray_info_idx", "") == ""
            assert not is_test(now.get("tray_color", ""))
        else:
            assert {k: now.get(k) for k in FIELDS} == {k: before.get(k) for k in FIELDS}, label


def no_test_colour_left(printer):
    return all(not is_test(printer.tray(*a).get("tray_color", "")) for a in ADDR.values())


def test_every_slot_confirmed_and_restored(rig):
    m, printer, c = rig
    steps = []
    res = slottest.run(m, SERIAL, steps.append)
    assert res.confirmed == {lab: {"ams_id": a, "tray_id": t} for lab, (a, t) in ADDR.items()}
    assert res.restored is True and res.problems == [] and res.needs_developer_mode is False
    tests = [w for w in printer.writes if is_test(w["tray_color"])]
    assert [w["tray_color"] for w in tests] == expected_colours()
    assert expected_colours() == [f"FA{n:02X}00FF" for n in range(1, 7)]      # no snapshot collides here
    assert all(re.fullmatch(r"[0-9A-F]{8}", c) for c in expected_colours())   # valid RRGGBBAA
    a2 = next(w for w in tests if (w["ams_id"], w["tray_id"]) == (0, 1))
    assert (a2["tray_info_idx"], a2["tray_type"], a2["nozzle_temp_min"], a2["nozzle_temp_max"]) == \
        ("Pa735293", "PETG", 235, 250)                       # the snapshot setting, only the colour differs
    a4 = next(w for w in tests if (w["ams_id"], w["tray_id"]) == (0, 3))
    assert (a4["tray_info_idx"], a4["tray_type"]) == ("", "")    # empty slot written like any other
    assert len(printer.writes) == 12                         # 6 test writes + 6 restores
    assert_back_to_original(printer)
    assert steps and any("A1" in s for s in steps) and any(s.startswith("Restoring") for s in steps)
    assert not (config.paths().state / "printers" / SERIAL / "slotmap.json").exists()   # Task 7 saves


def test_print_starting_mid_test_aborts_and_restores(rig):
    m, printer, c = rig
    respond = printer.respond

    def busy_on_second_write(topic, body):
        out = respond(topic, body)
        if len(printer.writes) == 2 and printer.report.get("gcode_state") == "IDLE":
            printer.report["gcode_state"] = "RUNNING"
            out = [{"print": {"gcode_state": "RUNNING"}}] + (out or [])
        return out
    c.responder = busy_on_second_write
    res = slottest.run(m, SERIAL, lambda s: None)
    assert res.confirmed == {"A1": {"ams_id": 0, "tray_id": 0}}
    assert any("printer_busy" in p for p in res.problems)
    for label in LABELS[1:]:
        assert any(p.startswith(f"{label}:") and "not confirmed" in p for p in res.problems), label
    assert res.restored is True
    assert_back_to_original(printer)
    tested = {(w["ams_id"], w["tray_id"]) for w in printer.writes if is_test(w["tray_color"])}
    assert tested == {(0, 0), (0, 1)}                        # nothing written after the print started


def test_refused_write_needs_developer_mode_and_restores_the_rest(rig):
    m, printer, c = rig
    printer.refuse[(0, 1)] = {"result": "fail", "reason": "mqtt message verify failed"}
    res = slottest.run(m, SERIAL, lambda s: None)
    assert res.needs_developer_mode is True
    assert any(p.startswith("needs_developer_mode") and "A2" in p for p in res.problems)
    assert res.confirmed == {"A1": {"ams_id": 0, "tray_id": 0}}
    for label in LABELS[1:]:
        assert any(p.startswith(f"{label}:") for p in res.problems), label
    assert res.restored is True
    assert_back_to_original(printer)
    assert {(w["ams_id"], w["tray_id"]) for w in printer.writes} == {(0, 0), (0, 1)}


def test_restore_failure_is_reported_never_silent(rig, monkeypatch):
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 0.3)
    m, printer, c = rig

    def on_step(step):
        if step.startswith("Restoring"):
            printer.frozen = True                            # the printer acks restores but keeps test colours
    res = slottest.run(m, SERIAL, on_step)
    assert len(res.confirmed) == 6
    assert res.restored is False
    for label in LABELS:
        assert any(p.startswith(f"{label}:") and "restore" in p for p in res.problems), label
    assert any("test colour" in p for p in res.problems)


def test_printer_going_offline_mid_test_reports_unrestored_slots(rig, monkeypatch):
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 0.5)
    m, printer, c = rig
    respond = printer.respond

    def drop_on_third_write(topic, body):
        out = respond(topic, body)
        if len(printer.writes) == 3:
            c.dropped()
            return None
        return out
    c.responder = drop_on_third_write
    res = slottest.run(m, SERIAL, lambda s: None)
    assert any("printer_offline" in p for p in res.problems)
    assert res.restored is False
    for label in ("A1", "A2", "A3"):
        assert any(p.startswith(f"{label}:") and "restore" in p for p in res.problems), label


def test_misaddressed_write_is_not_confirmed_and_both_slots_restored(rig):
    m, printer, c = rig
    printer.route[(0, 1)] = (0, 2)                            # A2's write lands on A3
    res = slottest.run(m, SERIAL, lambda s: None)
    assert "A2" not in res.confirmed
    assert any(p.startswith("A2:") and "A3" in p for p in res.problems)
    assert res.restored is True
    assert no_test_colour_left(printer)
    assert_back_to_original(printer, [l for l in LABELS if l != "A2"])


def test_refuses_to_start_when_busy_or_offline(rig):
    m, printer, c = rig
    printer.push({"gcode_state": "PREPARE"})
    assert m.wait_report(SERIAL, lambda r: r.get("gcode_state") == "PREPARE", 2)
    with pytest.raises(slottest.PrinterBusy):
        slottest.run(m, SERIAL, lambda s: None)
    c.dropped()
    with pytest.raises(PrinterOffline):
        slottest.run(m, SERIAL, lambda s: None)
    assert printer.writes == []


def test_pick_test_colour_skips_colours_a_slot_already_holds():
    assert slottest.pick_test_colour(1, set()) == "FA0100FF"
    assert slottest.pick_test_colour(11, set()) == "FA0B00FF"            # two hex digits
    assert slottest.pick_test_colour(1, {"FA0100FF"}) == "FB0100FF"
    assert slottest.pick_test_colour(1, {"fa0100ff", "FB0100FF"}) not in {"FA0100FF", "FB0100FF"}


COLLIDING = copy.deepcopy(REPORT)
COLLIDING["ams"]["ams"][0]["tray"][0]["tray_color"] = "FA0100FF"       # A1 already holds its default test colour
COLLIDING["ams"]["ams"][0]["tray"][1]["tray_color"] = "FA0300FF"       # A2 holds A3's default


@pytest.mark.parametrize("report", [COLLIDING])
def test_slot_already_holding_a_test_colour_refuses_the_test(rig, report):
    """C1 (final review): a test-colour-shaped colour may be a leftover of an interrupted run, so it is never taken
    as the slot's original: the test refuses before writing anything and names the slots."""
    m, printer, c = rig
    res = slottest.run(m, SERIAL, lambda s: None)
    assert printer.writes == [] and res.confirmed == {}
    assert [p.split(":")[0] for p in res.problems] == ["A1", "A2"]
    assert printer.tray(0, 0)["tray_color"] == "FA0100FF" and printer.tray(0, 1)["tray_color"] == "FA0300FF"


def test_restore_error_on_one_slot_is_reported_and_the_rest_restored(rig):
    m, printer, c = rig
    real = m.set_slot

    def set_slot(serial, ams_id, tray_id, setting, timeout=None):
        if (ams_id, tray_id) == (0, 1) and not is_test(setting["tray_color"]):
            raise RuntimeError("socket exploded")
        return real(serial, ams_id, tray_id, setting, timeout)
    m.set_slot = set_slot
    res = slottest.run(m, SERIAL, lambda s: None)
    assert res.restored is False
    assert any(p.startswith("A2: not restored (error:") and "socket exploded" in p for p in res.problems)
    assert_back_to_original(printer, [l for l in LABELS if l != "A2"])


def test_predicate_error_during_restore_is_reported_not_raised(rig, monkeypatch):
    m, printer, c = rig
    real = slottest._matches

    def matches(report, t):
        if t.label == "A3":
            raise ValueError("odd report")
        return real(report, t)
    monkeypatch.setattr(slottest, "_matches", matches)
    res = slottest.run(m, SERIAL, lambda s: None)
    assert res.restored is False
    assert any(p.startswith("A3: not restored (error:") for p in res.problems)
    assert_back_to_original(printer, [l for l in LABELS if l != "A3"])


def test_final_scan_error_is_reported_not_raised(rig):
    m, printer, c = rig
    real = m.wait_report
    zero_calls = []

    def wait_report(serial, predicate, timeout):
        if timeout == 0:
            zero_calls.append(1)
            if len(zero_calls) == 2:                       # the final scan (the first is the snapshot read)
                raise ValueError("odd report")
        return real(serial, predicate, timeout)
    m.wait_report = wait_report
    res = slottest.run(m, SERIAL, lambda s: None)
    assert res.restored is False
    assert any(p.startswith("final check failed") for p in res.problems)


def test_busy_abort_still_restores_a_slot_hit_by_a_misaddressed_write(rig):
    m, printer, c = rig
    printer.route[(0, 1)] = (0, 2)                            # A2's write lands on A3 ...
    respond = printer.respond

    def busy_with_second_write(topic, body):
        out = respond(topic, body)
        if len(printer.writes) == 2 and printer.report.get("gcode_state") == "IDLE":
            printer.report["gcode_state"] = "RUNNING"         # ... and a print starts in the same report
            out[-1]["print"]["gcode_state"] = "RUNNING"       # one report: colour on A3 and the job started
        return out
    c.responder = busy_with_second_write
    res = slottest.run(m, SERIAL, lambda s: None)
    assert any("printer_busy" in p for p in res.problems)
    assert res.restored is True
    assert no_test_colour_left(printer)
    assert_back_to_original(printer)
