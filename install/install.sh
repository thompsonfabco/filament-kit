#!/usr/bin/env bash
# filament-kit installer for Ubuntu 24.04 or newer. Run as root: sudo ./install.sh
# Safe to run again: an existing install is upgraded and keeps its data,
# settings, key and certificate. On upgrade the only question is the API key,
# and only if it is still missing.
set -euo pipefail

SPOOLMAN_VERSION=v0.27.0
SPOOLMAN_URL="https://github.com/Donkie/Spoolman/releases/download/${SPOOLMAN_VERSION}/spoolman.zip"
SPOOLMAN_SHA256=bcc961af4c20d7ad7f1740f5609cd3efd94c4556baafaeba5036122dd7e46704

ETC=/etc/filament-kit
STATE=/var/lib/filament-kit
OPT=/opt/filament-kit
SPOOLMAN_OPT=/opt/spoolman
SPOOLMAN_DATA=/var/lib/spoolman
VENV="$OPT/venv"
FK="$VENV/bin/filament-kit"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Files sit next to this script in the release tarball (install/...), or in the
# same directory when run from a source checkout (install/install.sh).
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -d "$HERE/install/systemd" ]; then
    RES="$HERE/install"
else
    RES="$HERE"
fi
WHEEL=""
for w in "$HERE"/filament_kit-*.whl; do
    if [ -f "$w" ]; then
        WHEEL="$w"
    fi
done

# ---------- 0. checks ----------
[ "$(id -u)" -eq 0 ] || die "run as root: sudo ./install.sh"
[ -n "$WHEEL" ] || die "no filament_kit-*.whl found next to install.sh"
[ -r /etc/os-release ] || die "cannot read /etc/os-release"
# shellcheck disable=SC1091
. /etc/os-release
major=${VERSION_ID%%.*}
if [ "${ID:-}" != ubuntu ] || ! [ "$major" -ge 24 ] 2>/dev/null; then
    die "Ubuntu 24.04 or newer is required (found ${PRETTY_NAME:-unknown})"
fi

FIRST_INSTALL=1
[ -f "$ETC/config.json" ] && FIRST_INSTALL=0

# ---------- 1. packages ----------
say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y python3-venv avahi-daemon qrencode curl unzip ffmpeg

# ---------- 2. users ----------
say "Creating service users"
for u in spoolman filament-kit; do
    if ! id -u "$u" >/dev/null 2>&1; then
        useradd --system --user-group --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin "$u"
    fi
done

install -d -m 750 -o spoolman -g spoolman "$SPOOLMAN_DATA"
install -d -m 750 -o filament-kit -g filament-kit "$STATE"
# setgid: files the CLI later writes here as root (config.json, key) keep the
# filament-kit group, so the service can still read them.
install -d -m 2750 -o root -g filament-kit "$ETC"

# ---------- 3. Spoolman ----------
# Built in $SPOOLMAN_OPT.new and swapped in only when complete; the marker is
# written last, so a failed or interrupted install is redone on the next run.
# Both markers carry the system Python version, so a distro Python upgrade rebuilds the venvs.
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

# ---------- 4. filament-kit ----------
# The marker is removed before and written after the venv work, so a failed
# install leaves no marker and the next run rebuilds the venv from scratch.
FK_MARKER="$OPT/.fk-installed"
say "Installing filament-kit ($(basename "$WHEEL"))"
mkdir -p "$OPT"
if [ ! -f "$FK_MARKER" ] || ! grep -qxF "$PYVER" "$FK_MARKER"; then
    rm -rf "$VENV"
fi
rm -f "$FK_MARKER"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q --upgrade "$WHEEL"
# Same version number on a rebuild: make sure the new code is in place.
"$VENV/bin/python" -m pip install -q --force-reinstall --no-deps "$WHEEL"
"$VENV/bin/python" -m compileall -q "$VENV/lib" >/dev/null || true
install -m 755 "$RES/backup.sh" "$OPT/backup.sh"
install -m 755 "$RES/filament-kit-cli.sh" /usr/local/bin/filament-kit
if [ -f "$HERE/app/filament-kit.apk" ]; then
    install -d -m 755 "$OPT/app"
    install -m 644 "$HERE/app/filament-kit.apk" "$OPT/app/filament-kit.apk"
    if [ -f "$HERE/app/version.txt" ]; then
        install -m 644 "$HERE/app/version.txt" "$OPT/app/version.txt"
    fi
