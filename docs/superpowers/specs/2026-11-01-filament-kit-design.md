# filament-kit — design

Date: 2026-11-01. Status: approved in conversation, awaiting written-spec review.

## 1. Purpose

A packaged, self-installing version of the owner's filament system for a family member starting from nothing:
an Android phone app that scans spool tags, takes label photos and takes a weight; an Ubuntu server that has
Claude read the labels and adds the spools to Spoolman; a bridge to his Bambu printers that sets AMS slots from a
tag tap and deducts filament used; and Bambu Studio presets generated per product line, printer and nozzle and
synced to his PC.

**Success:** he installs the server from a GitHub release by running one script, pairs the phone by scanning a
QR code, adds a printer by typing its IP, serial and Access Code, and from then on: photos + tag + weight on the
phone put a correct spool in Spoolman; a tag tap + slot pick loads the right preset into that AMS slot; finished
prints are deducted automatically; matching presets appear in Bambu Studio without manual steps.

### Decided

| Topic | Decision |
|---|---|
| Server platform | Ubuntu 24.04 / 26.04 LTS, native install (systemd, Python venvs), no Docker |
| Claude | Calls Anthropic directly from his server with a new API key on the owner's account; key typed into the installer, stored root-only |
| Scope | Everything: intake, Bambu bridge, Bambu Studio presets + PC sync |
| Printers | Bambu X2D, X1-series, P1-series, all in **LAN mode** (Developer Mode where firmware requires it); no Bambu cloud/Handy for them |
| Slicer | Bambu Studio on a Windows PC |
| Distribution | GitHub releases: server tarball, APK, PC sync installer. Spec library in its own GitHub repo |
| Network | LAN only; printers on fixed IPs / DHCP reservations |
| Architecture | Approach A: upstream Spoolman + one new service `filament-kit` + native Android app + Windows sync tool |
| Owner's own setup | Untouched; filament-kit is a separate, generalized copy of the code |

### Assumed (correct if wrong)

- He installs by following written steps, without SSH help.
- His tags are NTAG21x stickers or spool chips readable by phone NFC; only the UID is used.
- The APK is sideloaded (no Play Store).

## 2. Components

Repo `filament-kit` (this repo):

```
server/         filament-kit service (Python)
  api.py        HTTPS app API (Starlette + uvicorn)
  pairing.py    tokens, QR payload, self-signed cert
  spoolman.py   Spoolman client
  intake.py     photo reading with Claude, add + link
  tags.py       tag lookup, linking, nfc2klipper-format UIDs
  placement.py  storage location rules
  bridge/       Bambu printers: mqtt.py, ams.py (enumeration + slot map), calibrate.py, usage.py, ftps.py
  profiles/     line builder, value sources, generator (from gen.py/spec.py/inapp.py), builds
  library.py    spec library load + scheduled update
  cli.py        `filament-kit status|config|pair|unpair|library ...`
install/        install.sh, systemd units, avahi service, uninstall.sh
android/        Kotlin + Jetpack Compose app
pc-sync/        Windows sync tool (from fpsync.py/install.py), packaged as .exe + installer
docs/
```

Separate repo `filament-library`: the spec library (section 6).

Each server module has one job and a small interface; `api.py` and `cli.py` are thin layers over the rest.
Code is ported from the owner's working system (`C:\CODING\filament-ops\vm\intake.py`,
`open_spool.py`, `gen.py`, `spec.py`, `inapp.py`, `install.py`, `fpsync.py`, and the H2D orchestrator and usage
tracker in `C:\CODING\h2d-filament-scanner`), with owner-specific locations, host names and H2D-only paths
replaced by configuration.

## 3. Server

### Install

`sudo ./install.sh` from the release tarball:

1. Installs Python, avahi, qrencode.
2. Installs upstream Spoolman at a pinned version in its own venv; `spoolman` systemd service on port 7912,
   web UI open on the LAN.
3. Installs `filament-kit` in `/opt/filament-kit` (own venv, own system user), systemd service on HTTPS
   port 8710, with a self-signed certificate.
4. Asks: Anthropic API key (hidden input, stored `/etc/filament-kit/anthropic_key`, root:filament-kit 640,
   never echoed or logged); server name; default storage locations or his own.
5. Advertises `_filamentkit._tcp` over mDNS.
6. Keeps the matching APK on the server for the app to download.
7. Prints a pairing QR code.

Re-running a newer `install.sh` upgrades in place, keeping config and data. `uninstall.sh` removes services and
code; data is kept unless `--purge`.

