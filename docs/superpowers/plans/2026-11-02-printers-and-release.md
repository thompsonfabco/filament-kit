# Every Bambu printer + filament-kit for everyone — Implementation Plan

> **For agentic workers:** superpowers:subagent-driven-development. Tasks in one wave run in parallel, each in its own
> worktree branched from `merge-ops`; the controller merges each into `merge-ops` after its review.

**Specs:** `docs/superpowers/specs/2026-11-02-bambu-printers-design.md` (P) and
`docs/superpowers/specs/2026-11-02-public-release-design.md` (R). Both approved 2026-11-02.

## Global Constraints

- Nothing is published: repos stay private; no `gh release`, no visibility change, no push.
- New data files are XML (`defusedxml`, validator in code). Existing JSON files are NOT converted (deferred).
- A family install upgrade keeps working: no AI key needed, existing JSON state read as before, the Android app's
  HTTP JSON API stays compatible (additive only).
- No firewall/IPAddressAllow/pfSense changes by code; runbook lists them for the owner.
- Never read access codes, tokens or keys; the owner enters them. The live VM, station PC, printer and desktop are
  read-only for workers.
- No runtime use of Claude in the printer path.
- Tests: server `cd server && .venv/Scripts/python -m pytest -q`; pc-sync its own venv. Full suite once before the
  last commit (test_camera shutdown test = known Windows flake). Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A printer with 16 AMS units plus HT units plus two externals: every slot gets a unique label, a presence value or
   "unknown", a working slot command, and a usage decode → P2/P3 tests with a synthetic report.
2. Unknown model / unknown AMS module: generic handling, nothing crashes, status says what is unknown → P1, P2.
3. A bad override XML: last good data stays in use, status shows the error → P1.
4. Server mode without an API key: spools can be added by hand from the API and web app → R1.
5. get.sh with a tampered tarball or signature: refuses, installs nothing → R4.

---

## Wave A (parallel)

### P1: Hardware XML and loader
Files: `server/filament_kit/bridge/hardware.py` (new), `bridge/bambu_hardware.xml` (package data), `bridge/models.py`
(thin readers), `pyproject.toml` (`defusedxml` pinned, package data), tests.
- Schema per spec P §3 (models, ams-types, numbering-schemes, presence-layouts, speech). Fill models from today's
  `models.py` table (all codes, names, camera kinds, chamber max) plus nozzles, externals, numbering guesses,
  `gcode-only-failed-is-finish` for O1D; ams-types ams, ams_2pro (N3F05), ams_ht (N3S05), ams_lite (A1/A1 mini).
- `hardware.load() -> Hardware` (cached by mtime of bundled + `/etc/filament-kit/bambu_hardware.xml` override;
  override wins per element by `code`/`key`); `Hardware.model(code_or_name) -> ModelInfo` (generic record for
  unknown); `ams_type(ams_id, module_code, model, tray_count) -> AmsType` (generic for unknown);
  `scheme(key) -> Scheme` with `encode(ams_id, tray_id) -> int` / `decode(n) -> (ams_id, tray_id)` for kinds
  `linear` (per-unit, ht-from) and `shift` (bits); `presence(key) -> Presence` with `bit(ams_id, tray_id) -> int|None`
  from the safe expression grammar (`id`, `tray`, ints, `+ - * <<`, parentheses); `say(label) -> list[str]`;
  `Hardware.errors` (last load problems); bad override → keep last good.
- `models.py`: `camera_kind`, `printer_preset_name`, `chamber_max` unchanged signatures, now backed by `hardware`.
  Existing test_models must still pass.

### R1: AI optional
Files: `api.py`, `inventory.py` (only if needed), `web/intake_app.py` + `web/static/*`, `modules.py` (ai_intake not in
the default server mode set when no key is configured — keep the module, change the default for new installs only),
tests. Ungate `/api/intake/add` (keep read/retry behind ai_intake); web app: "Add by hand" form (vendor, product name,
material, colour, net, tare, count, sealed, location; existing-filament picker from `/api/spools`/Spoolman), shown
always; photo read shown only with ai_intake. `/api/info` modules list already tells the Android app. Also write
`docs/android-manual-add.md`: the API contract the Android session needs for a manual Add screen.

### R2: Module checklist menu
Files: `modules.py` (`Module.needs_text`, `optional_ai` flags; `menu_lines(cfg) -> list[str]`), `cli.py` (config →
Modules uses the checklist), `install/install.sh` (custom mode uses the same checklist via
`filament-kit modules menu --raw` or an inline python call; `--modules a,b` flag), tests. Turning a module on turns
on what it needs (and says so); turning one off lists dependents.

