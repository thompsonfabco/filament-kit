"""Klipper usage log (Moonraker deducts, the kit only records) and the Spoolman check (spec §6 Usage)."""
import json
import time
from pathlib import Path

import pytest

from filament_kit.bridge import registry
from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper import moonraker as mr
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
        self.calls.append(("POST", path))
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
    assert sm.calls == []                                    # never writes usage to Spoolman (no PUT, PATCH or POST)


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
    moonraker.server_config = {"spoolman": {"server": "http://192.0.2.30:7912"}}
    pid = registry.add_klipper("P", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 8)
        assert fam.status(pid)["spoolman_warning"] == "usage goes to another Spoolman: 192.0.2.30:7912"
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


# ---------- is Moonraker's Spoolman the kit's? ----------
# The kit is on 192.0.2.10. A loopback address means the machine that holds that config: the printer's, in Moonraker's.

DNS = {"kit.example.com": "192.0.2.10", "kit-alias.example.com": "192.0.2.10", "printer.example.com": "192.0.2.20",
       "other.example.com": "192.0.2.30", "localhost": "127.0.0.1", "127.0.0.1": "127.0.0.1", "::1": "::1",
       "192.0.2.10": "192.0.2.10", "192.0.2.20": "192.0.2.20", "192.0.2.30": "192.0.2.30", "fd00::1": "fd00::1",
       "2001:db8::10": "2001:db8::10",
       "kit-host": "127.0.1.1"}     # stock Ubuntu's /etc/hosts: the machine's own name is a loopback address


