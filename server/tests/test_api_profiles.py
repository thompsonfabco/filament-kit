"""Sync and profiles API routes (global-constraints "Sync and profiles API contract")."""
import io
import json
import logging
import re
import zipfile

import pytest
from starlette.testclient import TestClient

from filament_kit import config, library, pairing
from filament_kit.api import create_app
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer
from filament_kit.profiles import builds, lines as lines_mod

import test_generate as TG
from test_builds import FakeSm, SUNLU, system_zip, zip_of

ISO = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
LID = "sunlu--pla-plus-2-0"


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})
    monkeypatch.setattr(library, "load", lambda: TG.make_lib())
    registry.upsert(Printer("S1", "H2D", "O1D", "10.0.0.5", "", True))


@pytest.fixture
def sm():
    return FakeSm(SUNLU)


@pytest.fixture
def c(sm):
    return TestClient(create_app(sm=sm))


def token() -> str:
    return pairing.redeem_code(pairing.issue().code)


def auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def device_of(tok: str) -> str:
    return pairing.check(tok)


def put_zip(c, tok, kind, data, query=""):
    return c.put(f"/api/sync/{kind}{query}", content=data,
                 headers={**auth(tok), "Content-Type": "application/zip"})


def live_files():
    return (config.paths().state / "profiles" / "live" / "user")


def built(c, tok, sm):
    assert put_zip(c, tok, "system", system_zip()).status_code == 200
    r = builds.run_build(sm, now=TG.NOW)
    assert r["ok"], r
    return r["stamp"]


ROUTES = [("GET", "/api/sync/state"), ("PUT", "/api/sync/live"), ("PUT", "/api/sync/system"),
          ("POST", "/api/sync/rebuild"), ("GET", "/api/sync/build?stamp=20270115-080000"),
          ("POST", "/api/sync/installed"), ("GET", "/api/profiles/status"), ("GET", "/api/profiles/lines"),
          ("PATCH", f"/api/profiles/lines/{LID}"), ("GET", "/api/profiles/parents?material=PLA"),
          ("POST", "/api/profiles/propose"), ("POST", "/api/library/local"), ("GET", "/api/profiles/updates")]


def test_every_route_needs_a_token(c):
    for method, path in ROUTES:
        r = c.request(method, path)
        assert r.status_code == 401, (method, path)
        assert r.json()["error"] == "unauthorized"
        assert c.request(method, path, headers=auth("nope")).status_code == 401


def test_state_before_any_sync(c):
    tok = token()
    r = c.get("/api/sync/state", headers=auth(tok))
    assert r.status_code == 200
    assert r.json() == {"owner": None, "you": device_of(tok), "user_id": None, "live_hash": None,
                        "system_hash": None, "orca_live_hash": None, "orca_system_hash": None, "orca_target": False,
                        "build": None, "accepted_updates": None,
                        "last_attempt": None, "installed": None, "rebuild_requested": None}


def test_live_upload_state_and_rebuild(c):
    tok = token()
    me = device_of(tok)
    r = put_zip(c, tok, "live", zip_of({"base/x.json": "{}"}), "?user_id=1234_ab-C")
    assert r.status_code == 200
    h = r.json()["live_hash"]
    assert set(r.json()) == {"live_hash"} and h == builds.tree_hash(live_files())
    st = c.get("/api/sync/state", headers=auth(tok)).json()
    assert st["owner"] == me and st["user_id"] == "1234_ab-C" and st["live_hash"] == h

    r = c.post("/api/sync/rebuild", json={"live_hash": h}, headers=auth(tok))
    assert r.status_code == 202 and r.json() == {"requested": True}
    st = c.get("/api/sync/state", headers=auth(tok)).json()
    assert st["rebuild_requested"]["live_hash"] == h and ISO.fullmatch(st["rebuild_requested"]["at"])


@pytest.mark.parametrize("uid", ["a b", "x" * 65, "", "../x", "é"])
def test_live_upload_bad_user_id(c, uid):
    tok = token()
    from urllib.parse import quote
    r = put_zip(c, tok, "live", zip_of({"base/x.json": "{}"}), "?user_id=" + quote(uid))
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    assert not live_files().exists()


@pytest.mark.parametrize("part, status", [("20270115-080000", 200), ("20270115-080000-2", 200), ("x", 400),
                                          ("../20270115-080000", 400), ("", 400)])
