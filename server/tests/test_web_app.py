"""web.app: the MCP endpoint through the SDK client over the ASGI app, /health, and the phone intake app
(sign-in, dry-run add, add + tag link, open), LAN-only, Origin and CSP."""
from __future__ import annotations

import json

import anyio
import pytest

pytest.importorskip("mcp")

import httpx2  # noqa: E402
from fakes import readers_fake  # noqa: E402
from fakes.claude_fake import FakeClaude  # noqa: E402
from mcp.client.client import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from filament_kit import config, modules, tags, tagsources  # noqa: E402
from filament_kit.spoolman import Spoolman  # noqa: E402
from filament_kit.web import __main__ as web_main  # noqa: E402
from filament_kit.web import app as web_app, auth  # noqa: E402

PUBLIC = "https://mcp.example.test/filament"
ORIGIN = "https://mcp.example.test"
BASE = "/filament/intake"
HOME = ("192.168.1.20", 50000)
AWAY = ("203.0.113.9", 50000)
PASS = "correct horse battery"
UID = "a:b:c:d:e:f:1"
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
TOOLS = {"find_spools", "add_spools", "tag_state", "open_spool", "preset_status", "list_lines", "find_parents",
         "add_filaments_to_line", "add_line", "generate", "printer_slots", "printer_set_slot", "h2d_slots",
         "h2d_set_slot"}
RULES = {"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 2,
         "overflow": "Overflow", "sealed_location": "Sealed stock"}
READ = {"questions": ["which grey?"], "items": [{
    "photos": [0], "existing_filament_id": None, "vendor": "OVERTURE", "name": "PETG Black", "material": "PETG",
    "color_hex": "111111", "net": 1000, "tare": 155, "density": 1.27, "count": 1, "nozzle": 240, "bed": 75,
    "nozzle_range": "230-250", "bed_range": "70-80", "lot": None, "note": "SKU X", "estimates": [],
    "sealed": True, "sealed_reason": "in bag", "line": "PETG"}]}


@pytest.fixture(autouse=True)
def _sse_not_shutting_down():
    """sse_starlette keeps a process-wide "server is exiting" flag that its uvicorn hook sets on handle_exit
    (test_main_wiring calls it); once set, every SSE reply closes at once. A real process only sets it on its
    own shutdown, so reset it for these tests."""
    from sse_starlette.sse import AppStatus
    AppStatus.should_exit = False
    yield
    AppStatus.should_exit = False


@pytest.fixture
def readers():
    data = readers_fake.new_data()
    with readers_fake.Served(readers_fake.app(data)) as url:
        yield data, url


@pytest.fixture
def env(tmp_path, monkeypatch, readers):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    tagsources._failed.clear()
    data, url = readers
    mods = {n: True for n in modules.MODES["server"]}
    mods["web"] = mods["ai_intake"] = True
    config.save({"placement": RULES, "modules": mods, "tag_sources": [{"name": "printer", "url": url + "/last-tag"}],
                 "web": {"public_url": PUBLIC, "lan": ["192.168.1.0/24"]}})
    (tmp_path / "etc" / "web_passphrase").write_text(auth.hash_passphrase(PASS) + "\n", encoding="utf-8")
    (tmp_path / "etc" / "anthropic_key").write_text("test-key\n", encoding="utf-8")
    return data


@pytest.fixture
def sm(spoolman_url, env):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def store(env):
    return auth.Store(web_app.oauth_file())


@pytest.fixture
def lockout():
    return auth.Lockout()


@pytest.fixture
def fake():
    return FakeClaude(READ)


class CapKit:
    """The kit API's label-read cap and order routes, served from the kit's own ReadCap as api.py does."""

    def _cap(self):
        from filament_kit import intake
        return intake.ReadCap(config.paths().state / "reads.json", config.load()["reads_per_day"])

    def post(self, path, body):
        from filament_kit import intake
        from filament_kit.web.slots import SlotError
        if path == "/api/intake/cap/take":
            try:
                return {"ok": True, "ticket": self._cap().take("web (MCP)")}
            except intake.CapReached as e:
                raise SlotError(str(e), code="daily_cap", http=429) from None
        if path == "/api/intake/cap/refund":
            if self.refund_down:
                raise SlotError("the kit server did not answer", code="unreachable")
            try:
                self._cap().refund(body.get("ticket"), "web (MCP)")
            except intake.RefundRefused as e:
                raise SlotError(str(e), code="refund_refused", http=409) from None
            return {"ok": True}
        raise SlotError("the kit server answered 404", http=404)

    refund_down = orders_down = False

    def get(self, path):
        from filament_kit.web.slots import SlotError
        if path == "/api/intake/orders":
            if self.orders_down:
                raise SlotError("the kit server answered 401", code="unpaired", http=401)
            return {"orders": None}
        raise SlotError("the kit server answered 404", http=404)


