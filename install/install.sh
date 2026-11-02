#!/usr/bin/env bash
# filament-kit installer for Ubuntu 24.04 or newer.
# Run as root: sudo ./install.sh [--mode MODE] [--server NAME-OR-IP]
# MODE: server (default), station, all-in-one. A first install at a terminal asks for the mode
# (and offers custom). --server gives a station the kit server's address without a terminal;
# station mode needs it (or a terminal to ask at). Safe to run again: an existing install is upgraded and keeps its data,
# settings, modules, key and certificate; without --mode an upgrade asks nothing and changes no module.
# This script installs the program; `filament-kit modules apply` (run at the end) sets up the
# modules that are on, the same code path `sudo filament-kit config` uses later.
set -euo pipefail

ETC=/etc/filament-kit
STATE=/var/lib/filament-kit
OPT=/opt/filament-kit
VENV="$OPT/venv"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() { echo "usage: sudo ./install.sh [--mode server|station|all-in-one] [--server NAME-OR-IP]" >&2; exit 2; }
# one host name or address: station.allow never takes a range
bad_addr() { case "$1" in "" | */* | *"*"* | *" "*) return 0 ;; esac; return 1; }

MODE=""
SERVER_ADDR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --mode) [ $# -ge 2 ] || usage; MODE="$2"; shift 2 ;;
        --mode=*) MODE="${1#--mode=}"; shift ;;
        --server) [ $# -ge 2 ] || usage; SERVER_ADDR="$2"; shift 2 ;;
        --server=*) SERVER_ADDR="${1#--server=}"; shift ;;
        *) usage ;;
    esac
done
case "$MODE" in
    "" | server | station | all-in-one) ;;
    *) die "unknown mode '$MODE' (use server, station or all-in-one)" ;;
esac
if [ -n "$SERVER_ADDR" ] && bad_addr "$SERVER_ADDR"; then
    die "--server takes one name or address, e.g. spoolman.home.arpa or 192.0.2.10"
fi
# Checked before anything is installed: a station without the server's address would answer nobody.
if [ "$MODE" = station ] && [ -z "$SERVER_ADDR" ] && ! [ -t 0 ]; then
    die "station mode needs the kit server's address: run again with --server <name-or-IP>"
fi

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

# ---------- 1. packages (each module's packages come with `modules apply`) ----------
say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
# wait for the dpkg lock: on a fresh Ubuntu, unattended-upgrades often holds it for a few minutes
apt-get -o DPkg::Lock::Timeout=300 update -q
apt-get -o DPkg::Lock::Timeout=300 install -y python3-venv curl

# ---------- 2. user and folders (the spoolman and filament-kit-station users: created by apply) ----------
say "Creating the service user"
if ! id -u filament-kit >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin filament-kit
fi

install -d -m 750 -o filament-kit -g filament-kit "$STATE"
# presets (live upload, builds), the updated library, and local library additions
install -d -m 750 -o filament-kit -g filament-kit "$STATE/profiles" "$STATE/library" "$STATE/library-local"
# setgid: files the CLI later writes here as root (config.json, key) keep the
# filament-kit group, so the service can still read them.
install -d -m 2750 -o root -g filament-kit "$ETC"

# ---------- 3. filament-kit ----------
# The marker is removed before and written after the venv work, so a failed
# install leaves no marker and the next run rebuilds the venv from scratch.
# It carries the system Python version, so a distro Python upgrade rebuilds the venv.
PYVER=$(python3 --version 2>&1)
FK_MARKER="$OPT/.fk-installed"
say "Installing filament-kit ($(basename "$WHEEL"))"
mkdir -p "$OPT"
if [ ! -f "$FK_MARKER" ] || ! grep -qxF "$PYVER" "$FK_MARKER"; then
    rm -rf "$VENV"
fi
rm -f "$FK_MARKER"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
# [station,web]: any module can be switched on later without the tarball
"$VENV/bin/python" -m pip install -q --upgrade "$WHEEL[station,web]"
# Same version number on a rebuild: make sure the new code is in place.
"$VENV/bin/python" -m pip install -q --force-reinstall --no-deps "$WHEEL"
"$VENV/bin/python" -m compileall -q "$VENV/lib" >/dev/null || true
install -m 755 "$RES/backup.sh" "$OPT/backup.sh"
install -m 755 "$RES/filament-kit-cli.sh" /usr/local/bin/filament-kit
# Units, the avahi file and the Spoolman script: `modules apply` installs them from here.
rm -rf "$OPT/resources"
install -d -m 755 "$OPT/resources"
cp -R "$RES/systemd" "$RES/avahi" "$OPT/resources/"
install -m 755 "$RES/spoolman.sh" "$OPT/resources/spoolman.sh"
# The button panel's firmware (a binary and its VERSION): the station reflashes a panel on another version.
# In a release tarball it is install/panel/, in a source checkout station/panel/firmware/.
if [ -d "$RES/panel" ]; then PANEL_FW_SRC="$RES/panel"; else PANEL_FW_SRC="$HERE/../station/panel/firmware"; fi
install -d -m 755 "$OPT/resources/panel"
install -m 644 "$PANEL_FW_SRC/intake-panel.bin" "$PANEL_FW_SRC/VERSION" "$OPT/resources/panel/"
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

# ---------- 4. install mode ----------
# First install at a terminal: ask. --mode: set it, on any install. Upgrade without --mode: no
# questions, the modules stay as they are (a config without modules is the server mode).
CUSTOM=""
if [ -z "$MODE" ] && [ "$FIRST_INSTALL" -eq 1 ] && [ -t 0 ]; then
    say "Install mode"
    echo "  server      kit server with Spoolman, presets, library and backup"
    echo "  station     only the USB scale and NFC reader, for a kit server on another machine"
    echo "  all-in-one  server and station on this machine"
    echo "  custom      choose each module"
    choice=""
    read -r -p "Install mode: 1) server 2) station 3) all-in-one 4) custom [1] " choice || true
    case "${choice:-1}" in
        1 | server) MODE=server ;;
        2 | station) MODE=station ;;
        3 | all-in-one) MODE=all-in-one ;;
        4 | custom) MODE=custom ;;
        *) die "unknown choice '$choice'; run ./install.sh again" ;;
    esac
    if [ "$MODE" = custom ]; then
        # module list on fd 3, so the y/N answers still come from the terminal
        while IFS='|' read -r -u 3 name desc; do
            yn=""
            read -r -p "Turn on $name ($desc)? [y/N] " yn || true
            case "$yn" in
                [yY]*) CUSTOM="$CUSTOM,$name" ;;
            esac
        done 3< <("$VENV/bin/python" -I -c '
from filament_kit import modules
for m in modules.MODULES.values():
    print(f"{m.name}|{m.description}")
')
    fi
fi
# A station whose server is on another machine needs that server's address (spec section 3):
# station mode, or custom with station on and server off.
NEED_ADDR=0
case "$MODE" in
    station) NEED_ADDR=1 ;;
    custom)
        case "$CUSTOM," in
            *,station,*)
                case "$CUSTOM," in
                    *,server,*) ;;
                    *) NEED_ADDR=1 ;;
                esac
                ;;
        esac
        ;;
esac
if [ "$NEED_ADDR" -eq 1 ] && [ -z "$SERVER_ADDR" ]; then
    [ -t 0 ] || die "station mode needs the kit server's address: run again with --server <name-or-IP>"
    while :; do
        SERVER_ADDR=""
        read -r -p "Server address (name or IP): " SERVER_ADDR || true
        if bad_addr "$SERVER_ADDR"; then
            echo "Give one name or address, e.g. spoolman.home.arpa or 192.0.2.10."
        else
            break
        fi
    done
fi
[ "$NEED_ADDR" -eq 1 ] || SERVER_ADDR=""  # the address only matters for a station without a local server
if [ -z "$MODE" ] && [ "$FIRST_INSTALL" -eq 1 ]; then
    MODE=server  # non-interactive first install
fi
if [ -n "$MODE" ]; then
    # Only the modules and the station link change; on a first install there is no
    # server_name yet, so `modules apply` asks the first-run questions.
    FK_MODE="$MODE" FK_MODULES="$CUSTOM" FK_SERVER="$SERVER_ADDR" FK_NO_SYSTEMD=1 "$VENV/bin/python" -I -c '
import json, os, sys
from filament_kit import config, modules
f = config.paths().etc / "config.json"
cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
mode = os.environ["FK_MODE"]
if mode == "custom":
    on = set(filter(None, os.environ["FK_MODULES"].split(",")))
    cfg["modules"] = {n: n in on for n in modules.MODULES}
    if {"station", "server"} <= on:
        # station and server on one machine: as all-in-one, the server reads the local station
        st = cfg.setdefault("station", {})
        st["allow"] = ["127.0.0.1"]
        st["url"] = "http://127.0.0.1:5003"
else:
    cfg = modules.set_mode(cfg, mode)
if os.environ["FK_SERVER"]:
    cfg.setdefault("station", {})["allow"] = [os.environ["FK_SERVER"]]
try:
    modules.validate(cfg)
except modules.ModuleError as e:
    sys.exit(f"error: {e}\nfix: run ./install.sh again and choose again")
config.save(cfg)
print("Install mode: " + mode)
'
    chown root:filament-kit "$ETC/config.json"
    chmod 640 "$ETC/config.json"
fi

# ---------- 5. the modules ----------
exec /usr/local/bin/filament-kit modules apply
