"""filament-kit migrate-scanner: move the owner's H2D from h2d-filament-scanner to the kit (spec P §7).

    filament-kit migrate-scanner <calibration.json> [--printer SERIAL] [--apply] [--replace-map]

Input: the scanner usage tracker's learned calibration (`/var/lib/h2d-usage/calibration.json`, written by
`usage_tracker.save_cal`): `{"version": 1, "status", "scheme", "table": {"<printer number>": {"slot":
"H2D:ams<A>:tray<T>", "source": "job" | "print", "at"}}, ...}`. On the owner's printer: scheme shift8 and numbers
0 / 2 / 32768 / 33024 for AMS 1 trays 1 / 3, AMS HT 1 and AMS HT 2 (kit labels A1, A3, HT-A, HT-B).

Two changes, reported as `old → new` (a dry run, the default) or made (`--apply`):
  1. Spoolman: every spool at one of the scanner's slot locations ("H2D - AMS slot N", "H2D - AMS HT N",
     "H2D - External left|right", the scanner's `slot_location`) moves to the kit's location for that slot,
     `status.location(<printer name>, layout.label_for(...))` ("<name> – AMS A1", "<name> – AMS HT-A",
     "<name> – AMS Ext-L"), the name from the kit's printer record. Its `extra.active_tray` (the scanner's slot
     tag) is cleared; `extra.prev_location` stays. A spool at an "H2D - " location the scanner never wrote is
     reported and left alone, like every spool elsewhere.
  2. The kit's slot map for the printer (`ams.save_map`, the file every mapping job writes): the calibration job's
     numbers as the slots' global ids, numbers learned from prints as `learned`, the scheme when the kit knows it
     and every job number agrees with it; calibrated (deducting) when the scanner deducted on it (status
     "calibrated" or "learning", Ruling BP), else observe. A calibration with no usable entry seeds nothing.
     The fingerprint is left empty: `mapping.LayoutWatch` adopts the printer's layout at its first report, and
     marks the map stale (re-map when idle) if a seeded label is not a slot of it. The mapping status then says
     "Seeded from the h2d-filament-scanner calibration" until a mapping job runs. A different map already saved
     is refused unless `--replace-map`; one with the seed's slots and scheme that the kit has updated since
     (learned numbers, mismatch streak) is kept and reported. The save is a compare-and-save (`ams.save_map_if`): a
     map saved meanwhile wins and the run says so.
Nothing is guessed: a table entry that is not a number -> {slot tag, source job|print} the kit can label is listed
as unknown and not written. A second `--apply` finds nothing to change and says so.

Before the first write, a JSON backup (every spool to change, as it was, and the slot map it replaces) goes to
`<backups>/migrate-scanner-<stamp>.json` (mode 600) and its path is printed."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config
from .bridge import ams, hardware, layout, mapping, registry, status
from .pairing import _write_atomic
from .spoolman import Spoolman, SpoolmanError

OLD_PREFIX = "H2D - "                           # the scanner's LOC_PREFIX (its locations, not the printer's name)
SEEDED_STEP = "Seeded from the h2d-filament-scanner calibration (no calibration print)"
SOURCES = ("job", "print")
CALIBRATED = ("calibrated", "learning")     # scanner statuses it deducted on (usage_tracker.deducting)
_TAG = re.compile(r"H2D:ams(\d+):tray(\d+)")
_SLOT = re.compile(r"AMS slot (\d+)")
_HT = re.compile(r"AMS HT (\d+)")
_EXT = {"External left": 254, "External right": 255}   # the scanner's EXTERNAL: 254 left, 255 right
ARROW = "→"


class Refused(Exception):
    """Nothing can be done: the message says why; nothing was written."""


@dataclass
class Move:
    spool_id: int
    old: str
    new: str
    extra: dict            # the spool's extra as it is
    clear: str | None      # the active_tray value to clear, or None when it has none


@dataclass
class Plan:
    serial: str
    name: str
    moves: list[Move] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)        # entries and locations not understood: not written
    notes: list[str] = field(default_factory=list)
    smap: ams.SlotMap | None = None
    old_map: dict | None = None                             # the saved map file's content, None when there is none
    stamp: float | None = None                              # the saved map's `updated` when planned (compare-and-save)
    map_action: str = "new"                                 # new | same | updated | replace | refused | empty


def _unwrap(v: Any) -> Any:
    """A Spoolman extra value (a JSON string) as the value it holds."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def scanner_slot(location: str) -> tuple[int, int] | None:
    """(ams_id, tray_id) for one of the scanner's slot locations (the inverse of its `slot_location`), else None."""
    if not location.startswith(OLD_PREFIX):
        return None
    rest = location[len(OLD_PREFIX):]
    if m := _SLOT.fullmatch(rest):
        n = int(m.group(1))
        return ((n - 1) // 4, (n - 1) % 4) if n >= 1 else None
    if m := _HT.fullmatch(rest):
        n = int(m.group(1))
        return (127 + n, 0) if 1 <= n <= 126 else None
    if rest in _EXT:
        return (_EXT[rest], 0)
    return None


def read_calibration(path: str | Path) -> dict:
    try:
        c = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refused(f"cannot read the calibration file {path}: {e}") from e
    if not isinstance(c, dict) or c.get("version") != 1 or not isinstance(c.get("table"), dict):
        raise Refused(f"{path} is not a scanner calibration file (version 1 with a table)")
    return c


def pick_printer(serial: str | None) -> registry.Printer:
    printers = registry.load()
    if serial:
        p = printers.get(serial)
        if p is None:
            raise Refused(f"printer {serial} is not in the kit; add it first (Printers in the app)")
        return p
    if len(printers) == 1:
        return next(iter(printers.values()))
    if not printers:
        raise Refused("no printer in the kit yet; add the H2D first (Printers in the app)")
    raise Refused("more than one printer in the kit; say which with --printer SERIAL: " + ", ".join(sorted(printers)))


def seed_map(cal: dict, model, hw: hardware.Hardware, unknown: list[str], notes: list[str]) -> ams.SlotMap:
    """The kit slot map the scanner's calibration describes (only what the file says)."""
    slots: dict[str, dict] = {}
    learned: dict[str, str] = {}
    clash: set[str] = set()
    for key, e in cal["table"].items():
        n = int(key) if isinstance(key, str) and key.isdigit() else None
        m = _TAG.fullmatch(e.get("slot") or "") if isinstance(e, dict) and isinstance(e.get("slot"), str) else None
        src = e.get("source", "job") if isinstance(e, dict) else None
        if n is None or m is None or src not in SOURCES:
            unknown.append(f"calibration entry {key!r} ({json.dumps(e)[:80]}): not understood, not written")
            continue
        a, t = int(m.group(1)), int(m.group(2))
        label = layout.label_for(a, t, model, hw)
        if label is None:
            unknown.append(f"calibration entry {key!r}: slot {e['slot']} has no kit label, not written")
            continue
        if src == "job":
            if label in slots:
                clash.add(label)
            slots[label] = {"ams_id": a, "tray_id": t, "global_id": n}
        else:
            learned[str(n)] = label
    for label in sorted(clash):
        unknown.append(f"calibration: two job entries name slot {label}; neither is written")
        slots.pop(label)
    for k in [k for k in learned if any(s["global_id"] == int(k) for s in slots.values())]:
        learned.pop(k)                              # a number the job proved: the map's own entry wins

    scheme = cal.get("scheme")
    if scheme is not None and not (isinstance(scheme, str) and scheme):
        unknown.append(f"calibration scheme {scheme!r}: not understood, not seeded")
        scheme = None
    if scheme:
        mi = hw.model(model)
        try:
            sch = hw.scheme(scheme)
        except KeyError:
            unknown.append(f"calibration scheme {scheme!r} is unknown to the kit: not seeded")
            sch = None
        if sch is not None:
            bad = []
            for label, s in slots.items():
                if s["ams_id"] in layout.EXT_DEFAULT or any(x.id == s["ams_id"] for x in mi.externals):
                    continue                        # an external holder keeps its own id (ams.scheme_global)
                try:
                    ok = sch.encode(s["ams_id"], s["tray_id"]) == s["global_id"]
                except (KeyError, ValueError):
                    ok = False
                if not ok:
                    bad.append(f"{label} = {s['global_id']}")
            if bad:
                unknown.append(f"calibration scheme {scheme!r} does not explain {', '.join(bad)}: scheme not "
                               "seeded (the slots keep their own numbers)")
                sch = None
        scheme = scheme if sch is not None else None

    # Ruling BP: "learning" (calibrated by the job, still learning numbers from prints) deducted in the scanner too
    calibrated = cal.get("status") in CALIBRATED and bool(slots)
    if not calibrated:
        notes.append(f"the scanner's calibration is {cal.get('status')!r}"
                     f"{'' if slots else ' with no job entries'}: the map is seeded in observe mode (use is only "
                     "logged) until Map slots succeeds")
    return ams.SlotMap(slots=slots, calibrated=calibrated, observe=not calibrated, scheme=scheme, learned=learned)


def _map_file(serial: str) -> dict | None:
    try:
        d = json.loads((config.paths().state / "printers" / serial / ams.FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _same_map(a: ams.SlotMap, b: ams.SlotMap) -> bool:
    return (a.slots, a.calibrated, a.observe, a.scheme, a.learned) == (b.slots, b.calibrated, b.observe, b.scheme,
                                                                        b.learned)


def make_plan(cal: dict, printer: registry.Printer, spools: list[dict], replace_map: bool) -> Plan:
    hw = hardware.load()
    model = printer.model or None
    name = registry.display_name(printer)
    plan = Plan(printer.serial, name)
    for s in sorted(spools, key=lambda s: s.get("id") or 0):
        where = s.get("location") or ""
        if not where.startswith(OLD_PREFIX):
            continue
        slot = scanner_slot(where)
        label = layout.label_for(*slot, model, hw) if slot else None
        if label is None:
            plan.unknown.append(f"spool {s.get('id')} at {where!r}: not a scanner slot location, not moved")
            continue
        extra = dict(s.get("extra") or {})
        at = _unwrap(extra.get("active_tray"))
        plan.moves.append(Move(int(s["id"]), where, status.location(name, label), extra,
                               extra["active_tray"] if at not in (None, "") else None))

    plan.smap = seed_map(cal, model, hw, plan.unknown, plan.notes)
    old = ams.load_map(printer.serial)
    plan.old_map = _map_file(printer.serial)
    plan.stamp = old.updated
    if not plan.smap.slots and not plan.smap.learned:
        plan.map_action = "empty"
    elif old.slots:
        if _same_map(old, plan.smap):
            plan.map_action = "same"
        elif (old.slots, old.scheme) == (plan.smap.slots, plan.smap.scheme):
            plan.map_action = "updated"         # our seed, since changed by the kit (learned, streak ...): keep it
        else:
            plan.map_action = "replace" if replace_map else "refused"
    return plan


def _show(plan: Plan, out: Callable[[str], None]) -> None:
    out(f"Printer {plan.serial} ({plan.name}):")
    if plan.moves:
        out("Spoolman locations:")
        for mv in plan.moves:
            cleared = f"; active_tray {_unwrap(mv.clear)!r} cleared" if mv.clear else ""
            out(f"  spool {mv.spool_id}: {mv.old} {ARROW} {mv.new}{cleared}")
    else:
        out("Spoolman locations: no spool at a scanner slot location")
    m = plan.smap
    if plan.map_action == "same":
        out("Slot map: already seeded from this calibration")
    elif plan.map_action == "updated":
        out("Slot map: seeded earlier, since updated by the kit (kept as it is)")
    elif plan.map_action == "empty":
        out("Slot map: the calibration has no usable entries; no slot map seeded (run Map slots in the app)")
    else:
        what = {"new": "Slot map (new)", "replace": "Slot map (replaces the saved one)",
                "refused": "Slot map: a different map is saved; NOT replaced without --replace-map"}[plan.map_action]
        out(f"{what}:")
        for label, s in m.slots.items():
            out(f"  {label} = {s['global_id']} (ams {s['ams_id']} tray {s['tray_id']})")
        for n, label in m.learned.items():
            out(f"  {label} = {n} (learned from a print)")
        out(f"  scheme {m.scheme or 'none (the numbers above only)'}; "
            f"{'calibrated (filament use is deducted)' if m.calibrated else 'observe mode (use is only logged)'}")
    for line in plan.unknown:
        out(f"unknown: {line}")
    for line in plan.notes:
        out(f"note: {line}")


def _backup(plan: Plan, cal_path: str) -> Path:
    d = config.paths().backups
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    f = d / f"migrate-scanner-{stamp}.json"
    n = 1
    while f.exists():
        n += 1
        f = d / f"migrate-scanner-{stamp}-{n}.json"
    data = {"at": int(time.time()), "calibration": str(cal_path), "printer": plan.serial,
            "spools": [{"id": mv.spool_id, "location": mv.old, "extra": mv.extra} for mv in plan.moves],
            "slot_map": plan.old_map if plan.map_action == "replace" else None}
    _write_atomic(f, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"), 0o600)
    return f


def run(cal_path: str, *, apply: bool = False, replace_map: bool = False, serial: str | None = None,
        sm: Spoolman | None = None, out: Callable[[str], None] = print) -> int:
    try:
        cal = read_calibration(cal_path)
        printer = pick_printer(serial)
        sm = sm or Spoolman(config.load()["spoolman_url"])
        try:
            spools = sm.get("spool?allow_archived=true")
        except SpoolmanError as e:
            raise Refused(f"cannot read the spools from Spoolman: {e}") from e
        plan = make_plan(cal, printer, spools if isinstance(spools, list) else [], replace_map)
    except Refused as e:
        out(f"error: {e}")
        return 1
    _show(plan, out)
    if plan.map_action == "refused":
        out("error: the printer already has a slot map; nothing was changed. Run again with --replace-map to "
            "replace it (the old one goes into the backup).")
        return 1
    seed = plan.map_action in ("new", "replace")
    if not plan.moves and not seed:
        out("Nothing to change: the spools and the slot map are already migrated.")
        return 0
    if not apply:
        out("Dry run: nothing was written. Run again with --apply (as root) to migrate.")
        return 0
    if mapping.job_held_elsewhere(plan.serial):
        out("error: a slot mapping job is running for this printer; try again when it has finished. "
            "Nothing was changed.")
        return 1
    backup = _backup(plan, cal_path)
    out(f"backup of everything changed: {backup}")
    done = 0
    for mv in plan.moves:
        body: dict = {"location": mv.new}
        if mv.clear is not None:
            body["extra"] = {**mv.extra, "active_tray": json.dumps("")}
        try:
            sm.patch(f"spool/{mv.spool_id}", body)
        except SpoolmanError as e:
            out(f"error: spool {mv.spool_id}: {e}; {done} of {len(plan.moves)} spools moved, the slot map not "
                f"written. Fix it and run again (what moved stays moved); the backup is {backup}")
            return 1
        done += 1
    if seed:
        if not ams.save_map_if(plan.serial, plan.smap, plan.stamp):
            out(f"error: the printer's slot map changed meanwhile (a mapping job or usage saved it); it was not "
                f"replaced. {done} spool(s) moved. Run again to see the map now saved; the backup is {backup}")
            return 1
        mapping.record_seeded(plan.serial, SEEDED_STEP, plan.unknown + plan.notes)
    out(f"Done: {done} spool(s) moved{', slot map seeded' if seed else ''}.")
    return 0
