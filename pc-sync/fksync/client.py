"""HTTPS client for the filament-kit sync API, pinned to the server's certificate.

The server uses a self-signed certificate. Its SHA-256 fingerprint (of the DER leaf, lowercase hex,
the server's `pairing.fingerprint` and the Android app's pin) is stored in the sync config at pairing.
Each request connects TLS with no CA or hostname check, then compares the leaf's fingerprint with
the pinned one *before writing any request bytes*; on a mismatch the connection is closed unsent
and the next address is tried. So the Authorization header only ever goes to the pinned server.

The token is never put in a URL, logged or included in an exception message.
"""
import hashlib
import http.client
import json
import re
import socket
import ssl
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_PORT = 8710
_FP = re.compile(r"^[0-9a-fA-F]{64}$")
_TOKEN = re.compile(r"^[!-~]{1,512}$")  # printable ASCII, no spaces: safe in a header, never echoed


class Offline(Exception):
    """No address of the server could be reached (or a connection broke mid-request)."""


class CertChanged(Exception):
    """Every reachable address presented a certificate other than the pinned one; nothing was sent."""

    def __init__(self, expected: str, actual: str):
        super().__init__(f"the server's certificate changed (pinned {expected}, now {actual}); if the server was "
                         "reinstalled, run 'filament-kit-sync pair' again")
        self.expected = expected
        self.actual = actual


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"server said {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PairLink:
    host: str
    port: int
    token: str
    fp: str
    ips: list[str] = field(default_factory=list)


def parse_link(text: str) -> PairLink:
    """Parse `fkit://pair?h=<host>&p=<port>&t=<token>&fp=<sha256>&ip=<ip>...` (ip repeats 0..n times)."""
    text = (text or "").strip()
    try:
        u = urllib.parse.urlsplit(text)
    except ValueError:
        raise ValueError("not a filament-kit pairing link") from None
    if u.scheme.lower() != "fkit" or u.netloc.lower() != "pair":
        raise ValueError("not a filament-kit pairing link")
    try:
        params = urllib.parse.parse_qs(u.query, keep_blank_values=True, strict_parsing=bool(u.query))
    except ValueError:
        raise ValueError("the pairing link is not correctly encoded") from None

    def single(key: str) -> str:
        values = params.get(key, [])
        if len(values) > 1:
            raise ValueError(f"the pairing link has more than one '{key}' value")
        if not values or not values[0]:
            raise ValueError(f"the pairing link is missing '{key}'")
        return values[0]

    host = single("h")
    port_s = single("p")
    if not port_s.isdigit() or not 1 <= int(port_s) <= 65535:
        raise ValueError("the pairing link has an invalid port")
    token = single("t")
    if not _TOKEN.match(token):
        raise ValueError("the pairing link has an invalid token")
    fp = single("fp")
    if not _FP.match(fp):
        raise ValueError("the pairing link has an invalid certificate fingerprint")
    ips = [ip for ip in params.get("ip", []) if ip]
    return PairLink(host=host, port=int(port_s), token=token, fp=fp.lower(), ips=ips)


def _context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # trust comes from the pinned fingerprint, compared before sending
    return ctx


def leaf_fingerprint(sock: ssl.SSLSocket) -> str:
    der = sock.getpeercert(binary_form=True)
    return hashlib.sha256(der or b"").hexdigest()


