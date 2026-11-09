"""The intake station's button flow, server side: /api/station/tag, /recognize, /save (station_flow.py)."""
import copy
import sys
import types

import pytest
from fakes.claude_fake import FakeClaude
from starlette.testclient import TestClient

from filament_kit import config, inventory, pairing, station_flow, tags
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
UID = "a:b:c:d:e:f:1"
ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "OVERTURE", "name": "PETG Black",
        "material": "PETG", "color_hex": "111111", "net": 1000, "tare": 155, "density": 1.27, "count": 1,
        "nozzle": 240, "bed": 75, "nozzle_range": "230-250", "bed_range": "70-80", "lot": None, "note": "SKU X",
        "estimates": [], "sealed": False, "sealed_reason": "bare spool", "line": "PETG"}


def read_reply(**over):
    return {"questions": [], "items": [{**ITEM, **over}]}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})  # a legacy config: ai_intake on


@pytest.fixture(autouse=True)
def no_lines(monkeypatch):  # recording product lines needs the library and a build store: not this test's concern
    monkeypatch.setattr(inventory, "_record_lines", lambda items: None)
    monkeypatch.setattr(inventory, "_check_parents", lambda items: None)


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def auth() -> dict:
    return {"Authorization": f"Bearer {pairing.redeem_code(pairing.issue('station').code)}"}


def client(sm, claude=None) -> TestClient:
    return TestClient(create_app(sm=sm, claude=claude))


def recognize(c, h, image=JPEG):
    return c.post("/api/station/recognize", headers=h, files=[("image", ("s.jpg", image, "image/jpeg"))])


def save(c, h, **body):
    return c.post("/api/station/save", headers=h, json={"uid": UID, **body})


# ---------- screen lines ----------

def test_lines_title_then_two_wrapped_lines_ascii_only():
    out = station_flow.lines("A very long spool title here", "Polymaker Panchroma Matte PLA Galaxy Black", "3rd")
    assert out[0] == "A very long spool"[:16] and len(out) == 3
    assert all(len(x) <= 21 for x in out[1:])
    assert station_flow.lines("Café", "naïve") == ["Cafe", "naive"]
    assert all(all(" " <= ch <= "~" for ch in line) for line in station_flow.lines("Café ✓", "naïve ✓ x"))


# ---------- auth ----------

def test_routes_need_a_paired_device(sm):
    c = client(sm)
    for method, path in (("GET", f"/api/station/tag/{UID}"), ("POST", "/api/station/recognize"),
                         ("POST", "/api/station/save")):
        assert c.request(method, path).status_code == 401, path


# ---------- tag ----------

def test_unknown_tag_is_new(sm):
    r = client(sm).get(f"/api/station/tag/{UID}", headers=auth())
    assert r.status_code == 200
    assert r.json() == {"known": False, "uid": tags.normalize_uid(UID), "display": ["New Tag Scanned"]}


def test_known_tag_shows_the_spool(sm):
    c, h = client(sm), auth()
    assert save(c, h, gross_g=900, item=ITEM).status_code == 200
    r = c.get(f"/api/station/tag/{UID}", headers=h).json()
    assert r["known"] is True and r["spool"]["name"] == "PETG Black" and r["spool"]["remaining_g"] == 745
    assert r["display"][0] == "PETG Black" and "745 g left" in r["display"][2]


# ---------- recognize ----------

def test_recognize_with_claude(sm):
    fake = FakeClaude(read_reply())
    r = recognize(client(sm, fake), auth())
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["source"] == "claude" and b["confidence"] == "high" and b["item"]["vendor"] == "OVERTURE"
    assert b["display"] == ["PETG Black", "OVERTURE PETG", "opened"]
    assert len(fake.calls) == 1


def test_recognize_ignores_a_fresh_tap_so_the_photo_decides_sealed(sm, monkeypatch):
    from filament_kit import tagsources
    monkeypatch.setattr(tagsources, "fresh_unknown_tag", lambda cfg, sm: {"nfc_id": UID, "age_seconds": 2})
    b = recognize(client(sm, FakeClaude(read_reply(sealed=True, sealed_reason="in vacuum bag"))), auth()).json()
    assert b["item"]["sealed"] is True and b["display"][2] == "sealed"


def test_unsure_read_is_low_confidence_with_a_question_mark(sm):
    b = recognize(client(sm, FakeClaude(read_reply(sealed_reason="unsure", estimates=["vendor"]))), auth()).json()
    assert b["confidence"] == "low" and b["display"][0].endswith("?") and b["display"][2] == "?"


def test_no_recognizer_says_use_phone(sm):
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True, "ai_intake": False}
    config.save(cfg)
    r = recognize(client(sm, FakeClaude(read_reply())), auth())
    assert r.status_code == 409 and r.json()["error"] == "no_recognizer"
    assert r.json()["display"] == ["No AI on server", "use phone"]


