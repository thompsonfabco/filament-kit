"""Home-network checks shared by the web unit and the kit server's /setup page (no `mcp` import here)."""
from __future__ import annotations

import ipaddress
from typing import Iterable

Networks = list  # of ipaddress.IPv4Network | IPv6Network


def parse_lan(cidrs: Iterable[str]) -> Networks:
    return [ipaddress.ip_network(n, strict=False) for n in cidrs or ()]


# Why an IPv6 client on the home Wi-Fi was refused: most home IPv6 is a global prefix that no default could name, and a
# wide default such as fd00::/8 would take in Tailscale's and Docker's ranges. Never the client's address: this gets
# screenshotted.
IPV6_HINT = ("This device reached the server over IPv6. To let it in, add your home network's IPv6 prefix to web.lan in "
             "the server's settings (the user guide says how).")


def over_ipv6(host: str) -> bool:
    """`host` is an IPv6 address, and not an IPv4 client on a dual-stack socket."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.version == 6 and not ip.ipv4_mapped


def is_lan(host: str, nets: Networks) -> bool:
    """Loopback or inside one of the LAN ranges; anything that is not an IP address is not home."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:  # a dual-stack socket reports IPv4 clients as ::ffff:a.b.c.d
        ip = ip.ipv4_mapped
    return ip.is_loopback or any(ip in n for n in nets)
