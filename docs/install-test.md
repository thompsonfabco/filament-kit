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
systemctl is-active spoolman filament-kit filament-kit-backup.timer   # active x3
sudo sh -c 'stat -c "%U:%G %a %n" /etc/filament-kit /etc/filament-kit/* /var/lib/filament-kit /var/lib/spoolman'
```

Expected modes: `/etc/filament-kit` root:filament-kit 2750; `config.json`, `anthropic_key`, `key.pem`
root:filament-kit 640; `cert.pem` root:filament-kit 644; `/var/lib/filament-kit` filament-kit:filament-kit
750; `/var/lib/spoolman` spoolman:spoolman 750.

The key must not appear anywhere it should not:

```
sudo journalctl -b | grep -c sk-ant- ; history | grep -c sk-ant-      # both 0
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
