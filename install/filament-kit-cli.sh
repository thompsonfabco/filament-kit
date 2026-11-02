#!/usr/bin/env bash
# Installed as /usr/local/bin/filament-kit.
# Settings and the certificate live in /etc/filament-kit (root-owned), so
# `config` and `cert` run as root; so does `modules`, which installs and starts
# services. Everything else touches the service's state in /var/lib/filament-kit
# and runs as the filament-kit user, so the files it writes stay readable by the
# service.
set -euo pipefail

BIN=/opt/filament-kit/venv/bin/filament-kit

case "${1:-}" in
    config | cert | modules | remote)
        exec "$BIN" "$@"
        ;;
esac

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
