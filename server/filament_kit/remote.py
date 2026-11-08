"""Remote module (spec 4.4): an nginx path router with a certbot certificate, for the web unit.

The kit installs nginx files, a placeholder certificate and certbot hooks, and PRINTS the firewall and
port-forward rules the owner needs. It never applies them: nothing here (or in install/remote/) runs a
firewall tool or touches a router. Port 80 for certbot is the owner's to open; certbot (standalone) binds
it for the run.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
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
PLACEHOLDER_MARK = TLS_DIR + "/placeholder.sha256"  # the hash of the certificate the kit made itself
PLACEHOLDER_DAYS = 825  # iOS refuses a server certificate over 825 days, or one without serverAuth
RENEW_DAYS = 30         # at an apply, a placeholder this close to its end is made again; `web status` warns as well
LEGACY_DAYS = 31        # up to 0.4.x the placeholder lasted 30 days and had no mark
TIMER_DROPIN = "/etc/systemd/system/certbot.timer.d/acme-window.conf"
DEPLOY_HOOK_FILE = "/etc/letsencrypt/renewal-hooks/deploy/filament-kit"
KIT_ROUTES = ROUTER_DIR + "/kit-routes"  # names of the routes this kit added, one per line
# In the first line of every route the kit's mcp-route writes. The filament-ops router's mcp-route writes
# OLD_MARK, as the kit's did before v0.3.0, so a file with OLD_MARK is the kit's only when kit-routes lists it.
MARK = "written by filament-kit mcp-route"
OLD_MARK = "written by mcp-route"
DEFAULT_ROUTE = "filament"
ANTHROPIC = "160.79.104.0/21 2607:6bc0::/48"  # the same ranges the kit's units allow for Claude

_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_WINDOW = re.compile(r"^(\d{1,2}):(\d{2})(?: ([A-Za-z0-9_+/-]+))?$")


def make_placeholder(host: str, now: datetime.datetime | None = None) -> tuple[bytes, bytes]:
    """(certificate, key) in PEM: self-signed for `host`, lasting PLACEHOLDER_DAYS, with serverAuth."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    now = now or datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=PLACEHOLDER_DAYS))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption()))


def _names(cert) -> set[str]:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    out = {a.value for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)}
    try:
        out |= set(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                   .get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound:
        pass
    return out


def placeholder_due(cert_pem: bytes | None, mark: str | None, host: str,
                    now: datetime.datetime | None = None) -> str | None:
    """Why the kit should make its placeholder now, or None. Only a certificate that is provably the kit's own is ever
    replaced: its hash is in the mark, or (from before the mark) it is self-issued for this host and lasted LEGACY_DAYS
    or less. Anything else, a Let's Encrypt certificate or one placed by hand, however old, is left alone."""
    if cert_pem is None:
        return "there is none yet"
    from cryptography import x509
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except ValueError:
        return None
    start, end = cert.not_valid_before_utc, cert.not_valid_after_utc
    if mark is None or not mark.strip():
        ours = (cert.issuer == cert.subject and end - start <= datetime.timedelta(days=LEGACY_DAYS)
                and host in _names(cert))
        return "the placeholder from an earlier version lasts only 30 days" if ours else None
    if not hmac.compare_digest(hashlib.sha256(cert_pem).hexdigest(), mark.strip()):
        return None
    if host not in _names(cert):
        return "the host name changed"
    if end - now <= datetime.timedelta(days=RENEW_DAYS):
        return f"it ends within {RENEW_DAYS} days"
    return None


def served_certificate(port: int = 443, timeout: float = 3.0) -> dict | None:
    """What nginx serves here, by a handshake: {self_signed, not_after (a datetime, UTC)}. The certificate's folder is
    root's and this runs as the service user. None when nothing answers there."""
    from cryptography import x509

    from .bridge import tlspin
    try:
        cert = x509.load_der_x509_certificate(tlspin._leaf_der("127.0.0.1", port, timeout))
    except (OSError, ValueError):
        return None
    return {"self_signed": cert.issuer == cert.subject, "not_after": cert.not_valid_after_utc}


def certificate_warning(info: dict | None, now: datetime.datetime | None = None) -> tuple[bool, str, str] | None:
    """(expired, text, fix) when the served certificate ends within RENEW_DAYS, else None. For a self-signed one an
    apply is the fix (one the kit didn't make it leaves alone); certbot looks after the others."""
    if info is None:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    left = info["not_after"] - now
    if left > datetime.timedelta(days=RENEW_DAYS):
        return None
    day = info["not_after"].strftime("%Y-%m-%d")
    kind = "self-signed certificate" if info["self_signed"] else "certificate"
    fix = ("sudo filament-kit modules apply makes a new placeholder; the phone then asks you to accept it again"
           if info["self_signed"] else "sudo certbot renew; see the remote section of the guide")
    return (left.total_seconds() <= 0, f"the web address's {kind} {'ended' if left.total_seconds() <= 0 else 'ends'} "
                                       f"on {day}", fix)


def settings(cfg: dict) -> dict:
    """Validated remote settings from config; raises ModuleError naming the bad key."""
    rem = config._merge(config.DEFAULTS["remote"], cfg.get("remote") or {})
    web = config._merge(config.DEFAULTS["web"], cfg.get("web") or {})
    pu = urlparse(str(web.get("public_url") or ""))
    set_host = str(rem.get("hostname") or "").strip().lower()
    if set_host and pu.hostname and set_host != pu.hostname.lower():
        raise ModuleError(f"remote.hostname {set_host!r} differs from the host of web.public_url "
                          f"{pu.hostname.lower()!r}; make them the same")
    host = set_host or (pu.hostname or "").lower()
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
            f"[Timer]\nOnCalendar=\nOnCalendar=*-*-* {when}\nRandomizedDelaySec=0\nPersistent=false\n")


def _remote_dir(resources: Path) -> Path:
    d = Path(resources) / "remote"
    if not d.is_dir():  # `filament-kit remote firewall` before any apply: use the source checkout
        d = Path(__file__).resolve().parents[2] / "install" / "remote"
    return d


def read_resource(resources: Path, name: str) -> str:
    return (_remote_dir(resources) / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def sandbox_text(resources: Path, lan: list[str]) -> str:
    return read_resource(resources, "nginx-sandbox.conf").replace("@LAN@", " ".join(lan)).rstrip() + "\n"


def is_kit_route(text: str, name: str, listed) -> bool:
    """True when a route file (its text) is one the kit wrote: the kit's marker, or the old shared marker on a
    route the kit's kit-routes file lists. A route the ops router wrote is never the kit's."""
    first = text.split("\n", 1)[0]
    return MARK in first or (OLD_MARK in first and name in set(listed))


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
    except OSError as e:
        print(f"error: cannot read the remote files ({e})\n"
              "fix: run ./install.sh again (they live in /opt/filament-kit/resources/remote)")
        return 1
    return 0
