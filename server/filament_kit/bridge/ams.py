"""AMS model (units and slots read from a report) and the per-printer slot map store.

Labels come from `status` (A1-D4, HT-A...), so the app, the status join and the slot map agree. The slot map
ties each label to the printer's own global slot id once calibrated; until then `default_global` is the guess."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .. import config
from ..pairing import _write_atomic
from .status import HT_BASE, _d, _int, _l, _s, slot_label, unit_label

FILE = "slotmap.json"
EXT = "Ext"
EXT_ID = 254   # the external spool holder; a second nozzle's holder reports 255


@dataclass
class Slot:
    tray_id: int
    label: str
    global_id: int | None
    type: str = ""
    color: str = ""
    preset: str = ""


@dataclass
class Unit:
    ams_id: int
    kind: str          # "ams" | "ams_ht" | "ams_lite"
    label: str
    slots: list[Slot] = field(default_factory=list)


@dataclass
class SlotMap:
    slots: dict[str, dict] = field(default_factory=dict)   # label -> {ams_id, tray_id, global_id}
    calibrated: bool = False
    observe: bool = True
    updated: float | None = None


def default_global(ams_id: int, tray_id: int) -> int:
    """Part 1's best guess of the printer's global slot id: ams_id*4+tray (4-slot units), ams_id (HT)."""
    return ams_id if ams_id >= HT_BASE else ams_id * 4 + tray_id


def _slot(label: str, ams_id: int, tray_id: int, gid: int | None, t: dict) -> Slot:
    return Slot(tray_id=tray_id, label=label, global_id=gid, type=_s(t.get('tray_type')),
                color=_s(t.get('tray_color')), preset=_s(t.get('tray_info_idx')))


def units(report: dict) -> list[Unit]:
    """AMS units (ordered by ams_id) plus the external spool holder (`vt_tray`) from a merged report."""
    p = _d(report)
    out: list[Unit] = []
    for u in _l(_d(p.get('ams')).get('ams')):
        uid = _int(u.get('id'))
        if uid is None or uid < 0:
            continue
        label, kind = unit_label(uid)
        slots = []
        for t in _l(u.get('tray')):
            tid = _int(t.get('id'))
            if tid is None or tid < 0:
                continue
            slots.append(_slot(slot_label(uid, tid), uid, tid, default_global(uid, tid), t))
        slots.sort(key=lambda s: s.tray_id)
        out.append(Unit(uid, kind, label, slots))
    out.sort(key=lambda u: u.ams_id)
    vt = p.get('vt_tray')
    if isinstance(vt, dict):
        gid = _int(vt.get('id'), EXT_ID)
        out.append(Unit(gid if gid is not None else EXT_ID, 'ams', EXT,
                        [_slot(EXT, gid, 0, gid, vt)]))
    return out


def _file(serial: str):
    return config.paths().state / "printers" / serial / FILE


def load_map(serial: str) -> SlotMap:
    f = _file(serial)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SlotMap()
    if not isinstance(d, dict):
        return SlotMap()
    slots = d.get('slots')
    return SlotMap(slots=slots if isinstance(slots, dict) else {}, calibrated=bool(d.get('calibrated')),
                   observe=bool(d.get('observe', True)), updated=d.get('updated'))


def save_map(serial: str, m: SlotMap) -> None:
    f = _file(serial)
    f.parent.mkdir(parents=True, exist_ok=True)
    m.updated = time.time()
    data = {'slots': m.slots, 'calibrated': m.calibrated, 'observe': m.observe, 'updated': m.updated}
    _write_atomic(f, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)
