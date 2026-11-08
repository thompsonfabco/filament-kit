"""Klipper usage log (Moonraker deducts, the kit only records) and the Spoolman check (spec §6 Usage)."""
import json
import time
from pathlib import Path

import pytest

from filament_kit.bridge import registry
from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper import usage as kusage
from filament_kit.bridge.klipper.manager import KlipperFamily
from filament_kit.spoolman import Spoolman

DATA = Path(__file__).parent / "data" / "klipper"


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
    kh._reset_cache()
    yield
    kh._reset_cache()


def history_job(**kw):
    jobs = json.loads((DATA / "SV08-MAX" / "history.json").read_text())["jobs"]
    return {**jobs[0], **kw}


def test_record_and_entries():
    e = kusage.record("sv08-max", history_job(), 10)
    assert e["id"].startswith("k-") and e["source"] == "moonraker"
    assert e["spool_id"] == 7 and e["filament_mm"] == pytest.approx(4321.5, abs=0.01)
    assert e["grams"] == pytest.approx(12.97)
    got = kusage.entries("sv08-max", 36500)
    assert [x["id"] for x in got] == [e["id"]]
    assert got[0]["can_undo"] is False and got[0]["undone"] is False
    assert kusage.owns(e["id"]) and not kusage.owns("abc")
    assert kusage.entries("sv08-max", 0) == [] or all(x["ended"] for x in kusage.entries("sv08-max", 0))


def test_real_timestamps_keep_full_precision():
    # a 6-significant-digit format turned both times of a 23-minute print into the same 10-digit number
    job = {**history_job(), "job_id": "000099", "start_time": 1767270001.917, "end_time": 1767271379.388,
           "filament_used": 4321.123456789012}
    kusage.record("p", job, None)
    got = kusage.entries("p", 36500)[0]
    assert got["started"] == 1767270001.917 and got["ended"] == 1767271379.388
    assert got["filament_mm"] == 4321.123456789012


def test_record_same_job_once():
    kusage.record("p", history_job(), 10)
    kusage.record("p", history_job(), 10)
    assert len(kusage.entries("p", 36500)) == 1


def test_cap_2000(monkeypatch):
    monkeypatch.setattr(kusage, "KEEP", 5)
    for i in range(8):
        kusage.record("p", history_job(job_id=f"{i:06d}"), 1)
    ids = [e["job"] for e in kusage.entries("p", 36500)]
    assert len(ids) == 5 and "000007" in ids and "000000" not in ids


def test_entries_missing_or_broken_file(tmp_path):
    assert kusage.entries("none", 30) == []
    d = registry.config.paths().state / "printers" / "bad"
    d.mkdir(parents=True)
    (d / "usage.xml").write_text("<nope")
    assert kusage.entries("bad", 30) == []


class Recorder:
    def __init__(self, sm):
        self.sm, self.calls = sm, []

    def get(self, path):
        return self.sm.get(path)

    def put(self, path, body):
        self.calls.append(("PUT", path))
        return self.sm.put(path, body)

    def patch(self, path, body):
        self.calls.append(("PATCH", path))
        return self.sm.patch(path, body)

    def post(self, path, body):
        return self.sm.post(path, body)


