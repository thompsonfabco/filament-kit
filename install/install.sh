#!/usr/bin/env bash
# filament-kit installer for Ubuntu 24.04 or newer.
# Run as root: sudo ./install.sh [--mode MODE | --modules a,b,c [--set KEY=VALUE]...] [--server NAME-OR-IP]
#                                [--restore BACKUP.zip]   (--restore: this machine takes the backup's modules and data)
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
# get.sh deletes its unpacked folder, so telling people to rerun this script would point at nothing
AGAIN='curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh'
usage() { echo "usage: sudo ./install.sh [--mode server|station|all-in-one | --modules a,b,c [--set KEY=VALUE]...] [--server NAME-OR-IP] [--restore BACKUP.zip]" >&2; exit 2; }
# one host name or address: station.allow never takes a range
bad_addr() { case "$1" in "" | */* | *"*"* | *" "*) return 0 ;; esac; return 1; }

# --set KEY=VALUE: a setting a chosen module needs, the ones the module menu asks for (repeatable)
add_set() {
    case "$1" in
        web.public_url=* | orders.file=* | station.allow=*) ;;
        *) die "--set takes web.public_url=URL, orders.file=PATH or station.allow=ADDRESS (got '$1')" ;;
    esac
    SETS="$SETS${SETS:+
}set $1"
}

MODE=""
CUSTOM=""
SETS=""
SERVER_ADDR=""
RESTORE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --mode) [ $# -ge 2 ] || usage; MODE="$2"; shift 2 ;;
        --mode=*) MODE="${1#--mode=}"; shift ;;
        --modules) [ $# -ge 2 ] || usage; CUSTOM="$2"; shift 2 ;;
        --modules=*) CUSTOM="${1#--modules=}"; shift ;;
        --set) [ $# -ge 2 ] || usage; add_set "$2"; shift 2 ;;
        --set=*) add_set "${1#--set=}"; shift ;;
        --server) [ $# -ge 2 ] || usage; SERVER_ADDR="$2"; shift 2 ;;
        --server=*) SERVER_ADDR="${1#--server=}"; shift ;;
        --hub) [ $# -ge 2 ] || usage; SERVER_ADDR="$2"; shift 2 ;;
        --hub=*) SERVER_ADDR="${1#--hub=}"; shift ;;
        --restore) [ $# -ge 2 ] || usage; RESTORE="$2"; shift 2 ;;
        --restore=*) RESTORE="${1#--restore=}"; shift ;;
        *) usage ;;
    esac
done
if [ -n "$RESTORE" ]; then
    [ -f "$RESTORE" ] || die "$RESTORE: no such file (give the backup zip from the setup page or filament-kit backup create)"
    RESTORE="$(cd "$(dirname "$RESTORE")" && pwd)/$(basename "$RESTORE")"
fi
case "$MODE" in            # the Hub's setup names are the old words under new names
    hub) MODE=server ;;
    weigh-station) MODE=station ;;
    hub-with-weigh-station) MODE=all-in-one ;;
esac
case "$MODE" in
    "" | server | station | all-in-one) ;;
    *) die "unknown mode '$MODE' (use server, station or all-in-one; to choose single modules use --modules a,b,c)" ;;
esac
if [ -n "$CUSTOM" ]; then
    [ -z "$MODE" ] || die "use --mode or --modules, not both"
    MODE=custom                # internal: reached only through --modules or the installer's menu
    CUSTOM=",$CUSTOM"          # names are checked and what they need is added just before the address check
fi
if [ -n "$SETS" ]; then
    [ "$MODE" = custom ] || die "--set goes with --modules (a custom module list)"
    FLAG_ADDR=$(printf '%s\n' "$SETS" | sed -n 's/^set station\.allow=//p' | head -n 1)
    [ -z "$SERVER_ADDR" ] && SERVER_ADDR="$FLAG_ADDR"
fi
if [ -n "$SERVER_ADDR" ] && bad_addr "$SERVER_ADDR"; then
    die "--server takes one name or address, e.g. kit.example.lan or 192.0.2.10"
fi
# A station re-run without --server and without a terminal (the updater, get.sh piped to bash) keeps the server
# address the station already has: the first non-local station.allow entry of its config. At a terminal the
# custom menu or the "Server address" prompt below decide. FK_ETC: tests only, as in the program.
SAVED_CFG="${FK_ETC:-$ETC}/config.json"
if [ -z "$SERVER_ADDR" ] && ! [ -t 0 ] && { [ "$MODE" = station ] || [ "$MODE" = custom ]; } \
        && [ -f "$SAVED_CFG" ] && command -v python3 >/dev/null 2>&1; then
    SAVED_ADDR=$(python3 -I - "$SAVED_CFG" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        allow = (json.load(fh).get("station") or {}).get("allow") or []
except (OSError, ValueError, AttributeError):
    allow = []
print(next((str(a).strip() for a in allow if str(a).strip() not in ("127.0.0.1", "localhost", "::1")), ""))
PYEOF
)
    SAVED_ADDR=$(printf '%s' "$SAVED_ADDR" | tr -d '\r')
    if [ -n "$SAVED_ADDR" ] && ! bad_addr "$SAVED_ADDR"; then
        SERVER_ADDR="$SAVED_ADDR"
        echo "using the station's saved server address $SAVED_ADDR (--server changes it)" >&2
    fi
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
if [ "${FK_NO_SYSTEMD:-}" != 1 ] && [ ! -d /run/systemd/system ]; then
    die "systemd is not running on this computer, and filament-kit runs as systemd services"
fi
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    echo "note: this is WSL, which is not a supported server: a phone on your network cannot reach a server inside it."
fi

# --modules names are checked now, before any package or venv work, against the module registry inside the
# wheel (a wheel is a zip file; the names are the _m("name", ...) entries of filament_kit/modules.py).
if [ "$MODE" = custom ] && [ -n "$CUSTOM" ]; then
    python3 - "$WHEEL" "$CUSTOM" <<'PYEOF' || exit 1
import re, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    text = z.read("filament_kit/modules.py").decode("utf-8")
known = re.findall(r'_m[(]"([a-z_]+)"', text)
bad = [n for n in sys.argv[2].split(",") if n and n not in known]
if bad:
    sys.exit("error: unknown module %s\nfix: use module names from: %s" % (", ".join(bad), ", ".join(known)))
PYEOF
fi

FIRST_INSTALL=1
[ -f "$ETC/config.json" ] && FIRST_INSTALL=0

# ---------- 1. packages (each module's packages come with `modules apply`) ----------
say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
# wait for the dpkg lock: on a fresh Ubuntu, unattended-upgrades often holds it for a few minutes. stdin from
# /dev/null: apt never reads the terminal (the questions of this script do)
APT_FAILED="the package manager could not download; check the network and run the same command again"
apt-get -o DPkg::Lock::Timeout=300 update -q </dev/null || die "$APT_FAILED"
apt-get -o DPkg::Lock::Timeout=300 install -y python3-venv curl </dev/null || die "$APT_FAILED"

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
# root's backups (a restore's pinned upload too): the setup page's helper may write here, so it must exist before it runs
install -d -m 700 -o root -g root /var/backups/filament-kit

# ---------- 3. filament-kit ----------
# The marker is removed before and written after the venv work, so a failed
# install leaves no marker and the next run rebuilds the venv from scratch.
# It carries the system Python version, so a distro Python upgrade rebuilds the venv.
PYVER=$(python3 --version 2>&1)
FK_MARKER="$OPT/.fk-installed"
say "Installing filament-kit ($(basename "$WHEEL"))"
mkdir -p "$OPT"
# Earlier versions bundled the spec library inside the program. Keep a copy of it before the venv is replaced and
# hand it to the new program below, so an upgrade keeps its library (and its profiles do not change).
LEGACY_LIB=""
if [ ! -f "$STATE/library/current.json" ]; then
    for d in "$VENV"/lib/python*/site-packages/filament_kit/library_data; do
        if [ -f "$d/index.json" ] && [ -d "$d/library" ]; then
            LEGACY_LIB=$(mktemp -d)
            cp -a "$d/." "$LEGACY_LIB/"
            chmod -R a+rX "$LEGACY_LIB"
            break
        fi
    done
fi
if [ ! -f "$FK_MARKER" ] || ! grep -qxF "$PYVER" "$FK_MARKER"; then
    rm -rf "$VENV"
fi
rm -f "$FK_MARKER"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
# [station,web]: any module can be switched on later without the tarball
"$VENV/bin/python" -m pip install -q --upgrade "${WHEEL}[station,web]"
# Same version number on a rebuild: make sure the new code is in place.
"$VENV/bin/python" -m pip install -q --force-reinstall --no-deps "$WHEEL"
"$VENV/bin/python" -m compileall -q "$VENV/lib" >/dev/null || true
if [ -n "$LEGACY_LIB" ]; then
    runuser -u filament-kit -- "$VENV/bin/filament-kit" library adopt "$LEGACY_LIB"         || echo "warning: could not keep the earlier library; run: sudo filament-kit library update"
    rm -rf "$LEGACY_LIB"
fi
install -m 755 "$RES/backup.sh" "$OPT/backup.sh"
install -m 755 "$RES/filament-kit-cli.sh" /usr/local/bin/filament-kit
# Units, the avahi file and the Spoolman script: `modules apply` installs them from here.
# Everything but the Piper voices (60-80 MB each; `modules apply` checks their hashes): kept across upgrades.
if [ -d "$OPT/resources" ]; then
    find "$OPT/resources" -mindepth 1 -maxdepth 1 ! -name voice -exec rm -rf {} +
fi
install -d -m 755 "$OPT/resources"
cp -R "$RES/systemd" "$RES/avahi" "$RES/remote" "$OPT/resources/"
install -m 755 "$RES/spoolman.sh" "$OPT/resources/spoolman.sh"
# 0.4.0's setup job unit is gone (apply-run with it): an upgrade removes the file it left behind.
OLD_APPLY_UNIT=${FK_SYSTEMD_DIR:-/etc/systemd/system}/filament-kit-setup-apply.service
if [ -e "$OLD_APPLY_UNIT" ]; then
    rm -f "$OLD_APPLY_UNIT"
    if [ "${FK_NO_SYSTEMD:-}" != 1 ]; then systemctl daemon-reload || true; fi
fi
# The button panel's firmware (a binary and its VERSION): the station reflashes a panel on another version.
# In a release tarball it is install/panel/, in a source checkout station/panel/firmware/.
if [ -d "$RES/panel" ]; then PANEL_FW_SRC="$RES/panel"; else PANEL_FW_SRC="$HERE/../station/panel/firmware"; fi
install -d -m 755 "$OPT/resources/panel"
install -m 644 "$PANEL_FW_SRC/intake-panel.bin" "$PANEL_FW_SRC/VERSION" "$OPT/resources/panel/"
# The Printer Station's firmware (no settings in it: `filament-kit reader setup` writes them over USB).
# In a release tarball it is install/reader/, in a source checkout reader/firmware/.
if [ -d "$RES/reader" ]; then READER_FW_SRC="$RES/reader"; else READER_FW_SRC="$HERE/../reader/firmware"; fi
install -d -m 755 "$OPT/resources/reader"
install -m 644 "$READER_FW_SRC/printer-station.bin" "$READER_FW_SRC/VERSION" "$OPT/resources/reader/"
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

# ---------- restore: the backup's modules and data instead of the questions below ----------
if [ -n "${RESTORE:-}" ]; then
    exec /usr/local/bin/filament-kit restore --yes "$RESTORE"
fi

# ---------- 4. install mode ----------
# First install at a terminal: ask. --mode: set it, on any install. Upgrade without --mode: no
# questions, the modules stay as they are (a config without modules is the server mode).
AI_INTAKE=""
if [ -z "$MODE" ] && [ "$FIRST_INSTALL" -eq 1 ] && [ -t 0 ]; then
    say "Install mode"
    echo "  server      kit server with Spoolman, printers, presets and backup (AI label reading and library on request)"
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
        *) die "unknown choice '$choice'; run the install command again: $AGAIN" ;;
    esac
    if [ "$MODE" = custom ]; then
        # the same checklist as `filament-kit config` -> Modules (cursor keys and Space; drawn on /dev/tty, as
        # stdout is captured here; the numbered list without a usable terminal); prompts on the terminal, the
        # choice on stdout
        # First line: the modules, comma separated. Then one `set <key>=<value>` per setting the menu asked for.
        MENU_OUT=$("$VENV/bin/filament-kit" modules menu --raw) || die "no modules chosen; run the install command again: $AGAIN"
        CUSTOM=",$(printf '%s
