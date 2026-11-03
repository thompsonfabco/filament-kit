// H2D filament scanner — ESP32 reader node
// -----------------------------------------------------------------------------
// Thin client. Reads an NFC tag UID over I2C (PN532), lets you pick a target AMS
// slot with a rotary encoder (shown on an SSD1306 OLED), and POSTs {uid, ams_id,
// tray_id} to the orchestrator on the Spoolman VM. The orchestrator does the
// Spoolman lookup + printer MQTT and returns the result, which we buzz + show.
//
// Target board: ESP32-C3 Super Mini. All wiring is in the CONFIG block below —
// change pins freely. PN532 and OLED share the I2C bus (different addresses), so
// the whole thing is 2 I2C pins + PN532 IRQ/RST + encoder (CLK/DT/SW) + buzzer.
// -----------------------------------------------------------------------------
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Adafruit_PN532.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <TalkiePCM.h>
#include <Vocab_US_TI99.h>   // only for spt_LOAD (unused words are stripped at link)
#include <Update.h>
#include <esp_ota_ops.h>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>
#include <mbedtls/base64.h>
#include <Preferences.h>
#include "secrets.h"
#include "fw_build.h"        // FW_BUILD, generated per build by fw_build.py

// ======================= CONFIG (edit me) ====================================
// WIFI_SSID, WIFI_PASS and AUTH_TOKEN live in secrets.h (not in this file).

// Orchestrator endpoint on the Spoolman VM (HTTPS, via the nginx router).
static const char* ORCH_URL   = "https://mcp.example.com/h2d/set-slot";
// h2d-remote's printer state (LAN-gated, no token): what's loaded in each slot.
static const char* STATE_URL  = "https://mcp.example.com/printer/api/state";

// Root CA to validate the server cert (ISRG Root X1 — Let's Encrypt chain).
static const char* ROOT_CA = R"CERT(-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
)CERT";

// --- OTA (HTTPS pull from the VM, same CA pin + X-Auth-Token). Hold the knob
//     2 s to check; firmware/ota_publish.py builds, signs and uploads images. ---
static const char* OTA_MANIFEST_URL = "https://mcp.example.com/h2d/fw/manifest.json";
static const char* OTA_BIN_URL      = "https://mcp.example.com/h2d/fw/firmware.bin";
static const char* HEALTHZ_URL      = "https://mcp.example.com/h2d/healthz";
// ECDSA P-256 public key; images must be signed by the matching private key
// (kept on the desktop in ~/.h2d-ota/, never on the VM).
static const char* OTA_PUBKEY = R"KEY(-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEWCWNkQzFhqLWfDDLn8XRBf7gQDSg
W96ZG2mxT8c4zDy/km4y5rymX4bieiLIHYC+nZbe5bux2nZwQKXBCK1dyg==
-----END PUBLIC KEY-----
)KEY";

// --- Pin map: ESP32-C3 Super Mini. Only GPIO0-10,20,21 are broken out; avoid
//     GPIO8 (onboard LED + strap) and GPIO9 (BOOT button + strap). USB pins
//     18/19 and flash pins 12-17 are not on the header. ---

// --- I2C bus (PN532 + OLED share it) ---
static const int PIN_SDA     = 5;
static const int PIN_SCL     = 6;

// --- PN532 control pins: LEAVE THESE UNCONNECTED. The library's constructor
//     wants pin numbers, but over I2C it polls readiness on the bus (IRQ unused),
//     and the header's RSTO is the PN532's reset *output* (the real input, RSTPDN,
//     is tied high on-board). Wiring them on the red V3 board jammed the bus
//     (SCL held low, error 263). These GPIOs just stay unwired. ---
static const int PN532_IRQ   = 7;
static const int PN532_RESET = 10;

// --- OLED ---
static const int OLED_ADDR   = 0x3C;
static const int OLED_W      = 128;
static const int OLED_H      = 64;

// --- Rotary encoder (KY-040 style: CLK/DT quadrature + SW push, common to GND).
//     Rotate = change slot; short press = re-send the last tag to the shown slot.
//     If rotation feels reversed, swap CLK and DT (or the two pin numbers). ---
static const int PIN_ENC_CLK = 3;
static const int PIN_ENC_DT  = 4;
static const int PIN_ENC_SW  = 1;
// Push switch wiring: true = switch between GPIO1 and 3V3 (this build; internal
// pull-down, pressed = HIGH). false = switch to GND (internal pull-up, pressed = LOW).
static const bool ENC_SW_TO_VCC = true;

