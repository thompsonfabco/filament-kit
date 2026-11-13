"""The console's Printers tab (setup_console/printers_tab.py) and addresses as names (hostaddr): every address field takes an IP
or a name, keeps it as typed and resolves it at use; a Klipper printer is never asked for an Access Code; its API key is
write-only; the scan is bounded; slot mapping runs on the server's own Mapper."""
from __future__ import annotations

import logging
import socket
from pathlib import Path

import pytest

from filament_kit import cli, hostaddr, klipper_cli, modules, release, setup_page
from filament_kit.bridge import mapping, registry
from filament_kit.bridge.connection import PrinterOffline
from filament_kit.bridge.klipper import discovery
from filament_kit.bridge.slottest import PrinterBusy
from test_setup_page import (CODE, H, HOSTNAME, SERIAL, STATIC, FakeManager, client, env, helper, make, manager, post)  # noqa: F401

KEY = "abcdef0123456789abcdef0123456789"
NAME = "printer.example.com"


@pytest.fixture
def names(monkeypatch):
    """What this server can resolve; everything else doesn't."""
    known = {NAME, "h2d.local", "Workshop.Example.COM"}

    def lookup(host, port, *a, **k):
        if host in known:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.77", 0))]
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    return known


class FakeMapper:
    def __init__(self):
        self.started, self.stopped, self.fail = [], [], None
        self.stop_pending = []

    def start(self, serial):
        if self.fail:
            raise self.fail
        self.started.append(serial)
        return "job-1"

    def view(self, serial):
        return {"state": "running", "step": "testing slot A1", "slots": [], "problems": [], "notes": []}

    def abort(self, serial, pending=True):
        self.stopped.append(serial)
        self.stop_pending.append(pending)

    def report(self, serial):
        if self.fail:
            raise self.fail
        from filament_kit.bridge import printer_report
        path = printer_report.save(serial, b"<printer-report format='1'/>", "H2D")
        return {"name": path.name, "xml": "<printer-report/>", "path": str(path)}


@pytest.fixture
def both(env, helper, manager, names):
    return make(env, helper, manager, add=frozenset({"klipper"}))


@pytest.fixture
def kl():
    return registry.add_klipper("Workshop", NAME, 7125)


def _bambu(ip="192.0.2.40"):
    p = registry.Printer(SERIAL, "H2D", "H2D", ip, "12345678", True)
    registry.upsert(p)
    return p


# ---------- hostaddr ----------
@pytest.mark.parametrize("text, kept", [
    ("192.0.2.40", "192.0.2.40"), (" 192.0.2.40 ", "192.0.2.40"), ("2001:db8::1", "2001:db8::1"), ("[2001:db8::1]", "2001:db8::1"),
    ("printer.local", "printer.local"), ("Printer.Example.COM", "Printer.Example.COM"), ("printer", "printer")])
def test_good_addresses_are_kept_as_typed(text, kept):
    assert hostaddr.clean(text) == kept and hostaddr.form_error(kept) is None


@pytest.mark.parametrize("bad", ["", "not an address", "http://printer.local", "printer.local:7125", "192.0.2.999", "a/b", "-x.example", "x" * 300, None, 5])
def test_bad_forms_are_refused(bad):
    assert hostaddr.form_error(hostaddr.clean(bad))


def test_a_literal_address_is_never_looked_up():
    def boom(*a, **k):
        raise AssertionError("looked up")
    assert hostaddr.resolve_error("192.0.2.40", lookup=boom) is None and hostaddr.resolve_error("2001:db8::1", lookup=boom) is None
    assert hostaddr.inspect("[fd00::7]", lookup=boom) == ("fd00::7", None, None)


@pytest.mark.parametrize("host, reach", [
    ("192.168.1.40", True), ("10.0.0.7", True), ("172.31.0.9", True), ("127.0.0.1", True), ("fe80::1", True), ("fd00::7", True),
    ("192.0.2.40", False), ("100.64.7.7", False), ("169.254.7.7", False), ("2001:db8::1", False), ("203.0.113.9", False)])
