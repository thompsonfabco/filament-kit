#!/bin/sh
# Builds the Printer Station firmware with no settings in it and refreshes the copy the kit flashes
# (firmware/printer-station.bin + VERSION). Run after changing src/ or lib/, then commit both; a release carries them.
# The kit writes each reader's settings over USB after flashing (lib/reader_core/src/settings.h), so this one image
# serves every reader. printer-station.bin is one merged image written at address 0: the bootloader, partition table,
# boot_app0 (otadata pointing at app0) and application, at the offsets PlatformIO's own upload writes them.
# Needs PlatformIO (PIO: its command, default pio) and esptool 5.6.0, the kit's pin (ESPTOOL: its command, default
# python3 -m esptool). boot_app0.bin comes from PlatformIO's Arduino core package, under PLATFORMIO_CORE_DIR
# (default ~/.platformio). A src/secrets.h would be compiled in: the script refuses to run while one exists.
set -e
cd "$(dirname "$0")"
[ ! -e src/secrets.h ] || { echo "src/secrets.h exists: move it away, the bundled image must hold no settings" >&2; exit 1; }
${PIO:-pio} run -e esp32-c3-supermini
build=.pio/build/esp32-c3-supermini
boot_app0="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin"
mkdir -p firmware
${ESPTOOL:-python3 -m esptool} --chip esp32c3 merge-bin -o firmware/printer-station.bin \
  0x0 "$build/bootloader.bin" 0x8000 "$build/partitions.bin" 0xe000 "$boot_app0" 0x10000 "$build/firmware.bin"
cp "$build/fw_build.txt" firmware/VERSION
[ -s firmware/VERSION ] || { echo "no fw_build.txt from the build" >&2; exit 1; }
echo "firmware/printer-station.bin: build $(cat firmware/VERSION), $(wc -c < firmware/printer-station.bin) bytes"
