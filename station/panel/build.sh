#!/bin/sh
# Builds the panel firmware and refreshes the copy the station flashes itself (firmware/intake-panel.bin + VERSION).
# Run on the desktop (Git Bash) after changing src/, and bump VERSION in src/main.cpp first: the station service
# reflashes a panel whose HELLO version differs from firmware/VERSION. Then commit both; a release carries them.
# intake-panel.bin is one merged image, written at address 0: the bootloader, partition table, boot_app0 (otadata
# pointing at app0) and application, at the offsets PlatformIO's own upload writes them (pio run -t upload -v).
# Needs PlatformIO (PIO: its command, default py -3 -m platformio) and esptool 5.6.0, the kit's pin (ESPTOOL: its
# command, default python -m esptool; pip install esptool==5.6.0). boot_app0.bin comes from PlatformIO's Arduino core
# package, under PLATFORMIO_CORE_DIR (default ~/.platformio).
set -e
cd "$(dirname "$0")"
${PIO:-py -3 -m platformio} run -e esp32-c3-supermini  # PIO: another PlatformIO command if py -3 has none
build=.pio/build/esp32-c3-supermini
boot_app0="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin"
mkdir -p firmware
${ESPTOOL:-python -m esptool} --chip esp32c3 merge-bin -o firmware/intake-panel.bin \
  0x0 "$build/bootloader.bin" 0x8000 "$build/partitions.bin" 0xe000 "$boot_app0" 0x10000 "$build/firmware.bin"
sed -n 's/^static const char \*VERSION = "\([^"]*\)";.*/\1/p' src/main.cpp > firmware/VERSION
[ -s firmware/VERSION ] || { echo "no VERSION in src/main.cpp" >&2; exit 1; }
echo "firmware/intake-panel.bin: version $(cat firmware/VERSION), $(wc -c < firmware/intake-panel.bin) bytes"
