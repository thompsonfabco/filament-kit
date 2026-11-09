// BME280 / BMP280 compensation: Bosch's integer formulas (datasheet 4.2.3 and 8.2), kept free of Arduino so
// test/test_core/test_main.cpp can check them against the datasheet's worked example on the PC.
#pragma once
#include <stdint.h>

struct Bme280Calib {
  uint16_t T1, P1; int16_t T2, T3, P2, P3, P4, P5, P6, P7, P8, P9;
  uint8_t H1, H3; int16_t H2, H4, H5; int8_t H6;

  // c: registers 0x88-0xA1 (26 bytes); h: 0xE1-0xE7 (7 bytes, BME280 only)
  void load(const uint8_t *c, const uint8_t *h) {
    auto u16 = [&](int i) { return (uint16_t)(c[i] | c[i + 1] << 8); };
    T1 = u16(0); T2 = u16(2); T3 = u16(4);
    P1 = u16(6); P2 = u16(8); P3 = u16(10); P4 = u16(12); P5 = u16(14);
    P6 = u16(16); P7 = u16(18); P8 = u16(20); P9 = u16(22);
    H1 = c[25];
    if (h) {
      H2 = (int16_t)(h[0] | h[1] << 8); H3 = h[2];
      H4 = (int16_t)((int8_t)h[3] * 16 | (h[4] & 0x0F));
      H5 = (int16_t)((int8_t)h[5] * 16 | h[4] >> 4);
      H6 = (int8_t)h[6];
    }
  }

  int32_t tFine(int32_t adcT) const {
    int32_t var1 = ((((adcT >> 3) - ((int32_t)T1 << 1))) * T2) >> 11;
    int32_t var2 = (((((adcT >> 4) - (int32_t)T1) * ((adcT >> 4) - (int32_t)T1)) >> 12) * T3) >> 14;
    return var1 + var2;
  }

  static int32_t centiC(int32_t tf) { return (tf * 5 + 128) >> 8; }

  // Pa * 256 (0 if the calibration is broken)
  uint32_t pressure(int32_t adcP, int32_t tf) const {
    int64_t var1 = (int64_t)tf - 128000, var2 = var1 * var1 * P6;
    var2 += (var1 * P5) << 17;
    var2 += (int64_t)P4 << 35;
    var1 = ((var1 * var1 * P3) >> 8) + ((var1 * P2) << 12);
    var1 = (((int64_t)1 << 47) + var1) * P1 >> 33;
    if (!var1) return 0;
    int64_t p = 1048576 - adcP;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = ((int64_t)P9 * (p >> 13) * (p >> 13)) >> 25;
    var2 = ((int64_t)P8 * p) >> 19;
    return (uint32_t)(((p + var1 + var2) >> 8) + ((int64_t)P7 << 4));
  }

  // %RH * 1024
  uint32_t humidity(int32_t adcH, int32_t tf) const {
    int32_t v = tf - 76800;
    v = (((((adcH << 14) - ((int32_t)H4 << 20) - ((int32_t)H5 * v)) + 16384) >> 15) *
         (((((((v * (int32_t)H6) >> 10) * (((v * (int32_t)H3) >> 11) + 32768)) >> 10) + 2097152) *
           (int32_t)H2 + 8192) >> 14));
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)H1) >> 4);
    v = v < 0 ? 0 : v > 419430400 ? 419430400 : v;
    return (uint32_t)(v >> 12);
  }
};
