// Speech: turn the server's `say` tokens ("h t b", "external left", "a 1") into
// words of the built-in TI LPC vocabulary. Pure logic: main.cpp maps each Word to
// its LPC data (sp2_*/spt_* from TalkiePCM) and plays W_BEEP as a short beep, so a
// token with no word in the vocabulary beeps instead of being skipped.
#pragma once
#include <cstddef>

namespace reader {

enum Word {
  W_NONE = 0,  // "no lead word"; never emitted
  W_BEEP,      // stands in for a token the vocabulary has no word for
  // numbers
  W_ZERO, W_ONE, W_TWO, W_THREE, W_FOUR, W_FIVE, W_SIX, W_SEVEN, W_EIGHT, W_NINE,
  W_TEN, W_ELEVEN, W_TWELVE, W_THIRTEEN, W_FOURTEEN, W_FIFTEEN, W_TEEN,
  W_TWENTY, W_THIRTY, W_FORTY, W_FIFTY, W_SIXTY, W_SEVENTY, W_EIGHTY, W_NINETY,
  // letters
  W_A, W_B, W_C, W_D, W_E, W_F, W_G, W_H, W_I, W_J, W_K, W_L, W_M,
  W_N, W_O, W_P, W_Q, W_R, W_S, W_T, W_U, W_V, W_W, W_X, W_Y, W_Z,
  // words
  W_LEFT, W_RIGHT, W_TOP, W_BOTTOM, W_MIDDLE, W_CENTER, W_FRONT, W_BACK,
  W_SET, W_LOAD, W_READY, W_CONNECT, W_FAIL, W_POWER, W_CYCLE, W_PRINTER, W_UNIT,
  W_NUMBER, W_PLUS, W_LIGHT, W_HIGH, W_LOW, W_UP, W_DOWN, W_ON, W_OFF, W_AND, W_ERROR,
  W_RED, W_GREEN, W_BLUE, W_YELLOW, W_BLACK, W_WHITE, W_GRAY,
  W_COUNT
};

static const size_t MAX_UTTERANCE = 16;

// Words for one token (case-insensitive; numbers 0-99 as digits or words).
// Returns how many were written to out (at most max); 0 = no such token.
size_t expandToken(const char* token, Word* out, size_t max);

// Lead word (W_NONE for none) followed by the words of each whitespace-separated
// token in `say`; an unknown token becomes one W_BEEP. Truncated at max.
size_t buildUtterance(const char* say, Word lead, Word* out, size_t max);

// The named tokens of the table (for tests: every Word is reachable).
size_t tokenCount();
const char* tokenAt(size_t i);

}  // namespace reader
