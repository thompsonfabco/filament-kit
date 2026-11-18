"""web.push fed from the Hub's events (R80, EA4): the push.xml store and its one-time move from push.json, one push per
alert event, a condition once while it lasts, and the web twins of the events and alerts routes. No network, no Hub:
the kit API is a fake that answers GET api/events from a list."""
from __future__ import annotations

import json
import sys
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp")

from filament_kit import config  # noqa: E402
from filament_kit.web import push  # noqa: E402
from filament_kit.web.slots import SlotError  # noqa: E402
from test_web_printers import AWAY, FakeKit, H, env, kit, make_app, signed  # noqa: E402,F401

EP = "https://fcm.googleapis.com/a"
KEYS = {"p256dh": "k", "auth": "a"}


def sub(n="a"):
    return {"endpoint": f"https://fcm.googleapis.com/{n}", "keys": dict(KEYS)}


def alert(i, kind="print.failed", **kw):
    return {"id": i, "at": "2026-11-17T20:00:00Z", "kind": kind, "severity": "alert", "subject": {}, "actor": {},
            "data": {}, "condition": None, "alert": True, "title": f"title {i}", "text": f"text {i}",
            "action": {"place": "printer", "id": "SER 1"}, **kw}


class EventKit(FakeKit):
    """GET api/events from `events`: since / limit as the Hub has them; every call is kept in `queries`."""

    def __init__(self, events=()):
        super().__init__()
        self.events = list(events)
        self.queries: list[dict] = []

    def get(self, path):
        if not path.startswith("/api/events"):
            return super().get(path)
        self._check()
        self.calls.append(("GET", path))
        q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        self.queries.append(q)
        out = [e for e in self.events if e["id"] > int(q.get("since", 0))][:int(q.get("limit", 100))]
        return {"events": out, "next": out[-1]["id"] if out else int(q.get("since", 0)), "oldest": 1}


class Sent:
    def __init__(self):
        self.payloads: list[dict] = []
        self.calls: list[dict] = []          # what each push carried besides its payload: {topic, ttl}

    def __call__(self, info, payload, topic=None, ttl=None):
        self.payloads.append(json.loads(payload))
        self.calls.append({"topic": topic, "ttl": ttl})
        return 201


def make_feed(kit, n_subs=1):
    store = push.Store(config.paths().web / "push.xml")
    for n in range(n_subs):
        store.add(sub(str(n)))
    sent = Sent()
    return push.Feed(kit, store, sent, "https://x.example/filament/intake/", wait=0), sent


# ---------- push.xml ----------

def test_store_moves_push_json_once_and_never_touches_it(env):
    web = config.paths().web
    web.mkdir(parents=True, exist_ok=True)
    old = web / "push.json"
    old.write_text(json.dumps({"subs": {EP: {"info": sub("a"), "created": 5.0}}}), encoding="utf-8")
    before = (old.read_bytes(), old.stat().st_mtime_ns)
    store = push.Store(web / "push.xml", legacy=old)
    assert list(store.subs()) == [EP]
    assert (web / "push.xml").exists() and "<sub " in (web / "push.xml").read_text()
    store.remove(EP)                                   # emptied: the old file must not bring it back
    assert push.Store(web / "push.xml", legacy=old).subs() == {}
    assert (old.read_bytes(), old.stat().st_mtime_ns) == before


def test_store_ignores_push_json_when_push_xml_exists(env):
    web = config.paths().web
    web.mkdir(parents=True, exist_ok=True)
    push.Store(web / "push.xml").add(sub("new"))
    (web / "push.json").write_text(json.dumps({"subs": {EP: {"info": sub(), "created": 1}}}), encoding="utf-8")
    assert list(push.Store(web / "push.xml", legacy=web / "push.json").subs()) == ["https://fcm.googleapis.com/new"]


def test_store_keeps_a_broken_file_aside_and_does_not_crash(env):
    web = config.paths().web
    web.mkdir(parents=True, exist_ok=True)
    (web / "push.xml").write_text("<push><sub", encoding="utf-8")
    store = push.Store(web / "push.xml")
    assert store.subs() == {}
    store.add(sub())
    assert (web / "push.xml.unreadable").read_text() == "<push><sub" and list(store.subs()) == [EP]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes and links")
def test_store_mode_and_symbolic_link(env):
    web = config.paths().web
    store = push.Store(web / "push.xml")
    store.add(sub())
    assert ((web / "push.xml").stat().st_mode & 0o777) == 0o600
    (web / "push.xml").unlink()
    (web / "target").write_text("x")
    (web / "push.xml").symlink_to(web / "target")
    with pytest.raises(Exception):
        store.add(sub())
    assert (web / "target").read_text() == "x"


