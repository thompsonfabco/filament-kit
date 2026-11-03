# Install test (Task 10, Step 3)

Run on a **disposable** Ubuntu 26.04 host (a fresh VM is best) that the owner names. Call it
`KIT_TEST_HOST` below. Ask the owner which host before starting; never run this on a machine with data you
want to keep, and never on the owner's own Spoolman VM.

What you need: the release tarball from `bash tools/make_release.sh` (`dist/filament-kit-<version>.tar.gz`),
an Anthropic test key, and a JPEG label photo (≤ 3 MB), e.g. `label.jpg`.

Record every command's output in the task report.

## 1. Fresh install

```
scp dist/filament-kit-0.1.0.tar.gz label.jpg KIT_TEST_HOST:
ssh -t KIT_TEST_HOST
tar xzf filament-kit-0.1.0.tar.gz && cd filament-kit-0.1.0
sudo ./install.sh          # display name: type  Pat's Küche  (not the default), Enter for storage defaults, paste the key
```

Expect: the installer ends with `filament-kit status` (all lines `OK`, including `filament-kit API answering`)
and a QR code + 6-digit pairing code. Note the code. The display name must not break anything: the
certificate and the QR use the host name, not the display name.

```
sudo runuser -u filament-kit -- /opt/filament-kit/venv/bin/python -I -c \
  'from filament_kit import pairing; print(pairing.issue().qr)'    # the QR payload as text
sudo openssl x509 -in /etc/filament-kit/cert.pem -noout -subject -ext subjectAltName   # the dir is 2750: sudo
```

Here `<hostname>` is the short name (`hostname -s`). Expect the cert subject `CN=<hostname>`, SANs
`<hostname>`, `<hostname>.local`, `localhost` (plus the full name if `hostname` prints one with a domain) and
the host's LAN IPs (no 169.254.x.x). The QR payload has `h=<hostname>.local`, `p=8710`, `t=`, `fp=` and one
`ip=` per LAN address. Note: `pairing.issue().qr` creates a real pending pairing, just like
`sudo filament-kit pair`; its token and code stay valid for 10 minutes and then expire unused.

Checks on the host:

```
sudo filament-kit status; echo "exit=$?"                     # every line OK, exit=0
systemctl is-active spoolman filament-kit filament-kit-backup.timer filament-kit-library.timer filament-kit-build.path   # active x5
systemctl list-timers filament-kit-backup.timer filament-kit-library.timer   # both listed, each with a NEXT time
sudo sh -c 'stat -c "%U:%G %a %n" /etc/filament-kit /etc/filament-kit/* /var/lib/filament-kit /var/lib/spoolman'
```

Expected modes: `/etc/filament-kit` root:filament-kit 2750; `config.json`, `anthropic_key`, `key.pem`
root:filament-kit 640; `cert.pem` root:filament-kit 644; `/var/lib/filament-kit` filament-kit:filament-kit
750; `/var/lib/spoolman` spoolman:spoolman 750.

The key must not appear anywhere it should not:

```
sudo journalctl -b | grep -c sk-ant- ; history | grep -c sk-ant-      # both 0
```

### Library and presets

```
sudo filament-kit library update
#   prints the library version; while the filament-library repo is private, a warning "using bundled version N"
sudo systemctl start filament-kit-library.service; systemctl is-failed filament-kit-library.service
#   "inactive" (not "failed"), also while the repo is private
sudo filament-kit profiles build
#   before any PC sync has uploaded: prints the "install and pair the PC sync" message, makes no build
sudo sh -c 'stat -c "%U:%G %a %n" /var/lib/filament-kit/profiles /var/lib/filament-kit/library /var/lib/filament-kit/library-local'
#   filament-kit:filament-kit 750 x3
sudo -u filament-kit touch /var/lib/filament-kit/profiles/rebuild-request
sleep 3; journalctl -u filament-kit-build.service -n 5 --no-pager   # the build service ran once
```

## 2. Network checks (from another machine on the LAN)

