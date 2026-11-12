"""The intake history (intake_history.py): records from saves, photos from reads, revisions, undo, retention."""
import copy
import json

import pytest
from fakes.claude_fake import FakeClaude
from starlette.testclient import TestClient

from filament_kit import config, intake_history, inventory, pairing
from filament_kit.api import create_app
from filament_kit.intake import read_labels
from filament_kit.spoolman import Spoolman

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
JPEG2 = b"\xff\xd8\xff\xe0" + b"y" * 120
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}
ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA",
        "color_hex": "8A8C8E", "net": 1000, "tare": 213, "density": 1.24, "count": 1, "nozzle": 220, "bed": 55,
        "nozzle_range": "200-230", "bed_range": "50-60", "lot": None, "note": "label", "estimates": [],
        "sealed": True, "sealed_reason": "bag"}
READ = {"questions": [], "items": [ITEM]}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    (tmp_path / "etc" / "anthropic_key").write_text("sk-test\n")
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def add(sm, it=None, read_id=None, source="phone", count=1):
    it = {k: v for k, v in (it or ITEM).items() if k not in ("photos", "existing_filament_id", "estimates",
                                                             "sealed_reason")}
    it["count"] = count
    r = inventory.add_and_link(sm, [it], RULES, False, None)
    return r, intake_history.record_save(r.saved, source=source, device="test phone", read_id=read_id)


def read(sm, images=(JPEG, JPEG2), reply=READ):
    return read_labels(sm, list(images), "", None, client=FakeClaude(copy.deepcopy(reply)))


# ---------------------------------------------------------------- records

def test_a_save_after_a_read_keeps_its_photos_and_what_the_ai_read(sm):
    out = read(sm)
    rid = out["read_id"]
    assert (config.paths().state / "intake-history" / "pending" / rid / "photo2.jpg").is_file()
    r, hid = add(sm, read_id=rid)
    rec = intake_history.get(hid)
    assert rec["source"] == "phone" and rec["state"] == "detected" and rec["photos"] == 2
    assert intake_history.photo(hid, 1) == JPEG and intake_history.photo(hid, 2) == JPEG2
    assert rec["read"]["items"][0]["vendor"] == "SUNLU" and rec["device"] == "test phone"
    assert rec["saved"][0]["spool_ids"] == r.spool_ids and rec["saved"][0]["filament_id"]
    assert rec["spools"][0]["name"] == "PLA+ Grey"
    assert not (config.paths().state / "intake-history" / "pending" / rid).exists()


def test_a_save_by_hand_is_a_record_with_no_photo(sm):
    _, hid = add(sm)
    rec = intake_history.get(hid)
    assert rec["photos"] == 0 and rec["read"] is None
    with pytest.raises(intake_history.HistoryError):
        intake_history.photo(hid, 1)


def test_retention_keeps_the_newest_and_deletes_old_photos(sm):
    config.save({"placement": {"box_count": 2}, "intake": {"history_keep": 2}})
    ids = []
    for _ in range(3):
        ids.append(add(sm, read_id=read(sm)["read_id"])[1])
    listed = intake_history.list_records(True)
    assert [x["id"] for x in listed["records"]] == [ids[2], ids[1]] and listed["keep"] == 2
    assert not (config.paths().state / "intake-history" / ids[0]).exists()
    assert listed["photo_bytes"] == 2 * (len(JPEG) + len(JPEG2))


def test_retention_zero_keeps_nothing_not_even_the_read(sm):
    config.save({"placement": {"box_count": 2}, "intake": {"history_keep": 0}})
    rid = read(sm)["read_id"]
    assert not (config.paths().state / "intake-history" / "pending" / rid).exists()
    assert add(sm, read_id=rid)[1] is None and intake_history.list_records(True)["count"] == 0


# ---------------------------------------------------------------- revisions