### Security

- QR payload `fkit://pair?h=<hostname>.local&p=<port>&t=<token>&fp=<sha256>&ip=<a>&ip=<b>...`: the host's own
  mDNS name (never the display name `server_name`, which is only shown in `/api/info` and `status`), port, pairing
  token, certificate SHA-256 fingerprint, plus one `ip=` per current LAN IPv4 (no loopback, no 169.254.x.x). The
  app pins that certificate.
- Manual host entry: app shows the fingerprint for confirmation, then asks for a 6-digit pairing code shown by
  `sudo filament-kit pair`.
- `sudo filament-kit pair` issues a new token/QR; `unpair` revokes a device. Tokens are stored hashed.
- Daily cap on Claude reads (default 60).
- Service hardening as on the owner's VM (ProtectSystem, NoNewPrivileges, IPAddressAllow = localhost, LAN,
  Anthropic API ranges, his printers).

### Configuration

`/etc/filament-kit/config.json`, edited through `sudo filament-kit config` (menu; he never edits JSON):
storage locations; placement rule (PLA → named rack, others → lowest free numbered box up to N, then an overflow
location); Claude model and daily cap; printers; library update schedule.

### Operations

- `sudo filament-kit status`: each service, Spoolman, Claude key, library version, each printer's state, last
  profile build, with a fix for anything failing.
- Nightly backup of Spoolman's database and filament-kit state to `/var/backups/filament-kit`, 14 days kept.

## 4. Android app

- Kotlin + Jetpack Compose, minSdk 29 (Android 10), compiled against API 37.
- **Pairing:** scan the installer's QR (ML Kit bundled barcode model, works without Google services); or pick
  a server found by NSD; or type host/IP (fingerprint confirm + pairing code). Settings can change or re-pair.
- **Home:** Add spools · Printers · Search · Add profile (a hand-entered spec for a line the library lacks;
  stored as a local addition, section 6). A tag tap anywhere opens that spool's card if known; if unknown,
  offers "link to a sealed spool" or "add as new".
- **Add spools:** 1–8 label photos (CameraX, resized to ~1600 px before upload) → optional tag tap → weight in
  grams or "Sealed" → Read (server returns proposed spools, nothing written) → he edits brand, material, color,
  count and the preset parent → Add (spools saved; tag linked for a single opened spool). Drafts are kept on
  the phone until sent successfully.
- **Spool card:** Load into printer (printer + slot from the live list) · Update weight · Move · Mark empty.
- **Tags:** NFC reader mode; UID formatted like nfc2klipper (`":".join(f"{b:x}")`, bytes in hex, no padding).
- **Printers:** every printer the server has detected or been given, each with a state dot. Tapping one opens
  its screen: live camera; state and stage, job name, progress, layer, time left + ETA, temperatures (nozzles,
  bed, chamber), every AMS slot with colour, type and its Spoolman spool, active HMS messages; controls
  Pause / Resume / Stop / chamber light (Stop asks twice). A detected printer that isn't set up yet offers
  "Add printer" (asks for its Access Code, which goes to the server and never stays on the phone).
- **Updates:** checks the server for a newer APK and offers to install it (needs "install unknown apps" once).
- **Debug builds:** a "simulate tag tap" control for the emulator.

## 5. Bambu bridge

### Finding and adding printers

