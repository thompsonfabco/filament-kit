"""Stand-ins for the owner's LAN services the web process reads (tests only).

One Starlette app, state in a dict the test mutates:
  GET  /last-tag      a lasttag reader (SV08 lasttag service or the station's /last-tag): `data["tag"]`
  GET  /state         the intake station's state: `data["state"]`
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import serving


def new_data() -> dict:
    return {"tag": {"status": "none"}, "state": {"tag": None, "scale": None, "last_weight": None}}


def app(data: dict) -> Starlette:
    async def last_tag(request: Request):
        return JSONResponse(data["tag"])

    async def state(request: Request):
        return JSONResponse(data["state"])

    return Starlette(routes=[Route("/last-tag", last_tag), Route("/state", state)])


class Served:
    """Run an ASGI app on 127.0.0.1 in a thread (`with Served(app) as url:`). The port is bound when this object is
    made (`.port`, `.url`), so a test can name it in a config first; nothing answers there until `with`."""

    def __init__(self, asgi, port: int = 0):
        self.running = serving.Running(asgi, serving.bind(port))
        self.port, self.url = self.running.port, self.running.url

    def __enter__(self) -> str:
        self.running.start()
        return self.url

    def __exit__(self, *exc) -> None:
        self.running.stop()
