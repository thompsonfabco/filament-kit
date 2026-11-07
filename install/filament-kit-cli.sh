#!/usr/bin/env bash
# Installed as /usr/local/bin/filament-kit.
# Settings and the certificate live in /etc/filament-kit (root-owned), so
# `config` and `cert` run as root; so does `modules`, which installs and starts
# services, `migrate-ops`, which replaces the Spoolman database and installs
# secrets, `migrate-scanner`, which reads the old calibration from /root and
# writes the map, `update`, which installs a new release, and `station` (the station PC: its pairing files
# in /etc/filament-kit). Everything else touches
# the service's state in /var/lib/filament-kit and runs as the filament-kit
# user, so the files it writes stay readable by the service.
set -euo pipefail

BIN=/opt/filament-kit/venv/bin/filament-kit

case "${1:-}" in
    config | cert | modules | remote | migrate-ops | migrate-scanner | update | station)
        exec "$BIN" "$@"
        ;;
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
    exec runuser -u filament-kit -- "$BIN" "$@"
fi
exec "$BIN" "$@"
