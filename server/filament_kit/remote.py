"""Remote module (spec 4.4): an nginx path router with a certbot certificate, for the web unit.

The kit installs nginx files, a placeholder certificate and certbot hooks, and PRINTS the firewall and
port-forward rules the owner needs. It never applies them: nothing here (or in install/remote/) runs a
firewall tool or touches a router. Port 80 for certbot is the owner's to open; certbot (standalone) binds
it for the run.
"""
from __future__ import annotations

import ipaddress
import os
import re
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import config
from .modules import ModuleError

HOOK = "/usr/local/sbin/filament-kit-acme-hook"
MCP_ROUTE = "/usr/local/sbin/mcp-route"
ROUTER_CONF = "/etc/nginx/conf.d/filament-kit-router.conf"
PROXY_CONF = "/etc/nginx/mcp-proxy.conf"
ROUTE_DIR = "/etc/nginx/mcp.d"
ROUTER_DIR = "/etc/mcp-router"
TLS_DIR = ROUTER_DIR + "/tls"
TIMER_DROPIN = "/etc/systemd/system/certbot.timer.d/acme-window.conf"
DEPLOY_HOOK_FILE = "/etc/letsencrypt/renewal-hooks/deploy/filament-kit"
MARK = "written by mcp-route"  # first line of every route mcp-route writes; the only files we ever remove
DEFAULT_ROUTE = "filament"
ANTHROPIC = "160.79.104.0/21 2607:6bc0::/48"  # the same ranges the kit's units allow for Claude

_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_WINDOW = re.compile(r"^(\d{1,2}):(\d{2})(?: ([A-Za-z0-9_+/-]+))?$")


