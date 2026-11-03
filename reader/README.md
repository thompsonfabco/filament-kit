# filament-kit reader (ESP32-C3)

A small box next to the printer: tap a spool's NFC tag, pick the printer and slot with a knob, and the
filament-kit server links that spool to the slot (Spoolman location + the printer's filament setting). It
works with any printer and any AMS layout the server knows: the printer list and the slot list come from the
server, so a new printer or an added AMS unit needs no firmware change.

It started as the H2D-only reader of h2d-filament-scanner; this version has no hard-coded slots or URLs.

## Hardware

ESP32-C3 Super Mini, PN532 NFC board (I2C), SSD1306 128x64 OLED (I2C, same bus), KY-040 style rotary
encoder with push switch, 3-pin buzzer module.

| Part | Pin |
|---|---|
| I2C SDA / SCL (PN532 + OLED) | GPIO 5 / GPIO 6 |
| Encoder CLK / DT | GPIO 3 / GPIO 4 |
| Encoder switch | GPIO 1, switch to 3V3 (internal pull-down) |
| Buzzer I/O (active low) | GPIO 0 |
| PN532 IRQ / RST | leave unconnected |

Pins and polarities are in the CONFIG block at the top of `src/main.cpp`.

## Using it

- **Turn** the knob: next / previous slot. After a moment the reader says the slot ("a one", "h t b").
- **Tap** a tag: the reader sends it to the shown slot and shows, beeps and says the result.
- **Press**: send the last tag again to the shown slot (tapped the wrong slot? turn, then press).
- **Hold 1 s** (a tick tells you when), then let go: the printer list. Turn to a printer, press to pick it.
  Hold 1 s again, or leave it for 20 s, to close the list without changing printer.
- **Hold 4 s**: check for a firmware update and install it.

The top line shows the printer's name, the middle the slot label, the bottom what is in the slot. Long names
and labels scroll. The lists are read at power-on, every 60 s while the screen is lit, and 5 s after a set.
The screen dims after 2 minutes and turns off after 10; the first turn or press only wakes it.

The reader remembers the printer (by id) and the slot (by label) across power cuts and updates. If the AMS
layout changes, it keeps the slot as long as a slot with that label still exists; otherwise it starts at the
first slot.

| Result | Screen | Sound |
|---|---|---|
| `set` | what was set | two short beeps, "set" + slot |
| `queued` (slot is empty) | "Load into ..." for 15 s | short-long beep, "load" + slot |
| `unknown_tag`, `unknown_spool`, `archived_spool` | the server's message | one long beep |
| `no_preset`, `offline`, `error`, no reply | the server's message or "Server down" | three high beeps |

## Server API

The reader talks to the filament-kit web process. `READER_BASE` (in `src/secrets.h`) is the API's base URL,
for example `https://filament.example.net/filament/reader`. Every request carries the reader token in the
`X-Auth-Token` header (`filament-kit reader token` makes one). HTTPS, server certificate checked against the
pinned root (ISRG Root X1 unless `READER_ROOT_CA` is set). This contract is fixed; the server side is
`server/filament_kit/web/reader.py`.

`GET <READER_BASE>/printers` → `200`, a JSON list:

```json
[{"id": "h2d", "name": "H2D", "say": "h two d"}]
```

`GET <READER_BASE>/printers/<id>/slots` (id URL-encoded) → `200`, a JSON list in knob order:

```json
[{"label": "A1", "say": ["a", "1"], "kind": "ams", "present": true, "type": "PLA",
  "spool": {"id": 12, "name": "Polymaker Grey"}},
 {"label": "Ext-L", "say": ["external", "left"], "kind": "external", "present": null, "type": "", "spool": null}]
```

- `label` is required (entries without one are skipped) and must be unique per printer: it is what the reader
  saves and sends back. The kit server keeps to this within what the reader keeps: it never sends a label over
  40 bytes (that slot is left out, since a cut label would come back wrong), and never two slots of one printer
  whose labels are equal ignoring case (the kit matches labels whatever their case; only the first is listed).
- `say` is a list of tokens or one space-separated string; optional.
- `present`: `true`, `false` or `null`/missing (unknown). `type`: filament type the printer reports.
- `spool`: an object with `name` (or just `id`), a name string, an id number, or `null`.
- Other fields are ignored. At most 16 printers and 128 slots are kept.
- Size limits (the C3 has little RAM): a list reply over 20 KB (20480 bytes) is refused and the last good list
  stays; `label`, `name`, `say`, `type` and the spool name are cut to 40 bytes; a printer `id` longer than 64
  bytes is skipped (ids are never cut, they go back in URLs).
- The reader re-selects the saved printer id and slot label after every refresh, so a unit that is missing from
  one reply only moves the selection until it is back. If the slots of a newly picked printer cannot be read, the
  reader shows "No slots" and refuses scans rather than keep the old printer's slots.

`POST <READER_BASE>/scan` with `{"uid": "4:c7:96:11:9:22:89", "printer": "h2d", "slot": "A1", "dry_run": false}`
→ a JSON object `{"status": ..., "message": ..., "filament": ...}`:

- `status` is one of `set | queued | unknown_tag | unknown_spool | archived_spool | no_preset | offline | error`.
  `set` and `queued` count only with a 2xx code; the others are read from any reply. Anything else is an error.
- `message` (optional) is shown on the screen; `filament` (optional) is shown after `set` / `queued`.
- `uid` is lowercase hex, no leading zeros, colon separated (the nfc2klipper / Spoolman `extra.nfc_id` form).
- `printer` is the id from the printer list, always sent as a string (a numeric id `7` comes back as `"7"`);
  `slot` is the slot's `label`.

`GET <READER_BASE>/healthz` → `200` when the server is up. A freshly installed update keeps itself only if this
answers; otherwise the reader rolls back to the previous firmware on the next reset.

`GET <READER_BASE>/fw/manifest.json` and `GET <READER_BASE>/fw/firmware.bin`: the OTA files written by
`tools/ota_publish.py`, served behind the same token (the image contains the Wi-Fi password and the token).

### Speech tokens

`say` tokens are matched case-insensitively against the vocabulary the reader has: the letters `a`-`z`, numbers
`0`-`99` (as digits or as words such as `two`, `sixteen`), `external`/`ext` (spelled "E X T"), `left`, `right`,
`top`, `bottom`, `middle`, `center`, `front`, `back`, `set`, `load`, `ready`, `printer`, `unit`, `number`, `plus`,
`light`, `high`, `low`, `up`, `down`, `on`, `off`, `and`, `error` and a few colours. A token it does not have
becomes a short beep, so new labels only need a `say` text on the server (the table is in `lib/reader_core/src/speech.cpp`).

## Build

Needs [PlatformIO](https://platformio.org/) (`pip install platformio`). `platformio.ini` pins the pioarduino
platform (Arduino core 3.1.3) and exact library versions. The platform zip,
`https://github.com/pioarduino/platform-espressif32/releases/download/53.03.13/platform-espressif32.zip`, has
SHA-256 `e42240daaba9d4dfb9cec7ec702b6c84a0605d34c7f03e1ad342bbee74fc1db8` (1,472,729 bytes, checked 2026-11-03).

1. `cp src/secrets.example.h src/secrets.h` and fill in Wi-Fi, `READER_BASE`, `READER_TOKEN` and `OTA_PUBKEY`
   (see below). `secrets.h` is ignored by git; never commit it.
2. `pio run -e esp32-c3-supermini` builds; `pio run -e esp32-c3-supermini -t upload` flashes over USB (the first
   time only; updates go over Wi-Fi).

Tests: `pio test -e native` runs the host unit tests of `lib/reader_core` (list parsing, scan statuses, speech
tokens, knob and menu, saved choice, scrolling). Needs a host C++ compiler (on Windows, run it in WSL).
`pytest reader/tools` tests the publish tool. CI (`.github/workflows/reader.yml`) runs both and builds the
firmware with the example secrets.

## Updates over Wi-Fi (OTA)

1. Once: `py tools/ota_publish.py --init-key` creates the signing key (`~/.filament-kit/reader-ota-key.pem`,
   keep it on that PC) and prints the public key. Paste it into `src/secrets.h` as `OTA_PUBKEY` and flash once
   over USB. Until then the reader refuses every update ("bad signature").
2. Each release: `py tools/ota_publish.py --host <ssh host of the server>` builds with a fresh build number,
   signs, copies `firmware.bin` + `manifest.json` into `--remote-dir` (default `/var/lib/filament-kit/reader-fw`,
   group `filament-kit`, mode 0640) and checks that `<READER_BASE>/fw/manifest.json` shows the new build.
   `--dry-run` builds and signs only. `--help` lists the rest.
3. Hold the knob 4 s. The reader checks the manifest, downloads into the spare slot while hashing, verifies
   size, SHA-256 and the ECDSA signature, installs and restarts. "UPD" on the top line means a newer build is
   waiting (checked at power-on and daily).

## Moving from the H2D-only reader

One USB flash. In `src/secrets.h`: keep `WIFI_SSID`/`WIFI_PASS`, replace `AUTH_TOKEN` by `READER_TOKEN` (a new
token from `filament-kit reader token`), add `READER_BASE`, and set `OTA_PUBKEY` (the old public key from the old
`main.cpp` still works with the old signing key: pass `--key` with its path). The saved slot index of the old
firmware is dropped; the reader starts on the first slot of the first printer once.

## License

GPL-3.0, like the rest of filament-kit. The firmware links TalkiePCM (GPL-3.0) for speech.
