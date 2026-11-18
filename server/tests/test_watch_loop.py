"""The 5-minute loop: disk, low spools, the Weigh Station, Checks rows, retention (R80 sections 3, 6, 7, E2, E3)."""
from collections import namedtuple
from datetime import datetime, timezone

import pytest

from filament_kit import alerts, config, event_sink, inventory, station_client, watch
from filament_kit.event_sink import StoreSink
from filament_kit.events import EventStore
from filament_kit.spoolman import SpoolmanError
from filament_kit.status import Row

Usage = namedtuple("Usage", "total used free")
GB = 1000 ** 3


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "backups"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    alerts.reset()
    monkeypatch.setattr(alerts.shutil, "disk_usage",           # a roomy disk, whatever this machine's is
                        lambda p: Usage(100 * GB, 50 * GB, 50 * GB))
    yield tmp_path
    alerts.reset()


@pytest.fixture
def store(env):
    return EventStore(env / "state" / "events")


@pytest.fixture
def sink(store):
    s = StoreSink(store)
    event_sink.set_sink(s)
    yield s
    event_sink.set_sink(None)


def kinds(store):
    return [e["kind"] for e in store.read()["events"]]


def last(store):
    return store.read()["events"][-1]


def disk(monkeypatch, free_gb, total_gb=100):
    monkeypatch.setattr(alerts.shutil, "disk_usage",
                        lambda p: Usage(int(total_gb * GB), int((total_gb - free_gb) * GB), int(free_gb * GB)))


# ---------------------------------------------------------------- the disk

def test_disk_passing_the_warn_then_the_bad_limit_writes_one_event_each(sink, store, monkeypatch):
    disk(monkeypatch, 50)
    watch.check_disk(sink)
    assert kinds(store) == []
    disk(monkeypatch, 14)                                            # 86 % used
    watch.check_disk(sink)
    watch.check_disk(sink)
    assert kinds(store) == ["storage.low"] and last(store)["severity"] == "warn"
    assert last(store)["data"]["percent"] == "86.0" and last(store)["data"]["total"] == str(100 * GB)
    disk(monkeypatch, 4)                                             # 96 %
    watch.check_disk(sink)
    watch.check_disk(sink)
    assert kinds(store) == ["storage.low", "storage.low"] and last(store)["severity"] == "bad"
    assert store.is_raised("storage-low")


def test_disk_under_one_gb_free_is_bad_at_once(sink, store, monkeypatch):
    disk(monkeypatch, 0.5, total_gb=10)
    watch.check_disk(sink)
    assert last(store)["severity"] == "bad"


def test_disk_falling_from_bad_to_warn_writes_storage_low_again_with_direction_down(sink, store, monkeypatch):
    disk(monkeypatch, 4)
    watch.check_disk(sink)
    disk(monkeypatch, 10)
    watch.check_disk(sink)
    ev = last(store)
    assert ev["kind"] == "storage.low" and ev["severity"] == "warn" and ev["data"]["direction"] == "down"
    assert store.conditions()[0]["severity"] == "warn"               # the newest raise wins: the banner changes
    assert not alerts.is_alert(ev)                                   # and it is never sent as an alert
    watch.check_disk(sink)
    assert kinds(store) == ["storage.low", "storage.low"]


def test_disk_back_under_the_warn_limit_writes_storage_ok(sink, store, monkeypatch):
    disk(monkeypatch, 4)
    watch.check_disk(sink)
    disk(monkeypatch, 60)
    watch.check_disk(sink)
    assert kinds(store) == ["storage.low", "storage.ok"] and not store.is_raised("storage-low")
    watch.check_disk(sink)
    assert len(kinds(store)) == 2


def test_the_limits_come_from_alerts_xml(sink, store, monkeypatch):
    alerts.save({"storage_warn_percent": 40, "storage_bad_percent": 60})
    disk(monkeypatch, 55)
    watch.check_disk(sink)
    assert last(store)["severity"] == "warn"


# ---------------------------------------------------------------- low spools

class FakeSpoolman:
    def __init__(self, spools):
        self.spools = {s["id"]: s for s in spools}
        self.down = False

    def get(self, path):
        if self.down:
            raise SpoolmanError("down")
        if path == "spool":
            return [s for s in self.spools.values() if not s.get("archived")]
        sid = int(path.split("/")[1])
        if sid not in self.spools:
            raise SpoolmanError("no such spool", 404)
        return self.spools[sid]


def spool(i, left, fid=1, **kw):
    return {"id": i, "remaining_weight": left, "comment": "", "archived": False, "location": "Rack 1",
            "filament": {"id": fid, "name": "PLA Basic", "material": "PLA", "color_hex": "FF0000",
                         "vendor": {"name": "Acme"}}, **kw}


