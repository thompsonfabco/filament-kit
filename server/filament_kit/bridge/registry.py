"""Printer registry: `state/printers.xml` (mode 600). Holds Access Codes and Moonraker API keys, so it never leaves
the server.

Layout (spec 2026-11-03-klipper-printers §5.3): `<printers version="1">` with one `<printer>` per printer; plain
fields are attributes (`id family name model ip host port configured cert-fp lane-data`), secrets are child elements
(`<access-code>`, `<api-key>`) so a one-line grep never shows them. `family` is "bambu" (key = serial number) or
"klipper" (key = a slug of the name, `slug`). Unknown attributes and elements are ignored (a newer file).

Rollback (`update --rollback`, a failed install's restore): the release before this one reads only `printers.json`.
So every write also writes `printers.json` in that release's format (Bambu printers only, its six fields), and the
XML root records the SHA-256 of the JSON it wrote (`json-sha256`). A read that finds a JSON with another hash knows
an older release changed it (a code re-entered after a rollback): that JSON's Bambu printers replace the XML's and
the change is logged; Klipper printers stay as the XML has them. Without an XML (an upgrade), the JSON is read and
both files are written. The JSON is never renamed or removed."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
import logging
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace

from .. import config, hostaddr
from . import xmlfile
from ..pairing import _write_atomic, open_lock

try:
    import fcntl
except ImportError:  # Windows dev PCs: no cross-process lock (the service only runs on Linux)
    fcntl = None

log = logging.getLogger(__name__)
FILE = "printers.xml"
OLD_FILE = "printers.json"
MAX_FOUND = 32          # Klipper entries discovery made and nobody has added yet
FAMILIES = ("bambu", "klipper")
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
    cert_fp: str = ""   # SHA-256 of the printer's TLS leaf (DER, lowercase hex), pinned on first use; see tlspin
    family: str = "bambu"   # "bambu" | "klipper" (bridge.family routes by it)
    host: str = ""          # Klipper: Moonraker host name (a *.localdomain name preferred) or address
    port: int = 7125        # Klipper: Moonraker port
    api_key: str = field(default="", repr=False)   # Klipper: Moonraker API key when it wants one (never shown)
    lane_data: str = "auto"  # Klipper: publish slots to Moonraker lane_data: auto (multi-tool) | on | off


def display_name(p: Printer) -> str:
    """The printer's name everywhere it is shown or joined on (Spoolman slot locations "<name> – AMS <label>",
    usage's spool lookup, the status join): the registry name, else the serial. Renaming a printer therefore
    moves its slot locations: spools already "in" it keep the old location text (see README)."""
    return p.name or p.serial


class RegistryError(Exception):
    pass


class DuplicatePrinter(RegistryError):
    """That Klipper host and port is already added: the message names the entry."""


_FIELDS = {"name", "model", "ip", "access_code", "configured", "cert_fp", "family", "host", "port", "api_key"}
_OLD_FIELDS = ("name", "model", "ip", "access_code", "configured", "cert_fp")   # what the release before reads
LANE_DATA = ("auto", "on", "off")
_ATTRS = (("name", "name"), ("model", "model"), ("ip", "ip"), ("host", "host"), ("cert-fp", "cert_fp"))
_SECRETS = (("access-code", "access_code"), ("api-key", "api_key"))


def _from_xml(data: bytes, where) -> dict[str, Printer]:
    return _from_xml_sha(data, where)[0]


def _from_xml_sha(data: bytes, where) -> tuple[dict[str, Printer], str | None]:
    """(printers, the json-sha256 the XML recorded, or None)."""
    from defusedxml.ElementTree import fromstring
    root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if root.tag != "printers":
        raise ValueError(f"root element is <{root.tag}>, not <printers>")
    out: dict[str, Printer] = {}
    for el in root.findall("printer"):
        pid = el.get("id", "")
        if not pid:
            raise ValueError("a <printer> has no id")
        p = Printer(serial=pid)
        for attr, name in _ATTRS:
            setattr(p, name, el.get(attr, ""))
        fam = el.get("family", "bambu")
        p.family = fam if fam in FAMILIES else "bambu"
        p.configured = el.get("configured", "false") == "true"
        ld = el.get("lane-data", "auto")
        p.lane_data = ld if ld in LANE_DATA else "auto"
        try:
            p.port = int(el.get("port", "7125"))
        except ValueError:
            p.port = 7125
        for tag, name in _SECRETS:
            c = el.find(tag)
            setattr(p, name, (c.text or "").strip() if c is not None else "")
        out[pid] = p
    return out, root.get("json-sha256")


def _to_json(printers: dict[str, Printer]) -> bytes:
    """printers.json as the release before this one writes and reads it: Bambu printers only, its six fields."""
    data = {s: {k: getattr(p, k) for k in _OLD_FIELDS} for s, p in printers.items() if p.family != "klipper"}
    return json.dumps(data, indent=2).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _old_view(p: Printer) -> tuple:
    return tuple(getattr(p, k) for k in _OLD_FIELDS)


def _to_xml(printers: dict[str, Printer], json_sha: str | None = None) -> bytes:
    root = ET.Element("printers", version="1")
    if json_sha:
        root.set("json-sha256", json_sha)
    for pid, p in printers.items():
        el = ET.SubElement(root, "printer", id=xmlfile.clean(pid), family=p.family or "bambu")
        for attr, name in _ATTRS:
            v = getattr(p, name)
            if v:
                el.set(attr, xmlfile.clean(v))
        el.set("configured", "true" if p.configured else "false")
        if p.family == "klipper":
            el.set("port", str(p.port))
            if p.lane_data != "auto":
                el.set("lane-data", p.lane_data)
        for tag, name in _SECRETS:
            v = getattr(p, name)
            if v:
                ET.SubElement(el, tag).text = xmlfile.clean(v)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _from_json(raw: bytes) -> dict[str, Printer]:
    data = json.loads(raw.decode("utf-8"))
    return {s: Printer(serial=s, **{k: v for k, v in d.items() if k in _FIELDS}) for s, d in data.items()}


def _read(write: bool = True) -> dict[str, Printer]:
    """Read the registry (printers.json: see the module docstring). Raises RegistryError when the file in use exists
    but cannot be understood; caller holds _locked(), and `write=False` (peek) is what needs no lock."""
    state = config.paths().state
    f, old = state / FILE, state / OLD_FILE
    if not f.exists():
        try:
            raw = old.read_bytes()
        except FileNotFoundError:
            return {}
        try:
            printers = _from_json(raw)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            raise RegistryError(f"{old} is unreadable ({e}); fix or remove it, nothing was changed") from e
        if not write:
            return printers
        try:
            _write(printers)
            log.info("printer registry: %s written from %s (%s is kept for a rollback)", FILE, OLD_FILE, OLD_FILE)
        except OSError as e:
            log.error("printer registry: cannot write %s (%s); reading %s until it can", FILE, e, OLD_FILE)
        return printers
    try:
        printers, sha = _from_xml_sha(f.read_bytes(), f)
    except Exception as e:  # noqa: BLE001 - ParseError, DTDForbidden, ValueError ...
        raise RegistryError(f"{f} is unreadable ({e}); fix or remove it, nothing was changed") from e
    try:
        raw = old.read_bytes()
    except FileNotFoundError:
        return printers                           # printers.json is written again at the next change
    except OSError as e:
        log.error("printer registry: cannot read %s (%s); using %s", OLD_FILE, e, FILE)
        return printers
    if sha is not None and _sha(raw) == sha:
        return printers
    try:
        bambu = {s: p for s, p in _from_json(raw).items() if p.family != "klipper"}
    except (ValueError, TypeError, AttributeError) as e:
        log.error("printer registry: %s is unreadable (%s); using %s (%s is rewritten at the next change)",
                  OLD_FILE, e, FILE, OLD_FILE)
        return printers
    mine = {s: p for s, p in printers.items() if p.family != "klipper"}
    if {s: _old_view(p) for s, p in bambu.items()} == {s: _old_view(p) for s, p in mine.items()}:
        return printers                           # the same Bambu printers (no hash recorded yet, or rewritten)
    merged = {s: p for s, p in printers.items() if p.family == "klipper"}
    merged.update({s: p for s, p in bambu.items() if s not in merged})
    log.warning("printer registry: %s was changed by another program (an older filament-kit after a rollback?); "
                "its Bambu printers replace those in %s", OLD_FILE, FILE)
    if not write:
        return merged
    try:
        _write(merged)
    except OSError as e:
        log.error("printer registry: cannot update %s (%s)", FILE, e)
    return merged


def _write(printers: dict[str, Printer]) -> None:
    """printers.json first (the release before this one reads it), then printers.xml with that file's hash: a stop
    in between leaves a hash that doesn't match, and the next read takes the newer JSON's Bambu printers."""
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    js = _to_json(printers)
    _write_atomic(state / OLD_FILE, js, 0o600, state_owned=True)
    _write_atomic(state / FILE, _to_xml(printers, _sha(js)), 0o600, state_owned=True)


def peek() -> dict[str, Printer]:
    """The registry as load() would see it, for a dry run: no lock file, no migration, nothing written."""
    return _read(write=False)


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
        printers[serial].name = _free_name(name, printers, serial)
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
            by_name = p.configured and p.ip and not hostaddr.is_literal(p.ip)   # a name the owner typed stays: it resolves at use
            if p.configured and ip != p.ip and not by_name:
                log.warning("printer %s announced itself at %s (registry has %s)%s", serial, ip, p.ip,
                            "; ignored while the printer is connected at the old address" if keep_ip else
                            "; following it")
            if not (p.configured and keep_ip) and not by_name:
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
    already configured raises AlreadyConfigured unless `replace`; the name only changes when one is given. Clears
    the TLS pin: the next connection pins the leaf the printer presents then."""
    with _locked():
        printers = _read()
        p = printers.get(serial) or Printer(serial=serial)
        if p.configured and not replace:
            raise AlreadyConfigured(serial)
        p.access_code = code
        p.configured = True
        p.cert_fp = ""          # adding the printer again with its code = trust the leaf it presents next
        p.name = (name or "").strip() or p.name or serial
        printers[serial] = p
        _write(printers)
        return p


