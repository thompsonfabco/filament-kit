"""Trusted computers for the setup page: after the setup code was typed once, a browser may be told to stand in for it.

The browser holds a long random token in an HttpOnly, Secure, SameSite=Strict cookie; an address or a MAC wouldn't do, since
addresses change and a router hides MACs. `/etc/filament-kit/setup_trusted.xml` (root only, 600, under a flock, rewritten by a
temp file and a rename) holds only the token's hash, with a name the owner can change, when it was made and last seen, its last
address and when it runs out. Only the root helper reads or writes it, as with the setup code's hash, so the service user can't
add a computer of its own.

90 days, renewed on use. Turning the feature off, or revoking, takes effect at the next request; off also forgets every computer,
so turning it on again trusts nothing by surprise. It stands in for the code and nothing else: what asks for a second
confirmation still asks. Nothing here logs or prints a token.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as DET
from defusedxml import DefusedXmlException

from . import config, setup_code

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the helper only runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)

FILE = "setup_trusted.xml"
PREFIX = "trusted:"             # what stands in for the code in a request to the helper; a code is digits
COOKIE = "fk_setup_trusted"
LIFETIME = 90 * 24 * 3600
SEEN_GAP = 3600                 # a computer in steady use rewrites the file at most this often, or when its address changes
MAX_DEVICES = 50
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
ID = re.compile(r"[0-9a-f]{12}")
MAX_NAME = 64
_BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_SYSTEMS = (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Mac OS X", "Mac"),
            ("Linux", "Linux"))


def _path() -> Path:
    return config.paths().etc / FILE


def _hash(token: str) -> str:
    # a 256-bit random token: a plain hash is all it needs, unlike the short code's scrypt
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@contextmanager
def _locked():
    if fcntl is None:
        yield
        return
    with open(_path().with_suffix(".lock"), "a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield


def _load() -> dict:
    """{enabled, devices: [..]}. A file it can't read trusts nobody: the setup code still works."""
    try:
        root = DET.fromstring(_path().read_bytes(), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except OSError:
        return {"enabled": True, "devices": []}
    except (DET.ParseError, DefusedXmlException, ValueError):
        log.warning("setup: %s can't be read; no computer is trusted until it is replaced", FILE)
        return {"enabled": True, "devices": []}
    devices = []
    for el in root.findall("device"):
        a = el.attrib
        try:
            devices.append({"id": a["id"], "hash": a["hash"], "name": a.get("name", ""), "created": float(a["created"]),
                            "last_seen": float(a["last-seen"]), "last_address": a.get("last-address", ""),
                            "expires": float(a["expires"])})
        except (KeyError, ValueError):
            continue
    return {"enabled": root.get("enabled") != "false", "devices": devices}


def _save(st: dict) -> None:
    rows = "".join(
        f"  <device id={quoteattr(d['id'])} hash={quoteattr(d['hash'])} name={quoteattr(d['name'])} created={quoteattr(str(d['created']))} "
        f"last-seen={quoteattr(str(d['last_seen']))} last-address={quoteattr(d['last_address'])} expires={quoteattr(str(d['expires']))}/>\n"
        for d in st["devices"])
    data = f'<trusted version="1" enabled="{"true" if st["enabled"] else "false"}">\n{rows}</trusted>\n'.encode("utf-8")
    setup_code._write(_path(), data, 0o600, None)


def _live(st: dict, now: float) -> list[dict]:
    return [d for d in st["devices"] if d["expires"] > now]


def clean_name(text) -> str:
    text = text if isinstance(text, str) else ""
    return "".join(c for c in text if c.isprintable()).strip()[:MAX_NAME]


def name_from_agent(agent: str | None) -> str:
    """A first name for the computer, from what its browser says it is; the owner can change it."""
    agent = agent or ""
    browser = next((b for mark, b in _BROWSERS if mark in agent), "")
    system = next((s for mark, s in _SYSTEMS if mark in agent), "")
    return f"{browser} on {system}" if browser and system else browser or system or "A computer"


def enabled() -> bool:
    return _load()["enabled"]


def add(name: str, address: str, now: float | None = None) -> tuple[str, str] | None:
    """(id, token), or None when the feature is off. The token leaves here once, for the cookie."""
    now = time.time() if now is None else now
    with _locked():
        st = _load()
        if not st["enabled"]:
            return None
        devices = sorted(_live(st, now), key=lambda d: d["last_seen"])[-(MAX_DEVICES - 1):]    # the longest unused goes first
        token, did = secrets.token_urlsafe(32), secrets.token_hex(6)
        devices.append({"id": did, "hash": _hash(token), "name": clean_name(name) or "A computer", "created": now, "last_seen": now,
                        "last_address": address, "expires": now + LIFETIME})
        _save({**st, "devices": devices})
        return did, token


def _find(st: dict, token, now: float) -> dict | None:
    if not isinstance(token, str) or not TOKEN.fullmatch(token) or not st["enabled"]:
        return None
    want = _hash(token)
    found = None
    for d in _live(st, now):
        if hmac.compare_digest(d["hash"], want):
            found = d
    return found


def use(token, address: str, now: float | None = None) -> dict | None:
    """The computer this token belongs to, with its time renewed, or None: unknown, revoked, run out or the feature off."""
    now = time.time() if now is None else now
    with _locked():
        st = _load()
        d = _find(st, token, now)
        if d is None:
            return None
        moved = address != d["last_address"]
        if moved:
            log.info("setup: trusted computer %s seen at a new address: %s", d["id"], address)
        if moved or now - d["last_seen"] >= SEEN_GAP:
            d.update(last_seen=now, last_address=address, expires=now + LIFETIME)
            _save({**st, "devices": _live(st, now)})
        return d


def status(token, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st = _load()
    d = _find(st, token, now)
    return {"enabled": st["enabled"], "trusted": d is not None, "id": d["id"] if d else None, "name": d["name"] if d else None}


def listing(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [{k: d[k] for k in ("id", "name", "created", "last_seen", "last_address", "expires")} for d in _live(_load(), now)]


def revoke(did: str) -> bool:
    with _locked():
        st = _load()
        left = [d for d in st["devices"] if d["id"] != did]
        if len(left) == len(st["devices"]):
            return False
        _save({**st, "devices": left})
        return True


def revoke_all() -> int:
    with _locked():
        st = _load()
        _save({**st, "devices": []})
        return len(st["devices"])


def rename(did: str, name: str) -> bool:
    with _locked():
        st = _load()
        for d in st["devices"]:
            if d["id"] == did:
                d["name"] = clean_name(name) or d["name"]
                _save(st)
                return True
        return False


def set_enabled(on: bool) -> int:
    """Off forgets every computer. Returns how many went."""
    with _locked():
        st = _load()
        gone = 0 if on else len(st["devices"])
        _save({"enabled": bool(on), "devices": st["devices"] if on else []})
        return gone
