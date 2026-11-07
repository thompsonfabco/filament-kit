// Intake station button panel (Wemos D1 mini / ESP-12F). Thin I/O for intake_station.py over USB serial.
//
// Serial 115200, one ASCII line per message:
//   PC -> panel   "?"                     -> "HELLO intake-panel <version>"
//                 "L <hold> <discard>"    lamp modes: 0 off, 1 on, 2 flash, 3 three fast blinks then off,
//                                         4 rapid blink (3 only restarts the blinks when the mode changes to it)
//                 "D <row> [text]"        OLED text: row 0 the title (big), rows 1-4 the body; no text clears the
//                                         row. The bottom line is the panel's own: room air, always shown.
//                 "B <hz> <ms> [count]"   beep(s) on the passive buzzer, 60 ms apart
//                 "A <n>" + n raw bytes   speech for the speaker: unsigned 8-bit mono at 8 kHz (n 1-1024), each byte
//                                         the speaker MOSFET's PWM duty (/256), 0 = off. The PC streams it in real time and
//                                         ramps up from 0 and back down so the speaker doesn't click.
//   panel -> PC   "HELLO intake-panel <version>"   at boot and in answer to "?"
//                 "P H"                   Hold (yellow) pressed: sent on release, if held under LONG_MS
//                 "L H"                   Hold held down for LONG_MS (then its release sends nothing)
//                 "P D"                   Discard (red) pressed: sent at once (debounced, once per press)
//                 "AIR <C> <RH%|-> <hPa|->" room air every 10 s: a BME280, or a BMP280 + AHT20 board ("-": no such
//                                         sensor, e.g. RH on a lone BMP280)
// The PC resends "L" every second; with no "L" for 5 s (station service stopped) the lamps go dark and the display
// says the station is offline. The OLED (SSD1306 128x64, I2C 0x3C) shares the bus with the air sensor.
//
// Pins avoid the USB serial pins (GPIO1 TX, GPIO3 RX). Boot straps: GPIO0/D3 and GPIO2/D4 must be high at power-on,
// which the BME280 board's I2C pull-ups keep them; GPIO15/D8 must be low, which the speaker MOSFET's gate pull-down
// (and the D1 mini's own 10 kΩ) keep it.
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <Wire.h>
#include <core_esp8266_waveform.h>
#include <U8g2lib.h>
#include "aht20.h"
#include "bme280.h"

static const char *VERSION = "7";
static const uint8_t PIN_BUZZER = D7;       // GPIO13: buzzer module signal
static const uint8_t PIN_BTN_HOLD = D1;     // GPIO5:  Hold button to GND (internal pull-up)
static const uint8_t PIN_BTN_DISCARD = D2;  // GPIO4:  Discard button to GND
static const uint8_t PIN_LAMP_HOLD = D5;    // GPIO14: Hold lamp MOSFET gate (high = lit)
static const uint8_t PIN_LAMP_DISCARD = D6; // GPIO12: Discard lamp MOSFET gate
static const uint8_t PIN_SPEAKER = D8;      // GPIO15: speaker MOSFET gate (40 kHz PWM); its drain drives the
                                            // push-pull pair's bases, so the speaker signal comes out inverted
static const uint8_t PIN_SDA = D3;          // GPIO0:  I2C SDA (air sensor, OLED)
static const uint8_t PIN_SCL = D4;          // GPIO2:  I2C SCL

static const uint32_t FLASH_MS = 250;      // flash: 2 Hz
static const uint32_t RAPID_MS = 60;       // rapid blink: about 8 Hz
static const uint32_t BLINK3_MS = 90;      // three fast blinks: 90 ms on / 90 ms off
static const uint32_t DEBOUNCE_MS = 30;
static const uint32_t LONG_MS = 800;       // Hold held this long: a long press
static const uint32_t WATCHDOG_MS = 5000;
static const uint32_t AIR_MS = 10000;      // a forced-mode reading every 10 s: the sensor barely warms itself
static const uint32_t SAMPLE_RATE = 8000;