def test_live_upload_partial_stamp(c, part, status):
    """Ruling S28: `partial` (optional, a build stamp) is stored with the live upload; anything else is a 400."""
    tok = token()
    r = put_zip(c, tok, "live", zip_of({"base/x.json": "{}"}), "?user_id=1&partial=" + part)
    assert r.status_code == status, r.text
    if status == 200:
        assert builds.meta()["partial"] == part
    else:
        assert r.json()["error"] == "bad_request" and not live_files().exists()


def test_system_upload_counts_and_requests_rebuild(c):
    tok = token()
    r = put_zip(c, tok, "system", system_zip())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"system_hash", "presets"}
    assert body["presets"] == len(TG.presets())
    req = builds._request()
    assert req is not None
    assert c.get("/api/sync/state", headers=auth(tok)).json()["system_hash"] == body["system_hash"]


def test_system_upload_after_build_requests_fresh_rebuild(c, sm):
    tok = token()
    built(c, tok, sm)
    assert builds._pending_request() is None          # the build handled the first request
    assert put_zip(c, tok, "system", system_zip()).status_code == 200
    assert builds._pending_request() is not None


def test_too_large_live_upload_stores_nothing(c):
    tok = token()
    big = b"\0" * (33 << 20)
    r = put_zip(c, tok, "live", big)
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert not live_files().exists()
    assert not list((config.paths().state / "profiles").glob("upload-*"))


def test_zip_slip_is_bad_zip_and_keeps_previous(c):
    tok = token()
    assert put_zip(c, tok, "live", zip_of({"base/x.json": "{}"})).status_code == 200
    before = builds.tree_hash(live_files())
    for bad in ({"../evil.json": "{}"}, {"/abs.json": "{}"}, {"C:/x.json": "{}"}, {"base/x.txt": "hi"}):
        r = put_zip(c, tok, "live", zip_of(bad))
        assert r.status_code == 400 and r.json()["error"] == "bad_zip", bad
    r = put_zip(c, tok, "system", b"not a zip")
    assert r.status_code == 400 and r.json()["error"] == "bad_zip"
    assert builds.tree_hash(live_files()) == before


def test_second_device_is_other_pc(c, sm):
    a, b = token(), token()
    assert put_zip(c, a, "live", zip_of({"base/x.json": "{}"})).status_code == 200
    stamp = built(c, a, sm)
    for r in (put_zip(c, b, "live", zip_of({"base/y.json": "{}"})), put_zip(c, b, "system", system_zip()),
              c.post("/api/sync/rebuild", json={"live_hash": "0" * 64}, headers=auth(b)),
              c.post("/api/sync/installed", json={"stamp": stamp}, headers=auth(b))):
        assert r.status_code == 409 and r.json()["error"] == "other_pc"
        assert r.json()["owner"] == device_of(a)
    st = c.get("/api/sync/state", headers=auth(b)).json()
    assert st["owner"] == device_of(a) and st["you"] == device_of(b)


def test_other_pc_refused_before_the_body_is_read(c, monkeypatch):
    a, b = token(), token()
    assert put_zip(c, a, "live", zip_of({"base/x.json": "{}"})).status_code == 200
    calls = []
    monkeypatch.setattr(builds, "store_upload", lambda *a, **k: calls.append(1))
    r = put_zip(c, b, "live", b"\0" * (33 << 20))
    assert r.status_code == 409 and r.json()["error"] == "other_pc" and not calls


def test_build_download_and_installed(c, sm):
    tok = token()
    stamp = built(c, tok, sm)
    r = c.get(f"/api/sync/build?stamp={stamp}", headers=auth(tok))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "BUILD.json" in names and f"base/{TG.sunlu(TG.H2D, '0.4')}.json" in names
    for bad in ("nope", "20990101-000000", ""):
        r = c.get(f"/api/sync/build?stamp={bad}", headers=auth(tok))
        assert r.status_code == 404 and r.json()["error"] == "not_found", bad
    assert c.get("/api/sync/build", headers=auth(tok)).status_code == 404

    r = c.post("/api/sync/installed", json={"stamp": "20990101-000000"}, headers=auth(tok))
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = c.post("/api/sync/installed", json={"stamp": stamp, "trees": ["orca"]}, headers=auth(tok))
    assert r.status_code == 400
    (config.paths().state / "profiles" / "builds" / stamp / "orca").mkdir()   # "orca" counts for an orca/ tree
    r = c.post("/api/sync/installed", json={"stamp": stamp, "trees": ["base", "orca"]}, headers=auth(tok))
    assert r.status_code == 200
    assert builds._read_obj(config.paths().state / "profiles" / "installed.json")["orca_stamp"] == stamp
    r = c.post("/api/sync/installed", json={"stamp": stamp}, headers=auth(tok))     # an older PC sync
    assert r.status_code == 200
    inst = r.json()["installed"]
    assert inst["stamp"] == stamp and ISO.fullmatch(inst["at"])
    assert builds._read_obj(config.paths().state / "profiles" / "installed.json")["orca_stamp"] == stamp  # kept

    st = c.get("/api/sync/state", headers=auth(tok)).json()
    assert st["installed"] == inst
    assert st["build"]["stamp"] == stamp and ISO.fullmatch(st["build"]["created"])
    assert st["build"]["created"] == "2027-01-15T08:00:00Z"
    assert st["last_attempt"]["ok"] is True and ISO.fullmatch(st["last_attempt"]["at"])


