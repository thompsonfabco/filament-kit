"""Devices with their kind, version and out-of-date sentence, a device's detail, and the Weigh Station's own page passed
through the Hub (R83 section 9, 10.2, 10.4). Under /setup/api:

    GET  devices                    {devices: [{id, name, kind, version?, newest?, out_of_date, advice?, paired?, last_seen?,
                                    reachable?, built_in, page}]}: the pairings and the Tag Reader tokens (kind "reader")
    GET  device/{id}                {device, status?, settings?}: a station's status and settings come from the station
    POST device/{id}/settings {code, <setting id>: <value>, ...}   one change; {reset: true} removes the station's own values

and, outside /setup/api, `passthrough_routes(page)`: /setup/device/{id}/ and everything under it is the station's own page.
The Hub calls the station (the Hub page's lock decides: looking needs nothing, a POST needs the code or a trusted
computer, as every change on this page) and gives the answer back under its own address, so the page must use relative
addresses only. The kind and version of a pairing come from the pairing record once it holds them (`kind`, `version`;
the client header of R83 section 9.2); until then a row has no kind, or "station" when it is a Weigh Station pairing.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import anyio
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from .. import __version__, config, pairing, reader_tokens, station_client
from .station_tab import page_address

KINDS = ("phone", "pc", "station", "web", "reader", "builtin")
CLIENT_KINDS = {"android": "phone", "slicer-sync": "pc", "weigh-station": "station", "web": "web"}   # the header's names
ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
PATH = re.compile(r"[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*/?")        # a station path: no dots-only segment, no empty one
QUERY = re.compile(r"[A-Za-z0-9._~%&=+,-]{0,200}")
SETTING_ID = re.compile(r"[a-z][a-z0-9_.]{0,40}")
MAX_SETTINGS = 40
MAX_ANSWER = 8 * 1024 * 1024        # the station's photo is the biggest thing it serves
STATION_TIMEOUT = 5
# the page is the station's, run under the Hub's address: its own files and the Hub's only
PAGE_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
PAGE_TYPES = ("text/html", "text/css", "text/plain", "application/json", "application/javascript", "text/javascript",
              "image/png", "image/jpeg", "image/svg+xml", "image/x-icon", "font/woff2", "image/webp", "image/gif")


class StationError(Exception):
    """The Hub could not get an answer from the station: `status` is what the Hub page says (502, 503...)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---------- what the Hub offers (out of date is a comparison with these) ----------
