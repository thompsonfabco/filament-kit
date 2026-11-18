"""EA3 (c): `spoolwarden alerts`, `events`, `spools low`, the Alerts group of `config`, and the Storage and Running low
rows of `status` (06 9.1, 9.16 to 9.18, 8.3), against the real store and a fake Spoolman."""
from __future__ import annotations

import io
import json
import sys

import pytest

from filament_kit import alerts, alerts_api, cli, config, event_sink, events, inventory, output, status

RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2, "overflow": "Overflow",
         "sealed_location": "Sealed stock"}
GB = 1000 ** 3


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt", "backups"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    alerts.reset()
    yield tmp_path
    alerts.reset()
    event_sink.set_sink(None)


@pytest.fixture
def store(env):
    return events.EventStore()


def run(capsys, *argv):
    rc = cli.main(list(argv))
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def write(store, kind, data=None, subject=None):
    return store.write(kind, subject or {"type": "printer", "id": "p-3", "name": "Workshop X1"}, {"type": "hub"},
                       data or {})


def spools(sm, *grams):
    one = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000, "tare": 213,
           "density": 1.27, "count": 1, "sealed": False}
    return inventory.add_spools(sm, [{**one, "gross": g + 213} for g in grams], RULES, dry=False).spool_ids


# ---------------------------------------------------------------- alerts

def test_alerts_shows_the_switches_and_the_limits(capsys):
    rc, out, _ = run(capsys, "alerts")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "Alerts - 6 of 8 on" or lines[0] == "Alerts · 6 of 8 on"
    assert lines[1].split() == ["KEY", "ALERT", "EVENTS", "STATE"]
    assert lines[2].split()[0] == "runout" and lines[2].split()[-1] == "on"
    assert [ln.split()[0] for ln in lines[2:10]] == list(alerts.KEYS)
    assert "device.down, printer.offline" in lines[9] and lines[9].split()[-1] == "off"
    assert "Spool running low only when it is the last spool of that filament: off" in out
    flat = " ".join(out.split())
    assert "Running low under 150 g" in flat and "Storage warning at 85 % used (bad at 95 %, or under 1 GB free)" in flat
    assert "Change them: sudo spoolwarden alerts set -h" in out
    assert run(capsys, "alerts", "list")[1] == out


def test_alerts_json_is_the_answer_of_the_route(capsys):
    rc, out, _ = run(capsys, "alerts", "--json")
    assert rc == 0 and json.loads(out) == alerts_api.alerts_view()


def test_set_a_type_a_limit_and_the_storage_warning(capsys, env):
    assert run(capsys, "alerts", "set", "finished", "on")[:2] == (0, "Print finished alerts are on.\n")
    assert run(capsys, "alerts", "set", "runout", "off")[1] == "Filament ran out alerts are off.\n"
    assert run(capsys, "alerts", "set", "running-low", "200")[1] == "Running low under 200 g.\n"
    assert run(capsys, "alerts", "set", "storage-warning", "80")[1] == "Storage warning at 80 % used.\n"
    got = alerts.load()
    assert got["types"]["finished"] is True and got["types"]["runout"] is False
    assert (got["running_low_g"], got["storage_warn_percent"]) == (200, 80)
    assert (env / "state" / "alerts.xml").is_file()
    rc, out, _ = run(capsys, "alerts", "set", "running-low", "250", "--json")
    assert rc == 0 and json.loads(out) == {"ok": True, "running_low_g": 250}


@pytest.mark.parametrize("argv, message, fix", [
    (("running-low", "5"), "Enter a whole number, 10 to 2000.", None),
    (("running-low", "lots"), "Enter a whole number, 10 to 2000.", None),
    (("storage-warning", "0"), "Enter a whole number, 1 to 99.", None),
    (("storage-warning", "95"), "The storage warning must be lower than 95 % used, where storage counts as full.", None),
    (("runout", "maybe"), "runout must be on or off.", "Say on or off, or a number: alerts set runout on|off"),
    (("nope", "on"), "nope is not an alert type.",
     "the types are: runout, paused, failed, printer_error, finished, storage, running_low, device_down, running-low, "
     "storage-warning."),
])
def test_a_wrong_change_is_an_error_with_exit_code_2_and_changes_nothing(capsys, argv, message, fix):
    rc, out, err = run(capsys, "alerts", "set", *argv)
    assert rc == 2 and out == ""
    assert err.startswith("Error: ") and message in " ".join(err.split())
    if fix:
        assert fix in " ".join(err.split())
    assert alerts.load() == alerts.defaults()


