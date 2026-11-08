"""AFC-Klipper-Add-On (Box Turtle, Night Owl ...): one slot per `AFC_lane <name>` object, one unit per AFC unit.

A lane's label is its name when that fits the API's slot labels (`[A-Za-z0-9-]{1,16}`), else `L<n>` (its 1-based
place among the lanes). The set gcode names the lane by its real name, which must also be safe for gcode
(`[A-Za-z0-9_]{1,32}`); a lane whose name is not is shown but cannot be set from the kit (UnknownSlot).
AFC owns Moonraker's lane_data, so the kit never publishes it for AFC printers.
"""
from __future__ import annotations

import re

from .base import Adapter, SlotState, UnitState, UnknownSlot, color, fill, spool_value

PREFIX = "AFC_lane "
LABEL = re.compile(r"[A-Za-z0-9-]{1,16}")


def _lanes(status) -> list[tuple[str, str, dict]]:
    """(label, real name, fields) for every AFC_lane object in status, in their order."""
    out = []
    for i, (obj, fields) in enumerate(((k, v) for k, v in status.items() if k.startswith(PREFIX)), start=1):
        name = obj[len(PREFIX):]
        out.append((name if LABEL.fullmatch(name) else f"L{i}", name, fields or {}))
    return out


def _find(label, status) -> tuple[str, dict]:
    for lab, name, fields in _lanes(status or {}):
        if lab == label:
            return name, fields
    raise UnknownSlot(f"no AFC lane {label}")


class Afc(Adapter):
    name = "afc"

    def objects(self, model, system):
        return {"AFC": None}

    def objects_from(self, object_list):
        return {o: None for o in object_list if o == "AFC" or o.startswith(PREFIX)}

    def read(self, status, spool_id, db, model, system, hw):
        units: dict[str, UnitState] = {}
        for label, _name, f in _lanes(status):
            unit = str(f.get("unit") or "AFC")
            u = units.setdefault(unit, UnitState(len(units), unit, "lane"))
            present = f.get("load") if isinstance(f.get("load"), bool) else None
            u.slots.append(SlotState(label, hw.say(label), spool_value(f.get("spool_id")),
                                     bool(f.get("tool_loaded")), present,
                                     str(f.get("material") or "") or None, color(f.get("color"))))
        return list(units.values())

    def spool_on(self, status, spool_id, db, label, model, system):
        return spool_value(_find(label, status)[1].get("spool_id"))

    def set_gcode(self, label, spool_id, model, system, hw, status=None):
        return fill(system.set_gcode, lane=_find(label, status)[0], spool=spool_id)

    def clear_gcode(self, label, model, system, hw, status=None):
        return fill(system.clear_gcode, lane=_find(label, status)[0])