def test_bad_json_bodies(c):
    tok = token()
    for path in ("/api/sync/rebuild", "/api/sync/installed", "/api/profiles/propose"):
        r = c.post(path, content=b"{nope", headers={**auth(tok), "Content-Type": "application/json"})
        assert r.status_code == 400 and r.json()["error"] == "bad_request", path
        r = c.post(path, json=[1], headers=auth(tok))
        assert r.status_code == 400, path
    assert c.post("/api/sync/rebuild", json={"live_hash": 5}, headers=auth(tok)).status_code == 400
    assert c.post("/api/sync/installed", json={}, headers=auth(tok)).status_code in (400, 404)


def test_profiles_status(c, sm):
    tok = token()
    r = c.get("/api/profiles/status", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"lines", "presets", "orca_presets", "build", "updates", "last_attempt", "installed", "pc",
                         "library", "stale", "orca_stale", "problems"}
    assert body["updates"] == {"count": 0, "lines": 0, "accepted": 0, "new": 0}
    assert body["pc"] is None and body["build"] is None and body["lines"] == 0
    assert set(body["library"]) == {"version", "source", "local", "last_check"}
    assert body["library"]["source"] in ("bundled", "updated")

    stamp = built(c, tok, sm)
    body = c.get("/api/profiles/status", headers=auth(tok)).json()
    assert body["lines"] == 1 and body["presets"] > 0 and body["build"]["stamp"] == stamp
    assert body["pc"]["device_id"] == device_of(tok) and ISO.fullmatch(body["pc"]["last_upload"])
    assert ISO.fullmatch(body["build"]["created"]) and ISO.fullmatch(body["last_attempt"]["at"])
    assert isinstance(body["stale"], list) and isinstance(body["problems"], list) and len(body["problems"]) <= 20


def test_lines_list_and_patch(c, sm):
    tok = token()
    assert c.get("/api/profiles/lines", headers=auth(tok)).json() == {"lines": []}
    built(c, tok, sm)
    lines = c.get("/api/profiles/lines", headers=auth(tok)).json()["lines"]
    assert len(lines) == 1
    line = lines[0]
    assert set(line) == {"line_id", "vendor", "product", "material", "bambu_parent", "parent_source",
                         "orca_parent", "orca_parent_source", "spoolman_ids", "presets"}
    assert line["line_id"] == LID and line["spoolman_ids"] == [3, 17] and line["presets"] > 0

    before = builds._request()
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Generic PLA"}, headers=auth(tok))
    assert r.status_code == 200, r.text
    got = r.json()["line"]
    assert got["bambu_parent"] == "Generic PLA" and got["parent_source"] == "user" and got["line_id"] == LID
    after = builds._request()
    assert after is not None and (before is None or after["at"] >= before["at"])
    assert builds._pending_request() is not None
    assert lines_mod.load()[LID].bambu_parent == "Generic PLA"


def test_patch_unknown_line_and_parent(c, sm):
    tok = token()
    r = c.patch("/api/profiles/lines/nope--nope", json={"bambu_parent": "Generic PLA"}, headers=auth(tok))
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    built(c, tok, sm)
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Bambu Nothing"}, headers=auth(tok))
    assert r.status_code == 400 and r.json()["error"] == "unknown_parent"
    assert lines_mod.load()[LID].parent_source != "user"
    # gated only by a condition: not usable either
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Generic PETG"}, headers=auth(tok))
    assert r.status_code == 400 and r.json()["error"] == "unknown_parent"
    for bad in ({}, {"bambu_parent": ""}, {"bambu_parent": 3}, {"bambu_parent": "x" * 101},
                {"bambu_parent": "Generic PLA @BBL H2D"}):
        r = c.patch(f"/api/profiles/lines/{LID}", json=bad, headers=auth(tok))
        assert r.status_code == 400 and r.json()["error"] == "bad_request", bad


