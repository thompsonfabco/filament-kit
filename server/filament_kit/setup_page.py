"""The setup page: `/setup` on the kit server's own HTTPS port (8710), where the owner enters keys and codes without
the command line (owner's words: "a simple webpage after the server is installed"). Works without the web and remote
modules: it is part of the server.

Access (owner's choice A, 2026-11-07):
  - home network only (config `web.lan`, the private ranges by default; loopback always), every request;
  - the Host must be one of the server's own names or addresses (its certificate's names, its current IPs), and
    every POST must carry that same `Origin`: another site in the owner's browser cannot post here, and a DNS
    rebinding name is refused;
  - viewing needs nothing more; every change of a secret, a pairing, a printer or a module needs the setup code
    (setup_code.py). The server never checks a code: it hands it, with the client's address, to the root helper
    (op `check`, or the write itself), the only reader of the root-only hash, which keeps the lockout (5 wrong per
    10 minutes per address, a global ceiling with a doubling backoff);
  - the page's CSP allows only its own script and style (no external assets); the script never uses innerHTML.

Secret fields are write-only: the state says "set" / "not set", never a value; values never appear in logs, URLs or
replies. Every change writes one audit line to the journal (`setup: anthropic key replaced from 192.0.2.20`).

Where the writes go: the server runs as filament-kit, so what lives in its state directory (printers, pairings,
reader tokens) it writes itself with the CLI's own functions (registry, pairing, reader_tokens); what lives in
root's /etc/filament-kit (the Anthropic key, the web passphrase, the library token, config.json for modules and
addresses) and the background `modules apply` go to the root helper (setup_helper.py) over its socket, with the
setup code, which the helper checks again.

Routes (JSON under /setup/api; every POST body is a JSON object, `code` = the setup code):
    GET  /setup  /setup/setup.js  /setup/setup.css
    GET  state                          everything the page shows
    GET  modules/preview?name=N         what switching N would do (the checklist's notes and needed settings)
    GET  apply?from=N                   the background apply's output from byte N, and whether it finished
    POST key {code, key}  key/remove {code}  key/check {}      the Anthropic key (check: like `status`)
    POST printers {code, ip, access_code[, name, serial, model]}  printers/{serial}/code {code, access_code}
    POST printers/{serial}/test {}  printers/{serial}/forget {code}
    POST passphrase {code, passphrase}  library_token {code, token}  library_token/remove {code}
    POST readers {code[, name]} (the token, shown once)  readers/{id}/revoke {code}
    POST pair {code, kind: phone|pc|station}  devices/{id}/revoke {code}
    POST modules {code, name, on[, settings]}  settings {code, key, value}  apply {code}
"""
from __future__ import annotations

import contextvars
import html
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import anyio
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from . import config, lan, modules, pairing, reader_tokens, setup_code, setup_helper
from .bridge import registry

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "setup_static"
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
                               "connect-src 'self'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"}
HOME_ONLY = "the setup page only answers the home network"
BAD_HOST = "open the setup page by the server's own name or address"
NEED_CODE = "this change needs the setup code (shown when the kit was installed; at the server: sudo filament-kit setup-code)"
MAX_BODY = 16 * 1024
MAX_LOG = 64 * 1024
CHECK_GAP = 3.0                 # seconds between two key checks / printer tests (they reach the network)
KINDS = {"phone": "", "pc": "pc", "station": "station"}
ENTRY = re.compile(r"[A-Za-z0-9_-]{1,64}")
PRINTER_PORT = 8883
_CLIENT: contextvars.ContextVar[str] = contextvars.ContextVar("setup_client", default="?")


