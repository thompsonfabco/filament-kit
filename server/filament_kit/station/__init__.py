"""filament_kit.station: read-only HTTP view of an intake station's USB scale and NFC reader (the `station` module).

GET /state    -> {"tag": {...as /last-tag...}, "scale": {"grams", "status", "unit", "stable", "age_seconds"} | null,
                  "last_weight": {"grams", "age_seconds", "held"} | null, "panel": "/dev/ttyUSBn" | null}
                 scale = the latest report; last_weight = the latest stable reading above 20 g (the DYMO shuts itself
                 off after a few idle minutes, and the spool may be off the scale by the time the photos go in)
GET /last-tag -> {"status": "ok", "nfc_id", "read_at", "read_at_unix", "age_seconds", "held"}   (lasttag's shape)

Ported from filament-ops station/intake_station.py (split into modules, same behaviour and response shapes, so the
owner's filament-mcp reads a kit station unchanged):
- `state`: settings from the environment and the shared state every thread uses;
- `scale`: a USB HID postal scale (DYMO M10/M25/S-series, vendor 0922) read from /dev/hidraw*;
- `nfc`: a PN532 through nfcpy; tag ids via `tags.format_uid` (nfc2klipper's form, matching Spoolman's extra.nfc_id);
- `panel`: the optional button panel (station/panel/ + PANEL.md in the repo), a D1 mini on USB serial with a buzzer
  and lit Hold / Discard buttons, found by its HELLO; the reader gets the other ttyUSB port (NFC_DEVICE=auto);
- `beep`: without the panel, a scan beeps through ALSA (aplay);
- `http`: the read-only handler; answers only STATION_ALLOW.
Runs as filament-kit-station.service (`python -m filament_kit.station`); nfcpy and pyserial come from the
`[station]` extra and are imported only inside the reader and panel loops.
"""
