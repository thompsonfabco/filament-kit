"""What the Hub says about events and alerts (ruling R80 sections 5 to 8): one place behind `GET api/events`,
`GET api/alerts`, `POST api/alerts/test`, `GET api/spools/low`, `GET api/storage-use`, the Hub page's `P settings/alerts`
and the command line (`spoolwarden events`, `alerts`, `spools low`), so a client and the command line get the same
data and the same words.

Texts are not stored with an event (R80 section 1); each is built here, in the Hub's language, from the kind and the
values. `MESSAGES` holds every text the server builds, under its key in strings/en.json; the catalogue holds exactly
the same text (test_alerts_api.py keeps them equal), so a client that builds its own sentence finds the same words by
the key. A plural text is {"one": ..., "other": ...} and takes its form from `count`.

    event_view(ev, settings)       one event as the API gives it: the stored fields plus alert, title, text, action
    events(...)                    the answer of `GET api/events` (cursor, wait, alert filter, gap, test)
    newest(n, kinds)               the last n events, oldest first (the command line's default)
    alerts_view / save             `GET api/alerts` and the write behind it (the Hub page, the command line)
    low_view(sm), storage_view()   `GET api/spools/low`, `GET api/storage-use`
    queue_test / send_test_to_all  `POST api/alerts/test` (no storage: the Hub keeps one test for the caller)
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone

from . import alerts, config, events

log = logging.getLogger("filament_kit.alerts_api")

TEST_SECONDS = 60                 # a test alert waits this long for the caller's next events request (R80 E4)
TEST_FILE = "alert-test"          # the command line's test: the time it was asked, in the state folder
WAIT_MAX = events.WAIT_MAX

# ---------------------------------------------------------------- the texts the server builds
MESSAGES = {
    # alert banners: titles, sentences, actions (R80 section 5; the keys the shared alert banner already uses)
    "alert_title_runout": "Filament ran out on {printer}",
    "alert_text_runout": "{job} is paused at {percent} %. Load filament and resume at the printer.",
    "alert_text_runout_no_percent": "{job} is paused. Load filament and resume at the printer.",
    "alert_title_paused": "{printer} is paused",
    "alert_text_paused": "{job} is paused at {percent} %.",
    "alert_text_paused_no_percent": "{job} is paused.",
    "alert_title_failed": "Print stopped on {printer}",
    "alert_text_failed": "{job} stopped at {percent} %.",
    "alert_text_failed_no_percent": "{job} stopped.",
    "alert_cancelled": "It was cancelled.",
    "alert_title_error": "{printer} reports a problem",
    "alert_text_error_code": "Error code {code}.",
    "alert_title_finished": "Print finished on {printer}",
    "alert_text_finished": "{job} is done.",
    "alert_title_storage_warn": "Storage on the Hub is almost full",
    "alert_text_storage_warn": "{free} free of {total} ({percent} % used).",
    "alert_title_storage_bad": "Storage on the Hub is full",
    "alert_text_storage_bad": "{free} free of {total}. Backups and new photos may fail.",
    "alert_title_low": "Running low: {filament}",
    "alert_text_low": "Spool {id} has {grams} g left.",
    "alert_text_low_more": {"one": "{count} more in stock.", "other": "{count} more in stock."},
    "alert_text_low_last": "It is the last one.",
    "alert_title_device_down": "{device} stopped answering",
    "alert_text_device_down": "Last answer {time}.",
    "alert_title_offline": "{printer} is offline",
    "alert_text_offline": "Last seen {time}.",
    "alert_open_printer": "Open the printer",
    "alert_show_storage": "Show storage use",
    "alert_show_low": "Show running low",
    "alert_open_devices": "Open Devices",
    "alert_printer_unknown": "the printer",
    "alert_job_unknown": "The print",
    "alert_device_unknown": "A device",
    "alert_test_title": "Test alert",
    "alert_test_text": "If you can read this, alerts reach this device.",
    # the other events (the history and the command line show every kind)
    "event_title_print_started": "Print started on {printer}",
    "event_text_print_started": "{job} started.",
    "event_title_print_resumed": "Print resumed on {printer}",
    "event_text_print_resumed": "{job} is running again.",
    "event_title_printer_online": "{printer} is online",
    "event_text_printer_online": "It answers again.",
    "event_title_usage_recorded": "Filament use recorded on {printer}",
    "event_text_usage_recorded": "{job}: {grams} g from spool {spool}.",
    "event_title_spool_ok": "No longer running low: {filament}",
    "event_text_spool_ok": "Spool {spool} is above the limit again, or it was emptied or removed.",
    "event_title_spool_added": "Spool {spool} added",
    "event_text_spool_added": "{name} was added.",
    "event_title_spool_opened": "Spool {spool} opened",
    "event_text_spool_opened": "{name} was opened.",
    "event_title_spool_weighed": "Spool {spool} weighed",
    "event_text_spool_weighed": "{before} g before, {after} g now.",
    "event_title_spool_moved": "Spool {spool} moved",
    "event_text_spool_moved": "From {before} to {after}.",
    "event_title_spool_emptied": "Spool {spool} marked empty",
    "event_text_spool_emptied": "{name} is empty.",
    "event_title_spool_loaded": "Spool {spool} loaded",
    "event_text_spool_loaded": "Loaded into {slot}.",
    "event_title_spool_unloaded": "Spool {spool} unloaded",
    "event_text_spool_unloaded": "Taken out of {slot}.",
    "event_text_spool_changed": "{name}.",
    "event_title_storage_ok": "Storage on the Hub is fine again",
    "event_text_storage_ok": "{free} free of {total}.",
    "event_title_device_up": "{device} is answering again",
    "event_text_device_up": "It answers again.",
    "event_title_check_failed": "A check needs a look",
    "event_title_check_ok": "A check is fine again",
    "event_title_condition_cleared": "An alert ended",
    "event_text_condition_cleared": "{key}: {reason}.",
    "event_reason_reconciled": "it is no longer true",
    "event_reason_subject_removed": "what it was about was removed",
    "event_reason_feature_off": "the check is gone",
    "event_title_location_renamed": "Storage location renamed",
    "event_text_location_renamed": "{from} is now {to}. {spools} spools were updated.",
    # the alert types (GET api/alerts)
    "alerts_type_runout": "Filament ran out",
    "alerts_type_paused": "Print paused",
    "alerts_type_failed": "Print failed or stopped",
    "alerts_type_printer_error": "Printer error",
    "alerts_type_finished": "Print finished",
    "alerts_type_storage": "Storage almost full",
    "alerts_type_running_low": "Spool running low",
    "alerts_type_device_down": "Device stopped answering",
    "alerts_type_device_down_hint": "A Weigh Station or a printer stopped answering.",
    # refusals of a change to the alert settings (the Hub page, the command line)
    "alerts_error_body": "Send the alert settings as named values.",
    "alerts_error_unknown": "{field} is not an alert setting.",
    "alerts_error_type": "{type} is not an alert type. The types are: {types}.",
    "alerts_error_flag": "{field} must be on or off.",
    "alerts_error_whole": "Enter a whole number, {low} to {high}.",
    "alerts_error_warn_below_bad": "The storage warning must be lower than {bad} % used, where storage counts as full.",
    # storage use (GET api/storage-use)
    "storage_use_disk_state": "The Hub's disk",
    "storage_use_disk_backups": "The backups disk",
    "storage_use_item_backups": "Backups",
    "storage_use_item_photos": "Photos of recently added spools",
    "storage_use_item_reader": "Label Reader on this Hub",
    "storage_use_item_events": "Events",
    "storage_use_item_logs": "Logs",
    "storage_use_row": "Storage: {free} free of {total} ({percent} % used)",
    "storage_use_fix": "Show storage use (Hub page, Overview)",
    # the Checks rows of this phase (status, the Overview)
    "status_running_low": {"one": "Running low: {count} spool", "other": "Running low: {count} spools"},
    "status_running_low_fix": "{command} spools low",
    "status_alerts_unsaved": "Alerts settings could not be saved ({reason}).",
    "status_alerts_unsaved_fix": "Check that the Hub's state folder can be written, then change an alert setting again.",
    "status_alerts_unreadable": "Alerts settings could not be read ({reason}).",
    "status_alerts_unreadable_fix": "Fix or remove alerts.xml in the Hub's state folder; the defaults apply meanwhile.",
    # the command line
    "cli_alerts_heading": "Alerts · {count} of 8 on",
    "cli_alerts_columns": "Key|Alert|Events|State",
    "cli_alerts_state_on": "on",
    "cli_alerts_state_off": "off",
    "cli_alerts_last_spool": "Spool running low only when it is the last spool of that filament: {state}",
    "cli_alerts_limits": "Running low under {grams} g · Storage warning at {warn} % used (bad at {bad} %, or under 1 GB free)",
    "cli_alerts_change": "Change them: sudo {command} alerts set -h",
    "cli_alerts_summary": "{count} of 8 on · running low under {grams} g · storage warning at {warn} % used",
    "cli_alerts_set_on": "{alert} alerts are on.",
    "cli_alerts_set_off": "{alert} alerts are off.",
    "cli_alerts_set_low": "Running low under {grams} g.",
    "cli_alerts_set_warn": "Storage warning at {percent} % used.",
    "cli_alerts_unknown_type": "{type} is not an alert type.",
    "cli_alerts_unknown_type_fix": "the types are: {types}.",
    "cli_alerts_need_value": "Say on or off, or a number: {usage}",
    "cli_alerts_test_sent": "Test alert sent. Every device that asks in the next {seconds} seconds gets it.",
    "cli_events_columns": "Id|Time|Kind|Subject|What",
    "cli_events_count": {"one": "{count} event.", "other": "{count} events."},
    "cli_events_raised": "Raised now: {keys}",
    "cli_events_none": "No events.",
    "cli_events_gap": "Note: some events were deleted by age.",
    "cli_events_following": "Following events after {id}. Ctrl-C ends.",
    "cli_events_bad_since": "{value} is not an event number or a time.",
    "cli_events_bad_since_fix": "give a number such as 1412, or a time such as 2026-11-17 04:00.",
    "cli_events_unreadable": "The events could not be read ({reason}).",
    "cli_events_unreadable_fix": "run it with sudo: sudo {command} events",
    "cli_low_heading": {"one": "{count} spool running low (at or under {grams} g)",
                        "other": "{count} spools running low (at or under {grams} g)"},
    "cli_low_columns": "Spool|Filament|Left|Location|Stock",
    "cli_low_left": "{grams} g",
    "cli_low_in_stock": {"one": "{count} more in stock", "other": "{count} more in stock"},
    "cli_low_last": "Last one",
    "cli_low_none": "No spools are running low (at or under {grams} g).",
    "cli_low_change": "Change the limit: sudo {command} alerts set running-low <grams>",
}


PRODUCT, COMMAND = "Spoolwarden", "spoolwarden"     # the catalogue holds {product} and {command} (app_name, command_name)


def say(key: str, /, **fill) -> str:
    """The text of `key` with its {names} filled in; a plural text takes its form from `count`. {product} and
    {command} are the product's and the command's name, as in the generated catalogues."""
    text = MESSAGES[key]
    if isinstance(text, dict):
        text = text["one" if fill.get("count") == 1 else "other"]
    return text.format(product=PRODUCT, command=COMMAND, **fill)


# ---------------------------------------------------------------- refusals

class AlertsRefused(ValueError):
    """A change to the alert settings that is not allowed; `field` names the setting when it is about one."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


