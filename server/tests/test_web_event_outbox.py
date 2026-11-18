"""The web unit's hand-over of spool events (R80 E1, EA4b): the outbox file, the sender against a fake Hub (resend after
a failure, all-or-none batches, the bad item set aside, caps), a restart, and the phone web app's spool changes
reaching the fake Hub through the app's own lifespan. No network, no real Hub."""
from __future__ import annotations

import logging
import os
import stat
import sys
import threading
import time

import pytest

pytest.importorskip("mcp")

from filament_kit import event_sink  # noqa: E402
from filament_kit.web import app as web_app  # noqa: E402
from filament_kit.web import event_outbox as eo  # noqa: E402
from filament_kit.web.slots import SlotError  # noqa: E402
from test_web_app import ORIGIN, _client, _web_spool, app, env, fake, lockout, readers, sm, store  # noqa: E402,F401

AT = "2026-11-17T10:00:00Z"


def moved(i, **kw):
    return {"kind": "spool.moved", "subject": {"type": "spool", "id": "7", "name": "x"}, "actor": None,
            "data": {"spool": "7", "before_location": "A", "after_location": f"B{i}"}, "at": f"2026-11-17T10:00:0{i}Z", **kw}


class FakeHub:
    """POST api/events/web as the Hub has it: all or none ("event i of n"), a resent item written once, and it can be
    down (SlotError unreachable) or refuse with a status."""

    def __init__(self):
        self.stored: list[dict] = []
        self.calls: list[list[dict]] = []
        self.down = False
        self.status = None
        self.lock = threading.Lock()

    def post(self, path, body):
        assert path == "/api/events/web"
        with self.lock:
            items = body["events"]
            self.calls.append(items)
            if self.down:
                raise SlotError("the kit server is not reachable", code="unreachable")
            if self.status:
                raise SlotError(f"the kit server answered {self.status}", http=self.status)
            for i, it in enumerate(items):
                if not it["kind"].startswith("spool.") or "nope" in it["data"]:
                    raise SlotError(f"event {i + 1} of {len(items)}: bad value", code="bad_request", http=400)
            for it in items:
                if it not in self.stored:
                    self.stored.append(it)
            return {"ok": True, "ids": list(range(1, len(items) + 1))}


def add(box, i, **kw):
    it = moved(i, **kw)
    box.add(it["kind"], it["subject"], it["actor"], it["data"], it["at"])


def sender(box, hub, **kw):
    return eo.Sender(box, hub, **kw)


@pytest.fixture
def box(tmp_path):
    return eo.Outbox(tmp_path / "web" / "events-outbox.xml")


# ---------------------------------------------------------------- the outbox file

def test_an_item_is_kept_in_xml_and_survives_a_restart(box, tmp_path):
    add(box, 1)
    add(box, 2, actor={"type": "device", "id": "web-app", "name": "phone web app"})
    text = box.path.read_text(encoding="utf-8")
    assert text.startswith("<?xml") and "<outbox" in text and not text.lstrip().startswith("{")
    again = eo.Outbox(box.path)                                    # the web unit restarted
    got = again.pending()
    assert [i["at"] for i in got] == ["2026-11-17T10:00:01Z", "2026-11-17T10:00:02Z"]
    assert got[1]["actor"]["name"] == "phone web app" and got[0]["data"]["after_location"] == "B1"
    add(again, 3)
    assert [i["n"] for i in again.pending()] == [1, 2, 3]            # numbers go on from where they were


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_the_file_is_private_and_a_link_is_refused(box, tmp_path):
    add(box, 1)
    assert stat.S_IMODE(os.stat(box.path).st_mode) == 0o600
    box.path.unlink()
    (tmp_path / "elsewhere").write_text("x")
    os.symlink(tmp_path / "elsewhere", box.path)
    add(box, 2)                                                    # not written through the link, never raises
    assert (tmp_path / "elsewhere").read_text() == "x" and len(box) == 2


