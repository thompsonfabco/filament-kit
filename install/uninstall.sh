#!/usr/bin/env bash
# Remove filament-kit and its Spoolman. Run as root: sudo ./uninstall.sh
# Keeps settings (/etc/filament-kit), data (/var/lib/filament-kit,
# /var/lib/spoolman) and backups (/var/backups/filament-kit) unless --purge.
set -euo pipefail

PURGE=0
case "${1:-}" in
    "") ;;
    --purge) PURGE=1 ;;
    *) echo "usage: sudo ./uninstall.sh [--purge]" >&2; exit 2 ;;
esac

[ "$(id -u)" -eq 0 ] || { echo "error: run as root: sudo ./uninstall.sh" >&2; exit 1; }

if [ "$PURGE" -eq 1 ]; then
    echo "--purge deletes ALL spool data, settings, paired phones and backups."
    answer=""
    read -r -p "Type 'purge' to confirm: " answer || true
    [ "$answer" = purge ] || { echo "Cancelled; nothing removed."; exit 1; }
fi

UNITS="filament-kit-backup.timer filament-kit-backup.service filament-kit.service spoolman.service"
for u in $UNITS; do
    systemctl disable --now "$u" 2>/dev/null || true
    rm -f "/etc/systemd/system/$u"
done
systemctl daemon-reload

rm -f /etc/avahi/services/filament-kit.service
systemctl reload avahi-daemon 2>/dev/null || true
rm -f /usr/local/bin/filament-kit
rm -rf /opt/filament-kit /opt/spoolman /opt/spoolman.new /opt/spoolman.old

if [ "$PURGE" -eq 1 ]; then
    rm -rf /etc/filament-kit /var/lib/filament-kit /var/lib/spoolman /var/backups/filament-kit
    for u in filament-kit spoolman; do
        if id -u "$u" >/dev/null 2>&1; then
            userdel "$u" || true
        fi
    done
    echo "filament-kit and Spoolman removed, including all data."
else
    echo "filament-kit and Spoolman removed."
    echo "Kept: /etc/filament-kit /var/lib/filament-kit /var/lib/spoolman /var/backups/filament-kit"
    echo "Run again with --purge to delete them too."
fi