struct Lamp {
  uint8_t pin, mode = 0;
  uint32_t since = 0;
  void set(uint8_t m) {
    if (m > 4) return;
    if (m != mode) { mode = m; since = millis(); }
  }
  void update(uint32_t now) {
    bool lit = false;
    uint32_t t = now - since;
    switch (mode) {
      case 1: lit = true; break;
      case 2: lit = (t / FLASH_MS) % 2 == 0; break;
      case 3: lit = t < 6 * BLINK3_MS && (t / BLINK3_MS) % 2 == 0; break;
      case 4: lit = (t / RAPID_MS) % 2 == 0; break;
    }
    digitalWrite(pin, lit ? HIGH : LOW);
  }
};

struct Button {
  uint8_t pin; char code; bool longPress;  // longPress: "P" on a short press's release, "L" once held LONG_MS
  bool down = false, fired = false; uint32_t changed = 0, pressedAt = 0;
  void send(char kind) { Serial.print(kind); Serial.print(' '); Serial.println(code); }
  void poll(uint32_t now) {
    bool pressed = digitalRead(pin) == LOW;
    if (pressed != down) {
      if (now - changed < DEBOUNCE_MS) return;
      down = pressed; changed = now;
      if (down) {
        pressedAt = now; fired = false;
        if (!longPress) send('P');
      } else if (longPress && !fired) {
        send('P');
      }
      return;
    }
    changed = now;
    if (down && longPress && !fired && now - pressedAt >= LONG_MS) { fired = true; send('L'); }
  }
};

// ---------- speaker: samples from the PC through a ring buffer, played as 40 kHz PWM by a timer1 callback ----------
// PWM, not the ESP8266's sigma-delta: a first-order sigma-delta slow enough for the push-pull pair (1 kOhm base
// pull-up) repeats its pattern every 256 clocks, an audible whine in the speech band. PWM has one pulse per period at
// any duty, so the slow rising edge costs the same at every level (an offset, no distortion).
static const uint32_t RING = 8192;  // 1 s of audio; the PC keeps about 0.25 s queued
static uint8_t ring[RING];
static volatile uint32_t ringHead = 0, ringTail = 0;  // head: written by loop(), tail: by the timer callback
static const uint32_t PWM_PERIOD = F_CPU / 40000;    // 40 kHz carrier: inaudible, 5 periods per 8 kHz sample
static const uint32_t SPIN = F_CPU / 1000000 * 8;    // edges nearer than 8 us: wait them out here (the core won't
                                                     // schedule timer interrupts closer than 4 us)
static const uint32_t EARLY = F_CPU / 1000000 * 3;   // ask for the interrupt 3 us before an edge and wait out the
                                                     // rest: entry latency varies (e.g. loop() on a flash cache miss)
static const uint32_t SPK_BIT = 1u << 15;            // PIN_SPEAKER = GPIO15
static const uint32_t SUBS = F_CPU / PWM_PERIOD / SAMPLE_RATE;  // PWM periods per sample
static uint32_t nextEdge = 0, periodStart = 0, idleSamples = 0;
static uint8_t level = 0, sub = 0;
static bool spkHigh = false, ticked = false;

static inline __attribute__((always_inline)) void sampleTick() {
  // Once per PWM period, after that period's edge is set: a sample lasts SUBS periods (taken at once while silent).
  if (++sub < SUBS && level) return;
  sub = 0;
  if (ringTail != ringHead) {
    level = ring[ringTail];
    ringTail = (ringTail + 1) % RING;
    idleSamples = 0;
  } else if (++idleSamples > SAMPLE_RATE / 2 && level && (idleSamples & 15) == 0) {
    level--;  // stream stopped without its ramp down: fade to off over up to 0.5 s so the coupling cap doesn't thump
  }           // a short gap holds the last sample
}

