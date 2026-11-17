"""The event store (R80 section 1): files, ids, torn tails, conditions, cursor, wait, two processes, retention."""
import multiprocessing
import os
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from filament_kit import config, events
from filament_kit.events import EventError, EventStore

PRINTER = {"type": "printer", "id": "p-3", "name": "Workshop X1"}
HUB = {"type": "hub"}


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events")


def at(y, m, d=1, h=12):
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc)


def started(store, n=1, **kw):
    return [store.write("print.started", PRINTER, HUB, {"job": f"j{i}", "printer": "p-3"}, **kw) for i in range(n)]


def _writer(root, n, out):
    s = EventStore(root)
    out.put([s.write("print.started", PRINTER, HUB, {"job": "x"})["id"] for _ in range(n)])


def test_write_and_read_back(store):
    ev = store.write("print.paused", PRINTER, {"type": "device", "id": "d1", "name": "Pixel"},
                     {"job": "bracket_v4.3mf", "percent": 41, "reason": "user"}, now=at(2026, 11, 17))
    got = store.read()["events"]
    assert got == [ev]
    assert ev["id"] == 1 and ev["at"] == "2026-11-17T12:00:00Z" and ev["kind"] == "print.paused"
    assert ev["severity"] == "warn"
    assert ev["subject"] == {"type": "printer", "id": "p-3", "name": "Workshop X1"}
    assert ev["actor"] == {"type": "device", "id": "d1", "name": "Pixel"}
    assert ev["data"] == {"job": "bracket_v4.3mf", "percent": "41", "reason": "user"}
    assert ev["condition"] == {"key": "print-paused:p-3", "state": "raised"}


def test_the_file_is_xml_named_by_month_with_the_documented_attributes(store):
    started(store, now=at(2026, 11, 17))
    text = (store.root / "2026-11.xml").read_text(encoding="utf-8")
    assert text.startswith('<events version="1" month="2026-11">\n')
    assert 'kind="print.started"' in text and 'subject-id="p-3"' in text and 'subject-name="Workshop X1"' in text
    assert '<v name="job">j0</v>' in text
    assert not text.rstrip().endswith("</events>")          # appended, never closed or rewritten
    assert not any(p.suffix == ".json" for p in store.root.iterdir())


def test_append_does_not_rewrite_the_file(store):
    started(store)
    f = next(store.root.glob("????-??.xml"))
    before = f.read_bytes()
    started(store)
    assert f.read_bytes().startswith(before)


def test_ids_rise_and_survive_a_restart(store, tmp_path):
    ids = [e["id"] for e in started(store, 3)]
    assert ids == [1, 2, 3]
    again = EventStore(tmp_path / "events")                 # a new object: the Hub restarted
    assert again.write("print.started", PRINTER, HUB)["id"] == 4
    assert again.last_id() == 4


def test_a_lost_counter_is_rebuilt_from_the_newest_event(store):
    started(store, 3)
    (store.root / "next-id").unlink()
    assert store.write("print.started", PRINTER, HUB)["id"] == 4


def test_a_torn_last_element_is_ignored_and_cut_off_by_the_next_write(store):
    started(store, 2)
    f = next(store.root.glob("????-??.xml"))
    with open(f, "ab") as fh:
        fh.write(b'<event id="3" at="2026-11-17T12:00:00Z" kind="print.sta')    # a crash in the middle
    assert [e["id"] for e in store.read()["events"]] == [1, 2]
    ev = store.write("print.started", PRINTER, HUB)
    assert [e["id"] for e in store.read()["events"]] == [1, 2, ev["id"]]
    assert b'kind="print.sta"' not in f.read_bytes() and f.read_bytes().count(b"<event ") == 3


def test_a_torn_header_or_empty_file_is_repaired(store):
    store.root.mkdir(parents=True)
    f = store.root / "2026-11.xml"
    f.write_bytes(b'<events version="1" mon')
    assert store.read()["events"] == []
    store.write("print.started", PRINTER, HUB, now=at(2026, 11))
    assert [e["id"] for e in store.read()["events"]] == [1]


def test_a_damaged_element_in_the_middle_costs_only_itself(store):
    started(store, 3)
    f = next(store.root.glob("????-??.xml"))
    f.write_bytes(f.read_bytes().replace(b'kind="print.started"', b'kind="print.started', 1))   # an open quote
    assert [e["id"] for e in store.read()["events"]] == [2, 3]


