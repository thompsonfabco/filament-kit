// Host-side (PlatformIO native) tests for lib/panel_core: the serial line parser, lamp timing, button timing, speech
// sample conversion and fade, plus the BME280 compensation against the BMP280 datasheet's worked example (3.12), the
// humidity formula against Bosch's floating-point version, the packed H4/H5 calibration bytes, and the AHT20's CRC-8
// and decoding of a built measurement.  Run: pio test -e native
#include <unity.h>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "aht20.h"
#include "bme280.h"
#include "panel_core.h"

using namespace panel;

void setUp() {}
void tearDown() {}

#define CHECK(cond, ...) do { char msg_[96]; snprintf(msg_, sizeof msg_, __VA_ARGS__); TEST_ASSERT_TRUE_MESSAGE(cond, msg_); } while (0)

static double humidityFloat(const Bme280Calib &c, int32_t adcH, int32_t tf) {
  double h = tf - 76800.0;
  h = (adcH - (c.H4 * 64.0 + c.H5 / 16384.0 * h)) *
      (c.H2 / 65536.0 * (1.0 + c.H6 / 67108864.0 * h * (1.0 + c.H3 / 67108864.0 * h)));
  h = h * (1.0 - c.H1 * h / 524288.0);
  return h < 0 ? 0 : h > 100 ? 100 : h;
}

void test_bme280_and_aht20() {
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
  // AHT20: CRC-8 poly 0x31 init 0xFF ("CRC-8/NRSC-5", check value 0xF7 for "123456789")
  const uint8_t check[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
  CHECK(aht20Crc(check, 9) == 0xF7, "AHT20 CRC %02x, want f7", aht20Crc(check, 9));
  // humidity raw 0x80000 (50.0 %), temperature raw 0x66666 (30.00 C)
  uint8_t m[7] = {0x1C, 0x80, 0x00, 0x06, 0x66, 0x66, 0};
  m[6] = aht20Crc(m, 6);
  uint32_t rh10; int32_t cC;
  CHECK(aht20Decode(m, rh10, cC) && rh10 == 500 && cC == 3000, "AHT20 decode %u %d, want 500 3000", rh10, cC);
  m[6] ^= 1;
  CHECK(!aht20Decode(m, rh10, cC), "AHT20 bad CRC accepted");
  m[6] ^= 1; m[0] |= 0x80;
  CHECK(!aht20Decode(m, rh10, cC), "AHT20 busy accepted");
}

// ---- serial line parser ---------------------------------------------------------

void test_parse_lamps() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("L 2 4", c));
  TEST_ASSERT_EQUAL('L', c.kind);
  TEST_ASSERT_EQUAL(2, c.a);
  TEST_ASSERT_EQUAL(4, c.b);
  TEST_ASSERT_FALSE(parseLine("L 5 0", c));
}

void test_parse_hello() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("?", c));
  TEST_ASSERT_EQUAL('?', c.kind);
  TEST_ASSERT_FALSE(parseLine("Z 1", c));
  TEST_ASSERT_FALSE(parseLine("", c));
}

void test_parse_display_row() {
  Command c;
  const char *line = "D 3 hi";
  TEST_ASSERT_TRUE(parseLine(line, c));
  TEST_ASSERT_EQUAL('D', c.kind);
  TEST_ASSERT_EQUAL(3, c.a);
  TEST_ASSERT_EQUAL_STRING("hi", c.text);
  TEST_ASSERT_TRUE(c.text == line + 4);  // points into the line, not a copy
  TEST_ASSERT_TRUE(parseLine("D 0", c));  // no text: clears the row
  TEST_ASSERT_FALSE(parseLine("D 5 x", c));
  TEST_ASSERT_FALSE(parseLine("D 1x", c));
}

void test_parse_display_row_without_text() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("D 3", c));  // the text must not be read past the line's NUL
  TEST_ASSERT_EQUAL('D', c.kind);
  TEST_ASSERT_EQUAL(3, c.a);
  TEST_ASSERT_NOT_NULL(c.text);
  TEST_ASSERT_EQUAL_STRING("", c.text);
}

void test_parse_beep_defaults_count_1() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("B 880 120", c));
  TEST_ASSERT_EQUAL('B', c.kind);
  TEST_ASSERT_EQUAL(880, c.a);
  TEST_ASSERT_EQUAL(120, c.b);
  TEST_ASSERT_EQUAL(1, c.c);
  TEST_ASSERT_FALSE(parseLine("B 99 120", c));
  TEST_ASSERT_FALSE(parseLine("B 880 2001", c));
  TEST_ASSERT_FALSE(parseLine("B 880 0", c));
}

void test_parse_beep_clamps_count_to_5() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("B 880 120 9", c));
  TEST_ASSERT_EQUAL(5, c.c);
  TEST_ASSERT_TRUE(parseLine("B 880 120 0", c));
  TEST_ASSERT_EQUAL(1, c.c);
}

void test_parse_audio_bounds() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("A 1024", c));
  TEST_ASSERT_EQUAL('A', c.kind);
  TEST_ASSERT_EQUAL(1024, c.a);
  TEST_ASSERT_TRUE(parseLine("A 1", c));
  TEST_ASSERT_FALSE(parseLine("A 0", c));
  TEST_ASSERT_FALSE(parseLine("A 1025", c));
}