def pin(serial: str, fp: str) -> str:
    """Pin `fp` as `serial`'s TLS leaf unless one is pinned already; returns the pin now in force (the earlier
    one wins). A printer no longer in the registry is not written; `fp` is returned as is."""
    with _locked():
        printers = _read()
        p = printers.get(serial)
        if p is None:
            return fp
        if p.cert_fp:
            return p.cert_fp
        p.cert_fp = fp
        _write(printers)
        return fp


def clear_pin(serial: str) -> bool:
    """Forget `serial`'s pinned leaf; the next connection pins again. False when there is no such printer."""
    with _locked():
        printers = _read()
        p = printers.get(serial)
        if p is None:
            return False
        if p.cert_fp:
            p.cert_fp = ""
            _write(printers)
        return True


_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def slug(name: str, taken: set[str]) -> str:
    """A Klipper printer's id from its name: lower case, other characters -> "-", at most 48; "-2", "-3" ... on a
    clash with `taken`; "printer" when nothing is left."""
    base = _SLUG_RUN.sub("-", (name or "").lower()).strip("-")[:48].strip("-") or "printer"
    out, n = base, 1
    while out in taken:
        n += 1
        out = f"{base}-{n}"
    return out


def _host_key(host: str) -> str:
    """A host name as DNS compares it. Only the same text matches: an address and a name for it are the manager's job."""
    return (host or "").strip().rstrip(".").lower()


