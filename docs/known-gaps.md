# Known gaps

Things a normal user can't yet do the way the how-tos describe, found while writing them (2026-11-03, main at
fbe8641) and checking them against the code and an install on Ubuntu 26.04 in WSL. Remove an entry once it is
fixed.

## Releases and downloads

1. ~~No release exists.~~ Fixed 2026-11-03: v0.2.0 (beta) carries the signed tarball, APK, Slicer Sync setup, `get.sh`,
   `bambu_hardware.xml` and the signed `SHA256SUMS`. The release signing key is in `release.py` and `get.sh`, and
   the repository secrets are set.
2. ~~The repository is private.~~ Fixed 2026-11-03: the repository is public, so the one command and the
   Releases page downloads need no GitHub account.
3. ~~No library asset.~~ Fixed in v0.3.0: v0.3.0 and v0.4.0 carry `library.tar.gz` (v0.2.0 does not, so
   `filament-kit catalog update` finds nothing in that release).

## App (Android)


4. **No store.** The app is not on Google Play or F-Droid; it is sideloaded from the Releases page (or from the
   Hub). Google's developer verification for sideloaded apps is due to reach most phones in 2026–2027; check
   the current rules.
5. **The APK from the Hub shows a certificate warning.** `https://<server>.local:8710/app.apk` (served
   without sign-in) uses the Hub's self-signed certificate, so Chrome shows a warning first. Not tried on a
   phone.
## iPhone web app

6. **An https address on your own name needs nginx.** At home the Hub serves the web app itself, at
   `https://<server name>.local:8710/intake`, with no setup (v0.5.1); Safari warns once about its own certificate.
   Only to avoid that warning or to use a name of your own, `web.public_url` must be `https://` and the
   web service (127.0.0.1 only) sits behind nginx: tick Web access and Remote access and accept nginx's
   self-signed placeholder certificate in Safari. The placeholder lasts 825 days and is made again by an apply within
   30 days of its end, after which Safari asks again. Not tried on a real iPhone: whether Safari accepts it and a
   home-screen web app keeps working with an accepted self-signed certificate is unconfirmed.
7. **A public name needs split DNS or NAT loopback** so the phone reaches the Hub directly at home; otherwise
   the phone looks like it is away from home and is refused.
8. ~~`features on web` doesn't ask for the address.~~ Fixed in v0.3.0: at a terminal it asks for
   `web.public_url`; without a terminal it still stops with `error: ... needs ...`.
9. ~~`web status` showed `FAIL` without a passphrase.~~ Fixed in v0.3.0: it shows `--   sign-in passphrase not set`
   (exit 0); the passphrase is only for the Claude connector.
10. **Home networks in 172.16.0.0/12 are not "home" by default** (it's left out because of Docker). Those users
    must edit `web.lan` in `config.json` by hand; there is no menu or prompt for it. From v0.4.1 a `web.lan` edit also
    widens Spoolman's own allow-list, unless `spoolman.allow` is set, which overrides it. A home network on
    172.16.x.x, and Tailscale or Docker clients, must add their range (to `web.lan` or `spoolman.allow`) or Spoolman
    stops answering them after the update.

## Hub install

11. ~~Confusing lines in the installer output.~~ Fixed in v0.3.0: no `no such user` line or bare number; the Spoolman
    line reads `Spoolman: the kit's extra fields are in place` or `... added the kit's extra fields: ...`.
12. **The installer doesn't open firewall ports.** When `ufw` is on, it prints the `sudo ufw allow` lines for the ports
    with no rule (8710/tcp for the app, 5353/udp for `.local` names, 7912/tcp for Spoolman, 443/tcp for the web app);
    running them is up to you. Ubuntu ships with `ufw` off, so most users won't hit this.
13. ~~Uninstalling after a one-command install needed the kept tarball.~~ Fixed in v0.3.0:
    `sudo filament-kit uninstall [--purge]` runs the kept release's uninstaller.
14. **Not checked here:** pairing from a real phone, and the APK install on a phone.
15. **Klipper printers (v0.4.0).** Add one from the app's **Printers** screen (**Add a Klipper printer**), on the Hub page's
    Printers section (**Add a printer**, type Klipper, v0.4.3), in the web app's **Manage printers**, or with
    `sudo filament-kit printer add --klipper`. Sovol SV08 MAX is verified; Sovol M1D is an unverified placeholder. The usage entries the Hub logs for a Klipper printer can't be undone
    from the Hub; correct the spool in Spoolman.

16. **The Hub page's data still shows serials and addresses on the home network (v0.4.3).** The new Overview and job
    log hide them until you give the setup code, but the page's older state (`/setup/api/state`) still lists printer
    serial numbers and addresses to any device on the home network without it, until a later stage of the console.
17. **Going back from v0.4.3 leaves the console's job unit.** `filament-kit-setup-job@.service` stays on disk, unused,
    after `sudo filament-kit update --rollback` from v0.4.3; the earlier Hub page does not call it. From v0.5.0 a
    rollback removes the unit files the version it leaves introduced.

## How this was first checked (v0.2.0)

On WSL Ubuntu 26.04: a tarball built from main with `tools/make_release.sh` (`FK_NO_APP=1`), `sudo ./install.sh`
in a terminal pressing Enter at every question (the Hub Setup, no AI). It ended with every status line `OK` or
`--`, a QR code and a pairing code, exit 0. Then the Features checklist: web with `https://<host>.local/filament`, then
remote. nginx served `/filament/intake`, the manifest and the icon (HTTP 200) to an address inside `web.lan`,
refused others with 403, and refused a POST without the app's Origin. Then `uninstall.sh` and `--purge`, and the
packages the test added were removed.

Then the real v0.2.0 release: `get.sh` from the release, run with `--token-file` in a terminal pressing Enter at
every question. It printed `verified filament-kit 0.2.0`, installed (exit 0, status all OK), kept the release in
`/opt/filament-kit/releases/0.2.0/`, served the 63 MB APK at `/app.apk` (HTTP 200, `apk_version` 200), and
`update --check` said "up to date" with `updates.token_file` set (and a clear 404 message without it). Uninstalled
with `--purge` from the kept tarball, as the Hub how-to says.
