#!/usr/bin/env bash
# End-to-end test of filament-kit's Klipper support on a scratch Klipper + Moonraker (WSL Ubuntu or any Linux box
# with sudo). No printer hardware: Klipper runs with its Linux-process MCU and `kinematics: none`, Spoolman is the
# server tests' fake Spoolman. Steps (spec §9):
#   1. build/run Klipper (pinned tag) + Moonraker (pinned tag) under $WORK
#   2. printer pack: install (spool + check + moonraker parts, all answers yes, so it restarts Klipper and Moonraker
#      itself) twice (a reinstall), status, then later uninstall (twice). The spool check needs gcode_shell_command: tools/e2e/gcode_shell_command.py, a test
#      stand-in that parses PARAMS like the real extra, is copied into the scratch Klipper's klippy/extras
#   3. the kit's Klipper bridge (tools/e2e/klipper_e2e.py, in-process): detection, a load (SET_ACTIVE_SPOOL ->
#      confirmed -> Spoolman location), a tap (SET_ACTIVE_SPOOL sent to Moonraker -> follow mode), a short
#      virtual-sdcard print -> a usage entry; the spool check with a quote in the vendor (Klipper stays up) and in
#      cancel mode during a print (cancelled; the Spoolman names never reach gcode); then the M1D-like toolchanger
#      variant -> FK_SET_TOOL_SPOOL on real
#      Klipper -> lane_data in Moonraker's database
# Last line on success: "klipper e2e: all checks passed". Usage: bash tools/e2e/klipper.sh  (from the repo root)
#
# Two runs on one machine don't meet: each has its own run folder under $WORK (kept only when the run fails), its own
# MCU path and its own ports. FK_E2E_MOONRAKER_PORT and FK_E2E_SPOOLMAN_PORT choose the ports; by default each run
# takes free ones. $WORK holds what they share (Klipper, Moonraker, the venvs), set up under a lock. The kit's code
# always comes from this tree, whatever kit-env was first installed from.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${FK_E2E_WORK:-$HOME/fk-klipper-e2e}
KLIPPER_REF=${KLIPPER_REF:-v0.13.0}
MOONRAKER_REF=${MOONRAKER_REF:-v0.9.3}
# Klipper's and Moonraker's pinned requirements need Python <= 3.12; uv's managed 3.12 is used when present
# shellcheck disable=SC2012  # a glob of uv's own version folders
PY=${PYTHON:-$(ls -d "$HOME"/.local/share/uv/python/cpython-3.12*/bin/python3.12 2>/dev/null | tail -1)}
PY=${PY:-python3}
log() { printf '\n== %s\n' "$*"; }
checkout_ref() {   # $1 = clone dir, $2 = ref. A failed fetch is only tolerated (offline) when the ref is already here.
    git -C "$1" fetch -q --tags || echo "warning: git fetch failed in $1; using what is there" >&2
    git -C "$1" checkout -q "$2"
    [ "$(git -C "$1" rev-parse HEAD)" = "$(git -C "$1" rev-parse "$2^{commit}")" ] \
        || { echo "error: $1 is not at $2 after the checkout" >&2; exit 1; }
}

log "packages"
if ! dpkg -s build-essential python3-venv python3-dev libffi-dev liblmdb-dev libsodium-dev zlib1g-dev \
        libjpeg-dev git curl >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential python3-venv python3-dev libffi-dev \
        liblmdb-dev libsodium-dev zlib1g-dev libjpeg-dev git curl >/dev/null
