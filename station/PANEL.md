> In filament-kit the station is installed as the `station` module (`filament-kit modules`), runs as
> `filament-kit-station.service` from `filament_kit.station`, and this firmware lives in `station/panel/` of the
> filament-kit repo. Paths and service names below are from filament-ops.

# Intake station button panel

Front panel for the intake station: a Wemos D1 mini (ESP-12F) on the station PC's USB, with:

- two illuminated normally-open push buttons: **yellow** (Hold, advance) and **red** (Discard, cancel);
- a 128x64 I2C OLED;
- a 3-wire passive buzzer, and a speaker that says what happened;
- a BME280 (or BMP280 + AHT20) for room air.

The D1 mini is a thin I/O board. The station service (`filament_kit.station`) owns all the logic: it sends the screen
text and makes the speech, so behaviour changes never need a reflash. A USB webcam on the station PC photographs new
spools for recognition.

![wiring](panel/wiring.png)

## Wiring

| Part | D1 mini pin | ESP8266 GPIO |
|---|---|---|
| Hold (yellow) switch (either terminal; other to G) | D1 | 5 |
| Discard (red) switch (either terminal; other to G) | D2 | 4 |
| Hold (yellow) lamp: BS170 Q1 gate via 220 Ω, 100 kΩ gate to G | D5 | 14 |
| Discard (red) lamp: BS170 Q2 gate via 220 Ω, 100 kΩ gate to G | D6 | 12 |
| Buzzer S (signal) | D7 | 13 |
| Buzzer + / − | 3V3 / G | |
| Lamp + / lamp − | 5V / MOSFET drain (D); source (S) to G | |
| Speaker: BS170 Q3 gate via 220 Ω, 100 kΩ gate to G | D8 | 15 |
| BME280 (or BMP280 + AHT20) SDA / SCL | D3 / D4 | 0 / 2 |
| BME280 VIN / GND | 3V3 / G | |
| OLED SSD1306 128x64 (I2C 0x3C) SDA / SCL, on the same bus | D3 / D4 | 0 / 2 |
| OLED VCC / GND | 3V3 / G | |

**Speaker stage** (BS170 driving a push-pull pair, all from the parts drawer):

- Q3 BS170: source to G; drain to 5V through RU 1 kΩ. The drain node also goes to both transistor bases.
- Q4 KSC2073 (NPN): collector to 5V, emitter to the output node.
- Q5 KSA940 (PNP): emitter to the output node, collector to G.
- C1 470 µF electrolytic (10 V or more): + to the output node, − to the speakers.
- The two headset drivers in series, from C1 to G.

The pair follows the BS170's drain from about 0.7 V to 4.3 V, so the speakers get about 3.6 V p-p with almost no
current wasted, and C1 keeps DC out of them. The signal comes out inverted, which you can't hear. At idle the BS170 is
off, the output sits high and C1 just stays charged. Check the TO-220 pinouts (B C E) on your parts' datasheets.

**Boot pins.** D3 (GPIO0) and D4 (GPIO2) must be high at power-on, and the BME280 board's I2C pull-ups keep them high.
D8 (GPIO15) must be low, which RP3 and the D1 mini's own 10 kΩ keep it. A BME280 board without pull-ups would stop
the ESP8266 booting: add 4.7 kΩ from SDA and SCL to 3V3. TX/RX (GPIO1/3) carry the USB serial link to the PC, and D0
and A0 are still free.

The lamps (5 V type, resistor built in) are switched by BS170 N-MOSFETs because a GPIO pin gives 3.3 V at about 12 mA at
most; the 100 kΩ pull-downs keep them dark while the ESP8266 resets. BS170 legs, flat face toward you: D G S (the
look-alike 2N7000 is S G D).

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
- The station calls the kit server it was paired with (`sudo filament-kit station pair`, then restart the station):
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
| PC → panel | `A <n>` + n raw bytes | speech, unsigned 8-bit mono at 8 kHz (n ≤ 1024): each byte is the speaker MOSFET's duty, 0 = off |
| panel → PC | `HELLO intake-panel <version>` | at boot and after `?` (2: speaker and BME280; 3: PWM speaker; 4: AHT20; 5-6: whine-free PWM, 160 MHz; 7: OLED, long press; 8: "Waiting for PC" boot title) |
| panel → PC | `P H` | yellow pressed: sent on release, if held under 0.8 s |
| panel → PC | `L H` | yellow held 0.8 s (a long press; its release sends nothing) |
| panel → PC | `P D` | red pressed: sent at once |
| panel → PC | `AIR <°C> <RH%\|-> <hPa\|->` | room air every 10 s; `-` = that sensor isn't fitted |

The PC resends `L` every second, and `D` rows when they change. Until the first `L` since boot the title reads
"Waiting for PC" (firmware 8: the station may be about to reflash the panel, and an older firmware leaves the OLED as
it is). After 5 s without an `L` (service stopped), the panel turns its lamps off and the display shows
"Station offline" above the room air.

