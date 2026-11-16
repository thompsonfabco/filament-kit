"""A stand-in for the local label reader service (spoolwarden-vision's daemon; tests only, never real models), in the
forms of contract v1 (the module's docs/api-contract.md).

One Starlette app, state in a dict the test changes:
  GET  /v1/health     answers `data["health"]` with `data["health_status"]`
  POST /v1/read       records the JSON body and Authorization header in `data["reads"]`; answers `data["read"]`
  POST /v1/revise     the same into `data["revises"]`; answers `data["revise"]` (a callable(body) -> dict is fine)
  `data["errors"]`    a list of (status, code, retry_after) popped first by either POST (and by every feedback call):
                      an error answer
API 1.1, the opt-in correction queue (in memory; the fake never contacts any real upload address):
  GET  /v1/feedback               {opt_in, endpoint_configured, count, bundle_mb, entries}
  POST /v1/feedback               queue {images_b64, predicted, corrected, note[, source, record]}: 403 feedback_disabled
                                  while `data["opt_in"]` is false; a `record` already queued replaces its entry
  DELETE /v1/feedback/<id>        404 not_found for an unknown id
  GET  /v1/feedback/bundle.zip    a real zip (pending_feedback.xml + the photos); 404 empty_feedback_queue when empty
  POST /v1/feedback/submit        403 while opt-in is off; clears the queue, answers {ok, sent}; the body is recorded
                                  in `data["submits"]` (a test checks it holds no address); `data["submit"]` may be a
                                  (status, code) pair to fail with
  `data["token"]`                 when set, the feedback routes need `Authorization: Bearer <token>` (401 otherwise)
  `data["bodies"]`                every JSON body any feedback call received (the no-address test reads it)
  `capabilities(data)`            a section-14 health `capabilities` object from the live state;
  `feedback_health(data, ...)`    puts it (or not) into `data["health"]` as a 1.1 reader's health
"""
from __future__ import annotations

import base64
import io
import zipfile

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
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
            "reader": {"service": "spoolwarden-vision", "module_version": "0.2.2", "tier_used": tier,
                       "escalated": False, "fallback_reason": None, "model": f"fake-{tier}", "latency_ms": 240.5},
            "usage": {"model": f"spoolwarden-vision/{tier}", "input_tokens": 0, "cached": 0, "output_tokens": 0}}


def new_data() -> dict:
    return {"health": {"service": "spoolwarden-vision", "api_version": "1.0", "module_version": "0.2.2",
                       "status": "ok", "default_tier": "auto", "revise": True, "auth_required": False,
                       "tiers": {"cpu": {"usable": True, "reason": None},
                                 "gpu": {"usable": False, "reason": "no CUDA device", "loaded": False}},
                       "last_read_at": None},
            "health_status": 200, "read": reply(), "revise": reply(vendor="Polymaker", name="PolyLite PLA Grey"),
            "errors": [], "reads": [], "revises": [],
            "opt_in": True, "endpoint_configured": True, "queue": [], "next_id": 1, "token": None, "bodies": [],
            "feedback_auth": [], "submits": [], "submit": None, "submit_state": {"api_version": "1.1", "status": "idle"},
            "source_record": True, "accelerator": "cpu (fake)"}


def capabilities(data: dict) -> dict:
    """The section-14 `capabilities` object, from the fake's live state."""
    return {"feedback": {"supported": True, "opt_in": data["opt_in"],
                         "endpoint_configured": data["endpoint_configured"], "count": len(data["queue"]),
                         **({"source": True, "record": True} if data["source_record"] else {})},
            "accelerator": data["accelerator"]}


