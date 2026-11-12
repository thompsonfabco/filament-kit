// filament-kit reader — ESP32-C3 NFC tag reader for any printer, any slot layout
// -----------------------------------------------------------------------------
// Thin client. Reads an NFC tag UID over I2C (PN532), lets you pick a printer and
// one of its slots with a rotary encoder (shown on an SSD1306 OLED), and POSTs
// {uid, printer, slot} to the filament-kit server's reader API. The server does
// the Spoolman lookup + printer command and returns the result, which we beep
// and show. The printer and slot lists come from the server, so a new
// printer or AMS layout needs no firmware change. API contract: README.md.
//
// Target board: ESP32-C3 Super Mini. All wiring is in the CONFIG block below —
// change pins freely. PN532 and OLED share the I2C bus (different addresses), so
// the whole thing is 2 I2C pins + encoder (CLK/DT/SW) + buzzer.
//
// The pure logic (list parsing, scan statuses, knob menu, saved
// choice) lives in lib/reader_core and is unit-tested on the host (pio test -e native).
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
#include <Update.h>
#include <esp_ota_ops.h>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>
#include <mbedtls/base64.h>
#include <Preferences.h>
#include "secrets.h"         // WIFI_SSID, WIFI_PASS, READER_BASE, READER_TOKEN, OTA_PUBKEY[, READER_BUZZER_ACTIVE_LOW]
#include "fw_build.h"        // FW_BUILD, generated per build by fw_build.py
#include "reader_api.h"
#include "menu.h"

using namespace reader;

// ======================= CONFIG (edit me) ====================================
// Wi-Fi, the server's base URL, the reader token and the OTA public key live in
// secrets.h (not in this file). Everything the reader calls hangs off READER_BASE:
//   GET  printers                 GET  printers/<id>/slots      POST scan
//   GET  healthz (OTA rollback)   GET  fw/manifest.json + fw/firmware.bin (OTA)

// Root CA to validate the server cert. Default: ISRG Root X1 (Let's Encrypt
// chain); define READER_ROOT_CA in secrets.h for a server with another CA.
#ifdef READER_ROOT_CA
static const char* ROOT_CA = READER_ROOT_CA;
#else
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
#endif

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
static const int OLED_COLS   = OLED_W / 6;   // 21 columns at text size 1

// --- Rotary encoder (KY-040 style: CLK/DT quadrature + SW push).
//     Rotate = change slot; press = re-send the last tag; hold 1 s = printer
//     list; hold 4 s = OTA check. If rotation feels reversed, swap CLK and DT. ---
static const int PIN_ENC_CLK = 3;
static const int PIN_ENC_DT  = 4;
static const int PIN_ENC_SW  = 1;
// Push switch wiring: true = switch between GPIO1 and 3V3 (this build; internal
// pull-down, pressed = HIGH). false = switch to GND (internal pull-up, pressed = LOW).
static const bool ENC_SW_TO_VCC = true;

// --- Buzzer (on a PWM-capable pin) ---
//     High-triggered (the default): a magnetic buzzer switched by an N-channel
//     MOSFET such as a BS170, pin HIGH = on, so the pin idles LOW. A reader built
//     with the older 3-pin module (GND, I/O, VCC, PNP driver) is low-triggered:
//     `filament-kit reader setup --buzzer low` writes READER_BUZZER_ACTIVE_LOW 1
//     into secrets.h. A secrets.h written before the setting existed has no line,
//     and those readers were all built with that module, so no line means low.
static const int  PIN_BUZZER        = 0;
#ifdef READER_BUZZER_ACTIVE_LOW
static const bool BUZZER_ACTIVE_LOW = READER_BUZZER_ACTIVE_LOW;
#else
static const bool BUZZER_ACTIVE_LOW = true;
#endif

static const uint32_t SETTLE_MS = 600;   // knob idle time before the slot choice is saved