**Speech.** The PC makes each phrase with Piper, using its `en_US-libritts_r-medium` voice, speaker 0 (see the
third-party notices below). The voices the kit knows are one table in
`filament_kit/station/voice.py`, with their download address, pinned SHA-256 hashes and licence; the default voice is
one line at its top, and `station.voice` (or `STATION_PIPER_VOICE`, a model path) picks another. The service loads the voice once at start, which takes about a second, and then makes each phrase in about
0.1 s. Without Piper or its voice model, or with `station.tts` set to `espeak` (`STATION_TTS=espeak`), it uses
espeak-ng instead. ffmpeg then voices the phrase for a small headset driver in open air
(picked by ear in an A/B test): everything below 450 Hz is cut (the driver can't play it), 2.5 kHz is lifted 8 dB
for the consonants, the result is compressed hard, and it is resampled to 8 kHz. The PC normalises it to duty 16–240
around 128, letting the loudest 2 % of samples clip, and adds a 150 ms ramp from 0 at each end, so C1 charges and
discharges without a thump. It streams the result in 256-byte `A` frames in real time, 0.25 s ahead, between the
lamp lines. A newer phrase cuts the current one off with a fade.

The panel keeps the samples in a ring buffer (1 s). A timer1 callback plays them as 40 kHz PWM on D8, five PWM periods
per sample. It shares timer1 with `tone()`, so the buzzer still works. Every edge has to land on time, because any
regular timing error is audible:

- The callback asks for each interrupt 3 µs before its edge, then waits out the rest in a tight loop and sets the pin
  from the cycle counter. Edges under 8 µs away are waited out directly, since the core won't schedule interrupts
  closer than 4 µs. This works because interrupt entry time varies (for example when `loop()` is waiting on a flash
  read).
- The sample bookkeeping runs after an edge, in the longer half of the period. Doing it before the edge on every
  fifth period made an 8 kHz whine in firmware 3 and 4.
- The ESP8266 runs at 160 MHz (firmware 6), which halves interrupt overhead. That removed the last of the whine.

With the duty kept within 16–240, every pulse is at least 1.6 µs, long enough for RU to swing the pair's bases.
While silent, the callback runs only once a millisecond. If a stream stops without its ramp, the panel fades the
speaker to off over half a second.

**Louder.** If the speech is too quiet:

- Mount the driver sealed behind a hole in the enclosure (a baffle). Open-air headset drivers lose most of their
  output to the back wave.
- Use both drivers in parallel, and drop RU to 330 Ω. With 1 kΩ, the KSC2073's base current through RU clips the
  positive peaks into a 32 Ω or lower load.

The panel used the ESP8266's sigma-delta output up to version 2, but that was replaced. A first-order sigma-delta
slow enough for the push-pull pair repeats its pattern every 256 clocks, which at that clock speed is an audible
whine at about 2.4 kHz. PWM has one pulse per period at any duty, so the slow rising edge costs the same at every
level: a constant offset rather than distortion.

The panel and the PN532 reader both use CH340 USB serial chips with no serial number, so their `ttyUSB` numbers can
swap between boots. The service finds the panel by its HELLO and gives nfcpy the other port (`NFC_DEVICE=auto`).

## Build, flash and test

The station keeps the panel's firmware current itself. `panel/firmware/intake-panel.bin` and `panel/firmware/VERSION`
ship with the service, installed to `/opt/intake-station/panel/`. When the panel's HELLO reports a different version,
the service flashes the bundled build over USB with esptool, then finds the panel again. It tries once per bundled
version per run; if the flash doesn't take, it logs that and uses the panel as it is. `STATION_PANEL_FLASH=0` turns
this off. `/state` shows the running version as `panel_version`.

To ship a firmware change:

1. Edit `panel/src/`, and bump `VERSION` in `main.cpp`.
2. Run `sh panel/build.sh`. It builds with PlatformIO (`py -3 -m platformio`) and refreshes `panel/firmware/`.
3. Deploy with `sh install_station.sh intake-station`. The service restarts and reflashes the panel within seconds.
   The journal shows `flashing button panel on /dev/ttyUSBn with firmware N`, then
   `button panel on /dev/ttyUSBn (firmware N)`.

The first flash of a new board, or a board whose firmware won't answer, is done on the desktop. Plug it in and run
`py -3 -m platformio run -t upload` in `panel/` (add `--upload-port COMn` if there are several ports). Even a board
that won't boot can be reflashed this way, because the CH340 resets it into the ESP8266's ROM bootloader.
In filament-kit, `modules apply` (run by `install.sh`, and by `filament-kit modules enable station` when the station
module is switched on later) installs piper-tts (the `[station-tts]` extra) and the Piper voice wherever the station
module is on: into `/opt/filament-kit/resources/voice` (60-80 MB), from one pinned piper-voices commit and checked
against the pinned hashes, skipped when offline (run `sudo filament-kit modules apply` again later). A file that
doesn't match is a warning, never a failed install: espeak-ng speaks. Nothing is downloaded with `station.speech`
off, with `station.tts` set to `espeak` (`sudo filament-kit config`, then **7) Station voice**), or with
`FK_STATION_TTS=espeak`. It also installs espeak-ng and ffmpeg and gives the service the `video` group for the
webcam.

Offline tests (Linux / WSL):

- `panel/test/bme280_test.cpp`: the BME280 compensation against the datasheet example, and the AHT20 CRC and decoding
  (`g++ -std=c++17 -I../src bme280_test.cpp -o /tmp/bme280_test && /tmp/bme280_test` in `panel/test`).
- In filament-kit, `server/tests/test_station_flow_panel.py` drives the flow and the panel relay against a fake
  server and a recording serial port; `test_station_flow_e2e.py` runs the flow against the real kit API (TLS, fake
  Spoolman, fake Claude); `test_station_panel.py` covers speech framing and timing, the photo and AIR; and
  `test_station_voice.py` the Piper voice and its download.

## Third-party notices

**Speech voice.** Piper (piper-tts, GPL-3.0-or-later) speaks with `en_US-libritts_r-medium` from the Piper voices
repository (rhasspy/piper-voices). Its model card gives the dataset as LibriTTS-R (Koizumi et al., 2023,
http://www.openslr.org/141/), licensed CC BY 4.0. To use the public-domain `en_US-ljspeech-medium` voice (LJ Speech)
instead, set `station.voice` to it and run `install.sh` again, or point `STATION_PIPER_VOICE` at its model.

**Panel firmware.** It uses the U8g2 library by olikraus (BSD-2-Clause) and two of its fonts:

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
