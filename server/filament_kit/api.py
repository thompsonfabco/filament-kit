"""HTTPS JSON API for the phone app.

Every route but /api/info, /api/pair and /app.apk needs `Authorization: Bearer <token>`. Errors are
`{"error": <code>, "message": <text>}`; tracebacks are logged here and never sent.
"""
from __future__ import annotations

import functools
import logging
import math
import re

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import API_VERSION, __version__, config, intake, inventory, modules, pairing, profiles_api, tags
from .intake import CapReached, PhotoError, ReadCap, ReadError
from .bridge import camera, loading, mapping, registry, usage
from .bridge.connection import ACTIONS, DEVELOPER_MODE_REASON, Manager, NoReply, PrinterOffline, UnknownPrinter
from .bridge.slottest import NoStatus, PrinterBusy
from .bridge.models import camera_kind
from .inventory import AddFailed, TagConflict
from .profiles.errors import ProfileError
from .spoolman import Spoolman, SpoolmanError
from .station_client import StationClient, StationUnreachable

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
    if isinstance(e, ProfileError):
        if e.status >= 500:
            log.error("profiles error %s", e.code, exc_info=e)
        return _err(e.status, e.code, e.message, **e.extra)
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
    bridge = _bridge_error(e)
    if bridge is not None:
        return bridge
    if isinstance(e, ValueError):
        return _err(400, "bad_request", str(e))
    log.error("internal error", exc_info=e)
    return _err(500, "internal", "internal error")


OFFLINE = "the printer is offline; check that it is on and on the network"
CERT_CHANGED = camera.CERT_CHANGED   # one text for the API and the camera


def _bridge_error(e: Exception) -> JSONResponse | None:
    """Slot mapping, loading and usage errors (route-contract.md); None for anything else."""
    if isinstance(e, usage.UsageError):
        return _err(e.status, e.code, str(e))
    if isinstance(e, mapping.AlreadyRunning):   # also LoadRunning: a load is writing to the printer
        return _err(409, "already_running", e.message)
    if isinstance(e, mapping.CertChanged):
        return _err(409, "cert_changed", CERT_CHANGED)
    if isinstance(e, PrinterBusy):
        return _err(409, "printer_busy", f"the printer is busy ({e}); try again once it is idle")
    if isinstance(e, NoStatus):
        return _err(409, "printer_offline", str(e))
    if isinstance(e, PrinterOffline):
        return _err(409, "printer_offline", OFFLINE)
    if isinstance(e, loading.NoPreset):
        return _err(409, "no_preset", str(e))
    if isinstance(e, UnknownPrinter):
        return _err(404, "not_found", "no such printer")
    if isinstance(e, loading.NotFound):
        return _err(404, "not_found", str(e))
    return None


def _module_off(module: str) -> JSONResponse:
    return _err(409, "module_off", f"the {module} module is turned off on this server", module=module)


