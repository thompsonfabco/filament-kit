"""A stand-in for the local label reader service (the `local_intake` module's daemon; tests only, never real models).

One Starlette app, state in a dict the test changes:
  GET  /v1/health     answers `data["health"]` with `data["health_status"]`
  POST /v1/read       records the JSON body in `data["reads"]` (with the query string), answers `data["read"]`
                      with `data["read_status"]`; `data["read"]` may be a callable(body) -> dict
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA",
        "color_hex": "8a8c8e", "net": 1000, "tare": 213, "density": 1.24, "count": 1, "nozzle": 220, "bed": 55,
        "nozzle_range": "200-230", "bed_range": "50-60", "lot": None, "note": "", "estimates": [], "sealed": True,
        "sealed_reason": "shrink wrap", "line": "PLA+"}


def reply(confidence: float = 0.93, tier: str = "cpu", **item) -> dict:
    return {"api_version": 1, "items": [{**ITEM, **item}], "questions": [], "confidence": confidence,
            "tier": tier, "usage": {"model": "fk-vision-cpu", "ms": 240}}


def new_data() -> dict:
    return {"health": {"status": "ok", "api_version": 1, "version": "0.1.0", "tiers": {"cpu": True, "gpu": False}},
            "health_status": 200, "read": reply(), "read_status": 200, "reads": []}


def app(data: dict) -> Starlette:
    async def health(request: Request):
        return JSONResponse(data["health"], status_code=data["health_status"])

    async def read(request: Request):
        body = await request.json()
        data["reads"].append({"query": str(request.url.query), "body": body})
        out = data["read"](body) if callable(data["read"]) else data["read"]
        return JSONResponse(out, status_code=data["read_status"])

    return Starlette(routes=[Route("/v1/health", health), Route("/v1/read", read, methods=["POST"])])
