"""The station's read-only HTTP handler: GET /state, GET /last-tag and GET /photo (shapes in the package docstring;
the first two unchanged from filament-ops so filament-mcp keeps reading them), 404 for anything else, 403 for a
client not in `allow`."""
from __future__ import annotations

import datetime
import json
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler


def iso(t):
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds") if t else None


def age(t):
    return round(time.time() - t) if t else None


def make_handler(state_view: Callable[[], dict], allow: set[str]) -> type[BaseHTTPRequestHandler]:
    """A handler class over `state_view()`: a snapshot of the station state plus "panel" (the panel's port); "photo" is the JPEG bytes."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "intake-station"
        sys_version = ""

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.client_address[0] not in allow:
                return self._send(403, {"status": "error", "message": "forbidden"})
            s = state_view()
            held = s["held"] is not None  # weight taken (yellow): the scan and weight stay current until red / next scan
            tag = {"status": "ok", "nfc_id": s["tag"], "read_at": iso(s["tag_at"]), "read_at_unix": s["tag_at"],
                   "age_seconds": age(s["tag_at"]), "held": held}
            if self.path == "/last-tag":
                return self._send(200, tag)
            if self.path == "/state":
                sc = s["scale"]
                air = s["air"] if s["air"] and time.time() - s["air_at"] < 60 else None  # panel gone: no stale reading
                last = ({"grams": s["held"], "age_seconds": age(s["held_at"]), "held": True} if held else
                        {"grams": s["last"], "age_seconds": age(s["last_at"]), "held": False} if s["last"] else None)
                return self._send(200, {
                    "tag": tag,
                    "scale": dict(sc, stable=sc["status"] == "stable", age_seconds=age(s["scale_at"])) if sc else None,
                    "last_weight": last, "panel": s["panel"], "panel_version": s["panel_version"],
                    "air": dict(air, age_seconds=age(s["air_at"])) if air else None, "flow": s["flow"],
                    "photo": {"url": "/photo", "taken_at": iso(s["photo_at"]), "age_seconds": age(s["photo_at"])}
                    if s["photo"] else None})
            if self.path == "/photo" and s["photo"]:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(s["photo"])))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(s["photo"])
            self._send(404, {"status": "error", "message": "not found"})

        def log_message(self, fmt, *args):
            pass  # the phone app polls; one journal line per poll is noise

    return Handler
