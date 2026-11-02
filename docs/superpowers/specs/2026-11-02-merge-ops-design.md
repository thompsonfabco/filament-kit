# Merging filament-ops into filament-kit (sub-projects 2-4): design

Date: 2026-11-02. Status: awaiting owner approval. Follows `2026-11-02-modules-design.md` (sub-project 1, merged).
Inputs: survey notes `explore-ops-server.md` and `explore-presets.md` (side-session notes folder).

## 1. Purpose and success

Everything the owner's filament-ops setup does today runs from filament-kit modules, so the Spoolman VM, the
station PC and the desktop run one product, and filament-ops is archived.

**Success:**
- claude.ai's connector keeps working at the same URL (`https://mcp.example.com/filament/mcp`) with the same
  tools, now served by filament-kit.
- The phone web intake app works at the same URL with the same flows.
- Orca Slicer (SV08 MAX + H2D) and Bambu Studio (H2D) presets come from filament-kit's generator, installed by the
  paired filament-kit sync tool.
- The Samba share, `fpsync` task, `filament-mcp` service and the station PC's old `intake-station` service are retired.
- A family kit install still upgrades with no questions and no change (every new module is off by default).

## 2. Decisions

| Topic | Decision | Why |
|---|---|---|
| Presets | Extend kit's `profiles/` with an **Orca target** and **printer profiles** (survey option 1); retire `gen.py`/`regen.py` | one data model, tests, transport; kit's profiles are already a port of the BS half |
| Value policy | Kit's: Spoolman authoritative (reported, not clamped), library clamps parent values | kit is the base; owner's Spoolman values are curated |
| Calibrated values | Migration carries flow ratio, pressure advance, max volumetric speed and temps from the live presets as owner edits | avoids losing old-preset calibration (ops `pick()` harvest is not ported) |
| MCP + web app | New module **`web`**: one process `filament-kit-web.service` on `127.0.0.1:<web.port>` (default 8101) serving `/mcp` (+OAuth), `/login`, `/health`, `/intake` (PWA) | the public, trusted-cert side; kit's :8710 stays for the Android app |
| Auth for `web` | Port ops OAuth 2.1 + DCR (Claude callbacks only) + scrypt passphrase + LAN-only `/authorize` `/login` `/intake` + cookie sessions, unchanged in behaviour; state `FK_STATE/web/oauth.json`, passphrase `/etc/filament-kit/web_passphrase` | proven design; migration keeps existing connector tokens valid |
| Shared state across processes | inventory add lock and the daily read cap become **file locks** (fcntl), like pairing | `web` and `server` both write Spoolman |
| Remote access | New module **`remote`**: nginx path router (`mcp-route`), certbot standalone with pre/post/deploy hooks; config `remote.hostname`, `remote.acme_window`. Never edits nftables/ufw/pfSense: prints the exact rules for the owner | firewall changes need the owner |
| Tag sources | Config `tag_sources`: list of `{name, url}` read like the station's `/last-tag` (SV08 lasttag :5002, station :5003); newest tap wins, 300 s freshness, `held` always fresh | generic replacement for hard-coded SV08/station URLs |
| Orders | Module **`orders`**: optional `orders.file` (JSON `{items:[{order,date,asin,title,qty,unit_price,seller}]}`) fed to label reading; the exporter stays with amazon-mcp | owner-specific source, generic interface |
| Slot service | Config `slot_service` `{state_url, set_url, token_file}` gives MCP tools `printer_slots`/`printer_set_slot`; when absent and `printers` is on, the same tools use kit's bridge | keeps "never connect to the H2D directly" for the owner |
| Spoolman on the VM | Owner's VM Spoolman is v0.27.0 = kit's pin: migrate its sqlite DB into the `spoolman` module's data dir | one managed Spoolman |
| Owner data | Placement, locations, tare hints become config (`placement`, `locations`, `intake.tare_hints`); MCP `instructions` built from config | no hard-coded owner values in code |

## 3. New and changed modules

| Module | Depends | Units | Default |
|---|---|---|---|
| `web` | `server` (in-process use of kit code, same user) | `filament-kit-web.service` | off |
| `remote` | `web` | nginx + certbot timer (packages `nginx certbot`) | off |
| `orders` | `ai_intake` | — | off |

Modes are unchanged (server/station/all-in-one); `web`, `remote`, `orders` are added by `modules enable`. A new
mode `owner` is not added (YAGNI): the owner's VM is `server` + `web` + `remote` + `orders`.

## 4. Components

### 4.1 Intake core (server/filament_kit: inventory.py, intake.py, spoolman.py, new tagsources.py)
- File locks for `inventory` and `ReadCap`.
- `open_spool`: `humidity` → `extra.box_humidity`, `extra.humidity_checked`; pick by filament (lowest-id SEALED
  spool); `remaining`; one-byte-apart tag warning. `ensure-fields` adds the two extra fields.
- `tagsources.latest()` → `{nfc_id, read_at, age_seconds, reader, held}`; `fresh_unknown_tag()`;
  `scale_weight()` from the station state (station url from `station.url`).
- Label reading: optional orders block + price rules when `orders` is on; `gross` from a fresh station weight for one
  opened item; fresh unknown tag forces `sealed=false`.

