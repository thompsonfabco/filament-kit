# Moving from filament-ops to filament-kit (cut-over runbook)

This moves the owner's filament-ops setup onto filament-kit, one machine at a time: the Spoolman VM first, then
the intake station PC, then the Windows desktop. Each machine has its steps, the checks that say it worked, and a
rollback. **Run it only with the owner's go, and only when no print is running** (the H2D usage tracker writes
to Spoolman, and Spoolman is down for a few minutes on the VM).

What stays as it is: the claude.ai connector URL `https://mcp.example.com/filament/mcp`, the phone app at
`https://mcp.example.com/filament/intake`, the passphrase, Claude's sign-in (the OAuth store is carried
over), Spoolman's data and port 7912, the amazon and h2d routes, the SV08 MAX tag reader and the H2D services.

Rule for every step: never `cat`, `less` or paste a secret file (`/etc/filament-mcp/*` other than `server.json`,
`oauth.json`, `/etc/filament-kit/web_passphrase`, `anthropic_key`, `h2d_token`). Copy them with `install`.

## 0. Before you start (desktop, 10 minutes)

1. Check the kit release tarball and the PC sync setup (`filament-kit-sync-setup-<version>.exe`) are at hand,
   and copy the tarball to the VM: `scp filament-kit-<version>.tar.gz spoolman-vm:` (it lands in the owner's home
   folder there; the commands below run from that folder).
2. On the VM, note what runs now (for the rollback):
   ```
   systemctl list-units --no-pager 'filament*' Spoolman.service smbd.service nginx.service h2d-*.service
   ls /etc/nginx/sites-enabled /etc/nginx/mcp.d
   ```
3. Make a rehearsal first if anything changed since 2026-11-02 (new lines, a new slicer version): export with
   `--no-secrets` into WSL and run `migrate-ops` there (section 5). The 2026-11-02 rehearsal is in the Task 8
   report.

## 1. Spoolman VM (`ssh spoolman-vm`)

### 1.1 Stop the ops writers and export the bundle

```
sudo systemctl stop filament-mcp.service filament-regen.path filament-regen.service
sudo systemctl stop Spoolman.service          # nothing writes the database from here on
tar xzf filament-kit-<version>.tar.gz
sudo bash filament-kit-<version>/install/export_ops.sh /root/ops-bundle.tar.gz
```

