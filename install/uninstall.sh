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

# BEGIN foreign-spoolman check
# A Spoolman the kit did not install is someone's, wherever its program is: its program, unit, data and user all stay. The
# kit's own has the marker (from its first release), or, if an install stopped between the swap and the marker, the kit's unit.
SPOOLMAN_OPT=${SPOOLMAN_OPT:-/opt/spoolman}
SPOOLMAN_UNIT=${SPOOLMAN_UNIT:-/etc/systemd/system/spoolman.service}
KIT_SPOOLMAN=1
if [ ! -f "$SPOOLMAN_OPT/.fk-installed" ] && { [ -d "$SPOOLMAN_OPT" ] || [ -f "$SPOOLMAN_UNIT" ]; } \
        && ! grep -qs '^Description=Spoolman filament inventory' "$SPOOLMAN_UNIT"; then
    KIT_SPOOLMAN=0
fi
# END foreign-spoolman check

# Every unit of every module, from the installed program; the list below if it is already gone.
UNITS=""
if [ -x /opt/filament-kit/venv/bin/filament-kit ]; then
    # one per line; `for u in $UNITS` splits on newlines too
    UNITS=$(/opt/filament-kit/venv/bin/filament-kit modules units 2>/dev/null) || UNITS=""
fi
if [ -z "$UNITS" ]; then
    UNITS="filament-kit-setup.socket filament-kit-setup@.service filament-kit-setup-job@.service filament-kit-setup-apply.service filament-kit-web.service filament-kit-station.service filament-kit-station-pair.path filament-kit-station-pair.service filament-kit-build.path filament-kit-build.service filament-kit-library.timer filament-kit-library.service filament-kit-backup.timer filament-kit-backup.service filament-kit-update.timer filament-kit-update.service filament-kit.service spoolman.service"
fi
for u in $UNITS; do
    if [ "$u" = spoolman.service ] && [ "$KIT_SPOOLMAN" -eq 0 ]; then
        continue
    fi
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
        # listed and carrying the kit's own marker. A listed name whose file has the old shared header ('written
        # by mcp-route', the ops router's) stays: the listing may be stale and the file the ops route put back.
        # Every apply of this kit rewrites its route with its marker, so the kit's own routes all carry it.
        if [ -f "/etc/nginx/mcp.d/$n.conf" ] && head -n 1 "/etc/nginx/mcp.d/$n.conf" \
                | grep -qF 'written by filament-kit mcp-route'; then
            rm -f "/etc/nginx/mcp.d/$n.conf" && REMOTE_GONE=1
        fi
    done
    rm -f /etc/mcp-router/kit-routes
fi
# what is left in mcp.d is not the kit's (listed or not)
OTHER_ROUTES=""
for f in /etc/nginx/mcp.d/*.conf; do
    [ -f "$f" ] || continue
    OTHER_ROUTES="$OTHER_ROUTES $(basename "$f" .conf)"
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
# The local label reader (local_intake) has its own unit and prefix: its own uninstaller removes them, from the release
# folder the kit kept, before /opt/filament-kit (which holds that folder and its record) goes. The version is read as
# digits and dots only, so the path stays inside the root-owned store.
LI_STORE=/opt/filament-kit/local-intake
if [ -f "$LI_STORE/installed.json" ]; then
    LI_VER=$(sed -n 's/.*"version": *"\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)".*/\1/p' "$LI_STORE/installed.json" | head -n 1)
    LI_SH="$LI_STORE/$LI_VER/filament-kit-vision-$LI_VER/install/filament-kit-vision.sh"
    if [ -n "$LI_VER" ] && [ -f "$LI_SH" ]; then
        bash "$LI_SH" --uninstall --prefix /opt/filament-kit-vision \
            || echo "The local label reader's uninstaller failed: its unit and /opt/filament-kit-vision may be left."
    else
        echo "The local label reader's uninstaller was not found: its unit and /opt/filament-kit-vision may be left."
    fi
fi
rm -rf /opt/filament-kit
if [ "$KIT_SPOOLMAN" -eq 1 ]; then
    rm -rf /opt/spoolman /opt/spoolman.new /opt/spoolman.old /etc/systemd/system/spoolman.service.d
    REMOVED="filament-kit and Spoolman"
    KEPT_SPOOLMAN=" /var/lib/spoolman"
else
    echo "Left the Spoolman the kit did not install: its program, unit, settings, data and user."
    REMOVED="filament-kit"
    KEPT_SPOOLMAN=""
fi

if [ "$PURGE" -eq 1 ]; then
    rm -rf /etc/filament-kit /etc/filament-kit-station /var/lib/filament-kit /var/lib/filament-kit-web /var/lib/filament-kit-station /var/backups/filament-kit
    if [ "$KIT_SPOOLMAN" -eq 1 ]; then
        rm -rf /var/lib/spoolman
    fi
    rm -f /etc/tmpfiles.d/filament-kit-setup.conf
    # the certbot timer pin (remote.acme_window) is a setting of the kit's
    if [ -f /etc/systemd/system/certbot.timer.d/acme-window.conf ]; then
        rm -f /etc/systemd/system/certbot.timer.d/acme-window.conf
        rmdir /etc/systemd/system/certbot.timer.d 2>/dev/null || true
        systemctl daemon-reload
    fi
    KIT_USERS="filament-kit filament-kit-web"
    if [ "$KIT_SPOOLMAN" -eq 1 ]; then
        KIT_USERS="$KIT_USERS spoolman"
    fi
    for u in $KIT_USERS; do
        if id -u "$u" >/dev/null 2>&1; then
            userdel "$u" || true
        fi
    done
    echo "$REMOVED removed, including all data."
else
    echo "$REMOVED removed."
    echo "Kept: /etc/filament-kit /etc/filament-kit-station /var/lib/filament-kit /var/lib/filament-kit-web$KEPT_SPOOLMAN /var/backups/filament-kit"
    echo "Run again with --purge to delete them too."
fi
