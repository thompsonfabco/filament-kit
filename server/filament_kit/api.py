"""HTTPS JSON API for the phone app.

Every route but /api/info, POST /api/pair and /app.apk needs `Authorization: Bearer <token>`; the intake station's token
(`pair --station`) reaches only /api/station/*, the web unit's only WEB_ROUTES (403 elsewhere). Errors are `{"error": <code>, "message": <text>}`;
tracebacks are logged here and never sent.
"""
from __future__ import annotations

import functools
import json
import logging
import math
import re
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import (API_VERSION, __version__, config, intake, inventory, modules, pairing, profiles_api, setup_page,
               station_flow, station_requests, tags)
from .intake import CapReached, PhotoError, ReadCap, ReadError, RefundRefused
from .bridge import camera, family, hardware, loading, mapping, registry, usage
from .bridge.klipper import discovery
from .bridge.connection import ACTIONS, DEVELOPER_MODE_REASON, Manager, NoReply, PrinterOffline, UnknownPrinter
from .bridge.slottest import NoStatus, PrinterBusy
from .bridge.models import camera_kind, model_name
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
    if isinstance(e, RefundRefused):
        return _err(409, "refund_refused", str(e))
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
    if isinstance(e, loading.SlotInUse):
        return _err(409, "slot_in_use", str(e))
    if isinstance(e, loading.NoPreset):
        return _err(409, "no_preset", str(e))
    if isinstance(e, UnknownPrinter):
        return _err(404, "not_found", "no such printer")
    if isinstance(e, loading.NotFound):
        return _err(404, "not_found", str(e))
    if isinstance(e, family.ModuleOff):
        return _module_off(e.family)
    if isinstance(e, family.NotSupported):
        return _err(409, "not_supported", str(e) or "this printer does not support that")
    if isinstance(e, family.RecordedByMoonraker):
        return _err(409, "recorded_by_moonraker", "Moonraker recorded this usage in Spoolman; correct it in "
                    "Spoolman (the kit cannot undo it)")
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


STATION_PREFIX = "/api/station/"  # all a `pair --station` token may call (and /api/info, which needs none)
# All the web unit's token may call: exact method and route, because /api/printers/... mixes what its pages use with
# registry writes. A new route is refused until it is listed here. test_web_token_scope.py holds this to the app's
# routes and to what filament_kit/web calls.
WEB_ROUTES = (
    ("GET", "/api/printers"),
    ("GET", "/api/printers/{id}"),
    ("GET", "/api/printers/{id}/usage"),
    ("GET", "/api/printers/{id}/map"),
    ("POST", "/api/printers/{id}/map"),
    ("POST", "/api/printers/{id}/report"),
    ("POST", "/api/printers/{id}/command"),
    ("POST", "/api/printers/{id}/slots/{label}/load"),
    ("POST", "/api/printers/{id}/slots/{label}/unload"),
    ("GET", "/api/printers/{id}/camera.mjpeg"),
    ("GET", "/api/printers/{id}/camera/{name:path}"),
    ("POST", "/api/usage/{entry_id}/undo"),
    ("POST", "/api/intake/cap/take"),
    ("POST", "/api/intake/cap/refund"),
    ("GET", "/api/intake/orders"),
    ("POST", "/api/profiles/web/line_add"),
    ("POST", "/api/profiles/web/line_new"),
    ("POST", "/api/profiles/web/generate"),
)
_WEB_MATCH = {(m, re.compile(re.sub(r"\{\w+\}", "[^/]+", re.sub(r"\{\w+:path\}", ".+", r)))) for m, r in WEB_ROUTES}
WEB_ONLY_PREFIX = "/api/profiles/web/"  # the web unit's preset writes: no phone or PC calls them


def _web_may(method: str, path: str) -> bool:
    return any(m == method and rx.fullmatch(path) for m, rx in _WEB_MATCH)


