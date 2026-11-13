"""A stand-in for the local label reader service (filament-kit-vision's daemon; tests only, never real models), in the
forms of contract v1 (the module's docs/api-contract.md).

One Starlette app, state in a dict the test changes:
  GET  /v1/health     answers `data["health"]` with `data["health_status"]`
  POST /v1/read       records the JSON body and Authorization header in `data["reads"]`; answers `data["read"]`
  POST /v1/revise     the same into `data["revises"]`; answers `data["revise"]` (a callable(body) -> dict is fine)
  `data["errors"]`    a list of (status, code, retry_after) popped first by either POST: an error answer
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "SUNLU", "name": "PLA+ Grey", "material": "PLA",
        "line": "PLA+", "color_hex": "8A8C8E", "net": 1000, "tare": 213, "density": 1.24, "count": 1, "nozzle": 220,
        "bed": 55, "nozzle_range": "200-230", "bed_range": "50-60", "lot": None, "note": "", "estimates": [],
        "sealed": True, "sealed_reason": "shrink wrap"}


def reply(confidence: float = 0.93, tier: str = "cpu", **item) -> dict:
    return {"api_version": "1.0",
            "items": [{**ITEM, "confidence": confidence, "color_name": "Grey", "color_family": "grey",
                       "field_confidence": {"vendor": 0.97, "material": 0.99, "color": confidence}, **item}],
            "questions": [],
            "reader": {"service": "filament-kit-vision", "module_version": "0.1.0", "tier_used": tier,
                       "escalated": False, "fallback_reason": None, "model": f"fake-{tier}", "latency_ms": 240.5},
            "usage": {"model": f"filament-kit-vision/{tier}", "input_tokens": 0, "cached": 0, "output_tokens": 0}}


def new_data() -> dict:
    return {"health": {"service": "filament-kit-vision", "api_version": "1.0", "module_version": "0.1.0",
                       "status": "ok", "default_tier": "auto", "revise": True, "auth_required": False,
                       "tiers": {"cpu": {"usable": True, "reason": None},
                                 "gpu": {"usable": False, "reason": "no CUDA device", "loaded": False}},
                       "last_read_at": None},
            "health_status": 200, "read": reply(), "revise": reply(vendor="Polymaker", name="PolyLite PLA Grey"),
            "errors": [], "reads": [], "revises": []}


def app(data: dict) -> Starlette:
    async def health(request: Request):
        return JSONResponse(data["health"], status_code=data["health_status"])

    def _post(kind: str):
        async def handler(request: Request):
            body = await request.json()
            data[kind + "s"].append({"body": body, "auth": request.headers.get("authorization")})
            if data["errors"]:
                status, code, retry = data["errors"].pop(0)
                return JSONResponse({"error": {"code": code, "message": f"fake {code}"}}, status_code=status,
                                    headers={"Retry-After": str(retry)} if retry is not None else None)
            out = data[kind](body) if callable(data[kind]) else data[kind]
            return JSONResponse(out)
        return handler

    return Starlette(routes=[Route("/v1/health", health), Route("/v1/read", _post("read"), methods=["POST"]),
                             Route("/v1/revise", _post("revise"), methods=["POST"])])