def settings(cfg: dict) -> dict:
    """Validated remote settings from config; raises ModuleError naming the bad key."""
    rem = config._merge(config.DEFAULTS["remote"], cfg.get("remote") or {})
    web = config._merge(config.DEFAULTS["web"], cfg.get("web") or {})
    pu = urlparse(str(web.get("public_url") or ""))
    host = str(rem.get("hostname") or pu.hostname or "").strip().lower()
    if not host or not _HOST.match(host):
        raise ModuleError(f"remote.hostname {host!r} is not a host name")
    parts = [p for p in pu.path.split("/") if p]
    route = parts[0] if parts else DEFAULT_ROUTE
    if not _NAME.match(route):
        raise ModuleError(
            f"web.public_url path {route!r}: the route name is lowercase letters, digits and dashes (2-31)")
    email = rem.get("email")
    if email and not _EMAIL.match(str(email)):
        raise ModuleError(f"remote.email {email!r} is not an email address")
    window = rem.get("acme_window")
    if window:
        m = _WINDOW.match(str(window).strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ModuleError(f"remote.acme_window {window!r}: use HH:MM or 'HH:MM Zone/Name'")
    lan = []
    for net in web.get("lan") or []:
        try:
            lan.append(str(ipaddress.ip_network(str(net), strict=False)))
        except ValueError as e:
            raise ModuleError(f"web.lan entry {net!r}: {e}") from e
    return {"hostname": host, "route": route, "port": int(web["port"]), "email": email or None,
            "window": str(window).strip() if window else None, "lan": lan}


def timer_dropin(window: str) -> str:
    """certbot.timer drop-in that pins the renewal to the owner's ACME window (HH:MM[ Zone])."""
    m = _WINDOW.match(window)
    when = f"{int(m.group(1)):02d}:{m.group(2)}:00" + (f" {m.group(3)}" if m.group(3) else "")
    return ("# Pinned to the time your router opens port 80 (remote.acme_window)\n"
            f"[Timer]\nOnCalendar=\nOnCalendar=*-*-* {when}\nRandomizedDelaySec=0\n")


def _remote_dir(resources: Path) -> Path:
    d = Path(resources) / "remote"
    if not d.is_dir():  # `filament-kit remote firewall` before any apply: use the source checkout
        d = Path(__file__).resolve().parents[2] / "install" / "remote"
    return d


def read_resource(resources: Path, name: str) -> str:
    return (_remote_dir(resources) / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def sandbox_text(resources: Path, lan: list[str]) -> str:
    return read_resource(resources, "nginx-sandbox.conf").replace("@LAN@", " ".join(lan)).rstrip() + "\n"


def route_name(cfg: dict) -> str:
    """The route's name from web.public_url's path (default 'filament'); no validation, for the off path."""
    pu = urlparse(str((cfg.get("web") or {}).get("public_url") or ""))
    parts = [p for p in pu.path.split("/") if p]
    return parts[0] if parts and _NAME.match(parts[0]) else DEFAULT_ROUTE


def firewall_text(s: dict, resources: Path) -> str:
    """What the owner must set up by hand, from settings(). Printed only."""
    host = s["hostname"]
    window = s["window"]
    lan = s["lan"] or ["(no LAN ranges set in web.lan)"]
    when = (f"only during the certbot window, {window} (remote.acme_window)" if window
            else "only while certbot runs (set remote.acme_window to pin a time)")
    return "\n".join([
        "",
        f"==> Remote access for https://{host}/{s['route']}/ : set these up on your firewall and router",
        "The kit will not change any firewall, router or port forward. These are the rules it needs:",
        "",
        f"  443/tcp  in  -> this machine   from {ANTHROPIC} (Claude) and your LAN {' '.join(lan)}",
        f"  80/tcp   in  -> this machine   {when}; any source, closed the rest of the time",
        f"  DNS      {host} must resolve to your public address (and, at home, to this machine)",
        "",
        "Port 80 is only for certbot: it binds :80 itself during the run (nginx steps aside meanwhile).",
        "Open it, then run:  sudo filament-kit remote issue",
        "Until that succeeds, nginx serves a self-signed placeholder certificate.",
        "",
        "Optional hardening, save as /etc/systemd/system/nginx.service.d/filament-kit.conf",
        "then run: sudo systemctl daemon-reload && sudo systemctl restart nginx",
        "------------------------------------------------------------",
        sandbox_text(resources, s["lan"]).rstrip(),
        "------------------------------------------------------------",
        ""])


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def issue(cfg: dict, *, run: Callable[[list[str]], None] | None = None) -> int:
    """`filament-kit remote issue`: certbot standalone for remote.hostname, with the kit's hooks."""
    from .modules import enabled
    if run is None:
        from .apply import run_checked as run
    if "remote" not in enabled(cfg):
        print("The remote module is off. Turn it on first: sudo filament-kit modules enable remote")
        return 1
    if not _is_root():
        print("error: run this as root: sudo filament-kit remote issue")
        return 1
    try:
        s = settings(cfg)
    except ModuleError as e:
        print(f"error: {e}")
        return 1
    cmd = ["certbot", "certonly", "--standalone", "--non-interactive", "--agree-tos", "--keep-until-expiring",
           "--cert-name", s["hostname"], "-d", s["hostname"]]
    cmd += ["--email", s["email"]] if s["email"] else ["--register-unsafely-without-email"]
    cmd += ["--pre-hook", f"{HOOK} pre", "--post-hook", f"{HOOK} post", "--deploy-hook", f"{HOOK} deploy"]
    print(f"certbot will bind port 80 on this machine now. The kit does not open it: make sure port 80 "
          f"reaches this machine (run `filament-kit remote firewall` for the rules).\n"
          f"nginx stops for the run and starts again after.")
    try:
        run(cmd)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"certbot failed: {e}\nfix: check that {s['hostname']} resolves here and port 80 is open, then retry")
        return 1
    print(f"Certificate issued for {s['hostname']}.")
    return 0


def firewall(cfg: dict) -> int:
    try:
        print(firewall_text(settings(cfg), config.paths().opt / "resources"))
    except ModuleError as e:
        print(f"error: {e}")
        return 1
    return 0