static uint32_t IRAM_ATTR audioTick() {
  // Called on every timer1 interrupt (tone() shares the timer), so it keeps its own time on the cycle counter.
  // Each edge is set straight after its wait, and the sample bookkeeping runs in the longer half of the period:
  // work done before an edge on only some periods (every 5th, at each new sample) would make an 8 kHz whine.
  for (;;) {
    int32_t wait = (int32_t)(nextEdge - ESP.getCycleCount());
    if (wait > (int32_t)SPIN) return wait - EARLY;
    while ((int32_t)(nextEdge - ESP.getCycleCount()) > 0) {}  // exact edge
    if (spkHigh) {  // end of the pulse
      GPOC = SPK_BIT; spkHigh = false;
      if (!ticked) sampleTick();
      nextEdge = periodStart + PWM_PERIOD;
      continue;
    }
    periodStart = nextEdge;  // start of a period
    if ((int32_t)(ESP.getCycleCount() - periodStart) > (int32_t)PWM_PERIOD) periodStart = ESP.getCycleCount();
    uint32_t high = level * PWM_PERIOD >> 8;
    if (high) {
      GPOS = SPK_BIT; spkHigh = true;
      nextEdge = periodStart + high;
      ticked = high >= PWM_PERIOD / 2;  // long pulse: do the bookkeeping now, else after the falling edge
      if (ticked) sampleTick();
      continue;
    }
    sampleTick();  // no pulse this period
    // silent: look again in 1 ms instead of 40 000 interrupts a second
    nextEdge = periodStart + (!level && ringTail == ringHead ? F_CPU / 1000 : PWM_PERIOD);
  }
}

static void ringPush(uint8_t b) {
  uint32_t next = (ringHead + 1) % RING;
  if (next != ringTail) { ring[ringHead] = b; ringHead = next; }  // full: drop
}

// ---------- room air: BME280, or a BMP280 + AHT20 board (BMP280 temperature + pressure, AHT20 humidity) ----------
struct Air {
  uint8_t addr = 0; bool humidity = false;  // BME/BMP280 address (0: none), BME280 humidity
  bool aht = false;                          // AHT20 at 0x38
  Bme280Calib cal;
  uint32_t due = 0; bool measuring = false;
  static const uint8_t AHT = 0x38;
  char shown[24] = "";  // the display's bottom line, from the last reading
  uint32_t shownAt = 0;

  bool ahtBegin() {
    Wire.beginTransmission(AHT);
    if (Wire.endTransmission() != 0 || Wire.requestFrom(AHT, (uint8_t)1) != 1) return false;
    if (!(Wire.read() & 0x08)) {  // not calibrated yet: initialise
      Wire.beginTransmission(AHT); Wire.write(0xBE); Wire.write(0x08); Wire.write(0x00);
      if (Wire.endTransmission() != 0) return false;
      delay(10);
    }
    return true;
  }
  bool ahtTrigger() {
    Wire.beginTransmission(AHT); Wire.write(0xAC); Wire.write(0x33); Wire.write(0x00);
    return Wire.endTransmission() == 0;
  }
  bool ahtRead(uint32_t &rhTenths, int32_t &centiC) {
    uint8_t d[7];
    if (Wire.requestFrom(AHT, (uint8_t)7) != 7) return false;
    for (uint8_t i = 0; i < 7; i++) d[i] = Wire.read();
    return aht20Decode(d, rhTenths, centiC);
  }