def test_control_characters_never_make_a_month_unreadable(store):
    store.write("print.started", PRINTER, HUB, {"job": "a\x00b\x1bc"})
    store.write("print.started", {"type": "printer", "id": "p", "name": "n\x08"}, HUB)
    assert [e["id"] for e in store.read()["events"]] == [1, 2]
    assert store.read()["events"][0]["data"]["job"] == "a b c"


def test_month_rollover_creates_a_new_file(store):
    store.write("print.started", PRINTER, HUB, now=at(2026, 11, 30, 23))
    store.write("print.started", PRINTER, HUB, now=at(2026, 12, 1, 0))
    assert sorted(p.name for p in store.root.glob("????-??.xml")) == ["2026-11.xml", "2026-12.xml"]
    assert [e["id"] for e in store.read()["events"]] == [1, 2]


def test_cursor_limit_and_kinds_filters(store):
    store.write("print.started", PRINTER, HUB, now=at(2026, 10, 5))
    store.write("print.paused", PRINTER, HUB, now=at(2026, 11, 5))
    store.write("spool.low", {"type": "spool", "id": "7"}, HUB, now=at(2026, 11, 6))
    store.write("print.finished", PRINTER, HUB, now=at(2026, 11, 7))
    assert [e["id"] for e in store.read(since=1)["events"]] == [2, 3, 4]
    assert [e["id"] for e in store.read(since=4)["events"]] == []
    page = store.read(since=0, limit=2)
    assert [e["id"] for e in page["events"]] == [1, 2] and page["next"] == 2
    assert [e["id"] for e in store.read(since=page["next"], limit=2)["events"]] == [3, 4]
    assert [e["id"] for e in store.read(kinds=["print."])["events"]] == [1, 2, 4]
    assert [e["id"] for e in store.read(kinds="spool.low,print.finished")["events"]] == [3, 4]
    assert store.read(since=9)["next"] == 9


def test_unknown_kind_and_bad_values_are_refused(store):
    with pytest.raises(EventError):
        store.write("print.exploded", PRINTER, HUB)
    with pytest.raises(EventError):
        store.write("print.started", PRINTER, HUB, {"colour": "red"})
    with pytest.raises(EventError):
        store.write("print.started", {"type": "toaster"}, HUB)
    with pytest.raises(EventError):
        store.write("print.started", PRINTER, {"type": "nobody"})
    with pytest.raises(EventError):
        store.write("print.started", PRINTER, HUB, severity="bad")
    with pytest.raises(EventError):
        store.write("hub.started", HUB, HUB)                 # reserved for phase 4
    with pytest.raises(EventError):
        store.write("print.paused", HUB, HUB)                # a keyed condition needs a subject id
    assert store.read()["events"] == [] and store.last_id() == 0


def test_a_condition_is_raised_once_and_the_clearing_event_clears_it(store):
    first = store.write("print.paused", PRINTER, HUB, {"job": "a"})
    assert [c["id"] for c in store.conditions()] == [first["id"]]
    store.write("print.runout", PRINTER, HUB, {"job": "a"})        # same key: the event is written, one condition
    assert [c["id"] for c in store.conditions()] == [first["id"]]
    assert store.is_raised("print-paused:p-3") and len(store.read()["events"]) == 2
    cleared = store.write("print.resumed", PRINTER, HUB, {"job": "a"})
    assert cleared["condition"] == {"key": "print-paused:p-3", "state": "cleared"}
    assert store.conditions() == [] and not store.is_raised("print-paused:p-3")


@pytest.mark.parametrize("clearing", ["print.finished", "print.failed"])
def test_a_finished_or_failed_print_clears_the_pause(store, clearing):
    store.write("print.paused", PRINTER, HUB)
    store.write("print.paused", {"type": "printer", "id": "p-4"}, HUB)
    store.write(clearing, PRINTER, HUB)
    assert [c["condition"]["key"] for c in store.conditions()] == ["print-paused:p-4"]


def test_clearing_what_was_never_raised_is_a_plain_event(store):
    ev = store.write("print.resumed", PRINTER, HUB)
    assert ev["id"] == 1 and store.conditions() == []


def test_a_moment_has_no_condition(store):
    ev = store.write("printer.error", PRINTER, HUB, {"code": "0300", "text": "x"})
    assert ev["condition"] is None and store.conditions() == []


