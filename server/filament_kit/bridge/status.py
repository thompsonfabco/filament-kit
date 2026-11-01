"""Bambu MQTT report handling: merge report deltas and condense the merged report for the app.

Ported from the owner's single-printer remote (`h2d-filament-scanner/remote/remote.py`) and generalised to any
Bambu printer: nozzle count, AMS units and lights all come from the report itself."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

STAGES = {0: 'Printing', 1: 'Auto bed leveling', 2: 'Heatbed preheating', 3: 'Vibration compensation',
          4: 'Changing filament', 5: 'M400 pause', 6: 'Paused: filament runout', 7: 'Heating hotend',
          8: 'Calibrating extrusion', 9: 'Scanning bed surface', 10: 'Inspecting first layer',
          11: 'Identifying build plate', 12: 'Calibrating micro lidar', 13: 'Homing toolhead',
          14: 'Cleaning nozzle tip', 15: 'Checking extruder temperature', 16: 'Paused by user',
          17: 'Paused: front cover fell', 18: 'Calibrating micro lidar', 19: 'Calibrating extrusion flow',
          20: 'Paused: nozzle temperature fault', 21: 'Paused: heatbed temperature fault',
          22: 'Unloading filament', 23: 'Paused: skipped step', 24: 'Loading filament',
          25: 'Calibrating motor noise', 26: 'Paused: AMS lost', 27: 'Paused: heatbreak fan slow',
          28: 'Paused: chamber temperature fault', 29: 'Cooling chamber', 30: 'Paused by G-code',
          31: 'Motor noise showoff', 32: 'Paused: nozzle clumping', 33: 'Paused: cutter error',
          34: 'Paused: first layer error', 35: 'Paused: nozzle clog'}

# gcode_state values during which a stage, ETA and job are meaningful
ACTIVE = {'RUNNING', 'PAUSE', 'PREPARE', 'SLICING'}
HT_BASE = 128            # AMS HT units are addressed 128, 129, ... (one slot each, tray 0)
DASH = '–'          # Spoolman locations are "<printer name> – AMS <label>" (en dash)


def merge(full: dict, delta: dict) -> dict:
    """Deep-merge a report delta onto the last merged report; returns a new dict, inputs untouched.

    Dicts merge key by key (untouched keys stay). A list in the delta replaces the old list outright, as in the
    owner's remote.py: Bambu deltas carry complete `ams.ams` (with full tray objects) and `hms` lists (proven on
    the H2D), so an emptied slot (`{"id": "1"}`) really is empty and cleared alerts disappear."""
    out = dict(full)
    for k, v in delta.items():
        old = out.get(k)
        if isinstance(v, dict) and isinstance(old, dict):
            out[k] = merge(old, v)
        else:
            out[k] = v
    return out


def packed(v: Any) -> tuple[int | None, int | None]:
    """Newer printers (H2D family) pack a temperature as (target << 16) | current. Returns (current, target)."""
    v = _int(v)
    if v is None:
        return None, None
    return v & 0xFFFF, (v >> 16) & 0xFFFF


def hms_code(e: dict) -> str:
    """"AAAA_AAAA_CCCC_CCCC" from an HMS entry; odd values count as 0, each part is a 32-bit field."""
    a = (_int(e.get('attr'), 0) or 0) & 0xFFFFFFFF
    c = (_int(e.get('code'), 0) or 0) & 0xFFFFFFFF
    return f"{a >> 16:04X}_{a & 0xFFFF:04X}_{c >> 16:04X}_{c & 0xFFFF:04X}"


def tray_now_tag(n: Any) -> str | None:
    """`ams.tray_now` as "<ams_id>:<tray_id>"; 254 = external spool ('ext'), 255 = nothing loaded (None)."""
    n = _int(n)
    if n is None:
        return None
    if n >= 254:
        return None if n == 255 else 'ext'
    return f"{n}:0" if n >= HT_BASE else f"{n // 4}:{n % 4}"


def unit_label(ams_id: int) -> tuple[str, str]:
    """(label, kind) as Bambu Studio names units: 0 -> 'A', 1 -> 'B' ...; 128 -> 'HT-A', 129 -> 'HT-B' ...
    An id outside those ranges is labelled with its number ('#40')."""
    if HT_BASE <= ams_id < HT_BASE + 26:
        return f"HT-{chr(ord('A') + ams_id - HT_BASE)}", 'ams_ht'
    if 0 <= ams_id < 26:
        return chr(ord('A') + ams_id), 'ams'
    return f"#{ams_id}", 'ams'


def slot_label(ams_id: int, tray_id: int) -> str:
    """Studio's slot label: A1-A4, B1-B4 ... for 4-slot units; an AMS HT's single slot is the unit label."""
    label, kind = unit_label(ams_id)
    return label if kind == 'ams_ht' else f"{label}{tray_id + 1}"


def location(printer_name: str, label: str) -> str:
    """The Spoolman location of a spool sitting in that slot."""
    return f"{printer_name} {DASH} AMS {label}"


def _int(v: Any, default: int | None = None) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):  # OverflowError: JSON Infinity
        return default


def _d(v: Any) -> dict:
    """`v` if it is a dict, else {}: report fields are whatever the printer sent."""
    return v if isinstance(v, dict) else {}


def _l(v: Any) -> list:
    """The dict items of `v` if it is a list, else []."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _s(v: Any) -> str:
    return v if isinstance(v, str) else ''


