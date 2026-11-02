// Checks src/bme280.h on the PC: the BMP280 datasheet's worked example (3.12) for temperature and pressure, the
// humidity formula against Bosch's floating-point version, and the packed H4/H5 calibration bytes.
//   g++ -std=c++17 -I../src bme280_test.cpp -o /tmp/bme280_test && /tmp/bme280_test
#include <cmath>
#include <cstdio>
#include <initializer_list>
#include "bme280.h"

static int fails = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: " __VA_ARGS__); printf("\n"); fails++; } } while (0)

static double humidityFloat(const Bme280Calib &c, int32_t adcH, int32_t tf) {
  double h = tf - 76800.0;
  h = (adcH - (c.H4 * 64.0 + c.H5 / 16384.0 * h)) *
      (c.H2 / 65536.0 * (1.0 + c.H6 / 67108864.0 * h * (1.0 + c.H3 / 67108864.0 * h)));
  h = h * (1.0 - c.H1 * h / 524288.0);
  return h < 0 ? 0 : h > 100 ? 100 : h;
}

int main() {
  Bme280Calib c{};
  c.T1 = 27504; c.T2 = 26435; c.T3 = -1000;
  c.P1 = 36477; c.P2 = -10685; c.P3 = 3024; c.P4 = 2855; c.P5 = 140; c.P6 = -7; c.P7 = 15500; c.P8 = -14600;
  c.P9 = 6000;
  int32_t tf = c.tFine(519888);
  CHECK(tf == 128422, "t_fine %d, want 128422", tf);
  CHECK(Bme280Calib::centiC(tf) == 2508, "T %d, want 2508", Bme280Calib::centiC(tf));
  uint32_t p = c.pressure(415148, tf);
  // the datasheet's 100653.27 Pa comes from its floating-point formula; the integer one lands within 0.05 Pa
  CHECK(fabs(p / 256.0 - 100653.27) < 0.05, "P %.2f Pa, want 100653.27", p / 256.0);

  // calibration bytes as a typical BME280 has them, with negative H4/H5 to check the sign handling
  uint8_t cal[26] = {}, hb[7] = {0x6A, 0x01, 0x00, 0xEC, 0x9D, 0xFD, 0x1E};  // H2 362, H3 0, H4/H5 negative, H6 30
  cal[25] = 75;
  c.load(cal, hb);
  c.T1 = 27504; c.T2 = 26435; c.T3 = -1000;  // load() zeroed them with the empty T/P block
  CHECK(c.H1 == 75 && c.H2 == 362 && c.H3 == 0 && c.H6 == 30, "H1/H2/H3/H6 %d %d %d %d", c.H1, c.H2, c.H3, c.H6);
  CHECK(c.H4 == (int16_t)(-20 * 16 + 0xD), "H4 %d, want %d", c.H4, -20 * 16 + 0xD);
  CHECK(c.H5 == (int16_t)(-3 * 16 + 0x9), "H5 %d, want %d", c.H5, -3 * 16 + 0x9);
  // and the usual positive values (E4 0x13, E5 0x29, E6 0x03: H4 313, H5 50)
  uint8_t hb2[7] = {0x6A, 0x01, 0x00, 0x13, 0x29, 0x03, 0x1E};
  c.load(cal, hb2);
  CHECK(c.H4 == 313 && c.H5 == 50, "H4/H5 %d %d, want 313 50", c.H4, c.H5);
  for (int32_t adcH : {20000, 26000, 30000, 36000, 42000}) {
    for (int32_t adcT : {480000, 519888, 540000}) {
      int32_t t = c.tFine(adcT);
      double got = c.humidity(adcH, t) / 1024.0, want = humidityFloat(c, adcH, t);
      CHECK(fabs(got - want) < 0.05, "RH adcH %d adcT %d: %.3f, float %.3f", adcH, adcT, got, want);
    }
  }
  printf(fails ? "%d failed\n" : "all passed\n", fails);
  return fails != 0;
}
