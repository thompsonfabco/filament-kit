"""HTTPS JSON API for the phone app.

Every route but /api/info, /api/pair and /app.apk needs `Authorization: Bearer <token>`. Errors are
`{"error": <code>, "message": <text>}`; tracebacks are logged here and never sent.
"""
from __future__ import annotations

import functools
import logging

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import API_VERSION, __version__, config, intake, inventory, pairing, tags
from .intake import CapReached, PhotoError, ReadCap, ReadError
from .bridge import camera, registry
from .bridge.connection import ACTIONS, Manager, NoReply, PrinterOffline, UnknownPrinter
from .bridge.models import camera_kind
from .inventory import AddFailed, TagConflict
from .spoolman import Spoolman, SpoolmanError

log = logging.getLogger(__name__)

MAX_HINT = 2000
APK_TYPE = "application/vnd.android.package-archive"


class BadRequest(ValueError):
    pass


def _err(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, **extra}, status_code=status)


def _http_error(e: HTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "bad_request")
    return _err(e.status_code, code, str(e.detail))


def _to_response(e: Exception) -> JSONResponse:
    if isinstance(e, HTTPException):  # e.g. a malformed or oversized multipart body from request.form()
        return _http_error(e)
    if isinstance(e, PhotoError):
        return _err(400, "bad_photo", str(e))
    if isinstance(e, CapReached):
        return _err(429, "daily_cap", str(e))
    if isinstance(e, ReadError):
        return _err(404 if e.code == "not_found" else 502, e.code, e.message, read_id=e.read_id)
    if isinstance(e, TagConflict):
        return _err(409, "tag_conflict", str(e), reason=e.reason, other_spool=e.other)
    if isinstance(e, AddFailed):
        return _err(502, "spoolman_error", str(e), partial_spool_ids=e.partial.spool_ids)
    if isinstance(e, SpoolmanError):
        if e.status is None:
            return _err(503, "spoolman_unreachable",
                        "Spoolman is not reachable; check that the spoolman service is running")
        if e.status == 404:
            return _err(404, "not_found", f"not found in Spoolman: {e}")
        return _err(502, "spoolman_error", str(e))
    if isinstance(e, ValueError):
        return _err(400, "bad_request", str(e))
    log.error("internal error", exc_info=e)
    return _err(500, "internal", "internal error")


def _handle(fn):
    @functools.wraps(fn)
    async def wrapper(request: Request):
        try:
            return await fn(request)
        except Exception as e:  # noqa: BLE001 - every failure becomes a JSON error
            return _to_response(e)
    return wrapper


