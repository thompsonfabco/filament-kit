"""The setup code: what the kit server's /setup page asks for before it changes anything (owner's choice A,
2026-11-07). Viewing the page needs no code; every change of a secret, a pairing or a module does.

  - 8 random digits, shown as 1234-5678 (`shown`); typed with or without the dash or spaces (`normalize`).
  - `/etc/filament-kit/setup_code`: "salt_hex digest_hex", salted scrypt like the web passphrase,
    root:filament-kit 640: the server checks a code, it cannot learn it.
  - `/etc/filament-kit/setup_code.plain`: the code itself, root only (600), so `sudo filament-kit setup-code` can
    show it again; `--new` replaces both.
  - `Lockout`: at most LOCK_MAX wrong codes per LOCK_WINDOW seconds, counted before the (slow) check like the
    passphrase's (A-M1). The page keeps one in memory; the root helper (one process per request) keeps one in
    `/etc/filament-kit/setup_lockout` (root only), so a local process cannot reset it.

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
    """Store `code` (root): its hash for the server (640, group filament-kit), itself for root (600). The plain
    file goes first: a hash whose code nobody can show again would lock the owner out of the page."""
    if normalize(code) != code:
        raise ValueError("a setup code is 8 digits")
    _write(plain_file(), (code + "\n").encode(), 0o600, None)
    _write(hash_file(), (_hash(code) + "\n").encode(), 0o640, GROUP)


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
    """At most `max_fails` wrong codes per `window` seconds, for the whole page (only the LAN can reach it).

    `attempt()` counts one try before the check and returns a ticket (None, and nothing counted, when locked out);
    a right code (or a check that could not run) `release()`s it. With `path` the count lives in that file
    (root only, locked with flock), shared by every helper process."""

    def __init__(self, path: Path | None = None, max_fails: int = LOCK_MAX, window: float = LOCK_WINDOW):
        self.path, self.max, self.window = path, max_fails, window
        self._fails: list[list] = []         # [[time, ticket]]
        self._lock = threading.Lock()

    def _load(self, fh) -> list[list]:
        fh.seek(0)
        try:
            data = json.loads(fh.read() or "[]")
            return [f for f in data if isinstance(f, list) and len(f) == 2 and isinstance(f[0], (int, float))]
        except ValueError:
            return []

    def _store(self, fh, fails: list[list]) -> None:
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(fails))
        fh.flush()

    def _update(self, fn):
        """Run fn(fails) -> result on the pruned list, under the lock (and the file's flock with a path)."""
        with self._lock:
            if self.path is None:
                now = time.time()
                self._fails[:] = [f for f in self._fails if f[0] > now - self.window]
                return fn(self._fails)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            with os.fdopen(fd, "r+", encoding="utf-8") as fh:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                now = time.time()
                fails = [f for f in self._load(fh) if f[0] > now - self.window]
                out = fn(fails)
                self._store(fh, fails)
                return out

    def blocked(self) -> bool:
        return self._update(lambda fails: len(fails) >= self.max)

    def attempt(self) -> str | None:
        def take(fails):
            if len(fails) >= self.max:
                return None
            ticket = secrets.token_hex(8)
            fails.append([time.time(), ticket])
            return ticket
        return self._update(take)

    def release(self, ticket: str | None) -> None:
        if ticket is None:
            return
        self._update(lambda fails: fails.__setitem__(slice(None), [f for f in fails if f[1] != ticket]))


def lockout_file() -> Path:
    return config.paths().etc / LOCK_FILE


def page_url(cfg: dict) -> str:
    """The setup page's address as the installer prints it: https://<host>.local:<port>/setup."""
    from . import pairing
    return f"https://{pairing.short_hostname()}.local:{int(cfg.get('port', 8710))}/setup"
