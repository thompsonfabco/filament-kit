"""Devices with their kind, version and out-of-date sentence, and a device's detail the Hub page draws itself (R83 section 9,
10.2 and the rulings of 2026-11-17 21:18 and 21:22). Under /setup/api:

    GET  devices                    {devices: [{id, name, kind, version?, newest?, out_of_date, advice?, paired?, last_seen?,
                                    reachable?, built_in, page}]}: the pairings and the Tag Reader tokens (kind "reader")
    GET  device/{id}                {device, status?, settings?, settings_dropped?, own_page?, photo}: a station's status and
                                    settings come from the station as checked data
    GET  device/{id}/photo          the station's photo, only image/jpeg of at most 4 MiB
    POST device/{id}/settings {code, <setting id>: <value>, ...}   one change; {reset: true} removes the station's own values
    POST device/{id}/open {code}    {address: "<own_page>#ticket=<ticket>"}: a one-time ticket from the station (POST /ticket)

The Hub never serves a device's HTML, script or style. What it takes from a station is data: JSON only, at most 256 KiB, 5
seconds, a redirect is an error, only the address stored for that pairing. Every text from a station reaches the page as text.
The kind and version of a pairing come from the pairing record once it holds them (`kind`, `version`; the client header of
R83 section 9.2); until then a row has no kind, or "station" when it is a Weigh Station pairing.

The station's side (EV3): GET /state (with `photo: true` when it has one), GET /settings, POST /settings, GET /photo, and
POST /ticket -> {ticket, expires_in: 60}; the station's page hands the ticket to its own POST /session. The Hub's proof
for POST /settings and POST /ticket is `_proof_headers` (EV3's pinned client gives it).
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import threading
import time
import urllib.parse

import anyio
from starlette.responses import Response

from .. import __version__, config, pairing, reader_tokens, station_client

KINDS = ("phone", "pc", "station", "web", "reader", "builtin")
CLIENT_KINDS = {"android": "phone", "slicer-sync": "pc", "weigh-station": "station", "web": "web"}   # the header's names
SETTING_ID = re.compile(r"[a-z0-9_.-]{1,40}")
SETTING_KINDS = ("switch", "choice", "number", "text")
TICKET = re.compile(r"[A-Za-z0-9_-]{16,128}")
MAX_SETTINGS = 60
MAX_LABEL = 80
MAX_TEXT = 200
MAX_JSON = 256 * 1024
MAX_PHOTO = 4 * 1024 * 1024
STATION_TIMEOUT = 5
OPEN_SCHEMES = ("https",)           # the station's own page is opened only over https
DROPPED_NOTE = "Some of this station's settings could not be shown."


class StationError(Exception):
    """The Hub could not get a checked answer from the station: `status` is what the Hub page says (502, 503...)."""

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


# ---------- the station: data only, checked ----------
def _proof_headers() -> dict:
    """The proof the station wants for a change or a ticket (R83 section 13 item 3); EV3's pinned client gives it."""
    return {}


def call_station(url: str, method: str, path: str, body: bytes | None = None, cap: int = MAX_JSON) -> tuple[int, str, bytes]:
    """(status, content type, body) of one call to the stored address of the station, at a fixed `path`. The whole call
    (connect, headers, body) has ONE deadline of STATION_TIMEOUT seconds: a station that trickles its answer is cut off, the
    socket is shut at the deadline. A redirect (any 3xx), a slow answer or one larger than `cap` is a StationError. It
    is plain http.client, so no proxy of the environment is ever used and nothing is followed. The pinned certificate comes
    with EV3's client, which takes this one's place; the page routes and the tests go through this name only."""
    u = urllib.parse.urlsplit(url)
    secure = u.scheme == "https"
    conn = (http.client.HTTPSConnection if secure else http.client.HTTPConnection)(u.hostname, u.port, timeout=STATION_TIMEOUT)
    deadline = time.monotonic() + STATION_TIMEOUT

    def cut():
        sock = conn.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        conn.close()

    timer = threading.Timer(STATION_TIMEOUT, cut)
    timer.daemon = True
    timer.start()
    headers = {"Accept": "*/*", **_proof_headers(), **({"Content-Type": "application/json"} if body is not None else {})}
    try:
        conn.request(method, u.path.rstrip("/") + "/" + path, body=body, headers=headers)
        resp = conn.getresponse()
        status, kind = resp.status, resp.getheader("Content-Type", "") or ""
        if 300 <= status < 400:
            raise StationError(502, "the Weigh Station answered with a redirect")
        data = bytearray()
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            data += chunk
            if len(data) > cap:
                raise StationError(502, "the Weigh Station's answer is too large")
            if time.monotonic() > deadline:
                raise StationError(502, "the Weigh Station answers too slowly")
    except StationError:
        raise
    except (http.client.HTTPException, OSError, ValueError) as e:
        slow = time.monotonic() >= deadline - 0.05
        raise StationError(502, "the Weigh Station answers too slowly" if slow else f"the Weigh Station does not answer ({type(e).__name__})") from None
    finally:
        timer.cancel()
        conn.close()
    if time.monotonic() > deadline:
        raise StationError(502, "the Weigh Station answers too slowly")
    return status, kind, bytes(data)


