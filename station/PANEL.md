# Intake station button panel

Front panel for the intake station: an ESP32-C3 Super Mini on the station PC's USB (native USB serial), with:

- two illuminated normally-open push buttons: **yellow** (Hold, advance) and **red** (Discard, cancel);
- a 128x64 I2C OLED;
- a 3-wire passive buzzer, and a speaker on a MAX98357 amplifier module that says what happened;
- a BME280 (or BMP280 + AHT20) for room air.

The C3 is a thin I/O board. The station service (`filament_kit.station`) owns all the logic: it sends the screen
text and makes the speech, so behaviour changes never need a reflash. A USB webcam on the station PC photographs new
spools for recognition. The station is installed as the `station` module (`filament-kit modules`) and runs as
`filament-kit-station.service`.

Panels built on a Wemos D1 mini (ESP8266, firmware 9 and older) still work: the station uses them as they are but
never reflashes them. Everything below describes firmware 11 on the C3.

## Wiring and parts

The parts list, pin table, wiring, board, enclosure and bench checks for the panel are in the
[intake-panel guide](https://github.com/thompsonfabco/filament-kit-hardware/tree/main/devices/intake-panel) of the
[filament-kit-hardware](https://github.com/thompsonfabco/filament-kit-hardware) repository. What the station software does with the hardware stays here:

- **NFC reader (optional, firmware 11).** A PN532 in I2C mode (address 0x24) on the panel is looked for at boot and
  every 5 s after, so it can be plugged in later. The USB PN532 reader keeps working, alone or together with
  this one; the same tag seen by both within 2 s is one tap, and a quick second tap of the same tag on the same
  reader inside that 2 s is merged too.

**Wired the other way round?** If yellow's button and lamp ended up on the red pins (GPIO 4 and 7) and red's on the
yellow pins (GPIO 3 and 1), set `"panel_swap": true` under `"station"` in the kit config (`STATION_PANEL_SWAP=1`)
instead of rewiring or reflashing. The station then swaps the buttons' roles and the lamp modes. This needs firmware 9
or later, where both buttons report short and long presses alike.

**Speaker volume.** `station.speaker_volume` in the kit config (0-100, default 50; `STATION_SPEAKER_VOLUME`) sets how
loud the panel speaks. The station sends it to the panel once after it finds a C3 panel. Changing the setting
rewrites the station's drop-in, which restarts the station, so the new volume is sent then. If speech is too quiet,
raise `station.speaker_volume`, and mount the speaker sealed in the enclosure with its sound path open to the front.

## Behaviour: the intake flow (the owner's spec, 2026-11-06)

Red cancels at any step. Yellow advances: a short press does the step's job, and a long press (0.8 s) saves.

| Step | What you do next | Yellow lamp | Red lamp | Display |
|---|---|---|---|---|
| idle | scan a spool's tag | off | off | "Ready" |
| lookup (the server checks the tag) | wait | rapid blink | on | "Tag scanned" |
| camera (a new tag) | show the spool to the camera, press yellow | blinking | on | "New Tag Scanned" |
| recognising | wait | rapid blink | on | "Recognising..." |
| weigh (a recognised or linked spool) | spool on the scale, let it settle, press yellow | blinking | on | the spool and its colour |
| ready (weight taken) | hold yellow to save (or press it again to re-weigh) | on | on | "1042 g", the spool, its colour |
| saving | wait | rapid blink | on | "Saving..." |
| done | nothing: back to idle after 10 s | three blinks | off | "Saved" and the server's text |
| phone (the server or its AI can't help) | use the phone app; red starts over | off | on | "Use phone" and why |

- A linked tag (already on a spool in Spoolman) skips the camera, from lookup straight to weigh.
- Recognition is the kit server's job: the local AI module first, then Claude (`ai_intake`). With neither, the panel
  says "use phone". With no match it goes back to the camera step with "No match", so you can try again.
- Weighing needs a settled reading (the scale says stable, over 20 g). Otherwise the display says
  "Scale not settled".
- Any step except idle goes back to idle after 10 minutes with no progress (`STATION_FLOW_TIMEOUT`, seconds). A
  recognition waits up to 90 s (`STATION_RECOGNISE_TIMEOUT`).
- A new scan restarts the flow from any step. A server answer that comes back after red or a new scan is dropped.
- The buzzer beeps on a scan, on each step done (two high), on cancel (one low), and on a refused press (low buzz).
  The speaker says what to do next.
- `/state` gains `flow` (`step`, `message`, `spool`, `filament`). Its `last_weight` is the taken weight with
  `"held": true` at the ready step, so the phone app keeps working.
- The camera picture is at `/photo` (listed in `/state` as `photo`). `STATION_CAMERA` is a `/dev/video*` path,
  `auto` (the first USB camera) or `off`.
- The display's bottom line is the panel's own: room air, always shown, even with the station offline.
- The station calls the kit server it was paired with (`sudo filament-kit station pair`, which restarts the station itself when it needs to):
  by IP, over TLS with the server's certificate pinned, with the pairing token. Every answer can carry `display`, a
  list of OLED lines (a 16-character title and two 21-character lines; rows 3-4 are the station's own).

  | Call | Answers |
  |---|---|
  | `GET /api/station/tag/{uid}` | `known`, with the `spool` if it is linked |
  | `POST /api/station/recognize` (multipart: `image`, `uid`) | 200 with `item` (the label read); 409 when there's no recognizer (use the phone) |
  | `POST /api/station/save` with `{uid, gross_g, spool_id or filament}` | 200 with `spool_id` and `created`; 409 with the reason |

  `filament` is recognize's `item`, passed back unchanged (the server also takes it as `item`).
- Room air is in `/state` as `air` (`temp_c`, `rh`, `hpa`), read every 10 s, and `air` is null once the reading is
  over a minute old. The sensor can be a BME280, or a BMP280 + AHT20 combination board like the one fitted here: the
  BMP280 gives temperature and pressure and the AHT20 (I2C 0x38) gives humidity. A sensor that isn't there reads
  null: `rh` on a lone BMP280, `hpa` on a lone AHT20.
- Without the panel, a scan beeps and phrases are spoken through the PC's audio output instead.
  `STATION_SPEECH=0` turns speech off and `STATION_BEEP=0` turns beeps off.

## Serial protocol (115200 baud, one line each)

| Direction | Line | Meaning |
|---|---|---|
| PC → panel | `?` | answer with HELLO |
| PC → panel | `L <hold> <discard>` | lamp modes: 0 off, 1 on, 2 flash, 3 three fast blinks then off, 4 rapid blink |
| PC → panel | `D <row> [text]` | display text: row 0 the title (big, ~16 characters), rows 1-4 the body (21 characters); no text clears the row |
| PC → panel | `B <hz> <ms> [count]` | beep(s) |
| PC → panel | `V <percent>` | speech volume, 0-100 (firmware 10; the station sends it once after finding a C3 panel, and a changed `station.speaker_volume` restarts the station, so it is sent again then) |
| PC → panel | `A <n>` + n raw bytes | speech, unsigned 8-bit mono at 8 kHz (n ≤ 1024): each byte is one sample, 128 is silence (on firmware 9 and older it is the speaker MOSFET's duty, 0 = off) |
| panel → PC | `HELLO intake-panel <version> [<chip>]` | at boot and after `?`; firmware 11 answers `HELLO intake-panel 11 esp32c3`, and the chip token is missing on firmware 9 and older, which are ESP8266 (2: speaker and BME280; 3: PWM speaker; 4: AHT20; 5-6: whine-free PWM, 160 MHz; 7: OLED, long press; 8: "Waiting for PC" boot title; 9: long press on both buttons; 10: ESP32-C3, I2S speech, V volume, chip token; 11: PN532 on I2C, TAG and NFC lines) |
| panel → PC | `P H` / `P D` | the yellow / red button pressed: sent on release, if held under 0.8 s |
| panel → PC | `L H` / `L D` | the yellow / red button held 0.8 s (a long press; its release sends nothing). A long press on red cancels, like a short one. With station.panel_swap (`STATION_PANEL_SWAP=1`), H is red and D is yellow, and the `L` lamp modes go out swapped. |
| panel → PC | `AIR <°C> <RH%\|-> <hPa\|->` | room air every 10 s; `-` = that sensor isn't fitted |
| panel → PC | `TAG <hex>` | firmware 11: a tag read by the panel's PN532, its UID in lowercase hex, sent once per presentation (again only after no tag was seen for 1 s, or for a different tag). The station formats it like the USB reader's tags. |
| panel → PC | `NFC ok` / `NFC none` | firmware 11: whether a PN532 answers on the I2C bus; sent after every HELLO and when that changes. `curl http://127.0.0.1:5003/state` shows it as `"panel_nfc"`. |

The PC resends `L` every second, and `D` rows when they change. Until the first `L` since boot the title reads
"Waiting for PC" (firmware 8: the station may be about to reflash the panel, and an older firmware leaves the OLED as
it is). After 5 s without an `L` (service stopped), the panel turns its lamps off and the display shows
"Station offline" above the room air.

**Speech.** The PC makes each phrase with Piper, using its `en_US-libritts_r-medium` voice, speaker 0 (see the
third-party notices below). The voices the kit knows are one table in
`filament_kit/station/voice.py`, with their download address, pinned SHA-256 hashes and licence; the default voice is
one line at its top, and `station.voice` (or `STATION_PIPER_VOICE`, a model path) picks another. The service loads the voice once at start, which takes about a second, and then makes each phrase in about
0.1 s. Without Piper or its voice model, or with `station.tts` set to `espeak` (`STATION_TTS=espeak`), it uses
espeak-ng instead. For a C3 panel, ffmpeg then filters the phrase with a high-pass at 150 Hz, a low-pass at 3.6 kHz
and light compression, and resamples it to 8 kHz unsigned 8-bit. The PC streams the result in 256-byte `A` frames in
real time, 0.25 s ahead, between the lamp lines. A newer phrase cuts the current one off with a fade.

The C3 plays the bytes over I2S to the MAX98357. Each byte is a sample with 128 as silence; the panel converts it to
signed 16-bit, applies the volume from the `V` line, and writes it to both channels. The samples wait in a ring buffer
(1 s). When the stream runs dry, the panel fades to silence over 50 ms instead of holding the last sample, so there is
no click. Wi-Fi and Bluetooth are never started on the panel.

For an older ESP8266 panel the station keeps its original speech path: a headset driver in open air, so everything
below 450 Hz is cut, 2.5 kHz is lifted 8 dB and the result is compressed hard. The bytes are a PWM duty (16-240
around 128, 0 = off) with a 150 ms ramp from 0 at each end, and the panel fades to off over half a second if a stream
stops without its ramp. The `V` line and `station.speaker_volume` do not apply to those panels.

**Finding the panel.** The station looks at `ttyACM` ports whose USB vendor ID is `303a` (the C3's native USB), then
at `ttyUSB` ports (older panels on a CH340), and takes the first that answers HELLO. It gives the panel's serial port
a 1 s write timeout, so a stalled panel can't hang the service. An old CH340 panel and the PN532 reader both have no
USB serial number, so their `ttyUSB` numbers can swap between boots. The service finds the panel by its HELLO and
gives nfcpy the other port (`NFC_DEVICE=auto`).

## Build, flash and test

Paths here are relative to `station/` in this repo.

The station keeps a C3 panel's firmware current itself. `panel/firmware/intake-panel.bin` (a merged image written at
address 0) and `panel/firmware/VERSION` ship in each release and are installed to `/opt/filament-kit/resources/panel/`.
When a C3 panel's HELLO reports a different version, the service flashes the bundled build over USB with esptool,
then finds the panel again. That includes going back to an older version after a rollback. It tries once per bundled
version per run; if the flash doesn't take, it logs that and uses the panel as it is. `station.panel_flash` set to
false (`STATION_PANEL_FLASH=0`) turns this off. `/state` shows the running version as `panel_version`. A panel whose
HELLO has no chip token is an ESP8266 on firmware 9 or older: the station logs it as old firmware, uses it, and never
flashes it.

**First flash of a blank C3 board.** A new board has no firmware, so it can't answer HELLO. Plug it into the station
PC and run:

```
sudo filament-kit station flash-panel
```

It stops the station, lists the C3 ports that give no HELLO, and asks before flashing each one. After each flash it
checks for HELLO, then it restarts the station. A board that already answers is left alone.

To ship a firmware change:

1. Edit `panel/src/`, and bump `VERSION` in `main.cpp`.
2. Run `sh panel/build.sh`. It builds the `esp32-c3-supermini` PlatformIO environment and writes the merged image
   (bootloader, partition table and application at 0x0) as `panel/firmware/intake-panel.bin`. It needs esptool 5.6.0;
   see the header of `build.sh`.
3. Commit the source and the refreshed `panel/firmware/` together; a release carries them. After
   `sudo filament-kit update` on the station, the service restarts and reflashes the panel within seconds. The journal
   shows `flashing button panel on /dev/ttyACMn with firmware N`, then `button panel on /dev/ttyACMn (firmware N)`.

`modules apply` (run by `install.sh`, and by `filament-kit modules enable station` when the station module is switched
on later) installs piper-tts (the `[station-tts]` extra) and the Piper voice wherever the station module is on: into
`/opt/filament-kit/resources/voice` (60-80 MB), from one pinned piper-voices commit and checked against the pinned
hashes, skipped when offline (run `sudo filament-kit modules apply` again later). A file that doesn't match is a
warning, never a failed install: espeak-ng speaks. Nothing is downloaded with `station.speech` off, with `station.tts`
set to `espeak` (`sudo filament-kit config`, then **7) Station voice**), or with `FK_STATION_TTS=espeak`. It also
installs espeak-ng and ffmpeg and gives the service the `video` group for the webcam.

Offline tests (Linux / WSL):

- `panel/test/test_core/test_main.cpp`: the panel_core logic (line parser, lamp and button timing, speech conversion and volume), the BME280
  compensation against the datasheet example, and the AHT20 CRC and decoding (`pio test -d station/panel -e native`).
- `server/tests/test_station_flow_panel.py` drives the flow and the panel relay against a fake
  server and a recording serial port; `test_station_flow_e2e.py` runs the flow against the real kit API (TLS, fake
  Spoolman, fake Claude); `test_station_panel.py` covers speech framing and timing, the photo and AIR; and
  `test_station_voice.py` the Piper voice and its download.

## Third-party notices

**Speech voice.** Piper (piper-tts, GPL-3.0-or-later) speaks with `en_US-libritts_r-medium` from the Piper voices
repository (rhasspy/piper-voices). Its model card gives the dataset as LibriTTS-R (Koizumi et al., 2023,
http://www.openslr.org/141/), licensed CC BY 4.0. To use the public-domain `en_US-ljspeech-medium` voice (LJ Speech)
instead, set `station.voice` to it and run `install.sh` again, or point `STATION_PIPER_VOICE` at its model.

**Panel firmware.** It is built with the ESP32 Arduino core (LGPL-2.1) and uses the U8g2 library by olikraus (BSD-2-Clause) and two of its fonts:

- `u8g2_font_6x10_tf` (body text and the air line): X11 Misc-Fixed 6x10, "Public domain terminal emulator font".
- `u8g2_font_helvB10_tf` (titles): derived from the X11 font HELVB10.BDF. Its licence asks for this notice:

  > Copyright 1984-1989, 1994 Adobe Systems Incorporated.
  > Copyright 1988, 1994 Digital Equipment Corporation.
  >
  > Adobe is a trademark of Adobe Systems Incorporated which may be registered in certain jurisdictions. Permission to
  > use these trademarks is hereby granted only in association with the images described in this file.
  >
  > Permission to use, copy, modify, distribute and sell this software and its documentation for any purpose and
  > without fee is hereby granted, provided that the above copyright notices appear in all copies and that both those
  > copyright notices and this permission notice appear in supporting documentation, and that the names of Adobe
  > Systems and Digital Equipment Corporation not be used in advertising or publicity pertaining to distribution of
  > the software without specific, written prior permission. Adobe Systems and Digital Equipment Corporation make no
  > representations about the suitability of this software for any purpose. It is provided "as is" without express or
  > implied warranty.
