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
import time
from typing import Callable

from .. import config
from ..pairing import _write_atomic, make_state_dir
from . import layout, registry, status
from .connection import PrinterOffline, UnknownPrinter

log = logging.getLogger(__name__)

FILE = "slottest-snapshot.json"
CONFIRM_TIMEOUT = 20.0
ONLINE = ('connected', 'needs_developer_mode')


def path(serial: str):
    if not isinstance(serial, str) or not registry.SERIAL.fullmatch(serial):
        raise ValueError(f"bad serial {serial!r}")
    return config.paths().state / "printers" / serial / FILE


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
    """(ams_id, tray_id) -> raw tray dict; each external holder as (its id, 0) (`layout.raw_trays`)."""
    return layout.raw_trays(report)


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
    """Put back the slots of a pending snapshot that still show one of its test colours, and confirm it from the
    report. Returns the problems; [] means confirmed (or nothing pending) and the file is gone. The caller makes
    sure the printer is idle and nothing else writes to it.

    The snapshot may be old (the process was killed, the restore runs at the next start), and the owner may have
    changed a slot since (another spool, RFID, Studio, the touchscreen): only what a mapping wrote is undone. The
    slot test writes only its test colours, so a slot is put back only while its colour is one of the snapshot's
    `test_colours`; every other slot is left as is (logged). The calibration writes no slot setting at all, so a
    calibration snapshot puts nothing back. That one rule covers a snapshot of any age (also one older than ten
    minutes). The final check that no test colour is left looks only at the snapshot's own slots: a spool loaded
    since (`forget`) whose real colour equals a test colour must not block mapping."""
    snap = load(serial)
    if snap is None:
        return []
    if snap.get("corrupt"):
        return [f"the saved slot snapshot cannot be read, so the slots an interrupted mapping changed are unknown. "
                f"Test colours look like near-pure red FAnn00FF (the first two digits F7 to FE): set the filament "
                f"of any slot showing such a colour again, on the printer or in Bambu Studio, then delete "
                f"{path(serial)} and map again"]
    if manager.state(serial) not in ONLINE:
        return ["The printer is offline, so the slots an interrupted mapping changed cannot be put back yet."]
    report = manager.wait_report(serial, lambda r: True, 0)
    if report is None:
        return ["The printer is offline, so the slots an interrupted mapping changed cannot be put back yet."]
    if on_step is not None:
        on_step("Restoring the slots an interrupted mapping changed")
    problems: list[str] = []
    now = trays(report)
    printer = registry.load().get(serial)
    kinds = layout.kinds(report, printer.model if printer is not None else None)   # "ext": the model's addressing
    pending_slots = []
    tests = set(snap["test_colours"])
    for s in snap["slots"]:
        key = (s["ams_id"], s["tray_id"])
        if same(s["setting"], now.get(key)):
            continue
        if _norm((now.get(key) or {}).get('tray_color')) not in tests:
            log.info("%s: slot %s changed since the %s snapshot, left as is", registry.log_label(serial), s["label"],
                     snap["kind"])
            continue
        try:
            reply = manager.set_slot(serial, key[0], key[1], s["setting"], kind=kinds.get(key[0]))
        except (PrinterOffline, UnknownPrinter):
            problems.append(f"{s['label']}: not restored (the printer went offline); it may still hold a test colour")
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
        final = trays(manager.wait_report(serial, lambda r: True, 0) or {})
        for s in snap["slots"]:              # only the snapshot's own slots (a forgotten slot was loaded since)
            t = final.get((s["ams_id"], s["tray_id"])) or {}
            if _norm(t.get('tray_color')) in tests:
                problems.append(f"{s['label']}: test colour {t.get('tray_color')} still in the slot")
    if problems:
        log.warning("%s: restore from the saved slot snapshot not confirmed: %s", registry.log_label(serial), problems)
        return problems
    clear(serial)
    log.info("%s: slots restored from the saved slot snapshot (%s)", registry.log_label(serial), snap["kind"])
    return []
