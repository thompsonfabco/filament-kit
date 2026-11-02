"""Printer registry: `state/printers.json` (mode 600). Holds Access Codes, so it never leaves the server."""
from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from .. import config
from ..pairing import _write_atomic, open_lock

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the service only runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)
FILE = "printers.json"
SERIAL = re.compile(r"[A-Za-z0-9_-]{1,64}")      # also names the camera's runtime directory
ACCESS_CODE = re.compile(r"[A-Za-z0-9]{1,32}")
BAD_SERIAL = "the serial number may only have letters, digits, - and _ (at most 64)"
BAD_ACCESS_CODE = ("the Access Code is the letters and digits shown on the printer's screen "
                   "(at most 32, no spaces or symbols)")


def check_fields(serial: str, code: str) -> str | None:
    """A plain-English problem with a serial number / Access Code pair, or None when both are usable.
    The message never contains the code."""
    if not SERIAL.fullmatch(serial):
        return BAD_SERIAL
    if not ACCESS_CODE.fullmatch(code):
        return BAD_ACCESS_CODE
    return None
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
        with open_lock(state / "printers.lock") as fh:
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
    _write_atomic(state / FILE, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)


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


def detected(serial: str, ip: str, model: str = "", name: str = "", keep_ip: bool = False) -> Printer:
    """Record an SSDP announcement. New printer: unconfigured entry. Known one: IP follows the announcement
    (unless `keep_ip`: the caller has a live connection to the old IP, so a moved announce is ignored);
    only an unconfigured entry also takes model/name. A configured entry's Access Code and name are untouched.
    Every IP change of a configured printer is logged as a warning (serial and both IPs, never the code)."""
    with _locked():
        printers = _read()
        p = printers.get(serial)
        if p is None:
            p = Printer(serial=serial, name=name or serial, model=model, ip=ip)
        else:
            before = (p.ip, p.model, p.name)
            if p.configured and ip != p.ip:
                log.warning("printer %s announced itself at %s (registry has %s)%s", serial, ip, p.ip,
                            "; ignored while the printer is connected at the old address" if keep_ip else
                            "; following it")
            if not (p.configured and keep_ip):
                p.ip = ip
            if not p.configured:
                p.model = model or p.model
                p.name = name or p.name
            if (p.ip, p.model, p.name) == before:
                return p
        printers[serial] = p
        _write(printers)
        return p


class AlreadyConfigured(RegistryError):
    pass


def set_code(serial: str, code: str, name: str | None = None, replace: bool = False) -> Printer:
    """Atomically configure `serial` with an Access Code (creating the entry if needed). A printer that is
    already configured raises AlreadyConfigured unless `replace`; the name only changes when one is given."""
    with _locked():
        printers = _read()
        p = printers.get(serial) or Printer(serial=serial)
        if p.configured and not replace:
            raise AlreadyConfigured(serial)
        p.access_code = code
        p.configured = True
        p.name = (name or "").strip() or p.name or serial
        printers[serial] = p
        _write(printers)
        return p
