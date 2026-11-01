"""Printer registry: `state/printers.json` (mode 600). Holds Access Codes, so it never leaves the server."""
from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from .. import config
from ..pairing import _write_atomic

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the service only runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)
FILE = "printers.json"
_lock = threading.Lock()


@contextmanager
def _locked():
    """Serialize registry access between threads and with the CLI in another process."""
    with _lock:
        if fcntl is None:
            yield
            return
        state = config.paths().state
        state.mkdir(parents=True, exist_ok=True)
        with open(state / "printers.lock", "a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@dataclass
class Printer:
    serial: str
    name: str = ""
    model: str = ""
    ip: str = ""
    access_code: str = field(default="", repr=False)
    configured: bool = False


class RegistryError(Exception):
    pass


_FIELDS = {"name", "model", "ip", "access_code", "configured"}


def _read() -> dict[str, Printer]:
    """Read the file. Raises RegistryError when it exists but cannot be understood; caller holds _locked()."""
    f = config.paths().state / FILE
    if not f.exists():
        return {}
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        return {s: Printer(serial=s, **{k: v for k, v in d.items() if k in _FIELDS}) for s, d in raw.items()}
    except (OSError, ValueError, TypeError, AttributeError) as e:
        raise RegistryError(f"{f} is unreadable ({e}); fix or remove it, nothing was changed") from e


def _write(printers: dict[str, Printer]) -> None:
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    data = {s: asdict(p) for s, p in printers.items()}
    _write_atomic(state / FILE, json.dumps(data, indent=2).encode("utf-8"), 0o600)


def load() -> dict[str, Printer]:
    """All printers. A corrupt file is logged and read as empty; it is never overwritten by a read."""
    with _locked():
        try:
            return _read()
        except RegistryError as e:
            log.error("%s", e)
            return {}


def upsert(p: Printer) -> None:
    with _locked():
        printers = _read()
        printers[p.serial] = p
        _write(printers)


def remove(serial: str) -> bool:
    with _locked():
        printers = _read()
        if serial not in printers:
            return False
        del printers[serial]
        _write(printers)
        return True


def rename(serial: str, name: str) -> bool:
    with _locked():
        printers = _read()
        if serial not in printers:
            return False
        printers[serial].name = name
        _write(printers)
        return True


def detected(serial: str, ip: str, model: str = "", name: str = "") -> Printer:
    """Record an SSDP announcement. New printer: unconfigured entry. Known one: IP follows the announcement;
    only an unconfigured entry also takes model/name. A configured entry's Access Code and name are untouched."""
    with _locked():
        printers = _read()
        p = printers.get(serial)
        if p is None:
            p = Printer(serial=serial, name=name or serial, model=model, ip=ip)
        else:
            before = (p.ip, p.model, p.name)
            p.ip = ip
            if not p.configured:
                p.model = model or p.model
                p.name = name or p.name
            if (p.ip, p.model, p.name) == before:
                return p
        printers[serial] = p
        _write(printers)
        return p
