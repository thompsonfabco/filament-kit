#!/usr/bin/env bash
# End-to-end run of filament-kit on a disposable Ubuntu 24.04+ host, made for WSL Ubuntu (docs/testing-e2e.md):
#
#   wsl -d Ubuntu -- sudo bash /mnt/c/<checkout>/tools/e2e/run.sh [--only a,d,c,b,e,f,g] [--results FILE]
#                                                                 [--keep-work] [--previous vX.Y.Z]
#
# It builds two signed releases of this checkout with a throwaway ed25519 key, serves them from a fake GitHub
# releases API on 127.0.0.1 and runs the scenarios in tools/e2e/e2e.py against the real get.sh, install.sh,
# updater, Spoolman, kit server, web unit and a fake 16-unit Bambu printer (MQTT over TLS on 127.0.0.1:8883).
# --previous adds scenario f: that tag, built from its own files, updated to this checkout and rolled back to.
# Needs: root, internet (apt, PyPI, the Spoolman release on GitHub), python3 with python3-cryptography, a host
# with no filament-kit on it (it refuses otherwise) and ports 7912, 8101, 8710, 8883 free.
#
# Afterwards the host is put back as it was: the kit is uninstalled with --purge, the station's system changes
# are undone (sleep targets unmasked, ALSA state restored), packages the run installed are purged, and the work
# folder is removed. The state before and after (packages, unit files, users, the kit's paths) is compared; a
# difference fails the run. Exit 0 only when every scenario passed (or was skipped) and the host is clean.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=$(cd "$HERE/../.." && pwd)
ONLY=a,d,c,b,e
KEEP_WORK=0
RESULTS=""
PREVIOUS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --only) ONLY="$2"; shift 2 ;;
        --results) RESULTS="$2"; shift 2 ;;
        --keep-work) KEEP_WORK=1; shift ;;
        --previous) PREVIOUS=(--previous "$2"); shift 2 ;;
        *) echo "usage: sudo bash tools/e2e/run.sh [--only a,d,c,b,e,f,g] [--results FILE] [--keep-work] [--previous vX.Y.Z]" >&2; exit 2 ;;
    esac
done

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run as root: sudo bash $0"
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = ubuntu ] || die "Ubuntu only (found ${PRETTY_NAME:-unknown})"
command -v python3 >/dev/null || die "python3 is missing"
python3 -c 'import cryptography' 2>/dev/null || die "python3-cryptography is missing: sudo apt-get install python3-cryptography"
for p in /etc/filament-kit /opt/filament-kit /var/lib/filament-kit /var/lib/spoolman /opt/spoolman \
         /usr/local/bin/filament-kit; do
    [ ! -e "$p" ] || die "$p exists: this host already has filament-kit (data) on it; the e2e run needs a clean host"
done
for port in 7912 8101 8710 8883; do
    if ss -Hltn "sport = :$port" | grep -q .; then die "port $port is in use"; fi
done

# 0700: only root uses it (the run is root; the service user never reads it). It holds the throwaway release key.
WORK=$(mktemp -d /tmp/fk-e2e.XXXXXX)
chmod 700 "$WORK"
# The snapshots and the saved ALSA state live outside WORK (WORK may be kept or removed before the comparison).
KEEP=$(mktemp -d /tmp/fk-e2e-state.XXXXXX)
chmod 700 "$KEEP"
SLEEP_TARGETS="sleep.target suspend.target hibernate.target hybrid-sleep.target"
ALSA_STATE=/var/lib/alsa/asound.state

# What must be the same before and after. Not compared: apt's package lists (apt-get update), the journal.
snapshot() {
    {
        echo "## packages"
        dpkg-query -W -f '${Package} ${Version} ${Status}\n' | sort      # a changed version shows too
        echo "## unit files"
        systemctl list-unit-files --no-legend --no-pager | awk '{print $1, $2}' | sort
        echo "## /etc/systemd/system"
        find /etc/systemd/system -printf '%P %y %l\n' | sort
        echo "## kit units loaded"
        systemctl list-units --all --no-legend --no-pager 'filament-kit*' 'spoolman*' | awk '{print $1}'
        echo "## users and groups"
        sha256sum /etc/passwd /etc/group
        echo "## paths"
        for p in /etc/filament-kit /opt/filament-kit /var/lib/filament-kit /var/lib/spoolman /opt/spoolman \
                 /opt/spoolman.new /opt/spoolman.old /var/backups/filament-kit /usr/local/bin/filament-kit \
                 /etc/avahi/services/filament-kit.service /etc/udev/rules.d/99-zz-filament-kit-station.rules \
                 "$ALSA_STATE"; do
            if [ -e "$p" ]; then echo "$p present"; else echo "$p absent"; fi
        done
        [ ! -f "$ALSA_STATE" ] || sha256sum "$ALSA_STATE"
        echo "## root's home"
        ls -A /root /root/.cache 2>/dev/null || true
        ls -d /tmp/filament-kit-get.* 2>/dev/null || true
    } > "$1"
}

