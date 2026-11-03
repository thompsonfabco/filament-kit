#include "menu.h"

#include <cctype>

namespace reader {

// ---- button ---------------------------------------------------------------------

BtnEvent Button::update(bool pressed, uint32_t now) {
  if (pressed != down_ && (!changedOnce_ || now - lastChange_ > BTN_DEBOUNCE_MS)) {
    changedOnce_ = true;
    lastChange_ = now;
    down_ = pressed;
    if (pressed) {
      downAt_ = now;
      cued_ = fired_ = false;
      return BTN_NONE;
    }
    if (fired_) return BTN_NONE;
    return (now - downAt_ >= BTN_MENU_MS) ? BTN_MENU : BTN_SHORT;
  }
  if (down_ && !fired_) {
    uint32_t held = now - downAt_;
    if (held >= BTN_OTA_MS) {
      fired_ = true;
      return BTN_OTA;
    }
    if (held >= BTN_MENU_MS && !cued_) {
      cued_ = true;
      return BTN_CUE;
    }
  }
  return BTN_NONE;
}

// ---- menu -------------------------------------------------------------------------

static int wrap(int v, int n) { return ((v % n) + n) % n; }

Action Menu::rotate(int d, int nPrinters, int nSlots, uint32_t now) {
  if (!d) return ACT_NONE;
  lastInput = now;
  if (mode == MODE_PRINTERS) {
    if (nPrinters <= 0) return ACT_NONE;
    cursor = wrap(cursor + d, nPrinters);
    return ACT_CURSOR_MOVED;
  }
  if (nSlots <= 0) return ACT_NONE;
  slot = wrap(slot + d, nSlots);
  return ACT_SLOT_MOVED;
}

Action Menu::button(BtnEvent e, int nPrinters, uint32_t now) {
  lastInput = now;
  switch (e) {
    case BTN_OTA:
      mode = MODE_SLOTS;
      return ACT_OTA;
    case BTN_MENU:
      if (mode == MODE_PRINTERS) {
        mode = MODE_SLOTS;
        return ACT_CLOSE_LIST;
      }
      if (nPrinters <= 0) return ACT_NO_PRINTERS;
      mode = MODE_PRINTERS;
      cursor = (printer >= 0 && printer < nPrinters) ? printer : 0;
      return ACT_OPEN_LIST;
    case BTN_SHORT:
      if (mode == MODE_SLOTS) return ACT_RESEND;
      mode = MODE_SLOTS;
      if (cursor == printer) return ACT_CLOSE_LIST;
      printer = cursor;
      slot = 0;
      return ACT_PICK_PRINTER;
    default:
      return ACT_NONE;
  }
}

Action Menu::tick(uint32_t now) {
  if (mode == MODE_PRINTERS && now - lastInput >= LIST_TIMEOUT_MS) {
    mode = MODE_SLOTS;
    return ACT_CLOSE_LIST;
  }
  return ACT_NONE;
}

// ---- saved choice -------------------------------------------------------------------

static bool sameNoCase(const std::string& a, const std::string& b) {
  if (a.size() != b.size()) return false;
  for (size_t i = 0; i < a.size(); i++)
    if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) return false;
  return true;
}

int findPrinter(const std::vector<PrinterEntry>& list, const std::string& id) {
  if (list.empty()) return -1;
  for (size_t i = 0; i < list.size(); i++)
    if (list[i].id == id) return (int)i;
  return 0;
}

int findSlot(const std::vector<SlotEntry>& list, const std::string& label) {
  if (list.empty()) return -1;
  for (size_t i = 0; i < list.size(); i++)
    if (list[i].label == label) return (int)i;
  for (size_t i = 0; i < list.size(); i++)
    if (sameNoCase(list[i].label, label)) return (int)i;
  return 0;
}

// ---- display helpers ------------------------------------------------------------------

std::string marquee(const std::string& text, size_t width, size_t step) {
  if (width == 0) return "";
  if (text.size() <= width) return text;
  std::string loop = text + MARQUEE_GAP;
  size_t start = step % loop.size();
  std::string out;
  for (size_t i = 0; i < width; i++) out += loop[(start + i) % loop.size()];
  return out;
}

int labelTextSize(size_t len) { return len <= labelColumns(3) ? 3 : 2; }

size_t labelColumns(int textSize) { return 128 / (6 * (size_t)textSize); }

}  // namespace reader
