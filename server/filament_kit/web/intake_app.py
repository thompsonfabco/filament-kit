"""Phone web intake app (PWA) of the `web` process: add spools by hand or (with ai_intake) from label photos, open a
tapped spool, preset lines.

A port of filament-ops vm/intake.py and intake_static/ (same routes under `<public path>/intake`, same three-tab
page), on the kit's own functions: label reads go through `intake.read_labels` with the reader context
(`intake.read_context`) and the shared daily cap (`ReadCap`, the kit server's own file), writes through the
same `Tools` as the MCP tools, so the rules (dry run first, sealed defaults, tag checks) are the same.

Served twice (the user's decision, 2026-11-09: the phone page is part of the main software): by the kit server
itself at https://<server>:8710/intake on the home network, whatever modules are on, and by the web unit at
<public_url>/intake when the web module is on. Home network only (in the web unit `auth.lan_only` wraps the whole
app; in the kit server every route checks the address and the setup page's Host rule); there is no sign-in (the
owner's choice: the home network is the gate, as in filament-ops). Every POST must carry the app's own Origin.
The page's CSP allows only its own script and style; the script never puts server data into innerHTML.
"""
from __future__ import annotations

import html
import json
import logging
import math
import struct
import zlib
from pathlib import Path
from urllib.parse import urlparse

import anyio
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .. import intake, inventory, lan, modules, tagsources
from ..intake import CapReached, ReadError
from ..station_client import StationClient
from . import mcp_tools, printers_app
from .errors import Problem
from .mcp_tools import SpoolItem, Tools

log = logging.getLogger(__name__)

MAX_HINT = 2000
STATIC = Path(__file__).parent / "static"

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
                               "connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; form-action 'self'; "
                               "base-uri 'none'",
    "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"}
HOME_ONLY = "<main><p>Spool intake only works on the home network.</p></main>"


def icon_png(size: int = 180) -> bytes:
    """Home-screen icon: a filament spool (rings) drawn without image libraries."""
    rows, c = [], (size - 1) / 2
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5 / c
            if d > 0.86 or d < 0.2:
                px = (24, 28, 36)
            elif d > 0.78 or d < 0.3:
                px = (210, 214, 222)  # flanges and hub
            else:
                px = (46, 140, 214) if int(d * 40) % 2 else (58, 156, 230)  # windings
            row += bytes(px)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def _num(b: dict, key: str) -> float | None:
    """An optional number field (the phone sends the input's text): blank is None; NaN/infinity are refused."""
    v = b.get(key)
    if v in (None, ""):
        return None
    try:
        if isinstance(v, bool):
            raise ValueError
        n = float(v)
    except (TypeError, ValueError):
        raise Problem(f"{key} must be a number") from None
    if not math.isfinite(n):
        raise Problem(f"{key} must be a number")
    return n


def _ids(b: dict) -> list[int]:
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise Problem("ids must be a list of Spoolman filament ids")
    return ids


def _text(b: dict, key: str, *, required: bool = True) -> str:
    v = b.get(key)
    if v is None and not required:
        return ""
    if not isinstance(v, str) or (required and not v.strip()):
        raise Problem(f"{key} must be text")
    return v.strip()


class KitCap:
    """The kit server's daily label-read cap, taken and refunded through its API: the web unit may not write the
    kit's reads.json (no kit file is writable by its user). A 429 from the kit is the cap reached. One read per KitCap: `take` keeps the
    kit's single-use ticket, and `refund` gives back that read only (the kit refuses any other refund)."""

    def __init__(self, kit):
        self.kit, self.ticket = kit, None

    def take(self) -> None:
        from .slots import SlotError
        try:
            self.ticket = self.kit.post("/api/intake/cap/take", {}).get("ticket")
        except SlotError as e:
            if e.code == "daily_cap" or e.http == 429:
                raise CapReached(str(e)) from None
            raise

    def refund(self) -> None:
        ticket, self.ticket = self.ticket, None
        if ticket:
            self.kit.post("/api/intake/cap/refund", {"ticket": ticket})