snapshot "$KEEP/before.txt"
dpkg-query -W -f '${Package}\n' | sort > "$KEEP/packages-before.txt"
MASKED_BEFORE=""
for t in $SLEEP_TARGETS; do
    [ "$(systemctl is-enabled "$t" 2>/dev/null || true)" != masked ] || MASKED_BEFORE="$MASKED_BEFORE $t"
done
[ ! -f "$ALSA_STATE" ] || cp -p "$ALSA_STATE" "$KEEP/asound.state"

cleanup() {
    local rc=$?
    set +e
    echo
    echo "==> cleaning up"
    pkill -f "http.server .*--directory $WORK/www" 2>/dev/null
    if [ -n "$RESULTS" ] && [ -f "$WORK/results.json" ]; then
        cp "$WORK/results.json" "$RESULTS" && echo "results: $RESULTS"
    fi
    if [ -x /opt/filament-kit/venv/bin/filament-kit ] || [ -e /etc/filament-kit ]; then
        # shellcheck disable=SC2012
        uninstall=$(ls "$WORK"/tree-*/install/uninstall.sh 2>/dev/null | head -n 1)
        [ -n "$uninstall" ] || uninstall="$SRC/install/uninstall.sh"
        printf 'purge\n' | bash "$uninstall" --purge > "$WORK/uninstall-final.log" 2>&1 \
            || echo "warning: uninstall.sh failed; see $WORK/uninstall-final.log"
    fi
    # the station's system changes, which uninstall.sh leaves as they are
    for t in $SLEEP_TARGETS; do
        case " $MASKED_BEFORE " in *" $t "*) ;; *) systemctl unmask "$t" >/dev/null 2>&1 ;; esac
    done
    if [ -f "$KEEP/asound.state" ]; then
        cp -p "$KEEP/asound.state" "$ALSA_STATE"
    else
        rm -f "$ALSA_STATE"
    fi
    # packages this run installed (install.sh and the modules' apt lines)
    dpkg-query -W -f '${Package}\n' | sort > "$WORK/packages-after.txt"
    new=$(comm -13 "$KEEP/packages-before.txt" "$WORK/packages-after.txt" | tr '\n' ' ')
    if [ -n "${new// /}" ]; then
        echo "purging packages the run installed: $new"
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 purge -y -q $new >/dev/null 2>&1 \
            || echo "warning: could not purge: $new"
    fi
    gone=$(comm -23 "$KEEP/packages-before.txt" "$WORK/packages-after.txt" | tr '\n' ' ')
    if [ -n "${gone// /}" ]; then
        echo "reinstalling packages the run removed: $gone"
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y -q $gone >/dev/null 2>&1 \
            || echo "warning: could not reinstall: $gone"
    fi
    systemctl daemon-reload
    systemctl reset-failed 'filament-kit*' 'spoolman*' >/dev/null 2>&1
    rm -rf /tmp/filament-kit-get.*
    snapshot "$KEEP/after.txt"
    if [ "$KEEP_WORK" -eq 1 ]; then
        echo "work folder kept: $WORK (holds the throwaway release key; delete it when done)"
    else
        rm -rf "$WORK"
    fi
    if diff -u "$KEEP/before.txt" "$KEEP/after.txt" > "$KEEP/host.diff"; then
        echo "host state: same as before the run"
    else
        echo "FAIL host state differs from before the run:"
        cat "$KEEP/host.diff"
        rc=1
    fi
    rm -rf "$KEEP"
    exit "$rc"
}
trap cleanup EXIT

echo "==> filament-kit end-to-end run in $WORK (source: $SRC)"
python3 -I "$HERE/e2e.py" --work "$WORK" --only "$ONLY" "${PREVIOUS[@]}"