def test_patch_any_parent_before_a_system_store(c):
    tok = token()
    with lines_mod.transaction() as ls:
        lines_mod.ensure(ls, "SUNLU", "PLA+ 2.0", "PLA", bambu_parent=None, library=TG.make_lib(), store=None,
                         used_fids=set())
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Bambu Anything"}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["line"]["bambu_parent"] == "Bambu Anything"
    assert r.json()["line"]["presets"] == 0 and r.json()["line"]["spoolman_ids"] == []


def test_parents(c, sm):
    tok = token()
    r = c.get("/api/profiles/parents?material=PLA", headers=auth(tok))
    assert r.status_code == 200 and r.json() == {"parents": [], "synced": False}
    assert put_zip(c, tok, "system", system_zip()).status_code == 200
    body = c.get("/api/profiles/parents?material=PLA", headers=auth(tok)).json()
    assert body["synced"] is True
    assert body["parents"] == ["Bambu PLA Tough+", "Generic PLA"]
    body = c.get("/api/profiles/parents?material=petg", headers=auth(tok)).json()
    assert body == {"parents": [], "synced": True}        # Generic PETG is gated only by a condition
    body = c.get("/api/profiles/parents?material=PLA-CF", headers=auth(tok)).json()
    assert body["parents"] == ["Generic PLA-CF"]


def test_propose(c, sm):
    tok = token()
    r = c.post("/api/profiles/propose", json={"vendor": "SUNLU", "line": "PLA+ 2.0", "material": "PLA"},
               headers=auth(tok))
    assert r.status_code == 200
    assert r.json() == {"line_id": LID, "line": "PLA+ 2.0", "bambu_parent": r.json()["bambu_parent"],
                        "parent_source": r.json()["parent_source"], "orca_parent": "Generic PLA",
                        "orca_parent_source": "material", "exists": False}
    assert r.json()["bambu_parent"]
    built(c, tok, sm)
    r = c.post("/api/profiles/propose", json={"vendor": "SUNLU", "line": "PLA+ 2.0", "material": "PLA"},
               headers=auth(tok))
    assert r.json()["exists"] is True
    for bad in ({}, {"vendor": "SUNLU"}, {"vendor": "", "line": "x", "material": "PLA"},
                {"vendor": "SUNLU", "line": 3, "material": "PLA"}, {"vendor": "a" * 101, "line": "x", "material": "PLA"}):
        r = c.post("/api/profiles/propose", json=bad, headers=auth(tok))
        assert r.status_code == 400 and r.json()["error"] == "bad_request", bad
    assert not (config.paths().state / "profiles" / "lines.json").exists() or len(lines_mod.load()) == 1


def test_library_local(c):
    tok = token()
    entry = {"vendor": "Acme Plastics", "product": "PLA Max", "material": "PLA", "fields": {}}
    r = c.post("/api/library/local", json=entry, headers=auth(tok))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["line_id"] == "acme-plastics--pla-max" and body["entry"]["product"] == "PLA Max"
    assert builds._pending_request() is not None
    assert (config.paths().state / "library-local" / "acme-plastics" / "pla-max.json").is_file()


def test_library_local_invalid_entry(c):
    tok = token()
    bad = {"vendor": "SUNLU", "product": "PLA", "material": "",
           "fields": {"temperature_vitrification": ["60"], "filament_density": ["9"]}}
    r = c.post("/api/library/local", json=bad, headers=auth(tok))
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_entry" and isinstance(body["problems"], list) and len(body["problems"]) >= 3
    assert any("material" in p for p in body["problems"])
    assert any("temperature_vitrification" in p for p in body["problems"])
    for raw in (b"not json", b"[1]", b"\xff", b"{" * 5000):
        r = c.post("/api/library/local", content=raw, headers={**auth(tok), "Content-Type": "application/json"})
        assert r.status_code == 400 and r.json()["error"] == "invalid_entry" and r.json()["problems"], raw[:5]
    r = c.post("/api/library/local", content=b" " * (300 << 10), headers=auth(tok))
    assert r.status_code == 400 and r.json()["error"] == "invalid_entry"
    assert builds._request() is None
    loc = config.paths().state / "library-local"
    assert not loc.exists() or not list(loc.rglob("*.json"))