# ---------------------------------------------------------------- words for values

def size_text(n) -> str:
    """Bytes as people read a disk: `41 GB`, `0.8 GB`, `512 MB` (units of 1000, as the disk's own maker counts)."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit, step in (("TB", 1000 ** 4), ("GB", 1000 ** 3), ("MB", 1000 ** 2), ("kB", 1000)):
        if n >= step:
            v = n / step
            return f"{v:.0f} {unit}" if v >= 10 or unit in ("MB", "kB") else f"{v:.1f} {unit}"
    return f"{n:.0f} B"


def number(v) -> str:
    """A stored value as a short number: `41`, `85.2`; text that is not a number as it is."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


def when(at: str) -> str:
    """An event's time in the Hub's own clock: `14:02` today, `17 Nov 14:02` another day."""
    try:
        t = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
    except (TypeError, ValueError):
        return str(at)
    today = datetime.now(t.tzinfo).date()
    return t.strftime("%H:%M") if t.date() == today else f"{t.day} {t.strftime('%b %H:%M')}"


# ---------------------------------------------------------------- one event

def _d(ev: dict, name: str) -> str:
    return str((ev.get("data") or {}).get(name) or "")


def _printer(ev: dict) -> str:
    s = ev.get("subject") or {}
    return s.get("name") or s.get("id") or say("alert_printer_unknown")