def test_a_broken_file_is_kept_aside_and_the_outbox_starts_empty(box):
    box.path.parent.mkdir(parents=True)
    box.path.write_text("<outbox><event", encoding="utf-8")
    assert box.pending() == []
    assert box.path.with_name("events-outbox.xml.unreadable").exists()
    add(box, 1)
    assert len(eo.Outbox(box.path)) == 1


def test_the_count_cap_drops_the_oldest_with_a_log_line(tmp_path, caplog):
    box = eo.Outbox(tmp_path / "o.xml", max_items=3)
    with caplog.at_level(logging.WARNING):
        for i in range(1, 6):
            add(box, i)
    assert [i["data"]["after_location"] for i in box.pending()] == ["B3", "B4", "B5"]
    assert sum("more than 3 events wait" in r.message for r in caplog.records) == 2
    assert len(eo.Outbox(tmp_path / "o.xml", max_items=3)) == 3


def test_an_item_older_than_the_age_cap_is_dropped_with_a_log_line(tmp_path, caplog):
    now = [1_000_000.0]
    box = eo.Outbox(tmp_path / "o.xml", max_age=7 * 86400, clock=lambda: now[0])
    add(box, 1)
    now[0] += 6 * 86400
    add(box, 2)
    assert len(box.pending()) == 2
    now[0] += 2 * 86400                                            # item 1 is 8 days old, item 2 is 2
    with caplog.at_level(logging.WARNING):
        assert [i["data"]["after_location"] for i in box.pending()] == ["B2"]
    assert any("did not take it within 7 days" in r.message for r in caplog.records)
    assert len(eo.Outbox(tmp_path / "o.xml", clock=lambda: now[0])) == 1


# ---------------------------------------------------------------- the sink

def test_the_sink_queues_spool_events_once_and_nothing_else(box):
    s = eo.OutboxSink(box)
    s.write("spool.moved", {"type": "spool", "id": "7"}, {"type": "hub"}, {"spool": "7", "after_location": "B"})
    s.write("print.finished", {"type": "printer", "id": "p"}, None, {"job": "j"})
    s.write("location.renamed", {"type": "location", "id": "x"}, None, {})
    got = box.pending()
    assert len(got) == 1 and got[0]["kind"] == "spool.moved" and got[0]["at"].endswith("Z")
    assert "actor" not in eo.Outbox.body(got[0])                   # the Hub names the unit's own pairing


def test_the_sink_never_raises_into_the_change(box, caplog):
    class Broken(eo.Outbox):
        def add(self, *a, **kw):
            raise OSError("disk full")
    with caplog.at_level(logging.ERROR):
        assert eo.OutboxSink(Broken(box.path)).write("spool.moved", {"type": "spool", "id": "7"}, None, {}) is None
    assert any("not queued" in r.message for r in caplog.records)
    assert event_sink.emit("spool.moved", {"type": "spool", "id": "7"}) is None      # the default sink: nothing


def test_a_write_failure_keeps_the_item_in_memory_and_the_change_goes_on(box, monkeypatch, caplog):
    monkeypatch.setattr(eo.Outbox, "_write", lambda *a: (_ for _ in ()).throw(OSError("read-only")))
    with caplog.at_level(logging.WARNING):
        add(box, 1)
    assert len(box) == 1 and any("could not be written" in r.message for r in caplog.records)


# ---------------------------------------------------------------- the sender

def test_a_flush_posts_in_order_in_batches_and_empties_the_outbox(box):
    hub = FakeHub()
    for i in range(1, 6):
        add(box, i)
    assert sender(box, hub, batch=2).flush() is True
    assert [len(c) for c in hub.calls] == [2, 2, 1]
    assert [e["data"]["after_location"] for e in hub.stored] == [f"B{i}" for i in range(1, 6)]
    assert len(box) == 0 and hub.stored[0]["at"] == "2026-11-17T10:00:01Z"
    assert sender(box, hub).flush() is True and len(hub.calls) == 3         # nothing to send, nothing posted


