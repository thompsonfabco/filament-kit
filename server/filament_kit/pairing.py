"""Phone pairing: self-signed cert, pairing tokens/codes, device registry."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from . import config

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the service only runs on Linux)
    fcntl = None

TOKEN_TTL = 600
MAX_ATTEMPTS = 5
LAST_SEEN_STALE = 60
_lock = threading.Lock()


@contextmanager
def _locked():
    """Serialize pairing state between threads and with the CLI (`pair`/`unpair`) in another process."""
    with _lock:
        if fcntl is None:
            yield
            return
        state = config.paths().state
        state.mkdir(parents=True, exist_ok=True)
        with open(state / "pairing.lock", "a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class PairingError(Exception):
    pass


@dataclass
class Pairing:
    token: str
    code: str
    expires: float
    qr: str


def fingerprint(cert_pem: bytes) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.fingerprint(hashes.SHA256()).hex()


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _candidate_ips() -> list[str]:
    ips: list[str] = []
    if os.name != "nt":
        try:
            ips = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            ips = []
    if not ips:
        try:
            ips = [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
        except OSError:
            ips = []
    return ips


def _usable(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.version == 4 and not a.is_loopback and not a.is_link_local


def local_ips() -> list[str]:
    """This machine's IPv4 addresses a phone can reach: no loopback, no link-local (169.254.x.x)."""
    return list(dict.fromkeys(a for a in _candidate_ips() if _usable(a)))


def make_cert(hostname: str, ips: list[str], dest: Path) -> str:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    dns = list(dict.fromkeys([hostname, f"{hostname}.local", "localhost"]))
    sans: list[x509.GeneralName] = [x509.DNSName(n) for n in dns]
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in dict.fromkeys(ips) if _usable(ip)]
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    _write_atomic(dest / "cert.pem", cert_pem, 0o644)
    _write_atomic(dest / "key.pem", key_pem, 0o600)
    return fingerprint(cert_pem)


def _read(name: str) -> list:
    f = config.paths().state / name
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


def _write(name: str, obj: list) -> None:
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    _write_atomic(state / name, json.dumps(obj, indent=2).encode("utf-8"), 0o600)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _load_devices() -> list:
    """Read devices, purging QR tokens never claimed within their window. Caller holds _locked()."""
    now = time.time()
    devs = _read("devices.json")
    kept = [d for d in devs if d.get("claimed") is not None or d.get("expires", 0) > now]
    if len(kept) != len(devs):
        _write("devices.json", kept)
    return kept


def issue(device_hint: str = "") -> Pairing:
    cert = config.paths().etc / "cert.pem"
    if not cert.exists():
        raise PairingError(f"no server certificate at {cert}; create it first")
    fp = fingerprint(cert.read_bytes())
    port = config.load()["port"]
    with _locked():
        now = time.time()
        token = _new_token()
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires = now + TOKEN_TTL
        device_id = uuid.uuid4().hex[:12]

        devs = _load_devices()
        devs.append({
            "id": device_id,
            "name": device_hint or "phone",
            "hash": _hash(token),
            "paired": None,
            "last_seen": None,
            "expires": expires,
            "claimed": None,
        })
        _write("devices.json", devs)

        pending = [p for p in _read("pending.json") if p["expires"] > now]
        pending.append({"code": code, "device": device_id, "expires": expires, "attempts": 0})
        _write("pending.json", pending)

    # server_name is only a display name; the phone finds the server by mDNS hostname or one of its IPs
    query = urllib.parse.urlencode(
        {"h": f"{socket.gethostname()}.local", "p": port, "t": token, "fp": fp, "ip": local_ips()},
        doseq=True,
    )
    return Pairing(token=token, code=code, expires=expires, qr=f"fkit://pair?{query}")


def redeem_code(code: str) -> str:
    with _locked():
        now = time.time()
        pending = [p for p in _read("pending.json") if p["expires"] > now]
        match = None
        if isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code):
            match = next((p for p in pending if hmac.compare_digest(p["code"], code)), None)
        if match is None:
            # A wrong guess counts against every live code; at the limit a code is dropped.
            for p in pending:
                p["attempts"] += 1
            _write("pending.json", [p for p in pending if p["attempts"] < MAX_ATTEMPTS])
            raise PairingError("invalid, expired or locked pairing code")
        pending.remove(match)
        _write("pending.json", pending)
        devs = _load_devices()
        token = _new_token()
        for d in devs:
            if d["id"] == match["device"]:
                d["hash"] = _hash(token)
                d["paired"] = d["claimed"] = d["last_seen"] = now
                _write("devices.json", devs)
                return token
        raise PairingError("device for this code no longer exists")


def check(token: str) -> str | None:
    h = _hash(token)
    with _locked():
        devs = _load_devices()
        for d in devs:
            if hmac.compare_digest(d["hash"], h):
                now = time.time()
                if d.get("claimed") is None:
                    d["claimed"] = d["paired"] = d["last_seen"] = now
                    pend = [p for p in _read("pending.json") if p["device"] != d["id"]]
                    _write("pending.json", pend)
                    _write("devices.json", devs)
                elif d["last_seen"] is None or now - d["last_seen"] > LAST_SEEN_STALE:
                    d["last_seen"] = now
                    _write("devices.json", devs)
                return d["id"]
        return None


def revoke(device_id: str) -> bool:
    with _locked():
        devs = _load_devices()
        kept = [d for d in devs if d["id"] != device_id]
        if len(kept) == len(devs):
            return False
        _write("devices.json", kept)
        return True


def devices() -> list[dict]:
    with _locked():
        return [
            {k: d[k] for k in ("id", "name", "paired", "last_seen")}
            for d in _load_devices()
            if d.get("claimed") is not None
        ]
