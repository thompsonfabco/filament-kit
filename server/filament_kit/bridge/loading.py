"""Loading a Spoolman spool into a printer's AMS slot, and unloading it again.

`load(manager, sm, serial, label, spool_id, dry)`:
  1. the printer must be in the registry, the spool in Spoolman (not archived), the printer connected with a
     known `gcode_state`, the slot known (the calibrated slot map's address, else the report's units
     (`ams.units`: A1 ... Z4, AA1 ..., HT-A ..., Ext or Ext-L / Ext-R)). Ruling BK: a print does not block a
     load (the owner loads a spool into a free slot while printing, as the scanner allowed); only the slot that
     feeds the running job is refused (`SlotInUse`: `ams.tray_now`, and an extruder's `snow` when the report has
     it; Ruling BM: on a multi-nozzle model without `snow`, every slot in the job's `mapping`, and every slot
     while the job has no `mapping` yet), and a slot mapping or calibration job (`mapping.load_guard`). Mapping
     and the slot test keep `slottest.check_idle`;
  2. nozzle size: the report's top-level `nozzle_diameter`, else `device.nozzle.info[].diameter` of the slot's
     extruder (bits 8-11 of the unit's `info`; id 0 when the report does not say), else 0.4 with
     `nozzle_assumed: true` in the result (never refused for a missing size); preset =
     `profiles.preset_for(filament, model, nozzle_mm)`; None -> `NoPreset`, nothing sent. Never a Generic
     preset, never an invented id: `tray_info_idx` is the preset's `filament_id`;
  3. `ams_filament_setting` (`Manager.set_slot`): `tray_info_idx`, `tray_color` (Spoolman `color_hex` + "FF"),
     `tray_type` (the preset's Bambu filament_type, not the Spoolman material), `setting_id` (the preset's,
     from the live upload, else ""), nozzle temps from the preset (ints); then the next reports must show it
     (CONFIRM_TIMEOUT). A refused write raises `SlotWriteFailed` and Spoolman is untouched; a write that is not
     confirmed in time is reported (`confirmed: false`, `problems`), not raised, and Spoolman is still updated;
  4. Spoolman (under the inventory lock): every other spool at "<printer name> – AMS <label>" goes back to its
     `extra.prev_location` (or the sealed location, "Sealed stock", if it has none) and its prev_location is
     cleared; the spool moves to that location with its previous location in `extra.prev_location` (a spool
     coming from another printer slot keeps the prev_location it already had).
  Loads into the same printer slot are serialised (a lock per (serial, label)): the last one wins on the printer
  and in Spoolman, and Spoolman ends with exactly one spool at that location. The write phase holds the printer
  against slot mapping (`mapping.load_guard`: refused at once with `mapping.AlreadyRunning` while a mapping job
  runs in this or another process; loads do not exclude each other); a confirmed-sent write also drops that slot
  from a pending slot snapshot (`snapshot.forget`), so restoring an interrupted mapping never undoes a load.
  `dry=True` runs every check and returns the plan (`command`, `moved_back`, the spool as it would be) without
  writing anything to the printer or Spoolman.

`unload(manager, sm, serial, label, dry)`: Spoolman only, the printer's slot setting is left as it is (no MQTT
command, so it works whatever the printer is doing): every spool at that slot's location goes back to its
prev_location (or "Sealed stock").

Both return `{spool, slot: {label, ams_id, tray_id, location}, preset, dry_run, moved_back: [{id, location}]}`;
load adds `confirmed` (None on a dry run), `problems`, `nozzle_mm`, `nozzle_assumed` and, on a dry run, `command`.

Errors (the API maps them):
  NoPreset                     -> 409 no_preset
  SlotInUse                    -> 409 slot_in_use (the target slot feeds the running print)
  slottest.NoStatus            -> 409 printer_offline (no gcode_state reported yet)
  mapping.AlreadyRunning      -> 409 already_running (slot mapping holds the printer)
  connection.PrinterOffline    -> 409 printer_offline (also when the printer drops during the write)
  connection.UnknownPrinter    -> 404 not_found (printer not in the registry)
  NotFound                     -> 404 not_found (unknown slot, unknown or archived spool, empty slot on unload)
  SlotWriteFailed              -> the printer refused the write (e.g. Developer Mode needed); nothing in Spoolman
  spoolman.SpoolmanError       -> Spoolman failed (after a confirmed printer write: the slot is already set)"""
