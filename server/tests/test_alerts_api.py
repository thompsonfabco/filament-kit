"""EA3 (b): the routes of events and alerts (R80 section 8 and E1/E4), the words the Hub builds for each event (section 5),
and the catalogue holding exactly the texts the server builds (the drift test)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from filament_kit import alerts, alerts_api, config, event_kinds, event_sink, events, inventory, pairing
from filament_kit.alerts_api import AlertsRefused, say
from filament_kit.api import create_app
from filament_kit.event_sink import StoreSink
from filament_kit.spoolman import Spoolman

ROOT = Path(__file__).resolve().parents[2]
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
         "sealed_location": "Sealed stock"}
GB = 1000 ** 3


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "backups", "opt"):
        (tmp_path / name).mkdir(exist_ok=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    alerts.reset()
    alerts_api._tests.clear()
    alerts_api._served.clear()
    yield tmp_path
    alerts.reset()
    event_sink.set_sink(None)


@pytest.fixture
def store(env):
    s = events.EventStore()
    event_sink.set_sink(StoreSink(s))
    return s


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def hub(env, sm):
    pairing.make_cert("fkhost", [], env / "etc")
    return TestClient(create_app(sm=sm))


def phone() -> dict:
    return {"Authorization": "Bearer " + pairing.redeem_code(pairing.issue("Pixel").code)}


def web() -> dict:
    return {"Authorization": "Bearer " + pairing.redeem_code(pairing.issue("web (MCP)", role=pairing.WEB_ROLE).code)}


def write(store, kind, data=None, subject=None, **kw):
    subject = subject or {"type": "printer", "id": "p-3", "name": "Workshop X1"}
    return store.write(kind, subject, {"type": "hub"}, data or {}, **kw)


# ---------------------------------------------------------------- the texts: the catalogue holds what the server builds

def test_the_server_texts_are_the_catalogue_texts():
    """Case rule: the catalogue text is exactly what the server builds, first letter included: change one and this fails."""
    catalogue = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))
    drift = {k: (v, catalogue.get(k)) for k, v in alerts_api.MESSAGES.items() if catalogue.get(k) != v}
    assert not drift, f"server text and catalogue differ for: {drift}"
    assert len(alerts_api.MESSAGES) >= 130


DYNAMIC = ("alerts_type_", "event_title_spool_", "event_text_spool_", "event_reason_", "event_title_check_",
           "storage_use_disk_", "storage_use_item_", "status_alerts_")           # built from a kind or a key: `say(f"alerts_type_{k}")`


def test_every_server_text_is_built_somewhere_and_every_say_names_a_text():
    here = Path(alerts_api.__file__).parent
    code = "".join((here / n).read_text(encoding="utf-8")
                   for n in ("alerts_api.py", "alerts_cli.py", "status.py", "cli.py", "api.py", "watch.py"))
    block = Path(alerts_api.__file__).read_text(encoding="utf-8").split("MESSAGES = {", 1)[1].split(chr(10) + "}" + chr(10), 1)[0]
    outside = code.replace(block, "")
    unused = [k for k in alerts_api.MESSAGES if f'"{k}"' not in outside and not k.startswith(DYNAMIC)
              and not k.endswith("_no_percent")]
    assert not unused, f"texts nobody builds: {unused}"
    for m in re.finditer(r'\bsay\("([a-z_]+)"[,)]', code):
        assert m.group(1) in alerts_api.MESSAGES, m.group(1)


def test_the_titles_and_sentences_of_the_design_table():
    """R80 section 5, row by row."""
    def view(kind, data, **kw):
        ev = {"id": 1, "at": "2026-11-17T04:12:09Z", "kind": kind, "severity": kw.get("severity", "warn"),
              "subject": kw.get("subject", {"type": "printer", "id": "p-3", "name": "Workshop X1"}),
              "actor": {"type": "hub", "id": "", "name": ""}, "data": data, "condition": None}
        return alerts_api.words(ev)
    assert view("print.runout", {"job": "bracket", "percent": "41"}) == (
        "Filament ran out on Workshop X1", "bracket is paused at 41 %. Load filament and resume at the printer.")
    assert view("print.paused", {"job": "bracket", "percent": "41", "stage": "Paused by user"}) == (
        "Workshop X1 is paused", "bracket is paused at 41 %. Paused by user")
    assert view("print.failed", {"job": "bracket", "percent": "41", "reason": "cancelled"}) == (
        "Print stopped on Workshop X1", "bracket stopped at 41 %. It was cancelled.")
    assert view("print.failed", {"job": "bracket", "percent": "41", "reason": "error", "error": "Heater failed"})[1] == \
        "bracket stopped at 41 %. Heater failed"
    assert view("print.failed", {"job": "bracket", "percent": "41", "reason": "unknown"})[1] == "bracket stopped at 41 %."
    assert view("printer.error", {"code": "0500_0100", "text": "The nozzle is clogged"}) == (
        "Workshop X1 reports a problem", "The nozzle is clogged")
    assert view("print.finished", {"job": "bracket"}) == ("Print finished on Workshop X1", "bracket is done.")
    hub = {"type": "hub", "id": "", "name": ""}
    assert view("storage.low", {"free": str(14 * GB), "total": str(100 * GB), "percent": "86.0"}, subject=hub) == (
        "Storage on the Hub is almost full", "14 GB free of 100 GB (86 % used).")
    assert view("storage.low", {"free": str(3 * GB // 2), "total": str(100 * GB), "percent": "98"}, subject=hub,
                severity="bad") == ("Storage on the Hub is full",
                                    "1.5 GB free of 100 GB. Backups and new photos may fail.")
    spool = {"type": "spool", "id": "214", "name": "Prusament PLA"}
    assert view("spool.low", {"spool": "214", "filament": "Prusament PLA Galaxy Black", "grams": "96", "in_stock": "2"},
                subject=spool) == ("Running low: Prusament PLA Galaxy Black", "Spool 214 has 96 g left. 2 more in stock.")
    assert view("spool.low", {"spool": "77", "filament": "Teal", "grams": "140", "in_stock": "0"},
                subject=spool)[1] == "Spool 77 has 140 g left. It is the last one."
    dev = {"type": "device", "id": "w1", "name": "Bench Station"}
    title, text = view("device.down", {}, subject=dev)
    assert title == "Bench Station stopped answering" and re.fullmatch(r"Last answer (\d\d:\d\d|\d+ \w{3} \d\d:\d\d)\.", text)
    title, text = view("printer.offline", {})
    assert title == "Workshop X1 is offline" and text.startswith("Last seen ")


def test_a_missing_value_never_breaks_a_sentence():
    ev = {"id": 1, "at": "2026-11-17T04:12:09Z", "kind": "print.runout", "severity": "warn",
          "subject": {"type": "printer", "id": "p-3", "name": ""}, "actor": {"type": "hub", "id": "", "name": ""},
          "data": {}, "condition": None}
    assert alerts_api.words(ev) == ("Filament ran out on p-3",
                                    "The print is paused. Load filament and resume at the printer.")


def test_every_kind_the_store_writes_has_a_title(store):
    """No emitted kind falls through to its own name."""
    for name, kind in event_kinds.KINDS.items():
        if not kind.emitted:
            continue
        ev = {"id": 1, "at": "2026-11-17T04:12:09Z", "kind": name, "severity": kind.severity,
              "subject": {"type": "printer", "id": "x", "name": "N"}, "actor": {"type": "hub", "id": "", "name": ""},
              "data": {}, "condition": None}
        assert alerts_api.words(ev)[0] != name, name


# ---------------------------------------------------------------- GET api/events

def test_the_answer_has_the_contract_fields(hub, store):
    ev = write(store, "print.runout", {"job": "bracket", "percent": "41"})
    r = hub.get("/api/events", headers=phone())
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["events", "next", "oldest", "gap", "test", "conditions"]
    got = body["events"][0]
    assert list(got) == ["id", "at", "kind", "severity", "subject", "actor", "data", "condition", "alert", "title",
                         "text", "action"]
    assert got["id"] == ev["id"] and got["alert"] is True and got["title"] == "Filament ran out on Workshop X1"
    assert got["action"] == {"place": "printer", "id": "p-3"}
    assert got["condition"] == {"key": "print-paused:p-3", "state": "raised"}
    assert body["next"] == ev["id"] and body["gap"] is False and body["test"] is None
    assert [c["id"] for c in body["conditions"]] == [ev["id"]]               # the raised one, same shape
    assert list(body["conditions"][0]) == list(got)


def test_the_route_needs_the_token(hub):
    assert hub.get("/api/events").status_code == 401


def test_since_since_at_kinds_and_limit(hub, store):
    first = write(store, "print.started", {"job": "a"})
    write(store, "print.runout", {"job": "a", "percent": "5"})
    write(store, "spool.moved", {"spool": "1"}, subject={"type": "spool", "id": "1", "name": "x"})
    h = phone()
    assert [e["id"] for e in hub.get(f"/api/events?since={first['id']}", headers=h).json()["events"]] == [2, 3]
    assert [e["kind"] for e in hub.get("/api/events?kinds=print", headers=h).json()["events"]] == [
        "print.started", "print.runout"]
    assert [e["id"] for e in hub.get("/api/events?limit=1", headers=h).json()["events"]] == [1]
    assert hub.get("/api/events?since_at=2999-01-01T00:00:00Z", headers=h).json()["events"] == []
    assert len(hub.get("/api/events?since_at=2000-01-01T00:00:00Z", headers=h).json()["events"]) == 3
    assert hub.get("/api/events?since=1&since_at=2000-01-01T00:00:00Z", headers=h).status_code == 400
    assert hub.get("/api/events?since=x", headers=h).status_code == 400
    assert hub.get("/api/events?since_at=yesterday", headers=h).status_code == 400


def test_alert_1_keeps_only_what_an_alert_type_that_is_on_covers_and_the_cursor_moves_on(hub, store):
    write(store, "print.started", {"job": "a"})
    write(store, "print.finished", {"job": "a"})                 # type finished: off at the start
    write(store, "print.runout", {"job": "a", "percent": "5"})
    write(store, "spool.moved", {"spool": "1"}, subject={"type": "spool", "id": "1", "name": "x"})
    body = hub.get("/api/events?alert=1", headers=phone()).json()
    assert [e["kind"] for e in body["events"]] == ["print.runout"] and body["next"] == 4
    all_of_them = hub.get("/api/events", headers=phone()).json()["events"]
    assert [e["alert"] for e in all_of_them] == [False, False, True, False]
    # the switches decide: finished on
    alerts.save({"types": {"finished": True}})
    assert [e["kind"] for e in hub.get("/api/events?alert=1", headers=phone()).json()["events"]] == [
        "print.finished", "print.runout"]


def test_a_storage_low_that_is_going_down_is_never_an_alert(hub, store):
    write(store, "storage.low", {"free": str(GB * 14), "total": str(GB * 100), "percent": "86", "direction": "down"},
          subject={"type": "hub"}, severity="warn")
    got = hub.get("/api/events?alert=1", headers=phone()).json()
    assert got["events"] == [] and got["conditions"][0]["alert"] is False


def test_gap_and_oldest(hub, store):
    for i in range(3):
        write(store, "print.started", {"job": str(i)})
    store.prune(30, now=__import__("datetime").datetime(2999, 1, 1, tzinfo=__import__("datetime").timezone.utc))
    write(store, "print.started", {"job": "late"})
    body = hub.get("/api/events?since=1", headers=phone()).json()
    assert body["oldest"] == 4 and body["gap"] is True
    assert hub.get("/api/events?since=3", headers=phone()).json()["gap"] is False         # nothing between was lost
    assert hub.get("/api/events", headers=phone()).json()["gap"] is False                 # no cursor, no gap


def test_wait_returns_at_once_for_news_and_after_the_time_for_none(hub, store):
    write(store, "print.started", {"job": "a"})
    t = time.monotonic()
    assert len(hub.get("/api/events?since=0&wait=5", headers=phone()).json()["events"]) == 1
    assert time.monotonic() - t < 2
    t = time.monotonic()
    body = hub.get("/api/events?since=1&wait=1", headers=phone()).json()
    assert body["events"] == [] and body["next"] == 1 and 0.8 < time.monotonic() - t < 4


# ---------------------------------------------------------------- the test alert (R80 E4)

def test_a_test_alert_is_given_once_to_the_caller_that_asked_and_stores_nothing(hub, store):
    mine, other = phone(), phone()
    r = hub.post("/api/alerts/test", json={}, headers=mine)
    assert r.status_code == 200 and r.json()["test"] == {"title": "Test alert",
                                                          "text": "If you can read this, alerts reach this device."}
    assert hub.get("/api/events", headers=other).json()["test"] is None            # not to another device
    got = hub.get("/api/events", headers=mine).json()
    assert got["test"]["title"] == "Test alert" and got["events"] == []
    assert hub.get("/api/events", headers=mine).json()["test"] is None             # once
    assert store.last_id() == 0                                                      # nothing was stored


def test_the_hub_pages_test_goes_to_its_browser_id(hub):
    h = phone()
    hub.post("/api/alerts/test", json={"client": "br-1"}, headers=h)
    assert hub.get("/api/events?client=br-2", headers=h).json()["test"] is None
    assert hub.get("/api/events?client=br-1", headers=h).json()["test"]["title"] == "Test alert"


def test_a_test_alert_is_kept_60_seconds(hub, monkeypatch):
    h = phone()
    hub.post("/api/alerts/test", json={}, headers=h)
    real = time.monotonic
    monkeypatch.setattr(alerts_api.time, "monotonic", lambda: real() + 61)
    assert hub.get("/api/events", headers=h).json()["test"] is None


def test_the_command_lines_test_goes_to_every_client_that_asks_within_60_seconds(hub, env):
    alerts_api.send_test_to_all()
    assert (env / "state" / "alert-test").is_file()
    a, b = phone(), phone()
    assert hub.get("/api/events", headers=a).json()["test"]["title"] == "Test alert"
    assert hub.get("/api/events", headers=a).json()["test"] is None
    assert hub.get("/api/events", headers=b).json()["test"]["title"] == "Test alert"
    import os
    old = time.time() - 120
    os.utime(env / "state" / "alert-test", (old, old))
    assert hub.get("/api/events", headers=phone()).json()["test"] is None


# ---------------------------------------------------------------- GET api/alerts and its write

def test_alerts_view_is_the_contract(hub):
    body = hub.get("/api/alerts", headers=phone()).json()
    assert list(body) == ["types", "last_spool_only", "running_low_g", "storage_warn_percent", "storage_bad_percent"]
    assert [t["key"] for t in body["types"]] == ["runout", "paused", "failed", "printer_error", "finished", "storage",
                                                 "running_low", "device_down"]
    assert {t["key"]: t["on"] for t in body["types"]} == {
        "runout": True, "paused": True, "failed": True, "printer_error": True, "finished": False, "storage": True,
        "running_low": True, "device_down": False}
    assert body["types"][0]["title"] == "Filament ran out" and body["types"][0]["events"] == ["print.runout"]
    assert body["types"][7]["description"] == "A Weigh Station or a printer stopped answering."
    assert body["types"][0]["description"] == ""
    assert (body["last_spool_only"], body["running_low_g"], body["storage_warn_percent"],
            body["storage_bad_percent"]) == (False, 150, 85, 95)
    assert hub.get("/api/alerts").status_code == 401


def test_no_route_lets_a_phone_change_the_alerts(hub):
    """The types and limits are edited on the Hub page or the command line, not by a paired phone (R80 section 8)."""
    assert hub.post("/api/alerts", json={"running_low_g": 50}, headers=phone()).status_code == 405
    assert hub.put("/api/alerts", json={}, headers=phone()).status_code == 405


def test_save_changes_the_file_and_returns_the_view(env):
    out = alerts_api.save({"types": {"finished": True, "runout": False}, "running_low_g": 200,
                           "storage_warn_percent": 80, "last_spool_only": True})
    assert {t["key"]: t["on"] for t in out["types"]}["finished"] is True and out["running_low_g"] == 200
    assert (env / "state" / "alerts.xml").is_file() and alerts.load()["types"]["runout"] is False
    again = alerts_api.save({"types": [{"key": "runout", "on": True}]})              # the list GET gives, sent back
    assert again["types"][0]["on"] is True and again["running_low_g"] == 200


@pytest.mark.parametrize("body, field, message", [
    ({"running_low_g": 5}, "running_low_g", "Enter a whole number, 10 to 2000."),
    ({"running_low_g": "x"}, "running_low_g", "Enter a whole number, 10 to 2000."),
    ({"running_low_g": True}, "running_low_g", "Enter a whole number, 10 to 2000."),
    ({"storage_warn_percent": 100}, "storage_warn_percent", "Enter a whole number, 1 to 99."),
    ({"storage_warn_percent": 95}, "storage_warn_percent",
     "The storage warning must be lower than 95 % used, where storage counts as full."),
    ({"types": {"nope": True}}, "types", "nope is not an alert type. The types are: runout, paused, failed, "
                                          "printer_error, finished, storage, running_low, device_down."),
    ({"types": {"runout": "yes"}}, "types", "runout must be on or off."),
    ({"last_spool_only": 1}, "last_spool_only", "last_spool_only must be on or off."),
    ({"surprise": 1}, "surprise", "surprise is not an alert setting."),
    ([], None, "Send the alert settings as named values."),
])
def test_a_refused_change_says_which_and_changes_nothing(env, body, field, message):
    with pytest.raises(AlertsRefused) as e:
        alerts_api.save(body)
    assert str(e.value) == message and e.value.field == field
    assert alerts.load() == alerts.defaults() and not (env / "state" / "alerts.xml").exists()


def test_whole_takes_the_text_of_a_number():
    assert alerts_api.whole("200", 10, 2000) == 200
    for bad in ("2.5", "-1", "", None, 9, 2001):
        with pytest.raises(AlertsRefused):
            alerts_api.whole(bad, 10, 2000)


# ---------------------------------------------------------------- GET api/spools/low and api/storage-use

def test_spools_low_is_the_running_low_list(hub, sm):
    one = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000, "tare": 213,
           "density": 1.27, "count": 1, "sealed": False}
    inventory.add_spools(sm, [{**one, "gross": 303}, {**one, "gross": 333}], RULES, dry=False)       # 90 g and 120 g
    body = hub.get("/api/spools/low", headers=phone()).json()
    assert list(body) == ["threshold_g", "spools"] and body["threshold_g"] == 150
    assert list(body["spools"][0]) == ["id", "filament", "material", "color", "remaining_g", "location", "in_stock",
                                       "last_one"]
    assert [r["remaining_g"] for r in body["spools"]] == [90, 120]
    assert body["spools"][0]["in_stock"] == 1 and body["spools"][0]["last_one"] is False
    assert hub.get("/api/spools/low").status_code == 401
    assert hub.get("/api/spools/1", headers=phone()).status_code == 200          # the spool route is still its own


def test_storage_use_is_the_contract(hub):
    body = hub.get("/api/storage-use", headers=phone()).json()
    assert list(body) == ["filesystems", "items"] and body["filesystems"]
    assert {"path_label", "total", "free", "percent_used", "state", "title"} <= set(body["filesystems"][0])
    assert body["filesystems"][0]["title"] == "The Hub's disk"
    assert [i["key"] for i in body["items"]] == ["backups", "photos", "reader", "events", "logs"]
    assert body["items"][0] == {"key": "backups", "title": "Backups", "bytes": 0}
    assert hub.get("/api/storage-use").status_code == 401
    assert hub.get("/api/storage", headers=phone()).json().get("locations") is not None     # api/storage is the other


# ---------------------------------------------------------------- the web unit (R80 E1)

def test_the_web_unit_may_read_and_hand_over_and_a_phone_may_not_hand_over(hub, store):
    for path in ("/api/events", "/api/alerts", "/api/spools/low", "/api/storage-use"):
        assert hub.get(path, headers=web()).status_code == 200, path
    one = {"kind": "spool.moved", "at": "2026-11-16T10:00:00Z", "subject": {"type": "spool", "id": "7", "name": "x"},
           "data": {"spool": "7", "before_location": "A", "after_location": "B"}}
    assert hub.post("/api/events/web", json={"events": [one]}, headers=phone()).status_code == 403
    r = hub.post("/api/events/web", json={"events": [one, {**one, "data": {"spool": "7"}}]}, headers=web())
    assert r.status_code == 200 and r.json()["ids"] == [1, 2]
    ev = store.read()["events"][0]
    assert ev["at"] == "2026-11-16T10:00:00Z" and ev["actor"]["type"] == "connector" and ev["kind"] == "spool.moved"


def test_the_web_unit_hands_over_spool_kinds_only_and_names_its_actor(hub, store):
    bad = {"kind": "print.runout", "subject": {"type": "printer", "id": "p"}, "data": {}}
    r = hub.post("/api/events/web", json={"events": [bad]}, headers=web())
    assert r.status_code == 400 and store.last_id() == 0
    ok = {"kind": "spool.opened", "subject": {"type": "spool", "id": "7"}, "data": {"spool": "7"},
          "actor": {"type": "device", "id": "d1", "name": "Pixel"}}
    assert hub.post("/api/events/web", json={"events": [ok]}, headers=web()).status_code == 200
    assert store.read()["events"][0]["actor"] == {"type": "device", "id": "d1", "name": "Pixel"}
    assert hub.post("/api/events/web", json={"events": "x"}, headers=web()).status_code == 400
    assert hub.post("/api/events/web", json={"events": [{**ok, "data": {"nope": 1}}]}, headers=web()).status_code == 400


# ---------------------------------------------------------------- who did it: the request's device is the actor

def test_a_spool_change_through_the_api_is_done_by_the_device_of_the_token(hub, sm, store):
    sid = inventory.add_spools(sm, [{"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E",
                                     "net": 1000, "tare": 213, "density": 1.27, "count": 1, "sealed": False}],
                               RULES, dry=False).spool_ids[0]
    h = phone()
    r = hub.patch(f"/api/spools/{sid}", json={"location": "Shelf B", "dry_run": False}, headers=h)
    assert r.status_code == 200, r.text
    moved = [e for e in store.read()["events"] if e["kind"] == "spool.moved"]
    assert len(moved) == 1 and moved[0]["actor"]["type"] == "device" and moved[0]["actor"]["name"] == "Pixel"
    assert moved[0]["actor"]["id"] and moved[0]["data"]["batch"]


def test_the_command_line_and_the_hub_itself_stay_the_hub_without_a_request(store):
    event_sink.emit("spool.moved", {"type": "spool", "id": "1"}, {"spool": "1"})
    assert store.read()["events"][0]["actor"]["type"] == "hub"
