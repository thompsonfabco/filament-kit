"""Per-field Label Reader confidence, the record summary, and the engine that read it (design S2.6, N4): in the
read reply, stored with each Recently added record, and absent (not broken) on a record kept before they existed."""
from __future__ import annotations

import copy
import json

import pytest
from fakes import local_reader_fake as lrf
from fakes.claude_fake import FakeClaude

from filament_kit import config, intake, intake_history, inventory, local_reader, pairing, read_confidence
from filament_kit.spoolman import Spoolman
from test_intake_history import ITEM, JPEG, READ, RULES

BOTH = {"spoolman": True, "server": True, "ai_intake": True, "local_intake": True}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    (tmp_path / "etc" / "anthropic_key").write_text("sk-test\n")
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})
    monkeypatch.setattr(local_reader, "CONNECT_TIMEOUT", 0.5)


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def save(sm, read_id=None):
    it = {k: v for k, v in ITEM.items() if k not in ("photos", "existing_filament_id", "estimates", "sealed_reason")}
    r = inventory.add_and_link(sm, [it], RULES, False, None)
    return intake_history.record_save(r.saved, source="phone", device="t", read_id=read_id)


# ---------------------------------------------------------------- the rule

def test_levels_rule_per_engine():
    cloud = {**ITEM, "price_per_kg": None, "estimates": ["tare"]}
    lv = read_confidence.levels(cloud)
    assert lv["vendor"] is None and lv["tare"] == "medium" and lv["price_per_kg"] == "not_on_label"
    assert "line" not in lv and "high" not in lv.values() and "low" not in lv.values()
    assert not read_confidence.rated([cloud]) and read_confidence.filled(cloud) == ["tare"]
    local = {**ITEM, "confidence": 0.9, "field_confidence": {"vendor": 0.95, "name": 0.6, "material": 0.2}}
    lv = read_confidence.levels(local)
    assert (lv["vendor"], lv["name"], lv["material"], lv["net"]) == ("high", "medium", "low", "high")
    assert read_confidence.rated([local])
    assert read_confidence.levels({**ITEM, "vendor": "Unknown"})["vendor"] == "not_on_label"


def test_summary_names_the_lowest_level_first():
    assert read_confidence.summary([]) is None and read_confidence.summary([None]) is None
    assert read_confidence.summary([{"vendor": "high"}])["level"] == "high"
    s = read_confidence.summary([{"name": "medium", "net": "low"}, {"net": "low", "bed": "not_on_label"}])
    assert s == {"level": "low", "low": ["net"], "medium": ["name"], "not_on_label": ["bed"]}
    s = read_confidence.summary([{"vendor": None, "name": "medium", "bed": "not_on_label"}])
    assert s == {"level": "not_rated", "low": [], "medium": ["name"], "not_on_label": ["bed"]}


# ---------------------------------------------------------------- the read reply

def test_a_cloud_read_has_levels_summary_and_engine(sm):
    reply = copy.deepcopy(READ)
    reply["items"][0]["estimates"] = ["density"]
    out = intake.read_labels(sm, [JPEG], "", None, client=FakeClaude(reply))
    it = out["items"][0]
    lv = it["confidence_levels"]
    assert lv["density"] == "medium" and it["confidence_filled"] == ["density"]
    assert all(v is None for k, v in lv.items() if k not in ("density", "price_per_kg"))   # filled: no level
    assert lv["price_per_kg"] == "not_on_label"                                         # empty: not on the label
    assert out["confidence_rated"] is False and "high" not in lv.values()
    assert out["confidence_summary"]["level"] == "not_rated" and out["confidence_summary"]["medium"] == ["density"]
    assert out["engine"]["reader"] == "cloud" and out["engine"]["model"] == out["usage"]["model"]
    assert out["engine"]["tier"] is None
    assert out["reader"] == "cloud" and out["usage"] and "items" in out        # existing fields stay