def test_an_item_waits_while_the_hub_is_down_and_is_sent_once_when_it_is_back(box):
    hub = FakeHub()
    add(box, 1)
    hub.down = True
    s = sender(box, hub)
    assert s.flush() is False and s.flush() is False
    assert len(box) == 1 and hub.stored == []
    hub.down = False
    assert s.flush() is True and len(box) == 0 and len(hub.stored) == 1
    add(box, 2)
    assert s.flush() is True and [e["data"]["after_location"] for e in hub.stored] == ["B1", "B2"]


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_other_refusals_keep_the_items_and_are_not_quarantined(box, status):
    hub = FakeHub()
    hub.status = status
    add(box, 1)
    assert sender(box, hub).flush() is False
    assert len(box) == 1 and not box.rejected.exists()


def test_the_outbox_survives_a_restart_and_the_new_sender_sends_it(box):
    add(box, 1)
    add(box, 2)
    hub = FakeHub()
    assert sender(eo.Outbox(box.path), hub).flush() is True and len(hub.stored) == 2


def test_a_resent_batch_whose_answer_was_lost_is_not_written_twice(box):
    hub = FakeHub()
    add(box, 1)
    first = box.pending()
    hub.post(eo.PATH, {"events": [eo.Outbox.body(i) for i in first]})     # the Hub took it, the answer never came back
    assert sender(box, hub).flush() is True
    assert len(hub.stored) == 1 and len(hub.calls) == 2 and len(box) == 0


def test_a_bad_item_in_the_middle_is_set_aside_and_the_rest_is_sent(box, caplog):
    hub = FakeHub()
    add(box, 1)
    add(box, 2)
    box.add("spool.moved", {"type": "spool", "id": "7"}, None, {"nope": "1"}, AT)
    add(box, 4)
    with caplog.at_level(logging.WARNING):
        assert sender(box, hub).flush() is True
    assert [e["data"].get("after_location") for e in hub.stored] == ["B1", "B2", "B4"]
    assert [len(c) for c in hub.calls] == [4, 3]                           # not the same bad batch again
    assert len(box) == 0 and any("refused by the Hub" in r.message for r in caplog.records)
    kept, _ = box._read(box.rejected)
    assert len(kept) == 1 and kept[0]["data"] == {"nope": "1"}


def test_a_400_that_names_no_item_is_found_one_item_at_a_time(box):
    hub = FakeHub()
    real = hub.post

    def post(path, body):
        if len(body["events"]) > 1 and any("nope" in e["data"] for e in body["events"]):
            raise SlotError("the web unit may hand over spool.* events only", http=400)
        return real(path, body)
    hub.post = post
    add(box, 1)
    box.add("spool.moved", {"type": "spool", "id": "7"}, None, {"nope": "1"}, AT)
    add(box, 3)
    assert sender(box, hub).flush() is True
    assert [e["data"].get("after_location") for e in hub.stored] == ["B1", "B3"]
    assert len(box) == 0 and len(box._read(box.rejected)[0]) == 1


def test_every_item_bad_ends_with_an_empty_outbox_not_a_loop(box):
    hub = FakeHub()
    for _ in range(3):
        box.add("spool.moved", {"type": "spool", "id": "7"}, None, {"nope": "1"}, AT)
    assert sender(box, hub).flush() is True
    assert len(box) == 0 and len(hub.calls) == 3 and hub.stored == []     # each call names the first bad item: 3, 2, 1 left


def test_the_sender_never_raises(box):
    class Boom:
        def post(self, path, body):
            raise RuntimeError("surprise")
    add(box, 1)
    assert sender(box, Boom()).flush() is False and len(box) == 1


def test_the_thread_retries_with_a_wait_and_stops(box):
    hub = FakeHub()
    hub.down = True
    add(box, 1)
    s = sender(box, hub, backoff=(0.02, 0.05), idle=0.05)
    s.start()
    deadline = time.time() + 5
    while len(hub.calls) < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert len(hub.calls) >= 3 and len(box) == 1
    hub.down = False
    while len(box) and time.time() < deadline:
        time.sleep(0.01)
    assert len(box) == 0 and len(hub.stored) == 1
    add(box, 2)                                                    # an add wakes it
    s.wake.set()
    while len(hub.stored) < 2 and time.time() < deadline:
        time.sleep(0.01)
    s.stop()
    s.join(5)
    assert not s.is_alive() and len(hub.stored) == 2


