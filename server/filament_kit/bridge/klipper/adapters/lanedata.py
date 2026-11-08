"""Moonraker's `lane_data` database namespace (written by AFC, the kit or another tool): read only.

`lane<N>` entries become slots `L<N>` in one unit `Lanes`; their `spool_id`, `material` and `color` are shown.
"""
from __future__ import annotations

import re

from .base import Adapter, SlotState, UnitState, UnknownSlot, color, spool_value

KEY = re.compile(r"lane(\d{1,3})")


def _entries(db) -> list[tuple[int, dict]]:
    out = []
    for k, v in (db or {}).items():
        m = KEY.fullmatch(str(k))
        if m and isinstance(v, dict):
            out.append((int(m.group(1)), v))
    return sorted(out)


class LaneData(Adapter):
    name = "lanedata"

    def read(self, status, spool_id, db, model, system, hw):
        u = UnitState(0, "Lanes", "lane")
        for n, v in _entries(db):
            u.slots.append(SlotState(f"L{n}", hw.say(f"L{n}"), spool_value(v.get("spool_id")), False, None,
                                     str(v.get("material") or "") or None, color(v.get("color"))))
        return [u]

    def spool_on(self, status, spool_id, db, label, model, system):
        for n, v in _entries(db):
            if f"L{n}" == label:
                return spool_value(v.get("spool_id"))
        raise UnknownSlot(f"no lane {label}")
