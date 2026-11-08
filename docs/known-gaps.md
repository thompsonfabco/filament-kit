# Known gaps

Things a normal user can't yet do the way the how-tos describe, found while writing them (2026-11-03, main at
fbe8641) and checking them against the code and an install on Ubuntu 26.04 in WSL. Remove an entry once it is
fixed.

## Releases and downloads

1. ~~No release exists.~~ Fixed 2026-11-03: v0.2.0 (beta) carries the signed tarball, APK, PC sync setup, `get.sh`,
   `bambu_hardware.xml` and the signed `SHA256SUMS`. The release signing key is in `release.py` and `get.sh`, and
   the repository secrets are set.
2. ~~The repository is private.~~ Fixed 2026-11-03: the repository is public, so the one command and the
   Releases page downloads need no GitHub account.
3. ~~No library asset.~~ Fixed in v0.3.0: v0.3.0 and v0.4.0 carry `library.tar.gz` (v0.2.0 does not, so
   `filament-kit library update` finds nothing in that release).

## Android app

4. **No store.** The app is not on Google Play or F-Droid; it is sideloaded from the Releases page (or from the
   server). Google's developer verification for sideloaded apps is due to reach most phones in 2026–2027; check
   the current rules.
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
8. ~~`modules enable web` doesn't ask for the address.~~ Fixed in v0.3.0: at a terminal it asks for
   `web.public_url`; without a terminal it still stops with `error: ... needs ...`.
9. ~~`web status` showed `FAIL` without a passphrase.~~ Fixed in v0.3.0: it shows `--   sign-in passphrase not set`
   (exit 0); the passphrase is only for the Claude connector.
10. **Home networks in 172.16.0.0/12 are not "home" by default** (it's left out because of Docker). Those users
    must edit `web.lan` in `config.json` by hand; there is no menu or prompt for it.

## Server install

11. ~~Confusing lines in the installer output.~~ Fixed in v0.3.0: no `no such user` line or bare number; the Spoolman
    line reads `Spoolman: the kit's extra fields are in place` or `... added the kit's extra fields: ...`.
12. **No firewall help.** The installer doesn't mention or open `ufw` ports (8710/tcp for the app, 5353/udp for
    `.local` names, 7912/tcp for Spoolman, 443/tcp for the web app). Ubuntu ships with `ufw` off, so most users
    won't hit this.
13. ~~Uninstalling after a one-command install needed the kept tarball.~~ Fixed in v0.3.0:
    `sudo filament-kit uninstall [--purge]` runs the kept release's uninstaller.
14. **Not checked here:** pairing from a real phone, and the APK install on a phone.
15. **Klipper printers (v0.4.0).** The Android app has no Add screen for them; they appear once added with
    `sudo filament-kit klipper add`. The setup page (v0.4.1) lists and tests them (Moonraker Test and Forget) but can't add
    one either. Sovol SV08 MAX is verified; Sovol M1D is an unverified placeholder. The usage entries the kit logs for a Klipper printer can't be undone
    from the kit; correct the spool in Spoolman.

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
