# filament-kit server core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An installable Ubuntu server (Spoolman + `filament-kit` service) that pairs phones, reads label photos
with Claude, adds spools to Spoolman, links tags and places spools, with `status`/`config`/`pair` commands.

**Architecture:** Python package `filament_kit` under `server/`, one module per job (config, tags, placement,
spoolman client, inventory writes, intake/Claude, pairing, API, CLI), Starlette app on HTTPS :8710 behind a
self-signed cert. `install/install.sh` installs pinned upstream Spoolman and the service as systemd units. Code is
ported from the owner's working system and generalized through `config.json`.

**Tech Stack:** Python ≥ 3.12 (Ubuntu 24.04: 3.12, 26.04: 3.14), Starlette, uvicorn, python-multipart, anthropic
SDK, cryptography; pytest + httpx for tests; bash for the installer; Spoolman v0.27.0.

**Spec:** `docs/superpowers/specs/2026-11-01-filament-kit-design.md` (sections 3, 4 "Tags", 7, 8; build-order step 1).

## Global Constraints

- Ubuntu 24.04 / 26.04 LTS, native install (systemd, Python venvs), no Docker.
- Spoolman pinned at v0.27.0, own venv, systemd `spoolman`, port 7912, LAN-open web UI.
- `filament-kit` in `/opt/filament-kit`, own venv, own system user `filament-kit`, HTTPS port 8710, self-signed cert.
- Anthropic key: hidden input, stored `/etc/filament-kit/anthropic_key`, root:filament-kit 640, never echoed or logged.
- Config `/etc/filament-kit/config.json`; state `/var/lib/filament-kit/`; backups `/var/backups/filament-kit`, 14 days.
- mDNS service type `_filamentkit._tcp`.
- Daily Claude read cap default 60. Default model `claude-opus-5-5`.
- Tag UID format: `":".join(f"{b:x}" for b in uid)` (hex bytes, no padding), stored in Spoolman spool `extra.nfc_id` as a JSON string.
- Photos: JPEG only, ≤ 3 MB each, 1–8 per read.
- Writes: dry run → write → read back. A tag linked to another spool is refused unless `force`.
- No owner-specific values in code (no `printer-host`, `spoolman.home.arpa`, "Cereal Box", Amazon orders); they are config defaults or absent.
- Tests on the dev PC run in a Python 3.12 venv made with `uv venv --python 3.12 server/.venv`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Two phones adding opened spools at the same time must not get the same storage box → placement is computed inside the add, under a process-wide lock (test in Task 5).
2. A phone uploads HEIC/PNG or a 6 MB JPEG → clear 400 naming the file and the limit, no Claude call (test in Task 6).
3. Spoolman not up yet at boot or stopped → API answers 503 `{"error": "spoolman_unreachable", ...}` and `status` shows the fix, never a 500 trace (test in Task 8).
4. The server's DHCP address changes → the app must still trust it: the cert carries the hostname, `<hostname>.local` and current IPs as SANs, and pinning is by fingerprint, not by address (test in Task 7).
5. A tag tapped twice, or one already on another spool → second link is a no-op on the same spool; on a different spool it is refused naming that spool unless `force` (test in Task 5).

---

### Task 1: Package skeleton and config

**Files:**
- Create: `server/pyproject.toml`, `server/filament_kit/__init__.py`, `server/filament_kit/config.py`
- Test: `server/tests/test_config.py`

**Interfaces:**
- Produces: `filament_kit.__version__ = "0.1.0"`, `API_VERSION = 1`;
  `config.paths() -> Paths` (dataclass: `etc`, `state`, `backups`, `opt`; from env `FK_ETC`, `FK_STATE`, `FK_BACKUPS`, `FK_OPT`, defaults `/etc/filament-kit`, `/var/lib/filament-kit`, `/var/backups/filament-kit`, `/opt/filament-kit`);
  `config.load() -> dict` (defaults merged under the file); `config.save(cfg: dict) -> None` (atomic write, mode 640);
  `config.DEFAULTS` with keys: `server_name` (hostname), `spoolman_url` `"http://127.0.0.1:7912"`, `port` 8710,
  `model` `"claude-opus-5-5"`, `reads_per_day` 60, `locations` `["Sealed stock", "Rack 1", "Storage box", "Overflow"]`,
  `placement` `{"pla_location": "Rack 1", "box_prefix": "Storage box ", "box_count": 0, "overflow": "Overflow", "sealed_location": "Sealed stock"}`,
  `printers` `[]`, `library` `{"url": null, "schedule": "daily"}`.

