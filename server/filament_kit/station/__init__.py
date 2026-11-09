"""filament_kit.station: an intake station's USB scale, NFC reader and button panel (the `station` module): the intake
flow on the panel, asking the paired kit server, and a read-only HTTP view.

GET /state    -> {"tag": {...as /last-tag...}, "scale": {"grams", "status", "unit", "stable", "age_seconds"} | null,
                  "last_weight": {"grams", "age_seconds", "held"} | null, "panel": "/dev/ttyUSBn" | null,
                  "panel_version": "2" | null,
                  "air": {"temp_c", "rh", "hpa", "age_seconds"} | null, "photo": {"url", "taken_at", "age_seconds"} | null,
                  "flow": {"step", "message", "spool", "filament"}}
                 scale = the latest report; last_weight = the latest stable reading above 20 g (the DYMO shuts itself
                 off after a few idle minutes, and the spool may be off the scale by the time the photos go in), or the
                 weight taken with yellow ("held"); air = the panel's sensor (null fields: not fitted); photo = the
                 webcam's picture for recognition; flow = where the intake flow is (`flow`)
GET /last-tag -> {"status": "ok", "nfc_id", "read_at", "read_at_unix", "age_seconds", "held"}   (lasttag's shape)
GET /photo    -> image/jpeg: that picture (404 when there's none)

Ported from filament-ops station/intake_station.py (split into modules, same behaviour and response shapes, so the
owner's filament-mcp reads a kit station unchanged):
- `state`: settings from the environment and the shared state every thread uses;
- `scale`: a USB HID postal scale (DYMO M10/M25/S-series, vendor 0922) read from /dev/hidraw*;
- `nfc`: a PN532 through nfcpy; tag ids via `tags.format_uid` (nfc2klipper's form, matching Spoolman's extra.nfc_id);
- `panel`: the button panel (station/panel/ + PANEL.md in the repo), an ESP32-C3 on USB serial with a buzzer, an OLED
  and lit yellow (Hold) / red (Discard) buttons, found by its HELLO; the reader gets the other ttyUSB port
  (NFC_DEVICE=auto). A panel on other firmware than the bundled one is reflashed with esptool (STATION_PANEL_FLASH=0
  stops that);
- `flow`: the intake flow the panel runs (scan, camera + recognition, weigh, long yellow saves; red cancels), asking
  the kit server through `server_api` (pinned TLS, the pairing files from `filament-kit station pair`);
- `wire`: the one write path to the panel, shared by panel, beep and speech;
- `beep`: without the panel, a scan beeps through ALSA (aplay);
- `speech`: the panel speaks ("1042 grams. Hold yellow to save."): Piper (the voice from `voice`) or espeak-ng, cut
  to 8 kHz by ffmpeg, streamed to its speaker (else played on the beep output); STATION_SPEECH=0 turns it off;
- `air`: the panel's BME280 room air reading;
- `camera`: the webcam picture of a new spool for recognition (STATION_CAMERA: a /dev/video path, auto = the first
  USB camera, or off), kept until red or a new scan;
- `http`: the read-only handler; answers only STATION_ALLOW.
Runs as filament-kit-station.service (`python -m filament_kit.station`); nfcpy and pyserial come from the
`[station]` extra and are imported only inside the reader and panel loops.
"""
