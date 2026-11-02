"""Bambu printers announce themselves with SSDP NOTIFY: broadcast to UDP 2021, and some also multicast to
239.255.255.250:1990. The listener watches both."""
from __future__ import annotations

import ipaddress
import logging
import select
import socket
import struct
import threading

log = logging.getLogger(__name__)

PORT = 2021
MULTICAST_PORT = 1990
MULTICAST_GROUP = "239.255.255.250"


def parse_notify(data: bytes) -> dict | None:
    """Parse a Bambu SSDP NOTIFY into {serial, ip, model, name, connect}; anything else gives None."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines()
    if not lines or not lines[0].upper().startswith("NOTIFY"):
        return None
    h: dict[str, str] = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            h[key.strip().lower()] = value.strip()
    serial, ip = h.get("usn", ""), h.get("location", "")
    if not serial or not ip:
        return None
    if "bambu" not in (h.get("nt", "bambu")).lower():
        return None
    return {
        "serial": serial,
        "ip": ip,
        "model": h.get("devmodel.bambu.com", ""),
        "name": h.get("devname.bambu.com", ""),
        "connect": h.get("devconnect.bambu.com", ""),
    }


def valid_ip(text: str, allow_loopback: bool = False) -> bool:
    """A unicast IPv4 address a printer could really have."""
    try:
        a = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    if a.is_multicast or a.is_unspecified or a.is_reserved:
        return False
    return allow_loopback or not a.is_loopback


class Listener:
    """Listens for announcements in a thread and calls `on_found(info_dict)` for each valid one.

    An announcement is dropped unless its `Location` is a valid IPv4 address equal to the packet's source
    address: the Access Code is later sent to that IP, so it must not be spoofable by a third party.
    `multicast_port=None` turns the multicast socket off. `allow_loopback` is for tests."""

    def __init__(self, on_found, port: int = PORT, host: str = "0.0.0.0",
                 multicast_port: int | None = MULTICAST_PORT, allow_loopback: bool = False):
        self._on_found = on_found
        self._allow_loopback = allow_loopback
        self._socks = [self._bind(host, port)]
        self.port = self._socks[0].getsockname()[1]
        self.multicast_port = None
        self.multicast_joined = False
        if multicast_port is not None:
            try:
                m = self._bind(host, multicast_port)
            except OSError as e:
                log.warning("cannot listen on UDP %s for multicast announcements: %s", multicast_port, e)
            else:
                self._socks.append(m)
                self.multicast_port = m.getsockname()[1]
                try:
                    mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
                    m.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    self.multicast_joined = True
                except OSError as e:
                    log.warning("cannot join multicast group %s: %s", MULTICAST_GROUP, e)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ssdp-listener", daemon=True)

    @staticmethod
    def _bind(host: str, port: int) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        except OSError:
            s.close()
            raise
        return s

    def start(self) -> "Listener":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        for s in self._socks:
            s.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select(self._socks, [], [], 0.5)
            except (OSError, ValueError):
                return
            for s in ready:
                try:
                    data, addr = s.recvfrom(4096)
                except OSError:
                    continue
                info = parse_notify(data)
                if info is None or not valid_ip(info["ip"], self._allow_loopback) or info["ip"] != addr[0]:
                    continue
                try:
                    self._on_found(info)
                except Exception:  # noqa: BLE001 - one bad callback must not end discovery
                    log.exception("discovery callback failed")
