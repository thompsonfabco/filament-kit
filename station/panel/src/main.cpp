// Intake station button panel (ESP32-C3 Super Mini). Thin I/O for intake_station.py over native USB serial.
//
// Serial 115200, one ASCII line per message:
//   PC -> panel   "?"                     -> "HELLO intake-panel <version> esp32c3"
//                 "L <hold> <discard>"    lamp modes: 0 off, 1 on, 2 flash, 3 three fast blinks then off,
//                                         4 rapid blink (3 only restarts the blinks when the mode changes to it)
//                 "D <row> [text]"        OLED text: row 0 the title (big), rows 1-4 the body; no text clears the
//                                         row. The bottom line is the panel's own: room air, always shown.
//                 "B <hz> <ms> [count]"   beep(s) on the buzzer (an active-low module: the pin idles HIGH), 60 ms apart
//                 "A <n>" + n raw bytes   speech for the speaker: unsigned 8-bit mono at 8 kHz (n 1-1024), each byte
//                                         a sample, 128 = silence. The PC streams it in real time; when it stops, the
//                                         output fades to silence over 50 ms (it never holds the last sample).
//                 "V <percent>"           speaker volume 0-100 (50 until the station sends one)
//   panel -> PC   "HELLO intake-panel <version> esp32c3"   at boot and in answer to "?"
//                 "P H" / "P D"           the Hold / Discard button pressed: sent on release, if held under 800 ms
//                 "L H" / "L D"           the Hold / Discard button held down for 800 ms (then its release sends
//                                         nothing)
//                 H is the Hold (yellow) input and D the Discard (red) one as wired in PANEL.md. Both buttons report
//                 alike (since firmware 9), so the station can swap their roles for a panel wired the other way round
//                 (STATION_PANEL_SWAP) without a reflash; it swaps the "L" lamp modes to match.
//                 "AIR <C> <RH%|-> <hPa|->" room air every 10 s: a BME280, or a BMP280 + AHT20 board ("-": no such
//                                         sensor, e.g. RH on a lone BMP280)
//                 "TAG <hex>"             an NFC tag read by the PN532 on the I2C bus (since firmware 11): its UID in
//                                         lowercase hex, once per presentation (again only after no tag was seen for
//                                         1 s, or for a different tag)
//                 "NFC ok" / "NFC none"   whether a PN532 answers on the bus: sent after every HELLO and whenever that
//                                         changes (it is looked for every 5 s, so it can be plugged in later)
// The PC resends "L" every second; with no "L" for 5 s (station service stopped) the lamps go dark and the display
// says the station is offline ("Waiting for PC" before the first "L" since boot). The OLED (SSD1306 128x64, I2C
// 0x3C) shares the bus with the air sensor and the PN532
// (Elechouse NFC module V3 in I2C mode, 0x24; IRQ and RSTO unconnected, so no pin but SDA/SCL is touched for it). Line parsing, lamp and button timing and the speech sample conversion
// live in lib/panel_core (host tests in test/test_core).
//
// Pins follow the peripheral standard: I2C on 5/6 and the buzzer on 0 as on the reader; never the strapping pins
// 2, 8, 9 or the USB pair 18, 19. GPIO 20/21 are the C3's default UART, unused here (serial is native USB); the
// ROM's boot text on 21 is harmless, the amplifier stays silent with no I2S clock. Wi-Fi and Bluetooth stay off: the
// sketch never includes or calls them, and the core starts the radio only when it is used.
#include <Arduino.h>
#include <ESP_I2S.h>
#include <Wire.h>
#include <U8g2lib.h>
#include "aht20.h"
#include "bme280.h"
#include "pn532.h"
#include "panel_core.h"

static const char *VERSION = "11";
static const uint8_t PIN_SDA = 5;            // I2C SDA (air sensor, OLED)
static const uint8_t PIN_SCL = 6;            // I2C SCL
static const uint8_t PIN_BUZZER = 0;         // buzzer module signal
static const uint8_t PIN_BTN_HOLD = 3;       // Hold (yellow) button to GND (internal pull-up)
static const uint8_t PIN_BTN_DISCARD = 4;    // Discard (red) button to GND
static const uint8_t PIN_LAMP_HOLD = 1;      // Hold lamp MOSFET gate (high = lit)
static const uint8_t PIN_LAMP_DISCARD = 7;   // Discard lamp MOSFET gate
static const uint8_t PIN_I2S_BCLK = 10;      // MAX98357 BCLK
static const uint8_t PIN_I2S_LRC = 20;       // MAX98357 LRC (word select)
static const uint8_t PIN_I2S_DIN = 21;       // MAX98357 DIN

