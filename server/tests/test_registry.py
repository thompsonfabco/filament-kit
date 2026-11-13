import json
import os
import stat

import pytest

from filament_kit import hostaddr
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    return tmp_path


def test_repr_hides_access_code():
    p = Printer(serial="S1", access_code="12345678", configured=True)
    assert "12345678" not in repr(p)


def test_upsert_load_remove_roundtrip():
    registry.upsert(Printer("S1", "Office", "C11", "10.0.0.5", "99887766", True))
    got = registry.load()["S1"]
    assert (got.name, got.model, got.ip, got.access_code, got.configured) == ("Office", "C11", "10.0.0.5", "99887766", True)
    assert registry.remove("S1") is True
    assert registry.remove("S1") is False
    assert registry.load() == {}


def test_detected_adds_unconfigured():
    p = registry.detected("S2", "10.0.0.6", "N2", "Shed")
    assert p.configured is False and p.access_code == ""
    assert registry.load()["S2"].ip == "10.0.0.6"


def test_detected_updates_unconfigured_ip_model_name():
    registry.detected("S2", "10.0.0.6", "N2", "Shed")
    registry.detected("S2", "10.0.0.9", "N2", "Shed 2")
    p = registry.load()["S2"]
    assert (p.ip, p.name, p.configured) == ("10.0.0.9", "Shed 2", False)


def test_detected_updates_ip_of_configured_without_touching_code_or_name():
    registry.upsert(Printer("S3", "Mine", "O1D", "10.0.0.7", "55555555", True))
    registry.detected("S3", "10.0.0.8", "O1D", "Announced name")
    p = registry.load()["S3"]
    assert p.ip == "10.0.0.8"
    assert p.access_code == "55555555" and p.configured is True and p.name == "Mine"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_file_mode_600(env):
    registry.upsert(Printer("S1", access_code="x", configured=True))
    f = env / "state" / "printers.xml"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_file_is_xml_keyed_by_serial(env):
    registry.upsert(Printer("S1", "A"))
    assert '<printer id="S1" family="bambu" name="A"' in (env / "state" / "printers.xml").read_text()


def test_detected_unchanged_does_not_rewrite(env):
    registry.detected("S4", "10.0.0.1", "M", "N")
    f = env / "state" / "printers.xml"
    f.write_text(f.read_text() + " ")  # marker: a rewrite would drop it
    registry.detected("S4", "10.0.0.1", "M", "N")
    assert f.read_text().endswith(" ")
    registry.upsert(Printer("S5", "x", "m", "10.0.0.2", "c", True))
    f.write_text(f.read_text() + " ")
    registry.detected("S5", "10.0.0.2", "other", "other")
    assert f.read_text().endswith(" ")


def test_rename():
    registry.upsert(Printer("S1", "A", access_code="c", configured=True))
    assert registry.rename("S1", "B") is True
    assert registry.load()["S1"].name == "B" and registry.load()["S1"].access_code == "c"
    assert registry.rename("nope", "x") is False


def test_unknown_keys_ignored(env):
    (env / "state").mkdir()
    (env / "state" / "printers.json").write_text(json.dumps(
        {"S1": {"name": "A", "ip": "1.2.3.4", "future_field": 7}}))
    assert registry.load()["S1"].name == "A"


def test_corrupt_file_reads_empty_and_is_never_overwritten(env, caplog):
    (env / "state").mkdir()
    f = env / "state" / "printers.xml"
    f.write_text("{not json")
    assert registry.load() == {}
    assert "unreadable" in caplog.text
    for call in (lambda: registry.upsert(Printer("S1")), lambda: registry.remove("S1"),
                 lambda: registry.rename("S1", "x"), lambda: registry.detected("S1", "1.1.1.1")):
        with pytest.raises(registry.RegistryError):
            call()
    assert f.read_text() == "{not json"


# ---------- final review: root-run CLI must leave files the service user can read ----------

def _as_root(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid, **kw: calls.append((os.fspath(path), uid, gid)),
                        raising=False)
    # a new file's owner is set on its open temp file (pairing._write_atomic), never by name
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: calls.append(("<open temp file>", uid, gid)),
                        raising=False)
    return calls