// --- Buzzer (passive piezo on a PWM-capable pin) ---
//     3-pin module (GND, I/O, VCC) with a PNP driver = low-level trigger: I/O LOW
//     turns the transistor on, so the pin must idle HIGH. Set false for a bare piezo.
static const int  PIN_BUZZER        = 0;
static const bool BUZZER_ACTIVE_LOW = true;

// --- Voice (TI LPC speech via TalkiePCM, PWM'd out the buzzer pin) ---
//     Speaks the slot ("A three", "H T one") once the knob settles, and
//     "set" + slot after a successful tap. Tinny on a buzzer, but digits carry.
static const bool     TALK_ENABLED    = true;
static const float    TALK_VOLUME     = 6.0f;   // >1 louder (clips sooner); 3.3 V buzzer needs a lot
static const uint32_t SPEAK_SETTLE_MS = 600;    // knob idle time before speaking

// Re-scan guard: ignore the same tag if re-read within this window.
static const uint32_t SCAN_COOLDOWN_MS = 2500;
// How long a result stays on screen before reverting to the slot picker.
static const uint32_t RESULT_HOLD_MS   = 4000;
// "Load filament" (queued) prompt stays up longer — you're walking to the AMS.
static const uint32_t QUEUED_HOLD_MS   = 15000;

// Target slots, in selection order. ams_id / tray_id are what the printer wants
// (tray_id 0-based); label is cosmetic. Matches this H2D's topology.
struct Slot { int ams_id; int tray_id; const char* label; };
static const Slot SLOTS[] = {
  {0,   0, "AMS A1"},
  {0,   1, "AMS A2"},
  {0,   2, "AMS A3"},
  {0,   3, "AMS A4"},
  {128, 0, "HT 1"},
  {129, 0, "HT 2"},
  {130, 0, "HT 3"},
  {254, 0, "EXT L"},   // external spool path, left nozzle (no presence sensor: never queued)
  {255, 0, "EXT R"},   // external spool path, right nozzle
};
static const int NUM_SLOTS = sizeof(SLOTS) / sizeof(SLOTS[0]);
// =============================================================================

Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET);
Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);

int      selected = 0;
uint32_t lastScanMs = 0;
String   lastUid = "";
uint32_t resultUntil = 0;

// ---- buzzer patterns --------------------------------------------------------
// Park the pin at its "off" level (HIGH for the active-low module). Beeps drive
// LEDC directly rather than tone(): tone()'s async task ends each note at duty 0
// (pin LOW = transistor on) and can detach the pin after we've parked it.
void buzzIdle() { pinMode(PIN_BUZZER, OUTPUT); digitalWrite(PIN_BUZZER, BUZZER_ACTIVE_LOW ? HIGH : LOW); }
void beep(int freq, int ms) {
  if (!ledcAttach(PIN_BUZZER, freq, 10))  // 10-bit keeps the divider legal down to ~300 Hz
    Serial.printf("beep: ledcAttach(%d Hz) failed\n", freq);
  ledcWrite(PIN_BUZZER, 512);            // 50% square wave (polarity-agnostic)
  delay(ms);
  ledcDetach(PIN_BUZZER); buzzIdle();
}
// The 3.3 V buzzer is loud only near its resonance: 2 kHz (pleasant) and 4 kHz
// (shrill) tested loudest, so patterns differ by rhythm, with 4 kHz for errors.
void buzzOk()      { beep(2000, 90); delay(60); beep(2000, 90); }          // set OK
void buzzUnknown() { beep(2000, 600); }                                    // tag not in Spoolman
void buzzError()   { for (int i=0;i<3;i++){ beep(4000,120); delay(80);} }  // unreachable
void buzzTick()    { beep(2000, 15); }                                     // knob/button
void buzzQueued()  { beep(2000, 80); delay(80); beep(2000, 350); }         // queued: short-long

// ---- voice -----------------------------------------------------------------
// TalkiePCM decodes LPC frames to 8 kHz samples and hands each one to
// talkSample(); we pace them with micros() and write them as the duty of a
// 40 kHz PWM carrier, which the buzzer's coil low-passes back into audio.
TalkiePCM voice;
static const uint32_t TALK_SAMPLE_US = 125;  // 8 kHz
static uint32_t talkNextUs = 0;

void talkSample(int16_t* data, int len) {
  int duty = (data[0] >> 8) + 128;            // int16 -> 0..255 around mid
  if (BUZZER_ACTIVE_LOW) duty = 255 - duty;
  while ((int32_t)(micros() - talkNextUs) < 0) {}
  ledcWrite(PIN_BUZZER, duty);
  talkNextUs += TALK_SAMPLE_US;
}

