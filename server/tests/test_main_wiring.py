import asyncio

from filament_kit import __main__ as m
from filament_kit.bridge import registry


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
