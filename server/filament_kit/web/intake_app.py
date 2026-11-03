"""Phone web intake app (PWA) of the `web` process: add spools by hand or (with ai_intake) from label photos, open a
tapped spool, preset lines.

A port of filament-ops vm/intake.py and intake_static/ (same routes under `<public path>/intake`, same three-tab
page), on the kit's own functions: label reads go through `intake.read_labels` with the reader context
(`intake.read_context`) and the shared daily cap (`ReadCap`, the kit server's own file), writes through the
same `Tools` as the MCP tools, so the rules (dry run first, sealed defaults, tag checks) are the same.

Home network only (`auth.lan_only` wraps the whole app; every route checks again). Sign-in uses the connector's
passphrase and gives a 30-day session cookie `fi_session` (Secure, HttpOnly, SameSite=Strict, path = the app's
base path); wrong passphrases count in the same `Lockout` as /login. Every POST must carry the app's own Origin.
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
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .. import config, intake, inventory, modules, tagsources
from ..intake import CapReached, ReadCap, ReadError
from ..spoolman import SpoolmanError
from ..station_client import StationClient
from . import auth, mcp_tools, printers_app
from .errors import Problem
from .mcp_tools import SpoolItem, Tools

log = logging.getLogger(__name__)

COOKIE = "fi_session"
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


class IntakeApp:
    def __init__(self, tools: Tools, *, store: auth.Store, lockout: auth.Lockout, public_url: str,
                 lan_cidrs, passphrase_file: Path | str, claude=None, kit_api=None):
        self.tools, self.store, self.lockout, self.claude = tools, store, lockout, claude
        self.passphrase_file = passphrase_file
        self.nets = auth.parse_lan(lan_cidrs)
        self.origin = auth._origin(public_url)
        self.base = urlparse(public_url).path.rstrip("/") + "/intake"  # as the browser sees it (nginx strips it)
        self.static = {n: (STATIC / n).read_bytes() for n in ("app.js", "app.css", "printers.js")}
        self.icon = icon_png()
        self.tag_cache: dict = {}
        self.station: list = [None, None]  # [url, StationClient]
        cfg = tools.cfg()
        self.printers = None        # the Printers tab: only with the printers module on
        if "printers" in modules.enabled(cfg):
            self.printers = printers_app.PrintersApp(self, kit_api, push_on=(cfg.get("web") or {}).get("push") is True)

    def routes(self) -> list[Route]:
        return [Route(p, fn, methods=m) for p, fn, m in (
            ("/intake", self.page, ["GET"]), ("/intake/login", self.login, ["POST"]),
            ("/intake/logout", self.logout, ["POST"]), ("/intake/app.js", self.asset, ["GET"]),
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
                self.printers.routes() if self.printers else [])

    # ---------- session ----------
    def _lan(self, request: Request) -> bool:
        return auth.is_lan(request.client.host if request.client else "", self.nets)

    def _signed_in(self, request: Request) -> bool:
        return self.store.check_session(request.cookies.get(COOKIE))

    def _html(self, body: str, status: int = 200, signed_in: bool = False) -> HTMLResponse:
        b = html.escape(self.base, quote=True)
        return HTMLResponse(
            "<!doctype html><html lang=en><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
            "<meta name=apple-mobile-web-app-capable content=yes><meta name=apple-mobile-web-app-title content=Spools>"
            "<meta name=theme-color content='#181c24'><title>Spool intake</title>"
            f"<link rel=stylesheet href='{b}/app.css'><link rel=apple-touch-icon href='{b}/icon.png'>"
            f"<link rel=manifest href='{b}/manifest.webmanifest'>"
            + body + (("" if not self.printers else f"<script src='{b}/printers.js'></script>")
                      + f"<script src='{b}/app.js'></script>" if signed_in else ""),
            status_code=status, headers=HEADERS)

    def _shell(self) -> str:
        cfg = self.tools.cfg()
        pl = cfg["placement"]
        data = {"base": self.base, "locations": json.dumps(cfg["locations"]),
                "sealed": pl.get("sealed_location") or "", "auto": mcp_tools._placement_text(cfg),
                "picks": json.dumps([pl.get("pla_location") or ""]),
                "ai": "1" if "ai_intake" in modules.enabled(cfg) else "0",
                "printers": "1" if self.printers else "0",
                "push": "1" if self.printers and self.printers.push_on else "0"}  # label photos only with ai_intake
        attrs = " ".join(f"data-{k}='{html.escape(v, quote=True)}'" for k, v in data.items())
        return f"<body {attrs}><main id=app></main></body>"

    async def page(self, request: Request):
        if not self._lan(request):
            return self._html(HOME_ONLY, 403)
        if not self._signed_in(request):
            return self._html(f"<main class=login><h1>Spool intake</h1><form method=post "
                              f"action='{html.escape(self.base, quote=True)}/login'>"
                              "<input type=password name=passphrase placeholder=Passphrase "
                              "autocomplete=current-password autofocus required><button>Sign in</button></form></main>")
        return self._html(await anyio.to_thread.run_sync(self._shell), signed_in=True)

    async def login(self, request: Request):
        if not self._lan(request):
            return self._html(HOME_ONLY, 403)
        if request.headers.get("origin") != self.origin:
            return self._html("<main><p>Sign in from the intake page itself.</p></main>", 403)
        attempt = self.lockout.attempt()        # counted before the check (A-M1)
        if attempt is None:
            return self._html("<main><p>Too many wrong passphrases. Wait 10 minutes.</p></main>", 429)
        form = await request.form()
        ok = await anyio.to_thread.run_sync(auth.check_passphrase, str(form.get("passphrase", "")),
                                            self.passphrase_file)
        back = f"<p><a href='{html.escape(self.base, quote=True)}'>Try again</a></p></main>"
        if ok is not False:                     # right, or no passphrase set: not a wrong guess
            self.lockout.release(attempt)
        if ok is None:
            return self._html("<main class=login><p>No passphrase is set on the server yet (run: filament-kit web "
                              "passphrase).</p>" + back, 503)
        if not ok:
            return self._html("<main class=login><p>Wrong passphrase.</p>" + back, 401)
        tok = await anyio.to_thread.run_sync(self.store.new_session)
        r = RedirectResponse(self.base, 303)
        r.set_cookie(COOKIE, tok, max_age=auth.SESSION_TTL, path=self.base, secure=True, httponly=True,
                     samesite="strict")
        return r

    async def logout(self, request: Request):
        if request.headers.get("origin") == self.origin and (tok := request.cookies.get(COOKIE)):
            await anyio.to_thread.run_sync(self.store.end_session, tok)
        r = RedirectResponse(self.base, 303)
        r.delete_cookie(COOKIE, path=self.base, secure=True, httponly=True, samesite="strict")
        return r

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
            if not self._signed_in(request):
                return JSONResponse({"error": "signed out: reload the page"}, 401)
            if request.method == "POST" and request.headers.get("origin") != self.origin:
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

    # ---------- label photos -> items (Claude) ----------
    async def read(self, request: Request):
        if "ai_intake" not in modules.enabled(self.tools.cfg()):
            raise Problem("label reading (the ai_intake module) is off on this server")
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
            cap = ReadCap(config.paths().state / "reads.json", cfg["reads_per_day"])
            cap.take()
            try:
                ctx = intake.read_context(cfg, self.tools.sm, self._station())
                return intake.read_labels(self.tools.sm, images, hint, None, self.claude, **ctx)
            except SpoolmanError:  # as api.py: the catalog fetch failed before Claude was called
                cap.refund()
                raise
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
        return await anyio.to_thread.run_sync(lambda: self.tools.add_spools(items, dry, link))

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