- [ ] **Step 1: Write failing tests** — `test_defaults_when_no_file` (load() with empty `FK_ETC` dir equals DEFAULTS with server_name = `socket.gethostname()`); `test_file_overrides_and_nested_merge` (file `{"placement": {"box_count": 12}}` keeps the other placement keys); `test_save_is_atomic_and_640` (after save, no `.tmp` left, `stat.S_IMODE == 0o640` on POSIX, skipped on Windows); `test_unknown_keys_kept`.
- [ ] **Step 2: Run** `server/.venv/Scripts/python -m pytest server/tests/test_config.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `pyproject.toml` (name `filament-kit`, deps `starlette>=0.46`, `uvicorn>=0.34`, `python-multipart`, `anthropic>=0.80`, `cryptography>=44`; extras `test = ["pytest", "httpx"]`; console script `filament-kit = filament_kit.cli:main`), `__init__.py`, `config.py` (deep merge dicts one level down).
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `feat(server): package skeleton and config`.

### Task 2: Tag UIDs

**Files:** Create `server/filament_kit/tags.py`; Test `server/tests/test_tags.py`

**Interfaces:**
- Produces: `format_uid(uid: bytes) -> str`; `normalize_uid(text: str) -> str` (accepts `04:A2:0F`, `04a20f`, `4:a2:f`; returns the format_uid form; raises `ValueError` on non-hex or < 4 bytes); `stored(spool: dict) -> str | None` (decode `extra.nfc_id` JSON string; `""`/missing → None).

- [ ] **Step 1: Failing tests** — `format_uid(bytes.fromhex("0477900e092289")) == "4:77:90:e:9:22:89"`; `normalize_uid("04:77:90:0E:09:22:89") == "4:77:90:e:9:22:89"`; `normalize_uid("047790") ` raises (3 bytes); `stored({"extra": {"nfc_id": "\"4:77:90:e:9:22:89\""}}) == "4:77:90:e:9:22:89"`; `stored({"extra": {"nfc_id": "\"\""}}) is None`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(server): tag uid formatting`.

### Task 3: Placement

**Files:** Create `server/filament_kit/placement.py`; Test `server/tests/test_placement.py`

**Interfaces:**
- Consumes: placement dict from `config.load()["placement"]`.
- Produces: `place(items: list[dict], used: set[str], rules: dict) -> list[dict]` — items with `sealed` not False or with a `location` pass through; opened items: material starting `PLA` (case-insensitive) → `pla_location`; others → lowest free `f"{box_prefix}{n:02d}"` for n in 1..`box_count`, one per spool (an item with `count` N becomes N items of count 1), then `overflow`. `box_count` 0 → straight to `overflow`. Sealed items without location → `sealed_location`. Does not mutate inputs.