from __future__ import annotations

import contextlib
import json
import logging
import threading

from .. import inventory, profiles
from ..spoolman import SpoolmanError
from . import ams, hardware, layout, mapping, registry, slottest, snapshot, status
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


class SlotInUse(Exception):
    """The target slot feeds the print that is running now (Ruling BK); nothing was changed."""


def _feeding(report: dict) -> set[tuple[int, int]]:
    """(ams_id, tray_id) of the slots feeding the job now: `ams.tray_now` and, when the report has them, each
    extruder's `snow` ((ams_id << 8) | tray_id; 0xFFFF / 0xFF.. = none)."""
    out = set()
    tag = status.tray_now_tag(status._d(status._d(report).get("ams")).get("tray_now"))
    if tag:
        a, t = tag.split(":")
        out.add((int(a), int(t)))
    for e in status._l(status._d(status._d(status._d(report).get("device")).get("extruder")).get("info")):
        v = status._int(e.get("snow"))
        if v is not None and 0 <= v < 0xFF00 and (v >> 8) != 0xFF:
            out.add((v >> 8, v & 0xFF))
    return out


def _has_snow(report: dict) -> bool:
    infos = status._l(status._d(status._d(status._d(report).get("device")).get("extruder")).get("info"))
    return any("snow" in e for e in infos)


def _job_labels(serial: str, model, report: dict) -> set[str] | None:
    """The labels of every slot the running job's `mapping` names, or None when the report has no mapping. Decoded
    with the calibrated slot map, and also with every numbering scheme the model may use (a union: this only ever
    refuses more, Ruling BM)."""
    raw = status._d(report).get("mapping")
    if not isinstance(raw, list) or not raw:
        return None
    hw = hardware.load()
    mi = hw.model(model)
    smap = ams.load_map(serial)
    by_global = {}
    if smap.calibrated:
        for lab, a in smap.slots.items():
            g = status._int(a.get("global_id")) if isinstance(a, dict) else None
            if g is not None:
                by_global[g] = lab
    out = set()
    for v in raw:
        g = status._int(v)
        if g is None or g < 0:
            continue
        if g in by_global:
            out.add(by_global[g])
        for key in mi.numbering or ("legacy",):
            try:
                dec = hw.scheme(key).decode(g)
            except KeyError:
                continue
            lab = layout.label_for(dec[0], dec[1], mi, hw) if dec else None
            if lab:
                out.add(lab)
    return out


def in_use(serial: str, model, report: dict, ams_id: int, tray_id: int, label: str) -> str | None:
    """Why this slot may not be changed now (None: it may). Only while a job is active (Ruling BK): the slot that
    feeds it (`tray_now`, an extruder's `snow`). On a model with more than one nozzle whose report has no `snow`
    (Ruling BM), `tray_now` shows one nozzle only, so every slot in the job's `mapping` counts as in use, and an
    active job without a `mapping` refuses every slot (fails closed)."""
    gs = status._s(status._d(report).get("gcode_state"))
    if gs not in status.ACTIVE:
        return None
    if (ams_id, tray_id) in _feeding(report):
        return f"{label} feeds the print that is running ({gs})"
    if hardware.load().model(model).nozzles > 1 and not _has_snow(report):
        labels = _job_labels(serial, model, report)
        if labels is None:
            return f"the running print ({gs}) does not say yet which slots it uses"
        if label in labels:
            return f"{label} is used by the print that is running ({gs})"
    return None


