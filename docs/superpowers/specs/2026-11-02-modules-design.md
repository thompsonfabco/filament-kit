# filament-kit modules, install modes and intake station — design

Date: 2026-11-02. Status: approved in conversation, awaiting written-spec review.
Sub-project 1 of merging filament-ops into filament-kit.

## 1. Purpose

The owner runs two filament systems: **filament-ops** (loose scripts on a hand-built Spoolman VM: remote MCP
server, phone web intake app, Orca + Bambu Studio preset generator, and a separate intake station PC with a USB
scale and a PN532 reader) and **filament-kit** (a packaged, tested, self-installing server with an Android app,
built for a family member). They become one product, with **filament-kit as the base**. filament-ops features
arrive as modules; filament-ops is retired once the owner's own machines run the merged product.

This sub-project builds the frame the rest hangs on: a module system, install modes chosen at install time and
changeable later with the config program, and the intake station as the first ported module.

**Success:** on a clean Ubuntu 24.04+/26.04 machine, `sudo ./install.sh` asks for a mode and installs exactly
that: a server, a station that serves a server elsewhere, or both on one machine talking over 127.0.0.1.
`sudo filament-kit config` → **Modules** switches modes or single modules later, with the same result as a fresh
install in that mode. An existing family-member install upgrades with no questions and no change in behaviour.

### Decided

| Topic | Decision |
|---|---|
| Base | filament-kit (repo `C:\CODING\filament-kit`); filament-ops is ported in over sub-projects 1-4 |
| Name | stays "filament-kit" |
| Spoolman | not in the package: fetched by the installer (pinned release + SHA-256, as today) when the module is on |
| Selection | modules, grouped into modes; chosen at install, changed later in `filament-kit config` |
| One code path | install and config both end in `filament-kit modules apply` |
| Firewall | no nftables/ufw changes in this sub-project; systemd `IPAddressAllow` only, never wider than today |
| Station source | filament-ops `station/` **after** the scan-beep / button-panel work there lands (another session is editing it) |

### Later sub-projects (not here)

2. Remote MCP server + OAuth, the phone web intake app, HTTPS (nginx router + certbot), as modules.
3. Reconcile overlaps: Orca preset generator next to the Bambu Studio one, intake placement rules + order
   matching, PC sync (fpsync/Samba vs the paired sync tool), the owner's SV08 MAX and H2D add-ons; use station
   tag + weight in the intake flows.
4. Move the owner's Spoolman VM and station PC to the merged product; archive filament-ops.

## 2. Modules

`server/filament_kit/modules.py` is the single registry. Each module:

```python
Module(name, title, description, units=[...], timers=[...], depends=[...], apt=[...], extra=None)
```

| Module | What it does | Units | Depends | apt |
|---|---|---|---|---|
| `spoolman` | Spoolman, fetched to `/opt/spoolman`, data `/var/lib/spoolman` | `spoolman.service` | — | `unzip` |
| `server` | The app server: pairing, inventory, API, avahi announcement | `filament-kit.service` | Spoolman, local module or a remote `spoolman_url` | `avahi-daemon qrencode` |
| `ai_intake` | Claude label reading (`/api/intake/*`), the API key | — (in `server`) | `server` | — |
| `printers` | Bambu bridge: discovery, MQTT, usage, slot mapping, camera | — (in `server`) | `server` | `ffmpeg` |
| `presets` | Bambu Studio preset builds + PC sync endpoints | `filament-kit-build.path` | `server` | — |
| `library` | daily spec-library update | `filament-kit-library.timer` | — | — |
| `backup` | nightly backup (Spoolman db when local, settings, state) | `filament-kit-backup.timer` | — | — |
| `station` | USB scale + PN532 reader, read-only HTTP :5003 | `filament-kit-station.service` | — | `alsa-utils` |

- `server` with `spoolman` off needs `spoolman_url` set to a reachable Spoolman; apply refuses otherwise.
- A module whose dependency is off cannot be turned on; turning a dependency off asks to turn its dependents off
  too (config) or fails (non-interactive apply).
- `config.json` gains `"modules": {"spoolman": true, ...}`. Missing key = the **server** mode (section 3), which is
  exactly today's kit, so existing installs keep working.

### Behaviour when off

