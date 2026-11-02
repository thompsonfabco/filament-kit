"""The slot snapshot on disk: what the slot test / calibration job must put back, kept until the restore is confirmed.

`state/printers/<serial>/slottest-snapshot.json` (state-owned, written atomically) is saved BEFORE the first
write to the printer and deleted only after a confirmed restore. If it is still there, a job was cut short (the
process was killed, or its restore was not confirmed): the next mapping job (service or CLI) restores from it
first and refuses to go on unless that restore is confirmed; the service also restores from it at start when the
printer is connected and idle.

    {"kind": "slottest" | "calibration", "at": <unix s>,
     "slots": [{"label", "ams_id", "tray_id", "setting": {tray_info_idx, tray_color, tray_type, ...}}],
     "test_colours": ["FA0100FF", ...]}      # the colours the slot test may have written

Loading a spool into a slot drops that slot from the file (`forget`): the owner set it, so a later restore must not
undo the load."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable

from .. import config
from ..pairing import _write_atomic, make_state_dir
from . import registry, status
from .connection import PrinterOffline, UnknownPrinter

log = logging.getLogger(__name__)

FILE = "slottest-snapshot.json"
CONFIRM_TIMEOUT = 20.0
ONLINE = ('connected', 'needs_developer_mode')
TEST_PREFIXES = ("FA", "FB", "FC", "FD", "FE", "F9", "F8", "F7")
_TEST = re.compile(r"(FA|FB|FC|FD|FE|F9|F8|F7)([0-9A-F]{2})00FF")


def path(serial: str):
    if not isinstance(serial, str) or not registry.SERIAL.fullmatch(serial):
        raise ValueError(f"bad serial {serial!r}")
    return config.paths().state / "printers" / serial / FILE


def looks_like_test_colour(colour: str, n_slots: int) -> bool:
    """`colour` has the slot test's shape (`<prefix><nn>00FF`, nn = 1..n_slots): it may be a test colour an
    interrupted run left behind, so it is never taken as a slot's original colour."""
    m = _TEST.fullmatch((colour or "").upper())
    return m is not None and 1 <= int(m.group(2), 16) <= max(n_slots, 1)


def save(serial: str, kind: str, slots: list[dict], test_colours=()) -> None:
    """Write the snapshot (raises OSError: the caller must then not touch the printer)."""
    f = path(serial)
    make_state_dir(f.parent)
    data = {"kind": kind, "at": time.time(),
            "slots": [{"label": s["label"], "ams_id": int(s["ams_id"]), "tray_id": int(s["tray_id"]),
                       "setting": dict(s["setting"])} for s in slots],
            "test_colours": [str(c).upper() for c in test_colours]}
    _write_atomic(f, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)


def load(serial: str) -> dict | None:
    try:
        d = json.loads(path(serial).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # unreadable but present: still a pending restore, with nothing we can trust in it
        return {"kind": "unknown", "slots": [], "test_colours": [], "corrupt": True}
    if not isinstance(d, dict) or not isinstance(d.get("slots"), list):
        return {"kind": "unknown", "slots": [], "test_colours": [], "corrupt": True}
    slots = []
    for s in d["slots"]:
        if isinstance(s, dict) and isinstance(s.get("setting"), dict) and \
                status._int(s.get("ams_id")) is not None and status._int(s.get("tray_id")) is not None:
            slots.append({"label": str(s.get("label") or ""), "ams_id": int(s["ams_id"]),
                          "tray_id": int(s["tray_id"]), "setting": s["setting"]})
    tc = d.get("test_colours")
    return {"kind": str(d.get("kind") or ""), "slots": slots,
            "test_colours": [str(c).upper() for c in tc] if isinstance(tc, list) else []}


def pending(serial: str) -> bool:
    try:
        return path(serial).exists()
    except ValueError:
        return False


def pending_serials() -> list[str]:
    root = config.paths().state / "printers"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if registry.SERIAL.fullmatch(d.name) and (d / FILE).exists())


def clear(serial: str) -> None:
    try:
        path(serial).unlink()
    except FileNotFoundError:
        pass


def forget(serial: str, ams_id: int, tray_id: int) -> None:
    """Drop one slot from a pending snapshot (it was loaded since); the file goes when no slot is left."""
    snap = load(serial)
    if snap is None or snap.get("corrupt"):
        return
    keep = [s for s in snap["slots"] if (s["ams_id"], s["tray_id"]) != (int(ams_id), int(tray_id))]
    if len(keep) == len(snap["slots"]):
        return
    if keep:
        save(serial, snap["kind"], keep, snap["test_colours"])
    else:
        clear(serial)


