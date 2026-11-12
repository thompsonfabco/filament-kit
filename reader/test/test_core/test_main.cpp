// Host-side (PlatformIO native) tests for the reader's pure logic: reader API
// parsing, knob/menu state, saved-choice recovery
// and the marquee used for long labels.  Run: pio test -e native
#include <unity.h>
#include <cstring>
#include <string>
#include <vector>

#include "reader_api.h"
#include "menu.h"

using namespace reader;

void setUp() {}
void tearDown() {}

// ---- printers list ------------------------------------------------------------

void test_parse_printers_basic() {
  std::vector<PrinterEntry> p;
  TEST_ASSERT_TRUE(parsePrinters(
      R"([{"id":"h2d","name":"H2D","say":"h two d"},{"id":"x1c","name":"X1 Carbon","say":["x","one","carbon"]}])",
      p));
  TEST_ASSERT_EQUAL(2, (int)p.size());
  TEST_ASSERT_EQUAL_STRING("h2d", p[0].id.c_str());
  TEST_ASSERT_EQUAL_STRING("H2D", p[0].name.c_str());
}

void test_parse_printers_tolerant() {
  std::vector<PrinterEntry> p;
  // numeric id, missing name/say, junk entries skipped, extra fields ignored
  TEST_ASSERT_TRUE(parsePrinters(R"([{"id":7,"extra":1},{"name":"no id"},5,{"id":"","name":"x"}])", p));
  TEST_ASSERT_EQUAL(1, (int)p.size());
  TEST_ASSERT_EQUAL_STRING("7", p[0].id.c_str());
  TEST_ASSERT_EQUAL_STRING("7", p[0].name.c_str());  // name falls back to the id
}

void test_parse_printers_rejects_bad_json() {
  std::vector<PrinterEntry> p;
  p.push_back({"keep", "Keep"});
  TEST_ASSERT_FALSE(parsePrinters("not json", p));
  TEST_ASSERT_FALSE(parsePrinters(R"({"id":"obj, not list"})", p));
  TEST_ASSERT_EQUAL(1, (int)p.size());  // untouched on failure (last good list stays)
  TEST_ASSERT_EQUAL_STRING("keep", p[0].id.c_str());
}

void test_parse_printers_empty_list() {
  std::vector<PrinterEntry> p;
  p.push_back({"old", "Old"});
  TEST_ASSERT_TRUE(parsePrinters("[]", p));
  TEST_ASSERT_EQUAL(0, (int)p.size());
}

void test_parse_printers_caps_count() {
  std::string j = "[";
  for (int i = 0; i < MAX_PRINTERS + 5; i++) {
    if (i) j += ",";
    j += "{\"id\":\"p" + std::to_string(i) + "\"}";
  }
  j += "]";
  std::vector<PrinterEntry> p;
  TEST_ASSERT_TRUE(parsePrinters(j.c_str(), p));
  TEST_ASSERT_EQUAL(MAX_PRINTERS, (int)p.size());
}

// ---- slots list ---------------------------------------------------------------

void test_parse_slots_full() {
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(R"([
    {"label":"A1","say":["a","1"],"kind":"ams","present":true,"type":"PLA","spool":{"id":12,"name":"Polymaker Grey"}},
    {"label":"A2","say":"a 2","kind":"ams","present":false,"type":null,"spool":null},
    {"label":"HT-B","say":["h","t","b"],"kind":"ams_ht","present":null,"type":"PETG","spool":null},
    {"label":"Ext-L","say":["external","left"],"kind":"external","type":"","spool":"Spool 9"},
    {"label":"A3","present":true,"type":"","spool":44}
  ])", s));
  TEST_ASSERT_EQUAL(5, (int)s.size());
  TEST_ASSERT_EQUAL_STRING("A1", s[0].label.c_str());
  TEST_ASSERT_EQUAL_STRING("ams", s[0].kind.c_str());
  TEST_ASSERT_EQUAL(PRESENT_YES, s[0].present);
  TEST_ASSERT_EQUAL_STRING("PLA", s[0].type.c_str());
  TEST_ASSERT_EQUAL_STRING("Polymaker Grey", s[0].spool.c_str());
  TEST_ASSERT_EQUAL(PRESENT_NO, s[1].present);
  TEST_ASSERT_EQUAL(PRESENT_UNKNOWN, s[2].present);
  TEST_ASSERT_EQUAL(PRESENT_UNKNOWN, s[3].present);   // missing -> unknown
  TEST_ASSERT_EQUAL_STRING("Spool 9", s[3].spool.c_str());
  TEST_ASSERT_EQUAL_STRING("#44", s[4].spool.c_str());  // bare id
}