# ---------- the feed ----------

def test_first_start_replays_no_history_then_sends_each_alert_once(env):
    kit = EventKit([alert(1), alert(2)])
    feed, sent = make_feed(kit, n_subs=2)
    feed.tick()                                        # first sight: finds the newest id (2), sends nothing
    assert feed.last == 2 and sent.payloads == []
    kit.events.append(alert(3))
    feed.tick()
    assert [p["title"] for p in sent.payloads] == ["title 3", "title 3"]        # one event, one push per phone
    assert sent.payloads[0]["body"] == "text 3" and sent.payloads[0]["tag"] == "sw-event-3"
    assert sent.payloads[0]["url"] == "https://x.example/filament/intake/#printers/SER%201"
    feed.tick()
    assert len(sent.payloads) == 2                     # nothing new, nothing sent


def test_only_alert_events_and_only_phones_that_subscribed(env):
    kit = EventKit()
    feed, sent = make_feed(kit)
    feed.tick()
    kit.events.append(alert(1, "print.finished", alert=False))
    feed.tick()
    assert sent.payloads == [] and feed.last == 1
    for ep in list(feed.store.subs()):
        feed.store.remove(ep)                          # nobody subscribed: an alert goes nowhere
    kit.events.append(alert(2))
    feed.tick()
    assert sent.payloads == []


def cond(i, key, state="raised", severity="alert", **kw):
    return alert(i, condition={"key": key, "state": state}, severity=severity, **kw)


def test_a_condition_notifies_when_raised_not_while_it_lasts_and_clears_quietly(env):
    kit = EventKit()
    feed, sent = make_feed(kit)
    feed.tick()
    kit.events += [cond(1, "printer.p1.paused"), cond(2, "printer.p1.paused")]
    feed.tick()
    assert [p["title"] for p in sent.payloads] == ["title 1"]                 # the repeat while it lasts: silent
    kit.events.append(cond(3, "storage.low", severity="warn"))
    kit.events.append(cond(4, "storage.low", severity="bad"))                 # worse: a new notification
    feed.tick()
    assert [p["tag"] for p in sent.payloads] == ["sw-condition-printer.p1.paused", "sw-condition-storage.low", "sw-condition-storage.low"]
    gone = {"key": "printer.p1.paused", "state": "cleared"}
    n = len(sent.payloads)
    kit.events.append(alert(5, "print.resumed", alert=False, condition=gone))
    feed.tick()
    assert len(sent.payloads) == n                                            # a key outside the two that matter: nothing
    kit.events.append(cond(6, "print-paused:p1"))
    feed.tick()
    kit.events.append(alert(7, "print.resumed", alert=False, condition={"key": "print-paused:p1", "state": "cleared"}))
    feed.tick()
    r = sent.payloads[-1]
    assert (r["title"], r["body"], r["tag"], r["silent"], r["renotify"]) == ("title 7", "text 7", "sw-condition-print-paused:p1",
                                                                              True, False)
    assert "clear" not in r and sent.calls[-1]["ttl"] == push.REPLACE_TTL
    assert sent.calls[-1]["topic"] == sent.calls[-2]["topic"] == push.topic_of("sw-condition-print-paused:p1")   # one Topic: replaces
    assert sent.calls[-2]["ttl"] is None                                                           # the alert's TTL as built
    m = len(sent.payloads)
    kit.events.append(alert(8, "print.resumed", alert=False, condition={"key": "print-paused:p1", "state": "cleared"}))
    feed.tick()
    assert len(sent.payloads) == m                                            # an ending nobody was told of: nothing
    kit.events.append(cond(9, "print-paused:p1"))
    feed.tick()
    assert sent.payloads[-1]["title"] == "title 9" and "silent" not in sent.payloads[-1]   # raised again: told again


def test_storage_and_running_low_endings_push_nothing_and_device_down_is_replaced(env):
    kit = EventKit()
    feed, sent = make_feed(kit)
    feed.tick()
    kit.events += [cond(1, "storage-low", severity="warn"), cond(2, "spool-low:7"), cond(3, "device-down:w1")]
    feed.tick()
    n = len(sent.payloads)
    assert n == 3
    for i, key in enumerate(("storage-low", "spool-low:7", "device-down:w1"), 4):
        kit.events.append(alert(i, "x.ended", alert=False, condition={"key": key, "state": "cleared"}))
    feed.tick()
    assert [p["tag"] for p in sent.payloads[n:]] == ["sw-condition-device-down:w1"] and sent.payloads[-1]["silent"] is True


