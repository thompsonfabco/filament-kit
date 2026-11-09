"""An address the owner typed: an IPv4 or IPv6 address, a DNS name, or an mDNS `.local` name.

It is kept as typed and resolved each time it is used, so a printer that moves under DHCP stays found by its name. It is
checked once when it is given: the form here, and the name by resolving it from this machine, with a line saying what to
look at when that fails. Nothing stores what a name resolved to.
"""
from __future__ import annotations

import ipaddress
import queue
import re
import socket
import threading

_HOSTNAME = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}"
                       r"[A-Za-z0-9])?)*\.?")
BAD_FORM = "give an IP address or a host name, for example 192.0.2.40, printer.local or printer.example.com"
LOOKUP_WAIT = 5.0


def clean(text) -> str:
    """The address as it will be kept: without spaces round it, or the brackets of a typed `[fe80::1]`."""
    value = text.strip() if isinstance(text, str) else ""
    return value[1:-1] if value.startswith("[") and value.endswith("]") else value


def is_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def form_error(host: str) -> str | None:
    if is_literal(host):
        return None
    if not _HOSTNAME.fullmatch(host) or host.rstrip(".").rsplit(".", 1)[-1].isdigit():   # 192.0.2.999 is a bad address, not a name
        return BAD_FORM
    return None


def resolve_error(host: str, *, timeout: float = LOOKUP_WAIT, lookup=None) -> str | None:
    """Why `host` can't be used from this machine, or None. A literal address is not looked up. The answer isn't kept."""
    if is_literal(host):
        return None
    lookup = lookup or socket.getaddrinfo
    got: queue.Queue[bool] = queue.Queue()

    def ask() -> None:
        try:
            got.put(bool(lookup(host, None, type=socket.SOCK_STREAM)))
        except OSError:
            got.put(False)
    threading.Thread(target=ask, name="address-lookup", daemon=True).start()    # getaddrinfo has no timeout of its own
    try:
        found = got.get(timeout=timeout)
    except queue.Empty:
        found = False
    if found:
        return None
    if host.rstrip(".").lower().endswith(".local"):
        return (f"{host} did not answer from this server. A .local name needs the device switched on and on this network; "
                "check the spelling, or give its IP address")
    return f"{host} does not resolve from this server: check the spelling and your DNS, or give its IP address"


def checked(text, *, lookup=None) -> tuple[str, str | None]:
    """(the address as it will be kept, the problem with it or None)."""
    host = clean(text)
    return host, form_error(host) or resolve_error(host, lookup=lookup)


def url_host(host: str) -> str:
    """`host` as it goes in a URL."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
