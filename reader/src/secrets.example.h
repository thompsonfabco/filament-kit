// Copy to secrets.h and fill in. secrets.h is the real file; keep it out of
// version control (.gitignore lists it). It is compiled into the firmware image,
// so the image itself is secret too (the server serves /fw/ behind the token).
#pragma once
static const char* WIFI_SSID = "your-ssid";
static const char* WIFI_PASS = "your-wifi-password";

// The filament-kit server's reader API, no trailing slash. The reader calls
// <READER_BASE>/printers, /printers/<id>/slots, /scan, /healthz and /fw/*.
static const char* READER_BASE = "https://filament.example.net/filament/reader";

// From `filament-kit reader token` on the server (printed once; stored hashed).
// Sent as the X-Auth-Token header.
static const char* READER_TOKEN = "paste-the-reader-token-here";

// ECDSA P-256 public key that signed OTA images must match. Print yours with
// `py tools/ota_publish.py --init-key` (it creates the private key on your PC).
// Until a real key is here every OTA image is refused as "bad signature".
static const char* OTA_PUBKEY = R"KEY(-----BEGIN PUBLIC KEY-----
REPLACE-WITH-THE-KEY-FROM-ota_publish.py--init-key
-----END PUBLIC KEY-----
)KEY";

// The buzzer's trigger: 0 = high-triggered (a buzzer behind a MOSFET such as a BS170),
// 1 = low-triggered (the older 3-pin module). Without this line the reader assumes 1.
#define READER_BUZZER_ACTIVE_LOW 0

// Optional: the root CA of a server whose certificate is not from Let's Encrypt
// (the default pin is ISRG Root X1). Uncomment and paste the PEM.
// #define READER_ROOT_CA R"CERT(-----BEGIN CERTIFICATE-----
// ...
// -----END CERTIFICATE-----
// )CERT"
