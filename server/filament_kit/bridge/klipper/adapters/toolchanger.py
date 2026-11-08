"""Toolchangers and IDEX printers: one spool per tool, kept by the printer pack's `_FK_TOOL_SPOOLS` macro.

The macro and its variable names come from the system's `<spool-var macro var>` (`var` holds `{tool}`); tool n's
extruder is `extruder` for 0 and `extruder<n>` otherwise, so the active tool is the one whose extruder is
`toolhead.extruder`.
"""
from __future__ import annotations

from .base import Adapter, SlotState, UnitState, UnknownSlot, fill, say_for, spool_value


def _tool(label, model):
    for s in model.slots:
        if s.label == label:
            return s
    raise UnknownSlot(f"no tool {label} (tools: {', '.join(s.label for s in model.slots) or 'none'})")


def _var(system, n: int) -> str:
    return (system.spool_var or "t{tool}").replace("{tool}", str(n)).lower()


def _macro(system) -> str:
    return f"gcode_macro {system.spool_var_macro or '_FK_TOOL_SPOOLS'}"


class Toolchanger(Adapter):
    name = "toolchanger"
    publishes_lane_data = True

    def objects(self, model, system):
        return {_macro(system): None, "toolhead": None}

    def read(self, status, spool_id, db, model, system, hw):
        spools = status.get(_macro(system)) or {}
        active = (status.get("toolhead") or {}).get("extruder")
        units = []
        for i, s in enumerate(model.slots):
            ext = "extruder" if s.n == 0 else f"extruder{s.n}"
            units.append(UnitState(i, s.label, "toolhead",
                                   [SlotState(s.label, say_for(s, hw), spool_value(spools.get(_var(system, s.n))),
                                              active == ext, None)]))
        return units

    def spool_on(self, status, spool_id, db, label, model, system):
        s = _tool(label, model)
        return spool_value((status.get(_macro(system)) or {}).get(_var(system, s.n)))

    def set_gcode(self, label, spool_id, model, system, hw, status=None):
        return fill(system.set_gcode, tool=_tool(label, model).n, spool=spool_id)

    def clear_gcode(self, label, model, system, hw, status=None):
        return fill(system.clear_gcode, tool=_tool(label, model).n)