// Say a sequence of vocab words as one utterance (blocks ~0.4 s per word).
void say(std::initializer_list<const uint8_t*> words) {
  if (!TALK_ENABLED) return;
  if (!ledcAttach(PIN_BUZZER, 40000, 8)) Serial.println("say: ledcAttach failed");
  ledcWrite(PIN_BUZZER, 128);
  talkNextUs = micros();
  for (const uint8_t* w : words) voice.say(w);
  ledcDetach(PIN_BUZZER); buzzIdle();
}

const uint8_t* digitWord(int n) {
  static const uint8_t* const D[] = {sp2_ZERO, sp2_ONE, sp2_TWO, sp2_THREE, sp2_FOUR,
                                     sp2_FIVE, sp2_SIX, sp2_SEVEN, sp2_EIGHT, sp2_NINE};
  return D[(n >= 0 && n <= 9) ? n : 0];
}

// AMS 0 trays -> "A one".."A four"; AMS HT 128.. -> "H T one"..; external 254/255 ->
// "E X T left/right" (matches labels; the vocab has no "external").
// lead: optional word said first ("set", "load"), or nullptr.
void speakSlot(int i, const uint8_t* lead) {
  const Slot& s = SLOTS[i];
  if (s.ams_id >= 254) {
    const uint8_t* side = s.ams_id == 254 ? sp2_LEFT : sp2_RIGHT;
    if (lead) say({lead, sp2_E, sp2_X, sp2_T, side}); else say({sp2_E, sp2_X, sp2_T, side});
  } else if (s.ams_id == 0) {
    const uint8_t* n = digitWord(s.tray_id + 1);
    if (lead) say({lead, sp2_A, n}); else say({sp2_A, n});
  } else {
    const uint8_t* n = digitWord(s.ams_id - 127);
    if (lead) say({lead, sp2_H, sp2_T, n}); else say({sp2_H, sp2_T, n});
  }
}

// ---- OLED screens -----------------------------------------------------------
bool updateReady = false;        // a newer signed build is on the server
String slotInfo[NUM_SLOTS];      // what's loaded per slot (filled by refreshTrays)

void showPicker() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("Select slot  ");
  display.print(selected + 1); display.print("/"); display.print(NUM_SLOTS);
  if (updateReady) { display.setCursor(OLED_W - 18, 0); display.print("UPD"); }
  display.drawFastHLine(0, 11, OLED_W, SSD1306_WHITE);
  display.setTextSize(3);
  display.setCursor(0, 20);
  display.print(SLOTS[selected].label);
  display.setTextSize(1);
  display.setCursor(0, 54);
  // what's in this slot now (cached); one line, so trim to the 21 columns
  String info = slotInfo[selected].length() ? slotInfo[selected] : String("tap tag to assign");
  if (updateReady && !slotInfo[selected].length()) info = "update: hold knob 2s";
  display.print(info.substring(0, 21));
  display.display();
}

void showResult(const char* line1, const char* line2, bool big2) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(line1);
  display.drawFastHLine(0, 11, OLED_W, SSD1306_WHITE);
  display.setTextSize(big2 ? 2 : 1);
  display.setCursor(0, big2 ? 24 : 20);
  display.print(line2);
  display.display();
  resultUntil = millis() + RESULT_HOLD_MS;
}

// ---- UID formatting: match nfc2klipper / Spoolman extra.nfc_id --------------
// lowercase hex, NO leading zeros, colon-separated  ->  "4:c7:96:11:9:22:89"
String formatUid(const uint8_t* uid, uint8_t len) {
  String s;
  for (uint8_t i = 0; i < len; i++) {
    if (i) s += ':';
    s += String(uid[i], HEX);   // String(HEX) already drops the leading zero
  }
  return s;
}

// ---- HTTPS: one kept-alive TLS connection to the VM -------------------------
// Taps, tray-state refreshes and update checks share it, so a tap skips the
// ~1 s TLS handshake while nginx holds the connection open (75 s idle). A stale
// socket fails fast and is retried once on a fresh connection (set-slot is
// idempotent, so a repeat is harmless).
WiFiClientSecure apiTls;
HTTPClient       apiHttp;
int apiRequest(const char* url, const char* body, String& resp) {
  int code = -1;
  for (int attempt = 0; attempt < 2; attempt++) {
    apiHttp.setReuse(true);
    apiHttp.setTimeout(6000);
    if (!apiHttp.begin(apiTls, url)) { apiTls.stop(); continue; }
    apiHttp.addHeader("X-Auth-Token", AUTH_TOKEN);
    if (body) { apiHttp.addHeader("Content-Type", "application/json"); code = apiHttp.POST(body); }
    else      code = apiHttp.GET();
    if (code > 0) { resp = apiHttp.getString(); apiHttp.end(); return code; }
    apiHttp.end(); apiTls.stop();
  }
  return code;
}