def test_an_address_the_unit_doesnt_reach_is_kept_with_a_note(host, reach):
    """Review R31: the server's unit allows the home networks only (a test keeps SERVICE_REACH equal to it). A printer
    elsewhere is saved all the same (the owner's choice), with a note saying why it will show offline and what allows it."""
    kept, problem, note = hostaddr.inspect(host)
    assert kept == host and problem is None
    if reach:
        assert note is None
    else:
        assert host in note and "systemctl edit filament-kit" in note and "IPAddressAllow=" in note


def test_a_name_resolving_outside_the_units_reach_gets_the_same_note():
    far = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("100.64.7.7", 0))]  # noqa: E731
    near = lambda *a, **k: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd00::7", 0, 0, 0))]  # noqa: E731
    a = hostaddr.inspect("tailnet.example.com", lookup=far)
    assert a.problem is None and "tailnet.example.com (100.64.7.7)" in a.note and "IPAddressAllow=100.64.7.0/24" in a.note
    assert hostaddr.inspect("voron.local", lookup=near) == ("voron.local", None, None)
    assert hostaddr.addresses("voron.local", lookup=near) == {"fd00::7"} and hostaddr.addresses("fd00::7") == {"fd00::7"}
    assert hostaddr.addresses("nope.local", lookup=lambda *a, **k: (_ for _ in ()).throw(socket.gaierror(-2, "no"))) == set()


def test_the_note_travels_with_add_and_change_address(both, names, manager):
    c = client(both)
    r = post(c, "printers/klipper", {"host": "100.64.7.7"})
    assert r.status_code == 200 and "IPAddressAllow=100.64.7.0/24" in r.json()["note"]
    r2 = post(c, "printers/klipper", {"host": "192.168.1.40", "name": "Near"})
    assert r2.status_code == 200 and "note" not in r2.json()
    r3 = post(c, f"printers/{r2.json()['serial']}/address", {"address": "2001:db8::9"})
    assert r3.status_code == 200 and "2001:db8::9" in r3.json()["note"]
    assert post(c, f"printers/{r2.json()['serial']}/address", {"address": "192.168.1.41"}).json() == {"ok": True}


def test_a_name_that_doesnt_resolve_says_what_to_look_at():
    def no(*a, **k):
        raise socket.gaierror(-2, "no")
    assert "does not resolve" in hostaddr.resolve_error(NAME, lookup=no)
    assert "switched on" in hostaddr.resolve_error("h2d.local", lookup=no)


def test_a_lookup_that_never_answers_doesnt_hang(monkeypatch):
    import threading
    hold = threading.Event()
    assert "does not resolve" in hostaddr.resolve_error(NAME, timeout=0.05, lookup=lambda *a, **k: hold.wait(5))
    hold.set()


def test_url_host_brackets_only_ipv6():
    assert hostaddr.url_host("2001:db8::1") == "[2001:db8::1]" and hostaddr.url_host("printer.local") == "printer.local"


def test_both_ends_of_a_name_can_look_up_a_local_name():
    assert "libnss-mdns" in modules.MODULES["server"].apt and "libnss-mdns" in modules.MODULES["station"].apt
    assert "libnss-mdns" in (Path(__file__).resolve().parents[2] / "THIRD-PARTY.md").read_text(encoding="utf-8")


# ---------- a name stays a name ----------
def test_a_bambu_printer_added_by_name_keeps_it(both, manager, monkeypatch):
    seen = []
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip: seen.append(ip) or SERIAL)
    r = post(client(both), "printers", {"address": "h2d.local", "access_code": "12345678"})
    assert r.status_code == 200 and seen == ["h2d.local"]
    assert registry.load()[SERIAL].ip == "h2d.local"


def test_a_name_that_doesnt_resolve_is_refused_and_nothing_is_kept(both, monkeypatch):
    monkeypatch.setattr(setup_page, "setup_serial", lambda ip: pytest.fail("reached out"))
    r = post(client(both), "printers", {"address": "nosuch.local", "access_code": "12345678", "serial": SERIAL})
    assert r.status_code == 400 and "nosuch.local" in r.json()["error"] and not registry.load()