fi
mkdir -p "$WORK"
RUN=$(mktemp -d "$WORK/run.XXXXXX")
DATA=$RUN/printer_data
mkdir -p "$DATA"/{config,logs,gcodes,comms,database}
# both at once, so the two can't be the same port; a run that loses one in the moment before it binds fails below
read -r FREE_A FREE_B < <("$PY" -c '
import socket
a, b = socket.socket(), socket.socket()
a.bind(("127.0.0.1", 0)); b.bind(("127.0.0.1", 0))
print(a.getsockname()[1], b.getsockname()[1])')
MR_PORT=${FK_E2E_MOONRAKER_PORT:-$FREE_A}
SM_PORT=${FK_E2E_SPOOLMAN_PORT:-$FREE_B}
MR=http://127.0.0.1:$MR_PORT
SM=http://127.0.0.1:$SM_PORT
log "run folder $RUN, Moonraker on :$MR_PORT, fake Spoolman on :$SM_PORT"

exec 9>"$WORK/.setup.lock"   # a second run waits here: git and the venvs below aren't safe to run side by side
flock 9
log "Klipper $KLIPPER_REF"
[ -d "$WORK/klipper" ] || git clone -q https://github.com/Klipper3d/klipper.git "$WORK/klipper"
checkout_ref "$WORK/klipper" "$KLIPPER_REF"
cp "$REPO/tools/e2e/gcode_shell_command.py" "$WORK/klipper/klippy/extras/gcode_shell_command.py"
venv() {   # $1 = env dir, $2 = what the env is made from (ref and requirements hash), then pip install arguments;
           # redone until one install succeeds, and again when $2 changes
    local env=$1 key=$2; shift 2
    [ "$(cat "$env/.fk-ok" 2>/dev/null)" = "$key" ] && return 0
    rm -rf "$env"
    "$PY" -m venv "$env"
    "$env/bin/pip" install -q "$@"
    printf '%s\n' "$key" > "$env/.fk-ok"
}
reqkey() { printf '%s %s' "$1" "$(cat "${@:2}" | sha256sum | cut -d' ' -f1)"; }   # $1 = ref, then the requirements files
venv "$WORK/klippy-env" "$(reqkey "$KLIPPER_REF" "$WORK/klipper/scripts/klippy-requirements.txt")" \
    -r "$WORK/klipper/scripts/klippy-requirements.txt"
if [ ! -x "$WORK/klipper/out/klipper.elf" ] || [ "$(cat "$WORK/klipper/out/.fk-ref" 2>/dev/null)" != "$KLIPPER_REF" ]; then
    printf 'CONFIG_LOW_LEVEL_OPTIONS=y\nCONFIG_MACH_LINUX=y\n' > "$WORK/klipper/.config"
    make -C "$WORK/klipper" clean >/dev/null
    make -C "$WORK/klipper" olddefconfig >/dev/null && make -C "$WORK/klipper" -j"$(nproc)" >/dev/null
    printf '%s\n' "$KLIPPER_REF" > "$WORK/klipper/out/.fk-ref"
fi

log "Moonraker $MOONRAKER_REF"
[ -d "$WORK/moonraker" ] || git clone -q https://github.com/Arksine/moonraker.git "$WORK/moonraker"
checkout_ref "$WORK/moonraker" "$MOONRAKER_REF"
venv "$WORK/moonraker-env" "$(reqkey "$MOONRAKER_REF" "$WORK/moonraker/scripts/moonraker-requirements.txt")" \
    -r "$WORK/moonraker/scripts/moonraker-requirements.txt"

log "kit test environment"
venv "$WORK/kit-env" "$(reqkey kit "$REPO/server/pyproject.toml")" -e "$REPO/server[test]"
exec 9>&-                    # setup is done; the processes started below must not hold the lock
# kit-env's editable install points at whichever tree created it: PYTHONPATH makes it this one, and this checks it did
PYTHONPATH=$REPO/server "$WORK/kit-env/bin/python" -c '
import os, sys, filament_kit
where = os.path.realpath(filament_kit.__file__)
sys.exit(f"FAILED: the kit code comes from {where}, not this tree" if not where.startswith(os.path.realpath(sys.argv[1]) + os.sep) else 0)
' "$REPO/server"

PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
on_exit() {
    local rc=$?
    cleanup
    if [ "$rc" -eq 0 ]; then rm -rf "$RUN"; else echo "klipper e2e failed; logs kept in $RUN" >&2; fi
}
trap on_exit EXIT
pack() { sh "$REPO/printer-pack/fk-printer-pack.sh" "$1" --data "$DATA" --moonraker "$MR" "${@:2}"; }

write_config() {   # $1 = single | toolchanger
    cat > "$DATA/config/printer.cfg" <<EOF
[mcu]
serial: $RUN/mcu

[printer]
kinematics: none
max_velocity: 1
max_accel: 1

[virtual_sdcard]
path: $DATA/gcodes

[display_status]
[pause_resume]
[respond]
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
port: $MR_PORT
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

wait_ready() {   # Moonraker dying (a lost port, say) ends the wait at once
    for _ in $(seq 60); do
        if ! kill -0 "$MOON_PID" 2>/dev/null; then
            echo "Moonraker exited; logs in $DATA/logs" >&2; tail -5 "$DATA/logs/moonraker.out" >&2 || true; return 1
        fi
        if curl -fs "$MR/printer/info" 2>/dev/null | grep -q '"state": *"ready"'; then return 0; fi
        sleep 1
    done
    echo "Klipper/Moonraker did not become ready; logs in $DATA/logs" >&2
    tail -30 "$DATA/logs/klippy.log" >&2 || true
    return 1
}

start_stack() {
    "$WORK/klipper/out/klipper.elf" -I "$RUN/mcu" >"$DATA/logs/mcu.log" 2>&1 & PIDS+=($!)
    sleep 1
    "$WORK/klippy-env/bin/python" "$WORK/klipper/klippy/klippy.py" "$DATA/config/printer.cfg" \
        -a "$DATA/comms/klippy.sock" -l "$DATA/logs/klippy.log" >/dev/null 2>&1 & PIDS+=($!)
    "$WORK/moonraker-env/bin/python" "$WORK/moonraker/moonraker/moonraker.py" -d "$DATA" \
        >"$DATA/logs/moonraker.out" 2>&1 & PIDS+=($!)
    MOON_PID=$!
    wait_ready
}

stop_stack() { cleanup; PIDS=(); sleep 1; }

log "fake Spoolman on :$SM_PORT"
SPOOLMAN_PY=$(cat <<'EOF'
import sys, uvicorn
sys.path.insert(0, sys.argv[1])
from fakes import spoolman_fake
uvicorn.run(spoolman_fake.app(spoolman_fake.new_store()), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
EOF
)
start_spoolman() {   # it must be ours that answers: one that lost the port has exited by the time something does
    PYTHONPATH=$REPO/server "$WORK/kit-env/bin/python" -c "$SPOOLMAN_PY" "$REPO/server/tests" "$SM_PORT" & PIDS+=($!)
    local pid=$!
    for _ in $(seq 60); do
        if ! kill -0 "$pid" 2>/dev/null; then echo "the fake Spoolman exited (port $SM_PORT taken?)" >&2; return 1; fi
        if curl -s -o /dev/null "$SM/" 2>/dev/null; then sleep 0.5; kill -0 "$pid" 2>/dev/null && return 0; fi
        sleep 0.5
    done
    echo "the fake Spoolman did not answer on $SM_PORT" >&2
    return 1
}
start_spoolman

for variant in single toolchanger; do
    log "variant $variant: Klipper + Moonraker"
    rm -rf "$DATA/config/filament-kit"   # a run that stopped early leaves the pack behind
    rm -rf "$DATA/database" && mkdir -p "$DATA/database"   # each variant starts with an empty Moonraker database
    write_config "$variant"
    start_stack
    log "variant $variant: printer pack install (twice: a reinstall)"
    for _ in 1 2; do
        wait_ready   # the first install restarts Klipper: the second waits until it is back
        pack install --klipper "$WORK/klipper" --parts spool,check,moonraker --spoolman "$SM" --yes
        # Moonraker reads [spoolman] only at start: seeing it here proves the pack's own restart happened
        for _ in $(seq 60); do
            curl -fs "$MR/server/config" 2>/dev/null | grep -qF "\"$SM\"" && break; sleep 1
        done
        curl -fs "$MR/server/config" | grep -qF "\"$SM\"" || {
            echo "FAILED: Moonraker did not take up [spoolman] after the pack's restart" >&2; exit 1; }
    done
    wait_ready
    for _ in $(seq 60); do   # the pack restarted Klipper: wait until its macros are loaded
        curl -fs "$MR/printer/objects/list" 2>/dev/null | grep -q "FK_SET_TOOL_SPOOL" && break; sleep 1
    done
    pack status | tee "$RUN/status-$variant.txt"
    grep -q "FK_SET_TOOL_SPOOL: present" "$RUN/status-$variant.txt"
    grep -q "FK_SPOOL_CHECK: present" "$RUN/status-$variant.txt"
    "$PY" -c 'import json, sys; f = json.load(open(sys.argv[1]))["files"]; sys.exit(len(f) != len(set(f)))' \
        "$DATA/config/filament-kit/.manifest"
    log "variant $variant: the kit's bridge"
    mkdir -p "$RUN/state-$variant" "$RUN/etc-$variant"
    FK_STATE=$RUN/state-$variant FK_ETC=$RUN/etc-$variant FK_E2E_MOONRAKER_PORT=$MR_PORT FK_E2E_SPOOLMAN_PORT=$SM_PORT \
        PYTHONPATH=$REPO/server "$WORK/kit-env/bin/python" "$REPO/tools/e2e/klipper_e2e.py" "$variant" "$DATA"
        "$WORK/klippy-env/bin/python" "$REPO/tools/e2e/render_tag_macro.py" "$DATA/config/filament-kit/fk_spool.cfg"
    log "variant $variant: printer pack uninstall"
    pack uninstall --yes
    if grep -q "include filament-kit" "$DATA/config/printer.cfg"; then
        echo "FAILED: the include line is still in printer.cfg after uninstall" >&2; exit 1
    fi
    if [ -e "$DATA/config/filament-kit" ]; then
        echo "FAILED: config/filament-kit is still there after uninstall" >&2; exit 1
    fi
    pack uninstall --yes   # again: nothing left, no error
    stop_stack
    start_spoolman
done
echo "klipper e2e: all checks passed"
