#!/usr/bin/env bash
# Build the release tarball dist/filament-kit-<version>.tar.gz.
# Works on Linux and on the Windows dev PC under Git Bash.
# Contents: install.sh, uninstall.sh, install/ (units, avahi, helper scripts),
# the filament_kit wheel, and app/filament-kit.apk + app/version.txt (signed Android release build).
# FK_DIST: the output folder (default dist, relative to the checkout). FK_NO_APP=1: no Android build and no
# app/ (the tarball test in server/tests; nothing under android/ is touched).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
dist=${FK_DIST:-dist}
mkdir -p "$dist"

version=$(sed -n 's/^__version__ = "\(.*\)"\r\{0,1\}$/\1/p' server/filament_kit/__init__.py)
[ -n "$version" ] || { echo "error: no __version__ in server/filament_kit/__init__.py" >&2; exit 1; }

name="filament-kit-$version"
stage_root="$dist/stage"
stage="$stage_root/$name"
rm -rf "$stage_root"
mkdir -p "$stage/install/systemd" "$stage/install/avahi" "$stage/install/remote" "$stage/install/panel"

# ---------- wheel ----------
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) windows=1 ;; *) windows=0 ;; esac
if command -v uv >/dev/null 2>&1; then
    uv build --wheel server --out-dir "$stage"
elif [ "$windows" = 1 ] && command -v uv.cmd >/dev/null 2>&1; then   # Git Bash; WSL sees uv.cmd but cannot run it
    uv.cmd build --wheel server --out-dir "$stage"
else
    python3 -m build --wheel --outdir "$stage" server
fi
rm -f "$stage/.gitignore"
rm -rf server/build
ls "$stage"/filament_kit-"$version"-*.whl >/dev/null 2>&1 \
    || { echo "error: wheel for $version not built" >&2; exit 1; }
# The wheel bundles no library entries (the library is downloaded on request); a wheel that still carries them
# would ship the old 4 MB snapshot. Not `grep -q`: it stops at the first match, unzip then dies of SIGPIPE and
# pipefail fails the check.
for whl in "$stage"/filament_kit-"$version"-*.whl; do
    if unzip -l "$whl" | grep -E ' filament_kit/library_data/library/' >/dev/null; then
        echo "error: $whl bundles library entries; they belong in the library-<date>.tar.gz asset" >&2
        exit 1
    fi
done