- Units/timers of an off module are disabled and stopped. Data is never deleted (uninstall `--purge` still does).
- `server` process (`__main__.py`): `printers` off → no Manager, discovery listener, usage tracker, camera hub or
  mapper. Routes of an off module answer `409 {"error": "module_off", "module": "<name>"}`. `/api/info` adds
  `"modules": [...on...]` so the app can hide tabs later (the app change itself is not in this sub-project; it
  already shows unknown errors as a message).
- `filament-kit status` checks only modules that are on (no key check without `ai_intake`, no Spoolman service
  check when Spoolman is remote, station reachability when `station.url` is set).

## 3. Modes

A mode is a named module set; the config program shows "custom" when the set matches no mode.

| Mode | Modules on | Station settings |
|---|---|---|
| **server** (default, today's kit) | spoolman, server, ai_intake, printers, presets, library, backup | `station.url` unset |
| **station** (client) | station | `station.allow` = the server's address, asked at install |
| **all-in-one** | all | `station.allow = ["127.0.0.1"]`, `station.url = "http://127.0.0.1:5003"` |
| **custom** | chosen one by one | asked when `station` is on |

Settings in `config.json`:

```json
"station": {"url": null, "allow": ["127.0.0.1"], "port": 5003, "nfc_device": "auto",
            "beep": true, "beep_device": ""}
```

`station.url` is where the server reads a station (local or another machine); `station.allow` is who the local
station answers. Station-only mode keeps a minimal `config.json` (modules + station) and needs no key,
certificate or Spoolman.

## 4. Install and config flow

### `install.sh` (bootstrap)

1. Checks (root, Ubuntu ≥ 24.04), `apt-get install python3-venv curl`.
2. Service users `filament-kit` (and `spoolman`, `filament-kit-station` only when needed — created by apply).
3. venv + wheel (with the `[station]` extra, so any mode can be switched on later without a re-download of the
   tarball), `/usr/local/bin/filament-kit` wrapper, backup script.
4. First install, interactive: "Install mode: 1) server 2) station 3) all-in-one 4) custom [1]". Station mode
   asks the server's address. Non-interactive first install: `--mode <name>` (default `server`).
   Upgrade: no questions; a config without `modules` keeps the server mode.
5. `filament-kit modules apply` does the rest; the old steps 3 and 5-8 move into it.

### `filament-kit modules apply` (root, idempotent)

Plans then executes, so tests check the plan without a system:

1. Resolve and validate the module set (dependencies, `spoolman_url` when Spoolman is remote).
2. apt packages for the modules that are on (missing ones only).
3. Per module, in order spoolman → server → presets/library/backup → station:
   - **spoolman**: `install/spoolman.sh` (the current fetch-verify-swap step, moved verbatim), unit, wait for
     `/api/v1/info`, `ensure-fields`.
   - **server**: first-run questions that belong to it (display name, storage; key only if `ai_intake` is on and
     the key is missing and a terminal is attached), certificate (created once), avahi file, unit restart.
   - **presets / library / backup**: units and timers; first preset build as today (failure never stops apply).
   - **station**: section 5.
4. Disable + stop units of modules that are off.
5. `daemon-reload` once, then status for the modules that are on.

Other subcommands: `modules list` (name, on/off, description), `modules set <mode>`, `modules enable|disable
<name>` (each saves config then applies).

### `filament-kit config` → Modules

New menu item 6 **Modules**: shows the current mode and each module on/off; choose a mode or toggle a module,
answer that module's questions (station allow/url), then save → `modules apply`. The wrapper runs `config` as
root already.

### `uninstall.sh`

Uses `modules.py`'s unit list (all modules), removes the station user, udev rule and drop-in too; `--purge` as today.

## 5. Station module

### Code

- `filament-ops/station/intake_station.py` (final version with the button panel and scan beep) →
  `server/filament_kit/station/` (`__main__.py` entry, `scale.py` HID report parsing, `nfc.py` reader loop,
  `panel.py`, `beep.py`, `http.py`). Behaviour, endpoints (`GET /state`, `GET /last-tag`) and response shapes stay
  identical, so the owner's filament-mcp keeps reading a kit station unchanged.
- Tag ids use `tags.format_uid` (same format as nfc2klipper and the kit app).
- Settings come from environment variables as today (`STATION_ALLOW`, `STATION_PORT`, `NFC_DEVICE`,
  `STATION_BEEP`, `STATION_BEEP_DEVICE`); apply writes them from `config.json` into a drop-in, so the station never
  reads `/etc/filament-kit`.
- `nfcpy==1.0.4` (and pyserial for the panel) as extra `[station]`.
- The panel firmware (`panel/`, PlatformIO) and `PANEL.md` move to `station/panel/` in the repo, not the wheel.

### Service

`filament-kit-station.service`: user `filament-kit-station` (system, no home), `SupplementaryGroups=dialout audio`,
`ExecStart=/opt/filament-kit/venv/bin/python -I -m filament_kit.station`, `Restart=always`, `ProtectSystem=strict`,
`ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, empty capability set, `IPAddressDeny=any`.
Drop-in `/etc/systemd/system/filament-kit-station.service.d/kit.conf` written by apply:

```
[Service]
Environment=STATION_ALLOW=127.0.0.1 ... STATION_PORT=5003 NFC_DEVICE=auto STATION_BEEP=1
IPAddressAllow=localhost <each station.allow address>
```

All-in-one: localhost only. Station mode: localhost + the server address — narrower than the current station's
`192.168.1.0/24`. The server may be given by name (`spoolman.home.arpa`); `config.json` keeps the name and apply
resolves it to addresses for the drop-in (systemd and the station both match client IPs), printing what it used.
Re-running apply picks up an address change.

### Hardware handling (from station_setup.sh, done by apply when `station` is on)

- udev rule `99-filament-kit-station.rules`: DYMO hidraw (vendor 0922) → group `filament-kit-station`, 0640;
  `udevadm control --reload; udevadm trigger --subsystem-match=hidraw`.
- Remove `brltty` (claims CH340 adapters as braille displays).
- Disable ModemManager (probes new USB serial ports).
- Mask sleep/suspend/hibernate/hybrid-sleep (an idle GNOME desktop suspends and the station stops answering).
- Unmute analog outputs at 80% and `alsactl store` (scan beep).

These are not undone when the module is turned off (they are system changes the owner chose); apply prints that.

### Server side

- `GET /api/station` (paired devices only): the station's `/state` as-is, or `503 station_unreachable`; 60 s
  back-off after a failure, as filament-mcp does. `409 module_off` when `station.url` is unset.
- Status line: station answering at `station.url`, reader and scale seen (from `/state`).

## 6. Error handling

- apply stops at the first failing step with the step's name and a `fix:` line, as status does; re-running
  continues (each step is idempotent).
- A station without reader or scale runs and logs (as today); status shows "reader not seen" / "scale not seen".
- Mode change from all-in-one to server leaves the station's data-free system changes in place (see above).

## 7. Testing

- **pytest** (existing fakes, `FK_NO_SYSTEMD=1`):
  - registry: dependencies, mode resolution, "custom" detection, missing `modules` → server mode;
  - apply plan for every mode change (fresh, server→all-in-one, all-in-one→station, station→server), including the
    drop-in content and that IPAddressAllow never contains a range;
  - routes answer `module_off`; `__main__` builds no bridge with `printers` off; `/api/station` proxy + back-off;
  - station: scale report parsing (stable/moving, g/oz/lb, signed exponent) from captured reports and a fake
    hidraw, `/state` + `/last-tag` shapes, ALLOW refusal, panel HELLO detection with a fake serial port.
- **WSL Ubuntu 26.04** (`wsl -d Ubuntu`, systemd, no USB): fresh install in each mode from a built tarball;
  switch modes via `modules set`; re-run install; uninstall and `--purge`. In all-in-one the station answers
  `curl 127.0.0.1:5003/state` and refuses another address; status shows reader/scale not seen.
- **Not tested here:** the real DYMO, PN532 and panel. The owner's station PC is moved in sub-project 4.
- The family member's install, the owner's VM and the station PC are not touched.

## 8. Build order

1. `modules.py` registry + config `modules`/`station` keys + mode resolution (tests).
2. `modules apply` planner + executor; move install steps into it; `install/spoolman.sh`; slim `install.sh`.
3. Server gating (`__main__`, routes, `/api/info`, status).
4. Station package + unit + udev + drop-in; `/api/station`.
5. config Modules menu, `modules` subcommands, uninstall.
6. README: modes, Modules menu, station hardware notes; WSL install test notes in `docs/install-test.md`.
