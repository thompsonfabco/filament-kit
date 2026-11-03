#!/usr/bin/env bash
# Remove filament-kit, its Spoolman and its station. Run as root: sudo ./uninstall.sh
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

# Every unit of every module, from the installed program; the list below if it is already gone.
UNITS=""
if [ -x /opt/filament-kit/venv/bin/filament-kit ]; then
    # one per line; `for u in $UNITS` splits on newlines too
    UNITS=$(/opt/filament-kit/venv/bin/filament-kit modules units 2>/dev/null) || UNITS=""
fi
if [ -z "$UNITS" ]; then
    UNITS="filament-kit-web.service filament-kit-station.service filament-kit-build.path filament-kit-build.service filament-kit-library.timer filament-kit-library.service filament-kit-backup.timer filament-kit-backup.service filament-kit-update.timer filament-kit-update.service filament-kit.service spoolman.service"
fi
for u in $UNITS; do
    systemctl disable --now "$u" 2>/dev/null || true
    rm -f "/etc/systemd/system/$u"
done
rm -rf /etc/systemd/system/filament-kit-station.service.d
systemctl daemon-reload
# The station's udev rule. Its other system changes (brltty removed, ModemManager off, sleep masked,
# audio levels) are left as they are.
# (99-filament-kit-station.rules is its name before it was renamed to sort after the ops station's rule.)
if [ -f /etc/udev/rules.d/99-zz-filament-kit-station.rules ] || [ -f /etc/udev/rules.d/99-filament-kit-station.rules ]; then
    rm -f /etc/udev/rules.d/99-zz-filament-kit-station.rules /etc/udev/rules.d/99-filament-kit-station.rules
    udevadm control --reload 2>/dev/null || true
fi
# The station user owns no data; its unit is gone, so it goes on every uninstall.
if id -u filament-kit-station >/dev/null 2>&1; then
    userdel filament-kit-station || true
fi

rm -f /etc/avahi/services/filament-kit.service
systemctl reload avahi-daemon 2>/dev/null || true
rm -f /usr/local/bin/filament-kit
# remote: the kit's own nginx and certbot files, as `modules disable remote` removes them: its routes (only files
# mcp-route wrote), its router conf and its deploy hook. nginx, certbot, the certificate (/etc/mcp-router/tls),
# mcp-route, its hook and other routes stay. While /etc/nginx/mcp.d holds routes the kit did not add (the owner's
# amazon and h2d routes), the router conf stays too: once the ops router is gone it is what serves them.
REMOTE_GONE=0
KIT_ROUTES=""
if [ -f /etc/mcp-router/kit-routes ]; then
    KIT_ROUTES=$(tr -s '[:space:]' ' ' < /etc/mcp-router/kit-routes)
    for n in $KIT_ROUTES; do
        case "$n" in *[!a-z0-9-]*|"") continue ;; esac
        if [ -f "/etc/nginx/mcp.d/$n.conf" ] && grep -q 'written by mcp-route' "/etc/nginx/mcp.d/$n.conf"; then
            rm -f "/etc/nginx/mcp.d/$n.conf" && REMOTE_GONE=1
        fi
    done
    rm -f /etc/mcp-router/kit-routes
fi
OTHER_ROUTES=""
for f in /etc/nginx/mcp.d/*.conf; do
    [ -f "$f" ] || continue
    n=$(basename "$f" .conf)
    case " $KIT_ROUTES " in *" $n "*) continue ;; esac
    OTHER_ROUTES="$OTHER_ROUTES $n"
done
REMOTE_FILES=/etc/letsencrypt/renewal-hooks/deploy/filament-kit
if [ -z "$OTHER_ROUTES" ]; then
    REMOTE_FILES="/etc/nginx/conf.d/filament-kit-router.conf $REMOTE_FILES"
elif [ -f /etc/nginx/conf.d/filament-kit-router.conf ]; then
    echo "Remote: kept the kit's router conf /etc/nginx/conf.d/filament-kit-router.conf: it serves the other"
    echo "routes in /etc/nginx/mcp.d (${OTHER_ROUTES# }). Remove it by hand once nothing needs them."
fi
for f in $REMOTE_FILES; do
    [ -e "$f" ] && rm -f "$f" && REMOTE_GONE=1
done
if [ "$REMOTE_GONE" -eq 1 ]; then
    if command -v nginx >/dev/null 2>&1 && nginx -t -q 2>/dev/null && systemctl is-active -q nginx; then
        systemctl reload nginx || true
    fi
    echo "Removed the kit's own remote files. nginx, certbot, the certificate in /etc/mcp-router and"
    echo "mcp-route were left; remove them with apt and rm if nothing else uses them."
fi
rm -rf /opt/filament-kit /opt/spoolman /opt/spoolman.new /opt/spoolman.old

if [ "$PURGE" -eq 1 ]; then
    rm -rf /etc/filament-kit /var/lib/filament-kit /var/lib/spoolman /var/backups/filament-kit
    # the certbot timer pin (remote.acme_window) is a setting of the kit's
    if [ -f /etc/systemd/system/certbot.timer.d/acme-window.conf ]; then
        rm -f /etc/systemd/system/certbot.timer.d/acme-window.conf
        rmdir /etc/systemd/system/certbot.timer.d 2>/dev/null || true
        systemctl daemon-reload
    fi
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
