"""Happy Hare MMUs: one unit `MMU`, one slot per gate (`G0`, `G1` ...) from the `mmu` object's gate arrays.

gate_spool_id -1 = no spool; gate_status -1 = unknown, 0 = empty, 1/2 = filament there; `mmu.gate` = the gate in use.
Happy Hare keeps Moonraker's active spool itself when it changes gates.
"""
from __future__ import annotations

import re

from .base import Adapter, SlotState, UnitState, UnknownSlot, color, fill, spool_value

GATE = re.compile(r"G(\d{1,3})")


def _at(arr, i):
    return arr[i] if isinstance(arr, list) and i < len(arr) else None


def _gate(label, mmu) -> int:
    m = GATE.fullmatch(label or "")
    n = len(mmu.get("gate_status") or []) if mmu else 0
    if not m or int(m.group(1)) >= n:
        raise UnknownSlot(f"no MMU gate {label}")
    return int(m.group(1))


class HappyHare(Adapter):
    name = "happyhare"

    def objects(self, model, system):
        return {"mmu": None}

    def read(self, status, spool_id, db, model, system, hw):
        mmu = status.get("mmu") or {}
        gates = mmu.get("gate_status") or []
        u = UnitState(0, "MMU", "lane")
        for i, gs in enumerate(gates):
            present = None if not isinstance(gs, int) or gs < 0 else gs > 0
            u.slots.append(SlotState(f"G{i}", hw.say(f"G{i}"), spool_value(_at(mmu.get("gate_spool_id"), i)),
                                     mmu.get("gate") == i, present,
                                     str(_at(mmu.get("gate_material"), i) or "") or None,
                                     color(_at(mmu.get("gate_color"), i))))
        return [u]

    def spool_on(self, status, spool_id, db, label, model, system):
        mmu = status.get("mmu") or {}
        return spool_value(_at(mmu.get("gate_spool_id"), _gate(label, mmu)))

    def set_gcode(self, label, spool_id, model, system, hw, status=None):
        return fill(system.set_gcode, gate=str(_gate(label, (status or {}).get("mmu"))), spool=spool_id)

    def clear_gcode(self, label, model, system, hw, status=None):
        return fill(system.clear_gcode, gate=str(_gate(label, (status or {}).get("mmu"))))
