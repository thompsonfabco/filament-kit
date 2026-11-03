#!/usr/bin/env bash
# Removes the filament-kit PC sync of this user: the timer, the program and its symlink.
# The pairing token, config, log and backups in ~/.local/share/filament-kit-sync stay, so a reinstall is still
# paired; --purge deletes them too (then also run 'sudo filament-kit unpair <id>' on the server).
# The slicers' own folders and the presets installed there are never touched.
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }
usage() { echo "usage: $0 [--purge]" >&2; exit 2; }

PURGE=0
case "${1:-}" in
    "") ;;
    --purge) PURGE=1 ;;
    *) usage ;;
esac
[ $# -le 1 ] || usage
[ "$(id -u)" -ne 0 ] || die "run this as your own user, not as root"
[ -d "${HOME:-}" ] || die "HOME is not set to your home folder"

opt="$HOME/.local/opt/filament-kit-sync"
link="$HOME/.local/bin/filament-kit-sync"
data="${XDG_DATA_HOME:-$HOME/.local/share}/filament-kit-sync"     # where pair wrote the token (this shell's XDG)

# the timer first, in shell, so this works even when the program is already gone
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now filament-kit-sync.timer >/dev/null 2>&1 || true
    systemctl --user stop filament-kit-sync.service >/dev/null 2>&1 || true
fi
# the user manager may not see this shell's XDG_* values: look in both its places and the default ones
for units in "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user" "$HOME/.config/systemd/user"; do
    rm -f "$units/filament-kit-sync.timer" "$units/filament-kit-sync.service"
done
for state in "${XDG_DATA_HOME:-$HOME/.local/share}" "$HOME/.local/share"; do
    rm -f "$state/systemd/timers/stamp-filament-kit-sync.timer"  # Persistent=true keeps the last run time there
done
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

if [ -L "$link" ]; then
    case "$(readlink "$link")" in
        "$opt"/*) rm -f "$link" ;;
    esac
fi
rm -rf "$opt" "$opt.old" "$opt".new.*                          # .new.*: a copy an install left behind
echo "Removed the filament-kit PC sync (timer, $opt, $link)."

if [ "$PURGE" -eq 1 ]; then
    rm -rf "$data"
    echo "Deleted $data (token, settings, log, backups)."
    echo "On the server, run 'sudo filament-kit unpair <id>' so another PC can become the sync PC."
else
    echo "Kept $data (the pairing token and settings); run with --purge to delete it."
fi