// Re-scan guard: ignore the same tag if re-read within this window.
static const uint32_t SCAN_COOLDOWN_MS = 2500;
// How long a result stays on screen before reverting to the slot picker.
static const uint32_t RESULT_HOLD_MS   = 4000;
// "Load filament" (queued) prompt stays up longer — you're walking to the AMS.
static const uint32_t QUEUED_HOLD_MS   = 15000;
// Printer + slot lists: refreshed at boot, every LIST_REFRESH_MS while the screen
// is lit, and LIST_AFTER_SET_MS after a set (to show the new contents).
static const uint32_t LIST_REFRESH_MS   = 60000;
static const uint32_t LIST_AFTER_SET_MS = 5000;
// Long labels/names scroll one column per MARQUEE_STEP_MS.
static const uint32_t MARQUEE_STEP_MS  = 350;
// =============================================================================

Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET);
Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);

// URLs, built from READER_BASE in setup()
String urlPrinters, urlScan, urlHealthz, urlManifest, urlBin;

std::vector<PrinterEntry> printers;   // from GET printers
SlotCache slotCache;                  // GET printers/<id>/slots, tagged with that printer's id
std::vector<SlotEntry>& slots = slotCache.slots;
Menu   menu;
Button button;
bool   serverOk = false;              // the last list fetch worked

uint32_t lastScanMs = 0;
String   lastUid = "";
uint32_t resultUntil = 0;

const PrinterEntry* curPrinter() {
  return (menu.printer >= 0 && menu.printer < (int)printers.size()) ? &printers[menu.printer] : nullptr;
}
// Only slots fetched for the selected printer count; after a printer change whose
// fetch failed there are none (the screen says "No slots" and scans are refused).
bool slotsUsable() {
  const PrinterEntry* p = curPrinter();
  return p && slotCache.usableFor(p->id);
}
const SlotEntry* curSlot() {
  if (!slotsUsable()) return nullptr;
  return (menu.slot >= 0 && menu.slot < (int)slots.size()) ? &slots[menu.slot] : nullptr;
}

// ---- buzzer patterns --------------------------------------------------------
// Park the pin at its "off" level (LOW for a high-triggered buzzer, HIGH for the
// low-triggered module). Beeps drive LEDC directly rather than tone(): tone()'s
// async task ends each note at duty 0 and can detach the pin after we've parked it.
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
void buzzUnknown() { beep(2000, 600); }                                    // tag/spool not usable
void buzzError()   { for (int i=0;i<3;i++){ beep(4000,120); delay(80);} }  // unreachable / error
void buzzTick()    { beep(2000, 15); }                                     // knob/button
void buzzQueued()  { beep(2000, 80); delay(80); beep(2000, 350); }         // queued: short-long
void buzzStuck()   { for (int i=0;i<2;i++){ beep(4000,600); delay(200);} } // I2C bus stuck: unplug to power-cycle

// ---- OLED screens -----------------------------------------------------------
bool     updateReady = false;     // a newer signed build is on the server
uint32_t scrollStep = 0;          // marquee position for long names/labels
uint32_t scrollAt = 0;

bool needsScroll() {
  if (menu.mode == MODE_PRINTERS) {
    for (auto& p : printers) if (p.name.size() > (size_t)OLED_COLS - 2) return true;
    return false;
  }
  const PrinterEntry* p = curPrinter();
  const SlotEntry* s = curSlot();
  if (p && p->name.size() > (size_t)OLED_COLS - 6) return true;
  if (s) {
    if (s->label.size() > labelColumns(labelTextSize(s->label.size()))) return true;
    if (slotContents(*s).size() > (size_t)OLED_COLS) return true;
  }
  return false;
}

void header(const String& left, const String& right) {
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(left);
  if (right.length()) {
    display.setCursor(OLED_W - 6 * right.length(), 0);
    display.print(right);
  }
  display.drawFastHLine(0, 11, OLED_W, SSD1306_WHITE);
}

