# Known gaps

Things a normal user can't yet do the way the how-tos describe, found while writing them (2026-11-03, main at
fbe8641) and checking them against the code and an install on Ubuntu 26.04 in WSL. Remove an entry once it is
fixed.

## Releases and downloads

1. **No release exists.** The repository has no tags or GitHub releases, so `get.sh`, `filament-kit-<version>.tar.gz`,
   `filament-kit.apk` and `filament-kit-sync-setup-<version>.exe` can't be downloaded from anywhere. The
   one-command install answers 404.
2. **No release signing key.** `PUBKEY` in `server/filament_kit/release.py` (and the copy in `get.sh`) is empty, so
   `get.sh` and `filament-kit update` can verify nothing. The owner has to run `tools/sign_release.py keygen`, then
   `set-pubkey` and `sync-get`.
3. **No repository secrets.** `release.yml` needs `FK_RELEASE_KEY`, `FK_KEYSTORE_B64` and `FK_KEYSTORE_PASSWORD`
   (and `FK_LIBRARY_TOKEN` for the library asset). None are set, so a tag push would fail on purpose.
4. **The repository is private.** Even with a release, the one command only works once the repository is
   public. Until then the user needs a GitHub token and `get.sh --token-file`, which isn't a normal-user step.

## Android app

5. **No signed APK and no store.** The app is not on Google Play or F-Droid. Until the first release, the only
   APK is one a developer builds with Android Studio or Gradle. The release CI makes the signed one.
6. **The APK from the server shows a certificate warning.** `https://<server>.local:8710/app.apk` (served
   without sign-in) uses the server's self-signed certificate, so Chrome shows a warning first. Not tried on a
   phone. It only exists when the server was installed from a release tarball that carries the app.
7. **Google's developer verification for sideloaded apps** is due to reach most phones in 2026–2027. Sideloading
   the APK may then need it to come from a registered developer. Check before the public release.

## iPhone web app

8. **An https address and nginx are needed even at home.** The web service listens on 127.0.0.1 only, and
   `web.public_url` must be `https://`. A home-only user has to tick `web` and `remote` and accept nginx's
   self-signed placeholder certificate in Safari. Not tried on a real iPhone: whether a home-screen web app keeps
   working with an accepted self-signed certificate is unconfirmed.
9. **A public name needs split DNS or NAT loopback** so the phone reaches the server directly at home; otherwise
   the phone looks like it is away from home and is refused.
10. **`sudo filament-kit modules enable web` doesn't ask for the address.** It stops with
    `error: web needs web.public_url set ...`. Only the `config` → Modules checklist asks for it.
11. **`sudo filament-kit web status` shows `FAIL sign-in passphrase is set`** for a user who only wants the phone
    web app. The passphrase is only for the Claude connector.
12. **Home networks in 172.16.0.0/12 are not "home" by default** (it's left out because of Docker). Those users
    must edit `web.lan` in `config.json` by hand; there is no menu or prompt for it.

## Server install

13. **Confusing lines in the installer output.** A first install prints `id: 'spoolman': no such user`, and an
    apply prints a bare number (`997`) and `fields already present`. They are harmless, but look like errors.
14. **No firewall help.** The installer doesn't mention or open `ufw` ports (8710/tcp for the app, 5353/udp for
    `.local` names, 7912/tcp for Spoolman, 443/tcp for the web app). Ubuntu ships with `ufw` off, so most users
    won't hit this.
15. **Uninstalling after a one-command install** needs the user to unpack the kept tarball from
    `/opt/filament-kit/releases/<version>/` first. There is no `filament-kit uninstall`.
16. **Not checked here:** `get.sh` against a real GitHub release (`tools/e2e/run.sh` checks it against a fake
    one), pairing from a real phone, and the APK install.

## How this was checked

On WSL Ubuntu 26.04: a tarball built from main with `tools/make_release.sh` (`FK_NO_APP=1`), `sudo ./install.sh`
in a terminal pressing Enter at every question (server mode, no AI). It ended with every status line `OK` or
`--`, a QR code and a pairing code, exit 0. Then `config` → Modules: web with `https://<host>.local/filament`, then
remote. nginx served `/filament/intake`, the manifest and the icon (HTTP 200) to an address inside `web.lan`,
refused others with 403, and refused a POST without the app's Origin. Then `uninstall.sh` and `--purge`, and the
packages the test added were removed.