static const uint32_t WATCHDOG_MS = 5000;
static const uint32_t NFC_POLL_MS = 100;   // between tag polls
static const uint32_t NFC_RETRY_MS = 5000;  // between looks for an absent PN532
static const uint32_t AIR_MS = 10000;      // a forced-mode reading every 10 s: the sensor barely warms itself
static const uint32_t SAMPLE_RATE = 8000;

struct Lamp {
  uint8_t pin, mode = 0;
  uint32_t since = 0;
  void set(uint8_t m) {
    if (m > 4) return;
    if (m != mode) { mode = m; since = millis(); }
  }
  void update(uint32_t now) { digitalWrite(pin, panel::lampLit(mode, now - since) ? HIGH : LOW); }
};

struct Button {
  uint8_t pin; char code;
  panel::ButtonTimer timer;  // "P" on a short press's release, "L" once held 800 ms
  void poll(uint32_t now) {
    char kind = timer.poll(digitalRead(pin) == LOW, now);
    if (kind) { Serial.print(kind); Serial.print(' '); Serial.println(code); }
  }
};

// ---------- speaker: samples from the PC through a ring buffer, played over I2S by a task above loop()'s ----------
// The MAX98357 takes 16-bit I2S with no master clock; each sample goes to both slots, so it plays whichever channel
// the board's SD wiring selects. The ring is single-producer (loop() moves head) single-consumer (the speech task
// moves tail), so the volatile indices need no lock. The task blocks in i2s.write() while the DMA buffers are full,
// which paces it at 8 kHz and leaves the rest of the time to loop().
static const uint32_t RING = 8192;    // 1 s of audio; the PC keeps about 0.25 s queued
static volatile uint8_t ring[RING];
static volatile uint32_t ringHead = 0, ringTail = 0;  // head: written by loop(), tail: by the speech task
static volatile uint8_t volume = 50;  // percent, from "V"
static const uint32_t CHUNK = 64;     // frames per i2s.write(): 8 ms
static I2SClass i2s;

