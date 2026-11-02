# filament-kit build stage 4: profiles, spec library updater, PC sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the owner's Bambu Studio filament presets on the server (one per line × printer model × nozzle, from Spoolman + local additions + the spec library + the Bambu system parent), keep the spec library up to date, sync presets to and from his Windows PC, and make `profiles.preset_for` real so loading a spool into an AMS slot works.

**Architecture:** A new server package `server/filament_kit/profiles/` (`bbl` system-preset store, `lines`, `values`, `inapp`, `generate`, `builds`, `index`) and module `library.py`, ported from the owner's `C:\CODING\filament-ops` (`gen.py`, `spec.py`, `inapp.py`, `install.py`, `fpsync.py`, `regen.py`) with every owner-specific path, user id and H2D-only rule replaced by data. Builds run as a oneshot systemd unit triggered by a request file. They write `state/profiles/builds/<stamp>/` and swap a pointer only after validation, so a failed build keeps the last good one. A Windows tool `pc-sync/` (stdlib-only Python, PyInstaller + Inno Setup) uploads the live Bambu Studio folders over the pinned HTTPS API. It installs a build only when that build was made from exactly those live presets. The app gains the line's Bambu parent on the confirm screen, "Add profile", and preset build status.

**Tech Stack:** Python 3.12 (stdlib zipfile/hashlib/urllib/http.client/ssl/ctypes), existing Starlette API + systemd units; PyInstaller 6.11.1 + Inno Setup 6 (CI, `windows-2022`); Kotlin/Compose app; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-01-filament-kit-design.md`: section 6 (Profiles: Lines, Value sources, Spec library, PC sync), section 7 (Profiles + PC sync error handling), section 8 (testing), section 9 step 4; sections 1–3 for context. Owner source to port (read only): `C:\CODING\filament-ops\{gen,spec,inapp,install,fpsync,regen,linesfile,lines}.py`. Library repo (read only): `C:\CODING\filament-library` (`schema/entry.schema.json`, `tools/fl.py`, `index.json`).

## Global Constraints

- **No Generic preset, ever, in a slot.** `tray_info_idx` is always a generated preset's own `filament_id` (`^P[0-9a-f]{7}$`, one per line). A Bambu system preset (Generic or brand) is only ever the *template* a preset is flattened from (`inherits: ""`). `preset_for` returns None rather than any system id. A `PresetRef` never carries None temps: `nozzle_temp_min`/`nozzle_temp_max` are ints taken from the preset's `nozzle_temperature_range_low/high`; a preset without both is dropped from the build with a problem line.
- **Carried-over rules (spec §6, `spec.py`):** published ranges are bounds; clamp only values that came from the Bambu parent; values from Spoolman or from his in-app edits are never changed: if they lie outside a range they are kept and reported. Never invent midpoints. Never set `temperature_vitrification`. Never write `"nil"`. Fan OFF → `fan_min_speed`/`fan_max_speed` `["0"]`. Hardened → `required_nozzle_HRC` `["40"]`. Chamber only on printers that have one, capped at that printer's maximum.
- **Value priority, highest first:** (1) Spoolman data for the line's filaments, (2) his local additions `/var/lib/filament-kit/library-local/`, (3) the shipped/updated spec library, (4) the Bambu system parent. His in-app edits (inapp rules) are applied on top of all four.
- **Notes:** every preset's `filament_notes` ends with the line `Spoolman filament ids: <ids ascending, ", "-joined>`.
- **Secrets:** pairing tokens, the Anthropic key and Access Codes are never logged, printed (except the pairing link/QR that `pair` shows by design), put on a command line, written into a URL, or sent to the library host. The PC sync stores its token encrypted with Windows DPAPI (CurrentUser). The PC sync checks the server's leaf certificate before it sends any `Authorization` header.
- **Owner's real Bambu Studio folders:** no test, tool or step may read or write `%APPDATA%\BambuStudio*` on this PC. PC-sync tests build fixture trees under `tmp_path`, and `pc-sync/tests/conftest.py` points `APPDATA`/`LOCALAPPDATA` at `tmp_path` for every test (autouse). Only `fksync/__main__.py` reads the real environment variables.
- **No real hardware, no outward actions:** no printer, no H2D, no push, no merge to main, no change to the filament-library repo (ruling R24). CI files are written and linted, not run.
- **State files:** atomic writes with `pairing._write_atomic(path, data, mode, state_owned=True)`; new state directories via `pairing.make_state_dir`; cross-process locks via `fcntl` like `registry._locked()` (no-op on Windows).
- **Server runtime dependencies:** none new. pc-sync runtime: stdlib only.
- **Tests run on Windows (dev PC) and Linux (CI/WSL):** use `pathlib`, no POSIX-only calls outside `fcntl` guards, no hard-coded `/`-rooted paths, and `newline="\n"` when writing preset files.
- **Commands:**
  - Server tests: `cd <wt> && PYTHONPATH=<wt>/server /c/CODING/filament-kit/server/.venv/Scripts/python.exe -m pytest -q server/tests/<files>`, where `<wt>` is the task's worktree, e.g. `/c/CODING/fk-wt/t1`. Full suite: the same command with `server/tests`.
  - PC-sync tests, one-time setup (run by the first pc-sync task): `C:/REA/bin/uv.cmd venv C:/CODING/filament-kit/pc-sync/.venv --python 3.12` then `C:/REA/bin/uv.cmd pip install --python C:/CODING/filament-kit/pc-sync/.venv/Scripts/python.exe pytest==8.3.4`. Run: `cd <wt> && PYTHONPATH=<wt>/pc-sync /c/CODING/filament-kit/pc-sync/.venv/Scripts/python.exe -m pytest -q pc-sync/tests`. Nothing else is installed on this PC: no Inno Setup, and PyInstaller only inside that venv (Task 14).
  - Android: `cd <wt>/android && JAVA_HOME=/g/Android/jdk-21.0.13+9 ANDROID_HOME=G:/Android/Sdk ./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug`.
  - Linux check: the controller runs the full server suite plus the pc-sync suite in WSL Ubuntu after each wave merge, as in bridge part 2.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### Decisions (the owner reviews these)

- **Decision: library distribution.** A snapshot of the library (`index.json`, `schema/`, `library/`) ships inside the server wheel as package data (`filament_kit/library_data/`). The daily updater fetches from `config["library"]["url"]`, which defaults to `https://raw.githubusercontent.com/thompsonfabco/filament-library/main/`. Reason: it works on his server with no GitHub token; updates start automatically once the owner makes the repo public or points `url` at a public mirror. Until then a 404/401 shows as a warning ("using bundled version N"), not a failure.
- **Decision: library validation.** The server uses its own port of `tools/fl.py` `validate` (schema_version 1), not a jsonschema dependency. If any downloaded entry or index row is invalid, the whole update is aborted and the current version kept. Local additions use relaxed rules: `sources`, `source_quality`, `conflicts`, `colors`, `updated` and `published_ranges` may be left out. Reason: no new dependency; a half-applied library is worse than a day-old one.
- **Decision: line identity.** A line is `(vendor, product)`, with product = the Spoolman filament's `extra.line` (the field already exists in `EXTRA_FIELDS`). Claude's label read gains a `line` field (the product line without colour). A filament with no `extra.line` takes the longest library product of the same vendor that prefixes its name, else its own name. `line_id = slug(vendor) + "--" + slug(product)` using the library's slug. Reason: Spoolman filament names carry the colour; the field was reserved for this.
- **Decision: Bambu parent steps.** (1) library `bambu_parent` if the uploaded system store has it; (2) brand = an instantiable system preset whose `filament_vendor` equals the vendor (casefold) and whose `filament_type` matches the line's Bambu type, where the base name minus its first word equals the product (normalized: casefold, alphanumerics only); otherwise the only such brand preset of that vendor and type, if there is exactly one; (3) material = `Generic <type>`. With no system store uploaded yet, the static `Generic <type>` is proposed and re-checked at build time. Reason: deterministic and data-driven; Generic is a template, never the slot id.
- **Decision: printers and nozzles.** Presets are built for every printer in the registry whose model maps to a Bambu printer name, configured or only detected, times every nozzle size for which a system parent exists (from its `compatible_printers`). 0.2 is skipped for abrasive (`-CF`/`-GF`) lines, and so is every size the library's `_not_supported` names. Reason: matches the owner's generator, and a nozzle swap never waits for a rebuild.
- **Decision: protected values and rule details.** Spoolman and in-app values are protected; local entries override library entries field by field. Fan OFF only when the published text is `0`, `0%` or `0 (off)` in any case; `0-30` style ranges clamp instead. Hardened when the material matches `-(CF|GF)\b|CF\d|GF\d`, or `_hardened_nozzle_required` does not start with "No". The library's `filament_max_volumetric_speed` caps only 0.4 mm presets. Chamber maximum: H2D / H2D Pro / H2S / H2C 65 °C, X2D 65 °C (assumed H2D-like until checked), X1E 60 °C, others none. Reason: `gen.py`'s `startswith("0")` would turn "0-30" into OFF; a published flow rate is a 0.4 mm figure unless it says otherwise.
- **Decision: notes order.** Summary line, manufacturer-spec block, `MARK` + his own note lines, then the `Spoolman filament ids:` line last. `inapp.user_notes` drops `Spoolman filament ids:` lines. Reason: the spec says notes *end* with the ids.
- **Decision: the PC never deletes on disk.** Presets no longer generated are listed in the sync log and in `/api/profiles/status` as "delete in Bambu Studio"; the PC sync does not remove them. Reason: spec §6, "Deleting presets is done in the app, never on disk" (`install.py` did remove unsynced ones; that is dropped).
- **Decision: one sync PC per server.** The first paired device that uploads becomes the sync PC. Another device's uploads, rebuild requests and installs get `409 other_pc`, until the first one is unpaired (`filament-kit unpair <id>`). Reason: one live folder and one installed snapshot keep the in-app rules exact.
- **Decision: build trigger and retention.** Anything that should cause a rebuild writes `state/profiles/rebuild-request`. `filament-kit-build.path` (PathModified) starts `filament-kit-build.service` (oneshot), which runs `filament-kit profiles build`; the builder rebuilds again (at most 3 times) if the request changed while it ran. The last 5 builds plus the installed one are kept. A build that skips some lines (no parent, no temps) is still a good build with problems listed; a build fails only on an exception, on a validation error, or when no system presets have been uploaded. Reason: the owner's proven `filament-regen.path` pattern; one bad line must not block every other line.
- **Decision: preset_for source.** It reads the last good build and finds the line by the filament's vendor + `extra.line` (falling back to the build's filament-id map), so a new colour of a line that is already built loads at once. `setting_id` = the live upload's `base/<name>.info` `setting_id` when present, else `""`. `tray_type` = the preset's `filament_type`, not the Spoolman material. Reason: this matches the owner's proven orchestrator (`server.py` `build_command`); the printer accepts only Bambu type names.
- **Decision: library timer.** `filament-kit-library.timer` runs daily (RandomizedDelaySec 1h, Persistent). The service runs `filament-kit library update --scheduled`, which skips unless `config.library.schedule` (`daily` | `weekly` | `off`) says it is due. The library service has no `IPAddressDeny` (GitHub's CDN ranges change) but is otherwise hardened like the main service, whose allowlist is unchanged. `library add <file>` is read by the root wrapper and piped on stdin. Reason: the schedule stays configurable without drop-in files; the service user cannot read files in his home folder.
- **Decision: PC pairing.** `filament-kit-sync pair` accepts either the `fkit://pair?...` link, which `sudo filament-kit pair --pc` prints as text (device name "pc"), or a host/IP. For a host it shows the certificate fingerprint for confirmation, then asks for the 6-digit code (`POST /api/pair`). The token is pasted or typed on stdin, never passed as an argument. Reason: a PC has no QR scanner; this mirrors the app's manual flow.
- **Decision: sync uploads.** The user filament folder (`*.json`/`*.info`, including `base/`) and the whole `system/BBL/filament` folder are each sent as a zip, but only when their tree hash differs from what the server reports. The live hash gating an install covers the user folder only. Limits: live zip ≤ 32 MiB, system zip ≤ 64 MiB, ≤ 20 000 entries, each file ≤ 4 MiB, uncompressed total ≤ 512 MiB. Reason: inheritance chains cross printer models, so the whole BBL folder is needed; a Bambu Studio update changing system presets must not block installs.
- **Decision: Bambu Studio folder choice.** From `%APPDATA%\BambuStudio` and `%APPDATA%\BambuStudioBeta`, take the root whose `BambuStudio.conf` is newest (falling back to the newest `user/*/filament` dir); within it, the `user/<id>` whose `filament` dir is newest. The choice can be pinned in the sync config (`variant`, `user_id`), and `status` prints it. Reason: the owner runs Beta; a family member runs stable; logged-out installs use `user/default`.
- **Decision: PC sync toolchain.** PyInstaller 6.11.1 `--onedir` with two executables from one spec: `filament-kit-sync.exe` (console: pair/status/run) and `filament-kit-sync-task.exe` (windowed, for Task Scheduler). Inno Setup 6 builds a per-user installer (`PrivilegesRequired=lowest`, `{localappdata}\Programs\filament-kit-sync`) that registers the scheduled task through `install_task.ps1` and runs `pair` at the end. CI builds it on `windows-2022`, installing Inno Setup with choco if `iscc` is missing. Reason: both tools are scriptable in CI with no admin rights for the user; onedir avoids onefile's temp-extraction antivirus false positives.
- **Decision: release.** The workflow runs on tags `v*`. It fails if the tag does not equal `__version__`. versionCode = MAJOR×10000 + MINOR×100 + PATCH. The APK is signed from repository secrets `FK_KEYSTORE_B64` + `FK_KEYSTORE_PASSWORD`, and the job fails without them (it never publishes an unsigned APK). Server and pc-sync versions are bumped to 0.2.0. Reason: phones only update over the same key; a tag-derived code never goes down.

## Sync and profiles API contract (binding for Tasks 7, 9, 12, 13)

All routes need the Bearer token (`_authed`). Errors are `{"error", "message", ...}`; new errors come from `profiles.errors.ProfileError(status, code, message, **extra)`.

| Route | Body | Success | Errors |
|---|---|---|---|
| `GET /api/sync/state` | — | `{owner: str\|null, you: str, user_id: str\|null, live_hash: str\|null, system_hash: str\|null, build: {stamp, live_hash, created, presets: int, problems: int}\|null, last_attempt: {at, ok, error}\|null, installed: {stamp, at}\|null, rebuild_requested: {at, live_hash}\|null}` | — |
| `PUT /api/sync/live?user_id=<[A-Za-z0-9_-]{1,64}>` | `application/zip` | `{live_hash}` | 400 `bad_zip`, 413 `too_large`, 409 `other_pc` |
| `PUT /api/sync/system` | `application/zip` | `{system_hash, presets: int}` | same |
| `POST /api/sync/rebuild` | `{live_hash}` | 202 `{requested: true}` | 409 `other_pc` |
| `GET /api/sync/build?stamp=<stamp>` | — | `application/zip`: `BUILD.json` + `base/<name>.json` + `base/<name>.info` | 404 `not_found` |
| `POST /api/sync/installed` | `{stamp}` | `{installed: {stamp, at}}` | 404 `not_found`, 409 `other_pc` |
| `GET /api/profiles/status` | — | `{lines: int, presets: int, build, last_attempt, installed, pc: {device_id, last_upload}\|null, library: {version, source: "bundled"\|"updated", local: int, last_check: {at, ok, error}\|null}, stale: [str], problems: [str (first 20)]}` | — |
| `GET /api/profiles/lines` | — | `{lines: [{line_id, vendor, product, material, bambu_parent, parent_source, spoolman_ids: [int], presets: int}]}` | — |
| `PATCH /api/profiles/lines/{line_id}` | `{bambu_parent}` | `{line: {...as above}}` (+ rebuild request) | 404 `not_found`, 400 `unknown_parent` (only when a system store is uploaded) |
| `GET /api/profiles/parents?material=<m>` | — | `{parents: [str], synced: bool}` | — |
| `POST /api/profiles/propose` | `{vendor, line, material}` | `{line_id, line, bambu_parent, parent_source, exists}` | 400 |
| `POST /api/library/local` | an entry JSON object | 201 `{entry, line_id}` (+ rebuild request) | 400 `invalid_entry` with `problems: [str]` |

Intake: every `POST /api/intake/read` item also carries `line`, `bambu_parent`, `parent_source`, `line_exists`; `POST /api/intake/add` items accept optional `line` and `bambu_parent` (text ≤ 100, no `@`).

Tree hash (server `builds.tree_hash` and pc-sync `treehash.tree_hash`, must agree): take every file under the root whose suffix casefolds to `.json` or `.info`, as a relative POSIX path; sort the paths as strings; for each, `h.update(path.encode("utf-8") + b"\0" + sha256(content).digest())`; the result is the `hexdigest()` of the sha256 `h`. A missing root gives `sha256(b"").hexdigest()`.

## Review Focus

1. **Hostile or broken upload zip** (a `../` or absolute name, a drive letter, a symlink entry, a zip bomb, 30 000 entries, a non-JSON file): the server refuses it (400/413) and writes nothing outside a temp dir; the previous live folder stays (test in Task 6).
2. **Bambu Studio starts while the sync is installing** (after the first "not running" check): the sync checks again right before the first write; if Studio is running, nothing is written (not even the backup), the run reports `studio_running`, and the next run retries (test in Task 11).
3. **Library update half-fails** (an entry 404s, a hash mismatches, or one entry is invalid, after other entries downloaded): no swap; `current.json` and the served library are unchanged; `last_check` records the error; rollback still restores the previous version (test in Task 1).
4. **Odd Spoolman data on a line** (nozzle temp `null`/`0`/`"215"`, density missing, `extra.line` an unparsable string, a material with no Bambu type): that line is built from the other sources or skipped with a problem line; the rest of the build is good; no preset contains `"nil"` or a system `filament_id` (test in Task 5).
5. **Two Bambu Studio installs or accounts** (both `BambuStudio` and `BambuStudioBeta`, a stale `user/default` next to a logged-in id): the newest is chosen as defined, `status` names it, and a pinned `variant`/`user_id` in the config wins (test in Task 10).

---

### Task 1: Spec library on the server (store, validation, update, rollback, local additions, CLI)

**Files:**
- Create: `server/filament_kit/library.py`, `server/filament_kit/library_data/` (snapshot: `index.json`, `schema/entry.schema.json`, `library/**`), `tools/sync_library_snapshot.py`, `server/tests/test_library.py`, `server/tests/test_cli_library.py`, `server/tests/data/library/` (a 3-entry fixture library: `index.json`, `library/sunlu/pla-plus-2-0.json`, `library/elegoo/petg-cf.json`, `library/bambu-lab/petg-hf.json`, built with the index rules below)
- Modify: `server/pyproject.toml` (`[tool.setuptools.package-data] filament_kit = ["library_data/*.json", "library_data/schema/*.json", "library_data/library/*/*.json"]`), `.gitattributes` (`server/filament_kit/library_data/** -text`, so hashes match), `server/filament_kit/config.py` (`DEFAULTS["library"] = {"url": None, "schedule": "daily"}`; `url` None means `DEFAULT_LIBRARY_URL`), `server/filament_kit/cli.py` (the `library` subcommands only)

**Interfaces:**
- Produces (module `filament_kit.library`):
  - `DEFAULT_LIBRARY_URL = "https://raw.githubusercontent.com/thompsonfabco/filament-library/main/"`
  - `slug(text: str) -> str` (exact port of `fl.slug`)
  - `rel_path(entry: dict) -> str`
  - `validate(entry: dict, *, local: bool = False) -> list[str]` (port of `fl.validate`; `local=True` relaxes as in the Decision)
  - `@dataclass Lookup(library: dict | None, local: dict | None)`
  - `class Library` with `version: int`, `source: str`, `lookup(vendor, product) -> Lookup` (casefold vendor + product, also matched by slug), `vendor_entries(vendor) -> list[dict]` (library and local, local wins on the same product), `local_count: int`
  - `load() -> Library` (state `library/current.json` → that version dir; else the bundled `library_data`; local entries from `paths().state / "library-local"`)
  - `add_local(data: bytes) -> tuple[dict, str]` (entry, line_id; `ValueError` listing the problems; written to `library-local/<vslug>/<pslug>.json`; fills `schema_version: 1`, `updated` today, `local: true` is NOT a schema key so it is never stored; local files are never touched by `update`)
  - `@dataclass UpdateResult(changed: bool, version: int, downloaded: int, error: str | None)`
  - `update(url: str | None = None, *, opener=urllib.request.urlopen, now: float | None = None) -> UpdateResult`
  - `due(cfg: dict, now: float) -> bool`
  - `rollback() -> int`
  - `status() -> dict` (`{version, source, local, url, last_check: {at, ok, error} | None}`)
  - `LibraryError(Exception)`
- Line id helper for Task 3: `line_id(vendor: str, product: str) -> str` = `slug(vendor) + "--" + slug(product)` (lives here, so it shares the slug).
- CLI: `filament-kit library status|update [--scheduled]|rollback|add <file or ->`. `update` and `add` call `filament_kit.profiles.builds.request_rebuild(reason)` when something changed. Task 6 provides that function: here import it lazily inside the command and, if the import fails (module not yet present), skip it with no error. Task 7 removes the guard.

Update algorithm (no swap unless every step passes): fetch `<url>index.json` (≤ 8 MiB, 30 s timeout). Require `schema_version == 1`, `library_version` an int ≥ the current one, and `entries` a list of ≤ 20 000 rows, each with a `path` matching `^library/[a-z0-9-]+/[a-z0-9-]+\.json$` and a 64-hex `sha256`. Build `state/library/versions/<version>-<stamp>.tmp/`. For each row, copy the current file when its sha matches, else download it (≤ 256 KiB). In both cases check the sha256 of the bytes, run `validate`, and require `rel_path(entry) == path`. Rename the tmp dir to its final name. Write `previous.json` = old `current.json`, then write `current.json` atomically. Delete version dirs other than current and previous. On any failure: remove the tmp dir, write `last_check.json` `{at, ok: false, error}`, and return `error`. A URL must be `https://`, except a `http://127.0.0.1:<port>/` or `http://localhost:<port>/` URL, which tests use. Errors carry the HTTP status and, for 401/403/404, the text "the library repository may be private; using version N".

- [ ] **Step 1: Copy the snapshot.** Write `tools/sync_library_snapshot.py --from <library checkout> [--to server/filament_kit/library_data]`: copy bytes exactly, validate every entry, check every index sha; exit 1 on any problem. Run it: `/c/CODING/filament-kit/server/.venv/Scripts/python.exe -I tools/sync_library_snapshot.py --from C:/CODING/filament-library`. Expected: `1023 entries copied, library_version 2`.
- [ ] **Step 2: Write the failing tests** (`test_library.py`; a `http.server` serving `tests/data/library` copied to `tmp_path` on 127.0.0.1; `FK_STATE` → `tmp_path`):

```python
def test_bundled_snapshot_is_valid_and_matches_index():  # every library_data entry validates, sha256 == index row
def test_load_without_state_uses_bundled():  # load().source == "bundled", version == bundled index library_version
def test_validate_port_matches_fl_rules():  # temperature_vitrification -> problem; "@BBL" in bambu_parent -> problem;
    # nozzle low 260 > high 240 -> problem; schema_version 2 -> problem; local=True without sources -> []
def test_update_downloads_only_changed(served):  # bump one entry + index; result.downloaded == 1, changed is True
def test_update_unchanged_is_noop(served):  # same index -> changed False, no new version dir
def test_update_hash_mismatch_keeps_current(served):  # served file bytes differ from index sha -> error, load().version unchanged,
    # no *.tmp dir left, status()["last_check"]["ok"] is False
def test_update_invalid_entry_aborts_everything(served):  # one invalid entry among 3 changed -> nothing swapped
def test_update_refuses_older_version(served):  # index library_version lower than current -> error "older"
def test_update_404_says_private():  # error contains "may be private" and "using version"
def test_update_rejects_plain_http_remote():  # "http://example.com/" -> LibraryError, opener never called
def test_rollback_restores_previous(served):  # update twice, rollback() == first version, lookup returns first content
def test_lookup_case_and_slug():  # lookup("sunlu", "PLA+ 2.0") finds "SUNLU" "PLA+ 2.0"; vendor_entries("SUNLU") lists it
def test_local_overrides_and_survives_update(served):  # add_local same line -> Lookup.local set; update -> local file untouched
def test_add_local_invalid_lists_problems():  # ValueError message contains each problem
def test_due_schedule():  # daily: due after 20 h since last ok check; weekly: after 6.5 days; off: never
```
`test_cli_library.py`: `library status` prints `library version 2 (bundled), 0 local additions`; `library add -` reads stdin; `library update --scheduled` with schedule `off` prints `library updates are off` and exits 0; the update error exits 1 and the message contains no URL query string.
- [ ] **Step 3: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_library.py server/tests/test_cli_library.py`. Expected: FAIL, `ModuleNotFoundError: filament_kit.library`.
- [ ] **Step 4: Implement** `library.py`, the config default and the CLI subcommands, with the signatures above.
- [ ] **Step 5: Run the tests to see them pass.** Then run the full server suite; expected: all pass.
- [ ] **Step 6: Commit.** Message: `feat(library): bundled spec library, validated updates with rollback, local additions`.

### Task 2: Profiles package, Bambu system preset store, printer names

**Files:**
- Create: `server/filament_kit/profiles/__init__.py` (`git mv server/filament_kit/profiles.py server/filament_kit/profiles/__init__.py`; contents unchanged in this task), `profiles/errors.py`, `profiles/bbl.py`, `server/tests/test_bbl.py`, `server/tests/data/bbl/filament/*.json` (hand-written fixtures, see Step 1)
- Modify: `server/filament_kit/bridge/models.py`, `server/tests/test_models.py` (create if absent)

**Interfaces:**
- Produces:
  - `profiles.errors.ProfileError(Exception)` with `__init__(self, status: int, code: str, message: str, **extra)` and attributes `status`, `code`, `message`, `extra`
  - `bbl.STD = "Direct Drive Standard"`, `bbl.HF = "Direct Drive High Flow"`
  - `bbl.merge(child: dict, parent: dict) -> dict` (exact port of `gen.merge`)
  - `class bbl.Store`:
    - `Store.load(folder: Path) -> Store` (recursive `*.json`; unreadable files go to `store.problems: list[str]`)
    - `names() -> set[str]`
    - `resolve(name) -> dict` (port of `gen.resolve_bs_system`: inherits chain, then `include` templates, then own keys; cached; a cycle or missing parent raises `BblError`)
    - `base_name(name) -> str` (text before `" @"`)
    - `bases(material: str | None = None) -> list[str]` (sorted bases of instantiable presets, `instantiation == "true"`, optionally `filament_type[0]` == material)
    - `vendor_bases(vendor: str, bs_type: str) -> list[str]`
    - `parent_for(base: str, printer: str, nozzle: str) -> str | None` (instantiable preset with that base whose resolved `compatible_printers` contains `f"{printer} {nozzle} nozzle"`; prefer a name ending `f" {nozzle} nozzle"`, then the shortest name)
    - `nozzles_for(base: str, printer: str) -> list[str]` (sizes parsed from matching `compatible_printers`, sorted numerically, formatted like `"0.4"`)
    - `variants(name) -> list[str]` (resolved `filament_extruder_variant`, default `[STD]`)
    - `gcode_values() -> set[str]` (json.dumps(sort_keys) of every value whose key contains "gcode")
  - `bbl.BblError(Exception)`
  - `models.printer_preset_name(model: str | None) -> str | None` (`"Bambu Lab " + display name`; codes and typed names as `camera_kind` accepts, with `X1C` → `X1 Carbon`, `A1MINI` → `A1 mini`, `H2DPRO` → `H2D Pro`; unknown → None)
  - `models.chamber_max(model: str | None) -> int | None` (values from the Decision)

- [ ] **Step 1: Write the fixtures** in `server/tests/data/bbl/filament/`, with every list value a string array as Bambu Studio writes them:
  - `fdm_filament_common.json`: `instantiation "false"`; `filament_type ["PLA"]`, `filament_vendor ["Generic"]`, `nozzle_temperature ["220"]`, `nozzle_temperature_initial_layer ["220"]`, `nozzle_temperature_range_low ["190"]`, `nozzle_temperature_range_high ["240"]`; the five plate temps and their `_initial_layer` keys `["60"]`; `filament_flow_ratio ["0.98"]`, `filament_max_volumetric_speed ["21"]`, `fan_min_speed ["100"]`, `fan_max_speed ["100"]`, `chamber_temperatures ["0"]`, `filament_density ["1.24"]`, `filament_cost ["20"]`, `filament_extruder_variant ["Direct Drive Standard"]`, `temperature_vitrification ["45"]`, `filament_start_gcode ["; filament start gcode\n"]`.
  - `fdm_filament_pla.json` and `fdm_filament_petg.json`: inherit common; PETG sets type PETG and range 230–260.
  - `fdm_include_retract.json`: `instantiation "false"`, `filament_retraction_length ["0.8"]`.
  - `Generic PLA @base.json`: inherits pla, `filament_id "GFL99"`.
  - `Generic PLA @BBL H2D.json`: inherits `@base`; `include ["fdm_include_retract"]`; variants STD+HF; `nozzle_temperature ["220","230"]`, `nozzle_temperature_initial_layer ["220","230"]`, `filament_flow_ratio ["0.98","0.98"]`, `filament_max_volumetric_speed ["21","35"]`; compatible H2D 0.4/0.6/0.8 nozzle; `instantiation "true"`.
  - `Generic PLA @BBL H2D 0.2 nozzle.json`: compatible H2D 0.2; MVS `["2","2"]`.
  - `Generic PLA @BBL X1C.json`: compatible `Bambu Lab X1 Carbon 0.4 nozzle`, `Bambu Lab X1 Carbon 0.6 nozzle`, `Bambu Lab P1S 0.4 nozzle`.
  - `Generic PETG @base.json` and `Generic PETG @BBL H2D.json`.
  - `Generic PLA-CF @BBL H2D.json`: type PLA-CF; compatible H2D 0.2/0.4/0.6.
  - `Generic TPU for AMS @BBL H2D.json`: type TPU-AMS.
  - `Bambu PLA Basic @BBL H2D.json`: `filament_vendor ["Bambu Lab"]`, `filament_id "GFA00"`.
  - `SUNLU PLA+ @BBL X1C.json`: `filament_vendor ["SUNLU"]`, type PLA.
  - `broken.json`: invalid JSON.
- [ ] **Step 2: Write the failing tests.**

```python
def test_resolve_chain_and_include(store):  # resolve("Generic PLA @BBL H2D")["filament_retraction_length"] == ["0.8"];
    # ["nozzle_temperature_range_low"] == ["190"]; ["nozzle_temperature"] == ["220","230"]
def test_broken_file_is_a_problem_not_a_crash(store):  # "broken.json" named in store.problems
def test_parent_for_prefers_nozzle_specific(store):  # parent_for("Generic PLA","Bambu Lab H2D","0.2") == "Generic PLA @BBL H2D 0.2 nozzle";
    # ("...","0.4") == "Generic PLA @BBL H2D"; ("Generic PLA","Bambu Lab P1S","0.6") is None
def test_nozzles_for(store):  # nozzles_for("Generic PLA","Bambu Lab H2D") == ["0.2","0.4","0.6","0.8"]
def test_bases_filters_instantiable(store):  # "Generic PLA" in bases("PLA"); "fdm_filament_pla" not in bases()
def test_cycle_raises():  # a fixture written to tmp_path where A inherits B and B inherits A -> BblError
def test_printer_preset_name():  # "O1D"->"Bambu Lab H2D", "BL-P001"->"Bambu Lab X1 Carbon", "X1C"->"Bambu Lab X1 Carbon",
    # "C12"->"Bambu Lab P1S", "N1"->"Bambu Lab A1 mini", "zz"->None
def test_chamber_max():  # "O1D"->65, "N6"->65, "C13"->60, "C12"->None
```
- [ ] **Step 3: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_bbl.py server/tests/test_models.py`. Expected: FAIL (no `profiles.bbl`).
- [ ] **Step 4: Implement** the package move, `errors.py`, `bbl.py` and the models functions. Every existing import of `filament_kit.profiles` keeps working.
- [ ] **Step 5: Run the tests to see them pass**, then the full suite; expected: pass. `test_loading.py` must still pass unchanged.
- [ ] **Step 6: Commit.** Message: `feat(profiles): package, Bambu Studio system preset store, printer names`.

### Task 3: Lines and the Bambu parent choice

**Files:**
- Create: `server/filament_kit/profiles/lines.py`, `server/tests/test_lines.py`

**Interfaces:**
- Consumes: `library.Library`, `library.line_id`, `library.slug`, `bbl.Store`
- Produces:
  - `@dataclass Line(line_id: str, vendor: str, product: str, material: str, bambu_parent: str | None, parent_source: str, filament_id: str, created: str)`, where `parent_source` is one of `"library" | "brand" | "material" | "user" | "none"`
  - `load() -> dict[str, Line]` and `save(lines: dict[str, Line]) -> None` (`state/profiles/lines.json`, atomic, state-owned)
  - `bs_type(material: str) -> str` (port of `BS_TYPE` + `BS_VALID` from `lines.py`/`gen.py`: mapped or upper-cased material; returned even when not in `BS_VALID`)
  - `choose_parent(vendor, product, material, *, library: Library, store: Store | None) -> tuple[str | None, str]` (steps from the Decision; with `store=None` the library hint is accepted as is, then `Generic <bs_type>`)
  - `propose(vendor, product, material, *, library, store, lines) -> dict` (`{line_id, line, bambu_parent, parent_source, exists}`)
  - `new_filament_id(used: set[str]) -> str` (`"P"` + 7 hex digits from `secrets`, not in `used`)
  - `ensure(lines, vendor, product, material, *, bambu_parent: str | None, library, store, used_fids) -> Line` (creates a missing line; when `bambu_parent` is given and differs from the chosen one, it is set with source `"user"`)
  - `set_parent(lines, line_id, parent: str) -> Line` (`KeyError` when unknown)
  - `product_of(filament: dict, library) -> str` (JSON-decoded `extra.line`, stripped, if non-empty; else the longest `vendor_entries` product that is a casefold prefix of the filament name at a word boundary; else the filament name)
  - `group(filaments: list[dict], lines, *, library, store, used_fids) -> dict[str, list[dict]]` (line_id → filaments; creates missing lines with `ensure`; skips archived filaments and filaments without a vendor)

- [ ] **Step 1: Write the failing tests** (fixture library from Task 1, fixture store from Task 2, `FK_STATE` → tmp):

```python
def test_parent_from_library_hint():  # library entry bambu_parent "Bambu PLA Basic" in store -> ("Bambu PLA Basic","library")
def test_library_hint_missing_from_store_falls_through():  # hint "Nope" -> brand/material step, not "Nope"
def test_parent_brand_step():  # vendor "SUNLU", product "PLA+", material "PLA", no library entry -> ("SUNLU PLA+","brand")
def test_parent_material_step():  # vendor "XZN", "PETG", "PETG" -> ("Generic PETG","material")
def test_parent_without_store_is_static_generic():  # store None, no hint, material "PA12-CF" -> ("Generic PA-CF","material")
def test_ensure_user_parent_and_stable_fid():  # ensure(..., bambu_parent="Generic PLA") -> parent_source "user";
    # a second ensure keeps filament_id; ids match ^P[0-9a-f]{7}$
def test_product_of_extra_line_json_encoded():  # extra {"line": "\"PLA+ 2.0\""} -> "PLA+ 2.0"; extra {"line": "not json"} -> "not json"
def test_product_of_library_prefix():  # name "PLA+ 2.0 Grey", vendor SUNLU, no extra -> "PLA+ 2.0"
def test_group_creates_lines_and_skips_archived():  # 3 filaments, 2 same line -> 2 lines; archived skipped
def test_new_filament_id_avoids_used():  # with a seeded rng-free check: result not in used, 100 draws unique
def test_lines_roundtrip_atomic():  # save then load equal; no *.tmp left
```
- [ ] **Step 2: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_lines.py`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `lines.py`.
- [ ] **Step 4: Run the tests to see them pass**, then the full suite.
- [ ] **Step 5: Commit.** Message: `feat(profiles): product lines and Bambu parent choice`.

### Task 4: Value sources and in-app rules

**Files:**
- Create: `server/filament_kit/profiles/values.py`, `server/filament_kit/profiles/inapp.py`, `server/tests/test_values.py`, `server/tests/test_inapp.py`

**Interfaces:**
- Produces in `values`:
  - `@dataclass SpoolmanValues(material: str | None, density: float | None, cost: float, nozzle: int | None, bed: int | None, nozzle_range: tuple[int, int] | None, colors: str)`
  - `spoolman_values(filaments: list[dict]) -> SpoolmanValues` (port of `gen.spoolman_values`; mode/mean/median ignore `None`, `0` and non-numbers, and accept numeric strings; `nozzle_range` from JSON-decoded `extra.nozzle_range` like `"200-230"`)
  - `merged_entry(lookup: Lookup) -> dict | None` (deep copy of the library entry with the local entry's `fields`, `published_ranges`, `bambu_parent`, `material` keys overriding key by key)
  - `rng(text) -> tuple[float, float] | None`, `nozzle_bounds(fields) -> tuple`, `unsupported_nozzles(entry) -> set[str]`, `hardened(entry, material) -> bool`, `fan_off(entry) -> bool` (ports of `spec.py` with the Decision's fixes)
  - `apply_library(cfg: dict, entry: dict | None, *, template: dict, printer: str, nozzle: str, chamber_max: int | None, log: list[str]) -> None` (port of `spec.apply` for the library schema: set the SET_FIELDS, clamp parent-derived values, fan OFF, `required_nozzle_HRC ["40"]`, chamber only when `chamber_max` is not None and capped there, the MVS cap only when `nozzle == "0.4"`; never touches `temperature_vitrification`)
  - `apply_spoolman(cfg, sv: SpoolmanValues, *, variants: list[str], template: dict) -> set[str]` (returns the protected keys it set: nozzle temps per variant via a port of `gen.temps_for_variants`, hot/textured plate + initial layer from `sv.bed`, `nozzle_temperature_range_low/high` from `sv.nozzle_range`, `filament_density`, `filament_cost` when > 0)
  - `report_outside(cfg, entry, keys: set[str], log: list[str]) -> None` (for protected keys outside a published bound, append `"<name>: your <key> <v> is outside the published <lo>-<hi>; kept"`)
  - `spec_notes(entry) -> str | None` (port of `spec.notes` for library keys)
- Produces in `inapp` (path-free port of `inapp.py`):
  - `MARK`, `IGNORE` (as `inapp.py`, plus `"compatible_printers"`)
  - `norm`, `diff(installed: dict, live: dict) -> dict`
  - `user_notes(installed, live) -> list[str]` (drops lines starting `"Spoolman filament ids:"`)
  - `keep_edits(cfg: dict, installed: dict | None, live: dict | None, log: list[str]) -> set[str]` (the keys taken from live; notes handled as in `gen.keep_edits` but appended before the ids line by Task 5)
  - `is_reset(snapshot: set[str], live: set[str]) -> bool` (`snapshot` non-empty and more than `len(snapshot) / 4` of it missing from live)
  - `deleted(name: str, *, snapshot: set[str], live: set[str], before: set[str], reset: bool, restore: bool) -> bool` (port of `gen.gone`, casefolded names)

- [ ] **Step 1: Write the failing tests** with exact values:

```python
def test_clamp_parent_value_into_range():  # template nozzle_temperature ["250"], entry range 190-230 -> ["230"], log names "published 190-230"
def test_spoolman_value_outside_range_kept_and_reported():  # apply_spoolman nozzle 245, then report_outside with range 190-230
    # -> cfg value "245", log contains "your nozzle_temperature 245 is outside the published 190-230; kept"
def test_never_invent_midpoint():  # entry with only nozzle low 200, parent 190 -> "200"; no high -> no upper clamp
def test_no_vitrification_ever():  # entry carrying temperature_vitrification (bypassing validation) -> cfg unchanged for that key
def test_fan_off_exact_zero_only():  # "0 (OFF)" -> fan_min_speed ["0"], fan_max_speed ["0"]; "0-30" -> fan_max clamped to 30, not 0
def test_hardened_rules():  # material "PETG-CF" -> HRC ["40"]; note "No - brass ok" -> no HRC; "Hard steel nozzle required" -> ["40"]
def test_chamber_only_with_chamber():  # range "25-45": chamber_max None -> untouched; parent 70 with chamber_max 65 -> ["45"]
def test_mvs_cap_only_04():  # entry MVS ["12"], parent ["21","35"]: nozzle "0.4" -> ["12","12"]; "0.6" -> unchanged
def test_variant_temps_keep_offset():  # template ["220","230"], sv.nozzle 210 -> ["210","220"]
def test_spoolman_values_odd_input():  # nozzle None/0/"215" -> 215; density missing on one -> mean of the rest; no price -> cost 0
def test_local_overrides_library_per_key():  # library fields low 190 high 230, local high 220 -> merged low 190 high 220
def test_unsupported_nozzles():  # "_not_supported": "0.2, High Flow nozzle" -> {"0.2"}
def test_spec_notes_has_sources():  # text starts "Manufacturer specs:" and contains the first source URL
```
`test_inapp.py`: `diff` ignores IGNORE keys; `user_notes` keeps lines below MARK, minus `Spoolman filament ids:` lines; `keep_edits` copies a changed `filament_flow_ratio` and logs `"(your in-app value, kept)"`; `is_reset` is True for 3 of 8 missing (3 > 2) and False for 2 of 8 missing; `deleted` is False when `reset`, True when the name was in the snapshot and is gone from live, False with `restore=True`.
- [ ] **Step 2: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_values.py server/tests/test_inapp.py`. Expected: FAIL.
- [ ] **Step 3: Implement** `values.py` and `inapp.py`.
- [ ] **Step 4: Run the tests to see them pass**, then the full suite.
- [ ] **Step 5: Commit.** Message: `feat(profiles): value sources, spec rules and in-app edit rules`.

### Task 5: Preset generator

**Files:**
- Create: `server/filament_kit/profiles/generate.py`, `server/tests/test_generate.py`

**Interfaces:**
- Consumes: `bbl.Store`, `lines.{Line, group, bs_type, new_filament_id}`, `values.*`, `inapp.*`, `library.Library`, `bridge.models.{printer_preset_name, chamber_max}`
- Produces:
  - `@dataclass Live(root: Path, user_id: str)` with `preset(name) -> tuple[dict | None, dict]` (`base/<name>.json` parsed, `base/<name>.info` as a dict) and `names() -> set[str]` (stems of `base/*.json`)
  - `ID_RE = re.compile(r"^P[0-9a-f]{7}$")`
  - `preset_name(line: Line, printer: str, nozzle: str) -> str` (`f"{line.vendor} {line.product} @{printer} {nozzle} nozzle"`)
  - `check_preset(cfg: dict, parent_cfg: dict) -> list[str]` (no `"nil"` anywhere, `filament_id` matches `ID_RE`, `nozzle_temperature_range_low/high` parse as ints, the notes' last line starts `"Spoolman filament ids: "`, `inherits == ""`, a single `compatible_printers` entry, `temperature_vitrification` equal to the parent's, the name free of `\/:*?"<>|`)
  - `build_all(*, filaments: list[dict], models: list[str], store: Store, library: Library, lines: dict[str, Line], live: Live | None, snapshot: Path | None, deleted_before: set[str], restore_deleted: bool, out_dir: Path, now: float) -> tuple[dict, dict[str, Line]]`. Returns the manifest (the `BUILD.json` content minus `stamp`/`live_hash`/`system_hash`, which `builds` adds) and the updated lines. Manifest keys: `presets: [{name, line_id, printer, nozzle, filament_id, filament_type, nozzle_temp_min, nozzle_temp_max, spoolman_ids}]`, `lines: {line_id: {filament_id, spoolman_ids, vendor, product}}`, `problems`, `clamps`, `edits`, `deleted`, `stale`, `library_version`.

Per line × printer × nozzle, in this order:
1. `cfg = store.resolve(parent)`, then pop `type`, `instantiation`, `setting_id`, `description`, `renamed_from`, `is_custom_defined`, `inherits`, `filament_id`, `compatible_printers`. The parent is `store.parent_for(line.bambu_parent, printer, nozzle)`; None → problem and skip.
2. Set the common keys (port of `gen.common`/`bs_profile`): `name`, `from "User"`, `filament_settings_id [name]`, `filament_vendor [vendor]`, `filament_type [bs_type, or the parent's type when it is TPU-AMS or not in BS_VALID]`, `inherits ""`, `filament_id line.filament_id`, `compatible_printers [f"{printer} {nozzle} nozzle"]`, `compatible_printers_condition ""`, `compatible_prints []`, `compatible_prints_condition ""`, and `version` = the parent's `version` or `"2.0.0.0"`.
3. `apply_library` with the merged entry.
4. `apply_spoolman`.
5. `keep_edits` against the snapshot's `base/<name>.json` and the live preset.
6. `report_outside` for the Spoolman and in-app keys.
7. Notes in the order of the Decision.
8. `check_preset` (failure → problem and skip).
9. Write `out_dir/base/<name>.json` (sorted keys, indent 4, `ensure_ascii=False`, `newline="\n"`) and `.info` (`sync_info`, `user_id` = live user id or `""`, `setting_id`, `base_id`, `updated_time` = `int(now)`; when the live `.info` of that name has a `setting_id`, reuse it with `base_id` and `sync_info = "update"`).

Skip deleted names (`inapp.deleted`) and record them. Abrasive lines skip 0.2, and every line skips `unsupported_nozzles`. If live holds a base preset of the same name with a different `filament_id` that is not in the snapshot, adopt its id for the line (as `gen.py` does) and log it. `stale` = snapshot names that are no longer generated but are still present in live.

- [ ] **Step 1: Write the failing tests** (fixture store + library; Spoolman filaments as dicts; models `["O1D", "C12"]`):

```python
def test_one_preset_per_line_printer_nozzle():  # SUNLU PLA+ 2.0 on H2D -> names for 0.2,0.4,0.6,0.8; on P1S -> 0.4 only
def test_notes_end_with_spoolman_ids():  # last line == "Spoolman filament ids: 3, 17"
def test_priority_spoolman_over_library_over_parent():  # spoolman nozzle 210, library range 200-220, parent 220 -> ["210", "220"]
def test_never_generic_id_and_no_nil(tmp_path):  # every written json: filament_id matches ID_RE, "nil" not in text, inherits == ""
def test_temps_always_present():  # manifest preset nozzle_temp_min/max are ints for every preset
def test_line_without_parent_is_skipped_with_problem():  # material "PEEK" -> problem names the line; other presets still built
def test_odd_spoolman_values_do_not_break_build():  # nozzle None/"0"/"abc", density None -> build ok, values from library/parent
def test_abrasive_skips_02():  # Generic PLA-CF line -> no 0.2 nozzle preset
def test_deleted_in_app_left_out_and_reset_rebuilds():  # snapshot has 8, live missing 1 -> deleted; missing 3 -> reset, all 8 rebuilt
def test_in_app_edit_kept_and_reported():  # live flow ratio 0.95 vs snapshot 0.98 -> new cfg 0.95, edits log has it
def test_cloud_setting_id_reused():  # live .info setting_id "PFUS123" -> written .info setting_id PFUS123, sync_info update
def test_chamber_only_h2d():  # library chamber "25-45": H2D preset chamber clamped; P1S preset keeps parent value
```
- [ ] **Step 2: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_generate.py`. Expected: FAIL.
- [ ] **Step 3: Implement** `generate.py`.
- [ ] **Step 4: Run the tests to see them pass**, then the full suite.
- [ ] **Step 5: Commit.** Message: `feat(profiles): preset generator (line x printer x nozzle)`.

### Task 6: Builds, sync storage, preset_for

**Files:**
- Create: `server/filament_kit/profiles/builds.py`, `server/filament_kit/profiles/index.py`, `server/tests/test_builds.py`, `server/tests/test_index.py`
- Modify: `server/filament_kit/profiles/__init__.py` (the real `PresetRef`, re-exporting `index.preset_for`, docstring updated), `server/filament_kit/bridge/loading.py:253-258` (`tray_type` = `preset.filament_type`, `setting_id` = `preset.setting_id`, temps without `or 0`; `_preset_view` adds `filament_type`), `server/tests/test_loading.py` (fake `PresetRef`s with the new fields)

**Interfaces:**
- Consumes: `generate.build_all`, `generate.Live`, `lines.load/save`, `library.load`, `bbl.Store`, `registry.load`, `Spoolman.get("filament")`
- Produces:
  - `PresetRef(filament_id: str, name: str, nozzle_temp_min: int, nozzle_temp_max: int, filament_type: str, setting_id: str = "")`
  - `builds.tree_hash(root: Path) -> str` (the contract formula)
  - `builds.MAX_LIVE = 32 << 20`, `builds.MAX_SYSTEM = 64 << 20`
  - `builds.OtherPc(ProfileError)` (409 `other_pc`), `builds.BadZip(ProfileError)` (400 `bad_zip`), `builds.TooLarge(ProfileError)` (413 `too_large`)
  - `builds.store_upload(kind: "live" | "system", src: BinaryIO, *, device_id: str, user_id: str | None = None) -> str` (claims the sync owner; streams to a temp file counting bytes, so it raises `TooLarge` before reading past the cap; safe extract per the upload Decision; refuses absolute paths, `..`, drive letters, backslashes, symlink/dir entries with a payload, and suffixes other than `.json`/`.info`; every `.json` must parse; swaps `profiles/live/{user,system}` under the profiles lock; updates `profiles/live/meta.json`; returns the tree hash)
  - `builds.owner() -> str | None`
  - `builds.request_rebuild(reason: str, live_hash: str | None = None) -> None`
  - `builds.run_build(sm, *, now: float | None = None) -> dict` (`{stamp, ok, error, problems}`)
  - `builds.current() -> dict | None`, `builds.build_zip(stamp: str) -> bytes`, `builds.record_installed(stamp, device_id) -> dict`
  - `builds.state_view(device_id: str) -> dict` (`GET /api/sync/state` shape)
  - `builds.status() -> dict` (`GET /api/profiles/status` shape, minus the library part, which Task 7 adds)
  - `builds.restore_deleted_next() -> None` (writes the flag file)
  - `index.preset_for(filament: dict, model: str, nozzle_mm: float) -> PresetRef | None`

`run_build`:
1. Under the cross-process lock `profiles/build.lock`, remove leftover `builds/*.tmp`, and record `last_attempt` `{at, ok: null}`.
2. Load the system store from `live/system`; with no system presets, fail with `"no Bambu Studio system presets yet: install and pair the PC sync"`.
3. Load the library, the lines, the Spoolman filaments, and the registry models.
4. The snapshot is the installed build's dir, if any; `deleted.json` holds `deleted_before`; the restore flag is consumed.
5. Call `generate.build_all` into `builds/<stamp>.tmp`, write `BUILD.json`, rename to `builds/<stamp>`, save the lines, write `deleted.json`, then write `current.json` atomically.
6. Prune to 5 plus the installed build.
7. Any exception → `last_attempt` `{ok: false, error: "<type>: <message>"}`, the tmp dir removed, `current.json` untouched. Loop again when the request file's `at` is newer than this run's start (at most 3 runs).

Stamps are `%Y%m%d-%H%M%S`, with `-2`, `-3` … added when one is taken.

`preset_for`:
1. `printer = models.printer_preset_name(model)`, `nozzle = f"{nozzle_mm:g}"`.
2. `line_id = library.line_id(vendor, lines.product_of(filament, library))` if that line is in the current build, else the build's filament-id map.
3. Find the preset with that line, printer and nozzle; None if none.
4. Refuse (return None) when its `filament_id` does not match `generate.ID_RE`.
5. `setting_id` from `live/user/base/<name>.info`.

Cache the parsed `BUILD.json` by the mtime of `current.json`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_tree_hash_contract(tmp_path):  # files {"a.json": b"{}", "base/b.info": b"x", "c.txt": b"y"} -> equals the formula over a.json, base/b.info only
def test_upload_rejects_zip_slip_and_keeps_previous():  # entries "../x.json", "/abs.json", "C:/x.json", "a\\b.json" -> BadZip; live/user unchanged
def test_upload_rejects_bomb_and_count():  # 30 000 entries -> BadZip; 600 MiB uncompressed -> BadZip; nothing written outside tmp
def test_upload_too_large_stops_early():  # stream of 33 MiB -> TooLarge after reading at most MAX_LIVE + 1 bytes
def test_second_pc_refused():  # device "a" uploads, device "b" -> OtherPc; revoke "a" (pairing.revoke) -> "b" accepted
def test_failed_build_keeps_last_good():  # good build, then generate raises -> current() stamp unchanged, last_attempt ok False
def test_no_system_presets_fails_cleanly():  # error text contains "install and pair the PC sync"
def test_leftover_tmp_removed_on_next_run():  # builds/x.tmp exists -> gone after run_build
def test_rerun_when_requested_during_build():  # request_rebuild called inside a patched build_all -> run_build ran twice
def test_retention_keeps_5_and_installed():  # 8 builds, installed = 1st -> 6 dirs remain incl. the 1st
def test_build_zip_and_installed():  # zip has BUILD.json + base/*.json/*.info; record_installed unknown stamp -> ProfileError 404
```
`test_index.py`:
- After a fixture build: `preset_for(filament_of_line, "O1D", 0.4)` returns `PresetRef(filament_id=<line fid>, name="SUNLU PLA+ 2.0 @Bambu Lab H2D 0.4 nozzle", nozzle_temp_min=190, nozzle_temp_max=230, filament_type="PLA", setting_id="")`.
- A new colour with the same `extra.line` gives the same PresetRef.
- An unknown model, no build, or a nozzle without a preset → None.
- A tampered `BUILD.json` with `filament_id` `"GFL99"` → None.
- A live `.info` with `setting_id = PFUS1` → `setting_id == "PFUS1"`.
`test_loading.py`: the load command carries `tray_type == preset.filament_type`, `setting_id == preset.setting_id`, and int temps.
- [ ] **Step 2: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_builds.py server/tests/test_index.py server/tests/test_loading.py`. Expected: FAIL.
- [ ] **Step 3: Implement** `builds.py`, `index.py`, `PresetRef`, and the `loading.py` changes.
- [ ] **Step 4: Run the tests to see them pass**, then the full suite.
- [ ] **Step 5: Commit.** Message: `feat(profiles): builds with last-good fallback, sync storage, real preset_for`.

### Task 7a: API routes

**Files:**
- Create: `server/filament_kit/profiles_api.py`, `server/tests/test_api_profiles.py`
- Modify: `server/filament_kit/api.py` (map `ProfileError` in `_to_response` to `_err(e.status, e.code, e.message, **e.extra)`; add `*profiles_api.routes(_authed, sm)` to the route list)

**Interfaces:**
- Consumes: `builds.*`, `lines.*`, `library.*`, `bbl.Store`
- Produces: every route in the contract table; `routes(authed, sm) -> list[Route]`. Uploads read `request.stream()` into `builds.store_upload` (wrapped in a sync file-like object in the threadpool), never `await request.body()`. Every write route logs `device_id`, never a body. `PATCH lines` and `POST library/local` call `builds.request_rebuild`. `/api/profiles/status` merges `builds.status()` with `library.status()`.
- [ ] **Step 1: Write the failing tests.**
  - Each route's shape and error codes from the table.
  - 401 without a token.
  - `PUT /api/sync/live` with a 33 MiB body → 413 and nothing stored.
  - A zip-slip → 400 `bad_zip`.
  - A second device → 409 `other_pc`.
  - `GET /api/sync/build?stamp=nope` → 404.
  - `POST /api/library/local` with an invalid entry → 400 `invalid_entry` with `problems`.
  - `PATCH` with an unknown parent while a store is uploaded → 400 `unknown_parent`.
  - The token never appears in caplog.
- [ ] **Step 2: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_api_profiles.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the routes.
- [ ] **Step 4: Run the tests to see them pass**, then the full suite.
- [ ] **Step 5: Commit.** Message: `feat(api): sync and profile routes`.

### Task 7b: CLI, status, intake and inventory hooks

**Files:**
- Modify: `server/filament_kit/cli.py`, `server/filament_kit/intake.py`, `server/filament_kit/inventory.py`, `server/tests/test_cli.py`, `server/tests/test_intake.py`, `server/tests/test_inventory.py`

**Interfaces:**
- Consumes: `builds`, `lines`, `library`
- Produces:
  - CLI: `filament-kit profiles build` (runs `builds.run_build`; exit 1 when the run failed), `profiles status`, `profiles lines`, `profiles set-parent <line_id> <parent>`, `profiles restore-deleted`, and `pair --pc` (`pairing.issue(device_hint="pc")`; prints `Link for filament-kit-sync (paste it when asked):` then the `fkit://` link, the fingerprint and the code; no QR).
  - `status` gains: `--   library version N (bundled|updated <date>), M local additions`; an update error as `--   library update: <error>` (a warning, not a failure); `OK   profiles: build <stamp>, P presets for L lines (K problems)` or `FAIL profiles: last build failed: <error>; using build <stamp>` with fix `sudo journalctl -u filament-kit-build -n 50`; `--   PC sync: last upload <time>, installed build <stamp>`, or `--   PC sync: not set up (see README: Pair your PC)`.
  - The Task 1 import guard is removed.
  - Intake: `ITEM_PROPS` and the required list gain `"line": {"type": "string"}`. RULES gain: `line: the product line as printed, without the colour (e.g. 'PLA+ 2.0', 'PETG HF'); for an existing filament copy its line from the catalog`. The catalog rows add `| line <extra.line or ->`. After the call, `it.setdefault("line", lines.product_of(...))`; existing filaments take their `extra.line`. Each item is then updated with `profiles.lines.propose(...)` (store from `live/system` when present).
  - Inventory: `_OPT_STR` adds `line`, `bambu_parent`; `_validate` checks `bambu_parent` (≤ 100, no `@`); `_new_filament` writes `extra["line"] = json.dumps(line)` when given. After a non-dry `add_and_link`, call `lines.ensure` for each item's line (with its `bambu_parent`), `lines.save`, and `builds.request_rebuild("intake")`. Failures there are logged and never fail the add.
- [ ] **Step 1: Write the failing tests.**
  - `profiles build` exits 0 and prints the stamp; with no system presets it exits 1 with the "install and pair the PC sync" text.
  - `pair --pc` prints a link starting `fkit://pair?`, and the device list shows name `pc` after a claim.
  - The status lines appear in the exact formats above.
  - Intake: the recorded response without `line` gets a derived line plus `bambu_parent`/`parent_source`/`line_exists`.
  - Inventory: an add with `line "PETG HF"` and `bambu_parent "Generic PETG"` writes `extra.line == "\"PETG HF\""`, creates line `elegoo--petg-hf` with source `user`, and writes the request file; a dry run writes neither.
  - `bambu_parent "X @BBL H2D"` → `ValueError`.
- [ ] **Step 2: Run the tests to see them fail.** Run: `... -m pytest -q server/tests/test_cli.py server/tests/test_intake.py server/tests/test_inventory.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the CLI, status, intake and inventory changes.
- [ ] **Step 4: Run the tests to see them pass**, then the full suite.
- [ ] **Step 5: Commit.** Message: `feat(cli): profiles and library commands, status lines, line capture at intake`.

### Task 8: Installer, units, backup, uninstall

**Files:**
- Create: `install/systemd/filament-kit-library.service`, `install/systemd/filament-kit-library.timer`, `install/systemd/filament-kit-build.service`, `install/systemd/filament-kit-build.path`
- Modify: `install/install.sh` (install + enable `filament-kit-library.timer` and `filament-kit-build.path`; `install -d -m 750 -o filament-kit -g filament-kit "$STATE/profiles" "$STATE/library" "$STATE/library-local"`; run `filament-kit profiles build || true` once after the services start), `install/uninstall.sh` (disable and remove the four units), `install/backup.sh` (exclude `var/lib/filament-kit/profiles/live/system`, `var/lib/filament-kit/library/versions`, and `var/lib/filament-kit/profiles/builds/*.tmp`), `install/filament-kit-cli.sh` (`library add <file>`: as root, `exec runuser -u filament-kit -- "$BIN" library add - < "$3"`, refusing a missing file with a message), `tools/make_release.sh` (check that the wheel contains `filament_kit/library_data/index.json`), `docs/install-test.md` (new checks: both timers listed by `systemctl list-timers`; `sudo filament-kit library update`; `sudo filament-kit profiles build` before any PC sync prints the "install and pair the PC sync" message)

Units:
- `filament-kit-build.service`: Type=oneshot; User/Group filament-kit; `ExecStart=/opt/filament-kit/venv/bin/filament-kit profiles build`; `IPAddressDeny=any`, `IPAddressAllow=localhost`; ProtectSystem=strict; `ReadWritePaths=/var/lib/filament-kit`; NoNewPrivileges; PrivateTmp; ProtectHome.
- `filament-kit-build.path`: `PathModified=/var/lib/filament-kit/profiles/rebuild-request`; WantedBy multi-user.target.
- `filament-kit-library.service`: oneshot; `ExecStart=... library update --scheduled`; the same hardening without IPAddress lines.
- `filament-kit-library.timer`: `OnCalendar=daily`, `RandomizedDelaySec=1h`, `Persistent=true`.
- Library `update` and `library add` already write the request; nothing else is needed.

- [ ] **Step 1: Write the failing check.** `server/tests/test_units.py` parses the unit files: the build service has `IPAddressDeny=any` and `User=filament-kit`; the path unit watches `/var/lib/filament-kit/profiles/rebuild-request`; install.sh enables both new units and uninstall.sh removes all four (string checks); the CLI wrapper uses stdin for `library add`.
- [ ] **Step 2: Run the test to see it fail.** Run: `... -m pytest -q server/tests/test_units.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the units and script changes.
- [ ] **Step 4: Run the test to see it pass.** Also run `bash -n install/*.sh tools/*.sh` (Git Bash) and, if available, `wsl -d Ubuntu -- shellcheck` on them; the CI job runs shellcheck otherwise.
- [ ] **Step 5: Commit.** Message: `feat(install): library timer, build path unit, backups skip re-downloadable data`.

### Task 9: App — Bambu parent at confirm, Add profile, build status (Android)

**Files** (main paths relative to `android/app/src/main/java/com/thompsonfabco/filamentkit/`, tests to `android/app/src/test/java/com/thompsonfabco/filamentkit/`):
- Modify: `net/Models.kt` (`ProfileStatus`, `ProfileLine`, `Proposal`, `ParentList`, `LibraryInfo`), `net/Api.kt` (`profileStatus()`, `parents(material)`, `propose(vendor, line, material)`, `setLineParent(lineId, parent)`, `addLocalProfile(entry: JsonObject)`), `ui/add/ReviewScreen.kt` (`ItemCard`: a "Line" text field (`line`) and a "Bambu Studio parent" field (`bambu_parent`) with a dropdown from `parents(material)` when `synced`, free text otherwise; a hint "applies to every colour of this line" when `line_exists`; an edit of vendor, line or material re-proposes through `propose`, debounced 500 ms, and keeps a parent the user picked), `ui/add/AddViewModel.kt` (the proposal and parent state; items sent to add carry `line` + `bambu_parent`), `ui/home/HomeScreen.kt` ("Add profile" button; a "Presets" card: `"<presets> presets for <lines> lines, built <time>"`, or the build error in error colour, plus `"Installed on your PC <time>"` or `"PC sync not set up"`), `MainActivity.kt` (route `profile/add`), `ui/printers/PrinterViewModel.kt:100` (`no_preset` text: `"No preset for this filament on this printer yet. It is made at the next preset build; see Presets on the home screen."`)
- Create: `ui/profile/AddProfileScreen.kt`, `ui/profile/AddProfileViewModel.kt`
- Test: `test/.../net/ApiProfilesTest.kt`, `test/.../ui/profile/AddProfileViewModelTest.kt`, `test/.../ui/add/AddViewModelTest.kt` (extend)

The Add profile form has these fields: vendor*, product line*, material*, nozzle low/high (°C), bed range (text like `55-65`), density, max volumetric speed (mm³/s), Bambu Studio parent (dropdown/free), notes. The fields map to an entry: `fields.nozzle_temperature_range_low/high`, `filament_density`, `filament_max_volumetric_speed` as one-element string arrays; `published_ranges.bed_all_plates`, `_notes`; `bambu_parent`; `vendor`, `product`, `material`; `schema_version 1`. It posts to `/api/library/local`. On 400 `invalid_entry` it shows each problem; on success it shows "Saved. Presets are rebuilt in a minute."

- [ ] **Step 1: Write the failing tests.**
  - The API client parses every contract shape (MockWebServer, pinned TLS as the existing `ApiTest`).
  - VM: a parent edit is kept when the material changes the proposal; the add body contains `line` and `bambu_parent`.
  - The Add profile VM builds the exact entry JSON for a filled form, leaves out empty fields, and maps `invalid_entry` problems to the field errors list.
  - The Home presets card text in the built, failed and not-set-up states.
  - The `no_preset` message.
- [ ] **Step 2: Run the tests to see them fail** with the Android command; expected: FAIL (unresolved references).
- [ ] **Step 3: Implement** the screens, view models and API methods.
- [ ] **Step 4: Run the tests to see them pass.** Expected: `testDebugUnitTest lintDebug assembleDebug` succeed.
- [ ] **Step 5: Commit.** Message: `feat(android): Bambu parent at confirm, Add profile, preset build status`.

### Task 10: PC sync core (local folders, hashing, zips, secrets)

**Files:**
- Create: `pc-sync/pyproject.toml` (name `filament-kit-sync`, `requires-python >=3.12`, no dependencies, optional `test = ["pytest==8.3.4"]`, script `filament-kit-sync = "fksync.__main__:main"`), `pc-sync/fksync/__init__.py` (`__version__ = "0.1.0"`), `pc-sync/fksync/studio.py`, `pc-sync/fksync/treehash.py`, `pc-sync/fksync/zips.py`, `pc-sync/fksync/store.py`, `pc-sync/tests/conftest.py`, `pc-sync/tests/studio_fixture.py`, `pc-sync/tests/test_studio.py`, `pc-sync/tests/test_treehash.py`, `pc-sync/tests/test_zips.py`, `pc-sync/tests/test_store.py`
- Setup: create the pc-sync venv (Global Constraints) once.

**Interfaces:**
- Produces:
  - `studio.StudioFolders(root: Path, variant: str, user_id: str, user_filament: Path, system_filament: Path)`
  - `studio.locate(appdata: Path, pin: dict | None = None) -> StudioFolders` (raises `studio.NotFound(message)`; the Decision's rules)
  - `studio.running(tasklist: Callable[[], str] | None = None) -> bool` (`tasklist /fo csv /nh /fi "IMAGENAME eq bambu-studio.exe"` with `CREATE_NO_WINDOW`; False when not Windows)
  - `treehash.tree_hash(root: Path) -> str` (the contract formula)
  - `zips.pack(root: Path) -> bytes` (json/info only, sorted, deflated)
  - `zips.unpack_build(data: bytes, dest: Path) -> dict` (only `BUILD.json` and `base/<name>.(json|info)` with safe names; ≤ 64 MiB uncompressed; returns BUILD.json)
  - `store.AppDirs(base: Path)` with `.config`, `.token`, `.log_file`, `.backups`, `.installed`, `.state`, `.lock` paths
  - `store.save_token(dirs, token: str)`, `store.load_token(dirs) -> str | None` (DPAPI `CryptProtectData`/`CryptUnprotectData` via ctypes with entropy `b"filament-kit-sync"` on Windows; a 0600 plain file elsewhere)
  - `store.load_config(dirs) -> dict`, `store.save_config(dirs, cfg)`
  - `store.log(dirs, msg: str)` (timestamped; rotates at 1 MiB to `sync.log.1`)
  - `store.single_instance(dirs)` (context manager; `msvcrt.locking` / `fcntl`; raises `store.AlreadyRunning`)
  - `studio_fixture.make(appdata: Path, *, variant="BambuStudioBeta", user_id="1725623066", presets: dict[str, dict] = {}, base: dict[str, tuple[dict, dict]] = {}, system_src: Path | None = None) -> StudioFolders` (writes a fake tree; `system_src` copies a folder of system presets, otherwise one minimal `Generic PLA @BBL H2D.json`)
- `conftest.py` (autouse): `monkeypatch.setenv("APPDATA", tmp/"appdata")` and `("LOCALAPPDATA", tmp/"local")`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_locate_prefers_newest_conf(tmp_path):  # both variants, Beta conf newer -> variant "BambuStudioBeta"
def test_locate_newest_user_and_pin(tmp_path):  # user/default older than user/123 -> "123"; pin {"user_id": "default"} -> "default"
def test_locate_not_found_message(tmp_path):  # empty appdata -> NotFound mentioning "Bambu Studio"
def test_running_parses_tasklist():  # fake output with "bambu-studio.exe" -> True; "INFO: No tasks" -> False
def test_tree_hash_contract(tmp_path):  # same vector as server test_tree_hash_contract, hex compared with the inline formula
def test_pack_only_presets_sorted(tmp_path):  # names in zip == ["a.json","base/b.info"]; packing twice gives identical bytes
def test_unpack_build_refuses_unsafe(tmp_path):  # "../x.json", "base/../../x.json", "other/x.json" -> ValueError, dest untouched
def test_token_roundtrip_not_plaintext_on_windows(tmp_path):  # on win32: file bytes do not contain the token; load == token
def test_log_rotates(tmp_path):  # > 1 MiB -> sync.log.1 exists
def test_never_touches_real_appdata():  # os.environ["APPDATA"] is under tmp_path in every test (guard self-test)
```
- [ ] **Step 2: Run the tests to see them fail** with the pc-sync command; expected: FAIL.
- [ ] **Step 3: Implement** the four modules and the fixture helper.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** Message: `feat(pc-sync): Bambu Studio folder discovery, hashing, zips, DPAPI token`.

### Task 11: PC sync installer (port of install.py)

**Files:**
- Create: `pc-sync/fksync/inapp.py` (`IGNORE`, `norm`, `diff` copied from the server's `inapp`), `pc-sync/fksync/installer.py`, `pc-sync/tests/test_installer.py`

**Interfaces:**
- Consumes: `StudioFolders`, `AppDirs`, `zips.unpack_build` output dir
- Produces:
  - `installer.Refused(Exception)` (`.reason`)
  - `@dataclass InstallResult(installed: list[str], stale: list[str], backup: Path)`
  - `installer.install(build_dir: Path, folders: StudioFolders, dirs: AppDirs, *, running: Callable[[], bool], stamp_now: str) -> InstallResult`

Order:
1. Read the staged names from `build_dir/base`.
2. Untrusted G-code check (port of `install.py`): every value of a key containing "gcode" must be a value in the local system folder, or equal the live preset's current value; else `Refused("... G-code ...")`.
3. Edited/deleted-after-build check against `dirs.installed` (port).
4. `running()` checked here, immediately before the first write → `Refused("Bambu Studio is running")`.
5. Back up `user_filament` to `dirs.backups/<stamp_now>` and keep the 5 newest.
6. Copy each staged `.json`, and write its `.info` merged so a live `setting_id` is kept (port).
7. Never delete anything; `stale` = previous snapshot names not staged but still live.
8. Replace `dirs.installed` with a copy of `build_dir` (tmp dir + rename).

- [ ] **Step 1: Write the failing tests** (fixture tree from `studio_fixture`):
  - The happy path writes the files and keeps `setting_id`.
  - A 6th install leaves 5 backups.
  - A G-code value not in the system folder → `Refused`, nothing written.
  - Edited in the app after the build → `Refused` naming the key.
  - `running` returns False at first and True right before writing → `Refused`, no backup dir created, live unchanged.
  - A stale preset is still on disk afterwards and listed in `stale`.
  - `dirs.installed` equals the build after success.
- [ ] **Step 2: Run the tests to see them fail.**
- [ ] **Step 3: Implement** `installer.py` and `inapp.py`.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** Message: `feat(pc-sync): safe preset install with backups (port of install.py)`.

### Task 12: PC sync client, run loop and CLI

**Files:**
- Create: `pc-sync/fksync/client.py`, `pc-sync/fksync/sync.py`, `pc-sync/fksync/__main__.py`, `pc-sync/tests/test_client.py`, `pc-sync/tests/test_sync.py`, `pc-sync/tests/test_cli.py`
- Modify: `pc-sync/pyproject.toml` (test extra adds `cryptography>=44`, used only by the test TLS server). Install it: `C:/REA/bin/uv.cmd pip install --python C:/CODING/filament-kit/pc-sync/.venv/Scripts/python.exe "cryptography>=44"`.

**Interfaces:**
- Consumes: the contract routes, `/api/info`, `/api/pair`; Tasks 10 and 11
- Produces:
  - `client.PairLink(host, port, token, fp, ips)`
  - `client.parse_link(text) -> PairLink` (`ValueError` for anything that is not `fkit://pair?`)
  - `client.fetch_fingerprint(host, port, timeout=10) -> str`
  - `client.CertChanged`, `client.Offline`, `client.ApiError(status, code, message)`
  - `client.Client(cfg: dict, token: str | None, timeout=60)` with `info()`, `pair(code) -> str`, `state()`, `upload(kind, data, user_id=None)`, `rebuild(live_hash)`, `build(stamp) -> bytes`, `installed(stamp)`. It tries `cfg["host"]` then each of `cfg["ips"]`; on each it connects TLS with no CA check, compares the leaf DER sha256 with `cfg["fp"]` before writing any request bytes, and moves on to the next address on a mismatch without sending; if every address mismatches → `CertChanged`.
  - `sync.run_once(client, folders: StudioFolders, dirs, *, running, install=installer.install, now: float) -> str`, returning `"studio_running" | "uploaded" | "no_build" | "up_to_date" | "rebuild_requested" | "waiting" | "installed" | "refused" | "other_pc"`. The flow ports `fpsync.main` per the "Sync uploads" Decision: upload on a hash mismatch; rebuild requests are re-sent after 15 min (`state.json` `{requested: {live_hash, at}}`); an install needs `build.live_hash == local hash`; after an install, upload the live folder again and call `installed(stamp)`; the stale list and every outcome are logged in one line each.
  - CLI `filament-kit-sync pair|run [--quiet]|status|unpair` with hidden `--appdata DIR --localappdata DIR` (defaults from the environment, read only in `main`).
    - `pair` asks `Paste the pairing link, or type the server address:`. For a link it saves the config + token and calls `info()` to check. For an address it prints the fingerprint grouped by 4, asks `Does this match the fingerprint shown by 'sudo filament-kit pair'? [y/N]`, then `6-digit code:`.
    - `run` holds `single_instance` and exits 0 for every outcome except unexpected errors (exit 1, logged).
    - `status` prints the server, the Studio folder chosen, the last outcome, the installed stamp and the stale presets.
- [ ] **Step 1: Write the failing tests.**
  - `parse_link` with two `ip=` values.
  - The pinned client against a local TLS server (cert from a test helper using `cryptography`, added to the pc-sync test extra as `cryptography>=44`, test-only): a matching fp works; a wrong fp → `CertChanged`, and the server saw no request bytes.
  - `run_once` with a fake client: Studio running → `studio_running` and no client call; a hash mismatch uploads; no build → `no_build`; `build.live_hash` differs → `rebuild_requested` once, `waiting` within 15 min; matching → `installed`, then `installed(stamp)` is called and live re-uploaded; `Refused` → `refused` logged with the reason; 409 → `other_pc`.
  - CLI `pair` via monkeypatched stdin; the token never appears in `sync.log` or stdout after `pair` + `run`.
- [ ] **Step 2: Run the tests to see them fail.**
- [ ] **Step 3: Implement** the client, run loop and CLI.
- [ ] **Step 4: Run the tests to see them pass.**
- [ ] **Step 5: Commit.** Message: `feat(pc-sync): pinned client, sync loop (port of fpsync.py), CLI`.

### Task 13: End-to-end test (server + PC sync)

**Files:**
- Create: `server/tests/test_pcsync_e2e.py` (prepends `<repo>/pc-sync` to `sys.path`; real `create_app` under uvicorn with TLS from the test cert helper used by `test_api.py`; fake Spoolman; fixture system presets `server/tests/data/bbl/filament`; `studio_fixture.make(..., system_src=...)`)

- [ ] **Step 1: Write the failing test** `test_full_cycle` (each step asserted):
  1. Pair with a code.
  2. `run_once` → `uploaded` then `no_build`.
  3. `builds.run_build` → ok.
  4. `run_once` → `installed`; `base/` in the fixture user folder has the H2D presets with `Spoolman filament ids:` last.
  5. `preset_for(...)` gives int temps and the line's `P…` id.
  6. Edit `filament_flow_ratio` in one live preset, run `run_once` (upload), then request a rebuild + `run_build` + `run_once` → the edit is kept in the reinstalled preset.
  7. Delete one live preset, rebuild → it is not reinstalled.
  8. Delete 50 % → app reset → all of them come back.
  9. A second device → `other_pc`.
- [ ] **Step 2: Run the test to see it fail**, then fix integration gaps only inside the tasks' modules, with the owning task's tests kept green.
- [ ] **Step 3: Run the full server suite and the pc-sync suite**; expected: pass.
- [ ] **Step 4: Commit.** Message: `test: profiles and PC sync end to end`.

### Task 14: Packaging and CI/release

**Files:**
- Create: `pc-sync/fksync.spec` (PyInstaller: two EXEs from `fksync/__main__.py` sharing one COLLECT; `filament-kit-sync` console, `filament-kit-sync-task` windowed, which runs `run --quiet`), `pc-sync/fksync/task_entry.py`, `pc-sync/installer/filament-kit-sync.iss` (AppId fixed GUID, `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\filament-kit-sync`; `[Run]`: `install_task.ps1` then `filament-kit-sync.exe pair` in a console; `[UninstallRun]`: `uninstall_task.ps1`), `pc-sync/installer/install_task.ps1` (port of `install_sync_task.ps1`: task "filament-kit sync", every 10 min + at logon, `-MultipleInstances IgnoreNew`, `-ExecutionTimeLimit 20 min`, current user, the exe path as a parameter, no secrets), `pc-sync/installer/uninstall_task.ps1`, `.github/workflows/pc-sync.yml` (push/PR on `pc-sync/**`: windows-2022, Python 3.12, `pip install ./pc-sync[test]`, pytest, `pip install pyinstaller==6.11.1`, `pyinstaller pc-sync/fksync.spec`, smoke `dist/filament-kit-sync/filament-kit-sync.exe --help`), `.github/workflows/release.yml` (tags `v*`: version check; job `server` ubuntu-24.04: decode `FK_KEYSTORE_B64` to a temp file, set `FK_KEYSTORE`/`FK_KEYSTORE_PASSWORD`/`FK_VERSION_CODE` in env, set up JDK 21 + Android SDK as `android.yml`, `bash tools/make_release.sh`, failing when the secrets are missing; job `sync` windows-2022: PyInstaller, Inno Setup (choco if missing), `ISCC /DAppVersion=<version> pc-sync/installer/filament-kit-sync.iss`; job `publish`: `softprops/action-gh-release@v2` attaching `dist/filament-kit-<v>.tar.gz`, `filament-kit.apk` (from the stage) and `filament-kit-sync-setup-<v>.exe`)
- Modify: `.github/workflows/server.yml` (also `pip install "./pc-sync[test]"` and run `pytest pc-sync/tests` on ubuntu; the e2e test needs pc-sync in place), `server/filament_kit/__init__.py` and `pc-sync/fksync/__init__.py` (`__version__ = "0.2.0"`). `tools/make_release.sh` is not changed here (Task 8 owns it); the release job takes the APK from `android/app/build/outputs/apk/release/app-release.apk`.

- [ ] **Step 1: Write the failing check.** `server/tests/test_release_files.py` parses the workflow YAML as text: `release.yml` triggers on `v*` tags, references both secrets, uses `windows-2022` and `pyinstaller==6.11.1`; the `.iss` has `PrivilegesRequired=lowest`; `install_task.ps1` has `-RepetitionInterval (New-TimeSpan -Minutes 10)`; the server and pc-sync `__version__` are equal.
- [ ] **Step 2: Run the check to see it fail.**
- [ ] **Step 3: Implement** the files. Run PyInstaller locally inside the pc-sync venv: `C:/REA/bin/uv.cmd pip install --python C:/CODING/filament-kit/pc-sync/.venv/Scripts/python.exe pyinstaller==6.11.1`, then `cd <wt>/pc-sync && /c/CODING/filament-kit/pc-sync/.venv/Scripts/pyinstaller.exe --noconfirm fksync.spec && dist/filament-kit-sync/filament-kit-sync.exe --help`. Expected: the usage text. Do not install Inno Setup on this PC.
- [ ] **Step 4: Run the check to see it pass**, then the full server and pc-sync suites.
- [ ] **Step 5: Commit.** Message: `ci: pc-sync build, release workflow with APK, tarball and sync installer`.

### Task 15: README for the family member

**Files:**
- Modify: `README.md`

Sections, in plain steps like the existing README:
- "Install the server" (unchanged; mention the presets features).
- "Pair your phone" (unchanged).
- **"Pair your PC"**: download `filament-kit-sync-setup-<v>.exe` from Releases; run it with no admin rights; run `sudo filament-kit pair --pc` on the server; paste the link when the setup window asks; it then runs every 10 minutes and waits while Bambu Studio is open.
- **"Add a printer"**: from the app's Printers screen (Access Code) or `sudo filament-kit config` → Printers.
- **"Map slots"** (what it does).
- **"Presets in Bambu Studio"**: one per line × printer × nozzle; names `<brand> <line> @Bambu Lab <printer> <nozzle> nozzle`; in-app edits are kept; delete presets in Bambu Studio, never on disk; Bambu cloud keeps about 100 filament presets, the rest stay on this PC; "Add profile" in the app for a line the library lacks; how to change a line's Bambu parent).
- **"Spec library updates"**: daily; `sudo filament-kit library update`; `library rollback`; `library add <file>`.
- **"Troubleshooting"**: `sudo filament-kit status` lines, the sync log at `%LOCALAPPDATA%\filament-kit-sync\sync.log`, backups in `...\backups`.

- [ ] **Step 1: Write the sections.** Every command named matches the CLI in Tasks 1, 7b and 12 (check by grepping `cli.py` and `fksync/__main__.py`).
- [ ] **Step 2: Commit.** Message: `docs: README for presets, PC sync, library updates`.

### Owner checks (not overnight, owner present, each with his OK)

- Run `filament-kit-sync status` against a **copy** of his Bambu Studio Beta folder that he makes himself (the folder choice, the tree hash, one dry install into the copy). This confirms the hand-written fixture formats (`.info` keys, `base/` layout, `include` chains) match the real files.
- Load one real spool on the H2D with a generated preset (after Task 9 of bridge part 2).

## Execution waves (tasks in a wave touch disjoint files)

W1: Tasks 1, 2, 10 · W2: Tasks 3, 4, 11 · W3: Tasks 5, 12 · W4: Task 6 · W5: Tasks 7a, 7b, 9 · W6: Tasks 8, 13, 14, 15.

File ownership per wave:
- `cli.py`: Task 1 (W1), Task 7b (W5).
- `api.py`: Task 7a (W5).
- `profiles/__init__.py`: Task 2 (W1), Task 6 (W4).
- `loading.py`: Task 6.
- `intake.py` and `inventory.py`: Task 7b.
- `config.py` and `pyproject.toml`: Task 1.
- `server/filament_kit/__init__.py`: Task 14.
- `tools/make_release.sh`: Task 8 only.
- `pc-sync/pyproject.toml`: Task 10, then Task 12 (test extra).
- Android files: Task 9 only.
- `pc-sync/`: Tasks 10, 11, 12 and 14 in different waves.