def _job(ev: dict) -> str:
    return _d(ev, "job") or say("alert_job_unknown")


def _with_percent(ev: dict, key: str, **fill) -> str:
    """`<job> is paused at 41 %.` or, when the percent is not known, the sentence without it."""
    if _d(ev, "percent"):
        return say(key, job=_job(ev), percent=number(_d(ev, "percent")), **fill)
    return say(key + "_no_percent", job=_job(ev), **fill)


def _more(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def _spool_name(ev: dict) -> str:
    s = ev.get("subject") or {}
    return s.get("name") or f"Spool {s.get('id', '')}".strip()


def words(ev: dict) -> tuple[str, str]:
    """(title, sentence) of an event in the Hub's language (R80 section 5's table for the alert kinds)."""
    kind, sev = ev.get("kind", ""), ev.get("severity", "")
    sub = ev.get("subject") or {}
    if kind == "print.runout":
        return say("alert_title_runout", printer=_printer(ev)), _with_percent(ev, "alert_text_runout")
    if kind == "print.paused":
        return say("alert_title_paused", printer=_printer(ev)), _more(_with_percent(ev, "alert_text_paused"),
                                                                      _d(ev, "stage"))
    if kind == "print.failed":
        why = _d(ev, "error") or (say("alert_cancelled") if _d(ev, "reason") == "cancelled" else "")
        return say("alert_title_failed", printer=_printer(ev)), _more(_with_percent(ev, "alert_text_failed"), why)
    if kind == "printer.error":
        text = _d(ev, "text") or (say("alert_text_error_code", code=_d(ev, "code")) if _d(ev, "code") else "")
        return say("alert_title_error", printer=_printer(ev)), text
    if kind == "print.finished":
        return say("alert_title_finished", printer=_printer(ev)), say("alert_text_finished", job=_job(ev))
    if kind == "storage.low":
        free, total = size_text(_d(ev, "free")), size_text(_d(ev, "total"))
        if sev == "bad":
            return say("alert_title_storage_bad"), say("alert_text_storage_bad", free=free, total=total)
        return say("alert_title_storage_warn"), say("alert_text_storage_warn", free=free, total=total,
                                                    percent=number(_d(ev, "percent")))
    if kind == "spool.low":
        stock = _d(ev, "in_stock")
        tail = "" if stock == "" else (say("alert_text_low_more", count=int(float(stock)))
                                       if float(stock) > 0 else say("alert_text_low_last"))
        return (say("alert_title_low", filament=_d(ev, "filament") or sub.get("name", "")),
                _more(say("alert_text_low", id=_d(ev, "spool") or sub.get("id", ""), grams=number(_d(ev, "grams"))),
                      tail))
    if kind == "device.down":
        return (say("alert_title_device_down", device=sub.get("name") or sub.get("id") or say("alert_device_unknown")),
                say("alert_text_device_down", time=when(ev.get("at", ""))))
    if kind == "printer.offline":
        return say("alert_title_offline", printer=_printer(ev)), say("alert_text_offline", time=when(ev.get("at", "")))
    if kind == "print.started":
        return say("event_title_print_started", printer=_printer(ev)), say("event_text_print_started", job=_job(ev))
    if kind == "print.resumed":
        return say("event_title_print_resumed", printer=_printer(ev)), say("event_text_print_resumed", job=_job(ev))
    if kind == "printer.online":
        return say("event_title_printer_online", printer=_printer(ev)), say("event_text_printer_online")
    if kind == "usage.recorded":
        return (say("event_title_usage_recorded", printer=_d(ev, "printer") or say("alert_printer_unknown")),
                say("event_text_usage_recorded", job=_job(ev), grams=number(_d(ev, "grams")), spool=_d(ev, "spool")))
    if kind == "spool.ok":
        return say("event_title_spool_ok", filament=sub.get("name", "")), say("event_text_spool_ok",
                                                                             spool=_d(ev, "spool") or sub.get("id", ""))
    if kind.startswith("spool.") and kind[6:] in ("added", "opened", "weighed", "moved", "emptied", "loaded",
                                                  "unloaded"):
        what, sid, name = kind[6:], _d(ev, "spool") or sub.get("id", ""), _spool_name(ev)
        title = say(f"event_title_spool_{what}", spool=sid)
        if what == "weighed" and _d(ev, "before_grams") and _d(ev, "after_grams"):
            return title, say("event_text_spool_weighed", before=number(_d(ev, "before_grams")),
                              after=number(_d(ev, "after_grams")))
        if what == "moved" and _d(ev, "before_location") and _d(ev, "after_location"):
            return title, say("event_text_spool_moved", before=_d(ev, "before_location"),
                              after=_d(ev, "after_location"))
        if what == "loaded" and _d(ev, "after_slot"):
            return title, say("event_text_spool_loaded", slot=_d(ev, "after_slot"))
        if what == "unloaded" and _d(ev, "before_slot"):
            return title, say("event_text_spool_unloaded", slot=_d(ev, "before_slot"))
        if what in ("added", "opened", "emptied"):
            return title, say(f"event_text_spool_{what}", name=name)
        return title, say("event_text_spool_changed", name=name)
    if kind == "storage.ok":
        return say("event_title_storage_ok"), say("event_text_storage_ok", free=size_text(_d(ev, "free")),
                                                  total=size_text(_d(ev, "total")))
    if kind == "device.up":
        return (say("event_title_device_up", device=sub.get("name") or sub.get("id") or say("alert_device_unknown")),
                say("event_text_device_up"))
    if kind in ("check.failed", "check.ok"):
        return say(f"event_title_{kind.replace('.', '_')}"), _d(ev, "text")
    if kind == "condition.cleared":
        reason = _d(ev, "reason")
        why = say(f"event_reason_{reason}") if f"event_reason_{reason}" in MESSAGES else reason
        return say("event_title_condition_cleared"), say("event_text_condition_cleared", key=_d(ev, "key"), reason=why)
    if kind == "location.renamed":
        return say("event_title_location_renamed"), say("event_text_location_renamed", **{
            "from": _d(ev, "from"), "to": _d(ev, "to"), "spools": _d(ev, "spools") or "0"})
    return kind, ""


# where an alert's action goes: the place names the interfaces know (R80 section 5; the Hub page's addresses)
_ACTION = {"print.runout": "printer", "print.paused": "printer", "print.failed": "printer", "printer.error": "printer",
           "print.finished": "printer", "printer.offline": "printer", "storage.low": "storage-use",
           "spool.low": "running-low", "device.down": "devices"}
ACTION_LABELS = {"printer": "alert_open_printer", "storage-use": "alert_show_storage",
                 "running-low": "alert_show_low", "devices": "alert_open_devices"}


def action_of(ev: dict) -> dict | None:
    """{place, id} of the place that fixes the event, None for a kind with none."""
    place = _ACTION.get(ev.get("kind", ""))
    if place is None:
        return None
    sub = ev.get("subject") or {}
    return {"place": place, "id": "" if place == "storage-use" else (sub.get("id") or "")}


def event_view(ev: dict, settings: dict | None = None) -> dict:
    """An event as the API gives it (R80 section 8): what is stored, whether an alert type that is on covers it, and
    its title, sentence and action in the Hub's language."""
    title, text = words(ev)
    return {"id": ev["id"], "at": ev["at"], "kind": ev["kind"], "severity": ev["severity"],
            "subject": dict(ev["subject"]), "actor": dict(ev["actor"]), "data": dict(ev["data"]),
            "condition": dict(ev["condition"]) if ev.get("condition") else None,
            "alert": alerts.is_alert(ev, settings), "title": title, "text": text, "action": action_of(ev)}


# ---------------------------------------------------------------- GET api/events

def parse_time(text: str) -> str:
    """An ISO time (UTC `Z`, or with an offset) as the store writes times: `2026-11-17T04:00:00Z`."""
    t = str(text).strip()
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{text!r} is not a time (2026-11-17T04:00:00Z)") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def events_answer(*, since: int | None = None, since_at: str | None = None, wait: float = 0, kinds=None,
                  limit: int = events.LIMIT_DEFAULT, alert: bool = False, callers=()) -> dict:
    """`GET api/events`: {events, next, oldest, gap, test, conditions}. `since` (an id) or `since_at` (a time, UTC);
    `wait` up to 55 s waits for news; `alert` keeps only the events an alert type that is on covers (the cursor still
    moves over the others); `callers` are the keys this caller is known by (`device:<id>`, `client:<browser id>`),
    for the test alert it may be waiting for. Blocking: call it in a thread."""
    if since is not None and since_at:
        raise ValueError("give since or since_at, not both")
    store, settings = events.store(), alerts.load()
    deadline = time.monotonic() + min(max(float(wait or 0), 0.0), WAIT_MAX)
    cur, shown, res = max(int(since or 0), 0), [], {"events": [], "next": 0}
    while True:
        res = store.read(cur, limit, kinds, max(0.0, deadline - time.monotonic()), since_at=since_at)
        found = res["events"]
        shown = [e for e in found if alerts.is_alert(e, settings)] if alert else found
        cur = res["next"]
        if shown or not found:
            break
    oldest = res.get("oldest", store.oldest())
    gap = since is not None and oldest > 0 and since < oldest - 1
    return {"events": [event_view(e, settings) for e in shown], "next": cur, "oldest": oldest, "gap": bool(gap),
            "test": take_test(callers), "conditions": [event_view(c, settings) for c in store.conditions()]}