def test_root_write_gives_file_to_state_dir_owner(env, monkeypatch):
    (env / "state").mkdir()
    st = os.stat(env / "state")
    calls = _as_root(monkeypatch)
    registry.upsert(Printer("S1", access_code="x", configured=True))
    temps = [c for c in calls if c[0] == "<open temp file>"]
    assert temps and all(c[1:] == (st.st_uid, st.st_gid) for c in temps), calls


def test_non_root_write_does_not_chown(env, monkeypatch):
    calls = _as_root(monkeypatch)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    registry.upsert(Printer("S1"))
    assert calls == []


@pytest.mark.skipif(os.name == "nt", reason="no cross-process lock file on Windows")
def test_root_lock_file_given_to_state_dir_owner(env, monkeypatch):
    (env / "state").mkdir()
    calls = _as_root(monkeypatch)
    registry.load()
    assert any(os.path.basename(c[0]) == "printers.lock" for c in calls), calls


def test_display_name_is_the_name_or_the_serial():
    assert registry.display_name(Printer("S1", "Office H2D")) == "Office H2D"
    assert registry.display_name(Printer("S1", "")) == "S1"


def test_peek_reads_the_old_file_and_writes_nothing(env):
    """A dry run looks: it must not migrate printers.json, or touch the state folder at all."""
    (env / "state").mkdir(exist_ok=True)
    (env / "state" / "printers.json").write_text(json.dumps({"S1": {"name": "One", "configured": True}}))
    before = sorted(x.name for x in (env / "state").iterdir())
    assert registry.peek()["S1"].name == "One"
    assert sorted(x.name for x in (env / "state").iterdir()) == before


def test_peek_leaves_a_changed_old_file_for_the_next_real_read(env):
    registry.upsert(Printer(serial="S1", name="One"))
    xml = (env / "state" / "printers.xml").read_bytes()
    (env / "state" / "printers.json").write_text(json.dumps({"S2": {"name": "Two"}}))
    assert "S2" in registry.peek()
    assert (env / "state" / "printers.xml").read_bytes() == xml
    assert "S2" in registry.load()


def test_the_migrate_dry_run_only_peeks(env):
    from types import SimpleNamespace

    from filament_kit import migrate
    (env / "state").mkdir(exist_ok=True)
    (env / "state" / "printers.json").write_text(json.dumps({"S1": {"name": "One"}}))
    before = sorted(x.name for x in (env / "state").iterdir())
    ctx = SimpleNamespace(apply=False, say=lambda *a: None, verb=lambda dry, done: dry)
    migrate._h2d_entry(ctx, "printers")
    assert sorted(x.name for x in (env / "state").iterdir()) == before


# --- one printer, one entry ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("again", ["voron.home.arpa", "VORON.home.arpa", "voron.home.arpa.", " voron.home.arpa "])
def test_add_klipper_refuses_a_host_and_port_already_added(again):
    first = registry.add_klipper("Voron", "voron.home.arpa")
    with pytest.raises(registry.DuplicatePrinter, match="Voron"):
        registry.add_klipper("Other", again)
    assert list(registry.load()) == [first.serial]


def test_add_klipper_same_host_on_another_port_is_another_printer():
    registry.add_klipper("One", "host.home.arpa", 7125)
    assert registry.add_klipper("Two", "host.home.arpa", 7126).port == 7126


def test_add_klipper_takes_over_the_entry_discovery_made():
    found = registry.detected_klipper("192.0.2.20", 7125, "mainsailos")
    p = registry.add_klipper("Voron", "192.0.2.20")
    assert p.serial == found.serial and p.configured and p.name == "Voron"
    assert len(registry.load()) == 1


def test_add_klipper_keeps_display_names_apart():
    """Spoolman slot locations are joined on the display name: two printers with one name would share spools."""
    assert registry.add_klipper("Voron", "a.home.arpa").name == "Voron"
    assert registry.add_klipper("voron", "b.home.arpa").name == "voron 2"
    assert registry.add_klipper("Voron", "c.home.arpa").name == "Voron 3"


