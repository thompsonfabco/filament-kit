# Moving from filament-ops

filament-ops was the setup filament-kit grew out of: a filament MCP server and phone intake page on a Linux
server, a `regen.py` preset generator with a Samba share and a Windows scheduled task (`fpsync`), an
`intake-station` service for the scale and the NFC reader, and the `h2d-filament-scanner` services for one H2D.
The kit replaces all of it, and brings the data over.

This page is for anyone who ran filament-ops. It is the general procedure; a specific machine's addresses,
firewall and routes are yours to fill in.

## What moves

`filament-kit migrate-ops` takes an export bundle from the old server and moves into the kit:

- Spoolman's database (every spool, filament and vendor), replacing the kit's empty one;
- the filament lines with their Bambu Studio and Orca Slicer parents, and the `filament_id` of the existing
  presets, so the generated presets keep their names and ids;
- your calibrated values from the live presets (flow ratio, pressure advance, max volumetric speed, nozzle and
  plate temperatures, your note lines), kept as your in-app edits from then on;
- the Claude connector's sign-ins (the OAuth store), the web passphrase and the Anthropic key;
- the settings: placement rules, locations, tare hints, tag readers, the station, the orders file, the Orca
  printers, `web.public_url`, `remote.hostname` and the certbot window.

The H2D's slot numbering and usage calibration move separately with `filament-kit migrate-scanner`.

## 1. Export on the old server

Unpack the kit release there and run the exporter. It only reads (the database through sqlite's backup API) and
writes one bundle file, root-only:

```bash
sudo systemctl stop filament-mcp.service filament-regen.path filament-regen.service
sudo systemctl stop Spoolman.service          # nothing writes the database from here on
tar xzf filament-kit-<version>.tar.gz
sudo bash filament-kit-<version>/install/export_ops.sh /root/ops-bundle.tar.gz
```

It ends with one line of counts (`bundle: {'spool': N, 'filament': M, ...}`), the preset file counts, and a
`missing` part naming anything it could not include. The bundle holds the passphrase hash, the OAuth store and
the Anthropic key, so treat it as a secret and delete it when you are done. `--no-secrets` leaves those out (for
a rehearsal on another machine).

Rollback at this point: start the old services again; nothing was changed.

## 2. Install the kit on the same server

```bash
sudo systemctl disable Spoolman.service filament-mcp.service filament-regen.path
cd filament-kit-<version> && sudo ./install.sh --mode server
```

The kit's own Spoolman starts on port 7912 with an empty database in `/var/lib/spoolman`; the old database is
left where it was, as the rollback. Skip the Anthropic key question: the migration brings the key.

## 3. Migrate

```bash
sudo filament-kit migrate-ops /root/ops-bundle.tar.gz            # dry run: read the report
sudo filament-kit migrate-ops /root/ops-bundle.tar.gz --apply
```

The dry run prints every change it would make. `--apply` stops the services while it replaces the database
(the empty one is backed up under `/var/backups/filament-kit/migrate-ops-<stamp>/`), checks the counts, and
writes the lines, the owner edits, the stores and the settings. Running it again changes nothing. It refuses a
bundle whose database is not at the Spoolman schema the kit expects.

Check: the spool count in Spoolman matches the export; `sudo filament-kit profiles lines` lists your lines
with both parents; `sudo filament-kit status` is all OK.

Then turn on the modules you used: `sudo filament-kit modules enable web` (the connector and phone app keep
their address and sign-ins), `orders` (with `orders.file` pointing at your order history file), and `remote`
(see [Remote access](user-guide.md#remote-access); the kit takes over nginx and certbot, and keeps a real
certificate it finds).

## 4. The station computer

On the computer with the scale and the NFC reader: stop the old `intake-station` service (it holds port 5003),
move its udev rule aside (the kit installs its own), then
`sudo ./install.sh --mode station --server <the server's name or address>`. If a button panel is attached and
you want to keep its firmware as it is, put `{"station": {"panel_flash": false}}` into
`/etc/filament-kit/config.json` before installing. Details: [Intake station](user-guide.md#intake-station).

## 5. The Windows PC

Disable the old `fpsync` scheduled task first, so two installers never touch one slicer folder. Then install the
PC sync and pair it ([Pair your PC](user-guide.md#pair-your-pc)). The first build keeps every preset's name and
id and your calibrated values; `sudo filament-kit profiles status` shows it. Once it syncs, remove the old task
and the Samba share.

## 6. The H2D from the scanner

The kit's `printers` module replaces the `h2d-filament-scanner` services without a new calibration print:

1. Turn on `printers` (and `web` for the bench reader) and add the H2D in the app or with
   `sudo filament-kit config` → Printers, with its Access Code. Don't press Map slots yet.
2. With no print running, stop the scanner services (`h2d-scanner`, `h2d-remote`, `h2d-usage`), so no print is
   ever deducted twice.
3. Seed the slot map and move the spools' Spoolman locations from the scanner's calibration file:

   ```bash
   sudo filament-kit migrate-scanner /var/lib/h2d-usage/calibration.json          # dry run
   sudo filament-kit migrate-scanner /var/lib/h2d-usage/calibration.json --apply
   ```

   It prints each change as `old → new`, writes a backup first (`/var/backups/filament-kit/migrate-scanner-<stamp>.json`),
   refuses a printer that already has a different map unless `--replace-map`, and changes nothing when run again.
4. If the kit was pointed at the scanner's slot endpoints (`slot_service` in `config.json`), remove that setting
   and restart `filament-kit` and `filament-kit-web`. Then reflash the bench reader for the kit
   ([reader/README.md](../reader/README.md)).

Rollback: remove the printer from the kit (or delete its `slotmap.json`, which puts usage back to observe
mode), put the spools' old locations back from the backup, and start the scanner services again.

## Rehearsal

Export with `--no-secrets` and run steps 2 and 3 on a throwaway install (WSL works), then `uninstall.sh --purge`
and delete the bundle. Nothing on the old server changes.