### R3: Library on request
Files: `library.py`, `pyproject.toml` (no `library_data/library/**` in the wheel; keep schema + an empty index),
`tools/make_release.sh` (drop the bundled-index check; add `library-<date>.tar.gz` asset build from
`C:\CODING\filament-library` when present), `modules.py` (library default off for new installs), cli, tests.
Profiles must build without any library (test). `library update` downloads from `library.url` (release asset URL;
token header from `/etc/filament-kit/github_token` if present, for private testing).

### R4: get.sh, signed releases, updater module
Files: `get.sh` (repo root), `tools/sign_release.py`, `.github/workflows/release.yml` (sign SHA256SUMS with
secret `FK_RELEASE_KEY`; never print it), `server/filament_kit/updates.py` + module `updates` (timer unit
`filament-kit-update.timer`, default off), cli `update [--check|--rollback]`, tests (WSL: get.sh against a local
fake release server: good, bad signature, bad hash, no TTY). Signature: ed25519 via Python `cryptography` (already a
dependency) — get.sh ships a minimal verifier script it runs with the system python3. Token support for private
repos: `--token-file` / `FK_GITHUB_TOKEN` (never echoed).

## Wave B (after P1)

### P2: Units, labels, externals, presence, layout fingerprint, slot command
Files: `bridge/status.py`, `bridge/ams.py`, `bridge/slottest.py`, `bridge/snapshot.py`, `bridge/loading.py`,
`bridge/connection.py` (externals: `tray_id = ams_id`, `slot_id = 0`), `bridge/mapping.py` (stale on fingerprint
change + idle auto-remap, config `auto_remap` default true), `api.py` (additive fields), tests with synthetic
16-unit + HT + 2-external reports and the existing H2D fixtures. One shared unit builder used by status and ams.
Labels: spreadsheet style without limit; externals from the model (`Ext` single, `Ext-L`/`Ext-R` dual), `vir_slot[]`
and `vt_tray`. Additive slot fields `present`, `reading`, `say`; unit `kind`, `type_name`.

### P3: Numbering schemes in calibration and usage; FAILED-as-finish
Files: `bridge/calib3mf.py`, `bridge/mapping.py` (scheme pick), `bridge/usage.py`, tests. Calibration tries the
model's candidate schemes (and `ams_mapping2` if listed), keeps the one the reports confirm, saves scheme+decoding;
usage decodes via saved decoding then scheme; learn-unseen rule (exactly one matching loaded slot); two mismatches →
suspect → re-map when idle; gcode-only calibration FAILED with no print_error = finished when the model says so.
P2 and P3 both touch mapping.py: P3 starts after P2 is merged (sequential), or coordinate: P2 owns the fingerprint
part, P3 the scheme part.

## Wave C (after P2)

### P4: Reader API, reader token, queue, MCP generalization
Files: `web/reader.py` (routes under the web process: `GET reader/printers`, `GET reader/printers/{id}/slots`,
`POST reader/scan`), `web/slots.py` + `web/mcp_tools.py` (any printer, kit labels, H2D compat parser), cli
`reader token`, tests. Contract in spec P §4.7. Queue-on-empty port (900 s TTL, settle 3 s, verify 4 s, 3 tries).

### P5: Printers tab in the web app
Files: `web/printers_app.py`, `web/static/*`, tests. Status SSE, camera via kit hub, controls (stop needs confirm,
lights from `light_nodes`), filament per unit, usage + re-map, multi-printer picker. Web Push: config `web.push`
off; implement only the subscription storage + sender behind the flag (owner decides egress).

### P6: Reader firmware
Files: `reader/` (new: copy of `C:\CODING\h2d-filament-scanner\firmware` WITHOUT `src/secrets.h` and `.pio`; then
rewrite main.cpp per spec P §5), `reader/test/` (PlatformIO native tests for label/say parsing and menu state),
CI job builds it (`pio run`), `reader/README.md`. Never flash a device; never read secrets.h.

## Wave D

### P7: H2D migration, capture script, runbook
Files: `server/filament_kit/migrate_scanner.py` + cli `migrate-scanner <calibration.json> [--apply]`, `tools/capture_bambu.py`
(the owner runs it on the VM as root: read-only pushall + get_version from a printer using the env file it is given,
replaces serial/IP, writes a fixture; never prints the code), runbook additions (private: goes to
`docs/migrate-from-filament-ops.md` for now; moves to the owner repo before publishing), tests.

### Final: integration on WSL (fake MQTT printer with 16 units through the reader API; get.sh + updater against a
local fake release server; manual add without AI), README, final whole-branch review.
