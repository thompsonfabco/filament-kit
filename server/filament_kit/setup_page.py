"""The setup page: `/setup` on the kit server's own HTTPS port (8710), where the owner enters keys and codes without
the command line, after the server is installed. Works without the web and remote
modules: it is part of the server.

Access (a page on the home network that can change secrets, so each change needs more than reaching it):
  - home network only (config `web.lan`, the private ranges by default; loopback always), every request;
  - the Host must be one of the server's own names or addresses (its certificate's names, its current IPs), and
    every POST must carry that same `Origin`: another site in the owner's browser cannot post here, and a DNS
    rebinding name is refused;
  - viewing needs nothing more; every change of a secret, a pairing, a printer or a module needs the setup code
    (setup_code.py). The server never checks a code: it hands it, with the client's address, to the root helper
    (op `check`, or the write itself), the only reader of the root-only hash, which keeps the lockout (5 wrong per
    10 minutes per address, a global ceiling with a doubling backoff). A computer trusted after the code was typed once
    sends a cookie instead (trusted.py), which the helper checks in the code's place, and which can be turned off;
  - the page's CSP allows only its own script and style (no external assets); the script never uses innerHTML.

Secret fields are write-only: the state says "set" / "not set", never a value; values never appear in logs, URLs or
replies. Every change writes one audit line to the journal (`setup: anthropic key replaced from 192.0.2.20`).

Where the writes go: the server runs as filament-kit, so what lives in its state directory (printers, pairings,
reader tokens) it writes itself with the CLI's own functions (registry, pairing, reader_tokens); what lives in
root's /etc/filament-kit (the Anthropic key, the web passphrase, the library token, config.json for modules and
addresses) and the background `modules apply` go to the root helper (setup_helper.py) over its socket, with the
setup code, which the helper checks again.

Routes (JSON under /setup/api; every POST body is a JSON object, `code` = the setup code):
    GET  /setup  /setup/setup.js  /setup/setup_tabs.js  /setup/setup_printers.js  /setup/setup_trust.js  /setup/setup.css
         /setup/setup_flash.js  /setup/esptool.bundle.js (the Flash a device tab; setup_console/flash_tab.py)
    GET  state                          everything the page shows
    GET  modules/preview?name=N         what switching N would do (the checklist's notes and needed settings)
    GET  apply?from=N                   the job `apply`'s old name: as GET job
    (the console's own routes, by tab: setup_console/)
    POST key {code, key}  key/remove {code}  key/check {}      the Anthropic key (check: like `status`)
    POST printers {code, address, access_code[, name, serial, model]}  printers/{serial}/code {code, access_code}
    POST printers/{serial}/test {}  printers/{serial}/forget {code}
        Printers are listed (and tested, forgotten) when their family's module is on: Bambu with `printers`, Klipper
        with `klipper` (either alone is enough). This route and the Access Code are Bambu's (a Klipper printer: 400,
        and setup_console/printers_tab.py adds one); Test is a TLS handshake for Bambu, Moonraker's /printer/info for
        Klipper (its API key never shown). An address is an IP or a name, kept as typed (hostaddr).
    POST passphrase {code, passphrase}  library_token {code, token}  library_token/remove {code}
    POST local_intake_token {code, token}  local_intake_token/remove {code}   (the local label reader's bearer token)
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

from . import __version__, config, hostaddr, lan, modules, pairing, reader_tokens, setup_code, shared_files, trusted
from .bridge import registry
from .bridge.klipper.moonraker import Moonraker, MoonrakerError, NotFound, Offline, Unauthorized

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "setup_static"
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
                               "connect-src 'self'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"}
HOME_ONLY = "the setup page only answers the home network"
BAD_HOST = "Open the setup page by the server's own name or address"
NEED_CODE = "this change needs the setup code (shown when the kit was installed; at the server: sudo filament-kit setup-code)"
MAX_BODY = 16 * 1024
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

    def open_file(self, req: dict):
        """A request whose answer carries an open file beside the reply (op backup_open): (reply, file or None). A file
        that came with a broken reply is closed, never left open (audit v0.5.0, finding 2)."""
        fds: list[int] = []
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.path)
                s.sendall(json.dumps(req).encode("utf-8") + b"\n")
                s.shutdown(socket.SHUT_WR)
                data, fds, _flags, _addr = socket.recv_fds(s, 65536, 1)
                while chunk := s.recv(65536):
                    data += chunk
                    if len(data) > 1024 * 1024:
                        raise ValueError("reply too long")
            reply = json.loads(data or b"null")
            if not isinstance(reply, dict):
                raise ValueError("not an object")
            fh = os.fdopen(fds[0], "rb") if fds else None
            fds = fds[1:]
            return reply, fh
        except (OSError, ValueError, AttributeError) as e:
            log.error("setup: the root helper did not answer (%s)", type(e).__name__)
            return {"ok": False, "status": 503, "error": "the setup helper did not answer"}, None
        finally:
            for fd in fds:
                os.close(fd)

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
            if isinstance(e, PermissionError):     # only root and the kit server's user may use it
                return {"ok": False, "status": 503, "error": "this process may not use the setup helper (only the "
                                                              "kit server may)"}
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


# A name the owner's own DNS gives this server is accepted (the user's rule: DNS names everywhere), but only a local
# one: a single label, a private suffix, the server's own DNS domain, or a domain its DNS settings search (the home
# network's domain the router hands out). A public name that resolves here is how DNS rebinding reaches a LAN page
# from an attacker's site, so such a name has to be added on the Settings tab instead.
LOCAL_SUFFIXES = frozenset(("local", "lan", "home", "home.arpa", "internal", "intranet", "corp", "localhost"))
RESOLV_CONF = "/etc/resolv.conf"
_RESOLVED: dict[str, tuple[float, bool]] = {}      # name -> (when, resolves here), kept RESOLVE_TTL seconds
RESOLVE_TTL = 60.0


def _home_domains(resolv: str | None = None) -> set[str]:
    """The server's own DNS domain and the domains its resolver searches (`domain` and `search` in resolv.conf)."""
    out = set()
    fqdn = socket.getfqdn().lower().rstrip(".")
    if "." in fqdn:
        out.add(fqdn.split(".", 1)[1])
    try:
        lines = Path(resolv or RESOLV_CONF).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        f = line.split()
        if f and f[0] in ("domain", "search"):
            out.update(d.lower().rstrip(".") for d in f[1:] if "." in d or d.isalpha())
    return {d for d in out if d}


