#include "settings.h"

#include <ArduinoJson.h>
#include <cstdio>
#include <cstring>

namespace reader {

namespace {

bool tokenChars(const std::string& s) {
  for (char c : s)
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-'))
      return false;
  return true;
}

bool pem(const std::string& s, const char* kind) {
  return s.size() <= MAX_PEM && s.rfind(std::string("-----BEGIN ") + kind + "-----", 0) == 0 &&
         s.find(std::string("-----END ") + kind + "-----") != std::string::npos;
}

std::string str(JsonVariantConst v) { return v.is<const char*>() ? std::string(v.as<const char*>()) : std::string(); }

}  // namespace

bool parseSettings(const char* json, Settings& out, std::string& why) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok || !doc.is<JsonObjectConst>()) {
    why = "not a JSON object";
    return false;
  }
  JsonObjectConst o = doc.as<JsonObjectConst>();
  Settings s;
  s.ssid = str(o["ssid"]);
  s.pass = str(o["pass"]);
  s.base = str(o["base"]);
  s.token = str(o["token"]);
  s.otaKey = str(o["ota_key"]);
  s.rootCa = str(o["root_ca"]);
  s.buzzerLow = o["buzzer_low"].is<bool>() && o["buzzer_low"].as<bool>();
  while (!s.base.empty() && s.base.back() == '/') s.base.pop_back();
  if (s.ssid.empty() || s.ssid.size() > 32) { why = "ssid must be 1 to 32 bytes"; return false; }
  if (s.pass.size() > 63) { why = "pass must be at most 63 bytes"; return false; }
  if (s.base.rfind("https://", 0) != 0 || s.base.size() > 200) { why = "base must be an https address"; return false; }
  if (s.token.size() < 16 || s.token.size() > 128 || !tokenChars(s.token)) { why = "token is not a reader token"; return false; }
  if (!s.otaKey.empty() && !pem(s.otaKey, "PUBLIC KEY")) { why = "ota_key is not a PEM public key"; return false; }
  if (!s.rootCa.empty() && !pem(s.rootCa, "CERTIFICATE")) { why = "root_ca is not a PEM certificate"; return false; }
  out = s;
  return true;
}

Command command(const std::string& line, std::string& arg) {
  if (line.empty()) return CMD_NONE;
  if (line == "FK?") return CMD_HELLO;
  if (line.rfind("FK-SET ", 0) == 0) { arg = line.substr(7); return CMD_SET; }
  return CMD_OTHER;
}

bool LineReader::push(char c, std::string& line) {
  if (c == '\r') return false;
  if (c == '\n') {
    bool whole = !overflow_;
    overflow_ = false;
    if (whole) line.swap(buf_);
    buf_.clear();
    return whole;
  }
  if (overflow_) return false;
  if (buf_.size() >= MAX_LINE) { overflow_ = true; buf_.clear(); return false; }
  buf_.push_back(c);
  return false;
}

std::string helloLine(long build, bool configured, const char* wifi, const char* server) {
  char out[96];
  snprintf(out, sizeof(out), "FK-READER %ld configured=%d wifi=%s server=%s", build, configured ? 1 : 0, wifi, server);
  return out;
}

}  // namespace reader
