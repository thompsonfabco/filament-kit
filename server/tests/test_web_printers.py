"""web.printers_app: the Printers tab of the phone web app, over a fake kit API (no printer, no kit server).

Session, LAN, Origin and CSP come from the intake app; these tests pin the printer routes, the SSE status stream,
the camera proxy, the controls (stop needs confirm), usage + re-map, and Web Push (off by default; allow-list)."""
from __future__ import annotations

import asyncio
import copy
import io
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from starlette.testclient import TestClient  # noqa: E402

from filament_kit import config, modules  # noqa: E402
from filament_kit.web import app as web_app, auth  # noqa: E402
from filament_kit.web.slots import SlotError  # noqa: E402

PUBLIC = "https://mcp.example.test/filament"
ORIGIN = "https://mcp.example.test"
BASE = "/filament/intake"
HOME = ("192.168.1.20", 50000)
AWAY = ("203.0.113.9", 50000)
PASS = "correct horse battery"
SERIAL = "0948ZZ0A0000001"
OTHER = "03W00X123456789"
STATIC = Path(__file__).resolve().parent.parent / "filament_kit" / "web" / "static"

STATUS = {"gcode_state": "RUNNING", "stage": "Printing", "job": "benchy", "percent": 42, "layer": 10,
          "total_layers": 50, "remaining_min": 30, "eta": None, "temps": [{"name": "Nozzle", "cur": 200, "tgt": 220}],
          "ams": [{"unit": 0, "label": "AMS A", "kind": "ams", "type_name": "AMS", "say": [], "slots": [
              {"slot": 0, "label": "A1", "say": [], "type": "PLA", "color_hex": "FF0000", "active": True,
               "present": True, "reading": False,
               "spool": {"id": 7, "name": "Overture PLA Red", "material": "PLA", "color_hex": "FF0000",
                         "remaining_weight": 612.0}}]}],
          "presence": "bits", "notes": [], "hms": [], "light": "off", "updated": 1}