void test_parse_slots_spool_without_name_uses_id() {
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(R"([{"label":"A1","spool":{"id":5}}])", s));
  TEST_ASSERT_EQUAL_STRING("#5", s[0].spool.c_str());
}

void test_parse_slots_skips_unlabelled_and_rejects_bad() {
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(R"([{"say":"x"},{"label":""},{"label":"B4"}])", s));
  TEST_ASSERT_EQUAL(1, (int)s.size());
  TEST_ASSERT_EQUAL_STRING("B4", s[0].label.c_str());
  TEST_ASSERT_FALSE(parseSlots("[{", s));
  TEST_ASSERT_EQUAL(1, (int)s.size());
}

void test_parse_slots_sixteen_units() {
  // 16 AMS units x 4 + 8 HT + 2 externals = 74 slots: all kept, in order
  std::string j = "[";
  int n = 0;
  for (int u = 0; u < 16; u++)
    for (int t = 1; t <= 4; t++) {
      if (n++) j += ",";
      j += std::string("{\"label\":\"") + char('A' + u) + std::to_string(t) + "\"}";
    }
  for (int h = 0; h < 8; h++) j += std::string(",{\"label\":\"HT-") + char('A' + h) + "\"}";
  j += R"(,{"label":"Ext-L"},{"label":"Ext-R"}])";
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(j.c_str(), s));
  TEST_ASSERT_EQUAL(74, (int)s.size());
  TEST_ASSERT_EQUAL_STRING("A1", s[0].label.c_str());
  TEST_ASSERT_EQUAL_STRING("P4", s[63].label.c_str());
  TEST_ASSERT_EQUAL_STRING("HT-H", s[71].label.c_str());
  TEST_ASSERT_EQUAL_STRING("Ext-R", s[73].label.c_str());
}

void test_slot_contents() {
  SlotEntry e;
  e.label = "A1";
  e.present = PRESENT_NO;
  TEST_ASSERT_EQUAL_STRING("empty", slotContents(e).c_str());
  e.present = PRESENT_YES;
  TEST_ASSERT_EQUAL_STRING("loaded, not set", slotContents(e).c_str());
  e.type = "PLA";
  TEST_ASSERT_EQUAL_STRING("PLA (no spool)", slotContents(e).c_str());
  e.spool = "Sunlu Grey";
  TEST_ASSERT_EQUAL_STRING("PLA Sunlu Grey", slotContents(e).c_str());
  e.type = "";
  TEST_ASSERT_EQUAL_STRING("Sunlu Grey", slotContents(e).c_str());
  SlotEntry u;
  u.present = PRESENT_UNKNOWN;
  TEST_ASSERT_EQUAL_STRING("?", slotContents(u).c_str());
  // the slot reads "empty" even with a remembered spool: the printer says nothing is there
  e.present = PRESENT_NO;
  TEST_ASSERT_EQUAL_STRING("empty", slotContents(e).c_str());
}

// ---- scan --------------------------------------------------------------------

void test_scan_body() {
  std::string b = scanBody("4:c7:96:11:9:22:89", "h2d", "HT-B", false);
  TEST_ASSERT_EQUAL_STRING(
      R"({"uid":"4:c7:96:11:9:22:89","printer":"h2d","slot":"HT-B","dry_run":false})", b.c_str());
  std::string q = scanBody("a\"b", "p", "s", true);
  TEST_ASSERT_EQUAL_STRING(R"({"uid":"a\"b","printer":"p","slot":"s","dry_run":true})", q.c_str());
}

