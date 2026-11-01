"""Bambu printers announce themselves with SSDP NOTIFY on UDP 2021."""
from __future__ import annotations

import socket
import threading

PORT = 2021


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


class Listener:
    """Listens for announcements in a thread and calls `on_found(info_dict)` for each valid one."""

    def __init__(self, on_found, port: int = PORT, host: str = "0.0.0.0"):
        self._on_found = on_found
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ssdp-listener", daemon=True)

    def start(self) -> "Listener":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._sock.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            info = parse_notify(data)
            if info is not None:
                try:
                    self._on_found(info)
                except Exception:  # noqa: BLE001 - one bad callback must not end discovery
                    pass