def _authed(fn):
    @functools.wraps(fn)
    async def wrapper(request: Request):
        header = request.headers.get("authorization", "")
        scheme, _, tok = header.partition(" ")
        got = None
        if scheme.lower() == "bearer" and tok.strip():
            got = await run_in_threadpool(pairing.authorize, tok.strip())
        if got is None:
            return _err(401, "unauthorized", "pair this phone with the server first (missing or revoked token)")
        device, scope = got
        if scope == "station" and not request.url.path.startswith(STATION_PREFIX):
            return _err(403, "forbidden", "the intake station's token is for the station's routes only")
        # the path the router matched, not the URL's raw text
        path = request.scope["path"]
        if scope == "web" and not _web_may(request.method, path):
            return _err(403, "forbidden", "the web unit's token is for the web unit's routes only")
        if scope != "web" and path.startswith(WEB_ONLY_PREFIX):
            return _err(403, "forbidden", "this route is for the web unit only")
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
    fam = getattr(p, "family", "bambu")
    view = {"id": p.serial, "name": registry.display_name(p), "model": p.model, "serial": p.serial, "ip": p.ip,
            "configured": p.configured, "state": state, "camera": {"kind": camera_kind(p.model)},
            "model_name": model_name(p.model),
            "summary": summary, "family": fam}
    if fam == "klipper":
        kf = getattr(printers, "klipper", None)
        view["host"] = p.host
        view["verified"] = bool(kf.verified(p.serial)) if kf is not None else None
        view["camera"] = {"kind": kf.camera_kind(p.serial) if kf is not None else None}
        view["model_name"] = _klipper_model_name(p, kf)
    return view


def _klipper_model_name(p: registry.Printer, kf) -> str:
    """A Klipper printer's name from klipper_hardware.xml ("Sovol SV08 MAX"); the model text when nothing matched."""
    try:
        m = kf.model(p.serial)[0] if kf is not None else None
    except Exception:  # noqa: BLE001 - an unreadable detection must not fail the printer list
        m = None
    return m.name if m is not None and m.key != "generic" else (p.model or "").strip()


def _hardware_view() -> dict:
    """The printer hardware data files' state (`bambu_hardware.xml`, `klipper_hardware.xml`): errors = a refused
    override (the last good data stays in use), warnings = unknown elements/attributes that were ignored. Each entry
    names its file."""
    from .bridge.klipper import hardware as klipper_hardware
    out = {"errors": [], "warnings": []}
    for module in (hardware, klipper_hardware):
        try:
            hw = module.load()
        except Exception as e:  # noqa: BLE001 - the status must still answer
            log.exception("hardware data cannot be loaded")
            out["errors"].append(f"{type(e).__name__}: {e}")
            continue
        out["errors"] += hw.errors
        out["warnings"] += hw.warnings
    return out