def test_storage_low_has_one_condition_that_gets_worse_and_is_cleared_by_ok(store):
    store.write("storage.low", HUB, HUB, {"percent": 86}, severity="warn")
    store.write("storage.low", HUB, HUB, {"percent": 96}, severity="bad")
    store.write("storage.low", HUB, HUB, {"percent": 97}, severity="bad")
    (c,) = store.conditions()
    assert c["condition"]["key"] == "storage-low" and c["severity"] == "bad" and c["data"]["percent"] == "96"
    store.write("storage.ok", HUB, HUB, {"free": "9 GB"})
    assert store.conditions() == []


def test_a_check_row_key_stands_in_for_the_subject_id(store):
    store.write("check.failed", HUB, HUB, {"text": "x"}, key="hub-disk")
    store.write("check.failed", HUB, HUB, {"text": "y"}, key="backups")
    assert sorted(c["condition"]["key"] for c in store.conditions()) == ["check:backups", "check:hub-disk"]
    store.write("check.ok", HUB, HUB, key="backups")
    assert [c["condition"]["key"] for c in store.conditions()] == ["check:hub-disk"]


def test_conditions_survive_a_restart(store, tmp_path):
    store.write("spool.low", {"type": "spool", "id": "7"}, HUB, {"spool": "7"})
    assert [c["condition"]["key"] for c in EventStore(tmp_path / "events").conditions()] == ["spool-low:7"]


def test_wait_times_out_empty(store):
    t = time.monotonic()
    res = store.read(since=0, wait=0.6)
    assert res == {"events": [], "next": 0} and 0.5 <= time.monotonic() - t < 3


def test_wait_returns_at_once_when_there_is_news(store):
    started(store)
    t = time.monotonic()
    assert len(store.read(since=0, wait=30)["events"]) == 1 and time.monotonic() - t < 1


def test_wait_wakes_on_a_write_from_another_thread(store):
    threading.Timer(0.3, lambda: started(store)).start()
    t = time.monotonic()
    res = store.read(since=0, wait=20)
    assert [e["id"] for e in res["events"]] == [1] and time.monotonic() - t < 5


def test_wait_ignores_events_the_kinds_filter_does_not_match(store):
    threading.Timer(0.2, lambda: started(store)).start()
    res = store.read(since=0, kinds=["spool."], wait=0.8)
    assert res["events"] == []


def test_wait_wakes_on_a_write_from_another_process(store):
    ctx = multiprocessing.get_context()
    q = ctx.Queue()
    w = ctx.Process(target=_delayed_writer, args=(str(store.root), q))
    w.start()
    t = time.monotonic()
    res = store.read(since=0, wait=20)
    w.join(10)
    assert [e["id"] for e in res["events"]] == [1] and time.monotonic() - t < 10


def _delayed_writer(root, q):
    time.sleep(0.5)
    _writer(root, 1, q)


def test_two_processes_writing_never_reuse_an_id(store):
    ctx = multiprocessing.get_context()
    q = ctx.Queue()
    procs = [ctx.Process(target=_writer, args=(str(store.root), 25, q)) for _ in range(3)]
    for p in procs:
        p.start()
    got = [i for _ in procs for i in q.get(timeout=60)]
    for p in procs:
        p.join(30)
    assert len(got) == 75 and len(set(got)) == 75 and sorted(got) == list(range(1, 76))
    assert [e["id"] for e in store.read(limit=1000)["events"]] == list(range(1, 76))


