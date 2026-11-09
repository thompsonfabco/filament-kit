"""Finding Moonraker on the LAN (spec §6 Discovery): a passive mDNS browser and a scan the owner starts.

`Browser(on_found)` listens for `_moonraker._tcp.local.` (Moonraker announces itself when its `[zeroconf]` section is
on; the printer pack can switch it on) and calls `on_found(host, port, name)`. It only listens: it never sends
anything but the standard mDNS query.

`scan(subnet, port=7125, workers=64, timeout=0.3)` probes TCP `port` on every address of `subnet` (at most a /24)
and keeps the ones whose `/server/info` answers like Moonraker. It runs only when the owner asks (CLI
`filament-kit klipper scan`, the app's Scan button), never in the background. `own_subnet()` is the /24 of this
machine's default-route address (found without sending a packet). `check_range(net)` is what a client of the server may
ask for (`KlipperFamily.scan`); the CLI's `--subnet` is explicit and runs outside the service, so it isn't held to it.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .. import registry
from .moonraker import Moonraker, MoonrakerError

log = logging.getLogger(__name__)
SERVICE = "_moonraker._tcp.local."
DEFAULT_PORT = 7125
MAX_HOSTS = 256
# What the server's unit lets it reach (IPAddressAllow in install/systemd/filament-kit.service; a test keeps the two equal).
# A probe of anything else times out, and would read as "nothing there".
REACHABLE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def own_subnet() -> ipaddress.IPv4Network | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))          # TEST-NET-1: picks the outgoing interface, sends nothing
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return ipaddress.ip_network(f"{ip}/24", strict=False)


def check_range(net) -> None:
    """A network the server may be asked to scan: at most a /24, in a range its unit lets it reach. ValueError otherwise,
    rather than a scan that finds nothing."""
    if net.num_addresses > MAX_HOSTS:
        raise ValueError("scan at most a /24 (256 addresses)")
    if not any(net.version == r.version and net.subnet_of(r) for r in REACHABLE):
        raise ValueError(f"the server can only reach private networks ({', '.join(str(r) for r in REACHABLE)}), so a scan "
                         f"of {net} would find nothing")


def addresses(host: str, port: int) -> set[str]:
    """The addresses a printer's host name stands for now; empty when it can't be resolved from here."""
    try:
        return {a[4][0] for a in socket.getaddrinfo(host.strip("[]"), port, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return set()


def added_at() -> dict[tuple[str, int], registry.Printer]:
    """(address, port) -> the added printer there, so that a found address can be told from the name it was added by."""
    return {(a, p.port): p for p in registry.load().values() if p.family == "klipper" and p.configured
            for a in addresses(p.host, p.port)}


def add(name: str, host: str, port: int = DEFAULT_PORT) -> registry.Printer:
    """registry.add_klipper, which compares host text, and DuplicatePrinter too when `host` resolves to an address of a
    printer added under another name or address. A name that won't resolve from here is taken as typed. No lookups
    unless a printer on that port is there to compare."""
    others = [p for p in registry.load().values() if p.family == "klipper" and p.configured and p.port == int(port)]
    mine = addresses(host, port) if others else set()
    for p in others if mine else ():
        if mine & addresses(p.host, p.port):
            raise registry.DuplicatePrinter(f"{host}:{port} is already added as {registry.display_name(p)} ({p.host})")
    return registry.add_klipper(name, host, port)


def _open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_moonraker(host: str, port: int, timeout: float) -> bool:
    try:
        info = Moonraker(host, port, timeout=max(timeout, 0.5)).server_info()
    except MoonrakerError:
        return False
    return isinstance(info, dict) and "klippy_state" in info


def scan(subnet: ipaddress.IPv4Network, port: int | None = None, workers: int = 64,
         timeout: float = 0.3) -> list[tuple[str, int]]:
    port = port or DEFAULT_PORT
    if subnet.num_addresses > MAX_HOSTS:
        raise ValueError("scan at most a /24 (256 addresses)")
    hosts = [str(h) for h in (subnet.hosts() if subnet.num_addresses > 2 else subnet)]
    with ThreadPoolExecutor(max_workers=min(workers, len(hosts) or 1)) as ex:
        open_ = [h for h, ok in zip(hosts, ex.map(lambda h: _open(h, port, timeout), hosts)) if ok]
        found = [h for h, ok in zip(open_, ex.map(lambda h: _is_moonraker(h, port, timeout), open_)) if ok]
    return [(h, port) for h in found]


class Browser:
    def __init__(self, on_found: Callable[[str, int, str], None]):
        self.on_found = on_found
        self._zc = None
        self._browser = None

    def start(self) -> "Browser":
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except ImportError:
            log.info("klipper discovery: the zeroconf package is missing; add printers by host name")
            return self
        try:
            self._zc = Zeroconf()
            self._browser = ServiceBrowser(self._zc, SERVICE, handlers=[self._on_change])
        except OSError as e:
            log.warning("klipper discovery is off: %s", e)
            self._zc = None
        return self

    def stop(self) -> None:
        if self._zc is not None:
            try:
                self._zc.close()
            except Exception:  # noqa: BLE001
                pass
            self._zc = None

    def _on_change(self, zeroconf, service_type, name, state_change) -> None:
        from zeroconf import ServiceStateChange
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=3000)
        if info is not None:
            self._found(info, name)

    def _found(self, info, name: str) -> None:
        addrs = [a for a in (info.parsed_addresses() or []) if ":" not in a] or list(info.parsed_addresses() or [])
        host = addrs[0] if addrs else (info.server or "").rstrip(".")
        if not host or not info.port:
            return
        label = name.split("._moonraker", 1)[0] or host
        try:
            self.on_found(host, int(info.port), label)
        except Exception:  # noqa: BLE001 - a bad registry must not stop the browser
            log.exception("klipper discovery: cannot record %s", host)