def test_local_ai_first_then_claude(sm, monkeypatch):
    calls = []
    local = types.ModuleType(station_flow.LOCAL_MODULE)
    local.recognize = lambda sm, images, cfg: calls.append(len(images)) or read_reply(vendor="SUNLU")
    monkeypatch.setitem(sys.modules, station_flow.LOCAL_MODULE, local)
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True, "ai_intake": True, "local_ai": True}
    config.save(cfg)
    fake = FakeClaude(read_reply())
    b = recognize(client(sm, fake), auth()).json()
    assert b["source"] == "local" and b["item"]["vendor"] == "SUNLU" and calls == [1] and not fake.calls
    local.recognize = lambda sm, images, cfg: None  # the local model can't tell: Claude reads it
    b = recognize(client(sm, fake), auth()).json()
    assert b["source"] == "claude" and len(fake.calls) == 1


def test_local_ai_switched_on_but_not_installed_falls_to_claude(sm):
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True, "ai_intake": True, "local_ai": True}
    config.save(cfg)
    assert station_flow.recognizers(config.load()) == ["claude"]


def test_read_failure_is_502_with_a_display(sm):
    import anthropic
    r = recognize(client(sm, FakeClaude(raises=anthropic.APIConnectionError(request=None))), auth())
    assert r.status_code == 502 and r.json()["error"] == "read_failed"
    assert r.json()["display"] == ["Read failed", "try again, or", "use the phone"]


def test_bad_photo_is_400(sm):
    r = recognize(client(sm, FakeClaude(read_reply())), auth(), image=b"not an image")
    assert r.status_code == 400 and r.json()["display"][0] == "Bad photo"


# ---------- save ----------

def test_save_new_opened_spool_links_the_tag_and_places_it(sm):
    c, h = client(sm), auth()
    r = save(c, h, gross_g=900, item=ITEM)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["created"] is True and b["sealed"] is False and b["remaining_g"] == 745 and b["location"]
    s = sm.get(f"spool/{b['spool_id']}")
    assert tags.stored(s) == tags.normalize_uid(UID) and s["first_used"]
    assert b["display"][0] == "Saved"


def test_save_new_sealed_spool_links_the_tag_and_stays_sealed(sm):
    c, h = client(sm), auth()
    b = save(c, h, gross_g=1180, item={**ITEM, "sealed": True, "sealed_reason": "in vacuum bag"}).json()
    s = sm.get(f"spool/{b['spool_id']}")
    assert b["sealed"] is True and s["remaining_weight"] == 1000
    assert tags.stored(s) == tags.normalize_uid(UID) and not s.get("first_used")
    assert inventory.SEALED_COMMENT in (s.get("comment") or "")


@pytest.mark.parametrize("gross,sealed", [(1150, True), (1140, True), (1100, False)])
def test_unsure_photo_falls_back_to_the_weight(sm, gross, sealed):
    b = save(client(sm), auth(), gross_g=gross, item={**ITEM, "sealed_reason": "unsure"}).json()
    assert b["sealed"] is sealed  # full = net 1000 + tare 155; within 20 g counts as sealed


def test_save_existing_spool_updates_only_the_weight(sm):
    c, h = client(sm), auth()
    sid = save(c, h, gross_g=900, item=ITEM).json()["spool_id"]
    loc = sm.get(f"spool/{sid}")["location"]
    b = save(c, h, gross_g=500, spool_id=sid).json()
    assert b["created"] is False and b["remaining_g"] == 345 and b["location"] == loc
    b = save(c, h, gross_g=400).json()  # the tag alone finds the spool
    assert b["spool_id"] == sid and b["remaining_g"] == 245


def test_save_refusals(sm):
    c, h = client(sm), auth()
    r = save(c, h, gross_g=900)
    assert r.status_code == 409 and r.json()["error"] == "no_filament"
    r = save(c, h, gross_g=0, item=ITEM)
    assert r.status_code == 422 and r.json()["error"] == "no_weight"
    r = save(c, h, gross_g="heavy", item=ITEM)
    assert r.status_code == 400
    sid = save(c, h, gross_g=900, item=ITEM).json()["spool_id"]
    r = save(c, h, gross_g=100)  # below the spool's tare
    assert r.status_code == 422 and r.json()["error"] == "weight_out_of_range"
    r = c.post("/api/station/save", headers=h, json={"uid": "4:1:2:3:4:5:6", "gross_g": 900, "spool_id": sid})
    assert r.status_code == 409 and r.json()["error"] == "tag_mismatch"


def test_dry_run_writes_nothing(sm):
    c, h = client(sm), auth()
    b = save(c, h, gross_g=900, item=ITEM, dry_run=True).json()
    assert b["dry"] is True and b["display"][0] == "Would save"
    assert inventory.by_tag(sm, UID) is None and sm.get("spool") == []


def test_keep_sealed_link_does_not_open(sm):
    c, h = client(sm), auth()
    sid = save(c, h, gross_g=1180, item={**ITEM, "sealed": True, "sealed_reason": "bag"}).json()["spool_id"]
    s = sm.get(f"spool/{sid}")
    before = copy.deepcopy(s)
    inventory.link_tag(sm, sid, UID, force=False, dry=False, keep_sealed=True)  # already linked: no-op
    assert sm.get(f"spool/{sid}")["comment"] == before["comment"]