def newest(n: int = 50, kinds=None) -> list[dict]:
    """The last `n` events (oldest first) with their views; reads from just under the newest id."""
    store, settings = events.store(), alerts.load()
    last, span = store.last_id(), max(int(n), 1)
    got: list[dict] = []
    for _ in range(6):                                  # ids are rising by one, but a failed write can skip one
        got = store.read(max(last - span, 0), 1000, kinds)["events"]
        if len(got) >= n or last - span <= 0:
            break
        span *= 2
    return [event_view(e, settings) for e in got[-n:]]


# ---------------------------------------------------------------- the test alert (R80 E4)

_tests: dict[str, tuple[float, dict]] = {}
_served: dict[str, int] = {}
_tlock = threading.Lock()


def test_body() -> dict:
    return {"title": say("alert_test_title"), "text": say("alert_test_text")}


def queue_test(caller: str) -> dict:
    """Keep one test alert for `caller` (`device:<id>` or `client:<browser id>`) for 60 seconds; the next
    `GET api/events` of that caller gives it once. Nothing is stored."""
    caller = str(caller or "").strip()
    if not caller:
        raise ValueError("a test alert needs a device or a client id")
    with _tlock:
        _tests[caller] = (time.monotonic() + TEST_SECONDS, test_body())
    return test_body()


