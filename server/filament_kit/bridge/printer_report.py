"""The printer report: what a maintainer needs to add a printer or an AMS the kit doesn't know yet, as one XML file its owner
can attach to an issue. The kit never sends it anywhere.

It is built from an allow-list: nothing is copied from the printer's report unless it is named here, because a deny-list
would miss the next field Bambu adds. Never in it: the serial, Access Code, account id, addresses, the printer's name, Wi-Fi
fields, a spool's RFID identity (`tag_uid`, `tray_uuid`), `tray_info_idx` (it can be the owner's own preset), colours, file
and job names, HMS text, and any free text from a failure. Every value goes through a shape check, so a field that one day
holds something of another shape is left out, not copied. The shapes refuse what looks like an address, a host name or a serial;
a value that fits (a short word as a filament type, a number) would still pass, which is why the owner is told to read the file.
Field NAMES of the report are listed, to find what the kit doesn't read, but only names of a plain shape and with few digits.

Made at the end of a mapping that wasn't clean (kept on the server, the last KEEP) or on request.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import __version__, config
from ..pairing import _write_atomic, make_state_dir
from . import hardware, layout, status

FORMAT = "1"
KEEP = 5
NAME = re.compile(r"(?![A-Z0-9]{12})[A-Za-z0-9_+/-]{1,32}")     # a module code, filament type: no dot, not serial-like
VERSION = re.compile(r"\d{2}(?:\.\d{2})+")              # a firmware version, as in 01.02.03.04: two digits each
MODEL = re.compile(r"[A-Z0-9]{1,11}(?:-[A-Z0-9]{1,11})?")   # a model code, as in N6 or BL-P001: never someone's name for it
KEY = re.compile(r"[a-z0-9_]{1,40}")                   # a report field's name
KEY_DIGITS = 6                                         # a real field's name has few; a serial or an id in lower case has many
HEX_OR_INT = re.compile(r"[0-9A-Fa-f]{1,16}")          # presence bits: 16 hex digits for 16 units
INFO = re.compile(r"[0-9A-Fa-f]{1,8}")                 # a unit's `info`, 32 bits
PLAIN = re.compile(r"[A-Za-z0-9._+/-]{1,32}")          # the kit's own word for a unit
ERROR = re.compile(r"0x[0-9A-F]{1,16}")
SCHEME = re.compile(r"[a-z0-9_-]{1,20}")
_FINALS = {"FINISH", "FAILED", "IDLE"}
_JOB_FILES = {"minimal", "project"}
WANTED = ("unknown_model", "unknown_ams", "no_scheme", "job_refused", "job_failed", "no_mapping")
LOUD = ("no_scheme", "job_refused", "job_failed", "no_mapping")     # the others can come with a map that works
_WHY = {"unknown_model": "The kit doesn't know this printer model yet. A report helps add it.",
        "unknown_ams": "The kit doesn't know one of this printer's AMS units yet. A report helps add it.",
        "no_scheme": "The kit couldn't work out how this printer numbers its slots. A report helps fix that.",
        "job_refused": "The printer refused the mapping job. A report helps find out why.",
        "job_failed": "The mapping job failed on the printer. A report helps find out why.",
        "no_mapping": "The printer didn't say how it mapped the slots. A report helps find out why."}


def why(wanted) -> str | None:
    """The sentence for a `report_wanted`, in one place for every client."""
    return _WHY.get(wanted)


def _plain(v, shape=PLAIN) -> str | None:
    s = str(v).strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
    return s if s and shape.fullmatch(s) else None


def _set(el: ET.Element, key: str, value, shape=PLAIN) -> None:
    v = _plain(value, shape)
    if v is not None:
        el.set(key, v)


def _ints(values) -> str:
    out = []
    for v in values if isinstance(values, (list, tuple)) else []:
        n = status._int(v)
        if n is not None and -1 <= n < 2 ** 32:
            out.append(str(n))
    return " ".join(out)


def _firmware(root: ET.Element, report: dict) -> None:
    for m in report.get(layout.FIRMWARE) or []:
        if isinstance(m, dict) and _plain(m.get("name"), NAME) and _plain(m.get("version"), VERSION):
            el = ET.SubElement(root, "firmware")
            _set(el, "module", m.get("name"), NAME)
            _set(el, "version", m.get("version"), VERSION)


def _layout(root: ET.Element, report: dict, model) -> None:
    lay = layout.build(report, model)
    el = ET.SubElement(root, "layout", presence=lay.presence if lay.presence in ("bits", "tray_type") else "")
    raw = {status._int(u.get("id")): u for u in ((report.get("ams") or {}).get("ams") or []) if isinstance(u, dict)}
    for u in lay.units:
        kind = _plain(u.kind)
        unit = ET.SubElement(el, "unit", id=str(int(u.ams_id)), kind=kind or "", known=str(bool(u.known)).lower(),
                             slots=str(len(u.slots)))
        _set(unit, "module", u.module, NAME)
        _set(unit, "info", (raw.get(u.ams_id) or {}).get("info"), INFO)
        for s in u.slots:
            slot = ET.SubElement(unit, "slot", tray=str(int(s.tray_id)))
            if s.present is not None:
                slot.set("present", str(bool(s.present)).lower())
            t = (s.raw or {}).get("tray_type") if isinstance(s.raw, dict) else None
            _set(slot, "type", t, NAME)


def _presence(root: ET.Element, report: dict) -> None:
    a = report.get("ams") if isinstance(report.get("ams"), dict) else {}
    el = ET.SubElement(root, "presence")
    for key, name in (("tray_exist_bits", "tray-exist-bits"), ("tray_read_done_bits", "tray-read-done-bits"),
                      ("ams_exist_bits", "ams-exist-bits")):
        _set(el, name, a.get(key), HEX_OR_INT)


def _nozzles(root: ET.Element, report: dict) -> None:
    info = ((report.get("device") or {}).get("nozzle") or {}).get("info") if isinstance(report.get("device"), dict) else None
    for n in info if isinstance(info, list) else []:
        if isinstance(n, dict):
            i, d = status._int(n.get("id")), n.get("diameter")
            if i is not None and isinstance(d, (int, float)) and not isinstance(d, bool) and 0 < d < 3:
                ET.SubElement(root, "nozzle", id=str(i), diameter=str(d))
    _set(root, "nozzle-diameter", report.get("nozzle_diameter"), re.compile(r"[0-9.]{1,5}"))


def _keys(root: ET.Element, report: dict) -> None:
    a = report.get("ams") if isinstance(report.get("ams"), dict) else {}
    for tag, src in (("report-keys", report), ("ams-keys", a)):
        names = sorted(k for k in src if isinstance(k, str) and KEY.fullmatch(k) and sum(c.isdigit() for c in k) < KEY_DIGITS)
        ET.SubElement(root, tag).text = " ".join(names)


def _attempts(root: ET.Element, trail) -> None:
    for t in trail if isinstance(trail, list) else []:
        if not isinstance(t, dict):
            continue
        el = ET.SubElement(root, "attempt")
        _set(el, "scheme", t.get("scheme"), SCHEME)
        if t.get("job_file") in _JOB_FILES:
            el.set("job-file", t["job_file"])
        if t.get("final") in _FINALS:
            el.set("final", t["final"])
        _set(el, "print-error", t.get("print_error"), ERROR)
        if t.get("repeats_last_print") is True:
            el.set("repeats-last-print", "true")     # does a real printer's full report bring the old mapping back?
        ET.SubElement(el, "sent").text = _ints(t.get("sent"))
        ET.SubElement(el, "reported").text = _ints(t.get("reported"))
        ET.SubElement(el, "fits").text = " ".join(x for x in (_plain(f, SCHEME) for f in t.get("fits") or []) if x)


def build(report: dict | None, model, *, trail=None, wanted: str | None = None, when: float | None = None) -> bytes:
    """The report, as XML. Never raises for a strange field: it is left out."""
    report = report if isinstance(report, dict) else {}
    hw = hardware.load()
    mi = hw.model(model)
    root = ET.Element("printer-report", version=FORMAT, kit=__version__,
                      when=time.strftime("%Y-%m-%d", time.gmtime(time.time() if when is None else when)))
    if wanted in WANTED:
        root.set("wanted", wanted)
    printer = ET.SubElement(root, "printer", known=str(bool(mi.known)).lower(), family="bambu")
    _set(printer, "model-code", model, MODEL)
    sections = (lambda: _firmware(root, report), lambda: _layout(root, report, model), lambda: _presence(root, report),
                lambda: _nozzles(root, report), lambda: _keys(root, report), lambda: _attempts(root, trail))
    for section in sections:
        try:
            section()
        except Exception as e:  # noqa: BLE001 - one bad field never stops the report; the name of the error only
            ET.SubElement(root, "section-failed", error=type(e).__name__)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _folder(serial: str) -> Path:
    return config.paths().state / "printers" / serial


def file_name(model, when: float | None = None) -> str:
    """No serial, so the name is safe to attach too."""
    code = _plain(model, MODEL) or "unknown"
    return f"printer-report-{code}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(time.time() if when is None else when))}.xml"


def save(serial: str, data: bytes, model) -> Path:
    """Keep it beside the printer's other files, the last KEEP. It can run as root (`sudo filament-kit printer report`) in the
    service user's folder: never through a name planted there, and what it makes stays the service user's."""
    d = _folder(serial)
    make_state_dir(d)
    path = d / file_name(model)
    _write_atomic(path, data, 0o644, state_owned=True)
    for old in sorted(d.glob("printer-report-*.xml"), key=lambda p: p.name)[:-KEEP]:
        old.unlink(missing_ok=True)
    return path
