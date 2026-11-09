import json
import threading
import time

import pytest

from filament_kit import inventory, tags
from filament_kit.spoolman import Spoolman, SpoolmanError

RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def item(**kw):
    base = {"vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "color_hex": "8A8C8E", "net": 1000,
            "tare": 213, "density": 1.27, "nozzle": 220, "bed": 55, "nozzle_range": "200-260",
            "lot": "L1", "count": 1, "price_per_kg": 12.5}
    base.update(kw)
    return base


UID = "4:77:90:e:9:22:89"
UID2 = "4:77:8f:e:9:22:89"


def test_add_new_vendor_and_filament(sm, spoolman_fake_store):
    r = inventory.add_spools(sm, [item(count=2)], RULES, dry=False)
    assert len(r.spool_ids) == 2 and not r.dry
    assert any("new vendor" in ln for ln in r.lines)
    (v,) = spoolman_fake_store["vendors"].values()
    assert v["name"] == "SUNLU" and v["empty_spool_weight"] == 213
    (f,) = spoolman_fake_store["filaments"].values()
    assert f["price"] == 12.5 and f["settings_extruder_temp"] == 220
    assert json.loads(f["extra"]["nozzle_range"]) == "200-260"
    s = sm.get(f"spool/{r.spool_ids[0]}")
    assert s["location"] == "Sealed stock" and s["comment"] == inventory.SEALED_COMMENT
    assert s["remaining_weight"] == 1000


def test_add_existing_filament_joins(sm, spoolman_fake_store):
    inventory.add_spools(sm, [item()], RULES, dry=False)
    before = json.dumps(list(spoolman_fake_store["filaments"].values()), sort_keys=True)
    r = inventory.add_spools(sm, [item(vendor="sunlu", name="pla+ grey", tare=999, net=750)], RULES, dry=False)
    assert len(spoolman_fake_store["vendors"]) == 1 and len(spoolman_fake_store["filaments"]) == 1
    assert json.dumps(list(spoolman_fake_store["filaments"].values()), sort_keys=True) == before
    assert any("existing filament" in ln for ln in r.lines)
    assert len(spoolman_fake_store["spools"]) == 2


def test_the_result_lines_read_as_sentences(sm, spoolman_fake_store):
    """Emulator finding 7 (v0.4.2): the app shows these lines as Add's result, so they are sentences, not log lines."""
    r = inventory.add_spools(sm, [item(count=2)], RULES, dry=True)
    assert r.lines[-1] == ("Would add 2 spools of SUNLU PLA+ Grey (new filament) at Sealed stock (where sealed spools "
                           "go, since no location was given), 1000 g each")
    r = inventory.add_spools(sm, [item(count=2)], RULES, dry=False)
    a, b = r.spool_ids
    assert r.lines[-1] == (f"Added 2 spools of SUNLU PLA+ Grey (new filament), spool ids {a}, {b}, at Sealed stock "
                           "(where sealed spools go, since no location was given), 1000 g each")
    r = inventory.add_spools(sm, [item(sealed=False, gross=1150, location="Rack 1")], RULES, dry=False)
    (f,) = spoolman_fake_store["filaments"].values()
    assert r.lines[-1] == (f"Added 1 spool of SUNLU PLA+ Grey (existing filament F{f['id']}), spool id {r.spool_ids[0]}, "
                           "at Rack 1, opened, 937 g (weighed 1150 g, the spool itself 213 g)")
    assert "@" not in r.lines[-1] and "spool(s)" not in r.lines[-1] and "[" not in r.lines[-1]


def test_a_location_the_rules_chose_says_why(sm, spoolman_fake_store):
    """Finding 7, its second half: the location was left blank and the line said Sealed stock with no sign why."""
    r = inventory.add_spools(sm, [item(sealed=False, material="PETG", name="petg black", count=2)], RULES, dry=True)
    assert "at Storage box 01 (the first free storage box, since no location was given), opened" in r.lines[-2]
    assert "at Storage box 02 (the first free storage box, since no location was given)" in r.lines[-1]
    r = inventory.add_spools(sm, [item(sealed=False)], RULES, dry=True)
    assert "at Rack 1 (where opened PLA goes, since no location was given)" in r.lines[-1]
    # the default install has no storage boxes (box_count 0): the line must not say they are all taken
    r = inventory.add_spools(sm, [item(sealed=False, material="PETG", name="petg red")], {**RULES, "box_count": 0},
                             dry=True)
    assert "at Overflow (no storage boxes are set up, so opened spools go here, since no location was given)"         in r.lines[-1] and "taken" not in r.lines[-1]
    r = inventory.add_spools(sm, [item(location="Shelf")], RULES, dry=True)
    assert "at Shelf, " in r.lines[-1] and "no location was given" not in r.lines[-1]