class FakeKit:
    """Stands in for slots.KitApi: records calls, answers from `routes`."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.status = copy.deepcopy(STATUS)
        self.down = False
        self.camera = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + b"J" * 40000 + b"\r\n"
        self.closed = 0

    def _check(self):
        if self.down:
            raise SlotError("the kit server (https://127.0.0.1:1) is not reachable: refused")

    def get(self, path):
        self._check()
        self.calls.append(("GET", path))
        if path == "/api/printers":
            return {"printers": [
                {"id": SERIAL, "name": "H2D", "model": "O1D", "configured": True, "state": "connected",
                 "camera": {"kind": "hls"}, "summary": None, "ip": "10.0.0.1", "serial": SERIAL},
                {"id": OTHER, "name": "X1", "model": "BL-P001", "configured": False, "state": "not_configured",
                 "camera": {"kind": "mjpeg"}, "summary": None, "ip": "10.0.0.2", "serial": OTHER}]}
        if path in (f"/api/printers/{SERIAL}",):
            return {"printer": {"id": SERIAL, "name": "H2D", "model": "O1D", "state": "connected",
                                "camera": {"kind": "hls"}}, "status": copy.deepcopy(self.status), "hardware": {}}
        if path.startswith(f"/api/printers/{SERIAL}/usage"):
            return {"entries": [{"id": "u1", "at": "2026-11-02T10:00:00", "job": "benchy", "undone": False}]}
        if path == f"/api/printers/{SERIAL}/map":
            return {"state": "none", "step": "", "slots": [], "problems": []}
        raise SlotError("the kit server answered 404")

    def post(self, path, body):
        self._check()
        self.calls.append(("POST", path, body))
        if path == f"/api/printers/{SERIAL}/command":
            return {"ok": True, "reply": {"ok": True, "reply": {"result": "success"}}}
        if path == f"/api/printers/{SERIAL}/map":
            return {"job_id": "j1"}
        if path == "/api/usage/u1/undo":
            return {"entry": {"id": "u1", "undone": True}}
        raise SlotError("the kit server answered 404")

    def raw(self, path):
        self._check()
        self.calls.append(("RAW", path))
        outer = self

        class R(io.BytesIO):
            def close(self):
                outer.closed += 1
                super().close()
        ctype = ("application/vnd.apple.mpegurl" if path.endswith(".m3u8") else
                 "video/mp2t" if path.endswith(".ts") else "multipart/x-mixed-replace; boundary=frame")
        return 200, ctype, R(self.camera)


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: True for n in modules.MODES["server"]}
    mods["web"] = True
    config.save({"modules": mods, "web": {"public_url": PUBLIC, "lan": ["192.168.1.0/24"]}})
    (tmp_path / "etc" / "web_passphrase").write_text(auth.hash_passphrase(PASS) + "\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def kit():
    return FakeKit()


def make_app(env, kit, **web_cfg):
    cfg = config.load()
    cfg["web"] = {**cfg["web"], **web_cfg}
    config.save(cfg)
    from filament_kit.spoolman import Spoolman
    return web_app.build_app(cfg, sm=Spoolman("http://127.0.0.1:9"), store=auth.Store(web_app.oauth_file()),
                             lockout=auth.Lockout(), kit_api=kit)


@pytest.fixture
def app(env, kit):
    return make_app(env, kit)


def signed(app, who=HOME):
    """A client on the home network (the web app has no sign-in)."""
    return TestClient(app, base_url=ORIGIN, client=who)


P = "/intake/api/printers"
H = {"Origin": ORIGIN}


# ---------- the tab ----------

def test_printers_module_default_on_for_server_mode():
    assert "printers" in modules.MODES["server"]


def test_page_shows_the_tab_with_the_printers_module(app):
    c = signed(app)
    body = c.get("/intake").text
    assert "data-printers='1'" in body and "data-push='0'" in body


def test_page_hides_the_tab_without_the_printers_module(env, kit):
    cfg = config.load()
    cfg["modules"]["printers"] = False
    config.save(cfg)
    c = signed(make_app(env, kit))
    assert "data-printers='0'" in c.get("/intake").text
    assert c.get(P).status_code == 404
    assert c.get(P + f"/{SERIAL}/camera.mjpeg").status_code == 404
    assert "printers.js" not in c.get("/intake").text


def test_csp_adds_only_media_src_self_with_the_printers_tab(app, env, kit):
    from filament_kit.web import intake_app
    base = intake_app.HEADERS["Content-Security-Policy"]
    csp = signed(app).get("/intake").headers["content-security-policy"]
    assert "media-src 'self';" in csp and "unsafe" not in csp
    assert csp.replace(" media-src 'self';", "") == base
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    cfg = config.load()
    cfg["modules"]["printers"] = False
    config.save(cfg)
    off = signed(make_app(env, kit)).get("/intake").headers["content-security-policy"]
    assert off == base and "media-src" not in off


def test_camera_branches_on_the_kit_kind_in_the_script():
    src = (STATIC / "printers.js").read_text(encoding="utf-8")
    for needle in ('"mjpeg"', '"hls"', 'canPlayType("application/vnd.apple.mpegurl")', "playsInline", "autoplay",
                   'removeAttribute("src")', ".load()", "camera/index.m3u8"):
        assert needle in src, needle
    assert 'camBtn.classList.toggle("hidden", !camKind())' in src      # no kind, no button


def test_list_carries_the_kit_camera_kind(app):
    c = signed(app)
    assert c.get(P).json()["printers"][0]["camera"] == {"kind": "hls"}


def test_script_never_uses_innerhtml():
    for name in ("app.js", "printers.js"):
        lines = (STATIC / name).read_text(encoding="utf-8").splitlines()
        src = " ".join(ln for ln in lines if not ln.lstrip().startswith("//"))
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", src), name


# ---------- access ----------

def test_routes_need_lan_and_origin(app, kit):
    home = signed(app)
    assert TestClient(app, base_url=ORIGIN, client=AWAY).get(P).status_code == 403
    assert TestClient(app, base_url=ORIGIN, client=AWAY).get(P + f"/{SERIAL}/camera.mjpeg").status_code == 403
    r = home.post(P + f"/{SERIAL}/command", json={"action": "pause"})
    assert r.status_code == 403 and r.json()["error"] == "bad origin"
    r = home.post(P + f"/{SERIAL}/command", json={"action": "pause"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert not [x for x in kit.calls if x[0] == "POST"]


def test_bad_serial_is_refused_before_the_kit_is_called(app, kit):
    c = signed(app)
    for bad in ("..%2f..", "a b", "x" * 80):
        assert c.get(P + f"/{bad}/state").status_code in (400, 404)
    assert not kit.calls


# ---------- list + state ----------

def test_printer_list_has_configured_printers_only(app):
    c = signed(app)
    r = c.get(P)
    assert r.status_code == 200
    ps = r.json()["printers"]
    assert [p["id"] for p in ps] == [SERIAL] and ps[0]["name"] == "H2D"
    assert "ip" not in ps[0] and "access_code" not in json.dumps(r.json())


def test_state_returns_units_with_filament(app):
    c = signed(app)
    r = c.get(P + f"/{SERIAL}/state")
    st = r.json()["status"]
    assert r.json()["printer"]["name"] == "H2D"
    assert st["ams"][0]["slots"][0]["spool"]["remaining_weight"] == 612.0


def test_kit_down_is_a_readable_error(app, kit):
    c = signed(app)
    kit.down = True
    r = c.get(P + f"/{SERIAL}/state")
    assert r.status_code == 502 and "not reachable" in r.json()["error"]


# ---------- controls ----------

@pytest.mark.parametrize("action", ["pause", "resume", "light_on", "light_off"])
def test_simple_commands_go_to_the_kit(app, kit, action):
    c = signed(app)
    r = c.post(P + f"/{SERIAL}/command", json={"action": action}, headers=H)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert ("POST", f"/api/printers/{SERIAL}/command", {"action": action}) in kit.calls


def test_stop_needs_confirm(app, kit):
    c = signed(app)
    for body in ({"action": "stop"}, {"action": "stop", "confirm": "yes"}, {"action": "stop", "confirm": False}):
        r = c.post(P + f"/{SERIAL}/command", json=body, headers=H)
        assert r.status_code == 400 and "confirm" in r.json()["error"]
    assert not [x for x in kit.calls if x[0] == "POST"]
    r = c.post(P + f"/{SERIAL}/command", json={"action": "stop", "confirm": True}, headers=H)
    assert r.status_code == 200
    assert ("POST", f"/api/printers/{SERIAL}/command", {"action": "stop"}) in kit.calls


def test_unknown_action_and_bad_body(app, kit):
    c = signed(app)
    assert c.post(P + f"/{SERIAL}/command", json={"action": "format_disk"}, headers=H).status_code == 400
    assert c.post(P + f"/{SERIAL}/command", content=b"nope", headers=H).status_code == 400
    assert not [x for x in kit.calls if x[0] == "POST"]


# ---------- usage + re-map ----------

def test_usage_list_and_undo(app, kit):
    c = signed(app)
    r = c.get(P + f"/{SERIAL}/usage")
    assert r.json()["entries"][0]["id"] == "u1"
    assert ("GET", f"/api/printers/{SERIAL}/usage") in kit.calls
    r = c.post(P + f"/{SERIAL}/usage/u1/undo", headers=H)
    assert r.status_code == 200 and r.json()["entry"]["undone"] is True
    assert c.post(P + f"/{SERIAL}/usage/..%2fx/undo", headers=H).status_code in (400, 404)


def test_remap_calls_the_map_route(app, kit):
    c = signed(app)
    r = c.post(P + f"/{SERIAL}/map", headers=H)
    assert r.status_code == 200 and r.json()["job_id"] == "j1"
    assert ("POST", f"/api/printers/{SERIAL}/map", {}) in kit.calls
    assert c.get(P + f"/{SERIAL}/map").json()["state"] == "none"


# ---------- camera ----------

def test_mjpeg_is_proxied_and_the_upstream_closed(app, kit):
    c = signed(app)
    r = c.get(P + f"/{SERIAL}/camera.mjpeg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert r.content == kit.camera and ("RAW", f"/api/printers/{SERIAL}/camera.mjpeg") in kit.calls
    assert kit.closed == 1


def test_hls_names_are_checked(app, kit):
    c = signed(app)
    r = c.get(P + f"/{SERIAL}/camera/index.m3u8")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert c.get(P + f"/{SERIAL}/camera/seg00001.ts").headers["content-type"] == "video/mp2t"
    assert c.get(P + f"/{SERIAL}/camera/..%2fstate").status_code in (400, 404)
    assert c.get(P + f"/{SERIAL}/camera/x.txt").status_code == 400


def test_camera_off_the_lan_is_refused(app, kit):
    signed(app)
    assert TestClient(app, base_url=ORIGIN, client=AWAY).get(P + f"/{SERIAL}/camera.mjpeg").status_code == 403
    assert not [x for x in kit.calls if x[0] == "RAW"]


# ---------- SSE ----------

def test_event_stream_polls_pings_and_stops(env, kit):
    from filament_kit.web import printers_app
    pa = printers_app.PrintersApp(None, kit)
    pa.poll, pa.ping = 0.02, 0.1

    async def run():
        alive = {"v": True}

        async def is_alive():
            return alive["v"]
        out = []
        gen = pa.events(SERIAL, is_alive)
        async for chunk in gen:
            out.append(chunk)
            if len(out) == 1:
                kit.status["percent"] = 43          # a change -> a second data event
            if len(out) >= 4:
                alive["v"] = False
        return out
    out = asyncio.run(run())
    assert out[0].startswith("data: ") and json.loads(out[0][6:])["status"]["percent"] == 42
    assert any(o.startswith("data: ") and json.loads(o[6:])["status"]["percent"] == 43 for o in out[1:])
    assert any(o.startswith(": ping") for o in out)
    polls = len([x for x in kit.calls if x == ("GET", f"/api/printers/{SERIAL}")])
    assert polls >= 2
    after = len(kit.calls)
    asyncio.run(asyncio.sleep(0.15))
    assert len(kit.calls) == after                  # no client, no polling
    assert pa.streams == 0


def test_event_stream_throttle_is_one_second_by_default(env, kit):
    from filament_kit.web import printers_app
    assert printers_app.POLL_SECONDS >= 1.0 and printers_app.PING_SECONDS == 25.0


def test_event_stream_survives_a_kit_outage(env, kit):
    from filament_kit.web import printers_app
    pa = printers_app.PrintersApp(None, kit)
    pa.poll, pa.ping = 0.01, 5
    kit.down = True

    async def run():
        n = {"i": 0}

        async def alive():
            n["i"] += 1
            return n["i"] < 4
        return [c async for c in pa.events(SERIAL, alive)]
    out = asyncio.run(run())
    assert out and "not reachable" in json.loads(out[0][6:])["error"]


def test_events_route_over_http(env, kit):
    """Real HTTP: the stream starts with a data event, and a closed client ends the server side."""
    import httpx2
    from fakes import readers_fake
    from conftest import free_port
    app = make_app(env, kit)

    async def main(url):
        async with httpx2.AsyncClient(headers={"Host": "mcp.example.test", "X-Forwarded-For": "192.168.1.20"}) as hc:
            async with hc.stream("GET", url + "/intake/api/printers/" + SERIAL + "/events") as s:
                assert s.status_code == 200 and s.headers["content-type"].startswith("text/event-stream")
                async for line in s.aiter_lines():
                    if line.startswith("data: "):
                        return json.loads(line[6:])
    with readers_fake.Served(app, free_port()) as url:
        ev = asyncio.run(main(url))
    assert ev["status"]["gcode_state"] == "RUNNING"


# ---------- Web Push ----------

def test_push_off_by_default_runs_no_push_code(env, kit):
    sys.modules.pop("filament_kit.web.push", None)
    app = make_app(env, kit)
    c = signed(app)
    assert "data-push='0'" in c.get("/intake").text
    for path in ("/push/key",):
        assert c.get(P + path).status_code == 404
    assert c.post(P + "/push/subscribe", json={}, headers=H).status_code == 404
    assert "filament_kit.web.push" not in sys.modules


@pytest.fixture
def pushapp(env, kit, monkeypatch):
    app = make_app(env, kit, push=True)
    from filament_kit.web import push
    monkeypatch.setattr(push, "available", lambda: True)
    return app


def good_sub(host="fcm.googleapis.com"):
    return {"subscription": {"endpoint": f"https://{host}/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}}}


def test_push_subscribe_allow_list(pushapp):
    c = signed(pushapp)
    assert "data-push='1'" in c.get("/intake").text
    key = c.get(P + "/push/key").json()["key"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{80,100}", key)
    for host in ("fcm.googleapis.com", "web.push.apple.com", "updates.push.services.mozilla.com",
                 "wns2.notify.windows.com"):
        assert c.post(P + "/push/subscribe", json=good_sub(host), headers=H).status_code == 200, host
    for host in ("evil.example", "fcm.googleapis.com.evil.example", "169.254.169.254", "notpush.apple.com"):
        r = c.post(P + "/push/subscribe", json=good_sub(host), headers=H)
        assert r.status_code == 400, host
    bad = good_sub()
    bad["subscription"]["endpoint"] = "http://fcm.googleapis.com/x"
    assert c.post(P + "/push/subscribe", json=bad, headers=H).status_code == 400
    nokeys = good_sub()
    nokeys["subscription"]["keys"] = {}
    assert c.post(P + "/push/subscribe", json=nokeys, headers=H).status_code == 400


def test_push_store_unsubscribe_and_file_mode(pushapp, env):
    c = signed(pushapp)
    c.post(P + "/push/subscribe", json=good_sub(), headers=H)
    f = config.paths().web / "push.json"
    assert f.exists() and "fcm.googleapis.com" in f.read_text()
    if sys.platform != "win32":
        assert (f.stat().st_mode & 0o777) == 0o600
    c.post(P + "/push/unsubscribe", json={"endpoint": good_sub()["subscription"]["endpoint"]}, headers=H)
    assert json.loads(f.read_text())["subs"] == {}


def test_push_transitions():
    from filament_kit.web import push
    t = push.transitions
    assert t(None, {"gcode_state": "RUNNING", "hms": [], "job": "a", "percent": 5}) == []
    base = {"gcode_state": "RUNNING", "hms": [], "job": "benchy", "percent": 50}
    assert t(base, {**base, "gcode_state": "FINISH"})[0][0] == "Print finished"
    assert t(base, {**base, "gcode_state": "FAILED"})[0][0] == "Print stopped"
    assert t(base, {**base, "gcode_state": "PAUSE"})[0][0] == "Print paused"
    assert t({**base, "gcode_state": "IDLE"}, {**base, "gcode_state": "FINISH"}) == []
    assert t(base, {**base, "hms": [{"code": "0300_0100_0001_0001"}]})[0][0] == "Printer alert"
    assert t({**base, "hms": [{"code": "x"}]}, {**base, "hms": [{"code": "x"}]}) == []


def test_push_send_drops_dead_subscriptions(env):
    from filament_kit.web import push
    sent, store = [], push.Store(config.paths().web / "push.json")
    store.add({"endpoint": "https://fcm.googleapis.com/a", "keys": {"p256dh": "k", "auth": "a"}})
    store.add({"endpoint": "https://fcm.googleapis.com/dead", "keys": {"p256dh": "k", "auth": "a"}})

    def fake(info, payload):
        sent.append((info["endpoint"], json.loads(payload)["title"]))
        return 410 if info["endpoint"].endswith("dead") else 201
    push.send_all(store, "Print finished", "benchy", "job", sender=fake)
    assert len(sent) == 2 and sent[0][1] == "Print finished"
    assert list(store.subs()) == ["https://fcm.googleapis.com/a"]


# ---------- KitApi.raw / status ----------

def test_kitapi_raw_streams_and_errors_carry_the_http_status(env, monkeypatch):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route
    from fakes import readers_fake
    from conftest import free_port
    from filament_kit.web import slots

    async def cam(request):
        assert request.headers["authorization"] == "Bearer tok"
        return Response(b"frame-bytes", media_type="multipart/x-mixed-replace; boundary=frame")

    async def gone(request):
        return JSONResponse({"error": "not_found", "message": "no such printer"}, 404)
    app = Starlette(routes=[Route("/api/printers/a/camera.mjpeg", cam), Route("/api/printers/b", gone)])
    monkeypatch.setattr(slots.KitApi, "_token", lambda self: "tok")
    with readers_fake.Served(app, free_port()) as url:
        kit = slots.KitApi(base_url=url)
        status, ctype, r = kit.raw("/api/printers/a/camera.mjpeg")
        try:
            assert status == 200 and ctype == "multipart/x-mixed-replace" and r.read() == b"frame-bytes"
        finally:
            r.close()
        for call in (lambda: kit.get("/api/printers/b"), lambda: kit.raw("/api/printers/b")):
            with pytest.raises(slots.SlotError) as ei:
                call()
            assert ei.value.http == 404 and ei.value.code == "not_found" and "no such printer" in str(ei.value)
    with pytest.raises(slots.SlotError) as ei:
        slots.KitApi(base_url="http://127.0.0.1:1").raw("/x")
    assert ei.value.http is None and ei.value.code == "unreachable"


# ---------- review round 1 ----------

class _Req:
    def __init__(self, serial=SERIAL, **path):
        self.path_params = {"id": serial, **path}

    async def is_disconnected(self):
        return False


def test_camera_counter_cannot_leak_when_the_response_is_never_sent(env, kit):
    import gc
    from filament_kit.web import printers_app
    pa = printers_app.PrintersApp(None, kit)

    async def open_one():
        return await pa.mjpeg(_Req())
    resp = asyncio.run(open_one())
    assert pa.cameras == 1 and kit.closed == 0
    del resp                                  # never started, never iterated
    gc.collect()
    assert pa.cameras == 0 and kit.closed == 1


def test_camera_counter_released_after_serving_and_on_open_failure(env, kit):
    from filament_kit.web import printers_app
    pa = printers_app.PrintersApp(None, kit)

    async def serve():
        resp = await pa.mjpeg(_Req())
        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(m):
            sent.append(m)
        await resp({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    asyncio.run(serve())
    assert pa.cameras == 0 and kit.closed == 1
    kit.down = True
    with pytest.raises(SlotError):
        asyncio.run(pa.mjpeg(_Req()))
    assert pa.cameras == 0


def test_over_the_stream_cap_the_phone_gets_a_message(env, kit):
    from filament_kit.web import printers_app
    pa = printers_app.PrintersApp(None, kit)
    pa.streams = printers_app.MAX_STREAMS
    r = asyncio.run(pa.events_route(_Req()))
    text = r.body.decode()
    assert text.startswith("retry: 30000") and "too many open views" in text and not kit.calls


def test_hls_relay_passes_the_kit_error_through(app, kit):
    c = signed(app)

    def boom(path):
        raise SlotError("the camera stream did not start; check that LAN mode liveview is enabled", http=503)
    kit.raw = boom
    r = c.get(P + f"/{SERIAL}/camera/index.m3u8")
    assert r.status_code == 503 and "liveview" in r.json()["error"]
    r = c.get(P + f"/{SERIAL}/camera.mjpeg")
    assert r.status_code == 503


def test_stream_count_returns_to_zero_when_the_client_closes(env, kit, monkeypatch):
    import httpx2
    from filament_kit.web import printers_app
    from fakes import readers_fake
    from conftest import free_port
    seen = []
    orig = printers_app.PrintersApp.__init__

    def spy(self, *a, **k):
        orig(self, *a, **k)
        self.poll = 0.05
        seen.append(self)
    monkeypatch.setattr(printers_app.PrintersApp, "__init__", spy)
    app = make_app(env, kit)

    async def main(url):
        async with httpx2.AsyncClient(headers={"Host": "mcp.example.test", "X-Forwarded-For": "192.168.1.20"}) as hc:
            async with hc.stream("GET", url + f"/intake/api/printers/{SERIAL}/events") as s:
                async for line in s.aiter_lines():
                    if line.startswith("data: "):
                        break
                assert seen[0].streams == 1
        for _ in range(100):
            if seen[0].streams == 0:
                return True
            await asyncio.sleep(0.05)
        return False
    with readers_fake.Served(app, free_port()) as url:
        assert asyncio.run(main(url)) is True
        n = len(kit.calls)
        asyncio.run(asyncio.sleep(0.3))
        assert len(kit.calls) <= n + 1           # polling stopped with the client


def test_print_error_in_the_kit_status():
    from filament_kit.bridge import status
    assert status.summarize({"print_error": 0x0300_4001}, [])["print_error"] == "0300_4001"
    assert status.summarize({}, [])["print_error"] == ""


def test_push_unavailable_is_said_at_key_and_test(pushapp, monkeypatch):
    from filament_kit.web import push
    monkeypatch.setattr(push, "available", lambda: False)
    c = signed(pushapp)
    for r in (c.get(P + "/push/key"), c.post(P + "/push/test", headers=H)):
        assert r.status_code == 400 and "pywebpush is not installed" in r.json()["error"]


def test_push_caps_subscriptions_and_rate_limits_test(pushapp, env):
    c = signed(pushapp)
    for i in range(10):
        s = good_sub()
        s["subscription"]["endpoint"] = f"https://fcm.googleapis.com/fcm/send/{i}"
        assert c.post(P + "/push/subscribe", json=s, headers=H).status_code == 200
    s = good_sub()
    s["subscription"]["endpoint"] = "https://fcm.googleapis.com/fcm/send/extra"
    r = c.post(P + "/push/subscribe", json=s, headers=H)
    assert r.status_code == 400 and "too many" in r.json()["error"]
    s["subscription"]["endpoint"] = "https://fcm.googleapis.com/fcm/send/3"      # an existing one may refresh
    assert c.post(P + "/push/subscribe", json=s, headers=H).status_code == 200
    assert c.post(P + "/push/test", headers=H).status_code == 200
    r = c.post(P + "/push/test", headers=H)
    assert r.status_code == 400 and "wait" in r.json()["error"]


def test_service_worker_is_behind_the_lan_guard(pushapp):
    assert TestClient(pushapp, base_url=ORIGIN, client=AWAY).get("/intake/sw.js").status_code == 403
    r = signed(pushapp).get("/intake/sw.js")
    assert r.status_code == 200 and "showNotification" in r.text


def test_push_mapping_jobs_do_not_alert_and_print_error_does():
    from filament_kit.web import push
    base = {"gcode_state": "RUNNING", "hms": [], "job": "h2d-calib", "percent": 50, "stage": "", "print_error": ""}
    fin = {**base, "gcode_state": "FINISH"}
    assert push.transitions(base, fin, mapping=True) == []
    assert push.transitions(base, fin)[0][0] == "Print finished"
    err = {**base, "print_error": "0300_4001", "stage": "Printing"}
    assert push.transitions(base, err)[0][0] == "Print error"
    assert push.transitions(err, err) == []
    assert push.transitions(err, {**err, "print_error": ""}) == []
    # a mapping run does not hide a new error
    assert push.transitions(base, {**err, "gcode_state": "FINISH"}, mapping=True)[0][0] == "Print error"


def test_push_watcher_reads_the_map_state(env, kit):
    from filament_kit.web import push
    store = push.Store(config.paths().web / "push.json")
    store.add({"endpoint": "https://fcm.googleapis.com/a", "keys": {"p256dh": "k", "auth": "a"}})
    sent = []
    mapstate = {"v": "running"}
    orig = kit.get

    def get(path):
        if path.endswith("/map"):
            return {"state": mapstate["v"]}
        return orig(path)
    kit.get = get
    w = push.Watcher(kit, store, lambda info, payload: sent.append(json.loads(payload)["title"]) or 201, "/x")
    w.tick()                                              # first sight
    kit.status["gcode_state"] = "FINISH"
    w.tick()
    assert sent == []                                     # calibration run: silent
    kit.status["gcode_state"] = "RUNNING"
    mapstate["v"] = "none"
    w.tick()
    kit.status["gcode_state"] = "FINISH"
    w.tick()
    assert sent == ["Print finished"]


# ---------- load / unload (queue item 4: the Android app's slot actions, through the kit API) ----------

LOAD_PLAN = {"spool": {"id": 9, "name": "Acme PLA Black", "location": "Rack 1"},
             "slot": {"label": "A2", "ams_id": 0, "tray_id": 1, "location": "H2D – AMS A2"},
             "preset": {"name": "Acme PLA Black @H2D"}, "dry_run": True, "moved_back": [], "confirmed": False,
             "problems": [], "nozzle_mm": 0.4, "nozzle_assumed": False}


class SlotKit(FakeKit):
    """FakeKit that also answers the kit's load/unload routes; `refuse` = the SlotError the kit answers with."""

    def __init__(self):
        super().__init__()
        self.refuse = None

    def post(self, path, body):
        if "/slots/" in path:
            self._check()
            self.calls.append(("POST", path, body))
            if self.refuse is not None:
                raise self.refuse
            if path.endswith("/load"):
                return {**LOAD_PLAN, "dry_run": body["dry_run"], "confirmed": None if body["dry_run"] else True}
            return {"spool": {"id": 7, "name": "Overture PLA Red"}, "slot": {"label": "A1"},
                    "dry_run": body["dry_run"], "moved_back": [{"id": 7, "location": "Rack 1"}],
                    "location": "Rack 1"}
        return super().post(path, body)


