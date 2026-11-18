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

    def __call__(self, info, payload):
        self.payloads.append(json.loads(payload))
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
    assert sent.payloads[0]["body"] == "text 3" and sent.payloads[0]["tag"] == "event-3"
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
    assert [p["tag"] for p in sent.payloads] == ["printer.p1.paused", "storage.low", "storage.low"]
    gone = {"key": "printer.p1.paused", "state": "cleared"}
    kit.events.append(alert(5, "print.resumed", alert=False, condition=gone))
    feed.tick()
    last = sent.payloads[-1]
    assert last["clear"] is True and last["tag"] == "printer.p1.paused" and not last["title"]
    kit.events.append(alert(6, "print.resumed", alert=False, condition=gone))
    feed.tick()
    assert sent.payloads[-1] is last                                          # a clear nobody was told of: nothing
    kit.events.append(cond(7, "printer.p1.paused"))
    feed.tick()
    assert sent.payloads[-1]["title"] == "title 7"                            # raised again after clearing: told again


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
