#!/bin/sh
# filament-kit printer pack. RUN_SHELL_COMMAND CMD=fk_load_temp PARAMS=<spool id>: start the lookup detached and return
# at once, because Klipper blocks while a shell command runs and the script posts gcode back to it.
case "$1" in ''|*[!0-9]*) exit 0 ;; esac
setsid python3 "$(dirname "$0")/fk_load_temp.py" "$1" >/dev/null 2>&1 < /dev/null &
exit 0