void test_parse_volume() {
  Command c;
  TEST_ASSERT_TRUE(parseLine("V 0", c));
  TEST_ASSERT_EQUAL('V', c.kind);
  TEST_ASSERT_EQUAL(0, c.a);
  TEST_ASSERT_TRUE(parseLine("V 100", c));
  TEST_ASSERT_EQUAL(100, c.a);
  TEST_ASSERT_FALSE(parseLine("V 101", c));
  TEST_ASSERT_FALSE(parseLine("V -1", c));
  TEST_ASSERT_FALSE(parseLine("V x", c));
}

// ---- lamps ----------------------------------------------------------------------

void test_lamp_modes_match_fw9() {
  TEST_ASSERT_FALSE(lampLit(0, 1000));
  TEST_ASSERT_TRUE(lampLit(1, 1000));
  TEST_ASSERT_TRUE(lampLit(2, 0));
  TEST_ASSERT_FALSE(lampLit(2, 250));
  TEST_ASSERT_TRUE(lampLit(2, 500));
  // three blinks of 90 ms, then off
  TEST_ASSERT_TRUE(lampLit(3, 0));
  TEST_ASSERT_FALSE(lampLit(3, 90));
  TEST_ASSERT_TRUE(lampLit(3, 180));
  TEST_ASSERT_TRUE(lampLit(3, 360));
  TEST_ASSERT_FALSE(lampLit(3, 540));
  TEST_ASSERT_FALSE(lampLit(3, 720));
  TEST_ASSERT_TRUE(lampLit(4, 0));
  TEST_ASSERT_FALSE(lampLit(4, 60));
  TEST_ASSERT_TRUE(lampLit(4, 120));
  TEST_ASSERT_FALSE(lampLit(5, 0));
}

// ---- button ---------------------------------------------------------------------

void test_button_short_long_debounce() {
  ButtonTimer b;
  TEST_ASSERT_EQUAL(0, b.poll(false, 1000));
  // short press: 'P' on release
  TEST_ASSERT_EQUAL(0, b.poll(true, 1100));
  TEST_ASSERT_EQUAL(0, b.poll(true, 1400));
  TEST_ASSERT_EQUAL('P', b.poll(false, 1500));
  TEST_ASSERT_EQUAL(0, b.poll(false, 1600));
  // long press: 'L' once at 800 ms, nothing on release
  TEST_ASSERT_EQUAL(0, b.poll(true, 2000));
  TEST_ASSERT_EQUAL(0, b.poll(true, 2799));
  TEST_ASSERT_EQUAL('L', b.poll(true, 2800));
  TEST_ASSERT_EQUAL(0, b.poll(true, 3500));
  TEST_ASSERT_EQUAL(0, b.poll(false, 3600));
  // a 10 ms bounce right after the press is ignored
  ButtonTimer d;
  TEST_ASSERT_EQUAL(0, d.poll(true, 5000));
  TEST_ASSERT_EQUAL(0, d.poll(false, 5010));
  TEST_ASSERT_EQUAL(0, d.poll(true, 5020));
  TEST_ASSERT_EQUAL(0, d.poll(true, 5100));
  TEST_ASSERT_EQUAL('P', d.poll(false, 5200));
}

// ---- speech ---------------------------------------------------------------------

void test_to_pcm() {
  TEST_ASSERT_EQUAL_INT16(0, toPcm(128, 100));
  TEST_ASSERT_EQUAL_INT16(32512, toPcm(255, 100));
  TEST_ASSERT_EQUAL_INT16(-32768, toPcm(0, 100));
  TEST_ASSERT_EQUAL_INT16(16256, toPcm(255, 50));
  TEST_ASSERT_EQUAL_INT16(0, toPcm(255, 0));
}

void test_fade_reaches_zero_at_400() {
  TEST_ASSERT_EQUAL_INT16(1000, fadeTowardSilence(1000, 0));
  TEST_ASSERT_EQUAL_INT16(500, fadeTowardSilence(1000, 200));
  TEST_ASSERT_EQUAL_INT16(0, fadeTowardSilence(1000, 400));
  TEST_ASSERT_EQUAL_INT16(0, fadeTowardSilence(-1000, 5000));
  TEST_ASSERT_EQUAL_INT16(-500, fadeTowardSilence(-1000, 200));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_bme280_and_aht20);
  RUN_TEST(test_parse_lamps);
  RUN_TEST(test_parse_hello);
  RUN_TEST(test_parse_display_row);
  RUN_TEST(test_parse_display_row_without_text);
  RUN_TEST(test_parse_beep_defaults_count_1);
  RUN_TEST(test_parse_beep_clamps_count_to_5);
  RUN_TEST(test_parse_audio_bounds);
  RUN_TEST(test_parse_volume);
  RUN_TEST(test_lamp_modes_match_fw9);
  RUN_TEST(test_button_short_long_debounce);
  RUN_TEST(test_to_pcm);
  RUN_TEST(test_fade_reaches_zero_at_400);
  return UNITY_END();
}