```
curl -k https://KIT_TEST_HOST:8710/api/info          # {"name": "Pat's Küche", "version": "0.1.0", "api": 1, ...}
avahi-browse -rt _filamentkit._tcp                   # (needs avahi-utils) lists "filament-kit on <host>", port 8710
curl -s http://KIT_TEST_HOST:7912/api/v1/info        # Spoolman version 0.27.0
```

Printer discovery needs the test host on the **same L2 segment** as the printers (same switch / Wi-Fi, no
router in between) and, if a host firewall is on, inbound **UDP 2021 and 1990** allowed
(`sudo ufw allow from <LAN range> to any port 2021,1990 proto udp`). A WSL or NAT-networked host never receives
the printer announcements: add printers there by hand with `sudo filament-kit config` → Printers → add printer
(name, IP, serial, Access Code), and expect `POST /api/printers` for a never-seen printer to answer 404
`not_found` ("That printer hasn't been seen on the network yet").

## 3. Pair and add a spool through the API

Use the pairing code from step 1 (or `sudo filament-kit pair` for a new one):

```
H=https://KIT_TEST_HOST:8710
TOKEN=$(curl -sk -X POST $H/api/pair -H 'Content-Type: application/json' \
  -d '{"code": "<6-digit code>"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -sk $H/api/intake/read -H "Authorization: Bearer $TOKEN" -F photo=@label.jpg > read.json
cat read.json        # {"items": [...], "questions": [...], "tag": ..., "usage": {...}, "read_id": "..."}
```

`/api/intake/add`, `/api/spools/{id}/link` and `PATCH /api/spools/{id}` default to a dry run
(`"dry_run": true`) unless the body says otherwise. First a dry run, then the real write with
`"dry_run": false` sent explicitly:

```
python3 -c 'import json; r=json.load(open("read.json")); print(json.dumps({"items": r["items"], "dry_run": True}))' > dry.json
python3 -c 'import json; r=json.load(open("read.json")); print(json.dumps({"items": r["items"], "dry_run": False}))' > add.json
curl -sk $H/api/intake/add -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @dry.json
#   expect "dry": true, nothing in Spoolman yet
curl -sk $H/api/intake/add -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @add.json
```

Expect `{"spool_ids": [...], "dry": false, ...}` from the second call. Open `http://KIT_TEST_HOST:7912` in a
browser and confirm the spool is there with the right brand, material and colour.

### Unpair while the phone polls

Pair a second device (`sudo filament-kit pair`, redeem the code as above into `TOKEN2`), then poll with it from
the LAN machine while the CLI revokes it on the host:

```
while true; do curl -sk -o /dev/null -w '%{http_code}\n' $H/api/spools -H "Authorization: Bearer $TOKEN2"; sleep 0.5; done
# on the host, while the loop runs:
sudo filament-kit unpair                             # note the second device's id
sudo filament-kit unpair <id>
sudo filament-kit unpair                             # that id is gone and stays gone
```

Expect the loop to switch from `200` to `401` and stay there, the first device still listed and its `$TOKEN`
still answering `200`, and `/var/lib/filament-kit/devices.json` valid JSON
(`sudo python3 -m json.tool /var/lib/filament-kit/devices.json`).

## 4. Backup

```
sudo systemctl start filament-kit-backup.service
sudo ls -l /var/backups/filament-kit                  # <today>.tar.gz
sudo tar -tzf /var/backups/filament-kit/$(date +%F).tar.gz   # ./spoolman.db, etc/filament-kit/..., var/lib/filament-kit/...
sudo tar -tzf /var/backups/filament-kit/$(date +%F).tar.gz | grep -cE 'profiles/live/system|library/versions|profiles/builds/[^/]*\.tmp'   # 0
```

## 5. Upgrade (re-run)

```
sudo filament-kit cert > fp-before.txt
sudo ./install.sh                                    # must ask NO questions
sudo filament-kit cert | diff - fp-before.txt && echo "cert unchanged"
sudo filament-kit status                             # all OK
sudo filament-kit unpair                             # the device paired in step 3 is still listed
```