def _at(printers: dict[str, Printer], host: str, port: int) -> Printer | None:
    for p in printers.values():
        if p.family == "klipper" and p.port == int(port) and _host_key(p.host) == _host_key(host):
            return p
    return None


def _free_name(name: str, printers: dict[str, Printer], me: str = "") -> str:
    """`name`, or "name 2", "name 3" ...: Spoolman slot locations join on the display name (see display_name), so two
    printers with one name would share spools."""
    taken = {display_name(p).lower() for s, p in printers.items() if s != me and p.configured}
    out, n = name, 1
    while out.lower() in taken:
        n += 1
        out = f"{name} {n}"
    return out


def add_klipper(name: str, host: str, port: int = 7125) -> Printer:
    """Add a configured Klipper printer (host = Moonraker's host name or address). The entry discovery made for the same
    host and port becomes this one. DuplicatePrinter when that host and port is already added."""
    host, name = host.strip(), (name or host).strip()
    with _locked():
        printers = _read()
        old = _at(printers, host, port)
        if old is not None and old.configured:
            raise DuplicatePrinter(f"{host}:{port} is already added as {display_name(old)}")
        if old is not None:
            p = replace(old, name=_free_name(name, printers, old.serial), host=host, configured=True)
        else:
            p = Printer(serial=slug(name, set(printers)), name=_free_name(name, printers), family="klipper",
                        host=host, port=int(port), configured=True)
        printers[p.serial] = p
        _write(printers)
        return p


