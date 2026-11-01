#!/usr/bin/env bash
# Build the release tarball dist/filament-kit-<version>.tar.gz.
# Works on Linux and on the Windows dev PC under Git Bash.
# Contents: install.sh, uninstall.sh, install/ (units, avahi, helper scripts),
# the filament_kit wheel, and app/filament-kit.apk (+ app/version.txt) when an
# Android release build is present.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

version=$(sed -n 's/^__version__ = "\(.*\)"\r\{0,1\}$/\1/p' server/filament_kit/__init__.py)
[ -n "$version" ] || { echo "error: no __version__ in server/filament_kit/__init__.py" >&2; exit 1; }

name="filament-kit-$version"
stage_root="dist/stage"
stage="$stage_root/$name"
rm -rf "$stage_root"
mkdir -p "$stage/install/systemd" "$stage/install/avahi"

# ---------- wheel ----------
if command -v uv >/dev/null 2>&1; then
    uv build --wheel server --out-dir "$stage"
elif command -v uv.cmd >/dev/null 2>&1; then
    uv.cmd build --wheel server --out-dir "$stage"
else
    python3 -m build --wheel --outdir "$stage" server
fi
rm -f "$stage/.gitignore"
rm -rf server/build
ls "$stage"/filament_kit-"$version"-*.whl >/dev/null 2>&1 \
    || { echo "error: wheel for $version not built" >&2; exit 1; }

# ---------- scripts and units ----------
cp install/install.sh install/uninstall.sh "$stage/"
cp install/backup.sh install/filament-kit-cli.sh "$stage/install/"
cp install/systemd/*.service install/systemd/*.timer "$stage/install/systemd/"
cp install/avahi/filament-kit.service "$stage/install/avahi/"
# A Windows checkout may have CRLF line endings; Linux needs LF.
find "$stage" -type f \( -name '*.sh' -o -name '*.service' -o -name '*.timer' \) \
    -exec sed -i 's/\r$//' {} +
chmod 755 "$stage/install.sh" "$stage/uninstall.sh" "$stage/install/backup.sh" \
    "$stage/install/filament-kit-cli.sh"

# ---------- Android app (optional) ----------
apk_dir="android/app/build/outputs/apk/release"
apk=""
for candidate in "$apk_dir/filament-kit.apk" "$apk_dir/app-release.apk"; do
    if [ -f "$candidate" ]; then
        apk="$candidate"
        break
    fi
done
if [ -n "$apk" ]; then
    mkdir -p "$stage/app"
    cp "$apk" "$stage/app/filament-kit.apk"
    if [ -f "$apk_dir/version.txt" ]; then
        cp "$apk_dir/version.txt" "$stage/app/version.txt"
    fi
    echo "including app: $apk"
else
    echo "no Android release build found in $apk_dir; tarball has no app/"
fi

# ---------- tarball ----------
out="dist/$name.tar.gz"
tar -czf "$out" --owner=0 --group=0 --numeric-owner \
    --mode='u+rwX,go+rX,go-w' -C "$stage_root" "$name"
rm -rf "$stage_root"

echo "built $out"
tar -tzf "$out"