def test_a_local_read_gives_its_own_numbers_and_tier(sm, fake_reader):
    url, data = fake_reader
    cfg = config.load()
    cfg["modules"] = dict(BOTH)
    cfg["local_intake"] = {"url": url, "tier": "auto"}
    cfg["intake"] = {"reader": "local"}
    config.save(cfg)
    data["read"] = {**lrf.reply(), "items": [{**lrf.ITEM, "confidence": 0.93,
                                              "field_confidence": {"vendor": 0.97, "material": 0.3}}]}
    out = intake.read_labels(sm, [JPEG], "", None, None)
    assert out["confidence_rated"] is True and out["items"][0]["confidence_filled"] == []
    assert out["items"][0]["confidence_levels"]["material"] == "low"
    assert out["confidence_summary"]["level"] == "low" and out["confidence_summary"]["low"] == ["material"]
    assert out["engine"] == {"reader": "local", "model": out["usage"]["model"], "tier": "cpu"}
    assert out["tier"] == "cpu" and out["confidence"] == 0.93                    # existing fields stay


# ---------------------------------------------------------------- the record

def test_a_record_keeps_levels_summary_and_engine_and_the_count(sm):
    reply = copy.deepcopy(READ)
    reply["items"][0]["estimates"] = ["tare"]
    out = intake.read_labels(sm, [JPEG], "", None, client=FakeClaude(reply))
    hid = save(sm, out["read_id"])
    rec = intake_history.get(hid)
    assert rec["read"]["items"][0]["confidence_levels"]["tare"] == "medium"
    assert rec["read"]["items"][0]["confidence_filled"] == ["tare"]
    assert rec["read"]["engine"]["reader"] == "cloud" and rec["read"]["confidence_rated"] is False
    assert rec["confidence"]["level"] == "not_rated" and rec["confidence_rated"] is False and rec["engine"]["model"]
    listed = intake_history.list_records(True)
    assert listed["count"] == 1 and listed["records"][0]["confidence"] == rec["confidence"]
    assert listed["records"][0]["engine"] == rec["engine"] and rec["read"]["items"][0]["vendor"] == "SUNLU"


def test_a_record_by_hand_has_no_confidence(sm):
    rec = intake_history.get(save(sm))
    assert rec["read"] is None and rec["confidence"] is None and rec["engine"] is None


def test_an_old_record_without_the_new_fields_still_reads(sm):
    out = intake.read_labels(sm, [JPEG], "", None, client=FakeClaude(copy.deepcopy(READ)))
    hid = save(sm, out["read_id"])
    p = intake_history._dir(hid) / "record.json"
    rec = json.loads(p.read_text())
    rec["read"].pop("engine")
    for it in rec["read"]["items"]:
        it.pop("confidence_levels", None)
        it.pop("confidence", None)
    p.write_text(json.dumps(rec))
    got = intake_history.get(hid)
    assert got["confidence"] is None and got["engine"] is None
    assert got["read"]["items"][0]["vendor"] == "SUNLU" and got["photos"] == 1
    assert intake_history.list_records(True)["count"] == 1


def test_an_old_cloud_record_with_high_levels_is_not_rated(sm):
    """A record kept by the first S2.6 build: Cloud levels "high", no `confidence_rated`."""
    out = intake.read_labels(sm, [JPEG], "", None, client=FakeClaude(copy.deepcopy(READ)))
    hid = save(sm, out["read_id"])
    p = intake_history._dir(hid) / "record.json"
    rec = json.loads(p.read_text())
    rec["read"].pop("confidence_rated")
    rec["read"]["items"][0]["confidence_levels"] = {**{k: "high" for k in read_confidence.READ_FIELDS},
                                                    "price_per_kg": "not_on_label"}
    p.write_text(json.dumps(rec))
    got = intake_history.get(hid)
    assert got["confidence_rated"] is False and got["confidence"]["level"] == "not_rated"
    assert got["confidence"]["not_on_label"] == ["price_per_kg"]
