"""Taking the owner's addresses and serials out of text the setup console shows without the setup code (the Overview's
rows, a job's log). Two nets: the values this server knows (its printers' serials, IPs and hosts, the station's address,
the public URL), then the shapes of what it may not know about (URLs, which covers fkit://pair links, IP addresses,
local names, serial-like words, account ids, bearer values). Shapes, not one owner's value: this ships to every owner, and
what must never be written anywhere can't be listed here.
A line that loses too much only reads worse; a line that keeps too much is the failure, so it errs towards hiding.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

HIDDEN = "<hidden>"
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>)]+", re.I)
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?::\d{1,5})?(?![\d.])")
# at least a "::", or six groups: a time such as 14:03:22 or a MAC-less "a:b" is left alone
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])", re.I)
_LOCAL = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:local|localdomain|lan|home|internal|arpa|example)\b"
                    r"(?::\d{1,5})?", re.I)
# a serial: 12-20 capitals and digits with both in it (Bambu's look like this; a word of capitals or a date does not)
_SERIAL = re.compile(r"\b(?=[0-9A-Z]*[0-9])(?=[0-9A-Z]*[A-Z])[0-9A-Z]{12,20}\b")
# a Bambu account id: Studio's user folder and the sync's query parameter name it; any long run of digits may be one
_ACCOUNT = re.compile(r"\buser_?id\b[=:\s\"']+[^\s&\"']+|\b\d{9,}\b", re.I)
_USER_FOLDER = re.compile(r"([\\/]user[\\/]+)[^\\/\s]+", re.I)
_BEARER = re.compile(r"\b(?:authorization[=:\s\"']+(?:bearer\s+)?|bearer[=:\s\"']+|token\s*[=:]\s*)[^\s&\"']+", re.I)


def _ipv6(m: re.Match) -> str:
    s = m.group(0)
    return HIDDEN if "::" in s or s.count(":") >= 5 else s


def known_values(cfg: dict | None = None) -> list[str]:
    """What this server knows that must not show: its printers' serials, IPs and hosts, its station and public
    addresses. Longest first, so a value inside another goes with it. Never raises: a registry or config that cannot
    be read leaves the shapes to do the work."""
    out: set[str] = set()
    try:
        from .bridge import registry
        for p in registry.load().values():
            out.update(str(v) for v in (p.serial, p.ip, getattr(p, "host", "")) if v)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import config
        c = cfg if cfg is not None else config.load()
        for url in ((c.get("web") or {}).get("public_url"), (c.get("station") or {}).get("url"), c.get("spoolman_url")):
            host = urlsplit(url).hostname if isinstance(url, str) else None
            if host and host not in ("localhost",):
                out.add(host)
        out.update(str(a) for a in (c.get("station") or {}).get("allow") or () if a)
    except Exception:  # noqa: BLE001
        pass
    return sorted((v for v in out if len(v) >= 4 and v not in ("127.0.0.1", "localhost")), key=len, reverse=True)


def text(s: str, known: list[str] | None = None) -> str:
    """`s` without addresses or serials. Loopback stays hidden too: nothing here needs it, and a rule with no
    exceptions is one a test can hold."""
    s = _URL.sub(HIDDEN, s)
    s = _BEARER.sub(HIDDEN, s)
    s = _USER_FOLDER.sub(lambda m: m.group(1) + HIDDEN, s)
    s = _ACCOUNT.sub(HIDDEN, s)
    for v in known if known is not None else known_values():
        s = s.replace(v, HIDDEN)
    s = _IPV4.sub(HIDDEN, s)
    s = _IPV6.sub(_ipv6, s)
    s = _LOCAL.sub(HIDDEN, s)
    return _SERIAL.sub(HIDDEN, s)
