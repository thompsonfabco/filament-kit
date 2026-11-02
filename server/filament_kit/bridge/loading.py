"""Loading a Spoolman spool into a printer's AMS slot, and unloading it again.

`load(manager, sm, serial, label, spool_id, dry)`:
  1. the printer must be in the registry, the spool in Spoolman (not archived), the printer connected and idle
     (`slottest.check_idle`: the same rule as the slot test), the slot known (the calibrated slot map's address,
     else the report's AMS units: A1-D4, HT-A..., Ext);
  2. nozzle size: the report's top-level `nozzle_diameter`, else `device.nozzle.info[].diameter` of the slot's
     extruder (bits 8-11 of the unit's `info`; id 0 when the report does not say), else 0.4 with
     `nozzle_assumed: true` in the result (never refused for a missing size); preset =
     `profiles.preset_for(filament, model, nozzle_mm)`; None -> `NoPreset`, nothing sent. Never a Generic
     preset, never an invented id: `tray_info_idx` is the preset's `filament_id`;
  3. `ams_filament_setting` (`Manager.set_slot`): `tray_info_idx`, `tray_color` (Spoolman `color_hex` + "FF"),
     `tray_type` (the filament's material), nozzle temps from the preset; then the next reports must show it
     (CONFIRM_TIMEOUT). A refused write raises `SlotWriteFailed` and Spoolman is untouched; a write that is not
     confirmed in time is reported (`confirmed: false`, `problems`), not raised, and Spoolman is still updated;
  4. Spoolman (under the inventory lock): every other spool at "<printer name> – AMS <label>" goes back to its
     `extra.prev_location` (or the sealed location, "Sealed stock", if it has none) and its prev_location is
     cleared; the spool moves to that location with its previous location in `extra.prev_location` (a spool
     coming from another printer slot keeps the prev_location it already had).
  Loads into the same printer slot are serialised (a lock per (serial, label)): the last one wins on the printer
  and in Spoolman, and Spoolman ends with exactly one spool at that location.
  `dry=True` runs every check and returns the plan (`command`, `moved_back`, the spool as it would be) without
  writing anything to the printer or Spoolman.

`unload(manager, sm, serial, label, dry)`: Spoolman only, the printer's slot setting is left as it is (no MQTT
command, so it works whatever the printer is doing): every spool at that slot's location goes back to its
prev_location (or "Sealed stock").

Both return `{spool, slot: {label, ams_id, tray_id, location}, preset, dry_run, moved_back: [{id, location}]}`;
load adds `confirmed` (None on a dry run), `problems`, `nozzle_mm`, `nozzle_assumed` and, on a dry run, `command`.

Errors (the API maps them):
  NoPreset                     -> 409 no_preset
  slottest.PrinterBusy         -> 409 printer_busy
  connection.PrinterOffline    -> 409 printer_offline (also when the printer drops during the write)
  connection.UnknownPrinter    -> 404 not_found (printer not in the registry)
  NotFound                     -> 404 not_found (unknown slot, unknown or archived spool, empty slot on unload)
  SlotWriteFailed              -> the printer refused the write (e.g. Developer Mode needed); nothing in Spoolman
  spoolman.SpoolmanError       -> Spoolman failed (after a confirmed printer write: the slot is already set)"""
from __future__ import annotations

import json
import logging
import threading

from .. import inventory, profiles
from ..spoolman import SpoolmanError
from . import ams, registry, slottest, status
from .connection import PrinterOffline, UnknownPrinter

log = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 10.0            # seconds for a report to show the new slot setting
DEFAULT_NOZZLE = 0.4              # assumed when the report gives no nozzle size (`nozzle_assumed: true`)
SEALED = "Sealed stock"
SLOT_MARK = f" {status.DASH} AMS "   # every printer-slot location contains this

_SLOT_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_SLOT_LOCKS_GUARD = threading.Lock()


class NoPreset(Exception):
    """No preset of the owner's matches this filament on this printer and nozzle; nothing was sent."""


class NotFound(Exception):
    """Unknown slot or spool (or nothing in the slot to unload)."""


class SlotWriteFailed(Exception):
    """The printer refused the slot write (its reply is the message); Spoolman was not changed."""


def _slot_lock(serial: str, label: str) -> threading.Lock:
    with _SLOT_LOCKS_GUARD:
        return _SLOT_LOCKS.setdefault((serial, label), threading.Lock())


def _printer(serial: str) -> registry.Printer:
    p = registry.load().get(serial)
    if p is None:
        raise UnknownPrinter(serial)
    return p


