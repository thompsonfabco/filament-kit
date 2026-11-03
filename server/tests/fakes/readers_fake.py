"""Stand-ins for the owner's LAN services the web process reads (tests only).

One Starlette app, state in a dict the test mutates:
  GET  /last-tag      a lasttag reader (SV08 lasttag service or the station's /last-tag): `data["tag"]`
  GET  /state         the intake station's state: `data["state"]`
  GET  /api/state     the H2D slot service (h2d-remote): `data["slots"]`
  POST /set-slot      the H2D scanner orchestrator: records the body and header in `data["set_calls"]`,
                      answers `data["set_reply"]` with `data["set_status"]`
"""
from __future__ import annotations

import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def new_data() -> dict:
    return {"tag": {"status": "none"}, "state": {"tag": None, "scale": None, "last_weight": None},
            "slots": {"online": True, "state": "IDLE", "name": "", "ams": []},
            "set_calls": [], "set_reply": {"ok": True, "status": "set"}, "set_status": 200}


def app(data: dict) -> Starlette:
    async def last_tag(request: Request):
        return JSONResponse(data["tag"])

    async def state(request: Request):
        return JSONResponse(data["state"])

    async def slots(request: Request):
        return JSONResponse(data["slots"])

    async def set_slot(request: Request):
        data["set_calls"].append({"body": await request.json(), "token": request.headers.get("x-auth-token")})
        return JSONResponse(data["set_reply"], status_code=data["set_status"])

    return Starlette(routes=[Route("/last-tag", last_tag), Route("/state", state), Route("/api/state", slots),
                             Route("/set-slot", set_slot, methods=["POST"])])


class Served:
    """Run an ASGI app on 127.0.0.1:<port> in a thread (`with Served(app, port) as url:`)."""

    def __init__(self, asgi, port: int):
        self.server = uvicorn.Server(uvicorn.Config(asgi, host="127.0.0.1", port=port, log_level="warning"))
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self) -> str:
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self.url
            time.sleep(0.05)
        raise RuntimeError("fake did not start")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
