"""Moonraker client: the HTTP API calls the Klipper bridge makes, and a websocket subscriber for live status.

`Moonraker(host, port=7125, api_key="", timeout=5.0)`: one printer's Moonraker. Every method raises `Offline`
(connection refused, timeout, DNS), `Unauthorized` (401/403: Moonraker wants an API key) or `MoonrakerError` (any
other error answer); `gcode` raises `GcodeError` with Klipper's own message when Klipper refuses a script. The API key
goes in the `X-Api-Key` header and is never logged. Redirects are never followed, on HTTP or the websocket, to the same
host or another: real Moonraker doesn't send them, and the key must not go wherever one points.

`Subscriber(client, objects, on_status, on_event, backoff=(2, 60))`: a thread that keeps one websocket open to
`/websocket`, subscribes to `objects` (`printer.objects.subscribe`), calls `on_status(status)` with the full snapshot
after each (re)subscribe and with each `notify_status_update` delta, and `on_event(name, params)` for
`notify_klippy_ready|shutdown|disconnected`, `notify_active_spool_set` and `notify_spoolman_status_changed`. It
re-subscribes after
`notify_klippy_ready` (Klipper restarted: subscriptions are gone) and reconnects with doubling backoff. Callbacks
run on the subscriber's thread and must not block for long.
"""
from __future__ import annotations

import itertools
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger(__name__)
ACTIONS = ("pause", "resume", "cancel")
EVENTS = ("notify_klippy_ready", "notify_klippy_shutdown", "notify_klippy_disconnected", "notify_active_spool_set",
          "notify_spoolman_status_changed")
MAX_BODY = 8_000_000


class MoonrakerError(Exception):
    pass


class Offline(MoonrakerError):
    pass


class Unauthorized(MoonrakerError):
    pass


class GcodeError(MoonrakerError):
    pass


class NotFound(MoonrakerError):
    pass