class IntakeApp:
    def __init__(self, tools: Tools, *, public_url: str | None, lan_cidrs, claude=None, kit_api=None, host_ok=None,
                 push: bool = True, host_refusal=None):
        """`public_url`: the web unit's address (its Origin is the only one a POST may carry); None in the kit server,
        where the page is opened by the server's own names and a POST carries that same page's Origin. `host_ok`
        (the kit server): the setup page's Host rule, checked with the address on every route. `push`: the Printers
        tab's alerts (only one process sends them: the web unit)."""
        self.tools, self.claude = tools, claude
        # the intake history lives in the kit server's state: only the page the kit server serves itself (no public
        # URL: home network, this process) records and shows it; the web module's page is another process and user
        self.history = public_url is None
        self.nets = lan.parse_lan(lan_cidrs)
        u = urlparse(public_url) if public_url else None
        self.origin = f"{u.scheme}://{u.netloc}" if u else None
        self.base = (u.path.rstrip("/") if u else "") + "/intake"  # as the browser sees it (nginx strips it)
        self.host_ok = host_ok
        self.host_refusal = host_refusal    # the kit server: the setup page's refusal text (its names, the Settings fix)
        self.static = {n: (STATIC / n).read_bytes() for n in ("app.js", "app.css", "printers.js")}
        self.icon = icon_png()
        self.tag_cache: dict = {}
        self.station: list = [None, None]  # [url, StationClient]
        cfg = tools.cfg()
        self._kit = kit_api         # the kit server's API (slots.KitApi), made when first needed
        self.printers = None        # the Printers tab: only with the printers module on
        if "printers" in modules.enabled(cfg):
            self.printers = printers_app.PrintersApp(
                self, kit_api, push_on=push and (cfg.get("web") or {}).get("push") is True)

    @property
    def kit(self):
        if self._kit is None:
            from .slots import KitApi
            self._kit = KitApi()
        return self._kit

    def routes(self) -> list[Route]:
        rs = self._routes()
        if self.host_ok is None:
            return rs
        return [Route(r.path, self._guarded(r.endpoint), methods=sorted(r.methods - {"HEAD"})) for r in rs]

    def _guarded(self, fn):
        """The kit server: every route (the page, its assets and its API) answers the home network only, by the
        server's own names (setup_page.host_ok), as the web unit's outer wrapper does there."""
        async def route(request: Request):
            if not self._lan(request):
                return JSONResponse({"error": "home network only"}, 403)
            if not self.host_ok(request):
                text = self.host_refusal() if self.host_refusal else "open this page by the server's own name or address"
                return JSONResponse({"error": text}, 403)
            return await fn(request)
        return route

    def _origin_ok(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if self.origin:
            return origin == self.origin
        return bool(origin) and origin == f"https://{request.headers.get('host', '')}"

    def _routes(self) -> list[Route]:
        return [Route(p, fn, methods=m) for p, fn, m in (
            ("/intake", self.page, ["GET"]), ("/intake/app.js", self.asset, ["GET"]),
            ("/intake/app.css", self.asset, ["GET"]), ("/intake/printers.js", self.asset, ["GET"]),
            ("/intake/icon.png", self.icon_route, ["GET"]),
            ("/intake/manifest.webmanifest", self.manifest, ["GET"]),
            ("/intake/api/read", self.api(self.read), ["POST"]), ("/intake/api/add", self.api(self.add), ["POST"]),
            ("/intake/api/tag", self.api(self.tag), ["GET"]), ("/intake/api/find", self.api(self.find), ["GET"]),
            ("/intake/api/filaments", self.api(self.filaments), ["GET"]),
            ("/intake/api/vendors", self.api(self.vendors), ["GET"]),
            ("/intake/api/open", self.api(self.open), ["POST"]),
            ("/intake/api/presets", self.api(self.presets), ["GET"]),
            ("/intake/api/parents", self.api(self.parents), ["GET"]),
            ("/intake/api/line_add", self.api(self.line_add), ["POST"]),
            ("/intake/api/line_new", self.api(self.line_new), ["POST"]),
            ("/intake/api/generate", self.api(self.generate), ["POST"]))] + (
                self.printers.routes() if self.printers else []) + (self._history_routes() if self.history else [])

    # ---------- the intake history (intake_history.py; the kit's own page only, see __init__) ----------
    def _history_routes(self) -> list[Route]:
        return [Route(p, self.api(self._hist(fn)), methods=m) for p, fn, m in (
            ("/intake/api/history", self.history_list, ["GET"]),
            ("/intake/api/history/{hid}", self.history_get, ["GET"]),
            ("/intake/api/history/{hid}/photos/{n:int}", self.history_photo, ["GET"]),
            ("/intake/api/history/{hid}/revise", self.history_revise, ["POST"]),
            ("/intake/api/history/{hid}/apply", self.history_apply, ["POST"]),
            ("/intake/api/history/{hid}/undo", self.history_undo, ["POST"]))]

    @staticmethod
    def _hist(fn):
        from .. import intake_history

        async def route(request: Request):
            try:
                return await fn(request)
            except intake_history.HistoryError as e:
                return JSONResponse({"error": str(e), "code": e.code}, e.status)
        return route

    def _ai(self) -> bool:
        return "ai_intake" in modules.enabled(self.tools.cfg())

    async def history_list(self, request: Request):
        from .. import intake_history
        return await anyio.to_thread.run_sync(intake_history.list_records, self._ai())

    async def history_get(self, request: Request):
        from .. import intake_history
        return await anyio.to_thread.run_sync(intake_history.get, request.path_params["hid"])

    async def history_photo(self, request: Request):
        from .. import intake_history
        data = await anyio.to_thread.run_sync(intake_history.photo, request.path_params["hid"], request.path_params["n"])
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})

    async def history_revise(self, request: Request):
        from .. import intake_history
        body = await self._body(request)

        def run() -> dict:
            if not self._ai():
                raise intake_history.HistoryError(409, "ai_off", "label reading (the ai_intake module) is off on this "
                                                                 "server: edit the values by hand")
            cap = KitCap(self.kit)              # a revision is a read: the kit's daily cap
            cap.take()
            try:
                return intake_history.revise(self.tools.sm, request.path_params["hid"], body.get("note"),
                                             body.get("item"), client=self.claude)
            except Exception:
                try:
                    cap.refund()
                except Exception as e:  # noqa: BLE001 - best effort
                    log.warning("cap refund failed: %s", e)
                raise
        return await anyio.to_thread.run_sync(run)

    async def history_apply(self, request: Request):
        from .. import intake_history
        b = await self._body(request)
        if b.get("proposal") is not None and not isinstance(b.get("proposal"), str):
            raise intake_history.HistoryError(400, "bad_request", "proposal must be the id a revision gave")
        return await anyio.to_thread.run_sync(lambda: intake_history.apply(
            self.tools.sm, request.path_params["hid"], proposal=b.get("proposal"), item=b.get("item"),
            values=b.get("values") if b.get("proposal") is None else None, spool_ids=b.get("spool_ids"),
            device="phone web app"))

    async def history_undo(self, request: Request):
        from .. import intake_history
        b = await self._body(request)
        return await anyio.to_thread.run_sync(intake_history.undo, self.tools.sm, request.path_params["hid"],
                                              b.get("revision"))

    # ---------- home network ----------
    def _lan(self, request: Request) -> bool:
        return lan.is_lan(request.client.host if request.client else "", self.nets)

    def _html(self, body: str, status: int = 200, app: bool = False) -> HTMLResponse:
        b = html.escape(self.base, quote=True)
        return HTMLResponse(
            "<!doctype html><html lang=en><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
            "<meta name=apple-mobile-web-app-capable content=yes><meta name=apple-mobile-web-app-title content=Spools>"
            "<meta name=theme-color content='#181c24'><title>Spool intake</title>"
            f"<link rel=stylesheet href='{b}/app.css'><link rel=apple-touch-icon href='{b}/icon.png'>"
            f"<link rel=manifest href='{b}/manifest.webmanifest'>"
            + body + (("" if not self.printers else f"<script src='{b}/printers.js'></script>")
                      + f"<script src='{b}/app.js'></script>" if app else ""),
            status_code=status, headers=self.headers())

    def headers(self) -> dict:
        """The page headers. With the Printers tab the CSP also allows `media-src 'self'` (the HLS camera in a
        <video>); without it the CSP is exactly the intake app's."""
        h = dict(HEADERS)
        if self.printers:
            h["Content-Security-Policy"] = h["Content-Security-Policy"].replace(
                "connect-src 'self';", "connect-src 'self'; media-src 'self';")
        return h

    def _shell(self) -> str:
        cfg = self.tools.cfg()
        pl = cfg["placement"]
        data = {"base": self.base, "locations": json.dumps(cfg["locations"]),
                "sealed": pl.get("sealed_location") or "", "auto": mcp_tools._placement_text(cfg),
                "picks": json.dumps([pl.get("pla_location") or ""]),
                # label photos with either reader: Claude (ai_intake) or the local reader (local_intake)
                "ai": "1" if {"ai_intake", "local_intake"} & modules.enabled(cfg) else "0",
                "printers": "1" if self.printers else "0",
                "push": "1" if self.printers and self.printers.push_on else "0",
                "history": "1" if self.history else "0"}
        attrs = " ".join(f"data-{k}='{html.escape(v, quote=True)}'" for k, v in data.items())
        return f"<body {attrs}><main id=app></main></body>"

    async def page(self, request: Request):
        if not self._lan(request):
            client = request.client.host if request.client else ""
            hint = f"<main><p>{lan.IPV6_HINT}</p></main>" if lan.over_ipv6(client) else ""
            return self._html(HOME_ONLY + hint, 403)
        return self._html(await anyio.to_thread.run_sync(self._shell), app=True)

    async def asset(self, request: Request):
        name = request.url.path.rsplit("/", 1)[-1]
        return Response(self.static[name], media_type="text/javascript" if name.endswith(".js") else "text/css",
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    async def icon_route(self, request: Request):
        return Response(self.icon, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    async def manifest(self, request: Request):
        return JSONResponse({"name": "Spool intake", "short_name": "Spools", "start_url": self.base, "scope": self.base,
                             "display": "standalone", "background_color": "#181c24", "theme_color": "#181c24",
                             "icons": [{"src": self.base + "/icon.png", "sizes": "180x180", "type": "image/png"}]},
                            media_type="application/manifest+json")

    def api(self, fn):
        async def route(request: Request):
            if not self._lan(request):
                return JSONResponse({"error": "home network only"}, 403)
            if request.method == "POST" and not self._origin_ok(request):
                return JSONResponse({"error": "bad origin"}, 403)
            try:
                res = await fn(request)
                if isinstance(res, Response):      # a stream or a binary (the Printers tab's camera and events)
                    return res
                return JSONResponse(res, headers={"Cache-Control": "no-store"})
            except CapReached as e:
                return JSONResponse({"error": str(e)}, 429)
            except ReadError as e:
                return JSONResponse({"error": e.message, "read_id": e.read_id}, 502)
            except Exception as e:  # noqa: BLE001 - a refusal is shown on the phone; a crash is logged only
                text = mcp_tools.error_text(e)
                if text is None:
                    log.exception("intake %s", request.url.path)
                    return JSONResponse({"error": "internal error (see the server log)"}, 500)
                status = 409 if type(e).__name__ == "TagConflict" else 400
                return JSONResponse({"error": text}, status)
        return route

    async def _body(self, request: Request) -> dict:
        try:
            b = await request.json()
        except ValueError:
            raise Problem("the request body must be JSON") from None
        if not isinstance(b, dict):
            raise Problem("the request body must be a JSON object")
        return b

    def _station(self) -> StationClient | None:
        url = (self.tools.cfg().get("station") or {}).get("url")
        if not url:
            return None
        if self.station[0] != url:
            self.station[:] = [url, StationClient(url)]
        return self.station[1]

    def _orders(self) -> list[dict] | None:
        """The kit's order history for the prompt; a kit that cannot give it (down, or this unit unpaired) gives
        [] (the prompt says the history is unavailable) and the read goes on."""
        from .slots import SlotError
        try:
            return self.kit.get("/api/intake/orders").get("orders")
        except SlotError as e:
            log.warning("orders: the kit server did not give the order history: %s", e)
            return []

    # ---------- label photos -> items (Claude) ----------
    async def read(self, request: Request):
        if not {"ai_intake", "local_intake"} & modules.enabled(self.tools.cfg()):
            raise Problem("label reading (the ai_intake or local_intake module) is off on this server")
        async with request.form(max_files=intake.MAX_PHOTOS, max_fields=10) as form:
            photos = []
            for i, f in enumerate(form.getlist("photos")):
                if isinstance(f, UploadFile):
                    photos.append((f.filename or f"photo{i}", await f.read(intake.MAX_PHOTO_BYTES + 1)))
            hint = form.get("hint") or ""
        images = intake.check_photos(photos)
        hint = (hint if isinstance(hint, str) else "")[:MAX_HINT]

        def run() -> dict:
            cfg = self.tools.cfg()
            cap = KitCap(self.kit)                  # the kit's cap, through its API: only for a cloud read

            def charge():
                cap.take()
                return refund

            def refund():
                try:
                    cap.refund()
                except Exception as e:  # noqa: BLE001 - best effort
                    log.warning("cap refund failed: %s", e)
            ctx = intake.read_context(cfg, self.tools.sm, self._station(), orders_from=self._orders)
            return intake.read_labels(self.tools.sm, images, hint, None, self.claude, **ctx, charge=charge)
        return await anyio.to_thread.run_sync(run)

    # ---------- writes ----------
    async def add(self, request: Request):
        body = await self._body(request)
        items = []
        for raw in body.get("items") or []:
            if not isinstance(raw, dict):
                raise Problem("each item must be an object")
            it = {k: v for k, v in raw.items() if k in SpoolItem.model_fields and v not in ("", None)}
            if it.get("price_per_kg"):  # keep the read's order-based line unless the user changed the price
                ppk = float(it["price_per_kg"])
                if not str(it.get("price_line") or "").startswith(f"Price: ${ppk:g}/kg"):
                    it["price_line"] = f"Price: ${ppk:g}/kg - entered in the intake app"
            else:
                it.pop("price_line", None)
            try:
                items.append(mcp_tools.item_dict(SpoolItem.model_validate(it)))
            except ValidationError as e:
                err = e.errors()[0]
                where = ".".join(str(x) for x in err.get("loc", ()))
                raise Problem(f"{it.get('vendor')} {it.get('name')}: {where} {err.get('msg')}") from None
        if not items:
            raise Problem("no items")
        dry = bool(body.get("dry_run", True))
        single_opened = sum(it["count"] for it in items) == 1 and items[0].get("sealed") is False
        link = body.get("link_tag") if single_opened and isinstance(body.get("link_tag"), str) else None
        read_id = body.get("read_id") if isinstance(body.get("read_id"), str) else None

        def run() -> dict:
            out = self.tools.add_spools(items, dry, link, with_saved=True)
            saved = out.pop("saved", [])
            tag = out.pop("tag", None)
            if not out.get("dry") and self.history:     # the kit's own page: the kit's state is this process's
                from .. import intake_history
                hid = intake_history.record_save(saved, source="web", device="phone web app", read_id=read_id, tag=tag)
                if hid:
                    out["history_id"] = hid
            return out
        return await anyio.to_thread.run_sync(run)

    async def tag(self, request: Request):
        def run() -> dict:
            st = self._station()
            state = None
            if st is not None:
                try:
                    state = st.state()
                except Exception:  # noqa: BLE001 - a dead station only hides the scale
                    state = None
            t = tagsources.latest(self.tools.cfg()) or {}
            key = (t.get("nfc_id"), t.get("read_at_unix"))
            if self.tag_cache.get("key") != key:  # the Spoolman lookup only when a new tap arrives
                self.tag_cache = {"key": key, "text": self.tools.tag_state()["text"]}
            return {"nfc_id": t.get("nfc_id"), "read_at": t.get("read_at_unix"), "age_seconds": t.get("age_seconds"),
                    "reader": t.get("reader"), "text": self.tag_cache["text"],
                    "scale": tagsources.scale_weight(state)}
        return await anyio.to_thread.run_sync(run)

    async def find(self, request: Request):
        q = request.query_params
        return await anyio.to_thread.run_sync(self.tools.find_spools, q.get("q", ""), q.get("sealed") == "1", None)

    async def filaments(self, request: Request):  # the manual add's existing-filament picker
        return {"filaments": await anyio.to_thread.run_sync(inventory.filaments, self.tools.sm,
                                                            request.query_params.get("q", ""))}

    async def vendors(self, request: Request):
        return {"vendors": await anyio.to_thread.run_sync(inventory.vendors, self.tools.sm)}

    async def open(self, request: Request):
        b = await self._body(request)
        if not isinstance(b.get("spool"), int) or isinstance(b.get("spool"), bool):
            raise Problem("spool must be a spool id")
        loc = b.get("location")
        kw = dict(spool=b["spool"], location=loc if isinstance(loc, str) and loc.strip() else None,
                  gross=_num(b, "gross"), humidity=_num(b, "humidity"), dry_run=bool(b.get("dry_run", True)))
        return await anyio.to_thread.run_sync(lambda: self.tools.open_spool(**kw))

    async def presets(self, request: Request):
        return await anyio.to_thread.run_sync(self.tools.preset_status)

    async def parents(self, request: Request):
        return await anyio.to_thread.run_sync(self.tools.find_parents, request.query_params.get("q", ""))

    async def line_add(self, request: Request):
        b = await self._body(request)
        line, ids = _text(b, "line"), _ids(b)
        return await anyio.to_thread.run_sync(self.tools.add_filaments_to_line, line, ids)

    async def line_new(self, request: Request):
        b = await self._body(request)
        args = (_text(b, "name"), _text(b, "vendor"), _ids(b), _text(b, "orca_parent", required=False),
                _text(b, "bs_template"))
        return await anyio.to_thread.run_sync(self.tools.add_line, *args)

    async def generate(self, request: Request):
        return await anyio.to_thread.run_sync(self.tools.generate)
