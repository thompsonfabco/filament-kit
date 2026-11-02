# Intake station button panel

Optional front panel for the intake station: a Wemos D1 mini (ESP-12F) on the station PC's USB, a 3-wire passive
buzzer, two illuminated normally-open push buttons (**Hold** and **Discard**), a speaker that says what happened, and
a BME280 for room air. The D1 mini is a thin I/O board; `intake_station.py` owns all the logic (and makes the speech),
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
| BME280 SDA / SCL | D3 / D4 | 0 / 2 |
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
- Room air from the BME280 is in `/state` as `air` (`temp_c`, `rh`, `hpa`), read every 10 s; `rh` is null on a BMP280
  look-alike, and `air` is null when the reading is over a minute old.
- Without the panel, a scan beeps and phrases are spoken through the PC's audio output instead.
  `STATION_SPEECH=0` turns speech off and `STATION_BEEP=0` turns beeps off.

## Serial protocol (115200 baud, one line each)

| Direction | Line | Meaning |
|---|---|---|
| PC → panel | `?` | answer with HELLO |
| PC → panel | `L <hold> <discard>` | lamp modes: 0 off, 1 on, 2 flash, 3 three fast blinks then off |
| PC → panel | `B <hz> <ms> [count]` | beep(s) |
| PC → panel | `A <n>` + n raw bytes | speech, unsigned 8-bit mono at 8 kHz (n ≤ 1024): each byte is the speaker MOSFET's duty, 0 = off |
| panel → PC | `HELLO intake-panel <version>` | at boot and after `?` (version 2 has the speaker and BME280) |
| panel → PC | `P H` / `P D` | Hold / Discard pressed |
| panel → PC | `AIR <°C> <RH%\|-> <hPa>` | room air every 10 s |

The PC resends `L` every second; after 5 s without one (service stopped) the panel turns its lamps off.

**Speech.** The PC makes each phrase with espeak-ng, then ffmpeg band-limits it (250 Hz–3.5 kHz) and resamples it to
8 kHz. The PC peak-normalises it to duty 16–240 around 128 and adds a 150 ms ramp from 0 at each end, so C1 charges
and discharges without a thump. It streams the result in 256-byte `A` frames in real time, 0.25 s ahead, between the
lamp lines. A newer phrase cuts the current one off with a fade.

The panel keeps the samples in a ring buffer (1 s). A timer1 callback plays them into the ESP8266's sigma-delta output
on D8; it shares timer1 with `tone()`, so the buzzer still works. The sigma-delta clock is 80 MHz / 128, so pulses are
at least 1.6 µs, long enough for RU to swing the pair's bases. With the duty kept within 16–240, the lowest output
frequency is about 39 kHz, far above speech. If a stream stops without its ramp, the panel fades the speaker to off
over half a second.

The panel and the PN532 reader both use CH340 USB serial chips with no serial number, so their `ttyUSB` numbers can
swap between boots. The service finds the panel by its HELLO and gives nfcpy the other port (`NFC_DEVICE=auto`).

## Build, flash and test

PlatformIO on the desktop (`py -3 -m platformio`). Plug the D1 mini into the desktop, then:

```
cd <local path>\filament-ops\station\panel
py -3 -m platformio run -t upload
```

PlatformIO picks the COM port itself (add `--upload-port COMn` if there are several). Then move the board to the
station's USB and restart the service (`sudo systemctl restart intake-station`). The journal shows
`button panel on /dev/ttyUSBn`. `install_station.sh` installs espeak-ng and ffmpeg and gives the service the `video`
group for the webcam.

Offline tests (Linux / WSL):

- `panel/test/bme280_test.cpp`: the BME280 compensation against the datasheet example
  (`g++ -std=c++17 -I../src bme280_test.cpp -o /tmp/bme280_test && /tmp/bme280_test` in `panel/test`).
- `test_panel.py`: drives the PC side against a fake panel on a pty and a fake webcam (ffmpeg's test pattern). It
  covers lamps, beeps, speech framing and timing, the photo and AIR. Needs pyserial, espeak-ng and ffmpeg:
  `python3 -m venv /tmp/pt && /tmp/pt/bin/pip install pyserial`, then `/tmp/pt/bin/python -I test_panel.py .`.
