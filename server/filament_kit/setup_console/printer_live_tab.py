"""The live printer view of the Printers tab (R83 section 2 and 3, the 20:58 ruling point 3): what an open printer shows in its
Detail region. The page's own routes call the same printer code as the kit routes, in the Hub's process; they never call the web
app's routes (the page's lock must apply, and the web app may be switched off). Serials are the path's `serial`, as the other
Printers routes have them.

    GET  printers/{serial}/live                 no code: {summary, status, state, family, name, camera: {kind}, controls: {light}}
                                                (`summary` and `status` as GET /api/printers/{id} gives them; a slot waiting for its
                                                filament carries `pending: {spool_id, text}`)
    POST printers/{serial}/command {code, action[, confirm]}
        action: pause | resume | stop | light_on | light_off; `stop` needs `confirm: true`. Answers {ok: true, reply} or a refusal:
        409 `not_supported` (the printer has no such control), 409 `printer_offline`, 409 `refused` (the printer said no, its words
        in `error`), 504 `no_reply`
    POST printers/{serial}/slots/{label}/load {code, spool_id[, dry_run]}   POST .../unload {code[, dry_run]}   POST .../clear {code[, dry_run]}
        as the kit routes answer (dry_run defaults to true); a load of a slot not loaded yet answers `pending: true`. A refusal is 409
        with `code` (slot_in_use, printer_busy, no_preset, needs_developer_mode ...) and its sentence in `error`
    GET  printers/{serial}/usage[?days=7]       no code: {entries}, each with `spool`
    POST usage/{entry_id}/undo {code}           {entry}
    POST printers/{serial}/camera/ticket {code} {ticket, expires_in: 60}: for a computer that is not trusted (camera_ticket.py keeps the
                                                tickets). The FIRST camera request with ?ticket=<ticket> (the stream or the HLS playlist) spends it
                                                and sets the camera session's cookie (fk_setup_camera; path /setup/api/printers/<id>/camera, HttpOnly,
                                                Secure, SameSite=Strict, no Max-Age): that printer, 10 minutes from its last camera request, in
                                                memory (camera_ticket.py); at most 8 sessions, the ninth ticket is 429 `too_many_views`
    GET  printers/{serial}/camera.mjpeg[?ticket=]   the stream as the kit route gives it: a ticket, the camera session's cookie or the cookie of
                                                a trusted computer (an image request cannot carry the code)
    GET  printers/{serial}/camera/{name}        the HLS playlist and segments: the same three; a segment's address has no ticket, its cookie goes along
    POST printers/{serial}/camera/close         {closed: true}; needs only the camera session's cookie, and answers so also when there is none

`routes(page, sm=None, camera_hub=None)`: `sm` is the Spoolman client (the page's own, by default the configured one), `camera_hub` the
Hub's camera hub (bridge/camera.Hub; the server's one, as the kit routes have it); without one the camera answers 409.
"""
from __future__ import annotations

import math
import re

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from .. import camera_ticket, config, inventory, storage
from ..bridge import camera, family, loading, mapping, pending, registry, usage
from ..bridge.connection import ACTIONS, DEVELOPER_MODE_REASON, NoReply, PrinterOffline, UnknownPrinter
from ..bridge.slottest import NoStatus, PrinterBusy
from ..spoolman import Spoolman, SpoolmanError

LABEL = re.compile(r"[A-Za-z0-9-]{1,16}")
SESSION_COOKIE = "fk_setup_camera"      # R83 ruled 22:20; a session cookie (no Max-Age): the Hub's memory decides the end
MAX_DAYS = 366.0
DAYS = 7.0
OFFLINE = "the printer is offline; check that it is on and on the network"