def fetch_peer(host: str, port: int, timeout: float = 10) -> tuple[str, str]:
    """(fingerprint, IP actually connected to) for host:port (TLS handshake only; nothing is sent)."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            ip = raw.getpeername()[0]
            with _context().wrap_socket(raw, server_hostname=host) as tls:
                return leaf_fingerprint(tls), ip
    except (OSError, ssl.SSLError) as e:
        raise Offline(f"could not reach {host}:{port} ({e})") from None


def fetch_fingerprint(host: str, port: int, timeout: float = 10) -> str:
    """The fingerprint of the certificate host:port presents (TLS handshake only; nothing is sent)."""
    return fetch_peer(host, port, timeout)[0]


class _Mismatch(Exception):
    def __init__(self, actual: str):
        self.actual = actual


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, fp: str, timeout: float):
        super().__init__(host, port, timeout=timeout, context=_context())
        self._fp = fp

    def connect(self):
        super().connect()  # TCP + TLS handshake only; no HTTP bytes yet
        actual = leaf_fingerprint(self.sock)
        if actual != self._fp:
            self.sock.close()
            self.sock = None
            raise _Mismatch(actual)


class Client:
    def __init__(self, cfg: dict, token: str | None, timeout: float = 60,
                 log: Callable[[str], None] | None = None):
        self.host = cfg["host"]
        self.port = int(cfg.get("port") or DEFAULT_PORT)
        self.fp = str(cfg["fp"]).lower()
        self.ips = [ip for ip in (cfg.get("ips") or []) if ip]
        if token is not None and not _TOKEN.match(token):
            raise ValueError("the stored token is not valid; run 'filament-kit-sync pair' again")
        self._token = token
        self.timeout = timeout
        self._good: str | None = None
        self._log = log

    def __repr__(self):  # never show the token
        return f"Client({self.host}:{self.port})"

    def _addresses(self) -> list[str]:
        addrs = []
        for a in [self._good, self.host, *self.ips]:
            if a and a not in addrs:
                addrs.append(a)
        return addrs

    def _request(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None,
                 *, raw: bool = False, auth: bool = True):
        mismatch, mismatched, offline = None, [], []
        for addr in self._addresses():
            conn = _PinnedConnection(addr, self.port, self.fp, self.timeout)
            try:
                conn.connect()
            except _Mismatch as e:
                mismatch = mismatch or e.actual
                mismatched.append(addr)
                conn.close()
                continue
            except (OSError, ssl.SSLError) as e:
                offline.append(f"{addr}: {e}")
                conn.close()
                continue
            headers = {"Accept": "application/json", "Connection": "close"}
            if ctype:
                headers["Content-Type"] = ctype
            if auth and self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            try:
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                status = resp.status
            except (OSError, ssl.SSLError, http.client.HTTPException) as e:
                raise Offline(f"{addr}:{self.port}: {type(e).__name__}: {e}") from None
            finally:
                conn.close()
            self._good = addr
            if mismatched and self._log:
                for bad in mismatched:
                    self._log(f"certificate mismatch on {bad}, using {addr}")
            return self._result(status, data, raw)
        if mismatch:
            raise CertChanged(self.fp, mismatch)
        raise Offline(f"could not reach the filament-kit server ({'; '.join(offline) or 'no address'})")

    @staticmethod
    def _result(status: int, data: bytes, raw: bool):
        if status >= 400:
            code, message = f"http_{status}", ""
            try:
                body = json.loads(data)
                if isinstance(body, dict):
                    code = str(body.get("error") or code)
                    message = str(body.get("message") or "")
            except ValueError:
                pass
            raise ApiError(status, code, message)
        if raw:
            return data
        try:
            return json.loads(data) if data else {}
        except ValueError:
            raise ApiError(status, "bad_response", "the server's answer is not JSON") from None

    # --- routes -----------------------------------------------------------------------------

    def info(self) -> dict:
        return self._request("GET", "/api/info", auth=False)

    def pair(self, code: str) -> str:
        res = self._request("POST", "/api/pair", json.dumps({"code": code}).encode(), "application/json", auth=False)
        token = res.get("token") if isinstance(res, dict) else None
        if not isinstance(token, str) or not token:
            raise ApiError(200, "bad_response", "the server did not return a token")
        return token

    def state(self) -> dict:
        return self._request("GET", "/api/sync/state")

    def upload(self, kind: str, data: bytes, user_id: str | None = None, partial: str | None = None) -> dict:
        """`partial` (live and orca_live): the stamp of a build whose install stopped part-way in this folder (S28).
        `orca_live` / `orca_system` go to the same routes with `?target=orca` (no user id; Ruling O)."""
        if kind == "live":
            q = {k: v for k, v in (("user_id", user_id), ("partial", partial)) if v}
            path = "/api/sync/live" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        elif kind == "system":
            path = "/api/sync/system"
        elif kind == "orca_live":
            q = {"target": "orca", **({"partial": partial} if partial else {})}
            path = f"/api/sync/live?{urllib.parse.urlencode(q)}"
        elif kind == "orca_system":
            path = "/api/sync/system?target=orca"
        else:
            raise ValueError(f"unknown upload kind {kind!r}")
        return self._request("PUT", path, data, "application/zip")

    def rebuild(self, live_hash: str, orca_live_hash: str | None = None) -> dict:
        body = {"live_hash": live_hash}
        if orca_live_hash:
            body["orca_live_hash"] = orca_live_hash      # Ruling O
        return self._request("POST", "/api/sync/rebuild", json.dumps(body).encode(), "application/json")

    def build(self, stamp: str) -> bytes:
        return self._request("GET", f"/api/sync/build?{urllib.parse.urlencode({'stamp': stamp})}", raw=True)

    def installed(self, stamp: str) -> dict:
        return self._request("POST", "/api/sync/installed", json.dumps({"stamp": stamp}).encode(),
                             "application/json")
