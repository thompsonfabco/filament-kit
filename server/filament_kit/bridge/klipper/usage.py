"""The Klipper usage log: Moonraker's `[spoolman]` deducts filament live; the kit only records each job (spec §6).

`state/printers/<id>/usage.xml` holds `<entry>` elements (newest last, at most KEEP): id ("k-<job id>"), job,
file, started, ended (unix seconds), status (Moonraker's job status: completed, cancelled, error, klippy_shutdown
...), spool-id, filament-mm, grams (the file's `filament_weight_total` when the slicer wrote it) and
source="moonraker". Entries cannot be undone (Moonraker wrote Spoolman; the API answers 409 recorded_by_moonraker).
Nothing here ever writes to Spoolman or Moonraker.

`spoolman_report(server_config, kit_url, printer_host)` says whether Moonraker reports usage to the kit's Spoolman: same,
different or unknown (a name that doesn't resolve here may well resolve on the printer), with the line to show.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

from ... import config, pairing
from .. import xmlfile
from ..family import KLIPPER_ENTRY
from .moonraker import MoonrakerError, NotFound, _host_part

log = logging.getLogger(__name__)
FILE = "usage.xml"
KEEP = 2000
_lock = threading.Lock()


def _file(pid: str):
    return config.paths().state / "printers" / pid / FILE


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) < 1e12 else None


def _read(pid: str) -> list[dict]:
    try:
        from defusedxml.ElementTree import fromstring
        root = fromstring(_file(pid).read_bytes(), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001 - a broken file: start a new log rather than fail the status
        log.error("klipper usage log of %s is unreadable (%s)", pid, type(e).__name__)
        return []
    out = []
    for el in root.findall("entry"):
        sid = el.get("spool-id")
        out.append({"id": el.get("id", ""), "job": el.get("job", ""), "file": el.get("file", ""),
                    "started": _num(el.get("started")), "ended": _num(el.get("ended")),
                    "status": el.get("status", ""), "spool_id": int(sid) if (sid or "").isdigit() else None,
                    "filament_mm": _num(el.get("filament-mm")), "grams": _num(el.get("grams")),
                    "source": el.get("source", "moonraker")})
    return out


def _write(pid: str, entries: list[dict]) -> None:
    root = ET.Element("usage", version="1")
    for e in entries:
        attrs = {k: xmlfile.clean(e[k]) for k in ("id", "job", "file", "status", "source")}
        for k, name in (("started", "started"), ("ended", "ended"), ("filament_mm", "filament-mm"),
                        ("grams", "grams"), ("spool_id", "spool-id")):
            if e.get(k) is not None:
                attrs[name] = repr(e[k]) if isinstance(e[k], float) else str(e[k])
        ET.SubElement(root, "entry", attrs)
    ET.indent(root)
    f = _file(pid)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    tmp.replace(f)


def record(pid: str, job: dict, spool_id) -> dict:
    """Append Moonraker's history `job` (once per job id) and return the entry."""
    meta = job.get("metadata") or {}
    jid = str(job.get("job_id") or "")
    aux = next((a.get("value") for a in (job.get("auxiliary_data") or [])
                if isinstance(a, dict) and a.get("name") == "spool_ids"), None)
    if isinstance(aux, list) and aux and isinstance(aux[0], int):
        spool_id = aux[0]
    e = {"id": f"{KLIPPER_ENTRY}{jid or int(time.time())}", "job": jid, "file": str(job.get("filename") or ""),
         "started": _num(job.get("start_time")), "ended": _num(job.get("end_time")) or time.time(),
         "status": str(job.get("status") or ""), "spool_id": spool_id if isinstance(spool_id, int) else None,
         "filament_mm": _num(job.get("filament_used")), "grams": _num(meta.get("filament_weight_total")),
         "source": "moonraker"}
    with _lock:
        entries = _read(pid)
        old = next((x for x in entries if x["id"] == e["id"]), None)
        if old is not None:
            return old
        entries = (entries + [e])[-KEEP:]
        _write(pid, entries)
    log.info("klipper usage %s: job %s %s, %.0f mm (Moonraker deducted it in Spoolman)", pid, jid, e["status"],
             e["filament_mm"] or 0)
    return e


def entries(pid: str, days: float) -> list[dict]:
    """Entries of the last `days` days, newest first, shaped like the Bambu usage log's."""
    since = time.time() - days * 86400
    with _lock:
        got = _read(pid)
    return [{**e, "undone": False, "can_undo": False} for e in reversed(got) if (e["ended"] or 0) >= since]


# --- which Spoolman does Moonraker report to ----------------------------------------------------------------------

def _parse_host_port(url: str) -> tuple[str, int] | None:
    try:
        u = urllib.parse.urlsplit(url)
        host = (u.hostname or "").lower()
        return (host, u.port or (443 if u.scheme == "https" else 80)) if host else None
    except ValueError:
        return None


def _host_port(url: str) -> tuple[str, int] | None:
    """(host, port) of a URL, None when it has no readable host. An unencoded /, # or ? in a password would make
    urlsplit take part of the credentials for the host, so what comes before the last @ is dropped first. An @ after
    one of those characters is ambiguous when the part before them reads as host[:port] too: `user:123/x@host` and
    `host:7912/x@y` have the same shape, and guessing shows either a password or a wrong host. Those are unreadable."""
    try:
        scheme, sep, rest = url.strip().partition("://")
    except AttributeError:
        return None
    end = next((i for i, c in enumerate(rest) if c in "/?#"), len(rest))
    if "@" in rest[end:] and _parse_host_port(f"{scheme}{sep}{rest[:end].rpartition('@')[2]}"):
        return None
    return _parse_host_port(f"{scheme}{sep}{rest.rpartition('@')[2]}")


