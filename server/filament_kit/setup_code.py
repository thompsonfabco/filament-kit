"""The setup code: what the kit server's /setup page asks for before it changes anything (owner's choice A,
2026-11-07). Viewing the page needs no code; every change of a secret, a pairing or a module does.

  - 8 random digits, shown as 1234-5678 (`shown`); typed with or without the dash or spaces (`normalize`).
  - `/etc/filament-kit/setup_code`: "salt_hex digest_hex", salted scrypt like the web passphrase, root only
    (600, Ruling CF): only the root helper (setup_helper.py, op `check`) ever checks a code, so a process running as
    the service user cannot take the hash away and guess offline.
  - `/etc/filament-kit/setup_code.plain`: the code itself, root only (600), so `sudo filament-kit setup-code` can
    show it again; `--new` replaces both and clears the lockout.
  - `Lockout` (`/etc/filament-kit/setup_lockout`, root only, flock): at most LOCK_MAX wrong codes per LOCK_WINDOW
    seconds per client address, counted before the (slow) check like the passphrase's (A-M1); and over all addresses
    at most GLOBAL_MAX per window, after which every check waits a backoff that doubles each time the ceiling is hit
    again (LOCK_WINDOW, 2x, 4x ... at most MAX_BACKOFF); a right code resets it, and every quiet hour (DECAY)
    after a backoff ends takes it one level down, so one later burst does not start at the top.

Nothing here logs or prints a code."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from . import config

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the helper only runs on Linux)
    fcntl = None

HASH_FILE = "setup_code"
PLAIN_FILE = "setup_code.plain"
LOCK_FILE = "setup_lockout"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1, "maxmem": 2 ** 26}   # as the web passphrase (web/auth.py)
LOCK_MAX, LOCK_WINDOW = 5, 600
GLOBAL_MAX = 30
MAX_BACKOFF = 24 * 3600
DECAY = 3600            # each quiet hour after a backoff takes the next one a level down
DIGITS = 8
GROUP = "filament-kit"


def generate() -> str:
    return f"{secrets.randbelow(10 ** DIGITS):0{DIGITS}d}"


def shown(code: str) -> str:
    """'12345678' -> '1234-5678'."""
    return f"{code[:4]}-{code[4:]}"


def normalize(text) -> str | None:
    """The 8 digits of a typed code (dashes and spaces dropped), or None when it is not one."""
    if not isinstance(text, str) or len(text) > 32:
        return None
    digits = re.sub(r"[\s-]", "", text)
    return digits if re.fullmatch(rf"[0-9]{{{DIGITS}}}", digits) else None


def _hash(code: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()} {hashlib.scrypt(code.encode(), salt=salt, **SCRYPT).hex()}"


def hash_file() -> Path:
    return config.paths().etc / HASH_FILE


def plain_file() -> Path:
    return config.paths().etc / PLAIN_FILE


def is_set() -> bool:
    try:
        return hash_file().stat().st_size > 0
    except OSError:
        return False


def check(text) -> bool | None:
    """True/False for a right/wrong code; None (falsy) when no code is set or the file cannot be read."""
    try:
        salt, digest = hash_file().read_text(encoding="utf-8").split()
        salt_b = bytes.fromhex(salt)
    except (OSError, ValueError):
        return None
    code = normalize(text)
    if code is None:
        return False
    got = hashlib.scrypt(code.encode(), salt=salt_b, **SCRYPT).hex()
    return hmac.compare_digest(got, digest)


def _write(dest: Path, data: bytes, mode: int, group: str | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        if os.name == "nt":
            tmp.write_bytes(data)
        else:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
            with os.fdopen(fd, "wb") as fh:
                os.fchmod(fh.fileno(), mode)
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if os.geteuid() == 0:
                shutil.chown(tmp, user="root", group=group or "root")
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write(code: str) -> None:
    """Store `code` (root): its hash and itself, both root only (600). The plain file goes first: a hash whose code
    nobody can show again would lock the owner out of the page. A new code starts with a clear lockout."""
    if normalize(code) != code:
        raise ValueError("a setup code is 8 digits")
    _write(plain_file(), (code + "\n").encode(), 0o600, None)
    _write(hash_file(), (_hash(code) + "\n").encode(), 0o600, None)
    lockout_file().unlink(missing_ok=True)


def read() -> str | None:
    """The code (root only): None when there is none or it cannot be read."""
    try:
        code = plain_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return code if normalize(code) == code else None


def ensure() -> str:
    """The current code, made (and stored) when there is none yet or the two files disagree."""
    code = read()
    if code is not None and check(code):
        return code
    code = generate()
    write(code)
    return code


class Lockout:
    """Wrong codes per client address and over all of them, in `path` (root only, locked with flock), shared by
    every helper process. `attempt(client)` counts one try before the check and returns a ticket (None, and nothing
    counted, when that client or everyone is locked out); a right code `release(ticket, ok=True)`s it, which also
    ends a global backoff; a check that could not run `release(ticket)`s it."""

    def __init__(self, path: Path, max_fails: int = LOCK_MAX, window: float = LOCK_WINDOW,
                 global_max: int = GLOBAL_MAX):
        self.path, self.max, self.window, self.global_max = Path(path), max_fails, window, global_max
        self._lock = threading.Lock()

    @staticmethod
    def _load(fh) -> dict:
        fh.seek(0)
        try:
            d = json.loads(fh.read() or "{}")
        except ValueError:
            d = {}
        if not isinstance(d, dict):
            d = {}
        fails = [f for f in d.get("fails") or [] if isinstance(f, list) and len(f) == 3
                 and isinstance(f[0], (int, float))]
        num = lambda k: d.get(k) if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool) else 0  # noqa: E731
        level = d.get("level") if isinstance(d.get("level"), int) and not isinstance(d.get("level"), bool) else 0
        return {"fails": fails, "until": num("until"), "level": max(0, level), "since": num("since")}

    @staticmethod
    def _decay(st: dict, now: float) -> None:
        base = max(st["until"], st["since"])
        if st["level"] and now - base >= DECAY:
            steps = int((now - base) // DECAY)
            st["level"] = max(0, st["level"] - steps)
            st["since"] = base + steps * DECAY

    def _update(self, fn):
        """Run fn(state, now) -> result on the pruned state, under the lock and the file's flock."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            with os.fdopen(fd, "r+", encoding="utf-8") as fh:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                now = time.time()
                st = self._load(fh)
                st["fails"] = [f for f in st["fails"] if f[0] > now - self.window]
                self._decay(st, now)
                out = fn(st, now)
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps(st))
                fh.flush()
                return out

    def attempt(self, client: str) -> str | None:
        client = str(client or "?")[:64]

        def take(st, now):
            if now < st["until"]:
                return None
            if sum(1 for f in st["fails"] if f[1] == client) >= self.max:
                return None
            ticket = secrets.token_hex(8)
            st["fails"].append([now, client, ticket])
            if len(st["fails"]) >= self.global_max:     # the ceiling: everyone waits, longer each time
                st["until"] = now + min(self.window * 2 ** st["level"], MAX_BACKOFF)
                st["level"] += 1
                st["since"] = now
                st["fails"] = []
            return ticket
        return self._update(take)

    def release(self, ticket: str | None, ok: bool = False) -> None:
        if ticket is None:
            return

        def drop(st, now):
            st["fails"] = [f for f in st["fails"] if f[2] != ticket]
            if ok:
                st["level"] = 0
        self._update(drop)


def lockout_file() -> Path:
    return config.paths().etc / LOCK_FILE


def page_url(cfg: dict) -> str:
    """The setup page's address as the installer prints it: https://<host>.local:<port>/setup."""
    from . import pairing
    return f"https://{pairing.short_hostname()}.local:{int(cfg.get('port', 8710))}/setup"