class Refused(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


class HelperClient:
    """One request to the root helper over its socket: one JSON line out, one back."""

    def __init__(self, path: str | None = None, timeout: float = 120):
        self.path = path or os.environ.get("FK_SETUP_SOCKET", "/run/filament-kit-setup/setup.sock")
        self.timeout = timeout

    def __call__(self, req: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.path)
                s.sendall(json.dumps(req).encode("utf-8") + b"\n")
                s.shutdown(socket.SHUT_WR)
                data = b""
                while len(data) < 1024 * 1024:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            reply = json.loads(data or b"null")
            if not isinstance(reply, dict):
                raise ValueError("not an object")
            return reply
        except (OSError, ValueError, AttributeError) as e:
            log.error("setup: the root helper did not answer (%s)", type(e).__name__)
            return {"ok": False, "status": 503, "error": "the setup helper is not running; at the server: "
                                                          "sudo systemctl enable --now filament-kit-setup.socket"}


def _present(name: str) -> bool:
    try:
        return (config.paths().etc / name).stat().st_size > 0
    except OSError:
        return False


def _fmt_time(t) -> str | None:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if isinstance(t, (int, float)) and t else None


def _cert_names() -> set[str]:
    """The DNS names and IP addresses in the server's certificate (what a browser accepts without a warning)."""
    from cryptography import x509
    try:
        cert = x509.load_pem_x509_certificate((config.paths().etc / "cert.pem").read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return set()
    return ({n.lower() for n in san.get_values_for_type(x509.DNSName)}
            | {str(i) for i in san.get_values_for_type(x509.IPAddress)})


def allowed_hosts() -> set[str]:
    full = socket.gethostname().lower()
    short = pairing.short_hostname().lower()
    return (_cert_names() | set(pairing.local_ips())
            | {full, short, f"{short}.local", "localhost", "127.0.0.1", "::1"})


def _host_of(host_header: str) -> str:
    """'kit.local:8710' -> 'kit.local'; '[fe80::1]:8710' -> 'fe80::1'."""
    try:
        return (urlparse("//" + host_header).hostname or "").lower()
    except ValueError:
        return ""


class SetupPage:
    def __init__(self, printers=None, *, helper=None, client_factory=None, hosts=None):
        self.printers = printers                    # the connection manager (None: the printers module is off)
        self.helper = helper or HelperClient()
        self.client_factory = client_factory
        self.hosts = hosts or allowed_hosts         # a function: the names the page answers to
        self.last_check = 0.0
        self.static = {n: (STATIC / n).read_bytes() for n in ("setup.js", "setup.css")}

    # ---------- routes ----------
    def routes(self) -> list[Route]:
        g = self.guard
        w = lambda fn: self.guard(fn, write=True)  # noqa: E731
        hw = lambda fn: self.guard(fn, write="helper")  # noqa: E731
        table = [
            ("/state", g(self.state), "GET"), ("/modules/preview", g(self.preview), "GET"),
            ("/apply", g(self.apply_get), "GET"),
            ("/key", hw(self.key_set), "POST"), ("/key/remove", hw(self.key_remove), "POST"),
            ("/key/check", g(self.key_check), "POST"),
            ("/printers", w(self.printer_add), "POST"), ("/printers/{serial}/code", w(self.printer_code), "POST"),
            ("/printers/{serial}/test", g(self.printer_test), "POST"),
            ("/printers/{serial}/forget", w(self.printer_forget), "POST"),
            ("/passphrase", hw(self.passphrase), "POST"),
            ("/library_token", hw(self.library_token), "POST"),
            ("/library_token/remove", hw(self.library_token_remove), "POST"),
            ("/readers", w(self.reader_add), "POST"), ("/readers/{id}/revoke", w(self.reader_revoke), "POST"),
            ("/pair", w(self.pair), "POST"), ("/devices/{id}/revoke", w(self.device_revoke), "POST"),
            ("/modules", hw(self.module), "POST"), ("/settings", hw(self.setting), "POST"),
            ("/apply", hw(self.apply_start), "POST")]
        return ([Route("/setup", self.page, methods=["GET"]),
                 Route("/setup/setup.js", self.asset, methods=["GET"]),
                 Route("/setup/setup.css", self.asset, methods=["GET"])]
                + [Route("/setup/api" + p, fn, methods=[m]) for p, fn, m in table])

    # ---------- access ----------
    @staticmethod
    def _ip(request: Request) -> str:
        return request.client.host if request.client else ""

    def _lan(self, request: Request) -> bool:
        nets = lan.parse_lan((config.load().get("web") or {}).get("lan") or ())
        return lan.is_lan(self._ip(request), nets)

    def _host_ok(self, request: Request) -> bool:
        return _host_of(request.headers.get("host", "")) in self.hosts()

    def _origin_ok(self, request: Request) -> bool:
        origin, host = request.headers.get("origin"), request.headers.get("host", "")
        return bool(origin) and origin == f"https://{host}"

    def audit(self, request: Request, what: str) -> None:
        log.info("setup: %s from %s", what, self._ip(request))

    async def _body(self, request: Request) -> dict:
        """The JSON body, refused past MAX_BODY bytes: by Content-Length before reading, else while streaming."""
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            raise Refused(400, "bad Content-Length") from None
        if declared > MAX_BODY:
            raise Refused(413, "request too large")
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BODY:
                raise Refused(413, "request too large")
        try:
            b = json.loads(raw or b"{}")
        except ValueError:
            raise Refused(400, "the request body must be JSON") from None
        if not isinstance(b, dict):
            raise Refused(400, "the request body must be a JSON object")
        return b

    async def _code_ok(self, request: Request, body: dict) -> None:
        """The root helper checks the code (op `check`); a missing one is refused here and counts nowhere."""
        code = body.get("code")
        if not isinstance(code, str) or not code.strip():
            raise Refused(403, NEED_CODE)
        await self._helper({"op": "check", "code": code, "client": self._ip(request)})

    def guard(self, fn, write: bool | str = False):
        """`write`: True = a change the server makes itself (the helper's `check` first); "helper" = a change the
        helper makes, which checks the code in the same request."""
        async def route(request: Request):
            _CLIENT.set(self._ip(request))
            if not self._lan(request):
                return JSONResponse({"error": HOME_ONLY}, 403)
            if not self._host_ok(request):
                return JSONResponse({"error": BAD_HOST}, 403)
            try:
                body = {}
                if request.method == "POST":
                    if not self._origin_ok(request):
                        return JSONResponse({"error": "bad origin"}, 403)
                    body = await self._body(request)
                    if write == "helper":
                        if not isinstance(body.get("code"), str) or not body["code"].strip():
                            raise Refused(403, NEED_CODE)
                    elif write:
                        await self._code_ok(request, body)
                res = await fn(request, body)
                return JSONResponse(res, headers={"Cache-Control": "no-store"})
            except Refused as e:
                return JSONResponse({"error": e.message, **e.extra}, e.status)
            except Exception:  # noqa: BLE001 - a crash is logged (no values in it), the page gets a plain line
                log.exception("setup %s", request.url.path)
                return JSONResponse({"error": "internal error (see the server log)"}, 500)
        return route

    async def _helper(self, req: dict) -> dict:
        req.setdefault("client", _CLIENT.get())       # the address the helper's lockout counts against
        r = await anyio.to_thread.run_sync(self.helper, req)
        if not r.get("ok"):
            extra = {k: r[k] for k in ("needs",) if k in r}
            raise Refused(int(r.get("status") or 500), str(r.get("error") or "the setup helper refused"), **extra)
        return r

    # ---------- the page ----------
    async def page(self, request: Request):
        if not self._lan(request):
            return HTMLResponse(f"<!doctype html><p>{HOME_ONLY}.</p>", 403, headers=HEADERS)
        if not self._host_ok(request):
            return HTMLResponse(f"<!doctype html><p>{BAD_HOST}.</p>", 403, headers=HEADERS)
        name = html.escape(config.load()["server_name"])
        return HTMLResponse(
            "<!doctype html><html lang=en><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>filament-kit setup: {name}</title><link rel=stylesheet href='/setup/setup.css'>"
            "<body><main id=app></main><script src='/setup/setup.js'></script></body></html>", headers=HEADERS)

    async def asset(self, request: Request):
        if not self._lan(request):
            return Response(status_code=403)
        name = request.url.path.rsplit("/", 1)[-1]
        return Response(self.static[name], media_type="text/javascript" if name.endswith(".js") else "text/css",
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    # ---------- reads ----------
    def _printer_rows(self) -> list[dict]:
        out = []
        for p in registry.load().values():
            state = "not_configured"
            if p.configured and self.printers is not None:
                state = self.printers.state(p.serial)
            out.append({"serial": p.serial, "name": registry.display_name(p), "model": p.model, "ip": p.ip,
                        "configured": p.configured, "state": state, "pinned": bool(p.cert_fp)})
        return out

    def _state(self) -> dict:
        from . import cli
        cfg = config.load()
        on = modules.enabled(cfg)
        try:
            readers, readers_error = reader_tokens.TokenStore().list(), None
        except reader_tokens.TokenFileError as e:
            readers, readers_error = [], str(e)
        return {
            "server_name": cfg["server_name"], "address": setup_code.page_url(cfg), "code_set": setup_code.is_set(),
            "mode": modules.mode_of(on),
            "modules": [{"name": n, "title": m.title, "description": m.description, "needs": modules.needs_of(n),
                         "optional_ai": m.optional_ai, "on": n in on} for n, m in modules.MODULES.items()],
            "anthropic": {"set": _present(cli.KEY_FILE), "ai_intake": "ai_intake" in on},
            "passphrase": {"set": _present(cli.WEB_PASSPHRASE), "web": "web" in on},
            "library_token": {"set": _present("github_token"), "library": "library" in on},
            "printers": {"on": self.printers is not None, "list": self._printer_rows()},
            "readers": {"list": readers, "error": readers_error},
            "devices": [{"id": d["id"], "name": d["name"], "paired": _fmt_time(d["paired"]),
                         "last_seen": _fmt_time(d["last_seen"])} for d in pairing.devices()],
            "web": {"public_url": (cfg.get("web") or {}).get("public_url")},
            "station": {"url": (cfg.get("station") or {}).get("url")},
            "apply": self._apply_view(0, with_text=False),
        }

    async def state(self, request: Request, body: dict):
        return await anyio.to_thread.run_sync(self._state)

    async def preview(self, request: Request, body: dict):
        """What switching a module would do, in the checklist's words; changes nothing."""
        name = request.query_params.get("name", "")
        if name not in modules.MODULES:
            raise Refused(400, "no such module")
        cfg = await anyio.to_thread.run_sync(config.load)
        on = modules.enabled(cfg)
        if name == "server" and "server" in on:
            return {"name": name, "on": False, "notes": [], "after": sorted(on), "needs": [],
                    "refused": "this page is the server module's: switch it off at the server: "
                               "sudo filament-kit modules disable server"}
        chosen, notes = modules.toggle(on, name)
        needs = [{"key": k, "prompt": modules._SETTING_PROMPTS[k].rstrip(": ")}
                 for k in modules.missing_settings(chosen, cfg) if k != "station.allow"]
        return {"name": name, "on": name in chosen, "notes": notes,
                "after": [n for n in modules.MODULES if n in chosen], "needs": needs, "refused": None}

    def _apply_view(self, start: int, with_text: bool = True) -> dict:
        try:
            data = setup_helper.apply_log().read_bytes()
        except OSError:
            return {"seen": False, "running": False, "exit": None, "text": "", "next": 0}
        m = re.search(rb"==> finished \(exit (-?[0-9]+)\)", data)
        start = max(0, min(start, len(data)))
        chunk = data[start:start + MAX_LOG] if with_text else b""
        return {"seen": True, "running": m is None, "exit": int(m.group(1)) if m else None,
                "text": chunk.decode("utf-8", "replace"), "next": start + len(chunk)}

    async def apply_get(self, request: Request, body: dict):
        try:
            start = int(request.query_params.get("from", "0"))
        except ValueError:
            raise Refused(400, "from must be a number") from None
        return await anyio.to_thread.run_sync(self._apply_view, start)

    # ---------- the Anthropic key (root helper) ----------
    async def key_set(self, request: Request, body: dict):
        had = _present("anthropic_key")
        await self._helper({"op": "key_set", "code": body["code"], "key": body.get("key")})
        self.audit(request, "anthropic key replaced" if had else "anthropic key set")
        return {"ok": True, "set": True}

    async def key_remove(self, request: Request, body: dict):
        r = await self._helper({"op": "key_remove", "code": body["code"]})
        if r.get("removed"):
            self.audit(request, "anthropic key removed")
        return {"ok": True, "set": False}

    def _gap(self) -> None:
        now = time.monotonic()
        if now - self.last_check < CHECK_GAP:
            raise Refused(429, f"wait {CHECK_GAP:.0f} s between checks")
        self.last_check = now

    async def key_check(self, request: Request, body: dict):
        from . import cli
        self._gap()
        ok, text = await anyio.to_thread.run_sync(cli.check_key, self.client_factory)
        return {"ok": ok, "text": text}

    # ---------- printers (the server's own registry, as the CLI's printers menu) ----------
    def _manager(self):
        if self.printers is None:
            raise Refused(409, "the printers module is off on this server")
        return self.printers

    @staticmethod
    def _serial(request: Request) -> str:
        s = request.path_params["serial"]
        if not registry.SERIAL.fullmatch(s):
            raise Refused(404, "no such printer")
        return s

    @staticmethod
    def _access_code(body: dict) -> str:
        code = body.get("access_code")
        code = code.strip() if isinstance(code, str) else ""
        if not registry.ACCESS_CODE.fullmatch(code):
            raise Refused(400, registry.BAD_ACCESS_CODE)
        return code

    @staticmethod
    def _opt_text(body: dict, key: str, limit: int = 64) -> str:
        v = body.get(key)
        if v is None:
            return ""
        if not isinstance(v, str) or len(v) > limit or not v.isprintable():
            raise Refused(400, f"{key} must be text")
        return v.strip()

    async def printer_add(self, request: Request, body: dict):
        """Add a printer by IP: its serial from its TLS certificate (CN), else the typed one (upper-cased)."""
        manager = self._manager()
        ip = body.get("ip")
        try:
            ip = str(ipaddress.ip_address(ip.strip() if isinstance(ip, str) else ""))
        except ValueError:
            raise Refused(400, "ip must be the printer's IP address (on the printer: Settings > Network)") from None
        access = self._access_code(body)
        name, model = self._opt_text(body, "name"), self._opt_text(body, "model", 32)
        typed = self._opt_text(body, "serial").upper()

        def run() -> dict:
            try:
                seen, why = setup_serial(ip), ""
            except OSError as e:
                seen, why = None, f"the printer at {ip} did not answer ({type(e).__name__})"
            if seen and typed and seen != typed:
                raise Refused(400, f"the printer at {ip} names itself {seen}, not {typed}: check the IP address")
            serial = seen or typed
            if not serial:
                raise Refused(400, (why or f"the printer at {ip} did not name its serial") +
                              "; type the serial number (on the printer: Settings > Device)")
            problem = registry.check_fields(serial, access)
            if problem:
                raise Refused(400, problem)
            old = registry.load().get(serial)
            # as the CLI's add: a fresh entry (adding the printer again also clears its TLS pin)
            registry.upsert(registry.Printer(serial, name or (old.name if old else "") or serial,
                                             model or (old.model if old else ""), ip, access, True))
            manager.sync()
            return {"serial": serial, "replaced": old is not None and old.configured}
        r = await anyio.to_thread.run_sync(run)
        self.audit(request, f"printer {r['serial']} {'replaced' if r['replaced'] else 'added'}")
        return {"ok": True, "serial": r["serial"]}

    async def printer_code(self, request: Request, body: dict):
        manager, serial, access = self._manager(), self._serial(request), self._access_code(body)

        def run() -> None:
            if registry.load().get(serial) is None:
                raise Refused(404, "no such printer")
            registry.set_code(serial, access, replace=True)
            manager.sync()
        await anyio.to_thread.run_sync(run)
        self.audit(request, f"printer {serial} access code replaced")
        return {"ok": True}

    async def printer_test(self, request: Request, body: dict):
        """A TLS handshake with the printer (nothing is sent, nothing is pinned) and the connection's state."""
        from .bridge import tlspin
        manager, serial = self._manager(), self._serial(request)
        self._gap()

        def run() -> dict:
            p = registry.load().get(serial)
            if p is None:
                raise Refused(404, "no such printer")
            state = manager.state(serial) if p.configured else "not_configured"
            try:
                fp = tlspin.leaf_fp(p.ip, PRINTER_PORT)
            except OSError as e:
                return {"reachable": False, "state": state,
                        "text": f"no answer from {p.ip}:{PRINTER_PORT} ({type(e).__name__}): check that it is on"}
            cert = ("matches the pinned one" if fp == p.cert_fp else
                    "not pinned yet (pinned at the first connection)" if not p.cert_fp else
                    "differs from the pinned one: if the printer was not reset, check its IP before re-adding")
            return {"reachable": True, "state": state, "text": f"{p.ip} answers; its certificate {cert}"}
        return await anyio.to_thread.run_sync(run)

    async def printer_forget(self, request: Request, body: dict):
        manager, serial = self._manager(), self._serial(request)

        def run() -> bool:
            gone = registry.remove(serial)
            manager.sync()
            return gone
        if not await anyio.to_thread.run_sync(run):
            raise Refused(404, "no such printer")
        self.audit(request, f"printer {serial} forgotten")
        return {"ok": True}

    # ---------- the web passphrase, the library token (root helper) ----------
    async def passphrase(self, request: Request, body: dict):
        had = _present("web_passphrase")
        await self._helper({"op": "passphrase_set", "code": body["code"], "passphrase": body.get("passphrase")})
        self.audit(request, "web passphrase replaced" if had else "web passphrase set")
        return {"ok": True, "set": True}

    async def library_token(self, request: Request, body: dict):
        had = _present("github_token")
        await self._helper({"op": "library_token_set", "code": body["code"], "token": body.get("token")})
        self.audit(request, "library token replaced" if had else "library token set")
        return {"ok": True, "set": True}

    async def library_token_remove(self, request: Request, body: dict):
        r = await self._helper({"op": "library_token_remove", "code": body["code"]})
        if r.get("removed"):
            self.audit(request, "library token removed")
        return {"ok": True, "set": False}

    # ---------- readers, pairings (the server's own state, as `reader` and `pair` / `unpair`) ----------
    async def reader_add(self, request: Request, body: dict):
        name = self._opt_text(body, "name")

        def run():
            try:
                return reader_tokens.TokenStore().issue(name or None)
            except reader_tokens.TokenFileError as e:
                raise Refused(409, f"{e}; nothing was changed") from None
        tid, token = await anyio.to_thread.run_sync(run)
        self.audit(request, f"reader token {tid} made")
        return {"ok": True, "id": tid, "name": reader_tokens._clean_name(name), "token": token,
                "note": "Shown only this once: put it in the reader's src/secrets.h as READER_TOKEN, then build "
                        "and flash (reader/README.md)."}

    async def reader_revoke(self, request: Request, body: dict):
        tid = request.path_params["id"]
        if not reader_tokens.TOKEN_ID.fullmatch(tid):
            raise Refused(404, "no such reader token")

        def run() -> bool:
            try:
                return reader_tokens.TokenStore().revoke(tid)
            except reader_tokens.TokenFileError as e:
                raise Refused(409, f"{e}; nothing was changed") from None
        if not await anyio.to_thread.run_sync(run):
            raise Refused(404, "no such reader token")
        self.audit(request, f"reader token {tid} revoked")
        return {"ok": True}

    async def pair(self, request: Request, body: dict):
        kind = body.get("kind", "phone")
        if kind not in KINDS:
            raise Refused(400, "kind must be phone, pc or station")

        def run() -> dict:
            try:
                pr = pairing.issue(device_hint=KINDS[kind])
            except pairing.PairingError as e:
                raise Refused(503, str(e)) from None
            fp = pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
            return {"code": pr.code, "link": pr.qr, "qr_svg": qr_svg(pr.qr) if kind == "phone" else None,
                    "fingerprint": " ".join(fp[i:i + 4] for i in range(0, len(fp), 4)),
                    "expires_in": max(0, int(pr.expires - time.time()))}
        r = await anyio.to_thread.run_sync(run)
        self.audit(request, f"pairing started ({kind})")
        return {"ok": True, "kind": kind, **r}

    async def device_revoke(self, request: Request, body: dict):
        did = request.path_params["id"]
        if not ENTRY.fullmatch(did) or not await anyio.to_thread.run_sync(pairing.revoke, did):
            raise Refused(404, "no such paired device")
        self.audit(request, f"paired device {did} revoked")
        return {"ok": True}

    # ---------- modules, addresses, the apply (root helper) ----------
    async def module(self, request: Request, body: dict):
        name, on = body.get("name"), body.get("on")
        r = await self._helper({"op": "module", "code": body["code"], "name": name, "on": on,
                                "settings": body.get("settings")})
        if r.get("changed"):
            self.audit(request, f"module {name} switched {'on' if on else 'off'}")
        return {"ok": True, "changed": bool(r.get("changed")), "notes": r.get("notes") or []}

    async def setting(self, request: Request, body: dict):
        key = body.get("key")
        await self._helper({"op": "setting", "code": body["code"], "key": key, "value": body.get("value")})
        self.audit(request, {"web.public_url": "web public address", "station.url": "station address"}
                   .get(key, "setting") + " changed")
        return {"ok": True}

    async def apply_start(self, request: Request, body: dict):
        await self._helper({"op": "apply", "code": body["code"]})
        self.audit(request, "modules apply started")
        return {"ok": True}


def setup_serial(ip: str, timeout: float = 5) -> str | None:
    """The serial a printer names in its TLS leaf (`CN=<serial>`, a handshake only: nothing is sent, nothing is
    pinned), for adding it by IP; None when the leaf has no usable CN. Raises OSError when nothing answers."""
    from .bridge import tlspin
    cn = tlspin._cn(tlspin._leaf_der(ip, PRINTER_PORT, timeout))
    return cn if cn and registry.SERIAL.fullmatch(cn) else None


def qr_svg(payload: str) -> str | None:
    """The pairing link as an SVG QR code (qrencode, the server module's package; the link goes in on stdin, never
    on a command line), or None without qrencode."""
    exe = shutil.which("qrencode")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-t", "SVG", "-o", "-"], input=payload, capture_output=True, text=True, timeout=10,
                           check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.stdout.lstrip().startswith(("<?xml", "<svg")) else None


def routes(printers=None, **kw) -> list[Route]:
    return SetupPage(printers, **kw).routes()
