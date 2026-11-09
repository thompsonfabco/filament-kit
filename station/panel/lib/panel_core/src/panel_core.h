// Pure logic of the intake panel firmware: serial line parsing, lamp and button timing, speech sample conversion.
// No Arduino headers, so it runs in the host tests (test/test_core). Protocol: see ../../../src/main.cpp.
#pragma once
#include <stdint.h>

namespace panel {

// One parsed serial line from the PC. kind and the fields it uses:
//   '?'  HELLO request
//   'L'  lamps: a = yellow (Hold) mode, b = red (Discard) mode, each 0-4
//   'D'  display row: a = row 0-4. The text is not copied: it is whatever follows "D <row> " in the line, i.e.
//        line + 4, or empty when the line is just "D <row>" (clears the row)
//   'B'  beep: a = hz 100-10000, b = ms 1-2000, c = count (default 1, clamped to 1-5)
//   'A'  speech frame: a = n raw bytes to follow, 1-1024
//   'V'  speaker volume: a = percent 0-100
struct Command { char kind; int a, b, c; };

// True and fills out for a valid line; false for an unknown command or an argument out of range (out is then
// unspecified).
bool parseLine(const char *line, Command &out);

// Whether a lamp in `mode` is lit `msSinceModeSet` ms after the mode was set: 0 off, 1 on, 2 flash (250 ms),
// 3 three blinks of 90 ms then off, 4 rapid (60 ms).
bool lampLit(uint8_t mode, uint32_t msSinceModeSet);

// Debounced button with short and long presses, fed the raw state on every loop pass.
struct ButtonTimer {
  static const uint32_t DEBOUNCE_MS = 30;
  static const uint32_t LONG_MS = 800;
  bool down = false, fired = false;
  uint32_t changed = 0, pressedAt = 0;
  // 'P' on release after under LONG_MS, 'L' once when held LONG_MS (its release then gives nothing), else 0.
  char poll(bool pressed, uint32_t now);
};

// Unsigned 8-bit speech sample (128 = silence) to signed 16-bit with the volume (0-100 %) applied.
int16_t toPcm(uint8_t sample, uint8_t volumePct);

// The last sample faded linearly to 0 over 400 samples (50 ms at 8 kHz) of an empty ring; 0 after that.
int16_t fadeTowardSilence(int16_t last, uint32_t samplesSinceEmpty);

}  // namespace panel
