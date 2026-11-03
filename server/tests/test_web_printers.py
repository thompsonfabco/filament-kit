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
                 "camera": {"kind": "rtsp"}, "summary": None, "ip": "10.0.0.1", "serial": SERIAL},
                {"id": OTHER, "name": "X1", "model": "BL-P001", "configured": False, "state": "not_configured",
                 "camera": {"kind": "rtsp"}, "summary": None, "ip": "10.0.0.2", "serial": OTHER}]}
        if path in (f"/api/printers/{SERIAL}",):
            return {"printer": {"id": SERIAL, "name": "H2D", "model": "O1D", "state": "connected",
                                "camera": {"kind": "rtsp"}}, "status": copy.deepcopy(self.status), "hardware": {}}
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
    c = TestClient(app, base_url=ORIGIN, client=who)
    r = c.post("/intake/login", data={"passphrase": PASS}, headers={"Origin": ORIGIN}, follow_redirects=False)
    assert r.status_code == 303
    c.cookies.set("fi_session", r.headers["set-cookie"].split(";")[0].split("=", 1)[1])  # cookie path is the public one
    return c


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
    assert c.get(P).status_code == 404 or "printers" not in c.get(P).text


def test_csp_is_the_intake_csp(app):
    c = signed(app)
    r = c.get("/intake")
    from filament_kit.web import intake_app
    assert r.headers["content-security-policy"] == intake_app.HEADERS["Content-Security-Policy"]
    assert "unsafe" not in r.headers["content-security-policy"]


def test_script_never_uses_innerhtml():
    for name in ("app.js", "printers.js"):
        lines = (STATIC / name).read_text(encoding="utf-8").splitlines()
        src = " ".join(ln for ln in lines if not ln.lstrip().startswith("//"))
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", src), name


# ---------- access ----------

def test_routes_need_lan_session_and_origin(app, kit):
    away = signed(app)
    assert TestClient(app, base_url=ORIGIN, client=AWAY).get(P).status_code == 403
    assert TestClient(app, base_url=ORIGIN, client=HOME).get(P).status_code == 401
    assert TestClient(app, base_url=ORIGIN, client=HOME).get(P + f"/{SERIAL}/camera.mjpeg").status_code == 401
    r = away.post(P + f"/{SERIAL}/command", json={"action": "pause"})
    assert r.status_code == 403 and r.json()["error"] == "bad origin"
    r = away.post(P + f"/{SERIAL}/command", json={"action": "pause"}, headers={"Origin": "https://evil.example"})
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
            r = await hc.post(url + "/intake/login", data={"passphrase": PASS}, headers={"Origin": ORIGIN})
            cookie = r.headers["set-cookie"].split(";")[0]
            async with hc.stream("GET", url + "/intake/api/printers/" + SERIAL + "/events",
                                 headers={"Cookie": cookie}) as s:
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
def pushapp(env, kit):
    return make_app(env, kit, push=True)


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
    f = env / "state" / "web" / "push.json"
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
    sent, store = [], push.Store(env / "state" / "web" / "push.json")
    store.add({"endpoint": "https://fcm.googleapis.com/a", "keys": {"p256dh": "k", "auth": "a"}})
    store.add({"endpoint": "https://fcm.googleapis.com/dead", "keys": {"p256dh": "k", "auth": "a"}})

    def fake(info, payload):
        sent.append((info["endpoint"], json.loads(payload)["title"]))
        return 410 if info["endpoint"].endswith("dead") else 201
    push.send_all(store, "Print finished", "benchy", "job", sender=fake)
    assert len(sent) == 2 and sent[0][1] == "Print finished"
    assert list(store.subs()) == ["https://fcm.googleapis.com/a"]


# ---------- KitApi.raw / status ----------

def test_kitapi_raw_streams_and_errors_carry_the_status(env, monkeypatch):
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
            assert ei.value.status == 404 and "no such printer" in str(ei.value)
    with pytest.raises(slots.SlotError) as ei:
        slots.KitApi(base_url="http://127.0.0.1:1").raw("/x")
    assert ei.value.status is None
