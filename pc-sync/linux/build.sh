#!/usr/bin/env bash
# Builds the Linux PC sync package: dist/filament-kit-sync-linux-x86_64-<version>.tar.gz, holding
#   filament-kit-sync-linux-x86_64-<version>/
#     filament-kit-sync/   the PyInstaller onedir build (pc-sync/fksync.spec)
#     install.sh           installs it for this user (no root)
#     uninstall.sh         removes it again (the token stays unless --purge)
# Run from the repository root on Linux x86_64, with pyinstaller==6.11.1 installed next to the pc-sync package.
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || die "build the Linux package on Linux"
[ "$(uname -m)" = x86_64 ] || die "this package is for x86_64 (this machine is $(uname -m))"
[ -f pc-sync/fksync.spec ] || die "run from the repository root"

version=$(sed -n 's/^__version__ = "\(.*\)"\r\{0,1\}$/\1/p' pc-sync/fksync/__init__.py)
[ -n "$version" ] || die "no __version__ in pc-sync/fksync/__init__.py"
name="filament-kit-sync-linux-x86_64-$version"

pyinstaller --noconfirm pc-sync/fksync.spec
out=$(./dist/filament-kit-sync/filament-kit-sync --version)
[ "$out" = "filament-kit-sync $version" ] || die "the build reports '$out', expected filament-kit-sync $version"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/$name"
cp -a dist/filament-kit-sync "$stage/$name/filament-kit-sync"
install -m 755 pc-sync/linux/install.sh pc-sync/linux/uninstall.sh "$stage/$name/"
tar -C "$stage" --owner=0 --group=0 --numeric-owner -czf "dist/$name.tar.gz" "$name"
echo "dist/$name.tar.gz"
