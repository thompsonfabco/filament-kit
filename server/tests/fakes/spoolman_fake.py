"""In-memory Spoolman v0.27 stand-in (Starlette) for tests.

`new_store()` returns the data dict; `app(store)` serves it. Tests mutate/seed the store directly.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

VERSION = "0.27.0"


def new_store() -> dict[str, Any]:
    return {
        "vendors": {}, "filaments": {}, "spools": {},
        "fields": {"spool": [], "filament": [], "vendor": []},
        "next": {"vendor": 1, "filament": 1, "spool": 1},
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(msg: str, status: int) -> JSONResponse:
    return JSONResponse({"message": msg}, status_code=status)


def _filament_view(store: dict, f: dict) -> dict:
    out = copy.deepcopy(f)
    vid = out.pop("vendor_id", None)
    out["vendor"] = copy.deepcopy(store["vendors"][vid]) if vid else None
    return out


def _spool_view(store: dict, s: dict) -> dict:
    out = copy.deepcopy(s)
    fid = out.pop("filament_id")
    out["filament"] = _filament_view(store, store["filaments"][fid])
    return out


def _check_extra(store: dict, entity: str, extra: Any) -> JSONResponse | None:
    """Spoolman rule: keys must be registered fields; values must be strings holding JSON."""
    if extra is None:
        return None
    if not isinstance(extra, dict):
        return _err("extra must be an object", 422)
    keys = {f["key"] for f in store["fields"][entity]}
    for k, v in extra.items():
        if k not in keys:
            return _err(f"Unknown extra field {k}", 422)
        try:
            if not isinstance(v, str):
                raise ValueError
            json.loads(v)
        except ValueError:
            return _err(f"Extra field {k} value is not a JSON string", 422)
    return None


def app(store: dict[str, Any] | None = None) -> Starlette:
    store = store if store is not None else new_store()

    def alloc(kind: str) -> int:
        n = store["next"][kind]
        store["next"][kind] = n + 1
        return n

    async def info(request: Request):
        return JSONResponse({"version": VERSION, "debug_mode": False, "db_type": "sqlite"})

    async def vendors(request: Request):
        if request.method == "GET":
            return JSONResponse(list(store["vendors"].values()))
        b = await request.json()
        if not b.get("name"):
            return _err("name required", 422)
        if (bad := _check_extra(store, "vendor", b.get("extra"))):
            return bad
        v = {"id": alloc("vendor"), "registered": _now(), "name": b["name"],
             "empty_spool_weight": b.get("empty_spool_weight"),
             "comment": b.get("comment"), "extra": b.get("extra", {})}
        store["vendors"][v["id"]] = v
        return JSONResponse(v)

    async def filaments(request: Request):
        if request.method == "GET":
            return JSONResponse([_filament_view(store, f) for f in store["filaments"].values()])
        b = await request.json()
        vid = b.get("vendor_id")
        if vid is not None and vid not in store["vendors"]:
            return _err(f"No vendor with ID {vid} found", 404)
        if (bad := _check_extra(store, "filament", b.get("extra"))):
            return bad
        f = {"id": alloc("filament"), "registered": _now(), "name": b.get("name"),
             "vendor_id": vid, "material": b.get("material"), "price": b.get("price"),
             "density": b.get("density", 1.24), "diameter": b.get("diameter", 1.75),
             "weight": b.get("weight"), "spool_weight": b.get("spool_weight"),
             "comment": b.get("comment"),
             "settings_extruder_temp": b.get("settings_extruder_temp"),
             "settings_bed_temp": b.get("settings_bed_temp"),
             "color_hex": b.get("color_hex"), "extra": b.get("extra", {})}
        store["filaments"][f["id"]] = f
        return JSONResponse(_filament_view(store, f))

    async def filament_one(request: Request):
        f = store["filaments"].get(int(request.path_params["id"]))
        if not f:
            return _err("Filament not found", 404)
        return JSONResponse(_filament_view(store, f))

    def apply_weights(s: dict, b: dict) -> None:
        fil = store["filaments"][s["filament_id"]]
        if "initial_weight" in b:
            s["initial_weight"] = b["initial_weight"]
        elif s.get("initial_weight") is None:
            s["initial_weight"] = fil.get("weight")
        if "spool_weight" in b:
            s["spool_weight"] = b["spool_weight"]
        elif s.get("spool_weight") is None:
            s["spool_weight"] = fil.get("spool_weight")
        init = s.get("initial_weight")
        if "remaining_weight" in b and init is not None:
            s["used_weight"] = max(init - b["remaining_weight"], 0)
        elif "used_weight" in b:
            s["used_weight"] = b["used_weight"]
        s.setdefault("used_weight", 0)
        s["remaining_weight"] = None if init is None else init - s["used_weight"]

    async def spools(request: Request):
        if request.method == "GET":
            items = list(store["spools"].values())
            if request.query_params.get("allow_archived", "false") != "true":
                items = [s for s in items if not s["archived"]]
            return JSONResponse([_spool_view(store, s) for s in items])
        b = await request.json()
        fid = b.get("filament_id")
        if fid not in store["filaments"]:
            return _err(f"No filament with ID {fid} found", 404)
        if (bad := _check_extra(store, "spool", b.get("extra"))):
            return bad
        s = {"id": alloc("spool"), "registered": _now(), "first_used": b.get("first_used"),
             "last_used": None, "filament_id": fid, "location": b.get("location"),
             "comment": b.get("comment"), "archived": b.get("archived", False),
             "extra": b.get("extra", {})}
        apply_weights(s, b)
        store["spools"][s["id"]] = s
        return JSONResponse(_spool_view(store, s))

    async def spool_one(request: Request):
        s = store["spools"].get(int(request.path_params["id"]))
        if not s:
            return _err("Spool not found", 404)
        if request.method == "PATCH":
            b = await request.json()
            if (bad := _check_extra(store, "spool", b.get("extra"))):
                return bad
            if "filament_id" in b:
                if b["filament_id"] not in store["filaments"]:
                    return _err("No such filament", 404)
                s["filament_id"] = b["filament_id"]
            for k in ("first_used", "last_used", "location", "comment", "archived"):
                if k in b:
                    s[k] = b[k]
            if "extra" in b:
                s["extra"] = {**s["extra"], **b["extra"]}
            apply_weights(s, b)
        return JSONResponse(_spool_view(store, s))

    async def fields(request: Request):
        entity = request.path_params["entity"]
        if entity not in store["fields"]:
            return _err("Unknown entity", 404)
        return JSONResponse(store["fields"][entity])

    async def field_create(request: Request):
        entity, key = request.path_params["entity"], request.path_params["key"]
        if entity not in store["fields"]:
            return _err("Unknown entity", 404)
        if any(f["key"] == key for f in store["fields"][entity]):
            return _err("Field with this key already exists", 409)
        b = await request.json()
        f = {"name": b.get("name", key), "order": b.get("order", 0),
             "field_type": b.get("field_type", "text"), "key": key, "entity_type": entity}
        for opt in ("unit", "default_value", "choices", "multi_choice"):
            if opt in b:
                f[opt] = b[opt]
        store["fields"][entity].append(f)
        return JSONResponse(store["fields"][entity])

    return Starlette(routes=[
        Route("/api/v1/info", info),
        Route("/api/v1/vendor", vendors, methods=["GET", "POST"]),
        Route("/api/v1/filament", filaments, methods=["GET", "POST"]),
        Route("/api/v1/filament/{id:int}", filament_one),
        Route("/api/v1/spool", spools, methods=["GET", "POST"]),
        Route("/api/v1/spool/{id:int}", spool_one, methods=["GET", "PATCH"]),
        Route("/api/v1/field/{entity}", fields),
        Route("/api/v1/field/{entity}/{key}", field_create, methods=["POST"]),
    ])