void showPicker() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  const PrinterEntry* p = curPrinter();
  const SlotEntry* s = curSlot();
  if (!p) {
    header("filament-kit reader", "");
    display.setTextSize(1);
    display.setCursor(0, 20);
    if (WiFi.status() != WL_CONNECTED) display.print("No WiFi");
    else if (!serverOk)                display.print("Server unreachable\nretrying every 60 s");
    else                               display.print("No printers set up\non the server");
    if (updateReady) { display.setCursor(0, 54); display.print("update: hold knob 4s"); }
    display.display();
    return;
  }
  String right = updateReady ? String("UPD")
                             : (!s ? String("") : String(menu.slot + 1) + "/" + String(slots.size()));
  size_t nameCols = OLED_COLS - (right.length() ? right.length() + 1 : 0);
  header(marquee(p->name, nameCols, scrollStep).c_str(), right);
  if (!s) {
    display.setTextSize(1);
    display.setTextSize(2);
    display.setCursor(0, 20);
    display.print("No slots");
    display.setTextSize(1);
    display.setCursor(0, 54);
    display.print(serverOk ? "none reported" : "server unreachable");
    display.display();
    return;
  }
  int ts = labelTextSize(s->label.size());
  display.setTextSize(ts);
  display.setCursor(0, ts == 3 ? 20 : 24);
  display.print(marquee(s->label, labelColumns(ts), scrollStep).c_str());
  display.setTextSize(1);
  display.setCursor(0, 54);
  display.print(marquee(slotContents(*s), OLED_COLS, scrollStep).c_str());
  display.display();
}

// Printer list: up to 4 rows around the cursor, the cursor row inverted.
void showPrinterList() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  header("Pick printer", String(menu.cursor + 1) + "/" + String(printers.size()));
  const int rows = 4;
  int first = menu.cursor - rows / 2;
  if (first > (int)printers.size() - rows) first = (int)printers.size() - rows;
  if (first < 0) first = 0;
  for (int r = 0; r < rows && first + r < (int)printers.size(); r++) {
    int i = first + r;
    int y = 14 + r * 12;
    bool on = i == menu.cursor;
    if (on) display.fillRect(0, y - 1, OLED_W, 11, SSD1306_WHITE);
    display.setTextColor(on ? SSD1306_BLACK : SSD1306_WHITE);
    display.setCursor(2, y + 1);
    std::string name = on ? marquee(printers[i].name, OLED_COLS - 1, scrollStep)
                          : printers[i].name.substr(0, OLED_COLS - 1);
    display.print(name.c_str());
  }
  display.setTextColor(SSD1306_WHITE);
  display.display();
}

void redraw() {
  if (menu.mode == MODE_PRINTERS) showPrinterList(); else showPicker();
}

// line1 on top, then either one big word (big2) or small wrapped text.
void showResult(const char* line1, const char* line2, bool big2, uint32_t holdMs = RESULT_HOLD_MS) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(line1);
  display.drawFastHLine(0, 11, OLED_W, SSD1306_WHITE);
  display.setTextSize(big2 ? 2 : 1);
  display.setCursor(0, big2 ? 24 : 16);
  display.print(line2);
  display.display();
  resultUntil = millis() + holdMs;
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

// ---- HTTPS: one kept-alive TLS connection to the server --------------------
// Taps, list refreshes and update checks share it, so a tap skips the ~1 s TLS
// handshake while the server holds the connection open. A stale socket fails
// fast and is retried once on a fresh connection (a scan is idempotent: the same
// tag on the same slot just sets it again).
WiFiClientSecure apiTls;
HTTPClient       apiHttp;