def test_audit_lines_and_no_token_in_logs(c, sm, caplog):
    caplog.set_level(logging.DEBUG)
    tok = token()
    me = device_of(tok)
    put_zip(c, tok, "live", zip_of({"base/x.json": "{}"}), "?user_id=42")
    stamp = built(c, tok, sm)
    c.post("/api/sync/rebuild", json={"live_hash": "a" * 64}, headers=auth(tok))
    c.post("/api/sync/installed", json={"stamp": stamp}, headers=auth(tok))
    c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Generic PLA"}, headers=auth(tok))
    c.post("/api/library/local", json={"vendor": "Acme", "product": "PLA X", "material": "PLA", "fields": {}},
           headers=auth(tok))
    put_zip(c, tok, "live", zip_of({"../x.json": "{}"}))
    c.get("/api/sync/state", headers=auth(tok))
    c.get("/api/profiles/status", headers=auth(tok))
    text = caplog.text
    assert tok not in text
    audit = [r.getMessage() for r in caplog.records if f"device_id={me}" in r.getMessage()]
    for what in ("sync upload live", "sync upload system", "sync rebuild", "sync installed", "line parent",
                 "library local"):
        assert any(m.startswith(what) for m in audit), what
    assert any("result=BadZip" in m for m in audit)
    assert '"fields"' not in text and "{}" not in " ".join(audit)


def test_too_large_chunked_upload_stops_at_the_cap(c):
    """No Content-Length (chunked): the streamed body is refused once past the cap, not read to the end."""
    tok = token()

    def body():
        for _ in range(40):                     # 40 MiB offered
            yield b"\0" * (1 << 20)
    r = c.put("/api/sync/live", content=body(), headers={**auth(tok), "Content-Type": "application/zip"})
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert not live_files().exists()
    assert not list((config.paths().state / "profiles").glob("upload-*"))


def test_chunked_upload_streams_into_store(c):
    tok = token()
    data = zip_of({"base/x.json": "{}", "base/x.info": "setting_id = abc"})

    def body():
        for i in range(0, len(data), 7):
            yield data[i:i + 7]
    r = c.put("/api/sync/live", content=body(), headers={**auth(tok), "Content-Type": "application/zip"})
    assert r.status_code == 200 and r.json()["live_hash"] == builds.tree_hash(live_files())
    assert (live_files() / "base" / "x.info").is_file()


def test_patch_unknown_parent_same_error_as_intake(c, sm):
    """Task 7c: PATCH and the intake add share lines.check_parent: same code, message and `parent` field."""
    tok = token()
    built(c, tok, sm)
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Bambu Nothing"}, headers=auth(tok))
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "unknown_parent" and body["parent"] == "Bambu Nothing"
    assert "not a usable Bambu Studio system preset" in body["message"]


def test_profiles_api_uses_the_shared_store_loader():
    from filament_kit import profiles_api
    assert not hasattr(profiles_api, "system_store") and not hasattr(profiles_api, "_store_cache")


# ---------- Task 3: Orca uploads and the Orca parent ----------

from test_builds import orca_system_zip


def test_orca_live_upload(c):
    tok = token()
    r = put_zip(c, tok, "live", zip_of({"X @SV08 MAX 0.4.json": "{}"}), "?target=orca&user_id=f790a1c6-a")
    assert r.status_code == 200, r.text
    h = r.json()["live_hash"]
    assert set(r.json()) == {"live_hash"}
    assert h == builds.tree_hash(config.paths().state / "profiles" / "live" / "orca" / "user")
    st = c.get("/api/sync/state", headers=auth(tok)).json()
    assert (st["orca_live_hash"], st["live_hash"], st["user_id"]) == (h, None, None)
    assert builds.meta()["orca_user_id"] == "f790a1c6-a"
    assert not live_files().exists()


def test_orca_system_upload_requests_rebuild(c):
    tok = token()
    r = put_zip(c, tok, "system", orca_system_zip(), "?target=orca")
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"system_hash", "presets"} and r.json()["presets"] == 9 + 7
    assert builds._request() is not None
    st = c.get("/api/sync/state", headers=auth(tok)).json()
    assert (st["orca_system_hash"], st["system_hash"]) == (r.json()["system_hash"], None)