def _station_for(device_id: str) -> str:
    """The stored address of the station behind a device row; the Hub knows one station address, so the pairing must be the
    one station pairing (as `station_reach` has it)."""
    from ..setup_page import Refused
    devs = _pairings()
    stations = [d for d in devs if _kind_of(d, False) == "station"]
    if not any(d["id"] == device_id for d in stations):
        raise Refused(404, "no such Weigh Station")
    url = _station_url(config.load())
    if len(stations) != 1 or not _origin(url):
        raise Refused(503, "the Hub does not know this Weigh Station's address")
    return url


def _origin(url) -> str | None:
    """scheme://host[:port] of a stored address, or None when it is not an http(s) address with a host."""
    try:
        u = urllib.parse.urlsplit(str(url or ""))
        return f"{u.scheme}://{u.netloc}" if u.scheme in ("http", "https") and u.hostname and not u.username else None
    except ValueError:
        return None


def own_page(url) -> str | None:
    o = _origin(url)
    return o + "/" if o else None


def _station_json(url: str, method: str, path: str, body: dict | None = None) -> dict:
    from ..setup_page import Refused
    raw = None if body is None else json.dumps(body).encode()
    try:
        status, kind, data = call_station(url, method, path, raw)
    except StationError as e:
        raise Refused(e.status, e.message) from None
    if kind.split(";")[0].strip().lower() != "application/json":
        raise Refused(502, "the Weigh Station did not answer with JSON")
    try:
        out = json.loads(data or b"{}")
    except ValueError:
        out = None
    if not isinstance(out, dict):
        raise Refused(502, "the Weigh Station's answer is not valid")
    if not 200 <= status < 300:
        err = out.get("error")
        raise Refused(502 if status >= 500 else status if status in (400, 403, 404) else 502,
                      str(err)[:MAX_TEXT] if isinstance(err, str) and err else f"the Weigh Station answered {status}")
    return out


def _text(v, limit: int = MAX_TEXT) -> str | None:
    return v if isinstance(v, str) and len(v) <= limit else None


def clean_settings(raw) -> tuple[list[dict], bool]:
    """(the settings that pass the checks, whether any was dropped): `id` [a-z0-9_.-]{1,40}, `kind` one of four, `label` at
    most 80 characters, at most 60 settings, a value of the kind's own type."""
    if not isinstance(raw, list):
        return [], bool(raw)
    out, seen, dropped = [], set(), len(raw) > MAX_SETTINGS
    for s in raw[:MAX_SETTINGS]:
        item = _clean_setting(s) if isinstance(s, dict) else None
        if item is None or item["id"] in seen:
            dropped = True
            continue
        seen.add(item["id"])
        out.append(item)
    return out, dropped


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e12


def _clean_setting(s: dict) -> dict | None:
    sid, kind, label, value = s.get("id"), s.get("kind"), _text(s.get("label"), MAX_LABEL), s.get("value")
    if not (isinstance(sid, str) and SETTING_ID.fullmatch(sid)) or kind not in SETTING_KINDS or not label:
        return None
    out = {"id": sid, "label": label, "kind": kind}
    if kind == "switch":
        if not isinstance(value, bool):
            return None
    elif kind == "number":
        if not _number(value):
            return None
        for k in ("min", "max"):
            if _number(s.get(k)):
                out[k] = s[k]
    elif kind == "text":
        if _text(value) is None:
            return None
    else:
        if not (_text(value) is not None or _number(value)):
            return None
        choices = []
        for c in (s.get("choices") if isinstance(s.get("choices"), list) else [])[:40]:
            v, lab = (c.get("value"), c.get("label")) if isinstance(c, dict) else (c, c)
            if _text(v, MAX_LABEL) is None or _text(lab, MAX_LABEL) is None:
                return None
            choices.append(v if not isinstance(c, dict) else {"value": v, "label": lab})
        out["choices"] = choices
    out["value"] = value
    return out