@pytest.fixture
def app(sm, store, lockout, fake):
    return web_app.build_app(sm=sm, store=store, lockout=lockout, claude=fake, kit_api=CapKit())


def _token(store) -> str:
    return auth.Provider(store, PUBLIC)._issue("client-1", ["filament"], None).access_token


# ---------- MCP ----------

def _mcp(app, token, fn):
    """Run `fn(client)` against the app served by uvicorn on 127.0.0.1 (real HTTP + SSE and the app's own
    lifespan); the Host header is the public host, as nginx passes it."""
    async def main(url):
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}",
                                               "Host": "mcp.example.test"}) as hc:
            async with Client(streamable_http_client(url + "/mcp", http_client=hc), mode="legacy") as c:
                return await fn(c)
    with readers_fake.Served(app) as url:
        return anyio.run(main, url)


def test_mcp_handshake_and_tools_list(app, store):
    async def run(c):
        listed = await c.list_tools()
        return c.instructions, {t.name: t for t in listed.tools}
    instructions, tools = _mcp(app, _token(store), run)
    assert set(tools) == TOOLS
    assert "find_spools" in instructions and "'Rack 1'" in instructions
    assert tools["find_spools"].annotations.read_only_hint is True
    assert tools["add_spools"].annotations.read_only_hint is False
    props = tools["open_spool"].input_schema["properties"]
    assert set(props) == {"spool", "filament", "location", "gross", "remaining", "humidity", "force", "dry_run"}
    assert set(tools["h2d_set_slot"].input_schema["properties"]) == {"spool", "slot", "dry_run"}
    assert set(tools["add_line"].input_schema["properties"]) == {"name", "vendor", "filament_ids", "orca_parent",
                                                                 "bs_template"}


def test_mcp_calls_reach_kit(app, store):
    async def run(c):
        added = await c.call_tool("add_spools", {"items": [{
            "vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA", "net": 1000, "tare": 213, "density": 1.24,
            "count": 1}], "dry_run": False})
        found = await c.call_tool("find_spools", {"query": "sunlu"})
        refused = await c.call_tool("open_spool", {})
        return added, found, refused
    added, found, refused = _mcp(app, _token(store), run)
    assert not added.is_error and len(json.loads(added.content[0].text)["spool_ids"]) == 1
    assert json.loads(found.content[0].text)["matches"] == 1
    assert refused.is_error and "exactly one of spool or filament" in refused.content[0].text


def test_mcp_needs_token_host_and_origin(app, store):
    tok = _token(store)
    with TestClient(app, base_url=ORIGIN, client=AWAY) as c:
        assert c.post("/mcp", json={}).status_code == 401
        h = {"Authorization": f"Bearer {tok}", "Accept": "application/json, text/event-stream",
             "Content-Type": "application/json"}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
        assert c.post("/mcp", json=init, headers={**h, "Origin": "https://evil.example"}).status_code == 403
        assert c.post("/mcp", json=init, headers={**h, "Host": "evil.example"}).status_code in (400, 421)
        assert c.post("/mcp", json=init, headers={**h, "Origin": "https://claude.ai"}).status_code == 200


def test_health(app):
    with TestClient(app, base_url=ORIGIN, client=AWAY) as c:
        r = c.get("/health")
    assert r.status_code == 200 and r.text == "ok"


def test_uvicorn_options_trust_only_local_proxy():
    o = web_main.uvicorn_options({"web": {"port": 8101}})
    assert o["host"] == "127.0.0.1" and o["port"] == 8101 and o["proxy_headers"] is True
    assert o["forwarded_allow_ips"] == "127.0.0.1" and o["workers"] == 1


def test_build_app_needs_public_url(sm):
    cfg = config.load()
    cfg["web"]["public_url"] = None
    with pytest.raises(web_app.NotConfigured):
        web_app.build_app(cfg, sm=sm)


# ---------- phone intake app ----------

def _client(app, who=HOME):
    return TestClient(app, base_url=ORIGIN, client=who)