def _numbers(text) -> tuple[int, ...] | None:
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def _phone_offer() -> str | None:
    try:
        return (config.paths().opt / "app" / "version.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _reader_offer() -> str | None:
    from .. import reader_flash
    got = reader_flash.bundled_image()
    return str(got[1]) if got else None


def _offer(kind: str) -> str | None:
    return {"station": __version__, "pc": __version__, "phone": _phone_offer(), "reader": _reader_offer()}.get(kind)


def _advice(kind: str, version: str, newest: str) -> str:
    """The row's out-of-date sentence (R83 section 9.4); the page words it from the same fields."""
    return {"station": f"Out of date ({version}; the Hub is {newest}). On that machine: sudo spoolwarden update",
            "pc": f"Out of date ({version}). Install the current Slicer Sync on that PC.",
            "phone": "Out of date. The app offers the update when it is opened.",
            "reader": "Out of date. Hold the knob for 4 seconds to update."}[kind]


def _judge(kind: str | None, version) -> dict:
    """{version?, newest?, out_of_date, advice?}: a version that is not known is never out of date."""
    out: dict = {"out_of_date": False}
    have = str(version).strip() if version not in (None, "") else None
    if have:
        out["version"] = have
    newest = _offer(kind) if kind else None
    if newest:
        out["newest"] = newest
    a, b = _numbers(have), _numbers(newest)
    if have and newest and a is not None and b is not None and a < b:
        out["out_of_date"] = True
        out["advice"] = _advice(kind, have, newest)
    return out


# ---------- the sources, one place each so a test can stand in for them ----------
def _pairings() -> list[dict]:
    return pairing.devices()


def _readers() -> list[dict]:
    return reader_tokens.TokenStore().list()


def _station_url(cfg: dict) -> str | None:
    return (cfg.get("station") or {}).get("url")


def _kind_of(d: dict, built_in: bool) -> str | None:
    if built_in:
        return "builtin"
    k = d.get("kind")
    k = CLIENT_KINDS.get(k, k)
    if k in KINDS and k not in ("reader", "builtin"):
        return k
    return "station" if d.get("type") == "station" else None


def rows() -> list[dict]:
    """The Devices list: every pairing, then every Tag Reader token."""
    from ..setup_page import BUILT_IN_DEVICES, _fmt_time
    cfg = config.load()
    devs = _pairings()
    reach = station_client.station_reach(devs, _station_url(cfg))
    out = []
    for d in devs:
        built_in = d["name"] in BUILT_IN_DEVICES
        kind = _kind_of(d, built_in)
        row = {"id": d["id"], "name": d["name"], "kind": kind, **_judge(kind, d.get("version")),
               "paired": _fmt_time(d.get("paired")), "last_seen": _fmt_time(d.get("last_seen")),
               "built_in": built_in, "page": kind == "station"}
        if d["id"] in reach:
            row["reachable"] = reach[d["id"]]
        out.append(row)
    for t in _readers():
        made = str(t.get("created") or "").replace("T", " ")[:16]
        out.append({"id": "reader-" + str(t["id"]), "name": t["name"], "kind": "reader", **_judge("reader", t.get("build")),
                    "paired": made or None, "last_seen": _fmt_time(t.get("last_seen")), "built_in": False, "page": False})
    return out


# ---------- the station ----------
def call_station(url: str, method: str, path: str, query: str = "", body: bytes | None = None,
                 headers: dict | None = None) -> tuple[int, str, bytes]:
    """(status, content type, body) of one call to the station's own listener. The Hub's pinned HTTPS client (station_client,
    R83 step EV3) takes this one's place; the page routes and the tests go through this name only."""
    target = url.rstrip("/") + "/" + path.lstrip("/") + ("?" + query if query else "")
    req = urllib.request.Request(target, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=STATION_TIMEOUT) as r:
            status, kind, data = r.status, r.headers.get("Content-Type", ""), r.read(MAX_ANSWER + 1)
    except urllib.error.HTTPError as e:
        status, kind, data = e.code, e.headers.get("Content-Type", ""), e.read(MAX_ANSWER + 1)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise StationError(502, f"the Weigh Station does not answer ({type(e).__name__})") from None
    if len(data) > MAX_ANSWER:
        raise StationError(502, "the Weigh Station's answer is too large")
    return status, kind, data


def _station_for(device_id: str) -> str:
    """The address of the station behind a device row; the Hub knows one station address, so the pairing must be the one
    station pairing (as `station_reach` has it)."""
    from ..setup_page import Refused
    devs = _pairings()
    stations = [d for d in devs if _kind_of(d, False) == "station"]
    if not any(d["id"] == device_id for d in stations):
        raise Refused(404, "no such Weigh Station")
    url = _station_url(config.load())
    if len(stations) != 1 or not url:
        raise Refused(503, "the Hub does not know this Weigh Station's address")
    return url


def _station_json(url: str, method: str, path: str, body: dict | None = None) -> dict:
    from ..setup_page import Refused
    raw = None if body is None else json.dumps(body).encode()
    try:
        status, _, data = call_station(url, method, path, "", raw, {"Content-Type": "application/json"} if raw else {})
    except StationError as e:
        raise Refused(e.status, e.message) from None
    try:
        out = json.loads(data or b"{}")
    except ValueError:
        out = None
    if not 200 <= status < 300 or not isinstance(out, dict):
        raise Refused(502 if status < 400 or status >= 500 else status,
                      (out or {}).get("error") if isinstance(out, dict) and out.get("error") else f"the Weigh Station answered {status}")
    return out


# ---------- routes ----------
def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    async def listing(request, body):
        return {"devices": await anyio.to_thread.run_sync(rows)}

    def find(device_id: str) -> dict:
        row = next((r for r in rows() if r["id"] == device_id), None)
        if row is None:
            raise Refused(404, "no such device")
        return row

    def detail(device_id: str) -> dict:
        row = find(device_id)
        out: dict = {"device": row}
        if row["page"]:
            url = _station_for(device_id)
            for key, path in (("status", "state"), ("settings", "settings")):
                try:
                    got = _station_json(url, "GET", path)
                except Refused:
                    out["device"] = {**row, "reachable": False}
                    break
                out[key] = got if key == "status" else got.get("settings", [])
        return out

    async def one(request, body):
        return await anyio.to_thread.run_sync(detail, request.path_params["id"])

    def change(device_id: str, body: dict) -> dict:
        row = find(device_id)
        if not row["page"]:
            raise Refused(404, "this device has no settings")
        values = {k: v for k, v in body.items() if k != "code"}
        if values.get("reset") is True and len(values) == 1:
            sent = {"reset": True}
        else:
            if not values or len(values) > MAX_SETTINGS:
                raise Refused(400, "no settings to change")
            for k, v in values.items():
                if not SETTING_ID.fullmatch(k) or isinstance(v, (dict, list)) or v is None:
                    raise Refused(400, f"{k[:40]} is not a setting this page can change")
            sent = values
        got = _station_json(_station_for(device_id), "POST", "settings", sent)
        return {"settings": got.get("settings", [])}

    async def settings(request, body):
        device_id = request.path_params["id"]
        out = await anyio.to_thread.run_sync(change, device_id, body)
        page.audit(request, f"Weigh Station {device_id} settings changed")
        return out

    return [("/devices", page.guard(listing), "GET"), ("/device/{id}", page.guard(one), "GET"),
            ("/device/{id}/settings", page.guard(settings, write=True), "POST")]


def passthrough_routes(page) -> list[Route]:
    """The station's page under /setup/device/{id}/ (the registry mounts these beside the page's own routes)."""
    from ..setup_page import Refused

    def fetch(device_id: str, method: str, sub: str, query: str, body: dict) -> Response:
        if not ID.fullmatch(device_id):
            raise Refused(404, "no such Weigh Station")
        url = _station_for(device_id)
        if sub and (not PATH.fullmatch(sub) or any(p in (".", "..") for p in sub.split("/"))):
            raise Refused(404, "no such page")
        if not QUERY.fullmatch(query):
            raise Refused(400, "bad query")
        sent = None
        if method == "POST":
            sent = json.dumps({k: v for k, v in body.items() if k != "code"}).encode()      # the Hub's code stays here
        try:
            status, kind, data = call_station(url, method, sub, query, sent, {"Content-Type": "application/json"} if sent else {})
        except StationError as e:
            raise Refused(e.status, e.message) from None
        base = kind.split(";")[0].strip().lower()
        resp = Response(data, status, media_type=base if base in PAGE_TYPES else "application/octet-stream")
        resp.headers["Content-Security-Policy"] = PAGE_POLICY
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    def handler(method: str):
        async def route(request, body):
            return await anyio.to_thread.run_sync(
                fetch, request.path_params["id"], method, request.path_params.get("path", ""), request.url.query, body)
        return route

    async def slash(request, body):
        # the page's relative addresses need the trailing slash
        return RedirectResponse(page_address(request.path_params["id"]), 308)

    g, w = page.guard, lambda fn: page.guard(fn, write=True)  # noqa: E731
    return [Route("/setup/device/{id}", g(slash), methods=["GET"]),
            Route("/setup/device/{id}/", g(handler("GET")), methods=["GET"]),
            Route("/setup/device/{id}/", w(handler("POST")), methods=["POST"]),
            Route("/setup/device/{id}/{path:path}", g(handler("GET")), methods=["GET"]),
            Route("/setup/device/{id}/{path:path}", w(handler("POST")), methods=["POST"])]
