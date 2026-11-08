"""The `web` process's ASGI app: the remote MCP endpoint (+ OAuth), /login, /health and the phone intake app.

    build_app(cfg) -> ASGI app
      /mcp                      MCP streamable HTTP (bearer token from the OAuth flow; Host = the public host,
                                Origin = claude.ai / claude.com only)
      /authorize /token /register /revoke /.well-known/...   the SDK's OAuth routes over auth.Provider
      /login                    the passphrase page that approves a sign-in (LAN only)
      /health                   "ok"
      /intake ...               the phone web app (LAN only, no sign-in; POSTs need its Origin)
      /reader/...               the bench NFC reader's API (LAN only, reader token; reader.py)

The whole app is wrapped in `auth.lan_only`, so /authorize, /login, /intake and /reader answer the LAN only. Wrong
passphrases at /login count in its Lockout. State: `FK_STATE/web/oauth.json`; the passphrase hash
`FK_ETC/web_passphrase` (set with `filament-kit web passphrase`).
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from .. import __version__, config
from ..spoolman import Spoolman
from . import auth, mcp_tools, reader
from .intake_app import IntakeApp

ALLOWED_ORIGINS = ["https://claude.ai", "https://claude.com"]


class NotConfigured(Exception):
    pass


def public_url(cfg: dict) -> str:
    url = str((cfg.get("web") or {}).get("public_url") or "").rstrip("/")
    u = urlparse(url)
    if u.scheme != "https" or not u.netloc:
        raise NotConfigured("web.public_url is not set to an https URL (e.g. https://mcp.example.com/filament)")
    return url


def passphrase_file() -> Path:
    return config.paths().etc / "web_passphrase"


def oauth_file() -> Path:
    """In the web unit's own state folder (/var/lib/filament-kit-web; apply's web_state moved it there)."""
    return config.paths().web / "oauth.json"


def transport_security(public: str) -> TransportSecuritySettings:
    host = urlparse(public).netloc
    return TransportSecuritySettings(allowed_hosts=[host, host + ":*"], allowed_origins=list(ALLOWED_ORIGINS))


def build_app(cfg: dict | None = None, *, sm: Spoolman | None = None, claude=None, store: auth.Store | None = None,
              lockout: auth.Lockout | None = None, tools: mcp_tools.Tools | None = None, kit_api=None,
              reader_queue=None):
    cfg = cfg if cfg is not None else config.load()
    public = public_url(cfg)
    lan = (cfg.get("web") or {}).get("lan") or []
    sm = sm if sm is not None else Spoolman(cfg["spoolman_url"])
    store = store if store is not None else auth.Store(oauth_file())
    lockout = lockout if lockout is not None else auth.Lockout()
    tools = tools if tools is not None else mcp_tools.Tools(sm, kit_api=kit_api, kit_writes=True)

    mcp = MCPServer("filament-kit", title="Filament inventory", instructions=mcp_tools.instructions(cfg),
                    version=__version__, auth_server_provider=auth.Provider(store, public),
                    auth=auth.auth_settings(public))
    mcp_tools.register(mcp, tools)

    async def health(request: Request):
        return PlainTextResponse("ok")

    routes = [*auth.login_routes(store, public, passphrase_file(), lan_cidrs=lan, lockout=lockout),
              *IntakeApp(tools, public_url=public, lan_cidrs=lan,
                         claude=claude, kit_api=kit_api).routes(),
              *reader.Reader(tools, sm, lan_cidrs=lan, queue=reader_queue).routes()]
    mcp.custom_route("/health", methods=["GET"])(health)
    for r in routes:
        mcp.custom_route(r.path, methods=sorted(r.methods - {"HEAD"} if r.methods else ["GET"]))(r.endpoint)
    app = mcp.streamable_http_app(transport_security=transport_security(public))
    return auth.lan_only(with_root_path(app, urlparse(public).path.rstrip("/")), lan)


def with_root_path(app, prefix: str):
    """Run `app` under the public path (`/filament` of https://host/filament), as uvicorn's root_path does: nginx
    strips the prefix, so each request gets `root_path` = prefix and the prefix back in front of `path` (ASGI: path
    includes root_path). Starlette routes on the path without root_path and builds URLs (slash redirects,
    url_for) with it, so a redirect keeps the prefix. No prefix (a public URL at the host root): `app` as is."""
    if not prefix:
        return app

    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket") and not scope.get("root_path"):
            scope = {**scope, "root_path": prefix, "path": prefix + scope["path"],
                     **({"raw_path": prefix.encode() + scope["raw_path"]} if scope.get("raw_path") else {})}
        await app(scope, receive, send)
    return wrapped
