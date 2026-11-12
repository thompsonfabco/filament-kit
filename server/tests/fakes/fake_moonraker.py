"""A scriptable Moonraker for tests: the HTTP API the Klipper bridge uses plus the `/websocket` JSON-RPC subscription.

`FakeMoonraker()` holds the printer's state in plain attributes that tests change directly:
    objects        list of Klipper object names (`/printer/objects/list`)
    status         {object: {field: value}} (`/printer/objects/query`, subscription snapshots)
    klippy_state   "ready" | "shutdown" | "error" | "startup" (`/printer/info` state, `/server/info` klippy_state)
    state_message  Klipper's message for a non-ready state
    hostname       `/printer/info` hostname
    spool_id       Moonraker's active spool (`/server/spoolman/spool_id`)
    history        list of job dicts, newest first (`/server/history/list`)
    db             {namespace: {key: value}} (`/server/database/*`)
    webcams        list of webcam dicts
    server_config  dict returned as `/server/config` result.config
    spoolman       dict for `/server/spoolman/status`
    api_key        when set, every request needs `X-Api-Key: <it>` (401 otherwise)
    gcode_errors   {script prefix: message}: a matching gcode answers 400 with Klipper's message
    ignore_gcode   True: gcode is accepted but has no effect (a printer that never confirms)
`gcode_log` records every script; `actions` every print action and restart. Built-in gcode: SET_ACTIVE_SPOOL ID=n,
CLEAR_ACTIVE_SPOOL, FK_SET_TOOL_SPOOL TOOL=t ID=n (updates `gcode_macro _FK_TOOL_SPOOLS`).
`push(delta)` merges a status delta and notifies subscribers; `event(name, params)` sends a notification;
`drop()` closes every websocket (the client must reconnect). `serve()` → (base_url, stop()).
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _merge(dst: dict, delta: dict) -> None:
    for obj, fields in delta.items():
        dst.setdefault(obj, {}).update(fields)


class FakeMoonraker:
    def __init__(self, objects=None, status=None):
        self.objects: list[str] = list(objects or ["webhooks", "print_stats", "toolhead", "extruder",
                                                   "heater_bed", "virtual_sdcard", "gcode_macro SET_ACTIVE_SPOOL"])
        self.status: dict = status or {"print_stats": {"state": "standby", "filename": "", "info": {}},
                                       "toolhead": {"extruder": "extruder"},
                                       "extruder": {"temperature": 25.0, "target": 0.0},
                                       "heater_bed": {"temperature": 24.0, "target": 0.0},
                                       "virtual_sdcard": {"progress": 0.0}}
        self.klippy_state, self.state_message, self.hostname = "ready", "Printer is ready", "fakeprinter"
        self.subscribe_refused = False      # as Moonraker answers a subscribe with Klipper's host disconnected
        self.spool_id: int | None = None
        self.history: list[dict] = []
        self.db: dict = {}
        self.webcams: list[dict] = []
        self.server_config: dict = {"spoolman": {"server": "http://spoolman.example.com:7912"}}
        self.spoolman: dict = {"spoolman_connected": True, "pending_reports": [], "spool_id": None}
        self.api_key: str | None = None
        self.gcode_errors: dict[str, str] = {}
        self.ignore_gcode = False
        self.refuse_ws = False        # True: every websocket is closed at once (a printer whose socket stays down)
        self.gcode_log: list[str] = []
        self.actions: list[str] = []
        self._subs: list[tuple[WebSocket, dict]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.app = self._app()

    # --- test controls -------------------------------------------------------------------------------------------
    def push(self, delta: dict) -> None:
        _merge(self.status, delta)
        self._notify("notify_status_update", [delta, time.time()])

    def event(self, name: str, params: list | None = None) -> None:
        self._notify(name, params or [])

    def drop(self) -> None:
        if self._loop is None:
            return
        subs, self._subs = self._subs, []
        for ws, _ in subs:
            asyncio.run_coroutine_threadsafe(ws.close(code=1012), self._loop)

    def _notify(self, method: str, params: list) -> None:
        if self._loop is None:
            return
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        for ws, _ in list(self._subs):
            asyncio.run_coroutine_threadsafe(self._send(ws, msg), self._loop)

    async def _send(self, ws, msg) -> None:
        try:
            await ws.send_text(msg)
        except Exception:  # noqa: BLE001 - a closed socket
            pass

    def set_spool(self, sid: int | None) -> None:
        self.spool_id = sid
        self.spoolman["spool_id"] = sid
        self._notify("notify_active_spool_set", [{"spool_id": sid}])

    # --- gcode ---------------------------------------------------------------------------------------------------
    def _run_gcode(self, script: str) -> str | None:
        self.gcode_log.append(script)
        for prefix, msg in self.gcode_errors.items():
            if script.startswith(prefix):
                return msg
        if self.ignore_gcode:
            return None
        for line in script.splitlines():
            m = re.fullmatch(r"SET_ACTIVE_SPOOL ID=(\d+)", line.strip())
            if m:
                self.set_spool(int(m.group(1)))
            elif line.strip() == "CLEAR_ACTIVE_SPOOL":
                self.set_spool(None)
            m = re.fullmatch(r"FK_SET_TOOL_SPOOL TOOL=(\d+) ID=(\d*)", line.strip())
            if m:
                self.push({"gcode_macro _FK_TOOL_SPOOLS": {f"t{m.group(1)}": int(m.group(2) or 0)}})
        return None

    # --- the app -------------------------------------------------------------------------------------------------
    def _authed(self, headers) -> bool:
        return self.api_key is None or headers.get("x-api-key") == self.api_key

    def _app(self) -> Starlette:
        fake = self

        def ok(result):
            return JSONResponse({"result": result})

        def err(code, msg):
            return JSONResponse({"error": {"code": code, "message": msg}}, status_code=code)

        def guard(fn):
            async def wrapped(request: Request):
                if not fake._authed(request.headers):
                    return err(401, "Unauthorized")
                return await fn(request)
            return wrapped

        @guard
        async def printer_info(request):
            return ok({"state": fake.klippy_state, "state_message": fake.state_message, "hostname": fake.hostname,
                       "software_version": "v0.12.0-fake"})

        @guard
        async def server_info(request):
            return ok({"klippy_connected": True, "klippy_state": fake.klippy_state,
                       "components": ["spoolman", "database"]})

        @guard
        async def objects_list(request):
            return ok({"objects": fake.objects})

        @guard
        async def objects_query(request):
            if request.method == "POST":
                wanted = (await request.json()).get("objects", {})
            else:
                wanted = {k: (v.split(",") if v else None) for k, v in request.query_params.items()}
            out = {}
            for obj, fields in wanted.items():
                cur = fake.status.get(obj)
                if cur is None:
                    continue
                out[obj] = dict(cur) if not fields else {f: cur[f] for f in fields if f in cur}
            return ok({"eventtime": time.time(), "status": out})

        @guard
        async def gcode(request):
            script = (await request.json()).get("script", "")
            msg = fake._run_gcode(script)
            return err(400, msg) if msg else ok("ok")

        @guard
        async def print_action(request):
            fake.actions.append(request.path_params["action"])
            return ok("ok")

        @guard
        async def history_list(request):
            limit = int(request.query_params.get("limit", "50"))
            return ok({"count": len(fake.history), "jobs": fake.history[:limit]})

        @guard
        async def spool_id(request):
            return ok({"spool_id": fake.spool_id})

        @guard
        async def spoolman_status(request):
            return ok(fake.spoolman)

        @guard
        async def server_config(request):
            return ok({"config": fake.server_config})

        @guard
        async def db_list(request):
            return ok({"namespaces": sorted(fake.db), "backups": []})

        @guard
        async def db_item(request):
            if request.method == "POST":
                body = await request.json()
                fake.db.setdefault(body["namespace"], {})[body["key"]] = body["value"]
                return ok({"namespace": body["namespace"], "key": body["key"], "value": body["value"]})
            ns = request.query_params.get("namespace")
            if request.method == "DELETE":
                key = request.query_params.get("key")
                if key not in fake.db.get(ns, {}):
                    return err(404, f"Key '{key}' not found")
                return ok({"namespace": ns, "key": key, "value": fake.db[ns].pop(key)})
            if ns not in fake.db:
                return err(404, f"Namespace '{ns}' not found")
            return ok({"namespace": ns, "key": None, "value": fake.db[ns]})

        @guard
        async def restart(request):
            await request.body()    # read it: replying with a body unread makes Windows reset the connection
            fake.actions.append("restart")
            return ok("ok")

        @guard
        async def server_restart(request):
            await request.body()
            fake.actions.append("server_restart")
            return ok("ok")

        @guard
        async def webcams(request):
            return ok({"webcams": fake.webcams})

        async def ws_endpoint(ws: WebSocket):
            if not fake._authed(ws.headers) or fake.refuse_ws:
                await ws.close(code=4001)
                return
            await ws.accept()
            fake._loop = asyncio.get_running_loop()
            entry = (ws, {})
            fake._subs.append(entry)
            try:
                while True:
                    msg = json.loads(await ws.receive_text())
                    if msg.get("method") == "printer.objects.subscribe" and fake.subscribe_refused:
                        await ws.send_text(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                            "code": 503, "message": "Klippy Host not connected"}}))
                    elif msg.get("method") == "printer.objects.subscribe":
                        wanted = (msg.get("params") or {}).get("objects", {})
                        entry[1].clear()
                        entry[1].update(wanted)
                        snap = {o: dict(fake.status[o]) for o in wanted if o in fake.status}
                        await ws.send_text(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                                                       "result": {"eventtime": time.time(), "status": snap}}))
                    elif "id" in msg:
                        await ws.send_text(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"}))
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                if entry in fake._subs:
                    fake._subs.remove(entry)

        return Starlette(routes=[
            Route("/printer/info", printer_info),
            Route("/server/info", server_info),
            Route("/printer/objects/list", objects_list),
            Route("/printer/objects/query", objects_query, methods=["GET", "POST"]),
            Route("/printer/gcode/script", gcode, methods=["POST"]),
            Route("/printer/print/{action}", print_action, methods=["POST"]),
            Route("/server/history/list", history_list),
            Route("/server/spoolman/spool_id", spool_id),
            Route("/server/spoolman/status", spoolman_status),
            Route("/server/config", server_config),
            Route("/server/database/list", db_list),
            Route("/server/database/item", db_item, methods=["GET", "POST", "DELETE"]),
            Route("/server/webcams/list", webcams),
            Route("/printer/restart", restart, methods=["POST"]),
            Route("/server/restart", server_restart, methods=["POST"]),
            WebSocketRoute("/websocket", ws_endpoint),
        ])

    def serve(self):
        """Run on 127.0.0.1:<free port> in a thread; returns (host, port, stop)."""
        sock = socket.socket()      # bound here and handed over: with parallel workers, a port chosen first can be taken before it's used
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning",
                                               ws="websockets-sansio"))
        t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        t.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("fake moonraker did not start")

        def stop():
            server.should_exit = True
            t.join(timeout=5)
        return "127.0.0.1", port, stop
