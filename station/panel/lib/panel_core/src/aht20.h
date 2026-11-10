// AHT20 humidity / temperature sensor (I2C 0x38; often paired with a BMP280 on one board): decoding of its 7-byte
// measurement (status, 20-bit humidity, 20-bit temperature, CRC), kept free of Arduino so test/test_core/test_main.cpp
// can check it on the PC.
#pragma once
#include <stdint.h>

// CRC-8, polynomial 0x31, initial 0xFF (AHT20 datasheet)
static inline uint8_t aht20Crc(const uint8_t *d, uint8_t n) {
  uint8_t crc = 0xFF;
  for (uint8_t i = 0; i < n; i++) {
    crc ^= d[i];
    for (uint8_t b = 0; b < 8; b++) crc = crc & 0x80 ? (uint8_t)(crc << 1 ^ 0x31) : (uint8_t)(crc << 1);
  }
  return crc;
}

// d: the 7 bytes read after a measurement. False if busy or the CRC is wrong; else %RH * 10 and degrees C * 100.
static inline bool aht20Decode(const uint8_t *d, uint32_t &rhTenths, int32_t &centiC) {
  if (d[0] & 0x80 || aht20Crc(d, 6) != d[6]) return false;
  uint32_t rawH = (uint32_t)d[1] << 12 | (uint32_t)d[2] << 4 | d[3] >> 4;
  uint32_t rawT = ((uint32_t)d[3] & 0x0F) << 16 | (uint32_t)d[4] << 8 | d[5];
  rhTenths = (uint32_t)(((uint64_t)rawH * 1000 + (1 << 19)) >> 20);
  centiC = (int32_t)(((int64_t)rawT * 20000 + (1 << 19)) >> 20) - 5000;
  return true;
}