def test_add_dry_run_writes_nothing(sm, spoolman_fake_store):
    r = inventory.add_spools(sm, [item(count=3)], RULES, dry=True)
    assert r.dry and r.spool_ids == [] and r.lines
    assert not any("None" in line for line in r.lines)  # no placeholder ids in the preview
    assert not spoolman_fake_store["vendors"] and not spoolman_fake_store["filaments"]
    assert not spoolman_fake_store["spools"]


def test_gross_requires_count_1(sm, spoolman_fake_store):
    with pytest.raises(ValueError):
        inventory.add_spools(sm, [item(sealed=False, gross=500, count=2)], RULES, dry=False)
    with pytest.raises(ValueError):
        inventory.add_spools(sm, [item(sealed=False, gross=100)], RULES, dry=False)
    assert not spoolman_fake_store["spools"] and not spoolman_fake_store["vendors"]


def test_gross_sets_remaining(sm):
    r = inventory.add_spools(sm, [item(sealed=False, gross=500)], RULES, dry=False)
    s = sm.get(f"spool/{r.spool_ids[0]}")
    assert s["remaining_weight"] == 287 and s["comment"] in (None, "")
    assert s["location"] == "Rack 1"


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "2", None])
def test_count_validated(sm, spoolman_fake_store, bad):
    with pytest.raises(ValueError):
        inventory.add_spools(sm, [item(), item(name="Other", count=bad)], RULES, dry=False)
    assert not spoolman_fake_store["spools"]


def test_missing_required_key(sm):
    it = item()
    del it["density"]
    with pytest.raises(ValueError):
        inventory.add_spools(sm, [it], RULES, dry=False)


def test_spool_note_appended(sm):
    r = inventory.add_spools(sm, [item(spool_note="UNVERIFIED")], RULES, dry=False)
    assert sm.get(f"spool/{r.spool_ids[0]}")["comment"] == "SEALED - tag when opened | UNVERIFIED"


def _slow_spool_post(sm, monkeypatch):
    """Widen the race window: every spool POST sleeps, so an unlocked second add would read stale locations."""
    real_post = sm.post

    def post(path, body):
        if path == "spool":
            time.sleep(0.3)
        return real_post(path, body)

    monkeypatch.setattr(sm, "post", post)


def test_concurrent_adds_get_distinct_boxes(sm, monkeypatch):
    _slow_spool_post(sm, monkeypatch)
    results = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        results.append(inventory.add_spools(
            sm, [item(material="PETG", name="PETG Blue", sealed=False)], RULES, dry=False))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    locs = {sm.get(f"spool/{r.spool_ids[0]}")["location"] for r in results}
    assert locs == {"Storage box 01", "Storage box 02"}


def test_add_missing_readback_raises(sm, monkeypatch):
    real_get = sm.get

    def get(path):
        if path.startswith("spool/"):
            raise SpoolmanError("gone", status=404)
        return real_get(path)

    monkeypatch.setattr(sm, "get", get)
    with pytest.raises(inventory.AddFailed, match="not found after writing") as e:
        inventory.add_spools(sm, [item()], RULES, dry=False)
    assert len(e.value.partial.spool_ids) == 1


def _spool(sm, **kw):
    return sm.get(f"spool/{inventory.add_spools(sm, [item(**kw)], RULES, dry=False).spool_ids[0]}")


def test_link_same_spool_twice_is_noop(sm):
    s = _spool(sm)
    r1 = inventory.link_tag(sm, s["id"], "04:77:90:0E:09:22:89", force=False, dry=False)
    assert not r1.noop
    after = sm.get(f"spool/{s['id']}")
    assert tags.stored(after) == UID and after["first_used"] and after["comment"] in (None, "")
    r2 = inventory.link_tag(sm, s["id"], UID, force=False, dry=False)
    assert r2.noop
    assert sm.get(f"spool/{s['id']}") == after


def test_link_conflict_refused_names_other_spool(sm):
    a, b = _spool(sm), _spool(sm)
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    with pytest.raises(inventory.TagConflict) as e:
        inventory.link_tag(sm, b["id"], UID, force=False, dry=False)
    assert e.value.other["id"] == a["id"] and f"{a['id']}" in str(e.value)
    assert tags.stored(sm.get(f"spool/{b['id']}")) is None
    assert tags.stored(sm.get(f"spool/{a['id']}")) == UID


