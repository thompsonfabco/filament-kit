// The bytes an OTA image's `sig2` signature covers (pure, host-testable).
// tools/ota_publish.py build_digest() signs SHA-256 of the same bytes; test_main.cpp and
// tools/test_ota_publish.py both pin them on one fixed vector so the two cannot drift apart.
#pragma once
#include <cstdint>
#include <string>

namespace reader {

// "fk-reader-ota\x01" || image SHA-256 (32 bytes) || build as 8 bytes big-endian.
// The reader takes SHA-256 of this and checks the ECDSA signature against it.
inline std::string otaSigPreimage(const uint8_t imgHash[32], long build) {
  std::string s("fk-reader-ota\x01");
  s.append(reinterpret_cast<const char*>(imgHash), 32);
  for (int i = 0; i < 8; i++) s.push_back((char)(uint8_t)((uint64_t)build >> (56 - 8 * i)));
  return s;
}

}  // namespace reader