@pytest.fixture
def lookups(monkeypatch):
    """A fixed DNS (no real lookups); returns the list of names looked up."""
    asked = []

    def getaddrinfo(host, port, *a, **kw):
        asked.append(host)
        if host == "a..b":
            raise UnicodeError("label empty")
        if host not in DNS:
            raise OSError("no such name")
        return [(0, 0, 0, "", (DNS[host], 0))]
    monkeypatch.setattr(kusage.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(kusage.pairing, "_candidate_ips", lambda: ["192.0.2.10", "2001:db8::10"])
    monkeypatch.setattr(kusage.socket, "gethostname", lambda: "kit-host")
    return asked


KIT_LOCAL = "http://127.0.0.1:7912"     # the kit's default spoolman_url
PRINTER = "printer.example.com"


@pytest.mark.parametrize("server, kit, printer, want", [
    # the printer's own loopback is the printer, however the kit's url is written
    ("http://localhost:7912", KIT_LOCAL, PRINTER, "different"),
    ("http://127.0.0.1:7912", KIT_LOCAL, PRINTER, "different"),
    ("http://127.0.0.1:7912", "http://kit.example.com:7912", PRINTER, "different"),
    ("http://127.0.0.1:7912", "http://192.0.2.10:7912", PRINTER, "different"),
    # the correct all-in-one: the printer has the kit's LAN address, the kit its own loopback
    ("http://kit.example.com:7912", KIT_LOCAL, PRINTER, "same"),
    ("http://192.0.2.10:7912", KIT_LOCAL, PRINTER, "same"),
    # a name that resolves to loopback HERE is this machine, not the printer's own: the setting doesn't say loopback
    ("http://kit-host:7912", KIT_LOCAL, PRINTER, "same"),
    ("http://kit-host:7912", "http://kit.example.com:7912", PRINTER, "same"),
    ("http://kit-host:7912", "http://other.example.com:7912", PRINTER, "different"),
    # the kit's IPv6 LAN address counts as the kit too
    ("http://[2001:db8::10]:7912", KIT_LOCAL, PRINTER, "same"),
    # the printer on the kit's own machine: then loopback on both sides is the same place
    ("http://localhost:7912", KIT_LOCAL, "127.0.0.1", "same"),
    ("http://127.0.0.1:7912", "http://kit.example.com:7912", "kit.example.com", "same"),
    # Spoolman on the printer, the kit using it remotely
    ("http://localhost:7912", f"http://{PRINTER}:7912", PRINTER, "same"),
    # a kit with a remote Spoolman: spoolman_url is the answer, the kit's own addresses don't count
    ("http://other.example.com:7912", "http://other.example.com:7912", PRINTER, "same"),
    ("http://kit.example.com:7912", "http://other.example.com:7912", PRINTER, "different"),
    # plain names
    ("http://kit-alias.example.com:7912/", "http://kit.example.com:7912", PRINTER, "same"),
    ("http://other.example.com:7912", KIT_LOCAL, PRINTER, "different"),
    ("http://[fd00::1]:7912", "http://[fd00::1]:7912", PRINTER, "same"),
    ("http://u:p@kit.example.com:7912", "http://kit.example.com:7912", PRINTER, "same"),
    # the port still has to match
    ("http://kit.example.com:7913", "http://kit.example.com:7912", PRINTER, "different"),
    ("http://localhost:7913", KIT_LOCAL, "127.0.0.1", "different"),
    # cannot tell: a name that doesn't resolve here may well resolve on the printer
    ("http://gone.example.com:7912", KIT_LOCAL, PRINTER, "unknown"),
    ("http://a..b:7912", "http://kit.example.com:7912", PRINTER, "unknown"),
    ("http://kit.example.com:7912", "http://gone.example.com:7912", PRINTER, "unknown"),
    ("http://localhost:7912", KIT_LOCAL, "gone.example.com", "unknown"),
    ("http://kit.example.com:notaport", KIT_LOCAL, PRINTER, "unknown"),
    ("http://kit.example.com:7912", "not a url", PRINTER, "unknown"),
    # the same name, even one that doesn't resolve here, is the same place
    ("http://gone.example.com:7912", "http://gone.example.com:7912", PRINTER, "same"),
    ("http://a..b:7912", "http://a..b:7912", PRINTER, "same"),
])
def test_compare_spoolman(lookups, server, kit, printer, want):
    assert kusage.compare_spoolman(server, kit, printer) == want


def test_each_name_is_looked_up_once_per_call(lookups):
    r = kusage.spoolman_report({"spoolman": {"server": "http://localhost:7912"}}, f"http://{PRINTER}:7912", PRINTER)
    assert r["match"] == "same" and lookups == [PRINTER]     # "localhost" needs no lookup: it says what it means
    lookups.clear()
    r = kusage.spoolman_report({"spoolman": {"server": "http://localhost:7912"}}, KIT_LOCAL, "127.0.0.1")
    assert r["match"] == "same" and lookups.count("127.0.0.1") == 1 and lookups.count("kit-host") == 1
    lookups.clear()
    assert kusage.spoolman_report({"spoolman": {"server": "http://x.example.com:1"}}, KIT_LOCAL, PRINTER)["match"] == "different"
    assert lookups == []     # the ports differ: nothing to look up


def test_the_machines_own_addresses_are_found_once_per_call(lookups, monkeypatch):
    calls = []
    real = kusage.pairing._candidate_ips
    monkeypatch.setattr(kusage.pairing, "_candidate_ips", lambda: calls.append(1) or real())
    assert kusage.compare_spoolman("http://localhost:7912", KIT_LOCAL, "127.0.0.1") == "same"
    assert len(calls) == 1 and lookups.count("kit-host") == 1


def test_a_name_resolving_to_loopback_here_is_shown_as_another_only_when_it_is(lookups):
    r = kusage.spoolman_report({"spoolman": {"server": "http://kit-host:7912"}}, KIT_LOCAL, PRINTER)
    assert r == {"server": "kit-host:7912", "match": "same", "warning": None}
    r = kusage.spoolman_report({"spoolman": {"server": "http://kit-host:7912"}}, "http://other.example.com:7912", PRINTER)
    assert r["warning"] == "usage goes to another Spoolman: kit-host:7912"


def test_an_unreadable_kit_url_is_named_as_the_reason(lookups):
    r = kusage.spoolman_report({"spoolman": {"server": "http://localhost:7912"}}, "http://[bad", PRINTER)
    assert r["match"] == "unknown"
    assert r["warning"] == ("cannot tell whether Moonraker's Spoolman localhost:7912 is this kit's: this kit's "
                            "spoolman_url cannot be read")


class _Status:
    def __init__(self, answer):
        self.answer = answer

    def spoolman_status(self):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.mark.parametrize("answer, previous, want", [
    ({"spoolman_connected": True}, False, True),
    ({"spoolman_connected": False}, True, False),
    # a passing failure says nothing new: what was known stands
    (mr.Offline("gone"), False, False),
    (mr.MoonrakerError("500"), False, False),
    (mr.Offline("gone"), None, None),
    # 404: Moonraker has no [spoolman] now, so it really won't say
    (mr.NotFound("no"), False, None),
    ({"spoolman_connected": "x"}, False, None),
    ([], False, None),
])
def test_spoolman_connected(answer, previous, want):
    assert kusage.spoolman_connected(_Status(answer), previous) is want


def test_a_failed_status_request_on_reconnect_keeps_the_warning(moonraker, spoolman_url):
    moonraker.server_config = {"spoolman": {"server": spoolman_url}}
    moonraker.spoolman["spoolman_connected"] = False
    pid = registry.add_klipper("P", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 8)
        conn = fam._conns[pid]
        assert "cannot reach its Spoolman" in fam.status(pid)["spoolman_warning"]
        real, conn.client.spoolman_status = conn.client.spoolman_status, lambda: (_ for _ in ()).throw(mr.Offline("x"))
        conn._on_connect()
        assert "cannot reach its Spoolman" in fam.status(pid)["spoolman_warning"]
        conn.client.spoolman_status = real
    finally:
        fam.stop()


@pytest.mark.parametrize("server, match, address, warning", [
    ("http://kit.example.com:7912", "same", "kit.example.com:7912", None),
    ("http://other.example.com:7912", "different", "other.example.com:7912",
     "usage goes to another Spoolman: other.example.com:7912"),
    ("http://127.0.0.1:7912", "different", "127.0.0.1:7912",
     "usage goes to the printer's own 127.0.0.1:7912, not this kit's Spoolman"),
    ("http://localhost:7912", "different", "localhost:7912",
     "usage goes to the printer's own localhost:7912, not this kit's Spoolman"),
    ("http://gone.example.com:7912", "unknown", "gone.example.com:7912",
     "cannot tell whether Moonraker's Spoolman gone.example.com:7912 is this kit's: a name does not resolve here"),
    ("http://u:hunter@kit.example.com:notaport", "unknown", None,
     "Moonraker's [spoolman] server address cannot be read; usage may not reach this Spoolman"),
])
def test_report_sentences(lookups, server, match, address, warning):
    r = kusage.spoolman_report({"spoolman": {"server": server}}, KIT_LOCAL, PRINTER)
    assert r == {"server": address, "match": match, "warning": warning}


def test_report_no_section_or_no_kit_url(lookups):
    assert kusage.spoolman_report({}, KIT_LOCAL, PRINTER) == {
        "server": None, "match": None,
        "warning": "Moonraker does not report usage to Spoolman (no [spoolman] section)"}
    assert kusage.spoolman_report({"spoolman": {"server": "http://other.example.com:7912"}}, None, PRINTER) == {
        "server": "other.example.com:7912", "match": None, "warning": None}
    assert kusage.spoolman_warning(None, KIT_LOCAL, PRINTER) is None


def test_with_connection():
    assert kusage.with_connection(None, True) is None
    assert kusage.with_connection(None, None) is None
    assert kusage.with_connection("usage goes to x", None) == "usage goes to x"
    assert kusage.with_connection(None, False) == "Moonraker cannot reach its Spoolman: usage is not getting there"
    assert kusage.with_connection("usage goes to x", False) == (
        "usage goes to x; Moonraker cannot reach its Spoolman: usage is not getting there")


def test_connection_warning_at_set_up_and_as_it_changes(moonraker, spoolman_url):
    moonraker.server_config = {"spoolman": {"server": spoolman_url}}
    moonraker.spoolman["spoolman_connected"] = False
    pid = registry.add_klipper("P", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(pid, 8)
        assert "cannot reach its Spoolman" in fam.status(pid)["spoolman_warning"]
        moonraker._notify("notify_spoolman_status_changed", [{"spoolman_connected": True}])
        for _ in range(100):
            if fam.status(pid)["spoolman_warning"] is None:
                break
            time.sleep(0.05)
        assert fam.status(pid)["spoolman_warning"] is None
        moonraker._notify("notify_spoolman_status_changed", [{"spoolman_connected": False}])
        for _ in range(100):
            if fam.status(pid)["spoolman_warning"]:
                break
            time.sleep(0.05)
        assert "cannot reach its Spoolman" in fam.status(pid)["spoolman_warning"]
    finally:
        fam.stop()


def test_the_set_up_and_detect_compare_with_the_printers_own_host(moonraker, spoolman_url, monkeypatch):
    from filament_kit import klipper_cli
    hosts = []
    real = kusage.compare_spoolman

    def spy(server, kit, printer_host):
        hosts.append(printer_host)
        return real(server, kit, printer_host)
    monkeypatch.setattr(kusage, "compare_spoolman", spy)
    moonraker.server_config = {"spoolman": {"server": spoolman_url}}
    p = registry.add_klipper("P", moonraker.host, moonraker.port)
    fam = KlipperFamily(Spoolman(spoolman_url), backoff=(0.1, 0.4))
    fam.start()
    try:
        fam.wait_settled(p.serial, 8)
    finally:
        fam.stop()
    klipper_cli.detect(p, kit_spoolman=spoolman_url)
    assert set(hosts) == {moonraker.host} and len(hosts) == 2


def test_warning_never_shows_a_password():
    kit = "http://other.example.com:7912"
    for server in ("http://u:hunter/w@spoolman.example.com:7912", "http://u:hunter@spoolman.example.com:notaport",
                   "u:hunter@spoolman.example.com:7912"):
        assert "hunter" not in kusage.spoolman_warning({"spoolman": {"server": server}}, kit, "printer.invalid")


def test_host_port_with_a_plain_path_or_credentials():
    assert kusage._host_port("http://spoolman.example.com:7912/spoolman/") == ("spoolman.example.com", 7912)
    assert kusage._host_port("https://spoolman.example.com/x?y=1#z") == ("spoolman.example.com", 443)
    assert kusage._host_port("http://u:p@spoolman.example.com:7912/x") == ("spoolman.example.com", 7912)
    assert kusage._host_port("http://spoolman.example.com:7912/x@y") is None


def test_warning_odd_spoolman_section():
    assert "no [spoolman] section" in kusage.spoolman_warning({"spoolman": "x"}, "http://other.example.com:7912",
                                                              "printer.invalid")


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