// A String sink that refuses bytes past `cap`, so a huge (or endless chunked)
// reply cannot exhaust the heap; HTTPClient::writeToStream stops on the refusal.
class CappedString : public Stream {
 public:
  CappedString(String& s, size_t cap) : s_(s), cap_(cap) {}
  bool over = false;
  size_t write(uint8_t c) override { return write(&c, 1); }
  size_t write(const uint8_t* b, size_t n) override {
    if (s_.length() + n > cap_) { over = true; return 0; }
    s_.concat((const char*)b, n);
    return n;
  }
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
 private:
  String& s_;
  size_t cap_;
};
static const int HTTP_TOO_BIG = -100;   // our code: reply refused for size

int apiRequest(const String& url, const char* body, String& resp) {
  int code = -1;
  for (int attempt = 0; attempt < 2; attempt++) {
    apiHttp.setReuse(true);
    apiHttp.setTimeout(6000);
    if (!apiHttp.begin(apiTls, url)) { apiTls.stop(); continue; }
    apiHttp.addHeader("X-Auth-Token", READER_TOKEN);
    if (body) { apiHttp.addHeader("Content-Type", "application/json"); code = apiHttp.POST(body); }
    else      code = apiHttp.GET();
    if (code > 0) {
      resp = "";
      int len = apiHttp.getSize();          // -1 = unknown (chunked)
      if (responseTooBig(len)) {
        Serial.printf("%s: reply of %d bytes refused\n", url.c_str(), len);
        apiHttp.end(); apiTls.stop();
        return HTTP_TOO_BIG;
      }
      if (len > 0) resp.reserve(len);
      CappedString sink(resp, MAX_RESPONSE_BYTES);
      int r = apiHttp.writeToStream(&sink);
      if (r < 0 || sink.over) {
        Serial.printf("%s: reply over %u bytes or cut (%d)\n", url.c_str(), (unsigned)MAX_RESPONSE_BYTES, r);
        resp = "";
        apiHttp.end(); apiTls.stop();
        return sink.over ? HTTP_TOO_BIG : r;
      }
      apiHttp.end();
      return code;
    }
    apiHttp.end(); apiTls.stop();
  }
  return code;
}

// ---- remembered choice (NVS: survives reboots and OTA updates) --------------
// The printer by id and the slot by LABEL, so a layout change (an AMS added or
// removed) keeps the choice whenever that label still exists.
Preferences prefs;
std::string savedPrinter, savedLabel;
void savePrinter(const std::string& id) {
  if (id == savedPrinter) return;
  prefs.putString("printer", id.c_str());
  savedPrinter = id;
}
void saveSlot(const std::string& label) {
  if (label == savedLabel) return;
  prefs.putString("slot_label", label.c_str());
  savedLabel = label;
}

// ---- printer + slot lists ---------------------------------------------------
uint32_t listsAt = 0;

// Slots of the selected printer; keeps `label` selected when it still exists.
// A failed fetch keeps the last good list only when it is this printer's.
bool fetchSlots(const std::string& label) {
  const PrinterEntry* p = curPrinter();
  if (!p) { slotCache.apply("", false, {}); menu.slot = 0; return false; }
  String resp;
  String url = joinUrl(READER_BASE, "printers/" + urlEncode(p->id) + "/slots").c_str();
  int code = apiRequest(url, nullptr, resp);
  std::vector<SlotEntry> fresh;
  bool ok = code == 200 && parseSlots(resp.c_str(), fresh);
  resp = "";                                   // free the text before keeping the list
  if (!ok) Serial.printf("slots %s: HTTP %d\n", p->id.c_str(), code);
  slotCache.apply(p->id, ok, std::move(fresh));
  if (ok) {
    int i = findSlot(slots, label);
    menu.slot = i < 0 ? 0 : i;
  }
  return ok;
}

uint32_t settleAt = 0;   // when to save the selection after the knob stops (0 = none)