def test_a_wrong_brand_relinks_the_spool_and_reports_the_orphan(sm, spoolman_fake_store):
    r, hid = add(sm)
    sid = r.spool_ids[0]
    sm.patch(f"spool/{sid}", {"location": "Shelf 3", "remaining_weight": 700,
                              "extra": {"nfc_id": json.dumps("04aabbccddeeff")}})
    old_fid = sm.get(f"spool/{sid}")["filament"]["id"]
    rec = intake_history.apply(sm, hid, item=0, values={"vendor": "Polymaker", "nozzle": 215})
    rev = rec["revisions"][-1]
    s = sm.get(f"spool/{sid}")
    assert s["filament"]["vendor"]["name"] == "Polymaker" and s["filament"]["settings_extruder_temp"] == 215
    assert s["location"] == "Shelf 3" and s["remaining_weight"] == 700
    assert json.loads(s["extra"]["nfc_id"]) == "04aabbccddeeff"
    assert rev["filaments"] == {"from": old_fid, "to": s["filament"]["id"], "created": True, "edited": {},
                                "orphaned": [old_fid]}
    assert old_fid in {f["id"] for f in sm.get("filament")}                  # reported, never deleted
    assert rec["state"] == "edited" and rec["saved"][0]["values"]["vendor"] == "Polymaker"


def test_a_shared_filament_is_never_edited(sm):
    _, other = add(sm)          # another spool of the same filament, from another intake
    r, hid = add(sm)
    shared = sm.get(f"spool/{r.spool_ids[0]}")["filament"]["id"]
    intake_history.apply(sm, hid, item=0, values={"nozzle": 230})
    f = sm.get(f"filament/{shared}")
    assert f["settings_extruder_temp"] == 220                                 # the other spool's filament as it was
    assert sm.get(f"spool/{r.spool_ids[0]}")["filament"]["settings_extruder_temp"] == 230
    other_sid = intake_history.get(other)["saved"][0]["spool_ids"][0]
    assert sm.get(f"spool/{other_sid}")["filament"]["id"] == shared


def test_a_filament_only_this_intake_uses_is_edited_in_place_and_undone(sm):
    r, hid = add(sm, count=2)
    fid = sm.get(f"spool/{r.spool_ids[0]}")["filament"]["id"]
    rec = intake_history.apply(sm, hid, item=0, values={"nozzle": 230, "density": 1.25})
    assert rec["revisions"][-1]["filaments"]["to"] == fid
    assert sm.get(f"filament/{fid}")["settings_extruder_temp"] == 230
    rec = intake_history.undo(sm, hid, None)
    assert sm.get(f"filament/{fid}")["settings_extruder_temp"] == 220 and sm.get(f"filament/{fid}")["density"] == 1.24
    assert rec["state"] == "detected" and rec["revisions"][-1]["undone"] is True
    assert rec["saved"][0]["values"]["nozzle"] == 220


def test_apply_to_some_of_an_intakes_spools(sm):
    r, hid = add(sm, count=3)
    rec = intake_history.apply(sm, hid, item=0, values={"color_hex": "FF0000"}, spool_ids=[r.spool_ids[2]])
    fids = [sm.get(f"spool/{s}")["filament"]["id"] for s in r.spool_ids]
    assert fids[0] == fids[1] != fids[2] and rec["revisions"][-1]["spool_ids"] == [r.spool_ids[2]]


def test_undo_goes_back_one_revision_at_a_time(sm):
    r, hid = add(sm)
    sid = r.spool_ids[0]
    f0 = sm.get(f"spool/{sid}")["filament"]["id"]
    intake_history.apply(sm, hid, item=0, values={"vendor": "Polymaker"})
    intake_history.apply(sm, hid, item=0, values={"name": "PolyLite PLA Grey"})
    with pytest.raises(intake_history.HistoryError) as e:
        intake_history.undo(sm, hid, 1)
    assert e.value.code == "not_latest"
    intake_history.undo(sm, hid, 2)
    rec = intake_history.undo(sm, hid, 1)
    assert sm.get(f"spool/{sid}")["filament"]["id"] == f0 and rec["saved"][0]["values"]["vendor"] == "SUNLU"


