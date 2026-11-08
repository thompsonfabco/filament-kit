"""One extruder: the slot is Moonraker's active spool (`SET_ACTIVE_SPOOL` / `CLEAR_ACTIVE_SPOOL`)."""
from __future__ import annotations

from .. import hardware as kh
from .base import Adapter, SlotState, UnitState, UnknownSlot, fill, say_for, spool_value


def _slot(model) -> kh.Slot:
    return model.slots[0] if model.slots else kh.Slot(0, "T0", None)


class Single(Adapter):
    name = "single"

    def _check(self, label, model) -> None:
        if label != _slot(model).label:
            raise UnknownSlot(f"no slot {label} (this printer has one: {_slot(model).label})")

    def read(self, status, spool_id, db, model, system, hw):
        s = _slot(model)
        printing = (status.get("print_stats") or {}).get("state") == "printing"
        return [UnitState(0, s.label, "toolhead",
                          [SlotState(s.label, say_for(s, hw), spool_value(spool_id), printing, None)])]

    def spool_on(self, status, spool_id, db, label, model, system):
        self._check(label, model)
        return spool_value(spool_id)

    def set_gcode(self, label, spool_id, model, system, hw, status=None):
        self._check(label, model)
        return fill(system.set_gcode, spool=spool_id)

    def clear_gcode(self, label, model, system, hw, status=None):
        self._check(label, model)
        return fill(system.clear_gcode)
