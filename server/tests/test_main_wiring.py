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

    def state(self, serial):
        return "not_configured"


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
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: seen.update(app=app, kw=kw))
    m.main()
    assert seen["kw"]["timeout_graceful_shutdown"] == 5
    ctx = seen["app"].router.lifespan_context
    assert ctx.__qualname__.startswith("printer_lifespan")


def test_main_routes_app_info_logs_to_the_journal(tmp_path, monkeypatch):
    # The command audit line (device, serial, action) is INFO; without a handler on our logger it was dropped
    # (found on the real H2D check: uvicorn only configures its own loggers).
    import logging
    for n in ("etc", "state", "opt"):
        (tmp_path / n).mkdir()
        monkeypatch.setenv(f"FK_{n.upper()}", str(tmp_path / n))
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: None)
    log = logging.getLogger("filament_kit")
    monkeypatch.setattr(log, "handlers", [])
    monkeypatch.setattr(log, "level", logging.NOTSET)
    monkeypatch.setattr(log, "propagate", True)  # restored afterwards so caplog-based tests still see records
    m.main()
    assert log.isEnabledFor(logging.INFO)
    assert log.handlers or logging.getLogger().handlers


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
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: seen.update(serve_hub=hub))
    m.main()
    assert isinstance(seen["app_hub"], camera.Hub) and seen["life_hub"] is seen["app_hub"]
    assert seen["serve_hub"] is seen["app_hub"]


def test_exit_signal_ends_camera_streams_before_uvicorn_drains():
    hub = camera.Hub(lookup=lambda s: None)
    server = m._Server(m.uvicorn.Config(lambda scope, receive, send: None), hub.begin_stop)
    server.handle_exit(15, None)
    assert hub.stopping.is_set() and server.should_exit


# ---------- final review ----------

import logging  # noqa: E402

import pytest  # noqa: E402


def _fake_server(monkeypatch, started, raise_kbi=False):
    def run(self):
        self.started = started
        if raise_kbi:
            raise KeyboardInterrupt
    monkeypatch.setattr(m._Server, "run", run)


def test_serve_exits_3_when_uvicorn_never_started(monkeypatch):
    _fake_server(monkeypatch, started=False)
    hub = camera.Hub(lookup=lambda s: None)
    with pytest.raises(SystemExit) as e:
        m.serve(lambda scope, receive, send: None, hub)
    assert e.value.code == 3


def test_serve_returns_normally_after_a_clean_run_or_ctrl_c(monkeypatch):
    hub = camera.Hub(lookup=lambda s: None)
    _fake_server(monkeypatch, started=True)
    m.serve(lambda scope, receive, send: None, hub)
    _fake_server(monkeypatch, started=True, raise_kbi=True)
    m.serve(lambda scope, receive, send: None, hub)


class StateMgr:
    def __init__(self, states):
        self.states = states

    def state(self, serial):
        return self.states.get(serial, "not_configured")


def _configured(serial="S1", ip="10.0.0.5"):
    registry.upsert(registry.Printer(serial, "Mine", "O1D", ip, "SECRET99", True))


@pytest.mark.parametrize("state", ["connected", "needs_developer_mode"])
def test_announce_cannot_move_a_connected_printer(tmp_path, monkeypatch, caplog, state):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    _configured()
    cb = m.discovery_callback(StateMgr({"S1": state}))
    with caplog.at_level(logging.WARNING):
        cb({"serial": "S1", "ip": "10.0.0.66", "model": "O1D", "name": "x"})
    assert registry.load()["S1"].ip == "10.0.0.5"
    warn = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warn and "S1" in warn[0].getMessage() and "10.0.0.5" in warn[0].getMessage() \
        and "10.0.0.66" in warn[0].getMessage()
    assert "SECRET99" not in caplog.text


@pytest.mark.parametrize("state", ["offline", "wrong_code"])
def test_announce_moves_a_configured_printer_that_is_not_connected_and_warns(tmp_path, monkeypatch, caplog,
                                                                              state):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    _configured()
    cb = m.discovery_callback(StateMgr({"S1": state}))
    with caplog.at_level(logging.WARNING):
        cb({"serial": "S1", "ip": "10.0.0.66"})
    assert registry.load()["S1"].ip == "10.0.0.66"
    msg = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "S1" in msg and "10.0.0.5" in msg and "10.0.0.66" in msg and "SECRET99" not in caplog.text


