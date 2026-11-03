// Reader API client logic (pure, host-testable): parse the server's printer and
// slot lists and its scan replies, build the scan body and URLs. The contract is
// in reader/README.md ("Server API"). No Arduino types here: main.cpp does HTTP.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace reader {

// Upper bounds keep a bad reply from eating the C3's heap. 16 AMS units x 4 +
// 8 HT + 2 externals = 74 slots, so 128 leaves room.
static const int MAX_PRINTERS = 16;
static const int MAX_SLOTS = 128;
// A list reply larger than this is refused before it is read into RAM (74 slots
// with long names are ~12 KB).
static const size_t MAX_RESPONSE_BYTES = 20480;
// Display/speech strings (label, name, say, type, spool) are cut to this many
// bytes, at a UTF-8 character boundary.
static const size_t MAX_FIELD = 40;
// Printer ids go back in URLs, so they are never cut; longer ones are dropped.
static const size_t MAX_ID = 64;

// True when a Content-Length says the body is too big to read (-1 = unknown:
// the reader then reads with a cap of MAX_RESPONSE_BYTES).
bool responseTooBig(int contentLength);

struct PrinterEntry {
  std::string id;    // opaque; echoed back in URLs and the scan body
  std::string name;  // shown on the top line
  std::string say;   // speech tokens, space separated (lowercase)
};

enum Presence { PRESENT_UNKNOWN = 0, PRESENT_YES = 1, PRESENT_NO = 2 };

struct SlotEntry {
  std::string label;  // the kit label ("A1", "HT-B", "Ext-L"); what the reader saves and sends
  std::string say;    // speech tokens, space separated (lowercase)
  std::string kind;   // unit kind from the server ("ams", "ams_ht", "external", ...)
  Presence present = PRESENT_UNKNOWN;
  std::string type;   // filament type the printer reports ("PLA"), may be empty
  std::string spool;  // linked spool's display name ("#12" when it has no name), may be empty
};

// Parse GET printers / GET printers/{id}/slots. On success `out` is replaced and
// true is returned; on a malformed reply `out` is left as it was (keep the last
// good list) and false is returned. Entries without an id / label are skipped.
bool parsePrinters(const char* json, std::vector<PrinterEntry>& out);
bool parseSlots(const char* json, std::vector<SlotEntry>& out);

// The slot list together with the printer it belongs to, so a failed fetch after a
// printer change can never leave the old printer's slots on screen (or scan into
// them). A failed refresh of the same printer keeps the last good list.
struct SlotCache {
  std::string printer;            // whose slots these are ("" = none)
  std::vector<SlotEntry> slots;
  void apply(const std::string& printerId, bool ok, std::vector<SlotEntry> fresh);
  bool usableFor(const std::string& printerId) const {
    return !slots.empty() && printer == printerId;
  }
};

// The label to re-select after a refresh: the saved one, unless the knob was
// turned and the new choice is not saved yet. A unit that drops out for a moment
// then shows the first slot and goes back to the saved slot when it returns.
std::string wantedLabel(const std::string& saved, const std::string& current, bool turnedUnsaved);

// One line describing what is in a slot ("PLA Polymaker Grey", "empty", "?").
std::string slotContents(const SlotEntry& s);

enum ScanStatus {
  SCAN_SET,
  SCAN_QUEUED,
  SCAN_UNKNOWN_TAG,
  SCAN_UNKNOWN_SPOOL,
  SCAN_ARCHIVED_SPOOL,
  SCAN_NO_PRESET,
  SCAN_OFFLINE,       // the printer is offline (server said so)
  SCAN_ERROR,         // server error, unknown status, unreadable reply, HTTP error
  SCAN_UNREACHABLE,   // no HTTP reply at all (Wi-Fi/TLS/server down)
};

struct ScanResult {
  ScanStatus status = SCAN_ERROR;
  std::string message;   // server's message, or "HTTP <code>" when it sent none
  std::string filament;  // optional: what was set ("PLA Polymaker Grey")
};

// httpCode <= 0 means no reply. "set"/"queued" count only with a 2xx code; the
// other statuses are taken from any reply that names them.
ScanResult parseScanResult(int httpCode, const char* body);

// What the reader does about a result: beep pattern + screen hold.
enum Feedback { FB_OK, FB_QUEUED, FB_UNKNOWN, FB_ERROR };
Feedback feedbackFor(ScanStatus s);
const char* headline(ScanStatus s);  // short screen text ("Unknown tag")

// {"uid":..,"printer":..,"slot":..,"dry_run":..} with JSON escaping.
std::string scanBody(const std::string& uid, const std::string& printer, const std::string& slot,
                     bool dryRun);

// Percent-encode one URL path segment (RFC 3986 unreserved characters pass).
std::string urlEncode(const std::string& s);
// base + "/" + path with exactly one slash between them.
std::string joinUrl(const std::string& base, const std::string& path);

}  // namespace reader