// Both lists. Re-selects the SAVED printer and slot label (the current ones only
// while a knob turn is not saved yet), so a unit that drops out for one refresh
// does not move the choice for good. On a failure the last good lists stay.
void refreshLists() {
  listsAt = millis();
  if (WiFi.status() != WL_CONNECTED) { serverOk = false; return; }
  std::string wantPrinter = !savedPrinter.empty() ? savedPrinter
                                                  : (curPrinter() ? curPrinter()->id : std::string());
  std::string wantLabel = wantedLabel(savedLabel, curSlot() ? curSlot()->label : std::string(),
                                      settleAt != 0 && menu.mode == MODE_SLOTS);
  String resp;
  int code = apiRequest(urlPrinters, nullptr, resp);
  bool ok = code == 200 && parsePrinters(resp.c_str(), printers);
  resp = "";
  if (!ok) {
    Serial.printf("printers: HTTP %d\n", code);
    serverOk = false;
    return;
  }
  int i = findPrinter(printers, wantPrinter);
  menu.printer = i < 0 ? 0 : i;
  serverOk = fetchSlots(wantLabel);
}

// ---- POST a scan --------------------------------------------------------------
void sendScan(const String& uid) {
  const PrinterEntry* p = curPrinter();
  const SlotEntry* s = curSlot();
  if (WiFi.status() != WL_CONNECTED) { showResult("Scan", "No WiFi", true); buzzError(); return; }
  if (!p || !s) { showResult("Scan", "No slot", true); buzzError(); return; }
  // copy: a refresh after this call must not pull the strings out from under us
  PrinterEntry printer = *p;
  SlotEntry slot = *s;

  std::string payload = scanBody(uid.c_str(), printer.id, slot.label, false);
  String resp;
  uint32_t t0 = millis();
  int code = apiRequest(urlScan, payload.c_str(), resp);
  Serial.printf("scan round trip %lu ms\n", millis() - t0);
  if (code <= 0) {
    char tlsErr[120] = "";
    apiTls.lastError(tlsErr, sizeof(tlsErr));
    Serial.printf("POST failed: %d %s | TLS: %s | WiFi %s RSSI %d | heap %u\n", code,
                  HTTPClient::errorToString(code).c_str(), tlsErr,
                  WiFi.status() == WL_CONNECTED ? "up" : "DOWN", WiFi.RSSI(), ESP.getFreeHeap());
  } else {
    Serial.printf("POST %d: %s\n", code, resp.c_str());
  }

  ScanResult r = parseScanResult(code, resp.c_str());
  char head[48];
  snprintf(head, sizeof(head), "%s  %s", slot.label.c_str(), headline(r.status));
  switch (feedbackFor(r.status)) {
    case FB_OK: {
      const std::string& what = !r.filament.empty() ? r.filament : r.message;
      showResult(head, what.empty() ? "set" : what.c_str(), false);
      buzzOk();
      listsAt = millis() - LIST_REFRESH_MS + LIST_AFTER_SET_MS;   // re-read contents in ~5 s
      break;
    }
    case FB_QUEUED: {
      // Empty slot: the server holds the setting and applies it once the printer
      // reads the loaded filament. A success, just pending.
      char line1[48], line2[96];
      snprintf(line1, sizeof(line1), "Load into %s", slot.label.c_str());
      snprintf(line2, sizeof(line2), "%s\nwill set when loaded",
               !r.filament.empty() ? r.filament.c_str() : "filament");
      showResult(line1, line2, false, QUEUED_HOLD_MS);
      buzzQueued();
      break;
    }
    case FB_UNKNOWN:
      showResult(head, r.message.empty() ? headline(r.status) : r.message.c_str(), r.message.empty());
      buzzUnknown();
      break;
    default:
      showResult(head, r.message.empty() ? headline(r.status) : r.message.c_str(), r.message.empty());
      buzzError();
      break;
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

bool swPressed() { return digitalRead(PIN_ENC_SW) == (ENC_SW_TO_VCC ? HIGH : LOW); }

// ---- OTA --------------------------------------------------------------------
// Manifest {"build": <unix time>, "size": N, "sha256": "<hex>", "sig": "<base64 DER>"}.
// The image is streamed into the inactive OTA slot while hashing; it's only
// committed if size, SHA-256 and the ECDSA signature (over the SHA-256) all
// check out. The new image boots "pending verify" and marks itself valid once
// Wi-Fi is up and <READER_BASE>/healthz answers 200 (see confirmOtaImage);
// otherwise the bootloader rolls back to the previous image on the next reset.
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

bool httpsGet(HTTPClient& http, WiFiClientSecure& tls, const String& url) {
  tls.setCACert(ROOT_CA);
  http.setTimeout(15000);
  if (!http.begin(tls, url)) return false;
  http.addHeader("X-Auth-Token", READER_TOKEN);
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
  if (apiRequest(urlManifest, nullptr, resp) != 200) return false;
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
  if (!httpsGet(http, tls, urlBin) || (size_t)http.getSize() != size) {
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

// New OTA image: keep it only if it can reach the server's reader API.
void confirmOtaImage() {
  const esp_partition_t* run = esp_ota_get_running_partition();
  esp_ota_img_states_t st;
  if (esp_ota_get_state_partition(run, &st) != ESP_OK) st = ESP_OTA_IMG_UNDEFINED;
  Serial.printf("running %s, OTA state %d\n", run->label, (int)st);
  if (st != ESP_OTA_IMG_PENDING_VERIFY) return;
  bool ok = false;
  if (WiFi.status() == WL_CONNECTED) {
    String resp;
    ok = apiRequest(urlHealthz, nullptr, resp) == 200;
  }
#ifdef OTA_TEST_FAIL_HEALTH  // rollback drill: PLATFORMIO_BUILD_FLAGS=-DOTA_TEST_FAIL_HEALTH
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

// ---- screen sleep (OLED burn-in) --------------------------------------------
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
  // seed encoder state and watch both quadrature lines for edges
  encState = ((digitalRead(PIN_ENC_CLK) << 1) | digitalRead(PIN_ENC_DT)) & 0x03;
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_CLK), encISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_DT),  encISR, CHANGE);

  urlPrinters = joinUrl(READER_BASE, "printers").c_str();
  urlScan     = joinUrl(READER_BASE, "scan").c_str();
  urlHealthz  = joinUrl(READER_BASE, "healthz").c_str();
  urlManifest = joinUrl(READER_BASE, "fw/manifest.json").c_str();
  urlBin      = joinUrl(READER_BASE, "fw/firmware.bin").c_str();

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
    buzzStuck();                   // the OLED shares the stuck bus: two long beeps (and serial) say it
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
  display.print("filament-kit reader\nconnecting WiFi...");
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
  savedPrinter = prefs.getString("printer", "").c_str();
  savedLabel   = prefs.getString("slot_label", "").c_str();
  if (prefs.isKey("slot")) prefs.remove("slot");   // the H2D-only firmware's slot index
  refreshLists();
  checkForUpdate();
  lastActivity = millis();
  redraw();
  if (WiFi.status() != WL_CONNECTED || !serverOk) buzzError();
  else                                            buzzOk();
}

bool swallowPress = false;  // this press woke a dark screen: ignore the rest of it

void handleAction(Action a) {
  switch (a) {
    case ACT_SLOT_MOVED:
    case ACT_CURSOR_MOVED:
      buzzTick(); scrollStep = 0; redraw();
      settleAt = millis() + SETTLE_MS;        // re-armed by every detent
      break;
    case ACT_RESEND:
      buzzTick();
      if (lastUid.length() && curSlot()) {
        Serial.printf("re-send %s -> %s\n", lastUid.c_str(), curSlot()->label.c_str());
        sendScan(lastUid);
      } else {
        redraw();
      }
      break;
    case ACT_OPEN_LIST:
      buzzTick(); scrollStep = 0; redraw();
      settleAt = millis() + SETTLE_MS;
      break;
    case ACT_CLOSE_LIST:
      settleAt = 0; scrollStep = 0; redraw();
      break;
    case ACT_PICK_PRINTER:
      buzzTick(); settleAt = 0; scrollStep = 0;
      if (curPrinter()) savePrinter(curPrinter()->id);
      showProgress(curPrinter() ? curPrinter()->name.c_str() : "Printer", "loading slots...", -1);
      serverOk = fetchSlots(savedLabel);   // fails -> no slots, no scans (never the old printer's)
      listsAt = millis();
      redraw();
      break;
    case ACT_OTA:
      buzzTick(); otaCheck();
      break;
    case ACT_NO_PRINTERS:
      showResult("Printers", serverOk ? "none on the server" : "server unreachable", false);
      buzzError();
      break;
    default:
      break;
  }
}

void loop() {
  uint32_t now = millis();
  int np = (int)printers.size(), ns = slotsUsable() ? (int)slots.size() : 0;

  // rotary encoder: consume pending detents (CW = next, CCW = prev)
  int16_t d;
  noInterrupts(); d = encDetents; encDetents = 0; interrupts();
  if (d) {
    if (wake()) redraw();                     // dark screen: this turn only wakes it
    else { resultUntil = 0; handleAction(menu.rotate(d, np, ns, now)); }
  }
  if (settleAt && (int32_t)(millis() - settleAt) >= 0) {
    settleAt = 0;
    if (menu.mode == MODE_SLOTS && curSlot()) saveSlot(curSlot()->label);
  }

  // encoder push: short = re-send; hold 1 s = printer list; hold 4 s = OTA
  BtnEvent ev = button.update(swPressed(), millis());
  if (ev != BTN_NONE) {
    Serial.printf("button: %s\n", ev == BTN_SHORT ? "short" : ev == BTN_CUE ? "1 s" :
                                  ev == BTN_MENU ? "menu" : "ota");
    if (wake()) { redraw(); swallowPress = ev == BTN_CUE; ev = BTN_NONE; }
    else if (swallowPress && ev != BTN_CUE) { swallowPress = false; ev = BTN_NONE; }
  }
  if (ev == BTN_CUE) { if (!swallowPress) buzzTick(); }
  else if (ev != BTN_NONE) { resultUntil = 0; handleAction(menu.button(ev, np, millis())); }
  if (menu.tick(millis()) == ACT_CLOSE_LIST) redraw();

  // revert from a result screen after the hold window
  if (resultUntil && millis() > resultUntil) { resultUntil = 0; redraw(); }

  // background refreshes (skipped while a result or the printer list is showing)
  if (!resultUntil && menu.mode == MODE_SLOTS && !settleAt) {
    if (scr != SCR_OFF && millis() - listsAt > LIST_REFRESH_MS) { refreshLists(); redraw(); }
    if (millis() - updCheckAt > UPD_CHECK_MS) { checkForUpdate(); if (scr != SCR_OFF) redraw(); }
  }
  // scroll long names/labels
  if (!resultUntil && scr != SCR_OFF && millis() - scrollAt > MARQUEE_STEP_MS) {
    scrollAt = millis();
    if (needsScroll()) { scrollStep++; redraw(); }
  }
  screenIdle();

  // poll for a tag (short timeout keeps buttons responsive)
  uint8_t uid[7]; uint8_t uidLen = 0;
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLen, 80)) {
    String u = formatUid(uid, uidLen);
    uint32_t t = millis();
    if (u != lastUid || t - lastScanMs > SCAN_COOLDOWN_MS) {
      lastUid = u; lastScanMs = t;
      wake();
      if (menu.mode == MODE_PRINTERS) { menu.mode = MODE_SLOTS; }   // a tap closes the list
      Serial.printf("tag %s -> %s / %s\n", u.c_str(),
                    curPrinter() ? curPrinter()->id.c_str() : "-", curSlot() ? curSlot()->label.c_str() : "-");
      sendScan(u);
    }
  }
}
