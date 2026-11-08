#!/bin/sh
# filament-kit printer pack for Klipper printers: install | status | uninstall (see fkpack.py --help).
# Run on the printer as its normal user (it asks before every change and uses sudo only for services).
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null 2>&1 || { echo "python3 is needed" >&2; exit 1; }
exec python3 -I fkpack.py "$@"
