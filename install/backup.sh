#!/usr/bin/env bash
# Daily filament-kit backup (run by filament-kit-backup.service as root).
# Writes /var/backups/filament-kit/<date>.tar.gz with a consistent copy of the
# Spoolman database, /etc/filament-kit and /var/lib/filament-kit; keeps 14 days.
set -euo pipefail
umask 077

DEST=/var/backups/filament-kit
SPOOLMAN_DB=/var/lib/spoolman/spoolman.db
PYTHON=/opt/filament-kit/venv/bin/python

mkdir -p "$DEST"
chmod 700 "$DEST"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [ -f "$SPOOLMAN_DB" ]; then
    # sqlite3 online backup: safe while Spoolman is writing.
    "$PYTHON" -I - "$SPOOLMAN_DB" "$work/spoolman.db" <<'EOF'
import sqlite3
import sys

src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close()
src.close()
EOF
else
    echo "note: $SPOOLMAN_DB not found, backing up settings and state only" >&2
fi

paths=()
for p in etc/filament-kit var/lib/filament-kit; do
    if [ -e "/$p" ]; then
        paths+=("$p")
    fi
done

out="$DEST/$(date +%F).tar.gz"
tmp="$out.tmp"
tar -czf "$tmp" -C "$work" . -C / "${paths[@]}"
mv -f "$tmp" "$out"

# Keep 14 days of backups.
find "$DEST" -maxdepth 1 -name '*.tar.gz' -type f -mtime +13 -delete

echo "backup written: $out"
