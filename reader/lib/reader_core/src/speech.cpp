#include "speech.h"

#include <cctype>
#include <cstdlib>
#include <cstring>
#include <string>

namespace reader {

namespace {

struct Entry {
  const char* token;
  Word words[3];  // W_NONE-terminated when shorter
};

// Token -> words. Keep tokens lowercase. "external" has no vocabulary word, so it
// is spelled E X T, as the H2D reader always said it.
const Entry TABLE[] = {
    {"zero", {W_ZERO}}, {"oh", {W_ZERO}}, {"one", {W_ONE}}, {"two", {W_TWO}},
    {"three", {W_THREE}}, {"four", {W_FOUR}}, {"five", {W_FIVE}}, {"six", {W_SIX}},
    {"seven", {W_SEVEN}}, {"eight", {W_EIGHT}}, {"nine", {W_NINE}}, {"ten", {W_TEN}},
    {"eleven", {W_ELEVEN}}, {"twelve", {W_TWELVE}}, {"thirteen", {W_THIRTEEN}},
    {"fourteen", {W_FOURTEEN}}, {"fifteen", {W_FIFTEEN}}, {"sixteen", {W_SIX, W_TEEN}},
    {"seventeen", {W_SEVEN, W_TEEN}}, {"eighteen", {W_EIGHT, W_TEEN}},
    {"nineteen", {W_NINE, W_TEEN}}, {"twenty", {W_TWENTY}}, {"thirty", {W_THIRTY}},
    {"forty", {W_FORTY}}, {"fifty", {W_FIFTY}}, {"sixty", {W_SIXTY}},
    {"seventy", {W_SEVENTY}}, {"eighty", {W_EIGHTY}}, {"ninety", {W_NINETY}},
    {"a", {W_A}}, {"b", {W_B}}, {"c", {W_C}}, {"d", {W_D}}, {"e", {W_E}}, {"f", {W_F}},
    {"g", {W_G}}, {"h", {W_H}}, {"i", {W_I}}, {"j", {W_J}}, {"k", {W_K}}, {"l", {W_L}},
    {"m", {W_M}}, {"n", {W_N}}, {"o", {W_O}}, {"p", {W_P}}, {"q", {W_Q}}, {"r", {W_R}},
    {"s", {W_S}}, {"t", {W_T}}, {"u", {W_U}}, {"v", {W_V}}, {"w", {W_W}}, {"x", {W_X}},
    {"y", {W_Y}}, {"z", {W_Z}},
    {"external", {W_E, W_X, W_T}}, {"ext", {W_E, W_X, W_T}},
    {"left", {W_LEFT}}, {"right", {W_RIGHT}}, {"top", {W_TOP}}, {"bottom", {W_BOTTOM}},
    {"middle", {W_MIDDLE}}, {"center", {W_CENTER}}, {"front", {W_FRONT}}, {"back", {W_BACK}},
    {"set", {W_SET}}, {"load", {W_LOAD}}, {"ready", {W_READY}}, {"connect", {W_CONNECT}},
    {"fail", {W_FAIL}}, {"power", {W_POWER}}, {"cycle", {W_CYCLE}}, {"printer", {W_PRINTER}},
    {"unit", {W_UNIT}}, {"number", {W_NUMBER}}, {"plus", {W_PLUS}}, {"light", {W_LIGHT}},
    {"high", {W_HIGH}}, {"low", {W_LOW}}, {"up", {W_UP}}, {"down", {W_DOWN}}, {"on", {W_ON}},
    {"off", {W_OFF}}, {"and", {W_AND}}, {"error", {W_ERROR}},
    {"red", {W_RED}}, {"green", {W_GREEN}}, {"blue", {W_BLUE}}, {"yellow", {W_YELLOW}},
    {"black", {W_BLACK}}, {"white", {W_WHITE}}, {"gray", {W_GRAY}}, {"grey", {W_GRAY}},
};
const size_t TABLE_N = sizeof(TABLE) / sizeof(TABLE[0]);

const Word UNITS[] = {W_ZERO, W_ONE, W_TWO, W_THREE, W_FOUR, W_FIVE, W_SIX, W_SEVEN, W_EIGHT, W_NINE};
const Word TENS[] = {W_NONE, W_TEN, W_TWENTY, W_THIRTY, W_FORTY, W_FIFTY, W_SIXTY, W_SEVENTY,
                     W_EIGHTY, W_NINETY};

size_t put(Word* out, size_t max, size_t n, Word w) {
  if (n < max) out[n++] = w;
  return n;
}

// 0..99 written as digits.
size_t number(int v, Word* out, size_t max) {
  if (v < 10) return put(out, max, 0, UNITS[v]);
  if (v < 20) {
    static const Word TEENS[] = {W_TEN, W_ELEVEN, W_TWELVE, W_THIRTEEN, W_FOURTEEN, W_FIFTEEN};
    if (v < 16) return put(out, max, 0, TEENS[v - 10]);
    size_t n = put(out, max, 0, UNITS[v - 10]);
    return put(out, max, n, W_TEEN);
  }
  size_t n = put(out, max, 0, TENS[v / 10]);
  if (v % 10) n = put(out, max, n, UNITS[v % 10]);
  return n;
}

}  // namespace

size_t expandToken(const char* token, Word* out, size_t max) {
  std::string t;
  for (const char* p = token; p && *p; p++) t += (char)tolower((unsigned char)*p);
  if (t.empty() || max == 0) return 0;
  bool digits = true;
  for (char c : t) digits = digits && isdigit((unsigned char)c);
  if (digits) {
    if (t.size() > 2) return 0;
    return number(atoi(t.c_str()), out, max);
  }
  for (size_t i = 0; i < TABLE_N; i++) {
    if (t != TABLE[i].token) continue;
    size_t n = 0;
    for (Word w : TABLE[i].words) {
      if (w == W_NONE) break;
      n = put(out, max, n, w);
    }
    return n;
  }
  return 0;
}

size_t buildUtterance(const char* say, Word lead, Word* out, size_t max) {
  size_t n = 0;
  if (lead != W_NONE) n = put(out, max, n, lead);
  const char* p = say ? say : "";
  while (*p && n < max) {
    while (*p && isspace((unsigned char)*p)) p++;
    const char* start = p;
    while (*p && !isspace((unsigned char)*p)) p++;
    if (p == start) break;
    std::string tok(start, p - start);
    Word w[4];
    size_t k = expandToken(tok.c_str(), w, 4);
    if (k == 0) n = put(out, max, n, W_BEEP);
    for (size_t i = 0; i < k; i++) n = put(out, max, n, w[i]);
  }
  return n;
}

size_t tokenCount() { return TABLE_N; }
const char* tokenAt(size_t i) { return i < TABLE_N ? TABLE[i].token : ""; }

}  // namespace reader
