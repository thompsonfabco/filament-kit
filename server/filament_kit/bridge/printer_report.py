"""The printer report: what a maintainer needs to add a printer or an AMS the kit doesn't know yet, as one XML file its owner
can attach to an issue. The kit never sends it anywhere.

It is built from an allow-list: nothing is copied from the printer's report unless it is named here, because a deny-list
would miss the next field Bambu adds. Never in it: the serial, Access Code, account id, addresses, the printer's name, Wi-Fi
fields, a spool's RFID identity (`tag_uid`, `tray_uuid`), `tray_info_idx` (it can be the owner's own preset), colours, file
and job names, HMS text, and any free text from a failure. Every value goes through a shape check, so a field that one day
holds something of another shape is left out, not copied. The shapes refuse what looks like an address, a host name or a serial;
a value that fits (a short word as a filament type, a number) would still pass, which is why the owner is told to read the file.
Field NAMES of the report are listed, to find what the kit doesn't read, but only names of a plain shape and with few digits.

Made at the end of a mapping that wasn't clean (kept on the server, the last KEEP) or on request. When the printer cannot be
reached it is built from what the kit saved instead (`live="false"`, `saved-until` = the newest saved record): the layout the
slot map was made for, the map itself, the last mapping's state, reason and attempts. The kit keeps no copy of the printer's
own report, so the live sections (firmware, presence, nozzles, field names) are then absent.
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
FAIL_REASON = re.compile(r"[A-Za-z0-9_-]{1,40}")       # a code or a word: no dot or colon (never an address)
SCHEME = re.compile(r"[a-z0-9_-]{1,20}")
_FINALS = {"FINISH", "FAILED", "IDLE"}
_JOB_FILES = {"minimal", "project"}
WANTED = ("unknown_model", "unknown_ams", "no_scheme", "job_refused", "job_failed", "no_mapping")
LOUD = ("no_scheme", "job_refused", "job_failed", "no_mapping")     # the others can come with a map that works
_WHY = {"unknown_model": "The kit doesn't know this printer model yet. A report helps add it.",
        "unknown_ams": "The kit doesn't know one of this printer's AMS units yet. A report helps add it.",
        "no_scheme": "The kit couldn't work out how this printer numbers its slots. A report helps fix that.",
        "job_refused": "The printer refused the mapping job. A report helps find out why.",
        "job_failed": "The mapping job failed on the printer. What its screen said, and a report, help find out why.",
        "no_mapping": "The printer didn't say how it mapped the slots. A report helps find out why."}


def why(wanted) -> str | None:
    """The sentence for a `report_wanted`, in one place for every client."""
    return _WHY.get(wanted)


# A serial's shape (letters and digits, 12 or more, both kinds): never in the file, whatever field it turns up in.
SERIALISH = re.compile(r"(?=[0-9A-Za-z]*[0-9])(?=[0-9A-Za-z]*[A-Za-z])[0-9A-Za-z]{12,}")


def _plain(v, shape=PLAIN) -> str | None:
    s = str(v).strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
    # hex shapes (presence bits, a unit's info) keep long values: a-f and digits can't spell a serial's other letters
    return s if s and shape.fullmatch(s) and (shape in (HEX_OR_INT, INFO) or not SERIALISH.search(s)) else None


def _kinds(hw) -> set[str]:
    """The kit's own unit kinds: the AMS type keys of the hardware file, plus external holders and unknown units."""
    return {t.key for t in hw.ams_types} | {layout.EXT_KIND, "generic"}


def _label_shape(hw) -> re.Pattern:
    """The kit's own slot labels: a unit prefix ("", "HT-" or a type's), 1-3 letters and a slot number (A1, AA4,
    HT-A), or an external holder's label (Ext, Ext-L, Ext-R, or Ext-<id> for one the model doesn't know)."""
    prefixes = sorted({"", "HT-"} | {t.label_prefix for t in hw.ams_types if t.label_prefix}, key=len, reverse=True)
    ext = sorted({x.label for m in hw.models for x in m.externals} | set(layout.EXT_DEFAULT.values()) | {"Ext"},
                 key=len, reverse=True)
    units = "|".join(re.escape(p) for p in prefixes)
    return re.compile(rf"(?:(?:{units})[A-Z]{{1,3}}[1-9]?|{'|'.join(re.escape(e) for e in ext)}|Ext-\d{{1,3}})")


def _kind(value, hw) -> str | None:
    k = _plain(value)
    return k if k in _kinds(hw) else None


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


def _model_code(model) -> str | None:
    """The hardware file's own code for a model it knows, whatever name the printer reported, since that can't be anyone's own;
    otherwise what was reported, if it has a code's shape."""
    mi = hardware.load().model(model)
    return _plain(mi.code if mi.known else model, MODEL)


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
    hw = hardware.load()
    for u in lay.units:
        kind = _kind(u.kind, hw)
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
        _set(el, "mc-error", t.get("mc_error"), ERROR)
        _set(el, "fail-reason", t.get("fail_reason"), FAIL_REASON)
        if t.get("repeats_last_print") is True:
            el.set("repeats-last-print", "true")     # does a real printer's full report bring the old mapping back?
        ET.SubElement(el, "sent").text = _ints(t.get("sent"))
        ET.SubElement(el, "reported").text = _ints(t.get("reported"))
        ET.SubElement(el, "fits").text = " ".join(x for x in (_plain(f, SCHEME) for f in t.get("fits") or []) if x)


