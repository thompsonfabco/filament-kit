import json

import pytest
from fakes.claude_fake import FakeClaude
from starlette.testclient import TestClient

from conftest import free_port
from filament_kit import config, inventory, pairing
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50
UID = "4:77:90:e:9:22:89"

READ = {"questions": [], "items": [{
    "photos": [0], "existing_filament_id": None, "vendor": "OVERTURE", "name": "PETG Black", "material": "PETG",
    "color_hex": "111111", "net": 1000, "tare": 155, "density": 1.27, "count": 1, "nozzle": 240, "bed": 75,
    "nozzle_range": "230-250", "bed_range": "70-80", "lot": None, "note": "SKU X", "estimates": [],
    "sealed": False, "sealed_reason": "bare spool"}]}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def token() -> str:
    return pairing.redeem_code(pairing.issue().code)


def auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def client(sm, claude=None) -> TestClient:
    return TestClient(create_app(sm=sm, claude=claude))


def read(c, tok, photos, **data):
    files = [("photo", (name, body, "image/jpeg")) for name, body in photos]
    return c.post("/api/intake/read", headers=auth(tok), files=files, data=data)


def test_info_open_rest_needs_token(sm, tmp_path):
    c = client(sm)
    r = c.get("/api/info")
    assert r.status_code == 200
    body = r.json()
    assert body["api"] == 1 and body["apk_version"] is None and body["version"] and body["name"]
    (tmp_path / "opt" / "app").mkdir()
    (tmp_path / "opt" / "app" / "version.txt").write_text("1.2.3\n")
    assert c.get("/api/info").json()["apk_version"] == "1.2.3"
    for method, path in (("GET", "/api/spools"), ("GET", "/api/locations"), ("GET", f"/api/tags/{UID}"),
                         ("POST", "/api/intake/add"), ("PATCH", "/api/spools/1"),
                         ("POST", "/api/intake/retry/abc")):
        r = c.request(method, path)
        assert r.status_code == 401, path
        assert r.json()["error"] == "unauthorized"
    assert c.get("/api/spools", headers=auth("nope")).status_code == 401


def test_pair_then_call(sm):
    c = client(sm)
    p = pairing.issue()
    assert c.post("/api/pair", json={"code": "000000" if p.code != "000000" else "111111"}).status_code == 401
    r = c.post("/api/pair", json={"code": p.code})
    assert r.status_code == 200
    tok = r.json()["token"]
    r = c.get("/api/spools", headers=auth(tok))
    assert r.status_code == 200 and r.json() == {"spools": []}


def test_read_rejects_heic_400(sm):
    fake = FakeClaude(READ)
    c = client(sm, fake)
    r = read(c, token(), [("label.heic", PNG)])
    assert r.status_code == 400
    assert r.json()["error"] == "bad_photo" and "label.heic" in r.json()["message"]
    assert fake.calls == []
    assert not (config.paths().state / "reads.json").exists()  # a bad photo doesn't use up the cap


def test_read_bad_tag_400(sm):
    fake = FakeClaude(READ)
    r = read(client(sm, fake), token(), [("a.jpg", JPEG)], tag="zz")
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    assert fake.calls == []


def test_read_then_add_then_tag_lookup(sm):
    fake = FakeClaude(READ)
    c = client(sm, fake)
    tok = token()
    r = read(c, tok, [("a.jpg", JPEG), ("b.jpg", JPEG)], hint="x" * 5000, tag="04:77:90:0E:09:22:89")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["read_id"] and out["tag"] == {"nfc_id": UID}
    assert len(out["items"]) == 1 and out["items"][0]["sealed"] is False
    assert "x" * 2001 not in json.dumps(fake.calls[0]["messages"])
    assert "x" * 2000 in json.dumps(fake.calls[0]["messages"])

    r = c.post("/api/intake/add", headers=auth(tok), json={"items": out["items"], "dry_run": True, "tag": UID})
    assert r.status_code == 200 and r.json()["dry"] is True and r.json()["spool_ids"] == []
    r = c.post("/api/intake/add", headers=auth(tok), json={"items": out["items"], "dry_run": False, "tag": UID})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry"] is False and len(body["spool_ids"]) == 1 and body["lines"]
    sid = body["spool_ids"][0]

    r = c.get(f"/api/tags/{UID}", headers=auth(tok))
    assert r.status_code == 200 and r.json()["spool"]["id"] == sid
    assert r.json()["spool"]["location"] == "Storage box 01"
    assert c.get("/api/tags/4:1:2:3", headers=auth(tok)).json() == {"spool": None}
    assert c.get("/api/tags/zz", headers=auth(tok)).json()["error"] == "bad_request"

    found = c.get("/api/spools?q=overture", headers=auth(tok)).json()["spools"]
    assert [s["id"] for s in found] == [sid]
    assert c.get("/api/spools?q=overture&sealed=1", headers=auth(tok)).json()["spools"] == []