def test_link_conflict_on_archived_spool(sm):
    a, b = _spool(sm), _spool(sm)
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    sm.patch(f"spool/{a['id']}", {"archived": True})
    with pytest.raises(inventory.TagConflict):
        inventory.link_tag(sm, b["id"], UID, force=False, dry=False)


def test_link_force_moves_tag(sm):
    a, b = _spool(sm), _spool(sm)
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    inventory.link_tag(sm, b["id"], UID, force=True, dry=False)
    assert tags.stored(sm.get(f"spool/{a['id']}")) is None
    assert tags.stored(sm.get(f"spool/{b['id']}")) == UID


def test_link_spool_with_other_tag_refused_unless_force(sm):
    a = _spool(sm)
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    with pytest.raises(inventory.TagConflict):
        inventory.link_tag(sm, a["id"], UID2, force=False, dry=False)
    inventory.link_tag(sm, a["id"], UID2, force=True, dry=False)
    assert tags.stored(sm.get(f"spool/{a['id']}")) == UID2


def test_link_dry_and_bad_uid(sm):
    a = _spool(sm)
    r = inventory.link_tag(sm, a["id"], UID, force=False, dry=True)
    assert r.dry and tags.stored(sm.get(f"spool/{a['id']}")) is None
    with pytest.raises(ValueError):
        inventory.link_tag(sm, a["id"], "zz", force=False, dry=False)


def test_link_keeps_first_used(sm):
    a = _spool(sm)
    sm.patch(f"spool/{a['id']}", {"first_used": "2026-01-01T00:00:00Z"})
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    assert sm.get(f"spool/{a['id']}")["first_used"] == "2026-01-01T00:00:00Z"


def test_link_tag_did_not_land(sm, monkeypatch):
    a = _spool(sm)
    real_get = sm.get
    state = {"patched": False}
    real_patch = sm.patch

    def patch(path, body):
        state["patched"] = True
        return real_patch(path, body)

    def get(path):
        out = real_get(path)
        if state["patched"] and path == f"spool/{a['id']}":
            out["extra"] = {}
        return out

    monkeypatch.setattr(sm, "patch", patch)
    monkeypatch.setattr(sm, "get", get)
    with pytest.raises(RuntimeError, match="tag did not land"):
        inventory.link_tag(sm, a["id"], UID, force=False, dry=False)


def test_add_and_link_only_single_opened(sm):
    r = inventory.add_and_link(sm, [item(sealed=False)], RULES, dry=False, uid=UID)
    assert tags.stored(sm.get(f"spool/{r.spool_ids[0]}")) == UID
    r2 = inventory.add_and_link(sm, [item(count=2, name="Two")], RULES, dry=False, uid=UID2)
    assert all(tags.stored(sm.get(f"spool/{i}")) is None for i in r2.spool_ids)
    r3 = inventory.add_and_link(sm, [item(sealed=True, name="Sealed one")], RULES, dry=False, uid=UID2)
    assert tags.stored(sm.get(f"spool/{r3.spool_ids[0]}")) is None
    r4 = inventory.add_and_link(sm, [item(sealed=False, name="No tag")], RULES, dry=False, uid=None)
    assert tags.stored(sm.get(f"spool/{r4.spool_ids[0]}")) is None


def test_add_and_link_bad_uid_writes_nothing(sm, spoolman_fake_store):
    with pytest.raises(ValueError):
        inventory.add_and_link(sm, [item(sealed=False)], RULES, dry=False, uid="zz")
    assert not spoolman_fake_store["spools"]


def test_update_gross_below_tare_refused(sm):
    s = _spool(sm)
    with pytest.raises(ValueError):
        inventory.update_spool(sm, s["id"], gross=100, dry=False)
    assert sm.get(f"spool/{s['id']}")["remaining_weight"] == 1000


def test_update_gross_location_empty(sm):
    s = _spool(sm)
    out = inventory.update_spool(sm, s["id"], gross=513, location="Rack 1", dry=False)
    assert out["remaining_weight"] == 300 and out["location"] == "Rack 1"
    dry = inventory.update_spool(sm, s["id"], remaining=50, dry=True)
    assert dry["remaining_weight"] == 50 and sm.get(f"spool/{s['id']}")["remaining_weight"] == 300
    out = inventory.update_spool(sm, s["id"], empty=True, dry=False)
    assert out["remaining_weight"] == 0 and out["archived"] is True


