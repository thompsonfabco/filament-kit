"""Stand-ins for the owner's LAN services the web process reads (tests only).

One Starlette app, state in a dict the test mutates:
  GET  /last-tag      a lasttag reader (SV08 lasttag service or the station's /last-tag): `data["tag"]`
  GET  /state         the intake station's state: `data["state"]`
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
    return {"tag": {"status": "none"}, "state": {"tag": None, "scale": None, "last_weight": None}}


def app(data: dict) -> Starlette:
    async def last_tag(request: Request):
        return JSONResponse(data["tag"])

    async def state(request: Request):
        return JSONResponse(data["state"])

    return Starlette(routes=[Route("/last-tag", last_tag), Route("/state", state)])


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
