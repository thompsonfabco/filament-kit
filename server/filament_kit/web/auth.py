"""Sign-in for the `web` module (Claude's connector): OAuth 2.1 provider + store, passphrase, LAN-only routes.

A port of filament-ops vm/server.py (Provider, Store, LanOnly, /login), unchanged in behaviour, so a migrated
oauth.json keeps the Claude connector signed in. Claude registers itself (DCR, only its own callbacks), then the
owner approves once on /login, which only answers the home LAN and needs the passphrase. Tokens and codes are
stored as sha256 hashes in one JSON file (0600). The phone web app has no sign-in.

Everything comes in as parameters (public URL, LAN ranges, file paths); the caller reads the config.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import html
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urlparse

import anyio
from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
                                      RefreshToken, RegistrationError, TokenError, construct_redirect_uri)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

__all__ = ["AuthorizationParams", "CALLBACKS", "Lockout", "Provider", "Store", "auth_settings", "check_passphrase",
           "hash_passphrase", "is_lan", "lan_only", "login_routes", "parse_lan"]

CALLBACKS = frozenset({"https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"})
ACCESS_TTL, REFRESH_TTL, CODE_TTL, PENDING_TTL = 3600, 60 * 86400, 300, 600
SCOPE = "filament"
# registration and /token answer Anthropic's whole range (any Claude user's web fetch or sandbox can reach them),
# so registrations are bounded: one that never got a token is dropped after an hour, oldest first when full.
# /authorize and /login only answer the LAN (the browser doing the sign-in is always at home).
MAX_CLIENTS, MAX_PENDING, IDLE_CLIENT_TTL = 50, 20, 3600
REUSE_GRACE = 30  # a rotated refresh token seen again later than this means it leaked: end that client's tokens
LOCK_MAX, LOCK_WINDOW = 5, 600
MIN_PASSPHRASE = 12
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1, "maxmem": 2 ** 26}
# "sessions" held the phone web app's sign-ins (gone: the app has no sign-in); kept so old files load and
# the entries expire away.
_KEYS = ("clients", "codes", "access", "refresh", "used", "sessions")
_EXPIRING = ("codes", "access", "refresh", "used", "sessions")


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _origin(public_url: str) -> str:
    return "{0.scheme}://{0.netloc}".format(urlparse(public_url))


# ---------- LAN (lan.py: the kit server's /setup page uses the same checks) ----------

from ..lan import IPV6_HINT, Networks, is_lan, over_ipv6, parse_lan  # noqa: E402,F401  (re-exported)


# ---------- store ----------

class Store:
    """Clients, codes and hashed tokens in one JSON file (single user, tiny volume). Same format as ops oauth.json:
    clients, codes, access, refresh, used (rotated-out refresh token hashes), sessions (web app sign-ins)."""

    def __init__(self, path: Path | str):
        self.path, self.lock = Path(path), threading.Lock()
        self.d: dict[str, dict[str, Any]] = (json.loads(self.path.read_text(encoding="utf-8"))
                                             if self.path.exists() else {})
        for k in _KEYS:
            self.d.setdefault(k, {})
        self.pending: dict[str, dict[str, Any]] = {}  # authorize requests waiting on /login (memory only)

    def save(self) -> None:
        """Drop expired entries and write atomically; the file is 0600 from the moment it exists."""
        now = time.time()
        for k in _EXPIRING:
            self.d[k] = {t: v for t, v in self.d[k].items() if (v.get("expires_at") or now + 1) > now}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.d, f)
            os.chmod(tmp, 0o600)  # O_CREAT's mode does not apply to a leftover tmp file
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


# ---------- OAuth provider ----------

class Provider:
    """mcp OAuthAuthorizationServerProvider over a Store."""

    def __init__(self, store: Store, public_url: str):
        self.store, self.public = store, public_url.rstrip("/")

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        c = self.store.d["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(c) if c else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = {str(u) for u in client_info.redirect_uris or []}
        if not uris or not uris <= CALLBACKS:
            raise RegistrationError("invalid_redirect_uri", "only Claude's connector callback is accepted")
        st = self.store
        with st.lock:
            # forget clients that never got a token within the hour (abandoned or foreign registrations); when
            # still full, make room by dropping the oldest of those, so a flood can't lock the real connector out
            in_use = {v["client_id"] for v in st.d["refresh"].values()}
            now = time.time()
            idle = sorted((v.get("client_id_issued_at") or 0, k) for k, v in st.d["clients"].items()
                          if k not in in_use)
            drop = [k for t, k in idle if now - t >= IDLE_CLIENT_TTL]
            spare = [k for t, k in idle if k not in drop]
            drop += spare[:max(0, len(st.d["clients"]) - len(drop) - MAX_CLIENTS + 1)]
            for k in drop:
                del st.d["clients"][k]
            if len(st.d["clients"]) >= MAX_CLIENTS:
                raise RegistrationError("invalid_client_metadata", "too many connected clients")
            st.d["clients"][client_info.client_id] = client_info.model_dump(mode="json")
            st.save()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        st, now = self.store, time.time()
        rid = secrets.token_urlsafe(24)
        st.pending = {k: v for k, v in st.pending.items() if v["t"] > now - PENDING_TTL}
        if len(st.pending) >= MAX_PENDING:
            raise AuthorizeError("temporarily_unavailable", "too many sign-ins in progress; try again in 10 minutes")
        st.pending[rid] = {"t": now, "client_id": client.client_id,
                           "client_name": client.client_name or "unknown client",
                           "params": params.model_dump(mode="json")}
        return f"{self.public}/login?{urlencode({'req': rid})}"

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        c = self.store.d["codes"].get(_h(authorization_code))
        if not c or c["client_id"] != client.client_id or c["expires_at"] < time.time():
            return None
        return AuthorizationCode(code=authorization_code, **{k: v for k, v in c.items() if k != "code"})

    def _issue(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        st = self.store
        access, refresh, now = secrets.token_urlsafe(32), secrets.token_urlsafe(40), int(time.time())
        st.d["access"][_h(access)] = {"client_id": client_id, "scopes": scopes, "resource": resource,
                                      "expires_at": now + ACCESS_TTL}
        st.d["refresh"][_h(refresh)] = {"client_id": client_id, "scopes": scopes, "resource": resource,
                                        "expires_at": now + REFRESH_TTL, "access": _h(access)}
        st.save()
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL, refresh_token=refresh,
                          scope=" ".join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        with self.store.lock:
            if self.store.d["codes"].pop(_h(authorization_code.code), None) is None:
                raise TokenError("invalid_grant", "code already used")
            return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        st, key = self.store, _h(refresh_token)
        r = st.d["refresh"].get(key)
        if not r:
            used = st.d["used"].get(key)
            if used and time.time() - used["at"] > REUSE_GRACE:  # replayed: someone else holds a copy
                self._end_client(used["client_id"])
            return None
        if r["client_id"] != client.client_id or r["expires_at"] < time.time():
            return None
        return RefreshToken(token=refresh_token, client_id=r["client_id"], scopes=r["scopes"],
                            expires_at=r["expires_at"], resource=r.get("resource"))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        st = self.store
        with st.lock:
            old = st.d["refresh"].pop(_h(refresh_token.token), None)  # rotate
            if old is None:
                raise TokenError("invalid_grant", "refresh token already used")
            st.d["access"].pop(old.get("access", ""), None)
            st.d["used"][_h(refresh_token.token)] = {"client_id": client.client_id, "at": time.time(),
                                                     "expires_at": old["expires_at"]}
            return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.resource)

    def _end_client(self, client_id: str) -> None:
        """Revoke every token of a client whose rotated-out refresh token came back (the copy leaked)."""
        st = self.store
        with st.lock:
            for k in ("access", "refresh"):
                st.d[k] = {t: v for t, v in st.d[k].items() if v["client_id"] != client_id}
            st.save()
        print(f"refresh token replay for client {client_id}: all its tokens revoked; reconnect in Claude",
              file=sys.stderr, flush=True)

    async def load_access_token(self, token: str) -> AccessToken | None:
        a = self.store.d["access"].get(_h(token))
        if not a or a["expires_at"] < time.time():
            return None
        return AccessToken(token=token, client_id=a["client_id"], scopes=a["scopes"], expires_at=a["expires_at"],
                           resource=a.get("resource"))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        st = self.store
        with st.lock:
            key = _h(token.token)
            r = st.d["refresh"].pop(key, None)
            st.d["access"].pop(key, None)
            if r:
                st.d["access"].pop(r.get("access", ""), None)
            for k, v in list(st.d["refresh"].items()):  # revoking an access token ends its refresh token too
                if v.get("access") == key:
                    st.d["refresh"].pop(k)
            st.save()


def auth_settings(public_url: str) -> AuthSettings:
    public = public_url.rstrip("/")
    return AuthSettings(issuer_url=public, resource_server_url=f"{public}/mcp", validate_token_resource=False,
                        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE],
                                                                              default_scopes=[SCOPE]),
                        revocation_options=RevocationOptions(enabled=True), required_scopes=[SCOPE])


# ---------- passphrase + lockout ----------

def hash_passphrase(text: str) -> str:
    """'salt_hex digest_hex', salted scrypt (the format ops set_passphrase.py writes). ValueError for a passphrase
    shorter than MIN_PASSPHRASE characters: the login form faces the LAN, and five guesses per ten minutes only
    hold against a passphrase worth guessing."""
    if len(text or "") < MIN_PASSPHRASE:
        raise ValueError(f"the passphrase must be at least {MIN_PASSPHRASE} characters")
    salt = secrets.token_bytes(16)
    return f"{salt.hex()} {hashlib.scrypt(text.encode(), salt=salt, **SCRYPT).hex()}"


def check_passphrase(text: str, file: Path | str) -> bool | None:
    """True/False for a right/wrong passphrase; None (falsy) when no passphrase is set or the file is unreadable."""
    try:
        salt, digest = Path(file).read_text(encoding="utf-8").split()
        salt_b = bytes.fromhex(salt)
    except (OSError, ValueError):
        return None
    got = hashlib.scrypt(text.encode(), salt=salt_b, **SCRYPT).hex()
    return hmac.compare_digest(got, digest)


class Lockout:
    """At most LOCK_MAX wrong passphrases per LOCK_WINDOW seconds, counted across every sign-in form (one shared
    instance for /login and the web app). Global, not per IP: only the LAN can reach the forms anyway.

    A sign-in calls attempt() before the (slow) passphrase check: the attempt is counted at once, under the lock,
    so parallel guesses cannot all pass the check-then-count gap (A-M1); a right passphrase release()s it."""

    def __init__(self, max_fails: int = LOCK_MAX, window: float = LOCK_WINDOW):
        self.max, self.window, self.fails = max_fails, window, []   # fails: [(time, attempt id)]
        self._lock = threading.Lock()
        self._ids = itertools.count()

    def _prune(self) -> None:
        now = time.time()
        self.fails[:] = [f for f in self.fails if f[0] > now - self.window]

    def blocked(self) -> bool:
        with self._lock:
            self._prune()
            return len(self.fails) >= self.max

    def attempt(self) -> int | None:
        """Count one sign-in attempt; None (and nothing counted) when locked out. Pass the result to release()
        when the passphrase was right, or the check could not run."""
        with self._lock:
            self._prune()
            if len(self.fails) >= self.max:
                return None
            n = next(self._ids)
            self.fails.append((time.time(), n))
            return n

    def release(self, attempt: int | None) -> None:
        with self._lock:
            self.fails[:] = [f for f in self.fails if f[1] != attempt]

    def fail(self) -> None:
        with self._lock:
            self.fails.append((time.time(), next(self._ids)))


# ---------- sign-in page (LAN only) ----------

# no scripts, no framing, nothing cached; the form may only post here and then go on to Claude's callback
PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; "
                               "form-action 'self' " + " ".join(sorted(CALLBACKS)),
    "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"}
HOME_ONLY = "<p>Sign-in is only available from the home network.</p>"


def _home_only(client: str) -> str:
    return HOME_ONLY + (f"<p>{IPV6_HINT}</p>" if over_ipv6(client) else "")


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Filament MCP sign-in</title>"
        "<style>body{font:16px system-ui;max-width:28rem;margin:3rem auto;padding:0 1rem}input,button{font:inherit;"
        "padding:.6rem;width:100%;box-sizing:border-box;margin:.4rem 0}</style>" + body, status_code=status,
        headers=PAGE_HEADERS)


def _lan_path(path: str) -> bool:
    path = path.rstrip("/")
    return (path in ("/authorize", "/login", "/intake", "/reader") or path.startswith("/intake/")
            or path.startswith("/reader/"))


def lan_only(app: Any, lan_cidrs: Iterable[str]) -> Any:
    """ASGI wrapper: the SDK's /authorize, /login and the intake web app only answer the LAN. Claude's servers never
    call them; the owner's own browser does, from home. This keeps outsiders from parking sign-in requests
    (MAX_PENDING) or starting one to lure the owner into approving."""
    nets = parse_lan(lan_cidrs)

    async def wrapped(scope, receive, send):
        if scope["type"] == "http" and _lan_path(scope.get("path", "")) \
                and not is_lan((scope.get("client") or ("",))[0], nets):
            await _page(_home_only((scope.get("client") or ("",))[0]), 403)(scope, receive, send)
            return
        await app(scope, receive, send)

    return wrapped


def login_routes(store: Store, public_url: str, passphrase_file: Path | str, *, lan_cidrs: Iterable[str] = (),
                 lockout: Lockout) -> list[Route]:
    """The /login page that turns a pending /authorize request into a code. It checks the LAN itself too (with no
    lan_cidrs only loopback counts as home). `lockout` is the web app's own Lockout, so both forms share one
    failure count (required: a private count per form would double the guesses)."""
    nets, origin = parse_lan(lan_cidrs), _origin(public_url)

    async def login(request: Request) -> Response:
        if not is_lan(request.client.host if request.client else "", nets):
            return _page(_home_only(request.client.host if request.client else ""), 403)
        if request.method == "POST" and request.headers.get("origin") != origin:  # another site posting via a browser
            return _page("<p>This form only works from its own page. Start again from Claude.</p>", 403)
        form = await request.form() if request.method == "POST" else {}
        rid = str(form.get("req") or request.query_params.get("req", ""))
        pend = store.pending.get(rid)
        if not pend or pend["t"] < time.time() - PENDING_TTL:
            return _page("<p>This sign-in request expired. Start again from Claude.</p>", 400)
        who = html.escape(pend["client_name"])
        if request.method == "GET":
            return _page(f"<h2>Allow {who}?</h2><p>It will be able to read and change your Spoolman inventory and "
                         f"slicer presets.</p><form method=post><input type=hidden name=req value='{html.escape(rid)}'>"
                         "<input type=password name=passphrase placeholder=Passphrase autofocus>"
                         "<button>Allow</button></form>")
        attempt = lockout.attempt()             # counted before the check (A-M1)
        if attempt is None:
            return _page("<p>Too many wrong passphrases. Wait 10 minutes.</p>", 429)
        ok = await anyio.to_thread.run_sync(check_passphrase, str(form.get("passphrase", "")), passphrase_file)
        if ok is None:
            lockout.release(attempt)
            return _page("<p>No passphrase is set on the server yet (run: filament-kit web passphrase).</p>", 503)
        if not ok:
            return _page("<p>Wrong passphrase.</p><p><a href='login?req=" + html.escape(rid) + "'>Try again</a></p>", 401)
        lockout.release(attempt)
        store.pending.pop(rid, None)
        p, now = pend["params"], time.time()
        code = secrets.token_urlsafe(32)
        with store.lock:
            store.d["codes"][_h(code)] = {"scopes": p.get("scopes") or [SCOPE], "expires_at": now + CODE_TTL,
                                          "client_id": pend["client_id"], "code_challenge": p["code_challenge"],
                                          "redirect_uri": p["redirect_uri"],
                                          "redirect_uri_provided_explicitly": p["redirect_uri_provided_explicitly"],
                                          "resource": p.get("resource")}
            store.save()
        return RedirectResponse(construct_redirect_uri(p["redirect_uri"], code=code, state=p.get("state")), 302)

    return [Route("/login", login, methods=["GET", "POST"])]