# ---------------------------------------------------------------- restoring from the file

def trays(report: dict) -> dict[tuple[int, int], dict]:
    """(ams_id, tray_id) -> raw tray dict; the external holder as (its id, 0), as `ams.units` labels it."""
    out: dict[tuple[int, int], dict] = {}
    for u in status._l(status._d(status._d(report).get('ams')).get('ams')):
        uid = status._int(u.get('id'))
        if uid is None:
            continue
        for t in status._l(u.get('tray')):
            tid = status._int(t.get('id'))
            if tid is not None:
                out[(uid, tid)] = t
    vt = status._d(report).get('vt_tray')
    if isinstance(vt, dict):
        out[(status._int(vt.get('id'), 254), 0)] = vt
    return out


def _norm(colour) -> str:
    c = (colour if isinstance(colour, str) else '').upper()
    return '' if c in ('', '00000000') else c


def same(setting: dict, tray: dict | None) -> bool:
    """The tray shows that setting (preset, type, colour)."""
    t = tray or {}
    return (status._s(t.get('tray_info_idx')) == status._s(setting.get('tray_info_idx'))
            and status._s(t.get('tray_type')) == status._s(setting.get('tray_type'))
            and _norm(t.get('tray_color')) == _norm(setting.get('tray_color')))


def _failed(reply) -> bool:
    return isinstance(reply, dict) and str(reply.get('result', '')).lower() != 'success'


def restore(manager, serial: str, on_step: Callable[[str], None] | None = None,
            timeout: float = CONFIRM_TIMEOUT) -> list[str]:
    """Put back every slot of a pending snapshot that differs from it and confirm it from the report.
    Returns the problems; [] means confirmed (or nothing pending) and the file is gone. The caller makes sure the
    printer is idle and nothing else writes to it."""
    snap = load(serial)
    if snap is None:
        return []
    if snap.get("corrupt"):
        return [f"the saved slot snapshot ({FILE}) cannot be read; check every slot's filament on the printer, "
                f"then delete that file"]
    if manager.state(serial) not in ONLINE:
        return ["printer_offline: cannot restore the slots of an interrupted mapping"]
    report = manager.wait_report(serial, lambda r: True, 0)
    if report is None:
        return ["printer_offline: cannot restore the slots of an interrupted mapping"]
    if on_step is not None:
        on_step("Restoring the slots an interrupted mapping changed")
    problems: list[str] = []
    now = trays(report)
    pending_slots = []
    for s in snap["slots"]:
        key = (s["ams_id"], s["tray_id"])
        if same(s["setting"], now.get(key)):
            continue
        try:
            reply = manager.set_slot(serial, key[0], key[1], s["setting"])
        except (PrinterOffline, UnknownPrinter):
            problems.append(f"{s['label']}: not restored (printer_offline); it may still hold a test colour")
            continue
        if _failed(reply):
            problems.append(f"{s['label']}: restore refused ({reply.get('reason') or reply.get('result')}); "
                            f"it may still hold a test colour")
            continue
        pending_slots.append(s)
    if pending_slots:
        last: dict = {}

        def back(r: dict) -> bool:
            last['t'] = trays(r)
            return all(same(s["setting"], last['t'].get((s["ams_id"], s["tray_id"]))) for s in pending_slots)
        if manager.wait_report(serial, back, timeout) is None:
            seen = last.get('t', {})
            for s in pending_slots:
                if not same(s["setting"], seen.get((s["ams_id"], s["tray_id"]))):
                    problems.append(f"{s['label']}: restore not confirmed by the printer; it may still hold a "
                                    f"test colour")
    if not problems and snap["test_colours"]:
        final = manager.wait_report(serial, lambda r: True, 0)
        left = set(snap["test_colours"])
        for key, t in trays(final or {}).items():
            if _norm(t.get('tray_color')) in left:
                problems.append(f"AMS {key[0]} tray {key[1]}: test colour {t.get('tray_color')} still in the slot")
    if problems:
        log.warning("printer %s: restore from the saved slot snapshot not confirmed: %s", serial, problems)
        return problems
    clear(serial)
    log.info("printer %s: slots restored from the saved slot snapshot (%s)", serial, snap["kind"])
    return []