@pytest.fixture
def printer(moonraker, spoolman_url):
    moonraker.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    moonraker.status = json.loads((DATA / "SV08-MAX" / "status.json").read_text())
    moonraker.hostname = "SV08MAX"
    moonraker.server_config = {"spoolman": {"server": spoolman_url}}
    sm = Recorder(Spoolman(spoolman_url))
    pid = registry.add_klipper("SV08 MAX", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    assert fam.wait_settled(pid, 8) == "connected"
    yield fam, pid, moonraker, sm
    fam.stop()


def test_job_end_records_entry(printer):
    fam, pid, fake, sm = printer
    fake.push({"print_stats": {"state": "printing", "filename": "a.gcode"}})
    assert wait_for(lambda: fam.status(pid)["gcode_state"] == "RUNNING")
    fake.history = [history_job(job_id="000200", status="completed")]
    fake.push({"print_stats": {"state": "complete"}})
    assert wait_for(lambda: len(fam.usage(pid, 36500)) == 1)
    e = fam.usage(pid, 36500)[0]
    assert (e["job"], e["status"], e["source"]) == ("000200", "completed", "moonraker")
    assert not any(c[0] == "PUT" for c in sm.calls)          # never writes usage to Spoolman


def test_shutdown_mid_job_records_history_only(printer):
    """Review Focus 4: Klipper shuts down mid-print → one entry from Moonraker's history, no Spoolman write."""
    fam, pid, fake, sm = printer
    fake.push({"print_stats": {"state": "printing", "filename": "a.gcode"}})
    assert wait_for(lambda: fam.status(pid)["gcode_state"] == "RUNNING")
    fake.history = [history_job(job_id="000201", status="klippy_shutdown")]
    fake.klippy_state = "shutdown"
    fake.event("notify_klippy_shutdown")
    assert wait_for(lambda: len(fam.usage(pid, 36500)) == 1)
    assert fam.usage(pid, 36500)[0]["status"] == "klippy_shutdown"
    assert fam.state(pid) == "klippy_not_ready"
    assert sm.calls == []


def test_no_entry_without_a_job_end(printer):
    fam, pid, fake, sm = printer
    fake.push({"print_stats": {"state": "standby"}})
    time.sleep(0.5)
    assert fam.usage(pid, 36500) == []


def test_warning_none_when_same(printer):
    fam, pid, fake, sm = printer
    assert fam.status(pid)["spoolman_warning"] is None


def test_warning_other_spoolman(moonraker, spoolman_url):
    moonraker.server_config = {"spoolman": {"server": "http://other.example.com:7912"}}
    pid = registry.add_klipper("P", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 8)
        assert fam.status(pid)["spoolman_warning"] == "usage goes to another Spoolman: other.example.com:7912"
    finally:
        fam.stop()


def test_warning_no_spoolman_section(moonraker, spoolman_url):
    moonraker.server_config = {}
    pid = registry.add_klipper("P", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 8)
        assert "no [spoolman] section" in fam.status(pid)["spoolman_warning"]
    finally:
        fam.stop()


def test_same_spoolman_by_loopback():
    assert kusage.same_spoolman("http://127.0.0.1:7912", "http://127.0.0.1:7912")
    assert not kusage.same_spoolman("http://127.0.0.1:7912", "http://127.0.0.1:7913")
    assert kusage.same_spoolman("http://localhost:7912/", "http://127.0.0.1:7912")


def test_warning_never_shows_a_password():
    kit = "http://other.example.com:7912"
    for server in ("http://u:hunter/w@spoolman.example.com:7912", "http://u:hunter@spoolman.example.com:notaport",
                   "u:hunter@spoolman.example.com:7912"):
        assert "hunter" not in kusage.spoolman_warning({"spoolman": {"server": server}}, kit)


def test_host_port_with_a_plain_path_or_credentials():
    assert kusage._host_port("http://spoolman.example.com:7912/spoolman/") == ("spoolman.example.com", 7912)
    assert kusage._host_port("https://spoolman.example.com/x?y=1#z") == ("spoolman.example.com", 443)
    assert kusage._host_port("http://u:p@spoolman.example.com:7912/x") == ("spoolman.example.com", 7912)
    assert kusage._host_port("http://spoolman.example.com:7912/x@y") is None


def test_same_spoolman_with_a_host_getaddrinfo_cannot_encode():
    assert kusage.same_spoolman("http://a..b:7912", "http://other.example.com:7912") is False
    assert kusage.same_spoolman("http://a..b:7912", "http://a..b:7912") is True


def test_warning_odd_spoolman_section():
    assert "no [spoolman] section" in kusage.spoolman_warning({"spoolman": "x"}, "http://other.example.com:7912")


def test_short_print_seen_only_as_complete(printer):
    """A print can start and end between two Moonraker updates: standby -> complete still ends a job."""
    fam, pid, fake, sm = printer
    fake.history = [history_job(job_id="000300", status="completed")]
    fake.push({"print_stats": {"state": "complete", "filename": "short.gcode"}})
    assert wait_for(lambda: len(fam.usage(pid, 36500)) == 1)
    assert fam.usage(pid, 36500)[0]["job"] == "000300"


def test_connecting_to_a_finished_printer_records_nothing(moonraker, spoolman_url):
    moonraker.status["print_stats"]["state"] = "complete"
    moonraker.history = [history_job(job_id="000301", status="completed")]
    pid = registry.add_klipper("P", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 8)
        time.sleep(0.5)
        assert fam.usage(pid, 36500) == []
    finally:
        fam.stop()
