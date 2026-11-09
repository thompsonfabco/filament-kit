#include "panel_core.h"
#include <stdio.h>

namespace panel {

static const uint32_t FLASH_MS = 250;  // flash: 2 Hz
static const uint32_t RAPID_MS = 60;   // rapid blink: about 8 Hz
static const uint32_t BLINK3_MS = 90;  // three fast blinks: 90 ms on / 90 ms off
static const uint32_t FADE_SAMPLES = 400;

bool parseLine(const char *s, Command &out) {
  out = Command{s[0], 0, 0, 0, nullptr};
  switch (s[0]) {
    case '?':
      return true;
    case 'L':
      if (sscanf(s + 1, "%d %d", &out.a, &out.b) != 2) return false;
      return out.a >= 0 && out.a <= 4 && out.b >= 0 && out.b <= 4;
    case 'D':
      if (s[1] != ' ' || s[2] < '0' || s[2] > '4' || (s[3] != ' ' && s[3] != 0)) return false;
      out.a = s[2] - '0';
      out.text = s[3] ? s + 4 : "";  // "D 3" ends at s[3]: s + 4 would be past its NUL
      return true;
    case 'B': {
      int n = 1;
      if (sscanf(s + 1, "%d %d %d", &out.a, &out.b, &n) < 2) return false;
      if (out.a < 100 || out.a > 10000 || out.b <= 0 || out.b > 2000) return false;
      out.c = n < 1 ? 1 : n > 5 ? 5 : n;
      return true;
    }
    case 'A':
      return sscanf(s + 1, "%d", &out.a) == 1 && out.a > 0 && out.a <= 1024;
    case 'V':
      return sscanf(s + 1, "%d", &out.a) == 1 && out.a >= 0 && out.a <= 100;
  }
  return false;
}

bool lampLit(uint8_t mode, uint32_t t) {
  switch (mode) {
    case 1: return true;
    case 2: return (t / FLASH_MS) % 2 == 0;
    case 3: return t < 6 * BLINK3_MS && (t / BLINK3_MS) % 2 == 0;
    case 4: return (t / RAPID_MS) % 2 == 0;
  }
  return false;
}

char ButtonTimer::poll(bool pressed, uint32_t now) {
  if (pressed != down) {
    if (now - changed < DEBOUNCE_MS) return 0;
    down = pressed; changed = now;
    if (down) {
      pressedAt = now; fired = false;
      return 0;
    }
    return fired ? 0 : 'P';
  }
  changed = now;
  if (down && !fired && now - pressedAt >= LONG_MS) { fired = true; return 'L'; }
  return 0;
}

int16_t toPcm(uint8_t sample, uint8_t volumePct) {
  int32_t v = ((int32_t)sample - 128) * 256 * (int32_t)volumePct / 100;
  return v > 32767 ? 32767 : v < -32768 ? -32768 : (int16_t)v;
}

int16_t fadeTowardSilence(int16_t last, uint32_t samplesSinceEmpty) {
  if (samplesSinceEmpty >= FADE_SAMPLES) return 0;
  return (int16_t)((int32_t)last * (int32_t)(FADE_SAMPLES - samplesSinceEmpty) / (int32_t)FADE_SAMPLES);
}

}  // namespace panel
