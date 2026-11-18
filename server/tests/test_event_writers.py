"""Spool and usage events written by the code that changes things, through the event sink (R80 sections 2, E1, E5)."""
import pytest

from filament_kit import event_sink, inventory, storage
from filament_kit.event_sink import NullSink, StoreSink
from filament_kit.events import EventStore
from filament_kit.spoolman import Spoolman

RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}
UID = "a:b:c:d:e:f:1"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    yield
    event_sink.set_sink(None)
    event_sink.set_weight_hook(None)


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "state" / "events")
    event_sink.set_sink(StoreSink(s))
    return s


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def item(**kw):
    base = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000,
            "tare": 213, "density": 1.27, "count": 1}
    base.update(kw)
    return base


def evs(store, prefix="spool."):
    return [e for e in store.read()["events"] if e["kind"].startswith(prefix)]


def test_nothing_is_written_until_a_sink_is_given(sm, tmp_path):
    inventory.add_spools(sm, [item()], RULES, dry=False)
    assert not (tmp_path / "state" / "events").exists()
    assert isinstance(event_sink.sink(), NullSink)


def test_add_writes_spool_added_per_spool_with_one_batch_and_the_values(sm, store):
    r = inventory.add_spools(sm, [item(count=2)], RULES, dry=False)
    es = evs(store)
    assert [e["kind"] for e in es] == ["spool.added", "spool.added"]
    assert [e["subject"]["id"] for e in es] == [str(i) for i in r.spool_ids]
    assert es[0]["subject"]["name"] == "SUNLU PLA+ Grey" and es[0]["actor"] == {"type": "hub", "id": "", "name": ""}
    d = es[0]["data"]
    assert d["spool"] == str(r.spool_ids[0]) and d["after_grams"] == "1000" and d["after_location"]
    assert d["batch"].startswith("b-") and d["batch"] == es[1]["data"]["batch"]
    inventory.add_spools(sm, [item()], RULES, dry=False)
    assert evs(store)[2]["data"]["batch"] != d["batch"]            # another request, another batch


def test_a_preview_writes_nothing(sm, store):
    inventory.add_spools(sm, [item()], RULES, dry=True)
    assert evs(store) == []


def test_the_request_sets_the_actor_and_the_batch(sm, store):
    with event_sink.acting({"type": "device", "id": "d1", "name": "Pixel"}, batch="rec-77"):
        inventory.add_spools(sm, [item(count=2)], RULES, dry=False)
    assert {e["data"]["batch"] for e in evs(store)} == {"rec-77"}
    assert {e["actor"]["id"] for e in evs(store)} == {"d1"}


def new_spool(sm, **kw):
    return inventory.add_spools(sm, [item(**kw)], RULES, dry=False).spool_ids[0]


def test_weighing_moving_and_emptying_write_their_events_with_before_and_after(sm, store):
    sid = new_spool(sm, gross=713)                                  # opened, 500 g
    before = len(evs(store))
    inventory.update_spool(sm, sid, remaining=420, location="Rack 2", dry=False)
    w, m = evs(store)[before:]
    assert (w["kind"], m["kind"]) == ("spool.weighed", "spool.moved")
    assert w["data"]["before_grams"] == "500" and w["data"]["after_grams"] == "420" and w["data"]["batch"]
    assert m["data"]["before_location"] and m["data"]["after_location"] == "Rack 2"
    assert w["data"]["batch"] == m["data"]["batch"]
    inventory.update_spool(sm, sid, empty=True, dry=False)
    e = evs(store)[-1]
    assert e["kind"] == "spool.emptied" and e["data"]["before_grams"] == "420" and e["data"]["after_grams"] == "0"


def test_a_dry_edit_and_an_edit_that_changes_nothing_write_nothing(sm, store):
    sid = new_spool(sm, gross=713)
    n = len(evs(store))
    inventory.update_spool(sm, sid, remaining=100, dry=True)
    inventory.update_spool(sm, sid, dry=False)
    loc = sm.get(f"spool/{sid}")["location"]
    inventory.update_spool(sm, sid, location=loc, dry=False)        # the same place
    assert len(evs(store)) == n


def test_a_weight_change_checks_running_low_right_away_with_spoolman(sm, store):
    seen = []
    event_sink.set_weight_hook(lambda s: seen.append(s))
    sid = new_spool(sm, gross=713)
    inventory.update_spool(sm, sid, location="Rack 2", dry=False)
    assert seen == []                                               # a move is not a weight change
    inventory.update_spool(sm, sid, remaining=100, dry=False)
    assert seen == [sm]


def test_a_failing_sink_or_hook_never_fails_the_spool_change(sm):
    class Boom(NullSink):
        def write(self, *a, **k):
            raise RuntimeError("store is gone")
    event_sink.set_sink(Boom())
    event_sink.set_weight_hook(lambda s: 1 / 0)
    sid = new_spool(sm, gross=713)
    assert inventory.update_spool(sm, sid, remaining=50, dry=False)["remaining_weight"] == 50


def test_the_store_sink_swallows_a_store_error(sm):
    class Broken:
        def write(self, *a, **k):
            from filament_kit.events import EventError
            raise EventError("a link")
    event_sink.set_sink(StoreSink(Broken()))
    assert new_spool(sm)


def test_opening_a_spool_writes_spool_opened(sm, store):
    sid = new_spool(sm)                                             # sealed
    n = len(evs(store))
    inventory.open_spool(sm, sid, UID, RULES, gross=800, dry=False)
    (e,) = evs(store)[n:]
    assert e["kind"] == "spool.opened" and e["data"]["before_location"] == "Sealed stock"
    assert e["data"]["after_location"] and e["data"]["after_location"] != "Sealed stock"
    assert e["data"]["before_grams"] == "1000" and e["data"]["after_grams"] == "587"
    inventory.open_spool(sm, sid, UID, RULES, dry=True)             # a preview
    assert len(evs(store)) == n + 1


def test_linking_a_tag_to_a_sealed_spool_opens_it_and_says_so_once(sm, store):
    sid = new_spool(sm)
    n = len(evs(store))
    inventory.link_tag(sm, sid, UID, force=False, dry=False)
    assert [e["kind"] for e in evs(store)[n:]] == ["spool.opened"]
    inventory.link_tag(sm, sid, UID, force=False, dry=False)         # nothing changes
    assert len(evs(store)) == n + 1


class FakeSm:
    def __init__(self, spools):
        self.spools = spools

    def get(self, path):
        return self.spools

    def patch(self, path, body):
        self.spools[int(path.split("/")[1]) - 1].update(body)


def test_a_rename_writes_one_location_renamed_and_no_spool_moved(store):
    sm = FakeSm([{"id": 1, "location": "Rack 1"}, {"id": 2, "location": "Rack 1"}, {"id": 3, "location": "Box 01"},
                 {"id": 4, "location": "Box 02"}])
    inventory.rename_locations(sm, [storage.Rename("Rack 1", "PLA rack"), storage.Rename("Box ", "Dry ", True)])
    es = store.read()["events"]
    assert [e["kind"] for e in es] == ["location.renamed", "location.renamed"]
    assert [e["data"] for e in es] == [{"from": "Rack 1", "to": "PLA rack", "spools": "2"},
                                       {"from": "Box ", "to": "Dry ", "spools": "2"}]
    assert es[0]["subject"]["type"] == "location"


def test_a_rename_that_matches_no_spool_still_says_so(store):
    inventory.rename_locations(FakeSm([]), [storage.Rename("A", "B")])
    assert store.read()["events"][0]["data"]["spools"] == "0"
