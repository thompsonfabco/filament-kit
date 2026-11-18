"""The event sink: the actor and batch of a request, the run book, the store sink (R80 E1, E5)."""
import pytest

from filament_kit import event_sink
from filament_kit.events import EventStore


@pytest.fixture(autouse=True)
def clean():
    yield
    event_sink.set_sink(None)


def test_the_actor_is_the_hub_unless_a_request_says_otherwise():
    assert event_sink.current_actor() == {"type": "hub"}
    with event_sink.acting("cli"):
        assert event_sink.current_actor() == {"type": "cli"}
    with event_sink.acting({"type": "device", "id": "d1", "name": "Pixel"}):
        assert event_sink.current_actor()["id"] == "d1"
    assert event_sink.current_actor() == {"type": "hub"} and event_sink.current_batch() == ""


def test_one_batch_for_a_request_and_a_nested_scope_joins_it():
    with event_sink.acting("page") as _:
        outer = event_sink.current_batch()
        assert outer.startswith("b-")
        with event_sink.batch_scope() as inner:
            assert inner == outer
        with event_sink.acting("page"):
            assert event_sink.current_batch() == outer
    with event_sink.batch_scope() as alone:
        assert alone.startswith("b-") and alone != outer
    assert event_sink.current_batch() == ""


def test_a_given_batch_is_kept():
    with event_sink.acting("page", batch="rec-9"):
        assert event_sink.current_batch() == "rec-9"


def test_the_batch_does_not_leak_between_threads():
    import threading
    seen = []
    with event_sink.acting("page", batch="rec-1"):
        t = threading.Thread(target=lambda: seen.append(event_sink.current_batch()))
        t.start()
        t.join()
    assert seen == [""]


def test_emit_uses_the_request_actor_and_leaves_out_none_values(tmp_path):
    store = EventStore(tmp_path / "events")
    event_sink.set_sink(event_sink.StoreSink(store))
    with event_sink.acting({"type": "connector", "id": "c", "name": "Claude"}, batch="b-x"):
        event_sink.emit_spool("spool.moved", {"id": 4, "filament": {"name": "PLA", "vendor": {"name": "Acme"}}}, 4,
                              before_location="A", after_location="B", after_grams=None)
    (e,) = store.read()["events"]
    assert e["actor"]["type"] == "connector" and e["subject"] == {"type": "spool", "id": "4", "name": "Acme PLA"}
    assert e["data"] == {"spool": "4", "before_location": "A", "after_location": "B", "batch": "b-x"}


def test_the_run_book_names_a_run_for_its_first_event_and_keeps_it_after_the_run_ends(tmp_path):
    store = EventStore(tmp_path / "events")
    event_sink.set_sink(event_sink.StoreSink(store))
    store.write("print.started", {"type": "printer", "id": "p"}, {"type": "hub"}, {"job": "x"})
    runs = event_sink.RunBook()
    run = runs.begin("p", "a.3mf")
    assert run == "r-2" and runs.current("p") == "r-2"
    runs.end("p")
    assert runs.current("p") == "" and runs.last("p") == "r-2" and runs.last("p", "a.3mf") == "r-2"
    assert runs.last("p", "other.3mf") == "" and runs.last("q") == ""
    runs.forget("p")
    assert runs.last("p") == ""


def test_the_run_book_without_a_store_still_gives_a_unique_value():
    event_sink.set_sink(None)
    runs = event_sink.RunBook()
    a, b = runs.begin("p"), runs.begin("q")
    assert a.startswith("r-") and a != b


def test_the_store_sink_gives_the_next_id_and_the_conditions(tmp_path):
    s = event_sink.StoreSink(EventStore(tmp_path / "events"))
    assert s.next_id() == 1
    s.write("storage.low", {"type": "hub"}, {"type": "hub"}, {"percent": 90}, severity="warn")
    assert s.next_id() == 2 and s.is_raised("storage-low") and len(s.conditions()) == 1
    assert s.write("no.such.kind", {"type": "hub"}) is None            # refused by the store, logged, not raised
