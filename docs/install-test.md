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

- A first install in `station` mode prints `Failed to disable unit: Unit spoolman.service does not exist` (and
  the same for the other server units): apply turns off the units of every module that is off, installed or not.
- Turning modules off prints systemd's "The unit files have no installation config" note for the companion
  `.service` units of the timers and the build path.
- The station probes print `id: 'filament-kit-station': no such user`, `dpkg-query: package 'brltty' is not
  installed` and `not-found` (ModemManager) on a computer without them.
- The Android app was not built for this test (`dist/` tarball without `app/`).
