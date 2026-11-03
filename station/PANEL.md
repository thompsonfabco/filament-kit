> In filament-kit the station is installed as the `station` module (`filament-kit modules`), runs as
> `filament-kit-station.service` from `filament_kit.station`, and this firmware lives in `station/panel/` of the
> filament-kit repo. Paths and service names below are from filament-ops.

# Intake station button panel

Optional front panel for the intake station: a Wemos D1 mini (ESP-12F) on the station PC's USB, a 3-wire passive
buzzer, two illuminated normally-open push buttons (**Hold** and **Discard**), a speaker that says what happened, and
a BME280 (or BMP280 + AHT20) for room air. The D1 mini is a thin I/O board; `intake_station.py` owns all the logic (and makes the speech),
so behaviour changes never need a reflash. A USB webcam on the station PC takes a picture of the pan at each Hold.

![wiring](panel/wiring.png)

## Wiring

| Part | D1 mini pin | ESP8266 GPIO |
|---|---|---|
| Hold switch (either terminal; other to G) | D1 | 5 |
| Discard switch (either terminal; other to G) | D2 | 4 |
| Hold lamp: BS170 Q1 gate via 220 Ω, 100 kΩ gate to G | D5 | 14 |
| Discard lamp: BS170 Q2 gate via 220 Ω, 100 kΩ gate to G | D6 | 12 |
| Buzzer S (signal) | D7 | 13 |
| Buzzer + / − | 3V3 / G | |
| Lamp + / lamp − | 5V / MOSFET drain (D); source (S) to G | |
| Speaker: BS170 Q3 gate via 220 Ω, 100 kΩ gate to G | D8 | 15 |
| BME280 (or BMP280 + AHT20) SDA / SCL | D3 / D4 | 0 / 2 |
| BME280 VIN / GND | 3V3 / G | |

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

## Behaviour

| Event | Hold lamp | Discard lamp | Buzzer | Speaker |
|---|---|---|---|---|
| Idle | off | off | | |
| Tag scanned | on | on | one high beep | |
| A stable weight on the scale (no scan) | off | on | | |
| Hold pressed, scan + weight there | flashing | on | two short high beeps | "Held, 1042 grams" (+ webcam picture) |
| Hold pressed again | on (or off once the scan is over 5 min old) | on | one mid beep | "Released" |
| Hold pressed with no scan | unchanged | unchanged | one low buzz | "Scan a tag first" |
| Hold pressed with a scan but no weight | unchanged | unchanged | one low buzz | "Put the spool on the scale" |
| Discard pressed | off | three fast blinks, then off | one low beep | "Discarded" |
| Discard pressed with nothing there | unchanged | unchanged | one low buzz | "Nothing to discard" |

- A held weight keeps its scan current for the phone app until Discard or the next scan; without Hold, a scan and
  a weight count for 5 minutes (`STATION_ACTIVE`, matching the VM's `TAG_FRESH`). `/state` marks held entries
  with `"held": true`, and the VM's intake app accepts them at any age.
- After Discard, a spool still on the scale is ignored until the pan is emptied (or the scale switches itself off),
  so the Discard lamp doesn't come straight back on.
- A new scan replaces the old one and drops any held weight and picture.
- The webcam picture (`/photo`, listed in `/state` as `photo`) is taken a moment after Hold, so the camera has set its
  exposure. It lasts as long as the hold does. `STATION_CAMERA` is a `/dev/video*` path, `auto` (the first USB camera)
  or `off`.
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
| PC → panel | `L <hold> <discard>` | lamp modes: 0 off, 1 on, 2 flash, 3 three fast blinks then off |
| PC → panel | `B <hz> <ms> [count]` | beep(s) |
| PC → panel | `A <n>` + n raw bytes | speech, unsigned 8-bit mono at 8 kHz (n ≤ 1024): each byte is the speaker MOSFET's duty, 0 = off |
| panel → PC | `HELLO intake-panel <version>` | at boot and after `?` (2: speaker and BME280; 3: PWM speaker; 4: AHT20; 5-6: whine-free PWM, 160 MHz) |
| panel → PC | `P H` / `P D` | Hold / Discard pressed |
| panel → PC | `AIR <°C> <RH%\|-> <hPa\|->` | room air every 10 s; `-` = that sensor isn't fitted |

The PC resends `L` every second; after 5 s without one (service stopped) the panel turns its lamps off.

**Speech.** The PC makes each phrase with espeak-ng. ffmpeg then voices it for a small headset driver in open air
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
`install_station.sh` also installs espeak-ng and ffmpeg, esptool in the venv, and gives the service the `video` group
for the webcam.

Offline tests (Linux / WSL):

- `panel/test/bme280_test.cpp`: the BME280 compensation against the datasheet example, and the AHT20 CRC and decoding
  (`g++ -std=c++17 -I../src bme280_test.cpp -o /tmp/bme280_test && /tmp/bme280_test` in `panel/test`).
- `test_panel.py`: drives the PC side against a fake panel on a pty and a fake webcam (ffmpeg's test pattern). It
  covers lamps, beeps, speech framing and timing, the photo and AIR. Needs pyserial, espeak-ng and ffmpeg:
  `python3 -m venv /tmp/pt && /tmp/pt/bin/pip install pyserial`, then `/tmp/pt/bin/python -I test_panel.py .`.