def _all_marker():
    return config.paths().state / TEST_FILE


def send_test_to_all() -> None:
    """The command line's test (as root): every client that asks within 60 seconds gets one (the Hub reads the file)."""
    f = _all_marker()
    f.parent.mkdir(parents=True, exist_ok=True)
    events.EventStore()._atomic(f, (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n").encode("ascii"))


def take_test(callers=()) -> dict | None:
    """The test waiting for one of `callers`, once; None when there is none."""
    callers = [c for c in callers if c]
    if not callers:
        return None
    now = time.monotonic()
    with _tlock:
        for c in list(_tests):
            if _tests[c][0] <= now:
                del _tests[c]
        for c in callers:
            if c in _tests:
                return _tests.pop(c)[1]
        try:
            st = _all_marker().stat()
        except OSError:
            return None
        if time.time() - st.st_mtime > TEST_SECONDS:
            return None
        for c in callers:
            if _served.get(c) != st.st_mtime_ns:
                _served[c] = st.st_mtime_ns
                if len(_served) > 500:
                    _served.pop(next(iter(_served)))
                return test_body()
    return None


# ---------------------------------------------------------------- GET api/alerts and its write

def alerts_view(settings: dict | None = None) -> dict:
    """`GET api/alerts`: {types: [{key, title, on, events, description}], last_spool_only, running_low_g,
    storage_warn_percent, storage_bad_percent}."""
    s = settings or alerts.load()
    return {"types": [{"key": k, "title": say(f"alerts_type_{k}"), "on": bool(s["types"][k]), "events": list(kinds),
                       "description": say("alerts_type_device_down_hint") if k == "device_down" else ""}
                      for k, kinds, _on in alerts.TYPES],
            "last_spool_only": s["last_spool_only"], "running_low_g": s["running_low_g"],
            "storage_warn_percent": s["storage_warn_percent"], "storage_bad_percent": s["storage_bad_percent"]}


_NUMBERS = {"running_low_g": (alerts.LOW_G_MIN, alerts.LOW_G_MAX), "storage_warn_percent": (1, 99),
            "storage_bad_percent": (2, 100)}


def whole(value, low: int, high: int, field: str | None = None) -> int:
    """`value` (a number or the text of one) as a whole number from `low` to `high`, or AlertsRefused."""
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not low <= value <= high:
        raise AlertsRefused(say("alerts_error_whole", low=low, high=high), field)
    return int(value)


def changes_of(body) -> dict:
    """The checked changes of a body {types, last_spool_only, running_low_g, storage_warn_percent,
    storage_bad_percent}; `types` may be {key: true or false} or the list GET api/alerts gives ([{key, on}]).
    Raises AlertsRefused naming the setting."""
    if not isinstance(body, dict):
        raise AlertsRefused(say("alerts_error_body"))
    out: dict = {}
    for field, value in body.items():
        if field == "types":
            pairs = ({t.get("key"): t.get("on") for t in value if isinstance(t, dict)} if isinstance(value, list)
                     else value if isinstance(value, dict) else None)
            if pairs is None:
                raise AlertsRefused(say("alerts_error_body"), "types")
            for key, on in pairs.items():
                if key not in alerts.KEYS:
                    raise AlertsRefused(say("alerts_error_type", type=key, types=", ".join(alerts.KEYS)), "types")
                if not isinstance(on, bool):
                    raise AlertsRefused(say("alerts_error_flag", field=key), "types")
            out["types"] = dict(pairs)
        elif field == "last_spool_only":
            if not isinstance(value, bool):
                raise AlertsRefused(say("alerts_error_flag", field=field), field)
            out[field] = value
        elif field in _NUMBERS:
            out[field] = whole(value, *_NUMBERS[field], field)
        else:
            raise AlertsRefused(say("alerts_error_unknown", field=field), field)
    return out


def save(body) -> dict:
    """The write behind `GET api/alerts` (the Hub page's `P settings/alerts` calls it in the Hub process; the command
    line as root writes the same file with the same code): checks the body, writes alerts.xml, returns the view."""
    changes = changes_of(body)
    now = alerts.load()
    warn = changes.get("storage_warn_percent", now["storage_warn_percent"])
    bad = changes.get("storage_bad_percent", now["storage_bad_percent"])
    if warn >= bad:
        raise AlertsRefused(say("alerts_error_warn_below_bad", bad=bad), "storage_warn_percent")
    try:
        return alerts_view(alerts.save(changes))
    except alerts.AlertsError as e:
        raise AlertsRefused(str(e)) from None


# ---------------------------------------------------------------- GET api/spools/low and api/storage-use

def low_view(sm) -> dict:
    """`GET api/spools/low`: {threshold_g, spools: [{id, filament, material, color, remaining_g, location, in_stock,
    last_one}]}, least filament first."""
    return alerts.running_low(sm.get("spool"))


def storage_view(settings: dict | None = None) -> dict:
    """`GET api/storage-use`: {filesystems: [{path_label, path, total, free, percent_used, state, title}], items:
    [{key, title, bytes}]}."""
    got = alerts.storage_use(settings)
    return {"filesystems": [{**f, "title": say(f"storage_use_disk_{f['path_label']}")} for f in got["filesystems"]],
            "items": [{"key": i["key"], "title": say(f"storage_use_item_{i['key']}"), "bytes": i["bytes"]}
                      for i in got["items"]]}
