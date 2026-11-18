"""What a Tag Reader tells us (R83 s9.2): its build (`X-Reader-Build`) and when it last called, kept per token id."""
import json

import pytest

import test_reader as tr
from filament_kit import config, reader_tokens
from filament_kit.reader_tokens import SeenStore, TokenStore
from filament_kit.web import reader

env, sm, kit, queue, app, client = tr.env, tr.sm, tr.kit, tr.queue, tr.app, tr.client   # fixtures


class Clock:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


def seen_path():
    return config.paths().web / "reader-seen"


def test_parse_build():
    assert reader_tokens.parse_build("1794551072") == 1794551072 and reader_tokens.parse_build(" 7 ") == 7
    for bad in (None, "", "0", "-5", "1e9", "12 34", "abc", "1" * 13, 5, "١٢"):
        assert reader_tokens.parse_build(bad) is None


def test_identify_names_the_token_and_check_still_agrees(env):
    ts = TokenStore()
    a, ta = ts.issue("one")
    b, tb = ts.issue("two")
    assert ts.identify(ta) == a and ts.identify(tb) == b and ts.identify("nope") is None
    assert ts.identify(None) is None and ts.identify("") is None
    assert ts.check(ta) and not ts.check("nope")


def test_record_and_read_back(env):
    clock = Clock()
    s = SeenStore(clock=clock)
    assert s.read() == {}
    assert s.record("r1", 1794551072) is True
    assert s.read() == {"r1": {"build": 1794551072, "last_seen": "2027-01-15T08:00:00+00:00"}}
    clock.t += 3600
    assert s.record("r2", None) is True
    got = s.read()
    assert got["r2"]["build"] is None and got["r2"]["last_seen"].endswith("09:00:00+00:00") and "r1" in got


def test_the_file_is_xml_and_not_json(env):
    SeenStore().record("r1", 5)
    text = seen_path().read_text(encoding="utf-8")
    assert text.startswith("<?xml") and "<reader-seen" in text and 'id="r1"' in text and 'build="5"' in text
    with pytest.raises(ValueError):
        json.loads(text)


def test_a_call_without_a_build_keeps_the_build_known_and_a_new_build_is_written_at_once(env):
    clock = Clock()
    s = SeenStore(clock=clock)
    s.record("r1", 100)
    clock.t += 61
    s.record("r1", None)
    assert s.read()["r1"]["build"] == 100
    s.record("r1", 200)                                          # inside the interval, but the build changed
    assert s.read()["r1"]["build"] == 200


def test_frequent_calls_are_written_at_most_once_a_minute(env):
    clock = Clock()
    s = SeenStore(clock=clock)
    assert s.record("r1", 100) is True
    mtime = seen_path().stat().st_mtime_ns
    clock.t += 30
    assert s.record("r1", 100) is False and s.record("r1", None) is False
    assert seen_path().stat().st_mtime_ns == mtime
    clock.t += 31
    assert s.record("r1", 100) is True


def test_known_ids_prune_the_revoked(env):
    s = SeenStore()
    s.record("r1", 1)
    s.record("r2", 2)
    s.record("r3", 3, known={"r2", "r3"})
    assert set(s.read()) == {"r2", "r3"}


@pytest.mark.parametrize("raw", [b"", b"not xml", b"<other/>", b"<!DOCTYPE x [<!ENTITY a 'b'>]><reader-seen/>",
                                 b"<reader-seen><reader id='../x' build='1'/><reader id='r1' build='x'/></reader-seen>"])
def test_a_damaged_file_knows_nothing_and_never_raises(env, raw):
    seen_path().parent.mkdir(parents=True, exist_ok=True)
    seen_path().write_bytes(raw)
    got = SeenStore().read()
    assert "../x" not in got and all(v["build"] is None for v in got.values())


