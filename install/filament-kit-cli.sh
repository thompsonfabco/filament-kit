#!/usr/bin/env bash
# Installed as /usr/local/bin/filament-kit.
# Settings and the certificate live in /etc/filament-kit (root-owned), so
# `config` and `cert` run as root. Everything else touches the service's state
# in /var/lib/filament-kit and runs as the filament-kit user, so the files it
# writes stay readable by the service.
set -euo pipefail

BIN=/opt/filament-kit/venv/bin/filament-kit

case "${1:-}" in
    config | cert)
        exec "$BIN" "$@"
        ;;
esac

if [ "$(id -u)" -eq 0 ]; then
    exec runuser -u filament-kit -- "$BIN" "$@"
fi
exec "$BIN" "$@"