def test_topic_is_a_short_url_safe_hash_and_a_refusing_service_is_asked_again_without_it(env, monkeypatch):
    import re
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,32}", push.topic_of("print-paused:" + "x" * 500))
    assert push.topic_of("a") != push.topic_of("b")
    monkeypatch.setattr(push, "NO_TOPIC", set())
    store = push.Store(config.paths().web / "push.xml")
    store.add(sub("a"))
    seen = []

    def service(info, payload, topic=None, ttl=None):                        # a fake push service that refuses Topic
        seen.append(topic)
        return 400 if topic else 201
    assert push.send_all(store, "t", "b", "tag-1", sender=service)["sent"] == 1
    assert seen[0] == push.topic_of("tag-1") and seen[1] is None             # asked again without it, once
    assert "fcm.googleapis.com" in push.NO_TOPIC
    seen.clear()
    push.send_all(store, "t", "b", "tag-2", sender=service)
    assert seen == [None]                                                    # remembered: no Topic to that service
    # gone and slow-down answers are not a Topic refusal
    monkeypatch.setattr(push, "NO_TOPIC", set())
    seen.clear()
    r = push.send_all(store, "t", "b", "tag-3", sender=lambda i, p, topic=None, ttl=None: seen.append(topic) or 429)
    assert len(seen) == 1 and r["failed"] and not push.NO_TOPIC
    # a refusal that stays after the retry is no proof about the Topic: not remembered
    r = push.send_all(store, "t", "b", "tag-4", sender=lambda i, p, topic=None, ttl=None: seen.append(topic) or 403)
    assert not push.NO_TOPIC and r["sent"] == 0


def test_the_old_print_state_pushes_are_gone_and_no_printer_is_polled(env):
    assert not hasattr(push, "Watcher") and not hasattr(push, "transitions")
    kit = EventKit([alert(1)])
    feed, sent = make_feed(kit)
    feed.tick()
    kit.events.append(alert(2))
    feed.tick()
    assert all(c[1].startswith("/api/events") for c in kit.calls if c[0] == "GET") and len(sent.payloads) == 1


def test_a_hub_that_does_not_answer_is_asked_again_and_nothing_is_replayed(env):
    kit = EventKit([alert(1)])
    feed, sent = make_feed(kit)
    feed.tick()
    kit.down = True
    with pytest.raises(SlotError):
        feed.tick()
    kit.down = False
    kit.events.append(alert(2))
    feed.tick()
    assert [p["title"] for p in sent.payloads] == ["title 2"]


# ---------- the web twins ----------

def test_twins_pass_the_hub_answer_and_its_parameters(env):
    kit = EventKit([alert(1)])
    low = {"threshold_g": 150, "spools": []}
    orig = kit.get
    kit.get = lambda p: (low if p == "/api/spools/low" else {"types": []} if p == "/api/alerts"
                         else {"filesystems": [], "items": []} if p == "/api/storage-use" else orig(p))
    c = signed(make_app(env, kit))
    r = c.get("/intake/api/events?since=0&wait=55&alert=1&kinds=print&junk=1")
    assert r.status_code == 200 and r.json()["events"][0]["id"] == 1
    assert kit.queries[-1] == {"since": "0", "wait": "20", "alert": "1", "kinds": "print"}
    assert c.get("/intake/api/spools/low").json() == low
    assert c.get("/intake/api/alerts").json() == {"types": []}
    assert c.get("/intake/api/storage-use").json()["filesystems"] == []
    kit.down = True
    r = c.get("/intake/api/events")
    assert r.status_code == 502 and "not reachable" in r.json()["error"]


def test_twins_are_for_the_home_network_only(env):
    c = signed(make_app(env, EventKit()), AWAY)
    assert c.get("/intake/api/events").status_code == 403


def test_alerts_test_twin_sends_one_test_to_the_phones_only_with_push_on(env, monkeypatch):
    kit = EventKit()
    assert signed(make_app(env, kit)).post("/intake/api/alerts/test", headers=H).status_code == 404
    sent = Sent()
    monkeypatch.setattr(push, "available", lambda: True)
    monkeypatch.setattr(push, "webpush_sender", lambda subject: sent)
    c = signed(make_app(env, kit, push=True))
    assert c.post("/intake/api/printers/push/subscribe", json={"subscription": sub()}, headers=H).status_code == 200
    r = c.post("/intake/api/alerts/test", headers=H)
    assert r.status_code == 200 and r.json()["sent"] == 1 and len(sent.payloads) == 1