@pytest.mark.parametrize("values, says", [({}, "at least one"), ({"colour": "x"}, "unknown field"),
                                          ({"nozzle": "hot"}, "whole number"), ({"color_hex": "red"}, "6 hex"),
                                          ({"net": -1}, "positive"), ({"vendor": ""}, "text")])
def test_bad_values_change_nothing(sm, values, says):
    r, hid = add(sm)
    with pytest.raises(intake_history.HistoryError) as e:
        intake_history.apply(sm, hid, item=0, values=values)
    assert e.value.status == 400 and says in str(e.value)
    assert intake_history.get(hid)["revisions"] == []


def test_ai_revision_proposes_then_applies_as_shown(sm):
    rid = read(sm)["read_id"]
    _, hid = add(sm, read_id=rid)
    fixed = copy.deepcopy(READ)
    fixed["items"][0].update(vendor="Polymaker", name="PolyLite PLA Grey", nozzle=215)
    fake = FakeClaude(fixed)
    p = intake_history.revise(sm, hid, "brand is Polymaker", client=fake)
    assert {"vendor", "name", "nozzle"} <= set(p["changes"]) and p["before"]["vendor"] == "SUNLU"
    assert p["after"]["vendor"] == "Polymaker" and p["no_photo"] is False
    sent = fake.calls[0]["messages"][0]["content"]
    assert sum(1 for c in sent if c.get("type") == "image") == 2
    assert any("brand is Polymaker" in (c.get("text") or "") for c in sent)
    assert intake_history.get(hid)["revisions"] == []                         # nothing written yet
    rec = intake_history.apply(sm, hid, proposal=p["proposal"])
    assert rec["state"] == "revised_ai" and rec["revisions"][-1]["note"] == "brand is Polymaker"
    with pytest.raises(intake_history.HistoryError):                          # used up with the revision
        intake_history.apply(sm, hid, proposal=p["proposal"])


def test_an_old_proposal_is_stale_after_another_change(sm):
    _, hid = add(sm, read_id=read(sm)["read_id"])
    fixed = copy.deepcopy(READ)
    fixed["items"][0]["vendor"] = "Polymaker"
    p = intake_history.revise(sm, hid, "brand is Polymaker", client=FakeClaude(fixed))
    rec = intake_history._load(hid)
    keep = rec["proposals"]
    intake_history.apply(sm, hid, item=0, values={"nozzle": 230})
    rec = intake_history._load(hid)
    rec["proposals"] = keep                                                   # as if still held
    intake_history._save(rec)
    with pytest.raises(intake_history.HistoryError) as e:
        intake_history.apply(sm, hid, proposal=p["proposal"])
    assert e.value.code == "stale"


def test_ai_off_refuses_a_revision():
    with pytest.raises(intake_history.HistoryError) as e:
        intake_history.revise(None, "0" * 12, "brand is X", ai_on=False)
    assert e.value.code == "ai_off"


# ---------------------------------------------------------------- the API and the command line

def _client(sm, claude=None):
    c = TestClient(create_app(sm=sm, claude=claude))
    c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue("Pixel").code)
    return c


