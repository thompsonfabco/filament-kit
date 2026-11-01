import asyncio

from filament_kit import __main__ as m
from filament_kit.bridge import camera, registry


class Mgr:
    def __init__(self):
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


def test_lifespan_starts_and_stops_listener_and_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    seen = {}

    class L:
        def __init__(self, on_found):
            seen["cb"] = on_found
            seen["events"] = []

        def start(self):
            seen["events"].append("start")
            return self

        def stop(self):
            seen["events"].append("stop")

    mgr = Mgr()

    async def run():
        async with m.printer_lifespan(mgr, listener_factory=L)(None):
            assert mgr.events == ["start"] and seen["events"] == ["start"]
            seen["cb"]({"serial": "S1", "ip": "10.0.0.2", "model": "C12", "name": "P"})
    asyncio.run(run())
    assert mgr.events == ["start", "stop"] and seen["events"] == ["start", "stop"]
    assert registry.load()["S1"].ip == "10.0.0.2"


def test_lifespan_survives_listener_bind_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))

    def boom(on_found):
        raise OSError("address in use")
    mgr = Mgr()

    async def run():
        async with m.printer_lifespan(mgr, listener_factory=boom)(None):
            pass
    asyncio.run(run())
    assert mgr.events == ["start", "stop"]


def test_main_installs_lifespan_hook(tmp_path, monkeypatch):
    for n in ("etc", "state", "opt"):
        (tmp_path / n).mkdir()
        monkeypatch.setenv(f"FK_{n.upper()}", str(tmp_path / n))
    seen = {}
    monkeypatch.setattr(m.uvicorn, "run", lambda app, **kw: seen.update(app=app, kw=kw))
    m.main()
    ctx = seen["app"].router.lifespan_context
    assert ctx.__qualname__.startswith("printer_lifespan")


def test_manager_start_failure_does_not_leak_listener(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    events = []

    class L:
        def __init__(self, cb):
            pass

        def start(self):
            return self

        def stop(self):
            events.append("lx")

    class Bad(Mgr):
        def start(self):
            raise RuntimeError("boom")

        def stop(self):
            events.append("mx")

    async def run():
        async with m.printer_lifespan(Bad(), listener_factory=L)(None):
            pass
    try:
        asyncio.run(run())
    except RuntimeError:
        pass
    assert events == ["mx", "lx"]


class Hub:
    def __init__(self, events):
        self.events = events

    def shutdown(self):
        self.events.append("hub")


def test_lifespan_shuts_the_camera_hub_down_last(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    events = []

    class L:
        def __init__(self, cb):
            pass

        def start(self):
            return self

        def stop(self):
            events.append("lx")

    class M(Mgr):
        def stop(self):
            events.append("mx")

    async def run():
        async with m.printer_lifespan(M(), listener_factory=L, camera_hub=Hub(events))(None):
            assert events == []
    asyncio.run(run())
    assert events == ["mx", "lx", "hub"]


def test_camera_hub_shut_down_even_if_manager_stop_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    events = []

    class Bad(Mgr):
        def stop(self):
            raise RuntimeError("stop failed")

    def no_listener(cb):
        raise OSError("in use")

    async def run():
        async with m.printer_lifespan(Bad(), listener_factory=no_listener, camera_hub=Hub(events))(None):
            pass
    try:
        asyncio.run(run())
    except RuntimeError:
        pass
    assert events == ["hub"]


def test_main_passes_one_hub_to_app_and_lifespan(tmp_path, monkeypatch):
    for n in ("etc", "state", "opt"):
        (tmp_path / n).mkdir()
        monkeypatch.setenv(f"FK_{n.upper()}", str(tmp_path / n))
    seen = {}
    real_create, real_lifespan = m.create_app, m.printer_lifespan
    monkeypatch.setattr(m, "create_app", lambda *a, **kw: seen.update(app_hub=kw.get("camera_hub"))
                        or real_create(*a, **kw))
    monkeypatch.setattr(m, "printer_lifespan", lambda mgr, **kw: seen.update(life_hub=kw.get("camera_hub"))
                        or real_lifespan(mgr, **kw))
    monkeypatch.setattr(m.uvicorn, "run", lambda app, **kw: None)
    m.main()
    assert isinstance(seen["app_hub"], camera.Hub) and seen["life_hub"] is seen["app_hub"]