def test_page_needs_no_sign_in_and_has_csp(app):
    with _client(app) as c:
        r = c.get("/intake")
        assert r.status_code == 200 and "Passphrase" not in r.text and "Sign out" not in r.text
        assert f"src='{BASE}/app.js'" in r.text and f"data-base='{BASE}'" in r.text
        assert "data-sealed='Sealed stock'" in r.text and "Rack 1" in r.text
        csp = r.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
        assert "set-cookie" not in r.headers
        assert c.get("/intake/app.js").text.startswith("// Spool intake")
        assert c.get("/intake/icon.png").content[:4] == bytes([0x89]) + b"PNG"
        assert c.get("/intake/manifest.webmanifest").json()["start_url"] == BASE


def test_no_sign_in_routes(app):
    with _client(app) as c:
        for path in ("/intake/login", "/intake/logout"):
            assert c.post(path, data={"passphrase": PASS}, headers={"Origin": ORIGIN}).status_code in (404, 405), path


def test_api_answers_without_a_session(app):
    with _client(app) as c:
        r = c.get("/intake/api/vendors")
        assert r.status_code == 200, r.text


def test_lan_only_refusal(app):
    with _client(app, AWAY) as c:
        for path in ("/intake", "/intake/api/find", "/intake/api/vendors", "/login", "/authorize"):
            r = c.get(path)
            assert r.status_code == 403 and "home network" in r.text, path
        r = c.post("/intake/api/add", json={"items": [], "dry_run": True}, headers={"Origin": ORIGIN})
        assert r.status_code == 403