def clean_status(v, depth: int = 0):
    """The station's status as plain data: nested at most three deep, at most 60 entries a level, texts of at most 200
    characters; anything else becomes nothing."""
    if isinstance(v, dict) and depth < 3:
        return {k[:40]: clean_status(x, depth + 1) for k, x in list(v.items())[:60] if isinstance(k, str) and k.strip()}
    if isinstance(v, list) and depth < 3:
        return [clean_status(x, depth + 1) for x in v[:60]]
    if isinstance(v, str):
        return v[:MAX_TEXT]
    return v if isinstance(v, bool) or _number(v) else None


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
        out: dict = {"device": row, "photo": False}
        if row["page"]:
            url = _station_for(device_id)
            out["own_page"] = own_page(url)
            try:
                status = _station_json(url, "GET", "state")
                got = _station_json(url, "GET", "settings")
            except Refused:
                out["device"] = {**row, "reachable": False}
                return out
            out["status"] = clean_status(status)
            out["photo"] = status.get("photo") is True
            out["settings"], dropped = clean_settings(got.get("settings"))
            if dropped:
                out["settings_dropped"] = True
        return out

    async def one(request, body):
        return await anyio.to_thread.run_sync(detail, request.path_params["id"])

    def photo(device_id: str) -> Response:
        if not find(device_id)["page"]:
            raise Refused(404, "no photo")
        url = _station_for(device_id)
        try:
            status, kind, data = call_station(url, "GET", "photo", None, MAX_PHOTO)
        except StationError as e:
            raise Refused(e.status, e.message) from None
        if status != 200 or kind.split(";")[0].strip().lower() != "image/jpeg" or not data.startswith(b"\xff\xd8"):
            raise Refused(502, "the Weigh Station's photo is not a JPEG picture")
        return Response(data, 200, media_type="image/jpeg",
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})

    async def photo_route(request, body):
        return await anyio.to_thread.run_sync(photo, request.path_params["id"])

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
        settings, dropped = clean_settings(got.get("settings"))
        return {"settings": settings, **({"settings_dropped": True} if dropped else {})}

    async def settings(request, body):
        device_id = request.path_params["id"]
        out = await anyio.to_thread.run_sync(change, device_id, body)
        page.audit(request, f"Weigh Station {device_id} settings changed")
        return out

    def open_page(device_id: str) -> dict:
        """The address that opens the station's own page for this browser: its one-time ticket after the `#`."""
        if not find(device_id)["page"]:
            raise Refused(404, "this device has no page of its own")
        url = _station_for(device_id)
        base = own_page(url)
        if not base or urllib.parse.urlsplit(base).scheme not in OPEN_SCHEMES:
            raise Refused(409, "the Weigh Station's own page is opened over https only")
        if _origin(base) != _origin(url):
            raise Refused(502, "the Weigh Station's ticket is not valid")
        got = _station_json(url, "POST", "ticket", {})
        ticket = got.get("ticket")
        if not (isinstance(ticket, str) and TICKET.fullmatch(ticket)) or got.get("expires_in") != 60 or isinstance(got.get("expires_in"), bool):
            raise Refused(502, "the Weigh Station's ticket is not valid")
        address = f"{base}#ticket={ticket}"
        if _origin(address) != _origin(base):
            raise Refused(502, "the Weigh Station's ticket is not valid")
        return {"address": address}

    async def open_route(request, body):
        device_id = request.path_params["id"]
        out = await anyio.to_thread.run_sync(open_page, device_id)
        page.audit(request, f"Weigh Station {device_id} page opened")        # no ticket in the log
        return out

    return [("/devices", page.guard(listing), "GET"), ("/device/{id}", page.guard(one), "GET"),
            ("/device/{id}/photo", page.guard(photo_route), "GET"),
            ("/device/{id}/settings", page.guard(settings, write=True), "POST"),
            ("/device/{id}/open", page.guard(open_route, write=True), "POST")]
