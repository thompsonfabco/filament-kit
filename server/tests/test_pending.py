"""Pending slot assignments (bridge/pending.py): an assignment to a slot that is not clearly loaded waits for the
filament, is sent after the AMS's own reset, and is sent again when the AMS wipes the slot later."""
import logging

import pytest

from filament_kit import profiles
from filament_kit.bridge import connection, loading, pending, registry, status
from filament_kit.bridge.connection import Manager
from filament_kit.bridge.registry import Printer
from filament_kit.spoolman import Spoolman
from fakes.fake_paho import FakeClient, FakePrinter

SERIAL, NAME = "S1", "Office H2D"
FULL = {"id": "0", "state": 11, "tray_type": "PLA", "tray_color": "FF0000FF", "tray_info_idx": "Pa111111",
        "nozzle_temp_min": "190", "nozzle_temp_max": "230", "tray_sub_brands": ""}
EMPTY = {"id": "2", "state": 10}
WIPED = {"id": "2", "state": 27, "tray_type": "", "tray_info_idx": "", "tray_color": "00000000"}
RFID = dict(FULL, id="2", tray_info_idx="GFA00", tray_uuid="A1B2C3D4E5F60718293A4B5C6D7E8F90")


def report(a3, bits="7000f"):
    return {"gcode_state": "IDLE", "ams": {
        "tray_exist_bits": bits, "tray_reading_bits": "0",
        "ams": [{"id": "0", "tray": [dict(FULL, id="0"), dict(FULL, id="1"), a3, dict(FULL, id="3")]},
                {"id": "128", "tray": [dict(FULL, id="0")]}, {"id": "129", "tray": [dict(FULL, id="0")]},
                {"id": "130", "tray": [dict(FULL, id="0")]}]}}


PRESET = profiles.PresetRef(filament_id="P8a1b2c3", name="SUNLU PLA+ Grey @Bambu Lab H2D 0.4 nozzle",
                            nozzle_temp_min=200, nozzle_temp_max=230, filament_type="PLA", setting_id="")


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    monkeypatch.setattr(loading, "CONFIRM_TIMEOUT", 0.5)
    monkeypatch.setattr(profiles, "preset_for", lambda *a: PRESET)
    monkeypatch.setattr(pending, "STORE", pending.Store(start_thread=False))


@pytest.fixture
def rig():
    cs = []
    m = Manager(client_factory=lambda cid: cs.append(FakeClient(cid)) or cs[-1])
    registry.upsert(Printer(SERIAL, NAME, "O1D", "10.0.0.5", "13572468", True))
    m.sync()
    p = FakePrinter(cs[0], report(EMPTY, "7000b"))
    cs[0].connected(0)
    assert m.wait_report(SERIAL, lambda r: "ams" in r, 2) is not None
    yield m, p, cs[0]
    m.stop()


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    v = s.post("vendor", {"name": "SUNLU"})
    f = s.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA", "color_hex": "8a8c8e"})
    s.sp = s.post("spool", {"filament_id": f["id"], "location": "Rack 1"})
    s.sp2 = s.post("spool", {"filament_id": f["id"], "location": "Rack 1"})
    return s


@pytest.fixture
def store():
    return pending.Store(Clock(), start_thread=False)


def push(rig, a3, bits):
    m, p, _ = rig
    p.push({"ams": report(a3, bits)["ams"]})
    assert m.wait_report(SERIAL, lambda r: r["ams"]["tray_exist_bits"] == bits and
                         r["ams"]["ams"][0]["tray"][2].get("state") == a3.get("state"), 2) is not None


def a3(m):
    st = status.summarize(m.wait_report(SERIAL, lambda r: True, 0), [], model="O1D")
    return next(x for u in st["ams"] for x in u["slots"] if x["label"] == "A3")


def sends(c):
    return [b["print"] for _, b in c.published if b.get("print", {}).get("command") == "ams_filament_setting"]


def assign(rig, sm, store, spool=None):
    return pending.load_or_wait(rig[0], sm, SERIAL, "A3", (spool or sm.sp)["id"], False, store=store)


def run(store, n=1, dt=0.0):
    for _ in range(n):
        store.clock.t += dt
        store.tick()


def test_assign_to_an_empty_slot_waits_then_survives_the_wipe(rig, sm, store, caplog, monkeypatch):
    m, _, c = rig
    monkeypatch.setattr(pending, "STORE", store)             # Manager.status shows this store's waiting jobs
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        r = assign(rig, sm, store)
        assert r["pending"] is True and r["confirmed"] is None and "slot A3" in r["message"]
        assert sends(c) == [] and sm.get(f"spool/{sm.sp['id']}")["location"] == "Rack 1"   # nothing sent, no Spoolman
        shown = next(x for u in m.status(SERIAL)["ams"] for x in u["slots"] if x["label"] == "A3")["pending"]
        assert shown["text"] == "waiting for the spool to load in slot A3"
        run(store, 3, 5)
        assert sends(c) == []                              # still empty
        push(rig, EMPTY, "7000f")                          # filament in, the AMS has not wiped it yet
        run(store, 1, 1)                                   # seen
        run(store, 1, 1)
        assert sends(c) == []                              # settling
        run(store, 1, 3)
        assert len(sends(c)) == 1                          # sent
        push(rig, WIPED, "7000f")                          # the AMS's own reset lands after the send
        assert a3(m)["preset_id"] == ""
        run(store, 1, 2)
        assert len(sends(c)) == 2 and a3(m)["preset_id"] == "P8a1b2c3"       # set again
    assert sm.get(f"spool/{sm.sp['id']}")["location"] == f"{NAME} – AMS A3"
    msgs = [r.getMessage() for r in caplog.records if r.name.startswith("filament_kit")]
    assert sum(x.startswith("pending ") for x in msgs) == 1
    assert sum(x.startswith("applied ") for x in msgs) == 2 and not any(x.startswith("dropped") for x in msgs)


