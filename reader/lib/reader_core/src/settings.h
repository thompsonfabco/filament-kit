// The reader's settings, written into the device over USB at setup time (not compiled in), and the line protocol
// that carries them. Pure logic, host-tested (pio test -e native).
//
// The kit (`filament-kit reader setup`, or the setup page in a browser) talks to the reader over its USB serial
// port, one line each way at 115200 baud:
//   kit:    FK?                  reader: FK-READER <build> configured=<0|1> wifi=<ok|fail|-> server=<ok|fail|unauth|->
//   kit:    FK-SET <json>        reader: FK-OK (then it restarts with the new settings) or FK-ERR <reason>
// <json> is one line: {"ssid", "pass", "base", "token"[, "ota_key"][, "root_ca"][, "buzzer_low"]}. The reader never
// sends a setting back. wifi/server say how the last start went ("-": not tried yet).
#pragma once

#include <cstddef>
#include <string>

namespace reader {

static const size_t MAX_LINE = 6144;       // an FK-SET line with a root CA and an OTA key fits
static const size_t MAX_PEM = 3000;

struct Settings {
  std::string ssid;      // Wi-Fi name, 1-32 bytes
  std::string pass;      // Wi-Fi password, at most 63 bytes (empty: an open network)
  std::string base;      // the kit's reader API, https://.../reader (no trailing slash)
  std::string token;     // the reader token (X-Auth-Token)
  std::string otaKey;    // PEM public key OTA images must be signed with; empty: every update is refused
  std::string rootCa;    // PEM root CA of the server; empty: ISRG Root X1 (Let's Encrypt)
  bool buzzerLow = false;  // the older low-triggered 3-pin buzzer module
};

// The JSON of an FK-SET line into `out`. False with a short reason (sent back as FK-ERR) when a setting is missing,
// too long or the wrong shape; `out` is then unchanged.
bool parseSettings(const char* json, Settings& out, std::string& why);

enum Command { CMD_NONE, CMD_HELLO, CMD_SET, CMD_OTHER };

// One received line: FK? / FK-SET <json> / anything else. `arg` is the JSON of an FK-SET.
Command command(const std::string& line, std::string& arg);

// Collects serial bytes into lines (\n ends one, \r is dropped). A line longer than MAX_LINE is thrown away whole.
class LineReader {
 public:
  // True when `c` completed a line, which is then in `line`.
  bool push(char c, std::string& line);
 private:
  std::string buf_;
  bool overflow_ = false;
};

// The FK-READER answer.
std::string helloLine(long build, bool configured, const char* wifi, const char* server);

}  // namespace reader