Bambu printers announce themselves on the LAN (SSDP NOTIFY on UDP 2021: serial, model, name, IP, LAN/cloud).
The bridge listens and keeps a list of detected printers; an IP change is picked up automatically. A detected
printer is added from the app ("Add printer": Access Code) or `filament-kit config` → Printers (name, IP,
serial, Access Code, for printers that don't announce). Access Codes live in
`/var/lib/filament-kit/printers.json` (filament-kit 600), never on the phone. The bridge tests at once and
reports connected / wrong code / Developer Mode needed.

### Status

From the MQTT reports (deltas deep-merged onto the last full report; `pushall` on connect and after each
command): state, stage (named from `stg_cur`), job, progress, layer, time left, temperatures, AMS units and
slots (joined to Spoolman spools by `extra.active_tray`/location), HMS codes. `GET /api/printers` and
`GET /api/printers/{id}`; the app polls every 2 s while a printer screen is open.

### Controls

`POST /api/printers/{id}/command {action}` with `pause`, `resume`, `stop`, `light_on`, `light_off`; the bridge
waits for the printer's reply and returns it. Every command is logged with the paired device's id. Any paired
phone can control any printer (owner's choice, 2026-11-01).

### Camera relay

On demand, started by the first viewer and stopped 45 s after the last. X1-series, H2D/X2D (RTSPS on 322,
"LAN mode liveview" on): a loopback relay does the TLS and Digest auth, ffmpeg remuxes H.264 to HLS without
re-encoding (segments on tmpfs), served at `/api/printers/{id}/camera/index.m3u8`. P1/A1-series (JPEG stream on
TCP 6000): read frame by frame and served as MJPEG at `/api/printers/{id}/camera.mjpeg`. Both need the Bearer
token; the printer's entry says which kind it has. The Access Code is never on a command line. Ported from the
owner's H2D remote (`C:\CODING\h2d-filament-scanner\remote\remote.py`), proven on hardware.

### Connection

One local MQTT-over-TLS connection per printer (port 8883, user `bblp`, password = Access Code; publish
`device/<serial>/request`, subscribe `device/<serial>/report`). Reconnects with backoff. Per-printer state:
connected, offline, wrong code, Developer Mode needed, printing, idle.

### Slot mapping (automatic; runs when a printer is added and on demand)

1. Enumerate AMS units from the report: unit type (AMS, AMS 2 Pro, AMS HT, AMS lite if present), address
   (`ams_id`; HT units at 128+), slot count.
2. Save every slot's current setting (preset id, color, type).
3. For each slot in turn: write a test setting with a unique color via `ams_filament_setting`; confirm from the
   report which unit/slot changed. Ties each address to its Studio label (A1–A4, B1–B4, HT-A …) and its global
   slot number.
4. Restore every slot to its saved setting and confirm from the report.
5. **Calibration job:** build a 3MF whose `slice_info` declares one filament per slot and whose gcode is only
   comments and `M400` (no heating, homing, moves or `T` commands). Upload by FTPS, start with a print command
   whose `ams_mapping` the bridge chose (filament i → slot i), with bed leveling, flow, vibration calibration
   and timelapse off. Record how the printer reports the mapping and `tray_now`; compare with the 3MF metadata.
   That calibrates the slot decoding for usage tracking. Delete the 3MF afterwards; restore slots.
6. Save the map to `config.json`; the app's Printers screen uses its labels.

Only while the printer is idle. On any failure: restore what was changed, report what couldn't be confirmed.
A refused write is reported as "Developer Mode needed". If the calibration job is refused or its result is
inconsistent, usage tracking for that printer stays in **observe mode** (logs what it would deduct, writes
nothing) until a real multi-color print confirms the decoding, and status says why.

Optional "full slot test" (off by default, all slots must hold filament): the same job with one real `T`
change per slot, proving every slot feeds; costs a few grams of purge per slot.

### Loading a spool

Printer + slot picked in the app → `ams_filament_setting` with `tray_info_idx` = his own generated Bambu Studio
preset's `filament_id` for that line, printer and nozzle; color and type from Spoolman. **No matching preset →
refused, never a Generic preset.** Verified against the next report. Spoolman location becomes
"<printer> – AMS <label>"; the previous location is kept in `extra.prev_location`; the spool previously in that
slot returns to its previous location.

### Usage tracking

On print finish: fetch that job's 3MF by FTPS (name-based: `<subtask_name>[_plate_<n>].gcode.3mf` in `/` and
`/cache`; no MLSD), read grams per filament from `Metadata/slice_info.config`, scale by final `mc_percent` for
cancelled prints, map filaments to slots with the calibrated decoding, deduct from the spools in those slots.
Never settle a retained FINISH seen at startup. Every deduction is logged and can be undone from the app for
7 days.

### Prototype on the owner's H2D first

Before relying on the calibration job: confirm on the owner's H2D (idle, with the owner's OK for each job) that
LAN-mode firmware accepts an unsigned gcode-only job, whether it insists on heating or a plate check, and
whether it refuses a mapping to an empty slot. X2D slot numbering is treated as H2D-like until checked.

## 6. Profiles

### Lines

A line = brand + product (e.g. "SUNLU PETG HF"), all colors together. Created automatically when intake first
sees a new brand + product. Its Bambu system parent: the library's `bambu_parent` hint, else the brand's own
Bambu Studio system preset if one exists, else Bambu's preset for that material. Shown on the app's confirm
screen and editable. One preset per line × printer model × nozzle (models and nozzles from the bridge's printer
list). Every preset's notes end "Spoolman filament ids: …".

### Value sources, highest priority first