def test_save_accepts_the_panels_filament_key(sm):
    b = save(client(sm), auth(), gross_g=900, filament=ITEM).json()
    assert b["created"] is True and b["remaining_g"] == 745


# ---------- fix round 1 ----------

SEALED = {**ITEM, "sealed": True, "sealed_reason": "in vacuum bag"}


def _spools(sm):
    return len(sm.get("spool?allow_archived=true"))


def test_sealed_save_refuses_a_tag_linked_meanwhile_before_adding(sm, monkeypatch):
    """M1: the by_tag check, the add and the link run under one inventory lock: a tag another save linked since
    station_flow looked (a race) is refused before a second spool is written."""
    c, h = client(sm), auth()
    first = save(c, h, gross_g=1180, item=SEALED).json()["spool_id"]
    n = _spools(sm)
    real, calls = inventory.by_tag, []

    def stale_first_look(s, uid):  # station_flow's own look misses the link; the locked check sees it
        calls.append(uid)
        return None if len(calls) == 1 else real(s, uid)
    monkeypatch.setattr(inventory, "by_tag", stale_first_look)
    r = save(c, h, gross_g=1180, item=SEALED)
    assert r.status_code == 409 and r.json()["error"] == "tag_in_use", r.json()
    assert _spools(sm) == n and tags.stored(sm.get(f"spool/{first}")) == tags.normalize_uid(UID)


def test_sealed_save_link_failure_reports_the_added_spool(sm, monkeypatch):
    """M1: a link that fails after the add says which spool exists, so the panel doesn't invite a blind retry."""
    def broken_link(*a, **kw):
        raise RuntimeError("tag did not land")
    monkeypatch.setattr(inventory, "link_tag", broken_link)
    r = save(client(sm), auth(), gross_g=1180, item=SEALED)
    body = r.json()
    assert r.status_code == 502 and body["error"] == "tag_not_linked", body
    sid = body["spool_id"]
    assert sm.get(f"spool/{sid}") and body["display"][0] == f"Saved #{sid}"[:16]


def test_sealed_by_weight_counts_a_bagged_spool_as_sealed():
    """M2: a spool still in its bag or box weighs more than a bare full spool: heavier is sealed too."""
    it = {"net": 1000, "tare": 155}
    assert station_flow.sealed_by_weight(it, 1300) and station_flow.sealed_by_weight(it, 1135)
    assert not station_flow.sealed_by_weight(it, 1134)
    assert "bag" in station_flow.sealed_by_weight.__doc__


# ---------- final fix wave: the retry after tag_not_linked links that spool, never a second one ----------

@pytest.mark.parametrize("item", [ITEM, SEALED], ids=["opened", "sealed"])
def test_the_retry_after_tag_not_linked_links_the_same_spool(sm, monkeypatch, item):
    c, h = client(sm), auth()
    real = inventory.link_tag
    monkeypatch.setattr(inventory, "link_tag", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("tag did not land")))
    first = save(c, h, gross_g=1180, item=item).json()
    assert first["error"] == "tag_not_linked"
    sid, n = first["spool_id"], _spools(sm)
    before = sm.get(f"spool/{sid}")
    monkeypatch.setattr(inventory, "link_tag", real)
    r = save(c, h, gross_g=1180, spool_id=sid)  # the panel's next long press sends the spool it was told about
    assert r.status_code == 200 and r.json()["spool_id"] == sid and r.json()["created"] is False, r.json()
    assert _spools(sm) == n and tags.stored(sm.get(f"spool/{sid}")) == tags.normalize_uid(UID)
    after = sm.get(f"spool/{sid}")
    assert after["comment"] == before["comment"]  # a sealed spool stays sealed
    if item is SEALED:
        assert after["remaining_weight"] == before["remaining_weight"]


def test_the_retry_never_takes_a_spool_with_another_tag(sm):
    c, h = client(sm), auth()
    sid = c.post("/api/station/save", headers=h, json={"uid": "4:1:2:3:4:5:6", "gross_g": 900,
                                                       "item": ITEM}).json()["spool_id"]
    r = save(c, h, gross_g=900, spool_id=sid)
    assert r.status_code == 409 and r.json()["error"] == "tag_mismatch"
    assert inventory.by_tag(sm, UID) is None


def test_the_retry_gives_an_opened_spool_its_first_used(sm, monkeypatch):
    c, h = client(sm), auth()
    real = inventory.link_tag
    monkeypatch.setattr(inventory, "link_tag", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("tag did not land")))
    sid = save(c, h, gross_g=900, item=ITEM).json()["spool_id"]
    assert not sm.get(f"spool/{sid}").get("first_used")
    monkeypatch.setattr(inventory, "link_tag", real)
    assert save(c, h, gross_g=900, spool_id=sid).status_code == 200
    assert sm.get(f"spool/{sid}")["first_used"]