def test_changing_needs_sudo_and_reading_does_not(capsys, monkeypatch):
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    rc, out, err = run(capsys, "alerts", "set", "finished", "on")
    assert rc == 3 and "needs administrator rights" in err and "sudo spoolwarden alerts set finished on" in err
    assert alerts.load() == alerts.defaults()
    assert run(capsys, "alerts")[0] == 0
    assert run(capsys, "alerts", "test")[0] == 3


def test_alerts_test_asks_every_client_for_a_minute(capsys, env):
    rc, out, _ = run(capsys, "alerts", "test")
    assert rc == 0 and out == "Test alert sent. Every device that asks in the next 60 seconds gets it.\n"
    assert (env / "state" / alerts_api.TEST_FILE).is_file()
    assert alerts_api.take_test(["client:a"])["title"] == "Test alert"
    assert alerts_api.take_test(["client:a"]) is None and alerts_api.take_test(["client:b"]) is not None


def test_a_file_that_cannot_be_saved_is_said_and_the_value_stays(capsys, env, monkeypatch):
    monkeypatch.setattr(events.EventStore, "_atomic", lambda self, f, data: (_ for _ in ()).throw(PermissionError(13, "denied")))
    rc, out, err = run(capsys, "alerts", "set", "running-low", "300")
    assert rc == 0 and out == "Running low under 300 g.\n" and "Alerts settings could not be saved (denied)." in err


# ---------------------------------------------------------------- events

def test_events_prints_the_newest_oldest_first_with_the_titles_and_what_is_raised(capsys, store):
    write(store, "print.started", {"job": "a"})
    write(store, "print.runout", {"job": "bracket", "percent": "41"})
    write(store, "spool.low", {"spool": "214", "filament": "Prusament PLA", "grams": "96", "in_stock": "2"},
          {"type": "spool", "id": "214", "name": "Prusament PLA"})
    rc, out, _ = run(capsys, "events")
    lines = out.splitlines()
    assert rc == 0 and lines[0].split() == ["ID", "TIME", "KIND", "SUBJECT", "WHAT"]
    assert [ln.split()[0] for ln in lines[1:4]] == ["1", "2", "3"]
    assert "print.runout" in lines[2] and "Workshop X1" in lines[2] and "Filament ran out on Workshop X1" in lines[2]
    assert "Spool 214" in lines[3] and "Running low: Prusament PLA" in lines[3]
    assert lines[-1] == "3 events. Raised now: print-paused:p-3, spool-low:214"


def test_events_since_an_id_a_time_and_a_kind(capsys, store):
    for i in range(4):
        write(store, "print.started", {"job": str(i)})
    write(store, "spool.moved", {"spool": "1"}, {"type": "spool", "id": "1", "name": "x"})
    out = run(capsys, "events", "--since", "3")[1]
    assert [ln.split()[0] for ln in out.splitlines()[1:3]] == ["4", "5"] and "2 events." in out
    out = run(capsys, "events", "--kind", "spool")[1]
    assert "1 event." in out and "spool.moved" in out and "print.started" not in out
    assert "5 events." in run(capsys, "events", "--since", "2000-01-01 00:00")[1]
    assert run(capsys, "events", "--since", "2999-01-01 00:00")[1].startswith("No events.")


def test_events_with_nothing_says_so_and_a_bad_since_is_an_error(capsys):
    assert run(capsys, "events")[:2] == (0, "No events.\n")
    rc, out, err = run(capsys, "events", "--since", "yesterday")
    assert rc == 2 and "yesterday is not an event number or a time." in err and "such as 1412" in err


def test_events_json_is_the_answer_of_the_route(capsys, store):
    write(store, "print.runout", {"job": "bracket", "percent": "41"})
    rc, out, _ = run(capsys, "events", "--json")
    got = json.loads(out)
    assert rc == 0 and list(got) == ["events", "next", "oldest", "gap", "test", "conditions"]
    assert got["events"][0]["title"] == "Filament ran out on Workshop X1" and got["next"] == 1
    assert got["conditions"][0]["condition"]["key"] == "print-paused:p-3"
    again = json.loads(run(capsys, "events", "--since", "0", "--json")[1])
    assert again["events"] == got["events"] and again["gap"] is False