NOT_SEEN = "That printer hasn't been seen on the network yet"
HOST = re.compile(r"[A-Za-z0-9.:\[\]-]{1,253}")   # a host name, IPv4 or bracketed IPv6


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

    async def klipper_add(body: dict):
        host, name, port = body.get("host"), _opt(body, "name", str), _opt(body, "port", int, 7125)
        if not isinstance(host, str) or not HOST.fullmatch(host.strip()):
            raise BadRequest("host is required: the Moonraker host name or address (letters, digits, . - :)")
        if isinstance(port, bool) or not 1 <= port <= 65535:
            raise BadRequest("port must be between 1 and 65535")

        def run() -> dict:
            try:
                p = discovery.add((name or "").strip() or host.strip(), host.strip(), port)
            except registry.DuplicatePrinter as e:
                raise BadRequest(str(e)) from None
            printers.sync()
            printers.wait_settled(p.serial, FIRST_STATE_WAIT)
            return _printer_view(p, printers)
        return JSONResponse({"printer": await run_in_threadpool(run)})

    @_authed
    async def printer_add(request: Request):
        body = await _json(request)
        fam = body.get("family", "bambu")
        if fam == "klipper":
            return await klipper_add(body)
        if fam != "bambu":
            raise BadRequest("family must be bambu or klipper")
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
            return {"printer": _printer_view(p, printers), "status": printers.status(serial),
                    "hardware": _hardware_view()}
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
        except family.ModuleOff as e:
            return _module_off(e.family)
        return JSONResponse({"ok": True, "reply": reply})

    @_authed
    async def printer_scan(request: Request):
        """`POST /api/printers/scan {subnet?}`: the owner's Scan for Klipper printers (Moonraker on this machine's
        /24 unless a subnet is given). Found printers are listed unconfigured; add one with POST /api/printers."""
        body = await _json(request)
        subnet = _opt(body, "subnet", str)
        kf = getattr(printers, "klipper", None)
        if kf is None:
            return _module_off("klipper")
        try:
            found = await run_in_threadpool(kf.scan, subnet)
        except ValueError as e:
            raise BadRequest(str(e)) from None
        return JSONResponse({"found": found})

    return [
        Route("/api/printers", printer_list),
        Route("/api/printers", printer_add, methods=["POST"]),
        Route("/api/printers/scan", printer_scan, methods=["POST"]),
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

    def klipper_of(serial: str):
        """The Klipper family when `serial` is a Klipper printer, else None (a Bambu printer)."""
        p = registry.load().get(serial)
        if p is None or p.family != "klipper":
            return None
        kf = getattr(printers, "klipper", None)
        if kf is None:
            raise family.ModuleOff("klipper")
        return kf

    def bambu_only(serial: str) -> None:
        p = registry.load().get(serial)
        if p is not None and p.family == "klipper":
            raise family.NotSupported("slot mapping is for Bambu printers; a Klipper printer's slots are its "
                                      "tools or lanes")

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

    def manual_call(what: str, fn, write: bool = True):
        """A manual-map step for the app: the same answers as on the setup page. A Klipper printer's session is the
        Klipper family's (bridge/klipper/manual.py), a Bambu printer's the mapper's (bridge/manual.py)."""
        from .bridge import manual

        def session_of(serial: str):
            kf = klipper_of(serial)
            return kf.manual if kf is not None else mapper.manual

        @_authed
        async def route(request: Request):
            serial = request.path_params["id"]
            body = await _json(request) if request.method == "POST" else {}
            try:
                out = await run_in_threadpool(lambda: fn(session_of(serial), serial, body))
            except manual.ManualError as e:
                return _err(e.status, e.code, str(e))
            if write:
                await run_in_threadpool(audit, f"manual map {what}", request.state.device, "ok", serial=serial)
            return JSONResponse(out)
        return route

    manual_routes = [
        ("start", "POST", lambda mm, s, b: mm.start(s)),
        ("", "GET", lambda mm, s, b: mm.view(s)),
        ("confirm", "POST", lambda mm, s, b: mm.confirm(s, b.get("session"), b.get("position"), b.get("reported"),
                                                         b.get("nozzle"), b.get("by_hand") is True)),
        ("skip", "POST", lambda mm, s, b: mm.skip(s, b.get("session"), b.get("position"))),
        ("stop", "POST", lambda mm, s, b: mm.stop(s, b.get("session"))),
        ("offer", "POST", lambda mm, s, b: mm.answer_offer(s, b.get("share") is True)),
    ]

    @_authed
    async def map_start(request: Request):
        serial = request.path_params["id"]
        await run_in_threadpool(bambu_only, serial)
        job = await run_in_threadpool(audited, "slot mapping", request.state.device,
                                      lambda: mapper.start(serial), serial=serial)
        return JSONResponse({"job_id": job}, status_code=202)

    @_authed
    async def map_stop(request: Request):
        """Stop a running slot mapping (the slots are put back first); `filament-kit printer map` on Ctrl-C."""
        serial = request.path_params["id"]
        await run_in_threadpool(bambu_only, serial)
        await run_in_threadpool(audited, "slot mapping stopped", request.state.device, lambda: mapper.abort(serial),
                                serial=serial)
        return JSONResponse({"ok": True})

    @_authed
    async def map_get(request: Request):
        serial = request.path_params["id"]

        def build() -> dict:
            known(serial)
            bambu_only(serial)
            return mapper.view(serial)
        return JSONResponse(await run_in_threadpool(build))

    @_authed
    async def map_report(request: Request):
        """The printer report (bridge/printer_report.py): an XML file with no owner data, for its owner to share."""
        serial = request.path_params["id"]

        def build() -> dict:
            known(serial)
            bambu_only(serial)
            r = mapper.report(serial)        # built from saved records when the printer can't be reached
            return {"name": r["name"], "xml": r["xml"], "live": r.get("live", True),
                    "saved_until": r.get("saved_until")}
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
            kf = klipper_of(serial)
            if kf is not None:
                r = kf.load(sm, serial, label, spool_id, dry, sealed_location=sealed())
                return {**r, "confirmed": r.get("confirmed") if dry else bool(r.get("confirmed"))}
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
            kf = klipper_of(serial)
            if kf is not None:
                r = kf.unload(sm, serial, label, dry, sealed_location=sealed())
            else:
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
            kf = klipper_of(serial)
            return kf.usage(serial, days) if kf is not None else usage.entries(serial, days)
        return JSONResponse({"entries": await run_in_threadpool(build)})

    @_authed
    async def usage_undo(request: Request):
        entry_id = request.path_params["entry_id"]
        if family.is_klipper_entry(entry_id):
            raise family.RecordedByMoonraker(entry_id)
        e = await run_in_threadpool(audited, "usage undo", request.state.device,
                                    lambda: usage.undo(entry_id, sm), entry=entry_id)
        return JSONResponse({"entry": e})

    return [
        Route("/api/printers/{id}/map", map_start, methods=["POST"]),
        Route("/api/printers/{id}/map", map_get),
        Route("/api/printers/{id}/map/stop", map_stop, methods=["POST"]),
        *[Route("/api/printers/{id}/manual-map" + (f"/{name}" if name else ""),
                manual_call(name or "view", fn, write=method == "POST"), methods=[method])
          for name, method, fn in manual_routes],
        Route("/api/printers/{id}/report", map_report, methods=["POST"]),
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


from .web.slots import INTAKE_DEVICE  # noqa: E402  (the kit's own phone web app's pairing; no mcp import)
INTAKE_TOKEN = "intake_kit_token"       # in the state folder: the kit server's own phone web app's pairing


def _intake_web_app(cfg: dict, sm: Spoolman, claude, hosts=None) -> list:
    """The phone web app at /intake, served by the kit server itself on the home network (the user's decision,
    2026-11-09: part of the main software, no module needed). The same app as the web unit's, on the same rules:
    home network only, the setup page's Host rule, the page's own Origin on every POST. It calls this server's API
    over the loopback with its own pairing (device INTAKE_DEVICE, the web role), as the web unit does with its own.
    No push alerts here: the web unit sends those when it is on."""
    from . import web_access
    from .web import mcp_tools, slots
    from .web.intake_app import IntakeApp
    kit = slots.KitApi(token_file=config.paths().state / INTAKE_TOKEN, device=INTAKE_DEVICE, role=web_access.WEB_ROLE)
    tools = mcp_tools.Tools(sm, kit_api=kit, kit_writes=True)
    lan_cidrs = (cfg.get("web") or {}).get("lan") or []
    names = hosts or setup_page.allowed_hosts
    return IntakeApp(tools, public_url=None, lan_cidrs=lan_cidrs, claude=claude, kit_api=kit, push=False,
                     host_ok=lambda request: setup_page.host_ok(request, hosts),
                     host_refusal=lambda: setup_page.bad_host_text(names() | setup_page.extra_hosts())).routes()


def create_app(sm: Spoolman | None = None, claude=None, printers=None, camera_hub=None,
               mapper: mapping.Mapper | None = None, enabled_modules: frozenset[str] | None = None,
               setup: dict | None = None) -> Starlette:
    """The phone app's API, plus the setup page (/setup, setup_page.py; `setup` = its test hooks)."""
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

    def station_client() -> StationClient | None:  # sync: one client (and back-off) per station url
        url = (config.load().get("station") or {}).get("url")
        if not url:
            return None
        if station[0] != url:
            station[:] = [url, StationClient(url)]
        return station[1]

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
    async def unpair(request: Request):
        """A client leaving: only the calling token is revoked. Clients call it best effort when they forget the server."""
        device = request.state.device
        revoked = await run_in_threadpool(pairing.revoke, device)
        log.info("unpair device_id=%s result=%s", device, "ok" if revoked else "already-gone")
        return JSONResponse({"revoked": True})

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
        device = request.state.device

        def run() -> dict:
            ticket = cap.take(device)
            try:
                ctx = intake.read_context(config.load(), sm, station_client(), app_tag=uid is not None)
                return intake.read_labels(sm, images, hint[:MAX_HINT], uid, claude, **ctx)
            except SpoolmanError:  # Spoolman down: the catalog fetch failed before Claude was called
                intake.refund_quietly(cap, ticket, device)
                raise
        return JSONResponse(await run_in_threadpool(run))

    @_authed
    async def intake_retry(request: Request):
        read_id = request.path_params["read_id"]
        device = request.state.device

        def run() -> dict:
            if not intake.is_kept(read_id):  # an unknown or expired read fails with not_found, using no read
                return intake.retry(read_id, sm, claude)
            ticket = cap.take(device)
            try:
                return intake.retry(read_id, sm, claude, orders=intake.read_context(
                    config.load(), sm, None, app_tag=True)["orders"])
            except SpoolmanError:  # Spoolman down: the catalog fetch failed before Claude was called
                intake.refund_quietly(cap, ticket, device)
                raise
        return JSONResponse(await run_in_threadpool(run))

    # ---------- the web unit's label reads: the kit's cap and order history, never its files ----------
    @_authed
    async def cap_take(request: Request):
        """One read off the shared cap; the ticket gives it back (cap_refund) within intake.TICKET_TTL."""
        ticket = await run_in_threadpool(cap.take, request.state.device)
        return JSONResponse({"ok": True, "ticket": ticket})

    @_authed
    async def cap_refund(request: Request):
        """Give back the read of one live ticket this device's take returned (409 refund_refused otherwise)."""
        ticket = (await _json(request)).get("ticket")
        await run_in_threadpool(cap.refund, ticket, request.state.device)
        return JSONResponse({"ok": True})

    @_authed
    async def intake_orders(request: Request):
        """The order history for a label read's prompt (None: the orders module is off or no file is set). Only for
        the web unit's own device (role "web", set as root by `modules apply`): the kit's own reads use it in
        process, and no phone or PC needs the whole history."""
        if await run_in_threadpool(pairing.role_of, request.state.device) != pairing.WEB_ROLE:
            return _err(403, "forbidden", "the order history is for the web unit only")

        def build():
            cfg = config.load()
            path = (cfg.get("orders") or {}).get("file")
            return intake.load_orders(cfg) if path and Path(path).is_file() else None  # as read_context's
        return JSONResponse({"orders": await run_in_threadpool(build)})

    @_authed
    async def intake_add(request: Request):
        body = await _json(request)
        dry = _opt(body, "dry_run", bool, True)
        uid = _opt(body, "tag", str) or None
        r = await run_in_threadpool(lambda: inventory.add_and_link(sm, body.get("items"), rules(), dry, uid))
        return JSONResponse({"spool_ids": r.spool_ids, "lines": r.lines, "dry": r.dry})

    # ---------- the intake station's button flow (station_flow.py) ----------
    def _flow(fn):
        async def route(request: Request):
            try:
                return JSONResponse(await fn(request))
            except station_flow.FlowError as e:
                return _err(e.status, e.code, str(e), display=e.display, **e.extra)
            except CapReached as e:
                return _err(429, "daily_cap", str(e), display=station_flow.lines("Read limit reached", "use phone"))
            except SpoolmanError as e:
                r = _to_response(e)
                return JSONResponse({**json.loads(r.body), "display": station_flow.lines("Spoolman down", "try again")},
                                    status_code=r.status_code)
        return _authed(route)

    async def station_tag(request: Request):
        return await run_in_threadpool(station_flow.tag_info, sm, request.path_params["uid"])

    async def station_recognize(request: Request):
        async with request.form() as form:
            f = form.get("image")
            if not isinstance(f, UploadFile):
                raise station_flow.FlowError(400, "bad_request", "image must be a file upload",
                                             station_flow.lines("No photo", "try again"))
            data = await f.read(intake.MAX_PHOTO_BYTES + 1)
        try:
            (image,) = intake.check_photos([(f.filename or "station.jpg", data)])
        except PhotoError as e:
            raise station_flow.FlowError(400, "bad_photo", str(e), station_flow.lines("Bad photo", "try again")) from e
        return await run_in_threadpool(
            lambda: station_flow.recognize(sm, config.load(), image, claude, cap,
                                           getattr(request.state, "device", None)))

    @_authed
    async def station_hello(request: Request):
        """`filament-kit station pair` calls this once: the first authenticated call claims the station's token."""
        return JSONResponse({"ok": True})

    @_handle
    async def station_pair_request(request: Request):
        """An unpaired station asks to be paired (station_requests.py): no token yet, so no _authed."""
        body = await _json(request)
        try:
            out = await run_in_threadpool(station_requests.ask, body.get("request_id"), body.get("commit"),
                                          body.get("name"), request.client.host if request.client else "")
        except station_requests.RequestError as e:
            return _err(e.status, e.code, str(e))
        log.info("station pairing requested from %s", _safe(request.client.host if request.client else "?"))
        return JSONResponse(out, status_code=202)

    @_handle
    async def station_pair_reveal(request: Request):
        body = await _json(request)
        try:
            out = await run_in_threadpool(station_requests.reveal, request.path_params["request_id"], body.get("secret"))
        except station_requests.RequestError as e:
            return _err(e.status, e.code, str(e))
        return JSONResponse(out)

    @_handle
    async def station_pair_poll(request: Request):
        status, body = await run_in_threadpool(station_requests.poll, request.path_params["request_id"])
        return JSONResponse(body, status_code=status)

    async def station_save(request: Request):
        body = await _json(request)
        return await run_in_threadpool(lambda: station_flow.save(sm, rules(), body))

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
    async def filament_list(request: Request):
        q = request.query_params.get("q", "")
        return JSONResponse({"filaments": await run_in_threadpool(inventory.filaments, sm, q)})

    @_authed
    async def vendor_list(request: Request):
        return JSONResponse({"vendors": await run_in_threadpool(inventory.vendors, sm)})

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
        client = await run_in_threadpool(station_client)
        if client is None:
            return _module_off("station")
        try:
            return JSONResponse(await run_in_threadpool(client.state))
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
            Route("/api/pair", unpair, methods=["DELETE"]),
            *_gated([
                Route("/api/intake/read", intake_read, methods=["POST"]),
                Route("/api/intake/retry/{read_id}", intake_retry, methods=["POST"]),
                Route("/api/intake/cap/take", cap_take, methods=["POST"]),
                Route("/api/intake/cap/refund", cap_refund, methods=["POST"]),
                Route("/api/intake/orders", intake_orders),
            ], "ai_intake", on),
            Route("/api/intake/add", intake_add, methods=["POST"]),  # adding by hand needs no AI (spec R 2.4)
            Route("/api/tags/{uid}", tag_lookup),
            Route("/api/spools", spool_search),
            Route("/api/filaments", filament_list),
            Route("/api/vendors", vendor_list),
            Route("/api/spools/{id:int}/link", spool_link, methods=["POST"]),
            Route("/api/spools/{id:int}", spool_update, methods=["PATCH"]),
            Route("/api/locations", locations),
            Route("/app.apk", apk),
            Route("/api/station", station_state),
            Route("/api/station/hello", station_hello),
            Route("/api/station/pair-request", station_pair_request, methods=["POST"]),
            Route("/api/station/pair-request/{request_id}", station_pair_poll),
            Route("/api/station/pair-request/{request_id}/reveal", station_pair_reveal, methods=["POST"]),
            Route("/api/station/tag/{uid}", _flow(station_tag)),
            Route("/api/station/recognize", _flow(station_recognize), methods=["POST"]),
            Route("/api/station/save", _flow(station_save), methods=["POST"]),
            *_gated([*_printer_routes(printers), *_bridge_routes(printers, mapper, sm),
                     *camera.routes(camera_hub, _authed)],
                    "klipper" if "klipper" in on and "printers" not in on else "printers", on),
            *_gated(profiles_api.routes(_authed, sm), "presets", on),
            *_intake_web_app(cfg, sm, claude, (setup or {}).get("hosts")),
            *setup_page.routes(printers if on & {"printers", "klipper"} else None,
                               families={f for m, f in (("printers", "bambu"), ("klipper", "klipper")) if m in on},
                               mapper=mapper if "printers" in on else None,
                               **(setup or {})),
        ],
        exception_handlers={HTTPException: http_error},
    )