Spoolman UI still shows the spool from step 3; the token from step 3 still works:

```
curl -sk $H/api/spools -H "Authorization: Bearer $TOKEN"
```

## 6. Uninstall (keep data)

```
sudo ./uninstall.sh
systemctl list-unit-files | grep -E 'spoolman|filament-kit'    # nothing
ls /opt/filament-kit /opt/spoolman                             # both gone
sudo ls /etc/filament-kit /var/lib/filament-kit /var/lib/spoolman /var/backups/filament-kit   # all still there
```

Then `sudo ./install.sh` once more: no questions, the spool and the paired device are back, the certificate
fingerprint is unchanged.

## 7. Clean up

`sudo ./uninstall.sh --purge` (type `purge`), or destroy the VM.

# WSL install test: install modes and the station module

A second, repeatable test for the modules work (spec `docs/superpowers/specs/2026-11-02-modules-design.md`,
section 7). It runs on the dev PC's WSL **Ubuntu 26.04** (systemd running, passwordless sudo, no USB). Never on the
family member's install, the owner's Spoolman VM or the station PC.

Run every command with `wsl -d Ubuntu --exec bash -lc '...'`: plain `wsl -d Ubuntu -- ...` passes the command
through a login shell first, which expands `$?` and `$(...)` too early (an exit code then reads 0).

## Procedure

```
# Windows, Git Bash
bash tools/make_release.sh                                     # dist/filament-kit-<version>.tar.gz
# WSL: copy and unpack in the WSL home, never run from /mnt/c
mkdir -p ~/fk-test && cp <local path>/filament-kit-modules/dist/filament-kit-0.2.0.tar.gz ~/fk-test/
cd ~/fk-test && tar xzf filament-kit-0.2.0.tar.gz && cd filament-kit-0.2.0
```

Purge between the modes (`echo purge | sudo ./uninstall.sh --purge`). Run the installer with `</dev/null` so it
behaves as a non-interactive install, and type no API key.

1. **server**: `sudo ./install.sh --mode server`. `sudo filament-kit status` has one `FAIL` (the missing key) and
   exits 1; `spoolman filament-kit filament-kit-backup.timer filament-kit-library.timer filament-kit-build.path`
   active, `filament-kit-station` inactive; `curl localhost:7912/api/v1/info` answers 0.27.0.
2. **station**: `sudo ./install.sh --mode station --server 127.0.0.2` (127.0.0.2 is a single loopback address
   that is not a server). Only `filament-kit-station` active; `curl 127.0.0.1:5003/state` 200;
   `curl --interface 127.0.0.2 http://127.0.0.1:5003/state` 200; the drop-in has `IPAddressAllow=localhost
   127.0.0.2`; `journalctl -u filament-kit-station` shows `NFC reader None: no USB serial port for the reader;
   retrying in 5 s`.
