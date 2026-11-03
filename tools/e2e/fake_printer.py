"""A fake Bambu printer on the network for the end-to-end run: a tiny MQTT 3.1.1 broker over TLS on port 8883.

The printer's behaviour is the unit tests' `FakePrinter` (server/tests/fakes/fake_paho.py): it keeps a report,
answers `pushall` with all of it and applies `ams_filament_setting` to its units (reply, then the changed report).
This file only puts it on a real socket: TLS with a self-signed leaf whose CN is the serial (as a real printer's),
CONNECT checked against user `bblp` and the Access Code, SUBSCRIBE, PUBLISH (QoS 0 and 1), PINGREQ, DISCONNECT.

`big_report()` is a synthetic H2D-style report with 16 AMS units (ids 0-15), 8 AMS HT units (128-135) and both
external holders, as in server/tests/test_layout.py. Standard library plus `cryptography` (for the leaf).
"""
from __future__ import annotations

import json
import socket
import ssl
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "tests"))
from fakes.fake_certs import Leaf  # noqa: E402
from fakes.fake_paho import FakePrinter  # noqa: E402

CONNECT, CONNACK, PUBLISH, PUBACK, SUBSCRIBE, SUBACK = 1, 2, 3, 4, 8, 9
UNSUBSCRIBE, UNSUBACK, PINGREQ, PINGRESP, DISCONNECT = 10, 11, 12, 13, 14


def _tray(i, t="PLA", color="FF0000FF", idx="GFA00"):
    return {"id": str(i), "tray_type": t, "tray_color": color, "tray_info_idx": idx}


def _unit(uid, n=4):
    return {"id": str(uid), "tray": [_tray(i) for i in range(n)]}


def _ext(i, t="", color="00000000"):
    return {"id": str(i), "tray_type": t, "tray_color": color, "tray_info_idx": ""}


def big_report() -> dict:
    units = [_unit(i) for i in range(16)] + [_unit(128 + i, 1) for i in range(8)]
    return {"gcode_state": "IDLE", "nozzle_diameter": "0.4",
            "ams": {"ams": units, "tray_now": "255", "tray_exist_bits": "ffffffff", "tray_reading_bits": "0"},
            "vir_slot": [_ext(254, "TPU", "FFFFFFFF"), _ext(255)]}


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _packet(ptype: int, flags: int, body: bytes) -> bytes:
    return bytes([(ptype << 4) | flags]) + _varint(len(body)) + body


def _utf8(s: str) -> bytes:
    b = s.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


class _Conn:
    """What FakePrinter calls: `responder` is set by it, `deliver(payload)` sends a report to the kit."""

    def __init__(self, broker: "Broker"):
        self.broker = broker
        self.responder = None

    def deliver(self, payload, serial=None):
        self.broker.send_report(payload)


