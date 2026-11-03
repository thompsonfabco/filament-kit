"""The Printers tab of the phone web app: routes under `<public path>/intake/api/printers`, on the intake app's
session (cookie), LAN check, exact-Origin POSTs and CSP.

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
    GET  printers/{id}/camera.mjpeg     the kit camera hub's MJPEG, relayed (img tag; LAN only like the rest)
    GET  printers/{id}/camera/{name}    the hub's HLS playlist / segments, relayed
    push/key, push/subscribe, push/unsubscribe, push/test   only with config `web.push` true (see push.py)

A camera viewer is counted by the kit hub while its response is open; closing the relay's upstream when the phone
goes away is what stops the camera (the hub's own idle stop covers HLS).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .errors import Problem
from .slots import SlotError

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0        # at most one kit poll per second per open stream
PING_SECONDS = 25.0
MAX_STREAMS = 12          # open status streams (a phone or two per printer)
MAX_CAMERAS = 4           # open MJPEG relays
BUSY = "too many open views of the printers; close one (another phone or tab) and this one will retry"
ACTIONS = ("pause", "resume", "stop", "light_on", "light_off")
SERIAL = re.compile(r"[A-Za-z0-9]{1,32}")
ENTRY = re.compile(r"[A-Za-z0-9_-]{1,64}")
HLS_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\.(ts|m3u8)")
HLS_TYPES = {"m3u8": "application/vnd.apple.mpegurl", "ts": "video/mp2t"}
MAX_SEGMENT = 16 * 1024 * 1024
STATIC = Path(__file__).parent / "static"
LIST_FIELDS = ("id", "name", "model", "state", "camera", "summary")


def _printer(p: dict) -> dict:
    return {k: p.get(k) for k in LIST_FIELDS}


class PrintersApp:
    def __init__(self, intake, kit=None, *, push_on: bool = False):
        self.intake = intake
        self._kit = kit
        self.poll, self.ping = POLL_SECONDS, PING_SECONDS
        self.streams = self.cameras = 0
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
            ("/{id}/camera.mjpeg", g(self.mjpeg), ["GET"]),
            ("/{id}/camera/{name}", g(self.hls), ["GET"])]
        if self.push_on:
            table += [("/push/key", g(self.push_key), ["GET"]), ("/push/subscribe", g(self.push_subscribe), ["POST"]),
                      ("/push/unsubscribe", g(self.push_unsubscribe), ["POST"]),
                      ("/push/test", g(self.push_test), ["POST"])]
        routes = [Route("/intake/api/printers" + p, fn, methods=m) for p, fn, m in table]
        if self.push_on:   # the service worker: served from the app's path so its scope is the app (LAN + session)
            routes.append(Route("/intake/sw.js", g(self.service_worker), methods=["GET"]))
        return routes

    def guard(self, fn):
        """Session, LAN and Origin checks (the intake app's), plus the kit's refusals as readable errors."""
        async def inner(request: Request):
            try:
                return await fn(request)
            except SlotError as e:
                st = e.http
                return JSONResponse({"error": str(e)}, st if isinstance(st, int) and 400 <= st < 600 and st != 401
                                    else 502)
        return self.intake.api(inner)

    @staticmethod
    def _serial(request: Request) -> str:
        s = request.path_params["id"]
        if not SERIAL.fullmatch(s):
            raise Problem("no such printer")
        return s

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

    async def map_start(self, request: Request):
        return await self._kit_call(self.kit.post, f"/api/printers/{self._serial(request)}/map", {})

    # ---------- live status (SSE) ----------
    async def events(self, serial: str, is_alive):
        """SSE text chunks: `data: <json>` when the snapshot changes, `: ping` after PING_SECONDS of quiet. Polls
        the kit once per `poll` seconds while `is_alive()`; the loop (and so the polling) ends with the client."""
        self.streams += 1
        try:
            last, last_write = None, 0.0
            while await is_alive():
                try:
                    payload = await anyio.to_thread.run_sync(self.snapshot, serial)
                except SlotError as e:
                    payload = {"error": str(e)}
                text = _dump(payload)
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
        threading.Thread(target=self.push.send_all, daemon=True,
                         args=(self.push_store, "Printers test", "Notifications are working.", "test"),
                         kwargs={"sender": self.sender, "url": self.intake.base + "/"}).start()
        return {"ok": True}

    async def service_worker(self, request: Request):
        return Response((STATIC / "sw.js").read_bytes(), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


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
