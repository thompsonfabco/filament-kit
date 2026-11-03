"""AMS model (units and slots read from a report) and the per-printer slot map store.

Units and labels come from `layout.build` (A1 ... Z4, AA1 ..., HT-A ..., Ext / Ext-L / Ext-R), the builder
`status` uses too, so the app, the status join and the slot map agree. The slot map ties each label to the
printer's own global slot id once calibrated; until then `default_global` is the guess. It also keeps the layout
fingerprint the map was made for (`fingerprint`) and `stale` (the printer's layout changed since)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .. import config
from ..pairing import _write_atomic, make_state_dir
from . import hardware, layout, registry
from .status import EXT, EXT_ID, HT_BASE, _s  # noqa: F401 - EXT/EXT_ID re-exported

FILE = "slotmap.json"


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
    kind: str          # ams-type key ("ams", "ams_2pro", "ams_ht", "ams_lite", "generic") or "ext"
    label: str
    slots: list[Slot] = field(default_factory=list)


@dataclass
class SlotMap:
    slots: dict[str, dict] = field(default_factory=dict)   # label -> {ams_id, tray_id, global_id}
    calibrated: bool = False
    observe: bool = True
    updated: float | None = None
    fingerprint: list | None = None     # `layout` fingerprint of the hardware this map was made for
    stale: bool = False                 # the printer's layout changed since: re-map (auto when idle)


def default_global(ams_id: int, tray_id: int, model=None) -> int:
    """Best guess of the printer's global slot id before calibration: the model's first numbering scheme
    (`hardware.ModelInfo.numbering`; no model / unknown model: legacy = ams_id*4+tray, an HT unit its id). A slot
    that scheme cannot number falls back to legacy. Calibration learns the real scheme (P3)."""
    hw = hardware.load()
    mi = hw.model(model)
    for key in mi.numbering[:1] + ('legacy',):
        try:
            return hw.scheme(key).encode(ams_id, tray_id)
        except (KeyError, ValueError):
            continue
    return ams_id if ams_id >= HT_BASE else ams_id * 4 + tray_id


def _slot(label: str, gid: int | None, tray_id: int, t: dict) -> Slot:
    return Slot(tray_id=tray_id, label=label, global_id=gid, type=_s(t.get('tray_type')),
                color=_s(t.get('tray_color')), preset=_s(t.get('tray_info_idx')))


def units(report: dict, model=None) -> list[Unit]:
    """AMS units (ordered by ams_id) plus the external spool holders (`vir_slot[]`, `vt_tray`) from a merged
    report, built by `layout.build` (the same units and labels `status` shows). `model`: the printer's model
    code or name (`printer_model(serial)`), None = generic."""
    out: list[Unit] = []
    for u in layout.build(report, model).units:
        if u.kind == layout.EXT_KIND:
            out.append(Unit(u.ams_id, u.kind, u.label, [_slot(s.label, u.ams_id, s.tray_id, s.raw)
                                                        for s in u.slots]))
            continue
        out.append(Unit(u.ams_id, u.kind, u.label,
                        [_slot(s.label, default_global(u.ams_id, s.tray_id, model), s.tray_id, s.raw)
                         for s in u.slots]))
    return out


def printer_model(serial: str) -> str | None:
    """The model code or name the registry has for a printer (None when unknown)."""
    try:
        p = registry.load().get(serial)
    except Exception:  # noqa: BLE001 - a broken registry file: generic handling, never a crash here
        return None
    return (p.model or None) if p is not None else None


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
    fp = d.get('fingerprint')
    return SlotMap(slots=slots if isinstance(slots, dict) else {}, calibrated=bool(d.get('calibrated')),
                   observe=bool(d.get('observe', True)), updated=d.get('updated'),
                   fingerprint=fp if isinstance(fp, list) else None, stale=bool(d.get('stale')))


def save_map(serial: str, m: SlotMap) -> None:
    f = _file(serial)
    make_state_dir(f.parent)
    m.updated = time.time()
    data = {'slots': m.slots, 'calibrated': m.calibrated, 'observe': m.observe, 'updated': m.updated,
            'fingerprint': m.fingerprint, 'stale': m.stale}
    _write_atomic(f, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)