def set_api_key(pid: str, key: str) -> bool:
    """Store (or clear, with "") a Klipper printer's Moonraker API key. False when there is no such printer."""
    with _locked():
        printers = _read()
        p = printers.get(pid)
        if p is None:
            return False
        p.api_key = key.strip()
        _write(printers)
        return True


def configure_klipper(pid: str, name: str = "") -> bool:
    """A Klipper printer a scan found goes into use. False when there is no such printer."""
    with _locked():
        printers = _read()
        p = printers.get(pid)
        if p is None:
            return False
        p.configured = True
        p.name = name.strip() or p.name
        _write(printers)
        return True


def set_address(serial: str, host: str, port: int | None = None) -> bool:
    """Where the printer is, as typed: Bambu's `ip`, Klipper's `host` and `port`. Its pinned certificate stays: the pin is
    of the printer, not of its address. False when there is no such printer."""
    with _locked():
        printers = _read()
        p = printers.get(serial)
        if p is None:
            return False
        if p.family == "klipper":
            p.host = host
            p.port = int(port) if port else p.port
        else:
            p.ip = host
        _write(printers)
        return True


def klipper_names() -> set[str]:
    """Display names of the Klipper printers (their Spoolman slot locations start with "<name> – ")."""
    return {display_name(p) for p in load().values() if p.family == "klipper"}


def set_lane_data(pid: str, mode: str) -> bool:
    """Set a Klipper printer's lane_data publishing (auto | on | off). False when there is no such printer."""
    if mode not in LANE_DATA:
        raise ValueError(f"lane_data must be one of {', '.join(LANE_DATA)}")
    with _locked():
        printers = _read()
        p = printers.get(pid)
        if p is None:
            return False
        p.lane_data = mode
        _write(printers)
        return True


def klipper_at(printers: dict, host: str, port: int) -> Printer | None:
    """The configured Klipper printer at `host:port`, by text or because `host` and its typed name or address resolve to
    an address in common right now; else the unconfigured entry at that text, if any: a scan and an announcement report
    addresses, the owner types names or addresses, and one printer is one entry, so a twin must not hide what it's a twin
    of. A name that won't resolve matches by text only. No lookups unless a printer on that port is there to compare;
    call it outside the lock, as each name can take hostaddr.LOOKUP_WAIT."""
    port = int(port)
    here = [p for p in printers.values() if p.family == "klipper" and p.port == port]
    same = next((p for p in here if _host_key(p.host) == _host_key(host)), None)
    if same is not None and same.configured:
        return same
    added = [p for p in here if p.configured]
    mine = hostaddr.addresses(host) if added else set()
    if mine:
        for p in added:
            if mine & hostaddr.addresses(p.host):
                return p
    return same


def detected_klipper(host: str, port: int, name: str = "", lookups: bool = True) -> Printer:
    """Record a Klipper printer found on the LAN (mDNS or a scan): a new one is added unconfigured (the owner adds it
    with `filament-kit klipper add` or the app); a known host:port, or a configured name that resolves to it, is left
    as it is. `lookups` False compares text only, for a caller that has looked or can't wait: an unconfigured twin the
    sync's next round removes. Anything on the LAN can announce itself, so at most MAX_FOUND such entries stay in this
    file, which also holds the Access Codes: the oldest goes."""
    known = klipper_at(load(), host, port) if lookups else None      # the name lookups run outside the lock
    with _locked():
        printers = _read()
        if known is not None and known.serial in printers:
            return printers[known.serial]
        known = _at(printers, host, port)
        if known is not None:
            return known
        p = Printer(serial=slug(name or host, set(printers)), name=(name or host).strip(), family="klipper",
                    host=host, port=int(port), configured=False)
        printers[p.serial] = p
        found = [s for s, o in printers.items() if _forgettable(o) and s != p.serial]
        for s in found[:max(0, len(found) + 1 - MAX_FOUND)]:
            del printers[s]
        _write(printers)
        return p


def _forgettable(p: Printer) -> bool:
    return p.family == "klipper" and not p.configured and not p.api_key


def forget_found_at(addrs: set[tuple[str, int]]) -> int:
    """Remove the entries discovery made at these (host, port) pairs: printers already added under another name.
    An entry the owner gave an API key stays. How many went."""
    with _locked():
        printers = _read()
        gone = [s for s, p in printers.items() if _forgettable(p) and (p.host, p.port) in addrs]
        for s in gone:
            del printers[s]
        if gone:
            _write(printers)
        return len(gone)