def test_threads_writing_never_reuse_an_id(store):
    out = []
    ts = [threading.Thread(target=lambda: out.extend(e["id"] for e in started(store, 20))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == list(range(1, 81))


def test_retention_deletes_only_whole_months_older_than_the_limit(store):
    for m in (1, 2, 9, 10, 11):
        store.write("print.started", PRINTER, HUB, now=at(2026, m, 15))
    store.write("spool.low", {"type": "spool", "id": "7"}, HUB, now=at(2026, 11, 16))   # a raised condition
    now = at(2026, 11, 17)
    # 400 days before 2026-11-17 is 2025-10-13: nothing of 2026 is older
    assert store.prune(400, now) == []
    # 60 days: the cutoff is 2026-09-18; months that ended on or before it go (Jan, Feb), September ends later
    assert store.prune(60, now) == ["2026-01.xml", "2026-02.xml"]
    assert sorted(p.name for p in store.root.glob("????-??.xml")) == ["2026-09.xml", "2026-10.xml", "2026-11.xml"]
    assert [e["id"] for e in store.read()["events"]] == [3, 4, 5, 6]
    assert [c["condition"]["key"] for c in store.conditions()] == ["spool-low:7"]
    assert store.write("print.started", PRINTER, HUB, now=now)["id"] == 7             # ids are never reused


def test_retention_bounds_are_30_and_3650_days_and_the_default_is_400(store):
    store.write("print.started", PRINTER, HUB, now=at(2026, 1, 15))
    assert (events.KEEP_DAYS, events.KEEP_MIN, events.KEEP_MAX) == (400, 30, 3650)
    assert store.prune(1, at(2026, 2, 20)) == []                  # clamped to 30: January ended 20 days ago
    assert store.prune(1, at(2026, 3, 5)) == ["2026-01.xml"]      # 32 days after the end
    store.write("print.started", PRINTER, HUB, now=at(2000, 1, 15))
    assert store.prune(10**6, at(2026, 11, 17)) == ["2000-01.xml"]          # clamped to 3650: 2000 is older


def test_the_module_functions_use_the_state_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "st"))
    ev = events.write("print.started", PRINTER, HUB, {"job": "j"})
    assert events.read()["events"] == [ev] and events.last_id() == 1
    assert (tmp_path / "st" / "events" / "next-id").read_text().strip() == "2"
    assert events.conditions() == [] and events.prune() == []


POSIX = pytest.mark.skipif(os.name == "nt", reason="modes, owners and symbolic links are POSIX")


@POSIX
def test_files_and_directory_get_the_ruled_mode(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o750)
    os.chmod(state, 0o750)
    s = EventStore(state / "events")
    s.write("print.paused", PRINTER, HUB, now=at(2026, 11, 17))
    assert (state / "events").stat().st_mode & 0o777 == 0o750               # the state folder's mode bits
    for name in ("2026-11.xml", "next-id", "conditions.xml", ".lock"):
        assert (state / "events" / name).stat().st_mode & 0o777 == 0o644, name


@POSIX
def test_a_first_write_as_root_leaves_the_hubs_owner_and_mode_and_the_hub_can_write_after(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    os.chmod(state, 0o750)
    chowned = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)                          # root: the command line, the installer
    monkeypatch.setattr(events, "_state_owner", lambda root: (4242, 4343))  # the Hub's user and group
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: chowned.append(("fd", os.fstat(fd).st_ino, uid, gid)))
    monkeypatch.setattr(os, "lchown", lambda path, uid, gid: chowned.append(("dir", Path(path).name, uid, gid)))
    s = EventStore(state / "events")
    s.write("print.paused", PRINTER, {"type": "cli"}, now=at(2026, 11, 17))
    assert ("dir", "events", 4242, 4343) in chowned
    files = {n: (state / "events" / n).stat().st_ino for n in ("2026-11.xml", "next-id", "conditions.xml", ".lock")}
    for name, ino in files.items():                                         # every created file handed over
        assert ("fd", ino, 4242, 4343) in chowned, name
        assert (state / "events" / name).stat().st_mode & 0o777 == 0o644
    assert all(uid == 4242 and gid == 4343 for *_, uid, gid in chowned)
    monkeypatch.undo()                                                      # now the Hub itself writes
    assert s.write("print.resumed", PRINTER, HUB, now=at(2026, 12, 1))["id"] == 2
    assert [e["id"] for e in s.read()["events"]] == [1, 2] and s.conditions() == []


@POSIX
def test_nothing_is_chowned_when_the_owner_already_matches(store, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "fchown", lambda *a: calls.append(a))
    monkeypatch.setattr(os, "lchown", lambda *a: calls.append(a))
    store.write("print.paused", PRINTER, HUB)                               # the state folder is ours already
    assert calls == []