# ---------- scripts and units ----------
cp install/install.sh install/uninstall.sh "$stage/"
cp LICENSE THIRD-PARTY.md "$stage/"    # the GPL text and the third-party notices travel with every release
cp install/backup.sh install/filament-kit-cli.sh install/spoolman.sh "$stage/install/"
cp tools/export_ops.sh "$stage/install/"    # runs on a filament-ops VM (docs/migrate-from-filament-ops.md)
cp install/systemd/*.service install/systemd/*.timer install/systemd/*.path install/systemd/*.socket "$stage/install/systemd/"
cp install/avahi/filament-kit.service "$stage/install/avahi/"
cp install/remote/* "$stage/install/remote/"
cp station/panel/firmware/intake-panel.bin station/panel/firmware/VERSION "$stage/install/panel/"
# A Windows checkout may have CRLF line endings; Linux needs LF.
find "$stage" -type f \( -name '*.sh' -o -name '*.service' -o -name '*.timer' -o -name '*.path' -o -path '*/install/remote/*' \) \
    -exec sed -i 's/\r$//' {} +
chmod 755 "$stage/install.sh" "$stage/uninstall.sh" "$stage/install/backup.sh" \
    "$stage/install/filament-kit-cli.sh" "$stage/install/spoolman.sh" "$stage/install/export_ops.sh"

# ---------- Android app (optional) ----------
# versionCode: FK_VERSION_CODE (default 1) is passed to the Gradle build AND written to app/version.txt, so the
# update check on phones compares like with like. Bump it for every app release (see README).
FK_VERSION_CODE=${FK_VERSION_CODE:-1}
case "$FK_VERSION_CODE" in
    ""|*[!0-9]*|0*) echo "error: FK_VERSION_CODE must be a whole number above 0 (got '$FK_VERSION_CODE')" >&2; exit 1 ;;
esac
export FK_VERSION_CODE
# Signed release build runs when the keystore env is set (FK_KEYSTORE + FK_KEYSTORE_PASSWORD), or on the
# Windows dev PC when tools/android_keystore.ps1 has created the keystore; the password goes only into an
# env var of this process (never echoed, never on a command line).
if [ "${FK_NO_APP:-}" = 1 ]; then
    FK_KEYSTORE=""
fi
if [ -z "${FK_KEYSTORE:-}" ] && [ "${FK_NO_APP:-}" != 1 ] && command -v powershell >/dev/null 2>&1 \
        && command -v cygpath >/dev/null 2>&1; then
    # shellcheck disable=SC2016  # $env:LOCALAPPDATA is PowerShell's, expanded by PowerShell
    localapp=$(powershell -NoProfile -Command 'Write-Output $env:LOCALAPPDATA' | tr -d '\r')
    default_ks="$localapp\filament-kit\release.jks"
    if [ -f "$(cygpath -u "$default_ks")" ]; then
        FK_KEYSTORE=$(cygpath -m "$default_ks")
        FK_KEYSTORE_PASSWORD=$(powershell -NoProfile -ExecutionPolicy Bypass -File tools/android_keystore.ps1 -Print | tr -d '\r') \
            || { echo "error: could not read the keystore password" >&2; exit 1; }
        export FK_KEYSTORE FK_KEYSTORE_PASSWORD
    fi
fi
apk_dir="android/app/build/outputs/apk/release"
if [ -n "${FK_KEYSTORE:-}" ]; then
    [ -n "${FK_KEYSTORE_PASSWORD:-}" ] || { echo "error: FK_KEYSTORE set without FK_KEYSTORE_PASSWORD" >&2; exit 1; }
    if [ -z "${JAVA_HOME:-}" ] && [ -d /g/Android/jdk-21.0.13+9 ]; then
        export JAVA_HOME=/g/Android/jdk-21.0.13+9
    fi
    rm -f "$apk_dir"/*.apk
    (cd android && ./gradlew --no-daemon assembleRelease) \
        || { echo "error: assembleRelease failed; release NOT signed or packaged" >&2; exit 1; }
elif [ "${FK_NO_APP:-}" = 1 ]; then
    echo "FK_NO_APP=1: no Android build; the tarball has no app/"
else
    echo "FK_KEYSTORE not set; skipping the Android release build"
    # A stale APK from an earlier build must not be packaged with this release's version.txt.
    rm -f "$apk_dir"/*.apk
fi
apk=""
if [ "${FK_NO_APP:-}" != 1 ] && [ -f "$apk_dir/app-release.apk" ]; then
    apk="$apk_dir/app-release.apk"
fi
if [ -n "$apk" ]; then
    version_code=$FK_VERSION_CODE   # the value the APK above was just built with
    mkdir -p "$stage/app"
    cp "$apk" "$stage/app/filament-kit.apk"
    printf '%s\n' "$version_code" > "$stage/app/version.txt"
    echo "including app: $apk (versionCode $version_code)"
else
    echo "no signed Android release build found in $apk_dir; tarball has no app/"
fi

# ---------- tarball ----------
out="$dist/$name.tar.gz"
tar -czf "$out" --owner=0 --group=0 --numeric-owner \
    --mode='u+rwX,go+rX,go-w' -C "$stage_root" "$name"
rm -rf "$stage_root"

echo "built $out"
tar -tzf "$out"

# ---------- hardware data asset ----------
# The updater's hardware data feed (updates.hardware_feed) takes bambu_hardware.xml from the release, checked
# against the signed SHA256SUMS like the tarball; it is the same file the wheel bundles.
cp server/filament_kit/bridge/bambu_hardware.xml "$dist/bambu_hardware.xml"
echo "built $dist/bambu_hardware.xml"
# klipper_hardware.xml the same way (Klipper printers, updates.HW_ASSETS).
cp server/filament_kit/bridge/klipper/klipper_hardware.xml "$dist/klipper_hardware.xml"
echo "built $dist/klipper_hardware.xml"

# ---------- Klipper printer pack ----------
# fk-printer-pack.tar.gz unpacks to fk-printer-pack/ on a printer (`filament-kit klipper pack` prints the command);
# run with sh, so no file needs an exec bit.
tar -czf "$dist/fk-printer-pack.tar.gz" --owner=0 --group=0 --numeric-owner --mode='u+rwX,go+rX,go-w'     --exclude=tests --exclude=__pycache__ --transform='s,^printer-pack,fk-printer-pack,' printer-pack
echo "built $dist/fk-printer-pack.tar.gz"

# ---------- library asset (optional) ----------
# The filament-library data is a separate release asset, library-<date>.tar.gz, plus library.tar.gz under the
# fixed name the default `library.url` points at (releases/latest/download/library.tar.gz). Built from a
# filament-library checkout (FK_LIBRARY_SRC, default /c/CODING/filament-library) after the same validation the
# program applies on download; skipped when there is no checkout. Nothing is uploaded here.
lib_src=${FK_LIBRARY_SRC:-/c/CODING/filament-library}
if [ -f "$lib_src/index.json" ]; then
    py=python3
    command -v "$py" >/dev/null 2>&1 || py=python
    lib_out="$dist/library-$(date +%Y-%m-%d).tar.gz"
    "$py" -I tools/build_library_asset.py --from "$lib_src" --out "$lib_out" \
        || { echo "error: library asset not built" >&2; exit 1; }
    cp "$lib_out" "$dist/library.tar.gz"
    echo "built $lib_out and $dist/library.tar.gz"
else
    echo "no filament-library checkout at $lib_src; no library asset built"
fi