def test_bambu_adds_keep_display_names_apart():
    registry.upsert(Printer("S1", "Bench", "C12", "10.0.0.5", "x", True))
    assert registry.set_code("S2", "12345678", "bench").name == "bench 2"
    assert registry.add_bambu("S3", "BENCH", "C12", "10.0.0.7", "12345678").name == "BENCH 3"
    assert registry.add_bambu("S3", "BENCH", "C12", "10.0.0.7", "12345678").name == "BENCH 3"   # the same printer again
    assert registry.set_code("S1", "87654321", replace=True).name == "Bench"                    # a code swap keeps the name
    assert registry.add_bambu("S4", "", "", "10.0.0.8", "12345678").name == "S4"                # no name: the serial


def test_first_configure_of_a_found_printer_gets_a_free_name():
    registry.upsert(Printer("S1", "Bench", "C12", "10.0.0.5", "x", True))
    registry.detected("S2", "10.0.0.6", "C12", "Bench")          # announces itself under the taken name
    assert registry.set_code("S2", "12345678").name == "Bench 2"


def test_an_existing_entry_keeps_its_stored_name_even_when_shared():
    registry.upsert(Printer("S1", "Bench", "C12", "10.0.0.5", "x", True))
    registry.upsert(Printer("S2", "Bench", "C12", "10.0.0.6", "x", True))   # shared before the fix
    assert registry.add_bambu("S2", "Bench", "C12", "10.0.0.6", "12345678").name == "Bench"
    assert registry.set_code("S2", "87654321", replace=True).name == "Bench"
    assert registry.add_bambu("S2", "Shed", "C12", "10.0.0.6", "12345678").name == "Shed"   # a new name still applies


def test_free_names_stay_within_the_name_limit():
    long = "x" * registry.NAME_MAX
    registry.upsert(Printer("S1", long, "C12", "10.0.0.5", "x", True))
    got = registry.add_bambu("S2", long, "C12", "10.0.0.6", "12345678").name
    assert len(got) == registry.NAME_MAX and got.endswith(" 2") and got != long
    k = registry.add_klipper(long, "a.home.arpa").name
    assert len(k) == registry.NAME_MAX and k.endswith(" 3")


def test_detected_klipper_matches_a_name_whatever_its_case():
    first = registry.add_klipper("Voron", "Voron.home.arpa")
    assert registry.detected_klipper("voron.home.arpa", 7125).serial == first.serial
    assert len(registry.load()) == 1


def test_unconfigured_entries_are_capped_and_the_oldest_goes():
    configured = registry.add_klipper("Mine", "mine.home.arpa")
    for i in range(registry.MAX_FOUND + 5):
        registry.detected_klipper(f"10.0.{i // 250}.{i % 250 + 1}", 7125)
    printers = registry.load()
    assert configured.serial in printers
    hosts = [p.host for p in printers.values() if not p.configured]
    assert len(hosts) == registry.MAX_FOUND and "10.0.0.1" not in hosts and "10.0.0.37" in hosts


def test_the_cap_keeps_an_entry_that_holds_an_api_key():
    kept = registry.detected_klipper("10.0.0.200", 7125)
    registry.set_api_key(kept.serial, "abc")
    for i in range(registry.MAX_FOUND + 5):
        registry.detected_klipper(f"10.0.1.{i + 1}", 7125)
    assert kept.serial in registry.load()


def test_a_discovered_entry_never_replaces_bambu():
    registry.upsert(Printer(serial="S1", name="Bambu"))
    for i in range(registry.MAX_FOUND + 5):
        registry.detected_klipper(f"10.0.1.{i + 1}", 7125)
    assert "S1" in registry.load()