def _temp(cur: Any, tgt: Any) -> dict:
    return {'current': cur, 'target': tgt}


def _temps(p: dict) -> dict:
    dev = _d(p.get('device'))
    nozzles = []
    extruders = sorted(_l(_d(dev.get('extruder')).get('info')), key=lambda e: _int(e.get('id'), 0) or 0)
    for ex in extruders:
        nozzles.append(_temp(*packed(ex.get('temp'))))
    if not nozzles and ('nozzle_temper' in p or 'nozzle_target_temper' in p):
        nozzles.append(_temp(p.get('nozzle_temper'), p.get('nozzle_target_temper')))
    bc, bt = packed(_d(_d(dev.get('bed')).get('info')).get('temp'))
    bed = _temp(bc if bc is not None else p.get('bed_temper'), bt if bt is not None else p.get('bed_target_temper'))
    cc, ct = packed(_d(_d(dev.get('ctc')).get('info')).get('temp'))
    if cc is not None:
        chamber = _temp(cc, ct)
    elif p.get('chamber_temper') is not None:
        chamber = _temp(p.get('chamber_temper'), None)
    else:
        chamber = None
    return {'nozzle': nozzles, 'bed': bed, 'chamber': chamber}


def _spool_view(s: dict) -> dict:
    f = _d(s.get('filament'))
    vendor = _s(_d(f.get('vendor')).get('name'))
    return {'id': s.get('id'), 'name': f"{vendor} {_s(f.get('name'))}".strip(),
            'material': _s(f.get('material')), 'color_hex': _s(f.get('color_hex')),
            'remaining_weight': s.get('remaining_weight')}


def _ams(p: dict, spools: list[dict], printer_name: str) -> list[dict]:
    ams = _d(p.get('ams'))
    now = tray_now_tag(ams.get('tray_now'))
    by_location: dict[str, dict] = {}
    if printer_name:
        for s in sorted(_l(spools), key=lambda s: _int(s.get('id'), 0) or 0):
            by_location.setdefault(_s(s.get('location')), s)
    units = []
    for u in _l(ams.get('ams')):
        uid = _int(u.get('id'))
        if uid is None or uid < 0:
            continue
        label, kind = unit_label(uid)
        slots = []
        for t in _l(u.get('tray')):
            tid = _int(t.get('id'))
            if tid is None or tid < 0:
                continue
            sl = slot_label(uid, tid)
            spool = by_location.get(location(printer_name, sl)) if printer_name else None
            slots.append({'slot': tid, 'label': sl, 'type': _s(t.get('tray_type')),
                          'color_hex': _s(t.get('tray_color'))[:6],
                          'active': now == f"{uid}:{tid}",
                          'spool': _spool_view(spool) if spool else None})
        units.append({'unit': uid, 'label': label, 'kind': kind, 'slots': slots})
    return units


def summarize(report: dict, spools: list[dict], *, printer_name: str = '', updated: float | None = None,
              now: float | None = None) -> dict:
    """Condense a merged report (the `print` object) into the API's `status` shape.

    `spools` are Spoolman spools; a slot shows the spool whose `location` is "<printer_name> – AMS <label>"
    (no join without a printer name). `updated` is when the last report arrived (unix seconds)."""
    p = _d(report)
    now = time.time() if now is None else now
    gs = _s(p.get('gcode_state')) or 'UNKNOWN'
    active = gs in ACTIVE
    stg = _int(p.get('stg_cur'), -1)
    remaining = _int(p.get('mc_remaining_time'), 0) or 0
    eta = None
    if active and remaining > 0:
        try:
            eta = datetime.fromtimestamp(now + remaining * 60).astimezone().isoformat(timespec='minutes')
        except (OverflowError, OSError, ValueError):  # an absurd remaining time
            eta = None
    lights = {l.get('node'): l.get('mode') for l in _l(p.get('lights_report')) if isinstance(l.get('node'), str)}
    light = None
    if 'chamber_light' in lights:
        light = 'on' if lights['chamber_light'] == 'on' else 'off'
    hms = []
    for e in _l(p.get('hms')):
        code = hms_code(e)
        hms.append({'code': code, 'text': f"Printer alert HMS {code}"})
    return {
        'gcode_state': gs,
        'stage': STAGES.get(stg, f"Stage {stg}") if active and 0 <= stg < 255 else '',
        'job': _s(p.get('subtask_name')),
        'percent': _int(p.get('mc_percent'), 0) or 0,
        'layer': _int(p.get('layer_num')),
        'total_layers': _int(p.get('total_layer_num')),
        'remaining_min': remaining,
        'eta': eta,
        'temps': _temps(p),
        'ams': _ams(p, spools, printer_name),
        'hms': hms,
        'light': light,
        'updated': int(updated) if updated else None,
    }