// ---- what's in each slot (from h2d-remote) ----------------------------------
// Refreshed at boot, every TRAY_REFRESH_MS while the screen is on, and after a
// set; the picker draws from this cache so turning the knob never waits.
uint32_t traysAt = 0;
static const uint32_t TRAY_REFRESH_MS = 60000;
void refreshTrays() {
  traysAt = millis();
  if (WiFi.status() != WL_CONNECTED) return;
  String resp;
  if (apiRequest(STATE_URL, nullptr, resp) != 200) return;
  JsonDocument filter; filter["ams"][0]["id"] = true;
  JsonObject ft = filter["ams"][0]["trays"][0].to<JsonObject>();
  ft["id"] = true; ft["type"] = true; ft["empty"] = true; ft["spool"]["name"] = true;
  JsonDocument st;
  if (deserializeJson(st, resp, DeserializationOption::Filter(filter))) return;
  for (int i = 0; i < NUM_SLOTS; i++) {
    String info = "?";
    for (JsonObject u : st["ams"].as<JsonArray>()) {
      if ((int)u["id"] != SLOTS[i].ams_id) continue;
      for (JsonObject t : u["trays"].as<JsonArray>()) {
        // tray ids arrive as numbers for AMS units and as strings for the external paths
        int tid = t["id"].is<const char*>() ? atoi(t["id"].as<const char*>()) : t["id"].as<int>();
        if (tid != SLOTS[i].tray_id) continue;
        const char* type = t["type"] | "";
        const char* name = t["spool"]["name"] | "";
        if (t["empty"] | false) info = "empty";
        else if (*name)        info = String(type) + " " + name;
        else if (*type)        info = String(type) + " (no spool)";
        else                   info = "loaded, not set";
      }
    }
    slotInfo[i] = info;
  }
}

// ---- POST to the orchestrator ----------------------------------------------
void sendScan(const String& uid) {
  if (WiFi.status() != WL_CONNECTED) { showResult("Scan", "No WiFi", true); buzzError(); return; }

  JsonDocument body;
  body["uid"]     = uid;
  body["ams_id"]  = SLOTS[selected].ams_id;
  body["tray_id"] = SLOTS[selected].tray_id;
  String payload; serializeJson(body, payload);

  String resp;
  uint32_t t0 = millis();
  int code = apiRequest(ORCH_URL, payload.c_str(), resp);
  Serial.printf("set-slot round trip %lu ms\n", millis() - t0);

  if (code <= 0) {
    char tlsErr[120] = "";
    apiTls.lastError(tlsErr, sizeof(tlsErr));
    Serial.printf("POST failed: %d %s | TLS: %s | WiFi %s RSSI %d | heap %u\n", code,
                  HTTPClient::errorToString(code).c_str(), tlsErr,
                  WiFi.status() == WL_CONNECTED ? "up" : "DOWN", WiFi.RSSI(), ESP.getFreeHeap());
    showResult("Scan", "Orch down", true); buzzError(); return;
  }
  Serial.printf("POST %d: %s\n", code, resp.c_str());

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, resp);
  const char* status = (!err) ? (const char*)(doc["status"] | "") : "";
  const char* fil    = (!err) ? (const char*)(doc["filament"] | "") : "";

  char head[40];
  snprintf(head, sizeof(head), "%s  %s", SLOTS[selected].label,
           strlen(status) ? status : "resp?");

  if (code == 200 && strcmp(status, "set") == 0) {
    showResult(head, strlen(fil) ? fil : "set", false); buzzOk(); speakSlot(selected, sp2_SET);
    traysAt = millis() - TRAY_REFRESH_MS + 5000;   // re-read slot contents in ~5 s
  } else if (code == 200 && strcmp(status, "queued") == 0) {
    // Empty slot: the orchestrator holds the setting (15 min) and applies it once
    // the AMS reads the loaded filament. A success, just pending.
    char line1[40], line2[64];
    snprintf(line1, sizeof(line1), "Load into %s", SLOTS[selected].label);
    snprintf(line2, sizeof(line2), "%s\nwill set when loaded", strlen(fil) ? fil : "filament");
    showResult(line1, line2, false);
    resultUntil = millis() + QUEUED_HOLD_MS;
    buzzQueued(); speakSlot(selected, spt_LOAD);
  } else if (strcmp(status, "unknown_tag") == 0) {
    showResult(head, "Unknown tag", true); buzzUnknown();
  } else {
    showResult(head, "Error", true); buzzError();
  }
}

