#!/usr/bin/env bash
# Installed as /usr/local/bin/filament-kit.
# Settings and the certificate live in /etc/filament-kit (root-owned), so
# `config` and `cert` run as root; so does `modules`, which installs and starts
# services, `migrate-ops`, which replaces the Spoolman database and installs
# secrets, `migrate-scanner`, which reads the old calibration from /root and
# writes the map, `update`, which installs a new release, `uninstall`, which runs the kept release's
# uninstall.sh, `station` (the station PC: its pairing files in /etc/filament-kit-station), and `setup-code`,
# which shows or replaces the setup page's code in /etc/filament-kit, and `backup` and `restore`, which read and write
# everything the kit keeps.
# Everything else touches
# the service's state in /var/lib/filament-kit and runs as the filament-kit
# user, so the files it writes stay readable by the service.
set -euo pipefail

BIN=/opt/filament-kit/venv/bin/filament-kit
STATION_DIR=/etc/filament-kit-station
KIT_OPT=/opt/filament-kit

# install.sh removes this marker before it replaces the program and writes it once that is done, so no marker means
# an install stopped halfway, unless one is running now. This only says what to do: repairing is a root action, and
# reading `status` must not start one. The program may still work (`update --rollback` needs it), so it runs on if it can.
kit_installing() {
    systemctl is-active -q filament-kit-update.service filament-kit-setup-job@update.service \
        filament-kit-setup-job@rollback.service filament-kit-setup-job@apply.service 2>/dev/null && return 0
    pgrep -f '(^|/)install\.sh' >/dev/null 2>&1
}
if [ -d "$KIT_OPT" ] && [ ! -f "$KIT_OPT/.fk-installed" ] && ! kit_installing; then
    repair='curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh'
    earlier=$(sed -n 's/.*"previous": *"\([0-9][0-9.]*\)".*/\1/p' "$KIT_OPT/releases/state.json" 2>/dev/null) || earlier=""
    if [ -n "$earlier" ]; then
        repair="$repair --version $earlier"
    fi
    printf 'error: the last install or update stopped halfway. To repair it, run:\n  %s\n' "$repair" >&2
    if [ ! -x "$BIN" ]; then
        exit 1
    fi
fi

case "${1:-}" in
    config | cert | modules | remote | migrate-ops | migrate-scanner | update | uninstall | station | setup-code)
        exec "$BIN" "$@"
        ;;
esac
# `backup` and `restore` read and write everything the kit keeps, its root-owned files too.
case "${1:-}" in
    backup | restore) exec "$BIN" "$@" ;;
esac
# `web passphrase` writes the root-owned passphrase file (and refuses unless root); `web status` reads as the user.
if [ "${1:-}" = web ] && [ "${2:-}" = passphrase ]; then
    exec "$BIN" "$@"
fi
# `reader token` / `reader revoke` write the reader token file (handed to the service user) and refuse unless root;
# `reader tokens` only reads and runs as the user below.
if [ "${1:-}" = reader ] && { [ "${2:-}" = token ] || [ "${2:-}" = revoke ]; }; then
    exec "$BIN" "$@"
fi

if [ "$(id -u)" -eq 0 ]; then
    # `library add <file>`: the service user may not be able to read a file in the caller's home folder,
    # so root opens it and the CLI reads it on stdin.
    if [ "${1:-}" = library ] && [ "${2:-}" = add ] && [ -n "${3:-}" ] && [ "$3" != - ]; then
        if [ ! -f "$3" ] || [ ! -r "$3" ]; then
            printf 'error: %s: no such file (give the path to a library entry JSON file)\n' "$3" >&2
            exit 1
        fi
        exec runuser -u filament-kit -- "$BIN" library add - < "$3"
    fi
    # `status`: the station's pairing folder is closed to the service user, so root looks and status gets the answer
    # (one line, never the token). With no folder there is no pairing to find, and status says so itself.
    if [ "${1:-}" = status ] && [ -d "$STATION_DIR" ]; then
        state="$("$BIN" station pairing-state 2>/dev/null)" || state=failed
        exec runuser -u filament-kit -- "$BIN" "$@" "--station-pairing=$state"
    fi
    exec runuser -u filament-kit -- "$BIN" "$@"
fi
exec "$BIN" "$@"
