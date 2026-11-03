"""Module gating of the app API, /api/station, and the main wiring without printers."""
import asyncio
import threading
import time

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from conftest import free_port
from filament_kit import config, pairing
from filament_kit import __main__ as m
from filament_kit.api import create_app
from filament_kit.modules import MODES
from filament_kit.spoolman import Spoolman
from filament_kit.station_client import StationClient, StationUnreachable

STATE = {"tag": {"uid": "4:77:90:e:9:22:89"}, "scale": {"name": "DYMO"}, "last_weight": {"grams": 812.0}, "held": None}


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})


def auth():
    return {"Authorization": f"Bearer {pairing.redeem_code(pairing.issue().code)}"}


def app(on, **kw):
    return TestClient(create_app(sm=Spoolman("http://127.0.0.1:1"), enabled_modules=on, **kw))


def test_intake_off_returns_module_off():
    c = app(MODES["server"] - {"ai_intake"})
    r = c.post("/api/intake/read", headers=auth())
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "module_off" and body["module"] == "ai_intake"
    assert c.post("/api/intake/retry/abc", headers=auth()).json()["module"] == "ai_intake"


def test_gated_route_still_needs_pairing():
    c = app(MODES["server"] - {"ai_intake"})
    assert c.post("/api/intake/read").status_code == 401


def test_printers_off_routes_module_off():
    c = app(MODES["server"] - {"printers"})
    for method, path in (("GET", "/api/printers"), ("POST", "/api/printers/S1/map"),
                         ("POST", "/api/usage/x/undo"), ("GET", "/api/printers/S1/camera.mjpeg")):
        r = c.request(method, path, headers=auth())
        assert (r.status_code, r.json()["error"], r.json()["module"]) == (409, "module_off", "printers"), path
    assert c.get("/api/locations", headers=auth()).status_code != 409  # other routes untouched


def test_presets_off_routes_module_off():
    c = app(MODES["server"] - {"presets"})
    for method, path in (("GET", "/api/profiles/status"), ("GET", "/api/sync/state"),
                         ("PUT", "/api/sync/live")):
        r = c.request(method, path, headers=auth())
        assert (r.status_code, r.json()["module"]) == (409, "presets"), path


def test_modules_on_routes_not_gated():
    c = app(MODES["server"])
    assert c.get("/api/profiles/status", headers=auth()).status_code != 409
    assert c.get("/api/printers", headers=auth()).status_code == 200


def test_info_lists_modules():
    on = MODES["server"] - {"printers"}
    assert app(on).get("/api/info").json()["modules"] == sorted(on)


def test_info_modules_default_from_config():
    config.save({"modules": {"server": True, "station": True}})
    c = TestClient(create_app(sm=Spoolman("http://127.0.0.1:1")))
    assert c.get("/api/info").json()["modules"] == ["server", "station"]


class FakeStation:
    def __init__(self):
        self.hits = 0
        self.fail = False
        self.port = free_port()

        def state(request):
            self.hits += 1
            if self.fail:
                return Response("no", status_code=500)
            return JSONResponse(STATE)
        self.server = uvicorn.Server(uvicorn.Config(Starlette(routes=[Route("/state", state)]),
                                                    host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("station fake did not start")

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=5)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


def _station_url(url):
    cfg = config.load()
    cfg["station"]["url"] = url
    config.save(cfg)


def test_api_station_proxy():
    with FakeStation() as st:
        _station_url(st.url)
        c = app(MODES["all-in-one"])
        assert c.get("/api/station").status_code == 401
        r = c.get("/api/station", headers=auth())
        assert r.status_code == 200 and r.json() == STATE


def test_api_station_backoff():
    with FakeStation() as st:
        st.fail = True
        _station_url(st.url)
        c = app(MODES["all-in-one"])
        h = auth()
        r = c.get("/api/station", headers=h)
        assert (r.status_code, r.json()["error"]) == (503, "station_unreachable")
        hits = st.hits
        st.fail = False
        r = c.get("/api/station", headers=h)
        assert r.status_code == 503 and st.hits == hits   # inside the back-off: no connection


def test_api_station_unset_module_off():
    c = app(MODES["server"])
    r = c.get("/api/station", headers=auth())
    assert r.status_code == 409
    assert (r.json()["error"], r.json()["module"]) == ("module_off", "station")


def test_station_client_errors_and_recovery():
    with pytest.raises(StationUnreachable):
        StationClient("http://127.0.0.1:1", timeout=1, backoff=0).state()
    with FakeStation() as st:
        sc = StationClient(st.url, backoff=0)
        assert sc.state() == STATE
        st.fail = True
        with pytest.raises(StationUnreachable):
            sc.state()
        st.fail = False
        assert sc.state() == STATE


def test_main_without_printers_builds_no_bridge(monkeypatch):
    config.save({"modules": {"server": True, "ai_intake": True}})
    served = {}

    def boom(*a, **k):
        raise AssertionError("printer machinery built with printers off")
    monkeypatch.setattr(m, "Manager", boom)
    monkeypatch.setattr(m.discovery, "Listener", boom)
    monkeypatch.setattr(m.usage, "Tracker", boom)
    monkeypatch.setattr(m.camera, "Hub", boom)
    monkeypatch.setattr(m.mapping, "Mapper", boom)
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: served.update(app=app, hub=hub))
    m.main()
    c = TestClient(served["app"])
    assert c.get("/api/printers", headers=auth()).status_code == 409
    served["hub"].begin_stop()   # the signal hook must still be callable

    async def life():
        async with served["app"].router.lifespan_context(served["app"]):
            pass
    asyncio.run(life())          # starts and stops nothing printer-related


def test_main_with_printers_builds_bridge(monkeypatch):
    built = []

    class Fake:
        def __init__(self, *a, **k):
            built.append(type(self))

        def state(self, s):
            return "not_configured"
    monkeypatch.setattr(m, "Manager", Fake)
    monkeypatch.setattr(m.usage, "Tracker", Fake)
    monkeypatch.setattr(m.camera, "Hub", Fake)
    monkeypatch.setattr(m.mapping, "Mapper", Fake)
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: None)
    m.main()
    assert len(built) == 4


def test_manual_add_works_without_ai_intake():
    """R1: adding spools by hand needs no AI: /api/intake/add answers (here: the bad body), not module_off."""
    c = app(MODES["server"])
    assert "ai_intake" not in MODES["server"]
    r = c.post("/api/intake/add", headers=auth(), json={"items": []})
    assert (r.status_code, r.json()["error"]) == (400, "bad_request")
    for path in ("/api/filaments", "/api/vendors"):  # Spoolman is down here: answered, not gated
        assert c.get(path, headers=auth()).json()["error"] == "spoolman_unreachable"
    assert c.post("/api/intake/add", json={"items": []}).status_code == 401