// ---- rotary encoder (interrupt-driven quadrature) --------------------------
// Full-step Gray-code transition table, indexed [prevCLKDT<<2 | currCLKDT]:
// sums valid quarter-steps (4 per detent); invalid transitions return 0, which
// gives free contact debounce.
static const int8_t ENC_TABLE[16] = {
   0, -1,  1,  0,
   1,  0,  0, -1,
  -1,  0,  0,  1,
   0,  1, -1,  0
};
volatile uint8_t encState   = 0;    // last (CLK,DT) in the low 2 bits
volatile int8_t  encAccum   = 0;    // quarter-steps since last detent
volatile int16_t encDetents = 0;    // whole detents waiting for loop()

void IRAM_ATTR encISR() {
  encState = ((encState << 2) |
              (digitalRead(PIN_ENC_CLK) << 1) |
               digitalRead(PIN_ENC_DT)) & 0x0F;
  encAccum += ENC_TABLE[encState];
  if      (encAccum >=  4) { encDetents++; encAccum = 0; }
  else if (encAccum <= -4) { encDetents--; encAccum = 0; }
}

// ---- encoder push button (debounced, active-low) ---------------------------
// Short press (released before LONG_PRESS_MS) = re-send; hold = OTA check.
enum SwEvent { SW_NONE, SW_SHORT, SW_LONG };
bool     swPrev   = false;
bool     swLongFired = false;
uint32_t swLastMs = 0, swDownMs = 0;
static const uint32_t SW_DEBOUNCE_MS = 40;
static const uint32_t LONG_PRESS_MS  = 2000;
SwEvent swEvent() {
  bool now = digitalRead(PIN_ENC_SW) == (ENC_SW_TO_VCC ? HIGH : LOW);
  if (now != swPrev && (millis() - swLastMs) > SW_DEBOUNCE_MS) {
    swLastMs = millis();
    swPrev   = now;
    if (now) { swDownMs = millis(); swLongFired = false; return SW_NONE; }
    return swLongFired ? SW_NONE : SW_SHORT;           // released
  }
  if (now && !swLongFired && millis() - swDownMs >= LONG_PRESS_MS) {
    swLongFired = true;
    return SW_LONG;
  }
  return SW_NONE;
}

// ---- OTA --------------------------------------------------------------------
// Manifest {"build": <unix time>, "size": N, "sha256": "<hex>", "sig": "<base64 DER>"}.
// The image is streamed into the inactive OTA slot while hashing; it's only
// committed if size, SHA-256 and the ECDSA signature (over the SHA-256) all
// check out. The new image boots "pending verify" and marks itself valid once
// Wi-Fi is up and /h2d/healthz answers 200 (see confirmOtaImage); otherwise the
// bootloader rolls back to the previous image on the next reset.
// core: don't auto-mark the app valid. extern "C": the core's weak default is C.
extern "C" bool verifyRollbackLater() { return true; }

void showProgress(const char* title, const char* line, int pct) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);  display.print(title);
  display.drawFastHLine(0, 11, OLED_W, SSD1306_WHITE);
  display.setCursor(0, 20); display.print(line);
  if (pct >= 0) {
    display.drawRect(0, 44, OLED_W, 12, SSD1306_WHITE);
    display.fillRect(2, 46, (OLED_W - 4) * pct / 100, 8, SSD1306_WHITE);
  }
  display.display();
}

bool httpsGet(HTTPClient& http, WiFiClientSecure& tls, const char* url) {
  tls.setCACert(ROOT_CA);
  http.setTimeout(15000);
  if (!http.begin(tls, url)) return false;
  http.addHeader("X-Auth-Token", AUTH_TOKEN);
  return http.GET() == 200;
}