def check_slot_free(manager, serial: str, report: dict, ams_id: int, tray_id: int, label: str, model=None) -> None:
    """Raise PrinterOffline / NoStatus unless the printer is connected and says what it is doing; SlotInUse when
    `in_use` says so. A print on other slots does not refuse (Ruling BK)."""
    if manager.state(serial) not in slottest.ONLINE:
        raise PrinterOffline(serial)
    gs = status._s(status._d(report).get("gcode_state"))
    if gs in ("", "UNKNOWN"):
        raise slottest.NoStatus(serial)
    why = in_use(serial, model, report, ams_id, tray_id, label)
    if why:
        raise SlotInUse(f"{why}; set it once the print is done, or pick another slot")


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


def _address(serial: str, report: dict, label: str) -> tuple[int, int, str | None, str | None] | None:
    """(ams_id, tray_id, unit kind, older label) of a slot: the calibrated map's address, else the report's."""
    model = ams.printer_model(serial)
    lay = layout.build(report or {}, model)
    kinds = {u.ams_id: u.kind for u in lay.units}
    for x in lay.model.externals:       # a holder the live report does not list right now is still external
        kinds.setdefault(x.id, layout.EXT_KIND)
    alias = next((s.alias for u in lay.units for s in u.slots if s.label == label), None)
    m = ams.load_map(serial)
    a = m.slots.get(label) if m.calibrated else None
    if isinstance(a, dict) and status._int(a.get("ams_id")) is not None and status._int(a.get("tray_id")) is not None:
        aid = int(a["ams_id"])
        return aid, int(a["tray_id"]), kinds.get(aid), alias
    for u in lay.units:
        for s in u.slots:
            if s.label == label:
                return u.ams_id, s.tray_id, u.kind, s.alias
    return None


def _label(serial: str, label: str) -> str:
    """An older external label ("Ext" on the H2D) names the holder's current one ("Ext-L")."""
    return layout.aliases(ams.printer_model(serial)).get(label, label)


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
    return layout.raw_trays(report).get((ams_id, tray_id), {})


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


def _occupants(sm, loc: str, except_id=None, also: str | None = None) -> list[dict]:
    """Spools at `loc` (or at `also`, the slot's location under its older label) other than `except_id`."""
    locs = {loc, also} - {None}
    return [s for s in (sm.get("spool") or []) if s.get("location") in locs and s.get("id") != except_id]


def _target_patch(s: dict, loc: str) -> dict:
    cur = s.get("location") or ""
    if cur == loc:
        return {}
    prev = _prev(s) if _is_slot_location(cur) else cur      # slot-to-slot moves keep the original shelf
    return {"location": loc, "extra": {**(s.get("extra") or {}), "prev_location": json.dumps(prev)}}


def _preset_view(p: profiles.PresetRef) -> dict:
    return {"filament_id": p.filament_id, "name": p.name, "nozzle_temp_min": p.nozzle_temp_min,
            "nozzle_temp_max": p.nozzle_temp_max, "filament_type": p.filament_type}


