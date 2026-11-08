"""The Klipper usage log: Moonraker's `[spoolman]` deducts filament live; the kit only records each job (spec §6).

`state/printers/<id>/usage.xml` holds `<entry>` elements (newest last, at most KEEP): id ("k-<job id>"), job,
file, started, ended (unix seconds), status (Moonraker's job status: completed, cancelled, error, klippy_shutdown
...), spool-id, filament-mm, grams (the file's `filament_weight_total` when the slicer wrote it) and
source="moonraker". Entries cannot be undone (Moonraker wrote Spoolman; the API answers 409 recorded_by_moonraker).
Nothing here ever writes to Spoolman or Moonraker.

`spoolman_warning(server_config, kit_url)` says when Moonraker reports usage somewhere else than the kit's Spoolman.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

from ... import config
from .. import xmlfile
from ..family import KLIPPER_ENTRY

log = logging.getLogger(__name__)
FILE = "usage.xml"
KEEP = 2000
_lock = threading.Lock()


def _file(pid: str):
    return config.paths().state / "printers" / pid / FILE


def owns(entry_id: str) -> bool:
    return isinstance(entry_id, str) and entry_id.startswith(KLIPPER_ENTRY)


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

def _host_port(url: str) -> tuple[str, int] | None:
    try:
        u = urllib.parse.urlsplit(url.strip())
        return (u.hostname or "").lower(), u.port or (443 if u.scheme == "https" else 80)
    except (AttributeError, ValueError):
        return None


def _addrs(host: str) -> set[str]:
    try:
        out = {a[4][0] for a in socket.getaddrinfo(host, None)}
    except OSError:
        return {host}
    if any(ipaddress.ip_address(a.split("%")[0]).is_loopback for a in out):
        out |= _local_addrs()
    return out


def _local_addrs() -> set[str]:
    out = {"127.0.0.1", "::1"}
    try:
        out |= {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None)}
    except OSError:
        pass
    return out


def same_spoolman(a: str, b: str) -> bool:
    ha, hb = _host_port(a), _host_port(b)
    if ha is None or hb is None or ha[1] != hb[1]:
        return False
    return ha[0] == hb[0] or bool(_addrs(ha[0]) & _addrs(hb[0]))


def spoolman_warning(server_config: dict | None, kit_url: str | None) -> str | None:
    if server_config is None or not kit_url:
        return None
    server = ((server_config or {}).get("spoolman") or {}).get("server")
    if not server:
        return "Moonraker does not report usage to Spoolman (no [spoolman] section)"
    if same_spoolman(server, kit_url):
        return None
    hp = _host_port(server)
    return f"usage goes to another Spoolman: {hp[0]}:{hp[1]}" if hp else f"usage goes to another Spoolman: {server}"