- [ ] **Step 1: Failing tests** — PLA opened → "Rack 1"; PETG opened count 3 with boxes 01 used and box_count 3 → locations "Storage box 02", "Storage box 03", "Overflow" (three items, count 1 each); box_count 0 → "Overflow"; sealed item → "Sealed stock"; given location kept; input list unchanged.
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(server): storage placement rules`.

### Task 4: Spoolman client and fake

**Files:** Create `server/filament_kit/spoolman.py`, `server/tests/fakes/spoolman_fake.py`; Test `server/tests/test_spoolman.py`

**Interfaces:**
- Produces: `class SpoolmanError(Exception)` (attr `status: int | None`); `class Spoolman(base_url: str, timeout: float = 15)` with `get(path) -> Any`, `post(path, body) -> Any`, `patch(path, body) -> Any`, `ping() -> str` (returns version from `/api/v1/info`), `ensure_fields() -> list[str]` (creates missing extra fields, returns names created). Paths are relative to `/api/v1`. Connection failures raise `SpoolmanError(status=None, "spoolman_unreachable")`.
- Extra fields (Spoolman `POST /field/{entity}/{key}`): spool `nfc_id` (text), `prev_location` (text); filament `nozzle_range` (text), `bed_range` (text), `line` (text).
- Fake: `spoolman_fake.app()` — a Starlette app holding vendors/filaments/spools/fields in memory, implementing the GET/POST/PATCH routes used here with Spoolman's response shapes (filament embeds `vendor`, spool embeds `filament`; `extra` values are JSON strings). Tests serve it with `uvicorn` on a free port in a thread (fixture `spoolman_url` in `server/tests/conftest.py`).

- [ ] **Step 1: Failing tests** — `test_ping_returns_version`; `test_ensure_fields_idempotent` (first call returns the 5 names, second `[]`); `test_unreachable_raises` (port with nothing listening → `SpoolmanError` with `status is None`).
- [ ] **Step 2–4:** FAIL → implement client (urllib, JSON) and fake → PASS.
- [ ] **Step 5: Commit** `feat(server): spoolman client and test fake`.

### Task 5: Inventory writes (add, link, update, search)

**Files:** Create `server/filament_kit/inventory.py`; Test `server/tests/test_inventory.py`

**Interfaces:**
- Consumes: `Spoolman`, `placement.place`, `tags.normalize_uid`, `tags.stored`.
- Produces:
  - `SEALED_COMMENT = "SEALED - tag when opened"`
  - `add_spools(sm: Spoolman, items: list[dict], rules: dict, dry: bool) -> AddResult` — port of `add_spools.py` (item keys as documented there: vendor, name, material, color_hex, net, tare, density, nozzle, bed, nozzle_range, bed_range, lot, count, note, price_per_kg, price_line, location, sealed, gross, spool_note). Validates every item before writing (`gross` needs count 1 and gross > tare). Runs `place()` with the current used locations inside a module-level `threading.Lock`, then reads each new spool back and raises `RuntimeError` if one is missing. `AddResult` dataclass: `spool_ids: list[int]`, `lines: list[str]` (human-readable report), `dry: bool`.
  - `link_tag(sm, spool_id: int, uid: str, force: bool, dry: bool) -> LinkResult` — normalizes uid; same spool already has it → no-op; another spool has it → `TagConflict(other: dict)` unless force (force clears it there first); writes `extra.nfc_id` as `json.dumps(uid)`, stamps `first_used` if empty, drops `SEALED_COMMENT`, reads back and raises `RuntimeError("tag did not land")` if it differs.
  - `add_and_link(sm, items, rules, dry, uid: str | None) -> AddResult` — links only when exactly one opened spool was added.
  - `update_spool(sm, spool_id, *, gross: float | None = None, remaining: float | None = None, location: str | None = None, empty: bool = False, dry: bool) -> dict` (gross → remaining = gross − tare, refused below tare; empty → remaining 0 and `archived` true).
  - `find(sm, q: str, sealed_only: bool) -> list[dict]` (case-insensitive match on vendor + filament name + location + tag).
  - `by_tag(sm, uid) -> dict | None`.

- [ ] **Step 1: Failing tests** (against the fake): `test_add_new_vendor_and_filament`; `test_add_existing_filament_joins` (same vendor+name, case-insensitive, filament fields unchanged); `test_add_dry_run_writes_nothing`; `test_gross_requires_count_1`; `test_concurrent_adds_get_distinct_boxes` (two threads each add one opened PETG with box_count 2 → locations {"Storage box 01", "Storage box 02"}); `test_link_same_spool_twice_is_noop`; `test_link_conflict_refused_names_other_spool`; `test_link_force_moves_tag`; `test_add_and_link_only_single_opened`; `test_update_gross_below_tare_refused`; `test_find_by_tag`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(server): inventory writes`.

### Task 6: Label reading with Claude

**Files:** Create `server/filament_kit/intake.py`, `server/tests/data/read_response.json` (a recorded structured-output reply for two photos of one SUNLU PETG spool); Test `server/tests/test_intake.py`