bool verifySig(const uint8_t hash[32], const char* sigB64) {
  uint8_t sig[80]; size_t sigLen = 0;
  if (mbedtls_base64_decode(sig, sizeof(sig), &sigLen, (const uint8_t*)sigB64, strlen(sigB64)) != 0)
    return false;
  mbedtls_pk_context pk; mbedtls_pk_init(&pk);
  bool ok = mbedtls_pk_parse_public_key(&pk, (const uint8_t*)OTA_PUBKEY, strlen(OTA_PUBKEY) + 1) == 0 &&
            mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, 32, sig, sigLen) == 0;
  mbedtls_pk_free(&pk);
  return ok;
}

void otaFail(const char* why) {
  Serial.printf("OTA failed: %s\n", why);
  showResult("Update failed", why, false);
  buzzError();
}

struct Manifest { long build = 0; size_t size = 0; String sha, sig; };
bool fetchManifest(Manifest& m) {
  String resp;
  if (apiRequest(OTA_MANIFEST_URL, nullptr, resp) != 200) return false;
  JsonDocument j;
  if (deserializeJson(j, resp)) return false;
  m.build = j["build"] | 0L; m.size = j["size"] | 0;
  m.sha = (const char*)(j["sha256"] | ""); m.sig = (const char*)(j["sig"] | "");
  return true;
}

// Quiet check (boot + daily): just flags "UPD" on the picker; installing stays
// a deliberate knob hold.
uint32_t updCheckAt = 0;
static const uint32_t UPD_CHECK_MS = 24UL * 3600 * 1000;
void checkForUpdate() {
  updCheckAt = millis();
  Manifest m;
  if (WiFi.status() == WL_CONNECTED && fetchManifest(m)) {
    updateReady = m.build > (long)FW_BUILD;
    Serial.printf("update check: running %ld, server %ld%s\n", (long)FW_BUILD, m.build,
                  updateReady ? " -> UPDATE READY" : "");
  }
}

void otaCheck() {
  if (WiFi.status() != WL_CONNECTED) { otaFail("no WiFi"); return; }
  showProgress("Firmware update", "checking...", -1);

  Manifest m;
  if (!fetchManifest(m)) { otaFail("no manifest"); return; }
  long build = m.build; size_t size = m.size; String shaHex = m.sha, sigB64 = m.sig;
  Serial.printf("OTA: running build %ld, server build %ld (%u bytes)\n", (long)FW_BUILD, build, size);
  apiTls.stop();   // free the kept-alive TLS session's heap for the download
  if (build <= (long)FW_BUILD) {
    updateReady = false;
    char l[40]; snprintf(l, sizeof(l), "up to date\nbuild %ld", (long)FW_BUILD);
    showResult("Firmware update", l, false); buzzOk();
    return;
  }
  if (!size || shaHex.length() != 64 || !sigB64.length()) { otaFail("bad manifest"); return; }
  if (!Update.begin(size)) { otaFail("too big / no slot"); return; }

  WiFiClientSecure tls; HTTPClient http;
  if (!httpsGet(http, tls, OTA_BIN_URL) || (size_t)http.getSize() != size) {
    http.end(); Update.abort(); otaFail("download"); return;
  }
  mbedtls_sha256_context sha; mbedtls_sha256_init(&sha); mbedtls_sha256_starts(&sha, 0);
  WiFiClient* s = http.getStreamPtr();
  static uint8_t buf[4096];
  size_t got = 0; int lastPct = -1; uint32_t lastData = millis();
  while (got < size) {
    size_t avail = s->available();
    if (!avail) {
      if (!http.connected() || millis() - lastData > 15000) break;
      delay(2); continue;
    }
    int n = s->readBytes(buf, min(avail, min(sizeof(buf), size - got)));
    if (n <= 0) continue;
    lastData = millis();
    mbedtls_sha256_update(&sha, buf, n);
    if (Update.write(buf, n) != (size_t)n) break;
    got += n;
    int pct = got * 100 / size;
    if (pct != lastPct) {
      lastPct = pct;
      char l[32]; snprintf(l, sizeof(l), "downloading %d%%", pct);
      showProgress("Firmware update", l, pct);
    }
  }
  http.end();
  uint8_t hash[32]; mbedtls_sha256_finish(&sha, hash); mbedtls_sha256_free(&sha);
  if (got != size) { Update.abort(); otaFail("download cut"); return; }

  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", hash[i]);
  if (!shaHex.equalsIgnoreCase(hex)) { Update.abort(); otaFail("hash mismatch"); return; }
  if (!verifySig(hash, sigB64.c_str())) { Update.abort(); otaFail("bad signature"); return; }
  if (!Update.end(true)) { otaFail(Update.errorString()); return; }

  showProgress("Firmware update", "installed\nrestarting...", 100);
  buzzOk();
  // Reboot only now, with no I2C transfer in flight, so the PN532 isn't left
  // holding SCL (it has no reset line we can drive).
  delay(500);
  ESP.restart();
}