def test_find_by_tag(sm):
    a, b = _spool(sm), _spool(sm, vendor="Other", name="Red")
    inventory.link_tag(sm, b["id"], UID, force=False, dry=False)
    assert inventory.by_tag(sm, "04:77:90:0e:09:22:89")["id"] == b["id"]
    assert inventory.by_tag(sm, UID2) is None
    assert [s["id"] for s in inventory.find(sm, "4:77:90", sealed_only=False)] == [b["id"]]
    assert {s["id"] for s in inventory.find(sm, "SUNLU grey", sealed_only=False)} == {a["id"]}
    assert [s["id"] for s in inventory.find(sm, "sealed stock", sealed_only=True)] == [a["id"]]


def test_add_and_link_conflict_writes_nothing(sm, spoolman_fake_store):
    a = _spool(sm)
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    n = len(spoolman_fake_store["spools"])
    with pytest.raises(inventory.TagConflict) as e:
        inventory.add_and_link(sm, [item(sealed=False, name="New one")], RULES, dry=False, uid=UID)
    assert e.value.other["id"] == a["id"] and e.value.reason == "tag_on_other_spool"
    assert len(spoolman_fake_store["spools"]) == n
    assert not [f for f in spoolman_fake_store["filaments"].values() if f["name"] == "New one"]


@pytest.mark.parametrize("bad", [
    {"vendor": 5}, {"name": ["x"]}, {"material": None}, {"price_per_kg": "12"}, {"nozzle": "220"},
    {"bed": [1]}, {"location": 3}, {"color_hex": 1}, {"lot": 1}, {"note": 1}, {"nozzle_range": 1},
    {"bed_range": 1}, {"spool_note": 1}, {"gross": "5"}, {"sealed": "no"}, {"net": 0}, {"density": "1.2"},
])
def test_validation_covers_every_item_before_any_write(sm, spoolman_fake_store, bad):
    with pytest.raises(ValueError):
        inventory.add_spools(sm, [item(name="Good"), item(**{"name": "Bad", **bad})], RULES, dry=False)
    assert not spoolman_fake_store["spools"] and not spoolman_fake_store["filaments"]
    assert not spoolman_fake_store["vendors"]


def test_mid_batch_spoolman_error_reports_partial(sm, monkeypatch):
    real_post = sm.post
    calls = {"n": 0}

    def post(path, body):
        if path == "spool":
            calls["n"] += 1
            if calls["n"] == 2:
                raise SpoolmanError("boom", status=500)
        return real_post(path, body)

    monkeypatch.setattr(sm, "post", post)
    with pytest.raises(inventory.AddFailed) as e:
        inventory.add_spools(sm, [item(count=3)], RULES, dry=False)
    assert len(e.value.partial.spool_ids) == 1


def test_gross_checked_against_existing_filament_tare(sm, spoolman_fake_store):
    inventory.add_spools(sm, [item(tare=213)], RULES, dry=False)
    n = len(spoolman_fake_store["spools"])
    # item tare 100 would allow gross 150, but the existing filament's tare (213) will be used
    with pytest.raises(ValueError):
        inventory.add_spools(sm, [item(tare=100, sealed=False, gross=150)], RULES, dry=False)
    assert len(spoolman_fake_store["spools"]) == n