**Interfaces:**
- Consumes: `Spoolman`, `config.paths()`, `config.load()`.
- Produces:
  - `RULES: str` — the owner's rules text from `C:\CODING\filament-ops\vm\intake.py` (`RULES`) with the "Orders:" paragraph and every mention of Amazon orders removed, and `order`, `price_per_kg`, `price_line` removed from the schema (prices are entered by hand in the app).
  - `SCHEMA: dict` — that file's `SCHEMA` minus those three properties.
  - `class ReadCap(path: Path, per_day: int)` with `take() -> None` (raises `CapReached`) — timestamps persisted in `state/reads.json` so the cap survives restarts.
  - `check_photos(photos: list[tuple[str, bytes]]) -> list[bytes]` — 1–8 photos, each JPEG (starts `FF D8 FF`) and ≤ 3 MB, else `PhotoError(message)` naming the file and limit.
  - `read_labels(sm, images: list[bytes], hint: str, tag_uid: str | None, client=None) -> dict` — builds the cached catalog block (vendors + filaments as in the owner's code), photos, tag note, user note; calls `client.beta.messages.create(model=cfg["model"], max_tokens=16000, system=RULES, output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}, ...)`; maps errors to `ReadError(code, message)` with codes `bad_key`, `rate_limited`, `unreachable`, `refused`, `truncated`, `api_error`; post-processes exactly as the owner's `_read_labels` (existing filament match, hex cleanup, count ≥ 1, single item + tag → sealed False); returns `{"items", "questions", "tag", "usage"}`. `client=None` → `anthropic.Anthropic(api_key=<key file>, timeout=180, max_retries=2)`.
  - Failed reads keep the photos: `state/failed/<read_id>/photo<i>.jpg` for 24 h; `retry(read_id) -> dict` re-runs them; files older than 24 h are deleted on each call.

- [ ] **Step 1: Failing tests** — `test_rejects_png_and_large` (PNG bytes → PhotoError mentions the filename; 3 MB + 1 byte → PhotoError mentions "3 MB"; 9 photos → PhotoError); `test_cap_persists` (per_day 2: take, take, new ReadCap on same file → CapReached); `test_read_maps_existing_filament` (fake client returns the recorded JSON; fake Spoolman holds that filament → item has `existing_filament_id`, exact vendor/name, `match` "existing filament F<id>"); `test_single_item_with_tag_is_opened`; `test_bad_key_maps_to_code` (fake client raises `anthropic.AuthenticationError` → ReadError code `bad_key`); `test_failed_read_kept_and_retry`; `test_rules_mention_no_orders` (`"Amazon" not in RULES and "order" not in SCHEMA["properties"]["items"]["items"]["properties"]`).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(server): label reading with Claude`.

### Task 7: Pairing and certificate

**Files:** Create `server/filament_kit/pairing.py`; Test `server/tests/test_pairing.py`

**Interfaces:**
- Consumes: `config.paths()`.
- Produces:
  - `make_cert(hostname: str, ips: list[str], dest: Path) -> str` — EC P-256 self-signed, 10-year validity, SANs: hostname, `<hostname>.local`, `localhost`, each IP; writes `cert.pem` / `key.pem` (key 600); returns SHA-256 fingerprint as lowercase hex without colons.
  - `fingerprint(cert_pem: bytes) -> str`.
  - `issue(device_hint: str = "") -> Pairing` — dataclass `token` (32 random bytes urlsafe), `code` (6 digits), `expires` (now + 600 s), `qr: str` = `f"fkit://pair?h={host}&p={port}&t={token}&fp={fp}"` with host = `server_name`. Stores only `sha256(token)` and the code in `state/devices.json` / `state/pending.json`.
  - `redeem_code(code: str) -> str` — returns a new token for a valid pending code; 5 wrong attempts per code or expiry → `PairingError`.
  - `check(token: str) -> str | None` — device id or None. `revoke(device_id: str) -> bool`; `devices() -> list[dict]` (id, name, paired, last_seen).

- [ ] **Step 1: Failing tests** — `test_cert_sans_include_host_local_and_ips` (parse with cryptography; SAN DNS names ⊇ {host, host.local, localhost}, IPs ⊇ given); `test_fingerprint_matches_pem`; `test_token_stored_hashed` (token string absent from state files); `test_code_redeem_once` (second redeem fails); `test_code_five_wrong_attempts_locks`; `test_code_expires` (monkeypatched time); `test_revoke`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(server): pairing tokens and self-signed cert`.

### Task 8: App API

**Files:** Create `server/filament_kit/api.py`, `server/filament_kit/__main__.py`; Test `server/tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `create_app(sm: Spoolman | None = None, claude=None) -> Starlette`; `__main__` runs uvicorn on `0.0.0.0:<port>` with `ssl_certfile`/`ssl_keyfile` from `etc/`.
- Routes (JSON; all but `/api/info`, `/api/pair` need `Authorization: Bearer <token>`; 401 otherwise):
  - `GET /api/info` → `{"name", "version", "api": 1, "apk_version"}`
  - `POST /api/pair` `{"code"}` → `{"token"}`
  - `POST /api/intake/read` multipart `photo` ×1–8, `hint`, `tag` → read result (`read_id` included)
  - `POST /api/intake/retry/{read_id}`
  - `POST /api/intake/add` `{"items", "dry_run", "tag"}` → `{"spool_ids", "lines", "dry"}`
  - `GET /api/tags/{uid}` → `{"spool": {...} | null}`
  - `POST /api/spools/{id}/link` `{"tag", "force", "dry_run"}`
  - `PATCH /api/spools/{id}` `{"gross"|"remaining"|"location"|"empty", "dry_run"}`
  - `GET /api/spools?q=&sealed=1`
  - `GET /api/locations`
  - `GET /app.apk` (file `opt/app/filament-kit.apk`, 404 when absent)
- Errors: `{"error": <code>, "message": <text>}` — 400 `bad_photo`/`bad_request`, 401 `unauthorized`, 409 `tag_conflict` (with `other_spool`), 429 `daily_cap`, 502 Claude codes, 503 `spoolman_unreachable`. No tracebacks in responses.

- [ ] **Step 1: Failing tests** (Starlette `TestClient`, fake Spoolman, fake Claude): `test_info_open_rest_needs_token`; `test_pair_then_call`; `test_read_rejects_heic_400`; `test_read_then_add_then_tag_lookup` (full flow, tag linked); `test_tag_conflict_409_names_spool`; `test_spoolman_down_503` (sm pointed at a dead port → 503 `spoolman_unreachable` on `/api/spools`); `test_cap_429`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(server): app API`.

### Task 9: CLI (status, pair, unpair, config)

**Files:** Create `server/filament_kit/cli.py`; Test `server/tests/test_cli.py`

**Interfaces:**
- Consumes: config, pairing, Spoolman, intake key path.
- Produces: `main(argv: list[str] | None = None) -> int` with subcommands:
  - `status` — checks, one line each `OK`/`FAIL` + fix: services active (`systemctl is-active spoolman filament-kit`, skipped when `FK_NO_SYSTEMD=1`), Spoolman ping, key file present and accepted (`client.models.list()` with 10 s timeout), cert present + fingerprint, paired devices count, reads used today. Exit 1 if any FAIL.
  - `pair` — prints QR (`qrencode -t ansiutf8 <payload>` when available, else the payload) and the 6-digit code with its expiry.
  - `unpair [device-id]` — lists devices without an argument.
  - `config` — numbered menu: `1` server name, `2` storage (submenu: `1` locations, `2` PLA rack, `3` box prefix, `4` box count, `5` overflow, `0` back), `3` Claude model and daily cap, `4` Anthropic key (hidden `getpass`, written 640, never printed), `0` save and exit. Printers and library entries are added in later plans. Writes via `config.save`, then `systemctl restart filament-kit` (skipped when `FK_NO_SYSTEMD=1`).
  - `cert`, `ensure-fields` — thin wrappers over `pairing.make_cert` and `Spoolman.ensure_fields` (used by the installer).
- [ ] **Step 1: Failing tests** — `test_status_reports_spoolman_down` (exit 1, output contains `FAIL` and `sudo systemctl start spoolman`); `test_pair_prints_code`; `test_config_menu_sets_box_count` (stdin `2\n4\n12\n0\n0\n` → config placement box_count 12); `test_key_never_printed` (set key via menu; captured stdout lacks it).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(server): status/pair/config CLI`.

### Task 10: Installer, services, backup, release tarball

**Files:**
- Create: `install/install.sh`, `install/uninstall.sh`, `install/systemd/spoolman.service`, `install/systemd/filament-kit.service`, `install/systemd/filament-kit-backup.service`, `install/systemd/filament-kit-backup.timer`, `install/avahi/filament-kit.service`, `tools/make_release.sh`, `.github/workflows/server.yml`, `README.md` (install steps for him), `docs/install-test.md`
- Test: `shellcheck install/*.sh tools/*.sh` (via `uvx shellcheck-py` on the dev PC) + the install test below.

**Interfaces:**
- Consumes: the package (wheel built by `make_release.sh`), `filament_kit.cli`, `pairing.make_cert`.
- Produces: release tarball `dist/filament-kit-<version>.tar.gz` containing `install.sh`, `uninstall.sh`, `install/`, the wheel, and `app/filament-kit.apk` when present.

`install.sh` (run as root; refuses otherwise; idempotent):
1. Check Ubuntu 24.04+ (`/etc/os-release`); `apt-get install -y python3-venv avahi-daemon qrencode curl unzip`.
2. Users `spoolman`, `filament-kit` (system, nologin).
3. Spoolman v0.27.0: download the release `spoolman.zip` from `https://github.com/Donkie/Spoolman/releases/download/v0.27.0/spoolman.zip` into `/opt/spoolman`, venv, `pip install -r requirements.txt`, data dir `/var/lib/spoolman` (env `SPOOLMAN_DIR_DATA`), unit runs `python -m uvicorn spoolman.main:app --host 0.0.0.0 --port 7912`. Skip download when the installed version matches.
4. filament-kit: venv `/opt/filament-kit/venv`, `pip install <wheel>`; copy APK to `/opt/filament-kit/app/`.
5. First install only: prompt server name (default hostname), storage defaults or custom (calls `filament-kit config` storage section), API key (`read -rs`, written with `install -m 640 -o root -g filament-kit /dev/stdin`).
6. `make_cert` via `filament-kit cert` if no cert (hostname + `hostname -I` IPs).
7. Units + avahi file installed; `systemctl enable --now spoolman`, wait for `/api/v1/info`, `filament-kit ensure-fields`, `enable --now filament-kit filament-kit-backup.timer`.
8. `filament-kit status`, then `filament-kit pair`.

Backup: daily timer; `sqlite3`-safe copy via Spoolman's data file (`.backup` with python `sqlite3`) + `/etc/filament-kit` + `/var/lib/filament-kit` → `/var/backups/filament-kit/<date>.tar.gz`, delete older than 14 days.

`filament-kit.service`: `User=filament-kit`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/filament-kit`, `ProtectHome=yes`, `NoNewPrivileges=yes`, `PrivateTmp=yes`, `CapabilityBoundingSet=`, `AmbientCapabilities=` (port 8710 needs none).

`uninstall.sh`: stop/disable units, remove units, `/opt/filament-kit`, `/opt/spoolman`; keep `/etc/filament-kit`, `/var/lib/*` unless `--purge`.

`filament-kit.service` also sets `IPAddressDeny=any` and `IPAddressAllow=localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 160.79.104.0/21 2607:6bc0::/48` (LAN ranges + Anthropic API).

- [ ] **Step 1: Write the scripts, units, README install section, and the CI workflow** (ubuntu-24.04 runner: `pip install ./server[test]`, `pytest server/tests`, `shellcheck`).
- [ ] **Step 2: Run** `uvx shellcheck-py install/*.sh tools/*.sh` → no findings; `bash tools/make_release.sh` → tarball listed.
- [ ] **Step 3: Install test** per `docs/install-test.md` on a disposable Ubuntu 26.04 host the owner names (`KIT_TEST_HOST`; ask the owner which host before running): fresh install → `filament-kit status` all OK; `curl -k https://<host>:8710/api/info` → version 0.1.0; `avahi-browse -rt _filamentkit._tcp` lists it; pair with the code, add a spool through the API with `dry_run` false using a test photo, confirm it in Spoolman's UI; re-run `install.sh` (upgrade) → data kept, no prompts; `uninstall.sh` → services gone, data kept.
- [ ] **Step 4: Commit** `feat: installer, services, backup, release tarball`.
