"""The station's calls to the kit server for the button flow (server side: filament_kit/station_flow.py).

Pairing: `sudo filament-kit pair --station` on the server prints an fkit://pair link; `sudo filament-kit station pair`
on the station PC takes it, shows the server's certificate fingerprint for the owner to compare, and writes
/etc/filament-kit-station/station_server.json (address, port, fingerprint) and .../station_token (0600, the
station user's). Calls go to https://<ip>:<port> by IP (the unit allows only the server's address: no DNS, no
mDNS), with the certificate pinned by its SHA-256 and `Authorization: Bearer <token>`.

Each call returns (http_status, json); status 0 means the server was not reached (json carries `display`).
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import ssl
import uuid
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .. import config

TIMEOUT = 90  # s: a Claude read takes 3-15 s; the station drops a late answer when red was pressed
CONNECT_TIMEOUT = 5  # s per address: the link lists every server address, some (container bridges) unreachable
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_FP = re.compile(r"^[0-9a-fA-F]{64}$")
UNREACHABLE = ["Server offline", "check the network"]


@dataclass
class Link:
    host: str
    port: int
    token: str
    fp: str
    ips: list[str]


def parse_link(text: str) -> Link:
    """`fkit://pair?h=<host>&p=<port>&t=<token>&fp=<sha256>&ip=<ip>...` (as `filament-kit pair --station` prints)."""
    u = urllib.parse.urlsplit((text or "").strip())
    if u.scheme.lower() != "fkit" or u.netloc.lower() != "pair":
        raise ValueError("not a filament-kit pairing link")
    q = urllib.parse.parse_qs(u.query)

    def one(k: str) -> str:
        v = q.get(k) or [""]
        if len(v) != 1 or not v[0]:
            raise ValueError(f"the pairing link has no single '{k}'")
        return v[0]
    port = one("p")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("the pairing link has an invalid port")
    if not _TOKEN.match(one("t")):
        raise ValueError("the pairing link has an invalid token")
    if not _FP.match(one("fp")):
        raise ValueError("the pairing link has an invalid certificate fingerprint")
    return Link(one("h"), int(port), one("t"), one("fp").lower(), [i for i in q.get("ip", []) if i])


def pairing_dir() -> Path:
    """/etc/filament-kit-station: the station's own folder (root:filament-kit-station 0750). Not /etc/filament-kit,
    which is root:filament-kit 2750 and closed to the station's service user. Beside FK_ETC in tests."""
    etc = config.paths().etc
    return etc.parent / f"{etc.name}-station"


def server_file() -> Path:
    return pairing_dir() / "station_server.json"


def token_file() -> Path:
    return pairing_dir() / "station_token"


def _context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # trust is the pinned fingerprint, checked before anything is sent
    return ctx


class _Pinned(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, fp: str, timeout: float):
        super().__init__(host, port, timeout=timeout, context=_context())
        self._fp = fp

    def connect(self):
        full, self.timeout = self.timeout, min(self.timeout, CONNECT_TIMEOUT)
        try:
            super().connect()
        finally:
            self.timeout = full
        self.sock.settimeout(full)
        got = hashlib.sha256(self.sock.getpeercert(binary_form=True) or b"").hexdigest()
        if got != self._fp:
            self.sock.close()
            raise ssl.SSLError(f"server certificate changed (fingerprint {got[:16]}..., expected {self._fp[:16]}...)")


def peer_fingerprint(ip: str, port: int, timeout: float = 10) -> str:
    """The fingerprint the server presents (handshake only), for the owner to compare while pairing."""
    c = http.client.HTTPSConnection(ip, port, timeout=timeout, context=_context())
    try:
        c.connect()
        return hashlib.sha256(c.sock.getpeercert(binary_form=True) or b"").hexdigest()
    finally:
        c.close()


def save_pairing(link: Link, owner: str | None = "filament-kit-station", first: str | None = None) -> None:
    """Write the server file (0644) and the token (0600, owned by the station's service user when run as root) into
    pairing_dir() (0750, group of the station user). `first`: the address that answered while pairing, tried first
    from then on."""
    d = pairing_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o750)
    ips = link.ips or [link.host]
    if first:
        ips = [first] + [i for i in ips if i != first]
    server_file().write_text(json.dumps({"ips": ips, "port": link.port, "fp": link.fp,
                                         "host": link.host}, indent=1) + "\n", encoding="utf-8")
    tok = token_file()
    fd = os.open(tok, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(link.token + "\n")
    os.chmod(tok, 0o600)
    if owner and hasattr(os, "geteuid") and os.geteuid() == 0:
        import pwd
        try:
            pw = pwd.getpwnam(owner)
        except KeyError:
            return
        os.chown(d, 0, pw.pw_gid)          # root:filament-kit-station 0750: the service can read, others can't
        os.chown(server_file(), 0, pw.pw_gid)
        os.chown(tok, pw.pw_uid, pw.pw_gid)


class ServerApi:
    """The flow's three calls. Built from the pairing files; `paired` is False until `filament-kit station pair`."""

    def __init__(self, timeout: float = TIMEOUT):
        self.timeout = timeout
        try:
            cfg = json.loads(server_file().read_text(encoding="utf-8"))
            self.ips, self.port, self.fp = list(cfg["ips"]), int(cfg["port"]), str(cfg["fp"])
            self.token = token_file().read_text(encoding="utf-8").strip()
            self.paired = bool(self.ips and self.token)
        except (OSError, ValueError, KeyError, TypeError):
            self.ips, self.port, self.fp, self.token, self.paired = [], 0, "", "", False

    def _call(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None) -> tuple[int, dict]:
        if not self.paired:
            return 0, {"error": "not_paired", "display": ["Not paired", "sudo filament-kit station pair"]}
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if ctype:
            headers["Content-Type"] = ctype
        last = None
        for ip in self.ips:
            c = _Pinned(ip, self.port, self.fp, self.timeout)
            try:
                c.request(method, path, body=body, headers=headers)
                r = c.getresponse()
                raw = r.read()
                try:
                    data = json.loads(raw or b"{}")
                except ValueError:
                    data = {"error": "bad_answer"}
                if r.status == 401:
                    data.setdefault("display", ["Not paired", "pair the station again"])
                return r.status, data if isinstance(data, dict) else {"error": "bad_answer"}
            except ssl.SSLError as e:
                if "certificate changed" in str(e):
                    return 0, {"error": "cert_changed", "message": str(e),
                               "display": ["Server changed", "pair the station again"]}
                last = e
            except (OSError, http.client.HTTPException) as e:
                last = e
            finally:
                c.close()
        return 0, {"error": "unreachable", "message": str(last), "display": list(UNREACHABLE)}

    def tag_lookup(self, uid: str) -> tuple[int, dict]:
        return self._call("GET", "/api/station/tag/" + urllib.parse.quote(uid, safe=""))

    def recognize(self, jpeg: bytes, uid: str | None = None) -> tuple[int, dict]:
        b = uuid.uuid4().hex
        parts = [f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"station.jpg\"\r\n"
                 f"Content-Type: image/jpeg\r\n\r\n".encode() + jpeg + b"\r\n"]
        if uid:
            parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"uid\"\r\n\r\n{uid}\r\n".encode())
        body = b"".join(parts) + f"--{b}--\r\n".encode()
        return self._call("POST", "/api/station/recognize", body, f"multipart/form-data; boundary={b}")

    def save(self, body: dict) -> tuple[int, dict]:
        return self._call("POST", "/api/station/save", json.dumps(body).encode(), "application/json")