  bool read(uint8_t reg, uint8_t *buf, uint8_t n) {
    Wire.beginTransmission(addr); Wire.write(reg);
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom(addr, n) != n) return false;
    for (uint8_t i = 0; i < n; i++) buf[i] = Wire.read();
    return true;
  }
  bool write(uint8_t reg, uint8_t v) {
    Wire.beginTransmission(addr); Wire.write(reg); Wire.write(v);
    return Wire.endTransmission() == 0;
  }
  bool bmeBegin() {
    for (uint8_t a : {0x76, 0x77}) {
      addr = a; uint8_t id;
      if (!read(0xD0, &id, 1) || (id != 0x60 && id != 0x58)) continue;  // 0x60 BME280, 0x58 BMP280
      humidity = id == 0x60;
      uint8_t c[26], h[7];
      if (!read(0x88, c, 26) || (humidity && !read(0xE1, h, 7))) continue;
      cal.load(c, humidity ? h : nullptr);
      if (humidity) write(0xF2, 0x01);  // humidity x1 (takes effect with the next ctrl_meas write)
      write(0xF5, 0x00);    // no IIR filter (forced mode)
      return true;
    }
    addr = 0;
    return false;
  }
  void lost(uint32_t now) { addr = 0; aht = false; due = now + 30000; }
  void poll(uint32_t now) {
    if ((int32_t)(now - due) < 0) return;
    if (!addr && !aht) {  // nothing found (yet): look again every 30 s
      due = now + 30000;
      bmeBegin();
      aht = ahtBegin();
      if (!addr && !aht) return;
    }
    if (!measuring) {  // BMP/BME280: T x1, P x1, forced (~10 ms); AHT20: ~80 ms
      if ((addr && !write(0xF4, 0x25)) || (aht && !ahtTrigger())) { lost(now); return; }
      measuring = true; due = now + 100;
      return;
    }
    measuring = false; due = now + AIR_MS;
    int32_t centiC = 0; uint32_t centiHpa = 0, rhTenths = 0;
    bool haveT = false, haveRh = false;
    if (addr) {
      uint8_t d[8];
      if (!read(0xF7, d, humidity ? 8 : 6)) { lost(now); return; }
      int32_t adcP = (int32_t)d[0] << 12 | d[1] << 4 | d[2] >> 4;
      int32_t adcT = (int32_t)d[3] << 12 | d[4] << 4 | d[5] >> 4;
      int32_t tf = cal.tFine(adcT);
      uint32_t p = cal.pressure(adcP, tf);  // Pa * 256
      if (p) { centiC = Bme280Calib::centiC(tf); centiHpa = (p + 128) / 256; haveT = true; }  // Pa = hPa * 100
      if (humidity) { rhTenths = (cal.humidity(d[6] << 8 | d[7], tf) * 10 + 512) / 1024; haveRh = true; }
    }
    if (aht) {
      int32_t ahtC;
      if (ahtRead(rhTenths, ahtC)) {  // the AHT20's humidity; its temperature only without a BMP280
        haveRh = true;
        if (!haveT) { centiC = ahtC; haveT = true; }
      }
    }
    if (!haveT) return;
    char rh[8] = "-", hpa[12] = "-", out[48];
    if (haveRh) snprintf(rh, sizeof rh, "%u.%u", (unsigned)(rhTenths / 10), (unsigned)(rhTenths % 10));
    if (centiHpa) snprintf(hpa, sizeof hpa, "%u.%02u", (unsigned)(centiHpa / 100), (unsigned)(centiHpa % 100));
    snprintf(out, sizeof out, "AIR %s%d.%02d %s %s", centiC < 0 ? "-" : "", abs(centiC) / 100, abs(centiC) % 100,
             rh, hpa);
    Serial.println(out);
    // bottom line: "22.7°C 61%RH 1017hPa" (6x10 font: 21 characters)
    int32_t tenthsC = (centiC + (centiC < 0 ? -5 : 5)) / 10;
    int n = snprintf(shown, sizeof shown, "%s%d.%d\xb0" "C", tenthsC < 0 ? "-" : "", abs(tenthsC) / 10,
                     abs(tenthsC) % 10);
    if (haveRh) n += snprintf(shown + n, sizeof shown - n, " %u%%RH", (unsigned)((rhTenths + 5) / 10));
    if (centiHpa) snprintf(shown + n, sizeof shown - n, " %uhPa", (unsigned)((centiHpa + 50) / 100));
    shownAt = now;
  }
};

// ---------- OLED: SSD1306 128x64 on the shared I2C bus; the PC sends the text, the bottom line is room air ----------
static U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE, PIN_SCL, PIN_SDA);

struct Display {
  bool present = false, dirty = true, offline = true;
  uint32_t retry = 0, drawn = 0;
  char rows[5][41] = {{0}};  // 0: title, 1-4: body

  void set(int row, const char *text) {
    if (row < 0 || row > 4) return;
    if (strncmp(rows[row], text, sizeof rows[row] - 1) == 0) return;
    strncpy(rows[row], text, sizeof rows[row] - 1);
    rows[row][sizeof rows[row] - 1] = 0;
    dirty = true;
  }
  void setOffline(bool off) { if (off != offline) { offline = off; dirty = true; } }
  void poll(uint32_t now, const Air &air) {
    if (!present) {  // not found (yet): look again every 30 s
      if ((int32_t)(now - retry) < 0) return;
      retry = now + 30000;
      Wire.beginTransmission(0x3C);
      if (Wire.endTransmission() != 0) return;
      u8g2.begin();
      present = dirty = true;
    }
    if (air.shownAt != airSeen) { airSeen = air.shownAt; dirty = true; }
    if (!dirty || now - drawn < 100) return;  // at most 10 redraws a second
    dirty = false; drawn = now;
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_helvB10_tf);
    u8g2.drawStr(0, 11, offline ? "Station offline" : rows[0]);
    u8g2.setFont(u8g2_font_6x10_tf);
    if (!offline)
      for (int r = 1; r <= 4; r++) u8g2.drawStr(0, 12 + r * 10, rows[r]);
    u8g2.drawHLine(0, 53, 128);
    u8g2.drawStr(0, 63, air.shown[0] ? air.shown : "no air sensor");
    u8g2.sendBuffer();
  }
  uint32_t airSeen = 0;
};