def test_unknown_presence_waits_instead_of_sending_blind(rig, sm, store):
    _, p, c = rig
    p.push({"ams": {"ams": report(EMPTY)["ams"]["ams"]}})       # no exist bits at all
    r = assign(rig, sm, store)
    assert r["pending"] is True and sends(c) == []


def test_a_loaded_slot_is_sent_at_once_and_cancels_the_older_one(rig, sm, store):
    _, _, c = rig
    assign(rig, sm, store)                                       # empty: waits
    assert set(store.jobs()) == {(SERIAL, "A3")}
    push(rig, dict(FULL, id="2"), "7000f")                       # now loaded with a type
    r = assign(rig, sm, store, sm.sp2)                           # a newer assignment goes at once
    assert "pending" not in r and r["confirmed"] is True and len(sends(c)) == 1
    assert store.jobs() == {}
    run(store, 5, 5)
    assert len(sends(c)) == 1                                    # the older one never sends


def test_a_newer_waiting_assignment_replaces_the_older(rig, sm, store):
    _, _, c = rig
    assign(rig, sm, store)
    assign(rig, sm, store, sm.sp2)
    assert [j.spool_id for j in store.jobs().values()] == [sm.sp2["id"]]
    push(rig, EMPTY, "7000f")
    run(store, 3, 4)
    assert len(sends(c)) == 1 and sm.get(f"spool/{sm.sp2['id']}")["location"] == f"{NAME} – AMS A3"
    assert sm.get(f"spool/{sm.sp['id']}")["location"] == "Rack 1"


def test_a_spool_with_its_own_rfid_is_not_overridden(rig, sm, store, caplog):
    _, _, c = rig
    assign(rig, sm, store)
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        push(rig, RFID, "7000f")
        run(store, 4, 4)
    assert sends(c) == [] and store.jobs() == {}
    assert any(r.getMessage().startswith("dropped") and "RFID" in r.getMessage() for r in caplog.records)


def test_expires_after_15_minutes(rig, sm, store, caplog):
    _, _, c = rig
    assign(rig, sm, store)
    with caplog.at_level(logging.INFO, logger="filament_kit"):
        run(store, 1, pending.TTL - 1)
        assert set(store.jobs()) == {(SERIAL, "A3")}
        run(store, 1, 2)
    assert store.jobs() == {} and sends(c) == []
    assert any(r.getMessage().startswith("dropped") and "15 min" in r.getMessage() for r in caplog.records)


def test_a_restart_drops_it(rig, sm, store):
    assign(rig, sm, store)
    assert store.jobs()
    assert pending.Store(Clock(), start_thread=False).jobs() == {}      # memory only: a new process has none


def test_a_removed_filament_ends_the_watch_and_another_setting_is_left_alone(rig, sm, store):
    _, _, c = rig
    assign(rig, sm, store)
    push(rig, EMPTY, "7000f")
    run(store, 3, 4)
    assert len(sends(c)) == 1 and store.jobs()
    push(rig, EMPTY, "7000b")                                    # taken out
    run(store, 1, 2)
    assert store.jobs() == {}
    assign(rig, sm, store)
    push(rig, EMPTY, "7000f")
    run(store, 3, 4)
    push(rig, dict(FULL, id="2", tray_info_idx="Pa999999", tray_type="PETG"), "7000f")   # the user set another
    run(store, 2, 2)
    assert store.jobs() == {} and len(sends(c)) == 2


def test_a_refusal_that_waiting_does_not_change_drops_it(rig, sm, store, monkeypatch):
    _, _, c = rig
    assign(rig, sm, store)
    monkeypatch.setattr(profiles, "preset_for", lambda *a: None)
    push(rig, EMPTY, "7000f")
    run(store, 3, 4)
    assert store.jobs() == {} and sends(c) == []


def test_dry_run_and_a_missing_preset_do_not_queue(rig, sm, store, monkeypatch):
    r = pending.load_or_wait(rig[0], sm, SERIAL, "A3", sm.sp["id"], True, store=store)
    assert "pending" not in r and store.jobs() == {}
    monkeypatch.setattr(profiles, "preset_for", lambda *a: None)
    with pytest.raises(loading.NoPreset):
        assign(rig, sm, store)
    assert store.jobs() == {}
