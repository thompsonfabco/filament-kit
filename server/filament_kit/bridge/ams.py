"""AMS model (units and slots read from a report) and the per-printer slot map store.

Units and labels come from `layout.build` (A1 ... Z4, AA1 ..., HT-A ..., Ext / Ext-L / Ext-R), the builder
`status` uses too, so the app, the status join and the slot map agree. The slot map ties each label to the
printer's own global slot id once calibrated; until then `default_global` is the guess. It also keeps the layout
fingerprint the map was made for (`fingerprint`) and `stale` (the printer's layout changed since).

The decoding a printer uses (P3): each slot's `global_id` (what calibration saw the printer report, or for a slot
the job skipped the proven scheme's number), `scheme` (the numbering scheme calibration proved, None when none was
proven), and `learned` (numbers a print taught: `usage`, exactly one loaded slot held the sliced filament).
`mismatch_streak` / `suspect`: prints whose decoded slot held another filament; two in a row make the map suspect
(observe until re-mapped; `mapping.LayoutWatch` re-maps when the printer is idle)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .. import config
from ..pairing import _write_atomic, make_state_dir
from . import hardware, layout, registry
from .status import EXT, EXT_ID, HT_BASE, _s  # noqa: F401 - EXT/EXT_ID re-exported
from .status import _int as status_int

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
    scheme: str | None = None           # the numbering scheme calibration proved (`hardware.Scheme` key)
    learned: dict[str, str] = field(default_factory=dict)   # printer number (str) -> label, learned from prints
    mismatch_streak: int = 0            # prints in a row whose decoded slot held another filament than sliced
    suspect: bool = False               # two such prints: logging only (observe) until a re-map (auto when idle)


def default_global(ams_id: int, tray_id: int, model=None, hw: hardware.Hardware | None = None) -> int:
    """Best guess of the printer's global slot id before calibration: the model's first numbering scheme
    (`hardware.ModelInfo.numbering`; no model / unknown model: legacy = ams_id*4+tray, an HT unit its id). A slot
    that scheme cannot number falls back to legacy. Calibration learns the real scheme (P3). `hw`: an already
    loaded `hardware.Hardware` (one load for many slots)."""
    hw = hw or hardware.load()
    mi = hw.model(model)
    for key in mi.numbering[:1] + ('legacy',):
        try:
            return hw.scheme(key).encode(ams_id, tray_id)
        except (KeyError, ValueError):
            continue
    return ams_id if ams_id >= HT_BASE else ams_id * 4 + tray_id


def scheme_global(ams_id: int, tray_id: int, scheme: str | None, model=None,
                  hw: hardware.Hardware | None = None) -> int:
    """The printer's number for a slot under a proven `scheme` (an external holder keeps its own id, the number
    Bambu uses for a virtual tray); without one, or one that cannot number the slot, `default_global`."""
    hw = hw or hardware.load()
    if scheme:
        mi = hw.model(model)
        if any(x.id == ams_id for x in mi.externals) or ams_id in layout.EXT_DEFAULT:
            return int(ams_id)
        try:
            return hw.scheme(scheme).encode(ams_id, tray_id)
        except (KeyError, ValueError):
            pass
    return default_global(ams_id, tray_id, model, hw)


def _slot(label: str, gid: int | None, tray_id: int, t: dict) -> Slot:
    return Slot(tray_id=tray_id, label=label, global_id=gid, type=_s(t.get('tray_type')),
                color=_s(t.get('tray_color')), preset=_s(t.get('tray_info_idx')))


def units(report: dict, model=None) -> list[Unit]:
    """AMS units (ordered by ams_id) plus the external spool holders (`vir_slot[]`, `vt_tray`) from a merged
    report, built by `layout.build` (the same units and labels `status` shows). `model`: the printer's model
    code or name (`printer_model(serial)`), None = generic."""
    out: list[Unit] = []
    hw = hardware.load()
    mi = hw.model(model)
    for u in layout.build(report, mi, hw).units:
        if u.kind == layout.EXT_KIND:
            out.append(Unit(u.ams_id, u.kind, u.label, [_slot(s.label, u.ams_id, s.tray_id, s.raw)
                                                        for s in u.slots]))
            continue
        out.append(Unit(u.ams_id, u.kind, u.label,
                        [_slot(s.label, default_global(u.ams_id, s.tray_id, mi, hw), s.tray_id, s.raw)
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


def _current_labels(slots: dict, model) -> dict:
    """Slot-map keys under an older external label ("Ext" on the H2D) renamed to the current one ("Ext-L"); a
    key the current label already has wins. In memory only: the file changes at the next save."""
    names = layout.aliases(model)
    if not names or not any(k in names for k in slots):
        return slots
    out = {k: v for k, v in slots.items() if k not in names}
    for k, v in slots.items():
        if k in names:
            out.setdefault(names[k], v)
    return out


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
    model = printer_model(serial)
    slots = _current_labels(slots, model) if isinstance(slots, dict) else {}
    scheme = d.get('scheme')
    learned = d.get('learned')
    names = layout.aliases(model)
    learned = {str(k): names.get(v, v) for k, v in learned.items()
               if isinstance(v, str) and status_int(k) is not None} if isinstance(learned, dict) else {}
    streak = d.get('mismatch_streak')
    return SlotMap(slots=slots, calibrated=bool(d.get('calibrated')),
                   observe=bool(d.get('observe', True)), updated=d.get('updated'),
                   fingerprint=fp if isinstance(fp, list) else None, stale=bool(d.get('stale')),
                   scheme=scheme if isinstance(scheme, str) and scheme else None, learned=learned,
                   mismatch_streak=streak if isinstance(streak, int) and streak >= 0 else 0,
                   suspect=bool(d.get('suspect')))


def save_map(serial: str, m: SlotMap) -> None:
    f = _file(serial)
    make_state_dir(f.parent)
    m.updated = time.time()
    data = {'slots': m.slots, 'calibrated': m.calibrated, 'observe': m.observe, 'updated': m.updated,
            'fingerprint': m.fingerprint, 'stale': m.stale, 'scheme': m.scheme, 'learned': m.learned,
            'mismatch_streak': m.mismatch_streak, 'suspect': m.suspect}
    _write_atomic(f, json.dumps(data, indent=2).encode("utf-8"), 0o600, state_owned=True)