static Lamp hold{PIN_LAMP_HOLD}, discard{PIN_LAMP_DISCARD};
static Button btnHold{PIN_BTN_HOLD, 'H', true}, btnDiscard{PIN_BTN_DISCARD, 'D', false};
static Air air;
static Display display;
static uint32_t lastL = 0;
static uint16_t beepHz = 0, beepMs = 0; static uint8_t beepsLeft = 0; static uint32_t nextBeep = 0;
static char line[64]; static uint8_t len = 0;
static uint16_t binLeft = 0;  // raw audio bytes still to come after an "A <n>" line

static void hello() { Serial.print("HELLO intake-panel "); Serial.println(VERSION); }

static void handle(char *s) {
  if (s[0] == '?') { hello(); return; }
  if (s[0] == 'L') {
    int h, d;
    if (sscanf(s + 1, "%d %d", &h, &d) == 2) {
      hold.set(h); discard.set(d); lastL = millis(); display.setOffline(false);
    }
  } else if (s[0] == 'D' && s[1] == ' ' && s[2] >= '0' && s[2] <= '4' && (s[3] == ' ' || s[3] == 0)) {
    display.set(s[2] - '0', s[3] ? s + 4 : "");
  } else if (s[0] == 'B') {
    int hz, ms, n = 1;
    if (sscanf(s + 1, "%d %d %d", &hz, &ms, &n) >= 2 && hz >= 100 && hz <= 10000 && ms > 0 && ms <= 2000) {
      beepHz = hz; beepMs = ms; beepsLeft = constrain(n, 1, 5); nextBeep = millis();
    }
  } else if (s[0] == 'A') {
    int n;
    if (sscanf(s + 1, "%d", &n) == 1 && n > 0 && n <= 1024) binLeft = n;
  }
}

void setup() {
  WiFi.mode(WIFI_OFF);  // USB only; the radio would just add heat and noise
  WiFi.forceSleepBegin();
  Serial.setRxBufferSize(2048);  // audio arrives at ~8 KB/s; covers a slow I2C read
  Serial.begin(115200);
  for (uint8_t p : {PIN_LAMP_HOLD, PIN_LAMP_DISCARD, PIN_BUZZER, PIN_SPEAKER}) {
    pinMode(p, OUTPUT); digitalWrite(p, LOW);
  }
  pinMode(PIN_BTN_HOLD, INPUT_PULLUP);
  pinMode(PIN_BTN_DISCARD, INPUT_PULLUP);
  // The PC keeps the duty within 16-240: pulses of 1.6 us or more, about 5 time constants of the 1 kOhm pull-up
  // charging the push-pull pair's bases.
  nextEdge = ESP.getCycleCount() + F_CPU / 1000;
  setTimer1Callback(audioTick);
  Wire.begin(PIN_SDA, PIN_SCL);
  delay(50);
  Serial.println();
  hello();
}

void loop() {
  uint32_t now = millis();
  while (Serial.available()) {
    char c = Serial.read();
    if (binLeft) {
      ringPush((uint8_t)c);
      binLeft--;
    } else if (c == '\n' || c == '\r') {
      line[len] = 0;
      if (len) handle(line);
      len = 0;
    } else if (len < sizeof(line) - 1) {
      line[len++] = c;
    }
  }
  if (lastL && now - lastL > WATCHDOG_MS) { hold.set(0); discard.set(0); lastL = 0; display.setOffline(true); }
  if (beepsLeft && (int32_t)(now - nextBeep) >= 0) {
    tone(PIN_BUZZER, beepHz, beepMs);
    beepsLeft--; nextBeep = now + beepMs + 60;
  }
  btnHold.poll(now); btnDiscard.poll(now);
  hold.update(now); discard.update(now);
  air.poll(now);
  display.poll(now, air);
}
