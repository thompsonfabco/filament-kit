"""`spoolwarden alerts`, `events` and `spools low` (06 9.16 to 9.18) and the Alerts group of `config` (06 8.3).

They read and write what the Hub does, in process: the events are the store's files, the switches are alerts.xml (read
without sudo, written as root with the Hub's owner and mode by the same code the Hub page's save uses), the running-low
list is Spoolman's. `--json` is the answer of the matching route (`GET api/events`, `api/alerts`, `api/spools/low`).
Every text comes from `alerts_api.say`, which the catalogue equals (test_alerts_api.py).

    add_parsers(sub)         the three commands for cli.py's parser
    run_alerts / run_events / run_spools
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from . import alerts, alerts_api, events, output
from .alerts_api import say
from .spoolman import SpoolmanError

SET_WORDS = ("running-low", "storage-warning")


def _sep(text: str) -> str:
    return text.replace(" · ", output.sym("sep"))


def _need_root(tail: str) -> int | None:
    from . import cli
    if not cli._no_systemd() and not cli._is_root():
        return output.need_sudo(cli._sudo_command(f"sudo spoolwarden alerts {tail}".rstrip()))
    return None


def add_parsers(sub) -> None:
    """The three commands, in the parser of cli.py."""
    al = sub.add_parser("alerts", help="what Spoolwarden warns you about: the switches and limits; set, test (root)")
    als = al.add_subparsers(dest="alerts_cmd")
    als.add_parser("list", help="the alert switches and thresholds (also what alerts alone shows)")
    st = als.add_parser("set", help="switch an alert type on or off, or change a limit (root)")
    st.add_argument("what", metavar="type|running-low|storage-warning",
                    help="an alert type (" + ", ".join(alerts.KEYS) + "), running-low or storage-warning")
    st.add_argument("value", metavar="on|off|number", help="on or off for a type; grams for running-low; "
                    "percent used for storage-warning")
    als.add_parser("test", help="send one test alert to every device that asks within a minute (root)")
    ev = sub.add_parser("events", help="what happened on the Hub: the events, newest last; --follow keeps printing")
    ev.add_argument("--since", metavar="ID|TIME", help="an event number (everything after it) or a time such as "
                    "'2026-11-17 04:00'; without it the newest 50")
    ev.add_argument("--kind", metavar="PREFIX", help="only kinds that start with this, e.g. print or spool.low")
    ev.add_argument("--follow", action="store_true", help="keep printing new events as they come; Ctrl-C ends")
    sp = sub.add_parser("spools", help="spools running low")
    sps = sp.add_subparsers(dest="spools_cmd", required=True)
    sps.add_parser("low", help="the opened spools at or under the running-low limit, least filament first")


# ---------------------------------------------------------------- alerts

def _state(on: bool) -> str:
    return say("cli_alerts_state_on" if on else "cli_alerts_state_off")


def run_alerts(args) -> int:
    which = getattr(args, "alerts_cmd", None) or "list"
    if which == "set":
        return cmd_set(args.what, args.value)
    if which == "test":
        return cmd_test()
    return cmd_list()


def cmd_list() -> int:
    view = alerts_api.alerts_view()
    output.emit(view)
    on = sum(1 for t in view["types"] if t["on"])
    heads = say("cli_alerts_columns").split("|")
    rows = [[t["key"], t["title"], ", ".join(t["events"]), _state(t["on"])] for t in view["types"]]
    output.out(_sep(say("cli_alerts_heading", count=on)))
    output.out_lines(output.table(heads, rows, long=1))
    output.out()
    output.out(say("cli_alerts_last_spool", state=_state(view["last_spool_only"])))
    output.out(_sep(say("cli_alerts_limits", grams=view["running_low_g"], warn=view["storage_warn_percent"],
                        bad=view["storage_bad_percent"])))
    output.out(say("cli_alerts_change"))
    _problem()
    return 0


def _problem() -> None:
    """A note when alerts.xml cannot be read or written (the Checks row says it too)."""
    bad = alerts.problem()
    if bad:
        kind, reason = bad
        output.note(say("status_alerts_unsaved" if kind == "unsaved" else "status_alerts_unreadable", reason=reason))


def cmd_set(what: str, value: str) -> int:
    """`alerts set <type> on|off`, `alerts set running-low <grams>`, `alerts set storage-warning <percent>`."""
    stop = _need_root(f"set {what} {value}")
    if stop is not None:
        return stop
    word = str(what).strip()
    value = str(value).strip()
    try:
        if word in alerts.KEYS:
            if value.lower() not in ("on", "off"):
                output.error(say("alerts_error_flag", field=word), say("cli_alerts_need_value", usage=f"alerts set {word} on|off"))
                return output.USAGE
            on = value.lower() == "on"
            alerts_api.save({"types": {word: on}})
            output.emit({"ok": True, "type": word, "on": on})
            output.result(say("cli_alerts_set_on" if on else "cli_alerts_set_off", alert=say(f"alerts_type_{word}")))
        elif word == "running-low":
            grams = alerts_api.whole(value, alerts.LOW_G_MIN, alerts.LOW_G_MAX, "running_low_g")
            alerts_api.save({"running_low_g": grams})
            output.emit({"ok": True, "running_low_g": grams})
            output.result(say("cli_alerts_set_low", grams=grams))
        elif word == "storage-warning":
            percent = alerts_api.whole(value, 1, 99, "storage_warn_percent")
            alerts_api.save({"storage_warn_percent": percent})
            output.emit({"ok": True, "storage_warn_percent": percent})
            output.result(say("cli_alerts_set_warn", percent=percent))
        else:
            output.error(say("cli_alerts_unknown_type", type=word),
                         say("cli_alerts_unknown_type_fix", types=", ".join((*alerts.KEYS, *SET_WORDS))))
            return output.USAGE
    except alerts_api.AlertsRefused as e:
        output.error(str(e))
        return output.USAGE
    _problem()
    return 0


def cmd_test() -> int:
    """`alerts test`: one test alert to every client that asks within a minute (the Hub reads the marker file)."""
    stop = _need_root("test")
    if stop is not None:
        return stop
    try:
        alerts_api.send_test_to_all()
    except (OSError, events.EventError) as e:
        output.error(f"the test alert could not be asked for ({getattr(e, 'strerror', None) or e}).",
                     "check that the Hub's state folder can be written.")
        return output.FAILED
    output.emit({"ok": True, "seconds": alerts_api.TEST_SECONDS})
    output.result(say("cli_alerts_test_sent", seconds=alerts_api.TEST_SECONDS))
    return 0


# ---------------------------------------------------------------- events

def parse_since(text: str) -> tuple[int | None, str | None]:
    """`1412` is an event number (read with `since`); a time such as `2026-11-17 04:00` (the Hub's own clock, or
    with a zone) is read with `since_at`. ValueError when it is neither."""
    t = str(text).strip()
    if t.isdigit():
        return int(t), None
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(t) from None
    return None, alerts_api.parse_time((dt if dt.tzinfo else dt.astimezone()).isoformat())


def _time(at: str) -> str:
    try:
        return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=__import__("datetime").timezone.utc) \
            .astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return at


def _subject(ev: dict) -> str:
    s = ev["subject"]
    if s["type"] == "spool":
        return f"Spool {s['id']}"
    if s["type"] == "hub":
        return "Hub"
    return s["name"] or s["id"]


def _row(ev: dict) -> list:
    return [ev["id"], _time(ev["at"]), ev["kind"], _subject(ev), ev["title"]]


def _unreadable(e: Exception) -> int:
    output.error(say("cli_events_unreadable", reason=getattr(e, "strerror", None) or str(e)),
                 say("cli_events_unreadable_fix"))
    return output.FAILED


def run_events(args) -> int:
    kinds = [args.kind] if getattr(args, "kind", None) else None
    since = since_at = None
    if args.since:
        try:
            since, since_at = parse_since(args.since)
        except ValueError:
            output.error(say("cli_events_bad_since", value=args.since), say("cli_events_bad_since_fix"))
            return output.USAGE
    try:
        if args.follow:
            return follow(since, since_at, kinds)
        return show(since, since_at, kinds)
    except (OSError, events.EventError) as e:
        return _unreadable(e)


def show(since, since_at, kinds) -> int:
    if since is None and since_at is None:
        answer = {"events": alerts_api.newest(50, kinds), "next": None}
        answer["next"] = answer["events"][-1]["id"] if answer["events"] else events.last_id()
        answer.update(oldest=events.oldest(), gap=False, test=None,
                      conditions=[alerts_api.event_view(c) for c in events.conditions()])
    else:
        answer = alerts_api.events_answer(since=since, since_at=since_at, kinds=kinds, limit=1000)
        answer["test"] = None                        # a test alert is for a client, not for a command
    output.emit(answer)
    rows = answer["events"]
    if rows:
        output.out_lines(output.table(say("cli_events_columns").split("|"), [_row(e) for e in rows], long=4,
                                      right=(0,)))
        output.out()
    else:
        output.out(say("cli_events_none"))
    raised = ", ".join(c["condition"]["key"] for c in answer["conditions"])
    last = " ".join(p for p in (say("cli_events_count", count=len(rows)) if rows else "",
                                say("cli_events_raised", keys=raised) if raised else "") if p)
    if last:
        output.out(last)
    if answer["gap"]:
        output.out(say("cli_events_gap"))
    return 0


def follow(since, since_at, kinds) -> int:
    """`events --follow`: what is after the number given (or after the newest), then each event as it comes, until
    Ctrl-C (exit code 0). With `--json` one event object per line."""
    store = events.store()
    cursor = since if since is not None else (store.last_id() if since_at is None else 0)
    output.err(say("cli_events_following", id=cursor))
    settings = alerts.load()
    try:
        while True:
            got = store.read(cursor, 100, kinds, wait=events.WAIT_MAX, since_at=since_at)
            for ev in got["events"]:
                view = alerts_api.event_view(ev, settings)
                if output.json_mode():
                    sys.stdout.write(json.dumps(view) + "\n")
                    sys.stdout.flush()
                else:
                    output.out_lines(output.table(say("cli_events_columns").split("|"), [_row(view)], long=4,
                                                  right=(0,))[1:])
            cursor, since_at = got["next"], None
    except KeyboardInterrupt:
        return 0


# ---------------------------------------------------------------- spools low

def run_spools(args, sm_factory=None) -> int:
    from . import cli
    try:
        sm = (sm_factory or cli._default_spoolman)()
        view = alerts_api.low_view(sm)
    except SpoolmanError as e:
        output.error(f"Spoolman did not answer: {e}", "start Spoolman, then run it again.")
        return output.FAILED
    output.emit(view)
    rows, grams = view["spools"], view["threshold_g"]
    if not rows:
        output.out(say("cli_low_none", grams=grams))
        return 0
    output.out(say("cli_low_heading", count=len(rows), grams=grams))
    warn = output.glyph("look")                 # `Last one` is marked with the warn glyph (06 6.2)
    table = [[r["id"], r["filament"], say("cli_low_left", grams=alerts_api.number(r["remaining_g"])),
              r["location"] or "",
              (f"{warn} " if warn else "") + say("cli_low_last") if r["last_one"]
              else say("cli_low_in_stock", count=r["in_stock"])] for r in rows]
    output.out_lines(output.table(say("cli_low_columns").split("|"), table, long=1, right=(0, 2)))
    output.out(say("cli_low_change"))
    return 0