def test_an_announcement_doesnt_replace_a_typed_name_but_still_moves_a_typed_address(env, caplog):
    _bambu("h2d.local")
    caplog.set_level(logging.WARNING)
    assert registry.detected(SERIAL, "192.0.2.41").ip == "h2d.local"
    assert registry.load()[SERIAL].ip == "h2d.local" and "announced" not in caplog.text
    _bambu("192.0.2.40")
    assert registry.detected(SERIAL, "192.0.2.41").ip == "192.0.2.41"


def test_changing_the_address_keeps_the_pin(both, manager):
    _bambu()
    registry.pin(SERIAL, "ab" * 32)
    c = client(both)
    assert post(c, f"printers/{SERIAL}/address", {"address": "h2d.local"}).status_code == 200
    p = registry.load()[SERIAL]
    assert p.ip == "h2d.local" and p.cert_fp == "ab" * 32 and p.access_code == "12345678"
    assert post(c, f"printers/{SERIAL}/address", {"address": "not an address"}).status_code == 400
    assert post(c, f"printers/{SERIAL}/address", {"address": "nosuch.example.com"}).status_code == 400
    assert registry.load()[SERIAL].ip == "h2d.local"


def test_the_terminal_menu_takes_a_name_too(env, names, monkeypatch, capsys):
    answers = iter(["H2D", "h2d.local", SERIAL, "H2D"])
    monkeypatch.setattr(cli, "_ask", lambda q: next(answers))
    monkeypatch.setattr(cli.secret_input, "ask", lambda q: "12345678")
    cli._printers_action("2", [])
    assert registry.load()[SERIAL].ip == "h2d.local"
    answers = iter(["H2D", "nosuch.local", "0948ZZ0A0000002"])
    monkeypatch.setattr(cli, "_ask", lambda q: next(answers))
    cli._printers_action("2", [])
    assert "Not added" in capsys.readouterr().out and "0948ZZ0A0000002" not in registry.load()


