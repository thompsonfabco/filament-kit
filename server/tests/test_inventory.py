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
from filament_kit.profiles import errors as profile_errors, lines as lines_mod  # noqa: E402


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
    store = inventory.system_store()
    parent = next(n for n in sorted(store.bases()) if lines_mod._usable(store, n))
    inventory.add_and_link(sm, [_hf(bambu_parent=parent)], RULES, dry=False, uid=None)
    assert lines_mod.load()["elegoo--petg-hf"].bambu_parent == parent


def test_no_store_any_parent_accepted(sm):
    assert inventory.system_store() is None
    inventory.add_and_link(sm, [_hf(bambu_parent="Typo Preset")], RULES, dry=False, uid=None)
