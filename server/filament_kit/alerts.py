"""Alert rules and thresholds (R80 section 3), the Hub's disk measurement (section 6) and the running-low list (section 7).

`alerts.xml` lives in the Hub's STATE folder (R80 ruling of 01:12), written with the state folder's owner and mode
and never through a symbolic link (the same atomic write as the event store). It holds the eight alert switches, the
running-low threshold, the "only when it is the last spool" switch and the two storage limits; no per-device entries
(R80 E4: a device keeps its own switch). A start never fails because of it: a file that cannot be read gives the
defaults, one that cannot be written keeps the new values in memory; `problem()` says which, for the Checks row.

Every event is written whatever the switches say; `is_alert` tells whether an alert type that is on covers an event.
No texts are built here (EA3): functions return kinds, keys and numbers.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config, events

log = logging.getLogger("filament_kit.alerts")

FILE = "alerts.xml"
VERSION = "1"
# (key, the event kinds the type covers, on at the start): the keys are fixed (R80 ruling of 00:25)
TYPES = (("runout", ("print.runout",), True),
         ("paused", ("print.paused",), True),
         ("failed", ("print.failed",), True),
         ("printer_error", ("printer.error",), True),
         ("finished", ("print.finished",), False),
         ("storage", ("storage.low",), True),
         ("running_low", ("spool.low",), True),
         ("device_down", ("device.down", "printer.offline"), False))
KEYS = tuple(t[0] for t in TYPES)
LOW_G_MIN, LOW_G_MAX, LOW_G = 10, 2000, 150
WARN_PERCENT, BAD_PERCENT = 85, 95
GB = 1000 ** 3
FREE_BAD_BYTES = GB                      # always bad under 1 GB free, whatever the percentages say


class AlertsError(ValueError):
    """A value that is not allowed (the message says which and what is allowed)."""


def defaults() -> dict:
    return {"types": {k: on for k, _kinds, on in TYPES}, "last_spool_only": False, "running_low_g": LOW_G,
            "storage_warn_percent": WARN_PERCENT, "storage_bad_percent": BAD_PERCENT}


def _number(v, name: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not lo <= v <= hi:
        raise AlertsError(f"{name} must be a whole number from {lo} to {hi}.")
    return int(v)


def check(values: dict) -> dict:
    """The settings `values` (the shape of `defaults()`) as stored, or AlertsError."""
    if not isinstance(values, dict):
        raise AlertsError("The alert settings must be a set of named values.")
    out = defaults()
    types = values.get("types", out["types"])
    if not isinstance(types, dict) or set(types) - set(KEYS):
        raise AlertsError(f"Alert types are: {', '.join(KEYS)}.")
    for k, v in types.items():
        if not isinstance(v, bool):
            raise AlertsError(f"The alert type {k} is on or off.")
        out["types"][k] = v
    if "last_spool_only" in values:
        if not isinstance(values["last_spool_only"], bool):
            raise AlertsError("last_spool_only is on or off.")
        out["last_spool_only"] = values["last_spool_only"]
    if "running_low_g" in values:
        out["running_low_g"] = _number(values["running_low_g"], "running_low_g", LOW_G_MIN, LOW_G_MAX)
    if "storage_warn_percent" in values:
        out["storage_warn_percent"] = _number(values["storage_warn_percent"], "storage_warn_percent", 1, 99)
    if "storage_bad_percent" in values:
        out["storage_bad_percent"] = _number(values["storage_bad_percent"], "storage_bad_percent", 2, 100)
    if out["storage_warn_percent"] >= out["storage_bad_percent"]:
        raise AlertsError("The storage warning must be lower than the storage limit that makes it bad.")
    return out


def to_xml(values: dict) -> bytes:
    root = ET.Element("alerts", version=VERSION)
    for k in KEYS:
        ET.SubElement(root, "type", key=k, on="yes" if values["types"][k] else "no")
    ET.SubElement(root, "running-low", grams=str(values["running_low_g"]),
                  **{"last-spool-only": "yes" if values["last_spool_only"] else "no"})
    ET.SubElement(root, "storage", warn=str(values["storage_warn_percent"]), bad=str(values["storage_bad_percent"]))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def from_xml(raw: bytes) -> dict:
    """The settings in `raw`; a value that is missing keeps its default. Raises AlertsError for XML that is broken or
    holds a value that is not allowed."""
    from defusedxml.ElementTree import ParseError, fromstring
    try:
        root = fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError, ValueError) as e:
        raise AlertsError(f"it is not valid XML ({e})") from None
    if root.tag != "alerts":
        raise AlertsError("it is not an alerts file")
    out = defaults()
    try:
        for el in root.findall("type"):
            k = el.get("key")
            if k in KEYS:                        # a key a later version added is skipped, not an error
                if el.get("on") not in ("yes", "no"):
                    raise AlertsError(f"the alert type {k} must be yes or no")
                out["types"][k] = el.get("on") == "yes"
        low, st = root.find("running-low"), root.find("storage")
        if low is not None:
            if low.get("last-spool-only") is not None:
                out["last_spool_only"] = low.get("last-spool-only") == "yes"
            if low.get("grams") is not None:
                out["running_low_g"] = int(low.get("grams"))
        if st is not None:
            if st.get("warn") is not None:
                out["storage_warn_percent"] = int(st.get("warn"))
            if st.get("bad") is not None:
                out["storage_bad_percent"] = int(st.get("bad"))
    except ValueError as e:
        raise AlertsError(f"a value is not a number ({e})") from None
    return check(out)


# ---------------------------------------------------------------- the file

_lock = threading.Lock()
_state: dict = {"values": None, "stamp": None, "problem": None}     # what is in force; the stat of the file read


def _path() -> Path:
    return config.paths().state / FILE


def _stamp(f: Path):
    try:
        st = os.stat(f)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _reason(e: BaseException) -> str:
    return getattr(e, "strerror", None) or str(e) or e.__class__.__name__


def load() -> dict:
    """The settings in force: the file's when there is a good one, else the last good ones, else the defaults.
    The file is read again only when it changed (the command line edits it in another process). Settings that could
    not be written stay in force from memory."""
    f = _path()
    with _lock:
        stamp = _stamp(f)
        if _state["problem"] == "unwritten" and _state["values"] is not None:
            return _copy(_state["values"])
        if _state["values"] is not None and stamp == _state["stamp"]:
            return _copy(_state["values"])
        if stamp is None:
            _state.update(values=defaults(), stamp=None, problem=None)
            return _copy(_state["values"])
        try:
            values = from_xml(events._read_bytes(f))
        except (AlertsError, events.EventError, OSError) as e:
            if _state["problem"] != f"unreadable: {_reason(e)}":
                log.error("alerts.xml cannot be used (%s); the defaults apply until it is fixed", _reason(e))
            _state.update(values=_state["values"] or defaults(), stamp=stamp, problem=f"unreadable: {_reason(e)}")
            return _copy(_state["values"])
        _state.update(values=values, stamp=stamp, problem=None)
        return _copy(values)


def _copy(v: dict) -> dict:
    return {**v, "types": dict(v["types"])}


def save(changes: dict) -> dict:
    """Change settings: `changes` holds any of the keys of `defaults()` (`types` may hold only the types to change).
    The whole set is checked first (AlertsError), then written. A write that fails is logged once and the new values
    stay in force in memory (the next change and the next start try again); `problem()` says so. Returns the settings."""
    cur = load()
    merged = {**cur, **{k: v for k, v in (changes or {}).items() if k != "types"}}
    merged["types"] = {**cur["types"], **((changes or {}).get("types") or {})}
    new = check(merged)
    f = _path()
    with _lock:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            events.EventStore()._atomic(f, to_xml(new))
        except (OSError, events.EventError) as e:
            if _state["problem"] != "unwritten" or _state.get("why") != _reason(e):
                log.error("alerts.xml cannot be written (%s); the settings stay in memory", _reason(e))
            _state.update(values=new, stamp=_stamp(f), problem="unwritten")
            _state["why"] = _reason(e)
        else:
            _state.update(values=new, stamp=_stamp(f), problem=None)
    return _copy(new)


def problem() -> tuple[str, str] | None:
    """(`unreadable` or `unsaved`, the reason) while alerts.xml cannot be read or cannot be written, else None: the
    Checks row "Alerts settings could not be saved ({reason})." is built from it (EA3)."""
    load()
    with _lock:
        p = _state["problem"]
        if p == "unwritten":
            return "unsaved", _state.get("why", "")
        if p and p.startswith("unreadable: "):
            return "unreadable", p[len("unreadable: "):]
    return None


def reset() -> None:
    """Forget what is in force (tests; a changed state folder)."""
    with _lock:
        _state.update(values=None, stamp=None, problem=None)


# ---------------------------------------------------------------- what is an alert

def type_of(kind: str) -> str | None:
    """The alert type key that covers an event kind, None for a kind no alert type covers."""
    for k, kinds, _on in TYPES:
        if kind in kinds:
            return k
    return None


def is_alert(event: dict, settings: dict | None = None) -> bool:
    """Whether an alert type that is switched on covers `event` (a dict as the store returns it). A `storage.low`
    with direction `down` (the disk fell from bad to warn) is never an alert (R80 E2); `spool.low` is an alert only
    for the last spool of its filament when "only when last spool" is on."""
    s = settings or load()
    key = type_of(event.get("kind", ""))
    if key is None or not s["types"].get(key):
        return False
    data = event.get("data") or {}
    if event["kind"] == "storage.low" and data.get("direction") == "down":
        return False
    if event["kind"] == "spool.low" and s["last_spool_only"] and str(data.get("in_stock", "0")) not in ("0", ""):
        return False
    return True
