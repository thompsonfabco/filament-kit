# Maintainer notes

The release chores of whoever maintains filament-kit. Users don't need this page. The tools named here are in
`tools/`; the release workflow is `.github/workflows/release.yml`.

## What a release is

A tag `v<x.y.z>` pushed to GitHub builds and publishes one release, with:

- `filament-kit-<version>.tar.gz`: the server (the Python wheel, `install.sh`, `uninstall.sh`, the units) with
  the signed Android app inside (`app/filament-kit.apk`, `app/version.txt`);
- `filament-kit.apk` on its own, and `filament-kit-sync-setup-<version>.exe` (the Windows PC sync);
- `get.sh` (the one-command installer) and `bambu_hardware.xml` (the printer data feed the updater reads);
- `library.tar.gz` when the library token is set (see below);
- `SHA256SUMS` listing all of them, and `SHA256SUMS.sig`, its ed25519 signature.

`get.sh` and `filament-kit update` refuse anything whose hash is not in a correctly signed `SHA256SUMS`.

## Cutting a release

1. Set the same version in `server/filament_kit/__init__.py` and `pc-sync/fksync/__init__.py` (`__version__`).
   The workflow refuses a tag that differs from either. Versions are `MAJOR.MINOR.PATCH` with MINOR and PATCH
   below 100; pre-release tags such as `v0.3.0-rc1` are refused on purpose.
2. If you edited `server/filament_kit/release.py`, run `python tools/sign_release.py sync-get`: `get.sh` carries
   a copy of that file, and the workflow fails when they differ.
3. Commit, then tag and push: `git tag v0.3.0 && git push origin main v0.3.0`.
4. Watch the `release` workflow. It needs the three secrets below; without them it fails rather than publish
   an unsigned release.
5. Edit the release notes on GitHub if you like. Installs with the `updates` module pick the release up within a
   day; `sudo filament-kit update` does it now.

The Android app's `versionCode` comes from the tag: `MAJOR*10000 + MINOR*100 + PATCH` (so `v0.2.0` is 200).
Phones only offer an update when the server's `app/version.txt` is above the installed app's code, so every
release that carries the app must have a higher version than the one before.

## Secrets the workflow needs

Add them under the repository's **Settings > Secrets and variables > Actions**:

| Secret | What |
|---|---|
| `FK_RELEASE_KEY` | The private half of the release signing key (the whole `.pem` file). |
| `FK_KEYSTORE_B64` | The Android release keystore, base64 encoded. |
| `FK_KEYSTORE_PASSWORD` | Its password (store and key password are the same). |
| `FK_LIBRARY_TOKEN` | Optional: a read-only token for the `filament-library` repository, for `library.tar.gz`. |

### The release signing key

Once:

1. On your PC, with Python and the `cryptography` package:
   `python tools/sign_release.py keygen --out <a folder outside the repo>/filament-kit-release.pem`. It writes
   the private key there (only you can read it; it never overwrites one) and prints only the public key.
2. `python tools/sign_release.py set-pubkey <the public key>` puts the public key into
   `server/filament_kit/release.py` and `get.sh`; commit both.
3. Add the `.pem` file's contents as the `FK_RELEASE_KEY` secret.
4. Back the `.pem` file up somewhere safe and off this PC. Losing it means a new key, and installs from before
   the change then refuse the new releases until updated by hand.

### The Android signing key

Android only installs an update over an installed app if it is signed with the **same** key, so losing the key
means everyone has to uninstall and reinstall the app.

1. Once, on a Windows PC: `powershell -ExecutionPolicy Bypass -File tools\android_keystore.ps1`. It creates
   `%LOCALAPPDATA%\filament-kit\release.jks` and a random password stored (encrypted with Windows DPAPI) in
   `%LOCALAPPDATA%\filament-kit\keystore.pw.dpapi`. You never type or see the password. It refuses to overwrite
   an existing keystore, and uses `keytool` from `JAVA_HOME` if set, otherwise the one on `PATH`.
2. Put the keystore (base64) and its password into the `FK_KEYSTORE_B64` and `FK_KEYSTORE_PASSWORD` secrets.
3. **Back up both** `release.jks` **and** `keystore.pw.dpapi` together, somewhere safe and off this PC. A DPAPI
   file only decrypts on this Windows account on this PC, so also make a portable backup:
   `powershell -ExecutionPolicy Bypass -File tools\android_keystore.ps1 -Export <path>` (you type a passphrase of
   at least 12 characters; remember it). On another PC restore it with `-Import <file>`. The
   `FK_BACKUP_PASSPHRASE` environment variable is for test automation only; never use it for a real backup.
4. `-Forget` deletes the keystore and the password file (it asks first).

### The filament library token

The workflow builds `library.tar.gz` from the private `thompsonfabco/filament-library` repository, lists it in
the signed `SHA256SUMS` and publishes it with the release. Installs check it against that signature before they
use it, and refuse a library from the default URL without one.

1. Make a GitHub token that can only read `thompsonfabco/filament-library`: **Settings > Developer settings >
   Personal access tokens > Fine-grained tokens > Generate new token**, repository access **Only select
   repositories** with `filament-library`, permission **Contents: Read-only**. Pick an expiry and note it.
2. Add it as the `FK_LIBRARY_TOKEN` secret, and renew it before it expires.

Without the secret the release is still built and published, without `library.tar.gz`; the run shows a warning.
Installs then keep the library copy they already have (or none) until a release carries one.

## Building a release tarball by hand

`bash tools/make_release.sh` builds `dist/filament-kit-<version>.tar.gz` and `dist/bambu_hardware.xml` on Linux
or in Git Bash on Windows. With the Android keystore on the PC it also builds and signs the app; set
`FK_VERSION_CODE=<n>` to the code that release will get (the workflow's formula above). `FK_NO_APP=1` skips the
app; the tarball then carries none, and a server installed from it offers no app at `/app.apk`.

A hand-built tarball is not signed. Users can install it with `sudo ./install.sh` (no signature check), but
`get.sh` and the updater only take releases from GitHub.

## Testing

- `server/tests` (`pytest`), `pc-sync/tests`, the Android unit tests (`./gradlew testDebugUnitTest`) and the
  reader's native tests run in CI on every push.
- [testing-e2e.md](testing-e2e.md): the end-to-end run on a disposable Ubuntu host (WSL), with real
  Spoolman, a fake printer and a fake releases server.
- [android-e2e.md](android-e2e.md): the Android end-to-end test on an emulator against a real server, and the
  checks that need a real phone.

## Third-party licences

[THIRD-PARTY.md](../THIRD-PARTY.md) lists every component a release ships or the installer fetches, with its
licence, and the open items (the Piper voice, ML Kit, our own licence metadata, notices in the release files).
Redo the check when a dependency is added or a pin changes: `pip-licenses` in a venv with
`filament-kit[station,web,push]`, `android/gradle/libs.versions.toml`, the two `platformio.ini` files and the
`apt` lists in `modules.py`.

## Before the repository goes public

- Close the open items in [THIRD-PARTY.md](../THIRD-PARTY.md), or decide to live with them.
- Scan the tree and the git history for private addresses, host names, serials and secrets.
  `server/tests/test_readme.py` scans the public docs and code for a list of such strings; extend the list
  rather than the exceptions.
- The one-command install in the README only works once the repository is public; remove the "private for
  now" notes from the README and the how-tos, and the `--token-file` route from
  [install-server.md](install-server.md).
- Google's developer verification for sideloaded Android apps (rolling out 2026–2027) may apply to the APK on
  the Releases page; check the current rules.