def test_events_json_next_is_the_highest_id_and_conditions_is_a_list_with_none(capsys, store):
    assert json.loads(run(capsys, "events", "--json")[1])["conditions"] == []
    write(store, "print.started", {"job": "a"})
    write(store, "print.started", {"job": "b"})
    got = json.loads(run(capsys, "events", "--kind", "nothing.", "--json")[1])
    assert got["events"] == [] and got["next"] == 2 and got["conditions"] == []
    assert json.loads(run(capsys, "events", "--since", "9", "--json")[1])["next"] == 2


def test_events_says_when_some_were_deleted_by_age(capsys, store):
    import datetime
    for i in range(3):
        write(store, "print.started", {"job": str(i)})
    store.prune(30, now=datetime.datetime(2999, 1, 1, tzinfo=datetime.timezone.utc))
    write(store, "print.started", {"job": "late"})
    assert "Note: some events were deleted by age." in run(capsys, "events", "--since", "1")[1]


class Feed:
    """A store that gives its events in rounds and then Ctrl-C."""

    def __init__(self, store, rounds):
        self.store, self.rounds = store, list(rounds)
        self.asked = []

    def __getattr__(self, name):
        return getattr(self.store, name)

    def read(self, since=0, limit=100, kinds=None, wait=0, *, since_at=None):
        self.asked.append((since, wait))
        if not self.rounds:
            raise KeyboardInterrupt
        self.rounds.pop(0)()
        return self.store.read(since, limit, kinds, 0, since_at=since_at)


def test_follow_starts_after_the_newest_prints_as_they_come_and_ends_with_ctrl_c_as_success(capsys, store, monkeypatch):
    write(store, "print.started", {"job": "old"})
    feed = Feed(store, [lambda: write(store, "print.runout", {"job": "bracket", "percent": "41"}),
                        lambda: write(store, "print.finished", {"job": "bracket"})])
    monkeypatch.setattr(events, "store", lambda: feed)
    rc, out, err = run(capsys, "events", "--follow")
    assert rc == 0 and "Following events after 1. Ctrl-C ends." in err
    rows = [ln for ln in out.splitlines() if ln.strip()]
    assert [r.split()[0] for r in rows] == ["2", "3"] and "Filament ran out on Workshop X1" in rows[0]
    assert "old" not in out and feed.asked == [(1, 55), (2, 55), (3, 55)]


def test_follow_json_is_one_event_object_per_line(capsys, store, monkeypatch):
    feed = Feed(store, [lambda: write(store, "print.runout", {"job": "bracket", "percent": "41"}),
                        lambda: write(store, "print.finished", {"job": "bracket"})])
    monkeypatch.setattr(events, "store", lambda: feed)
    rc, out, err = run(capsys, "events", "--follow", "--json")
    lines = out.splitlines()
    assert rc == 0 and len(lines) == 2
    docs = [json.loads(ln) for ln in lines]
    assert [d["kind"] for d in docs] == ["print.runout", "print.finished"] and docs[0]["title"].startswith("Filament ran")