// New OTA image: keep it only if it can reach the orchestrator.
void confirmOtaImage() {
  const esp_partition_t* run = esp_ota_get_running_partition();
  esp_ota_img_states_t st;
  if (esp_ota_get_state_partition(run, &st) != ESP_OK) st = ESP_OTA_IMG_UNDEFINED;
  Serial.printf("running %s, OTA state %d\n", run->label, (int)st);
  if (st != ESP_OTA_IMG_PENDING_VERIFY) return;
  bool ok = false;
  if (WiFi.status() == WL_CONNECTED) {
    String resp;
    ok = apiRequest(HEALTHZ_URL, nullptr, resp) == 200;
  }
#ifdef OTA_TEST_FAIL_HEALTH  // rollback drill: PLATFORMIO_BUILD_FLAGS=-DOTA_TEST_FAIL_HEALTH py ota_publish.py
  ok = false;
#endif
  if (ok) {
    esp_ota_mark_app_valid_cancel_rollback();
    Serial.printf("OTA image build %ld confirmed\n", (long)FW_BUILD);
  } else {
    Serial.println("OTA image failed its health check -> rolling back");
    showProgress("Firmware update", "new build failed\nrolling back...", -1);
    buzzError();
    delay(1500);
    esp_ota_mark_app_invalid_rollback_and_reboot();
  }
}

// ---- screen sleep (OLED burn-in) + remembered slot --------------------------
// Dim after 2 min idle, off after 10. The first knob turn / press on a dark
// screen only wakes it; a tag tap wakes it and is processed as usual.
static const uint32_t DIM_AFTER_MS = 2UL * 60 * 1000;
static const uint32_t OFF_AFTER_MS = 10UL * 60 * 1000;
enum Screen { SCR_ON, SCR_DIM, SCR_OFF };
Screen   scr = SCR_ON;
uint32_t lastActivity = 0;
bool wake() {                       // returns true if the screen was off
  lastActivity = millis();
  bool wasOff = scr == SCR_OFF;
  if (wasOff) display.ssd1306_command(SSD1306_DISPLAYON);
  if (scr != SCR_ON) display.dim(false);
  scr = SCR_ON;
  return wasOff;
}
void screenIdle() {
  uint32_t idle = millis() - lastActivity;
  if (scr == SCR_ON  && idle > DIM_AFTER_MS) { display.dim(true); scr = SCR_DIM; }
  if (scr == SCR_DIM && idle > OFF_AFTER_MS) { display.ssd1306_command(SSD1306_DISPLAYOFF); scr = SCR_OFF; }
}

Preferences prefs;                  // NVS: survives reboots and OTA updates
int savedSlot = -1;
void saveSlot() {
  if (selected == savedSlot) return;
  prefs.putUChar("slot", selected);
  savedSlot = selected;
}

