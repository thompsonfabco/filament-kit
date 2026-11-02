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

from conftest import free_port  # noqa: E402
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
UID = "4:77:90:e:9:22:89"
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


@pytest.fixture
def readers():
    data = readers_fake.new_data()
    with readers_fake.Served(readers_fake.app(data), free_port()) as url:
        yield data, url


@pytest.fixture
def env(tmp_path, monkeypatch, readers):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    tagsources._failed.clear()
    data, url = readers
    mods = {n: True for n in modules.MODES["server"]}
    mods["web"] = True
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


@pytest.fixture
def app(sm, store, lockout, fake):
    return web_app.build_app(sm=sm, store=store, lockout=lockout, claude=fake)


def _token(store) -> str:
    return auth.Provider(store, PUBLIC)._issue("client-1", ["filament"], None).access_token


# ---------- MCP ----------

def _mcp(app, token, fn):
    async def main():
        async with _lifespan(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app, client=AWAY),
                                          base_url=ORIGIN, headers={"Authorization": f"Bearer {token}"}) as hc:
                async with Client(streamable_http_client(ORIGIN + "/mcp", http_client=hc), mode="legacy") as c:
                    return await fn(c)
    return anyio.run(main)


class _lifespan:
    """Run the inner Starlette app's lifespan (the MCP session manager) around an ASGI test."""

    def __init__(self, app):
        self.app = app
        self.queue_in: list = []

    async def __aenter__(self):
        self._send, self._recv = anyio.create_memory_object_stream(10)
        self._out_send, self._out_recv = anyio.create_memory_object_stream(10)
        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()

        async def receive():
            return await self._recv.receive()

        async def send(msg):
            await self._out_send.send(msg)
        self._tg.start_soon(self.app, {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)
        await self._send.send({"type": "lifespan.startup"})
        msg = await self._out_recv.receive()
        assert msg["type"] == "lifespan.startup.complete", msg
        return self

    async def __aexit__(self, *exc):
        await self._send.send({"type": "lifespan.shutdown"})
        await self._out_recv.receive()
        await self._tg.__aexit__(None, None, None)


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


def _sign_in(c) -> str:
    r = c.post("/intake/login", data={"passphrase": PASS}, headers={"Origin": ORIGIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == BASE
    cookie = r.headers["set-cookie"]
    low = cookie.lower()
    assert "secure" in low and "httponly" in low and "samesite=strict" in low
    assert f"path={BASE}" in low and "max-age=2592000" in low
    tok = cookie.split(";")[0].split("=", 1)[1]
    c.cookies.set("fi_session", tok)    # the cookie's path is the public one (nginx strips /filament)
    return tok


def test_page_signed_out_then_in_with_csp(app):
    with _client(app) as c:
        r = c.get("/intake")
        assert r.status_code == 200 and "Passphrase" in r.text and "app.js" not in r.text
        csp = r.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
        _sign_in(c)
        r = c.get("/intake")
        assert f"src='{BASE}/app.js'" in r.text and f"data-base='{BASE}'" in r.text
        assert "data-sealed='Sealed stock'" in r.text and "Rack 1" in r.text
        assert r.headers["content-security-policy"] == csp
        assert c.get("/intake/app.js").text.startswith("// Spool intake")
        assert c.get("/intake/icon.png").content[:4] == b"\x89PNG"
        assert c.get("/intake/manifest.webmanifest").json()["start_url"] == BASE


def test_login_wrong_passphrase_and_shared_lockout(app, lockout):
    with _client(app) as c:
        for _ in range(5):
            r = c.post("/intake/login", data={"passphrase": "wrong one!!!"}, headers={"Origin": ORIGIN})
            assert r.status_code == 401
        r = c.post("/intake/login", data={"passphrase": PASS}, headers={"Origin": ORIGIN})
        assert r.status_code == 429
        assert lockout.blocked()               # the same count /login reads
        r = c.post("/login", data={"req": "x", "passphrase": PASS}, headers={"Origin": ORIGIN})
        assert r.status_code in (400, 429)     # the request is unknown; never a sign-in


def test_lan_only_refusal(app):
    with _client(app, AWAY) as c:
        for path in ("/intake", "/intake/api/find", "/login", "/authorize"):
            r = c.get(path)
            assert r.status_code == 403 and "home network" in r.text, path
        assert c.post("/intake/login", data={"passphrase": PASS}, headers={"Origin": ORIGIN}).status_code == 403


def test_origin_refusal(app):
    with _client(app) as c:
        assert c.post("/intake/login", data={"passphrase": PASS},
                      headers={"Origin": "https://evil.example"}).status_code == 403
        _sign_in(c)
        r = c.post("/intake/api/add", json={"items": [], "dry_run": True}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["error"] == "bad origin"
        assert c.post("/intake/api/add", json={"items": []}).status_code == 403   # no Origin at all


def test_api_needs_session(app):
    with _client(app) as c:
        r = c.get("/intake/api/find")
        assert r.status_code == 401 and "signed out" in r.json()["error"]


def test_read_add_link_open_flow(app, env, sm, fake):
    data = env
    with _client(app) as c:
        _sign_in(c)
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
        _sign_in(c)
        post = {"headers": {"Origin": ORIGIN}}
        r = c.post("/intake/api/add", json={"items": [{"vendor": "X", "name": "Y", "material": "PLA"}]}, **post)
        assert r.status_code == 400 and "net" in r.json()["error"]
        assert c.post("/intake/api/open", json={"spool": "x"}, **post).status_code == 400
        r = c.post("/intake/api/read", files=[("photos", ("a.heic", b"\x89PNG....", "image/heic"))], **post)
        assert r.status_code == 400 and "a.heic" in r.json()["error"]


def test_logout_ends_session(app, store):
    with _client(app) as c:
        tok = _sign_in(c)
        assert store.check_session(tok)
        r = c.post("/intake/logout", headers={"Origin": ORIGIN}, follow_redirects=False)
        assert r.status_code == 303 and not store.check_session(tok)
