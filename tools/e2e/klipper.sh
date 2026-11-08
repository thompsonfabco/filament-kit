#!/usr/bin/env bash
# End-to-end test of filament-kit's Klipper support on a scratch Klipper + Moonraker (WSL Ubuntu or any Linux box
# with sudo). No printer hardware: Klipper runs with its Linux-process MCU and `kinematics: none`, Spoolman is the
# server tests' fake Spoolman. Steps (spec §9):
#   1. build/run Klipper (pinned tag) + Moonraker (pinned tag) under $WORK
#   2. printer pack: install (spool + moonraker parts, all answers yes), status, then later uninstall
#   3. the kit's Klipper bridge (tools/e2e/klipper_e2e.py, in-process): detection, a load (SET_ACTIVE_SPOOL ->
#      confirmed -> Spoolman location), a tap (SET_ACTIVE_SPOOL sent to Moonraker -> follow mode), a short
#      virtual-sdcard print -> a usage entry; then the M1D-like toolchanger variant -> FK_SET_TOOL_SPOOL on real
#      Klipper -> lane_data in Moonraker's database
# Last line on success: "klipper e2e: all checks passed". Usage: bash tools/e2e/klipper.sh  (from the repo root)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${FK_E2E_WORK:-$HOME/fk-klipper-e2e}
KLIPPER_REF=${KLIPPER_REF:-v0.13.0}
MOONRAKER_REF=${MOONRAKER_REF:-v0.9.3}
DATA=$WORK/printer_data
# Klipper's and Moonraker's pinned requirements need Python <= 3.12; uv's managed 3.12 is used when present
PY=${PYTHON:-$(ls -d "$HOME"/.local/share/uv/python/cpython-3.12*/bin/python3.12 2>/dev/null | tail -1)}
PY=${PY:-python3}
log() { printf '\n== %s\n' "$*"; }

log "packages"
if ! dpkg -s build-essential python3-venv python3-dev libffi-dev liblmdb-dev libsodium-dev zlib1g-dev \
        libjpeg-dev git curl >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential python3-venv python3-dev libffi-dev \
        liblmdb-dev libsodium-dev zlib1g-dev libjpeg-dev git curl >/dev/null
fi
mkdir -p "$WORK" "$DATA"/{config,logs,gcodes,comms,database}

log "Klipper $KLIPPER_REF"
[ -d "$WORK/klipper" ] || git clone -q https://github.com/Klipper3d/klipper.git "$WORK/klipper"
git -C "$WORK/klipper" fetch -q --tags && git -C "$WORK/klipper" checkout -q "$KLIPPER_REF"
venv() {   # $1 = env dir, then pip install arguments; redone until one install succeeds
    local env=$1; shift
    [ -f "$env/.fk-ok" ] && return 0
    rm -rf "$env"
    "$PY" -m venv "$env"
    "$env/bin/pip" install -q "$@"
    touch "$env/.fk-ok"
}
venv "$WORK/klippy-env" -r "$WORK/klipper/scripts/klippy-requirements.txt"
if [ ! -x "$WORK/klipper/out/klipper.elf" ]; then
    printf 'CONFIG_LOW_LEVEL_OPTIONS=y\nCONFIG_MACH_LINUX=y\n' > "$WORK/klipper/.config"
    make -C "$WORK/klipper" olddefconfig >/dev/null && make -C "$WORK/klipper" -j"$(nproc)" >/dev/null
fi

log "Moonraker $MOONRAKER_REF"
[ -d "$WORK/moonraker" ] || git clone -q https://github.com/Arksine/moonraker.git "$WORK/moonraker"
git -C "$WORK/moonraker" fetch -q --tags && git -C "$WORK/moonraker" checkout -q "$MOONRAKER_REF"
venv "$WORK/moonraker-env" -r "$WORK/moonraker/scripts/moonraker-requirements.txt"

log "kit test environment"
venv "$WORK/kit-env" -e "$REPO/server[test]"

PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT

write_config() {   # $1 = single | toolchanger
    cat > "$DATA/config/printer.cfg" <<EOF
[mcu]
serial: /tmp/klipper_host_mcu

[printer]
kinematics: none
max_velocity: 1
max_accel: 1

[virtual_sdcard]
path: $DATA/gcodes

[display_status]
[pause_resume]
[save_variables]
filename: $DATA/config/variables.cfg

[gcode_macro CANCEL_PRINT]
rename_existing: CANCEL_PRINT_BASE
gcode:
  CANCEL_PRINT_BASE
EOF
    if [ "$1" = toolchanger ]; then
        printf '\n[gcode_macro FK_UNVERIFIED_M1D]\ngcode:\n  M117 m1d-like test printer\n' >> "$DATA/config/printer.cfg"
    fi
    cat > "$DATA/config/moonraker.conf" <<EOF
[server]
host: 127.0.0.1
port: 7125
klippy_uds_address: $DATA/comms/klippy.sock

[authorization]
trusted_clients:
  127.0.0.0/8

[history]

[file_manager]
enable_object_processing: False
EOF
    : > "$DATA/config/variables.cfg"
}