void test_scan_statuses() {
  struct { const char* s; ScanStatus st; Feedback fb; } cases[] = {
      {"set", SCAN_SET, FB_OK},
      {"queued", SCAN_QUEUED, FB_QUEUED},
      {"unknown_tag", SCAN_UNKNOWN_TAG, FB_UNKNOWN},
      {"unknown_spool", SCAN_UNKNOWN_SPOOL, FB_UNKNOWN},
      {"archived_spool", SCAN_ARCHIVED_SPOOL, FB_UNKNOWN},
      {"no_preset", SCAN_NO_PRESET, FB_ERROR},
      {"offline", SCAN_OFFLINE, FB_ERROR},
      {"error", SCAN_ERROR, FB_ERROR},
  };
  for (auto& c : cases) {
    std::string body = std::string(R"({"status":")") + c.s + R"(","message":"m1","filament":"PLA Grey"})";
    ScanResult r = parseScanResult(200, body.c_str());
    TEST_ASSERT_EQUAL_MESSAGE(c.st, r.status, c.s);
    TEST_ASSERT_EQUAL_MESSAGE(c.fb, feedbackFor(r.status), c.s);
    TEST_ASSERT_EQUAL_STRING("m1", r.message.c_str());
    TEST_ASSERT_EQUAL_STRING("PLA Grey", r.filament.c_str());
    TEST_ASSERT_TRUE(strlen(headline(r.status)) > 0);
  }
}

void test_scan_status_on_error_codes() {
  // a status in a non-2xx body still counts (e.g. 404 + unknown_tag)
  ScanResult r = parseScanResult(404, R"({"status":"unknown_tag","message":"no spool has this tag"})");
  TEST_ASSERT_EQUAL(SCAN_UNKNOWN_TAG, r.status);
  // but "set" only counts with 2xx
  r = parseScanResult(500, R"({"status":"set"})");
  TEST_ASSERT_EQUAL(SCAN_ERROR, r.status);
  r = parseScanResult(-1, "");
  TEST_ASSERT_EQUAL(SCAN_UNREACHABLE, r.status);
  TEST_ASSERT_EQUAL(FB_ERROR, feedbackFor(r.status));
  r = parseScanResult(401, "");
  TEST_ASSERT_EQUAL(SCAN_ERROR, r.status);
  TEST_ASSERT_EQUAL_STRING("HTTP 401", r.message.c_str());
  r = parseScanResult(200, R"({"status":"brand_new_status","message":"hi"})");
  TEST_ASSERT_EQUAL(SCAN_ERROR, r.status);
  TEST_ASSERT_EQUAL_STRING("hi", r.message.c_str());
  r = parseScanResult(200, "garbage");
  TEST_ASSERT_EQUAL(SCAN_ERROR, r.status);
}

void test_url_encode() {
  TEST_ASSERT_EQUAL_STRING("h2d", urlEncode("h2d").c_str());
  TEST_ASSERT_EQUAL_STRING("my%20printer%2F1", urlEncode("my printer/1").c_str());
  TEST_ASSERT_EQUAL_STRING("a-b_c.d~e", urlEncode("a-b_c.d~e").c_str());
}

void test_join_url() {
  TEST_ASSERT_EQUAL_STRING("https://h/filament/reader/printers",
                           joinUrl("https://h/filament/reader", "printers").c_str());
  TEST_ASSERT_EQUAL_STRING("https://h/filament/reader/printers",
                           joinUrl("https://h/filament/reader/", "/printers").c_str());
}

// ---- button --------------------------------------------------------------------

static std::vector<BtnEvent> press(Button& b, uint32_t start, uint32_t heldMs) {
  std::vector<BtnEvent> ev;
  for (uint32_t t = start; t <= start + heldMs; t += 10) {
    BtnEvent e = b.update(true, t);
    if (e != BTN_NONE) ev.push_back(e);
  }
  for (uint32_t t = start + heldMs + 10; t <= start + heldMs + 100; t += 10) {
    BtnEvent e = b.update(false, t);
    if (e != BTN_NONE) ev.push_back(e);
  }
  return ev;
}

void test_button_short() {
  Button b;
  auto ev = press(b, 1000, 200);
  TEST_ASSERT_EQUAL(1, (int)ev.size());
  TEST_ASSERT_EQUAL(BTN_SHORT, ev[0]);
}

void test_button_hold_menu() {
  Button b;
  auto ev = press(b, 1000, 1500);
  TEST_ASSERT_EQUAL(2, (int)ev.size());
  TEST_ASSERT_EQUAL(BTN_CUE, ev[0]);       // 1 s reached: tick so the user can let go
  TEST_ASSERT_EQUAL(BTN_MENU, ev[1]);      // released between 1 and 4 s
}

void test_button_hold_ota() {
  Button b;
  auto ev = press(b, 1000, 5000);
  TEST_ASSERT_EQUAL(2, (int)ev.size());
  TEST_ASSERT_EQUAL(BTN_CUE, ev[0]);
  TEST_ASSERT_EQUAL(BTN_OTA, ev[1]);       // fires at 4 s while held; release adds nothing
}

void test_button_debounce() {
  Button b;
  // chatter shorter than the debounce window does nothing
  TEST_ASSERT_EQUAL(BTN_NONE, b.update(true, 1000));
  TEST_ASSERT_EQUAL(BTN_NONE, b.update(false, 1005));
  TEST_ASSERT_EQUAL(BTN_NONE, b.update(true, 1010));
  auto ev = press(b, 1020, 150);
  TEST_ASSERT_EQUAL(1, (int)ev.size());
  TEST_ASSERT_EQUAL(BTN_SHORT, ev[0]);
}

// ---- menu ------------------------------------------------------------------------

void test_menu_rotate_slots_wraps() {
  Menu m;
  TEST_ASSERT_EQUAL(ACT_SLOT_MOVED, m.rotate(1, 3, 4));
  TEST_ASSERT_EQUAL(1, m.slot);
  m.rotate(-3, 3, 4);
  TEST_ASSERT_EQUAL(2, m.slot);  // (1-3) mod 4
  m.rotate(9, 3, 4);
  TEST_ASSERT_EQUAL(3, m.slot);
  TEST_ASSERT_EQUAL(ACT_NONE, m.rotate(0, 3, 4));
  m.slot = 0;
  TEST_ASSERT_EQUAL(ACT_NONE, m.rotate(1, 3, 0));  // no slots: nothing to move
  TEST_ASSERT_EQUAL(0, m.slot);
}

void test_menu_short_press_resends() {
  Menu m;
  TEST_ASSERT_EQUAL(ACT_RESEND, m.button(BTN_SHORT, 2));
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
}

void test_menu_printer_list_pick() {
  Menu m;
  m.printer = 1;
  m.slot = 2;
  TEST_ASSERT_EQUAL(ACT_OPEN_LIST, m.button(BTN_MENU, 3));
  TEST_ASSERT_EQUAL(MODE_PRINTERS, m.mode);
  TEST_ASSERT_EQUAL(1, m.cursor);              // starts on the current printer
  TEST_ASSERT_EQUAL(ACT_CURSOR_MOVED, m.rotate(1, 3, 4));
  TEST_ASSERT_EQUAL(2, m.cursor);
  TEST_ASSERT_EQUAL(2, m.slot);                // the slot is untouched while browsing
  m.rotate(1, 3, 4);
  TEST_ASSERT_EQUAL(0, m.cursor);              // wraps
  TEST_ASSERT_EQUAL(ACT_PICK_PRINTER, m.button(BTN_SHORT, 3));
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
  TEST_ASSERT_EQUAL(0, m.printer);
}

void test_menu_pick_same_printer_just_closes() {
  Menu m;
  m.printer = 1;
  m.button(BTN_MENU, 3);
  TEST_ASSERT_EQUAL(ACT_CLOSE_LIST, m.button(BTN_SHORT, 3));
  TEST_ASSERT_EQUAL(1, m.printer);
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
}

void test_menu_hold_again_cancels_list() {
  Menu m;
  m.button(BTN_MENU, 3);
  m.rotate(1, 3, 4);
  TEST_ASSERT_EQUAL(ACT_CLOSE_LIST, m.button(BTN_MENU, 3));
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
  TEST_ASSERT_EQUAL(0, m.printer);
}

void test_menu_ota_from_anywhere() {
  Menu m;
  TEST_ASSERT_EQUAL(ACT_OTA, m.button(BTN_OTA, 2));
  m.button(BTN_MENU, 2);
  TEST_ASSERT_EQUAL(ACT_OTA, m.button(BTN_OTA, 2));
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
}

void test_menu_list_needs_printers() {
  Menu m;
  TEST_ASSERT_EQUAL(ACT_NO_PRINTERS, m.button(BTN_MENU, 0));
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
}

void test_menu_list_times_out() {
  Menu m;
  m.button(BTN_MENU, 2, 1000);
  TEST_ASSERT_EQUAL(ACT_NONE, m.tick(1000 + LIST_TIMEOUT_MS - 1));
  m.rotate(1, 2, 1, 5000);                     // activity re-arms the timeout
  TEST_ASSERT_EQUAL(ACT_NONE, m.tick(5000 + LIST_TIMEOUT_MS - 1));
  TEST_ASSERT_EQUAL(ACT_CLOSE_LIST, m.tick(5000 + LIST_TIMEOUT_MS));
  TEST_ASSERT_EQUAL(MODE_SLOTS, m.mode);
  TEST_ASSERT_EQUAL(ACT_NONE, m.tick(999999));
}

// ---- saved choice ----------------------------------------------------------------

static std::vector<SlotEntry> slots(std::initializer_list<const char*> labels) {
  std::vector<SlotEntry> v;
  for (auto l : labels) { SlotEntry e; e.label = l; v.push_back(e); }
  return v;
}

void test_find_printer() {
  std::vector<PrinterEntry> p = {{"a", "A"}, {"b", "B"}};
  TEST_ASSERT_EQUAL(1, findPrinter(p, "b"));
  TEST_ASSERT_EQUAL(0, findPrinter(p, "gone"));   // removed -> first printer
  TEST_ASSERT_EQUAL(0, findPrinter(p, ""));
  std::vector<PrinterEntry> none;
  TEST_ASSERT_EQUAL(-1, findPrinter(none, "a"));
}

void test_find_slot_by_label_survives_layout_change() {
  auto before = slots({"A1", "A2", "A3", "A4", "HT-A", "Ext-L"});
  int i = findSlot(before, "HT-A");
  TEST_ASSERT_EQUAL(4, i);
  // a second AMS was added in front of the HT: same label, new position
  auto after = slots({"A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "HT-A", "Ext-L"});
  TEST_ASSERT_EQUAL(8, findSlot(after, "HT-A"));
  // the HT unit went away: fall back to the first slot
  auto gone = slots({"A1", "A2", "A3", "A4", "Ext-L"});
  TEST_ASSERT_EQUAL(0, findSlot(gone, "HT-A"));
  // case differences still match
  TEST_ASSERT_EQUAL(4, findSlot(gone, "ext-l"));
  TEST_ASSERT_EQUAL(-1, findSlot(slots({}), "A1"));
}

// ---- display helpers ----------------------------------------------------------------

void test_marquee_short_text_static() {
  TEST_ASSERT_EQUAL_STRING("A1", marquee("A1", 7, 0).c_str());
  TEST_ASSERT_EQUAL_STRING("A1", marquee("A1", 7, 99).c_str());
  TEST_ASSERT_EQUAL_STRING("1234567", marquee("1234567", 7, 5).c_str());
}

void test_marquee_long_text_scrolls() {
  std::string t = "Ext-Left-2";               // 10 chars in a 7-char window
  TEST_ASSERT_EQUAL_STRING("Ext-Lef", marquee(t, 7, 0).c_str());
  TEST_ASSERT_EQUAL_STRING("xt-Left", marquee(t, 7, 1).c_str());
  // the text is followed by a gap, then wraps around to the start
  std::string loop = t + MARQUEE_GAP;
  TEST_ASSERT_EQUAL_STRING(marquee(t, 7, 0).c_str(), marquee(t, 7, loop.size()).c_str());
  TEST_ASSERT_EQUAL(7, (int)marquee(t, 7, 12).size());
  TEST_ASSERT_EQUAL_STRING("", marquee(t, 0, 3).c_str());
}

void test_label_text_size() {
  TEST_ASSERT_EQUAL(3, labelTextSize(2));
  TEST_ASSERT_EQUAL(3, labelTextSize(7));
  TEST_ASSERT_EQUAL(2, labelTextSize(8));
  TEST_ASSERT_EQUAL(2, labelTextSize(30));
  TEST_ASSERT_EQUAL(7, labelColumns(3));
  TEST_ASSERT_EQUAL(10, labelColumns(2));
}

// ---- bounded memory --------------------------------------------------------------

void test_oversize_fields_truncated() {
  std::string longLabel(100, 'L');
  std::string longName(100, 'N');
  std::string j = "[{\"label\":\"" + longLabel + "\",\"say\":\"" + std::string(100, 'a') +
                  "\",\"type\":\"" + std::string(100, 'T') + "\",\"spool\":{\"name\":\"" + longName + "\"}}]";
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(j.c_str(), s));
  TEST_ASSERT_EQUAL(1, (int)s.size());
  TEST_ASSERT_EQUAL((int)MAX_FIELD, (int)s[0].label.size());
  TEST_ASSERT_EQUAL((int)MAX_FIELD, (int)s[0].type.size());
  TEST_ASSERT_EQUAL((int)MAX_FIELD, (int)s[0].spool.size());
  std::vector<PrinterEntry> p;
  std::string pj = "[{\"id\":\"p1\",\"name\":\"" + longName + "\",\"say\":[\"" + std::string(60, 'x') + "\"]}]";
  TEST_ASSERT_TRUE(parsePrinters(pj.c_str(), p));
  TEST_ASSERT_EQUAL((int)MAX_FIELD, (int)p[0].name.size());
}

void test_truncation_keeps_utf8_whole() {
  // 39 ASCII chars then a 2-byte char: cutting at 40 bytes would split it
  std::string label = std::string(39, 'A') + "\xc3\xa9" + "tail";
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(("[{\"label\":\"" + label + "\"}]").c_str(), s));
  TEST_ASSERT_EQUAL(39, (int)s[0].label.size());
}

void test_overlong_printer_id_skipped() {
  // an id is never truncated (it goes back in URLs); one too long to be real is dropped
  std::vector<PrinterEntry> p;
  std::string j = "[{\"id\":\"" + std::string(MAX_ID + 1, 'i') + "\"},{\"id\":\"ok\"}]";
  TEST_ASSERT_TRUE(parsePrinters(j.c_str(), p));
  TEST_ASSERT_EQUAL(1, (int)p.size());
  TEST_ASSERT_EQUAL_STRING("ok", p[0].id.c_str());
}

void test_oversize_list_rejected() {
  std::string j = "[";
  int n = 0;
  while (j.size() <= MAX_RESPONSE_BYTES) {
    if (n++) j += ",";
    j += "{\"label\":\"A1\",\"kind\":\"ams\",\"type\":\"PLA\",\"spool\":{\"name\":\"Spool\"}}";
  }
  j += "]";
  std::vector<SlotEntry> s = slots({"keep"});
  TEST_ASSERT_FALSE(parseSlots(j.c_str(), s));
  TEST_ASSERT_EQUAL(1, (int)s.size());          // last good list stays
  std::vector<PrinterEntry> p;
  TEST_ASSERT_FALSE(parsePrinters(j.c_str(), p));
  TEST_ASSERT_TRUE(responseTooBig((int)MAX_RESPONSE_BYTES + 1));
  TEST_ASSERT_FALSE(responseTooBig((int)MAX_RESPONSE_BYTES));
  TEST_ASSERT_FALSE(responseTooBig(-1));        // unknown length (chunked): read with a cap instead
}

void test_unknown_fields_dropped() {
  // the filter keeps only known fields, so a big unknown field costs nothing after parsing
  std::string j = "[{\"label\":\"A1\",\"junk\":{\"deep\":[1,2,3,\"" + std::string(500, 'z') + "\"]}}]";
  std::vector<SlotEntry> s;
  TEST_ASSERT_TRUE(parseSlots(j.c_str(), s));
  TEST_ASSERT_EQUAL_STRING("A1", s[0].label.c_str());
}

// ---- slots belong to one printer ---------------------------------------------------

void test_slot_cache_keeps_list_on_same_printer_failure() {
  SlotCache c;
  c.apply("h2d", true, slots({"A1", "A2"}));
  TEST_ASSERT_TRUE(c.usableFor("h2d"));
  c.apply("h2d", false, {});                    // a refresh failed: keep the last good list
  TEST_ASSERT_TRUE(c.usableFor("h2d"));
  TEST_ASSERT_EQUAL(2, (int)c.slots.size());
}

void test_slot_cache_clears_on_other_printer_failure() {
  SlotCache c;
  c.apply("h2d", true, slots({"A1", "A2"}));
  c.apply("x1c", false, {});                    // switched printer, fetch failed
  TEST_ASSERT_FALSE(c.usableFor("x1c"));
  TEST_ASSERT_FALSE(c.usableFor("h2d"));
  TEST_ASSERT_EQUAL(0, (int)c.slots.size());
  c.apply("x1c", true, slots({"Ext"}));
  TEST_ASSERT_TRUE(c.usableFor("x1c"));
  TEST_ASSERT_FALSE(c.usableFor("h2d"));        // never H2D's slots for another printer
}

void test_slot_cache_empty_list_not_usable() {
  SlotCache c;
  c.apply("p", true, {});
  TEST_ASSERT_FALSE(c.usableFor("p"));
}

// ---- saved label wins until the knob is turned -------------------------------------

void test_wanted_label_prefers_saved() {
  TEST_ASSERT_EQUAL_STRING("HT-B", wantedLabel("HT-B", "A1", false).c_str());
  TEST_ASSERT_EQUAL_STRING("A3", wantedLabel("HT-B", "A3", true).c_str());   // turned, not yet saved
  TEST_ASSERT_EQUAL_STRING("A1", wantedLabel("", "A1", false).c_str());      // nothing saved yet
}

void test_unit_dropping_out_briefly_keeps_selection() {
  std::string saved = "HT-B";
  auto full = slots({"A1", "A2", "A3", "A4", "HT-A", "HT-B"});
  auto dropped = slots({"A1", "A2", "A3", "A4", "HT-A"});
  int i = findSlot(full, wantedLabel(saved, "", false));
  TEST_ASSERT_EQUAL(5, i);
  i = findSlot(dropped, wantedLabel(saved, full[i].label, false));
  TEST_ASSERT_EQUAL(0, i);                      // shown on the first slot while HT-B is away...
  i = findSlot(full, wantedLabel(saved, dropped[i].label, false));
  TEST_ASSERT_EQUAL(5, i);                      // ...and back on HT-B when it returns
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_parse_printers_basic);
  RUN_TEST(test_parse_printers_tolerant);
  RUN_TEST(test_parse_printers_rejects_bad_json);
  RUN_TEST(test_parse_printers_empty_list);
  RUN_TEST(test_parse_printers_caps_count);
  RUN_TEST(test_parse_slots_full);
  RUN_TEST(test_parse_slots_spool_without_name_uses_id);
  RUN_TEST(test_parse_slots_skips_unlabelled_and_rejects_bad);
  RUN_TEST(test_parse_slots_sixteen_units);
  RUN_TEST(test_slot_contents);
  RUN_TEST(test_scan_body);
  RUN_TEST(test_scan_statuses);
  RUN_TEST(test_scan_status_on_error_codes);
  RUN_TEST(test_url_encode);
  RUN_TEST(test_join_url);
  RUN_TEST(test_button_short);
  RUN_TEST(test_button_hold_menu);
  RUN_TEST(test_button_hold_ota);
  RUN_TEST(test_button_debounce);
  RUN_TEST(test_menu_rotate_slots_wraps);
  RUN_TEST(test_menu_short_press_resends);
  RUN_TEST(test_menu_printer_list_pick);
  RUN_TEST(test_menu_pick_same_printer_just_closes);
  RUN_TEST(test_menu_hold_again_cancels_list);
  RUN_TEST(test_menu_ota_from_anywhere);
  RUN_TEST(test_menu_list_needs_printers);
  RUN_TEST(test_menu_list_times_out);
  RUN_TEST(test_find_printer);
  RUN_TEST(test_find_slot_by_label_survives_layout_change);
  RUN_TEST(test_marquee_short_text_static);
  RUN_TEST(test_marquee_long_text_scrolls);
  RUN_TEST(test_label_text_size);
  RUN_TEST(test_oversize_fields_truncated);
  RUN_TEST(test_truncation_keeps_utf8_whole);
  RUN_TEST(test_overlong_printer_id_skipped);
  RUN_TEST(test_oversize_list_rejected);
  RUN_TEST(test_unknown_fields_dropped);
  RUN_TEST(test_slot_cache_keeps_list_on_same_printer_failure);
  RUN_TEST(test_slot_cache_clears_on_other_printer_failure);
  RUN_TEST(test_slot_cache_empty_list_not_usable);
  RUN_TEST(test_wanted_label_prefers_saved);
  RUN_TEST(test_unit_dropping_out_briefly_keeps_selection);
  return UNITY_END();
}
