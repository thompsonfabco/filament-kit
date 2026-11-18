"""What a Tag Reader tells us (R83 s9.2, ruled 20:33): the web unit keeps the newest build and call time per reader in
memory and hands them to the Hub on POST /api/readers/web/seen; the Hub keeps the newest in its own file."""
import json
import threading

import pytest

import test_reader as tr
from filament_kit import config, hub_view, reader_tokens
from filament_kit.reader_tokens import SeenBuffer, SeenError, SeenStore, TokenStore, flush, record_seen

env, sm, kit, queue, app, client = tr.env, tr.sm, tr.kit, tr.queue, tr.app, tr.client   # fixtures
T0 = 1_800_000_000.0


class Clock:
    t = T0

    def __call__(self):
        return self.t


class Hub:
    """The kit's side as the web unit's client sees it: records the calls, can be made to fail."""

    def __init__(self):
        self.calls, self.down = [], False

    def post(self, path, body):
        if self.down:
            raise OSError("no answer")
        self.calls.append((path, body))
        return {"ok": True}


def seen_path():
    return config.paths().state / "reader-seen"


def test_parse_build():
    assert reader_tokens.parse_build("1794551072") == 1794551072 and reader_tokens.parse_build(" 7 ") == 7
    assert reader_tokens.parse_build(42) == 42
    for bad in (None, "", "0", "-5", "1e9", "12 34", "abc", "1" * 13, True, "١٢"):
        assert reader_tokens.parse_build(bad) is None


def test_identify_names_the_token_and_check_still_agrees(env):
    ts = TokenStore()
    a, ta = ts.issue("one")
    b, tb = ts.issue("two")
    assert ts.identify(ta) == a and ts.identify(tb) == b and ts.identify("nope") is None
    assert ts.identify(None) is None and ts.identify("") is None
    assert ts.check(ta) and not ts.check("nope")


# ---------- the web unit: throttle and memory ----------

def test_the_first_call_and_a_build_change_are_sent_at_once_and_a_second_call_within_a_minute_is_not():
    clock, hub = Clock(), Hub()
    buf = SeenBuffer(clock)
    buf.note("r1", 100)
    assert flush(buf, hub) is True
    assert hub.calls == [("/api/readers/web/seen", {"readers": [{"id": "r1", "build": 100,
                                                                  "seen_at": "2027-01-15T08:00:00+00:00"}]})]
    clock.t += 30
    buf.note("r1", 100)
    assert flush(buf, hub) is False and len(hub.calls) == 1             # same build, inside the minute
    clock.t += 5
    buf.note("r1", 200)                                                 # a changed build goes at once
    assert flush(buf, hub) is True and hub.calls[-1][1]["readers"][0]["build"] == 200
    clock.t += 61
    buf.note("r1", None)                                                # a call that tells no build, after a minute
    assert flush(buf, hub) is True and hub.calls[-1][1]["readers"][0]["build"] == 200
    assert flush(buf, hub) is False                                     # nothing new since


def test_one_post_carries_every_reader_due():
    clock, hub = Clock(), Hub()
    buf = SeenBuffer(clock)
    buf.note("r2", 5)
    buf.note("r1", None)
    assert flush(buf, hub) and [r["id"] for r in hub.calls[0][1]["readers"]] == ["r1", "r2"]
    assert "build" not in hub.calls[0][1]["readers"][0]                 # a reader that told no build


def test_a_hub_that_does_not_answer_keeps_the_newest_value_for_the_next_call():
    clock, hub = Clock(), Hub()
    buf = SeenBuffer(clock)
    hub.down = True
    buf.note("r1", 100)
    assert flush(buf, hub) is False                                     # no exception to the caller
    clock.t += 10
    buf.note("r1", 150)                                                 # newer value replaces the old one
    clock.t += 1
    assert flush(buf, hub) is False and hub.calls == []
    hub.down = False
    clock.t += 1
    assert flush(buf, hub) is True
    (sent,) = hub.calls[0][1]["readers"]
    assert sent["build"] == 150 and sent["seen_at"] == "2027-01-15T08:00:10+00:00"