def test_forget_found_at_only_takes_unconfigured_klipper_entries():
    twin = registry.detected_klipper("192.0.2.20", 7125, "twin")
    keyed = registry.detected_klipper("192.0.2.21", 7125, "keyed")
    registry.set_api_key(keyed.serial, "abc")
    other = registry.detected_klipper("192.0.2.22", 7125, "other")
    mine = registry.add_klipper("Mine", "192.0.2.23")
    assert registry.forget_found_at({("192.0.2.20", 7125), ("192.0.2.21", 7125), ("192.0.2.23", 7125)}) == 1
    assert set(registry.load()) == {keyed.serial, other.serial, mine.serial} and twin.serial not in registry.load()


def test_rename_keeps_display_names_apart():
    """Spoolman slot locations join on the display name, so a rename must not make two printers share spools."""
    registry.add_klipper("Voron", "192.0.2.20")
    other = registry.add_klipper("Other", "192.0.2.21")
    assert registry.rename(other.serial, "voron")
    assert registry.display_name(registry.load()[other.serial]) == "voron 2"
    assert registry.rename(other.serial, "voron 2")                # its own name is free to it
    assert registry.display_name(registry.load()[other.serial]) == "voron 2"


def _spellings(monkeypatch):
    table = {"voron.local": {"192.0.2.20"}, "workshop.example.com": {"192.0.2.20", "2001:db8::20"},
             "192.0.2.20": {"192.0.2.20"}, "other.local": {"192.0.2.21"}}
    monkeypatch.setattr(hostaddr, "addresses", lambda host, **kw: table.get(host, set()))


def test_klipper_at_finds_a_printer_by_any_spelling_of_it(monkeypatch):
    _spellings(monkeypatch)
    by_name = registry.add_klipper("Voron", "voron.local")
    printers = registry.load()
    for spelling in ("voron.local", "VORON.local", "192.0.2.20", "workshop.example.com"):
        assert registry.klipper_at(printers, spelling, 7125).serial == by_name.serial, spelling
    assert registry.klipper_at(printers, "other.local", 7125) is None
    assert registry.klipper_at(printers, "192.0.2.20", 7126) is None             # another port is another Moonraker


def test_klipper_at_finds_a_name_for_a_printer_added_by_address(monkeypatch):
    _spellings(monkeypatch)
    by_address = registry.add_klipper("Voron", "192.0.2.20")
    assert registry.klipper_at(registry.load(), "voron.local", 7125).serial == by_address.serial


def test_klipper_at_prefers_the_added_printer_to_a_found_entry_at_the_address(monkeypatch):
    """A twin an announcement left must not hide the printer it is a twin of."""
    _spellings(monkeypatch)
    mine = registry.add_klipper("Voron", "voron.local")
    registry.detected_klipper("192.0.2.20", 7125, lookups=False)
    assert registry.klipper_at(registry.load(), "192.0.2.20", 7125).serial == mine.serial


def test_klipper_at_still_finds_a_found_entry_with_no_added_printer_there(monkeypatch):
    _spellings(monkeypatch)
    registry.add_klipper("Voron", "voron.local")
    found = registry.detected_klipper("192.0.2.21", 7125, lookups=False)
    assert registry.klipper_at(registry.load(), "192.0.2.21", 7125).serial == found.serial


def test_klipper_at_looks_nothing_up_with_nothing_to_compare(monkeypatch):
    monkeypatch.setattr(hostaddr, "addresses", lambda host, **kw: pytest.fail("a lookup with nothing to compare"))
    registry.add_klipper("Other port", "voron.local", 7126)
    assert registry.klipper_at(registry.load(), "workshop.local", 7125) is None


def test_klipper_at_ignores_a_name_that_does_not_resolve(monkeypatch):
    monkeypatch.setattr(hostaddr, "addresses", lambda host, **kw: set())
    registry.add_klipper("Voron", "voron.local")
    assert registry.klipper_at(registry.load(), "other.local", 7125) is None


def test_detected_klipper_can_leave_the_lookups_to_its_caller(monkeypatch):
    monkeypatch.setattr(hostaddr, "addresses", lambda host, **kw: pytest.fail("no lookups were asked for"))
    registry.add_klipper("Voron", "voron.local")
    assert not registry.detected_klipper("192.0.2.20", 7125, lookups=False).configured
