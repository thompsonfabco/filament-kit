import json
import os
import stat

import pytest

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