static void speechTask(void *) {
  static int16_t frames[CHUNK * 2];  // left, right
  int16_t last = 0;                  // the last sample played from the ring, faded out when it runs empty
  uint32_t idle = 0;                 // samples since the ring ran empty
  for (;;) {
    for (uint32_t i = 0; i < CHUNK; i++) {
      int16_t s;
      uint32_t tail = ringTail;
      if (tail != ringHead) {
        s = last = panel::toPcm(ring[tail], volume);
        ringTail = (tail + 1) % RING;
        idle = 0;
      } else if ((s = panel::fadeTowardSilence(last, idle)) != 0) {
        idle++;
      } else {
        last = 0;  // faded out: zeros from here on, which keep the amplifier settled between phrases
      }
      frames[2 * i] = frames[2 * i + 1] = s;
    }
    if (i2s.write((const uint8_t *)frames, sizeof frames) == 0) vTaskDelay(1);  // an I2S error: don't spin
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

// ---------- NFC: PN532 on the shared I2C bus, a state machine of short transactions (each well under 20 ms) ----------
// Commands go out as frames (pn532.h), the chip ACKs, then answers when done; the answer's ready bit is polled. The
// poll is InListPassiveTarget with no retries (RFConfiguration), so the chip answers at once, tag or not.
struct Nfc {
  enum Phase : uint8_t { SEND, ACK, RESP };
  Phase phase = SEND;
  uint8_t cmd = 0, fails = 0;  // cmd: 0 SAMConfiguration, 1 RFConfiguration, 2 InListPassiveTarget (the polling)
  bool nacked = false;         // the chip NACKed the last write: it may need a few ms after an exchange (UM0701 6.2.4)
  bool ok = false;             // initialised and answering
  bool loud = false;           // announce changes (not during the boot probe: HELLO says it then)
  uint32_t due = 0, deadline = 0, retryMs = NFC_RETRY_MS;
  TagGate gate;
  static constexpr uint8_t ARGS[3][6] = {{0x14, 0x01, 0x00, 0x01}, {0x32, 0x05, 0xFF, 0x01, 0x00}, {0x4A, 0x01, 0x00}};
  static constexpr uint8_t ARGN[3] = {4, 5, 3};

  void say() { Serial.println(ok ? "NFC ok" : "NFC none"); }
  void note() { if (loud) say(); }
  void fail(uint32_t now) {
    static const uint8_t cancel[6] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};  // an ACK frame aborts the chip's command
    Wire.beginTransmission(PN532_ADDR); Wire.write(cancel, 6); Wire.endTransmission();
    phase = SEND; nacked = false;
    if (ok && ++fails < 3) { due = now + NFC_POLL_MS; return; }
    if (ok) { ok = false; note(); }
    cmd = 0; fails = 0; due = now + retryMs;
  }
  void poll(uint32_t now) {
    if ((int32_t)(now - due) < 0) return;
    uint8_t r[64];  // status + the largest InListPassiveTarget answer we read; a longer ATS is clipped, not a failure
    if (phase == SEND) {
      uint8_t f[16], n = pn532Frame(f, ARGS[cmd], ARGN[cmd]);
      Wire.beginTransmission(PN532_ADDR); Wire.write(f, n);
      if (Wire.endTransmission() != 0) {
        if (!nacked) { nacked = true; deadline = now + 10; }  // a few ms of grace before it counts
        if ((int32_t)(now - deadline) >= 0) fail(now); else due = now + 2;
        return;
      }
      nacked = false;
      phase = ACK; due = now + 3; deadline = now + 100;
      return;
    }
    uint8_t want = phase == ACK ? 7 : sizeof r;
    if (Wire.requestFrom(PN532_ADDR, want) != want) {  // a NACK: retry until the deadline
      if ((int32_t)(now - deadline) >= 0) fail(now); else due = now + 3;
      return;
    }
    for (uint8_t i = 0; i < want; i++) r[i] = Wire.read();
    if (phase == ACK) {
      if (!pn532IsAck(r)) { if ((int32_t)(now - deadline) >= 0) fail(now); else due = now + 5; return; }
      phase = RESP; due = now + 10; deadline = now + 100;
      return;
    }
    if (!pn532Ready(r)) { if ((int32_t)(now - deadline) >= 0) fail(now); else due = now + 10; return; }
    uint8_t n = 0;
    bool clipped;
    const uint8_t *d = pn532Answer(r, sizeof r - 1, ARGS[cmd][0] + 1, n, &clipped);
    if (!d) { fail(now); return; }
    fails = 0; phase = SEND; due = now + 3;
    if (cmd < 2) {
      if (++cmd == 2) { ok = true; note(); }
      return;
    }
    due = now + NFC_POLL_MS;
    uint8_t uid[10], len;
    if (!pn532Uid(d, n, uid, len) || !gate.report(uid, len, now)) return;
    char hex[21];
    pn532Hex(uid, len, hex);
    Serial.print("TAG "); Serial.println(hex);
  }
};

// ---------- OLED: SSD1306 128x64 on the shared I2C bus; the PC sends the text, the bottom line is room air ----------
// U8g2 (BSD-2-Clause) with two fonts only: u8g2_font_helvB10_tf (title; Adobe/DEC X11 HELVB10.BDF, permissive, its
// notice is in ../PANEL.md) and u8g2_font_6x10_tf (body + air line; X11 Misc-Fixed, public domain).
static U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE, PIN_SCL, PIN_SDA);

struct Display {
  bool present = false, dirty = true, offline = true;
  bool seen = false;  // the station has talked to us since boot: until then the title says "Waiting for PC", not
                      // "offline" (the station may be about to reflash us, and an older firmware leaves the OLED as is)
  uint32_t retry = 0, drawn = 0;
  char rows[5][41] = {{0}};  // 0: title, 1-4: body