def test_origin_refusal(app):
    with _client(app) as c:
        r = c.post("/intake/api/add", json={"items": [], "dry_run": True}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["error"] == "bad origin"
        assert c.post("/intake/api/add", json={"items": []}).status_code == 403   # no Origin at all


def test_read_add_link_open_flow(app, env, sm, fake):
    data = env
    with _client(app) as c:
        post = {"headers": {"Origin": ORIGIN}}
        # label read: a fresh unknown tap on the reader makes the pictured spool an opened one
        data["tag"] = {"status": "ok", "nfc_id": UID, "read_at_unix": 1, "age_seconds": 8}
        r = c.post("/intake/api/read", files=[("photos", ("a.jpg", JPEG, "image/jpeg"))], data={"hint": "one"}, **post)
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["tag"]["nfc_id"] == UID and res["items"][0]["sealed"] is False
        assert res["questions"] == ["which grey?"] and fake.calls
        items = [dict(it, location="") for it in res["items"]]
        # dry run: nothing written
        r = c.post("/intake/api/add", json={"items": items, "dry_run": True, "link_tag": UID}, **post)
        assert r.status_code == 200, r.text
        assert r.json()["spool_ids"] == [] and f"would link tag {UID}" in r.json()["output"]
        assert sm.get("spool") == []
        # add + link by the new spool's id
        r = c.post("/intake/api/add", json={"items": items, "dry_run": False, "link_tag": UID}, **post)
        assert r.status_code == 200, r.text
        (sid,) = r.json()["spool_ids"]
        s = sm.get(f"spool/{sid}")
        assert tags.stored(s) == UID and s["location"] == "Storage box 01" and s["first_used"]
        # a second, sealed spool to open with the next tap
        r = c.post("/intake/api/add", json={"items": [dict(items[0], sealed=True, name="PETG Red")],
                                            "dry_run": False}, **post)
        (sid2,) = r.json()["spool_ids"]
        uid2 = "4:1:2:3:4:5:6"
        data["tag"] = {"status": "ok", "nfc_id": uid2, "read_at_unix": 2, "age_seconds": 3}
        t = c.get("/intake/api/tag").json()
        assert t["nfc_id"] == uid2 and "not linked" in t["text"] and t["reader"] == "printer"
        found = c.get("/intake/api/find", params={"q": "overture red", "sealed": "1"}).json()
        assert found["filaments"][0]["spools"][0]["spool_id"] == sid2
        r = c.post("/intake/api/open", json={"spool": sid2, "gross": "1100", "location": "", "humidity": "41",
                                             "dry_run": True}, **post)
        assert r.status_code == 200 and tags.stored(sm.get(f"spool/{sid2}")) is None
        r = c.post("/intake/api/open", json={"spool": sid2, "gross": "1100", "location": "", "humidity": "41",
                                             "dry_run": False}, **post)
        assert r.status_code == 200, r.text
        s2 = sm.get(f"spool/{sid2}")
        assert tags.stored(s2) == uid2 and s2["remaining_weight"] == 945 and s2["location"] == "Storage box 02"
        assert json.loads(s2["extra"]["box_humidity"]) == 41
        # the first tag again on another spool: refused (no force from the phone)
        data["tag"] = {"status": "ok", "nfc_id": UID, "read_at_unix": 3, "age_seconds": 1}
        r = c.post("/intake/api/open", json={"spool": sid2, "dry_run": False}, **post)
        assert r.status_code == 409 and "already" in r.json()["error"]


def test_bad_inputs_are_400(app):
    with _client(app) as c:
        post = {"headers": {"Origin": ORIGIN}}
        r = c.post("/intake/api/add", json={"items": [{"vendor": "X", "name": "Y", "material": "PLA"}]}, **post)
        assert r.status_code == 400 and "net" in r.json()["error"]
        assert c.post("/intake/api/open", json={"spool": "x"}, **post).status_code == 400
        r = c.post("/intake/api/read", files=[("photos", ("a.heic", b"\x89PNG....", "image/heic"))], **post)
        assert r.status_code == 400 and "a.heic" in r.json()["error"]


def test_start_pairs_for_the_bridge_and_skips_it_with_a_slot_service(env, monkeypatch):
    from filament_kit import pairing
    from filament_kit.web import slots
    pairing.make_cert("fkhost", [], config.paths().etc)
    cfg = config.load()                                          # printers on, no slot_service
    kit = web_main.kit_api_at_start(cfg)
    assert isinstance(kit, slots.KitApi)
    assert [d["name"] for d in pairing.devices()] == ["web (MCP)"]
    assert (config.paths().web / "kit_token").is_file()
    cfg["slot_service"] = {"state_url": "http://x/api/state", "set_url": "http://x/set", "token_file": "/x"}
    assert web_main.kit_api_at_start(cfg) is None
    cfg["slot_service"] = None
    cfg["modules"]["printers"] = False
    assert web_main.kit_api_at_start(cfg) is None


def test_start_survives_a_pairing_failure(env, caplog):
    import logging
    # no server certificate: pairing fails; logged, the unit still starts
    with caplog.at_level(logging.ERROR, logger="filament_kit"):
        assert web_main.kit_api_at_start(config.load()) is not None
    assert any("cannot pair" in r.getMessage() for r in caplog.records)


# ---------- fix round 1 ----------

def test_web_numbers_and_line_bodies_are_checked(app, sm):
    with _client(app) as c:
        post = {"headers": {"Origin": ORIGIN}}
        for bad in ("nan", "inf", "-Infinity"):
            r = c.post("/intake/api/open", json={"spool": 1, "gross": bad, "dry_run": True}, **post)
            assert r.status_code == 400 and "gross" in r.json()["error"], bad
        for path, body in (("line_add", {}), ("line_add", {"line": "X", "ids": "1"}),
                           ("line_add", {"line": 5, "ids": [1]}), ("line_new", {"name": "A B", "ids": [1]}),
                           ("line_new", {"name": "A B", "vendor": "A", "ids": [True], "bs_template": "x"})):
            r = c.post(f"/intake/api/{path}", json=body, **post)
            assert r.status_code == 400, (path, body, r.text)


def test_web_unexpected_errors_are_generic(app, monkeypatch, caplog):
    import logging
    from filament_kit.web import mcp_tools as mt

    def boom(self, *a, **kw):
        raise KeyError("secret detail")
    monkeypatch.setattr(mt.Tools, "find_spools", boom)
    with _client(app) as c:
        with caplog.at_level(logging.ERROR, logger="filament_kit"):
            r = c.get("/intake/api/find")
    assert r.status_code == 500 and "secret detail" not in r.text
    assert any("intake" in rec.getMessage() for rec in caplog.records)


def test_web_read_refunds_only_when_claude_was_not_reached(app, sm, fake, monkeypatch):
    from filament_kit.spoolman import SpoolmanError
    reads = config.paths().state / "reads.json"

    def count():
        return len(json.loads(reads.read_text())) if reads.exists() else 0
    with _client(app) as c:
        post = {"headers": {"Origin": ORIGIN}}
        photo = [("photos", ("a.jpg", JPEG, "image/jpeg"))]
        fake.raises = RuntimeError("Claude blew up after the call")       # Claude was reached: no refund
        assert c.post("/intake/api/read", files=photo, **post).status_code == 500
        assert count() == 1
        fake.raises = None
        orig = sm.get

        def down(path, *a, **kw):
            if "filament" in path:
                raise SpoolmanError("spoolman_unreachable", status=None)
            return orig(path, *a, **kw)
        monkeypatch.setattr(sm, "get", down)                             # catalog fetch fails: refunded
        r = c.post("/intake/api/read", files=photo, **post)
        assert r.status_code == 400 and count() == 1


def test_web_read_gives_the_cap_back_when_claude_is_unreachable(app, fake):
    import anthropic
    reads = config.paths().state / "reads.json"
    fake.raises = anthropic.APIConnectionError(request=None)
    with _client(app) as c:
        r = c.post("/intake/api/read", files=[("photos", ("a.jpg", JPEG, "image/jpeg"))],
                   headers={"Origin": ORIGIN})
    assert r.status_code >= 400
    assert not reads.exists() or len(json.loads(reads.read_text())) == 0


def test_web_read_goes_on_without_orders_when_the_kit_cannot_give_them(sm, store, lockout, fake):
    kit = CapKit()
    kit.orders_down = True
    app = web_app.build_app(sm=sm, store=store, lockout=lockout, claude=fake, kit_api=kit)
    with _client(app) as c:
        r = c.post("/intake/api/read", files=[("photos", ("a.jpg", JPEG, "image/jpeg"))],
                   headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    assert fake.calls


def test_web_read_failed_refund_never_hides_the_spoolman_error(sm, store, lockout, fake, monkeypatch, caplog):
    from filament_kit.spoolman import SpoolmanError
    kit = CapKit()
    kit.refund_down = True
    app = web_app.build_app(sm=sm, store=store, lockout=lockout, claude=fake, kit_api=kit)
    orig = sm.get

    def down(path, *a, **kw):
        if "filament" in path:
            raise SpoolmanError("spoolman_unreachable", status=None)
        return orig(path, *a, **kw)
    monkeypatch.setattr(sm, "get", down)
    with _client(app) as c:
        r = c.post("/intake/api/read", files=[("photos", ("a.jpg", JPEG, "image/jpeg"))],
                   headers={"Origin": ORIGIN})
    assert r.status_code == 400 and "spoolman" in r.text.lower(), r.text
    # the cap is taken only just before a cloud read, after the catalog fetch: Spoolman down uses no read at all
    from filament_kit import intake
    assert intake.reads_today(config.paths().state / "reads.json") == 0


def test_ai_off_page_hides_reading_and_manual_add_works(app, env, sm):
    """R1: without ai_intake the page says so (no photo read), label reading is refused, and a spool added by
    hand (vendor, name, material, weights; or an existing filament picked from the list) is saved."""
    cfg = config.load()
    cfg["modules"]["ai_intake"] = False
    config.save(cfg)
    with _client(app) as c:
        post = {"headers": {"Origin": ORIGIN}}
        assert "data-ai='0'" in c.get("/intake").text
        r = c.post("/intake/api/read", files=[("photos", ("a.jpg", JPEG, "image/jpeg"))], **post)
        assert r.status_code == 400 and "ai_intake" in r.json()["error"]
        item = {"vendor": "Elegoo", "name": "PLA Red", "material": "PLA", "net": "1000", "tare": "160",
                "density": "1.24", "count": "2", "sealed": True, "location": "", "color_hex": "cc0000"}
        r = c.post("/intake/api/add", json={"items": [item], "dry_run": False}, **post)
        assert r.status_code == 200, r.text
        assert len(r.json()["spool_ids"]) == 2
        fils = c.get("/intake/api/filaments", params={"q": "elegoo"}).json()["filaments"]
        assert [(f["vendor"], f["name"], f["tare"], f["spools"]) for f in fils] == [("Elegoo", "PLA Red", 160, 2)]
        assert [v["name"] for v in c.get("/intake/api/vendors").json()["vendors"]] == ["Elegoo"]
        cfg["modules"]["ai_intake"] = True
        config.save(cfg)
        assert "data-ai='1'" in c.get("/intake").text


# ---------- R1 minors: the manual add's picker ----------

def test_picker_tare_falls_back_to_the_vendor_and_vendorless_filaments_are_listed(app, sm):
    v = sm.post("vendor", {"name": "SUNLU", "empty_spool_weight": 213})
    sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA+", "density": 1.24})
    sm.post("filament", {"name": "PETG Blue", "vendor_id": v["id"], "material": "PETG", "density": 1.27,
                         "spool_weight": 180})
    sm.post("filament", {"name": "Mystery PLA", "material": "PLA", "density": 1.24})
    with _client(app) as c:
        fils = c.get("/intake/api/filaments").json()["filaments"]
    by = {f["name"]: f for f in fils}
    assert by["PLA+ Grey"]["tare"] == 213             # no spool weight of its own: the vendor's empty spool
    assert by["PETG Blue"]["tare"] == 180             # its own wins
    assert by["Mystery PLA"]["vendor"] == "" and by["Mystery PLA"]["tare"] is None   # listed, not dropped


def test_picker_routes_refuse_off_lan(app):
    with _client(app, AWAY) as c:
        for path in ("/intake/api/filaments", "/intake/api/vendors", "/intake/api/presets", "/intake/api/parents",
                     "/intake/api/tag"):
            r = c.get(path)
            assert r.status_code == 403 and "home network" in r.text, path


def _node():
    import shutil
    return shutil.which("node")


@pytest.mark.skipif(not _node(), reason="needs node")
def test_density_lookup_matches_by_prefix():
    """A material with no exact entry gets the density of the longest known material it starts with."""
    import re
    import subprocess
    from pathlib import Path
    src = (Path(web_app.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    table = re.search(r"^const DENSITY = .*?;$", src, re.M).group(0)
    fn = re.search(r"^function densityFor\(.*?^}$", src, re.M | re.S).group(0)
    probe = ["PLA", "pla+", "PLA Silk", "PETG-CF", "PA6-GF", "ASA", "Wood", "", " petg ", "PCTG", "pctg-cf", "PC"]
    js = f"{table}\n{fn}\nconsole.log(JSON.stringify({json.dumps(probe)}.map(densityFor)));"
    out = subprocess.run([_node(), "-e", js], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == [1.24, 1.24, 1.24, 1.27, 1.14, 1.07, None, None, 1.27, 1.23, 1.23, 1.2]


def test_picker_names_filaments_without_a_vendor():
    from pathlib import Path
    src = (Path(web_app.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert '"(no vendor)"' in src


# ---------- the public prefix (nginx strips it) ----------

def test_intake_with_a_slash_is_refused_off_the_lan(app):
    """The redirect itself (kept within the public prefix) is test_slash_redirects_stay_within_the_public_prefix."""
    assert _client(app, AWAY).get("/intake/", follow_redirects=False).status_code == 403


def test_router_streams_sse_under_the_public_prefix():
    """The Printers tab's live status (SSE) goes through the router's route: no buffering, and a read timeout far
    above the stream's keep-alive ping; /<name> without a slash gets nginx's own redirect to /<name>/ (a prefix
    location ending in a slash with proxy_pass)."""
    import re
    from pathlib import Path
    from filament_kit.web import printers_app
    remote = Path(__file__).resolve().parents[2] / "install" / "remote"
    route = (remote / "route.template").read_text(encoding="utf-8")
    proxy = (remote / "mcp-proxy.conf").read_text(encoding="utf-8")
    assert re.search(r"location \^~ /@NAME@/ \{\s*proxy_pass http://127\.0\.0\.1:@PORT@/;", route)
    assert route.count("include /etc/nginx/mcp-proxy.conf;") == 3
    assert "proxy_buffering off;" in proxy and "proxy_cache off;" in proxy
    timeout = int(re.search(r"proxy_read_timeout (\d+)s;", proxy).group(1))
    assert timeout >= 10 * printers_app.PING_SECONDS
    assert 'proxy_set_header Connection "";' in proxy and "proxy_http_version 1.1;" in proxy


@pytest.mark.parametrize("path, target", [("/reader/printers/", "/filament/reader/printers"),
                                          ("/intake/", BASE)])
def test_slash_redirects_stay_within_the_public_prefix(app, path, target):
    """M4: the app runs with the public path as its root_path, so every slash redirect keeps the prefix nginx
    strips (not only /intake/)."""
    with _client(app) as c:
        r = c.get(path, follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308), (r.status_code, r.text[:200])
    assert r.headers["location"] in (target, ORIGIN + target), r.headers["location"]


def test_a_link_can_open_a_tab_by_its_hash():
    """The setup page's "Open the live printer view" links /intake#printers; only a tab the page has is taken."""
    from pathlib import Path
    src = (Path(web_app.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "if (Object.hasOwn(tabs, location.hash.slice(1))) first = location.hash.slice(1);" in src