def test_add_bad_items_400(sm):
    c = client(sm)
    r = c.post("/api/intake/add", headers=auth(token()), json={"items": [], "dry_run": False})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    r = c.post("/api/intake/add", headers=auth(token()), content=b"not json")
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_add_rejects_a_tare_of_zero_or_less(sm):
    c = client(sm)
    for tare in (0, -5):
        it = {"vendor": "SUNLU", "name": "PETG Grey", "material": "PETG", "net": 1000, "tare": tare,
              "density": 1.27, "count": 1}
        r = c.post("/api/intake/add", headers=auth(token()), json={"items": [it], "dry_run": True})
        assert r.status_code == 400 and r.json()["error"] == "bad_request"
        assert "tare must be a positive number" in r.json()["message"]

def sealed_spool(sm, **kw) -> int:
    it = {"vendor": "SUNLU", "name": "PETG Grey", "material": "PETG", "net": 1000, "tare": 213, "density": 1.27,
          "count": 1, **kw}
    return inventory.add_spools(sm, [it], config.load()["placement"], dry=False).spool_ids[0]


def test_tag_conflict_409_names_spool(sm):
    c = client(sm)
    tok = token()
    a, b = sealed_spool(sm), sealed_spool(sm)
    r = c.post(f"/api/spools/{a}/link", headers=auth(tok), json={"tag": UID, "dry_run": False, "gross": 1100})
    assert r.status_code == 200, r.text
    s = r.json()["spool"]
    assert s["location"] == "Storage box 01" and s["remaining_weight"] == 887 and s["first_used"]
    assert inventory.SEALED_COMMENT not in (s["comment"] or "")

    r = c.post(f"/api/spools/{b}/link", headers=auth(tok), json={"tag": UID, "dry_run": False})
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "tag_conflict" and body["reason"] == "tag_on_other_spool"
    assert body["other_spool"]["id"] == a and f"spool {a}" in body["message"]

    r = c.post(f"/api/spools/{a}/link", headers=auth(tok), json={"tag": "4:1:2:3", "dry_run": False})
    assert r.status_code == 409
    assert r.json()["reason"] == "spool_has_other_tag" and r.json()["other_spool"] is None

    r = c.post(f"/api/spools/{b}/link", headers=auth(tok), json={"tag": UID, "dry_run": False, "force": True})
    assert r.status_code == 200 and r.json()["spool"]["id"] == b


def test_patch_and_locations(sm):
    c = client(sm)
    tok = token()
    sid = sealed_spool(sm)
    r = c.patch(f"/api/spools/{sid}", headers=auth(tok), json={"remaining": 500, "dry_run": True})
    assert r.status_code == 200 and r.json()["spool"]["remaining_weight"] == 500
    assert sm.get(f"spool/{sid}")["remaining_weight"] == 1000
    r = c.patch(f"/api/spools/{sid}", headers=auth(tok), json={"remaining": 400})  # no dry_run = dry run
    assert r.status_code == 200 and sm.get(f"spool/{sid}")["remaining_weight"] == 1000
    r = c.patch(f"/api/spools/{sid}", headers=auth(tok),
                json={"gross": 713, "location": "Rack 1", "dry_run": False})
    assert r.status_code == 200
    assert r.json()["spool"]["remaining_weight"] == 500 and r.json()["spool"]["location"] == "Rack 1"
    stored = sm.get(f"spool/{sid}")
    assert stored["remaining_weight"] == 500 and stored["location"] == "Rack 1"
    r = c.patch(f"/api/spools/{sid}", headers=auth(tok), json={"gross": 10})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    r = c.patch(f"/api/spools/{sid}", headers=auth(tok), json={"remaining": "lots"})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    locs = c.get("/api/locations", headers=auth(tok)).json()["locations"]
    assert locs[:4] == config.load()["locations"]