@pytest.mark.parametrize("q", ["?target=cura", "?target=", "?target=ORCA"])
def test_bad_target(c, q):
    tok = token()
    for kind in ("live", "system"):
        r = put_zip(c, tok, kind, zip_of({"a.json": "{}"}), q)
        assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_bambu_target_is_the_default(c):
    tok = token()
    r = put_zip(c, tok, "live", zip_of({"base/x.json": "{}"}), "?target=bambu")
    assert r.status_code == 200 and live_files().is_dir()


@pytest.mark.parametrize("part, status", [("20270115-080000", 200), ("x", 400), ("", 400)])
def test_orca_live_partial(c, part, status):
    """Ruling O: orca_live takes `partial` exactly like live."""
    tok = token()
    r = put_zip(c, tok, "live", zip_of({"a.json": "{}"}), "?target=orca&partial=" + part)
    assert r.status_code == status, r.text
    if status == 200:
        assert builds.meta()["orca_partial"] == part and "partial" not in builds.meta()
    else:
        assert r.json()["error"] == "bad_request"


def test_rebuild_with_orca_live_hash(c):
    tok = token()
    r = c.post("/api/sync/rebuild", json={"live_hash": "a" * 64, "orca_live_hash": "b" * 64}, headers=auth(tok))
    assert r.status_code == 202
    req = c.get("/api/sync/state", headers=auth(tok)).json()["rebuild_requested"]
    assert (req["live_hash"], req["orca_live_hash"]) == ("a" * 64, "b" * 64)
    r = c.post("/api/sync/rebuild", json={"orca_live_hash": "B" * 64}, headers=auth(tok))
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_patch_orca_parent(c, sm):
    tok = token()
    built(c, tok, sm)
    r = c.patch(f"/api/profiles/lines/{LID}", json={"orca_parent": "Anything Before Upload"}, headers=auth(tok))
    assert r.status_code == 200, r.text
    got = r.json()["line"]
    assert (got["orca_parent"], got["orca_parent_source"]) == ("Anything Before Upload", "user")
    bambu = (got["bambu_parent"], got["parent_source"])
    assert lines_mod.load()[LID].orca_parent == "Anything Before Upload"
    assert put_zip(c, tok, "system", orca_system_zip(), "?target=orca").status_code == 200
    r = c.patch(f"/api/profiles/lines/{LID}", json={"orca_parent": "Nope"}, headers=auth(tok))
    assert r.status_code == 400 and r.json()["error"] == "unknown_parent"
    r = c.patch(f"/api/profiles/lines/{LID}", json={"orca_parent": "Overture PLA Pro"}, headers=auth(tok))
    got = r.json()["line"]
    assert got["orca_parent"] == "Overture PLA Pro" and (got["bambu_parent"], got["parent_source"]) == bambu
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Generic PLA", "orca_parent": "Generic PLA"},
                headers=auth(tok))
    assert r.status_code == 200
    line = lines_mod.load()[LID]
    assert (line.bambu_parent, line.orca_parent) == ("Generic PLA", "Generic PLA")
    for bad in ({"orca_parent": ""}, {"orca_parent": 3}, {"orca_parent": "Generic PLA @System"},
                {"bambu_parent": "Generic PLA", "orca_parent": "x" * 101}):
        r = c.patch(f"/api/profiles/lines/{LID}", json=bad, headers=auth(tok))
        assert r.status_code == 400 and r.json()["error"] == "bad_request", bad
    # a refused orca parent leaves the Bambu one unchanged too (one transaction)
    r = c.patch(f"/api/profiles/lines/{LID}", json={"bambu_parent": "Bambu PLA Tough+", "orca_parent": "Nope"},
                headers=auth(tok))
    assert r.status_code == 400 and lines_mod.load()[LID].bambu_parent == "Generic PLA"


def test_patch_orca_parent_stores_the_canonical_spelling(c, sm):
    """Fix I1: a case-insensitive match is stored as the Orca store spells it, so `inherits` resolves."""
    tok = token()
    built(c, tok, sm)
    assert put_zip(c, tok, "system", orca_system_zip(), "?target=orca").status_code == 200
    r = c.patch(f"/api/profiles/lines/{LID}", json={"orca_parent": "overture pla PRO"}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["line"]["orca_parent"] == "Overture PLA Pro"
    assert lines_mod.load()[LID].orca_parent == "Overture PLA Pro"