def test_an_unreadable_store_is_an_error_naming_sudo(capsys, monkeypatch):
    def broken(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(events.EventStore, "last_id", broken)
    monkeypatch.setattr(events.EventStore, "read", broken)
    rc, out, err = run(capsys, "events")
    assert rc == 1 and "The events could not be read (Permission denied)." in err and "sudo spoolwarden events" in err


def test_the_command_line_as_root_writes_the_hubs_events_and_leaves_the_sink_as_it_was(capsys, store, monkeypatch):
    seen = []

    def dispatch(args, **kw):
        seen.append(type(event_sink.sink()).__name__)
        event_sink.emit("spool.moved", {"type": "spool", "id": "9", "name": "x"}, {"spool": "9"})
        return 0
    monkeypatch.setattr(cli, "_dispatch", dispatch)
    before = event_sink.sink()
    assert run(capsys, "alerts")[0] == 0
    assert seen == ["StoreSink"] and event_sink.sink() is before
    assert [e["kind"] for e in store.read()["events"]] == ["spool.moved"]
    monkeypatch.delenv("FK_NO_SYSTEMD")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    run(capsys, "alerts")
    assert seen[-1] == "NullSink" and len(store.read()["events"]) == 1                       # not as a person


# ---------------------------------------------------------------- spools low

def test_spools_low_lists_the_least_filament_first_with_stock_and_the_last_one(capsys, spoolman_url, monkeypatch):
    from filament_kit.spoolman import Spoolman
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    ids = spools(sm, 96, 140, 600)
    monkeypatch.setattr(cli, "_default_spoolman", lambda: sm)
    rc, out, _ = run(capsys, "spools", "low")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "2 spools running low (at or under 150 g)"
    assert lines[1].split() == ["SPOOL", "FILAMENT", "LEFT", "LOCATION", "STOCK"]
    assert lines[2].split()[0] == str(ids[0]) and "96 g" in lines[2] and "2 more in stock" in lines[2]
    assert "140 g" in lines[3] and "Last one" not in lines[3]
    assert lines[-1] == "Change the limit: sudo spoolwarden alerts set running-low <grams>"
    body = json.loads(run(capsys, "spools", "low", "--json")[1])
    assert body == alerts_api.low_view(sm) and [s["remaining_g"] for s in body["spools"]] == [96, 140]


def test_spools_low_with_none_low_says_so_with_the_limit(capsys, spoolman_url, monkeypatch):
    from filament_kit.spoolman import Spoolman
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    spools(sm, 600)
    monkeypatch.setattr(cli, "_default_spoolman", lambda: sm)
    alerts.save({"running_low_g": 50})
    assert run(capsys, "spools", "low")[:2] == (0, "No spools are running low (at or under 50 g).\n")


def test_the_last_one_is_marked_and_the_stock_counts_other_spools(capsys, spoolman_url, monkeypatch):
    from filament_kit.spoolman import Spoolman
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    spools(sm, 90)
    monkeypatch.setattr(cli, "_default_spoolman", lambda: sm)
    rc, out, _ = run(capsys, "spools", "low")
    assert "1 spool running low (at or under 150 g)" in out and "Last one" in out.splitlines()[2]
    monkeypatch.setenv("SPOOLWARDEN_GLYPHS", "unicode")
    assert "▲ Last one" in run(capsys, "spools", "low", "--color", "never")[1]


# ---------------------------------------------------------------- status

def test_status_has_the_storage_row_and_it_needs_a_look_past_a_limit(capsys, monkeypatch):
    rows = list(status.alerts_rows({}))
    storage = next(r for r in rows if r.key == "hub.storage")
    assert storage.state == status.OK and storage.group == "Hub"
    assert storage.text == "Storage: 900 GB free of 1.0 TB (10.0 % used)".replace("1.0 TB", "1.0 TB") or \
        storage.text.startswith("Storage: 900 GB free of ")
    monkeypatch.setattr(alerts.shutil, "disk_usage", lambda p: type("U", (), {"total": 100 * GB, "used": 86 * GB,
                                                                             "free": 14 * GB})())
    warn = next(r for r in status.alerts_rows({}) if r.key == "hub.storage")
    assert warn.state == status.FAIL and warn.text == "Storage: 14 GB free of 100 GB (86 % used)"
    assert warn.fix == "Show storage use (Hub page, Overview)" and warn.action == "storage_use"
    monkeypatch.setattr(alerts.shutil, "disk_usage", lambda p: type("U", (), {"total": 100 * GB, "used": 99 * GB,
                                                                             "free": 1 * GB // 2})())
    assert next(r for r in status.alerts_rows({}) if r.key == "hub.storage").state == status.FAIL


def test_status_counts_the_spools_that_are_running_low_from_what_the_hub_raised(capsys, store):
    assert not [r for r in status.alerts_rows({}) if r.key == "hub.running-low"]              # none low: no row
    for i in (1, 2):
        write(store, "spool.low", {"spool": str(i)}, {"type": "spool", "id": str(i), "name": "x"})
    row = next(r for r in status.alerts_rows({}) if r.key == "hub.running-low")
    assert (row.state, row.text, row.group) == (status.INFO, "Running low: 2 spools", "Hub")
    store.write("spool.ok", {"type": "spool", "id": "2", "name": "x"}, {"type": "hub"}, {"spool": "2"})
    assert next(r for r in status.alerts_rows({}) if r.key == "hub.running-low").text == "Running low: 1 spool"


def test_status_says_when_the_alert_settings_cannot_be_saved_or_read(capsys, env, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(events.EventStore, "_atomic",
                  lambda self, f, data: (_ for _ in ()).throw(PermissionError(13, "denied")))
        alerts.save({"running_low_g": 300})
        row = next(r for r in status.alerts_rows({}) if r.key == "hub.alerts-settings")
    assert row.state == status.FAIL and row.text == "Alerts settings could not be saved (denied)."
    assert row.fix.startswith("Check that the Hub's state folder can be written")
    alerts.reset()
    (env / "state" / "alerts.xml").write_text("<nope", encoding="utf-8")
    assert next(r for r in status.alerts_rows({}) if r.key == "hub.alerts-settings").text.startswith(
        "Alerts settings could not be read (")


def test_status_json_carries_the_numbers(capsys, store, spoolman_url, monkeypatch):
    write(store, "spool.low", {"spool": "1"}, {"type": "spool", "id": "1", "name": "x"})
    cfg = config.load()
    cfg["spoolman_url"] = spoolman_url
    config.save(cfg)
    rc, out, _ = run(capsys, "status", "--json")
    doc = json.loads(out)
    assert doc["running_low"] == 1 and set(doc["storage"]) == {"filesystems", "items"}
    assert [i["key"] for i in doc["storage"]["items"]] == ["backups", "photos", "reader", "events", "logs"]
    assert any(r["key"] == "hub.storage" for r in doc["rows"])


# ---------------------------------------------------------------- config

def menu(monkeypatch, script, *flags):
    monkeypatch.setattr(sys, "stdin", io.StringIO(script))
    return cli.main(["config", "--numbered", *flags])


def test_the_alerts_group_is_fourth_with_its_summary_and_eleven_rows(capsys, monkeypatch):
    assert menu(monkeypatch, "q\n") == 0
    out = capsys.readouterr().out
    assert "4  Alerts" in out and "6 of 8 on - running low under 150 g - storage warning at 85 % used" in " ".join(
        out.replace("·", "-").split())
    assert menu(monkeypatch, "4\nq\nq\n") == 0
    out = capsys.readouterr().out
    assert "Settings > Alerts" in out
    labels = ["Filament ran out", "Print paused", "Print failed or stopped", "Printer error", "Print finished",
              "Storage almost full", "Spool running low", "Device stopped answering",
              "Only when it is the last spool of that filament", "Running low under", "Storage warning at"]
    rows = [ln for ln in out.split("Settings > Alerts")[1].splitlines() if ln[:4].strip().isdigit()]
    assert [r.split("  ")[2].strip() for r in rows[:11]] == labels


def test_changing_the_alerts_group_stages_then_saves_with_s_into_alerts_xml(capsys, monkeypatch, env):
    # 4 Alerts: 5 Print finished (toggle), 1 Filament ran out (toggle), 10 Running low under 200, 11 Storage warning 70
    assert menu(monkeypatch, "4\n5\n1\n10\n200\n11\n70\nq\ns\nq\n") == 0
    out = capsys.readouterr().out
    got = alerts.load()
    assert got["types"]["finished"] is True and got["types"]["runout"] is False
    assert (got["running_low_g"], got["storage_warn_percent"]) == (200, 70)
    assert "Saved 4 changes: print finished, filament ran out, running low under, storage warning at." in " ".join(
        out.split())
    assert (env / "state" / "alerts.xml").is_file() and "alerts" not in config.load()


def test_a_wrong_number_in_the_menu_is_refused_with_the_range(capsys, monkeypatch):
    assert menu(monkeypatch, "4\n10\n5\n\nq\nq\n") == 0
    err = capsys.readouterr().err
    assert "Enter a whole number, 10 to 2000." in err
    assert alerts.load() == alerts.defaults()


def test_a_warning_at_or_over_the_bad_limit_is_refused_at_the_save_and_nothing_is_lost(capsys, monkeypatch):
    assert menu(monkeypatch, "4\n11\n95\nq\ns\nq\nn\nq\ny\n") == 5                         # refused: still staged, so q asks
    err = capsys.readouterr().err
    assert "nothing was saved: The storage warning must be lower than 95 % used" in " ".join(err.split())
    assert alerts.load() == alerts.defaults()


def test_config_show_prints_the_alerts_group_and_json_lists_it_without_a_key(capsys):
    rc, out, _ = run(capsys, "config", "show")
    assert rc == 0 and "Alerts\n" in out and "Running low under" in out and "Print finished" in out
    doc = json.loads(run(capsys, "config", "show", "--json")[1])
    group = next(g for g in doc["groups"] if g["group"] == "Alerts")
    assert [i["label"] for i in group["items"]][:2] == ["Filament ran out", "Print paused"]
    assert all(i["key"] is None for i in group["items"]) and group["items"][9]["value"] == 150
    assert not [k for k in doc["values"] if "alert" in k]


def test_config_set_does_not_change_the_alerts(capsys):
    rc, out, err = run(capsys, "config", "set", "running_low_g", "200")
    assert rc == 2 and "alerts" not in out
    assert alerts.load() == alerts.defaults()
    assert output  # the module is imported for its switches
