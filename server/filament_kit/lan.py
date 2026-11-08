"""Home-network checks shared by the web unit and the kit server's /setup page (no `mcp` import here)."""
from __future__ import annotations

import ipaddress
from typing import Iterable

Networks = list  # of ipaddress.IPv4Network | IPv6Network


def parse_lan(cidrs: Iterable[str]) -> Networks:
    return [ipaddress.ip_network(n, strict=False) for n in cidrs or ()]


def is_lan(host: str, nets: Networks) -> bool:
    """Loopback or inside one of the LAN ranges; anything that is not an IP address is not home."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:  # a dual-stack socket reports IPv4 clients as ::ffff:a.b.c.d
        ip = ip.ipv4_mapped
    return ip.is_loopback or any(ip in n for n in nets)