def test_a_spool_falling_to_the_threshold_writes_spool_low_once(sink, store):
    sm = FakeSpoolman([spool(1, 400), spool(2, 900, comment=inventory.SEALED_COMMENT)])
    watch.check_low(sm, sink)
    assert kinds(store) == []
    sm.spools[1]["remaining_weight"] = 150
    watch.check_low(sm, sink)
    watch.check_low(sm, sink)
    ev = last(store)
    assert kinds(store) == ["spool.low"] and ev["subject"] == {"type": "spool", "id": "1", "name": "Acme PLA Basic"}
    assert ev["data"] == {"spool": "1", "filament": "Acme PLA Basic", "material": "PLA", "grams": "150",
                          "in_stock": "1"}
    assert ev["condition"] == {"key": "spool-low:1", "state": "raised"} and store.is_raised("spool-low:1")


def test_the_spool_above_the_threshold_again_or_emptied_or_removed(sink, store):
    sm = FakeSpoolman([spool(1, 100), spool(2, 90, fid=2), spool(3, 80, fid=3)])
    watch.check_low(sm, sink)
    assert kinds(store) == ["spool.low"] * 3
    sm.spools[1]["remaining_weight"] = 700                           # refilled / weighed
    sm.spools[2]["archived"] = True                                  # marked empty
    del sm.spools[3]                                                 # deleted
    watch.check_low(sm, sink)
    new = store.read()["events"][3:]
    by = {e["subject"]["id"]: e for e in new}
    assert by["1"]["kind"] == "spool.ok" and by["2"]["kind"] == "spool.ok"
    assert by["3"]["kind"] == "condition.cleared" and by["3"]["data"] == {"key": "spool-low:3",
                                                                          "reason": "subject_removed"}
    assert store.conditions() == []


def test_spoolman_down_writes_nothing_and_keeps_the_conditions(sink, store):
    sm = FakeSpoolman([spool(1, 100)])
    watch.check_low(sm, sink)
    sm.down = True
    watch.check_low(sm, sink)
    assert kinds(store) == ["spool.low"] and store.is_raised("spool-low:1")


def test_the_event_is_written_whatever_the_switch_says(sink, store):
    alerts.save({"types": {"running_low": False}})
    watch.check_low(FakeSpoolman([spool(1, 100)]), sink)
    assert kinds(store) == ["spool.low"] and not alerts.is_alert(last(store))


def test_the_last_spool_is_in_the_event_for_the_only_last_switch(sink, store):
    watch.check_low(FakeSpoolman([spool(1, 100)]), sink)
    assert last(store)["data"]["in_stock"] == "0"
    alerts.save({"last_spool_only": True})
    assert alerts.is_alert(last(store))


# ---------------------------------------------------------------- the Weigh Station

def reach(monkeypatch, answer):
    monkeypatch.setattr(station_client, "station_reach",
                        lambda devs, url: {d["id"]: answer for d in devs if d.get("type") == "station"}
                        if url and len([d for d in devs if d.get("type") == "station"]) == 1 else {})


STATION = {"id": "d1", "name": "Bench scale", "type": "station"}
READER = {"id": "d2", "name": "Tag Reader", "type": None}


def test_a_station_that_stops_and_starts_answering(sink, store, monkeypatch):
    reach(monkeypatch, True)
    watch.check_devices(sink, "http://st", [STATION, READER])
    assert kinds(store) == []
    reach(monkeypatch, False)
    watch.check_devices(sink, "http://st", [STATION, READER])
    watch.check_devices(sink, "http://st", [STATION, READER])
    assert kinds(store) == ["device.down"] and store.is_raised("device-down:d1")
    assert last(store)["subject"] == {"type": "device", "id": "d1", "name": "Bench scale"}
    reach(monkeypatch, True)
    watch.check_devices(sink, "http://st", [STATION, READER])
    assert kinds(store) == ["device.down", "device.up"] and not store.is_raised("device-down:d1")


def test_no_event_without_an_address_or_with_two_stations_and_none_for_tag_readers(sink, store, monkeypatch):
    reach(monkeypatch, False)
    watch.check_devices(sink, None, [STATION])
    watch.check_devices(sink, "http://st", [STATION, {**STATION, "id": "d3"}])
    watch.check_devices(sink, "http://st", [READER])
    assert kinds(store) == []


def test_a_raised_device_condition_is_cleared_when_the_station_is_unpaired_or_cannot_be_asked(sink, store, monkeypatch):
    reach(monkeypatch, False)
    watch.check_devices(sink, "http://st", [STATION])
    watch.check_devices(sink, "http://st", [])                       # unpaired
    assert last(store)["data"] == {"key": "device-down:d1", "reason": "subject_removed"}
    watch.check_devices(sink, "http://st", [STATION])
    assert last(store)["kind"] == "device.down"
    watch.check_devices(sink, None, [STATION])                       # the address was removed
    assert last(store)["data"] == {"key": "device-down:d1", "reason": "reconciled"}
    assert store.conditions() == []


# ---------------------------------------------------------------- Checks rows