### 4.2 Web package (server/filament_kit/web/)
- `auth.py`: OAuth provider + store (port of ops `Provider`, `Store`), passphrase (scrypt n=2^15), lockout 5/600 s,
  `LanOnly` with `web.lan` CIDRs, cookie sessions.
- `mcp_tools.py`: tools `find_spools, add_spools, tag_state, open_spool, preset_status, list_lines, find_parents,
  add_filaments_to_line, add_line, generate, printer_slots, printer_set_slot` (same names/arguments as ops; the H2D
  tools are kept as aliases `h2d_slots`, `h2d_set_slot`). They call kit functions in-process.
- `intake_app.py` + `static/`: the ops SPA (3 tabs) on kit's functions; base path from `web.public_url`.
- `__main__.py`: uvicorn on 127.0.0.1, `proxy_headers` trusting 127.0.0.1 only; `TransportSecuritySettings` hosts
  = public host. Dependency `mcp>=2.3` as extra `[web]`.
- CLI: `filament-kit web passphrase` (root, hidden prompt, ≥12 chars), `web status`.

### 4.3 Presets: Orca target (server/filament_kit/profiles/, library, pc-sync)
- `Line.orca_parent` (+ source), lines.json v2 (reads v1). Library schema optional `orca_parent`.
- Config `slicer_printers`: non-Bambu printers `[{"name": "Sovol SV08 MAX", "slicer": "orca", "nozzles":
  ["0.4","0.6","1.0"], "label": "SV08 MAX" (optional, used in preset names), "compatible_printers": {"0.4":
  "Sovol SV08 MAX", "0.6": "Sovol SV08 MAX 0.6", "1.0": "Sovol SV08 MAX 1.0"} (optional)}]`; Bambu printers also
  get Orca presets when top-level `presets_orca` is true (nozzles from the Orca store minus 0.2, or
  `presets_orca_nozzles`). The Orca target is on only when one of these asks for Orca presets (amended 2026-11-02,
  Rulings W/X/Y).
- `profiles/orca.py`: Orca system store from a pc-sync upload (names, `@System` parents, setting ids), generator
  `_build_orca_preset` (inherits `"<parent> @System"`, `compatible_printers`, variants, never nil), output tree
  `orca/` beside `base/`; names `"<vendor> <product> @<printer> <nozzle>"` matching ops names for adoption.
- G-code rule for Orca: no `gcode` key unless equal to the live value.
- pc-sync: Orca folder discovery + `orca-slicer.exe` check, upload/install a second tree, per-target backups.

### 4.4 Remote module (install/remote/, apply actions)
- Ports `vm/router/*` (nginx router, route template, `mcp-route`) and `vm/etc/acme-hooks.sh`, parameterised by
  `remote.hostname`. certbot standalone with hooks; timer pinned to `remote.acme_window` if set.
- Prints required firewall/port-forward rules; never applies them.

### 4.5 Migration (sub-project 4): `filament-kit migrate-ops` (root)
Reads an ops export bundle (made by `tools/export_ops.sh` on the VM: lines.py, oauth.json, passphrase hash,
server.json, regen_config, filament_orders path, the installed preset snapshot, spoolman.db copy) and:
1. Spoolman DB into `/var/lib/spoolman` (services stopped, backup kept).
2. lines.py → lines.json (vendor/product, BS parent `user`, `orca_parent`; `extra.line` on filaments of the 15
   non-library lines), adopting existing `filament_id`s from the live presets.
3. Snapshot seeding + calibrated keys as owner edits (section 2).
4. OAuth store + passphrase hash → web module (same hashes, so connectors stay connected); `web.public_url`.
5. Config: placement/locations/tare hints, `tag_sources`, `slot_service`, `orders.file`.
Dry run by default; `--apply` writes. Tested on WSL with a copy of the VM bundle.

**Live cut-over runbook** (`docs/migrate-from-filament-ops.md`), executed only with the owner's go, one machine at a
time, each with a rollback step: VM (stop filament-mcp/regen/Spoolman → install kit server+web+remote+orders → migrate
→ same port 8101 so the nginx route is unchanged), station PC (kit station mode, remove old service), desktop (pair
pc-sync, retire fpsync task, then Samba). filament-ops archived after a week of normal use.

## 5. Security
- `web` listens on 127.0.0.1 only; LAN-only routes enforced in code; OAuth DCR limited to Claude callbacks;
  no secrets in logs; passphrase and key files root:filament-kit 640; oauth.json 600.
- `filament-kit-web.service`: same hardening as `filament-kit.service`, `IPAddressAllow` = localhost + LAN ranges +
  Anthropic (already in the kit allowlist).
- No firewall changes by any installer path.

## 6. Testing
- pytest per component (ported ops behaviour gets ported tests: OAuth rotation/replay, Origin, CSP, lockout, DCR
  limits; Orca output against fixtures from the owner's real Orca presets; migration against a fixture bundle).
- WSL: all-in-one + web + remote (self-signed hostname, certbot not run), MCP handshake with the SDK client, web
  intake login + dry-run add, Orca build from fixtures, `migrate-ops --apply` on a copy of the VM bundle.
- Not testable here: claude.ai connector over the internet, real certbot issuance, real slicers on Windows (pc-sync
  tests use fixtures), the live cut-over.
