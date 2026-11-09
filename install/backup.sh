#!/usr/bin/env bash
# Daily filament-kit backup (run by filament-kit-backup.service as root).
# Writes /var/backups/filament-kit/<date>.tar.gz with a consistent copy of the
# Spoolman database, /etc/filament-kit and /var/lib/filament-kit; keeps backup.keep_days days (default 14).
# The setup page offers each as the same zip `filament-kit backup create` writes (filament_kit/backup.py).
set -euo pipefail
umask 077

DEST=/var/backups/filament-kit
SPOOLMAN_DB=/var/lib/spoolman/spoolman.db
PYTHON=/opt/filament-kit/venv/bin/python

mkdir -p "$DEST"
# root:filament-kit 750: the setup page lists the backups and offers each as a zip download
chmod 750 "$DEST"
chgrp filament-kit "$DEST" 2>/dev/null || chmod 700 "$DEST"
KEEP=$("$PYTHON" -I -m filament_kit.backup keep-days 2>/dev/null) || KEEP=14
case "$KEEP" in ''|*[!0-9]*) KEEP=14 ;; esac

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
for p in etc/filament-kit var/lib/filament-kit var/lib/filament-kit-web; do
    if [ -e "/$p" ]; then
        paths+=("$p")
    fi
done

out="$DEST/$(date +%F).tar.gz"
tmp="$out.tmp"
# Skipped: data that is downloaded again (the uploaded Bambu system presets, earlier library versions)
# and half-written builds.
# --acls/--xattrs: the web unit's grants (filament_kit/web_access.py) come back with a restore
tar -czf "$tmp" --acls --xattrs \
    --exclude='var/lib/filament-kit/profiles/live/system' \
    --exclude='var/lib/filament-kit/library/versions' \
    --exclude='var/lib/filament-kit/profiles/builds/*.tmp' \
    -C "$work" . -C / "${paths[@]}"
chgrp filament-kit "$tmp" 2>/dev/null && chmod 640 "$tmp"
mv -f "$tmp" "$out"

# Keep backup.keep_days days (14 unless set on the setup page): the nightly ones, the page's and a restore's own.
find "$DEST" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name 'filament-kit-backup-*.zip' -o -name 'pre-restore-*.zip' \) \
    -mtime +$((KEEP - 1)) -delete

echo "backup written: $out"