@pytest.fixture
def slotkit():
    return SlotKit()


@pytest.fixture
def slotapp(env, slotkit):
    return make_app(env, slotkit)


def test_load_is_a_dry_run_unless_said_otherwise(slotapp, slotkit):
    c = signed(slotapp)
    r = c.post(P + f"/{SERIAL}/slots/A2/load", json={"spool_id": 9}, headers=H)
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert ("POST", f"/api/printers/{SERIAL}/slots/A2/load", {"spool_id": 9, "dry_run": True}) in slotkit.calls
    r = c.post(P + f"/{SERIAL}/slots/A2/load", json={"spool_id": 9, "dry_run": False}, headers=H)
    assert r.status_code == 200 and r.json()["confirmed"] is True
    assert ("POST", f"/api/printers/{SERIAL}/slots/A2/load", {"spool_id": 9, "dry_run": False}) in slotkit.calls


def test_unload_goes_to_the_kit(slotapp, slotkit):
    c = signed(slotapp)
    r = c.post(P + f"/{SERIAL}/slots/A1/unload", json={}, headers=H)
    assert r.status_code == 200 and r.json()["location"] == "Rack 1"
    assert ("POST", f"/api/printers/{SERIAL}/slots/A1/unload", {"dry_run": True}) in slotkit.calls
    c.post(P + f"/{SERIAL}/slots/A1/unload", json={"dry_run": False}, headers=H)
    assert ("POST", f"/api/printers/{SERIAL}/slots/A1/unload", {"dry_run": False}) in slotkit.calls


