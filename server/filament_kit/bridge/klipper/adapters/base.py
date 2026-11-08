"""What every filament-system adapter offers (spec §4.2).

An adapter turns Moonraker data into the kit's units and slots and knows the gcode that puts a spool in a slot. It is
stateless: every call gets the printer's `Model` and `System` from klipper_hardware.xml (`hw` for speech words).

    objects(model, system) -> {object: None}          what to subscribe to besides the common objects
    read(status, spool_id, db, model, system, hw) -> list[UnitState]
                                                       status = the merged subscription, spool_id = Moonraker's
                                                       active spool, db = the lane_data namespace (or None)
    spool_on(status, spool_id, db, label, model, system) -> int | None   the spool the printer shows in that slot
    set_gcode(label, spool_id, model, system, hw) -> str     raises UnknownSlot, NotSupported
    clear_gcode(label, model, system, hw) -> str
    publishes_lane_data: bool                          the kit writes Moonraker lane_data for it by default

A slot's `spool_id` is None when the printer shows none (0, -1, missing or not a number).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import hardware as kh


class UnknownSlot(Exception):
    pass


class NotSupported(Exception):
    pass


@dataclass
class SlotState:
    label: str
    say: list = field(default_factory=list)
    spool_id: int | None = None
    active: bool = False
    present: bool | None = None
    material: str | None = None      # what the printer itself says (AFC / Happy Hare), else None
    color: str | None = None         # "#RRGGBB" from the printer, else None


@dataclass
class UnitState:
    unit: int
    label: str
    kind: str                          # "toolhead" | "lane"
    slots: list = field(default_factory=list)


def spool_value(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        return None
    return v


def say_for(slot: kh.Slot, hw: kh.Hardware) -> list[str]:
    """Speech for a slot: a `<speech><word>` for its label wins, then the slot's own `say`, then letters/digits."""
    if slot.label.upper() in hw.words:
        return hw.say(slot.label)
    return [slot.say] if slot.say else hw.say(slot.label)


def fill(template: str | None, **values) -> str:
    if not template:
        raise NotSupported("this filament system has no gcode for that")
    try:
        return kh.fill(template, **values)
    except ValueError as e:
        raise UnknownSlot(str(e)) from None


def color(v) -> str | None:
    s = str(v or "").strip().lstrip("#")
    if len(s) >= 6 and all(c in "0123456789abcdefABCDEF" for c in s[:6]):
        return "#" + s[:6].upper()
    return None


class Adapter:
    name = "base"
    publishes_lane_data = False

    def objects(self, model, system) -> dict:
        return {}

    def objects_from(self, object_list) -> dict:
        """Objects to subscribe to that depend on the printer's object list (AFC lanes)."""
        return {}

    def read(self, status, spool_id, db, model, system, hw) -> list[UnitState]:
        raise NotImplementedError

    def spool_on(self, status, spool_id, db, label, model, system) -> int | None:
        raise NotImplementedError

    def set_gcode(self, label, spool_id, model, system, hw, status=None) -> str:
        raise NotSupported(f"{self.name} slots are set on the printer")

    def clear_gcode(self, label, model, system, hw, status=None) -> str:
        raise NotSupported(f"{self.name} slots are cleared on the printer")
