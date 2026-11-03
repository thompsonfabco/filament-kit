# Known gaps

Things a normal user can't yet do the way the how-tos describe, found while writing them (2026-11-03, main at
fbe8641) and checking them against the code and an install on Ubuntu 26.04 in WSL. Remove an entry once it is
fixed.

## Releases and downloads

1. ~~No release exists.~~ Fixed 2026-11-03: v0.2.0 (beta) carries the signed tarball, APK, PC sync setup, `get.sh`,
   `bambu_hardware.xml` and the signed `SHA256SUMS`. The release signing key is in `release.py` and `get.sh`, and
   the repository secrets are set.
2. **The repository is private.** The one command only works once the repository is public. Until then the user
   needs a GitHub account that can see the repository plus a token and `get.sh --token-file`, which isn't a
   normal-user step. Downloads from the Releases page work in a browser that is signed in to GitHub.
3. **No library asset.** v0.2.0 has no `library.tar.gz`, so `filament-kit library update` and the `library`
   module find nothing until a release carries one (`FK_LIBRARY_TOKEN`).

## Android app

4. **No store.** The app is not on Google Play or F-Droid; it is sideloaded from the Releases page (or from the
   server). Google's developer verification for sideloaded apps is due to reach most phones in 2026–2027; check
   before the public release.
5. **The APK from the server shows a certificate warning.** `https://<server>.local:8710/app.apk` (served
   without sign-in) uses the server's self-signed certificate, so Chrome shows a warning first. Not tried on a
   phone.
## iPhone web app

6. **An https address and nginx are needed even at home.** The web service listens on 127.0.0.1 only, and
   `web.public_url` must be `https://`. A home-only user has to tick `web` and `remote` and accept nginx's
   self-signed placeholder certificate in Safari. Not tried on a real iPhone: whether a home-screen web app keeps
   working with an accepted self-signed certificate is unconfirmed.
7. **A public name needs split DNS or NAT loopback** so the phone reaches the server directly at home; otherwise
   the phone looks like it is away from home and is refused.
8. **`sudo filament-kit modules enable web` doesn't ask for the address.** It stops with
   `error: web needs web.public_url set ...`. Only the `config` → Modules checklist asks for it.
9. **`sudo filament-kit web status` shows `FAIL sign-in passphrase is set`** for a user who only wants the phone
   web app. The passphrase is only for the Claude connector.
10. **Home networks in 172.16.0.0/12 are not "home" by default** (it's left out because of Docker). Those users
    must edit `web.lan` in `config.json` by hand; there is no menu or prompt for it.

## Server install

11. **Confusing lines in the installer output.** A first install prints `id: 'spoolman': no such user`, and an
    apply prints a bare number (`997`) and `fields already present`. They are harmless, but look like errors.
12. **No firewall help.** The installer doesn't mention or open `ufw` ports (8710/tcp for the app, 5353/udp for
    `.local` names, 7912/tcp for Spoolman, 443/tcp for the web app). Ubuntu ships with `ufw` off, so most users
    won't hit this.
13. **Uninstalling after a one-command install** needs the user to unpack the kept tarball from
    `/opt/filament-kit/releases/<version>/` first. There is no `filament-kit uninstall`.
14. **Not checked here:** pairing from a real phone, and the APK install on a phone.

## How this was checked

On WSL Ubuntu 26.04: a tarball built from main with `tools/make_release.sh` (`FK_NO_APP=1`), `sudo ./install.sh`
in a terminal pressing Enter at every question (server mode, no AI). It ended with every status line `OK` or
`--`, a QR code and a pairing code, exit 0. Then `config` → Modules: web with `https://<host>.local/filament`, then
remote. nginx served `/filament/intake`, the manifest and the icon (HTTP 200) to an address inside `web.lan`,
refused others with 403, and refused a POST without the app's Origin. Then `uninstall.sh` and `--purge`, and the
packages the test added were removed.

Then the real v0.2.0 release: `get.sh` from the release, run with `--token-file` in a terminal pressing Enter at
every question. It printed `verified filament-kit 0.2.0`, installed (exit 0, status all OK), kept the release in
`/opt/filament-kit/releases/0.2.0/`, served the 63 MB APK at `/app.apk` (HTTP 200, `apk_version` 200), and
`update --check` said "up to date" with `updates.token_file` set (and a clear 404 message without it). Uninstalled
with `--purge` from the kept tarball, as the server how-to says.
