# Spool Sync (OrcaSlicer plugin)

Selects the filament presets in OrcaSlicer's slots from the spools loaded on a Klipper printer: every slot from
Moonraker's `lane_data` (filament-kit publishes it for toolchangers; AFC writes it too), or slot 1 from Moonraker's
active spool on a one-tool printer. It prefers the preset filament-kit names for the lane, then a preset whose notes
list the Spoolman filament id, then the best vendor + type match.

Install: copy `spool_sync.py` into `%APPDATA%\OrcaSlicer\orca_plugins\spool_sync\` (Windows) and enable it in
Orca's Plugins dialog. Needs an Orca build with the preset plugin API (nightly after 2026-10-23). Orca asks for
network access to the active printer preset's print host at load; list more printers (one URL per line) in
`hosts.txt` in the plugin's storage folder.

Tests: `python -m pytest integrations/orca-spool-sync` (a stub `orca` module).