def load(manager, sm, serial: str, label: str, spool_id, dry: bool, *, preset_for=None,
         sealed_location: str = SEALED) -> dict:
    """Load spool `spool_id` into slot `label` of printer `serial` (see the module docstring)."""
    preset_for = preset_for or profiles.preset_for
    p = _printer(serial)
    name = registry.display_name(p)
    spool = _spool(sm, spool_id)
    if manager.state(serial) not in slottest.ONLINE:
        raise PrinterOffline(serial)
    report = manager.wait_report(serial, lambda r: True, 0)
    if report is None:
        raise PrinterOffline(serial)
    label = _label(serial, label)
    addr = _address(serial, report, label)
    if addr is None:
        raise NotFound(f"{name} has no slot {label}")
    ams_id, tray_id, kind, alias = addr
    check_slot_free(manager, serial, report, ams_id, tray_id, label, p.model)
    loc = status.location(name, label)
    old_loc = status.location(name, alias) if alias else None
    slot = {"label": label, "ams_id": ams_id, "tray_id": tray_id, "location": loc}
    fil = spool.get("filament") or {}
    nozzle, assumed = _nozzle(report, ams_id)
    preset = preset_for(fil, p.model, nozzle)
    if preset is None:
        what = f"{status._s((fil.get('vendor') or {}).get('name'))} {status._s(fil.get('name'))}".strip()
        raise NoPreset(f"no preset of yours for Spoolman filament {fil.get('id')} ({what}) on {p.model or name} "
                       f"with a {nozzle:g} mm nozzle; slot left unchanged")
    setting = {"tray_info_idx": preset.filament_id, "tray_color": _colour(fil),
               "tray_type": preset.filament_type, "tray_sub_brands": "", "setting_id": preset.setting_id,
               "nozzle_temp_min": preset.nozzle_temp_min, "nozzle_temp_max": preset.nozzle_temp_max}
    result = {"slot": slot, "preset": _preset_view(preset), "dry_run": bool(dry), "problems": [],
              "nozzle_mm": nozzle, "nozzle_assumed": assumed}

    if dry:
        with inventory._LOCK:
            moved = _send_back(sm, _occupants(sm, loc, spool["id"], old_loc), sealed_location, dry=True)
        patch = _target_patch(spool, loc)
        return {**result, "spool": {**spool, **patch}, "confirmed": None, "moved_back": moved,
                "command": {"ams_id": ams_id, "tray_id": tray_id, **setting}}

    with mapping.load_guard(serial), _slot_lock(serial, label):
        now = manager.wait_report(serial, lambda r: True, 0)   # the job may have moved on while we waited
        if now is None:
            raise PrinterOffline(serial)
        check_slot_free(manager, serial, now, ams_id, tray_id, label, p.model)
        reply = manager.set_slot(serial, ams_id, tray_id, setting, kind=kind)
        if reply is not None and str(reply.get("result", "")).lower() != "success":
            raise SlotWriteFailed(f"{name} refused the write to {label}: "
                                  f"{reply.get('reason') or reply.get('err_code') or reply.get('result')}")
        try:      # the owner set this slot: a pending restore of an interrupted mapping must not undo it
            snapshot.forget(serial, ams_id, tray_id)
        except (OSError, ValueError):
            log.exception("load on %s: cannot update the pending slot snapshot", serial)
        confirmed = manager.wait_report(serial, lambda r: _shows(r, ams_id, tray_id, setting),
                                        CONFIRM_TIMEOUT) is not None
        if not confirmed:
            result["problems"].append(f"{label}: not confirmed (no report showed the new setting within "
                                      f"{CONFIRM_TIMEOUT:g} s)")
            log.warning("load on %s: %s not confirmed", serial, label)
        with inventory._LOCK:
            moved = _send_back(sm, _occupants(sm, loc, spool["id"], old_loc), sealed_location, dry=False)
            fresh = sm.get(f"spool/{spool['id']}")
            patch = _target_patch(fresh, loc)
            if patch:
                sm.patch(f"spool/{spool['id']}", patch)
            final = sm.get(f"spool/{spool['id']}")
    return {**result, "spool": final, "confirmed": confirmed, "moved_back": moved}


def unload(manager, sm, serial: str, label: str, dry: bool, *, sealed_location: str = SEALED) -> dict:
    """Take the spool(s) in slot `label` of printer `serial` back to their previous location, in Spoolman only."""
    p = _printer(serial)
    name = registry.display_name(p)
    label = _label(serial, label)
    loc = status.location(name, label)
    report = manager.wait_report(serial, lambda r: True, 0) if manager is not None else None
    addr = _address(serial, report or {}, label)
    slot = {"label": label, "ams_id": addr[0] if addr else None, "tray_id": addr[1] if addr else None,
            "location": loc}
    alias = addr[3] if addr else next((a for a, cur in layout.aliases(p.model).items() if cur == label), None)
    old_loc = status.location(name, alias) if alias else None
    # Spoolman only, so it works offline; but not the slot the running print feeds (Ruling BK)
    why = in_use(serial, p.model, report, addr[0], addr[1], label) if addr and report else None
    if why:
        raise SlotInUse(f"{why}; unload it once the print is done")
    guard = mapping.load_guard(serial) if not dry else contextlib.nullcontext()
    with guard, _slot_lock(serial, label), inventory._LOCK:
        here = _occupants(sm, loc, also=old_loc)
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