start_stack() {
    "$WORK/klipper/out/klipper.elf" >"$DATA/logs/mcu.log" 2>&1 & PIDS+=($!)
    sleep 1
    "$WORK/klippy-env/bin/python" "$WORK/klipper/klippy/klippy.py" "$DATA/config/printer.cfg" \
        -a "$DATA/comms/klippy.sock" -l "$DATA/logs/klippy.log" >/dev/null 2>&1 & PIDS+=($!)
    "$WORK/moonraker-env/bin/python" "$WORK/moonraker/moonraker/moonraker.py" -d "$DATA" \
        >"$DATA/logs/moonraker.out" 2>&1 & PIDS+=($!)
    MOON_PID=$!
    for _ in $(seq 60); do
        if curl -fs localhost:7125/printer/info 2>/dev/null | grep -q '"state": *"ready"'; then return 0; fi
        sleep 1
    done
    echo "Klipper/Moonraker did not become ready; logs in $DATA/logs" >&2
    tail -30 "$DATA/logs/klippy.log" >&2 || true
    return 1
}

stop_stack() { cleanup; PIDS=(); sleep 1; }

log "fake Spoolman on :7912"
SPOOLMAN_PY=$(cat <<'EOF'
import sys, uvicorn
sys.path.insert(0, sys.argv[1])
from fakes import spoolman_fake
uvicorn.run(spoolman_fake.app(spoolman_fake.new_store()), host="127.0.0.1", port=7912, log_level="warning")
EOF
)
"$WORK/kit-env/bin/python" -c "$SPOOLMAN_PY" "$REPO/server/tests" & PIDS+=($!)

for variant in single toolchanger; do
    log "variant $variant: Klipper + Moonraker"
    rm -rf "$DATA/config/filament-kit"   # a run that stopped early leaves the pack behind
    rm -rf "$DATA/database" && mkdir -p "$DATA/database"   # each variant starts with an empty Moonraker database
    write_config "$variant"
    start_stack
    log "variant $variant: printer pack install"
    sh "$REPO/printer-pack/fk-printer-pack.sh" install --data "$DATA" --parts spool,moonraker \
        --spoolman http://127.0.0.1:7912 --yes
    for _ in $(seq 60); do
        curl -fs localhost:7125/printer/info 2>/dev/null | grep -q '"state": *"ready"' && break; sleep 1
    done
    # Moonraker reads [spoolman] at start: restart it so the pack's moonraker.conf edit takes effect
    kill "$MOON_PID"; wait "$MOON_PID" 2>/dev/null || true
    "$WORK/moonraker-env/bin/python" "$WORK/moonraker/moonraker/moonraker.py" -d "$DATA" \
        >>"$DATA/logs/moonraker.out" 2>&1 & PIDS+=($!)
    MOON_PID=$!
    for _ in $(seq 60); do
        curl -fs localhost:7125/printer/info 2>/dev/null | grep -q '"state": *"ready"' && break; sleep 1
    done
    for _ in $(seq 60); do   # the pack restarted Klipper: wait until its macros are loaded
        curl -fs localhost:7125/printer/objects/list 2>/dev/null | grep -q "FK_SET_TOOL_SPOOL" && break; sleep 1
    done
    sh "$REPO/printer-pack/fk-printer-pack.sh" status --data "$DATA" | tee "$WORK/status-$variant.txt"
    grep -q "FK_SET_TOOL_SPOOL: present" "$WORK/status-$variant.txt"
    log "variant $variant: the kit's bridge"
    rm -rf "$WORK/state-$variant" "$WORK/etc-$variant"; mkdir -p "$WORK/state-$variant" "$WORK/etc-$variant"
    FK_STATE=$WORK/state-$variant FK_ETC=$WORK/etc-$variant "$WORK/kit-env/bin/python" \
        "$REPO/tools/e2e/klipper_e2e.py" "$variant" "$DATA"
    log "variant $variant: printer pack uninstall"
    sh "$REPO/printer-pack/fk-printer-pack.sh" uninstall --data "$DATA" --yes
    ! grep -q "include filament-kit" "$DATA/config/printer.cfg"
    stop_stack
    "$WORK/kit-env/bin/python" -c "$SPOOLMAN_PY" "$REPO/server/tests" & PIDS+=($!)
done
echo "klipper e2e: all checks passed"
