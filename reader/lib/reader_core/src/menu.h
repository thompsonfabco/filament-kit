// Knob + menu state (pure, host-testable) and the saved-choice / display helpers.
//
//   rotate              next/previous slot (or printer, while the list is open)
//   press               re-send the last tag (or pick the highlighted printer)
//   hold 1 s, release   open the printer list (again: close it)
//   hold 4 s            OTA check (fires while still held)
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "reader_api.h"

namespace reader {

// ---- push button --------------------------------------------------------------
enum BtnEvent {
  BTN_NONE,
  BTN_SHORT,  // released before 1 s
  BTN_CUE,    // 1 s reached while held: tick so the user knows letting go opens the list
  BTN_MENU,   // released between 1 and 4 s
  BTN_OTA,    // 4 s reached while held (nothing more on release)
};

static const uint32_t BTN_DEBOUNCE_MS = 40;
static const uint32_t BTN_MENU_MS = 1000;
static const uint32_t BTN_OTA_MS = 4000;

class Button {
 public:
  // Feed the raw "pressed" level and the time; returns at most one event per call.
  BtnEvent update(bool pressed, uint32_t nowMs);

 private:
  bool down_ = false;
  bool cued_ = false;
  bool fired_ = false;  // OTA fired: the release is swallowed
  bool changedOnce_ = false;
  uint32_t lastChange_ = 0;
  uint32_t downAt_ = 0;
};

// ---- menu ---------------------------------------------------------------------
enum Mode { MODE_SLOTS, MODE_PRINTERS };

enum Action {
  ACT_NONE,
  ACT_SLOT_MOVED,    // show + (after settling) save the new slot
  ACT_CURSOR_MOVED,  // redraw the printer list
  ACT_RESEND,        // re-send the last tag to the shown slot
  ACT_OPEN_LIST,     // show the printer list
  ACT_CLOSE_LIST,    // back to the slot picker, printer unchanged
  ACT_PICK_PRINTER,  // a different printer was picked: save it, fetch its slots
  ACT_OTA,           // run the OTA check
  ACT_NO_PRINTERS,   // the list was asked for but there is nothing to show
};

static const uint32_t LIST_TIMEOUT_MS = 20000;  // an untouched printer list closes itself

struct Menu {
  Mode mode = MODE_SLOTS;
  int printer = 0;  // index into the printer list
  int slot = 0;     // index into the selected printer's slots
  int cursor = 0;   // highlighted printer while the list is open
  uint32_t lastInput = 0;

  Action rotate(int detents, int nPrinters, int nSlots, uint32_t nowMs = 0);
  Action button(BtnEvent e, int nPrinters, uint32_t nowMs = 0);
  Action tick(uint32_t nowMs);
};

// ---- saved choice -----------------------------------------------------------------
// Index of the saved printer id / slot label; the first entry when it is gone;
// -1 for an empty list. Labels match exactly first, then ignoring case.
int findPrinter(const std::vector<PrinterEntry>& list, const std::string& id);
int findSlot(const std::vector<SlotEntry>& list, const std::string& label);

// ---- display helpers ---------------------------------------------------------------
static const char* const MARQUEE_GAP = "   ";
// A `width`-column window onto `text` at scroll position `step`; text that fits is
// returned as-is. Long text loops with MARQUEE_GAP between the end and the start.
std::string marquee(const std::string& text, size_t width, size_t step);
// Font size for a slot label of `len` characters (3 = 18 px wide, 2 = 12 px) on a
// 128 px screen, and how many columns fit at that size.
int labelTextSize(size_t len);
size_t labelColumns(int textSize);

}  // namespace reader