def test_record_refuses_an_id_that_is_not_a_token_id(env):
    s = SeenStore()
    for bad in ("", "x", "../r1", "r", None):
        assert s.record(bad, 1) is False
    assert not seen_path().exists()


def test_an_unwritable_place_is_logged_not_raised(env, monkeypatch, caplog):
    def boom(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(reader_tokens.pairing, "_write_atomic", boom)
    assert SeenStore().record("r1", 1) is False
    assert "cannot write" in caplog.text


# ---------- through the reader API ----------

def test_a_reader_call_records_its_build_and_time(app, env):
    ts = TokenStore()
    tid, tok = ts.issue("bench")
    with client(app) as c:
        r = c.get("/reader/healthz", headers={"X-Auth-Token": tok, "X-Reader-Build": "1794551072"})
        assert r.status_code == 200
    mark = SeenStore().read()[tid]
    assert mark["build"] == 1794551072 and mark["last_seen"]


def test_a_reader_that_sends_no_build_or_a_bad_one_is_served_and_noted(app, env):
    tid, tok = TokenStore().issue("bench")
    with client(app) as c:
        assert c.get("/reader/healthz", headers={"X-Auth-Token": tok}).status_code == 200
        assert c.get("/reader/healthz", headers={"X-Auth-Token": tok, "X-Reader-Build": "bad"}).status_code == 200
    assert SeenStore().read()[tid]["build"] is None


def test_a_refused_call_notes_nothing(app, env):
    TokenStore().issue("bench")
    with client(app) as c:
        assert c.get("/reader/healthz", headers={"X-Auth-Token": "wrong", "X-Reader-Build": "5"}).status_code == 401
    with client(app, tr.AWAY) as c:
        assert c.get("/reader/healthz", headers={"X-Reader-Build": "5"}).status_code == 403
    assert not seen_path().exists()


def test_a_store_that_cannot_write_does_not_fail_the_reader(app, env, monkeypatch):
    tid, tok = TokenStore().issue("bench")

    def boom(*a, **k):
        raise RuntimeError("disk")
    monkeypatch.setattr(SeenStore, "record", boom)
    with client(app) as c:
        assert c.get("/reader/healthz", headers={"X-Auth-Token": tok}).status_code == 200


# ---------- what the Hub shows ----------

def test_offered_build(env):
    assert reader_tokens.offered_build() is None
    fw = config.paths().state / "reader-fw"
    fw.mkdir()
    (fw / "manifest.json").write_text('{"build": 1794551072}', encoding="utf-8")
    assert reader_tokens.offered_build() == 1794551072
    for bad in ('{"build": "7"}', '{"build": true}', '{"build": 0}', "[1]", "nope", '{"x": 1}'):
        (fw / "manifest.json").write_text(bad, encoding="utf-8")
        assert reader_tokens.offered_build() is None


def test_readers_lists_build_last_seen_and_out_of_date(env):
    ts, seen = TokenStore(), SeenStore()
    a, _ = ts.issue("never called")
    b, _ = ts.issue("old")
    c, _ = ts.issue("current")
    seen.record(b, 100)
    seen.record(c, 200)
    rows = {r["id"]: r for r in reader_tokens.readers(ts, seen)}
    assert rows[a]["build"] is None and rows[a]["last_seen"] is None and rows[a]["out_of_date"] is False
    assert rows[b]["build"] == 100 and rows[b]["out_of_date"] is False                    # nothing offered: not called out
    fw = config.paths().state / "reader-fw"
    fw.mkdir()
    (fw / "manifest.json").write_text('{"build": 200}', encoding="utf-8")
    rows = {r["id"]: r for r in reader_tokens.readers(ts, seen)}
    assert (rows[a]["out_of_date"], rows[b]["out_of_date"], rows[c]["out_of_date"]) == (False, True, False)
    assert set(rows[b]) == {"id", "name", "created", "build", "last_seen", "out_of_date"}
    assert rows[b]["last_seen"].endswith("+00:00")
