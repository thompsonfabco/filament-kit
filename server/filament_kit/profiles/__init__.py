"""The owner's generated Bambu Studio filament presets.

Loading a spool into a printer slot sends the preset's `filament_id` as `tray_info_idx`: always the owner's own
preset for that filament line x printer model x nozzle, never a Generic one and never an invented id.
`preset_for` (`index.preset_for`) reads the last good build (`builds.current()`): it finds the line by the
filament's vendor + `extra.line` (falling back to the build's Spoolman filament-id map), refuses a preset whose
`filament_id` is not a generated id or that lacks either nozzle temperature, and takes `setting_id` from the PC
sync's live upload. No build yet, an unknown model or a nozzle without a preset gives None (loading refuses with
`no_preset`).

Modules: `builds` (sync storage, builds with last-good fallback), `index` (preset_for), `generate`, `lines`,
`values`, `inapp`, `bbl`, `orca` (the Orca Slicer system store), `errors`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetRef:
    filament_id: str               # the preset's Bambu Studio filament_id (sent as tray_info_idx), P + 7 hex
    name: str                      # the preset's name, e.g. "SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle"
    nozzle_temp_min: int           # the preset's nozzle_temperature_range_low
    nozzle_temp_max: int           # the preset's nozzle_temperature_range_high
    filament_type: str             # the preset's Bambu filament_type (sent as tray_type)
    setting_id: str = ""           # Bambu Studio's setting_id from the live upload's base/<name>.info, else ""


from . import errors  # noqa: E402
from . import index  # noqa: E402
from .index import preset_for  # noqa: E402

__all__ = ["PresetRef", "preset_for", "errors", "index"]