' "$MENU_OUT" | head -n 1)"
        SETS=$(printf '%s
' "$MENU_OUT" | tail -n +2)
        # the server's address for a station without a server is the one setting the installer itself uses below
        MENU_ADDR=$(printf '%s
' "$SETS" | sed -n 's/^set station\.allow=//p' | head -n 1)
        [ -z "$SERVER_ADDR" ] && SERVER_ADDR="$MENU_ADDR"
    elif [ "$MODE" != station ]; then
        # AI is optional (off unless chosen here or later in `filament-kit config`); spools are added by hand without it
        yn=""
        read -r -p "Read spool labels from photos with Claude (ai_intake; needs an Anthropic API key)? [y/N] " yn || true
        case "$yn" in
            [yY]*) AI_INTAKE=1 ;;
        esac
    fi
fi
# A custom list is closed first (what the chosen modules need goes on too), so the checks below see
# the real set: --modules station,printers has a server and needs no address.
if [ "$MODE" = custom ]; then
    CUSTOM=$(FK_MODULES="$CUSTOM" "$VENV/bin/python" -I -c '
import os, sys
from filament_kit import modules
try:
    chosen, notes = modules.close_selection(os.environ["FK_MODULES"].split(","))
except modules.ModuleError as e:
    names = ", ".join(modules.MODULES)
    sys.exit(f"error: {e}\nfix: use module names from: {names}")
for note in notes:
    print(note, file=sys.stderr)
print("," + ",".join(n for n in modules.MODULES if n in chosen))
') || exit 1
fi
# With the server on this machine the station reads it over loopback; an address would break that link.
case "$MODE:$CUSTOM,:$SETS" in
    custom:*,server,*:*"set station.allow="*)
        die "station.allow is for a station without the server on this machine; with server in the module list the station is linked locally, so drop --set station.allow" ;;
esac
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
            echo "Give one name or address, e.g. kit.example.lan or 192.0.2.10."
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
    FK_MODE="$MODE" FK_MODULES="$CUSTOM" FK_AI="$AI_INTAKE" FK_SETS="$SETS" FK_SERVER="$SERVER_ADDR" FK_NO_SYSTEMD=1 "$VENV/bin/python" -I -c '
import json, os, sys
from filament_kit import config, modules
f = config.paths().etc / "config.json"
cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
mode = os.environ["FK_MODE"]
if mode == "custom":
    try:
        chosen, notes = modules.close_selection(os.environ["FK_MODULES"].split(","))
    except modules.ModuleError as e:
        names = ", ".join(modules.MODULES)
        sys.exit(f"error: {e}\nfix: use module names from: {names}")
    for note in notes:
        print(note)
    on = set(chosen)
    cfg["modules"] = modules.module_map(on, cfg)
    if {"station", "server"} <= on:
        # station and server on one machine: as all-in-one, the server reads the local station
        st = cfg.setdefault("station", {})
        st["allow"] = ["127.0.0.1"]
        st["url"] = "http://127.0.0.1:5003"
    for line in os.environ.get("FK_SETS", "").splitlines():
        if line.startswith("set ") and "=" in line:
            key, value = line[4:].split("=", 1)
            bad = modules.check_setting(key, value)
            if bad:
                sys.exit(f"error: {key}: {bad}")
            modules.set_setting(cfg, key, value)
    if "web" in on:
        cfg.setdefault("web", {}).setdefault("lan", list(config.DEFAULTS["web"]["lan"]))
else:
    cfg = modules.set_mode(cfg, mode)
    if os.environ.get("FK_AI"):
        cfg["modules"]["ai_intake"] = True  # the first install question
if os.environ["FK_SERVER"]:
    cfg.setdefault("station", {})["allow"] = [os.environ["FK_SERVER"]]
try:
    modules.validate(cfg)
except modules.ModuleError as e:
    sys.exit(f"error: {e}\nfix: choose again by running the install command again: curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh")
config.save(cfg)
print("Install mode: " + mode)
'
    chown root:filament-kit "$ETC/config.json"
    chmod 640 "$ETC/config.json"
fi

# ---------- 5. the modules ----------
# (with the station on, `modules apply` also installs Piper, the [station-tts] extra, and its voice)
exec /usr/local/bin/filament-kit modules apply
