// PN532 NFC module over I2C (7-bit address 0x24; the Elechouse V3 in I2C mode): the command frames and the decoding of
// its answers, kept free of Arduino so test/test_core/test_main.cpp can check them on the PC. Only SDA and SCL are
// used (IRQ and RSTO stay unconnected), so the answer's ready bit is polled in the status byte that leads every read.
// Also the once-per-presentation rule for reporting a tag.
#pragma once
#include <stdint.h>
#include <string.h>

static const uint8_t PN532_ADDR = 0x24;

// The frame for TFI D4 and `n` data bytes (command + arguments): 00 00 FF LEN LCS D4 data DCS 00. Returns its length.
static inline uint8_t pn532Frame(uint8_t *out, const uint8_t *data, uint8_t n) {
  uint8_t len = n + 1, sum = 0xD4;
  out[0] = 0x00; out[1] = 0x00; out[2] = 0xFF; out[3] = len; out[4] = (uint8_t)(0x100 - len); out[5] = 0xD4;
  for (uint8_t i = 0; i < n; i++) { out[6 + i] = data[i]; sum += data[i]; }
  out[6 + n] = (uint8_t)(0x100 - sum); out[7 + n] = 0x00;
  return 8 + n;
}

// A read returns a status byte (bit 0: an answer is ready), then the frame.
static inline bool pn532Ready(const uint8_t *r) { return r[0] & 1; }
static inline bool pn532IsAck(const uint8_t *r) {  // r: status + 6 bytes
  static const uint8_t ack[6] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
  return pn532Ready(r) && memcmp(r + 1, ack, 6) == 0;
}

// The answer frame (after the status byte) must be 00 00 FF LEN LCS D5 <resp> ... with both checksums right, and
// <resp> the command code + 1. Returns a pointer to the data after <resp> and sets n to its length, or nullptr.
// `max` is the number of bytes of frame available.
static inline const uint8_t *pn532Answer(const uint8_t *r, uint8_t max, uint8_t resp, uint8_t &n) {
  const uint8_t *f = r + 1;
  if (!pn532Ready(r) || max < 9 || f[0] != 0 || f[1] != 0 || f[2] != 0xFF) return nullptr;
  uint8_t len = f[3];
  if ((uint8_t)(len + f[4]) != 0 || len < 2 || (uint16_t)len + 7 > max || f[5] != 0xD5 || f[6] != resp) return nullptr;
  uint8_t sum = 0;
  for (uint8_t i = 0; i < len; i++) sum += f[5 + i];
  if ((uint8_t)(sum + f[5 + len]) != 0) return nullptr;
  n = len - 2;
  return f + 7;
}

// InListPassiveTarget (106 kbps type A) answer data: NbTg, Tg, SENS_RES(2), SEL_RES, NFCIDLength, NFCID. False when
// no target; else the id in uid (up to 10 bytes) and its length.
static inline bool pn532Uid(const uint8_t *d, uint8_t n, uint8_t *uid, uint8_t &uidLen) {
  if (n < 6 || d[0] < 1) return false;
  uint8_t l = d[5];
  if (l == 0 || l > 10 || n < 6 + l) return false;
  memcpy(uid, d + 6, l);
  uidLen = l;
  return true;
}

// Reports a tag once per presentation: when it appears, or is another one, or has been absent for at least `gapMs`.
struct TagGate {
  uint8_t uid[10]; uint8_t len = 0; uint32_t seen = 0; bool any = false;
  bool report(const uint8_t *id, uint8_t n, uint32_t now, uint32_t gapMs = 1000) {
    bool again = !any || n != len || memcmp(id, uid, n) != 0 || now - seen >= gapMs;
    memcpy(uid, id, n); len = n; seen = now; any = true;
    return again;
  }
};

// "04a1b2c3" (lowercase hex, no separators), for the "TAG" line; out needs 2 * n + 1 bytes.
static inline void pn532Hex(const uint8_t *id, uint8_t n, char *out) {
  static const char *h = "0123456789abcdef";
  for (uint8_t i = 0; i < n; i++) { out[2 * i] = h[id[i] >> 4]; out[2 * i + 1] = h[id[i] & 15]; }
  out[2 * n] = 0;
}