def _gated(routes: list[Route], module: str, on: frozenset[str]) -> list[Route]:
    """`routes` as they are when `module` is on; otherwise the same paths and methods, each answering 409
    `module_off` (after the usual token check, so an unpaired caller still gets 401)."""
    if module in on:
        return routes

    @_authed
    async def off(request: Request):
        return _module_off(module)
    return [Route(r.path, off, methods=sorted(r.methods or ())) for r in routes]


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
    return {"id": p.serial, "name": registry.display_name(p), "model": p.model, "serial": p.serial, "ip": p.ip,
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


# ---- slot mapping, loading and usage routes (route-contract.md) ------------------------------------------
LABEL = re.compile(r"[A-Za-z0-9-]{1,16}")    # A1-D4, HT-A ..., Ext
MAX_DAYS = 366.0


def _bridge_routes(printers, mapper: mapping.Mapper, sm) -> list[Route]:
    def known(serial: str) -> registry.Printer:
        p = registry.load().get(serial)
        if p is None:
            raise UnknownPrinter(serial)
        return p

    def label_of(request: Request) -> str:
        label = request.path_params["label"]
        if not LABEL.fullmatch(label):
            raise loading.NotFound(f"no slot {label!r}")
        return label

    def not_cert_changed(serial: str) -> None:
        if printers.state(serial) == "cert_changed":
            raise mapping.CertChanged(serial)

    def not_mapping(serial: str) -> None:
        """Slot mapping changes the slots (test colours, the calibration job): no load or unload meanwhile, also
        when `filament-kit printer map` runs it in another process (dry runs too: the slots are in flux)."""
        if mapper.in_progress(serial):
            raise mapping.AlreadyRunning(serial)

    def sealed() -> str:
        return config.load()["placement"].get("sealed_location") or loading.SEALED

    def audit(what: str, device, result: str, **fields) -> None:
        extra = " ".join(f"{k}={_safe(v)}" for k, v in fields.items())
        log.info("%s device_id=%s %s result=%s", what, device, extra, result)

    def audited(what: str, device, fn, **fields):
        result = "ok"
        try:
            return fn()
        except Exception as e:
            result = type(e).__name__
            raise
        finally:
            audit(what, device, result, **fields)

    @_authed
    async def map_start(request: Request):
        serial = request.path_params["id"]
        job = await run_in_threadpool(audited, "slot mapping", request.state.device,
                                      lambda: mapper.start(serial), serial=serial)
        return JSONResponse({"job_id": job}, status_code=202)

    @_authed
    async def map_get(request: Request):
        serial = request.path_params["id"]

        def build() -> dict:
            known(serial)
            return mapper.view(serial)
        return JSONResponse(await run_in_threadpool(build))

    @_authed
    async def slot_load(request: Request):
        serial, label = request.path_params["id"], label_of(request)
        body = await _json(request)
        spool_id = body.get("spool_id")
        if not isinstance(spool_id, int) or isinstance(spool_id, bool):
            raise BadRequest("spool_id must be a whole number")
        dry = _opt(body, "dry_run", bool, True)

        def run() -> dict:
            known(serial)
            not_cert_changed(serial)
            not_mapping(serial)
            try:
                r = loading.load(printers, sm, serial, label, spool_id, dry, sealed_location=sealed())
            except loading.SlotWriteFailed as e:
                if printers.state(serial) == "needs_developer_mode" or DEVELOPER_MODE_REASON.search(str(e)):
                    raise _Refused("needs_developer_mode",
                                   f"{e}; turn on Developer Mode (LAN-only mode) on the printer and retry") from e
                raise _Refused("write_refused", str(e)) from e
            return {**r, "confirmed": bool(r.get("confirmed"))}
        try:
            r = await run_in_threadpool(audited, "slot load", request.state.device, run, serial=serial,
                                        slot=label, spool=spool_id, dry_run=dry)
        except _Refused as e:
            return _err(409, e.code, e.message)
        return JSONResponse(r)

    @_authed
    async def slot_unload(request: Request):
        serial, label = request.path_params["id"], label_of(request)
        dry = _opt(await _json(request), "dry_run", bool, True)

        def run() -> dict:
            known(serial)
            not_mapping(serial)
            r = loading.unload(printers, sm, serial, label, dry, sealed_location=sealed())
            first = next((m for m in r["moved_back"] if m["id"] == r["spool"].get("id")), None)
            return {**r, "location": first["location"] if first else r["spool"].get("location")}
        return JSONResponse(await run_in_threadpool(audited, "slot unload", request.state.device, run,
                                                    serial=serial, slot=label, dry_run=dry))

    @_authed
    async def usage_list(request: Request):
        serial = request.path_params["id"]
        raw = request.query_params.get("days", str(usage.UNDO_DAYS))
        try:
            days = float(raw)
        except ValueError:
            raise BadRequest("days must be a number") from None
        if not math.isfinite(days) or not 0 <= days <= MAX_DAYS:
            raise BadRequest(f"days must be between 0 and {MAX_DAYS:g}")

        def build() -> list[dict]:
            known(serial)
            return usage.entries(serial, days)
        return JSONResponse({"entries": await run_in_threadpool(build)})

    @_authed
    async def usage_undo(request: Request):
        entry_id = request.path_params["entry_id"]
        e = await run_in_threadpool(audited, "usage undo", request.state.device,
                                    lambda: usage.undo(entry_id, sm), entry=entry_id)
        return JSONResponse({"entry": e})

    return [
        Route("/api/printers/{id}/map", map_start, methods=["POST"]),
        Route("/api/printers/{id}/map", map_get),
        Route("/api/printers/{id}/slots/{label}/load", slot_load, methods=["POST"]),
        Route("/api/printers/{id}/slots/{label}/unload", slot_unload, methods=["POST"]),
        Route("/api/printers/{id}/usage", usage_list),
        Route("/api/usage/{entry_id}/undo", usage_undo, methods=["POST"]),
    ]


def _safe(v) -> str:
    """A path value for a log line: as is when it is plain (serials, labels, entry ids), else a placeholder."""
    s = str(v)
    return s if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", s) else "<invalid>"


class _Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message
# ---- end slot mapping, loading and usage routes ----------------------------------------------------------


def create_app(sm: Spoolman | None = None, claude=None, printers=None, camera_hub=None,
               mapper: mapping.Mapper | None = None, enabled_modules: frozenset[str] | None = None) -> Starlette:
    cfg = config.load()
    on = enabled_modules if enabled_modules is not None else modules.enabled(cfg)
    sm = sm if sm is not None else Spoolman(cfg["spoolman_url"])
    if "printers" in on:
        printers = printers if printers is not None else Manager(spoolman=sm)  # started by __main__, not here
        # stopped by __main__'s lifespan; the Manager's `cert_changed` also refuses the camera
        camera_hub = camera_hub if camera_hub is not None else camera.Hub(printer_state=printers.state)
        mapper = mapper if mapper is not None else mapping.Mapper(printers)
    # else: the gated routes never reach these; nothing printer-related is built
    station: list = [None, None]  # [url, client]: the client (and its back-off) lives as long as the url does
    cap = ReadCap(config.paths().state / "reads.json", cfg["reads_per_day"])

    def rules() -> dict:  # sync: call it from inside the threadpool
        return config.load()["placement"]

    def info_body() -> dict:
        return {"name": config.load()["server_name"], "version": __version__, "api": API_VERSION,
                "apk_version": _apk_version(), "modules": sorted(on)}

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

    @_authed
    async def station_state(request: Request):
        url = (config.load().get("station") or {}).get("url")
        if not url:
            return _module_off("station")
        if station[0] != url:
            station[:] = [url, StationClient(url)]
        try:
            return JSONResponse(await run_in_threadpool(station[1].state))
        except StationUnreachable as e:
            log.warning("station: %s", e)
            return _err(503, "station_unreachable", "the intake station is not reachable")

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
            *_gated([
                Route("/api/intake/read", intake_read, methods=["POST"]),
                Route("/api/intake/retry/{read_id}", intake_retry, methods=["POST"]),
                Route("/api/intake/add", intake_add, methods=["POST"]),
            ], "ai_intake", on),
            Route("/api/tags/{uid}", tag_lookup),
            Route("/api/spools", spool_search),
            Route("/api/spools/{id:int}/link", spool_link, methods=["POST"]),
            Route("/api/spools/{id:int}", spool_update, methods=["PATCH"]),
            Route("/api/locations", locations),
            Route("/app.apk", apk),
            Route("/api/station", station_state),
            *_gated([*_printer_routes(printers), *_bridge_routes(printers, mapper, sm),
                     *camera.routes(camera_hub, _authed)], "printers", on),
            *_gated(profiles_api.routes(_authed, sm), "presets", on),
        ],
        exception_handlers={HTTPException: http_error},
    )
