"""Phone pairing: self-signed cert, pairing tokens/codes, device registry."""
from __future__ import annotations

import datetime as dt
import errno
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

# cryptography is imported where a certificate is read or made, so the file helpers below (_write_atomic,
# open_lock ...) import without it: the release job's library build uses them with a plain Python.

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
        with open_lock(state / "pairing.lock") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class PairingError(Exception):
    pass


class CertUnreadable(PairingError):
    """The certificate exists but this user may not read it (the CLI run without sudo)."""


@dataclass
class Pairing:
    token: str
    code: str
    expires: float
    qr: str


def fingerprint(cert_pem: bytes) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.fingerprint(hashes.SHA256()).hex()


def give_to_state_owner(path) -> None:
    """Run as root (`sudo filament-kit config`), a new state file would belong to root and the service user
    could not read it: hand it to the owner of the state directory instead. A no-op for everyone else."""
    if getattr(os, "geteuid", lambda: -1)() != 0:
        return
    st = os.stat(config.paths().state)
    os.chown(path, st.st_uid, st.st_gid, follow_symlinks=False)      # never through a planted link


def make_state_dir(path) -> None:
    """`mkdir -p` for a directory in the state directory; each directory it creates is handed to the state
    directory's owner (as `give_to_state_owner` does for files), so a root-run CLI that creates
    `printers/<serial>/` first does not lock the service user out of it."""
    path = Path(path)
    missing = []
    p = path
    while not p.exists() and p.parent != p:
        missing.append(p)
        p = p.parent
    path.mkdir(parents=True, exist_ok=True)
    state = Path(config.paths().state)
    for d in reversed(missing):
        if state in d.parents:
            give_to_state_owner(d)


_REFUSED = (errno.EACCES, errno.EPERM, errno.EROFS)


class LockUnavailable(OSError):
    """A lock this process may not create, and that does not exist yet (made by the kit's install as root)."""


def open_lock(path: Path):
    """Open (creating if needed) a lock file in the state directory, owned like the state directory."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fh = os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | nofollow, 0o644), "a")
    except OSError as e:
        if e.errno not in _REFUSED:
            raise
        # a lock this process may only read (the web unit's user on the kit's locks, or a read-only mount under
        # ProtectSystem=strict): flock works on a read-only descriptor all the same
        try:
            fh = os.fdopen(os.open(path, os.O_RDONLY | nofollow), "r")
        except FileNotFoundError:
            raise LockUnavailable(e.errno, f"the lock {path} is missing and this process may not create it; "
                                  "run `sudo filament-kit modules apply` to make the shared locks", str(path)) from e
    try:
        give_to_state_owner(path)
    except BaseException:
        fh.close()
        raise
    return fh


def _write_atomic(path: Path, data: bytes, mode: int, state_owned: bool = False) -> None:
    """Write via a temp file and a rename. `state_owned`: a state file, handed to the state directory's owner
    before the rename when running as root."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
            # mode and owner on the open file, not by name: a link swapped in at `tmp` is never followed
            if hasattr(os, "fchmod"):
                os.fchmod(fh.fileno(), mode)
            else:
                os.chmod(tmp, mode)
            if state_owned and getattr(os, "geteuid", lambda: -1)() == 0:
                st = os.stat(config.paths().state)
                os.fchown(fh.fileno(), st.st_uid, st.st_gid)
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


def short_hostname() -> str:
    """The host's own name without any domain: what avahi publishes as <name>.local."""
    return socket.gethostname().split(".")[0]


def make_cert(hostname: str, ips: list[str], dest: Path, extra_dns: list[str] = ()) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    dns = list(dict.fromkeys([hostname, f"{hostname}.local", "localhost", *extra_dns]))
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
    try:   # never through a link: root (modules apply) reads these too, in a folder the service user owns
        fd = os.open(f, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return []
    with os.fdopen(fd, encoding="utf-8") as fh:
        return json.loads(fh.read())


def _write(name: str, obj: list) -> None:
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    _write_atomic(state / name, json.dumps(obj, indent=2).encode("utf-8"), 0o600, state_owned=True)


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


def issue(device_hint: str = "", role: str | None = None, scope: str | None = None) -> Pairing:
    """A new pairing for a device named `device_hint`. `scope` ("station") limits its token to that scope's routes; it is
    given here, never read from the name. `role` marks what the device is for routes that serve only
    one kind of device ("web": the web unit's pairing, made by `modules apply` as root; see role_of)."""
    cert = config.paths().etc / "cert.pem"
    try:
        cert_pem = cert.read_bytes()
    except FileNotFoundError:
        raise PairingError(f"no server certificate at {cert}; create it first") from None
    except PermissionError:
        raise CertUnreadable(f"cannot read the server certificate {cert}: permission denied") from None
    fp = fingerprint(cert_pem)
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
            # the intake station's token reaches only /api/station/* (api._authed); phones and the PC sync: all
            **({"scope": scope} if scope else {}),
            **({"role": role} if role else {}),
        })
        _write("devices.json", devs)

        pending = [p for p in _read("pending.json") if p["expires"] > now]
        pending.append({"code": code, "device": device_id, "expires": expires, "attempts": 0})
        _write("pending.json", pending)

    # server_name is only a display name; the phone finds the server by mDNS hostname or one of its IPs
    query = urllib.parse.urlencode(
        {"h": f"{short_hostname()}.local", "p": port, "t": token, "fp": fp, "ip": local_ips()},
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


def authorize(token: str) -> tuple[str, str | None] | None:
    """(device id, scope) for a live token, else None. Claims an unclaimed QR token (its first use). scope is
    "station" for a token from `pair --station`, "web" for the web unit's (from its role, so a pairing made before this
    needs nothing done), else None (every route but the web unit's own)."""
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
                # a device paired as "station" before scopes existed is scoped too
                if d.get("scope") or d.get("name") == "station":
                    return d["id"], d.get("scope") or "station"
                return d["id"], "web" if d.get("role") == WEB_ROLE else None
        return None


def check(token: str) -> str | None:
    got = authorize(token)
    return got[0] if got else None


def revoke(device_id: str) -> bool:
    with _locked():
        devs = _load_devices()
        kept = [d for d in devs if d["id"] != device_id]
        if len(kept) == len(devs):
            return False
        _write("devices.json", kept)
        return True


WEB_ROLE = "web"     # the web unit's pairing: the kit API's web-only routes (GET /api/intake/orders) serve it


def role_of(device_id: str) -> str | None:
    """The `role` of a paired device's record (None: none set, or no such device)."""
    with _locked():
        for d in _load_devices():
            if d.get("id") == device_id:
                r = d.get("role")
                return r if isinstance(r, str) else None
    return None


def set_role_by_name(name: str, role: str) -> int:
    """Give `role` to every device named `name` that has none (the upgrade of pairings made before roles
    existed). Returns how many changed."""
    with _locked():
        devs = _load_devices()
        n = 0
        for d in devs:
            if d.get("name") == name and not d.get("role"):
                d["role"] = role
                n += 1
        if n:
            _write("devices.json", devs)
        return n


def devices() -> list[dict]:
    with _locked():
        return [
            {k: d[k] for k in ("id", "name", "paired", "last_seen")}
            for d in _load_devices()
            if d.get("claimed") is not None
        ]