def test_a_call_that_arrives_while_the_batch_is_in_flight_stays_due():
    clock = Clock()
    buf = SeenBuffer(clock)
    buf.note("r1", 100)
    batch = buf.due()
    clock.t += 70
    buf.note("r1", 100)
    buf.sent(batch)
    assert buf.due() == []                                              # just handed over: not again inside the minute
    clock.t += 61
    assert [r["id"] for r in buf.due()] == ["r1"]                       # but the call that came meanwhile is not lost


def test_a_note_for_something_that_is_not_a_token_id_is_ignored():
    buf = SeenBuffer(Clock())
    for bad in ("", "x", "../r1", None):
        buf.note(bad, 1)
    assert buf.due() == []


# ---------- the Hub: record_seen ----------

def at(sec):
    return reader_tokens._utc(T0 + sec)


def test_record_seen_keeps_the_newest_and_answers_ok(env):
    a, _ = TokenStore().issue("bench")
    assert record_seen([{"id": a, "build": 100, "seen_at": at(0)}], now=T0) == {"ok": True}
    assert SeenStore().read()[a] == {"build": 100, "last_seen": at(0)}
    record_seen([{"id": a, "build": 90, "seen_at": at(-60)}], now=T0)          # an older report does not win
    assert SeenStore().read()[a] == {"build": 100, "last_seen": at(0)}
    record_seen([{"id": a, "seen_at": at(30)}], now=T0 + 30)                    # newer, no build: the build is kept
    assert SeenStore().read()[a] == {"build": 100, "last_seen": at(30)}
    record_seen([{"id": a, "build": 200, "seen_at": at(60)}, {"id": a, "build": 150, "seen_at": at(50)}], now=T0 + 60)
    assert SeenStore().read()[a] == {"build": 200, "last_seen": at(60)}


def test_the_hubs_file_is_xml_in_its_state_folder(env):
    a, _ = TokenStore().issue("bench")
    record_seen([{"id": a, "build": 5, "seen_at": at(0)}], now=T0)
    text = seen_path().read_text(encoding="utf-8")
    assert text.startswith("<?xml") and 'id="r1"' in text and 'build="5"' in text
    with pytest.raises(ValueError):
        json.loads(text)
    assert not (config.paths().web / "reader-seen").exists()                   # nothing in the web unit's folder


def test_an_unknown_or_revoked_reader_is_ignored_and_named(env):
    ts = TokenStore()
    a, _ = ts.issue("one")
    b, _ = ts.issue("two")
    out = record_seen([{"id": a, "build": 1, "seen_at": at(0)}, {"id": "r99", "build": 2, "seen_at": at(0)}], now=T0)
    assert out == {"ok": True, "ignored": ["r99"]} and set(SeenStore().read()) == {a}
    record_seen([{"id": b, "build": 3, "seen_at": at(0)}], now=T0)
    ts.revoke(b)
    record_seen([{"id": a, "build": 1, "seen_at": at(10)}], now=T0 + 10)
    assert set(SeenStore().read()) == {a}                                       # the revoked one's record is dropped
    assert record_seen([{"id": b, "build": 3, "seen_at": at(20)}], now=T0 + 20)["ignored"] == [b]


@pytest.mark.parametrize("body", [None, "x", {"id": "r1"}, [1], [{"id": 1, "seen_at": "2027-01-15T08:00:00Z"}],
                                  [{"id": "../x", "seen_at": "2027-01-15T08:00:00Z"}], [{"id": "r1"}],
                                  [{"id": "r1", "seen_at": "yesterday"}],
                                  [{"id": "r1", "seen_at": "2027-01-15T08:00:00Z", "build": "abc"}],
                                  [{"id": "r1", "seen_at": "2030-01-01T00:00:00Z"}],       # far in the future
                                  [{"id": "r1", "seen_at": "2027-01-15T08:00:00Z"}] * 65])
def test_a_body_that_is_not_the_contract_is_refused_and_keeps_nothing(env, body):
    TokenStore().issue("bench")
    with pytest.raises(SeenError):
        record_seen(body, now=T0)
    assert not seen_path().exists()