The export only reads (the database through sqlite's backup API; a database Spoolman left in WAL mode is read
from a private copy of it and its `-wal`, so nothing in Spoolman's folder is touched) and writes the one bundle
file (root, 600). It refuses a WAL database while Spoolman still runs. It ends with one line like
`bundle: {'spool': 296, 'filament': 213, 'vendor': ...} from <database>; presets {'presets/installed': N,
'presets/live': M}; secrets included`: expect about 296 spools and 213 filaments. N and M are **files** per tree
(a `.json` and a `.info` per preset: 413 Bambu Studio plus ~700 Orca presets), each a little over 2200; a
`missing` part at the end names anything left out. The bundle holds the passphrase hash, `oauth.json` and the
Anthropic key; it never holds the H2D token.

**Check:** `sudo tar tzf /root/ops-bundle.tar.gz | grep -c presets/` is over 4000; the counts printed match
Spoolman's web page from before.

**Rollback:** `sudo systemctl start Spoolman.service filament-mcp.service filament-regen.path` (nothing was
changed).

### 1.2 Install the kit (server mode)

```
sudo systemctl disable Spoolman.service filament-mcp.service filament-regen.path
cd filament-kit-<version> && sudo ./install.sh --mode server
```

The kit's own Spoolman (v0.27.0, the same as the ops one) starts on port 7912 with an empty database in
`/var/lib/spoolman`. The old database in `/home/user/.local/share/spoolman` is left exactly as it is (it is the
rollback). Skip the Anthropic key question if the installer asks: the migration brings it.

**Check:** `sudo filament-kit status` (Spoolman answers; the key line may FAIL until 1.3).

**Rollback:** `sudo ./uninstall.sh` (keeps data), then 1.1's rollback plus
`sudo systemctl enable Spoolman.service filament-mcp.service filament-regen.path`. If 1.3 got as far as the orders
drop-in, remove it as well (1.3's rollback).

### 1.3 Migrate

```
sudo filament-kit migrate-ops /root/ops-bundle.tar.gz            # dry run: read the report
sudo filament-kit migrate-ops /root/ops-bundle.tar.gz --apply
```

What `--apply` does (each line of the report says it): Spoolman's database replaced by the bundle's (services
stopped meanwhile, counts checked, the empty one backed up under `/var/backups/filament-kit/migrate-ops-<stamp>/`);
`lines.json` with the 116 ops lines (same names, Bambu Studio template and Orca parent set by you, and the
`filament_id` of the existing Bambu Studio presets); `extra.line` on the ~35 filaments the kit would otherwise
group elsewhere; `owner-edits.json` with the calibrated flow ratio, pressure advance, max volumetric speed,
nozzle and plate temperatures of every live preset plus your note lines; the OAuth store, the passphrase hash
and the Anthropic key; config (placement, locations, tare hints, the SV08 MAX tag reader, the station, the H2D
slot service, the orders file, the SV08 MAX and H2D Orca printers, `web.public_url`, `remote.hostname`, the
certbot window); and the H2D as a model-only printer (no address, no Access Code: the kit never connects to it,
the entry only makes the H2D presets). Running it again changes nothing. If the printers module's discovery
later sees the real H2D on the LAN, the app lists a second, "detected, not set up" H2D row next to `ops-h2d`;
the presets are made once per model either way. Remove the placeholder from the app's printer list then, or
leave it.
The step refuses a bundle whose database is not at Spoolman 0.27.0's schema revision (`fe4970567bb3`), read from
the database itself (the manifest has no version when Spoolman was stopped for the export).

Then the H2D token (never printed) and the orders exporter (it now writes into the kit's state folder; the ops
path is inside `filament-mcp`'s private folder, which the kit's user cannot read, and goes away with ops):

```
sudo install -m 640 -o root -g filament-kit /etc/filament-mcp/h2d_token /etc/filament-kit/h2d_token
sudo mkdir -p /etc/systemd/system/filament-orders.service.d
sudo tee /etc/systemd/system/filament-orders.service.d/filament-kit.conf >/dev/null <<'EOF'
[Service]
Environment=FILAMENT_ORDERS=/var/lib/filament-kit/filament_orders.json
ReadWritePaths=/var/lib/filament-kit
ExecStartPost=/bin/chgrp filament-kit /var/lib/filament-kit/filament_orders.json
EOF
sudo systemctl daemon-reload && sudo systemctl start filament-orders.service
```

(The exporter still sets group `filament-mcp` first, so keep that group until the exporter moves to the
amazon-mcp side; see section 4.)

**Check:**
- `curl -s 'http://127.0.0.1:7912/api/v1/spool?allow_archived=true' | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'`
  gives the spool count of 1.1 (and the same for `filament`).
- `sudo filament-kit profiles lines | head` lists the ops line names with both parents.
- `sudo ls -l /var/lib/filament-kit/filament_orders.json` is `root filament-kit`, fresh time.
- The H2D tools: `curl -s http://127.0.0.1:8105/api/state` still answers (owner service, unchanged).

**Rollback:** remove the orders drop-in first, so the exporter writes the ops file again:
`sudo rm -r /etc/systemd/system/filament-orders.service.d && sudo systemctl daemon-reload`. Then
`sudo systemctl stop filament-kit spoolman`, then 1.2's rollback. Spools added in the kit since then are in
`/var/lib/spoolman/spoolman.db` only: copy them over by hand if any.

### 1.4 Web unit and orders (same port 8101: the ops nginx route keeps working)

```
sudo filament-kit modules enable web
sudo filament-kit modules enable orders
sudo filament-kit web status
```

**Check:** `curl -s http://127.0.0.1:8101/health` is `ok`; `web status` shows the public URL, the passphrase
set and the connector registrations from ops. On the phone, open the intake app (same URL): it should still be
signed in; tap a tag on the SV08 MAX reader and see it in the Open spool tab. In claude.ai, ask the filament
connector for `preset_status` and `printer_slots`: it answers without a new sign-in.

**Rollback:** `sudo filament-kit modules disable web` (and `orders`), then
`sudo systemctl start filament-mcp.service` (port 8101 is free again; the route is unchanged). The ops server
still has its old `oauth.json`: the kit rotated Claude's refresh token since, so Claude has to sign in again
(the passphrase is the same). To avoid that, copy the kit's store back first (same format):
`sudo install -m 600 -o filament-mcp -g filament-mcp /var/lib/filament-kit/web/oauth.json /var/lib/filament-mcp/oauth.json`.

### 1.5 Remote access (the kit takes over nginx and certbot)

The ops router and the kit router collide (both are the default server on 443, and both install
`/usr/local/sbin/mcp-route`), so the ops pieces go first. The amazon, amazon-ext and h2d routes in
`/etc/nginx/mcp.d/` stay and are served by the kit's router, which includes the same folder and the same
`/etc/nginx/mcp-proxy.conf`. The certificate in `/etc/mcp-router/tls` (valid to 2027-01-28) is kept: the kit
never replaces a real one.

The kit overwrites some ops files when `remote` is turned on: `/usr/local/sbin/mcp-route`,
`/etc/nginx/mcp-proxy.conf`, `/etc/mcp-router/route.template`, the `filament` route in `/etc/nginx/mcp.d/` and
the certbot timer drop-in `/etc/systemd/system/certbot.timer.d/acme-window.conf`. It also adds
`/etc/mcp-router/host` and `/etc/mcp-router/kit-routes`; it never touches `/etc/mcp-router/tls`. Save the
overwritten ones first (the copy leaves the certificate's key where it is):

```
sudo mkdir -p /root/ops-router && sudo cp -a /etc/nginx/sites-available/mcp-router /usr/local/sbin/mcp-route \
    /etc/nginx/mcp.d /etc/nginx/mcp-proxy.conf /etc/mcp-router/route.template /root/ops-router/
sudo cp -a /etc/systemd/system/certbot.timer.d/acme-window.conf /root/ops-router/ 2>/dev/null || true
sudo ls /root/ops-router                               # mcp-router mcp-route mcp.d mcp-proxy.conf route.template ...
sudo rm /etc/nginx/sites-enabled/mcp-router            # the ops router conf (the file in sites-available stays)
sudo rm /usr/local/sbin/mcp-route                      # replaced by the kit's
sudo filament-kit modules enable remote                # router conf, mcp-route, hooks; route filament -> 8101
sudo nginx -t && sudo /usr/local/sbin/mcp-route ls
```

`remote.hostname` is `mcp.example.com` and `remote.acme_window` is `03:10 America/New_York` (the
migration set both; pfSense forwards port 80 only from 03:00 to 03:30).

From now on the kit's router conf `/etc/nginx/conf.d/filament-kit-router.conf` is the only server block that
includes `/etc/nginx/mcp.d`: it serves the amazon, amazon-ext and h2d routes as well. Turning `remote` off, or
uninstalling the kit, keeps that file while those routes are there (it says so); remove it by hand only once
nothing needs them.

Each certificate renewal by the kit stops nginx for the few seconds certbot needs port 80 (certbot runs
standalone; the kit's hooks stop and start nginx), so the amazon, amazon-ext and h2d routes are down for that
moment too, inside the 03:10 window.

**Check:** from the LAN: `curl -s https://mcp.example.com/health` (router ok),
`curl -s https://mcp.example.com/filament/health` (ok), the amazon connector and
`https://mcp.example.com/h2d/` and `/printer/` still answer; the claude.ai connector works from outside.

**The certificate.** The ops lineage (`spoolman-mcp.example.com`) keeps renewing with the ops hook
(`/usr/local/sbin/filament-acme-hook`) until the kit has its own. That hook is the only thing that opens port 80
on the VM today: its `pre` step turns the nft `acme` chain to accept and its `post` step back to drop. The kit's
hooks never touch the firewall, so once the ops hook is gone **port 80 must stay open to certbot on the VM for
good**, or every renewal fails. pfSense already forwards port 80 only from 03:00 to 03:30 (schedule ACME), so
that is safe. The owner makes this change themselves (the kit only documents it), one of:
- switch the acme chain to accept for good: `sudo nft flush chain inet filament acme && sudo nft add rule inet
  filament acme accept`, and the same in `/etc/nftables.d-filament.nft` so it survives a reboot; or
- a permanent `tcp dport 80 accept` in the input chain (`filament-kit remote firewall` prints it).

Then, at the next window (03:00-03:30): `sudo filament-kit remote issue`. After it succeeds:
`sudo certbot delete --cert-name spoolman-mcp.example.com` and `sudo rm /usr/local/sbin/filament-acme-hook`
(the old `spoolman-mcp` name is no longer served; nothing uses it since 2026-10-30).

**Check (certificate):** in the following window, `sudo certbot renew --dry-run` succeeds for
`mcp.example.com`; `sudo certbot certificates` lists only that lineage; `systemctl list-timers certbot.timer`
shows 03:10.

**Rollback:** `sudo filament-kit modules disable remote`. That removes only the kit's own files: its certbot
deploy hook `/etc/letsencrypt/renewal-hooks/deploy/filament-kit` and its `filament` route; nginx, certbot, the
certificate and the other routes stay. Its router conf `/etc/nginx/conf.d/filament-kit-router.conf` stays too,
because the amazon and h2d routes are still in `/etc/nginx/mcp.d` (the command says so); remove it by hand right
before the ops router goes back (both are the default server on 443). Then put the ops pieces back:
```
sudo rm /etc/nginx/conf.d/filament-kit-router.conf
sudo ln -s /etc/nginx/sites-available/mcp-router /etc/nginx/sites-enabled/mcp-router
sudo cp -a /root/ops-router/mcp-route /usr/local/sbin/ && sudo cp -a /root/ops-router/mcp.d/. /etc/nginx/mcp.d/
sudo cp -a /root/ops-router/route.template /etc/mcp-router/
sudo test -f /root/ops-router/acme-window.conf && sudo cp -a /root/ops-router/acme-window.conf \
    /etc/systemd/system/certbot.timer.d/ && sudo systemctl daemon-reload
sudo cp /root/ops-router/mcp-proxy.conf /etc/nginx/ && sudo nginx -t && sudo systemctl reload nginx
```
`/etc/mcp-router/host` and `kit-routes` can stay (the ops pieces do not read them). If the ops hook or lineage
was already removed, renewals stay on the kit's lineage and still reach `/etc/mcp-router/tls`: `remote issue`
wrote `--deploy-hook /usr/local/sbin/filament-kit-acme-hook deploy` into that lineage's renewal conf, and the
hook script and `/etc/mcp-router/host` stay when `remote` is turned off. Only the second copy of the hook (the
file in `renewal-hooks/deploy/`) is gone; it matters only after a `certbot --expand`, which rewrites the renewal
conf: then copy the renewed cert into `/etc/mcp-router/tls` by hand, or turn `remote` on again. If the acme
chain was switched to accept, the owner may switch it back to drop.

### 1.6 Optional hardening (the owner's firewall)

The ops `inet filament` output chain limits uid `filament-mcp` only. The kit's units already restrict addresses
(`IPAddressAllow`); mirror the egress rules for uid `filament-kit` in nftables if wanted. The phone app port
8710 (Android) is open on the LAN by the default input policy.

## 2. Station PC (192.0.2.11, `intake.home.arpa`)

1. Copy the release tarball to the station PC and unpack it there (the steps below run from that folder):
   `scp filament-kit-<version>.tar.gz intake.home.arpa:`, then on the station PC
   `tar xzf filament-kit-<version>.tar.gz && cd filament-kit-<version>`.
2. Stop the old service and move its udev rule aside (the ops rule `99-intake-station.rules` gives the scale to
   group `intake-station`, which the kit's station user is not in):
   ```
   sudo systemctl disable --now intake-station.service          # it holds port 5003
   sudo mv /etc/udev/rules.d/99-intake-station.rules /root/99-intake-station.rules.ops
   sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
   ```
   The kit's own rule, `99-zz-filament-kit-station.rules`, sorts after the ops one, so the kit's group wins even
   if the ops rule comes back; moving it aside keeps one owner per device.
3. **The panel firmware.** On its first start the kit's station writes its bundled firmware to the SV08 MAX
   panel when the panel runs another version (about a minute; the panel restarts). To leave the panel's firmware
   as it is, set `station.panel_flash` to false **before** installing (the installer keeps the settings it finds
   and adds the rest):
   ```
   sudo install -d -m 750 /etc/filament-kit
   echo '{"station": {"panel_flash": false}}' | sudo tee /etc/filament-kit/config.json >/dev/null
   ```
4. Install the kit in station mode, pointing at the VM:
   `sudo ./install.sh --mode station --server spoolman.home.arpa`.
5. Leave the scale switched on (it must be on to enumerate).

**Check:** from the VM, `curl -s http://intake.home.arpa:5003/state` shows the scale and tag; on the
VM `sudo filament-kit status` has the station OK; a tag tapped at the station shows in the phone app's Open spool
tab within 3 s, with the scale weight. On the station PC, `ls -l /dev/hidraw*` shows the scale's node in group
`filament-kit-station`.

**Rollback:** `sudo ./uninstall.sh`, then put the ops rule back and start the old service:
```
sudo mv /root/99-intake-station.rules.ops /etc/udev/rules.d/99-intake-station.rules
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
sudo systemctl enable --now intake-station.service
```

## 3. Desktop (Windows, Bambu Studio and Orca Slicer)

Two installers on one slicer folder is the hazard: the ops task must not run once the kit's sync is paired.

1. **Stop fpsync:** in PowerShell, `Disable-ScheduledTask -TaskName 'Filament preset sync'`.
2. **Pair the PC sync:** close Bambu Studio and Orca Slicer, run `filament-kit-sync-setup-<version>.exe`, then on
   the VM `sudo filament-kit pair --pc` and paste the link (see the README, "PC sync"). It uploads both slicers'
   presets; the VM's first build follows.
3. **The first build** (`sudo filament-kit profiles status` on the VM): its `build:` line should read about
   `413 presets, 694 Orca presets, 0 Orca stale` (413 Bambu Studio presets, every one keeping its `filament_id`).
   It rewrites, once:
   - the per-variant arrays of the Orca H2D presets from 3 extruder variants to the 2 the Orca H2D parent has
     (your calibrated values follow by variant name: "fitted from 3 to 2 extruder variants" lines);
   - the `version` of the adopted Orca H2D presets (ops wrote 2.8.0.16; the kit writes the parent's);
   - one preset ops had is not made (`Bambu Lab TPU 85A @SV08 MAX 0.4`: the library rules that nozzle out).
   The `problems` list shows the stock system presets your slicers cannot resolve (Bambu Support, COEX, ...):
   they were there before and do not affect the generated presets.
4. Open both slicers once the sync says it installed: the presets keep their names; your calibrated values are
   kept (they are recorded as your in-app values from now on).
5. **Retire fpsync:** `Unregister-ScheduledTask -TaskName 'Filament preset sync' -Confirm:$false`.
6. **Retire Samba** (VM, after a day of normal syncing):
   `sudo systemctl disable --now smbd nmbd`; remove the `[filament]` share from `/etc/samba/smb.conf`
   (or the included `smb-filament.conf`); the owner removes the nft rules for 139/445 from 192.0.2.7.
   `/srv/filament` stays until filament-ops is archived.

**Check:** `sudo filament-kit profiles status` shows the PC sync owner, the installed build and no new
problems; Bambu Studio and Orca Slicer show the presets with the same names.

**Rollback:** unpair the PC (`sudo filament-kit unpair <id>` on the VM), uninstall the PC sync, then
`Enable-ScheduledTask -TaskName 'Filament preset sync'` and (if retired) `sudo systemctl enable --now smbd`. The
slicers' folders keep the kit's last install until fpsync installs the next ops build, and that needs the ops
side running on the VM again: the whole VM chain backwards, 1.5's rollback, then 1.4's, 1.3's, 1.2's and 1.1's,
in that order (each rollback assumes the later steps are undone).

## 4. After a week of normal use

- Archive filament-ops (repository read-only). On the VM: `/opt/filament-mcp`, `/var/lib/filament-mcp`,
  `/etc/filament-mcp`, `/srv/filament`, the ops units and the old Spoolman in `/home/user/Spoolman` can go.
- Keep `export_filament_orders.py` (move it next to amazon-mcp, change its group to `filament-kit` and drop the
  `ExecStartPost` line) before removing the `filament-mcp` user and group.
- Delete `/root/ops-bundle.tar.gz` (it holds secrets).
- The kit's router conf serves the amazon, amazon-ext and h2d routes too. If the kit is ever removed from the
  VM, `uninstall.sh` keeps that router conf while those routes are in `/etc/nginx/mcp.d` (it says so); give them
  another router before removing it by hand.

## 5. Rehearsal (no live changes)

```
ssh spoolman-vm 'sudo bash -s -- --no-secrets -' < tools/export_ops.sh > (a WSL path)/ops-bundle.tar.gz
```

On a WSL all-in-one install: add fixture secrets to the bundle (never the real ones), run `migrate-ops` dry and
with `--apply`, check the counts, `lines.json` (116 lines, Orca parents), upload the slicers' presets and run a
build; then `uninstall.sh --purge` and delete the bundle.
