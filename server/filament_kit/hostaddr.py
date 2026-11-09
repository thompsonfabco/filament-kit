"""An address the owner typed: an IPv4 or IPv6 address, a DNS name, or an mDNS `.local` name.

It is kept as typed and resolved each time it is used, so a printer that moves under DHCP stays found by its name. It is
checked once when it is given: the form here, and the name by resolving it from this machine, with a line saying what to
look at when that fails. Where it points is held against the networks the server's unit lets it reach (SERVICE_REACH):
an address outside them is saved all the same, with a note saying why it will show offline and what allows it. Nothing
stores what a name resolved to.
"""
from __future__ import annotations

import ipaddress
import queue
import re
import socket
import threading
from typing import NamedTuple

_HOSTNAME = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}"
                       r"[A-Za-z0-9])?)*\.?")
BAD_FORM = "give an IP address or a host name, for example 192.0.2.40, printer.local or printer.example.com"
LOOKUP_WAIT = 5.0
# What the server's unit lets it reach (IPAddressAllow in install/systemd/filament-kit.service; a test keeps the two
# equal): the home networks, IPv4 and IPv6. The unit's own lines for the update check are not here.
SERVICE_REACH = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                         "fe80::/10", "fc00::/7"))
UNREACHABLE = ("{where} is outside the networks the kit's service may reach (home networks: 10/8, 172.16/12, 192.168/16, "
               "fe80::/10, fc00::/7), so it will show offline until its network is allowed: sudo systemctl edit filament-kit, "
               "add the two lines [Service] and IPAddressAllow={net}, then sudo systemctl restart filament-kit")


class Inspected(NamedTuple):
    host: str               # as it will be kept
    problem: str | None     # why it can't be used: a bad form, a name that doesn't resolve
    note: str | None        # it can be kept, but: the server's unit doesn't reach where it points


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


def _lookup(host: str, timeout: float, lookup) -> list | None:
    """getaddrinfo's answer for `host` within `timeout`, None when there is none. The answer is never kept."""
    lookup = lookup or socket.getaddrinfo
    got: queue.Queue = queue.Queue()

    def ask() -> None:
        try:
            got.put(lookup(host, None, type=socket.SOCK_STREAM) or None)
        except OSError:
            got.put(None)
    threading.Thread(target=ask, name="address-lookup", daemon=True).start()    # getaddrinfo has no timeout of its own
    try:
        return got.get(timeout=timeout)
    except queue.Empty:
        return None


def _literals(answer) -> list:
    out = []
    for entry in answer or ():
        try:
            out.append(ipaddress.ip_address(str(entry[4][0]).split("%", 1)[0]))
        except (TypeError, IndexError, ValueError):
            continue
    return out


def reachable(addr) -> bool:
    """Whether the server's unit lets it connect to `addr` (an ip_address): the home networks, and this machine."""
    return addr.is_loopback or any(addr.version == n.version and addr in n for n in SERVICE_REACH)


def _network_of(addr) -> str:
    """The line to allow for `addr`: its /24 or /64, as a person would write it."""
    return str(ipaddress.ip_network(f"{addr}/{24 if addr.version == 4 else 64}", strict=False))


def reach_note(host: str, answer=None) -> str | None:
    """The note for an address the unit doesn't reach: `host` itself when it is one, else the first of the `answer` it
    resolved to. None when it is reachable, or when the answer carries no address to judge."""
    found = [ipaddress.ip_address(host)] if is_literal(host) else _literals(answer)
    if not found or any(reachable(a) for a in found):
        return None
    where = host if is_literal(host) else f"{host} ({found[0]})"
    return UNREACHABLE.format(where=where, net=_network_of(found[0]))


def addresses(host: str, *, timeout: float = LOOKUP_WAIT, lookup=None) -> set[str]:
    """The addresses `host` stands for right now: itself when it is one, else what it resolves to (empty when it doesn't).
    For telling a found address and a typed name apart; nothing keeps the answer."""
    if is_literal(host):
        return {str(ipaddress.ip_address(host))}
    return {str(a) for a in _literals(_lookup(host, timeout, lookup))}


def inspect(text, *, timeout: float = LOOKUP_WAIT, lookup=None) -> Inspected:
    """The address as it will be kept, why it can't be used (or None), and the note to show beside saving it (or None).
    A literal address is not looked up; a name is looked up once, for both answers."""
    host = clean(text)
    problem = form_error(host)
    if problem:
        return Inspected(host, problem, None)
    if is_literal(host):
        return Inspected(host, None, reach_note(host))
    answer = _lookup(host, timeout, lookup)
    if answer is None:
        if host.rstrip(".").lower().endswith(".local"):
            problem = (f"{host} did not answer from this server. A .local name needs the device switched on and on this "
                       "network; check the spelling, or give its IP address")
        else:
            problem = f"{host} does not resolve from this server: check the spelling and your DNS, or give its IP address"
        return Inspected(host, problem, None)
    return Inspected(host, None, reach_note(host, answer))


def resolve_error(host: str, *, timeout: float = LOOKUP_WAIT, lookup=None) -> str | None:
    """Why `host` can't be used from this machine, or None. A literal address is not looked up. The answer isn't kept."""
    if is_literal(host):
        return None
    return inspect(host, timeout=timeout, lookup=lookup).problem


def checked(text, *, lookup=None) -> tuple[str, str | None]:
    """(the address as it will be kept, the problem with it or None)."""
    host = clean(text)
    return host, form_error(host) or resolve_error(host, lookup=lookup)


def url_host(host: str) -> str:
    """`host` as it goes in a URL."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