def test_link_tag_is_serialized(sm, monkeypatch):
    a, b = _spool(sm), _spool(sm)
    real_patch = sm.patch

    def patch(path, body):
        time.sleep(0.3)
        return real_patch(path, body)

    monkeypatch.setattr(sm, "patch", patch)
    outcomes = []
    barrier = threading.Barrier(2)

    def go(sid):
        barrier.wait()
        try:
            inventory.link_tag(sm, sid, UID, force=False, dry=False)
            outcomes.append("ok")
        except inventory.TagConflict:
            outcomes.append("conflict")

    ts = [threading.Thread(target=go, args=(s["id"],)) for s in (a, b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(outcomes) == ["conflict", "ok"]


def test_tag_conflict_reason_for_spool_with_other_tag(sm):
    a = _spool(sm)
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)
    with pytest.raises(inventory.TagConflict) as e:
        inventory.link_tag(sm, a["id"], UID2, force=False, dry=False)
    assert e.value.other is None and e.value.reason == "spool_has_other_tag"


def test_open_spool_petg_gets_lowest_free_box(sm):
    taken = _spool(sm, material="PETG", name="P1", sealed=False)
    assert taken["location"] == "Storage box 01"
    s = _spool(sm, material="PETG", name="P2")
    assert s["location"] == "Sealed stock"
    out = inventory.open_spool(sm, s["id"], UID, RULES, gross=500, dry=False)
    assert out["location"] == "Storage box 02" and tags.stored(out) == UID
    assert out["first_used"] and out["comment"] in (None, "") and out["remaining_weight"] == 287


def test_open_spool_pla_goes_to_rack_and_explicit_location_wins(sm):
    s = _spool(sm)
    out = inventory.open_spool(sm, s["id"], UID, RULES, dry=False)
    assert out["location"] == "Rack 1"
    s2 = _spool(sm, name="P3", material="PETG")
    out = inventory.open_spool(sm, s2["id"], UID2, RULES, location="Dry box", dry=False)
    assert out["location"] == "Dry box"


def test_open_spool_dry_and_conflict_and_low_gross(sm):
    s, t = _spool(sm, material="PETG", name="Q"), _spool(sm, material="PETG", name="R")
    dry = inventory.open_spool(sm, s["id"], UID, RULES, dry=True)
    assert dry["location"] == "Storage box 01"
    assert sm.get(f"spool/{s['id']}")["location"] == "Sealed stock"
    inventory.open_spool(sm, s["id"], UID, RULES, dry=False)
    with pytest.raises(inventory.TagConflict):
        inventory.open_spool(sm, t["id"], UID, RULES, dry=False)
    assert sm.get(f"spool/{t['id']}")["location"] == "Sealed stock"
    with pytest.raises(ValueError):
        inventory.open_spool(sm, t["id"], UID2, RULES, gross=10, dry=False)


def test_concurrent_open_spool_distinct_boxes(sm, monkeypatch):
    a = _spool(sm, material="PETG", name="A1")
    b = _spool(sm, material="PETG", name="B1")
    real_patch = sm.patch

    def patch(path, body):
        time.sleep(0.3)
        return real_patch(path, body)

    monkeypatch.setattr(sm, "patch", patch)
    barrier = threading.Barrier(2)

    def go(sid, uid):
        barrier.wait()
        inventory.open_spool(sm, sid, uid, RULES, dry=False)

    ts = [threading.Thread(target=go, args=(a["id"], UID)), threading.Thread(target=go, args=(b["id"], UID2))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    locs = {sm.get(f"spool/{i}")["location"] for i in (a["id"], b["id"])}
    assert locs == {"Storage box 01", "Storage box 02"}


def test_add_and_link_tag_not_landing_reports_created_spool(sm, monkeypatch):
    real_get = sm.get

    def get(path):
        out = real_get(path)
        if path.startswith("spool/") and isinstance(out, dict):
            out["extra"] = {}
        return out

    monkeypatch.setattr(sm, "get", get)
    with pytest.raises(inventory.AddFailed, match="tag did not land") as e:
        inventory.add_and_link(sm, [item(sealed=False)], RULES, dry=False, uid=UID)
    assert len(e.value.partial.spool_ids) == 1


def test_add_and_link_spoolman_error_while_linking_reports_created_spool(sm, monkeypatch):
    def patch(path, body):
        raise SpoolmanError("down", status=None)

    monkeypatch.setattr(sm, "patch", patch)
    with pytest.raises(inventory.AddFailed) as e:
        inventory.add_and_link(sm, [item(sealed=False)], RULES, dry=False, uid=UID)
    assert len(e.value.partial.spool_ids) == 1


# ---------- Task 7b: product lines on add ----------

from filament_kit import config  # noqa: E402
from filament_kit.profiles import builds, errors as profile_errors, lines as lines_mod  # noqa: E402


def _request_file():
    return config.paths().state / "profiles" / "rebuild-request"


def _hf(**kw):
    return item(**{"vendor": "ELEGOO", "name": "PETG HF Black", "material": "PETG", "tare": 154,
                   "line": "PETG HF", "bambu_parent": "Generic PETG", **kw})


def test_add_with_line_writes_extra_line_and_creates_line(sm, spoolman_fake_store):
    inventory.add_and_link(sm, [_hf()], RULES, dry=False, uid=None)
    (f,) = spoolman_fake_store["filaments"].values()
    assert f["extra"]["line"] == "\"PETG HF\""
    line = lines_mod.load()["elegoo--petg-hf"]
    assert (line.bambu_parent, line.parent_source) == ("Generic PETG", "user")
    req = json.loads(_request_file().read_text(encoding="utf-8"))
    assert req["reason"] == "intake"


def test_add_dry_run_writes_no_line_and_no_request(sm, spoolman_fake_store):
    inventory.add_and_link(sm, [_hf()], RULES, dry=True, uid=None)
    assert lines_mod.load() == {}
    assert not _request_file().exists()
    assert spoolman_fake_store["filaments"] == {}


def test_add_without_line_derives_one(sm):
    inventory.add_and_link(sm, [item(name="PLA+ 2.0 Grey")], RULES, dry=False, uid=None)
    line = lines_mod.load()["sunlu--pla-plus-2-0"]
    assert line.parent_source == "library"


@pytest.mark.parametrize("bad", [{"bambu_parent": "X @BBL H2D"}, {"bambu_parent": "x" * 101},
                                 {"line": "PETG @HF"}, {"line": "y" * 101}, {"bambu_parent": 5}])
def test_line_and_parent_validated(sm, spoolman_fake_store, bad):
    with pytest.raises(ValueError):
        inventory.add_and_link(sm, [item(**bad)], RULES, dry=False, uid=None)
    assert spoolman_fake_store["spools"] == {}


def test_line_failure_never_fails_the_add(sm, spoolman_fake_store, monkeypatch, caplog):
    def boom(*a, **k):
        raise lines_mod.LineStoreError("lines.json is unusable")

    monkeypatch.setattr(lines_mod, "load", boom)
    r = inventory.add_and_link(sm, [_hf()], RULES, dry=False, uid=None)
    assert len(r.spool_ids) == 1
    assert "lines.json is unusable" in caplog.text


def _upload_store():
    import io

    import test_builds as TB
    TB.pair("a")
    from filament_kit.profiles import builds
    builds.store_upload("system", io.BytesIO(TB.system_zip()), device_id="a")


def test_unknown_parent_with_store_is_refused(sm, spoolman_fake_store):
    _upload_store()
    for dry in (True, False):
        with pytest.raises(profile_errors.ProfileError) as e:
            inventory.add_and_link(sm, [_hf(bambu_parent="No Such Preset")], RULES, dry=dry, uid=None)
        assert (e.value.status, e.value.code) == (400, "unknown_parent")
    assert spoolman_fake_store["spools"] == {} and spoolman_fake_store["filaments"] == {}


def test_known_parent_with_store_is_accepted(sm):
    _upload_store()
    store = builds.system_store()
    parent = next(n for n in sorted(store.bases()) if lines_mod.usable(store, n))
    inventory.add_and_link(sm, [_hf(bambu_parent=parent)], RULES, dry=False, uid=None)
    assert lines_mod.load()["elegoo--petg-hf"].bambu_parent == parent


def test_no_store_any_parent_accepted(sm):
    assert builds.system_store() is None
    inventory.add_and_link(sm, [_hf(bambu_parent="Typo Preset")], RULES, dry=False, uid=None)


# ---------- Task 7c: one store definition, edited lines on existing filaments, lines after a failed link ----------

def test_inventory_has_no_own_store_or_parent_check():
    import inspect

    from filament_kit import intake
    assert not hasattr(inventory, "system_store") and not hasattr(inventory, "check_parent")
    assert not hasattr(inventory, "UnknownParent")
    assert "inventory" not in inspect.getsource(intake).split("log = ")[0]


def test_system_folder_without_hash_is_no_store(sm):
    """Same definition as the profiles API: a store is uploaded only when meta.json has a system_hash."""
    import test_generate as TG
    folder = config.paths().state / "profiles" / "live" / "system"
    folder.mkdir(parents=True)
    for n, cfg in TG.presets().items():
        (folder / f"{n}.json").write_text(json.dumps(cfg), encoding="utf-8")
    inventory.add_and_link(sm, [_hf(bambu_parent="Typo Preset")], RULES, dry=False, uid=None)
    assert lines_mod.load()["elegoo--petg-hf"].bambu_parent == "Typo Preset"


def _existing(spoolman_fake_store, sm, line=None):
    inventory.add_and_link(sm, [_hf(line=line, bambu_parent=None)], RULES, dry=False, uid=None)
    (f,) = spoolman_fake_store["filaments"].values()
    return f


def test_edited_line_on_existing_filament_sets_its_extra_line(sm, spoolman_fake_store):
    f = _existing(spoolman_fake_store, sm, line=None)
    assert "line" not in f["extra"]
    r = inventory.add_and_link(sm, [_hf(line="PETG High Flow", bambu_parent=None)], RULES, dry=False, uid=None)
    assert json.loads(f["extra"]["line"]) == "PETG High Flow"
    assert any(f"F{f['id']}" in ln and "line set to PETG High Flow" in ln for ln in r.lines)
    assert "elegoo--petg-high-flow" in lines_mod.load()
    assert len(spoolman_fake_store["filaments"]) == 1 and len(spoolman_fake_store["spools"]) == 2


def test_edited_line_replaces_a_different_extra_line(sm, spoolman_fake_store):
    f = _existing(spoolman_fake_store, sm, line="PETG HF")
    f["extra"]["nozzle_range"] = json.dumps("230-260")
    inventory.add_and_link(sm, [_hf(line="PETG HF Pro", bambu_parent=None)], RULES, dry=False, uid=None)
    assert json.loads(f["extra"]["line"]) == "PETG HF Pro"
    assert json.loads(f["extra"]["nozzle_range"]) == "230-260"      # other extra fields are kept


def test_same_line_on_existing_filament_writes_nothing(sm, spoolman_fake_store):
    f = _existing(spoolman_fake_store, sm, line="PETG HF")
    before = json.dumps(f, sort_keys=True)
    r = inventory.add_and_link(sm, [_hf(line="petg hf", bambu_parent=None)], RULES, dry=False, uid=None)
    assert json.dumps(f, sort_keys=True) == before
    assert not any("line set to" in ln for ln in r.lines)


def test_derived_line_on_existing_filament_writes_nothing(sm, spoolman_fake_store):
    """The read proposes the derived line for an existing filament without extra.line: sending it back unedited
    must not pin the filament."""
    inventory.add_and_link(sm, [item(name="PLA+ 2.0 Grey")], RULES, dry=False, uid=None)
    (f,) = spoolman_fake_store["filaments"].values()
    inventory.add_and_link(sm, [item(name="PLA+ 2.0 Grey", line="PLA+ 2.0")], RULES, dry=False, uid=None)
    assert "line" not in f["extra"]


def test_edited_line_dry_run_only_reports(sm, spoolman_fake_store):
    f = _existing(spoolman_fake_store, sm, line=None)
    r = inventory.add_and_link(sm, [_hf(line="PETG High Flow", bambu_parent=None)], RULES, dry=True, uid=None)
    assert "line" not in f["extra"]
    assert any("would set line to PETG High Flow" in ln for ln in r.lines)


def test_lines_recorded_when_the_tag_link_fails(sm, spoolman_fake_store, monkeypatch):
    def patch(path, body):
        raise SpoolmanError("down", status=None)

    monkeypatch.setattr(sm, "patch", patch)
    with pytest.raises(inventory.AddFailed) as e:
        inventory.add_and_link(sm, [_hf(sealed=False)], RULES, dry=False, uid=UID)
    assert len(e.value.partial.spool_ids) == 1
    line = lines_mod.load()["elegoo--petg-hf"]
    assert line.bambu_parent == "Generic PETG"
    assert json.loads(_request_file().read_text(encoding="utf-8"))["reason"] == "intake"


def test_lines_recorded_only_for_items_added_before_spoolman_failed(sm, spoolman_fake_store, monkeypatch):
    real_post = sm.post
    spools = []

    def post(path, body):
        if path == "spool":
            spools.append(body)
            if len(spools) == 2:
                raise SpoolmanError("down", status=None)
        return real_post(path, body)

    monkeypatch.setattr(sm, "post", post)
    second = item(vendor="ACME", name="PLA Matte Red", material="PLA", line="PLA Matte")
    with pytest.raises(inventory.AddFailed) as e:
        inventory.add_and_link(sm, [_hf(), second], RULES, dry=False, uid=None)
    assert len(e.value.partial.spool_ids) == 1
    ls = lines_mod.load()
    assert "elegoo--petg-hf" in ls and "acme--pla-matte" not in ls


# ---------- final review I6: an intake add never blocks spool loads during a build ----------

def test_add_never_holds_the_inventory_lock_while_a_build_holds_its_locks(sm, spoolman_fake_store):
    """The build service holds live.lock and the lines lock for the whole build; a spool load (bridge loading)
    needs inventory._LOCK. An add checks parents before taking _LOCK and records lines after releasing it, so
    _LOCK stays free and the spools are added while the build runs."""
    _upload_store()
    store = builds.system_store()
    parent = next(n for n in sorted(store.bases()) if lines_mod.usable(store, n))
    held, release = threading.Event(), threading.Event()

    def the_build():
        with builds._locked("live.lock"), lines_mod.locked():
            held.set()
            release.wait(20)

    b = threading.Thread(target=the_build, daemon=True)
    b.start()
    assert held.wait(5)
    errs = []

    def the_add():
        try:
            inventory.add_and_link(sm, [_hf(bambu_parent=parent)], RULES, dry=False, uid=None)
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    a = threading.Thread(target=the_add, daemon=True)
    try:
        a.start()
        deadline = time.time() + 5
        while not spoolman_fake_store["spools"] and time.time() < deadline:
            time.sleep(0.02)
        assert spoolman_fake_store["spools"], "the add's inventory phase did not finish while the build ran"
        for _ in range(10):                                     # a spool load could take the lock meanwhile
            assert inventory._LOCK.acquire(timeout=1), "inventory._LOCK held while waiting for build locks"
            inventory._LOCK.release()
            time.sleep(0.02)
        assert a.is_alive()                                     # still waiting to record its line
    finally:
        release.set()
        b.join(5)
        a.join(10)
    assert not errs, errs
    assert lines_mod.load()["elegoo--petg-hf"].bambu_parent == parent


def test_system_store_cache_hit_needs_no_live_lock():
    _upload_store()
    first = builds.system_store()
    got = []
    held, release = threading.Event(), threading.Event()

    def holder():
        with builds._locked("live.lock"):
            held.set()
            release.wait(10)

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert held.wait(5)
    r = threading.Thread(target=lambda: got.append(builds.system_store()), daemon=True)
    r.start()
    r.join(2)
    quick = list(got)                                           # before live.lock is released
    release.set()
    t.join(5)
    r.join(5)
    assert quick and quick[0] is first


# ---------- merge-ops: open_spool humidity/remaining, pick by filament, one-byte-apart tags ----------

def test_open_spool_humidity_and_remaining(sm):
    s = _spool(sm, material="PETG", name="H1")
    out = inventory.open_spool(sm, s["id"], UID, RULES, humidity=38.5, remaining=640, dry=False)
    ex = out["extra"]
    assert json.loads(ex["box_humidity"]) == 38.5
    checked = json.loads(ex["humidity_checked"])
    assert checked.endswith("Z") and checked[:4].isdigit()
    assert tags.stored(out) == UID                      # the tag patch is kept beside the humidity fields
    assert out["remaining_weight"] == 640


def test_open_spool_humidity_dry_run_writes_nothing(sm):
    s = _spool(sm, material="PETG", name="H2")
    dry = inventory.open_spool(sm, s["id"], UID, RULES, humidity=40, dry=True)
    assert json.loads(dry["extra"]["box_humidity"]) == 40
    assert "box_humidity" not in (sm.get(f"spool/{s['id']}").get("extra") or {})


def test_open_spool_gross_and_remaining_conflict_and_negative(sm):
    s = _spool(sm, material="PETG", name="H3")
    with pytest.raises(ValueError):
        inventory.open_spool(sm, s["id"], UID, RULES, gross=900, remaining=600, dry=False)
    with pytest.raises(ValueError):
        inventory.open_spool(sm, s["id"], UID, RULES, remaining=-1, dry=False)
    for bad in (True, "40", 101):
        with pytest.raises(ValueError):
            inventory.open_spool(sm, s["id"], UID, RULES, humidity=bad, dry=False)
    for bad in (True, "600", [1]):                          # remaining must be a number too
        with pytest.raises(ValueError, match="remaining"):
            inventory.open_spool(sm, s["id"], UID, RULES, remaining=bad, dry=False)
    assert tags.stored(sm.get(f"spool/{s['id']}")) is None   # refused before linking


def test_pick_sealed_lowest_id_sealed_spool(sm):
    r = inventory.add_spools(sm, [item(name="Pick", count=3)], RULES, dry=False)
    a, b, c = r.spool_ids
    fid = sm.get(f"spool/{a}")["filament"]["id"]
    inventory.open_spool(sm, a, UID, RULES, dry=False)       # a is opened: no longer sealed
    assert inventory.pick_sealed(sm, fid) == b
    assert inventory.pick_sealed(sm, 9999) is None
    inventory.open_spool(sm, b, UID2, RULES, dry=False)
    inventory.open_spool(sm, c, "4:77:91:e:9:22:89", RULES, dry=False)
    assert inventory.pick_sealed(sm, fid) is None


def test_tag_neighbours_one_byte_apart(sm):
    a, b, c = (_spool(sm, name=n) for n in ("N1", "N2", "N3"))
    inventory.link_tag(sm, a["id"], UID, force=False, dry=False)               # 4:77:90:e:9:22:89
    inventory.link_tag(sm, b["id"], "4:77:90:e:9:22:8a", force=False, dry=False)  # last byte differs
    inventory.link_tag(sm, c["id"], "4:78:91:e:9:22:89", force=False, dry=False)  # two bytes differ
    assert inventory.tag_neighbours(sm, UID2) == [a["id"]]                     # 4:77:8f:... vs 4:77:90:...
    assert sorted(inventory.tag_neighbours(sm, "04:77:90:0E:09:22:8B")) == [a["id"], b["id"]]
    assert inventory.tag_neighbours(sm, UID) == [b["id"]]                      # its own spool is not a neighbour