def test_add_without_dry_run_is_dry(sm, spoolman_fake_store):
    c = client(sm)
    r = c.post("/api/intake/add", headers=auth(token()), json={"items": READ["items"]})
    assert r.status_code == 200, r.text
    assert r.json()["dry"] is True and r.json()["spool_ids"] == []
    assert spoolman_fake_store["spools"] == {} and spoolman_fake_store["filaments"] == {}


def test_missing_spool_404(sm):
    r = client(sm).patch("/api/spools/99999", headers=auth(token()), json={"remaining": 5, "dry_run": False})
    assert r.status_code == 404 and r.json()["error"] == "not_found" and r.json()["message"]


def test_spoolman_down_503():
    dead = Spoolman(f"http://127.0.0.1:{free_port()}", timeout=2)
    c = client(dead)
    r = c.get("/api/spools", headers=auth(token()))
    assert r.status_code == 503
    assert r.json()["error"] == "spoolman_unreachable" and "Traceback" not in r.text


def test_internal_error_hides_traceback(sm, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(inventory, "find", boom)
    r = client(sm).get("/api/spools", headers=auth(token()))
    assert r.status_code == 500
    assert r.json() == {"error": "internal", "message": "internal error"}


def test_cap_429(sm):
    cfg = config.load()
    cfg["reads_per_day"] = 1
    config.save(cfg)
    fake = FakeClaude(READ)
    c = client(sm, fake)
    tok = token()
    assert read(c, tok, [("a.jpg", JPEG)]).status_code == 200
    r = read(c, tok, [("a.jpg", JPEG)])
    assert r.status_code == 429 and r.json()["error"] == "daily_cap"
    assert len(fake.calls) == 1


def test_read_error_502_then_retry(sm):
    import anthropic
    import httpx
    fake = FakeClaude(READ, raises=anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")))
    c = client(sm, fake)
    tok = token()
    r = read(c, tok, [("a.jpg", JPEG)])
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "unreachable" and body["read_id"]
    fake.raises = None
    r = c.post(f"/api/intake/retry/{body['read_id']}", headers=auth(tok))
    assert r.status_code == 200 and r.json()["read_id"] == body["read_id"]
    r = c.post("/api/intake/retry/gone", headers=auth(tok))
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert len(json.loads((config.paths().state / "reads.json").read_text())) == 2  # not_found took no read


def test_retry_expired_read_costs_no_cap(sm, tmp_path):
    import os
    import time
    old = tmp_path / "state" / "failed" / "oldread"
    old.mkdir(parents=True)
    (old / "photo0.jpg").write_bytes(JPEG)
    t = time.time() - 25 * 3600
    os.utime(old, (t, t))
    fake = FakeClaude(READ)
    r = client(sm, fake).post("/api/intake/retry/oldread", headers=auth(token()))
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert fake.calls == [] and not (tmp_path / "state" / "reads.json").exists()


def test_read_oversized_hint_400(sm, caplog):
    fake = FakeClaude(READ)
    r = read(client(sm, fake), token(), [("a.jpg", JPEG)], hint="x" * (1024 * 1024 + 10))
    assert r.status_code == 400 and r.json()["error"] == "bad_request" and r.json()["message"]
    assert fake.calls == [] and "Traceback" not in caplog.text and "internal error" not in caplog.text


def test_add_failed_502_partial(sm, monkeypatch):
    from filament_kit.spoolman import SpoolmanError
    real_post, spools = sm.post, []

    def post(path, body):
        if path == "spool":
            spools.append(1)
            if len(spools) == 2:
                raise SpoolmanError("spoolman POST spool -> 500: boom", status=500)
        return real_post(path, body)
    monkeypatch.setattr(sm, "post", post)
    it = {"vendor": "SUNLU", "name": "PETG Grey", "material": "PETG", "net": 1000, "tare": 213, "density": 1.27,
          "count": 2}
    r = client(sm).post("/api/intake/add", headers=auth(token()), json={"items": [it], "dry_run": False})
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "spoolman_error" and body["partial_spool_ids"] == [1]


def test_apk(sm, tmp_path):
    c = client(sm)
    r = c.get("/app.apk")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    (tmp_path / "opt" / "app").mkdir()
    (tmp_path / "opt" / "app" / "filament-kit.apk").write_bytes(b"PK apk")
    r = c.get("/app.apk")
    assert r.status_code == 200 and r.content == b"PK apk"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"


def test_unknown_route_json_404(sm):
    r = client(sm).get("/api/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_add_and_link_tag_not_landing_502_partial(sm, monkeypatch):
    real_get = sm.get

    def get(path):
        out = real_get(path)
        if path.startswith("spool/") and isinstance(out, dict):
            out["extra"] = {}
        return out
    monkeypatch.setattr(sm, "get", get)
    it = {"vendor": "SUNLU", "name": "PETG Grey", "material": "PETG", "net": 1000, "tare": 213, "density": 1.27,
          "count": 1, "sealed": False}
    r = client(sm).post("/api/intake/add", headers=auth(token()),
                        json={"items": [it], "dry_run": False, "tag": UID})
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "spoolman_error" and len(body["partial_spool_ids"]) == 1
    assert "tag did not land" in body["message"]


def test_read_spoolman_down_503_refunds_cap(sm):
    import anthropic
    import httpx
    fake = FakeClaude(READ)
    c = client(sm, fake)
    tok = token()
    assert read(c, tok, [("a.jpg", JPEG)]).status_code == 200
    reads = config.paths().state / "reads.json"
    assert len(json.loads(reads.read_text())) == 1
    dead = Spoolman(f"http://127.0.0.1:{free_port()}", timeout=2)
    c_dead = client(dead, fake)
    r = read(c_dead, tok, [("a.jpg", JPEG)])
    assert r.status_code == 503 and r.json()["error"] == "spoolman_unreachable"
    assert len(json.loads(reads.read_text())) == 1
    # retry of a kept read: a Spoolman outage gives the read back too
    fake.raises = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    read_id = read(c, tok, [("a.jpg", JPEG)]).json()["read_id"]
    assert len(json.loads(reads.read_text())) == 2
    r = c_dead.post(f"/api/intake/retry/{read_id}", headers=auth(tok))
    assert r.status_code == 503 and r.json()["error"] == "spoolman_unreachable"
    assert len(json.loads(reads.read_text())) == 2


def test_filaments_and_vendors_for_a_manual_add(sm):
    """R1: the app's manual Add lists the existing filaments (with or without spools) and vendors; a filament's
    fields are named as an add item's, so the app can copy them into the item."""
    c = client(sm)
    tok = token()
    sealed_spool(sm)
    v = sm.post("vendor", {"name": "Elegoo", "empty_spool_weight": 160})
    sm.post("filament", {"name": "PLA Red", "vendor_id": v["id"], "material": "PLA", "density": 1.24,
                         "diameter": 1.75, "weight": 1000, "spool_weight": 160, "color_hex": "cc0000",
                         "settings_extruder_temp": 210, "settings_bed_temp": 60})
    fils = c.get("/api/filaments", headers=auth(tok)).json()["filaments"]
    assert [(f["vendor"], f["name"]) for f in fils] == [("Elegoo", "PLA Red"), ("SUNLU", "PETG Grey")]
    red = fils[0]
    assert {k: red[k] for k in ("material", "density", "net", "tare", "color_hex", "nozzle", "bed")} == {
        "material": "PLA", "density": 1.24, "net": 1000, "tare": 160, "color_hex": "cc0000", "nozzle": 210,
        "bed": 60}
    assert isinstance(red["id"], int) and red["spools"] == 0 and fils[1]["spools"] == 1
    assert [f["name"] for f in c.get("/api/filaments?q=sunlu petg", headers=auth(tok)).json()["filaments"]] == [
        "PETG Grey"]
    vendors = c.get("/api/vendors", headers=auth(tok)).json()["vendors"]
    assert [(x["name"], x["tare"]) for x in vendors] == [("Elegoo", 160), ("SUNLU", 213)]
    assert c.get("/api/filaments").status_code == 401 and c.get("/api/vendors").status_code == 401

    # a manual add of the existing filament reuses it
    item = {k: red[k] for k in ("vendor", "name", "material", "density", "net", "tare")}
    r = c.post("/api/intake/add", headers=auth(tok), json={"items": [{**item, "count": 2}], "dry_run": False})
    assert r.status_code == 200, r.text
    assert len(r.json()["spool_ids"]) == 2 and "existing filament" in r.json()["lines"][0]