@pytest.mark.parametrize("body", [{}, {"spool_id": "9"}, {"spool_id": True}, {"spool_id": 9.5},
                                  {"spool_id": 9, "dry_run": "no"}])
def test_load_checks_its_body_before_the_kit(slotapp, slotkit, body):
    c = signed(slotapp)
    r = c.post(P + f"/{SERIAL}/slots/A2/load", json=body, headers=H)
    assert r.status_code == 400
    assert not [x for x in slotkit.calls if x[0] == "POST"]


def test_bad_slot_labels_are_refused_before_the_kit(slotapp, slotkit):
    c = signed(slotapp)
    for bad in ("A%231", "..", "x" * 40, "A 1"):
        r = c.post(P + f"/{SERIAL}/slots/{bad}/unload", json={}, headers=H)
        assert r.status_code in (400, 404), bad
    assert not [x for x in slotkit.calls if x[0] == "POST"]


def test_load_and_unload_need_lan_and_origin(slotapp, slotkit):
    away = TestClient(slotapp, base_url=ORIGIN, client=AWAY)
    assert away.post(P + f"/{SERIAL}/slots/A2/load", json={"spool_id": 9}, headers=H).status_code == 403
    home = signed(slotapp)
    r = home.post(P + f"/{SERIAL}/slots/A2/load", json={"spool_id": 9})
    assert r.status_code == 403 and r.json()["error"] == "bad origin"
    r = home.post(P + f"/{SERIAL}/slots/A1/unload", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert not [x for x in slotkit.calls if x[0] == "POST"]


@pytest.mark.parametrize("code,status,needle", [
    ("slot_in_use", 409, "feeds the print that is running"),
    ("printer_offline", 409, "The printer is offline"),
    ("no_preset", 409, "No preset for this filament on this printer yet"),
    ("already_running", 409, "Slot mapping or a load is in progress"),
    ("needs_developer_mode", 409, "Developer Mode"),
    ("cert_changed", 409, "certificate changed"),
])
def test_load_refusals_read_as_the_android_app_says_them(slotapp, slotkit, code, status, needle):
    slotkit.refuse = SlotError("raw kit text", code=code, http=status)
    r = signed(slotapp).post(P + f"/{SERIAL}/slots/A2/load", json={"spool_id": 9}, headers=H)
    assert r.status_code == status and needle in r.json()["error"] and r.json()["code"] == code


def test_a_not_found_refusal_keeps_the_kits_own_words(slotapp, slotkit):
    slotkit.refuse = SlotError("no slot 'Z9'", code="not_found", http=404)
    r = signed(slotapp).post(P + f"/{SERIAL}/slots/Z9/unload", json={}, headers=H)
    assert r.status_code == 404 and r.json()["error"] == "no slot 'Z9'"


def test_tagged_names_the_last_tapped_spool(slotapp, monkeypatch):
    from filament_kit.web import mcp_tools
    monkeypatch.setattr(mcp_tools.Tools, "tag_state", lambda self: {
        "nfc_id": "04AABBCCDD", "spool": {"id": 9, "vendor": "Acme", "name": "PLA Black", "location": "Rack 1",
                                          "remaining_g": 800, "extra": {"x": 1}}, "near": [], "text": "t"})
    r = signed(slotapp).get(P + "/tagged")
    assert r.status_code == 200
    assert r.json() == {"nfc_id": "04AABBCCDD", "spool": {"id": 9, "vendor": "Acme", "name": "PLA Black",
                                                         "location": "Rack 1", "remaining_g": 800}}


def test_script_has_the_load_and_unload_flows():
    src = (STATIC / "printers.js").read_text(encoding="utf-8")
    for needle in ("/slots/", "/load", "/unload", "dry_run: false", "window.confirm", "find?q=", "pj(\"tagged\")"):
        assert needle in src, needle


def test_script_reruns_a_dry_run_asked_for_while_another_ran():
    """Picking spool B while A's dry run is in flight queues B's (dryAgain), run when A's ends (slotDone), instead
    of leaving an empty plan and a disabled Load button."""
    src = (STATIC / "printers.js").read_text(encoding="utf-8")
    assert "if (slotBusy) { if (dry) dryAgain = { plan, go }; return; }" in src
    assert "if (again && loadSpool) doLoad(true, again.plan, again.go);" in src
    assert src.count("finally { slotDone(); }") == 2 and "finally { slotBusy = false; }" not in src


def test_the_report_route_asks_the_kit_and_needs_lan_and_origin(app, kit):
    with TestClient(app, base_url=ORIGIN, client=HOME) as c:
        c.post(P + f"/{SERIAL}/report", headers=H)
        assert ("POST", f"/api/printers/{SERIAL}/report", {}) in kit.calls
        assert c.post(P + f"/{SERIAL}/report").status_code == 403       # no Origin


# ---------- Map by loading filament (interface parity, 2026-11-10: the setup page and Android had it) ----------

def test_manual_map_steps_go_to_the_kit_with_only_their_keys(app, kit):
    with TestClient(app, base_url=ORIGIN, client=HOME) as c:
        c.post(P + f"/{SERIAL}/manual-map/start", headers=H, json={})
        c.post(P + f"/{SERIAL}/manual-map/confirm", headers=H,
               json={"session": "s1", "position": "A2", "reported": {"ams_id": 0, "tray_id": 1}, "nozzle": None,
                     "by_hand": False, "path": "/api/pair"})
        c.post(P + f"/{SERIAL}/manual-map/offer", headers=H, json={"share": True})
        c.get(P + f"/{SERIAL}/manual-map")
    assert ("POST", f"/api/printers/{SERIAL}/manual-map/start", {}) in kit.calls
    assert ("POST", f"/api/printers/{SERIAL}/manual-map/confirm",
            {"session": "s1", "position": "A2", "reported": {"ams_id": 0, "tray_id": 1}, "nozzle": None,
             "by_hand": False}) in kit.calls
    assert ("POST", f"/api/printers/{SERIAL}/manual-map/offer", {"share": True}) in kit.calls
    assert ("GET", f"/api/printers/{SERIAL}/manual-map") in kit.calls


def test_manual_map_refuses_another_step_and_a_post_without_origin(app, kit):
    with TestClient(app, base_url=ORIGIN, client=HOME) as c:
        assert c.post(P + f"/{SERIAL}/manual-map/pair", headers=H, json={}).status_code == 400
        assert c.post(P + f"/{SERIAL}/manual-map/start", json={}).status_code == 403
    assert not [x for x in kit.calls if "manual-map" in x[1]]


def test_the_printers_tab_offers_map_by_loading_filament():
    text = (STATIC / "printers.js").read_text(encoding="utf-8")
    assert 'textContent: "Map by loading filament", disabled: running, on: { click: manualMap }' in text
    for step in ("start", "confirm", "skip", "stop", "offer"):
        assert f'"{step}"' in text


# ---------- Manage printers (interface parity gap 3: add, edit, forget from the phone web app) ----------

class ManagingKit(FakeKit):
    def get(self, path):
        if path == "/api/printers":
            self.calls.append(("GET", path))
            return {"printers": [
                {"id": SERIAL, "name": "H2D", "model": "O1D", "model_name": "H2D", "family": "bambu", "ip": "10.0.0.1",
                 "configured": True, "state": "connected", "access_code": "LEAK", "camera": {"kind": "hls"}},
                {"id": "sv08-max", "name": "SV08", "family": "klipper", "host": "10.0.0.3", "configured": True,
                 "state": "connected", "api_key": "LEAK"}]}
        return super().get(path)

    def post(self, path, body):
        if path == "/api/printers":
            self.calls.append(("POST", path, body))
            return {"printer": {"id": body.get("serial", "x"), "name": body.get("name"), "configured": True,
                                "access_code": "LEAK"}}
        return super().post(path, body)

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        return {"printer": {"id": "sv08-max", "name": body.get("name"), "api_key": "LEAK"}, "changed": sorted(body),
                "note": "a note"}

    def delete(self, path):
        self.calls.append(("DELETE", path))
        return {"ok": True, "id": path.rsplit("/", 1)[-1]}


@pytest.fixture
def managing(env):
    kit = ManagingKit()
    return make_app(env, kit), kit


def test_manage_lists_every_printer_without_secrets(managing):
    app, kit = managing
    with TestClient(app, base_url=ORIGIN, client=HOME) as c:
        r = c.get(P + "/manage")
    assert r.status_code == 200 and "LEAK" not in r.text
    assert [p["id"] for p in r.json()["printers"]] == [SERIAL, "sv08-max"]
    assert r.json()["printers"][1]["host"] == "10.0.0.3"


def test_add_edit_and_forget_go_to_the_kit_with_only_their_keys(managing):
    app, kit = managing
    with TestClient(app, base_url=ORIGIN, client=HOME) as c:
        r = c.post(P + "/add", headers=H, json={"serial": SERIAL, "access_code": "12345678", "name": "H2D",
                                                 "configured": True})
        assert r.status_code == 200 and "LEAK" not in r.text
        r = c.post(P + "/sv08-max/edit", headers=H, json={"name": "Big", "api_key": "k", "family": "bambu"})
        assert r.status_code == 200 and "LEAK" not in r.text and r.json()["note"] == "a note"
        assert c.post(P + "/sv08-max/forget", headers=H, json={}).json() == {"ok": True, "id": "sv08-max"}
    assert ("POST", "/api/printers", {"serial": SERIAL, "access_code": "12345678", "name": "H2D"}) in kit.calls
    assert ("PATCH", "/api/printers/sv08-max", {"name": "Big", "api_key": "k"}) in kit.calls
    assert ("DELETE", "/api/printers/sv08-max") in kit.calls


def test_add_edit_and_forget_need_the_pages_origin_and_the_home_network(managing):
    app, kit = managing
    with TestClient(app, base_url=ORIGIN, client=HOME) as c:
        assert c.post(P + "/add", json={"serial": SERIAL}).status_code == 403
        assert c.post(P + f"/{SERIAL}/edit", json={"name": "x"}).status_code == 403
        assert c.post(P + f"/{SERIAL}/forget", json={}).status_code == 403
        assert c.post(P + "/bad%20id/forget", headers=H, json={}).status_code == 400
    assert not [x for x in kit.calls if x[0] in ("PATCH", "DELETE") or (x[0] == "POST" and x[1] == "/api/printers")]


def test_forget_from_away_needs_the_session(env):
    kit = ManagingKit()
    with TestClient(make_app(env, kit), base_url=ORIGIN, client=AWAY) as c:
        assert c.post(P + f"/{SERIAL}/forget", headers=H, json={}).status_code in (401, 403)
    assert not [x for x in kit.calls if x[0] == "DELETE"]


def test_the_printers_tab_has_manage_printers():
    text = (STATIC / "printers.js").read_text(encoding="utf-8")
    for words in ('"Add or change printers"', '"Rename"', '"Address"', '"Access Code"', '"Forget certificate"',
                  '"API key"', '"Forget"', '"Add a Klipper printer"', '`${id}/edit`', '`${id}/forget`', 'manageDo("add"'):
        assert words in text, words
