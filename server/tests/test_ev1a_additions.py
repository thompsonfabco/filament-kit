"""Brief 18: a spool move that asks for the placement rule (`auto_location`), and a 400 `invalid_entry` that keeps its
`problems` through the web unit's kit client."""
import io
import urllib.error

import pytest

from filament_kit import inventory
from filament_kit.web import slots
from test_inventory import RULES, _spool, sm  # noqa: F401  (fixture)


def test_auto_location_places_an_opened_spool_by_the_rule_and_says_why(sm):
    s = _spool(sm)
    inventory.link_tag(sm, s["id"], "a:b:c:d:e:f:1", force=False, dry=False)
    sm.patch(f"spool/{s['id']}", {"location": "Somewhere odd"})
    out = inventory.edit_spool(sm, s["id"], auto_location=True, dry=False, rules=RULES)
    assert out["spool"]["location"] == "Rack 1" and out["view"]["location"] == "Rack 1"
    assert out["placed_by"] == "material" and out["placed_text"] == "the first place for PLA with room"
    assert out["before"]["location"] == "Somewhere odd" and sm.get(f"spool/{s['id']}")["location"] == "Rack 1"


def test_auto_location_puts_a_sealed_spool_where_sealed_spools_go(sm):
    s = _spool(sm)
    sm.patch(f"spool/{s['id']}", {"location": "Somewhere odd"})
    out = inventory.edit_spool(sm, s["id"], auto_location=True, dry=False, rules=RULES)
    assert out["spool"]["location"] == "Sealed stock" and out["placed_by"] == "sealed"


def test_a_dry_auto_location_changes_nothing(sm):
    s = _spool(sm)
    sm.patch(f"spool/{s['id']}", {"location": "Somewhere odd"})
    out = inventory.edit_spool(sm, s["id"], auto_location=True, dry=True, rules=RULES)
    assert out["spool"]["location"] == "Sealed stock" and out["dry"] is True
    assert sm.get(f"spool/{s['id']}")["location"] == "Somewhere odd"


def test_an_explicit_location_wins_and_false_or_missing_is_ignored(sm):
    s = _spool(sm)
    out = inventory.edit_spool(sm, s["id"], auto_location=True, location="Shelf 9", dry=False, rules=RULES)
    assert out["spool"]["location"] == "Shelf 9" and "placed_by" not in out
    for kw in ({}, {"auto_location": False}):
        out = inventory.edit_spool(sm, s["id"], dry=False, rules=RULES, **kw)
        assert out["spool"]["location"] == "Shelf 9" and "placed_by" not in out
    out = inventory.edit_spool(sm, s["id"], auto_location=False, location="Shelf 2", dry=False, rules=RULES)
    assert out["spool"]["location"] == "Shelf 2"


def test_auto_location_without_a_rule_is_refused(sm):
    s = _spool(sm)
    with pytest.raises(inventory.SpoolEditError):
        inventory.edit_spool(sm, s["id"], auto_location=True, dry=False)


def _kit(monkeypatch, code, body):
    def fail(req, timeout, context=None):
        raise urllib.error.HTTPError("https://kit", code, "bad", {}, io.BytesIO(body))
    monkeypatch.setattr(slots, "_http_json", fail)
    api = slots.KitApi(base_url="http://kit.invalid")
    monkeypatch.setattr(api, "_token", lambda: "t")
    return api


def test_kit_client_keeps_problems_of_an_invalid_entry(monkeypatch):
    body = (b'{"error": "invalid_entry", "message": "x", "problems": [{"field": "brand", "text": "required"}]}')
    with pytest.raises(slots.SlotError) as e:
        _kit(monkeypatch, 400, body).post("/api/library/local/form", {})
    assert e.value.code == "invalid_entry" and e.value.http == 400
    assert e.value.problems == [{"field": "brand", "text": "required"}]
    assert e.value.body["error"] == "invalid_entry"


def test_other_errors_carry_no_problems(monkeypatch):
    with pytest.raises(slots.SlotError) as e:
        _kit(monkeypatch, 404, b'{"error": "not_found", "problems": [1]}').get("/api/x")
    assert e.value.problems is None and e.value.body is None