def test_an_unwritable_hub_state_raises_oserror_for_the_route_to_report(env, monkeypatch):
    a, _ = TokenStore().issue("bench")

    def boom(*args, **kw):
        raise PermissionError(13, "denied")
    monkeypatch.setattr(reader_tokens.pairing, "_write_atomic", boom)
    with pytest.raises(OSError):
        record_seen([{"id": a, "seen_at": at(0)}], now=T0)


@pytest.mark.parametrize("raw", [b"", b"not xml", b"<other/>", b"<!DOCTYPE x [<!ENTITY a 'b'>]><reader-seen/>",
                                 b"<reader-seen><reader id='../x' build='1'/><reader id='r1' build='x'/></reader-seen>"])
def test_a_damaged_file_knows_nothing_and_never_raises(env, raw):
    seen_path().write_bytes(raw)
    got = SeenStore().read()
    assert "../x" not in got and all(v["build"] is None for v in got.values())


# ---------- through the reader API ----------

def test_a_reader_call_is_handed_to_the_hub_with_its_build(app, env, monkeypatch):
    tid, tok = TokenStore().issue("bench")
    hub = Hub()
    from filament_kit.web import reader as web_reader
    sent = threading.Event()
    real = web_reader.flush

    def flush_here(buf, kit):
        r = real(buf, hub)
        sent.set()
        return r
    monkeypatch.setattr(web_reader, "flush", flush_here)
    with client(app) as c:
        r = c.get("/reader/healthz", headers={"X-Auth-Token": tok, "X-Reader-Build": "1794551072"})
        assert r.status_code == 200
        assert sent.wait(10)
    (path, body), = hub.calls
    assert path == "/api/readers/web/seen" and body["readers"][0]["id"] == tid
    assert body["readers"][0]["build"] == 1794551072 and body["readers"][0]["seen_at"]
    assert not seen_path().exists()


def test_a_reader_is_served_when_the_hub_does_not_answer(app, env, monkeypatch):
    tid, tok = TokenStore().issue("bench")
    from filament_kit.web import reader as web_reader

    def boom(buf, kit):
        raise RuntimeError("hub down")
    monkeypatch.setattr(web_reader, "flush", boom)
    with client(app) as c:
        assert c.get("/reader/healthz", headers={"X-Auth-Token": tok, "X-Reader-Build": "bad"}).status_code == 200
        assert c.get("/reader/healthz", headers={"X-Auth-Token": tok}).status_code == 200


def test_a_refused_call_notes_nothing(app, env):
    TokenStore().issue("bench")
    seen = []
    with client(app) as c:
        assert c.get("/reader/healthz", headers={"X-Auth-Token": "wrong", "X-Reader-Build": "5"}).status_code == 401
    with client(app, tr.AWAY) as c:
        assert c.get("/reader/healthz", headers={"X-Reader-Build": "5"}).status_code == 403
    assert seen == [] and not seen_path().exists()


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
    ts = TokenStore()
    a, _ = ts.issue("never called")
    b, _ = ts.issue("old")
    c, _ = ts.issue("current")
    record_seen([{"id": b, "build": 100, "seen_at": at(0)}, {"id": c, "build": 200, "seen_at": at(0)}], now=T0)
    rows = {r["id"]: r for r in reader_tokens.readers()}
    assert rows[a]["build"] is None and rows[a]["last_seen"] is None and rows[a]["out_of_date"] is False
    assert rows[b]["build"] == 100 and rows[b]["out_of_date"] is False                 # nothing offered: not called out
    fw = config.paths().state / "reader-fw"
    fw.mkdir()
    (fw / "manifest.json").write_text('{"build": 200}', encoding="utf-8")
    rows = {r["id"]: r for r in reader_tokens.readers()}
    assert (rows[a]["out_of_date"], rows[b]["out_of_date"], rows[c]["out_of_date"]) == (False, True, False)
    assert rows[b]["last_seen"] == at(0)


def test_hub_view_shows_build_and_last_seen_from_the_hubs_store(env):
    a, _ = TokenStore().issue("bench")
    record_seen([{"id": a, "build": 1794551072, "seen_at": at(0)}], now=T0)
    d = hub_view.build(paired=[])["devices"]
    assert d == [{"name": "bench", "kind": "reader", "version": "1794551072", "last_seen": int(T0),
                  "out_of_date": False, "this": False}]
