"""The Printers tab of the phone web app: routes under `<public path>/intake/api/printers`, guarded like the
intake app (no sign-in): LAN check, Host check, exact-Origin POSTs and CSP.

The web process never talks to a printer. Everything goes to the kit server's own API on 127.0.0.1 through
`slots.KitApi` (this unit's self-paired token):

    GET  printers                       configured printers (id, name, model, state, camera kind, summary)
    GET  printers/{id}/state            {printer, status}  (status = the kit's: temps, AMS units/slots/spools, hms)
    GET  printers/{id}/events           SSE: the same object whenever it changes; the kit is polled at most once a
                                        second per open stream, a ping every 25 s, and no stream = no polling
    POST printers/{id}/command          {action: pause|resume|stop|light_on|light_off[, confirm]}; stop needs
                                        confirm: true
    GET  printers/{id}/usage            filament usage log;  POST printers/{id}/usage/{entry}/undo
    POST printers/{id}/map              re-map the printer's slots;  GET printers/{id}/map  its progress
    POST printers/{id}/report           the printer report: an XML file with no owner data, to share
    GET  printers/{id}/manual-map       Map by loading filament: the session's state (the kit's, shared with the
    POST printers/{id}/manual-map/{step}  setup page and the Android app); step = start | confirm | skip | stop | offer,
                                        body keys as the kit's (session, position, reported, nozzle, by_hand, share)
    POST printers/{id}/slots/{label}/load    {spool_id[, dry_run]}: put a spool in a slot (dry run unless
                                        dry_run: false), as the Android app does
    POST printers/{id}/slots/{label}/unload  {[dry_run]}: the slot's spool goes back to where it was (Spoolman
                                        only)
    GET  printers/tagged                the last tapped tag and its spool (the load picker's "last tap")
    GET  printers/manage                every printer the kit knows, set up or only seen on the network (no secrets)
    POST printers/add                   {serial, access_code[, name]} a Bambu printer the kit has seen;
                                        {family: klipper, host[, port, name]} a Klipper printer
    POST printers/{id}/edit             {name?, address?, port?, access_code?, api_key?, unpin?}: the kit's PATCH
    POST printers/{id}/forget           the kit's DELETE: the printer is forgotten
                                        add/edit/forget: always when the kit server itself serves the page (at
                                        home, :8710/intake); at the web module's public address only with
                                        config web.printer_changes true (Settings, default off); else 403
                                        (POSTs, so the intake app's exact-Origin check covers them)
    GET  printers/{id}/camera.mjpeg     the kit camera hub's MJPEG, relayed (img tag; LAN only like the rest)
    GET  printers/{id}/camera/{name}    the hub's HLS playlist / segments, relayed
    push/key, push/subscribe, push/unsubscribe, push/test   only with config `web.push` true (see push.py)

A camera viewer is counted by the kit hub while its response is open; closing the relay's upstream when the phone
goes away is what stops the camera (the hub's own idle stop covers HLS).
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .errors import Problem
from .slots import LABEL, SlotError

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0        # at most one kit poll per second per open stream
PING_SECONDS = 25.0
MAX_STREAMS = 12          # open status streams (a phone or two per printer)
MAX_CAMERAS = 4           # open MJPEG relays
BUSY = "too many open views of the printers; close one (another phone or tab) and this one will retry"
ACTIONS = ("pause", "resume", "stop", "light_on", "light_off")
# A printer id as the kit names it: a Bambu serial, or a Klipper printer's slug ("sv08-max", registry.slug). One
# check for every printer route: a Bambu-only one refused Klipper printers before the kit was asked.
ENTRY = re.compile(r"[A-Za-z0-9_-]{1,64}")
HLS_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\.(ts|m3u8)")
HLS_TYPES = {"m3u8": "application/vnd.apple.mpegurl", "ts": "video/mp2t"}
MAX_SEGMENT = 16 * 1024 * 1024
STATIC = Path(__file__).parent / "static"
LIST_FIELDS = ("id", "name", "model", "family", "state", "camera", "summary")
# the kit path of each step, written out so test_web_token_scope sees every path this unit calls
MANUAL_STEPS = {"start": "/api/printers/{serial}/manual-map/start", "confirm": "/api/printers/{serial}/manual-map/confirm",
                "skip": "/api/printers/{serial}/manual-map/skip", "stop": "/api/printers/{serial}/manual-map/stop",
                "offer": "/api/printers/{serial}/manual-map/offer"}
MANUAL_KEYS = ("session", "position", "reported", "nozzle", "by_hand", "share")
MANAGE_FIELDS = ("id", "name", "model", "model_name", "family", "ip", "host", "configured", "state", "pinned")
EDIT_KEYS = ("name", "address", "port", "access_code", "api_key", "unpin")
ADD_KEYS = ("family", "serial", "access_code", "name", "host", "port")
PUBLIC_CHANGES_OFF = ("Printer changes from the public address are off. Open this page on the home network, or turn "
                      "on \"Allow printer changes from the public address\" on the setup page (Settings, General).")
TAGGED_FIELDS = ("id", "vendor", "name", "location", "remaining_g")
# The kit's refusals in the Android app's words (PrinterHelp.message); a not_found keeps the kit's own text, which
# names what is missing (printer, slot or spool).
REFUSALS = {
    "printer_offline": "The printer is offline. Check that it is turned on and on the network.",
    "no_reply": "The printer did not answer in time. Try again.",
    "printer_busy": "The printer is printing. Try again when it's idle.",
    "slot_in_use": "This slot feeds the print that is running. Set it when the print is done, or pick another slot.",
    "cert_changed": ("The printer's certificate changed. If you reset the printer or its mainboard was replaced, add "
                     "it again with its Access Code. If not, something else may be answering at the printer's "
                     "address: check the printer's IP before re-adding."),
    "needs_developer_mode": ("The printer refuses remote control. On the printer open Settings > Network/LAN, turn "
                             "on LAN Only mode and then Developer Mode, then try again."),
    "no_preset": ("No preset for this filament on this printer yet. It is made at the next preset build; see the "
                  "Presets tab."),
    "write_refused": "The printer refused the change",
    "already_running": "Slot mapping or a load is in progress on this printer. Try again in a moment.",
}


def _printer(p: dict) -> dict:
    return {k: p.get(k) for k in LIST_FIELDS}


class PrintersApp:
    def __init__(self, intake, kit=None, *, push_on: bool = False):
        self.intake = intake
        self._kit = kit
        self.poll, self.ping = POLL_SECONDS, PING_SECONDS
        self.streams = self.cameras = 0
        self._shared: dict[str, tuple[float, dict]] = {}    # serial -> (when taken, snapshot) for the open streams
        self._shared_lock: dict[str, anyio.Lock] = {}
        self.last_test = 0.0
        self.push_on = push_on
        self.push_store = self.sender = self.watcher = None
        if push_on:
            from . import push   # the only import of push.py: with web.push off none of it runs
            self.push = push
            self.push_store = push.Store(push.state_dir() / "push.json")
            self.sender = push.webpush_sender(intake.origin)
            self.watcher = push.Watcher(self.kit, self.push_store, self.sender, intake.base + "/")
            self.watcher.start()

    @property
    def kit(self):
        if self._kit is None:
            from .slots import KitApi
            self._kit = KitApi()
        return self._kit

    # ---------- routes ----------
    def routes(self) -> list[Route]:
        g = self.guard
        table = [
            ("", g(self.list), ["GET"]),
            ("/{id}/state", g(self.state), ["GET"]),
            ("/{id}/events", g(self.events_route), ["GET"]),
            ("/{id}/command", g(self.command), ["POST"]),
            ("/{id}/usage", g(self.usage), ["GET"]),
            ("/{id}/usage/{entry}/undo", g(self.undo), ["POST"]),
            ("/{id}/map", g(self.map_start), ["POST"]),
            ("/{id}/map", g(self.map_get), ["GET"]),
            ("/{id}/report", g(self.map_report), ["POST"]),
            ("/{id}/manual-map", g(self.manual_get), ["GET"]),
            ("/{id}/manual-map/{step}", g(self.manual_step), ["POST"]),
            ("/{id}/slots/{label}/load", g(self.slot_load), ["POST"]),
            ("/{id}/slots/{label}/unload", g(self.slot_unload), ["POST"]),
            ("/tagged", g(self.tagged), ["GET"]),
            ("/manage", g(self.manage), ["GET"]),
            ("/add", g(self.add), ["POST"]),
            ("/{id}/edit", g(self.edit), ["POST"]),
            ("/{id}/forget", g(self.forget), ["POST"]),
            ("/{id}/camera.mjpeg", g(self.mjpeg), ["GET"]),
            ("/{id}/camera/{name}", g(self.hls), ["GET"])]
        if self.push_on:
            table += [("/push/key", g(self.push_key), ["GET"]), ("/push/subscribe", g(self.push_subscribe), ["POST"]),
                      ("/push/unsubscribe", g(self.push_unsubscribe), ["POST"]),
                      ("/push/test", g(self.push_test), ["POST"])]
        routes = [Route("/intake/api/printers" + p, fn, methods=m) for p, fn, m in table]
        return routes

    def guard(self, fn):
        """LAN, Host and Origin checks (the intake app's), plus the kit's refusals as readable errors."""
        async def inner(request: Request):
            try:
                return await fn(request)
            except SlotError as e:
                st = e.http
                body = {"error": REFUSALS.get(e.code or "", str(e))}
                if e.code:
                    body["code"] = e.code
                if e.field:
                    body["field"] = e.field       # the kit's refusal names the body key it is about
                return JSONResponse(body, st if isinstance(st, int) and 400 <= st < 600 and st != 401 else 502)
        return self.intake.api(inner)

    @staticmethod
    def _serial(request: Request) -> str:
        """The printer id of a per-printer route (_entry's check: Bambu serials and Klipper slugs)."""
        return PrintersApp._entry(request)

    async def _kit_call(self, fn, *args):
        return await anyio.to_thread.run_sync(fn, *args)

    async def _body(self, request: Request) -> dict:
        return await self.intake._body(request)

    # ---------- reads ----------
    async def list(self, request: Request):
        d = await self._kit_call(self.kit.get, "/api/printers")
        return {"printers": [_printer(p) for p in d.get("printers", []) if p.get("configured")]}

    def snapshot(self, serial: str) -> dict:
        d = self.kit.get(f"/api/printers/{serial}")
        return {"printer": _printer(d.get("printer") or {}), "status": d.get("status")}

    async def state(self, request: Request):
        return await self._kit_call(self.snapshot, self._serial(request))

    async def usage(self, request: Request):
        serial = self._serial(request)
        days = request.query_params.get("days")
        path = f"/api/printers/{serial}/usage"
        if days is not None:
            if not re.fullmatch(r"\d{1,3}(\.\d{1,2})?", days):
                raise Problem("days must be a number")
            path += f"?days={days}"
        return await self._kit_call(self.kit.get, path)

    async def map_get(self, request: Request):
        return await self._kit_call(self.kit.get, f"/api/printers/{self._serial(request)}/map")

    # ---------- writes ----------
    async def command(self, request: Request):
        serial = self._serial(request)
        b = await self._body(request)
        action = b.get("action")
        if action not in ACTIONS:
            raise Problem("action must be one of: " + ", ".join(ACTIONS))
        if action == "stop" and b.get("confirm") is not True:
            raise Problem("stop needs confirm: true")
        log.info("printers tab: %s %s", action, serial)
        return await self._kit_call(self.kit.post, f"/api/printers/{serial}/command", {"action": action})

    async def undo(self, request: Request):
        serial, entry = self._serial(request), request.path_params["entry"]
        if not ENTRY.fullmatch(entry):
            raise Problem("no such usage entry")

        def run():   # only this printer's own entries (the kit's undo route takes any id)
            mine = self.kit.get(f"/api/printers/{serial}/usage?days=366").get("entries") or []
            if not any(isinstance(e, dict) and e.get("id") == entry for e in mine):
                raise Problem("that usage entry is not this printer's")
            return self.kit.post(f"/api/usage/{entry}/undo", {})
        return await self._kit_call(run)

    @staticmethod
    def _label(request: Request) -> str:
        label = request.path_params["label"]
        if not LABEL.fullmatch(label):
            raise Problem("no such slot")
        return label

    @staticmethod
    def _dry(b: dict) -> bool:
        dry = b.get("dry_run", True)
        if not isinstance(dry, bool):
            raise Problem("dry_run must be true or false")
        return dry

    async def slot_load(self, request: Request):
        """The kit's load (preset, slot setting, Spoolman location), a dry run unless `dry_run: false`; the phone
        shows the dry run's plan and sends the real load only after the user confirms it."""
        serial, label = self._serial(request), self._label(request)
        b = await self._body(request)
        spool = b.get("spool_id")
        if not isinstance(spool, int) or isinstance(spool, bool) or spool < 1:
            raise Problem("spool_id must be a spool id")
        dry = self._dry(b)
        if not dry:
            log.info("printers tab: load spool %s into %s %s", spool, serial, label)
        return await self._kit_call(self.kit.post, f"/api/printers/{serial}/slots/{label}/load",
                                    {"spool_id": spool, "dry_run": dry})

    async def slot_unload(self, request: Request):
        serial, label = self._serial(request), self._label(request)
        dry = self._dry(await self._body(request))
        if not dry:
            log.info("printers tab: unload %s %s", serial, label)
        return await self._kit_call(self.kit.post, f"/api/printers/{serial}/slots/{label}/unload", {"dry_run": dry})

    async def tagged(self, request: Request):
        """The newest tap on any reader and the spool linked to it (only the fields the picker shows)."""
        t = await anyio.to_thread.run_sync(self.intake.tools.tag_state)
        sp = t.get("spool")
        return {"nfc_id": t.get("nfc_id"), "spool": {k: sp.get(k) for k in TAGGED_FIELDS} if sp else None}

    async def map_report(self, request: Request):
        return await self._kit_call(self.kit.post, f"/api/printers/{self._serial(request)}/report", {})

    # ---------- add, edit, forget (the kit's POST / PATCH / DELETE /api/printers) ----------
    @staticmethod
    def _entry(request: Request) -> str:
        """A printer id as the kit names it: a Bambu serial, or a Klipper printer's slug."""
        s = request.path_params["id"]
        if not ENTRY.fullmatch(s):
            raise Problem("no such printer")
        return s

    def changes_allowed(self) -> bool:
        """Printer changes (add, edit, forget): the page the kit server serves at home always; the web module's page
        at its public address only when the owner turned it on (orchestrator ruling, 2026-11-10)."""
        if self.intake.origin is None:          # served by the kit server itself: home network only
            return True
        from .. import config
        return ((config.load().get("web") or {}).get("printer_changes")) is True

    def _changes_or_refuse(self) -> JSONResponse | None:
        if self.changes_allowed():
            return None
        return JSONResponse({"error": PUBLIC_CHANGES_OFF}, 403)

    async def manage(self, request: Request):
        d = await self._kit_call(self.kit.get, "/api/printers")
        return {"printers": [{k: p.get(k) for k in MANAGE_FIELDS} for p in d.get("printers", [])],
                "changes": self.changes_allowed()}

    async def add(self, request: Request):
        if (no := self._changes_or_refuse()) is not None:
            return no
        b = await self._body(request)
        body = {k: b[k] for k in ADD_KEYS if k in b}
        log.info("printers tab: add a %s printer", body.get("family", "bambu"))
        r = await self._kit_call(self.kit.post, "/api/printers", body)
        return {"printer": {k: (r.get("printer") or {}).get(k) for k in MANAGE_FIELDS}}

    async def edit(self, request: Request):
        if (no := self._changes_or_refuse()) is not None:
            return no
        serial = self._entry(request)
        b = await self._body(request)
        body = {k: b[k] for k in EDIT_KEYS if k in b}
        log.info("printers tab: edit %s (%s)", serial, ",".join(sorted(body)))
        r = await self._kit_call(self.kit.patch, f"/api/printers/{serial}", body)
        out = {"printer": {k: (r.get("printer") or {}).get(k) for k in MANAGE_FIELDS}, "changed": r.get("changed", [])}
        if r.get("note"):
            out["note"] = r["note"]
        return out

    async def forget(self, request: Request):
        if (no := self._changes_or_refuse()) is not None:
            return no
        serial = self._entry(request)
        log.info("printers tab: forget %s", serial)
        return await self._kit_call(self.kit.delete, f"/api/printers/{serial}")

    async def manual_get(self, request: Request):
        return await self._kit_call(self.kit.get, f"/api/printers/{self._serial(request)}/manual-map")

    async def manual_step(self, request: Request):
        serial, step = self._serial(request), request.path_params["step"]
        if step not in MANUAL_STEPS:
            raise Problem("no such step")
        b = await self._body(request)
        body = {k: b[k] for k in MANUAL_KEYS if k in b}
        log.info("printers tab: manual map %s %s", step, serial)
        return await self._kit_call(self.kit.post, MANUAL_STEPS[step].format(serial=serial), body)

    async def map_start(self, request: Request):
        return await self._kit_call(self.kit.post, f"/api/printers/{self._serial(request)}/map", {})

    # ---------- live status (SSE) ----------
    async def _shared_snapshot(self, serial: str) -> dict:
        """The snapshot for one stream's tick. Streams on one printer (two phones, two tabs) share one kit call per
        tick: an answer younger than half a poll is reused, and a second stream waits for the call under way."""
        def fresh():
            hit = self._shared.get(serial)
            return hit[1] if hit is not None and time.monotonic() - hit[0] < self.poll / 2 else None
        if (payload := fresh()) is not None:
            return payload
        lock = self._shared_lock.setdefault(serial, anyio.Lock())
        async with lock:
            if (payload := fresh()) is not None:
                return payload
            try:
                payload = await anyio.to_thread.run_sync(self.snapshot, serial)
            except SlotError as e:
                payload = {"error": str(e)}
            self._shared[serial] = (time.monotonic(), payload)
            if len(self._shared) > MAX_STREAMS:             # only printers with a stream open matter
                now = time.monotonic()
                for old in [k for k, (t, _) in self._shared.items() if now - t >= self.poll and k != serial]:
                    self._shared.pop(old, None)
                    self._shared_lock.pop(old, None)
            return payload

    async def events(self, serial: str, is_alive):
        """SSE text chunks: `data: <json>` when the snapshot changes, `: ping` after PING_SECONDS of quiet. Polls
        the kit once per `poll` seconds while `is_alive()`; the loop (and so the polling) ends with the client."""
        self.streams += 1
        try:
            last, last_write = None, 0.0
            while await is_alive():
                text = _dump(await self._shared_snapshot(serial))
                now = time.monotonic()
                if text != last:
                    last, last_write = text, now
                    yield f"data: {text}\n\n"
                elif now - last_write >= self.ping:
                    last_write = now
                    yield ": ping\n\n"
                await anyio.sleep(self.poll)
        finally:
            self.streams -= 1

    async def events_route(self, request: Request):
        serial = self._serial(request)
        heads = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        if self.streams >= MAX_STREAMS:    # a readable message, and a long retry so the phone does not hammer
            msg = "retry: 30000\ndata: " + _dump({"error": BUSY}) + "\n\n"
            return Response(msg, media_type="text/event-stream", headers=heads)

        async def alive():
            return not await request.is_disconnected()
        return StreamingResponse(self.events(serial, alive), media_type="text/event-stream", headers=heads)

    # ---------- camera ----------
    async def mjpeg(self, request: Request):
        serial = self._serial(request)
        if self.cameras >= MAX_CAMERAS:
            return JSONResponse({"error": "too many open camera views"}, 429)
        self.cameras += 1
        try:
            _status, _ctype, up = await anyio.to_thread.run_sync(self.kit.raw, f"/api/printers/{serial}/camera.mjpeg")
        except BaseException:
            self.cameras -= 1
            raise
        read = getattr(up, "read1", up.read)

        def release():
            self.cameras -= 1
            up.close()      # the kit hub counts the viewer out when this connection ends

        async def body():
            while True:
                chunk = await anyio.to_thread.run_sync(read, 65536)
                if not chunk:
                    break
                yield chunk
        return _Relay(body(), release, media_type="multipart/x-mixed-replace; boundary=frame",
                      headers={"Cache-Control": "no-cache"})

    async def hls(self, request: Request):
        serial, name = self._serial(request), request.path_params["name"]
        m = HLS_NAME.fullmatch(name)
        if not m:
            raise Problem("only index.m3u8 and .ts segments are served here")

        def fetch() -> bytes:
            _s, _c, up = self.kit.raw(f"/api/printers/{serial}/camera/{name}")
            try:
                return up.read(MAX_SEGMENT)
            finally:
                up.close()
        data = await anyio.to_thread.run_sync(fetch)
        return Response(data, media_type=HLS_TYPES[m.group(1)], headers={"Cache-Control": "no-cache"})

    # ---------- Web Push (only with web.push) ----------
    def _sendable(self) -> None:
        if not self.push.available():
            raise Problem(self.push.NOT_INSTALLED)

    async def push_key(self, request: Request):
        self._sendable()
        return {"key": (await anyio.to_thread.run_sync(self.push.vapid))[1]}

    async def push_subscribe(self, request: Request):
        b = await self._body(request)
        try:
            info = self.push.check_subscription(b.get("subscription"))
        except ValueError as e:
            raise Problem(str(e)) from None
        await anyio.to_thread.run_sync(self.push_store.add, info)
        return {"ok": True}

    async def push_unsubscribe(self, request: Request):
        ep = (await self._body(request)).get("endpoint")
        if isinstance(ep, str):
            await anyio.to_thread.run_sync(self.push_store.remove, ep)
        return {"ok": True}

    async def push_test(self, request: Request):
        self._sendable()
        now = time.monotonic()
        if now - self.last_test < self.push.TEST_EVERY:
            raise Problem(f"wait {self.push.TEST_EVERY:.0f} s between test alerts")
        self.last_test = now
        r = await anyio.to_thread.run_sync(lambda: self.push.send_all(
            self.push_store, "Printers test", "Notifications are working.", "test", sender=self.sender,
            url=self.intake.base + "/", budget=self.push.TEST_BUDGET))
        if r["removed"] and not r["sent"] and not r["failed"]:
            raise Problem(f"the test alert was not delivered: {r['removed']} subscription(s) no longer exist and were "
                          "removed; turn notifications on again in this browser.")
        if r["failed"] and not r["sent"]:
            raise Problem("the test alert was not delivered: " + "; ".join(r["failed"][:3])
                          + ". If the push service cannot be reached, the web service's network limits may block it "
                          "(user guide, Web Push).")
        return {"ok": True, **r}


class _Relay(StreamingResponse):
    """A streaming response whose cleanup runs exactly once however it ends: served, client gone, error, or never
    started (a response that is dropped without being sent is cleaned up when it is collected)."""

    def __init__(self, content, on_close, **kw):
        super().__init__(content, **kw)
        self._on_close = on_close

    def _close(self) -> None:
        cb, self._on_close = self._on_close, None
        if cb is not None:
            cb()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._close()

    def __del__(self):
        try:
            self._close()
        except Exception:  # noqa: BLE001
            pass


def _dump(obj) -> str:
    import json
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