3. **all-in-one**: `sudo ./install.sh --mode all-in-one`. All six units active; status shows `station answering at
   http://127.0.0.1:5003`, `station reader not seen`, `station scale not seen`; with a paired token
   `GET /api/station` 200 (the station's `/state`), without one 401;
   `curl --interface <eth0 IP> http://<eth0 IP>:5003/state` gets no answer.
4. **Switches without reinstall** (from all-in-one, with a spool added through Spoolman's API):
   `modules set station` without `--server` is refused with a `fix:`; `modules set station --server 127.0.0.2`
   leaves only the station running and `/var/lib/spoolman/spoolman.db` in place; `modules set all-in-one` brings
   back every unit, the spool and the paired token; `modules disable printers` makes `GET /api/printers` answer
   409 `module_off` and drops `printers` from `/api/info`; `sudo ./install.sh` with no flags asks nothing and
   keeps the same units (also in the custom mode); `modules enable printers` gives 200 again.
5. **Uninstall**: `sudo ./uninstall.sh` removes units, `/opt`, the wrapper, the drop-in, the udev rule and the
   station user and keeps `/etc/filament-kit`, `/var/lib/filament-kit`, `/var/lib/spoolman`; `sudo ./install.sh`
   brings back the same mode, spool and paired device. `--purge` leaves no unit, file or user
   (`filament-kit`, `spoolman`, `filament-kit-station`).
6. **Clean up**: `sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target` (the
   station masked them), `rm -rf ~/fk-test`.

## Results, 2026-11-02 (filament-kit 0.2.0, branch `modules`)

All steps passed after the fixes below. Details: `.superpowers/sdd/2026-11-02-modules/task-7-report.md`.

- **Upgrade from 0.1.0** (an older test install was still on WSL): `sudo ./install.sh` with no flags asked
  nothing, left `config.json` without `modules` (server mode), kept the spools, key, certificate and paired
  devices, and every status line was OK.
- **server**: as expected; the only `FAIL` was `Anthropic key missing`, status exit 1.
- **station** (`--server 127.0.0.2`, accepted: validate only refuses 127.0.0.1, localhost and ::1): as expected.
  No speaker and no reader on WSL: the journal shows `scan beep: no speaker output found` and the reader retry
  every 5 s. A missing scale is not logged (as in filament-ops). brltty and ModemManager were not installed on
  this WSL, so nothing was removed; the sleep targets were masked.
- **all-in-one**: as expected. The eth0 request (172.21.246.152) timed out (curl exit 28): systemd's
  `IPAddressDeny=any` drops the packets before the station's own 403 check.
- **Switches, re-run, uninstall, purge**: as expected.

### Found and fixed

- `tools/make_release.sh` failed with "wheel has no filament_kit/library_data/index.json" although the file was
  there: `unzip -l | grep -q` under `set -o pipefail` fails when grep stops at the first match and unzip gets
  SIGPIPE. Now `grep ... >/dev/null` (test `test_release_no_grep_q_after_a_pipe`).
- `filament-kit status` never printed `station reader not seen`: the real station's `/state` always has a `tag`
  object; only its `nfc_id` is null before a tap. Now checks `tag.nfc_id` (tests with the real `/state` shape in
  `test_status_modules.py`).
- `modules disable` and `install.sh` failed at once with "Could not get lock /var/lib/dpkg/lock-frontend"
  while unattended-upgrades ran. Every `apt-get` now waits up to 5 minutes for the lock
  (`-o DPkg::Lock::Timeout=300`); checked on WSL by holding the lock for 20 s during `modules disable printers`.
- With the installer's output going to a file, apply's `==>` lines came after the output of the commands they
  announce (Python block-buffers a pipe). apply now flushes before every command.

### Harmless output to expect

- (Fixed in the final review: apply no longer asks systemd to disable a unit whose file is not installed, so
  `Failed to disable unit: Unit ... does not exist` no longer appears in `station` or `server` mode.)
- Turning modules off prints systemd's "The unit files have no installation config" note for the companion
  `.service` units of the timers and the build path.
- The station probes print `id: 'filament-kit-station': no such user`, `dpkg-query: package 'brltty' is not
  installed` and `not-found` (ModemManager) on a computer without them.
- The Android app was not built for this test (`dist/` tarball without `app/`).

# WSL integration test: web, remote, orders, Orca and migrate-ops

The merge-ops modules on one WSL install (Ubuntu 26.04, systemd, passwordless sudo, no USB). Nothing here runs
certbot or changes a firewall; the only contact with a live machine is the read-only export from the Spoolman
VM (`--no-secrets`; the bundle stays in WSL and is deleted at the end).

## Procedure

```
# Windows, Git Bash: the tarball without the Android app (PowerShell off PATH, so no keystore lookup)
PATH=$(echo "$PATH" | tr ':' '\n' | grep -vi powershell | paste -sd:) bash tools/make_release.sh

# WSL, in ~/t9 (copied from /mnt/c, never run from there)
sudo ./install.sh --mode all-in-one </dev/null      # no tty: no questions, no key (the key line FAILs)
# config.json: web.public_url https://fk-test.localhost/filament, remote.hostname fk-test.localhost,
# orders.file /var/lib/filament-kit/t9-orders.json (a one-item fixture, root:filament-kit 640)
python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > pp    # 600, never printed
#   typed into `sudo filament-kit web passphrase` through a pty (getpass reads the tty, not stdin)
sudo filament-kit modules enable web
sudo filament-kit modules enable orders
sudo filament-kit modules enable remote             # installs nginx + certbot; certbot is NOT run
sudo filament-kit web status
sudo nginx -t; sudo /usr/local/sbin/mcp-route ls; sudo filament-kit remote firewall
curl -sk --resolve fk-test.localhost:443:127.0.0.1 https://fk-test.localhost/filament/health
```

OAuth and MCP (a script with plain HTTP to `127.0.0.1:8101` for OAuth, then the `mcp` SDK's
`streamable_http_client` + `ClientSession`, `Host: fk-test.localhost`, run with `/opt/filament-kit/venv/bin/python`):
`/.well-known/oauth-authorization-server`, `/register` (Claude's callback; a foreign one must fail),
`/authorize` (PKCE S256), `/login` (GET, then POST with the passphrase and `Origin: https://fk-test.localhost`),
the callback's `code`, `/token`, then `tools/list` and `find_spools`. The same script signs in to the web app
(`POST /intake/login` with `Origin`; the cookie is `Secure`, so send it by hand over plain http) and posts a dry
run to `/intake/api/add`.

migrate-ops: `ssh spoolman-vm 'sudo bash -s -- --no-secrets -' < tools/export_ops.sh | wsl ... 'cat > ~/t9/ops-bundle.tar.gz'`
(umask 077). Set `tag_sources` to a local dummy first, so the migration keeps it and nothing in WSL calls the
live tag reader afterwards (`station.url` is already the local station). Then `migrate-ops` dry (hash the data
folders before and after), `--apply`, and `--apply` again.

Orca: `sudo filament-kit pair --pc`; pc-sync's own `fksync.client.Client` with that link uploads the server
tests' fixtures (`test_builds.system_zip()`, `test_builds_orca.orca_system_zip()`, a one-file live and Orca live
zip) through `PUT /api/sync/system|live[?target=orca]`, asks `POST /api/sync/rebuild` with both live hashes,
waits for the build, downloads it and reports `installed` with `["base", "orca"]`.

Uninstall: `sudo ./uninstall.sh`, then `echo purge | sudo ./uninstall.sh --purge`. Clean-up afterwards:
`apt-get purge nginx nginx-common certbot` and the packages they pulled in; remove `/etc/mcp-router`,
`/usr/local/sbin/mcp-route`, `/usr/local/sbin/filament-kit-acme-hook`, `/etc/nginx` and `/etc/letsencrypt`;
`systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target`; delete `~/t9` (bundle,
passphrase file, token, logs).

## Results, 2026-11-02 (filament-kit 0.2.0, branch `mo-t9`)

- **Install** all-in-one: every line OK except `FAIL Anthropic key missing` (expected without a tty).
- **web**: `web passphrase` wrote `/etc/filament-kit/web_passphrase` root:filament-kit 640. `web status`: module
  on, public URL, passphrase set, `web unit answers on 127.0.0.1:8101`, printer slots `the kit's printer bridge`,
  tag readers `0 + station`.
- **remote**: nginx and certbot installed by the module; placeholder certificate `CN=fk-test.localhost` (30
  days); `nginx -t` ok; `mcp-route ls` gives `filament https://fk-test.localhost/filament/ -> 127.0.0.1:8101`;
  `remote firewall` prints 443 from Claude's ranges and the LAN, 80 "only while certbot runs", DNS, and the nginx
  hardening drop-in, and changes nothing. Through nginx: `/health` is `router ok`, `/filament/health` is `ok`,
  `/filament/intake` 200 over HTTP/1.1, a wrong Host is closed (444), `/filament/mcp` initialize with the token
  200 (event stream), without it 401; both `.well-known` forms answer 200. With `remote.acme_window` set, the
  certbot timer's next run is 03:10.
- **orders**: on with the fixture file.
- **OAuth**: metadata issuer `https://fk-test.localhost/filament`; DCR with a foreign callback 400
  `invalid_redirect_uri`, with Claude's 201; `/authorize` 302 to `/login`, 403 from outside the LAN
  (`X-Forwarded-For 203.0.113.9`); `/login` POST from another Origin 403, with the passphrase 302 to Claude's
  callback (state kept); `/token` 200 Bearer, 3600 s, with a refresh token; the code replayed 400 `invalid_grant`.
- **MCP**: no token 401; token with a foreign Origin 403; Host `127.0.0.1:8101` 421. With the SDK: server
  `filament-kit 0.2.0`, 14 tools (the 12 ops tools plus the `h2d_slots`/`h2d_set_slot` aliases);
  `find_spools("PLA")` gave 0 before the migration and 89 matches in 60 filaments after it.
- **Web app**: page 200 with CSP; a wrong passphrase 401; login 303 with `Secure; HttpOnly; SameSite=strict;
  Path=/filament/intake`; dry-run add `T9 Test PLA Basic Grey (new filament): 2 spool(s) @ Sealed stock ... dry
  run: nothing written`, and `find` shows nothing afterwards; the add without Origin 403; the API from outside
  the LAN 403.
- **migrate-ops** (bundle: 296 spools, 213 filaments, 39 vendors, 4518 preset files, no secrets): the dry run
  changed nothing but Spoolman's own `spoolman.log` (it logs the API reads). `--apply`: Spoolman 296/213/39,
  116 lines (all with an Orca parent, all keeping their Bambu Studio `filament_id`), `extra.line` on 35
  filaments, owner edits for 413 + 689 presets (7719 values), `[web] skipped` (no secrets), the keys set in
  this test (`web.public_url`, `remote.hostname`, `tag_sources`, `station.url`, `orders.file`) kept with the ops
  value shown, 11 keys set, the H2D model-only entry. The second `--apply` changed nothing. `spoolman.db` is
  spoolman:spoolman 640; all units active afterwards; `web status`: 1 connector signed in, 1 phone session,
  slots `slot_service`.
- **Orca** (the migrated lines with the fixture slicer stores): the system uploads hold 10 Bambu Studio and 17
  Orca presets; the build is ok with 59 `base/` and 186 `orca/` presets (each with its `.info`), for example
  `AMOLEN PLA Glow @H2D 0.4` and `@SV08 MAX 1.0`; no Orca preset has a `nil` value or a G-code key; `BUILD.json`
  carries the Orca live hash; 392 problems, all lines whose parents the small fixture stores do not have;
  `installed` with both trees is recorded.
- **Uninstall**: units, users (filament-kit, spoolman, filament-kit-station), the station drop-in and udev rule,
  the avahi file, `/opt`, the wrapper and (with `--purge`) all data are gone; after the fix below also the kit's
  router conf, route and deploy hook, and (purge) the certbot timer drop-in. nginx stays active with no 443
  listener.
- Linux-only tests: `test_migrate.py` 36 passed, 1 skipped (the wheel in a WSL venv, tests copied), including the
  WAL export with and without `--force`.

### Found and fixed

- `uninstall.sh` left the kit's nginx router conf, its `filament` route (pointing at the removed web unit) and
  its certbot deploy hook. It now removes them like `modules disable remote` (Ruling AF): only the kit's files,
  only routes `mcp-route` wrote; nginx, certbot, the certificate, `mcp-route` and other routes stay. `--purge`
  also removes the certbot timer drop-in. Test `test_uninstall_removes_the_kits_remote_files`; checked on WSL.

### Harmless output to expect

- `filament-kit web passphrase` reads the terminal (getpass); piping the passphrase into `sudo` hangs. Type it.
- `profiles status`: `N presets` counts the Bambu Studio presets; the Orca ones are `N Orca presets` beside it
  (since the final review fix C-I5).
- migrate-ops copies the order list to `/var/lib/filament-kit/filament_orders.json` even when `orders.file`
  points elsewhere (it is the path the runbook's exporter drop-in writes).