def _spool(sm, spool_id) -> dict:
    try:
        s = sm.get(f"spool/{int(spool_id)}")
    except (TypeError, ValueError) as e:
        raise NotFound(f"spool {spool_id!r} not found") from e
    except SpoolmanError as e:
        if e.status == 404:
            raise NotFound(f"spool {spool_id} not found") from e
        raise
    if not isinstance(s, dict) or s.get("id") is None:
        raise NotFound(f"spool {spool_id} not found")
    if s.get("archived"):
        raise NotFound(f"spool {spool_id} is archived")
    return s


def _address(serial: str, report: dict, label: str) -> tuple[int, int] | None:
    m = ams.load_map(serial)
    a = m.slots.get(label) if m.calibrated else None
    if isinstance(a, dict) and status._int(a.get("ams_id")) is not None and status._int(a.get("tray_id")) is not None:
        return int(a["ams_id"]), int(a["tray_id"])
    for u in ams.units(report or {}):
        for s in u.slots:
            if s.label == label:
                return u.ams_id, s.tray_id
    return None


def _mm(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if n > 0 else None


def _extruder(report: dict, ams_id: int) -> int | None:
    """The extruder an AMS unit feeds, when the report says so: bits 8-11 of the unit's hex `info` (H2D/X2D, as
    Home Assistant's bambulab integration reads it). None when the report does not say (or for the Ext holder)."""
    for u in status._l(status._d(status._d(report).get("ams")).get("ams")):
        if status._int(u.get("id")) == ams_id:
            info = u.get("info")
            if isinstance(info, str) and info.strip():
                try:
                    return (int(info, 16) >> 8) & 0xF
                except ValueError:
                    return None
            return None
    return None


def _nozzle(report: dict, ams_id: int) -> tuple[float, bool]:
    """(nozzle mm, assumed) for the slot's unit (ruling R10): the top-level `nozzle_diameter`; else
    `device.nozzle.info[].diameter` of the unit's extruder (id 0 when the report does not say which); else 0.4,
    assumed."""
    p = status._d(report)
    n = _mm(p.get("nozzle_diameter"))
    if n is not None:
        return n, False
    infos = status._l(status._d(status._d(p.get("device")).get("nozzle")).get("info"))
    ex = _extruder(report, ams_id)
    want = 0 if ex is None else ex
    for e in infos:
        if status._int(e.get("id")) == want:
            n = _mm(e.get("diameter"))
            if n is not None:
                return n, False
    return DEFAULT_NOZZLE, True


def _colour(filament: dict) -> str:
    c = (status._s(filament.get("color_hex")) or "000000").upper().lstrip("#")
    return c + "FF" if len(c) == 6 else c


def _tray_at(report: dict, ams_id: int, tray_id: int) -> dict:
    p = status._d(report)
    vt = status._d(p.get("vt_tray"))
    if vt and status._int(vt.get("id")) == ams_id:
        return vt
    for u in status._l(status._d(p.get("ams")).get("ams")):
        if status._int(u.get("id")) == ams_id:
            for t in status._l(u.get("tray")):
                if status._int(t.get("id")) == tray_id:
                    return t
    return {}


def _shows(report: dict, ams_id: int, tray_id: int, setting: dict) -> bool:
    t = _tray_at(report, ams_id, tray_id)
    return (status._s(t.get("tray_info_idx")) == setting["tray_info_idx"]
            and status._s(t.get("tray_type")) == setting["tray_type"]
            and status._s(t.get("tray_color")).upper() == setting["tray_color"])


def _prev(s: dict) -> str:
    v = (s.get("extra") or {}).get("prev_location")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            pass
    return v if isinstance(v, str) else ""


def _is_slot_location(loc: str) -> bool:
    return SLOT_MARK in (loc or "")


def _send_back(sm, spools: list[dict], sealed: str, dry: bool) -> list[dict]:
    """Move each spool to its prev_location (or the sealed location) and clear the prev_location."""
    out = []
    for s in sorted(spools, key=lambda s: s["id"]):
        dest = _prev(s) or sealed
        if not dry:
            sm.patch(f"spool/{s['id']}", {"location": dest,
                                          "extra": {**(s.get("extra") or {}), "prev_location": json.dumps("")}})
        out.append({"id": s["id"], "location": dest})
    return out


def _occupants(sm, loc: str, except_id=None) -> list[dict]:
    return [s for s in (sm.get("spool") or []) if s.get("location") == loc and s.get("id") != except_id]


def _target_patch(s: dict, loc: str) -> dict:
    cur = s.get("location") or ""
    if cur == loc:
        return {}
    prev = _prev(s) if _is_slot_location(cur) else cur      # slot-to-slot moves keep the original shelf
    return {"location": loc, "extra": {**(s.get("extra") or {}), "prev_location": json.dumps(prev)}}


def _preset_view(p: profiles.PresetRef) -> dict:
    return {"filament_id": p.filament_id, "name": p.name, "nozzle_temp_min": p.nozzle_temp_min,
            "nozzle_temp_max": p.nozzle_temp_max}


def load(manager, sm, serial: str, label: str, spool_id, dry: bool, *, preset_for=None,
         sealed_location: str = SEALED) -> dict:
    """Load spool `spool_id` into slot `label` of printer `serial` (see the module docstring)."""
    preset_for = preset_for or profiles.preset_for
    p = _printer(serial)
    name = p.name or p.serial
    spool = _spool(sm, spool_id)
    slottest.check_idle(manager, serial)
    report = manager.wait_report(serial, lambda r: True, 0)
    if report is None:
        raise PrinterOffline(serial)
    addr = _address(serial, report, label)
    if addr is None:
        raise NotFound(f"{name} has no slot {label}")
    ams_id, tray_id = addr
    loc = status.location(name, label)
    slot = {"label": label, "ams_id": ams_id, "tray_id": tray_id, "location": loc}
    fil = spool.get("filament") or {}
    nozzle, assumed = _nozzle(report, ams_id)
    preset = preset_for(fil, p.model, nozzle)
    if preset is None:
        what = f"{status._s((fil.get('vendor') or {}).get('name'))} {status._s(fil.get('name'))}".strip()
        raise NoPreset(f"no preset of yours for Spoolman filament {fil.get('id')} ({what}) on {p.model or name} "
                       f"with a {nozzle:g} mm nozzle; slot left unchanged")
    setting = {"tray_info_idx": preset.filament_id, "tray_color": _colour(fil),
               "tray_type": status._s(fil.get("material")), "tray_sub_brands": "",
               "nozzle_temp_min": preset.nozzle_temp_min or 0, "nozzle_temp_max": preset.nozzle_temp_max or 0}
    result = {"slot": slot, "preset": _preset_view(preset), "dry_run": bool(dry), "problems": [],
              "nozzle_mm": nozzle, "nozzle_assumed": assumed}

    if dry:
        with inventory._LOCK:
            moved = _send_back(sm, _occupants(sm, loc, spool["id"]), sealed_location, dry=True)
        patch = _target_patch(spool, loc)
        return {**result, "spool": {**spool, **patch}, "confirmed": None, "moved_back": moved,
                "command": {"ams_id": ams_id, "tray_id": tray_id, **setting}}

    with _slot_lock(serial, label):
        slottest.check_idle(manager, serial)           # the printer may have started a job while we waited
        reply = manager.set_slot(serial, ams_id, tray_id, setting)
        if reply is not None and str(reply.get("result", "")).lower() != "success":
            raise SlotWriteFailed(f"{name} refused the write to {label}: "
                                  f"{reply.get('reason') or reply.get('err_code') or reply.get('result')}")
        confirmed = manager.wait_report(serial, lambda r: _shows(r, ams_id, tray_id, setting),
                                        CONFIRM_TIMEOUT) is not None
        if not confirmed:
            result["problems"].append(f"{label}: not confirmed (no report showed the new setting within "
                                      f"{CONFIRM_TIMEOUT:g} s)")
            log.warning("load on %s: %s not confirmed", serial, label)
        with inventory._LOCK:
            moved = _send_back(sm, _occupants(sm, loc, spool["id"]), sealed_location, dry=False)
            fresh = sm.get(f"spool/{spool['id']}")
            patch = _target_patch(fresh, loc)
            if patch:
                sm.patch(f"spool/{spool['id']}", patch)
            final = sm.get(f"spool/{spool['id']}")
    return {**result, "spool": final, "confirmed": confirmed, "moved_back": moved}


def unload(manager, sm, serial: str, label: str, dry: bool, *, sealed_location: str = SEALED) -> dict:
    """Take the spool(s) in slot `label` of printer `serial` back to their previous location, in Spoolman only."""
    p = _printer(serial)
    name = p.name or p.serial
    loc = status.location(name, label)
    report = manager.wait_report(serial, lambda r: True, 0) if manager is not None else None
    addr = _address(serial, report or {}, label)
    slot = {"label": label, "ams_id": addr[0] if addr else None, "tray_id": addr[1] if addr else None,
            "location": loc}
    with _slot_lock(serial, label), inventory._LOCK:
        here = _occupants(sm, loc)
        if not here:
            raise NotFound(f"no spool is in {name} slot {label}")
        moved = _send_back(sm, here, sealed_location, dry)
        first = min(here, key=lambda s: s["id"])
        if dry:
            spool = {**first, "location": moved[0]["location"],
                     "extra": {**(first.get("extra") or {}), "prev_location": json.dumps("")}}
        else:
            spool = sm.get(f"spool/{first['id']}")
    return {"spool": spool, "slot": slot, "preset": None, "dry_run": bool(dry), "moved_back": moved}
