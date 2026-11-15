#!/usr/bin/env bash
# Installed as /usr/local/bin/filament-kit.
# Settings and the certificate live in /etc/filament-kit (root-owned), so
# `config` and `cert` run as root; so does `modules`, which installs and starts
# services, `update`, which installs a new release, `uninstall`, which runs the kept release's
# uninstall.sh, `station` (the station PC: its pairing files in /etc/filament-kit-station), and `setup-code`,
# which shows or replaces the setup page's code in /etc/filament-kit, and `backup` and `restore`, which read and write
# everything the kit keeps.
# Everything else touches
# the service's state in /var/lib/filament-kit and runs as the filament-kit
# user, so the files it writes stay readable by the service.
set -euo pipefail

BIN=/opt/filament-kit/venv/bin/filament-kit
STATION_DIR=/etc/filament-kit-station
KIT_OPT=/opt/filament-kit

# install.sh removes this marker before it replaces the program and writes it once that is done, so no marker means
# an install stopped halfway, unless one is running now. This only says what to do: repairing is a root action, and
# reading `status` must not start one. The program may still work (`update --rollback` needs it), so it runs on if it can.
kit_installing() {
    systemctl is-active -q filament-kit-update.service filament-kit-setup-job@update.service \
        filament-kit-setup-job@rollback.service filament-kit-setup-job@apply.service 2>/dev/null && return 0
    pgrep -f '(^|/)install\.sh' >/dev/null 2>&1
}
if [ -d "$KIT_OPT" ] && [ ! -f "$KIT_OPT/.fk-installed" ] && ! kit_installing; then
    repair='curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh'
    earlier=$(sed -n 's/.*"previous": *"\([0-9][0-9.]*\)".*/\1/p' "$KIT_OPT/releases/state.json" 2>/dev/null) || earlier=""
    if [ -n "$earlier" ]; then
        repair="$repair --version $earlier"
    fi
    printf 'error: the last install or update stopped halfway. To repair it, run:\n  %s\n' "$repair" >&2
    if [ ! -x "$BIN" ]; then
        exit 1
    fi
fi

# The switches every command takes (`--plain`, `--no-progress`, `--json`, `--quiet`, `-q`, `--color <when>`) may stand
# before the command, as in `sudo filament-kit --plain backup create`: they are set aside here, so the route below is
# chosen on the command itself, and they go on to the program in front of it.
SWITCHES=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --plain | --no-progress | --json | --quiet | -q | --color=*) SWITCHES+=("$1"); shift ;;
        --color) SWITCHES+=("$1"); shift; if [ "$#" -gt 0 ]; then SWITCHES+=("$1"); shift; fi ;;
        *) break ;;
    esac
done
run_as_root() { exec "$BIN" ${SWITCHES[@]+"${SWITCHES[@]}"} "$@"; }
run_as_user() { exec runuser -u filament-kit -- "$BIN" ${SWITCHES[@]+"${SWITCHES[@]}"} "$@"; }

case "${1:-}" in
    config | cert | certificate | modules | features | remote | update | uninstall | station | weigh-station \
        | setup-code | logs)
        run_as_root "$@"
        ;;
esac
# `spoolman address` saves the Hub's settings and applies them; `spoolman fields` runs as the user below.
if [ "${1:-}" = spoolman ] && [ "${2:-}" = address ] && [ -n "${3:-}" ]; then
    run_as_root "$@"
fi
# `catalog token` writes the root-owned token file; `catalog status`, `update`, `rollback`, `add` and `adopt` run as the user.
if [ "${1:-}" = catalog ] && [ "${2:-}" = token ]; then
    run_as_root "$@"
fi
# `backup` and `restore` read and write everything the kit keeps, its root-owned files too.
case "${1:-}" in
    backup | restore) run_as_root "$@" ;;
esac
# `web passphrase` writes the root-owned passphrase file (and refuses unless root); `web status` reads as the user.
if [ "${1:-}" = web ] && [ "${2:-}" = passphrase ]; then
    run_as_root "$@"
fi
# `reader token` / `reader revoke` write the reader token file (handed to the service user) and refuse unless root;
# `reader setup` makes a token the same way and writes or flashes the reader's secrets.h for the caller;
# `reader tokens` only reads and runs as the user below.
if [ "${1:-}" = reader ] && { [ "${2:-}" = token ] || [ "${2:-}" = revoke ] || [ "${2:-}" = setup ]; }; then
    run_as_root "$@"
fi
# `local-intake install` / `remove` install or remove the local reader's service, `token` writes its root-owned token
# file and `plan` saves what an install needs in the root-owned store for the setup page; `status` and `test` only
# read and run as the user below.
if [ "${1:-}" = local-intake ] && { [ "${2:-}" = install ] || [ "${2:-}" = remove ] || [ "${2:-}" = token ] \
        || [ "${2:-}" = plan ] || [ "${2:-}" = share-corrections ]; }; then
    run_as_root "$@"
fi
# `label-reader corrections` (list, remove, retry, package, send) uses the reader's root-owned token; `status` and
# `test` read as the user below.
if [ "${1:-}" = label-reader ] && [ "${2:-}" = corrections ]; then
    run_as_root "$@"
fi

if [ "$(id -u)" -eq 0 ]; then
    # `catalog add <file>` (and the old `library add`): the service user may not be able to read a file in the
    # caller's home folder, so root opens it and the CLI reads it on stdin.
    if { [ "${1:-}" = catalog ] || [ "${1:-}" = library ]; } && [ "${2:-}" = add ] && [ -n "${3:-}" ] && [ "$3" != - ]; then
        if [ ! -f "$3" ] || [ ! -r "$3" ]; then
            printf 'Error: there is no readable file at %s.\nFix: give the path of one catalog entry as a JSON file.\n' "$3" >&2
            exit 2
        fi
        run_as_user "$1" add - < "$3"
    fi
    # `status`: the station's pairing folder is closed to the service user, so root looks and status gets the answer
    # (one line, never the token). With no folder there is no pairing to find, and status says so itself.
    if [ "${1:-}" = status ] && [ -d "$STATION_DIR" ]; then
        state="$("$BIN" station pairing-state 2>/dev/null)" || state=failed
        run_as_user "$@" "--station-pairing=$state"
    fi
    run_as_user "$@"
fi
run_as_root "$@"
