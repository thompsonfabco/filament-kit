#!/usr/bin/env bash
# Installs the filament-kit PC sync for this user, no root:
#   ~/.local/opt/filament-kit-sync/     the program (replaced as a whole on an update)
#   ~/.local/bin/filament-kit-sync      a symlink to it
#   filament-kit-sync.timer             a systemd user timer: `filament-kit-sync run --quiet` every 10 minutes
# The pairing token, config and log stay in ~/.local/share/filament-kit-sync ($XDG_DATA_HOME) across updates.
# Then: filament-kit-sync pair
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run this as your own user, not as root (the sync is per user)"
[ -d "${HOME:-}" ] || die "HOME is not set to your home folder"

here=$(cd "$(dirname "$0")" && pwd)
src="$here/filament-kit-sync"
[ -x "$src/filament-kit-sync" ] || die "no filament-kit-sync program next to this script (unpack the whole tarball)"

opt="$HOME/.local/opt/filament-kit-sync"
bin="$HOME/.local/bin"
mkdir -p "$HOME/.local/opt" "$bin"

# copy next to the old install, then swap, so a failed copy leaves the old one working
new=$(mktemp -d "$opt.new.XXXXXX")
trap 'rm -rf "$new"' ERR                 # a failed copy leaves no half-made $opt.new.* folder
cp -a "$src/." "$new/"
install -m 755 "$here/uninstall.sh" "$new/uninstall.sh"
chmod 755 "$new"
rm -rf "$opt.old"
# stop a sync run in progress before its program is swapped (a preset install it stops part-way is picked up
# again by the next run)
systemctl --user stop filament-kit-sync.service >/dev/null 2>&1 || true
if [ -e "$opt" ]; then
    mv "$opt" "$opt.old"
fi
mv "$new" "$opt"
trap - ERR
rm -rf "$opt.old"
ln -sfn "$opt/filament-kit-sync" "$bin/filament-kit-sync"
echo "Installed $("$opt/filament-kit-sync" --version) in $opt"

if ! "$opt/filament-kit-sync" install-timer; then
    echo "warning: the timer is not on yet; run 'filament-kit-sync install-timer' from your desktop session" >&2
fi

case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "Note: $bin is not on your PATH; log out and in again, or run $bin/filament-kit-sync" ;;
esac
echo "Next: filament-kit-sync pair   (paste the link from 'sudo filament-kit pair --pc' on the server)"
echo "To remove it: $opt/uninstall.sh   (add --purge to delete the token and settings too)"