def _hw_file_version() -> str | None:
    """The hardware data file in use: the newer of the bundled one and the updater's override, as major.minor."""
    best = None
    for path in (hardware.BUNDLED, hardware.override_path()):
        try:
            v = hardware.file_version(Path(path).read_bytes())
        except (OSError, ValueError, TypeError):
            v = None
        if v and (best is None or tuple(v) > tuple(best)):
            best = v
    return f"{best[0]}.{best[1]}" if best else None


def _saved(root: ET.Element, saved: dict) -> None:
    """What the kit saved about the printer (no live report): its layout fingerprint, the slot map, the last mapping."""
    el = ET.SubElement(root, "saved")
    hw = hardware.load()
    labels = _label_shape(hw)
    for item in (saved.get("fingerprint") or [])[:64]:
        try:
            uid, kind, n = item
            unit = ET.SubElement(el, "unit", id=str(int(uid)), slots=str(int(n)))
        except (TypeError, ValueError):
            continue
        kind = _kind(kind, hw)          # the same rule as the live report: the kit's own kinds only
        if kind is not None:
            unit.set("kind", kind)
    m = ET.SubElement(el, "map", calibrated=str(bool(saved.get("calibrated"))).lower(),
                      slots=str(len(saved.get("slots") or {})))
    _set(m, "scheme", saved.get("scheme"), SCHEME)
    for label, s in list((saved.get("slots") or {}).items())[:128]:
        if not isinstance(s, dict) or _plain(label) is None or not labels.fullmatch(str(label)):
            continue                    # only the kit's own labels: never a serial, a host or a name
        slot = ET.SubElement(m, "slot", label=str(label))
        for k in ("ams_id", "tray_id", "global_id"):
            if isinstance(s.get(k), int) and not isinstance(s.get(k), bool):
                slot.set(k.replace("_", "-"), str(s[k]))
    last = ET.SubElement(el, "last-mapping")
    _set(last, "state", saved.get("state"), SCHEME)
    _set(last, "reason", saved.get("reason"), SCHEME)


def build(report: dict | None, model, *, trail=None, wanted: str | None = None, when: float | None = None,
          saved: dict | None = None, saved_until: float | None = None) -> bytes:
    """The report, as XML. Never raises for a strange field: it is left out. `saved` (the printer could not be reached):
    the kit's saved records (_saved) in place of a live report, `saved_until` the time of the newest of them."""
    report = report if isinstance(report, dict) else {}
    hw = hardware.load()
    mi = hw.model(model)
    root = ET.Element("printer-report", version=FORMAT, kit=__version__,
                      when=time.strftime("%Y-%m-%d", time.gmtime(time.time() if when is None else when)),
                      live="false" if saved is not None else "true")
    if saved is not None and isinstance(saved_until, (int, float)):
        root.set("saved-until", time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(saved_until)))
    if wanted in WANTED:
        root.set("wanted", wanted)
    hv = _hw_file_version()
    if hv:
        root.set("hardware-file", hv)
    printer = ET.SubElement(root, "printer", known=str(bool(mi.known)).lower(), family="bambu")
    _set(printer, "model-code", _model_code(model), MODEL)
    live = (lambda: _firmware(root, report), lambda: _layout(root, report, model), lambda: _presence(root, report),
            lambda: _nozzles(root, report), lambda: _keys(root, report))
    sections = (*(live if saved is None else (lambda: _saved(root, saved),)), lambda: _attempts(root, trail))
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
    code = _model_code(model) or "unknown"
    return f"printer-report-{code}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(time.time() if when is None else when))}.xml"


FILE = re.compile(r"printer-report-[A-Za-z0-9-]{1,40}-\d{8}-\d{6}\.xml")
NEVER = ("It never holds the printer's serial, Access Code, account, addresses, name, Wi-Fi, spool tag identities, "
         "colours, file or job names, or error text; read it before you share it.")


def saved(serial: str) -> list[dict]:
    """The reports kept for this printer, newest first: [{name, size, at}] (`at` = epoch seconds)."""
    out = []
    try:
        entries = list(_folder(serial).iterdir())
    except OSError:
        return out
    for p in entries:
        if not FILE.fullmatch(p.name) or p.is_symlink():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({"name": p.name, "size": st.st_size, "at": st.st_mtime})
    return sorted(out, key=lambda r: r["name"], reverse=True)


def read_saved(serial: str, name: str) -> bytes:
    """One kept report's bytes: only a report file's name, never through a link, at most 1 MiB. FileNotFoundError else."""
    import os
    if not FILE.fullmatch(name or ""):
        raise FileNotFoundError(name)
    fd = os.open(_folder(serial) / name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as fh:
        data = fh.read(2**20 + 1)
    if len(data) > 2**20:
        raise FileNotFoundError(name)
    return data


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