def spoolman_address(url: str) -> str | None:
    """A Spoolman URL as host:port, safe to show (it never holds the URL's credentials); None when unreadable."""
    hp = _host_port(url)
    return f"{_host_part(hp[0])}:{hp[1]}" if hp else None


def _resolve(host: str) -> set[str] | None:
    try:
        return {a[4][0] for a in socket.getaddrinfo(host, None)}
    except (OSError, UnicodeError):     # UnicodeError: a label idna can't encode (empty, or over 63 characters)
        return None


def _is_loopback(addrs: set[str]) -> bool:
    return any(ipaddress.ip_address(a.split("%")[0]).is_loopback for a in addrs)


def _local_addrs() -> set[str]:
    """This machine's addresses. Its name alone often resolves only to a loopback address; _candidate_ips, not
    local_ips: that drops IPv6, and a printer may point at the kit's IPv6 address."""
    out = {"127.0.0.1", "::1"}
    try:
        out |= {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None)}
    except (OSError, UnicodeError):
        pass
    return out | set(pairing._candidate_ips())


def compare_spoolman(server_url: str, kit_url: str, printer_host: str) -> str:
    """Is Moonraker's `[spoolman] server` the kit's `spoolman_url`? "same", "different" or "unknown". A loopback address
    means the machine that holds that setting: the printer on Moonraker's side, the kit on the kit's. So a printer
    pointing at its own loopback is the kit's Spoolman only if the printer is on the kit's machine, or the kit's URL
    names the printer. Only a setting that says loopback in so many words counts: a name that merely resolves to
    loopback HERE (stock Ubuntu's /etc/hosts gives the machine's own name 127.0.1.1) is this machine. Each name is looked
    up at most once per call, and this machine's own addresses found at most once."""
    server, kit = _host_port(server_url), _host_port(kit_url)
    if server is None or kit is None:
        return "unknown"
    if server[1] != kit[1]:
        return "different"
    seen: dict[str, set[str] | None] = {}
    local: set[str] | None = None

    def machine(host: str) -> set[str] | None:
        nonlocal local
        host = host.strip("[]")
        if host not in seen:
            seen[host] = _resolve(host)
        addrs = seen[host]
        if addrs and _is_loopback(addrs):
            if local is None:
                local = _local_addrs()
            return addrs | local
        return addrs

    if _names_loopback(server_url):
        theirs = machine(printer_host)
    else:
        theirs = machine(server[0])
        if theirs is None and server[0] == kit[0]:
            return "same"
    ours = machine(kit[0])
    if theirs is None or ours is None:
        return "unknown"
    return "same" if theirs & ours else "different"


def _names_loopback(url: str) -> bool:
    """Without a lookup: does this URL say, in so many words, the machine holding it?"""
    hp = _host_port(url)
    if hp is None:
        return False
    if hp[0] == "localhost" or hp[0].endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hp[0]).is_loopback
    except ValueError:
        return False


def spoolman_report(server_config: dict, kit_url: str | None, printer_host: str) -> dict:
    """{"server": host:port or None, never the URL (it may hold a password); "match": "same" | "different" | "unknown" |
    None (no [spoolman] server, or no kit URL to compare with); "warning": the line to show, or None}."""
    section = server_config.get("spoolman")
    server = section.get("server") if isinstance(section, dict) else None
    if not server:
        return {"server": None, "match": None,
                "warning": "Moonraker does not report usage to Spoolman (no [spoolman] section)" if kit_url else None}
    address = spoolman_address(server)
    if not kit_url:
        return {"server": address, "match": None, "warning": None}
    match = compare_spoolman(server, kit_url, printer_host)
    if address is None:     # a fixed sentence: the unreadable URL itself may hold a password
        warning = "Moonraker's [spoolman] server address cannot be read; usage may not reach this Spoolman"
    elif match == "same":
        warning = None
    elif match == "unknown":
        why = "a name does not resolve here" if _host_port(kit_url) else "this kit's spoolman_url cannot be read"
        warning = f"cannot tell whether Moonraker's Spoolman {address} is this kit's: {why}"
    elif _names_loopback(server):
        warning = f"usage goes to the printer's own {address}, not this kit's Spoolman"
    else:
        warning = f"usage goes to another Spoolman: {address}"
    return {"server": address, "match": match, "warning": warning}


def spoolman_warning(server_config: dict | None, kit_url: str | None, printer_host: str) -> str | None:
    if server_config is None:
        return None
    return spoolman_report(server_config, kit_url, printer_host)["warning"]


def spoolman_connected(client, previous: bool | None = None) -> bool | None:
    """Moonraker's own word on whether it reaches its Spoolman; None when it won't say (no [spoolman] section: 404, or
    an odd answer). A request that fails says nothing new, so `previous` stands: it must not clear a real warning."""
    try:
        v = client.spoolman_status().get("spoolman_connected")
    except NotFound:
        return None
    except MoonrakerError:
        return previous
    except AttributeError:
        return None
    return v if isinstance(v, bool) else None


def with_connection(warning: str | None, connected: bool | None) -> str | None:
    """A warning with Moonraker's connection added: only False says anything (None is "it won't say")."""
    if connected is not False:
        return warning
    lost = "Moonraker cannot reach its Spoolman: usage is not getting there"
    return f"{warning}; {lost}" if warning else lost
