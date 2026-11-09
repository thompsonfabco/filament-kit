#!/bin/sh
# Builds the panel firmware and refreshes the copy the station flashes itself (firmware/intake-panel.bin + VERSION).
# Run on the desktop (Git Bash) after changing src/, and bump VERSION in src/main.cpp first: the station service
# reflashes a panel whose HELLO version differs from firmware/VERSION. Then commit both; a release carries them.
set -e
cd "$(dirname "$0")"
${PIO:-py -3 -m platformio} run  # PIO: another PlatformIO command if py -3 has none
mkdir -p firmware
cp .pio/build/d1_mini/firmware.bin firmware/intake-panel.bin
sed -n 's/^static const char \*VERSION = "\([^"]*\)";.*/\1/p' src/main.cpp > firmware/VERSION
[ -s firmware/VERSION ] || { echo "no VERSION in src/main.cpp" >&2; exit 1; }
echo "firmware/intake-panel.bin: version $(cat firmware/VERSION), $(wc -c < firmware/intake-panel.bin) bytes"