fi
chown -R root:root "$OPT"
chmod -R go-w "$OPT"
{ basename "$WHEEL"; echo "$PYVER"; } > "$FK_MARKER"

# ---------- 5. first-install questions ----------
if [ "$FIRST_INSTALL" -eq 1 ]; then
    say "First-time setup"
    default_name=$(hostname)
    name=""
    read -r -p "Display name shown in the phone app (any text) [$default_name]: " name || true
    name=${name:-$default_name}
    FK_NAME="$name" FK_NO_SYSTEMD=1 "$VENV/bin/python" -I -c '
import os
from filament_kit import config
cfg = config.load()
cfg["server_name"] = os.environ["FK_NAME"]
config.save(cfg)
'
    chown root:filament-kit "$ETC/config.json"
    chmod 640 "$ETC/config.json"

    storage=""
    read -r -p "Use the default storage locations? [Y/n]: " storage || true
    case "$storage" in
        [nN]*)
            echo "Opening settings. Choose 2 (storage), make your changes, then 0 to save."
            FK_NO_SYSTEMD=1 "$FK" config
            ;;
    esac
fi

# Ask for the key whenever it is missing and someone is at the keyboard
# (also on upgrade, e.g. after an earlier install skipped it).
if [ ! -s "$ETC/anthropic_key" ] && [ -t 0 ]; then
    key=""
    read -r -s -p "Anthropic API key (typing is hidden, Enter to skip): " key || true
    echo
    if [ -n "$key" ]; then
        printf '%s\n' "$key" | install -m 640 -o root -g filament-kit /dev/stdin "$ETC/anthropic_key"
        echo "Key saved."
    else
        echo "No key entered. Add it later with: sudo filament-kit config  (option 4)"
    fi
    unset key
fi
for f in "$ETC/config.json" "$ETC/anthropic_key"; do
    if [ -f "$f" ]; then
        chown root:filament-kit "$f"
        chmod 640 "$f"
    fi
done

# ---------- 6. certificate (created once, never replaced) ----------
say "Server certificate"
"$FK" cert
chown root:filament-kit "$ETC/cert.pem" "$ETC/key.pem"
chmod 644 "$ETC/cert.pem"
chmod 640 "$ETC/key.pem"

# ---------- 7. services ----------
say "Installing services"
install -m 644 "$RES/systemd/spoolman.service" /etc/systemd/system/spoolman.service
install -m 644 "$RES/systemd/filament-kit.service" /etc/systemd/system/filament-kit.service
install -m 644 "$RES/systemd/filament-kit-backup.service" /etc/systemd/system/filament-kit-backup.service
install -m 644 "$RES/systemd/filament-kit-backup.timer" /etc/systemd/system/filament-kit-backup.timer
port=$("$VENV/bin/python" -I -c 'from filament_kit import config; print(int(config.load()["port"]))')
sed "s|<port>8710</port>|<port>$port</port>|" "$RES/avahi/filament-kit.service" > /etc/avahi/services/filament-kit.service
chmod 644 /etc/avahi/services/filament-kit.service
systemctl daemon-reload
systemctl enable --now avahi-daemon
systemctl reload avahi-daemon 2>/dev/null || systemctl restart avahi-daemon

systemctl enable spoolman
systemctl restart spoolman
say "Waiting for Spoolman to start"
ok=0
for _ in $(seq 1 90); do
    if curl -fs -o /dev/null http://127.0.0.1:7912/api/v1/info; then
        ok=1
        break
    fi
    sleep 2
done
[ "$ok" -eq 1 ] || die "Spoolman did not answer on port 7912; see: journalctl -u spoolman"

/usr/local/bin/filament-kit ensure-fields
systemctl enable filament-kit filament-kit-backup.timer
systemctl restart filament-kit
systemctl start filament-kit-backup.timer

# ---------- 8. check and pair ----------
say "Waiting for filament-kit to start"
for _ in $(seq 1 30); do
    if curl -kfs -o /dev/null "https://127.0.0.1:$port/api/info"; then
        break
    fi
    sleep 1
done

say "Status"
/usr/local/bin/filament-kit status || echo "Some checks failed; follow the 'fix:' lines above."

say "Pair a phone: open the filament-kit app and scan this code"
/usr/local/bin/filament-kit pair || true

echo
echo "Done. Spoolman: http://$(hostname).local:7912   Pair another phone: sudo filament-kit pair"
