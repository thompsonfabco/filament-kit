"""Klipper loads, unloads and follow mode: Spoolman locations follow what the printer shows (spec §6)."""
import json
import threading
import time
from pathlib import Path

import pytest

from filament_kit.bridge import loading, registry, status
from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper import loads
from filament_kit.bridge.klipper.manager import KlipperFamily
from filament_kit.spoolman import Spoolman

DATA = Path(__file__).parent / "data" / "klipper"
LOC = "SV08 MAX – T0"


def wait_for(pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.03)
    return False


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setattr(loads, "CONFIRM_TIMEOUT", 2.0)
    kh._reset_cache()
    yield
    kh._reset_cache()


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def fil(sm):
    v = sm.post("vendor", {"name": "SUNLU"})
    return sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA", "color_hex": "8a8c8e"})


def spool(sm, fil, location, prev=None):
    extra = {} if prev is None else {"prev_location": json.dumps(prev)}
    return sm.post("spool", {"filament_id": fil["id"], "location": location, "extra": extra})


def loc_of(sm, sid):
    return sm.get(f"spool/{sid}")["location"]


def prev_of(sm, sid):
    return json.loads((sm.get(f"spool/{sid}").get("extra") or {}).get("prev_location") or '""')


@pytest.fixture
def printer(moonraker, sm):
    moonraker.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    moonraker.status = json.loads((DATA / "SV08-MAX" / "status.json").read_text())
    moonraker.hostname = "SV08MAX"
    pid = registry.add_klipper("SV08 MAX", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    yield fam, pid, moonraker
    fam.stop()


def test_location_formats():
    assert status.location("SV08 MAX", "T0", family="klipper") == LOC
    assert status.location("H2D", "A1") == "H2D – AMS A1"           # Bambu unchanged


def test_dry_run_changes_nothing(printer, sm, fil):
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 2")
    r = fam.load(sm, pid, "T0", s["id"], True, sealed_location="Sealed stock")
    assert r["dry_run"] is True and r["confirmed"] is None
    assert r["command"] == {"gcode": f"SET_ACTIVE_SPOOL ID={s['id']}"}
    assert r["slot"]["location"] == LOC
    assert fake.gcode_log == [] and loc_of(sm, s["id"]) == "Shelf 2"


def test_load_confirmed_moves_location(printer, sm, fil):
    fam, pid, fake = printer
    old = spool(sm, fil, LOC, prev="Shelf 1")
    new = spool(sm, fil, "Shelf 2")
    r = fam.load(sm, pid, "T0", new["id"], False, sealed_location="Sealed stock")
    assert r["confirmed"] is True, r["problems"]
    assert fake.gcode_log == [f"SET_ACTIVE_SPOOL ID={new['id']}"]
    assert loc_of(sm, new["id"]) == LOC and prev_of(sm, new["id"]) == "Shelf 2"
    assert loc_of(sm, old["id"]) == "Shelf 1"
    assert r["moved_back"] == [{"id": old["id"], "location": "Shelf 1"}]


def test_load_not_confirmed_no_spoolman_write(printer, sm, fil):
    fam, pid, fake = printer
    fake.ignore_gcode = True
    s = spool(sm, fil, "Shelf 2")
    r = fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")
    assert r["confirmed"] is False and "not confirmed" in r["problems"][0]
    assert loc_of(sm, s["id"]) == "Shelf 2"


def test_load_gcode_refused_word_for_word(printer, sm, fil):
    fam, pid, fake = printer
    fake.gcode_errors["SET_ACTIVE_SPOOL"] = "Unknown command:\"SET_ACTIVE_SPOOL\""
    s = spool(sm, fil, "Shelf 2")
    r = fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")
    assert r["confirmed"] is False
    assert any("Unknown command" in p for p in r["problems"])
    assert loc_of(sm, s["id"]) == "Shelf 2"


def test_load_ws_drop_mid_confirm(printer, sm, fil):
    """Review Focus 1: the websocket closes between the gcode and the confirmation → not confirmed, no write."""
    fam, pid, fake = printer
    fake.ignore_gcode = True                 # the printer takes the gcode but no update arrives ...
    s = spool(sm, fil, "Shelf 2")

    def drop_soon():
        time.sleep(0.2)
        fake.drop()
    threading.Thread(target=drop_soon).start()
    t0 = time.monotonic()
    r = fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")
    assert time.monotonic() - t0 < loads.CONFIRM_TIMEOUT - 0.5     # the drop ended the wait, not the timeout
    assert r["confirmed"] is False
    assert loc_of(sm, s["id"]) == "Shelf 2"


def test_load_notices_a_drop_it_only_sees_the_end_of(printer, sm, fil, monkeypatch):
    """The drop comes and the reconnect is done between two looks at `connected` (a busy machine; the reviewer's flaky
    run of the test above): the next look ends the wait, instead of the wait running out. Counted, not timed."""
    fam, pid, fake = printer
    fake.ignore_gcode = True
    s = spool(sm, fil, "Shelf 2")
    real_wait, real_model = fam._wait_shows, fam.model
    looks = []
    waiter = []                 # the follow thread calls model() as well when the printer reconnects

    def wait_shows(*a):
        waiter.append(threading.current_thread())
        try:
            return real_wait(*a)
        finally:
            waiter.clear()

    def model(p):
        if threading.current_thread() in waiter:
            looks.append(1)
            if len(looks) == 1:
                sub = fam._conn(pid).sub
                before = sub.drops
                fake.drop()
                assert wait_for(lambda: sub.drops > before and sub.connected)
        return real_model(p)
    monkeypatch.setattr(fam, "_wait_shows", wait_shows)
    monkeypatch.setattr(fam, "model", model)
    r = fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")
    assert len(looks) == 1 and r["confirmed"] is False
    assert loc_of(sm, s["id"]) == "Shelf 2"


def test_load_refused_while_printing(printer, sm, fil):
    fam, pid, fake = printer
    fake.push({"print_stats": {"state": "printing"}})
    assert wait_for(lambda: fam.status(pid)["gcode_state"] == "RUNNING")
    s = spool(sm, fil, "Shelf 2")
    with pytest.raises(loading.SlotInUse):
        fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")
    fake.push({"print_stats": {"state": "paused"}})
    assert wait_for(lambda: fam.status(pid)["gcode_state"] == "PAUSE")
    assert fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")["confirmed"] is True


def test_load_unknown_slot_and_spool(printer, sm, fil):
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 2")
    with pytest.raises(loading.NotFound):
        fam.load(sm, pid, "T5", s["id"], True, sealed_location="Sealed stock")
    with pytest.raises(loading.NotFound):
        fam.load(sm, pid, "T0", 9999, True, sealed_location="Sealed stock")


def test_tap_follow_mode(printer, sm, fil):
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 3")
    fake.set_spool(s["id"])                  # an nfc2klipper tap runs SET_ACTIVE_SPOOL on the printer
    assert wait_for(lambda: loc_of(sm, s["id"]) == LOC)
    assert prev_of(sm, s["id"]) == "Shelf 3"
    fake.set_spool(None)                     # CLEAR_ACTIVE_SPOOL on the printer → back to its shelf
    assert wait_for(lambda: loc_of(sm, s["id"]) == "Shelf 3")


def _spoolman_fails_once(fam, monkeypatch):
    real, calls = fam._move, []

    def flaky(*a, **kw):
        calls.append(a)
        if len(calls) == 1:
            raise OSError("Spoolman unreachable")
        return real(*a, **kw)
    monkeypatch.setattr(fam, "_move", flaky)
    return calls


def test_follow_retries_a_tap_when_spoolman_was_down(printer, sm, fil, monkeypatch):
    """FA-066: a spool change made while Spoolman fails is applied on the next update, not lost."""
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 3")
    calls = _spoolman_fails_once(fam, monkeypatch)
    fake.set_spool(s["id"])
    assert wait_for(lambda: len(calls) == 1)
    time.sleep(0.2)
    assert loc_of(sm, s["id"]) == "Shelf 3"
    fam._follow_q.put(pid)                   # the next update
    assert wait_for(lambda: loc_of(sm, s["id"]) == LOC)


def test_follow_retries_an_unload_when_spoolman_was_down(printer, sm, fil, monkeypatch):
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 3")
    fake.set_spool(s["id"])
    assert wait_for(lambda: loc_of(sm, s["id"]) == LOC)
    calls = _spoolman_fails_once(fam, monkeypatch)
    fake.set_spool(None)
    assert wait_for(lambda: len(calls) == 1)
    time.sleep(0.2)
    assert loc_of(sm, s["id"]) == LOC
    fam._follow_q.put(pid)
    assert wait_for(lambda: loc_of(sm, s["id"]) == "Shelf 3")


def test_connect_reconcile_is_retried_when_spoolman_was_down(moonraker, sm, fil, monkeypatch):
    s = spool(sm, fil, "Shelf 1")
    moonraker.set_spool(s["id"])
    pid = registry.add_klipper("Voron", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    calls = _spoolman_fails_once(fam, monkeypatch)
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "unknown_model"
        assert wait_for(lambda: len(calls) == 1)
        fam._follow_q.put(pid)               # the next update (the connect's own follow-up may already have done it)
        assert wait_for(lambda: loc_of(sm, s["id"]) == "Voron – T0")
    finally:
        fam.stop()


def test_tap_during_kit_load(printer, sm, fil):
    """Review Focus 2: a kit load of spool A is in flight and a tap sets spool B → one spool ends in the slot,
    the one the printer shows."""
    fam, pid, fake = printer
    a = spool(sm, fil, "Shelf A")
    b = spool(sm, fil, "Shelf B")
    fake.ignore_gcode = True                 # the kit's gcode never lands; the tap does

    def tap():
        time.sleep(0.3)
        fake.set_spool(b["id"])
    threading.Thread(target=tap).start()
    r = fam.load(sm, pid, "T0", a["id"], False, sealed_location="Sealed stock")
    assert r["confirmed"] is False
    assert wait_for(lambda: loc_of(sm, b["id"]) == LOC)
    here = [x["id"] for x in sm.get("spool") if x.get("location") == LOC]
    assert here == [b["id"]]
    assert loc_of(sm, a["id"]) == "Shelf A"


def test_connect_reconciles_what_the_printer_shows(moonraker, sm, fil):
    """Final review I4: a tap while the kit was not running. At connect the printer's spool wins: it moves into the
    slot and the spool Spoolman still had there goes back to its shelf."""
    old = spool(sm, fil, "Voron – T0", prev="Shelf 5")
    s = spool(sm, fil, "Shelf 1")
    moonraker.set_spool(s["id"])             # set on the printer before the kit connects
    pid = registry.add_klipper("Voron", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "unknown_model"
        assert wait_for(lambda: loc_of(sm, s["id"]) == "Voron – T0")
        assert loc_of(sm, old["id"]) == "Shelf 5"
    finally:
        fam.stop()


def test_connect_reconciles_even_when_the_first_follow_check_came_too_early(moonraker, sm, fil, monkeypatch):
    """The FLAKY run of the test above (v0.4.2 pre-tag): the first snapshot's follow check ran before the subscriber
    was marked connected, did nothing, and nothing asked again until the printer's next change. Here the first check is
    made to do nothing on purpose; set-up asks once more after the snapshot, so the reconcile still happens.

    Set-up's request waits for that first check: a follow thread that wakes late would otherwise take both requests as
    one check (`_follow_run` coalesces them), and the stub would swallow the only one."""
    checks: list[str] = []
    first_done = threading.Event()
    real = KlipperFamily._follow_check

    def first_one_too_early(self, pid):
        checks.append(pid)
        if len(checks) == 1:
            first_done.set()
            return
        real(self, pid)
    monkeypatch.setattr(KlipperFamily, "_follow_check", first_one_too_early)
    old = spool(sm, fil, "Voron – T0", prev="Shelf 5")
    s = spool(sm, fil, "Shelf 1")
    moonraker.set_spool(s["id"])
    pid = registry.add_klipper("Voron", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    put = fam._follow_q.put

    def set_up_waits_for_the_first_check(item):
        if not threading.current_thread().name.startswith("moonraker-"):     # the subscriber's own requests go at once
            first_done.wait(8)
        put(item)
    monkeypatch.setattr(fam._follow_q, "put", set_up_waits_for_the_first_check)
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "unknown_model"
        assert wait_for(lambda: loc_of(sm, s["id"]) == "Voron – T0")
        assert loc_of(sm, old["id"]) == "Shelf 5" and len(checks) >= 2
    finally:
        fam.stop()


def test_connect_leaves_spoolman_alone_when_the_printer_shows_none(moonraker, sm, fil):
    """Moonraker forgets its active spool on a restart: an empty printer slot is no reason to unload Spoolman."""
    s = spool(sm, fil, "Voron – T0", prev="Shelf 5")
    pid = registry.add_klipper("Voron", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "unknown_model"
        time.sleep(0.5)
        assert loc_of(sm, s["id"]) == "Voron – T0"
    finally:
        fam.stop()


def test_unknown_spool_on_the_printer_changes_nothing(printer, sm, fil, caplog):
    """Final review I3: the printer shows a spool this Spoolman does not have (another Spoolman, a deleted spool)."""
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 1")
    assert fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")["confirmed"] is True
    import logging
    with caplog.at_level(logging.WARNING):
        fake.set_spool(99999)
        time.sleep(1.0)
        for i in range(5):                   # more updates must not repeat the attempt
            fake.push({"print_stats": {"print_duration": float(i)}})
        time.sleep(0.5)
    assert loc_of(sm, s["id"]) == LOC        # nothing sent back for a spool we cannot place
    assert sum("99999" in r.getMessage() for r in caplog.records) == 1
    assert not any(r.levelname == "ERROR" for r in caplog.records)
    s2 = spool(sm, fil, "Shelf 2")
    fake.set_spool(s2["id"])                 # a real spool afterwards still follows
    assert wait_for(lambda: loc_of(sm, s2["id"]) == LOC)


def test_renamed_printer_keeps_prev(printer, sm, fil):
    """Review Focus 3: spools sitting in a renamed printer keep their shelf as prev_location."""
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 1")
    assert fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")["confirmed"] is True
    registry.rename(pid, "Big Sovol")
    # the spool still says "SV08 MAX – T0"; a load into the renamed printer must not make that its shelf
    fake.set_spool(None)
    t = spool(sm, fil, "Shelf 9")
    fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")
    assert loc_of(sm, s["id"]) == "Big Sovol – T0"
    assert prev_of(sm, s["id"]) == "Shelf 1"
    assert loc_of(sm, t["id"]) == "Shelf 9"


def test_unload_sends_back_and_clears(printer, sm, fil):
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 1")
    assert fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")["confirmed"] is True
    r = fam.unload(sm, pid, "T0", False, sealed_location="Sealed stock")
    assert r["moved_back"] == [{"id": s["id"], "location": "Shelf 1"}]
    assert fake.gcode_log[-1] == "CLEAR_ACTIVE_SPOOL"
    assert loc_of(sm, s["id"]) == "Shelf 1"
    with pytest.raises(loading.NotFound):
        fam.unload(sm, pid, "T0", False, sealed_location="Sealed stock")


def test_unload_of_a_slot_with_no_safe_gcode_is_a_not_found(printer, sm, fil, monkeypatch):
    from filament_kit.bridge.klipper.adapters.base import UnknownSlot
    fam, pid, fake = printer
    s = spool(sm, fil, "Shelf 1")
    assert fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")["confirmed"] is True

    def refuse(self, *a, **kw):
        raise UnknownSlot("lane name not usable in gcode")
    monkeypatch.setattr(type(fam.model(pid)[2]), "clear_gcode", refuse)
    with pytest.raises(loading.NotFound, match="T0"):
        fam.unload(sm, pid, "T0", False, sealed_location="Sealed stock")
    assert loc_of(sm, s["id"]) == LOC        # nothing moved


def test_unload_offline_is_spoolman_only(sm, fil):
    pid = registry.add_klipper("Gone", "127.0.0.1", 9).serial
    s = spool(sm, fil, "Gone – T0", prev="Shelf 4")
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 5)
        r = fam.unload(sm, pid, "T0", False, sealed_location="Sealed stock")
        assert r["moved_back"] == [{"id": s["id"], "location": "Shelf 4"}]
    finally:
        fam.stop()


def test_nozzle_from_klipper_config(printer, sm, fil):
    fam, pid, fake = printer
    fake.status["configfile"] = {"settings": {"extruder": {"nozzle_diameter": 0.6}}}
    fam.sync()
    c = fam._conn(pid)
    c._again.set()                       # set up again: re-reads the config
    assert wait_for(lambda: fam._nozzle(pid) == (0.6, False))
    s = spool(sm, fil, "Shelf 2")
    r = fam.load(sm, pid, "T0", s["id"], True, sealed_location="Sealed stock")
    assert (r["nozzle_mm"], r["nozzle_assumed"], r["preset"]) == (0.6, False, None)


def test_nozzle_assumed_from_xml(printer):
    fam, pid, fake = printer
    assert fam._nozzle(pid) == (0.4, True)