def _host_part(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None     # the 3xx then reaches the caller as an HTTPError


_OPENER = urllib.request.build_opener(_NoRedirect)


class Moonraker:
    def __init__(self, host: str, port: int = 7125, api_key: str = "", timeout: float = 5.0):
        self.host, self.port, self.timeout = host, int(port), timeout
        self._key = api_key or ""
        self.base = f"http://{_host_part(host)}:{self.port}"

    def __repr__(self) -> str:   # never shows the key
        return f"Moonraker({self.host}:{self.port})"

    def _headers(self) -> dict:
        h = {"Accept": "application/json", "User-Agent": "filament-kit"}
        if self._key:
            h["X-Api-Key"] = self._key
        return h

    def _call(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None):
        url = self.base + path + (("?" + urllib.parse.urlencode(query, safe=",")) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with _OPENER.open(req, timeout=self.timeout) as r:
                raw = r.read(MAX_BODY + 1)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:     # Location is left out: it is the far side's text
                raise MoonrakerError(f"Moonraker at {self.host}:{self.port} answered with a redirect ({e.code}), which "
                                     "the kit does not follow: give the printer's direct address") from None
            msg = _error_message(e)
            if e.code in (401, 403):
                raise Unauthorized(f"Moonraker at {self.host} wants an API key ({e.code})") from None
            if e.code == 404:
                raise NotFound(msg) from None
            if path == "/printer/gcode/script" and e.code == 400:
                raise GcodeError(msg) from None
            raise MoonrakerError(f"{method} {path}: {e.code} {msg}") from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise Offline(f"Moonraker at {self.host}:{self.port} is not answering ({_reason(e)})") from None
        if len(raw) > MAX_BODY:
            raise MoonrakerError(f"{method} {path}: answer larger than {MAX_BODY} bytes")
        try:
            return json.loads(raw)["result"]
        except (ValueError, KeyError, TypeError) as e:
            raise MoonrakerError(f"{method} {path}: not a Moonraker answer ({type(e).__name__})") from None

    # --- reads ---------------------------------------------------------------------------------------------------
    def info(self) -> dict:
        return self._call("GET", "/printer/info")

    def server_info(self) -> dict:
        return self._call("GET", "/server/info")

    def objects(self) -> list[str]:
        return list(self._call("GET", "/printer/objects/list").get("objects") or [])

    def query(self, objs: dict[str, list[str] | None]) -> dict:
        return dict(self._call("POST", "/printer/objects/query", body={"objects": objs}).get("status") or {})

    def history_last(self) -> dict | None:
        jobs = self._call("GET", "/server/history/list", query={"limit": 1, "order": "desc"}).get("jobs") or []
        return jobs[0] if jobs else None

    def spool_id(self) -> int | None:
        v = self._call("GET", "/server/spoolman/spool_id").get("spool_id")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def spoolman_status(self) -> dict:
        return self._call("GET", "/server/spoolman/status")

    def server_config(self) -> dict:
        return dict(self._call("GET", "/server/config").get("config") or {})

    def db_namespaces(self) -> list[str]:
        return list(self._call("GET", "/server/database/list").get("namespaces") or [])

    def db_get(self, ns: str) -> dict | None:
        try:
            v = self._call("GET", "/server/database/item", query={"namespace": ns}).get("value")
        except NotFound:
            return None
        return v if isinstance(v, dict) else None

    def webcams(self) -> list[dict]:
        return list(self._call("GET", "/server/webcams/list").get("webcams") or [])

    # --- writes --------------------------------------------------------------------------------------------------
    def gcode(self, script: str) -> None:
        self._call("POST", "/printer/gcode/script", body={"script": script})

    def print_action(self, action: str) -> None:
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
        self._call("POST", f"/printer/print/{action}")

    def db_post(self, ns: str, key: str, value) -> None:
        self._call("POST", "/server/database/item", body={"namespace": ns, "key": key, "value": value})

    # --- websocket -----------------------------------------------------------------------------------------------
    def ws_url(self) -> str:
        return f"ws://{_host_part(self.host)}:{self.port}/websocket"


def _error_message(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read(65536))
        msg = (body.get("error") or {}).get("message")
        if isinstance(msg, str) and msg:
            return msg
    except Exception:  # noqa: BLE001 - not JSON
        pass
    return str(e.reason)


def _reason(e: Exception) -> str:
    r = getattr(e, "reason", None)
    return str(r or e or type(e).__name__)


class Subscriber:
    def __init__(self, client: Moonraker, objects: dict, on_status: Callable[[dict], None],
                 on_event: Callable[[str, list], None], backoff: tuple[float, float] = (2.0, 60.0),
                 on_connect: Callable[[], None] | None = None):
        self.client, self.objects = client, dict(objects)
        self.on_status, self.on_event, self.on_connect = on_status, on_event, on_connect
        self.backoff = backoff
        self.connected = False
        self.down_since = time.monotonic()     # when `connected` last went False (or the subscriber started)
        self.drops = 0                         # times `connected` went False: a reconnect can undo it between two looks
        self._stop = threading.Event()
        self._ws = None
        self._thread: threading.Thread | None = None
        self._ids = itertools.count(1)
        self._later: set[int] = set()          # subscribes from set_objects whose snapshot is still to come

    def start(self) -> "Subscriber":
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"moonraker-{self.client.host}")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(5)
        self.connected = False

    def set_objects(self, objects: dict) -> None:
        """Subscribe to another object set (takes effect now if connected, else on the next connect)."""
        self.objects = dict(objects)
        ws = self._ws
        if ws is not None:
            try:
                self._subscribe(ws, later=True)
            except Exception:  # noqa: BLE001 - the reader loop notices a dead socket
                pass

    def _subscribe(self, ws, later: bool = False) -> int:
        rid = next(self._ids)
        if later:
            self._later.add(rid)
        ws.send(json.dumps({"jsonrpc": "2.0", "method": "printer.objects.subscribe",
                            "params": {"objects": self.objects}, "id": rid}))
        return rid

    def _run(self) -> None:
        from websockets.sync.client import connect
        delay = self.backoff[0]
        while not self._stop.is_set():
            try:
                headers = {"X-Api-Key": self.client._key} if self.client._key else None
                # Our own socket because websockets then refuses every redirect; left to itself it follows them,
                # and on another host it would strip only its own credential headers, not X-Api-Key.
                sock = socket.create_connection((self.client.host.strip("[]"), self.client.port),
                                                timeout=self.client.timeout)
                sock.settimeout(None)
                with connect(self.client.ws_url(), sock=sock, additional_headers=headers,
                             open_timeout=self.client.timeout, close_timeout=1, max_size=MAX_BODY) as ws:
                    self._ws = ws
                    if self._stop.is_set():
                        break
                    sub_id = self._subscribe(ws)
                    for raw in ws:
                        if self._stop.is_set():
                            break
                        msg = json.loads(raw)
                        if msg.get("id") in self._later:     # its snapshot is news, but no new connect
                            self._later.discard(msg["id"])
                            if isinstance(msg.get("result"), dict):
                                self.on_status(dict(msg["result"].get("status") or {}))
                            continue
                        if msg.get("id") == sub_id and (msg.get("error") or {}).get("code") == 503:
                            # Klipper's host is away, and the event saying so may have gone before this socket came up.
                            # Only for this subscribe: set-up answers the event with set_objects, so that one must not.
                            self.on_event("notify_klippy_disconnected", [])
                            continue
                        if msg.get("id") == sub_id and isinstance(msg.get("result"), dict):
                            delay = self.backoff[0]
                            self.on_status(dict(msg["result"].get("status") or {}))
                            self.connected = True          # after the snapshot is applied
                            if self.on_connect is not None:
                                try:
                                    self.on_connect()
                                except Exception:  # noqa: BLE001 - a callback bug must not drop the socket
                                    log.exception("moonraker %s: on_connect failed", self.client.host)
                            continue
                        method = msg.get("method")
                        params = msg.get("params") or []
                        if method == "notify_status_update" and params and isinstance(params[0], dict):
                            self.on_status(params[0])
                        elif method in EVENTS:
                            self.on_event(method, params)
                            if method == "notify_klippy_ready":
                                sub_id = self._subscribe(ws)
            except Exception as e:  # noqa: BLE001 - any failure: reconnect after a pause
                if not self._stop.is_set():
                    log.info("moonraker %s: websocket %s; retry in %.0f s", self.client.host,
                             type(e).__name__, delay)
            finally:
                self._ws = None
                self._later.clear()
                if self.connected:
                    self.down_since = time.monotonic()
                    self.drops += 1
                self.connected = False
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, self.backoff[1])