# ---------------------------------------------------------------- the phone web app

def wait_for(pred, secs=10):
    deadline = time.time() + secs
    while not pred() and time.time() < deadline:
        time.sleep(0.02)
    return pred()


def test_a_spool_change_from_the_phone_reaches_the_hub_once_through_the_outbox(sm, store, lockout, fake, tmp_path):
    sid = _web_spool(sm)
    hub = FakeHub()
    handover = eo.Handover(hub, eo.Outbox(tmp_path / "ob" / "events-outbox.xml"), idle=0.05, backoff=(0.02, 0.05))
    app = web_app.build_app(sm=sm, store=store, lockout=lockout, claude=fake, kit_api=hub, handover=handover)
    post = {"headers": {"Origin": ORIGIN}}
    with _client(app) as c:
        assert isinstance(event_sink.sink(), eo.OutboxSink)
        r = c.post(f"/intake/api/spools/{sid}", json={"gross": 713, "dry_run": True}, **post)       # a preview: no event
        assert r.status_code == 200
        r = c.post(f"/intake/api/spools/{sid}", json={"gross": 713, "location": "Rack 1", "dry_run": False}, **post)
        assert r.status_code == 200
        assert wait_for(lambda: len(hub.stored) == 2)
        r = c.post(f"/intake/api/spools/{sid}", json={"empty": True, "dry_run": False}, **post)
        assert r.status_code == 200
        assert wait_for(lambda: len(hub.stored) == 3)
    assert not isinstance(event_sink.sink(), eo.OutboxSink)                                         # stopped with the app
    kinds = [e["kind"] for e in hub.stored]
    assert sorted(kinds) == ["spool.emptied", "spool.moved", "spool.weighed"], kinds
    assert all(e["subject"]["id"] == str(sid) and e["actor"] == eo.ACTOR_PHONE for e in hub.stored)
    assert len({e["data"]["batch"] for e in hub.stored[:2]}) == 1                                   # one request, one batch
    assert len(handover.outbox) == 0


def test_a_phone_request_does_not_wait_for_a_hub_that_is_down_and_the_change_is_kept(sm, store, lockout, fake, tmp_path):
    sid = _web_spool(sm)
    hub = FakeHub()
    hub.down = True
    path = tmp_path / "ob" / "events-outbox.xml"
    handover = eo.Handover(hub, eo.Outbox(path), idle=0.05, backoff=(0.02, 0.05))
    app = web_app.build_app(sm=sm, store=store, lockout=lockout, claude=fake, kit_api=hub, handover=handover)
    with _client(app) as c:
        r = c.post(f"/intake/api/spools/{sid}", json={"location": "Rack 1", "dry_run": False}, headers={"Origin": ORIGIN})
        assert r.status_code == 200 and sm.get(f"spool/{sid}")["location"] == "Rack 1"
        assert wait_for(lambda: len(hub.calls) >= 2)
        assert len(handover.outbox) == 1
    assert len(eo.Outbox(path)) == 1                                # kept for the next start
    hub.down = False
    assert eo.Sender(eo.Outbox(path), hub).flush() is True and [e["kind"] for e in hub.stored] == ["spool.moved"]


def test_the_501st_item_drops_the_oldest_with_a_log_line(tmp_path, caplog):
    assert eo.MAX_ITEMS == 500                                     # R80 E1
    box = eo.Outbox(tmp_path / "o.xml")
    with caplog.at_level(logging.WARNING):
        for i in range(501):
            box.add("spool.moved", {"type": "spool", "id": "7"}, None, {"after_location": f"B{i}"}, AT)
    got = box.pending(1000)
    assert len(got) == 500 and got[0]["data"]["after_location"] == "B1" and got[-1]["data"]["after_location"] == "B500"
    assert sum("more than 500 events wait" in r.message for r in caplog.records) == 1