def test_a_row_needing_a_look_and_fine_again(sink, store):
    rows = [Row("ok", "Spoolman reachable", group="Spoolman"), Row("fail", "Backup is 9 days old", "do x",
                                                                 group="Hub"), Row("info", "a note")]
    watch.check_rows(sink, rows)
    watch.check_rows(sink, rows)
    assert kinds(store) == ["check.failed"] and last(store)["data"] == {"text": "Backup is 9 days old"}
    assert last(store)["condition"]["key"] == "check:hub.backup-is"
    rows = [Row("ok", "Spoolman reachable", group="Spoolman"), Row("ok", "Backup is 0 days old", group="Hub")]
    watch.check_rows(sink, rows)
    assert kinds(store) == ["check.failed", "check.ok"] and store.conditions() == []


def test_the_key_does_not_change_with_the_numbers_in_the_text(sink, store):
    watch.check_rows(sink, [Row("fail", "Backup is 9 days old", group="Hub")])
    watch.check_rows(sink, [Row("fail", "Backup is 10 days old", group="Hub")])
    assert kinds(store) == ["check.failed"]


def test_a_row_that_no_longer_exists_clears_its_check(sink, store):
    watch.check_rows(sink, [Row("fail", "Weigh Station not answering", group="Weigh Station")])
    watch.check_rows(sink, [])
    assert last(store)["data"]["reason"] == "feature_off" and store.conditions() == []


def test_a_row_with_its_own_key_uses_it(sink, store):
    class Keyed(namedtuple("Keyed", "state text group key")):
        pass
    watch.check_rows(sink, [Keyed("fail", "x", "Hub", "storage")])
    assert last(store)["condition"]["key"] == "check:storage"


# ---------------------------------------------------------------- the loop

def test_a_round_runs_every_step_and_one_failure_stops_none(sink, store, monkeypatch, caplog):
    disk(monkeypatch, 4)
    sm = FakeSpoolman([spool(1, 100)])
    loop = watch.Loop(sink, spoolman=sm, rows=lambda: [Row("fail", "Backup is old", group="Hub")],
                      devices=lambda: [])

    def boom(*a, **k):
        raise RuntimeError("devices broke")
    monkeypatch.setattr(watch, "check_devices", boom)
    loop.tick()
    assert sorted(kinds(store)) == ["check.failed", "spool.low", "storage.low"]
    assert "devices failed" in caplog.text


def test_a_round_reconciles_the_printers_conditions(sink, store):
    w = watch.Watcher(sink)
    w._p["P1"] = watch._Printer()
    w._p["P1"].state = "IDLE"
    store.write("print.runout", {"type": "printer", "id": "P1", "name": "x"}, {"type": "hub"}, {"job": "a"})
    watch.Loop(sink, watcher=w, rows=None, devices=lambda: []).tick()
    assert last(store)["kind"] == "condition.cleared" and not store.is_raised("print-paused:P1")


def test_old_month_files_are_deleted_once_a_day_with_the_setting(sink, store, env, monkeypatch):
    now = datetime.now(timezone.utc)
    store.write("print.started", {"type": "printer", "id": "p"}, {"type": "hub"}, {"job": "a"},
                now=datetime(now.year - 3, 1, 5, tzinfo=timezone.utc))
    store.write("print.started", {"type": "printer", "id": "p"}, {"type": "hub"}, {"job": "b"})
    (env / "etc" / "config.json").write_text('{"events": {"keep_days": 60}}', encoding="utf-8")
    t = [1000.0]
    loop = watch.Loop(sink, devices=lambda: [], clock=lambda: t[0])
    loop.tick()
    assert [e["data"]["job"] for e in store.read()["events"]] == ["b"]
    called = []
    monkeypatch.setattr("filament_kit.events.prune", lambda days: called.append(days) or [])
    t[0] += 3600
    loop.tick()
    assert called == []                                              # not again within the day
    t[0] += 86400
    loop.tick()
    assert called == [60]
    assert config.keep_days(config.load()) == 60


def test_the_loop_thread_runs_a_round_at_start_and_stops(sink, store, monkeypatch):
    disk(monkeypatch, 4)
    loop = watch.Loop(sink, devices=lambda: [], every=0.05, first=0)
    loop.start()
    try:
        import time
        end = time.monotonic() + 5
        while "storage.low" not in kinds(store) and time.monotonic() < end:
            time.sleep(0.02)
    finally:
        loop.stop()
    assert kinds(store) == ["storage.low"]


def test_the_first_round_waits_for_the_services_to_start(sink, store, monkeypatch):
    disk(monkeypatch, 4)
    loop = watch.Loop(sink, devices=lambda: [], every=0.05, first=0.4)
    loop.start()
    try:
        import time
        time.sleep(0.2)
        assert kinds(store) == []                                    # still waiting
        end = time.monotonic() + 5
        while "storage.low" not in kinds(store) and time.monotonic() < end:
            time.sleep(0.02)
    finally:
        loop.stop()
    assert kinds(store) == ["storage.low"]