def test_announce_same_ip_or_unconfigured_printer_does_not_warn(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    _configured()
    cb = m.discovery_callback(StateMgr({"S1": "connected"}))
    with caplog.at_level(logging.WARNING):
        cb({"serial": "S1", "ip": "10.0.0.5"})
        cb({"serial": "N1", "ip": "10.0.0.7"})
        cb({"serial": "N1", "ip": "10.0.0.8"})
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert registry.load()["N1"].ip == "10.0.0.8"


def test_announce_with_a_serial_that_could_not_be_removed_again_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    cb = m.discovery_callback(StateMgr({}))
    for bad in ("a b", "x/y", "S" * 65):
        cb({"serial": bad, "ip": "10.0.0.7"})
    cb({"serial": "GOOD1", "ip": "10.0.0.7"})
    assert list(registry.load()) == ["GOOD1"]


def test_corrupt_registry_logged_at_most_once_a_minute(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    (tmp_path / "printers.json").write_text("{broken")
    clock = [1000.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    cb = m.discovery_callback(StateMgr({}))
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            cb({"serial": "S1", "ip": "10.0.0.5"})       # must not raise
        clock[0] += 61
        cb({"serial": "S1", "ip": "10.0.0.5"})
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == m.log.name]
    assert len(errs) == 2 and all(r.exc_info is None for r in errs)
    assert (tmp_path / "printers.json").read_text() == "{broken"


def test_main_starts_the_usage_tracker_and_lifespan_stops_it(tmp_path, monkeypatch):
    from filament_kit.bridge import usage
    for n in ("etc", "state", "opt"):
        (tmp_path / n).mkdir()
        monkeypatch.setenv(f"FK_{n.upper()}", str(tmp_path / n))
    seen = {}
    real_lifespan = m.printer_lifespan
    monkeypatch.setattr(m, "printer_lifespan", lambda mgr, **kw: seen.update(mgr=mgr, tracker=kw.get("tracker"))
                        or real_lifespan(mgr, **kw))
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: None)
    m.main()
    t = seen["tracker"]
    assert isinstance(t, usage.Tracker) and t._on_report in seen["mgr"]._listeners
    from filament_kit.bridge import mapping
    assert any(isinstance(fn, mapping.LayoutWatch) for fn in seen["mgr"]._listeners)   # P2: stale + re-map


def test_lifespan_stops_the_tracker(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))

    class T:
        stopped = 0

        def stop(self):
            T.stopped += 1
    mgr = Mgr()

    async def run():
        async with m.printer_lifespan(mgr, listener_factory=lambda cb: (_ for _ in ()).throw(OSError("x")),
                                      tracker=T())(None):
            assert T.stopped == 0
    asyncio.run(run())
    assert T.stopped == 1 and mgr.events == ["start", "stop"]


def test_lifespan_stops_mapping_before_the_manager_and_recovers_at_start(tmp_path, monkeypatch):
    """C1: a running mapping job is stopped and its restore awaited while the printer connections are still up;
    at start the mapper restores any slot snapshot a killed job left."""
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    events = []

    class M:
        def start(self):
            events.append("manager.start")

        def stop(self):
            events.append("manager.stop")

    class Mp:
        def recover_pending(self):
            events.append("mapper.recover")

        def shutdown(self, timeout=60):
            events.append("mapper.shutdown")

    async def run():
        async with m.printer_lifespan(M(), listener_factory=lambda cb: (_ for _ in ()).throw(OSError("x")),
                                      mapper=Mp())(None):
            events.append("serving")
    asyncio.run(run())
    assert events == ["manager.start", "mapper.recover", "serving", "mapper.shutdown", "manager.stop"]


def test_main_passes_one_mapper_to_app_and_lifespan(tmp_path, monkeypatch):
    from filament_kit.bridge import mapping
    for n in ("etc", "state", "opt"):
        (tmp_path / n).mkdir()
        monkeypatch.setenv(f"FK_{n.upper()}", str(tmp_path / n))
    seen = {}
    real_create, real_lifespan = m.create_app, m.printer_lifespan
    monkeypatch.setattr(m, "create_app", lambda *a, **kw: seen.update(app=kw.get("mapper")) or real_create(*a, **kw))
    monkeypatch.setattr(m, "printer_lifespan", lambda mgr, **kw: seen.update(life=kw.get("mapper"))
                        or real_lifespan(mgr, **kw))
    monkeypatch.setattr(m, "serve", lambda app, hub, **kw: None)
    m.main()
    assert isinstance(seen["app"], mapping.Mapper) and seen["life"] is seen["app"]