@POSIX
def test_a_link_at_the_events_directory_is_refused(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (tmp_path / "events").symlink_to(victim)
    s = EventStore(tmp_path / "events")
    with pytest.raises(EventError, match="symbolic link"):
        s.write("print.started", PRINTER, HUB)
    with pytest.raises(EventError):
        s.read()
    assert list(victim.iterdir()) == []


@POSIX
@pytest.mark.parametrize("name", ["2026-11.xml", "next-id", "conditions.xml", ".lock"])
def test_a_link_at_a_store_file_is_refused_and_nothing_is_written_through_it(store, tmp_path, name):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    store.root.mkdir(parents=True)
    (store.root / name).symlink_to(victim)
    with pytest.raises(EventError, match="symbolic link"):
        store.write("print.paused", PRINTER, HUB, now=at(2026, 11, 17))
    assert victim.read_text() == "keep" and (store.root / name).is_symlink()
    if name != ".lock":
        assert not (store.root / "next-id").exists() or name == "next-id"      # nothing was counted or written


@POSIX
def test_a_name_planted_for_the_temporary_file_is_skipped(store, tmp_path, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    store.root.mkdir(parents=True)
    names = iter(["planted", "fresh", "fresh2", "fresh3"])
    monkeypatch.setattr(events, "_tmp_name", lambda f: f.with_name(f"{f.name}.{next(names)}.tmp"))
    (store.root / "next-id.planted.tmp").symlink_to(victim)
    assert store.write("print.started", PRINTER, HUB)["id"] == 1
    assert victim.read_text() == "keep" and (store.root / "next-id.planted.tmp").is_symlink()
    assert store.last_id() == 1


@POSIX
def test_a_link_at_a_month_file_is_not_read_through(store, tmp_path):
    started(store, now=at(2026, 11, 17))
    real = store.root / "2026-11.xml"
    moved = tmp_path / "moved.xml"
    real.rename(moved)
    real.symlink_to(moved)
    assert store.read()["events"] == []


# ---------------------------------------------------------------- R464 items 2 to 6

def test_replace_is_retried_while_a_reader_holds_the_file(store, monkeypatch):          # item 2
    monkeypatch.setattr(events, "RETRY_REPLACE", True)
    monkeypatch.setattr(events, "REPLACE_PAUSE", 0)
    real, left = os.replace, [3]

    def flaky(a, b):
        if left[0] > 0:
            left[0] -= 1
            raise PermissionError(13, "in use by another process")
        return real(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    ev = store.write("print.paused", PRINTER, HUB)
    assert left[0] == 0 and [c["id"] for c in store.conditions()] == [ev["id"]]


def test_replace_that_never_works_is_a_clear_error_and_writes_nothing(store, monkeypatch):    # item 2
    monkeypatch.setattr(events, "RETRY_REPLACE", True)
    monkeypatch.setattr(events, "REPLACE_PAUSE", 0)
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(13, "in use")))
    with pytest.raises(EventError, match="another program keeps it open"):
        store.write("print.started", PRINTER, HUB)
    monkeypatch.undo()
    assert store.read()["events"] == [] and not list(store.root.glob("*.tmp"))


def test_without_the_retry_a_permission_error_is_raised_as_it_is(store, monkeypatch):         # item 2: POSIX unchanged
    monkeypatch.setattr(events, "RETRY_REPLACE", False)
    calls = []
    monkeypatch.setattr(os, "replace", lambda a, b: calls.append(1) or (_ for _ in ()).throw(PermissionError(13, "x")))
    with pytest.raises(PermissionError):
        store.write("print.started", PRINTER, HUB)
    assert calls == [1]


def test_writers_and_a_reader_never_meet_a_replace_error(store):                             # item 2 (real on Windows)
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                store.conditions()
                store.read()
            except Exception as e:                                    # noqa: BLE001
                errors.append(e)

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(60):
            store.write("print.paused", {"type": "printer", "id": f"p{i % 7}"}, HUB)
    finally:
        stop.set()
        t.join()
    assert errors == [] and store.last_id() == 60


def _reader_process(root, stop_file, out):
    s = EventStore(root)
    errors = 0
    while not os.path.exists(stop_file):
        try:
            s.conditions()
            s.read()
        except Exception:                                             # noqa: BLE001
            errors += 1
    out.put(errors)


def test_a_reader_in_another_process_never_makes_a_write_fail(store, tmp_path):               # item 2 (real on Windows)
    store.write("print.paused", PRINTER, HUB)
    stop = tmp_path / "stop"
    q = multiprocessing.get_context().Queue()
    p = multiprocessing.get_context().Process(target=_reader_process, args=(str(store.root), str(stop), q))
    p.start()
    try:
        for i in range(150):
            store.write("print.paused", {"type": "printer", "id": f"p{i % 7}"}, HUB)
    finally:
        stop.write_text("x")
        p.join(30)
    assert q.get(timeout=10) == 0 and store.last_id() == 151


def test_ids_continue_above_the_old_maximum_after_everything_was_pruned(store):               # item 3
    for m in (1, 2, 3):
        store.write("print.started", PRINTER, HUB, now=at(2026, m, 15))
    assert store.prune(30, at(2026, 11, 17)) == ["2026-01.xml", "2026-02.xml", "2026-03.xml"]
    (store.root / "next-id").unlink()
    assert store.write("print.started", PRINTER, HUB, now=at(2026, 11, 17))["id"] == 4


def test_a_lost_counter_does_not_repeat_the_id_held_by_a_raised_condition(store):            # item 3
    ev = store.write("spool.low", {"type": "spool", "id": "7"}, HUB, now=at(2026, 1, 15))
    for name in ("next-id", "2026-01.xml", "high-water"):
        (store.root / name).unlink(missing_ok=True)
    assert store.write("print.started", PRINTER, HUB, now=at(2026, 2, 1))["id"] == ev["id"] + 1


def test_a_failed_conditions_update_does_not_hide_the_written_event(store, monkeypatch):      # item 4
    real, calls = store._save_conditions, []

    def boom(conds):
        calls.append(1)
        if len(calls) == 1:
            raise OSError(5, "disk trouble")
        return real(conds)
    monkeypatch.setattr(store, "_save_conditions", boom)
    ev = store.write("print.paused", PRINTER, HUB)                  # no error: the event is committed
    assert ev["id"] == 1 and [e["id"] for e in store.read()["events"]] == [1]
    assert (store.root / "conditions-stale").exists()
    assert [c["id"] for c in store.conditions()] == [1]             # repaired from the log
    assert not (store.root / "conditions-stale").exists()


def test_the_next_write_completes_a_missed_conditions_update(store, monkeypatch):             # item 4
    real, calls = store._save_conditions, []

    def boom(conds):
        calls.append(1)
        if len(calls) == 1:
            raise OSError(5, "disk trouble")
        return real(conds)
    monkeypatch.setattr(store, "_save_conditions", boom)
    store.write("print.paused", PRINTER, HUB)
    store.write("spool.low", {"type": "spool", "id": "7"}, HUB)
    assert sorted(c["condition"]["key"] for c in store.conditions()) == ["print-paused:p-3", "spool-low:7"]
    store.write("print.resumed", PRINTER, HUB)
    assert [c["condition"]["key"] for c in store.conditions()] == ["spool-low:7"]


@POSIX
def test_the_directory_is_synced_after_a_new_month_file_and_after_each_replace(store, monkeypatch):   # item 5
    real, dirs = os.fsync, []

    def spy(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            dirs.append(fd)
        return real(fd)
    monkeypatch.setattr(os, "fsync", spy)
    store.write("print.paused", PRINTER, HUB)               # new month file, next-id and conditions.xml replaced
    assert len(dirs) >= 3
    dirs.clear()
    store.write("print.started", PRINTER, HUB)              # the counter replaced
    assert len(dirs) >= 1


def test_a_clock_step_back_across_a_month_does_not_hide_newer_ids(store):                    # item 6
    store.write("print.started", PRINTER, HUB, now=at(2026, 12, 1))
    store.write("print.started", PRINTER, HUB, now=at(2026, 12, 2))
    store.write("print.started", PRINTER, HUB, now=at(2026, 11, 30))     # the clock stepped back: id 3 in Nov
    store.write("print.started", PRINTER, HUB, now=at(2026, 11, 30))
    assert [e["id"] for e in store.read(since=2)["events"]] == [3, 4]
    assert [e["id"] for e in store.read(since=0)["events"]] == [1, 2, 3, 4]


def test_unchanged_months_are_not_parsed_again(store, monkeypatch):                           # item 6 (cost)
    store.write("print.started", PRINTER, HUB, now=at(2026, 10, 1))
    store.write("print.started", PRINTER, HUB, now=at(2026, 11, 1))
    store.read()
    seen = []
    real = events._parse
    monkeypatch.setattr(events, "_parse", lambda raw: seen.append(1) or real(raw))
    store.read()
    store.read(since=1)
    assert seen == []