class Broker:
    def __init__(self, serial: str, code: str, certdir: Path, host: str = "127.0.0.1", port: int = 8883,
                 report: dict | None = None):
        self.serial, self._code = serial, code
        self.leaf = Leaf(cn=serial)
        self.ctx = self.leaf.server_ctx(Path(certdir))
        self.conn = _Conn(self)
        self.printer = FakePrinter(self.conn, report if report is not None else big_report())
        self.requests: list[dict] = []          # every request body the kit published
        self.connects = 0
        self.auth_failures = 0
        self._sock_lock = threading.Lock()
        self._client: ssl.SSLSocket | None = None
        self._stop = threading.Event()
        self.srv = socket.create_server((host, port), reuse_port=False)
        self.srv.settimeout(0.5)
        self.thread = threading.Thread(target=self._accept, name="fake-printer", daemon=True)
        self.thread.start()

    # ---------------------------------------------------------------- what the e2e checks
    def writes(self) -> list[dict]:
        return list(self.printer.writes)

    def close(self) -> None:
        self._stop.set()
        with self._sock_lock:
            if self._client is not None:
                try:
                    self._client.close()
                except OSError:
                    pass
        self.srv.close()
        self.thread.join(5)

    # ---------------------------------------------------------------- network
    def send_report(self, payload: dict) -> None:
        body = _utf8(f"device/{self.serial}/report") + json.dumps(payload).encode("utf-8")
        self._send(_packet(PUBLISH, 0, body))

    def _send(self, data: bytes) -> None:
        with self._sock_lock:
            if self._client is None:
                return
            try:
                self._client.sendall(data)
            except OSError:
                pass

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                raw, _ = self.srv.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(raw,), daemon=True).start()

    def _serve(self, raw: socket.socket) -> None:
        try:
            tls = self.ctx.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            raw.close()
            return
        tls.settimeout(None)
        try:
            self._session(tls)
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            with self._sock_lock:
                if self._client is tls:
                    self._client = None
            try:
                tls.close()
            except OSError:
                pass

    @staticmethod
    def _read_exact(s, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def _read_packet(self, s) -> tuple[int, int, bytes]:
        first = self._read_exact(s, 1)[0]
        mult, length = 1, 0
        while True:
            b = self._read_exact(s, 1)[0]
            length += (b & 0x7F) * mult
            if not b & 0x80:
                break
            mult *= 128
        return first >> 4, first & 0x0F, self._read_exact(s, length) if length else b""

    def _session(self, s) -> None:
        ptype, _, body = self._read_packet(s)
        if ptype != CONNECT:
            return
        user, password = self._parse_connect(body)
        if user != "bblp" or password != self._code:
            self.auth_failures += 1
            s.sendall(_packet(CONNACK, 0, b"\x00\x05"))     # not authorized
            return
        with self._sock_lock:
            old, self._client = self._client, s
        if old is not None:
            try:
                old.close()
            except OSError:
                pass
        self.connects += 1
        s.sendall(_packet(CONNACK, 0, b"\x00\x00"))
        while not self._stop.is_set():
            ptype, flags, body = self._read_packet(s)
            if ptype == PUBLISH:
                self._on_publish(flags, body)
            elif ptype == SUBSCRIBE:
                pid, rest = body[:2], body[2:]
                granted = bytearray()
                while rest:
                    n = int.from_bytes(rest[:2], "big")
                    rest = rest[2 + n + 1:]
                    granted.append(0)
                self._send(_packet(SUBACK, 0, pid + bytes(granted)))
            elif ptype == UNSUBSCRIBE:
                self._send(_packet(UNSUBACK, 0, body[:2]))
            elif ptype == PINGREQ:
                self._send(_packet(PINGRESP, 0, b""))
            elif ptype == DISCONNECT:
                return

    @staticmethod
    def _parse_connect(body: bytes) -> tuple[str | None, str | None]:
        i = 0

        def field() -> bytes:
            nonlocal i
            n = int.from_bytes(body[i:i + 2], "big")
            v = body[i + 2:i + 2 + n]
            i += 2 + n
            return v

        field()                         # protocol name
        i += 1                          # level
        flags = body[i]
        i += 1 + 2                      # flags, keepalive
        field()                         # client id
        if flags & 0x04:                # will topic + message
            field()
            field()
        user = field().decode() if flags & 0x80 else None
        password = field().decode() if flags & 0x40 else None
        return user, password

    def _on_publish(self, flags: int, body: bytes) -> None:
        qos = (flags >> 1) & 3
        n = int.from_bytes(body[:2], "big")
        topic = body[2:2 + n].decode("utf-8", "replace")
        rest = body[2 + n:]
        if qos:
            pid, rest = rest[:2], rest[2:]
            self._send(_packet(PUBACK, 0, pid))
        if topic != f"device/{self.serial}/request":
            return
        try:
            req = json.loads(rest)
        except ValueError:
            return
        if not isinstance(req, dict):
            return
        self.requests.append(req)
        reply = self.printer.respond(topic, req)
        if reply is None:
            return
        replies = reply if isinstance(reply, list) else [reply]

        def later():
            time.sleep(0.05)            # as a printer: the reply comes after the request, not inside it
            for p in replies:
                self.send_report(p)
        threading.Thread(target=later, daemon=True).start()