def _authed(fn):
    @functools.wraps(fn)
    async def wrapper(request: Request):
        header = request.headers.get("authorization", "")
        scheme, _, tok = header.partition(" ")
        device = None
        if scheme.lower() == "bearer" and tok.strip():
            device = await run_in_threadpool(pairing.check, tok.strip())
        if device is None:
            return _err(401, "unauthorized", "pair this phone with the server first (missing or revoked token)")
        request.state.device = device
        return await fn(request)
    return _handle(wrapper)


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise BadRequest("the request body must be JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("the request body must be a JSON object")
    return body


_KINDS = {bool: "true or false", float: "a number", str: "text"}


def _opt(body: dict, key: str, kind: type, default=None):
    """Optional body field of `kind` (bool, float = any JSON number, or str); None/absent gives `default`."""
    v = body.get(key)
    if v is None:
        return default
    if kind is float:
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
    else:
        ok = isinstance(v, kind)
    if not ok:
        raise BadRequest(f"{key} must be {_KINDS[kind]}")
    return v


def _apk_version() -> str | None:
    f = config.paths().opt / "app" / "version.txt"
    try:
        return f.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ---- printer routes --------------------------------------------------------------------------------------
FIRST_STATE_WAIT = 8.0  # seconds POST /api/printers waits for the first connection result


def _printer_view(p: registry.Printer, printers) -> dict:
    """The public shape of a printer. Built field by field so the Access Code can never leak."""
    state = "not_configured"
    if p.configured:
        state = printers.state(p.serial)
        if state == "not_configured":  # configured, but the manager has no connection for it (yet)
            state = "offline"
    try:
        summary = printers.summary(p.serial)
    except Exception:  # noqa: BLE001 - one odd report must not fail the whole printer list
        log.exception("printer %s: cannot summarize its report", p.serial)
        summary = None
    return {"id": p.serial, "name": p.name or p.serial, "model": p.model, "serial": p.serial, "ip": p.ip,
            "configured": p.configured, "state": state, "camera": {"kind": camera_kind(p.model)},
            "summary": summary}


NOT_SEEN = "That printer hasn't been seen on the network yet"


def _printer_routes(printers) -> list[Route]:
    def known(serial: str) -> registry.Printer:
        p = registry.load().get(serial)
        if p is None:
            raise HTTPException(404, "no such printer")
        return p

    @_authed
    async def printer_list(request: Request):
        def build() -> list[dict]:
            return [_printer_view(p, printers) for p in registry.load().values()]
        return JSONResponse({"printers": await run_in_threadpool(build)})

    @_authed
    async def printer_add(request: Request):
        body = await _json(request)
        serial, code = body.get("serial"), body.get("access_code")
        if not isinstance(serial, str) or not serial.strip():
            raise BadRequest("serial is required")
        if not isinstance(code, str) or not code.strip():
            raise BadRequest("access_code is required")
        name = _opt(body, "name", str)
        serial, code = serial.strip(), code.strip()
        problem = registry.check_fields(serial, code)
        if problem:
            raise BadRequest(problem)

        def run() -> dict | None:
            old = registry.load().get(serial)
            if old is None or not old.ip:  # the Access Code would have nowhere to go
                raise HTTPException(404, NOT_SEEN)
            # a connected printer keeps its code; a wrong-code or offline one is re-keyed with the new one
            replace = old is not None and old.configured and printers.state(serial) != "connected"
            try:
                p = registry.set_code(serial, code, name, replace=replace)
            except registry.AlreadyConfigured:
                return None
            printers.sync()
            printers.wait_settled(serial, FIRST_STATE_WAIT)
            return _printer_view(p, printers)
        view = await run_in_threadpool(run)
        if view is None:
            return _err(409, "exists", "this printer is already set up")
        return JSONResponse({"printer": view})

    @_authed
    async def printer_get(request: Request):
        serial = request.path_params["id"]

        def build() -> dict:
            p = known(serial)
            return {"printer": _printer_view(p, printers), "status": printers.status(serial)}
        return JSONResponse(await run_in_threadpool(build))

    @_authed
    async def printer_command(request: Request):
        """`POST /api/printers/{id}/command {action}`. The success body nests the Manager's result inside the
        route's own envelope, and the app parses exactly this shape:

            {"ok": true,                      # the request reached the printer and it answered
             "reply": {"ok": <bool>,          # every reply said "success" (false: refused, see reply.reply)
                       "reply": {...}}}       # the printer's raw reply object (result, reason, err_code ...)

        Errors: 400 `bad_request` (unknown action), 404 `not_found`, 409 `printer_offline`, 504 `no_reply`."""
        serial = request.path_params["id"]
        action = (await _json(request)).get("action")
        if action not in ACTIONS:
            raise BadRequest("action must be one of: " + ", ".join(ACTIONS))
        device = request.state.device

        def run() -> dict:
            result = "ok"
            try:
                return printers.command(serial, action)
            except Exception as e:
                result = type(e).__name__
                raise
            finally:
                log.info("printer command device_id=%s serial=%s action=%s result=%s", device, serial, action, result)
        try:
            reply = await run_in_threadpool(run)
        except PrinterOffline:
            return _err(409, "printer_offline", "the printer is offline; check that it is on and on the network")
        except NoReply:
            return _err(504, "no_reply", "the printer did not answer in time")
        except UnknownPrinter:
            return _err(404, "not_found", "no such printer")
        return JSONResponse({"ok": True, "reply": reply})

    return [
        Route("/api/printers", printer_list),
        Route("/api/printers", printer_add, methods=["POST"]),
        Route("/api/printers/{id}", printer_get),
        Route("/api/printers/{id}/command", printer_command, methods=["POST"]),
    ]
# ---- end printer routes ----------------------------------------------------------------------------------


def create_app(sm: Spoolman | None = None, claude=None, printers=None, camera_hub=None) -> Starlette:
    cfg = config.load()
    sm = sm if sm is not None else Spoolman(cfg["spoolman_url"])
    printers = printers if printers is not None else Manager(spoolman=sm)  # started by __main__, not here
    # stopped by __main__'s lifespan; the Manager's `cert_changed` also refuses the camera
    camera_hub = camera_hub if camera_hub is not None else camera.Hub(printer_state=printers.state)
    cap = ReadCap(config.paths().state / "reads.json", cfg["reads_per_day"])

    def rules() -> dict:  # sync: call it from inside the threadpool
        return config.load()["placement"]

    def info_body() -> dict:
        return {"name": config.load()["server_name"], "version": __version__, "api": API_VERSION,
                "apk_version": _apk_version()}

    @_handle
    async def info(request: Request):
        return JSONResponse(await run_in_threadpool(info_body))

    @_handle
    async def pair(request: Request):
        code = (await _json(request)).get("code")
        try:
            token = await run_in_threadpool(pairing.redeem_code, code)
        except pairing.PairingError as e:
            return _err(401, "unauthorized", str(e))
        return JSONResponse({"token": token})

    @_authed
    async def intake_read(request: Request):
        async with request.form() as form:
            photos = []
            for i, f in enumerate(form.getlist("photo")):
                if not isinstance(f, UploadFile):
                    raise BadRequest("photo must be a file upload")
                photos.append((f.filename or f"photo{i + 1}", await f.read(intake.MAX_PHOTO_BYTES + 1)))
            hint = form.get("hint") or ""
            tag = form.get("tag") or ""
        if not isinstance(hint, str) or not isinstance(tag, str):
            raise BadRequest("hint and tag must be text fields")
        images = intake.check_photos(photos)
        uid = tags.normalize_uid(tag) if tag.strip() else None
        def run() -> dict:
            cap.take()
            try:
                return intake.read_labels(sm, images, hint[:MAX_HINT], uid, claude)
            except SpoolmanError:  # Spoolman down: the catalog fetch failed before Claude was called
                cap.refund()
                raise
        return JSONResponse(await run_in_threadpool(run))

    @_authed
    async def intake_retry(request: Request):
        read_id = request.path_params["read_id"]

        def run() -> dict:
            if not intake.is_kept(read_id):  # an unknown or expired read fails with not_found, using no read
                return intake.retry(read_id, sm, claude)
            cap.take()
            try:
                return intake.retry(read_id, sm, claude)
            except SpoolmanError:  # Spoolman down: the catalog fetch failed before Claude was called
                cap.refund()
                raise
        return JSONResponse(await run_in_threadpool(run))

    @_authed
    async def intake_add(request: Request):
        body = await _json(request)
        dry = _opt(body, "dry_run", bool, True)
        uid = _opt(body, "tag", str) or None
        r = await run_in_threadpool(lambda: inventory.add_and_link(sm, body.get("items"), rules(), dry, uid))
        return JSONResponse({"spool_ids": r.spool_ids, "lines": r.lines, "dry": r.dry})

    @_authed
    async def tag_lookup(request: Request):
        return JSONResponse({"spool": await run_in_threadpool(inventory.by_tag, sm, request.path_params["uid"])})

    @_authed
    async def spool_link(request: Request):
        body = await _json(request)
        tag = body.get("tag")
        if not isinstance(tag, str) or not tag.strip():
            raise BadRequest("tag is required")
        kw = dict(gross=_opt(body, "gross", float), location=_opt(body, "location", str),
                  force=_opt(body, "force", bool, False), dry=_opt(body, "dry_run", bool, True))
        spool = await run_in_threadpool(
            lambda: inventory.open_spool(sm, request.path_params["id"], tag, rules(), **kw))
        return JSONResponse({"spool": spool})

    @_authed
    async def spool_update(request: Request):
        body = await _json(request)
        spool = await run_in_threadpool(functools.partial(
            inventory.update_spool, sm, request.path_params["id"], gross=_opt(body, "gross", float),
            remaining=_opt(body, "remaining", float), location=_opt(body, "location", str),
            empty=_opt(body, "empty", bool, False), dry=_opt(body, "dry_run", bool, True)))
        return JSONResponse({"spool": spool})

    @_authed
    async def spool_search(request: Request):
        q = request.query_params.get("q", "")
        sealed = request.query_params.get("sealed", "").lower() in ("1", "true", "yes")
        return JSONResponse({"spools": await run_in_threadpool(inventory.find, sm, q, sealed)})

    @_authed
    async def locations(request: Request):
        def names() -> list[str]:
            out = list(config.load()["locations"])
            for loc in sorted({s["location"] for s in sm.get("spool") if s.get("location")}):
                if loc not in out:
                    out.append(loc)
            return out
        return JSONResponse({"locations": await run_in_threadpool(names)})

    @_handle
    async def apk(request: Request):
        f = config.paths().opt / "app" / "filament-kit.apk"
        if not await run_in_threadpool(f.is_file):
            return _err(404, "not_found", "no app package is installed on this server")
        return FileResponse(f, media_type=APK_TYPE, filename="filament-kit.apk")

    async def http_error(request: Request, exc: HTTPException):
        return _http_error(exc)

    return Starlette(
        routes=[
            Route("/api/info", info),
            Route("/api/pair", pair, methods=["POST"]),
            Route("/api/intake/read", intake_read, methods=["POST"]),
            Route("/api/intake/retry/{read_id}", intake_retry, methods=["POST"]),
            Route("/api/intake/add", intake_add, methods=["POST"]),
            Route("/api/tags/{uid}", tag_lookup),
            Route("/api/spools", spool_search),
            Route("/api/spools/{id:int}/link", spool_link, methods=["POST"]),
            Route("/api/spools/{id:int}", spool_update, methods=["PATCH"]),
            Route("/api/locations", locations),
            Route("/app.apk", apk),
            *_printer_routes(printers),
            *camera.routes(camera_hub, _authed),
        ],
        exception_handlers={HTTPException: http_error},
    )
