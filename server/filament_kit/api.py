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


def create_app(sm: Spoolman | None = None, claude=None) -> Starlette:
    cfg = config.load()
    sm = sm if sm is not None else Spoolman(cfg["spoolman_url"])
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
        await run_in_threadpool(cap.take)
        out = await run_in_threadpool(intake.read_labels, sm, images, hint[:MAX_HINT], uid, claude)
        return JSONResponse(out)

    @_authed
    async def intake_retry(request: Request):
        read_id = request.path_params["read_id"]

        def run() -> dict:
            if intake.is_kept(read_id):  # an unknown or expired read fails with not_found without using up a read
                cap.take()
            return intake.retry(read_id, sm, claude)
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
        ],
        exception_handlers={HTTPException: http_error},
    )