  void set(int row, const char *text) {
    if (row < 0 || row > 4) return;
    if (strncmp(rows[row], text, sizeof rows[row] - 1) == 0) return;
    strncpy(rows[row], text, sizeof rows[row] - 1);
    rows[row][sizeof rows[row] - 1] = 0;
    dirty = true;
  }
  void setOffline(bool off) {
    if (!off) seen = true;
    if (off != offline) { offline = off; dirty = true; }
  }
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
    u8g2.drawStr(0, 11, !offline ? rows[0] : seen ? "Station offline" : "Waiting for PC");
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
static Button btnHold{PIN_BTN_HOLD, 'H'}, btnDiscard{PIN_BTN_DISCARD, 'D'};
static Air air;
static Nfc nfc;
static Display display;
static uint32_t lastL = 0;
static uint16_t beepHz = 0, beepMs = 0; static uint8_t beepsLeft = 0; static uint32_t nextBeep = 0;
static bool beeping = false; static uint32_t beepEnd = 0;
static char line[64]; static uint8_t len = 0;
static uint16_t binLeft = 0;  // raw audio bytes still to come after an "A <n>" line

static void hello() {
  Serial.print("HELLO intake-panel "); Serial.print(VERSION); Serial.println(" esp32c3");
  nfc.say();
}

static void handle(const char *s) {
  panel::Command cmd;
  if (!panel::parseLine(s, cmd)) return;
  switch (cmd.kind) {
    case '?': hello(); break;
    case 'L': hold.set(cmd.a); discard.set(cmd.b); lastL = millis(); display.setOffline(false); break;
    case 'D': display.set(cmd.a, cmd.text); break;
    case 'B': beepHz = cmd.a; beepMs = cmd.b; beepsLeft = cmd.c; nextBeep = millis(); break;
    case 'A': binLeft = cmd.a; break;
    case 'V': volume = cmd.a; break;
  }
}

// The buzzer module is active-low (low-level trigger, transistor-switched): pin LOW is ON, so silence is the pin held
// HIGH (LOW would keep the transistor on with DC through the coil). A beep is a 50% square wave on the LEDC channel.
static void buzzerIdle() {
  ledcDetach(PIN_BUZZER);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, HIGH);
}
static void buzzerTone(uint32_t hz) {
  ledcAttach(PIN_BUZZER, 2000, 10);  // the buzzer's own LEDC channel; ledcWriteTone() sets the pitch
  ledcWriteTone(PIN_BUZZER, hz);
}

void setup() {
  Serial.setRxBufferSize(2048);  // audio arrives at ~8 KB/s; covers a slow I2C read
  Serial.setTxTimeoutMs(0);      // no host reading: drop output instead of stalling loop()
  Serial.begin(115200);
  for (uint8_t p : {PIN_LAMP_HOLD, PIN_LAMP_DISCARD}) {
    pinMode(p, OUTPUT); digitalWrite(p, LOW);
  }
  pinMode(PIN_BTN_HOLD, INPUT_PULLUP);
  pinMode(PIN_BTN_DISCARD, INPUT_PULLUP);
  buzzerIdle();
  i2s.setPins(PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DIN);
  bool speech = i2s.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  // setup() runs in loopTask: one priority above it
  if (speech) xTaskCreate(speechTask, "speech", 3072, nullptr, uxTaskPriorityGet(nullptr) + 1, nullptr);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);  // a full OLED update stays short
  u8g2.setBusClock(400000);
  delay(50);
  // look for the PN532 for up to 150 ms so the first NFC line is true; then every 5 s
  nfc.retryMs = 10;
  for (uint32_t end = millis() + 150; !nfc.ok && (int32_t)(millis() - end) < 0; delay(2)) nfc.poll(millis());
  nfc.retryMs = NFC_RETRY_MS;
  nfc.loud = true;
  Serial.println();
  hello();
  if (!speech) Serial.println("I2S failed: no speech");
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
  if (beeping && (int32_t)(now - beepEnd) >= 0) { buzzerIdle(); beeping = false; }
  if (beepsLeft && (int32_t)(now - nextBeep) >= 0) {
    buzzerTone(beepHz); beeping = true; beepEnd = now + beepMs;
    beepsLeft--; nextBeep = now + beepMs + 60;
  }
  btnHold.poll(now); btnDiscard.poll(now);
  hold.update(now); discard.update(now);
  air.poll(now);
  nfc.poll(now);
  display.poll(now, air);
}
