#!/usr/bin/env bash
# Build the release tarball dist/filament-kit-<version>.tar.gz.
# Works on Linux and on the Windows dev PC under Git Bash.
# Contents: install.sh, uninstall.sh, install/ (units, avahi, helper scripts),
# the filament_kit wheel, and app/filament-kit.apk + app/version.txt (signed Android release build).
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
# The bundled library snapshot is package data; a wheel without it has no library at all.
for whl in "$stage"/filament_kit-"$version"-*.whl; do
    unzip -l "$whl" | grep -qE ' filament_kit/library_data/index\.json[[:space:]]*$' \
        || { echo "error: $whl has no filament_kit/library_data/index.json" >&2; exit 1; }
done

# ---------- scripts and units ----------
cp install/install.sh install/uninstall.sh "$stage/"
cp install/backup.sh install/filament-kit-cli.sh install/spoolman.sh "$stage/install/"
cp install/systemd/*.service install/systemd/*.timer install/systemd/*.path "$stage/install/systemd/"
cp install/avahi/filament-kit.service "$stage/install/avahi/"
# A Windows checkout may have CRLF line endings; Linux needs LF.
find "$stage" -type f \( -name '*.sh' -o -name '*.service' -o -name '*.timer' -o -name '*.path' \) \
    -exec sed -i 's/\r$//' {} +
chmod 755 "$stage/install.sh" "$stage/uninstall.sh" "$stage/install/backup.sh" \
    "$stage/install/filament-kit-cli.sh" "$stage/install/spoolman.sh"

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
if [ -z "${FK_KEYSTORE:-}" ] && command -v powershell >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1; then
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
else
    echo "FK_KEYSTORE not set; skipping the Android release build"
    # A stale APK from an earlier build must not be packaged with this release's version.txt.
    rm -f "$apk_dir"/*.apk
fi
apk=""
if [ -f "$apk_dir/app-release.apk" ]; then
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
out="dist/$name.tar.gz"
tar -czf "$out" --owner=0 --group=0 --numeric-owner \
    --mode='u+rwX,go+rX,go-w' -C "$stage_root" "$name"
rm -rf "$stage_root"

echo "built $out"
tar -tzf "$out"