def feedback_health(data: dict, version: str = "1.1", with_capabilities: bool = True) -> dict:
    """Make the fake's health that of a 1.1 reader (with or without `capabilities`) and return it."""
    h = {**data["health"], "api_version": version, "module_version": "0.2.0"}
    h.pop("capabilities", None)
    if with_capabilities:
        h["capabilities"] = capabilities(data)
    data["health"] = h
    return h


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

    def _err(status: int, code: str):
        return JSONResponse({"error": {"code": code, "message": f"fake {code}"}}, status_code=status)

    def _gate(request: Request, body=None):
        """The front of every feedback call: record the body, then the token check and a queued error."""
        data["bodies"].append(body)
        data["feedback_auth"].append(request.headers.get("authorization"))
        if data["token"] and request.headers.get("authorization") != f"Bearer {data['token']}":
            return _err(401, "unauthorized")
        if data["errors"]:
            status, code, retry = data["errors"].pop(0)
            return JSONResponse({"error": {"code": code, "message": f"fake {code}"}}, status_code=status,
                                headers={"Retry-After": str(retry)} if retry is not None else None)
        return None

    def _summary(e: dict) -> dict:
        keys = ("id", "created_at", "predicted", "corrected", "note", "photos", "thumbnail_b64")
        return {**{k: e[k] for k in keys}, **{k: e[k] for k in ("source", "record") if k in e}}

    def _mb() -> float:
        return round(sum(len(j) for e in data["queue"] for j in e["jpegs"]) / 1048576, 6)

    async def feedback_list(request: Request):
        if (r := _gate(request)):
            return r
        return JSONResponse({"api_version": "1.1", "opt_in": data["opt_in"],
                             "endpoint_configured": data["endpoint_configured"], "count": len(data["queue"]),
                             "bundle_mb": _mb(), "entries": [_summary(e) for e in data["queue"]]})

    async def feedback_add(request: Request):
        body = await request.json()
        if (r := _gate(request, body)):
            return r
        if not data["opt_in"]:
            return _err(403, "feedback_disabled")
        images = body.get("images_b64") or []
        if not images:
            return _err(400, "bad_request")
        jpegs = [base64.b64decode(i) for i in images]
        if sum(len(j) for j in jpegs) > data.get("max_add_bytes", 20 * 1048576):
            return _err(413, "too_large")
        e = {"id": f"fb-{data['next_id']}", "created_at": "2026-11-15T12:00:00Z",
             "predicted": body.get("predicted") or {}, "corrected": body.get("corrected") or {},
             "note": str(body.get("note") or ""), "photos": len(jpegs), "jpegs": jpegs,
             "thumbnail_b64": base64.b64encode(jpegs[0][:16]).decode("ascii")}
        data["next_id"] += 1
        if data["source_record"]:
            for k in ("source", "record"):
                if body.get(k) is not None:
                    e[k] = str(body[k])
        if e.get("record"):                  # a spool revised twice replaces its entry
            data["queue"] = [q for q in data["queue"] if q.get("record") != e["record"]]
        data["queue"].append(e)
        return JSONResponse({"api_version": "1.1", "ok": True, "id": e["id"], "queued_count": len(data["queue"]),
                             "bundle_mb": _mb()})

    async def feedback_delete(request: Request):
        if (r := _gate(request)):
            return r
        eid = request.path_params["entry_id"]
        keep = [e for e in data["queue"] if e["id"] != eid]
        if len(keep) == len(data["queue"]):
            return _err(404, "not_found")
        data["queue"] = keep
        return JSONResponse({"api_version": "1.1", "ok": True, "deleted_id": eid, "queued_count": len(keep),
                             "bundle_mb": _mb()})

    async def feedback_bundle(request: Request):
        if (r := _gate(request)):
            return r
        if not data["queue"]:
            return _err(404, "empty_feedback_queue")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("pending_feedback.xml", "<feedback>" + "".join(
                f'<entry id="{e["id"]}"/>' for e in data["queue"]) + "</feedback>")
            for e in data["queue"]:
                for n, j in enumerate(e["jpegs"]):
                    z.writestr(f"{e['id']}_{n}.jpg", j)
        return Response(buf.getvalue(), media_type="application/zip")

    async def feedback_image(request: Request):
        if (r := _gate(request)):
            return r
        eid = request.path_params["entry_id"]
        try:
            idx = int(request.query_params.get("index", "0"))
        except ValueError:
            return _err(400, "bad_request")
        entry = next((e for e in data["queue"] if e["id"] == eid), None)
        if entry is None or idx < 0 or idx >= len(entry["jpegs"]):
            return _err(404, "not_found")
        return Response(entry["jpegs"][idx], media_type="image/jpeg")

    async def feedback_submit(request: Request):
        body = await request.json()
        data["submits"].append(body)
        if (r := _gate(request, body)):
            return r
        if not data["opt_in"]:
            return _err(403, "feedback_disabled")
        if not data["queue"]:
            return _err(400, "bad_request")
        if data["submit"]:
            return _err(*data["submit"])
        sent, data["queue"] = len(data["queue"]), []
        data["submit_state"] = {"api_version": "1.1", "ok": True, "status": "ok", "sent": sent}
        return JSONResponse({"api_version": "1.1", "accepted": True, "status": "running"}, status_code=202)

    async def feedback_submit_status(request: Request):
        if (r := _gate(request)):
            return r
        return JSONResponse(data["submit_state"])

    return Starlette(routes=[
        Route("/v1/health", health), Route("/v1/read", _post("read"), methods=["POST"]),
        Route("/v1/revise", _post("revise"), methods=["POST"]),
        Route("/v1/feedback", feedback_list, methods=["GET"]),
        Route("/v1/feedback", feedback_add, methods=["POST"]),
        Route("/v1/feedback/bundle.zip", feedback_bundle, methods=["GET"]),
        Route("/v1/feedback/submit", feedback_submit, methods=["POST"]),
        Route("/v1/feedback/submit", feedback_submit_status, methods=["GET"]),
        Route("/v1/feedback/{entry_id}/image", feedback_image, methods=["GET"]),
        Route("/v1/feedback/{entry_id}", feedback_delete, methods=["DELETE"])])
