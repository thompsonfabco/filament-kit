#!/usr/bin/env bash
# Fetch, verify and install Spoolman, and its systemd unit. Run as root by `filament-kit modules apply`
# (from /opt/filament-kit/resources/spoolman.sh) when the spoolman module is on; the spoolman user exists by then.
# This was step 3 of install.sh. Safe to run again: the marker skips a finished install.
set -euo pipefail

# Raising this pin needs a pre-swap copy of the database and a downgrade path in the same release: see
# test_a_spoolman_pin_bump_brings_its_database_copy.
SPOOLMAN_VERSION=v0.27.0
SPOOLMAN_URL="https://github.com/Donkie/Spoolman/releases/download/${SPOOLMAN_VERSION}/spoolman.zip"
SPOOLMAN_SHA256=bcc961af4c20d7ad7f1740f5609cd3efd94c4556baafaeba5036122dd7e46704

SPOOLMAN_OPT=/opt/spoolman
SPOOLMAN_DATA=/var/lib/spoolman

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# systemd/spoolman.service sits next to this script (resources/ or install/ in a checkout).
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

[ "$(id -u)" -eq 0 ] || die "run as root"

install -d -m 750 -o spoolman -g spoolman "$SPOOLMAN_DATA"

# Built in $SPOOLMAN_OPT.new and swapped in only when complete; the marker is
# written last, so a failed or interrupted install is redone on the next run.
# The marker carries the system Python version, so a distro Python upgrade rebuilds the venv.
PYVER=$(python3 --version 2>&1)
SPOOLMAN_MARKER="$SPOOLMAN_OPT/.fk-installed"
SPOOLMAN_STAMP="$SPOOLMAN_VERSION $PYVER"
if [ -f "$SPOOLMAN_MARKER" ] && [ "$(cat "$SPOOLMAN_MARKER")" = "$SPOOLMAN_STAMP" ]; then
    say "Spoolman $SPOOLMAN_VERSION already installed"
else
    say "Installing Spoolman $SPOOLMAN_VERSION"
    new="$SPOOLMAN_OPT.new"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp" "$new"' EXIT
    curl -fsSL --retry 3 -o "$tmp/spoolman.zip" "$SPOOLMAN_URL"
    echo "$SPOOLMAN_SHA256  $tmp/spoolman.zip" | sha256sum -c --quiet - \
        || die "spoolman.zip checksum mismatch"
    rm -rf "$new"
    mkdir -p "$new"
    unzip -q "$tmp/spoolman.zip" -d "$new"
    if [ ! -f "$new/requirements.txt" ] || [ ! -d "$new/spoolman" ]; then
        die "spoolman.zip does not look like a Spoolman release"
    fi
    python3 -m venv "$new/venv"
    "$new/venv/bin/python" -m pip install -q --upgrade pip
    "$new/venv/bin/python" -m pip install -q -r "$new/requirements.txt"
    "$new/venv/bin/python" -m compileall -q "$new/spoolman" >/dev/null || true
    chown -R root:root "$new"
    chmod -R go-w "$new"
    systemctl stop spoolman 2>/dev/null || true
    rm -rf "$SPOOLMAN_OPT.old"
    if [ -d "$SPOOLMAN_OPT" ]; then
        mv "$SPOOLMAN_OPT" "$SPOOLMAN_OPT.old"
    fi
    mv "$new" "$SPOOLMAN_OPT"
    # the venv was built under $new: point its scripts (alembic, which Spoolman runs at startup) at the final path
    grep -rlIZ -- "$new" "$SPOOLMAN_OPT/venv/bin" | xargs -0 -r sed -i "s|$new|$SPOOLMAN_OPT|g"
    rm -rf "$SPOOLMAN_OPT.old"
    printf '%s\n' "$SPOOLMAN_STAMP" > "$SPOOLMAN_MARKER"
    rm -rf "$tmp"
    trap - EXIT
fi

install -m 644 "$HERE/systemd/spoolman.service" /etc/systemd/system/spoolman.service
