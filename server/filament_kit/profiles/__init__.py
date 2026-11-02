"""The owner's generated Bambu Studio filament presets (interface only until the profiles plan lands).

Loading a spool into a printer slot sends the preset's `filament_id` as `tray_info_idx`: always the owner's own
preset for that filament line x printer model x nozzle, never a Generic one and never an invented id. Until the
profiles plan provides the index, `preset_for` finds nothing, so loading refuses (`no_preset`)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetRef:
    filament_id: str               # the preset's Bambu Studio filament_id (sent as tray_info_idx)
    name: str                      # the preset's name, e.g. "SUNLU PLA+ Grey @Bambu Lab H2D 0.4 nozzle"
    nozzle_temp_min: int | None
    nozzle_temp_max: int | None


def preset_for(filament: dict, model: str, nozzle_mm: float) -> PresetRef | None:
    """The owner's preset for this Spoolman `filament` on a printer `model` with a `nozzle_mm` nozzle, or None.

    Stub: always None until the profiles plan lands."""
    return None