def test_the_api_records_an_add_with_its_read_and_serves_history(sm):
    c = _client(sm, FakeClaude(copy.deepcopy(READ)))
    files = [("photo", ("a.jpg", JPEG, "image/jpeg"))]
    rid = c.post("/api/intake/read", files=files).json()["read_id"]
    it = {k: v for k, v in ITEM.items() if k not in ("photos", "existing_filament_id", "estimates", "sealed_reason")}
    r = c.post("/api/intake/add", json={"items": [it], "dry_run": False, "read_id": rid}).json()
    hid = r["history_id"]
    lst = c.get("/api/intake/history").json()
    assert lst["records"][0]["id"] == hid and lst["keep"] == 20
    full = c.get(f"/api/intake/history/{hid}").json()
    assert full["device"] == "Pixel" and full["photos"] == 1
    ph = c.get(f"/api/intake/history/{hid}/photos/1")
    assert ph.status_code == 200 and ph.headers["content-type"] == "image/jpeg" and ph.content == JPEG
    assert c.get(f"/api/intake/history/{hid}/photos/2").status_code == 404
    done = c.post(f"/api/intake/history/{hid}/apply", json={"item": 0, "values": {"nozzle": 230}}).json()
    assert done["state"] == "edited" and done["revisions"][0]["device"] == "Pixel"
    assert c.post(f"/api/intake/history/{hid}/undo", json={}).json()["state"] == "detected"
    assert c.post(f"/api/intake/history/{hid}/apply", json={"item": 0, "values": {"x": 1}}).json()["error"] \
        == "bad_request"
    assert c.get("/api/intake/history/zzz").status_code == 404
    dry = c.post("/api/intake/add", json={"items": [it], "dry_run": True}).json()
    assert "history_id" not in dry


def test_the_api_refuses_a_revision_when_ai_is_off(sm):
    config.save({"placement": {"box_count": 2}, "modules": {"server": True, "spoolman": True}})
    c = _client(sm)
    _, hid = add(sm)
    r = c.post(f"/api/intake/history/{hid}/revise", json={"note": "brand is X"})
    assert r.status_code == 409 and r.json()["error"] == "ai_off"
    assert c.get("/api/intake/history").json()["ai"] is False


def test_history_needs_a_token(sm):
    c = TestClient(create_app(sm=sm))
    assert c.get("/api/intake/history").status_code == 401


def test_cli_lists_records_with_their_photo_paths(sm, capsys, monkeypatch):
    from filament_kit import cli
    monkeypatch.setattr(cli, "Spoolman", lambda url: sm)
    _, hid = add(sm, read_id=read(sm)["read_id"])
    assert cli.main(["intake", "history"]) == 0
    out = capsys.readouterr().out
    assert hid in out and "photo1.jpg" in out and "SUNLU PLA+ Grey" in out
    assert cli.main(["intake", "edit", hid, "nozzle=230"]) == 0
    assert "nozzle 220 -> 230" in capsys.readouterr().out
    assert cli.main(["intake", "show", hid]) == 0
    assert "revision 1" in capsys.readouterr().out
    assert cli.main(["intake", "undo", hid]) == 0
    assert cli.main(["intake", "edit", hid, "nozzle"]) == 1


def test_a_corrected_brand_joins_the_filament_that_has_it_and_takes_its_values(sm):
    _, other = add(sm, it={**ITEM, "vendor": "Polymaker", "nozzle": 210, "density": 1.20})
    pf = sm.get(f"spool/{intake_history.get(other)['saved'][0]['spool_ids'][0]}")["filament"]["id"]
    r, hid = add(sm)
    rec = intake_history.apply(sm, hid, item=0, values={"vendor": "Polymaker"})
    assert sm.get(f"spool/{r.spool_ids[0]}")["filament"]["id"] == pf
    v = rec["saved"][0]["values"]
    assert v["nozzle"] == 210 and v["density"] == 1.20 and rec["revisions"][-1]["filaments"]["created"] is False


def test_the_intake_station_save_is_recorded_with_its_photo(sm, monkeypatch):
    from filament_kit import station_flow
    out = read(sm, images=(JPEG,))
    item = {k: v for k, v in ITEM.items() if k not in ("photos", "estimates")}
    item["read_id"] = out["read_id"]
    r = station_flow.save(sm, RULES, {"uid": "a:b:c:d:e:f:1", "gross_g": 1300, "filament": item, "dry_run": False})
    (s,) = intake_history.list_records(True)["records"]
    rec = intake_history.get(s["id"])
    assert rec["source"] == "station" and rec["photos"] == 1 and rec["weight"] == 1300
    assert rec["saved"][0]["spool_ids"] == [r["spool_id"]]