// Print every I2C address that ACKs (PN532 = 0x24, OLED = 0x3C).
void i2cScan() {
  Serial.print("I2C scan:");
  int n = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { Serial.printf(" 0x%02X", a); n++; }
  }
  Serial.println(n ? "" : " nothing answered");
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_ENC_CLK, INPUT_PULLUP);
  pinMode(PIN_ENC_DT,  INPUT_PULLUP);
  pinMode(PIN_ENC_SW,  ENC_SW_TO_VCC ? INPUT_PULLDOWN : INPUT_PULLUP);
  buzzIdle();
  voice.setDataCallback(talkSample);
  voice.setVolume(TALK_VOLUME);
  // seed encoder state and watch both quadrature lines for edges
  encState = ((digitalRead(PIN_ENC_CLK) << 1) | digitalRead(PIN_ENC_DT)) & 0x03;
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_CLK), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_DT),  encISR, CHANGE);

  // Idle I2C lines must read HIGH (pulled up). LOW with no internal pull-up means
  // no pull-up resistors; LOW even with the pull-up means something holds it down.
  pinMode(PIN_SDA, INPUT); pinMode(PIN_SCL, INPUT); delay(5);
  int sdaF = digitalRead(PIN_SDA), sclF = digitalRead(PIN_SCL);
  pinMode(PIN_SDA, INPUT_PULLUP); pinMode(PIN_SCL, INPUT_PULLUP); delay(5);
  Serial.printf("I2C idle: SDA=%d SCL=%d (no pull)  SDA=%d SCL=%d (internal pull-up)\n",
                sdaF, sclF, digitalRead(PIN_SDA), digitalRead(PIN_SCL));
  // A PN532 left mid-transfer by a C3-only reset can hold SCL low; only a power
  // cycle clears it (RSTPDN isn't on the header). Say so instead of hanging.
  uint32_t w0 = millis();
  while (digitalRead(PIN_SCL) == LOW && millis() - w0 < 500) delay(1);
  if (digitalRead(PIN_SCL) == LOW) {
    Serial.println("I2C SCL stuck LOW (PN532 wedged?) -> unplug USB to power-cycle");
    say({sp2_POWER, sp2_CYCLE});   // the OLED shares the stuck bus, so speak it
  }
  Wire.begin(PIN_SDA, PIN_SCL);
  i2cScan();

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("SSD1306 init failed");
  }
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("H2D filament scan\nconnecting WiFi...");
  display.display();

  nfc.begin();
  uint32_t ver = nfc.getFirmwareVersion();
  if (!ver) Serial.println("PN532 not found");
  else {
    Serial.printf("PN532 found: chip PN5%02X fw %d.%d\n",
                  (ver >> 24) & 0xFF, (ver >> 16) & 0xFF, (ver >> 8) & 0xFF);
    nfc.SAMConfig();
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) { delay(250); }

  Serial.printf("firmware build %ld\n", (long)FW_BUILD);
  apiTls.setCACert(ROOT_CA);
  confirmOtaImage();
  prefs.begin("reader", false);
  int s = prefs.getUChar("slot", 0);
  selected = savedSlot = (s < NUM_SLOTS) ? s : 0;
  refreshTrays();
  checkForUpdate();
  lastActivity = millis();
  showPicker();
  if (WiFi.status() == WL_CONNECTED) say({sp2_READY});
  else                               say({sp2_CONNECT, sp2_FAIL});
}

uint32_t speakAt = 0;   // when to announce the slot after the knob stops (0 = none)

void loop() {
  // rotary encoder: consume pending detents (CW = next, CCW = prev)
  int16_t d;
  noInterrupts(); d = encDetents; encDetents = 0; interrupts();
  if (d) {
    if (wake()) {
      showPicker();                           // dark screen: this turn only wakes it
    } else {
      selected = (((selected + d) % NUM_SLOTS) + NUM_SLOTS) % NUM_SLOTS;
      buzzTick(); showPicker();
      speakAt = millis() + SPEAK_SETTLE_MS;   // re-armed by every detent
    }
  }
  if (speakAt && (int32_t)(millis() - speakAt) >= 0) {
    speakAt = 0; saveSlot(); speakSlot(selected, nullptr);
  }
  // encoder push: short = re-send the last tag to the shown slot; hold 2 s = OTA
  SwEvent ev = swEvent();
  if (ev != SW_NONE) Serial.printf("button: %s press\n", ev == SW_LONG ? "long" : "short");
  if (ev != SW_NONE && wake()) { showPicker(); ev = SW_NONE; }
  if (ev == SW_LONG) { buzzTick(); otaCheck(); }
  if (ev == SW_SHORT) {
    buzzTick();
    if (lastUid.length()) {
      Serial.printf("re-send %s -> %s\n", lastUid.c_str(), SLOTS[selected].label);
      sendScan(lastUid);
    } else {
      showPicker();
    }
  }

  // revert from a result screen after the hold window
  if (resultUntil && millis() > resultUntil) { resultUntil = 0; showPicker(); }

  // background refreshes (skipped while a result is showing)
  if (!resultUntil) {
    if (scr != SCR_OFF && millis() - traysAt > TRAY_REFRESH_MS) { refreshTrays(); showPicker(); }
    if (millis() - updCheckAt > UPD_CHECK_MS) { checkForUpdate(); if (scr != SCR_OFF) showPicker(); }
  }
  screenIdle();

  // poll for a tag (short timeout keeps buttons responsive)
  uint8_t uid[7]; uint8_t uidLen = 0;
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLen, 80)) {
    String u = formatUid(uid, uidLen);
    uint32_t now = millis();
    if (u != lastUid || now - lastScanMs > SCAN_COOLDOWN_MS) {
      lastUid = u; lastScanMs = now;
      wake();
      Serial.printf("tag %s -> %s (ams %d tray %d)\n", u.c_str(),
                    SLOTS[selected].label, SLOTS[selected].ams_id, SLOTS[selected].tray_id);
      sendScan(u);
    }
  }
}
