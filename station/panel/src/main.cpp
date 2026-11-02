// Intake station button panel (Wemos D1 mini / ESP-12F). Thin I/O for intake_station.py over USB serial.
//
// Serial 115200, one ASCII line per message:
//   PC -> panel   "?"                     -> "HELLO intake-panel <version>"
//                 "L <hold> <discard>"    lamp modes: 0 off, 1 on, 2 flash, 3 three fast blinks then off
//                                         (3 only restarts the blinks when the mode changes to it)
//                 "B <hz> <ms> [count]"   beep(s) on the passive buzzer, 60 ms apart
//   panel -> PC   "HELLO intake-panel <version>"   at boot and in answer to "?"
//                 "P H" / "P D"           Hold / Discard pressed (debounced, once per press)
// The PC resends "L" every second; with no "L" for 5 s (station service stopped) the lamps go dark.
//
// Pins avoid the ESP8266 boot straps (GPIO0/D3, GPIO2/D4, GPIO15/D8) and the USB serial pins (GPIO1 TX, GPIO3 RX).
#include <Arduino.h>
#include <ESP8266WiFi.h>

static const char *VERSION = "1";
static const uint8_t PIN_BUZZER = D7;       // GPIO13: buzzer module signal
static const uint8_t PIN_BTN_HOLD = D1;     // GPIO5:  Hold button to GND (internal pull-up)
static const uint8_t PIN_BTN_DISCARD = D2;  // GPIO4:  Discard button to GND
static const uint8_t PIN_LAMP_HOLD = D5;    // GPIO14: Hold lamp MOSFET gate (high = lit)
static const uint8_t PIN_LAMP_DISCARD = D6; // GPIO12: Discard lamp MOSFET gate

static const uint32_t FLASH_MS = 250;      // flash: 2 Hz
static const uint32_t BLINK3_MS = 90;      // three fast blinks: 90 ms on / 90 ms off
static const uint32_t DEBOUNCE_MS = 30;
static const uint32_t WATCHDOG_MS = 5000;

struct Lamp {
  uint8_t pin, mode = 0;
  uint32_t since = 0;
  void set(uint8_t m) {
    if (m > 3) return;
    if (m != mode) { mode = m; since = millis(); }
  }
  void update(uint32_t now) {
    bool lit = false;
    uint32_t t = now - since;
    switch (mode) {
      case 1: lit = true; break;
      case 2: lit = (t / FLASH_MS) % 2 == 0; break;
      case 3: lit = t < 6 * BLINK3_MS && (t / BLINK3_MS) % 2 == 0; break;
    }
    digitalWrite(pin, lit ? HIGH : LOW);
  }
};

struct Button {
  uint8_t pin; char code;
  bool down = false; uint32_t changed = 0;
  void poll(uint32_t now) {
    bool pressed = digitalRead(pin) == LOW;
    if (pressed == down) { changed = now; return; }
    if (now - changed < DEBOUNCE_MS) return;
    down = pressed; changed = now;
    if (down) { Serial.print("P "); Serial.println(code); }
  }
};

static Lamp hold{PIN_LAMP_HOLD}, discard{PIN_LAMP_DISCARD};
static Button btnHold{PIN_BTN_HOLD, 'H'}, btnDiscard{PIN_BTN_DISCARD, 'D'};
static uint32_t lastL = 0;
static uint16_t beepHz = 0, beepMs = 0; static uint8_t beepsLeft = 0; static uint32_t nextBeep = 0;
static char line[48]; static uint8_t len = 0;

static void hello() { Serial.print("HELLO intake-panel "); Serial.println(VERSION); }

static void handle(char *s) {
  if (s[0] == '?') { hello(); return; }
  if (s[0] == 'L') {
    int h, d;
    if (sscanf(s + 1, "%d %d", &h, &d) == 2) { hold.set(h); discard.set(d); lastL = millis(); }
  } else if (s[0] == 'B') {
    int hz, ms, n = 1;
    if (sscanf(s + 1, "%d %d %d", &hz, &ms, &n) >= 2 && hz >= 100 && hz <= 10000 && ms > 0 && ms <= 2000) {
      beepHz = hz; beepMs = ms; beepsLeft = constrain(n, 1, 5); nextBeep = millis();
    }
  }
}

void setup() {
  WiFi.mode(WIFI_OFF);  // USB only; the radio would just add heat and noise
  WiFi.forceSleepBegin();
  Serial.begin(115200);
  for (uint8_t p : {PIN_LAMP_HOLD, PIN_LAMP_DISCARD, PIN_BUZZER}) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
  pinMode(PIN_BTN_HOLD, INPUT_PULLUP);
  pinMode(PIN_BTN_DISCARD, INPUT_PULLUP);
  delay(50);
  Serial.println();
  hello();
}

void loop() {
  uint32_t now = millis();
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      line[len] = 0;
      if (len) handle(line);
      len = 0;
    } else if (len < sizeof(line) - 1) {
      line[len++] = c;
    }
  }
  if (lastL && now - lastL > WATCHDOG_MS) { hold.set(0); discard.set(0); lastL = 0; }
  if (beepsLeft && (int32_t)(now - nextBeep) >= 0) {
    tone(PIN_BUZZER, beepHz, beepMs);
    beepsLeft--; nextBeep = now + beepMs + 60;
  }
  btnHold.poll(now); btnDiscard.poll(now);
  hold.update(now); discard.update(now);
}