# ---------- Klipper: no Access Code, an optional key ----------
def test_a_klipper_printer_is_added_with_a_name_and_no_access_code(both, manager, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(both)
    r = post(c, "printers/klipper", {"host": NAME, "name": "Workshop"})
    assert r.status_code == 200, r.text
    p = registry.load()[r.json()["serial"]]
    assert (p.family, p.host, p.port, p.access_code, p.api_key, p.configured) == ("klipper", NAME, 7125, "", "", True)
    assert manager.synced == 1 and "added from 192.0.2.20" in caplog.text


def test_the_api_key_is_write_only(both, manager, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(both)
    r = post(c, "printers/klipper", {"host": NAME, "port": "7130", "name": "Workshop", "api_key": KEY})
    assert r.status_code == 200 and KEY not in r.text
    pid = r.json()["serial"]
    p = registry.load()[pid]
    assert p.api_key == KEY and p.port == 7130
    st = c.get("/setup/api/state")
    row = next(x for x in st.json()["printers"]["list"] if x["serial"] == pid)
    assert row["api_key"] is True and KEY not in st.text and KEY not in caplog.text
    assert post(c, f"printers/{pid}/api_key", {"key": "with a space"}).status_code == 400
    assert post(c, f"printers/{pid}/api_key", {"key": "x" * 65}).status_code == 400
    assert registry.load()[pid].api_key == KEY
    assert post(c, f"printers/{pid}/api_key", {"key": ""}).json() == {"ok": True, "set": False}
    assert registry.load()[pid].api_key == ""


@pytest.mark.parametrize("body", [{"host": "not an address"}, {"host": "nosuch.example.com"}, {"host": NAME, "port": 0},
                                  {"host": NAME, "port": "x"}, {"host": NAME, "port": True}, {"host": NAME, "api_key": "a b"}])
def test_a_bad_klipper_add_changes_nothing(both, body):
    assert post(client(both), "printers/klipper", body).status_code == 400 and not registry.load()


def test_the_same_host_and_port_twice_is_refused(both, kl):
    assert post(client(both), "printers/klipper", {"host": NAME}).status_code == 409 and len(registry.load()) == 1


def test_a_name_for_a_printer_added_by_address_is_refused(both, manager, names):
    c = client(both)
    assert post(c, "printers/klipper", {"host": "192.0.2.77", "name": "Voron"}).status_code == 200
    r = post(c, "printers/klipper", {"host": NAME})
    assert r.status_code == 409 and "Voron" in r.text and len(registry.load()) == 1


def test_another_name_for_a_printer_added_by_name_is_refused(both, kl, names):
    r = post(client(both), "printers/klipper", {"host": "Workshop.Example.COM"})
    assert r.status_code == 409 and len(registry.load()) == 1


def test_an_address_a_found_entry_holds_for_a_printer_added_by_name_is_refused(both, kl, names):
    registry.detected_klipper("192.0.2.77", 7125, lookups=False)
    r = post(client(both), "printers/klipper", {"host": "192.0.2.77"})
    assert r.status_code == 409 and sum(p.configured for p in registry.load().values()) == 1


def test_changing_an_address_to_a_name_for_another_printer_is_refused(both, manager, names):
    c = client(both)
    assert post(c, "printers/klipper", {"host": "192.0.2.77", "name": "Voron"}).status_code == 200
    other = post(c, "printers/klipper", {"host": "192.168.50.40", "name": "Other"}).json()["serial"]
    r = post(c, f"printers/{other}/address", {"address": NAME})
    assert r.status_code == 409 and "Voron" in r.text and registry.load()[other].host == "192.168.50.40"


def test_changing_a_printer_to_another_name_for_itself_is_fine(both, kl, names):
    r = post(client(both), f"printers/{kl.serial}/address", {"address": "Workshop.Example.COM"})
    assert r.status_code == 200 and registry.load()[kl.serial].host == "Workshop.Example.COM"


def test_adding_what_a_scan_found_puts_that_entry_into_use(both, manager):
    p = registry.detected_klipper(NAME, 7125)
    assert not p.configured
    r = post(client(both), "printers/klipper", {"host": NAME, "name": "Workshop", "api_key": KEY})
    assert r.json()["serial"] == p.serial and len(registry.load()) == 1
    after = registry.load()[p.serial]
    assert after.configured and after.name == "Workshop" and after.api_key == KEY


def test_a_scan_knows_a_printer_added_by_name(both, kl, manager, scanned):
    """Review R31: `kl` is at printer.example.com, which resolves to 192.0.2.77 here; a scan finding 192.0.2.77 reports
    that printer, and adds no second entry for it."""
    scanned.found = [("192.0.2.77", 7125)]
    r = post(client(both), "printers/scan", {})
    assert r.status_code == 200 and r.json()["found"] == [{"serial": kl.serial, "host": "192.0.2.77", "port": 7125, "configured": True}]
    assert list(registry.load()) == [kl.serial]
    assert registry.detected_klipper("192.0.2.77", 7125).serial == kl.serial              # the mDNS path is the same call
    assert registry.detected_klipper("192.0.2.77", 7126).serial != kl.serial              # another port is another printer


def test_adding_by_name_what_a_scan_found_by_address_is_one_printer(both, manager):
    found = registry.detected_klipper("192.0.2.77", 7125)
    r = post(client(both), "printers/klipper", {"host": NAME, "name": "Workshop"})
    assert r.status_code == 200 and r.json()["serial"] == found.serial and len(registry.load()) == 1
    after = registry.load()[found.serial]
    assert after.configured and after.name == "Workshop" and after.host == NAME        # the typed name is what's kept
    assert post(client(both), "printers/klipper", {"host": "192.0.2.77"}).status_code == 409


def test_an_address_another_printer_has_is_refused(both, kl, manager):
    other = registry.add_klipper("Other", "192.168.1.9", 7125)
    c = client(both)
    r = post(c, f"printers/{other.serial}/address", {"address": "192.0.2.77"})
    assert r.status_code == 409 and "Workshop" in r.json()["error"]
    assert post(c, f"printers/{other.serial}/address", {"address": NAME}).status_code == 409
    assert post(c, f"printers/{other.serial}/address", {"address": "192.0.2.77", "port": 7126}).status_code == 200


def test_a_scanned_printer_goes_into_use_from_its_row(both, manager):
    p = registry.detected_klipper(NAME, 7125)
    c = client(both)
    assert post(c, f"printers/{p.serial}/connect", {"api_key": KEY}).status_code == 200
    assert registry.load()[p.serial].configured and registry.load()[p.serial].api_key == KEY


def test_lane_data_and_rename(both, kl, manager):
    c = client(both)
    assert post(c, f"printers/{kl.serial}/lane_data", {"mode": "on"}).status_code == 200
    assert registry.load()[kl.serial].lane_data == "on"
    assert post(c, f"printers/{kl.serial}/lane_data", {"mode": "sometimes"}).status_code == 400
    assert post(c, f"printers/{kl.serial}/rename", {"name": "Bench"}).status_code == 200
    assert registry.load()[kl.serial].name == "Bench"
    assert post(c, f"printers/{kl.serial}/rename", {"name": "  "}).status_code == 400
    assert post(c, f"printers/{kl.serial}/address", {"address": "h2d.local", "port": 7130}).status_code == 200
    assert (registry.load()[kl.serial].host, registry.load()[kl.serial].port) == ("h2d.local", 7130)


def test_controls_are_for_their_own_family(both, kl):
    _bambu()
    c = client(both)
    assert post(c, f"printers/{SERIAL}/api_key", {"key": KEY}).status_code == 400
    assert post(c, f"printers/{SERIAL}/lane_data", {"mode": "on"}).status_code == 400
    assert post(c, f"printers/{SERIAL}/detect", {}, code=None).status_code == 400
    assert post(c, f"printers/{kl.serial}/unpin", {"access_code": "12345678"}).status_code == 400
    assert post(c, f"printers/{kl.serial}/map", {}).status_code == 400
    assert post(c, f"printers/{kl.serial}/code", {"access_code": "12345678"}).status_code == 400


@pytest.mark.parametrize("body", [{}, {"access_code": ""}, {"access_code": "bad code!"}])
def test_unpin_needs_the_access_code_in_the_same_request(both, body):
    _bambu()
    registry.pin(SERIAL, "ab" * 32)
    c = client(both)
    assert post(c, f"printers/{SERIAL}/unpin", body).status_code == 400
    assert registry.load()[SERIAL].cert_fp == "ab" * 32       # nothing changed


def test_unpin_with_an_access_code_clears_the_pin_and_saves_the_code(both):
    _bambu()
    registry.pin(SERIAL, "ab" * 32)
    c = client(both)
    assert post(c, f"printers/{SERIAL}/unpin", {"access_code": "87654321"}).status_code == 200
    p = registry.load()[SERIAL]
    assert p.cert_fp == "" and p.access_code == "87654321"


def test_unpin_refuses_a_printer_never_set_up(both):
    registry.upsert(registry.Printer(SERIAL, "Found", "", "192.0.2.41", "", False))
    c = client(both)
    assert post(c, f"printers/{SERIAL}/unpin", {"access_code": "87654321"}).status_code == 409
    p = registry.load()[SERIAL]
    assert not p.configured and p.access_code == ""


def test_a_family_whose_module_is_off_has_no_controls(env, helper, manager, names):
    app = make(env, helper, manager, drop=frozenset({"klipper"}))
    c = client(app)
    assert post(c, "printers/klipper", {"host": NAME}).status_code == 409
    assert post(c, "printers/scan", {}).status_code == 409
    assert post(c, "printers/pack", {}, code=None).status_code == 409


@pytest.mark.parametrize("path, body", [
    ("printers/klipper", {"host": NAME}), ("printers/scan", {}), ("printers/{s}/rename", {"name": "x"}),
    ("printers/{s}/address", {"address": NAME}), ("printers/{s}/unpin", {}), ("printers/{s}/connect", {}),
    ("printers/{s}/api_key", {"key": KEY}), ("printers/{s}/lane_data", {"mode": "on"}), ("printers/{s}/map", {}),
    ("printers/{s}/map/stop", {})])
def test_every_change_needs_the_code(both, kl, path, body):
    c = client(both)
    path = path.format(s=kl.serial)
    assert post(c, path, body, code=None).status_code == 403
    assert post(c, path, body, code="00000000").status_code == 403
    assert post(c, path, body, headers={"Origin": "https://elsewhere.example"}).status_code == 403


# ---------- the scan ----------
@pytest.fixture
def scanned(monkeypatch):
    calls = type("Calls", (list,), {})()        # the subnets asked for; `.found` is what the scan answers

    def scan(net, port=None):
        calls.append(str(net))
        return list(calls.found)
    calls.found = [("192.0.2.50", 7125)]
    monkeypatch.setattr(discovery, "scan", scan)
    monkeypatch.setattr(discovery, "own_subnet", lambda: __import__("ipaddress").ip_network("192.168.1.0/24"))
    return calls


def test_scan_finds_and_lists_for_picking(both, scanned, caplog):
    caplog.set_level(logging.INFO, logger="filament_kit")
    c = client(both)
    r = post(c, "printers/scan", {})
    assert r.status_code == 200 and scanned == ["192.168.1.0/24"]
    row = r.json()["found"][0]
    assert (row["host"], row["port"], row["configured"]) == ("192.0.2.50", 7125, False)
    assert any(x["host"] == "192.0.2.50" and x["configured"] is False for x in c.get("/setup/api/state").json()["printers"]["list"])
    assert "1 found" in caplog.text


def test_scans_are_spaced_server_wide(both, scanned):
    c = client(both)
    assert post(c, "printers/scan", {}).status_code == 200
    r = post(client(both, who=("192.0.2.21", 50000)), "printers/scan", {"subnet": "10.0.0.0/24"})
    assert r.status_code == 429 and scanned == ["192.168.1.0/24"]


@pytest.mark.parametrize("subnet", ["8.8.8.0/24", "127.0.0.0/24", "169.254.1.0/24", "224.0.0.0/24", "10.0.0.0/16", "2001:db8::/120", "nope"])
def test_a_scan_stays_on_a_private_small_network(both, scanned, subnet):
    assert post(client(both), "printers/scan", {"subnet": subnet}).status_code == 400 and scanned == []


# ---------- the printer pack, Detect ----------
def test_pack_shows_the_commands(both, monkeypatch):
    monkeypatch.setattr(klipper_cli, "pack_info", lambda v, cfg: {"version": "0.4.3", "sha256": "ab", "url": "u", "lines": ["curl x", "sha256sum y"]})
    r = post(client(both), "printers/pack", {}, code=None)
    assert r.status_code == 200 and r.json() == {"version": "0.4.3", "lines": ["curl x", "sha256sum y"]}


def test_a_pack_it_can_not_check_gives_no_command(both, monkeypatch):
    def bad(v, cfg):
        raise release.ReleaseError("a bad signature")
    monkeypatch.setattr(klipper_cli, "pack_info", bad)
    r = post(client(both), "printers/pack", {}, code=None)
    assert r.status_code == 409 and "bad signature" in r.json()["error"] and "lines" not in r.json()


def test_detect_never_returns_the_key(both, kl, monkeypatch):
    registry.set_api_key(kl.serial, KEY)
    monkeypatch.setattr(klipper_cli, "detect", lambda p: {"ok": True, "problem": None, "message": "", "model": "Voron", "verified": True, "slots": ["T0"], "spoolman": None})
    r = post(client(both), f"printers/{kl.serial}/detect", {}, code=None)
    assert r.status_code == 200 and r.json()["model"] == "Voron" and KEY not in r.text


# ---------- slot mapping on the server's own Mapper ----------
@pytest.fixture
def mapped(env, helper, manager, names, monkeypatch):
    fake = FakeMapper()
    import filament_kit.api as api
    from test_setup_page import Spoolman
    on = modules.enabled(__import__("filament_kit.config", fromlist=["load"]).load()) | {"klipper"}
    app = api.create_app(Spoolman("http://127.0.0.1:9"), printers=manager, camera_hub=object(), mapper=fake, enabled_modules=on,
                         setup={"helper": helper, "hosts": lambda: {HOSTNAME}})
    return app, fake


def test_map_starts_follows_and_stops(mapped):
    app, fake = mapped
    _bambu()
    c = client(app)
    r = post(c, f"printers/{SERIAL}/map", {})
    assert r.status_code == 200 and r.json()["job_id"] == "job-1" and fake.started == [SERIAL]
    v = c.get(f"/setup/api/printers/{SERIAL}/map")
    assert v.status_code == 200 and v.json()["step"] == "testing slot A1"
    assert post(c, f"printers/{SERIAL}/map/stop", {}).status_code == 200 and fake.stopped == [SERIAL]
    assert fake.stop_pending == [False]      # a Stop with no job must not leave a pending abort for the next map


@pytest.mark.parametrize("error, words", [
    (mapping.AlreadyRunning(SERIAL), ""), (mapping.CertChanged(SERIAL), "certificate"), (PrinterBusy("printing"), "busy"),
    (PrinterOffline(SERIAL), "offline")])
def test_a_map_that_cant_start_says_why(mapped, error, words):
    app, fake = mapped
    _bambu()
    fake.fail = error
    r = post(client(app), f"printers/{SERIAL}/map", {})
    assert r.status_code == 409 and words in r.json()["error"]


def test_no_mapper_no_map(env, helper, manager, names):
    app = make(env, helper, manager, drop=frozenset({"printers"}), add=frozenset({"klipper"}))
    _bambu()
    assert post(client(app), f"printers/{SERIAL}/map", {}).status_code == 409


# ---------- the page ----------
def test_the_tab_has_its_own_script_under_the_same_csp(both):
    c = client(both)
    page = c.get("/setup").text
    assert "/setup/setup_printers.js" in page
    r = c.get("/setup/setup_printers.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]


def test_the_script_keeps_the_page_rules():
    text = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    assert "innerHTML" not in text and "eval(" not in text and "http" not in text


def test_the_add_form_asks_a_klipper_printer_for_no_access_code():
    text = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    klipper = text.split('if (family.value === "klipper") {')[1].split("} else {")[0]
    assert "Access Code" not in klipper and "access_code" not in klipper and "API key (optional)" in klipper
    row = text.split("function klipperRow(p)")[1].split("// -----")[0]
    assert "Access Code" not in row and "access_code" not in row


def test_a_running_mapping_is_followed_again_after_a_reload(mapped):
    """Review R31: the row says when this server's Mapper runs a job for the printer, and the page follows it (progress
    and Stop) as it draws, not only from the Map slots click; a refused start also joins a job that is running."""
    app, fake = mapped
    fake.running_for = set()
    fake.running = lambda serial: serial in fake.running_for
    _bambu()
    c = client(app)
    rows = c.get("/setup/api/state").json()["printers"]["list"]
    assert [r["mapping"] for r in rows if r["serial"] == SERIAL] == [False]
    fake.running_for.add(SERIAL)
    rows = c.get("/setup/api/state").json()["printers"]["list"]
    assert [r["mapping"] for r in rows if r["serial"] == SERIAL] == [True]
    text = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    assert "if (p.mapping) followMap(p, mapBox);" in text
    start = text.split("async function startMap(p, box)")[1].split("\n}\n")[0]
    assert 'state === "running") followMap(p, box)' in start


def test_a_family_with_its_module_off_is_not_rendered():
    text = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    assert '...(P.klipper ? [h("option"' in text and '...(P.bambu ? [h("option"' in text
    assert "P.klipper ? scanCard()" in text and "P.klipper ? packCard()" in text


def test_map_by_loading_filament_on_a_klipper_printer(env, helper, manager, kl):
    """The page's routes reach the Klipper family's session (bridge/klipper/manual.py), not the Bambu mapper."""
    from filament_kit.bridge import family
    from filament_kit.bridge.klipper import manual as kmanual
    from test_klipper_manual_map import StubFamily
    k = type("K", (), {"manual": kmanual.KlipperManualMaps(StubFamily(labels=("T0",))), "sync": lambda self: None})()
    c = client(make(env, helper, family.Printers(bambu=manager, klipper=k), add=frozenset({"klipper"})))
    r = post(c, f"printers/{kl.serial}/manual-map/start")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["step"]["position"]["label"] == "T0"
    r = post(c, f"printers/{kl.serial}/manual-map/stop", {"session": s["session"]})
    assert r.status_code == 200 and r.json()["open"] is False


def test_map_by_loading_filament_on_klipper_without_its_family_is_refused(both, kl):
    r = post(client(both), f"printers/{kl.serial}/manual-map/start")
    assert r.status_code == 409


def test_the_printers_tab_links_the_live_view_in_the_phone_web_app():
    """Interface parity (gap 5 of the 2026-11-10 matrix): the live printer view (slots, load, camera, controls, usage)
    is the phone web app's Printers tab; the setup page links it, only when the printers module gives the web app
    that tab, at /intake beside /setup on the same server."""
    text = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    card = text.split("function liveCard()")[1].split("\n}\n")[0]
    assert 'replace(/\/setup\/?$/, "") + "/intake#printers"' in card
    assert 'rel: "noopener"' in card and "Open the live printer view" in card
    assert "P.bambu ? liveCard() : null" in text


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs node")
def test_the_live_view_link_resolves_beside_the_setup_page():
    import json
    import re
    import shutil
    import subprocess
    text = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    expr = re.search(r"const url = (location\.pathname\..*);$", text, re.M).group(1)
    probe = ["/setup", "/setup/", "/kit/setup"]
    js = f"console.log(JSON.stringify({json.dumps(probe)}.map((p) => {{ const location = {{ pathname: p }}; return {expr}; }})));"
    out = subprocess.run([shutil.which("node"), "-e", js], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == ["/intake#printers", "/intake#printers", "/kit/intake#printers"]


# ---------- printer reports on the setup page (the user, 2026-11-10: "available on the computer setup page as well") ----------
def test_collect_list_and_download_a_report(mapped):
    app, fake = mapped
    _bambu()
    c = client(app)
    assert post(c, f"printers/{SERIAL}/report", {}, code=None).status_code in (401, 403)       # the code, as every write
    r = post(c, f"printers/{SERIAL}/report", {})
    assert r.status_code == 200 and r.json()["name"].startswith("printer-report-")
    v = post(c, f"printers/{SERIAL}/reports", {}).json()
    assert [x["name"] for x in v["reports"]] == [r.json()["name"]] and "never holds" in v["never"]
    d = post(c, f"printers/{SERIAL}/reports/{r.json()['name']}", {})
    assert d.status_code == 200 and d.content == b"<printer-report format='1'/>"
    assert f'filename="{r.json()["name"]}"' in d.headers["content-disposition"]


@pytest.mark.parametrize("name", ["..%2Fprinters.xml", "printers.xml", "printer-report-H2D-20261110-120000.xml.bak",
                                  "printer-report-H2D-20261110-120000.xml"])
def test_only_a_kept_report_downloads(mapped, name):
    app, _ = mapped
    _bambu()
    assert post(client(app), f"printers/{SERIAL}/reports/{name}", {}).status_code == 404


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX links")
def test_a_planted_link_is_not_followed(mapped, tmp_path):
    app, _ = mapped
    _bambu()
    from filament_kit import config
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / "secret"
    secret.write_text("not a report")
    (d / "printer-report-H2D-20261110-120000.xml").symlink_to(secret)
    c = client(app)
    assert post(c, f"printers/{SERIAL}/reports", {}).json()["reports"] == []
    assert post(c, f"printers/{SERIAL}/reports/printer-report-H2D-20261110-120000.xml", {}).status_code == 404


def test_an_offline_printer_says_so(mapped):
    app, fake = mapped
    _bambu()
    fake.fail = PrinterOffline(SERIAL)
    r = post(client(app), f"printers/{SERIAL}/report", {})
    assert r.status_code == 409 and "saved nothing" in r.json()["error"]


def test_the_row_says_when_a_report_would_help(mapped):
    app, _ = mapped
    _bambu()
    from filament_kit import config
    import json
    d = config.paths().state / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    (d / mapping.STATUS_FILE).write_text(json.dumps({"job_id": "x", "state": "done", "step": "", "problems": [],
                                                     "report_wanted": "no_scheme"}), encoding="utf-8")
    row = next(p for p in client(app).get("/setup/api/state").json()["printers"]["list"] if p["serial"] == SERIAL)
    assert row["report_why"]
    js = (STATIC / "setup_printers.js").read_text(encoding="utf-8")
    assert "Collect a report" in js and "Saved reports" in js and "function listReports(" in js