def routes(page, sm: Spoolman | None = None, camera_hub=None) -> list[tuple]:
    from ..setup_page import NEED_CODE, Refused

    g, w = page.guard, (lambda fn: page.guard(fn, write=True))

    def spoolman() -> Spoolman:
        return sm if sm is not None else Spoolman(config.load()["spoolman_url"])

    def hub():
        return camera_hub if camera_hub is not None else getattr(page, "camera_hub", None)

    def refused(e: Exception) -> Refused | None:
        """The bridge's errors as the page's refusals, with the kit routes' codes beside the sentence (None: not one of them)."""
        def r(status, code, text=None):
            return Refused(status, text if text is not None else str(e), code=code)
        if isinstance(e, usage.UsageError):
            return r(e.status, e.code)
        if isinstance(e, mapping.AlreadyRunning):
            return r(409, "already_running", e.message)
        if isinstance(e, mapping.CertChanged):
            return r(409, "cert_changed", camera.CERT_CHANGED)
        if isinstance(e, PrinterBusy):
            return r(409, "printer_busy", f"the printer is busy ({e}); try again once it is idle")
        if isinstance(e, NoStatus):
            return r(409, "printer_offline")
        if isinstance(e, PrinterOffline):
            return r(409, "printer_offline", OFFLINE)
        if isinstance(e, loading.SlotInUse):
            return r(409, "slot_in_use")
        if isinstance(e, loading.NoPreset):
            return r(409, "no_preset")
        if isinstance(e, UnknownPrinter):
            return r(404, "not_found", "no such printer")
        if isinstance(e, loading.NotFound):
            return r(404, "not_found")
        if isinstance(e, family.ModuleOff):
            return r(409, "module_off", f"the {e.family} feature is turned off on the Hub")
        if isinstance(e, family.NotSupported):
            return r(409, "not_supported", str(e) or "this printer does not support that")
        if isinstance(e, family.RecordedByMoonraker):
            return r(409, "recorded_by_moonraker", "Moonraker recorded this usage in Spoolman; correct it in Spoolman "
                     "(Spoolwarden cannot undo it)")
        if isinstance(e, NoReply):
            return r(504, "no_reply", "the printer did not answer in time")
        if isinstance(e, SpoolmanError):
            return r(502, "spoolman", "Spoolman could not be reached" if e.status is None else str(e))
        return None

    async def call(fn, *args):
        """`fn(*args)` in a thread; a bridge error becomes the page's refusal, anything else is the guard's 500."""
        try:
            return await anyio.to_thread.run_sync(fn, *args)
        except Exception as e:  # noqa: BLE001 - mapped, or raised again as it was
            mapped = refused(e)
            if mapped is None:
                raise
            raise mapped from None

    def known(serial: str) -> registry.Printer:
        if serial not in registry.load():
            camera_ticket.drop_printer(serial)  # a printer taken away ends its tickets and camera sessions
        p = page._entry(serial)         # 404 for none; 409 when its family's module is off
        if not p.configured:
            raise Refused(409, "that printer is not set up on this Hub", code="not_configured")
        return p

    def klipper_of(serial: str):
        p = registry.load().get(serial)
        if p is None or p.family != "klipper":
            return None
        kf = getattr(page.printers, "klipper", None)
        if kf is None:
            raise family.ModuleOff("klipper")
        return kf

    def sealed() -> str:
        return storage.current().sealed_location().name

    # ---- the live view ----
    def live_view(serial: str) -> dict:
        p = registry.load().get(serial)
        if p is None:
            raise UnknownPrinter(serial)
        printers = page._manager(p.family)
        state = printers.state(serial)
        if state == "not_configured" and p.configured:
            state = "offline"
        try:
            summary = printers.summary(serial)
        except Exception:  # noqa: BLE001 - one odd report must not fail the view
            summary = None
        status = pending.annotate(serial, printers.status(serial))
        kf = klipper_of(serial)
        light = False
        if kf is not None:
            try:
                light = bool(kf.model(serial)[0].light_on)
            except Exception:  # noqa: BLE001 - a printer that cannot say has no light control to show
                light = False
        elif status is not None:
            light = status.get("light") is not None
        cam = kf.camera_kind(serial) if kf is not None else camera_kind_of(p)
        return {"summary": summary, "status": status, "state": state, "family": p.family, "name": registry.display_name(p),
                "camera": {"kind": cam}, "controls": {"light": light}}

    def camera_kind_of(p):
        from ..bridge.models import camera_kind
        return camera_kind(p.model)

    async def live(request, body):
        serial = page._serial(request)
        return await call(live_view, serial)

    # ---- controls ----
    async def command(request, body):
        serial = page._serial(request)
        action = body.get("action")
        if action not in ACTIONS:
            raise Refused(400, "action must be one of: " + ", ".join(ACTIONS), field="action")
        if action == "stop" and body.get("confirm") is not True:
            raise Refused(400, "stopping a print needs confirm: true", field="confirm", code="confirm_needed")

        def run() -> dict:
            known(serial)
            return page.printers.command(serial, action)
        reply = await call(run)
        if reply.get("ok") is False:
            why = (reply.get("reply") or {}).get("reason")
            if why == "not_supported":
                raise Refused(409, str((reply.get("reply") or {}).get("message") or "this printer has no such control"), code="not_supported")
            raise Refused(409, str(why or "the printer said no"), code="refused", reply=reply.get("reply"))
        page.audit(request, f"printer {serial} command {action}")
        return {"ok": True, "reply": reply}

    # ---- slots ----
    def label_of(request: Request) -> str:
        label = request.path_params["label"]
        if not LABEL.fullmatch(label):
            raise Refused(404, f"no slot {label!r}", code="not_found")
        return label

    def not_mapping(serial: str) -> None:
        """Slot mapping changes the slots: no load, unload or clear meanwhile (dry runs too: the slots are in flux)."""
        if page.mapper is not None and getattr(page.mapper, "in_progress", lambda s: False)(serial):
            raise mapping.AlreadyRunning(serial)

    def dry_of(body: dict) -> bool:
        dry = body.get("dry_run", True)
        if not isinstance(dry, bool):
            raise Refused(400, "dry_run must be true or false", field="dry_run")
        return dry

    async def slot_load(request, body):
        serial, label = page._serial(request), label_of(request)
        spool_id = body.get("spool_id")
        if not isinstance(spool_id, int) or isinstance(spool_id, bool):
            raise Refused(400, "spool_id must be a whole number", field="spool_id")
        dry = dry_of(body)

        def run() -> dict:
            known(serial)
            kf = klipper_of(serial)
            if kf is not None:
                r = kf.load(spoolman(), serial, label, spool_id, dry, sealed_location=sealed())
                return {**r, "confirmed": r.get("confirmed") if dry else bool(r.get("confirmed"))}
            if page.printers.state(serial) == "cert_changed":
                raise mapping.CertChanged(serial)
            not_mapping(serial)
            try:
                r = pending.load_or_wait(page.printers, spoolman(), serial, label, spool_id, dry, sealed_location=sealed())
            except loading.SlotWriteFailed as e:
                if page.printers.state(serial) == "needs_developer_mode" or DEVELOPER_MODE_REASON.search(str(e)):
                    raise Refused(409, f"{e}; turn on Developer Mode (LAN-only mode) on the printer and try again",
                                  code="needs_developer_mode") from e
                raise Refused(409, str(e), code="write_refused") from e
            return {**r, "confirmed": bool(r.get("confirmed"))}
        r = await call(run)
        if not dry:
            page.audit(request, f"printer {serial} slot {label} load, spool {spool_id}")
        return r

    async def slot_unload(request, body):
        serial, label = page._serial(request), label_of(request)
        dry = dry_of(body)

        def run() -> dict:
            known(serial)
            kf = klipper_of(serial)
            if kf is not None:
                r = kf.unload(spoolman(), serial, label, dry, sealed_location=sealed())
                r = {**r, "waiting_ended": False}
            else:
                not_mapping(serial)
                r = pending.unload(page.printers, spoolman(), serial, label, dry, sealed_location=sealed())
            first = next((m for m in r["moved_back"] if m["id"] == r["spool"].get("id")), None)
            return {**r, "location": first["location"] if first else r["spool"].get("location")}
        r = await call(run)
        if not dry:
            page.audit(request, f"printer {serial} slot {label} unload")
        return r

    async def slot_clear(request, body):
        serial, label = page._serial(request), label_of(request)
        dry = dry_of(body)

        def run() -> dict:
            known(serial)
            kf = klipper_of(serial)
            if kf is not None:
                return kf.clear(spoolman(), serial, label, dry, sealed_location=sealed())
            not_mapping(serial)
            return pending.clear_slot(page.printers, spoolman(), serial, label, dry, sealed_location=sealed())
        r = await call(run)
        if not dry:
            page.audit(request, f"printer {serial} slot {label} cleared")
        return r

    # ---- Filament used ----
    async def usage_list(request, body):
        serial = page._serial(request)
        raw = request.query_params.get("days", str(DAYS))
        try:
            days = float(raw)
        except ValueError:
            raise Refused(400, "days must be a number", field="days") from None
        if not math.isfinite(days) or not 0 <= days <= MAX_DAYS:
            raise Refused(400, f"days must be between 0 and {MAX_DAYS:g}", field="days")

        def run() -> list[dict]:
            known(serial)
            kf = klipper_of(serial)
            got = kf.usage(serial, days) if kf is not None else usage.entries(serial, days)
            return inventory.with_spools(got, spoolman())
        return {"entries": await call(run)}

    async def usage_undo(request, body):
        entry_id = request.path_params["entry_id"]
        if family.is_klipper_entry(entry_id):
            raise Refused(409, "Moonraker recorded this usage in Spoolman; correct it in Spoolman (Spoolwarden cannot undo it)",
                          code="recorded_by_moonraker")
        e = await call(usage.undo, entry_id, spoolman())
        page.audit(request, f"usage {entry_id} undone")
        return {"entry": e}

    # ---- the camera (camera_ticket.py keeps the tickets and the sessions) ----
    async def ticket(request, body):
        serial = page._serial(request)
        await call(known, serial)
        if hub() is None:
            raise Refused(409, "the camera is not running on this Hub", code="module_off")
        page.audit(request, f"printer {serial} camera ticket")
        try:
            return camera_ticket.issue(serial)
        except camera_ticket.TooManyViews as e:
            raise Refused(429, str(e), code="too_many_views") from None

    async def allowed(request, serial: str) -> str | None:
        """The camera is for an unlocked page, and a request carries no code: a ticket made for this printer (spent here: it opens
        the camera session, whose id is returned to go in a cookie), the camera session's own cookie, or the cookie of a trusted
        computer (the helper checks it, as it does a code)."""
        given = request.query_params.get("ticket")
        if given is not None:
            try:
                sid = camera_ticket.use_ticket(serial, given)
            except camera_ticket.TooManyViews as e:
                raise Refused(429, str(e), code="too_many_views") from None
            if sid is not None:
                return sid
        if camera_ticket.verify_session(serial, request.cookies.get(SESSION_COOKIE)):
            return None
        body: dict = {}
        if page._trusted_token(request, body) is None:
            raise Refused(403, NEED_CODE, field="code")
        await page._code_ok(request, body)
        return None

    def with_session(res, serial: str, sid: str | None):
        if sid is not None:
            c = camera_ticket.session_cookie(serial, sid)       # the path is the kit's; the name is the ruled one and it has no Max-Age
            res.set_cookie(SESSION_COOKIE, sid, path=c["path"], secure=True, httponly=True, samesite="strict")
        return res

    async def close(request, body):
        serial = page._serial(request)
        r = camera_ticket.close_session(serial, request.cookies.get(SESSION_COOKIE))      # always {closed: true}
        res = JSONResponse(r, headers={"Cache-Control": "no-store"})
        res.delete_cookie(SESSION_COOKIE, path=camera_ticket.session_cookie(serial, "")["path"], secure=True, httponly=True, samesite="strict")
        return res

    def stream_of(path: str, serial: str, request: Request):
        """The camera module's own handler for `path`, called with the path's parameters as the kit route has them."""
        found = {r.path: r.endpoint for r in camera.routes(hub(), lambda f: f)}[path]
        request.scope["path_params"] = {**request.scope.get("path_params", {}), "id": serial}
        return found(request)

    async def mjpeg(request, body):
        serial = page._serial(request)
        await call(known, serial)
        if hub() is None:
            raise Refused(409, "the camera is not running on this Hub", code="module_off")
        sid = await allowed(request, serial)
        return with_session(await stream_of("/api/printers/{id}/camera.mjpeg", serial, request), serial, sid)

    async def hls(request, body):
        serial = page._serial(request)
        await call(known, serial)
        if hub() is None:
            raise Refused(409, "the camera is not running on this Hub", code="module_off")
        sid = await allowed(request, serial)
        return with_session(await stream_of("/api/printers/{id}/camera/{name:path}", serial, request), serial, sid)

    one = "/printers/{serial}"
    return [(one + "/live", g(live), "GET"), (one + "/command", w(command), "POST"),
            (one + "/slots/{label}/load", w(slot_load), "POST"), (one + "/slots/{label}/unload", w(slot_unload), "POST"),
            (one + "/slots/{label}/clear", w(slot_clear), "POST"),
            (one + "/usage", g(usage_list), "GET"), ("/usage/{entry_id}/undo", w(usage_undo), "POST"),
            (one + "/camera/ticket", w(ticket), "POST"), (one + "/camera/close", g(close), "POST"),
            (one + "/camera.mjpeg", g(mjpeg), "GET"), (one + "/camera/{name:path}", g(hls), "GET")]

