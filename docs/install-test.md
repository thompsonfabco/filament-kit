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
sudo ./install.sh          # Enter for name, Enter for storage defaults, paste the key
```

Expect: the installer ends with `filament-kit status` (all lines `OK`) and a QR code + 6-digit pairing code.
Note the code.

Checks on the host:

```
sudo filament-kit status; echo "exit=$?"                     # every line OK, exit=0
systemctl is-active spoolman filament-kit filament-kit-backup.timer   # active x3
sudo stat -c '%U:%G %a %n' /etc/filament-kit /etc/filament-kit/* /var/lib/filament-kit /var/lib/spoolman
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
curl -k https://KIT_TEST_HOST:8710/api/info          # {"name": ..., "version": "0.1.0", "api": 1, ...}
avahi-browse -rt _filamentkit._tcp                   # lists "filament-kit on <host>", port 8710
curl -s http://KIT_TEST_HOST:7912/api/v1/info        # Spoolman version 0.27.0
```

## 3. Pair and add a spool through the API

Use the pairing code from step 1 (or `sudo filament-kit pair` for a new one):

```
H=https://KIT_TEST_HOST:8710
TOKEN=$(curl -sk -X POST $H/api/pair -H 'Content-Type: application/json' \
  -d '{"code": "<6-digit code>"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -sk $H/api/intake/read -H "Authorization: Bearer $TOKEN" -F photo=@label.jpg > read.json
cat read.json                                        # proposed spool(s), read_id
```

Build the add body from the proposed items in `read.json` and add for real:

```
python3 -c 'import json; r=json.load(open("read.json")); print(json.dumps({"items": r["items"], "dry_run": False}))' > add.json
curl -sk $H/api/intake/add -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @add.json
```

Expect `{"spool_ids": [...], "dry": false, ...}`. Open `http://KIT_TEST_HOST:7912` in a browser and confirm
the spool is there with the right brand, material and colour.
(If the read result's field names differ from `items`, adjust the body to the shape Task 8 documents.)

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
