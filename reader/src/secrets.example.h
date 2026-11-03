// Copy to secrets.h and fill in. secrets.h is the real file; keep it out of
// version control (.gitignore lists it).
#pragma once
static const char* WIFI_SSID = "your-ssid";
static const char* WIFI_PASS = "your-wifi-password";
// Must match AUTH_TOKEN in /etc/h2d-scanner/env on the VM.
static const char* AUTH_TOKEN = "your-48-hex-char-token";