def local_name(name: str) -> bool:
    """A name of the home network, not of the internet: one label, the server's own domain, or a private suffix."""
    if not name or ":" in name or name.replace(".", "").isdigit():
        return False
    if "." not in name:
        return True
    return any(name.endswith("." + s) for s in LOCAL_SUFFIXES | _home_domains())


def resolves_here(name: str, now: float | None = None) -> bool:
    """The name's forward lookup gives one of this server's own addresses (cached RESOLVE_TTL seconds)."""
    now = time.monotonic() if now is None else now
    hit = _RESOLVED.get(name)
    if hit and now - hit[0] < RESOLVE_TTL:
        return hit[1]
    try:
        found = {ai[4][0].split("%", 1)[0] for ai in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        found = set()
    ok = bool(found & (set(pairing.local_ips()) | {"127.0.0.1", "::1"}))
    if len(_RESOLVED) > 256:
        _RESOLVED.clear()
    _RESOLVED[name] = (now, ok)
    return ok


def extra_hosts() -> set[str]:
    """The names the owner added on the Settings tab (setup.hosts in config.json)."""
    try:
        names = (config.load().get("setup") or {}).get("hosts") or []
    except (OSError, ValueError):
        return set()
    return {n.lower() for n in names if isinstance(n, str)}


def bad_host_text() -> str:
    """The refusal, for whoever reached the port by another name: how to get in, never the server's own names or
    addresses (a stranger probing the port learns nothing from it; emulator finding F2, 2026-11-10)."""
    return (f"{BAD_HOST}. A name of your own DNS that points at this server works too if it is a local one (one word, "
            ".local, .lan, .home.arpa, or your network's own domain); add any other name on the Settings tab, under "
            "General: Names for this page.")


from .web.slots import CLI_DEVICE, INTAKE_DEVICE  # noqa: E402
BUILT_IN_DEVICES = (INTAKE_DEVICE, CLI_DEVICE)     # the server's own pairings: shown as built in, never revoked here


def host_ok(request, hosts=None) -> bool:
    """The Host rule of the kit server's own pages (the setup page, the phone web app at /intake): one of the server's
    names or addresses (`hosts`, default allowed_hosts), a name added on the Settings tab, or a local name of the
    owner's DNS that resolves here."""
    name = _host_of(request.headers.get("host", ""))
    if not name:
        return False
    if name in (hosts or allowed_hosts)() or name in extra_hosts():
        return True
    return local_name(name) and resolves_here(name)


def _host_of(host_header: str) -> str:
    """'kit.local:8710' -> 'kit.local'; '[fe80::1]:8710' -> 'fe80::1'."""
    try:
        return (urlparse("//" + host_header).hostname or "").lower()
    except ValueError:
        return ""


class SetupPage:
    def __init__(self, printers=None, *, families=None, helper=None, client_factory=None, hosts=None, mapper=None):
        # the connection manager: the Bambu Manager or family.Printers (None: no printer module is on); `families`
        # = the printer families whose module is on ("bambu" = the printers module, "klipper" = the klipper module)
        self.printers = printers
        self.mapper = mapper                        # Bambu slot mapping: the server's own (None: the printers module is off)
        self.families = frozenset(families if families is not None else ({"bambu"} if printers is not None else ()))
        if printers is None:
            self.families = frozenset()
        self.helper = helper or HelperClient()
        self.client_factory = client_factory
        self.hosts = hosts or allowed_hosts         # a function: the names the page answers to
        self.last_check = 0.0
        self.shared = shared_files.load()           # tokens, strings, icon sprite, components: served at /setup/shared/<file>
        self.static = {n: (STATIC / n).read_bytes()
                       for n in ("setup.js", "setup_tabs.js", "setup_printers.js", "setup_trust.js", "setup_presets.js",
                                 "setup_backup.js",
                                 "setup_logs.js", "setup_intake.js", "setup_flash.js",
                                 # esptool-js 0.7.0 as published (THIRD-PARTY.md): only the Flash a device tab
                                 # loads it, when the owner writes a board from the browser
                                 "esptool.bundle.js",
                                 "setup.css")}

    # ---------- routes ----------
    def routes(self) -> list[Route]:
        from . import setup_console
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
            ("/local_intake_token", hw(self.local_intake_token), "POST"),
            ("/local_intake_token/remove", hw(self.local_intake_token_remove), "POST"),
            ("/readers", w(self.reader_add), "POST"), ("/readers/{id}/revoke", w(self.reader_revoke), "POST"),
            ("/pair", w(self.pair), "POST"), ("/devices/{id}/revoke", w(self.device_revoke), "POST"),
            ("/modules", hw(self.module), "POST"), ("/settings", hw(self.setting), "POST"),
            ("/apply", hw(self.apply_start), "POST")] + setup_console.routes(self)
        return ([Route("/setup", self.page, methods=["GET"]),
                 Route("/setup/setup.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_tabs.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_printers.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_trust.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_presets.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_backup.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_logs.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_intake.js", self.asset, methods=["GET"]),
                 Route("/setup/setup_flash.js", self.asset, methods=["GET"]),
                 Route("/setup/esptool.bundle.js", self.asset, methods=["GET"]),
                 Route("/setup/setup.css", self.asset, methods=["GET"]),
                 Route("/setup/shared/{name}", self.shared_asset, methods=["GET"])]
                + [Route("/setup/api" + p, fn, methods=[m]) for p, fn, m in table])

    # ---------- access ----------
    @staticmethod
    def _ip(request: Request) -> str:
        return request.client.host if request.client else ""

    @classmethod
    def _client_key(cls, request: Request) -> str:
        """Whom the helper's lockout counts a wrong code against: the address, except that every local process
        (loopback) is one client, so a local caller cannot spread its tries over made-up addresses."""
        ip = cls._ip(request)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return ip
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        return "loopback" if addr.is_loopback else ip

    def _lan(self, request: Request) -> bool:
        nets = lan.parse_lan((config.load().get("web") or {}).get("lan") or ())
        return lan.is_lan(self._ip(request), nets)

    def _host_ok(self, request: Request) -> bool:
        return host_ok(request, self.hosts)

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
        await self._helper({"op": "check", "code": code, "client": self._client_key(request)})

    @staticmethod
    def _trusted_token(request: Request, body: dict) -> str | None:
        """No code typed, and a trusted computer's cookie: the token, put in the code's place for the helper to check.
        A typed code always wins, so the path without a cookie is the same as ever."""
        code = body.get("code")
        token = request.cookies.get(trusted.COOKIE)
        if (isinstance(code, str) and code.strip()) or not token or not trusted.TOKEN.fullmatch(token):
            return None
        body["code"] = trusted.PREFIX + token
        return token

    @staticmethod
    def _set_trust(resp: Response, token: str) -> None:
        resp.set_cookie(trusted.COOKIE, token, max_age=trusted.LIFETIME, path="/setup", secure=True, httponly=True,
                        samesite="strict")

    @staticmethod
    def _clear_trust(resp: Response) -> None:
        resp.delete_cookie(trusted.COOKIE, path="/setup", secure=True, httponly=True, samesite="strict")

    def guard(self, fn, write: bool | str = False, raw: bool = False):
        """`write`: True = a change the server makes itself (the helper's `check` first); "helper" = a change the
        helper makes, which checks the code in the same request. Either way a trusted computer's cookie may stand in for
        the code, and its time is renewed when it did."""
        async def route(request: Request):
            _CLIENT.set(self._client_key(request))
            if not self._lan(request):
                return JSONResponse({"error": HOME_ONLY}, 403)
            if not self._host_ok(request):
                return JSONResponse({"error": bad_host_text()}, 403)
            try:
                body = {}
                token = None
                if request.method == "POST":
                    if not self._origin_ok(request):
                        return JSONResponse({"error": "bad origin"}, 403)
                    # raw: the body is a file the route reads itself; the code comes in a header
                    body = {"code": request.headers.get("x-setup-code", "")} if raw else await self._body(request)
                    if write:
                        token = self._trusted_token(request, body)
                    if write == "helper":
                        if not isinstance(body.get("code"), str) or not body["code"].strip():
                            raise Refused(403, NEED_CODE)
                    elif write:
                        await self._code_ok(request, body)
                res = await fn(request, body)
                if isinstance(res, Response):           # a download
                    res.headers["Cache-Control"] = "no-store"
                    resp = res
                else:
                    resp = JSONResponse(res, headers={"Cache-Control": "no-store"})
                if getattr(request.state, "clear_trust", False):
                    self._clear_trust(resp)
                elif getattr(request.state, "set_trust", None) or token:
                    self._set_trust(resp, getattr(request.state, "set_trust", None) or token)
                return resp
            except Refused as e:
                resp = JSONResponse({"error": e.message, **e.extra}, e.status)
                if e.extra.get("trust_gone"):
                    self._clear_trust(resp)
                return resp
            except Exception:  # noqa: BLE001 - a crash is logged (no values in it), the page gets a plain line
                log.exception("setup %s", request.url.path)
                return JSONResponse({"error": "internal error (see the server log)"}, 500)
        return route

    async def _helper_file(self, req: dict):
        """(reply, file) from a helper op that hands back an open file; Refused as _helper."""
        req.setdefault("client", _CLIENT.get())
        r, fh = await anyio.to_thread.run_sync(self.helper.open_file, req)
        if not r.get("ok") or fh is None:
            if fh is not None:
                fh.close()
            extra = {k: r[k] for k in ("needs", "trust_gone") if k in r}
            raise Refused(int(r.get("status") or 500), str(r.get("error") or "the setup helper refused"), **extra)
        return r, fh

    async def _helper(self, req: dict) -> dict:
        req.setdefault("client", _CLIENT.get())       # the address the helper's lockout counts against
        r = await anyio.to_thread.run_sync(self.helper, req)
        if not r.get("ok"):
            extra = {k: r[k] for k in ("needs", "trust_gone") if k in r}
            raise Refused(int(r.get("status") or 500), str(r.get("error") or "the setup helper refused"), **extra)
        return r

    # ---------- the page ----------
    async def page(self, request: Request):
        if not self._lan(request):
            return HTMLResponse(f"<!doctype html><p>{HOME_ONLY}.</p>", 403, headers=HEADERS)
        if not self._host_ok(request):
            return HTMLResponse(f"<!doctype html><p>{html.escape(bad_host_text())}</p>",
                                403, headers=HEADERS)
        name = html.escape(config.load()["server_name"])
        return HTMLResponse(
            "<!doctype html><html lang=en><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>filament-kit setup: {name}</title><link rel=stylesheet href='/setup/setup.css'>"
            f"<body>{shared_files.sprite_inline(self.shared)}<main id=app></main><script src='/setup/setup.js'></script>"
            "<script src='/setup/setup_tabs.js'></script><script src='/setup/setup_printers.js'></script>"
            "<script src='/setup/setup_trust.js'></script><script src='/setup/setup_presets.js'></script><script src='/setup/setup_backup.js'></script><script src='/setup/setup_logs.js'></script><script src='/setup/setup_intake.js'></script><script src='/setup/setup_flash.js'></script></body></html>",
            headers=HEADERS)

    async def asset(self, request: Request):
        if not self._lan(request):
            return Response(status_code=403)
        name = request.url.path.rsplit("/", 1)[-1]
        return Response(self.static[name], media_type="text/javascript" if name.endswith(".js") else "text/css",
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    async def shared_asset(self, request: Request):
        if not self._lan(request):
            return Response(status_code=403)
        return shared_files.response(self.shared, request.path_params["name"])

    # ---------- reads ----------
    def _printer_rows(self) -> list[dict]:
        out = []
        for p in registry.load().values():
            if p.family not in self.families:
                continue                            # its module is off: nothing on this page can act on it
            state = "not_configured"
            if p.configured and self.printers is not None:
                state = self.printers.state(p.serial)
            row = {"serial": p.serial, "name": registry.display_name(p), "model": p.model, "ip": p.ip,
                   "configured": p.configured, "state": state, "pinned": bool(p.cert_fp), "family": p.family}
            if p.family == "bambu":
                # a slot mapping this server runs: the page follows it again after a reload (a test's mapper is a bare object)
                running = getattr(self.mapper, "running", None)
                row["mapping"] = bool(p.configured and running is not None and running(p.serial))
                # the last mapping said a printer report would help (printer_report.WANTED): the button stands out
                from .bridge import mapping as _mapping, printer_report as _report
                row["report_why"] = _report.why((_mapping._load_status(p.serial) or {}).get("report_wanted"))
            if p.family == "klipper":
                row.update(host=p.host, port=p.port, api_key=bool(p.api_key), lane_data=p.lane_data)   # never the key itself
            out.append(row)
        return out

    def _state(self) -> dict:
        from . import cli
        cfg = config.load()
        on = modules.enabled(cfg)
        try:
            readers, readers_error = reader_tokens.TokenStore().list(), None
        except reader_tokens.TokenFileError as e:
            readers, readers_error = [], str(e)
        from .setup_console import jobs
        return {
            "server_name": cfg["server_name"], "address": setup_code.page_url(cfg), "code_set": setup_code.is_set(),
            "version": __version__, "mode": modules.mode_of(on),
            "modes": [{"name": n, "modules": sorted(m), "here": "server" in m} for n, m in modules.MODES.items()],
            "modules": [{"name": n, "title": m.title, "description": m.description, "needs": modules.needs_of(n),
                         "optional_ai": m.optional_ai, "on": n in on} for n, m in modules.MODULES.items()],
            "anthropic": {"set": _present(cli.KEY_FILE), "ai_intake": "ai_intake" in on},
            "passphrase": {"set": _present(cli.WEB_PASSPHRASE), "web": "web" in on},
            "library_token": {"set": _present("github_token"), "library": "library" in on},
            "local_intake_token": {"set": _present("local_intake_token"), "on": "local_intake" in on},
            "printers": {"on": bool(self.families), "bambu": "bambu" in self.families,
                         "klipper": "klipper" in self.families, "list": self._printer_rows()},
            "readers": {"list": readers, "error": readers_error},
            "devices": [{"id": d["id"], "name": d["name"], "paired": _fmt_time(d["paired"]),
                         "last_seen": _fmt_time(d["last_seen"]), "built_in": d["name"] in BUILT_IN_DEVICES}
                        for d in pairing.devices()],
            # the public address is owner data (`redact` hides its host): this answers without the code, so only that it is set
            "web": {"public_set": bool((cfg.get("web") or {}).get("public_url"))},
            "station": {"url": (cfg.get("station") or {}).get("url")},
            "apply": jobs.view(0, with_text=False),
        }

    async def state(self, request: Request, body: dict):
        return await anyio.to_thread.run_sync(self._state)

    async def preview(self, request: Request, body: dict):
        """What switching a module, or a mode preset, would do, in the checklist's words; changes nothing."""
        if "mode" in request.query_params:
            from .setup_console import modes
            return await anyio.to_thread.run_sync(modes.preview, request.query_params["mode"])
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

    async def apply_get(self, request: Request, body: dict):
        from .setup_console import jobs
        return await jobs.read(self, request, body)

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
    def _manager(self, family: str = "bambu"):
        if self.printers is None or family not in self.families:
            raise Refused(409, f"the {'printers' if family == 'bambu' else family} module is off on this server")
        return self.printers

    def _entry(self, serial: str) -> registry.Printer:
        """The registry entry (404 when there is none); 409 when its family's module is off."""
        p = registry.load().get(serial)
        if p is None:
            raise Refused(404, "no such printer")
        self._manager(p.family)
        return p

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
        """Add a printer by its address, kept as typed: its serial from its TLS certificate (CN), else the typed one
        (upper-cased)."""
        manager = self._manager()
        ip = hostaddr.clean(body.get("address", body.get("ip")))
        problem = hostaddr.form_error(ip)
        if problem:
            raise Refused(400, f"{problem} (on the printer: Settings > Network)")
        access = self._access_code(body)
        name, model = self._opt_text(body, "name"), self._opt_text(body, "model", 32)
        typed = self._opt_text(body, "serial").upper()

        def run() -> dict:
            _, problem, note = hostaddr.inspect(ip)
            if problem:
                raise Refused(400, problem)
            try:
                seen, why = setup_serial(ip), ""
            except OSError as e:
                seen, why = None, f"the printer at {ip} did not answer ({type(e).__name__})"
            if seen and typed and seen != typed:
                raise Refused(400, f"the printer at {ip} names itself {seen}, not {typed}: check the address")
            serial = seen or typed
            if not serial:
                raise Refused(400, (why or f"the printer at {ip} did not name its serial") +
                              "; type the serial number (on the printer: Settings > Device)")
            problem = registry.check_fields(serial, access)
            if problem:
                raise Refused(400, problem)
            old = registry.load().get(serial)
            # as the CLI's add: a fresh entry (adding the printer again also clears its TLS pin)
            registry.add_bambu(serial, name or (old.name if old else ""), model or (old.model if old else ""), ip, access)
            manager.sync()
            return {"serial": serial, "replaced": old is not None and old.configured, "note": note}
        r = await anyio.to_thread.run_sync(run)
        self.audit(request, f"printer {r['serial']} {'replaced' if r['replaced'] else 'added'}")
        return {"ok": True, "serial": r["serial"], **({"note": r["note"]} if r["note"] else {})}

    async def printer_code(self, request: Request, body: dict):
        serial, access = self._serial(request), self._access_code(body)

        def run() -> None:
            p = registry.load().get(serial)
            if p is not None and p.family == "klipper":
                raise Refused(400, "a Klipper printer has no Access Code (a Moonraker API key instead, when it wants one)")
            manager = self._manager()
            if p is None:
                raise Refused(404, "no such printer")
            registry.set_code(serial, access, replace=True)
            manager.sync()
        await anyio.to_thread.run_sync(run)
        self.audit(request, f"printer {serial} access code replaced")
        return {"ok": True}

    async def printer_test(self, request: Request, body: dict):
        """Bambu: a TLS handshake with the printer (nothing is sent, nothing is pinned); Klipper: Moonraker's
        /printer/info. And the connection's state."""
        from .bridge import tlspin
        serial = self._serial(request)
        await anyio.to_thread.run_sync(self._entry, serial)   # 404 / 409 before the gap is spent
        self._gap()

        def run() -> dict:
            p = self._entry(serial)
            manager = self.printers
            state = manager.state(serial) if p.configured else "not_configured"
            if p.family == "klipper":
                return self._moonraker_test(p, state)
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

    @staticmethod
    def _moonraker_test(p: registry.Printer, state: str) -> dict:
        where = f"{p.host}:{p.port}"
        try:
            info = Moonraker(p.host, p.port, p.api_key, timeout=5.0).info()
        except Unauthorized:
            return {"reachable": True, "state": state,
                    "text": f"Moonraker at {where} answers but wants an API key: set it on this printer's row"}
        except Offline:
            return {"reachable": False, "state": state,
                    "text": f"no answer from Moonraker at {where}: check that the printer is on and the address"}
        except MoonrakerError as e:   # a fixed line: the answer's own text is not shown to a page viewer
            why = " (HTTP 404)" if isinstance(e, NotFound) else ""
            return {"reachable": False, "state": state, "text": f"{where} answers, but not as Moonraker{why}"}
        klippy = info.get("state") if isinstance(info, dict) else None
        klippy = klippy if isinstance(klippy, str) and klippy.isprintable() else "unknown"
        return {"reachable": True, "state": state, "text": f"Moonraker at {where} answers; Klipper is {klippy[:32]}"}

    async def printer_forget(self, request: Request, body: dict):
        serial = self._serial(request)

        def run() -> bool:
            self._entry(serial)
            gone = registry.remove(serial)
            self.printers.sync()
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

    async def local_intake_token(self, request: Request, body: dict):
        had = _present("local_intake_token")
        await self._helper({"op": "local_intake_token_set", "code": body["code"], "token": body.get("token")})
        self.audit(request, "local reader token replaced" if had else "local reader token set")
        return {"ok": True, "set": True}

    async def local_intake_token_remove(self, request: Request, body: dict):
        r = await self._helper({"op": "local_intake_token_remove", "code": body["code"]})
        if r.get("removed"):
            self.audit(request, "local reader token removed")
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
                pr = pairing.issue(device_hint=KINDS[kind], scope="station" if kind == "station" else None)
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
        if any(d["id"] == did and d["name"] in BUILT_IN_DEVICES for d in await anyio.to_thread.run_sync(pairing.devices)):
            raise Refused(409, "this is one of the server's own pairings (its phone web app, or its command line) reaching "
                               "its API; it pairs again when next needed, so there is nothing to unpair")
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


def setup_serial(ip: str, timeout: float = 5) -> str | None:   # `ip`: an address or a name
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