1. Spoolman data for that filament (label-read values or his edits).
2. His local additions (`/var/lib/filament-kit/library-local/`, via `filament-kit library add <file>` or the
   app's "add profile").
3. The shipped spec library.
4. The Bambu system parent preset.

Rules carried over: published ranges are bounds (clamp only values that did not come from his own edits; report
his values outside a range); never invent midpoints; never set `temperature_vitrification`; never write `nil`;
fan OFF → 0; hardened → `required_nozzle_HRC` 40; chamber only where the printer has one, capped at its maximum.

### Spec library

Repo `filament-library`: one JSON file per brand + product line, `schema/entry.schema.json`, `index.json`
(library version, per-entry sha256), validator and index builder. Seeded from the owner's 93 `specs.json`
entries; further collection directed by the owner in a separate session.

On the server, a systemd timer (daily, configurable) fetches `index.json` from GitHub, downloads changed entries,
validates them against the schema, swaps the library atomically (previous version kept for rollback), and
triggers a profile rebuild if anything changed. Local additions are never overwritten.
`sudo filament-kit library update` runs it now.

### PC sync (`filament-kit-sync`, Windows)

Packaged from `fpsync.py` + `install.py` as an `.exe` with an installer. Paired once with the same QR/pairing
code. Runs every 10 minutes from Task Scheduler; does nothing while Bambu Studio runs. Uploads his live Bambu
Studio user filament folder and the system preset folder for his printer models to the server over HTTPS;
installs a newer build only when it was built from those exact live presets, otherwise requests a rebuild.
In-app edits are kept and in-app deletions respected (`inapp.py` rules; >25% vanishing at once = app reset, not
deletions). Backs up before each install (last 5). Finds the Bambu Studio user folder itself, including the
Beta folder. Bambu Studio's cloud keeps ~100 filament presets; the rest stay local. Deleting presets is done in
the app, never on disk.

## 7. Error handling

- Server: startup checks feed `status`. Claude errors (bad key, rate limit, daily cap, timeout) each get their
  own message; after two failed reads the photos are kept 24 h for retry. Writes are dry-run → write → read back.
  A tag linked elsewhere is refused unless he confirms the move.
- Bridge: per-printer state; slot writes verified against the next report; failed writes reported as failed.
- Profiles: a failed build keeps the last good build installed; the error shows in `status` and the sync log.
- App: drafts survive restarts and dropped connections; a changed certificate fingerprint stops and asks;
  app/server version mismatch shows an update prompt.
- PC sync: never writes while Bambu Studio is open; backs up first; refuses stale builds.

## 8. Testing

- Server (pytest): tag-id formatting, placement, line builder, value-source priority, library update with
  checks and rollback, 3MF parsing, slot decoding; Claude calls against recorded responses.
- Bridge: a fake printer (local MQTT broker + FTPS server replaying reports and 3MFs captured from the owner's
  H2D) for enumeration, the slot test, the calibration job and usage tracking. Real-printer checks only on the
  owner's H2D, idle, with the owner's OK each time.
- Install: fresh Ubuntu 26.04 VM on the dev PC: install from tarball, upgrade over an existing install,
  uninstall.
- App: unit tests (API client, pairing, drafts); instrumented UI tests in the emulator against the test server:
  pair → add spools with a simulated tag and webcam photos → confirm → load into the fake printer.
- PC sync: against copies of a Bambu Studio user folder.
- CI: GitHub Actions runs server tests and builds APK + tarball + sync installer on tags; a release attaches all
  three.
- Not covered until real hardware: real NFC tags on a phone; his X2D/X1/P1 firmware behavior (reported by the
  bridge at runtime); his network's mDNS.

## 9. Build order

1. Server core: install, Spoolman, pairing, intake, tags, placement, status/config CLI.
2. Android app against the server core, plus printers: discovery, connection, status, controls and camera
   (server and app together, owner's choice 2026-11-01).
3. Rest of the Bambu bridge (slot mapping, loading, usage tracking), starting with the H2D prototype checks.
4. Profiles, spec library updater, PC sync.

Each step gets its own implementation plan.

## 10. Dev environment (this PC)

JDK 21 (Temurin) at `G:\Android\jdk-21.0.13+9`; Android SDK at `G:\Android\Sdk` (platform-tools, build-tools
37.0.0, platform android-37.0, emulator, system image android-37.0 google_apis x86_64). Emulator acceleration
needs Windows Hypervisor Platform enabled (admin) and a reboot.
